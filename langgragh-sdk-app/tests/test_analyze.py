from pathlib import Path

from policy_kg.analyze import analyze_pdf, persist_analysis, segment_policy_text
from policy_kg.neo4j_store import NullStore
from policy_kg.sample_pdfs import render_policy_text, write_pdf, write_plain_pdf

ROOT = Path(__file__).resolve().parents[1]
OSCAL = ROOT / "data" / "oscal"
ORG = ROOT / "data" / "organization.json"


def test_segment_keeps_substantive_paragraphs():
    text = "Too short.\n\nThe bank shall report every serious incident that affects customers."
    assert segment_policy_text(text) == [
        "The bank shall report every serious incident that affects customers."
    ]


def test_policy_block_keeps_declared_controls(tmp_path):
    path = tmp_path / "declared.pdf"
    write_pdf(
        path,
        render_policy_text(
            {
                "policy_id": "POL-NEW-001",
                "title": "Incident notice",
                "owner": "Chief Information Security Officer",
                "applies_to": "credit-decisioning",
                "oscal_controls": "aia-73",
                "classification": "Internal",
                "statement": "Report a serious incident.",
            }
        ),
    )
    report = analyze_pdf(path, OSCAL)
    assert report["source_kind"] == "policy-block"
    assert report["policies"][0]["policy_id"] == "POL-NEW-001"
    assert report["policies"][0]["alignments"][0]["control_id"] == "aia-73"
    assert report["policies"][0]["alignments"][0]["status"] == "matched"
    assert not any(item["code"] == "unmapped-policy" for item in report["findings"])


def test_sourced_pdf_without_a_block_aligns_by_phrase(tmp_path):
    path = tmp_path / "sourced.pdf"
    write_plain_pdf(
        path,
        "Credit decisioning staff shall report every serious incident that affects the model "
        "to the oversight board before the next business day.",
    )
    report = analyze_pdf(path, OSCAL)
    assert report["source_kind"] == "text"
    policy = report["policies"][0]
    assert policy["policy_id"].startswith("SRC-")
    assert policy["applies_to"] == ["credit-decisioning"]
    assert policy["alignments"][0]["control_id"] == "aia-73"
    assert policy["alignments"][0]["method"] == "phrase"
    assert any(item["code"] == "sourced-text" for item in report["findings"])


def test_persist_merges_the_analyzed_policy_without_dropping_the_report(tmp_path):
    path = tmp_path / "sourced.pdf"
    write_plain_pdf(
        path,
        "The payments platform shall report every serious incident that affects customers.",
    )
    report = analyze_pdf(path, OSCAL)
    saved = persist_analysis(report, ORG, OSCAL, NullStore())
    assert saved["persisted"] is True
    assert saved["summary"]["nodes"]["PolicyStatement"] == 1
    assert saved["summary"]["relationships"]["IMPLEMENTS"] >= 1
