import json
from pathlib import Path

from policy_kg.cli import main
from policy_kg.pipeline import STAGES
from policy_kg.sample_pdfs import POLICY_SPECS

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def test_cli_skip_neo4j_writes_a_report(tmp_path: Path):
    from policy_kg.sample_pdfs import generate_pdfs

    generate_pdfs(tmp_path / "policies")
    report = tmp_path / "run.json"
    code = main(
        [
            "run",
            "--policy-dir",
            str(tmp_path / "policies"),
            "--oscal-dir",
            str(DATA / "oscal"),
            "--organization",
            str(DATA / "organization.json"),
            "--skip-neo4j",
            "--report",
            str(report),
        ]
    )
    assert code == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["persisted"] is True
    assert payload["trace"] == list(STAGES)
    assert {row["policy_id"] for row in payload["policies"]} == {spec["policy_id"] for spec in POLICY_SPECS}


def test_cli_generate_pdfs(tmp_path: Path):
    code = main(["generate-pdfs", "--out", str(tmp_path)])
    assert code == 0
    assert len(list(tmp_path.glob("*.pdf"))) == len(POLICY_SPECS)


def test_cli_missing_organization_is_a_usage_error(tmp_path: Path):
    code = main(
        [
            "run",
            "--policy-dir",
            str(tmp_path),
            "--oscal-dir",
            str(DATA / "oscal"),
            "--organization",
            str(tmp_path / "missing.json"),
            "--skip-neo4j",
        ]
    )
    assert code == 2


def test_cli_requires_neo4j_settings(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    code = main(
        [
            "run",
            "--policy-dir",
            str(DATA / "policies"),
            "--oscal-dir",
            str(DATA / "oscal"),
            "--organization",
            str(DATA / "organization.json"),
        ]
    )
    assert code == 2
