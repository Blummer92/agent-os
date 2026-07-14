#!/usr/bin/env python3
"""Build a conservative local dependency graph for dashboard migration proposals."""

from __future__ import annotations

import argparse
from pathlib import Path

from dashboard_migration_common import TOOL_ROOT, change_id, load_changes, load_json, write_json

UNKNOWN_DEPENDENCY_TYPES = [
    "records",
    "fields",
    "formulas",
    "relations",
    "rollups",
    "linked_views",
    "templates",
    "buttons",
    "automations",
    "permissions",
    "documentation_references",
    "agent_references",
    "synced_databases",
]


def build_graph(changes_path: Path, snapshot_path: Path | None = None) -> dict:
    snapshot_path = snapshot_path or TOOL_ROOT / "snapshots" / "latest.json"
    snapshot = load_json(snapshot_path, default={}) or {}
    manifest = load_changes(changes_path)
    nodes = []
    edges = []

    placeholder = bool(snapshot.get("placeholder", True))
    snapshot_status = "missing" if placeholder else snapshot.get("evidence_status", "inferred")

    for change in manifest.get("changes", []):
        cid = change_id(change)
        source_node = f"{cid}::source"
        canonical_node = f"{cid}::canonical"
        nodes.append({
            "id": source_node,
            "type": change.get("item_type", "unknown"),
            "name": change.get("source_item", "Unknown source item"),
            "dashboard": change.get("source_database", "Unknown source dashboard"),
            "depends_on": [f"{cid}::{dep}" for dep in UNKNOWN_DEPENDENCY_TYPES],
            "depended_on_by": [],
            "risk_level": "high" if placeholder else "medium",
            "evidence_status": snapshot_status,
        })
        nodes.append({
            "id": canonical_node,
            "type": "canonical_target",
            "name": change.get("canonical_item", "Unknown canonical item"),
            "dashboard": change.get("canonical_database", "Unknown canonical dashboard"),
            "depends_on": [],
            "depended_on_by": [source_node],
            "risk_level": "medium" if placeholder else "low",
            "evidence_status": snapshot_status,
        })
        edges.append({"from": source_node, "to": canonical_node, "type": "proposed_migration"})
        for dep in UNKNOWN_DEPENDENCY_TYPES:
            dep_node = f"{cid}::{dep}"
            nodes.append({
                "id": dep_node,
                "type": dep,
                "name": dep.replace("_", " "),
                "dashboard": change.get("source_database", "Unknown source dashboard"),
                "depends_on": [],
                "depended_on_by": [source_node],
                "risk_level": "high",
                "evidence_status": "missing" if placeholder else "inferred",
            })
            edges.append({"from": source_node, "to": dep_node, "type": "unknown_dependency"})

    return {
        "generated_from": {
            "changes": str(changes_path),
            "snapshot": str(snapshot_path),
        },
        "placeholder_snapshot": placeholder,
        "nodes": nodes,
        "edges": edges,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--changes", required=True, help="Path to proposed changes YAML or JSON.")
    parser.add_argument("--snapshot", default=None, help="Optional snapshot path.")
    args = parser.parse_args()

    graph = build_graph(Path(args.changes), Path(args.snapshot) if args.snapshot else None)
    output_path = TOOL_ROOT / "graph" / "dependency_graph.json"
    write_json(output_path, graph)
    print(f"Wrote dependency graph: {output_path}")
    print("Live mutations: none")


if __name__ == "__main__":
    main()
