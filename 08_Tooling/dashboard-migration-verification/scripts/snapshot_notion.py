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


class PlaceholderSnapshotProvider:
    """Produces a conservative scaffold until live Notion access is wired in."""

    def fetch_dashboard(self, entry: DashboardEntry) -> Dict[str, Any]:
        return {
            "name": entry.name,
            "notion_id": entry.notion_id,
            "data_source_id": entry.data_source_id,
            "schema": {
                "evidence_status": "missing",
                "captured": False,
                "properties": {},
            },
            "views": {
                "evidence_status": "missing",
                "captured": False,
                "items": {},
            },
            "templates": {
                "evidence_status": "missing",
                "captured": False,
                "items": {},
            },
            "permissions": {
                "evidence_status": "missing",
                "captured": False,
                "items": {},
            },
            "automations": {
                "evidence_status": "missing",
                "captured": False,
                "items": {},
            },
            "buttons": {
                "evidence_status": "missing",
                "captured": False,
                "items": {},
            },
            "records_summary": {
                "record_count": None,
                "unique_records_verified": False,
                "duplicate_risk": "unknown",
                "evidence_status": "missing",
                "notes": [
                    "Placeholder snapshot only. Replace with verified Notion inventory before retirement decisions."
                ],
            },
            "records_sample": [],
        }


class NotionApiSnapshotProvider:
    """Extension point for real Notion connectivity."""

    def __init__(self, api_token: str) -> None:
        self.api_token = api_token

    def fetch_dashboard(self, entry: DashboardEntry) -> Dict[str, Any]:
        raise NotImplementedError(
            "Real Notion connectivity is not configured yet. Use the placeholder provider until credentials and API wiring are available."
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
        dashboard_snapshot.setdefault("name", entry.name)
        dashboard_snapshot.setdefault("notion_id", entry.notion_id)
        dashboard_snapshot.setdefault("data_source_id", entry.data_source_id)
        dashboards[dashboard_key] = dashboard_snapshot

    return {
        "generated_at": generated_at,
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
