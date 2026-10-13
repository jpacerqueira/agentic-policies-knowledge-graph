"""Consistency checks for the projected policy and control graph."""

from __future__ import annotations

from policy_kg.graphdoc import GraphDocument, NodeRef


def _finding(code: str, subject: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": "error", "subject": subject, "message": message}


def _policy_rows(graph: GraphDocument) -> list[dict[str, object]]:
    rows = []
    for ref, props in sorted(graph.nodes_by_label("PolicyStatement"), key=lambda item: item[0].as_dict()["policy_id"]):
        controls = sorted(
            dst.as_dict()["control_id"]
            for dst, _props in graph.outgoing(ref, "IMPLEMENTS")
        )
        rows.append(
            {
                "policy_id": ref.as_dict()["policy_id"],
                "title": props.get("title", ""),
                "controls": controls,
            }
        )
    return rows


def validate_graph(
    graph: GraphDocument,
    *,
    organization: dict,
    policies: list[dict],
    alignments: list[dict],
    bundle: dict,
    rejected_pdfs: list[dict],
) -> dict[str, object]:
    findings: list[dict[str, str]] = []
    findings.extend(bundle.get("errors") or [])

    orgs = graph.nodes_by_label("Organization")
    if len(orgs) != 1:
        findings.append(
            _finding(
                "organization-profile",
                organization.get("uuid", ""),
                "The graph needs exactly one tier-1 organization with 100000 employees",
            )
        )
    else:
        props = orgs[0][1]
        if props.get("tier") != 1 or props.get("employee_count") != 100000:
            findings.append(
                _finding(
                    "organization-profile",
                    str(props.get("name", "")),
                    "Northline baseline requires tier 1 and employee_count 100000",
                )
            )

    for rejected in rejected_pdfs:
        code = rejected.get("code") or "missing-policy-block"
        findings.append(_finding(code, rejected.get("path", ""), rejected.get("message", "PDF was rejected")))

    counts: dict[str, int] = {}
    for policy in policies:
        counts[policy["policy_id"]] = counts.get(policy["policy_id"], 0) + 1
    for policy_id, count in counts.items():
        if count > 1:
            findings.append(
                _finding("duplicate-policy-id", policy_id, f"Policy id {policy_id} appears {count} times")
            )

    slugs = {system.get("slug") for system in organization.get("systems") or []}
    for policy in policies:
        for slug in policy.get("applies_to") or []:
            if slug not in slugs:
                findings.append(
                    _finding(
                        "unknown-system",
                        f"{policy['policy_id']}:{slug}",
                        f"Policy {policy['policy_id']} applies to unknown system slug {slug}",
                    )
                )

    matched = {item["policy_id"] for item in alignments if item.get("status") == "matched"}
    for policy in policies:
        if policy["policy_id"] not in matched:
            findings.append(
                _finding(
                    "unmapped-policy",
                    policy["policy_id"],
                    f"Policy {policy['policy_id']} does not match an OSCAL control",
                )
            )
    for item in alignments:
        if item.get("status") == "unknown":
            findings.append(
                _finding(
                    "unknown-control",
                    f"{item['policy_id']}:{item['control_id']}",
                    f"Control {item['control_id']} is not in a loaded catalog",
                )
            )
        elif item.get("status") == "ambiguous":
            findings.append(
                _finding(
                    "ambiguous-control",
                    f"{item['policy_id']}:{item['control_id']}",
                    f"Control {item['control_id']} matched more than one catalog entry",
                )
            )

    for setting in bundle.get("parameter_sets") or []:
        if not setting.get("found"):
            findings.append(
                _finding(
                    "unknown-parameter",
                    f"{setting.get('profile_uuid')}:{setting.get('param_id')}",
                    f"Parameter {setting.get('param_id')} is not defined once in the imported catalogs",
                )
            )

    org_system_ids = {
        ref.as_dict()["uuid"]
        for ref, _props in graph.nodes_by_label("System")
        if graph.incoming(ref, "OPERATES")
    }
    in_scope: set[NodeRef] = set()
    for ssp_ref, ssp_props in graph.nodes_by_label("SystemSecurityPlan"):
        if ssp_props.get("system_uuid") not in org_system_ids:
            continue
        if not graph.outgoing(ssp_ref, "DESCRIBES"):
            continue
        for profile_ref, _props in graph.outgoing(ssp_ref, "IMPORTS_PROFILE"):
            for control_ref, _props in graph.outgoing(profile_ref, "SELECTS"):
                in_scope.add(control_ref)
    for control_ref in sorted(in_scope, key=lambda ref: ref.as_dict()["control_id"]):
        control_id = control_ref.as_dict()["control_id"]
        if not graph.incoming(control_ref, "IMPLEMENTS"):
            findings.append(
                _finding(
                    "uncovered-control",
                    control_id,
                    f"Selected control {control_id} has no policy statement",
                )
            )
        if not graph.incoming(control_ref, "SATISFIES"):
            findings.append(
                _finding(
                    "unimplemented-control",
                    control_id,
                    f"Selected control {control_id} has no SSP or component implementation",
                )
            )

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in findings:
        identity = (finding["code"], finding["subject"], finding["message"])
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(finding)
    deduped.sort(key=lambda item: (item["code"], item["subject"], item["message"]))
    return {
        "ok": not deduped,
        "findings": deduped,
        "policies": _policy_rows(graph),
    }
