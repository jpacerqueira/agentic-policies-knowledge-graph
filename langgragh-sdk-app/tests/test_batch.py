import json
from io import BytesIO
from pathlib import Path

from policy_kg.batch import BotoS3PdfSource, parse_s3_uri, run_batch
from policy_kg.cli import main
from policy_kg.neo4j_store import NullStore
from policy_kg.sample_pdfs import write_plain_pdf

ROOT = Path(__file__).resolve().parents[1]
OSCAL = ROOT / "data" / "oscal"
ORG = ROOT / "data" / "organization.json"


class FakeS3:
    def __init__(self, objects: dict[tuple[str, str], bytes]) -> None:
        self.objects = objects

    def list_keys(self, bucket: str, prefix: str) -> list[str]:
        return sorted(
            key
            for (found_bucket, key), _data in self.objects.items()
            if found_bucket == bucket and key.startswith(prefix) and key.lower().endswith(".pdf")
        )

    def read_bytes(self, bucket: str, key: str) -> bytes:
        return self.objects[(bucket, key)]


class _Paginator:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages

    def paginate(self, **kwargs):
        prefix = kwargs.get("Prefix") or ""
        for page in self.pages:
            contents = [
                item
                for item in page.get("Contents") or []
                if str(item.get("Key") or "").startswith(prefix)
            ]
            yield {"Contents": contents}


class _BotoClient:
    def __init__(self, pages: list[dict], objects: dict[str, bytes]) -> None:
        self.pages = pages
        self.objects = objects

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        return _Paginator(self.pages)

    def get_object(self, Bucket: str, Key: str):
        return {"Body": BytesIO(self.objects[Key])}


def _pdf(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    write_plain_pdf(path, text)
    return path


def test_folder_batch_copies_pdfs_into_one_submission_run(tmp_path):
    folder = tmp_path / "incoming"
    nested = folder / "october"
    nested.mkdir(parents=True)
    _pdf(
        nested,
        "incident.pdf",
        "Credit decisioning staff shall report every serious incident that affects the model.",
    )
    (folder / "notes.txt").write_text("not a pdf", encoding="utf-8")
    result = run_batch(
        folders=[folder],
        s3_uris=[],
        oscal_dir=OSCAL,
        organization_path=ORG,
        intake_dir=tmp_path / "submissions",
        store=NullStore(),
        persist=True,
    )
    assert result["ok"] is True
    assert result["persisted"] is True
    assert result["documents"][0]["policies"][0]["controls"] == ["aia-73"]
    run_dir = Path(result["submission_dir"])
    assert run_dir.parent == tmp_path / "submissions"
    assert list(run_dir.glob("*.pdf"))
    assert not list((tmp_path / "submissions").glob("*.pdf"))


def test_s3_folder_downloads_only_pdfs_into_the_submission_run(tmp_path):
    sample = _pdf(
        tmp_path,
        "remote.pdf",
        "The bank shall report every serious incident that affects payment customers.",
    )
    source = FakeS3(
        {
            ("policy-bucket", "policies/incident.pdf"): sample.read_bytes(),
            ("policy-bucket", "policies/readme.txt"): b"ignore",
            ("policy-bucket", "other/skip.pdf"): sample.read_bytes(),
        }
    )
    result = run_batch(
        folders=[],
        s3_uris=["s3://policy-bucket/policies/"],
        oscal_dir=OSCAL,
        organization_path=ORG,
        intake_dir=tmp_path / "submissions",
        store=NullStore(),
        persist=False,
        s3_source=source,
    )
    assert result["ok"] is True
    assert result["persisted"] is False
    assert result["count"] == 1
    assert result["documents"][0]["location"] == "s3://policy-bucket/policies/incident.pdf"
    assert result["documents"][0]["policies"][0]["controls"] == ["aia-73"]
    assert len(list(Path(result["submission_dir"]).glob("*.pdf"))) == 1


def test_boto_listing_skips_non_pdf_keys():
    client = _BotoClient(
        [
            {
                "Contents": [
                    {"Key": "policies/a.pdf"},
                    {"Key": "policies/notes.txt"},
                    {"Key": "archive/old.PDF"},
                ]
            }
        ],
        {},
    )
    keys = BotoS3PdfSource(client=client).list_keys("bucket", "policies/")
    assert keys == ["policies/a.pdf"]


def test_s3_uri_must_name_a_bucket():
    bucket, key = parse_s3_uri("s3://policy-bucket/policies/")
    assert bucket == "policy-bucket"
    assert key == "policies/"
    try:
        parse_s3_uri("https://example.com/file.pdf")
    except Exception as exc:
        assert "s3://" in str(exc)
    else:
        raise AssertionError("expected a bad S3 URI to fail")


def test_cli_batch_from_a_folder_can_skip_neo4j(tmp_path, monkeypatch):
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    folder = tmp_path / "incoming"
    folder.mkdir()
    _pdf(
        folder,
        "incident.pdf",
        "Credit decisioning staff shall report every serious incident that affects the model.",
    )
    report = tmp_path / "batch.json"
    code = main(
        [
            "batch",
            "--from-dir",
            str(folder),
            "--oscal-dir",
            str(OSCAL),
            "--organization",
            str(ORG),
            "--intake-dir",
            str(tmp_path / "submissions"),
            "--skip-neo4j",
            "--report",
            str(report),
        ]
    )
    assert code == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["persisted"] is False
    assert payload["submission_dir"]
    assert payload["documents"][0]["policies"][0]["controls"] == ["aia-73"]


def test_cli_batch_without_a_source_is_a_usage_error(tmp_path, monkeypatch):
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    code = main(
        [
            "batch",
            "--oscal-dir",
            str(OSCAL),
            "--organization",
            str(ORG),
            "--intake-dir",
            str(tmp_path),
            "--skip-neo4j",
        ]
    )
    assert code == 2
