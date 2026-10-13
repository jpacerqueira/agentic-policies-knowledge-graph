"""Save a policy PDF from an http(s) link, an upload, or a submission run."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from urllib import request as urllib_request
from urllib.parse import urlparse

MAX_BYTES = 15 * 1024 * 1024


class IntakeError(Exception):
    """The link or file cannot be accepted as a policy PDF."""


def require_http_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise IntakeError("Policy link must be an http or https URL")
    return url.strip()


class _HttpOnlyRedirect(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def create_submission_dir(root: Path, now: datetime | None = None) -> Path:
    """One private folder per submission run, named with the local date and time."""
    root.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y-%m-%dT%H%M%S")
    dest = root / stamp
    suffix = 1
    while dest.exists():
        suffix += 1
        dest = root / f"{stamp}-{suffix}"
    dest.mkdir()
    return dest


def safe_pdf_name(filename: str) -> str:
    name = Path(filename or "document.pdf").name
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .") or "document.pdf"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return name


def save_named_pdf(data: bytes, dest_dir: Path, filename: str) -> Path:
    if len(data) > MAX_BYTES:
        raise IntakeError("PDF is larger than 15 MB")
    if not data.startswith(b"%PDF"):
        raise IntakeError("File is not a PDF")
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / safe_pdf_name(filename)
    if path.exists():
        path = path.with_name(f"{path.stem}-{hashlib.sha256(data).hexdigest()[:8]}{path.suffix}")
    path.write_bytes(data)
    return path


def save_pdf_bytes(data: bytes, dest_dir: Path) -> Path:
    if len(data) > MAX_BYTES:
        raise IntakeError("PDF is larger than 15 MB")
    if not data.startswith(b"%PDF"):
        raise IntakeError("File is not a PDF")
    dest_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    path = dest_dir / f"{digest}.pdf"
    path.write_bytes(data)
    return path


def fetch_pdf(url: str, dest_dir: Path, opener=None, timeout: float = 20) -> Path:
    """Download a PDF. ``opener`` is injectable so tests do not use the network."""
    clean = require_http_url(url)
    open_url = opener or urllib_request.build_opener(_HttpOnlyRedirect)
    req = urllib_request.Request(clean, headers={"User-Agent": "policy-kg-intake"})
    try:
        with open_url.open(req, timeout=timeout) as response:
            data = response.read(MAX_BYTES + 1)
    except IntakeError:
        raise
    except Exception as exc:
        raise IntakeError(f"Could not download the policy PDF: {exc}") from exc
    return save_pdf_bytes(data, dest_dir)
