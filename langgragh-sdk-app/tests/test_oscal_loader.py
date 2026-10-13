import json
from pathlib import Path

from policy_kg.oscal_loader import load_oscal_dirs, walk_controls

DATA = Path(__file__).resolve().parents[1] / "data" / "oscal"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _metadata(title: str = "Example") -> dict:
    return {
        "title": title,
        "last-modified": "2026-10-13T00:00:00Z",
        "version": "0.1.0",
        "oscal-version": "1.1.2",
    }


def test_nested_groups_and_dotted_control_ids():
    catalog = {
        "uuid": "11111111-1111-4111-8111-111111111111",
        "metadata": _metadata(),
        "groups": [
            {
                "id": "chapter-ii",
                "title": "Prohibited",
                "controls": [
                    {
                        "id": "aia-5.1.a",
                        "title": "Parent",
                        "parts": [{"id": "aia-5.1.a_smt", "name": "statement", "prose": "Parent prose"}],
                        "controls": [
                            {
                                "id": "aia-5.1.a.1",
                                "title": "Child",
                                "parts": [{"name": "statement", "prose": "Child prose"}],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    found = walk_controls(catalog)
    by_id = {item["control"]["id"]: item for item in found}
    assert set(by_id) == {"aia-5.1.a", "aia-5.1.a.1"}
    assert by_id["aia-5.1.a"]["parent_control_id"] is None
    assert by_id["aia-5.1.a.1"]["parent_control_id"] == "aia-5.1.a"
    assert [group["id"] for group in by_id["aia-5.1.a"]["groups"]] == ["chapter-ii"]


def test_sample_catalog_keeps_article_18_unselected():
    bundle = load_oscal_dirs([DATA])
    assert bundle["errors"] == []
    control_ids = {item["control_id"] for item in bundle["controls"]}
    assert "aia-18" in control_ids
    assert "aia-5.1.a" not in control_ids
    selected = {item["control_id"] for item in bundle["selections"] if item["found"]}
    assert "aia-9" in selected
    assert "ds-vm-1" in selected
    assert "aia-18" not in selected
    groups = next(item for item in bundle["controls"] if item["control_id"] == "aia-9")
    assert groups["group_ids"] == ["chapter-iii", "chapter-iii-section-2"]
    parameter = next(item for item in bundle["parameter_sets"] if item["param_id"] == "ds-vm-1_prm_1")
    assert parameter["found"] is True
    assert parameter["values"] == ["7 days"]


def test_back_matter_href_resolves_like_the_ssp_template(tmp_path: Path):
    catalog = tmp_path / "catalog.json"
    profile = tmp_path / "profile.json"
    ssp = tmp_path / "ssp.json"
    _write(
        catalog,
        {
            "catalog": {
                "uuid": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
                "metadata": _metadata("Catalog"),
                "groups": [
                    {
                        "id": "g",
                        "title": "G",
                        "controls": [{"id": "aia-9", "title": "Risk", "parts": [{"name": "statement", "prose": "Risk"}]}],
                    }
                ],
            }
        },
    )
    _write(
        profile,
        {
            "profile": {
                "uuid": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
                "metadata": _metadata("Profile"),
                "imports": [{"href": "catalog.json", "include-controls": [{"with-ids": ["aia-9"]}]}],
            }
        },
    )
    _write(
        ssp,
        {
            "system-security-plan": {
                "uuid": "6d1a2f0e-3c7b-4a9e-8f11-2b4c6d8e0a35",
                "metadata": _metadata("Template shaped SSP"),
                "import-profile": {"href": "#1e5d9a3c-77b2-4f60-9c8d-53a1e4b7c206"},
                "system-characteristics": {
                    "system-ids": [{"id": "00000000-0000-4000-8000-000000000000"}],
                    "system-name": "Placeholder",
                },
                "control-implementation": {
                    "implemented-requirements": [
                        {"uuid": "cccccccc-cccc-4ccc-8ccc-ccccccccccc1", "control-id": "aia-9", "remarks": "placeholder"}
                    ]
                },
                "back-matter": {
                    "resources": [
                        {
                            "uuid": "1e5d9a3c-77b2-4f60-9c8d-53a1e4b7c206",
                            "rlinks": [{"href": "profile.json"}],
                        }
                    ]
                },
            }
        },
    )
    bundle = load_oscal_dirs([tmp_path])
    assert bundle["errors"] == []
    from policy_kg.project import project_graph

    organization = {
        "uuid": "8f3c1a20-6b14-4d7e-9c31-0a6e5b7d1001",
        "name": "Northline Bank plc",
        "tier": 1,
        "employee_count": 100000,
        "systems": [],
    }
    graph = project_graph(organization, [], [], bundle)
    profiles = [ref.as_dict()["uuid"] for ref, _props in graph.outgoing(
        next(ref for ref, _props in graph.nodes_by_label("SystemSecurityPlan")),
        "IMPORTS_PROFILE",
    )]
    assert profiles == ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1"]


def test_unknown_model_and_larger_catalog_wins(tmp_path: Path):
    small = tmp_path / "small"
    large = tmp_path / "large"
    body = {
        "uuid": "dddddddd-dddd-4ddd-8ddd-ddddddddddd1",
        "metadata": _metadata("Small"),
        "groups": [{"id": "g", "title": "G", "controls": [{"id": "c-1", "title": "One"}]}],
    }
    _write(small / "catalog.json", {"catalog": body})
    larger = {
        "uuid": body["uuid"],
        "metadata": _metadata("Large"),
        "groups": [
            {
                "id": "g",
                "title": "G",
                "controls": [
                    {"id": "c-1", "title": "One"},
                    {"id": "c-2", "title": "Two"},
                ],
            }
        ],
    }
    _write(large / "catalog.json", {"catalog": larger})
    _write(small / "notes.json", {"note": "not oscal"})
    bundle = load_oscal_dirs([small, large])
    catalogs = [doc for doc in bundle["documents"] if doc["model"] == "catalog"]
    assert len(catalogs) == 1
    assert catalogs[0]["title"] == "Large"
    assert any(item["code"] == "unknown-oscal-model" for item in bundle["errors"])


def test_missing_import_is_an_unresolved_import(tmp_path: Path):
    _write(
        tmp_path / "profile.json",
        {
            "profile": {
                "uuid": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee1",
                "metadata": _metadata("Broken"),
                "imports": [{"href": "missing.json", "include-controls": [{"with-ids": ["aia-9"]}]}],
            }
        },
    )
    bundle = load_oscal_dirs([tmp_path])
    assert any(item["code"] == "unresolved-import" for item in bundle["errors"])
