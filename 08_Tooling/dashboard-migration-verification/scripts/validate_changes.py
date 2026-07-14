from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

try:
    import yaml
except ImportError as exc:  # pragma: no cover - import guard for local setup
    raise SystemExit(
        "PyYAML is required to run this script. Install it with `pip install pyyaml`."
    ) from exc


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "dashboards.yaml"
DEFAULT_SNAPSHOT = ROOT / "snapshots" / "latest.json"
DEFAULT_GRAPH = ROOT / "graph" / "dependency_graph.json"
DEFAULT_CHANGES = ROOT / "proposed_changes" / "proposed_changes.example.yaml"
DEFAULT_RESULTS = ROOT / "validation" / "validation_results.json"
DEFAULT_REPORT = ROOT / "validation" / "validation_report.md"
DEFAULT_TEMPLATE = ROOT / "templates" / "validation_report.md"

RETIREMENT_ACTIONS = {"archive_view", "archive_database", "merge_database"}
ACTIVE_WORKFLOW_TYPES = {
    "automation",
    "button",
    "template",
    "documentation_reference",
    "agent_reference",
    "synced_database",
    "permission",
}
DEPENDENCY_TYPES = {
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
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate dashboard migration proposals against local evidence files."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--changes", type=Path, default=DEFAULT_CHANGES)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    return parser.parse_args()


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected YAML mapping at {path}")
    return payload


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def build_registry_name_index(registry_payload: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    dashboards = registry_payload.get("dashboards", {})
    if not isinstance(dashboards, Mapping):
        raise ValueError("dashboards.yaml must contain a top-level `dashboards` mapping")
    return {
        str(entry.get("name", key)): {"key": str(key), **entry}
        for key, entry in dashboards.items()
        if isinstance(entry, Mapping)
    }


def get_snapshot_by_name(snapshot_payload: Mapping[str, Any], dashboard_name: str) -> Tuple[str | None, Dict[str, Any] | None]:
    dashboards = snapshot_payload.get("dashboards", {})
    if not isinstance(dashboards, Mapping):
        return None, None
    for dashboard_key, raw in dashboards.items():
        if isinstance(raw, Mapping) and raw.get("name") == dashboard_name:
            return str(dashboard_key), dict(raw)
    return None, None


def get_graph_nodes_by_dashboard(graph_payload: Mapping[str, Any], dashboard_keys: Iterable[str]) -> List[Dict[str, Any]]:
    wanted = set(dashboard_keys)
    nodes = graph_payload.get("nodes", [])
    if not isinstance(nodes, list):
        return []
    return [node for node in nodes if isinstance(node, dict) and str(node.get("dashboard")) in wanted]


def get_records_verified(snapshot_entry: Mapping[str, Any] | None) -> bool:
    if not snapshot_entry:
        return False
    summary = snapshot_entry.get("records_summary", {})
    if not isinstance(summary, Mapping):
        return False
    return bool(summary.get("unique_records_verified", False))


def determine_migration_status(change: Mapping[str, Any], blockers: List[str], review_reasons: List[str]) -> str:
    action = str(change.get("action", ""))
    if blockers:
        return "Requires Manual Review" if action not in RETIREMENT_ACTIONS else "Requires Dependency Cleanup"
    if action in {"rename_field", "merge_field", "rename_status_value", "normalize_status_vocabulary", "update_formula_dependency"}:
        return "Requires Field Migration"
    if action in {"archive_view", "update_linked_view"}:
        return "Requires View Migration"
    if action == "merge_database":
        return "Requires Record Migration"
    if action == "archive_database":
        return "Safe to Retire" if not review_reasons else "Requires Record Migration"
    if action == "dependency_cleanup":
        return "Requires Dependency Cleanup"
    return "Requires Manual Review"


def risk_level(score: int) -> str:
    if score >= 4:
        return "Critical"
    if score == 3:
        return "High"
    if score == 2:
        return "Medium"
    return "Low"


def compute_risk_ratings(
    change: Mapping[str, Any],
    blockers: List[str],
    review_reasons: List[str],
    unresolved_nodes: List[Mapping[str, Any]],
) -> Dict[str, str]:
    action = str(change.get("action", ""))
    unresolved_dependency_count = sum(
        1
        for node in unresolved_nodes
        if str(node.get("type")) in DEPENDENCY_TYPES
    )
    active_workflow_count = sum(
        1
        for node in unresolved_nodes
        if str(node.get("type")) in ACTIVE_WORKFLOW_TYPES
    )

    return {
        "Data Loss": risk_level((1 if action in {"merge_field", "merge_database", "archive_database"} else 0) + (2 if blockers else 0)),
        "Workflow Risk": risk_level((1 if review_reasons else 0) + (2 if active_workflow_count else 0)),
        "Sync Risk": risk_level(2 if any(str(node.get("type")) == "synced_database" for node in unresolved_nodes) else 1 if action == "merge_database" else 0),
        "Navigation Risk": risk_level(2 if action in {"archive_view", "archive_database", "update_linked_view"} else 1 if review_reasons else 0),
        "Dependency Risk": risk_level(min(4, unresolved_dependency_count if unresolved_dependency_count else (2 if blockers else 0))),
    }


def evaluate_change(
    change: Mapping[str, Any],
    registry_by_name: Mapping[str, Dict[str, Any]],
    snapshot_payload: Mapping[str, Any],
    graph_payload: Mapping[str, Any],
) -> Dict[str, Any]:
    source_database = str(change.get("source_database", ""))
    canonical_database = str(change.get("canonical_database", ""))
    action = str(change.get("action", ""))
    approval_required = bool(change.get("approval_required", False))

    blockers: List[str] = []
    review_reasons: List[str] = []

    source_registry = registry_by_name.get(source_database)
    canonical_registry = registry_by_name.get(canonical_database)

    if source_registry is None:
        blockers.append("Source dashboard is not present in the local dashboard registry.")
    if canonical_registry is None:
        blockers.append("Canonical dashboard is not present in the local dashboard registry.")

    source_key, source_snapshot = get_snapshot_by_name(snapshot_payload, source_database)
    canonical_key, canonical_snapshot = get_snapshot_by_name(snapshot_payload, canonical_database)

    if source_snapshot is None:
        blockers.append("Source dashboard is missing from the latest local snapshot.")
    if canonical_snapshot is None:
        blockers.append("Canonical dashboard is missing from the latest local snapshot.")

    dashboard_keys = [key for key in [source_key, canonical_key] if key]
    graph_nodes = get_graph_nodes_by_dashboard(graph_payload, dashboard_keys)
    unresolved_nodes = [
        node
        for node in graph_nodes
        if str(node.get("evidence_status", "missing")) in {"missing", "stale", "contradictory"}
    ]

    if not graph_nodes:
        blockers.append("No dependency evidence was found for the impacted dashboards.")
    if unresolved_nodes:
        blockers.append("Dependencies remain missing, stale, or contradictory in the local graph.")

    if action in RETIREMENT_ACTIONS and not get_records_verified(source_snapshot):
        blockers.append("Unique records have not been verified for the retirement target.")

    if any(str(node.get("type")) in ACTIVE_WORKFLOW_TYPES for node in unresolved_nodes):
        blockers.append("Active workflows, templates, permissions, syncs, or automation references remain unresolved.")

    if source_registry and not bool(source_registry.get("retirement_allowed", False)) and action in RETIREMENT_ACTIONS:
        review_reasons.append("The dashboard registry does not currently allow retirement for this source dashboard.")

    if approval_required or bool((source_registry or {}).get("human_approval_required", True)):
        review_reasons.append("Human approval is required before any migration recommendation can be treated as executable.")

    if source_database == canonical_database and action in {"merge_field", "merge_database"}:
        review_reasons.append("Merge actions on similarly named sources still require explicit evidence of equivalence.")

    classification = (
        "Blocked by missing information"
        if blockers
        else "Requires manual review"
        if review_reasons
        else "Safe to automate"
    )
    migration_status = determine_migration_status(change, blockers, review_reasons)
    risks = compute_risk_ratings(change, blockers, review_reasons, unresolved_nodes)

    return {
        "action": action,
        "item_type": change.get("item_type"),
        "source_database": source_database,
        "source_item": change.get("source_item"),
        "canonical_database": canonical_database,
        "canonical_item": change.get("canonical_item"),
        "classification": classification,
        "migration_status": migration_status,
        "risk_ratings": risks,
        "blockers": blockers,
        "review_reasons": review_reasons,
        "notes": change.get("notes", ""),
    }


def render_table(rows: List[Mapping[str, Any]]) -> str:
    lines = [
        "| Action | Source | Classification | Migration status |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['action']} | {row['source_database']} / {row['source_item']} | {row['classification']} | {row['migration_status']} |"
        )
    return "\n".join(lines)


def render_list(items: Iterable[str], empty_message: str) -> str:
    values = [item for item in items if item]
    if not values:
        return f"- {empty_message}"
    return "\n".join(f"- {item}" for item in values)


def determine_final_decision(results: List[Mapping[str, Any]]) -> str:
    if any(result["classification"] == "Blocked by missing information" for result in results):
        return "Do Not Retire Yet"
    if any(result["migration_status"] != "Safe to Retire" for result in results):
        return "Ready After Migration"
    return "Ready for Retirement"


def render_report(
    template_text: str,
    results: List[Mapping[str, Any]],
    final_decision: str,
) -> str:
    classifications = Counter(result["classification"] for result in results)
    executive_summary = (
        f"Reviewed {len(results)} proposed changes. "
        f"Blocked: {classifications.get('Blocked by missing information', 0)}. "
        f"Manual review: {classifications.get('Requires manual review', 0)}. "
        f"Safe to automate: {classifications.get('Safe to automate', 0)}."
    )

    data_integrity_review = render_list(
        [
            f"{result['source_database']} / {result['source_item']}: unique record verification is required before retirement actions when evidence is missing."
            for result in results
            if result["classification"] != "Safe to automate"
        ],
        "No additional data integrity warnings were raised.",
    )

    dependency_review = render_list(
        [
            f"{result['source_database']} / {result['source_item']}: {'; '.join(result['blockers'])}"
            for result in results
            if result["blockers"]
        ],
        "No unresolved dependency blockers were raised.",
    )

    migration_tasks = render_list(
        [
            f"{result['source_database']} / {result['source_item']}: resolve blockers and review items before treating this change as migration-ready."
            for result in results
            if result["classification"] != "Safe to automate"
        ],
        "No additional migration tasks are required.",
    )

    retirement_order = render_list(
        [
            f"{result['source_database']} / {result['source_item']}"
            for result in results
            if result["migration_status"] == "Safe to Retire"
        ],
        "No dashboard surfaces are ready for retirement ordering yet.",
    )

    must_not_retire = render_list(
        [
            f"{result['source_database']} / {result['source_item']}"
            for result in results
            if result["classification"] != "Safe to automate"
        ],
        "No protected retirement blockers were identified.",
    )

    replacements = {
        "{{executive_summary}}": executive_summary,
        "{{migration_readiness_table}}": render_table(results),
        "{{data_integrity_review}}": data_integrity_review,
        "{{dependency_review}}": dependency_review,
        "{{migration_tasks}}": migration_tasks,
        "{{retirement_order}}": retirement_order,
        "{{items_that_must_not_be_retired}}": must_not_retire,
        "{{final_decision}}": final_decision,
    }

    report_text = template_text
    for placeholder, value in replacements.items():
        report_text = report_text.replace(placeholder, value)
    return report_text


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(content.rstrip() + "\n")


def main() -> int:
    args = parse_args()
    registry_payload = load_yaml(args.config)
    changes_payload = load_yaml(args.changes)
    snapshot_payload = load_json(args.snapshot)
    graph_payload = load_json(args.graph)
    template_text = args.template.read_text(encoding="utf-8")

    registry_by_name = build_registry_name_index(registry_payload)
    changes = changes_payload.get("changes", [])
    if not isinstance(changes, list):
        raise ValueError("Changes manifest must contain a `changes` list")

    results = [
        evaluate_change(change, registry_by_name, snapshot_payload, graph_payload)
        for change in changes
        if isinstance(change, Mapping)
    ]
    final_decision = determine_final_decision(results)

    results_payload = {
        "generated_at": snapshot_payload.get("generated_at"),
        "final_decision": final_decision,
        "results": results,
    }
    report_text = render_report(template_text, results, final_decision)

    write_json(args.results, results_payload)
    write_text(args.report, report_text)
    print(f"Wrote validation results to {args.results}")
    print(f"Wrote validation report to {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
