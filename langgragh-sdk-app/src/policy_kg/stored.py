"""Read the policies and OSCAL ontology stored in Neo4j."""

from __future__ import annotations

STORED_QUERIES: dict[str, str] = {
    "summary": (
        "/* stored-summary */ "
        "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count ORDER BY label"
    ),
    "organization": (
        "/* stored-organization */ "
        "MATCH (o:Organization) "
        "OPTIONAL MATCH (o)-[:OPERATES]->(s:System) "
        "RETURN o.name AS name, o.tier AS tier, o.employee_count AS employee_count, "
        "o.sector AS sector, collect(DISTINCT s.slug) AS systems "
        "ORDER BY name"
    ),
    "catalogs": (
        "/* stored-catalogs */ "
        "MATCH (cat:Catalog) "
        "OPTIONAL MATCH (cat)-[:DEFINED_BY]->(f:FrameworkSource) "
        "RETURN cat.uuid AS catalog_uuid, cat.title AS title, cat.version AS version, "
        "cat.oscal_version AS oscal_version, f.framework_id AS framework_id, "
        "f.title AS framework_title, f.repository AS repository, f.scope AS scope, "
        "f.ssp_template AS ssp_template, f.specification AS specification "
        "ORDER BY title"
    ),
    "profiles": (
        "/* stored-profiles */ "
        "MATCH (pr:Profile) "
        "OPTIONAL MATCH (pr)-[:IMPORTS]->(cat:Catalog) "
        "OPTIONAL MATCH (pr)-[:SELECTS]->(c:Control) "
        "RETURN pr.title AS title, pr.uuid AS uuid, "
        "collect(DISTINCT cat.title) AS catalogs, "
        "collect(DISTINCT c.control_id) AS controls "
        "ORDER BY title"
    ),
    "groups": (
        "/* stored-groups */ "
        "MATCH (g:ControlGroup) "
        "RETURN g.catalog_uuid AS catalog_uuid, g.group_id AS group_id, g.title AS title "
        "ORDER BY catalog_uuid, group_id"
    ),
    "controls": (
        "/* stored-controls */ "
        "MATCH (c:Control)-[:IN_CATALOG]->(cat:Catalog) "
        "OPTIONAL MATCH (p:PolicyStatement)-[:IMPLEMENTS]->(c) "
        "RETURN cat.title AS catalog, c.control_id AS control_id, c.title AS title, "
        "collect(DISTINCT p.policy_id) AS policies "
        "ORDER BY catalog, control_id"
    ),
    "policies": (
        "/* stored-policies */ "
        "MATCH (p:PolicyStatement) "
        "OPTIONAL MATCH (p)-[:IMPLEMENTS]->(c:Control) "
        "OPTIONAL MATCH (p)-[:APPLIES_TO]->(s:System) "
        "RETURN p.policy_id AS policy_id, p.title AS title, p.owner AS owner, "
        "p.statement AS statement, p.classification AS classification, "
        "p.source_path AS source_path, "
        "collect(DISTINCT c.control_id) AS controls, "
        "collect(DISTINCT s.slug) AS systems "
        "ORDER BY policy_id"
    ),
}


def _texts(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _clean_row(row: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in row.items():
        if isinstance(value, (list, tuple)):
            cleaned[key] = _texts(value)
        else:
            cleaned[key] = value
    return cleaned


def read_stored_graph(store) -> dict[str, object]:
    """Return the policies and ontology currently stored in Neo4j."""
    if not hasattr(store, "run"):
        return {"connected": False, "reason": "Neo4j is not connected"}
    try:
        raw = {name: store.run(cypher) for name, cypher in STORED_QUERIES.items()}
    except Exception as exc:
        return {"connected": False, "reason": str(exc)}
    view = {name: [_clean_row(row) for row in rows] for name, rows in raw.items()}
    view["connected"] = True
    view["reason"] = ""
    return view
