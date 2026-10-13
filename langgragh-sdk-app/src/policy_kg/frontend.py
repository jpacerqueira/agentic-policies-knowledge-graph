"""Python page for adding a policy PDF from a link or a file."""

from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from policy_kg.analyze import analyze_pdf, persist_analysis
from policy_kg.batch import stage_s3_pdfs
from policy_kg.intake import IntakeError, create_submission_dir, fetch_pdf, save_named_pdf
from policy_kg.stored import read_stored_graph

PAGE_TITLE = "Policy intake"
GRAPH_TITLE = "Stored graph"
REQUEST_LIMIT = 200 * 1024 * 1024


def parse_form(content_type: str, body: bytes) -> dict[str, object]:
    """Read a URL-encoded or multipart intake form."""
    header = content_type or ""
    if "application/x-www-form-urlencoded" in header:
        parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
        return {
            "source_url": (parsed.get("source_url") or [""])[0].strip(),
            "s3_uri": (parsed.get("s3_uri") or [""])[0].strip(),
            "persist": "persist" in parsed,
            "file_bytes": b"",
            "files": [],
        }
    if "multipart/form-data" not in header:
        raise IntakeError("Submit the form as multipart data or URL-encoded fields")
    marker = ""
    for piece in header.split(";"):
        piece = piece.strip()
        if piece.startswith("boundary="):
            marker = piece.split("=", 1)[1].strip().strip('"')
    if not marker:
        raise IntakeError("The upload is missing a multipart boundary")
    result: dict[str, object] = {
        "source_url": "",
        "s3_uri": "",
        "persist": False,
        "file_bytes": b"",
        "files": [],
    }
    delimiter = b"--" + marker.encode("utf-8", errors="replace")
    for chunk in body.split(delimiter):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        if chunk.endswith(b"--"):
            chunk = chunk[:-2].strip(b"\r\n")
        header_blob, separator, payload = chunk.partition(b"\r\n\r\n")
        if not separator:
            continue
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        disposition = header_blob.decode("utf-8", errors="replace")
        name = _disposition_param(disposition, "name")
        if name == "source_url":
            result["source_url"] = payload.decode("utf-8", errors="replace").strip()
        elif name == "s3_uri":
            result["s3_uri"] = payload.decode("utf-8", errors="replace").strip()
        elif name == "persist":
            result["persist"] = True
        elif name == "pdf" and payload:
            filename = _disposition_param(disposition, "filename") or "document.pdf"
            files = result["files"]
            assert isinstance(files, list)
            files.append({"filename": filename, "file_bytes": payload})
            if not result["file_bytes"]:
                result["file_bytes"] = payload
    return result


def _disposition_param(disposition: str, key: str) -> str:
    needle = f'{key}="'
    start = disposition.find(needle)
    if start < 0:
        return ""
    start += len(needle)
    end = disposition.find('"', start)
    if end < 0:
        return ""
    return disposition[start:end]


class FrontendApp:
    def __init__(
        self,
        *,
        oscal_dir: Path,
        organization_path: Path,
        intake_dir: Path,
        store,
        opener=None,
        s3_source=None,
    ) -> None:
        self.oscal_dir = Path(oscal_dir)
        self.organization_path = Path(organization_path)
        self.intake_dir = Path(intake_dir)
        self.store = store
        self.opener = opener
        self.s3_source = s3_source

    def accept(self, form: dict[str, object]) -> dict:
        files = list(form.get("files") or [])
        if not files and form.get("file_bytes"):
            files = [{"filename": "upload.pdf", "file_bytes": form.get("file_bytes")}]
        source_url = str(form.get("source_url") or "").strip()
        s3_uri = str(form.get("s3_uri") or "").strip()
        if not files and not source_url and not s3_uri:
            raise IntakeError("Provide a policy link, PDFs or a local folder, or an S3 folder")
        run_dir = create_submission_dir(self.intake_dir)
        saved: list[Path] = []
        skipped: list[str] = []
        for item in files:
            data = item.get("file_bytes") or b""
            filename = str(item.get("filename") or "document.pdf")
            if not isinstance(data, bytes) or not data:
                continue
            if not data.startswith(b"%PDF"):
                skipped.append(filename)
                continue
            saved.append(save_named_pdf(data, run_dir, filename))
        if source_url:
            saved.append(fetch_pdf(source_url, run_dir, opener=self.opener))
        if s3_uri:
            source = self.s3_source
            if source is None:
                from policy_kg.batch import BotoS3PdfSource

                source = BotoS3PdfSource()
            try:
                saved.extend(stage_s3_pdfs(s3_uri, run_dir, source))
            except IntakeError:
                raise
            except Exception as exc:
                raise IntakeError(f"Could not read the S3 folder: {exc}") from exc
        if not saved:
            detail = f" Skipped: {', '.join(skipped)}." if skipped else ""
            raise IntakeError(f"No PDF documents were found.{detail}")
        reports = [analyze_pdf(path, self.oscal_dir) for path in saved]
        report = _combine_reports(reports, run_dir)
        if skipped:
            report["findings"] = [
                {
                    "code": "skipped-file",
                    "severity": "info",
                    "subject": name,
                    "message": f"Skipped {name} because it is not a PDF",
                }
                for name in skipped
            ] + list(report.get("findings") or [])
        origins = []
        if files:
            origins.append("upload")
        if source_url:
            origins.append("link")
        if s3_uri:
            origins.append("s3")
        report["origin"] = origins[0] if len(origins) == 1 else "mixed"
        report["source_url"] = source_url
        report["s3_uri"] = s3_uri
        report["submission_dir"] = str(run_dir)
        if form.get("persist"):
            saved_graph = persist_analysis(report, self.organization_path, self.oscal_dir, self.store)
            report["persisted"] = saved_graph["persisted"]
            report["graph_summary"] = saved_graph.get("summary") or {}
        else:
            report["persisted"] = False
            report["graph_summary"] = {}
        return report

    def stored(self) -> dict:
        return read_stored_graph(self.store)


def _combine_reports(reports: list[dict], run_dir: Path) -> dict:
    policies: list[dict] = []
    alignments: list[dict] = []
    findings: list[dict] = []
    for report in reports:
        policies.extend(report.get("policies") or [])
        alignments.extend(report.get("alignments") or [])
        findings.extend(report.get("findings") or [])
    kinds = {report.get("source_kind") for report in reports}
    source_kind = next(iter(kinds)) if len(kinds) == 1 else "mixed"
    sha = reports[0].get("sha256", "") if len(reports) == 1 else "multiple"
    return {
        "source_kind": source_kind,
        "path": str(run_dir),
        "sha256": sha,
        "policies": policies,
        "alignments": alignments,
        "findings": findings,
        "submission_dir": str(run_dir),
    }


SITE_CSS = """
body{margin:0;background:#000;color:#1c1e21;font-family:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",Roboto,Ubuntu,Cantarell,"Helvetica Neue",sans-serif;line-height:1.5}
.topbar{display:flex;align-items:center;justify-content:space-between;background:#fff;color:#1c1e21;padding:8px 16px;box-shadow:rgba(0,0,0,.1) 0 1px 2px 0;position:sticky;top:0;z-index:2}
.brand{font-family:"Space Grotesk","IBM Plex Sans",system-ui,sans-serif;font-weight:700;color:#000063;text-decoration:none;letter-spacing:-.03em;font-size:1.15rem}
.topbar nav a{color:#1c1e21;text-decoration:none;font-weight:500;padding:4px 12px}
.topbar nav a:hover{color:#007dff}
.hero{background:#000;padding:3.25rem 1.5rem 4.5rem}
.kicker{margin:0 0 .8rem;color:#007dff;font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;font-weight:600;letter-spacing:1.44px;text-transform:uppercase}
.hero h1{margin:0;max-width:18ch;color:#9eb6ff;font-family:"Space Grotesk","IBM Plex Sans",system-ui,sans-serif;font-size:36px;font-weight:700;letter-spacing:-.72px;line-height:1.05}
.sheet{max-width:64rem;margin:-2rem auto 3rem;padding:0 1.25rem}
.panel{background:#fff;color:#1c1e21;border-radius:16px;padding:1.5rem 1.5rem 1.75rem;box-shadow:0 16px 40px rgba(0,0,0,.28)}
.panel h2,.sheet>h2{font-family:"Space Grotesk","IBM Plex Sans",system-ui,sans-serif;font-weight:700;letter-spacing:-.02em}
.panel h2{color:#000063;font-size:32px;margin:1.5rem 0 .5rem}
.sheet>h2{color:#dbe7ff;font-size:32px;margin:1.75rem 0 .25rem}
.note{color:#414b60;font-size:18px}
label{display:block;margin-top:1rem;font-weight:600}
input[type=url],input[type=text],input[type=file]{width:100%;box-sizing:border-box;margin-top:.35rem;border:1.5px solid #cdd7e6;border-radius:9px;padding:.65rem .75rem;font:inherit;background:#fff;color:#1c1e21}
button{margin-top:1rem;background:#007dff;color:#fff;border:1.5px solid transparent;border-radius:9px;padding:11px 20px;font-family:inherit;font-size:15px;font-weight:600;box-shadow:0 10px 22px -8px rgba(0,125,255,.55);cursor:pointer}
.drop{border:1.5px dashed #9bbcf5;border-radius:14px;padding:1.5rem;margin-top:1rem;text-align:center;background:#f5f8fd;color:#1c1e21}
.drop.ready{border-color:#007dff;box-shadow:0 0 0 4px rgba(0,125,255,.25)}
.record{background:#0b1030;color:#c7d0f0;border-radius:14px;padding:18px 20px;margin:1rem 0;box-shadow:0 12px 28px -16px rgba(11,16,32,.24),0 0 0 1px rgba(110,168,255,.28)}
.record-bar{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:12px}
.record-name{color:#7f8bb5;font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}
.record-action{margin-left:auto;font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11px;border-radius:6px;padding:3px 9px;white-space:nowrap}
.record-action.ok{color:#22d3a7;background:rgba(34,211,167,.14)}
.record-action.warn{color:#ffb020;background:rgba(255,176,32,.14)}
.record-body{margin:0;font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;line-height:1.6;color:#c7d0f0;white-space:pre-wrap;word-break:break-word}
.key{color:#6ea8ff}
.value{color:#8ee6c8}
.sheet>p{color:#c5cad3}
.sheet a{color:#8eb6ff}
.panel a{color:#007dff}
code{font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.92em}
"""


def _page(title: str, body: str, *, kicker: str) -> str:
    return "\n".join(
        [
            "<!DOCTYPE html>",
            "<html lang=\"en\">",
            "<head>",
            "<meta charset=\"utf-8\">",
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
            f"<title>{html.escape(title)}</title>",
            "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">",
            "<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>",
            "<link href=\"https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@600;700&display=swap\" rel=\"stylesheet\">",
            "<style>",
            SITE_CSS,
            "</style>",
            "</head>",
            "<body>",
            "<header class=\"topbar\">",
            "<a class=\"brand\" href=\"/\">Northline</a>",
            "<nav><a href=\"/\">Add a policy</a><a href=\"/graph\">Stored graph</a></nav>",
            "</header>",
            "<main>",
            "<section class=\"hero\">",
            f"<p class=\"kicker\">{html.escape(kicker)}</p>",
            f"<h1>{html.escape(title)}</h1>",
            "</section>",
            f"<div class=\"sheet\">{body}</div>",
            "</main>",
            "</body></html>",
        ]
    )


def _record(name: str, action: str, rows: list[tuple[str, str]], *, tone: str = "ok") -> str:
    body = "\n".join(
        f'<span class="key">{html.escape(key)}</span>  <span class="value">{html.escape(value)}</span>'
        for key, value in rows
    )
    return (
        '<article class="record">'
        '<header class="record-bar">'
        f'<span class="record-name">{html.escape(name)}</span>'
        f'<span class="record-action {html.escape(tone)}">{html.escape(action)}</span>'
        "</header>"
        f'<pre class="record-body">{body}</pre>'
        "</article>"
    )


def _policy_mark(alignments: list[dict] | None, controls: list | None = None) -> tuple[str, str]:
    if alignments:
        if any(item.get("status") == "matched" for item in alignments):
            return "validated", "ok"
        if any(item.get("status") == "ambiguous" for item in alignments):
            return "review", "warn"
        return "unmapped", "warn"
    if controls:
        return "validated", "ok"
    return "unmapped", "warn"


def render_page(report: dict | None = None, error: str | None = None) -> str:
    parts = [
        "<div class=\"panel\">",
        "<p class=\"note\">Add DevSecOps policies for Northline Bank plc, a fictional tier-1 bank. "
        "Drop PDFs or a folder here, choose files, choose a local folder, paste a policy link, "
        "or point at an S3 folder such as <code>s3://bucket/policies/</code>. "
        "Each submission run is stored in its own date-time folder under <code>submissions</code>, "
        "which is shared with the app container and is not part of the sample policy scan. "
        "This page is not legal advice and not a conformity assessment.</p>",
        "<form id=\"intake\" action=\"/analyze\" method=\"post\" enctype=\"multipart/form-data\">",
        "<div id=\"drop\" class=\"drop\">Drop PDF files or a folder here</div>",
        "<label for=\"pdf\">PDF files</label>",
        "<input id=\"pdf\" name=\"pdf\" type=\"file\" accept=\"application/pdf,.pdf\" multiple>",
        "<label for=\"folder\">Local folder</label>",
        "<input id=\"folder\" name=\"pdf\" type=\"file\" accept=\"application/pdf,.pdf\" webkitdirectory multiple>",
        "<label for=\"source_url\">Policy link</label>",
        "<input id=\"source_url\" name=\"source_url\" type=\"url\" placeholder=\"https://example.com/policy.pdf\">",
        "<label for=\"s3_uri\">S3 folder</label>",
        "<input id=\"s3_uri\" name=\"s3_uri\" type=\"text\" placeholder=\"s3://bucket/policies/\">",
        "<label><input name=\"persist\" type=\"checkbox\" value=\"1\" checked> "
        "Add the analyzed policies to the knowledge graph</label>",
        "<button type=\"submit\">Analyze policy</button>",
        "</form>",
        "<script>",
        "const drop = document.getElementById('drop');",
        "const pdf = document.getElementById('pdf');",
        "drop.addEventListener('dragover', (event) => { event.preventDefault(); drop.classList.add('ready'); });",
        "drop.addEventListener('dragleave', () => drop.classList.remove('ready'));",
        "drop.addEventListener('drop', async (event) => {",
        "  event.preventDefault();",
        "  drop.classList.remove('ready');",
        "  const found = [];",
        "  const items = event.dataTransfer.items;",
        "  if (items && items.length && items[0].webkitGetAsEntry) {",
        "    const walks = [];",
        "    for (const item of items) {",
        "      const entry = item.webkitGetAsEntry();",
        "      if (entry) walks.push(walkEntry(entry, found));",
        "    }",
        "    await Promise.all(walks);",
        "  } else {",
        "    for (const file of event.dataTransfer.files) found.push(file);",
        "  }",
        "  const transfer = new DataTransfer();",
        "  for (const file of found) {",
        "    if (file.name.toLowerCase().endsWith('.pdf')) transfer.items.add(file);",
        "  }",
        "  pdf.files = transfer.files;",
        "  drop.textContent = transfer.files.length ? transfer.files.length + ' PDF(s) ready to analyze' : 'No PDF files in that drop';",
        "});",
        "function walkEntry(entry, found) {",
        "  return new Promise((resolve) => {",
        "    if (entry.isFile) { entry.file((file) => { found.push(file); resolve(); }); return; }",
        "    if (!entry.isDirectory) { resolve(); return; }",
        "    const reader = entry.createReader();",
        "    const children = [];",
        "    const read = () => reader.readEntries(async (batch) => {",
        "      if (!batch.length) { await Promise.all(children.map((child) => walkEntry(child, found))); resolve(); return; }",
        "      children.push(...batch);",
        "      read();",
        "    });",
        "    read();",
        "  });",
        "}",
        "</script>",
        "</div>",
    ]
    if error:
        parts.append(_record("Analysis", "review", [("message", error)], tone="warn"))
    if report:
        parts.extend(_render_report(report))
    return _page(PAGE_TITLE, "\n".join(parts), kicker="Northline Bank")


def render_graph(view: dict) -> str:
    if not view.get("connected"):
        reason = str(view.get("reason") or "Neo4j is not connected")
        body = _record(
            "Stored graph",
            "unavailable",
            [("status", f"The stored graph is unavailable. {reason}")],
            tone="warn",
        )
        return _page(GRAPH_TITLE, body, kicker="Knowledge graph")
    parts = [
        "<div class=\"panel\"><p class=\"note\">Policies and the OSCAL ontology currently stored in Neo4j "
        "for Northline Bank plc. This view is not legal advice and not a conformity assessment.</p></div>",
    ]
    parts.append("<h2>Organization</h2>")
    organizations = view.get("organization") or []
    if not organizations:
        parts.append("<p>No organization is stored.</p>")
    for org in organizations:
        parts.append(
            _record(
                str(org.get("name") or "Organization"),
                "stored",
                [
                    ("tier", str(org.get("tier") or "")),
                    ("employees", str(org.get("employee_count") or "")),
                    ("systems", _plain(org.get("systems"))),
                ],
            )
        )
    parts.append("<h2>Ontology</h2>")
    parts.append("<h2>Catalogs and frameworks</h2>")
    catalogs = view.get("catalogs") or []
    if not catalogs:
        parts.append("<p>No catalogs are stored.</p>")
    for catalog in catalogs:
        parts.append(
            _record(
                str(catalog.get("title") or "Catalog"),
                "stored",
                [
                    ("framework", str(catalog.get("framework_id") or catalog.get("framework_title") or "")),
                    ("version", str(catalog.get("version") or "")),
                    ("specification", str(catalog.get("specification") or "")),
                ],
            )
        )
    parts.append("<h2>Profiles</h2>")
    profiles = view.get("profiles") or []
    if not profiles:
        parts.append("<p>No profiles are stored.</p>")
    for profile in profiles:
        selected = profile.get("controls") or []
        action, tone = ("validated", "ok") if selected else ("stored", "ok")
        parts.append(
            _record(
                str(profile.get("title") or "Profile"),
                action,
                [
                    ("catalogs", _plain(profile.get("catalogs"))),
                    ("controls", _plain(selected)),
                ],
                tone=tone,
            )
        )
    parts.append("<h2>Control groups</h2>")
    groups = view.get("groups") or []
    if not groups:
        parts.append("<p>No control groups are stored.</p>")
    for group in groups:
        parts.append(
            _record(
                str(group.get("group_id") or "Group"),
                "stored",
                [("title", str(group.get("title") or ""))],
            )
        )
    parts.append("<h2>Controls</h2>")
    controls = view.get("controls") or []
    if not controls:
        parts.append("<p>No controls are stored.</p>")
    for control in controls:
        linked = control.get("policies") or []
        action, tone = ("validated", "ok") if linked else ("stored", "ok")
        parts.append(
            _record(
                str(control.get("control_id") or "Control"),
                action,
                [
                    ("catalog", str(control.get("catalog") or "")),
                    ("title", str(control.get("title") or "")),
                    ("policies", _plain(linked)),
                ],
                tone=tone,
            )
        )
    parts.append("<h2>Policies</h2>")
    policies = view.get("policies") or []
    if not policies:
        parts.append("<p>No policies are stored.</p>")
    for policy in policies:
        action, tone = _policy_mark(None, policy.get("controls") or [])
        parts.append(
            _record(
                str(policy.get("policy_id") or "Policy"),
                action,
                [
                    ("title", str(policy.get("title") or "")),
                    ("owner", str(policy.get("owner") or "")),
                    ("systems", _plain(policy.get("systems"))),
                    ("controls", _plain(policy.get("controls"))),
                    ("statement", str(policy.get("statement") or "")),
                ],
                tone=tone,
            )
        )
    summary = view.get("summary") or []
    if summary:
        parts.append("<h2>Stored nodes</h2>")
        parts.append(
            _record(
                "Stored nodes",
                "stored",
                [(str(row.get("label") or ""), str(row.get("count") or "")) for row in summary],
            )
        )
    return _page(GRAPH_TITLE, "\n".join(parts), kicker="Knowledge graph")


def _plain(values: object) -> str:
    if isinstance(values, (list, tuple)):
        text = ", ".join(str(item) for item in values if item not in (None, ""))
    else:
        text = "" if values is None else str(values)
    return text or "none"


def _render_report(report: dict) -> list[str]:
    labels = {"upload": "uploaded PDFs", "link": "policy link", "s3": "S3 folder", "mixed": "mixed sources"}
    origin = labels.get(str(report.get("origin") or ""), "submission")
    findings = list(report.get("findings") or [])
    has_error = any(item.get("severity") == "error" for item in findings)
    if has_error:
        summary_action, summary_tone = "review", "warn"
    elif report.get("persisted"):
        summary_action, summary_tone = "validated", "ok"
    else:
        summary_action, summary_tone = "not stored", "warn"
    written = (
        "The analyzed policy was merged into the knowledge graph."
        if report.get("persisted")
        else "The analyzed policy was not written to the knowledge graph."
    )
    rows = [
        ("source", origin),
        ("kind", str(report.get("source_kind", ""))),
        ("sha256", str(report.get("sha256", ""))),
        ("result", written),
    ]
    if report.get("submission_dir"):
        rows.insert(3, ("submission", str(report["submission_dir"])))
    lines = [
        "<h2>Analysis</h2>",
        _record("Analysis", summary_action, rows, tone=summary_tone),
    ]
    if findings:
        lines.append("<h2>Findings</h2>")
        for finding in findings:
            tone = "warn" if finding.get("severity") == "error" else "ok"
            action = "review" if finding.get("severity") == "error" else "noted"
            lines.append(
                _record(
                    str(finding.get("code") or "finding"),
                    action,
                    [("message", str(finding.get("message") or ""))],
                    tone=tone,
                )
            )
    lines.append("<h2>Policies</h2>")
    policies = report.get("policies") or []
    if not policies:
        lines.append("<p>No policy statement was extracted.</p>")
    for policy in policies:
        alignments = list(policy.get("alignments") or [])
        controls = ", ".join(
            f"{item.get('control_id')} ({item.get('method')}, {item.get('status')})"
            for item in alignments
        ) or "none"
        applies = ", ".join(policy.get("applies_to") or []) or "not stated"
        action, tone = _policy_mark(alignments)
        lines.append(
            _record(
                str(policy.get("policy_id") or "Policy"),
                action,
                [
                    ("title", str(policy.get("title") or "")),
                    ("owner", str(policy.get("owner") or "")),
                    ("applies_to", applies),
                    ("statement", str(policy.get("statement") or "")),
                    ("controls", controls),
                ],
                tone=tone,
            )
        )
    lines.append('<p><a href="/graph">Open the stored graph</a></p>')
    return lines


def handler_for(app: FrontendApp):
    class IntakeHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._send(200, b"ok", "text/plain; charset=utf-8")
                return
            if path == "/graph":
                self._send(200, render_graph(app.stored()).encode("utf-8"), "text/html; charset=utf-8")
                return
            if path in {"/", "/index.html"}:
                self._send(200, render_page().encode("utf-8"), "text/html; charset=utf-8")
                return
            self._send(404, b"not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if path != "/analyze":
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > REQUEST_LIMIT:
                page = render_page(error="The upload is empty or larger than 200 MB")
                self._send(400, page.encode("utf-8"), "text/html; charset=utf-8")
                return
            body = self.rfile.read(length)
            try:
                form = parse_form(self.headers.get("Content-Type", ""), body)
                report = app.accept(form)
            except IntakeError as exc:
                page = render_page(error=str(exc))
                self._send(400, page.encode("utf-8"), "text/html; charset=utf-8")
                return
            except Exception as exc:
                page = render_page(error=f"Analysis failed: {exc}")
                self._send(500, page.encode("utf-8"), "text/html; charset=utf-8")
                return
            self._send(200, render_page(report=report).encode("utf-8"), "text/html; charset=utf-8")

        def _send(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return IntakeHandler


class IntakeServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def make_server(app: FrontendApp, host: str, port: int) -> IntakeServer:
    return IntakeServer((host, port), handler_for(app))


def serve(app: FrontendApp, host: str, port: int) -> None:
    server = make_server(app, host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
