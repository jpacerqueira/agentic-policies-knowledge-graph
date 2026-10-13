"""LangGraph pipeline: PDF policies and OSCAL in, knowledge graph out."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from policy_kg.align import align_policies
from policy_kg.discover_sources import fetch_eu_ai_act, list_pdfs
from policy_kg.graphdoc import GraphDocument
from policy_kg.oscal_loader import load_oscal_dirs
from policy_kg.pdf_reader import extract_policies_from_pdf
from policy_kg.project import project_graph
from policy_kg.validate import validate_graph

logger = logging.getLogger("policy_kg")

STAGES = (
    "discover",
    "read_pdfs",
    "extract_policies",
    "load_oscal",
    "align",
    "project",
    "validate",
    "persist",
)


class PipelineState(TypedDict, total=False):
    policy_dir: str
    oscal_dir: str
    organization_path: str
    organization: dict
    fetch_eu_ai_act: bool
    eu_ai_act_cache: str
    pdf_paths: list
    pdf_documents: list
    policies: list
    rejected_pdfs: list
    oscal_bundle: dict
    alignments: list
    graph_summary: dict
    validation: dict
    persisted: bool
    errors: list
    trace: list


class PipelineResult:
    def __init__(self, state: dict, graph: GraphDocument) -> None:
        self.state = state
        self.graph = graph

    @property
    def ok(self) -> bool:
        return bool((self.state.get("validation") or {}).get("ok"))


def _stage(name: str, fn):
    def _run(state: PipelineState) -> dict:
        logger.info("stage %s", name)
        update = fn(state) or {}
        update["trace"] = [*state.get("trace", []), name]
        return update

    _run.__name__ = name
    return _run


def build_pipeline(store):
    """Compile the linear LangGraph. The store is closed over so it stays out of state."""
    box: dict[str, GraphDocument] = {}

    def discover(state: PipelineState) -> dict:
        cache = state.get("eu_ai_act_cache") or ""
        if state.get("fetch_eu_ai_act"):
            if not cache:
                raise ValueError("eu_ai_act_cache is required when fetch_eu_ai_act is set")
            fetch_eu_ai_act(Path(cache))
        organization_path = Path(state["organization_path"])
        organization = json.loads(organization_path.read_text(encoding="utf-8"))
        return {
            "organization": organization,
            "pdf_paths": list_pdfs(Path(state["policy_dir"])),
        }

    def read_pdfs(state: PipelineState) -> dict:
        documents = []
        errors = list(state.get("errors") or [])
        for raw in state.get("pdf_paths") or []:
            path = Path(raw)
            try:
                documents.append(extract_policies_from_pdf(path))
            except Exception as exc:
                errors.append(f"{path}: {exc}")
        return {"pdf_documents": documents, "errors": errors}

    def extract_policies(state: PipelineState) -> dict:
        policies = []
        rejected = []
        for document in state.get("pdf_documents") or []:
            blocks = document.get("policies") or []
            if not blocks:
                rejected.append(
                    {
                        "code": "missing-policy-block",
                        "path": document["path"],
                        "message": "PDF has no POLICY-BLOCK-START / POLICY-BLOCK-END block",
                    }
                )
                continue
            for block in blocks:
                missing = block.get("missing_fields") or []
                if missing:
                    rejected.append(
                        {
                            "code": "invalid-policy-block",
                            "path": document["path"],
                            "message": f"Policy block is missing {', '.join(missing)}",
                        }
                    )
                    continue
                policies.append(
                    {
                        "policy_id": block["policy_id"],
                        "title": block["title"],
                        "owner": block["owner"],
                        "applies_to": block["applies_to"],
                        "control_ids": block["control_ids"],
                        "statement": block["statement"],
                        "classification": block["classification"],
                        "source_path": document["path"],
                        "document_sha256": document["sha256"],
                    }
                )
        return {"policies": policies, "rejected_pdfs": rejected}

    def load_oscal(state: PipelineState) -> dict:
        directories = [Path(state["oscal_dir"])]
        cache = state.get("eu_ai_act_cache") or ""
        if cache and Path(cache).exists():
            directories.append(Path(cache))
        return {"oscal_bundle": load_oscal_dirs(directories)}

    def align(state: PipelineState) -> dict:
        bundle = state.get("oscal_bundle") or {}
        return {"alignments": align_policies(state.get("policies") or [], bundle.get("controls") or [])}

    def project(state: PipelineState) -> dict:
        graph = project_graph(
            state.get("organization") or {},
            state.get("policies") or [],
            state.get("alignments") or [],
            state.get("oscal_bundle") or {},
        )
        box["graph"] = graph
        return {"graph_summary": graph.summary()}

    def validate(state: PipelineState) -> dict:
        report = validate_graph(
            box["graph"],
            organization=state.get("organization") or {},
            policies=state.get("policies") or [],
            alignments=state.get("alignments") or [],
            bundle=state.get("oscal_bundle") or {},
            rejected_pdfs=state.get("rejected_pdfs") or [],
        )
        return {"validation": report}

    def persist(state: PipelineState) -> dict:
        if not (state.get("validation") or {}).get("ok"):
            return {"persisted": False}
        store.write(box["graph"])
        return {"persisted": True}

    graph = StateGraph(PipelineState)
    steps = {
        "discover": discover,
        "read_pdfs": read_pdfs,
        "extract_policies": extract_policies,
        "load_oscal": load_oscal,
        "align": align,
        "project": project,
        "validate": validate,
        "persist": persist,
    }
    for name in STAGES:
        graph.add_node(name, _stage(name, steps[name]))
    graph.add_edge(START, STAGES[0])
    for left, right in zip(STAGES, STAGES[1:]):
        graph.add_edge(left, right)
    graph.add_edge(STAGES[-1], END)
    return graph.compile(), box


def initial_state(
    *,
    policy_dir: Path,
    oscal_dir: Path,
    organization_path: Path,
    fetch_eu_ai_act: bool = False,
    eu_ai_act_cache: Path | None = None,
) -> PipelineState:
    return {
        "policy_dir": str(policy_dir),
        "oscal_dir": str(oscal_dir),
        "organization_path": str(organization_path),
        "fetch_eu_ai_act": fetch_eu_ai_act,
        "eu_ai_act_cache": str(eu_ai_act_cache) if eu_ai_act_cache else "",
        "pdf_paths": [],
        "pdf_documents": [],
        "policies": [],
        "rejected_pdfs": [],
        "oscal_bundle": {},
        "alignments": [],
        "graph_summary": {},
        "validation": {},
        "persisted": False,
        "errors": [],
        "trace": [],
    }


def run_pipeline(
    *,
    policy_dir: Path,
    oscal_dir: Path,
    organization_path: Path,
    store,
    fetch_eu_ai_act: bool = False,
    eu_ai_act_cache: Path | None = None,
) -> PipelineResult:
    compiled, box = build_pipeline(store)
    state = compiled.invoke(
        initial_state(
            policy_dir=policy_dir,
            oscal_dir=oscal_dir,
            organization_path=organization_path,
            fetch_eu_ai_act=fetch_eu_ai_act,
            eu_ai_act_cache=eu_ai_act_cache,
        )
    )
    return PipelineResult(state, box["graph"])
