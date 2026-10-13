"""Named Cypher used by the local query command."""

QUERIES: dict[str, str] = {
    "summary": (
        "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count ORDER BY label"
    ),
    "policies": (
        "MATCH (p:PolicyStatement)-[:IMPLEMENTS]->(c:Control) "
        "RETURN p.policy_id AS policy_id, p.title AS title, "
        "collect(DISTINCT c.control_id) AS controls ORDER BY policy_id"
    ),
    "gaps": (
        "MATCH (ssp:SystemSecurityPlan)-[:DESCRIBES]->(:System) "
        "MATCH (ssp)-[:IMPORTS_PROFILE]->(pr:Profile)-[:SELECTS]->(c:Control) "
        "WHERE NOT (:PolicyStatement)-[:IMPLEMENTS]->(c) "
        "RETURN DISTINCT c.control_id AS control_id, c.title AS title ORDER BY control_id"
    ),
    "layers": (
        "MATCH (o:Ontology)-[h:HAS_LAYER]->(l:Layer) "
        "OPTIONAL MATCH (n)-[:IN_LAYER]->(l) "
        "RETURN o.title AS ontology, l.order AS order, l.layer_id AS layer_id, "
        "l.title AS title, l.summary AS summary, count(DISTINCT n) AS documents "
        "ORDER BY l.order"
    ),
    "frameworks": (
        "MATCH (c:Catalog)-[:DEFINED_BY]->(f:FrameworkSource) "
        "RETURN c.title AS catalog, f.framework_id AS framework_id, "
        "f.repository AS repository, f.scope AS scope, f.ssp_template AS ssp_template, "
        "f.specification AS specification ORDER BY framework_id"
    ),
}
