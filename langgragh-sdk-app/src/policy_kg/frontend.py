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


def _page(title: str, body: str) -> str:
    return "\n".join(
        [
            "<!DOCTYPE html>",
            "<html lang=\"en\">",
            "<head>",
            "<meta charset=\"utf-8\">",
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
            f"<title>{html.escape(title)}</title>",
            "<style>",
            "body{font-family:Georgia,serif;margin:2rem auto;max-width:64rem;line-height:1.45;color:#1c1c1c}",
            "h1{font-size:1.6rem} label{display:block;margin-top:1rem;font-weight:600}",
            "nav a{margin-right:1rem} input[type=url],input[type=file]{width:100%;margin-top:.3rem}",
            "button{margin-top:1rem;padding:.5rem 1rem} .note{color:#444}",
            ".finding{margin:.3rem 0} .error{color:#8a1f1f} .policy{border-top:1px solid #ccc;padding-top:1rem}",
            ".drop{border:2px dashed #888;padding:1.4rem;margin-top:1rem;text-align:center}",
            ".drop.ready{border-color:#1c1c1c;background:#f4f4f4}",
            "table{border-collapse:collapse;width:100%;margin:1rem 0}",
            "td,th{border-bottom:1px solid #ccc;text-align:left;padding:.35rem .4rem;vertical-align:top}",
            "</style>",
            "</head>",
            "<body>",
            "<nav><a href=\"/\">Add a policy</a><a href=\"/graph\">Stored graph</a></nav>",
            f"<h1>{html.escape(title)}</h1>",
            body,
            "</body></html>",
        ]
    )


def render_page(report: dict | None = None, error: str | None = None) -> str:
    parts = [
        "<p class=\"note\">Add DevSecOps policies for Northline Bank plc, a fictional tier-1 bank. "
        "Drop PDFs or a folder here, choose files, choose a local folder, paste a policy link, "
        "or point at an S3 folder such as <code>s3://bucket/policies/</code>. "
        "Each submission run is stored in its own date-time folder under <code>submittions</code>, "
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
    ]
    if error:
        parts.append(f"<h2>Could not analyze</h2><p class=\"error\">{html.escape(error)}</p>")
    if report:
        parts.extend(_render_report(report))
    return _page(PAGE_TITLE, "\n".join(parts))


def _join(values: object) -> str:
    if isinstance(values, (list, tuple)):
        text = ", ".join(str(item) for item in values if item not in (None, ""))
    else:
        text = "" if values is None else str(values)
    return html.escape(text or "none")


def render_graph(view: dict) -> str:
    if not view.get("connected"):
        reason = html.escape(str(view.get("reason") or "Neo4j is not connected"))
        body = f"<p class=\"error\">The stored graph is unavailable. {reason}</p>"
        return _page(GRAPH_TITLE, body)
    parts = [
        "<p class=\"note\">Policies and the OSCAL ontology currently stored in Neo4j "
        "for Northline Bank plc. This view is not legal advice and not a conformity assessment.</p>",
    ]
    parts.append("<h2>Organization</h2>")
    organizations = view.get("organization") or []
    if not organizations:
        parts.append("<p>No organization is stored.</p>")
    for org in organizations:
        parts.append(
            f"<p>{html.escape(str(org.get('name') or ''))}. "
            f"Tier {html.escape(str(org.get('tier') or ''))}. "
            f"{html.escape(str(org.get('employee_count') or ''))} employees. "
            f"Systems: {_join(org.get('systems'))}.</p>"
        )
    parts.append("<h2>Ontology</h2>")
    parts.append("<h3>Catalogs and frameworks</h3>")
    catalogs = view.get("catalogs") or []
    if not catalogs:
        parts.append("<p>No catalogs are stored.</p>")
    else:
        parts.append("<table><thead><tr><th>Catalog</th><th>Framework</th><th>Version</th><th>Specification</th></tr></thead><tbody>")
        for catalog in catalogs:
            parts.append(
                "<tr>"
                f"<td>{html.escape(str(catalog.get('title') or ''))}</td>"
                f"<td>{html.escape(str(catalog.get('framework_id') or catalog.get('framework_title') or ''))}</td>"
                f"<td>{html.escape(str(catalog.get('version') or ''))}</td>"
                f"<td>{html.escape(str(catalog.get('specification') or ''))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
    parts.append("<h3>Profiles</h3>")
    profiles = view.get("profiles") or []
    if not profiles:
        parts.append("<p>No profiles are stored.</p>")
    for profile in profiles:
        parts.append(
            f"<p>{html.escape(str(profile.get('title') or ''))}. "
            f"Catalogs: {_join(profile.get('catalogs'))}. "
            f"Selected controls: {_join(profile.get('controls'))}.</p>"
        )
    parts.append("<h3>Control groups</h3>")
    groups = view.get("groups") or []
    if not groups:
        parts.append("<p>No control groups are stored.</p>")
    else:
        parts.append("<table><thead><tr><th>Group</th><th>Title</th></tr></thead><tbody>")
        for group in groups:
            parts.append(
                "<tr>"
                f"<td>{html.escape(str(group.get('group_id') or ''))}</td>"
                f"<td>{html.escape(str(group.get('title') or ''))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
    parts.append("<h3>Controls</h3>")
    controls = view.get("controls") or []
    if not controls:
        parts.append("<p>No controls are stored.</p>")
    else:
        parts.append(
            "<table><thead><tr><th>Catalog</th><th>Control</th><th>Title</th><th>Policies</th></tr></thead><tbody>"
        )
        for control in controls:
            parts.append(
                "<tr>"
                f"<td>{html.escape(str(control.get('catalog') or ''))}</td>"
                f"<td>{html.escape(str(control.get('control_id') or ''))}</td>"
                f"<td>{html.escape(str(control.get('title') or ''))}</td>"
                f"<td>{_join(control.get('policies'))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
    parts.append("<h2>Policies</h2>")
    policies = view.get("policies") or []
    if not policies:
        parts.append("<p>No policies are stored.</p>")
    for policy in policies:
        parts.append("<section class=\"policy\">")
        parts.append(f"<h3>{html.escape(str(policy.get('policy_id') or ''))}</h3>")
        parts.append(f"<p>{html.escape(str(policy.get('title') or ''))}</p>")
        parts.append(
            f"<p>Owner: {html.escape(str(policy.get('owner') or ''))}. "
            f"Applies to: {_join(policy.get('systems'))}. "
            f"Controls: {_join(policy.get('controls'))}.</p>"
        )
        parts.append(f"<p>{html.escape(str(policy.get('statement') or ''))}</p>")
        parts.append("</section>")
    summary = view.get("summary") or []
    if summary:
        parts.append("<h2>Stored nodes</h2><ul>")
        for row in summary:
            parts.append(
                f"<li>{html.escape(str(row.get('label') or ''))}: {html.escape(str(row.get('count') or ''))}</li>"
            )
        parts.append("</ul>")
    return _page(GRAPH_TITLE, "\n".join(parts))


def _render_report(report: dict) -> list[str]:
    labels = {"upload": "uploaded PDFs", "link": "policy link", "s3": "S3 folder", "mixed": "mixed sources"}
    origin = labels.get(str(report.get("origin") or ""), "submission")
    lines = [
        "<h2>Analysis</h2>",
        f"<p>Source: {html.escape(origin)}. Kind: {html.escape(str(report.get('source_kind', '')))}. "
        f"SHA-256: {html.escape(str(report.get('sha256', '')))}.</p>",
    ]
    if report.get("submission_dir"):
        lines.append(f"<p>Submission folder: {html.escape(str(report['submission_dir']))}.</p>")
    if report.get("persisted"):
        lines.append("<p>The analyzed policy was merged into the knowledge graph.</p>")
    else:
        lines.append("<p>The analyzed policy was not written to the knowledge graph.</p>")
    findings = report.get("findings") or []
    if findings:
        lines.append("<h2>Findings</h2>")
        for finding in findings:
            css = "finding error" if finding.get("severity") == "error" else "finding"
            lines.append(
                f"<p class=\"{css}\">{html.escape(str(finding.get('code', '')))}: "
                f"{html.escape(str(finding.get('message', '')))}</p>"
            )
    lines.append("<h2>Policies</h2>")
    policies = report.get("policies") or []
    if not policies:
        lines.append("<p>No policy statement was extracted.</p>")
    for policy in policies:
        controls = ", ".join(
            f"{item.get('control_id')} ({item.get('method')}, {item.get('status')})"
            for item in policy.get("alignments") or []
        ) or "none"
        applies = ", ".join(policy.get("applies_to") or []) or "not stated"
        lines.append("<section class=\"policy\">")
        lines.append(f"<h3>{html.escape(str(policy.get('policy_id', '')))}</h3>")
        lines.append(f"<p>{html.escape(str(policy.get('title', '')))}</p>")
        lines.append(
            f"<p>Owner: {html.escape(str(policy.get('owner', '')))}. "
            f"Applies to: {html.escape(applies)}.</p>"
        )
        lines.append(f"<p>{html.escape(str(policy.get('statement', '')))}</p>")
        lines.append(f"<p>Controls: {html.escape(controls)}</p>")
        lines.append("</section>")
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
