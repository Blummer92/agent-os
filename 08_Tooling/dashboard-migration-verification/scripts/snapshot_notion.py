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
MISSING_EVIDENCE_SECTIONS = (
    "schema",
    "views",
    "templates",
    "permissions",
    "automations",
    "buttons",
)


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
    """Return explicit fast-path metadata for local placeholder snapshots.

    B3 intentionally keeps dashboard snapshots local and placeholder-only. This
    metadata lets agents use the snapshot for quick context while blocking any
    migration or retirement decision until cached lookup and/or live Notion
    verification is added in a later approved path.
    """

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
        "next_required_evidence": "cached_navigation_lookup_then_optional_live_verification",
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


def build_evidence_path_summary(dashboards: Mapping[str, Any]) -> Dict[str, Any]:
    evidence_paths = []
    for raw_dashboard in dashboards.values():
        if isinstance(raw_dashboard, Mapping):
            raw_evidence_path = raw_dashboard.get("evidence_path", {})
            if isinstance(raw_evidence_path, Mapping):
                evidence_paths.append(raw_evidence_path)

    return {
        "mode": "placeholder_only",
        "evidence_speed_tier": "local_placeholder",
        "dashboards_total": len(dashboards),
        "dashboards_with_live_verification": sum(
            1 for path in evidence_paths if bool(path.get("live_notion_used", False))
        ),
        "dashboards_safe_for_migration_decision": sum(
            1 for path in evidence_paths if bool(path.get("safe_for_migration_decision", False))
        ),
        "dashboards_safe_for_retirement_decision": sum(
            1 for path in evidence_paths if bool(path.get("safe_for_retirement_decision", False))
        ),
        "requires_network": any(bool(path.get("requires_network", False)) for path in evidence_paths),
        "requires_credentials": any(
            bool(path.get("requires_credentials", False)) for path in evidence_paths
        ),
        "live_verification_required": any(
            bool(path.get("live_verification_required", True)) for path in evidence_paths
        ),
    }


class PlaceholderSnapshotProvider:
    """Produces a conservative local scaffold until cached/live evidence is wired in."""

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
                    "Placeholder snapshot only. Replace with verified Notion inventory before retirement decisions.",
                    "B3 evidence path is local placeholder context only; it is not migration or retirement proof.",
                ],
            },
            "records_sample": [],
        }


class NotionApiSnapshotProvider:
    """Deferred extension point for approved future live Notion connectivity."""

    def __init__(self, api_token: str) -> None:
        self.api_token = api_token

    def fetch_dashboard(self, entry: DashboardEntry) -> Dict[str, Any]:
        raise NotImplementedError(
            "Live Notion connectivity is intentionally deferred. Use the placeholder provider until approved cached lookup and/or live verification integration exists."
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
        help="Reserved for future Notion API support",
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
        dashboard_snapshot.setdefault("key", entry.key)
        dashboard_snapshot.setdefault("name", entry.name)
        dashboard_snapshot.setdefault("notion_id", entry.notion_id)
        dashboard_snapshot.setdefault("data_source_id", entry.data_source_id)
        dashboard_snapshot.setdefault("owner", entry.owner)
        dashboard_snapshot.setdefault("source_of_truth_role", entry.source_of_truth_role)
        dashboard_snapshot.setdefault("retirement_allowed", entry.retirement_allowed)
        dashboard_snapshot.setdefault("human_approval_required", entry.human_approval_required)
        dashboard_snapshot.setdefault("notes", entry.notes)
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
