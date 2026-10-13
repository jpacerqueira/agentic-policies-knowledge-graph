from pathlib import Path

from policy_kg.neo4j_store import NullStore
from policy_kg.pipeline import run_pipeline
from policy_kg.project import LAYERS, ONTOLOGY_UUID
from policy_kg.sample_pdfs import generate_pdfs

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def test_oscal_models_are_layers_in_lifecycle_order(tmp_path: Path):
    generate_pdfs(tmp_path)
    result = run_pipeline(
        policy_dir=tmp_path,
        oscal_dir=DATA / "oscal",
        organization_path=DATA / "organization.json",
        store=NullStore(),
    )
    assert result.ok, result.state["validation"]["findings"]
    ontology = result.graph.nodes_by_label("Ontology")
    assert ontology[0][1]["uuid"] == ONTOLOGY_UUID
    stored = {props["layer_id"]: props for _ref, props in result.graph.nodes_by_label("Layer")}
    assert [layer_id for layer_id, _title, _summary in LAYERS] == [
        layer_id for layer_id, _props in sorted(stored.items(), key=lambda item: item[1]["order"])
    ]
    follows = result.graph.edges_of_type("FOLLOWS")
    assert len(follows) == len(LAYERS) - 1
    catalogs = result.graph.nodes_by_label("Catalog")
    for ref, props in catalogs:
        assert props["layer"] == "catalog"
        assert result.graph.outgoing(ref, "IN_LAYER")[0][0].as_dict()["layer_id"] == "catalog"
    policies = result.graph.nodes_by_label("PolicyStatement")
    assert policies
    for ref, props in policies:
        assert props["layer"] == "policy"
        assert result.graph.outgoing(ref, "IN_LAYER")[0][0].as_dict()["layer_id"] == "policy"
    reviewed = {dst.as_dict()["control_id"] for _src, dst, _props in result.graph.edges_of_type("REVIEWED_CONTROL")}
    assert reviewed == {dst.as_dict()["control_id"] for _src, dst, _props in result.graph.edges_of_type("REVIEWS")}
    assert result.graph.edges_of_type("HAS_COMPONENT")
    assert result.graph.edges_of_type("HAS_ROLE")
