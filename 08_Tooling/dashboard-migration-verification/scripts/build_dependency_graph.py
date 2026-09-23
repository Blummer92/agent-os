from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

try:
    import yaml
except ImportError as exc:  # pragma: no cover - import guard for local setup
    raise SystemExit(
        "PyYAML is required to run this script. Install it with `pip install pyyaml`."
    ) from exc


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT = ROOT / "snapshots" / "latest.json"
DEFAULT_OUTPUT = ROOT / "graph" / "dependency_graph.json"
DEFAULT_CHANGES = ROOT / "proposed_changes" / "proposed_changes.example.yaml"

SECTION_TO_NODE_TYPE = {
    "views": "linked_view",
    "templates": "template",
    "permissions": "permission",
    "automations": "automation",
    "buttons": "button",
}

MISSING_COVERAGE_TYPES = [
    "field",
    "status_value",
    "formula",
    "relation",
    "rollup",
    "linked_view",
    "template",
    "button",
    "automation",
    "permission",
    "documentation_reference",
    "agent_reference",
    "synced_database",
]


@dataclass
class Node:
    id: str
    type: str
    name: str
    dashboard: str
    depends_on: List[str]
    depended_on_by: List[str]
    risk_level: str
    evidence_status: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a dependency graph from dashboard snapshots and proposed changes."
    )
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--changes", type=Path, default=DEFAULT_CHANGES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected YAML mapping at {path}")
    return payload


def make_id(node_type: str, dashboard: str, name: str) -> str:
    safe_dashboard = dashboard.lower().replace(" ", "_")
    safe_name = name.lower().replace(" ", "_")
    return f"{node_type}:{safe_dashboard}:{safe_name}"


def add_node(nodes: Dict[str, Node], node: Node) -> None:
    existing = nodes.get(node.id)
    if existing is None:
        nodes[node.id] = node
        return

    existing.depends_on = sorted(set(existing.depends_on) | set(node.depends_on))
    existing.depended_on_by = sorted(set(existing.depended_on_by) | set(node.depended_on_by))
    existing.risk_level = max_risk(existing.risk_level, node.risk_level)
    existing.evidence_status = max_evidence(existing.evidence_status, node.evidence_status)


def max_risk(left: str, right: str) -> str:
    order = ["low", "medium", "high", "critical"]
    return order[max(order.index(left), order.index(right))]


def max_evidence(left: str, right: str) -> str:
    order = ["verified", "inferred", "stale", "missing", "contradictory"]
    return order[max(order.index(left), order.index(right))]


def ensure_dependency(nodes: Dict[str, Node], source_id: str, target_id: str) -> None:
    if source_id == target_id:
        return
    nodes[source_id].depends_on = sorted(set(nodes[source_id].depends_on) | {target_id})
    nodes[target_id].depended_on_by = sorted(set(nodes[target_id].depended_on_by) | {source_id})


def build_dashboard_root_node(dashboard_key: str, dashboard_snapshot: Mapping[str, Any]) -> Node:
    return Node(
        id=make_id("dashboard", dashboard_key, str(dashboard_snapshot.get("name", dashboard_key))),
        type="dashboard",
        name=str(dashboard_snapshot.get("name", dashboard_key)),
        dashboard=dashboard_key,
        depends_on=[],
        depended_on_by=[],
        risk_level="medium",
        evidence_status="verified",
    )


def extract_field_nodes(
    dashboard_key: str,
    dashboard_snapshot: Mapping[str, Any],
    dashboard_root_id: str,
) -> List[Node]:
    schema = dashboard_snapshot.get("schema", {})
    if not isinstance(schema, Mapping):
        schema = {}
    properties = schema.get("properties", {})
    evidence_status = str(schema.get("evidence_status", "missing"))

    if not isinstance(properties, Mapping) or not properties:
        return [
            Node(
                id=make_id("field", dashboard_key, "unknown_field_inventory"),
                type="field",
                name="Unknown field inventory",
                dashboard=dashboard_key,
                depends_on=[dashboard_root_id],
                depended_on_by=[],
                risk_level="high",
                evidence_status="missing",
            )
        ]

    nodes: List[Node] = []
    for field_name, raw_field in properties.items():
        field_payload = raw_field if isinstance(raw_field, Mapping) else {}
        field_node_id = make_id("field", dashboard_key, str(field_name))
        nodes.append(
            Node(
                id=field_node_id,
                type="field",
                name=str(field_name),
                dashboard=dashboard_key,
                depends_on=[dashboard_root_id],
                depended_on_by=[],
                risk_level="medium",
                evidence_status=evidence_status,
            )
        )

        for status_name in field_payload.get("status_values", []) or []:
            nodes.append(
                Node(
                    id=make_id("status_value", dashboard_key, f"{field_name}:{status_name}"),
                    type="status_value",
                    name=f"{field_name}: {status_name}",
                    dashboard=dashboard_key,
                    depends_on=[field_node_id],
                    depended_on_by=[],
                    risk_level="medium",
                    evidence_status=evidence_status,
                )
            )

        for formula_name in field_payload.get("formula_dependencies", []) or []:
            nodes.append(
                Node(
                    id=make_id("formula", dashboard_key, f"{field_name}:{formula_name}"),
                    type="formula",
                    name=f"{field_name} -> {formula_name}",
                    dashboard=dashboard_key,
                    depends_on=[field_node_id],
                    depended_on_by=[],
                    risk_level="high",
                    evidence_status=evidence_status,
                )
            )

        for relation_name in field_payload.get("relation_targets", []) or []:
            nodes.append(
                Node(
                    id=make_id("relation", dashboard_key, f"{field_name}:{relation_name}"),
                    type="relation",
                    name=f"{field_name} -> {relation_name}",
                    dashboard=dashboard_key,
                    depends_on=[field_node_id],
                    depended_on_by=[],
                    risk_level="high",
                    evidence_status=evidence_status,
                )
            )

        for rollup_name in field_payload.get("rollup_targets", []) or []:
            nodes.append(
                Node(
                    id=make_id("rollup", dashboard_key, f"{field_name}:{rollup_name}"),
                    type="rollup",
                    name=f"{field_name} -> {rollup_name}",
                    dashboard=dashboard_key,
                    depends_on=[field_node_id],
                    depended_on_by=[],
                    risk_level="high",
                    evidence_status=evidence_status,
                )
            )

    return nodes


def extract_section_nodes(
    dashboard_key: str,
    section_name: str,
    section_payload: Any,
    dashboard_root_id: str,
) -> List[Node]:
    node_type = SECTION_TO_NODE_TYPE[section_name]
    if not isinstance(section_payload, Mapping):
        section_payload = {}
    evidence_status = str(section_payload.get("evidence_status", "missing"))
    items = section_payload.get("items", {})

    if not isinstance(items, Mapping) or not items:
        return [
            Node(
                id=make_id(node_type, dashboard_key, f"unknown_{node_type}_inventory"),
                type=node_type,
                name=f"Unknown {node_type.replace('_', ' ')} inventory",
                dashboard=dashboard_key,
                depends_on=[dashboard_root_id],
                depended_on_by=[],
                risk_level="high",
                evidence_status="missing",
            )
        ]

    return [
        Node(
            id=make_id(node_type, dashboard_key, str(item_name)),
            type=node_type,
            name=str(item_name),
            dashboard=dashboard_key,
            depends_on=[dashboard_root_id],
            depended_on_by=[],
            risk_level="medium" if node_type == "permission" else "high",
            evidence_status=evidence_status,
        )
        for item_name in items.keys()
    ]


def add_missing_coverage_nodes(nodes: Dict[str, Node], dashboard_key: str, dashboard_root_id: str) -> None:
    present_types = {node.type for node in nodes.values() if node.dashboard == dashboard_key}
    for node_type in MISSING_COVERAGE_TYPES:
        if node_type in present_types:
            continue
        add_node(
            nodes,
            Node(
                id=make_id(node_type, dashboard_key, f"unknown_{node_type}_inventory"),
                type=node_type,
                name=f"Unknown {node_type.replace('_', ' ')} inventory",
                dashboard=dashboard_key,
                depends_on=[dashboard_root_id],
                depended_on_by=[],
                risk_level="high",
                evidence_status="missing",
            ),
        )


def extract_snapshot_nodes(snapshot: Mapping[str, Any]) -> Dict[str, Node]:
    nodes: Dict[str, Node] = {}
    dashboards = snapshot.get("dashboards", {})
    if not isinstance(dashboards, Mapping):
        raise ValueError("Snapshot JSON must contain a `dashboards` mapping")

    for dashboard_key, raw_dashboard in dashboards.items():
        dashboard_snapshot = raw_dashboard if isinstance(raw_dashboard, Mapping) else {}
        dashboard_root = build_dashboard_root_node(str(dashboard_key), dashboard_snapshot)
        add_node(nodes, dashboard_root)

        for field_node in extract_field_nodes(str(dashboard_key), dashboard_snapshot, dashboard_root.id):
            add_node(nodes, field_node)
            ensure_dependency(nodes, field_node.id, dashboard_root.id)

        for section_name in SECTION_TO_NODE_TYPE:
            for section_node in extract_section_nodes(
                str(dashboard_key),
                section_name,
                dashboard_snapshot.get(section_name, {}),
                dashboard_root.id,
            ):
                add_node(nodes, section_node)
                ensure_dependency(nodes, section_node.id, dashboard_root.id)

        add_missing_coverage_nodes(nodes, str(dashboard_key), dashboard_root.id)

    return nodes


def find_dashboard_keys_by_name(snapshot: Mapping[str, Any], dashboard_name: str) -> List[str]:
    dashboards = snapshot.get("dashboards", {})
    matches: List[str] = []
    for dashboard_key, raw_dashboard in dashboards.items():
        dashboard_snapshot = raw_dashboard if isinstance(raw_dashboard, Mapping) else {}
        if dashboard_snapshot.get("name") == dashboard_name:
            matches.append(str(dashboard_key))
    return matches


def collect_related_nodes(nodes: Mapping[str, Node], dashboard_keys: Iterable[str], item_type: str) -> List[str]:
    item_type_map = {
        "field": ["field", "formula", "relation", "rollup", "status_value"],
        "view": ["linked_view"],
        "database": ["dashboard", "field", "linked_view", "template", "automation", "permission"],
        "status_value": ["status_value", "formula", "linked_view"],
        "linked_view": ["linked_view"],
        "formula_dependency": ["formula"],
        "dependency": ["formula", "relation", "rollup", "automation", "template", "button", "permission"],
    }
    allowed = set(item_type_map.get(item_type, [item_type]))
    return [node.id for node in nodes.values() if node.dashboard in dashboard_keys and node.type in allowed]


def add_change_nodes(nodes: Dict[str, Node], snapshot: Mapping[str, Any], changes_payload: Mapping[str, Any]) -> None:
    changes = changes_payload.get("changes", [])
    if not isinstance(changes, list):
        raise ValueError("Changes manifest must contain a `changes` list")

    for index, raw_change in enumerate(changes, start=1):
        if not isinstance(raw_change, Mapping):
            continue
        source_database = str(raw_change.get("source_database", "unknown"))
        canonical_database = str(raw_change.get("canonical_database", "unknown"))
        item_type = str(raw_change.get("item_type", "dependency"))
        action = str(raw_change.get("action", "unknown_action"))
        source_item = str(raw_change.get("source_item", "unknown_item"))
        dashboard_keys = sorted(
            set(find_dashboard_keys_by_name(snapshot, source_database))
            | set(find_dashboard_keys_by_name(snapshot, canonical_database))
        )
        change_node_id = make_id("proposed_change", "manifest", f"{index}_{action}_{source_item}")
        related_nodes = collect_related_nodes(nodes, dashboard_keys, item_type)
        change_node = Node(
            id=change_node_id,
            type="proposed_change",
            name=f"{action}: {source_item}",
            dashboard=source_database,
            depends_on=sorted(set(related_nodes)),
            depended_on_by=[],
            risk_level="medium" if related_nodes else "high",
            evidence_status="verified" if related_nodes else "missing",
        )
        add_node(nodes, change_node)
        for related_node_id in related_nodes:
            ensure_dependency(nodes, change_node_id, related_node_id)


def serialise_graph(snapshot: Mapping[str, Any], changes_path: Path, nodes: Mapping[str, Node]) -> Dict[str, Any]:
    return {
        "generated_at": snapshot.get("generated_at"),
        "changes_path": str(changes_path),
        "nodes": [asdict(node) for node in sorted(nodes.values(), key=lambda node: node.id)],
    }


def write_graph(graph: Mapping[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(graph, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    args = parse_args()
    snapshot = load_json(args.snapshot)
    changes_payload = load_yaml(args.changes)
    nodes = extract_snapshot_nodes(snapshot)
    add_change_nodes(nodes, snapshot, changes_payload)
    graph = serialise_graph(snapshot, args.changes, nodes)
    write_graph(graph, args.output)
    print(f"Wrote dependency graph to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
