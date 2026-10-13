"""Project organization, policy, and OSCAL records onto the graph document."""

from __future__ import annotations

from pathlib import Path

from policy_kg.frameworks import FRAMEWORKS
from policy_kg.graphdoc import GraphDocument, NodeRef

ONTOLOGY_UUID = "oscal-control-lifecycle"
LAYERS = (
    ("catalog", "Catalog", "Lists of controls, groups, parts, and parameters. Nodes merge on catalog uuid and control id."),
    ("profile", "Profile", "Controls selected from an imported catalog, plus parameter values set for this organization."),
    ("component-definition", "Component definition", "How a component implements a control. Requirements point at the catalog control."),
    ("system-security-plan", "System security plan", "The operated system, its components, users, roles, parties, and the imported profile."),
    ("assessment-plan", "Assessment plan", "How the selected controls will be reviewed. It imports the system security plan."),
    ("assessment-results", "Assessment results", "Findings from that review. It imports the assessment plan and shares parties and roles by uuid."),
    ("plan-of-action-and-milestones", "Plan of action and milestones", "Corrective items. Each item addresses a control and can relate to a risk."),
    ("policy", "Policy", "Bank policy statements. A matched statement implements a control in a catalog."),
)


def _props_map(props: list | None) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for item in props or []:
        name = item.get("name")
        if name:
            mapped[str(name)] = "" if item.get("value") is None else str(item["value"])
    return mapped


def _project_ontology(graph: GraphDocument) -> dict[str, NodeRef]:
    ontology = graph.merge_node(
        "Ontology",
        {"uuid": ONTOLOGY_UUID},
        {
            "title": "OSCAL control lifecycle",
            "method": "Each OSCAL model is one layer. Nodes merge on uuid or id. Shared uuids and import hrefs connect the layers.",
        },
    )
    layers: dict[str, NodeRef] = {}
    previous: NodeRef | None = None
    for order, (layer_id, title, summary) in enumerate(LAYERS, start=1):
        layer = graph.merge_node(
            "Layer",
            {"layer_id": layer_id},
            {"title": title, "summary": summary, "order": order, "model": layer_id},
        )
        graph.merge_edge(ontology, "HAS_LAYER", layer, {"order": order})
        if previous is not None:
            graph.merge_edge(layer, "FOLLOWS", previous, {})
        layers[layer_id] = layer
        previous = layer
    return layers


def _in_layer(graph: GraphDocument, node: NodeRef, layer_id: str, layers: dict[str, NodeRef]) -> None:
    graph.merge_edge(node, "IN_LAYER", layers[layer_id], {})


def _project_metadata(graph: GraphDocument, metadata: dict, owner: NodeRef | None) -> None:
    for role in metadata.get("roles") or []:
        if not role.get("id"):
            continue
        role_ref = graph.merge_node(
            "Role",
            {"role_id": role["id"]},
            {"title": role.get("title", ""), "description": role.get("description", "")},
        )
        if owner is not None:
            graph.merge_edge(owner, "HAS_ROLE", role_ref, {})
    for party in metadata.get("parties") or []:
        if not party.get("uuid"):
            continue
        party_ref = graph.merge_node(
            "Party",
            {"uuid": party["uuid"]},
            {"name": party.get("name", ""), "party_type": party.get("type", "")},
        )
        if owner is not None:
            graph.merge_edge(owner, "HAS_PARTY", party_ref, {})
    if owner is None:
        return
    for responsible in metadata.get("responsible-parties") or []:
        role_id = responsible.get("role-id", "")
        for party_uuid in responsible.get("party-uuids") or []:
            graph.merge_edge(
                owner,
                "ACCOUNTABLE",
                NodeRef.make("Party", {"uuid": party_uuid}),
                {"role_id": role_id},
            )
            if role_id:
                graph.merge_edge(
                    NodeRef.make("Role", {"role_id": role_id}),
                    "RESPONSIBLE_PARTY",
                    NodeRef.make("Party", {"uuid": party_uuid}),
                    {},
                )
                graph.merge_edge(
                    NodeRef.make("Party", {"uuid": party_uuid}),
                    "PERFORMS",
                    NodeRef.make("Role", {"role_id": role_id}),
                    {},
                )


def _project_org(graph: GraphDocument, organization: dict) -> None:
    org = graph.merge_node(
        "Organization",
        {"uuid": organization["uuid"]},
        {
            "name": organization.get("name", ""),
            "tier": organization.get("tier"),
            "employee_count": organization.get("employee_count"),
            "sector": organization.get("sector", ""),
            "jurisdictions": organization.get("jurisdictions") or [],
            "fictional": True,
        },
    )
    for system in organization.get("systems") or []:
        system_ref = graph.merge_node(
            "System",
            {"uuid": system["uuid"]},
            {
                "name": system.get("name", ""),
                "slug": system.get("slug", ""),
                "description": system.get("description", ""),
                "risk_classification": system.get("risk_classification", ""),
                "annex_iii": system.get("annex_iii", ""),
                "operator_roles": system.get("operator_roles") or [],
            },
        )
        graph.merge_edge(org, "OPERATES", system_ref, {})


def _project_catalog(graph: GraphDocument, doc: dict, controls: list[dict], layers: dict[str, NodeRef]) -> None:
    body = doc["body"]
    metadata = body.get("metadata") or {}
    framework_id = _props_map(metadata.get("props")).get("framework-id", "")
    catalog = graph.merge_node(
        "Catalog",
        {"uuid": body["uuid"]},
        {
            "title": metadata.get("title", ""),
            "version": metadata.get("version", ""),
            "oscal_version": metadata.get("oscal-version", ""),
            "framework_id": framework_id,
            "source_path": doc["path"],
            "layer": "catalog",
        },
    )
    _in_layer(graph, catalog, "catalog", layers)
    if framework_id:
        info = FRAMEWORKS.get(framework_id, {})
        source = graph.merge_node(
            "FrameworkSource",
            {"framework_id": framework_id},
            {"title": info.get("title", framework_id), **info},
        )
        graph.merge_edge(catalog, "DEFINED_BY", source, {})
    _project_metadata(graph, metadata, catalog)
    for item in controls:
        parent: NodeRef = catalog
        for group_id, group_title in zip(item["group_ids"], item["group_titles"]):
            if not group_id:
                continue
            group = graph.merge_node(
                "ControlGroup",
                {"catalog_uuid": body["uuid"], "group_id": group_id},
                {"title": group_title},
            )
            graph.merge_edge(parent, "HAS_GROUP", group, {})
            parent = group
        control_body = item["control"]
        props = _props_map(control_body.get("props"))
        control = graph.merge_node(
            "Control",
            {"catalog_uuid": body["uuid"], "control_id": item["control_id"]},
            {
                "title": control_body.get("title", ""),
                "class": control_body.get("class", ""),
                "statement": item.get("statement", ""),
                "label": props.get("label", ""),
                "article": props.get("article", ""),
            },
        )
        graph.merge_edge(parent, "HAS_CONTROL", control, {})
        graph.merge_edge(control, "IN_CATALOG", catalog, {})
        parent_id = item.get("parent_control_id")
        if parent_id:
            graph.merge_edge(
                control,
                "CHILD_OF",
                NodeRef.make("Control", {"catalog_uuid": body["uuid"], "control_id": parent_id}),
                {},
            )
        for part in control_body.get("parts") or []:
            part_id = part.get("id") or f"{item['control_id']}_{part.get('name', 'part')}"
            part_ref = graph.merge_node(
                "ControlPart",
                {"catalog_uuid": body["uuid"], "part_id": part_id},
                {"name": part.get("name", ""), "prose": part.get("prose", "")},
            )
            graph.merge_edge(control, "HAS_PART", part_ref, {})
        for param in control_body.get("params") or []:
            if not param.get("id"):
                continue
            param_ref = graph.merge_node(
                "Parameter",
                {"catalog_uuid": body["uuid"], "param_id": param["id"]},
                {
                    "label": param.get("label", ""),
                    "values": param.get("values") or [],
                },
            )
            graph.merge_edge(control, "HAS_PARAMETER", param_ref, {})


def _project_profile(graph: GraphDocument, doc: dict, bundle: dict, layers: dict[str, NodeRef]) -> None:
    body = doc["body"]
    metadata = body.get("metadata") or {}
    profile = graph.merge_node(
        "Profile",
        {"uuid": body["uuid"]},
        {
            "title": metadata.get("title", ""),
            "version": metadata.get("version", ""),
            "oscal_version": metadata.get("oscal-version", ""),
            "source_path": doc["path"],
            "layer": "profile",
        },
    )
    _in_layer(graph, profile, "profile", layers)
    _project_metadata(graph, metadata, profile)
    for selection in bundle["selections"]:
        if selection["profile_uuid"] != body["uuid"] or not selection["found"]:
            continue
        catalog = NodeRef.make("Catalog", {"uuid": selection["catalog_uuid"]})
        graph.merge_edge(profile, "IMPORTS", catalog, {"href": selection["href"]})
        control = NodeRef.make(
            "Control",
            {"catalog_uuid": selection["catalog_uuid"], "control_id": selection["control_id"]},
        )
        graph.merge_edge(profile, "SELECTS", control, {})
    for setting in bundle["parameter_sets"]:
        if setting["profile_uuid"] != body["uuid"] or not setting["found"]:
            continue
        graph.merge_edge(
            profile,
            "SETS_PARAMETER",
            NodeRef.make(
                "Parameter",
                {"catalog_uuid": setting["catalog_uuid"], "param_id": setting["param_id"]},
            ),
            {"values": setting["values"]},
        )


def _control_in_catalog(bundle: dict, catalog_uuid: str | None, control_id: str) -> bool:
    return any(
        item["catalog_uuid"] == catalog_uuid and item["control_id"] == control_id
        for item in bundle["controls"]
    )


def _project_requirement(
    graph: GraphDocument,
    owner: NodeRef,
    requirement: dict,
    catalog_uuid: str | None,
    bundle: dict,
) -> None:
    control_id = requirement.get("control-id", "")
    req = graph.merge_node(
        "ImplementedRequirement",
        {"uuid": requirement["uuid"]},
        {
            "control_id": control_id,
            "description": requirement.get("description", "") or requirement.get("remarks", ""),
        },
    )
    graph.merge_edge(owner, "HAS_REQUIREMENT", req, {})
    if catalog_uuid and _control_in_catalog(bundle, catalog_uuid, control_id):
        graph.merge_edge(
            req,
            "SATISFIES",
            NodeRef.make("Control", {"catalog_uuid": catalog_uuid, "control_id": control_id}),
            {},
        )


def _catalog_for_href(bundle: dict, source_path: str, href: str) -> str | None:
    if not href:
        return None
    if href.startswith("#"):
        return None
    target = str((Path(source_path).parent / href).resolve())
    for doc in bundle["documents"]:
        if doc["path"] == target and doc["model"] == "catalog":
            return doc["uuid"]
    return None


def _project_component_definition(graph: GraphDocument, doc: dict, bundle: dict, layers: dict[str, NodeRef]) -> None:
    body = doc["body"]
    metadata = body.get("metadata") or {}
    definition = graph.merge_node(
        "ComponentDefinition",
        {"uuid": body["uuid"]},
        {
            "title": metadata.get("title", ""),
            "source_path": doc["path"],
            "oscal_version": metadata.get("oscal-version", ""),
            "layer": "component-definition",
        },
    )
    _in_layer(graph, definition, "component-definition", layers)
    _project_metadata(graph, metadata, definition)
    for component in body.get("components") or []:
        component_ref = graph.merge_node(
            "Component",
            {"uuid": component["uuid"]},
            {
                "title": component.get("title", ""),
                "description": component.get("description", ""),
                "component_type": component.get("type", ""),
            },
        )
        graph.merge_edge(definition, "DEFINES", component_ref, {})
        graph.merge_edge(definition, "HAS_COMPONENT", component_ref, {})
        for implementation in component.get("control-implementations") or []:
            catalog_uuid = _catalog_for_href(bundle, doc["path"], implementation.get("source", ""))
            for requirement in implementation.get("implemented-requirements") or []:
                _project_requirement(graph, component_ref, requirement, catalog_uuid, bundle)


def _system_uuid(body: dict) -> str:
    identifiers = (body.get("system-characteristics") or {}).get("system-ids") or []
    if identifiers:
        return str(identifiers[0].get("id", ""))
    return ""


def _profile_uuid_for_ssp(bundle: dict, doc: dict) -> str | None:
    href = (doc["body"].get("import-profile") or {}).get("href", "")
    if not href:
        return None
    if href.startswith("#"):
        resources = (doc["body"].get("back-matter") or {}).get("resources") or []
        for resource in resources:
            if f"#{resource.get('uuid')}" == href:
                for link in resource.get("rlinks") or []:
                    href = link.get("href", href)
    if href.startswith("#"):
        return href[1:]
    target = str((Path(doc["path"]).parent / href).resolve())
    for item in bundle["documents"]:
        if item["path"] == target and item["model"] == "profile":
            return item["uuid"]
    return None


def _project_ssp(graph: GraphDocument, doc: dict, bundle: dict, layers: dict[str, NodeRef]) -> None:
    body = doc["body"]
    metadata = body.get("metadata") or {}
    characteristics = body.get("system-characteristics") or {}
    system_uuid = _system_uuid(body)
    ssp = graph.merge_node(
        "SystemSecurityPlan",
        {"uuid": body["uuid"]},
        {
            "title": metadata.get("title", ""),
            "oscal_version": metadata.get("oscal-version", ""),
            "source_path": doc["path"],
            "system_uuid": system_uuid,
            "system_name": characteristics.get("system-name", ""),
            "security_sensitivity_level": characteristics.get("security-sensitivity-level", ""),
            "layer": "system-security-plan",
        },
    )
    _in_layer(graph, ssp, "system-security-plan", layers)
    _project_metadata(graph, metadata, ssp)
    profile_uuid = _profile_uuid_for_ssp(bundle, doc)
    if profile_uuid and any(item["uuid"] == profile_uuid for item in bundle["documents"] if item["model"] == "profile"):
        graph.merge_edge(ssp, "IMPORTS_PROFILE", NodeRef.make("Profile", {"uuid": profile_uuid}), {})
    if system_uuid and any(ref.as_dict().get("uuid") == system_uuid for ref, _props in graph.nodes_by_label("System")):
        graph.merge_edge(ssp, "DESCRIBES", NodeRef.make("System", {"uuid": system_uuid}), {})
    for component in (body.get("system-implementation") or {}).get("components") or []:
        component_ref = graph.merge_node(
            "Component",
            {"uuid": component["uuid"]},
            {
                "title": component.get("title", ""),
                "description": component.get("description", ""),
                "component_type": component.get("type", ""),
            },
        )
        graph.merge_edge(ssp, "HAS_COMPONENT", component_ref, {})
    for user in (body.get("system-implementation") or {}).get("users") or []:
        if not user.get("uuid"):
            continue
        user_ref = graph.merge_node(
            "User",
            {"uuid": user["uuid"]},
            {"title": user.get("title", "")},
        )
        if system_uuid and any(ref.as_dict().get("uuid") == system_uuid for ref, _props in graph.nodes_by_label("System")):
            graph.merge_edge(user_ref, "OVERSEES", NodeRef.make("System", {"uuid": system_uuid}), {})
        for role_id in user.get("role-ids") or []:
            graph.merge_node("Role", {"role_id": role_id}, {})
            graph.merge_edge(user_ref, "PERFORMS", NodeRef.make("Role", {"role_id": role_id}), {})
            graph.merge_edge(user_ref, "HAS_ROLE", NodeRef.make("Role", {"role_id": role_id}), {})
    selected = {
        (item["catalog_uuid"], item["control_id"])
        for item in bundle["selections"]
        if item["profile_uuid"] == profile_uuid and item["found"]
    }
    for requirement in (body.get("control-implementation") or {}).get("implemented-requirements") or []:
        control_id = requirement.get("control-id", "")
        catalog_uuid = next((catalog for catalog, cid in selected if cid == control_id), None)
        _project_requirement(graph, ssp, requirement, catalog_uuid, bundle)


def _link_import(graph: GraphDocument, owner: NodeRef, rel: str, href: str, source_path: str, bundle: dict, model: str) -> None:
    if not href or href.startswith("#"):
        target_uuid = href[1:] if href.startswith("#") else ""
        if any(doc["uuid"] == target_uuid and doc["model"] == model for doc in bundle["documents"]):
            label = {
                "system-security-plan": "SystemSecurityPlan",
                "assessment-plan": "AssessmentPlan",
            }[model]
            graph.merge_edge(owner, rel, NodeRef.make(label, {"uuid": target_uuid}), {})
        return
    target = str((Path(source_path).parent / href).resolve())
    for doc in bundle["documents"]:
        if doc["path"] == target and doc["model"] == model:
            label = {
                "system-security-plan": "SystemSecurityPlan",
                "assessment-plan": "AssessmentPlan",
            }[model]
            graph.merge_edge(owner, rel, NodeRef.make(label, {"uuid": doc["uuid"]}), {})


def _project_assessment_plan(graph: GraphDocument, doc: dict, bundle: dict, layers: dict[str, NodeRef]) -> None:
    body = doc["body"]
    metadata = body.get("metadata") or {}
    plan = graph.merge_node(
        "AssessmentPlan",
        {"uuid": body["uuid"]},
        {
            "title": metadata.get("title", ""),
            "source_path": doc["path"],
            "oscal_version": metadata.get("oscal-version", ""),
            "layer": "assessment-plan",
        },
    )
    _in_layer(graph, plan, "assessment-plan", layers)
    _project_metadata(graph, metadata, plan)
    href = (body.get("import-ssp") or {}).get("href", "")
    _link_import(graph, plan, "IMPORTS_SSP", href, doc["path"], bundle, "system-security-plan")
    include_all = any(
        "include-all" in selection
        for selection in (body.get("reviewed-controls") or {}).get("control-selections") or []
    )
    if not include_all:
        return
    ssp_targets = graph.outgoing(plan, "IMPORTS_SSP")
    for ssp_ref, _props in ssp_targets:
        for profile_ref, _profile_props in graph.outgoing(ssp_ref, "IMPORTS_PROFILE"):
            for control_ref, _control_props in graph.outgoing(profile_ref, "SELECTS"):
                graph.merge_edge(plan, "REVIEWS", control_ref, {})
                graph.merge_edge(plan, "REVIEWED_CONTROL", control_ref, {})
    for task in body.get("tasks") or []:
        if not task.get("uuid"):
            continue
        task_ref = graph.merge_node(
            "AssessmentTask",
            {"uuid": task["uuid"]},
            {"title": task.get("title", ""), "description": task.get("description", ""), "task_type": task.get("type", "")},
        )
        graph.merge_edge(plan, "HAS_TASK", task_ref, {})


def _project_assessment_results(graph: GraphDocument, doc: dict, bundle: dict, layers: dict[str, NodeRef]) -> None:
    body = doc["body"]
    metadata = body.get("metadata") or {}
    results = graph.merge_node(
        "AssessmentResults",
        {"uuid": body["uuid"]},
        {"title": metadata.get("title", ""), "source_path": doc["path"], "layer": "assessment-results"},
    )
    _in_layer(graph, results, "assessment-results", layers)
    _project_metadata(graph, metadata, results)
    href = (body.get("import-ap") or {}).get("href", "")
    _link_import(graph, results, "IMPORTS_AP", href, doc["path"], bundle, "assessment-plan")
    known = {(item["catalog_uuid"], item["control_id"]): item["control_id"] for item in bundle["controls"]}
    by_id: dict[str, list[str]] = {}
    for catalog_uuid, control_id in known:
        by_id.setdefault(control_id, []).append(catalog_uuid)
    for result in body.get("results") or []:
        for finding in result.get("findings") or []:
            if not finding.get("uuid"):
                continue
            target_id = ((finding.get("target") or {}).get("target-id")) or ""
            finding_ref = graph.merge_node(
                "Finding",
                {"uuid": finding["uuid"]},
                {
                    "title": finding.get("title", ""),
                    "description": finding.get("description", ""),
                    "target_id": target_id,
                },
            )
            graph.merge_edge(results, "HAS_FINDING", finding_ref, {})
            control_id = target_id.split("_", 1)[0] if target_id else ""
            # Dotted ids such as aia-5.1.a have no underscore suffix. Statement ids do.
            if target_id in by_id:
                control_id = target_id
            catalogs = by_id.get(control_id) or []
            if len(catalogs) == 1:
                graph.merge_edge(
                    finding_ref,
                    "AGAINST",
                    NodeRef.make("Control", {"catalog_uuid": catalogs[0], "control_id": control_id}),
                    {},
                )


def _project_poam(graph: GraphDocument, doc: dict, bundle: dict, layers: dict[str, NodeRef]) -> None:
    body = doc["body"]
    metadata = body.get("metadata") or {}
    poam = graph.merge_node(
        "PlanOfAction",
        {"uuid": body["uuid"]},
        {"title": metadata.get("title", ""), "source_path": doc["path"], "layer": "plan-of-action-and-milestones"},
    )
    _in_layer(graph, poam, "plan-of-action-and-milestones", layers)
    href = (body.get("import-ssp") or {}).get("href", "")
    _link_import(graph, poam, "IMPORTS_SSP", href, doc["path"], bundle, "system-security-plan")
    for risk in body.get("risks") or []:
        if not risk.get("uuid"):
            continue
        graph.merge_node(
            "Risk",
            {"uuid": risk["uuid"]},
            {
                "title": risk.get("title", ""),
                "description": risk.get("description", ""),
                "status": risk.get("status", ""),
            },
        )
    by_id: dict[str, list[str]] = {}
    for item in bundle["controls"]:
        by_id.setdefault(item["control_id"], []).append(item["catalog_uuid"])
    for item in body.get("poam-items") or []:
        if not item.get("uuid"):
            continue
        control_id = _props_map(item.get("props")).get("control-id", "")
        poam_item = graph.merge_node(
            "PoamItem",
            {"uuid": item["uuid"]},
            {
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "control_id": control_id,
            },
        )
        graph.merge_edge(poam, "HAS_ITEM", poam_item, {})
        catalogs = by_id.get(control_id) or []
        if len(catalogs) == 1:
            graph.merge_edge(
                poam_item,
                "ADDRESSES",
                NodeRef.make("Control", {"catalog_uuid": catalogs[0], "control_id": control_id}),
                {},
            )
        for related in item.get("related-risks") or []:
            risk_uuid = related.get("risk-uuid")
            if risk_uuid:
                graph.merge_edge(poam_item, "RELATED_RISK", NodeRef.make("Risk", {"uuid": risk_uuid}), {})
                graph.merge_edge(poam_item, "RELATED_TO_RISK", NodeRef.make("Risk", {"uuid": risk_uuid}), {})


def _project_policies(
    graph: GraphDocument,
    organization: dict,
    policies: list[dict],
    alignments: list[dict],
    layers: dict[str, NodeRef],
) -> None:
    org = NodeRef.make("Organization", {"uuid": organization["uuid"]})
    systems = {
        system["slug"]: system["uuid"]
        for system in organization.get("systems") or []
        if system.get("slug") and system.get("uuid")
    }
    for policy in policies:
        document = graph.merge_node(
            "Document",
            {"sha256": policy["document_sha256"]},
            {"source_path": policy["source_path"], "media_type": "application/pdf"},
        )
        statement = graph.merge_node(
            "PolicyStatement",
            {"policy_id": policy["policy_id"]},
            {
                "title": policy.get("title", ""),
                "owner": policy.get("owner", ""),
                "statement": policy.get("statement", ""),
                "classification": policy.get("classification", ""),
                "source_path": policy["source_path"],
                "layer": "policy",
            },
        )
        _in_layer(graph, statement, "policy", layers)
        graph.merge_edge(document, "CONTAINS_POLICY", statement, {})
        graph.merge_edge(statement, "STATED_IN", document, {})
        graph.merge_edge(org, "OWNS", statement, {})
        for slug in policy.get("applies_to") or []:
            system_uuid = systems.get(slug)
            if system_uuid:
                graph.merge_edge(statement, "APPLIES_TO", NodeRef.make("System", {"uuid": system_uuid}), {})
        for alignment in alignments:
            if alignment["policy_id"] != policy["policy_id"] or alignment["status"] != "matched":
                continue
            graph.merge_edge(
                statement,
                "IMPLEMENTS",
                NodeRef.make(
                    "Control",
                    {"catalog_uuid": alignment["catalog_uuid"], "control_id": alignment["control_id"]},
                ),
                {"method": alignment["method"], "confidence": alignment["confidence"]},
            )


def project_graph(organization: dict, policies: list[dict], alignments: list[dict], bundle: dict) -> GraphDocument:
    graph = GraphDocument()
    layers = _project_ontology(graph)
    _project_org(graph, organization)
    by_model: dict[str, list[dict]] = {}
    for doc in bundle.get("documents") or []:
        by_model.setdefault(doc["model"], []).append(doc)
    for doc in by_model.get("catalog", []):
        controls = [item for item in bundle.get("controls") or [] if item["catalog_uuid"] == doc["uuid"]]
        _project_catalog(graph, doc, controls, layers)
    for doc in by_model.get("profile", []):
        _project_profile(graph, doc, bundle, layers)
    for doc in by_model.get("component-definition", []):
        _project_component_definition(graph, doc, bundle, layers)
    for doc in by_model.get("system-security-plan", []):
        _project_ssp(graph, doc, bundle, layers)
    for doc in by_model.get("assessment-plan", []):
        _project_assessment_plan(graph, doc, bundle, layers)
    for doc in by_model.get("assessment-results", []):
        _project_assessment_results(graph, doc, bundle, layers)
    for doc in by_model.get("plan-of-action-and-milestones", []):
        _project_poam(graph, doc, bundle, layers)
    _project_policies(graph, organization, policies, alignments, layers)
    return graph
