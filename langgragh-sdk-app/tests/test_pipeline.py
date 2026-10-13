import json
from pathlib import Path

from policy_kg.frameworks import EU_AI_ACT_SCOPE, EU_AI_ACT_SSP_TEMPLATE, OSCAL_HOME
from policy_kg.neo4j_store import NullStore
from policy_kg.pipeline import STAGES, run_pipeline
from policy_kg.sample_pdfs import POLICY_SPECS, generate_pdfs, write_plain_pdf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class RecordingStore(NullStore):
    def __init__(self) -> None:
        self.writes = 0

    def write(self, graph):
        self.writes += 1
        return super().write(graph)


def _run(policy_dir: Path, store=None, organization: Path | None = None, **kwargs):
    return run_pipeline(
        policy_dir=policy_dir,
        oscal_dir=DATA / "oscal",
        organization_path=organization or DATA / "organization.json",
        store=store or NullStore(),
        **kwargs,
    )


def test_sample_bank_pipeline_is_valid(tmp_path: Path):
    generate_pdfs(tmp_path)
    result = _run(tmp_path)
    assert result.state["trace"] == list(STAGES)
    assert result.ok, result.state["validation"]["findings"]
    assert result.state["persisted"] is True
    summary = result.graph.summary()
    assert summary["nodes"]["PolicyStatement"] == 8
    assert summary["nodes"]["Organization"] == 1
    assert summary["nodes"]["System"] == 2
    org = result.graph.nodes_by_label("Organization")[0][1]
    assert org["tier"] == 1
    assert org["employee_count"] == 100000
    policies = {row["policy_id"]: row["controls"] for row in result.state["validation"]["policies"]}
    assert "aia-9" in policies["POL-SSD-001"]
    assert "ds-cm-1" in policies["POL-SSD-001"]
    assert "aia-73" in policies["POL-INC-006"]
    reviewed = {
        dst.as_dict()["control_id"]
        for _src, dst, _props in [
            (src, dst, props)
            for src, dst, props in result.graph.edges_of_type("REVIEWS")
        ]
    }
    assert "aia-18" not in reviewed
    assert "aia-9" in reviewed
    assert len(reviewed) == 17
    parameter_edges = result.graph.edges_of_type("SETS_PARAMETER")
    assert parameter_edges[0][2]["values"] == ["7 days"]
    frameworks = {props["framework_id"]: props for _ref, props in result.graph.nodes_by_label("FrameworkSource")}
    assert frameworks["eu-ai-act"]["scope"] == EU_AI_ACT_SCOPE
    assert frameworks["eu-ai-act"]["ssp_template"] == EU_AI_ACT_SSP_TEMPLATE
    assert frameworks["eu-ai-act"]["specification"] == OSCAL_HOME
    poam = result.graph.edges_of_type("ADDRESSES")
    assert {dst.as_dict()["control_id"] for _src, dst, _props in poam} == {"aia-15"}
    users = result.graph.nodes_by_label("User")
    assert users[0][1]["title"] == "Credit decision reviewer"


def test_new_pdf_without_declared_controls_uses_the_phrase_rule(tmp_path: Path):
    oscal = tmp_path / "oscal"
    policies = tmp_path / "policies"
    org_path = tmp_path / "organization.json"
    catalog = {
        "catalog": {
            "uuid": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa9",
            "metadata": {
                "title": "Tiny",
                "last-modified": "2026-10-13T00:00:00Z",
                "version": "0.1.0",
                "oscal-version": "1.1.2",
                "props": [{"name": "framework-id", "value": "eu-ai-act"}],
            },
            "groups": [
                {
                    "id": "g",
                    "title": "Incidents",
                    "controls": [
                        {
                            "id": "aia-73",
                            "title": "Serious incident reporting",
                            "parts": [{"name": "statement", "prose": "Report a serious incident."}],
                        }
                    ],
                }
            ],
        }
    }
    profile = {
        "profile": {
            "uuid": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb9",
            "metadata": {
                "title": "Tiny profile",
                "last-modified": "2026-10-13T00:00:00Z",
                "version": "0.1.0",
                "oscal-version": "1.1.2",
            },
            "imports": [
                {"href": "../catalog.json", "include-controls": [{"with-ids": ["aia-73"]}]}
            ],
        }
    }
    ssp = {
        "system-security-plan": {
            "uuid": "cccccccc-cccc-4ccc-8ccc-ccccccccccc9",
            "metadata": {
                "title": "Tiny SSP",
                "last-modified": "2026-10-13T00:00:00Z",
                "version": "0.1.0",
                "oscal-version": "1.1.2",
            },
            "import-profile": {"href": "../profiles/tiny.json"},
            "system-characteristics": {
                "system-ids": [{"id": "8f3c1a20-6b14-4d7e-9c31-0a6e5b7d2001"}],
                "system-name": "Credit Decisioning Platform",
            },
            "control-implementation": {
                "implemented-requirements": [
                    {
                        "uuid": "dddddddd-dddd-4ddd-8ddd-ddddddddddd9",
                        "control-id": "aia-73",
                        "description": "Report serious incidents.",
                    }
                ]
            },
        }
    }
    (oscal / "profiles").mkdir(parents=True)
    (oscal / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    (oscal / "profiles" / "tiny.json").write_text(json.dumps(profile), encoding="utf-8")
    (oscal / "ssp.json").write_text(json.dumps(ssp), encoding="utf-8")
    org = json.loads((DATA / "organization.json").read_text(encoding="utf-8"))
    org_path.write_text(json.dumps(org), encoding="utf-8")
    generate_pdfs(
        policies,
        [
            {
                "policy_id": "POL-NEW-073",
                "title": "Serious incident reporting",
                "owner": "CISO",
                "applies_to": "credit-decisioning",
                "oscal_controls": "",
                "classification": "Internal",
                "statement": "A serious incident in the credit AI system is reported on the statutory clock.",
            }
        ],
    )
    result = run_pipeline(
        policy_dir=policies,
        oscal_dir=oscal,
        organization_path=org_path,
        store=NullStore(),
    )
    assert result.ok, result.state["validation"]["findings"]
    alignment = result.state["alignments"][0]
    assert alignment["method"] == "phrase"
    assert alignment["control_id"] == "aia-73"


def test_invalid_pdf_is_not_persisted(tmp_path: Path):
    generate_pdfs(tmp_path)
    write_plain_pdf(tmp_path / "notes.pdf", "A memo with no policy block.")
    store = RecordingStore()
    result = _run(tmp_path, store)
    assert result.ok is False
    assert store.writes == 0
    assert result.state["persisted"] is False
    assert any(item["code"] == "missing-policy-block" for item in result.state["validation"]["findings"])


def test_unknown_control_and_wrong_headcount_fail(tmp_path: Path):
    specs = [dict(spec) for spec in POLICY_SPECS]
    specs[0]["oscal_controls"] = "does-not-exist"
    generate_pdfs(tmp_path, specs)
    result = _run(tmp_path)
    codes = {item["code"] for item in result.state["validation"]["findings"]}
    assert "unknown-control" in codes
    assert "uncovered-control" in codes
    org = json.loads((DATA / "organization.json").read_text(encoding="utf-8"))
    org["employee_count"] = 12
    org_path = tmp_path / "organization.json"
    org_path.write_text(json.dumps(org), encoding="utf-8")
    generate_pdfs(tmp_path / "policies")
    sized = _run(tmp_path / "policies", organization=org_path)
    assert any(item["code"] == "organization-profile" for item in sized.state["validation"]["findings"])


def test_duplicate_policy_id(tmp_path: Path):
    from policy_kg.sample_pdfs import render_policy_text, write_pdf

    text = render_policy_text(POLICY_SPECS[0])
    write_pdf(tmp_path / "one.pdf", text)
    write_pdf(tmp_path / "two.pdf", text)
    result = _run(tmp_path)
    assert any(item["code"] == "duplicate-policy-id" for item in result.state["validation"]["findings"])


def test_fetch_adds_an_upstream_catalog_without_dropping_the_baseline(tmp_path: Path, monkeypatch):
    payload = {
        "catalogs/eu-ai-act/catalog.json": {
            "catalog": {
                "uuid": "99999999-9999-4999-8999-999999999999",
                "metadata": {
                    "title": "Fetched Catalog",
                    "last-modified": "2026-10-13T00:00:00Z",
                    "version": "0.1.0",
                    "oscal-version": "1.1.2",
                },
                "groups": [{"id": "g", "title": "G", "controls": [{"id": "fetched-1", "title": "Fetched"}]}],
            }
        },
        "profiles/high-risk-provider-annex-iii/profile.json": {
            "profile": {
                "uuid": "88888888-8888-4888-8888-888888888888",
                "metadata": {
                    "title": "Fetched profile",
                    "last-modified": "2026-10-13T00:00:00Z",
                    "version": "0.1.0",
                    "oscal-version": "1.1.2",
                },
                "imports": [],
            }
        },
        "docs/examples/template-system-security-plan.json": {
            "system-security-plan": {
                "uuid": "77777777-7777-4777-8777-777777777777",
                "metadata": {
                    "title": "Fetched template",
                    "last-modified": "2026-10-13T00:00:00Z",
                    "version": "0.1.0",
                    "oscal-version": "1.1.2",
                },
                "import-profile": {"href": "#missing"},
                "system-characteristics": {
                    "system-ids": [{"id": "00000000-0000-4000-8000-000000000000"}],
                    "system-name": "Placeholder",
                },
            }
        },
        "assessment-plans/high-risk-provider-readiness/assessment-plan.json": {
            "assessment-plan": {
                "uuid": "66666666-6666-4666-8666-666666666666",
                "metadata": {
                    "title": "Fetched assessment",
                    "last-modified": "2026-10-13T00:00:00Z",
                    "version": "0.1.0",
                    "oscal-version": "1.1.2",
                },
                "import-ssp": {"href": "#missing"},
            }
        },
        "docs/SCOPE.md": "# scope\n",
    }

    class _Response:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def opener(url, timeout=60):
        for relative, body in payload.items():
            if url.endswith(relative):
                raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                return _Response(raw)
        raise AssertionError(url)

    monkeypatch.setattr("policy_kg.discover_sources.urlopen", opener)
    generate_pdfs(tmp_path / "policies")
    result = run_pipeline(
        policy_dir=tmp_path / "policies",
        oscal_dir=DATA / "oscal",
        organization_path=DATA / "organization.json",
        store=NullStore(),
        fetch_eu_ai_act=True,
        eu_ai_act_cache=tmp_path / "cache",
    )
    assert result.ok, result.state["validation"]["findings"]
    titles = {props["title"] for _ref, props in result.graph.nodes_by_label("Catalog")}
    assert "Fetched Catalog" in titles
    assert "EU AI Act offline snapshot for the Northline baseline" in titles
    assert (tmp_path / "cache" / "docs" / "SCOPE.md").read_text(encoding="utf-8").startswith("# scope")
