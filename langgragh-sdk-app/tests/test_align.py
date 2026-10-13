from policy_kg.align import align_policies


def _control(catalog: str, control_id: str, title: str, statement: str = "") -> dict:
    return {
        "catalog_uuid": catalog,
        "control_id": control_id,
        "title": title,
        "statement": statement,
    }


def _policy(policy_id: str, statement: str, control_ids: list[str] | None = None) -> dict:
    return {
        "policy_id": policy_id,
        "statement": statement,
        "control_ids": control_ids or [],
    }


def test_declared_mapping_beats_phrase_rules():
    controls = [
        _control("eu", "aia-9", "Risk management system"),
        _control("eu", "aia-73", "Serious incident reporting", "Report a serious incident"),
    ]
    alignments = align_policies(
        [_policy("POL-1", "This mentions a serious incident but declares risk only.", ["aia-9"])],
        controls,
    )
    assert [(item["control_id"], item["status"], item["method"]) for item in alignments] == [
        ("aia-9", "matched", "declared")
    ]


def test_unknown_and_ambiguous_declared_controls():
    controls = [
        _control("eu", "aia-9", "Risk"),
        _control("other", "aia-9", "Risk copy"),
    ]
    alignments = align_policies(
        [_policy("POL-1", "Nothing relevant.", ["missing-1", "aia-9"])],
        controls,
    )
    by_id = {item["control_id"]: item["status"] for item in alignments}
    assert by_id == {"missing-1": "unknown", "aia-9": "ambiguous"}


def test_phrase_rule_maps_serious_incident():
    controls = [_control("eu", "aia-73", "Serious incident reporting")]
    alignments = align_policies(
        [_policy("POL-KW", "A serious incident in the credit system must be reported.")],
        controls,
    )
    assert alignments[0]["status"] == "matched"
    assert alignments[0]["control_id"] == "aia-73"
    assert alignments[0]["method"] == "phrase"
    assert alignments[0]["catalog_uuid"] == "eu"


def test_token_overlap_maps_a_single_title_and_ties_are_ambiguous():
    controls = [
        _control("ds", "ds-cm-1", "Production change control"),
        _control("ds", "ds-other", "Production change control"),
    ]
    tied = align_policies(
        [_policy("POL-T", "Peer review of production change control before release.")],
        controls,
    )
    assert {item["status"] for item in tied} == {"ambiguous"}
    unique = align_policies(
        [_policy("POL-T", "Peer review of production change control before release.")],
        [controls[0]],
    )
    assert unique[0]["status"] == "matched"
    assert unique[0]["control_id"] == "ds-cm-1"
    assert unique[0]["method"] == "overlap"
