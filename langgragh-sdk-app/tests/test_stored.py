import threading
from urllib.request import urlopen

from policy_kg.frontend import FrontendApp, make_server, render_graph
from policy_kg.neo4j_store import NullStore
from policy_kg.stored import read_stored_graph

ROOT_ROWS = {
    "stored-summary": [{"label": "PolicyStatement", "count": 1}, {"label": "Catalog", "count": 1}],
    "stored-organization": [
        {
            "name": "Northline Bank plc",
            "tier": 1,
            "employee_count": 100000,
            "sector": "banking",
            "systems": ["credit-decisioning"],
        }
    ],
    "stored-catalogs": [
        {
            "catalog_uuid": "catalog-1",
            "title": "EU AI Act",
            "version": "1.0",
            "oscal_version": "1.1.2",
            "framework_id": "eu-ai-act",
            "framework_title": "EU Artificial Intelligence Act",
            "repository": "https://github.com/olon-standards/eu-ai-act-oscal",
            "scope": "",
            "ssp_template": "",
            "specification": "https://pages.nist.gov/OSCAL/",
        }
    ],
    "stored-profiles": [
        {
            "title": "Northline tier 1",
            "uuid": "profile-1",
            "catalogs": ["EU AI Act"],
            "controls": ["aia-9", None],
        }
    ],
    "stored-groups": [{"catalog_uuid": "catalog-1", "group_id": "oversight", "title": "Oversight"}],
    "stored-controls": [
        {
            "catalog": "EU AI Act",
            "control_id": "aia-73",
            "title": "Serious incident",
            "policies": ["POL-1"],
        }
    ],
    "stored-policies": [
        {
            "policy_id": "POL-1",
            "title": "Incident notice",
            "owner": "Chief Information Security Officer",
            "statement": "Report a serious incident.",
            "classification": "Internal",
            "source_path": "submissions/run/policy.pdf",
            "controls": ["aia-73"],
            "systems": ["credit-decisioning"],
        }
    ],
}


class QueryStore:
    def run(self, cypher: str):
        for marker, rows in ROOT_ROWS.items():
            if marker in cypher:
                return rows
        return []


def test_stored_view_lists_policies_and_ontology():
    view = read_stored_graph(QueryStore())
    assert view["connected"] is True
    assert view["policies"][0]["policy_id"] == "POL-1"
    assert view["policies"][0]["controls"] == ["aia-73"]
    assert view["profiles"][0]["controls"] == ["aia-9"]
    page = render_graph(view)
    assert "Stored graph" in page
    assert "EU AI Act" in page
    assert "aia-73" in page
    assert "POL-1" in page
    assert "Ontology" in page
    assert "Northline Bank plc" in page


def test_stored_page_says_when_neo4j_is_not_connected():
    page = render_graph(read_stored_graph(NullStore()))
    assert "Neo4j is not connected" in page


def test_graph_route_renders_the_stored_view():
    app = FrontendApp(
        oscal_dir=".",
        organization_path=".",
        intake_dir=".",
        store=QueryStore(),
    )
    server = make_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with urlopen(f"http://127.0.0.1:{port}/graph", timeout=10) as response:
            page = response.read().decode("utf-8")
        assert response.status == 200
        assert "POL-1" in page
        assert "eu-ai-act" in page
    finally:
        server.shutdown()
        server.server_close()
