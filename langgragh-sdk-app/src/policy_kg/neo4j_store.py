"""Write a GraphDocument into a local Neo4j database."""

from __future__ import annotations

import json
import time

from neo4j import GraphDatabase

from policy_kg.graphdoc import KEY_FIELDS, GraphDocument

_SCALAR = (str, int, float, bool)


def _neo_value(value: object) -> object | None:
    if value is None or isinstance(value, _SCALAR):
        return value
    if isinstance(value, (list, tuple)):
        if all(item is None or isinstance(item, _SCALAR) for item in value):
            return list(value)
        return json.dumps(value, sort_keys=True)
    return json.dumps(value, sort_keys=True)


def _sanitize(props: dict[str, object]) -> dict[str, object]:
    clean: dict[str, object] = {}
    for key, value in props.items():
        converted = _neo_value(value)
        if converted is not None:
            clean[key] = converted
    return clean


def _constraint_cypher() -> list[str]:
    statements = []
    for label, fields in KEY_FIELDS.items():
        name = "pkg_" + label.lower() + "_" + "_".join(fields)
        if len(fields) == 1:
            field = fields[0]
            statements.append(
                f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.{field} IS UNIQUE"
            )
        else:
            joined = ", ".join(f"n.{field}" for field in fields)
            statements.append(
                f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE ({joined}) IS UNIQUE"
            )
    return statements


def _merge_pattern(keys: dict[str, str]) -> str:
    return ", ".join(f"{name}: ${name}" for name in keys)


class Neo4jStore:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        self.database = database
        self._driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=5)

    def close(self) -> None:
        self._driver.close()

    def wait_until_ready(self, attempts: int = 30, delay: float = 2.0) -> None:
        last: Exception | None = None
        for _ in range(attempts):
            try:
                self._driver.verify_connectivity()
                return
            except Exception as exc:  # connection errors vary by driver version
                last = exc
                time.sleep(delay)
        raise TimeoutError(f"Neo4j did not accept connections: {last}") from last

    def reset(self) -> None:
        with self._driver.session(database=self.database) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()

    def write(self, graph: GraphDocument) -> dict[str, dict[str, int]]:
        with self._driver.session(database=self.database) as session:
            for statement in _constraint_cypher():
                session.run(statement).consume()
            session.execute_write(lambda tx: _write_tx(tx, graph))
        return graph.summary()

    def run(self, cypher: str) -> list[dict[str, object]]:
        records, _, _ = self._driver.execute_query(cypher, database_=self.database)
        rows = []
        for record in records:
            rows.append({key: record[key] for key in record.keys()})
        return rows


def _write_tx(tx, graph: GraphDocument) -> None:
    for ref, props in graph.nodes.items():
        keys = ref.as_dict()
        cypher = f"MERGE (n:{ref.label} {{{_merge_pattern(keys)}}}) SET n += $props"
        tx.run(cypher, {**keys, "props": _sanitize(props)}).consume()
    for (src, rel, dst), props in graph.edges.items():
        src_keys = src.as_dict()
        dst_keys = dst.as_dict()
        src_pattern = ", ".join(f"{name}: $src_{name}" for name in src_keys)
        dst_pattern = ", ".join(f"{name}: $dst_{name}" for name in dst_keys)
        cypher = (
            f"MATCH (a:{src.label} {{{src_pattern}}}) "
            f"MATCH (b:{dst.label} {{{dst_pattern}}}) "
            f"MERGE (a)-[r:{rel}]->(b) "
            f"SET r += $props"
        )
        parameters = {f"src_{name}": value for name, value in src_keys.items()}
        parameters.update({f"dst_{name}": value for name, value in dst_keys.items()})
        parameters["props"] = _sanitize(props)
        tx.run(cypher, parameters).consume()


class NullStore:
    """Accept a graph without contacting Neo4j."""

    def write(self, graph: GraphDocument) -> dict[str, dict[str, int]]:
        return graph.summary()
