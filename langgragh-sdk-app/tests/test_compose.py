from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_app_compose_uses_a_dedicated_network_for_both_containers():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "name: policy-kg\n" in text
    assert "container_name: policy-kg-neo4j" in text
    assert "container_name: policy-kg-app" in text
    assert "name: policy-kg-net" in text
    assert "NEO4J_URI: bolt://neo4j:7687" in text
    assert "8080:8080" in text
    assert "profiles:" not in text
    entry = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "policy-kg serve" in entry
    assert "submissions" in entry
    assert "./submissions:/app/submissions" in text


def test_pytest_compose_uses_a_different_network():
    text = (ROOT / "docker-compose.test.yml").read_text(encoding="utf-8")
    assert "name: policy-kg-test-net" in text
    assert "container_name: policy-kg-test-neo4j" in text
    assert "policy-kg-net" not in text
