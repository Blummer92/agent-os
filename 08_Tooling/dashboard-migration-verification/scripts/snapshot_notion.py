from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Protocol

try:
    import yaml
except ImportError as exc:  # pragma: no cover - import guard for local setup
    raise SystemExit(
        "PyYAML is required to run this script. Install it with `pip install pyyaml`."
    ) from exc


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "dashboards.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "snapshots"

KNOWN_EVIDENCE_MODES = {
    "placeholder_only",
    "cached_navigation_lookup",
    "live_notion_verification",
}
KNOWN_EVIDENCE_TIERS = {
    "local_placeholder",
    "cached_navigation",
    "live_verified",
}
REQUIRED_EVIDENCE_PATH_FIELDS = {
    "mode": str,
    "evidence_speed_tier": str,
    "requires_network": bool,
    "requires_credentials": bool,
    "cached_navigation_lookup_used": bool,
    "live_notion_used": bool,
    "contract_normalization_used": bool,
    "safe_for_fast_agent_context": bool,
    "safe_for_migration_decision": bool,
    "safe_for_retirement_decision": bool,
    "human_review_required": bool,
    "live_verification_required": bool,
}


@dataclass(frozen=True)
class DashboardEntry:
    key: str
    name: str
    notion_id: str
    data_source_id: str
    owner: str
    source_of_truth_role: str
    retirement_allowed: bool
    human_approval_required: bool
    notes: str


class SnapshotProvider(Protocol):
    def fetch_dashboard(self, entry: DashboardEntry) -> Dict[str, Any]:
        ...


def placeholder_evidence_path() -> Dict[str, Any]:
    """Return explicit safety metadata for local placeholder snapshots."""

    return {
        "mode": "placeholder_only",
        "evidence_speed_tier": "local_placeholder",
        "requires_network": False,
        "requires_credentials": False,
        "cached_navigation_lookup_used": False,
        "live_notion_used": False,
        "contract_normalization_used": False,
        "safe_for_fast_agent_context": True,
        "safe_for_migration_decision": False,
        "safe_for_retirement_decision": False,
        "human_review_required": True,
        "live_verification_required": True,
        "next_required_evidence": (
            "cached_navigation_lookup_then_optional_live_verification"
        ),
    }


def missing_evidence_section(empty_key: str) -> Dict[str, Any]:
    return {
        "evidence_status": "missing",
        "captured": False,
        empty_key: {},
    }


def dashboard_registry_fields(entry: DashboardEntry) -> Dict[str, Any]:
    return {
        "key": entry.key,
        "name": entry.name,
        "notion_id": entry.notion_id,
        "data_source_id": entry.data_source_id,
        "owner": entry.owner,
        "source_of_truth_role": entry.source_of_truth_role,
        "retirement_allowed": entry.retirement_allowed,
        "human_approval_required": entry.human_approval_required,
        "notes": entry.notes,
    }


def _valid_evidence_path(raw_path: Any) -> Mapping[str, Any] | None:
    if not isinstance(raw_path, Mapping):
        return None

    for field_name, expected_type in REQUIRED_EVIDENCE_PATH_FIELDS.items():
        if not isinstance(raw_path.get(field_name), expected_type):
            return None

    if raw_path["mode"] not in KNOWN_EVIDENCE_MODES:
        return None
    if raw_path["evidence_speed_tier"] not in KNOWN_EVIDENCE_TIERS:
        return None
    return raw_path


def build_evidence_path_summary(
    dashboards: Mapping[str, Any],
) -> Dict[str, Any]:
    """Build a fail-closed summary from per-dashboard evidence metadata."""

    evidence_paths = []
    invalid_paths = 0

    for raw_dashboard in dashboards.values():
        if not isinstance(raw_dashboard, Mapping):
            invalid_paths += 1
            continue
        evidence_path = _valid_evidence_path(raw_dashboard.get("evidence_path"))
        if evidence_path is None:
            invalid_paths += 1
            continue
        evidence_paths.append(evidence_path)

    dashboard_total = len(dashboards)
    modes = {str(path["mode"]) for path in evidence_paths}
    tiers = {str(path["evidence_speed_tier"]) for path in evidence_paths}

    if dashboard_total == 0:
        summary_mode = "empty"
        summary_tier = "none"
    elif invalid_paths:
        summary_mode = "unknown" if not evidence_paths else "mixed"
        summary_tier = "unknown" if not evidence_paths else "mixed"
    else:
        summary_mode = next(iter(modes)) if len(modes) == 1 else "mixed"
        summary_tier = next(iter(tiers)) if len(tiers) == 1 else "mixed"

    return {
        "mode": summary_mode,
        "evidence_speed_tier": summary_tier,
        "dashboards_total": dashboard_total,
        "dashboards_with_valid_evidence_path": len(evidence_paths),
        "dashboards_with_invalid_evidence_path": invalid_paths,
        "dashboards_with_cached_navigation_lookup": sum(
            1
            for path in evidence_paths
            if path["cached_navigation_lookup_used"]
        ),
        "dashboards_with_live_verification": sum(
            1 for path in evidence_paths if path["live_notion_used"]
        ),
        "dashboards_safe_for_fast_agent_context": sum(
            1 for path in evidence_paths if path["safe_for_fast_agent_context"]
        ),
        "dashboards_safe_for_migration_decision": sum(
            1 for path in evidence_paths if path["safe_for_migration_decision"]
        ),
        "dashboards_safe_for_retirement_decision": sum(
            1 for path in evidence_paths if path["safe_for_retirement_decision"]
        ),
        "requires_network": any(
            path["requires_network"] for path in evidence_paths
        ),
        "requires_credentials": any(
            path["requires_credentials"] for path in evidence_paths
        ),
        "human_review_required": (
            dashboard_total == 0
            or invalid_paths > 0
            or any(path["human_review_required"] for path in evidence_paths)
        ),
        "live_verification_required": (
            dashboard_total > 0
            and (
                invalid_paths > 0
                or any(
                    path["live_verification_required"]
                    for path in evidence_paths
                )
            )
        ),
    }


class PlaceholderSnapshotProvider:
    """Produce conservative local evidence without network or credentials."""

    def fetch_dashboard(self, entry: DashboardEntry) -> Dict[str, Any]:
        return {
            **dashboard_registry_fields(entry),
            "evidence_path": placeholder_evidence_path(),
            "schema": missing_evidence_section("properties"),
            "views": missing_evidence_section("items"),
            "templates": missing_evidence_section("items"),
            "permissions": missing_evidence_section("items"),
            "automations": missing_evidence_section("items"),
            "buttons": missing_evidence_section("items"),
            "records_summary": {
                "record_count": None,
                "unique_records_verified": False,
                "duplicate_risk": "unknown",
                "evidence_status": "missing",
                "notes": [
                    (
                        "Placeholder snapshot only. Replace with verified Notion "
                        "inventory before retirement decisions."
                    ),
                    "Local placeholder context is not migration or retirement proof.",
                ],
            },
            "records_sample": [],
        }


class NotionApiSnapshotProvider:
    """Deferred extension point; approved live reads belong behind B4."""

    def __init__(self, api_token: str) -> None:
        self.api_token = api_token

    def fetch_dashboard(self, entry: DashboardEntry) -> Dict[str, Any]:
        raise NotImplementedError(
            "Direct live Notion connectivity is not configured. Use the "
            "placeholder provider until an approved B4 read-only integration "
            "exists."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture a structured dashboard evidence snapshot."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to dashboards.yaml",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for JSON snapshots",
    )
    parser.add_argument(
        "--provider",
        choices=["placeholder", "notion"],
        default="placeholder",
        help="Snapshot provider implementation",
    )
    parser.add_argument(
        "--api-token",
        default="",
        help="Reserved for future approved Notion read support",
    )
    return parser.parse_args()


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping at {path}")
    return data


def load_dashboard_registry(path: Path) -> Dict[str, DashboardEntry]:
    payload = load_yaml(path)
    dashboards = payload.get("dashboards", {})
    if not isinstance(dashboards, Mapping):
        raise ValueError("dashboards.yaml must contain a top-level `dashboards` mapping")

    registry: Dict[str, DashboardEntry] = {}
    for key, raw in dashboards.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"Dashboard entry `{key}` must be a mapping")
        registry[str(key)] = DashboardEntry(
            key=str(key),
            name=str(raw.get("name", key)),
            notion_id=str(raw.get("notion_id", "unknown")),
            data_source_id=str(raw.get("data_source_id", "unknown")),
            owner=str(raw.get("owner", "unknown")),
            source_of_truth_role=str(raw.get("source_of_truth_role", "unknown")),
            retirement_allowed=bool(raw.get("retirement_allowed", False)),
            human_approval_required=bool(raw.get("human_approval_required", True)),
            notes=str(raw.get("notes", "")),
        )
    return registry


def get_provider(args: argparse.Namespace) -> SnapshotProvider:
    if args.provider == "placeholder":
        return PlaceholderSnapshotProvider()
    if not args.api_token:
        raise SystemExit("--api-token is required when --provider notion is selected.")
    return NotionApiSnapshotProvider(api_token=args.api_token)


def build_snapshot(
    registry: Mapping[str, DashboardEntry], provider: SnapshotProvider
) -> Dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    dashboards: Dict[str, Any] = {}

    for dashboard_key, entry in registry.items():
        dashboard_snapshot = provider.fetch_dashboard(entry)
        if not isinstance(dashboard_snapshot, dict):
            raise TypeError("Snapshot providers must return a dictionary")
        for field_name, value in dashboard_registry_fields(entry).items():
            dashboard_snapshot.setdefault(field_name, value)
        dashboards[dashboard_key] = dashboard_snapshot

    return {
        "generated_at": generated_at,
        "evidence_path_summary": build_evidence_path_summary(dashboards),
        "dashboards": dashboards,
    }


def write_snapshot(snapshot: Mapping[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = snapshot["generated_at"].replace(":", "-")
    snapshot_path = output_dir / f"snapshot_{timestamp}.json"
    latest_path = output_dir / "latest.json"

    with snapshot_path.open("w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, sort_keys=True)
        handle.write("\n")

    with latest_path.open("w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, sort_keys=True)
        handle.write("\n")

    return snapshot_path


def main() -> int:
    args = parse_args()
    registry = load_dashboard_registry(args.config)
    provider = get_provider(args)
    snapshot = build_snapshot(registry, provider)
    written_path = write_snapshot(snapshot, args.output_dir)
    print(f"Wrote snapshot to {written_path}")
    print(f"Updated latest snapshot at {args.output_dir / 'latest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
