"""Load OSCAL JSON catalogs, profiles, and implementation/assessment models."""

from __future__ import annotations

import json
from pathlib import Path

MODEL_ROOTS = (
    "catalog",
    "profile",
    "component-definition",
    "system-security-plan",
    "assessment-plan",
    "assessment-results",
    "plan-of-action-and-milestones",
)

METADATA_FIELDS = ("title", "last-modified", "version", "oscal-version")


def _read_json(path: Path) -> tuple[dict | None, dict | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, {
            "code": "invalid-oscal",
            "severity": "error",
            "subject": str(path),
            "message": f"JSON parse error: {exc}",
        }
    if not isinstance(payload, dict):
        return None, {
            "code": "invalid-oscal",
            "severity": "error",
            "subject": str(path),
            "message": "OSCAL root must be an object",
        }
    return payload, None


def _model_of(payload: dict) -> str | None:
    found = [key for key in MODEL_ROOTS if key in payload]
    if len(found) == 1:
        return found[0]
    return None


def _metadata_errors(body: dict, path: Path) -> list[dict[str, str]]:
    metadata = body.get("metadata")
    if not isinstance(metadata, dict):
        return [
            {
                "code": "invalid-oscal",
                "severity": "error",
                "subject": str(path),
                "message": "metadata is required",
            }
        ]
    errors = []
    for field in METADATA_FIELDS:
        if not metadata.get(field):
            errors.append(
                {
                    "code": "invalid-oscal",
                    "severity": "error",
                    "subject": str(path),
                    "message": f"metadata.{field} is required",
                }
            )
    if not body.get("uuid"):
        errors.append(
            {
                "code": "invalid-oscal",
                "severity": "error",
                "subject": str(path),
                "message": "uuid is required",
            }
        )
    return errors


def walk_controls(catalog_body: dict) -> list[dict[str, object]]:
    """Flatten nested groups and nested controls. Group ids keep dotted control ids intact."""
    found: list[dict[str, object]] = []

    def walk_control(control: dict, groups: list[dict], parent_id: str | None) -> None:
        found.append({"groups": list(groups), "control": control, "parent_control_id": parent_id})
        for child in control.get("controls") or []:
            walk_control(child, groups, control.get("id"))

    def walk_group(group: dict, ancestors: list[dict]) -> None:
        here = [*ancestors, group]
        for control in group.get("controls") or []:
            walk_control(control, here, None)
        for child in group.get("groups") or []:
            walk_group(child, here)

    for group in catalog_body.get("groups") or []:
        walk_group(group, [])
    for control in catalog_body.get("controls") or []:
        walk_control(control, [], None)
    return found


def _count_controls(body: dict) -> int:
    return len(walk_controls(body))


def _statement_of(control: dict) -> str:
    parts = []
    for part in control.get("parts") or []:
        if part.get("name") == "statement" and part.get("prose"):
            parts.append(str(part["prose"]))
    return " ".join(parts)


def _prop(props: list | None, name: str) -> str:
    for item in props or []:
        if item.get("name") == name and item.get("value") is not None:
            return str(item["value"])
    return ""


def _collect_files(dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for directory in dirs:
        if not directory.exists():
            continue
        files.extend(path for path in directory.rglob("*.json") if path.is_file())
    return sorted(files)


def _prefer(current: dict, candidate: dict) -> dict:
    if current["model"] == "catalog" and candidate["model"] == "catalog":
        current_count = _count_controls(current["body"])
        candidate_count = _count_controls(candidate["body"])
        if candidate_count > current_count:
            return candidate
        if candidate_count == current_count and candidate["path"] >= current["path"]:
            return candidate
        return current
    if candidate["path"] >= current["path"]:
        return candidate
    return current


def _resolve_href(source: Path, href: str, by_uuid: dict[str, dict], by_path: dict[str, dict]) -> dict | None:
    if not href:
        return None
    if href.startswith("#"):
        resource_uuid = href[1:]
        owner = by_path.get(str(source.resolve()))
        resources = ((owner or {}).get("body") or {}).get("back-matter", {}).get("resources") or []
        for resource in resources:
            if resource.get("uuid") != resource_uuid:
                continue
            for link in resource.get("rlinks") or []:
                if link.get("href"):
                    return _resolve_href(source, link["href"], by_uuid, by_path)
        return by_uuid.get(resource_uuid)
    target = (source.parent / href).resolve()
    return by_path.get(str(target))


def _index_controls(documents: list[dict]) -> list[dict[str, object]]:
    controls: list[dict[str, object]] = []
    for doc in documents:
        if doc["model"] != "catalog":
            continue
        body = doc["body"]
        framework_id = _prop(body.get("metadata", {}).get("props"), "framework-id")
        for item in walk_controls(body):
            control = item["control"]
            groups = item["groups"]
            controls.append(
                {
                    "catalog_uuid": body.get("uuid"),
                    "catalog_title": body.get("metadata", {}).get("title", ""),
                    "framework_id": framework_id,
                    "source_path": doc["path"],
                    "group_ids": [group.get("id", "") for group in groups],
                    "group_titles": [group.get("title", "") for group in groups],
                    "parent_control_id": item["parent_control_id"],
                    "control_id": control.get("id", ""),
                    "title": control.get("title", ""),
                    "class": control.get("class", ""),
                    "statement": _statement_of(control),
                    "control": control,
                }
            )
    return controls


def _selections(documents: list[dict], by_path: dict[str, dict], by_uuid: dict[str, dict]) -> list[dict[str, object]]:
    selections: list[dict[str, object]] = []
    control_ids_by_catalog = {}
    for doc in documents:
        if doc["model"] != "catalog":
            continue
        control_ids_by_catalog[doc["body"]["uuid"]] = {
            item["control"].get("id", "") for item in walk_controls(doc["body"])
        }
    for doc in documents:
        if doc["model"] != "profile":
            continue
        profile = doc["body"]
        for imported in profile.get("imports") or []:
            href = imported.get("href", "")
            target = _resolve_href(Path(doc["path"]), href, by_uuid, by_path)
            catalog_uuid = target["body"].get("uuid") if target and target["model"] == "catalog" else None
            known = control_ids_by_catalog.get(catalog_uuid, set())
            includes = imported.get("include-controls") or []
            if not includes:
                for control_id in sorted(known):
                    selections.append(
                        {
                            "profile_uuid": profile.get("uuid"),
                            "catalog_uuid": catalog_uuid,
                            "href": href,
                            "control_id": control_id,
                            "found": True,
                        }
                    )
                if target is None:
                    selections.append(
                        {
                            "profile_uuid": profile.get("uuid"),
                            "catalog_uuid": None,
                            "href": href,
                            "control_id": "*",
                            "found": False,
                        }
                    )
                continue
            for include in includes:
                for control_id in include.get("with-ids") or []:
                    selections.append(
                        {
                            "profile_uuid": profile.get("uuid"),
                            "catalog_uuid": catalog_uuid,
                            "href": href,
                            "control_id": control_id,
                            "found": bool(catalog_uuid) and control_id in known,
                        }
                    )
    return selections


def _parameter_sets(documents: list[dict], controls: list[dict]) -> list[dict[str, object]]:
    params_by_id: dict[str, list[str]] = {}
    for item in controls:
        for param in item["control"].get("params") or []:
            params_by_id.setdefault(param.get("id", ""), []).append(item["catalog_uuid"])
    sets: list[dict[str, object]] = []
    for doc in documents:
        if doc["model"] != "profile":
            continue
        for setting in (doc["body"].get("modify") or {}).get("set-parameters") or []:
            param_id = setting.get("param-id", "")
            catalogs = params_by_id.get(param_id) or []
            sets.append(
                {
                    "profile_uuid": doc["body"].get("uuid"),
                    "param_id": param_id,
                    "catalog_uuid": catalogs[0] if len(catalogs) == 1 else None,
                    "values": setting.get("values") or [],
                    "found": len(catalogs) == 1,
                    "ambiguous": len(catalogs) > 1,
                }
            )
    return sets


def load_oscal_dirs(dirs: list[Path]) -> dict[str, object]:
    errors: list[dict[str, str]] = []
    parsed: list[dict] = []
    for path in _collect_files(dirs):
        payload, error = _read_json(path)
        if error:
            errors.append(error)
            continue
        assert payload is not None
        model = _model_of(payload)
        if model is None:
            errors.append(
                {
                    "code": "unknown-oscal-model",
                    "severity": "error",
                    "subject": str(path),
                    "message": "JSON is not an OSCAL catalog, profile, component-definition, SSP, assessment-plan, assessment-results, or POA&M",
                }
            )
            continue
        body = payload[model]
        if not isinstance(body, dict):
            errors.append(
                {
                    "code": "invalid-oscal",
                    "severity": "error",
                    "subject": str(path),
                    "message": f"{model} must be an object",
                }
            )
            continue
        errors.extend(_metadata_errors(body, path))
        parsed.append(
            {
                "model": model,
                "path": str(path.resolve()),
                "uuid": body.get("uuid", ""),
                "title": (body.get("metadata") or {}).get("title", ""),
                "body": body,
            }
        )

    chosen: dict[tuple[str, str], dict] = {}
    for doc in parsed:
        identity = (doc["model"], doc["uuid"])
        current = chosen.get(identity)
        chosen[identity] = doc if current is None else _prefer(current, doc)
    documents = list(chosen.values())
    by_uuid = {doc["uuid"]: doc for doc in documents if doc["uuid"]}
    by_path = {doc["path"]: doc for doc in documents}
    controls = _index_controls(documents)
    selections = _selections(documents, by_path, by_uuid)
    for selection in selections:
        if not selection["found"]:
            errors.append(
                {
                    "code": "unresolved-import" if not selection["catalog_uuid"] else "unknown-control",
                    "severity": "error",
                    "subject": f"{selection['profile_uuid']}:{selection['control_id']}",
                    "message": f"Profile import {selection['href']} did not resolve control {selection['control_id']}",
                }
            )
    return {
        "documents": documents,
        "controls": controls,
        "selections": selections,
        "parameter_sets": _parameter_sets(documents, controls),
        "errors": errors,
    }
