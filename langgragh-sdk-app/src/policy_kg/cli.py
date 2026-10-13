"""Command line for the policy knowledge-graph pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from neo4j.exceptions import AuthError, ServiceUnavailable

from policy_kg.neo4j_store import Neo4jStore, NullStore
from policy_kg.pipeline import STAGES, run_pipeline
from policy_kg.queries import QUERIES
from policy_kg.sample_pdfs import generate_pdfs


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="policy-kg")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Read policy PDFs and OSCAL, then update the graph")
    run.add_argument("--policy-dir", type=Path, required=True)
    run.add_argument("--oscal-dir", type=Path, required=True)
    run.add_argument("--organization", type=Path, required=True)
    run.add_argument("--neo4j-uri", default="")
    run.add_argument("--neo4j-user", default="")
    run.add_argument("--neo4j-password", default="")
    run.add_argument("--skip-neo4j", action="store_true")
    run.add_argument("--fetch-eu-ai-act", action="store_true")
    run.add_argument("--eu-ai-act-cache", type=Path)
    run.add_argument("--report", type=Path)

    generate = sub.add_parser("generate-pdfs", help="Write the sample Northline Bank policy PDFs")
    generate.add_argument("--out", type=Path, required=True)

    fetch = sub.add_parser("fetch-eu-ai-act", help="Download the upstream EU AI Act OSCAL files")
    fetch.add_argument("--cache", type=Path, required=True)

    query = sub.add_parser("query", help="Run a named read-only Cypher query")
    query.add_argument("name", choices=sorted(QUERIES))
    query.add_argument("--neo4j-uri", default="")
    query.add_argument("--neo4j-user", default="")
    query.add_argument("--neo4j-password", default="")

    serve = sub.add_parser("serve", help="Open the page that analyzes a policy link or PDF")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--oscal-dir", type=Path, required=True)
    serve.add_argument("--organization", type=Path, required=True)
    serve.add_argument("--intake-dir", type=Path, required=True)
    serve.add_argument("--neo4j-uri", default="")
    serve.add_argument("--neo4j-user", default="")
    serve.add_argument("--neo4j-password", default="")
    serve.add_argument("--skip-neo4j", action="store_true")

    batch = sub.add_parser("batch", help="Ingest policy PDFs from a folder or an S3 prefix")
    batch.add_argument("--from-dir", type=Path, action="append", default=[])
    batch.add_argument("--s3-uri", action="append", default=[])
    batch.add_argument("--oscal-dir", type=Path, required=True)
    batch.add_argument("--organization", type=Path, required=True)
    batch.add_argument("--intake-dir", type=Path, required=True)
    batch.add_argument("--neo4j-uri", default="")
    batch.add_argument("--neo4j-user", default="")
    batch.add_argument("--neo4j-password", default="")
    batch.add_argument("--skip-neo4j", action="store_true")
    batch.add_argument("--report", type=Path)
    return parser


def _env(name: str, fallback: str = "") -> str:
    import os

    return os.environ.get(name, fallback)


def _connection(args) -> tuple[str, str, str]:
    uri = args.neo4j_uri or _env("NEO4J_URI")
    user = args.neo4j_user or _env("NEO4J_USER", "neo4j")
    password = args.neo4j_password or _env("NEO4J_PASSWORD")
    return uri, user, password


def _print_run(result, report_path: Path | None) -> None:
    validation = result.state.get("validation") or {}
    payload = {
        "ok": result.ok,
        "persisted": result.state.get("persisted", False),
        "trace": result.state.get("trace") or [],
        "summary": result.state.get("graph_summary") or {},
        "policies": validation.get("policies") or [],
        "findings": validation.get("findings") or [],
        "errors": result.state.get("errors") or [],
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text + "\n", encoding="utf-8")
    print(text)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "generate-pdfs":
        written = generate_pdfs(args.out)
        for path in written:
            print(path)
        return 0
    if args.command == "fetch-eu-ai-act":
        from policy_kg.discover_sources import fetch_eu_ai_act

        for path in fetch_eu_ai_act(args.cache):
            print(path)
        return 0
    if args.command == "serve":
        return _serve(args)
    if args.command == "batch":
        return _batch(args)
    if args.command == "query":
        uri, user, password = _connection(args)
        if not uri or not password:
            print("NEO4J_URI and NEO4J_PASSWORD are required", file=sys.stderr)
            return 2
        store = Neo4jStore(uri, user, password)
        try:
            store.wait_until_ready()
            print(json.dumps(store.run(QUERIES[args.name]), indent=2, default=str))
        except (ServiceUnavailable, AuthError, TimeoutError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        finally:
            store.close()
        return 0

    uri, user, password = _connection(args)
    store = None
    try:
        if args.skip_neo4j:
            store = NullStore()
        else:
            if not uri or not password:
                print("NEO4J_URI and NEO4J_PASSWORD are required, or pass --skip-neo4j", file=sys.stderr)
                return 2
            store = Neo4jStore(uri, user, password)
            store.wait_until_ready()
        cache = args.eu_ai_act_cache
        if args.fetch_eu_ai_act and cache is None:
            cache = args.oscal_dir.parent / "cache" / "eu-ai-act"
        result = run_pipeline(
            policy_dir=args.policy_dir,
            oscal_dir=args.oscal_dir,
            organization_path=args.organization,
            store=store,
            fetch_eu_ai_act=args.fetch_eu_ai_act,
            eu_ai_act_cache=cache,
        )
    except (ServiceUnavailable, AuthError, TimeoutError, OSError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        if isinstance(store, Neo4jStore):
            store.close()
    _print_run(result, args.report)
    if result.state.get("trace") != list(STAGES):
        print("pipeline trace did not match the expected stages", file=sys.stderr)
        return 1
    return 0 if result.ok else 1


def _batch(args) -> int:
    from policy_kg.batch import run_batch
    from policy_kg.intake import IntakeError

    if not args.from_dir and not args.s3_uri:
        print("Provide --from-dir or --s3-uri", file=sys.stderr)
        return 2
    if not args.oscal_dir.is_dir():
        print(f"OSCAL directory not found: {args.oscal_dir}", file=sys.stderr)
        return 2
    if not args.organization.is_file():
        print(f"Organization file not found: {args.organization}", file=sys.stderr)
        return 2
    store = None
    try:
        if args.skip_neo4j:
            store = NullStore()
        else:
            uri, user, password = _connection(args)
            if not uri or not password:
                print("NEO4J_URI and NEO4J_PASSWORD are required, or pass --skip-neo4j", file=sys.stderr)
                return 2
            store = Neo4jStore(uri, user, password)
            store.wait_until_ready()
        result = run_batch(
            folders=list(args.from_dir),
            s3_uris=list(args.s3_uri),
            oscal_dir=args.oscal_dir,
            organization_path=args.organization,
            intake_dir=args.intake_dir,
            store=store,
            persist=not args.skip_neo4j,
        )
    except IntakeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (ServiceUnavailable, AuthError, TimeoutError, OSError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        if isinstance(store, Neo4jStore):
            store.close()
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("ok") else 1


def _serve(args) -> int:
    from policy_kg.frontend import FrontendApp, serve

    if not args.oscal_dir.is_dir():
        print(f"OSCAL directory not found: {args.oscal_dir}", file=sys.stderr)
        return 2
    if not args.organization.is_file():
        print(f"Organization file not found: {args.organization}", file=sys.stderr)
        return 2
    store = None
    try:
        if args.skip_neo4j:
            store = NullStore()
        else:
            uri, user, password = _connection(args)
            if not uri or not password:
                print("NEO4J_URI and NEO4J_PASSWORD are required, or pass --skip-neo4j", file=sys.stderr)
                return 2
            store = Neo4jStore(uri, user, password)
            store.wait_until_ready()
        app = FrontendApp(
            oscal_dir=args.oscal_dir,
            organization_path=args.organization,
            intake_dir=args.intake_dir,
            store=store,
        )
        print(f"Policy intake listening on http://{args.host}:{args.port}", flush=True)
        serve(app, args.host, args.port)
    except (ServiceUnavailable, AuthError, TimeoutError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
    finally:
        if isinstance(store, Neo4jStore):
            store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
