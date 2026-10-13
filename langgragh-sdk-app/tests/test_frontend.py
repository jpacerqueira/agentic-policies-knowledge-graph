import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from policy_kg.frontend import FrontendApp, make_server, parse_form, render_page
from policy_kg.neo4j_store import NullStore
from policy_kg.sample_pdfs import write_plain_pdf

ROOT = Path(__file__).resolve().parents[1]
OSCAL = ROOT / "data" / "oscal"
ORG = ROOT / "data" / "organization.json"


class _BytesResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self._data)
        chunk, self._data = self._data[:amount], self._data[amount:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False


class _Opener:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def open(self, request, timeout=None):
        return _BytesResponse(self.data)


def _multipart(fields: list[tuple[str, str]], file_bytes: bytes | None = None) -> tuple[str, bytes]:
    boundary = "----policykgboundary"
    chunks: list[bytes] = []
    for name, value in fields:
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )
    if file_bytes is not None:
        chunks.append(
            (
                f"--{boundary}\r\n"
                "Content-Disposition: form-data; name=\"pdf\"; filename=\"policy.pdf\"\r\n"
                "Content-Type: application/pdf\r\n\r\n"
            ).encode()
            + file_bytes
            + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


def test_parse_form_reads_link_and_upload():
    content_type, body = _multipart([("source_url", "https://example.com/a.pdf"), ("persist", "1")])
    form = parse_form(content_type, body)
    assert form["source_url"] == "https://example.com/a.pdf"
    assert form["persist"] is True
    assert form["file_bytes"] == b""
    assert form["files"] == []
    assert form["s3_uri"] == ""


def test_page_explains_link_or_pdf():
    page = render_page()
    assert "Policy intake" in page
    assert "policy link" in page.lower() or "Policy link" in page
    assert 'type="file"' in page
    assert "webkitdirectory" in page
    assert "Drop PDF files or a folder here" in page
    assert "s3://bucket/policies/" in page
    assert "submissions" in page
    assert "not legal advice" in page


def test_upload_is_analyzed_and_empty_submission_is_rejected(tmp_path):
    pdf_path = tmp_path / "sourced.pdf"
    write_plain_pdf(
        pdf_path,
        "Credit decisioning staff shall report every serious incident that affects the model.",
    )
    app = FrontendApp(
        oscal_dir=OSCAL,
        organization_path=ORG,
        intake_dir=tmp_path / "intake",
        store=NullStore(),
    )
    server = make_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        content_type, body = _multipart([("persist", "1")], pdf_path.read_bytes())
        request = Request(
            f"http://127.0.0.1:{port}/analyze",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        with urlopen(request, timeout=30) as response:
            page = response.read().decode("utf-8")
        assert response.status == 200
        assert "aia-73" in page
        assert "merged into the knowledge graph" in page
        saved = list((tmp_path / "intake").rglob("*.pdf"))
        assert len(saved) == 1
        assert saved[0].parent.name[:11].count("-") == 2

        missing = Request(
            f"http://127.0.0.1:{port}/analyze",
            data=b"source_url=",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with pytest_http_error(missing) as error_page:
            assert "Provide a policy link, PDFs or a local folder, or an S3 folder" in error_page
    finally:
        server.shutdown()
        server.server_close()


def test_link_uses_the_injected_downloader(tmp_path):
    pdf_path = tmp_path / "remote.pdf"
    write_plain_pdf(
        pdf_path,
        "The bank shall report every serious incident that affects payment customers.",
    )
    app = FrontendApp(
        oscal_dir=OSCAL,
        organization_path=ORG,
        intake_dir=tmp_path / "intake",
        store=NullStore(),
        opener=_Opener(pdf_path.read_bytes()),
    )
    report = app.accept(
        {
            "source_url": "https://policies.example/incident.pdf",
            "persist": False,
            "file_bytes": b"",
            "files": [],
            "s3_uri": "",
        }
    )
    assert report["origin"] == "link"
    assert "submissions" not in report["submission_dir"]
    assert (tmp_path / "intake").joinpath(Path(report["submission_dir"]).name).is_dir()
    assert report["persisted"] is False
    assert report["policies"][0]["alignments"][0]["control_id"] == "aia-73"
    page = render_page(report=report)
    assert "not written" in page
    assert "validated" in page
    assert "record-action" in page


class _ErrorBody:
    def __init__(self, exc: HTTPError) -> None:
        self.page = exc.read().decode("utf-8")

    def __enter__(self) -> str:
        return self.page

    def __exit__(self, *_args) -> bool:
        return False


def pytest_http_error(request: Request):
    try:
        urlopen(request, timeout=10)
    except HTTPError as exc:
        assert exc.code == 400
        return _ErrorBody(exc)
    raise AssertionError("expected the intake form to reject an empty submission")
