"""Ingest many policy PDFs from a folder or an S3 prefix."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from policy_kg.analyze import analyze_pdf, persist_analysis
from policy_kg.intake import MAX_BYTES, IntakeError, create_submission_dir, save_named_pdf


def parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse((uri or "").strip())
    if parsed.scheme != "s3" or not parsed.netloc or parsed.username or parsed.password:
        raise IntakeError("S3 location must look like s3://bucket/prefix")
    return parsed.netloc, parsed.path.lstrip("/")


def collect_folder_pdfs(folder: Path) -> list[Path]:
    path = Path(folder)
    if not path.is_dir():
        raise IntakeError(f"Folder not found: {path}")
    return sorted(
        item
        for item in path.rglob("*")
        if item.is_file() and item.suffix.lower() == ".pdf"
    )


class BotoS3PdfSource:
    """List and download PDFs with boto3. Credentials come from the AWS default chain."""

    def __init__(self, client=None) -> None:
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise IntakeError("Install boto3 to read policy PDFs from S3") from exc
            client = boto3.client("s3")
        self.client = client

    def list_keys(self, bucket: str, prefix: str) -> list[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        kwargs: dict[str, str] = {"Bucket": bucket}
        if prefix:
            kwargs["Prefix"] = prefix
        keys: list[str] = []
        for page in paginator.paginate(**kwargs):
            for item in page.get("Contents") or []:
                key = item.get("Key") or ""
                if key.lower().endswith(".pdf"):
                    keys.append(key)
        return sorted(keys)

    def read_bytes(self, bucket: str, key: str) -> bytes:
        body = self.client.get_object(Bucket=bucket, Key=key)["Body"]
        return body.read(MAX_BYTES + 1)


def _public_policy(policy: dict) -> dict[str, object]:
    controls = [
        item.get("control_id", "")
        for item in policy.get("alignments") or []
        if item.get("status") == "matched" and item.get("control_id")
    ]
    return {
        "policy_id": policy.get("policy_id", ""),
        "title": policy.get("title", ""),
        "statement": policy.get("statement", ""),
        "controls": controls,
    }


def _document(source: str, location: str, report: dict | None = None, error: str = "") -> dict:
    if error or report is None:
        return {
            "source": source,
            "location": location,
            "ok": False,
            "persisted": False,
            "source_kind": "",
            "policies": [],
            "findings": [],
            "error": error,
        }
    unreadable = report.get("source_kind") == "unreadable" or any(
        item.get("code") == "unreadable-pdf" for item in report.get("findings") or []
    )
    return {
        "source": source,
        "location": location,
        "ok": not unreadable,
        "persisted": False,
        "source_kind": report.get("source_kind", ""),
        "policies": [_public_policy(policy) for policy in report.get("policies") or []],
        "findings": list(report.get("findings") or []),
        "error": "",
        "_policies": list(report.get("policies") or []),
        "_alignments": list(report.get("alignments") or []),
    }


def _analyze_path(path: Path, oscal_dir: Path, source: str, location: str) -> dict:
    try:
        report = analyze_pdf(path, oscal_dir)
    except Exception as exc:
        return _document(source, location, error=str(exc))
    return _document(source, location, report=report)


def _s3_objects(uri: str, source: BotoS3PdfSource) -> list[tuple[str, str, str]]:
    bucket, key = parse_s3_uri(uri)
    if key.lower().endswith(".pdf"):
        return [(bucket, key, f"s3://{bucket}/{key}")]
    return [(bucket, item, f"s3://{bucket}/{item}") for item in source.list_keys(bucket, key)]


def stage_s3_pdfs(uri: str, dest: Path, source: BotoS3PdfSource) -> list[Path]:
    """Download every PDF under an S3 folder into one submission directory."""
    saved: list[Path] = []
    for bucket, key, _location in _s3_objects(uri, source):
        saved.append(save_named_pdf(source.read_bytes(bucket, key), dest, Path(key).name))
    return saved


def run_batch(
    *,
    folders: list[Path],
    s3_uris: list[str],
    oscal_dir: Path,
    organization_path: Path,
    intake_dir: Path,
    store,
    persist: bool,
    s3_source: BotoS3PdfSource | None = None,
) -> dict[str, object]:
    """Analyze every PDF and, when asked, merge them into the graph in one write."""
    for folder in folders:
        if not Path(folder).is_dir():
            raise IntakeError(f"Folder not found: {folder}")
    for uri in s3_uris:
        parse_s3_uri(uri)

    documents: list[dict] = []
    run_dir: Path | None = None

    def destination() -> Path:
        nonlocal run_dir
        if run_dir is None:
            run_dir = create_submission_dir(intake_dir)
        return run_dir

    for folder in folders:
        paths = collect_folder_pdfs(folder)
        if not paths:
            documents.append(_document("folder", str(folder), error="Folder contains no PDF files"))
            continue
        for path in paths:
            try:
                staged = save_named_pdf(path.read_bytes(), destination(), path.name)
            except Exception as exc:
                documents.append(_document("folder", str(path), error=str(exc)))
                continue
            documents.append(_analyze_path(staged, oscal_dir, "folder", str(path)))

    if s3_uris:
        source = s3_source or BotoS3PdfSource()
        for uri in s3_uris:
            try:
                objects = _s3_objects(uri, source)
            except IntakeError:
                raise
            except Exception as exc:
                documents.append(_document("s3", uri, error=str(exc)))
                continue
            if not objects:
                documents.append(_document("s3", uri, error="S3 location contains no PDF objects"))
                continue
            for bucket, key, location in objects:
                try:
                    staged = save_named_pdf(source.read_bytes(bucket, key), destination(), Path(key).name)
                except Exception as exc:
                    documents.append(_document("s3", location, error=str(exc)))
                    continue
                documents.append(_analyze_path(staged, oscal_dir, "s3", location))

    policies: list[dict] = []
    alignments: list[dict] = []
    for document in documents:
        if document.get("ok"):
            policies.extend(document.pop("_policies", []))
            alignments.extend(document.pop("_alignments", []))
        else:
            document.pop("_policies", None)
            document.pop("_alignments", None)
    persisted = False
    if persist and policies:
        saved = persist_analysis(
            {"policies": policies, "alignments": alignments},
            organization_path,
            oscal_dir,
            store,
        )
        persisted = bool(saved.get("persisted"))
        ready = {policy.get("policy_id") for policy in policies}
        for document in documents:
            if document.get("ok") and any(item.get("policy_id") in ready for item in document["policies"]):
                document["persisted"] = persisted
    else:
        for document in documents:
            document.pop("_policies", None)
            document.pop("_alignments", None)

    failed = [document for document in documents if not document.get("ok")]
    return {
        "ok": bool(documents) and not failed,
        "count": len(documents),
        "failed": len(failed),
        "persisted": persisted,
        "submission_dir": str(run_dir) if run_dir else "",
        "documents": documents,
    }
