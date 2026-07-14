#!/usr/bin/env python3
"""Validate dashboard migration proposals conservatively."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from dashboard_migration_common import (
    DESTRUCTIVE_ACTIONS,
    REPORT_SECTIONS,
    TOOL_ROOT,
    change_id,
    load_changes,
    load_json,
    migration_status_for_action,
    write_json,
)


def validate_changes(
    changes_path: Path,
    snapshot_path: Path | None = None,
    graph_path: Path | None = None,
) -> dict[str, Any]:
    snapshot_path = snapshot_path or TOOL_ROOT / "snapshots" / "latest.json"
    graph_path = graph_path or TOOL_ROOT / "graph" / "dependency_graph.json"
    manifest = load_changes(changes_path)
    snapshot = load_json(snapshot_path, default={}) or {}
    graph = load_json(graph_path, default={}) or {}

    placeholder = bool(snapshot.get("placeholder", True))
    graph_nodes = graph.get("nodes", [])
    missing_nodes = [node for node in graph_nodes if node.get("evidence_status") == "missing"]

    results = []
    for change in manifest.get("changes", []):
        result = classify_change(change, placeholder, missing_nodes)
        results.append(result)

    output = {
        "changes_path": str(changes_path),
        "snapshot_path": str(snapshot_path),
        "graph_path": str(graph_path),
        "results": results,
        "final_decision": final_decision(results),
    }
    return output


def classify_change(change: dict[str, Any], placeholder: bool, missing_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    action = str(change.get("action", "unknown"))
    blockers: list[str] = []
    review_reasons: list[str] = []

    if placeholder:
        blockers.append("Snapshot evidence is placeholder-only and not proof.")
    if missing_nodes:
        blockers.append("Dependency evidence contains missing nodes.")
    if action in DESTRUCTIVE_ACTIONS and (placeholder or missing_nodes):
        blockers.append("Destructive action cannot be approved with unknown dependencies.")

    if blockers:
        classification = "Blocked by missing information"
    elif change.get("approval_required", True):
        classification = "Requires manual review"
        review_reasons.append("Human approval required by manifest.")
    else:
        classification = "Safe to automate"

    if placeholder:
        review_reasons.append("Refresh live evidence before any governed write.")
    if missing_nodes:
        review_reasons.append("Resolve missing dependency graph coverage.")

    return {
        "change_id": change_id(change),
        "action": action,
        "item_type": change.get("item_type", "unknown"),
        "source_database": change.get("source_database", ""),
        "source_item": change.get("source_item", ""),
        "canonical_database": change.get("canonical_database", ""),
        "canonical_item": change.get("canonical_item", ""),
        "classification": classification,
        "migration_status": migration_status_for_action(action),
        "risk_ratings": {
            "data_integrity": "high" if blockers else "medium",
            "dependency": "high" if missing_nodes else "medium",
            "rollback": "medium",
        },
        "blockers": blockers,
        "review_reasons": review_reasons,
    }


def final_decision(results: list[dict[str, Any]]) -> str:
    if any(result["classification"] == "Blocked by missing information" for result in results):
        return "Do Not Retire Yet"
    if any(result["classification"] == "Requires manual review" for result in results):
        return "Ready After Migration"
    return "Ready for Retirement"


def render_report(validation: dict[str, Any]) -> str:
    rows = validation.get("results", [])
    readiness_rows = [
        "| Change | Classification | Migration Status |",
        "|---|---|---|",
    ]
    for row in rows:
        readiness_rows.append(
            f"| {row['change_id']} | {row['classification']} | {row['migration_status']} |"
        )

    blockers = [blocker for row in rows for blocker in row.get("blockers", [])]
    must_not_retire = [row["change_id"] for row in rows if row.get("blockers")]

    report = "\n\n".join(
        [
            REPORT_SECTIONS[0] + "\n\n" + f"Reviewed {len(rows)} proposed change(s).",
            REPORT_SECTIONS[1] + "\n\n" + "\n".join(readiness_rows),
            REPORT_SECTIONS[2] + "\n\n" + ("Blockers present." if blockers else "No blockers detected."),
            REPORT_SECTIONS[3] + "\n\n" + ("\n".join(f"- {item}" for item in blockers) or "No unresolved dependency blockers."),
            REPORT_SECTIONS[4] + "\n\nResolve blockers before any live migration.",
            REPORT_SECTIONS[5] + "\n\nNo retirement order approved by this verification run.",
            REPORT_SECTIONS[6] + "\n\n" + ("\n".join(f"- {item}" for item in must_not_retire) or "None."),
            REPORT_SECTIONS[7] + "\n\n" + validation["final_decision"],
        ]
    )
    return report + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--changes", required=True, help="Path to proposed changes YAML or JSON.")
    parser.add_argument("--snapshot", default=None, help="Optional snapshot path.")
    parser.add_argument("--graph", default=None, help="Optional dependency graph path.")
    args = parser.parse_args()

    validation = validate_changes(
        Path(args.changes),
        Path(args.snapshot) if args.snapshot else None,
        Path(args.graph) if args.graph else None,
    )
    write_json(TOOL_ROOT / "validation" / "validation_results.json", validation)
    report = render_report(validation)
    report_path = TOOL_ROOT / "validation" / "validation_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"Wrote validation results: {TOOL_ROOT / 'validation' / 'validation_results.json'}")
    print(f"Wrote validation report: {report_path}")
    print("Live mutations: none")


if __name__ == "__main__":
    main()
