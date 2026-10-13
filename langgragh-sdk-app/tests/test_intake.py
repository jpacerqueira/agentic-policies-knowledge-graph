from pathlib import Path

import pytest

from policy_kg.discover_sources import list_pdfs
from datetime import datetime

from policy_kg.intake import (
    IntakeError,
    _HttpOnlyRedirect,
    create_submission_dir,
    fetch_pdf,
    require_http_url,
    save_named_pdf,
    save_pdf_bytes,
)
from policy_kg.sample_pdfs import write_plain_pdf


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
        self.urls: list[str] = []

    def open(self, request, timeout=None):
        self.urls.append(request.full_url)
        return _BytesResponse(self.data)


def _pdf_bytes(tmp_path: Path) -> bytes:
    path = tmp_path / "source.pdf"
    write_plain_pdf(path, "The bank shall report every serious incident to the oversight board.")
    return path.read_bytes()


def test_link_must_be_http(tmp_path):
    with pytest.raises(IntakeError, match="http"):
        require_http_url("file:///tmp/policy.pdf")
    with pytest.raises(IntakeError, match="http"):
        fetch_pdf("file:///tmp/policy.pdf", tmp_path)


def test_redirect_handler_rejects_non_http():
    with pytest.raises(IntakeError, match="http"):
        _HttpOnlyRedirect().redirect_request(None, None, 302, "Found", {}, "file:///etc/passwd")


def test_fetch_saves_pdf_from_injected_opener(tmp_path):
    data = _pdf_bytes(tmp_path)
    opener = _Opener(data)
    saved = fetch_pdf("https://policies.example/credit.pdf", tmp_path / "intake", opener=opener)
    assert saved.read_bytes() == data
    assert opener.urls == ["https://policies.example/credit.pdf"]
    assert saved.parent == tmp_path / "intake"


def test_non_pdf_and_oversized_files_are_rejected(tmp_path):
    with pytest.raises(IntakeError, match="not a PDF"):
        save_pdf_bytes(b"not a pdf", tmp_path)
    with pytest.raises(IntakeError, match="15 MB"):
        save_pdf_bytes(b"%PDF" + b"x" * (15 * 1024 * 1024), tmp_path)


def test_each_submission_run_gets_its_own_datetime_folder(tmp_path):
    moment = datetime(2026, 10, 13, 13, 31, 4)
    first = create_submission_dir(tmp_path, now=moment)
    second = create_submission_dir(tmp_path, now=moment)
    assert first.name == "2026-10-13T133104"
    assert second.name == "2026-10-13T133104-2"
    saved = save_named_pdf(b"%PDF-1.4\n", first, "../secrets/policy.pdf")
    assert saved.parent == first
    assert saved.name == "policy.pdf"
    assert ".." not in saved.parts


def test_nested_intake_pdfs_stay_out_of_the_baseline_scan(tmp_path):
    nested = tmp_path / "intake"
    nested.mkdir()
    (nested / "imported.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "pol-ssd-001.pdf").write_bytes(b"%PDF-1.4")
    found = list_pdfs(tmp_path)
    assert len(found) == 1
    assert found[0].endswith("pol-ssd-001.pdf")
