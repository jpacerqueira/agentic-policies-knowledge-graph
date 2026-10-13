"""Analyze one policy PDF against the loaded OSCAL catalogs."""

from __future__ import annotations

import json
import re
from pathlib import Path

from policy_kg.align import align_policies
from policy_kg.oscal_loader import load_oscal_dirs
from policy_kg.pdf_reader import extract_policies_from_pdf
from policy_kg.project import project_graph

SYSTEM_SLUGS = ("credit-decisioning", "payments-delivery")


def segment_policy_text(text: str) -> list[str]:
    """Split extracted PDF text into statements long enough to align."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs: list[str] = []
    for chunk in re.split(r"\n\s*\n", normalized):
        cleaned = " ".join(chunk.split())
        if len(cleaned) >= 40:
            paragraphs.append(cleaned[:4000])
    if paragraphs:
        return paragraphs
    cleaned = " ".join(normalized.split())
    if len(cleaned) >= 40:
        return [cleaned[:4000]]
    return []


def _title(statement: str, index: int) -> str:
    sentence = re.split(r"(?<=[.!?])\s", statement, maxsplit=1)[0].strip()
    if not sentence:
        return f"Imported policy {index}"
    if len(sentence) > 72:
        return sentence[:69].rstrip() + "..."
    return sentence


def _applies_to(statement: str) -> list[str]:
    lowered = statement.lower()
    found = []
    for slug in SYSTEM_SLUGS:
        if slug in lowered or slug.replace("-", " ") in lowered:
            found.append(slug)
    return found


def _policies_from_document(document: dict) -> tuple[list[dict], str, list[dict]]:
    findings: list[dict] = []
    blocks = document.get("policies") or []
    if blocks:
        policies = []
        for block in blocks:
            missing = block.get("missing_fields") or []
            if missing:
                findings.append(
                    {
                        "code": "invalid-policy-block",
                        "severity": "error",
                        "subject": document.get("path", ""),
                        "message": f"Policy block is missing {', '.join(missing)}",
                    }
                )
                continue
            policies.append(
                {
                    "policy_id": block["policy_id"],
                    "title": block["title"],
                    "owner": block["owner"],
                    "applies_to": list(block.get("applies_to") or []),
                    "control_ids": list(block.get("control_ids") or []),
                    "statement": block["statement"],
                    "classification": block.get("classification", ""),
                    "source_path": document["path"],
                    "document_sha256": document["sha256"],
                }
            )
        return policies, "policy-block", findings

    policies = []
    for index, statement in enumerate(segment_policy_text(document.get("text") or ""), start=1):
        policies.append(
            {
                "policy_id": f"SRC-{document['sha256'][:8]}-{index:03d}",
                "title": _title(statement, index),
                "owner": "Imported",
                "applies_to": _applies_to(statement),
                "control_ids": [],
                "statement": statement,
                "classification": "Imported",
                "source_path": document["path"],
                "document_sha256": document["sha256"],
            }
        )
    if policies:
        findings.append(
            {
                "code": "sourced-text",
                "severity": "info",
                "subject": document.get("path", ""),
                "message": (
                    "PDF has no policy block. Statements were taken from the document text "
                    "and aligned to OSCAL controls."
                ),
            }
        )
    return policies, "text", findings


def _alignment_findings(policies: list[dict], alignments: list[dict]) -> list[dict]:
    findings = []
    matched = {item["policy_id"] for item in alignments if item.get("status") == "matched"}
    for policy in policies:
        if policy["policy_id"] not in matched:
            findings.append(
                {
                    "code": "unmapped-policy",
                    "severity": "error",
                    "subject": policy["policy_id"],
                    "message": f"Policy {policy['policy_id']} does not match an OSCAL control",
                }
            )
    for item in alignments:
        if item.get("status") == "unknown":
            findings.append(
                {
                    "code": "unknown-control",
                    "severity": "error",
                    "subject": item.get("control_id", ""),
                    "message": f"Control {item.get('control_id', '')} is not in a loaded catalog",
                }
            )
        elif item.get("status") == "ambiguous":
            findings.append(
                {
                    "code": "ambiguous-control",
                    "severity": "error",
                    "subject": item.get("control_id", ""),
                    "message": f"Control {item.get('control_id', '')} matches more than one catalog",
                }
            )
    return findings


def analyze_pdf(path: Path, oscal_dir: Path) -> dict:
    """Read one PDF and align it to catalogs under ``oscal_dir``.

    A ``POLICY-BLOCK`` is used when present. Otherwise the extracted text is
    segmented and aligned by phrase and token overlap.
    """
    try:
        document = extract_policies_from_pdf(path)
    except Exception as exc:
        return {
            "source_kind": "unreadable",
            "path": str(path),
            "sha256": "",
            "policies": [],
            "alignments": [],
            "findings": [
                {
                    "code": "unreadable-pdf",
                    "severity": "error",
                    "subject": str(path),
                    "message": str(exc),
                }
            ],
        }

    text = (document.get("text") or "").strip()
    policies, source_kind, findings = _policies_from_document(document)
    if not text:
        findings.append(
            {
                "code": "no-extractable-text",
                "severity": "error",
                "subject": str(path),
                "message": "PDF has no extractable text",
            }
        )
    elif not policies and source_kind == "text":
        findings.append(
            {
                "code": "no-extractable-text",
                "severity": "error",
                "subject": str(path),
                "message": "PDF text is too short to analyze as a policy",
            }
        )

    bundle = load_oscal_dirs([Path(oscal_dir)])
    for error in bundle.get("errors") or []:
        findings.append(dict(error))
    alignments = align_policies(policies, bundle.get("controls") or []) if policies else []
    findings.extend(_alignment_findings(policies, alignments))
    by_policy: dict[str, list[dict]] = {}
    for item in alignments:
        by_policy.setdefault(item["policy_id"], []).append(item)
    published = []
    for policy in policies:
        row = dict(policy)
        row["alignments"] = by_policy.get(policy["policy_id"], [])
        published.append(row)
    return {
        "source_kind": source_kind,
        "path": str(path),
        "sha256": document.get("sha256", ""),
        "policies": published,
        "alignments": alignments,
        "findings": findings,
    }


def persist_analysis(report: dict, organization_path: Path, oscal_dir: Path, store) -> dict:
    """Merge the analyzed policies into the graph. Existing nodes stay."""
    policies = report.get("policies") or []
    if not policies:
        return {"persisted": False, "summary": {}}
    organization = json.loads(Path(organization_path).read_text(encoding="utf-8"))
    bundle = load_oscal_dirs([Path(oscal_dir)])
    graph = project_graph(organization, policies, report.get("alignments") or [], bundle)
    summary = store.write(graph)
    return {"persisted": True, "summary": summary}
