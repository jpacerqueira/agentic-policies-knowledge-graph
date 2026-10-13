from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPO = ROOT.parent

TEST_PASSWORD = "policy-graph-test"


def _neo4j_settings() -> tuple[str, str, str]:
    uri = os.environ.get("NEO4J_URI", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    user = os.environ.get("NEO4J_USER", "neo4j")
    if uri:
        if password != TEST_PASSWORD:
            raise RuntimeError(
                "Refusing to wipe Neo4j unless NEO4J_PASSWORD is the disposable test password"
            )
        return uri, user, password
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.test.yml",
            "-p",
            "policykgtest",
            "up",
            "-d",
            "--wait",
        ],
        cwd=ROOT,
        check=True,
    )
    return "bolt://localhost:7688", user, TEST_PASSWORD


@pytest.fixture(scope="session")
def neo4j_store():
    from policy_kg.neo4j_store import Neo4jStore

    uri, user, password = _neo4j_settings()
    store = Neo4jStore(uri, user, password)
    store.wait_until_ready()
    if password != TEST_PASSWORD:
        store.close()
        raise RuntimeError("Refusing to wipe Neo4j unless the password is the disposable test password")
    store.reset()
    yield store
    store.close()
