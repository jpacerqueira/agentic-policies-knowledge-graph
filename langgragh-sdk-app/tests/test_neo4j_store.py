from pathlib import Path

from policy_kg.pipeline import STAGES, run_pipeline
from policy_kg.queries import QUERIES
from policy_kg.sample_pdfs import POLICY_SPECS, generate_pdfs

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _counts(store, cypher: str) -> dict[str, int]:
    rows = store.run(cypher)
    return {row["label"]: row["count"] for row in rows}


def test_neo4j_write_is_idempotent_and_queryable(neo4j_store, tmp_path):
    neo4j_store.reset()
    generate_pdfs(tmp_path)
    result = run_pipeline(
        policy_dir=tmp_path,
        oscal_dir=DATA / "oscal",
        organization_path=DATA / "organization.json",
        store=neo4j_store,
    )
    assert result.ok, result.state["validation"]["findings"]
    labels = _counts(neo4j_store, "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count")
    rels = _counts(neo4j_store, "MATCH ()-[r]->() RETURN type(r) AS label, count(*) AS count")
    assert labels == result.graph.summary()["nodes"]
    assert rels == result.graph.summary()["relationships"]
    neo4j_store.write(result.graph)
    assert _counts(neo4j_store, "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count") == labels
    policies = neo4j_store.run(QUERIES["policies"])
    assert {row["policy_id"] for row in policies} == {spec["policy_id"] for spec in POLICY_SPECS}
    gaps = neo4j_store.run(QUERIES["gaps"])
    assert gaps == []
    frameworks = neo4j_store.run(QUERIES["frameworks"])
    by_id = {row["framework_id"]: row for row in frameworks}
    assert "olon-standards/eu-ai-act-oscal" in by_id["eu-ai-act"]["repository"]
    assert by_id["eu-ai-act"]["scope"].endswith("/docs/SCOPE.md")
    assert by_id["eu-ai-act"]["ssp_template"].endswith("template-system-security-plan.json")
    assert by_id["northline-devsecops"]["specification"] == "https://pages.nist.gov/OSCAL/"
    trace_ok = result.state["trace"] == list(STAGES)
    assert trace_ok
