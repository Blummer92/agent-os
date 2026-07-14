#!/usr/bin/env python3
"""Create a conservative placeholder dashboard snapshot.

Live Notion access is intentionally not wired in this scaffold. The generated snapshot
is useful as local structure, not as proof of migration readiness.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from dashboard_migration_common import TOOL_ROOT, write_json


def build_placeholder_snapshot() -> dict:
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": generated_at,
        "placeholder": True,
        "evidence_status": "missing",
        "dashboards": {
            "example_dashboard": {
                "name": "Example Dashboard",
                "notion_id": "EXAMPLE_NOTION_ID",
                "data_source_id": "EXAMPLE_DATA_SOURCE_ID",
                "schema": {},
                "views": {},
                "templates": {},
                "permissions": {},
                "automations": {},
                "buttons": {},
                "records_summary": {},
                "records_sample": [],
            }
        },
    }


def main() -> None:
    snapshot = build_placeholder_snapshot()
    stamp = snapshot["generated_at"].replace(":", "").replace("-", "").split(".")[0]
    snapshot_path = TOOL_ROOT / "snapshots" / f"snapshot_{stamp}.json"
    latest_path = TOOL_ROOT / "snapshots" / "latest.json"
    write_json(snapshot_path, snapshot)
    write_json(latest_path, snapshot)
    print(f"Wrote placeholder snapshot: {snapshot_path}")
    print("Evidence status: missing")
    print("Live Notion mutations: none")


if __name__ == "__main__":
    main()
