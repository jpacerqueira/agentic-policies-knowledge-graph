from pathlib import Path

from policy_kg.pdf_reader import parse_policy_blocks, read_pdf_text
from policy_kg.sample_pdfs import POLICY_SPECS, generate_pdfs, render_policy_text, write_plain_pdf


def test_policy_block_parser_joins_wrapped_statements():
    text = """
    POLICY-BLOCK-START
    policy_id=POL-NEW-001
    title=Wrapped policy
    owner=CISO
    applies_to=credit-decisioning, payments-delivery
    oscal_controls=aia-9, aia-15
    statement=First sentence
    stays on the control.
    statement=Second sentence.
    POLICY-BLOCK-END
    """
    parsed = parse_policy_blocks(text)
    assert len(parsed) == 1
    policy = parsed[0]
    assert policy["policy_id"] == "POL-NEW-001"
    assert policy["applies_to"] == ["credit-decisioning", "payments-delivery"]
    assert policy["control_ids"] == ["aia-9", "aia-15"]
    assert policy["statement"] == "First sentence stays on the control. Second sentence."
    assert policy["missing_fields"] == []


def test_dotted_control_ids_stay_intact():
    text = """
    POLICY-BLOCK-START
    policy_id=POL-DOT-001
    title=Dotted
    owner=CISO
    applies_to=credit-decisioning
    oscal_controls=aia-5.1.a, aia-5.1.ba
    statement=Do not deploy a prohibited practice.
    POLICY-BLOCK-END
    """
    parsed = parse_policy_blocks(text)[0]
    assert parsed["control_ids"] == ["aia-5.1.a", "aia-5.1.ba"]


def test_generated_pdf_roundtrip(tmp_path: Path):
    written = generate_pdfs(tmp_path)
    assert len(written) == len(POLICY_SPECS)
    found = set()
    for path in written:
        text = read_pdf_text(path)
        blocks = parse_policy_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["missing_fields"] == []
        found.add(blocks[0]["policy_id"])
        assert "POLICY-BLOCK-START" in text
    assert found == {spec["policy_id"] for spec in POLICY_SPECS}


def test_plain_pdf_has_no_block(tmp_path: Path):
    path = tmp_path / "notes.pdf"
    write_plain_pdf(path, "This note has no policy block.")
    assert parse_policy_blocks(read_pdf_text(path)) == []


def test_render_contains_the_contract_markers():
    text = render_policy_text(POLICY_SPECS[0])
    assert "POLICY-BLOCK-START" in text
    assert "POLICY-BLOCK-END" in text
    assert "policy_id=POL-SSD-001" in text
