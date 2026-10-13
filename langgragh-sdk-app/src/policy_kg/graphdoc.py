"""In-memory knowledge graph used before, and alongside, Neo4j."""

from __future__ import annotations

from dataclasses import dataclass

LABELS = (
    "Organization",
    "System",
    "Document",
    "PolicyStatement",
    "Catalog",
    "ControlGroup",
    "Control",
    "ControlPart",
    "Parameter",
    "Profile",
    "Component",
    "ComponentDefinition",
    "SystemSecurityPlan",
    "ImplementedRequirement",
    "AssessmentPlan",
    "AssessmentTask",
    "AssessmentResults",
    "Finding",
    "PlanOfAction",
    "PoamItem",
    "Risk",
    "Party",
    "Role",
    "User",
    "FrameworkSource",
    "Ontology",
    "Layer",
)

REL_TYPES = (
    "OPERATES",
    "OWNS",
    "CONTAINS_POLICY",
    "APPLIES_TO",
    "IMPLEMENTS",
    "HAS_GROUP",
    "HAS_CONTROL",
    "HAS_PART",
    "HAS_PARAMETER",
    "IN_CATALOG",
    "CHILD_OF",
    "IMPORTS",
    "SELECTS",
    "SETS_PARAMETER",
    "DESCRIBES",
    "HAS_COMPONENT",
    "HAS_REQUIREMENT",
    "SATISFIES",
    "DEFINES",
    "IMPORTS_PROFILE",
    "IMPORTS_SSP",
    "IMPORTS_AP",
    "REVIEWS",
    "HAS_TASK",
    "HAS_RESULT",
    "HAS_FINDING",
    "AGAINST",
    "HAS_ITEM",
    "ADDRESSES",
    "RELATED_RISK",
    "PERFORMS",
    "OVERSEES",
    "STATED_IN",
    "DEFINED_BY",
    "ACCOUNTABLE",
    "HAS_LAYER",
    "IN_LAYER",
    "FOLLOWS",
    "HAS_ROLE",
    "HAS_PARTY",
    "RESPONSIBLE_PARTY",
    "REVIEWED_CONTROL",
    "RELATED_TO_RISK",
)

KEY_FIELDS: dict[str, tuple[str, ...]] = {
    "Organization": ("uuid",),
    "System": ("uuid",),
    "Document": ("sha256",),
    "PolicyStatement": ("policy_id",),
    "Catalog": ("uuid",),
    "ControlGroup": ("catalog_uuid", "group_id"),
    "Control": ("catalog_uuid", "control_id"),
    "ControlPart": ("catalog_uuid", "part_id"),
    "Parameter": ("catalog_uuid", "param_id"),
    "Profile": ("uuid",),
    "Component": ("uuid",),
    "ComponentDefinition": ("uuid",),
    "SystemSecurityPlan": ("uuid",),
    "ImplementedRequirement": ("uuid",),
    "AssessmentPlan": ("uuid",),
    "AssessmentTask": ("uuid",),
    "AssessmentResults": ("uuid",),
    "Finding": ("uuid",),
    "PlanOfAction": ("uuid",),
    "PoamItem": ("uuid",),
    "Risk": ("uuid",),
    "Party": ("uuid",),
    "Role": ("role_id",),
    "User": ("uuid",),
    "FrameworkSource": ("framework_id",),
    "Ontology": ("uuid",),
    "Layer": ("layer_id",),
}


@dataclass(frozen=True)
class NodeRef:
    label: str
    keys: tuple[tuple[str, str], ...]

    @classmethod
    def make(cls, label: str, keys: dict[str, object]) -> NodeRef:
        if label not in KEY_FIELDS:
            raise KeyError(f"unknown label {label}")
        fields = KEY_FIELDS[label]
        missing = [field for field in fields if keys.get(field) in (None, "")]
        if missing:
            raise KeyError(f"{label} missing key {missing}")
        material = tuple((field, str(keys[field])) for field in fields)
        return cls(label, material)

    def as_dict(self) -> dict[str, str]:
        return dict(self.keys)


class GraphDocument:
    def __init__(self) -> None:
        self.nodes: dict[NodeRef, dict[str, object]] = {}
        self.edges: dict[tuple[NodeRef, str, NodeRef], dict[str, object]] = {}

    def merge_node(self, label: str, keys: dict[str, object], props: dict[str, object] | None = None) -> NodeRef:
        ref = NodeRef.make(label, keys)
        stored = dict(props or {})
        stored.update(ref.as_dict())
        current = self.nodes.get(ref)
        if current is None:
            self.nodes[ref] = stored
        else:
            current.update(stored)
        return ref

    def merge_edge(
        self,
        src: NodeRef,
        rel: str,
        dst: NodeRef,
        props: dict[str, object] | None = None,
    ) -> None:
        if rel not in REL_TYPES:
            raise KeyError(f"unknown relationship {rel}")
        if src not in self.nodes or dst not in self.nodes:
            raise KeyError(f"missing endpoint for {src.label}-[{rel}]->{dst.label}")
        identity = (src, rel, dst)
        current = self.edges.get(identity)
        if current is None:
            self.edges[identity] = dict(props or {})
        else:
            current.update(props or {})

    def nodes_by_label(self, label: str) -> list[tuple[NodeRef, dict[str, object]]]:
        return [(ref, props) for ref, props in self.nodes.items() if ref.label == label]

    def edges_of_type(self, rel: str) -> list[tuple[NodeRef, NodeRef, dict[str, object]]]:
        return [(src, dst, props) for (src, kind, dst), props in self.edges.items() if kind == rel]

    def outgoing(self, src: NodeRef, rel: str) -> list[tuple[NodeRef, dict[str, object]]]:
        return [(dst, props) for (edge_src, kind, dst), props in self.edges.items() if edge_src == src and kind == rel]

    def incoming(self, dst: NodeRef, rel: str) -> list[tuple[NodeRef, dict[str, object]]]:
        return [(src, props) for (src, kind, edge_dst), props in self.edges.items() if edge_dst == dst and kind == rel]

    def summary(self) -> dict[str, dict[str, int]]:
        labels: dict[str, int] = {}
        for ref in self.nodes:
            labels[ref.label] = labels.get(ref.label, 0) + 1
        rels: dict[str, int] = {}
        for (_src, rel, _dst) in self.edges:
            rels[rel] = rels.get(rel, 0) + 1
        return {"nodes": labels, "relationships": rels}
