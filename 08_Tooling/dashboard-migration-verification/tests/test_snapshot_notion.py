from argparse import Namespace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "snapshot_notion.py"
spec = importlib.util.spec_from_file_location("snapshot_notion", SCRIPT_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def sample_entry() -> module.DashboardEntry:
    return module.DashboardEntry(
        key="unit_alignment_and_readiness_dashboard",
        name="Unit Alignment & Readiness Dashboard",
        notion_id="unknown",
        data_source_id="unknown",
        owner="Curriculum Operations",
        source_of_truth_role="alignment and readiness source",
        retirement_allowed=False,
        human_approval_required=True,
        notes="Status normalization requires explicit evidence.",
    )


def complete_path(mode: str, tier: str) -> dict:
    path = module.placeholder_evidence_path()
    path["mode"] = mode
    path["evidence_speed_tier"] = tier
    return path


def test_placeholder_snapshot_includes_explicit_evidence_path() -> None:
    snapshot = module.PlaceholderSnapshotProvider().fetch_dashboard(sample_entry())
    evidence_path = snapshot["evidence_path"]

    assert evidence_path["mode"] == "placeholder_only"
    assert evidence_path["requires_network"] is False
    assert evidence_path["requires_credentials"] is False
    assert evidence_path["cached_navigation_lookup_used"] is False
    assert evidence_path["live_notion_used"] is False
    assert evidence_path["safe_for_fast_agent_context"] is True
    assert evidence_path["safe_for_migration_decision"] is False
    assert evidence_path["safe_for_retirement_decision"] is False
    assert evidence_path["live_verification_required"] is True


def test_placeholder_snapshot_preserves_dashboard_registry_fields() -> None:
    entry = sample_entry()
    snapshot = module.PlaceholderSnapshotProvider().fetch_dashboard(entry)

    for field_name, expected in module.dashboard_registry_fields(entry).items():
        assert snapshot[field_name] == expected


def test_placeholder_snapshot_keeps_missing_evidence_missing() -> None:
    snapshot = module.PlaceholderSnapshotProvider().fetch_dashboard(sample_entry())

    for section_name in (
        "schema",
        "views",
        "templates",
        "permissions",
        "automations",
        "buttons",
    ):
        assert snapshot[section_name]["evidence_status"] == "missing"
        assert snapshot[section_name]["captured"] is False

    assert snapshot["records_summary"]["evidence_status"] == "missing"
    assert snapshot["records_summary"]["unique_records_verified"] is False
    assert snapshot["records_sample"] == []


def test_all_placeholder_summary_is_derived_from_dashboard_paths() -> None:
    registry = {"one": sample_entry()}
    snapshot = module.build_snapshot(registry, module.PlaceholderSnapshotProvider())
    summary = snapshot["evidence_path_summary"]

    assert summary["mode"] == "placeholder_only"
    assert summary["evidence_speed_tier"] == "local_placeholder"
    assert summary["dashboards_total"] == 1
    assert summary["dashboards_with_valid_evidence_path"] == 1
    assert summary["dashboards_with_invalid_evidence_path"] == 0
    assert summary["dashboards_safe_for_fast_agent_context"] == 1
    assert summary["dashboards_safe_for_migration_decision"] == 0
    assert summary["human_review_required"] is True
    assert summary["live_verification_required"] is True


def test_empty_registry_summary_is_explicit() -> None:
    summary = module.build_evidence_path_summary({})

    assert summary["mode"] == "empty"
    assert summary["evidence_speed_tier"] == "none"
    assert summary["dashboards_total"] == 0
    assert summary["human_review_required"] is True
    assert summary["live_verification_required"] is False


def test_missing_evidence_path_fails_closed() -> None:
    summary = module.build_evidence_path_summary({"one": {"name": "No path"}})

    assert summary["mode"] == "unknown"
    assert summary["dashboards_with_invalid_evidence_path"] == 1
    assert summary["dashboards_safe_for_fast_agent_context"] == 0
    assert summary["human_review_required"] is True
    assert summary["live_verification_required"] is True


def test_unknown_evidence_mode_fails_closed() -> None:
    bad_path = complete_path("mystery", "local_placeholder")
    summary = module.build_evidence_path_summary(
        {"one": {"evidence_path": bad_path}}
    )

    assert summary["mode"] == "unknown"
    assert summary["dashboards_with_invalid_evidence_path"] == 1
    assert summary["human_review_required"] is True


def test_mixed_valid_evidence_modes_are_reported_as_mixed() -> None:
    cached_path = complete_path(
        "cached_navigation_lookup", "cached_navigation"
    )
    cached_path["cached_navigation_lookup_used"] = True
    summary = module.build_evidence_path_summary(
        {
            "placeholder": {
                "evidence_path": module.placeholder_evidence_path()
            },
            "cached": {"evidence_path": cached_path},
        }
    )

    assert summary["mode"] == "mixed"
    assert summary["evidence_speed_tier"] == "mixed"
    assert summary["dashboards_with_cached_navigation_lookup"] == 1


def test_custom_provider_without_evidence_path_is_not_treated_as_safe() -> None:
    class CustomProvider:
        def fetch_dashboard(self, entry: module.DashboardEntry) -> dict:
            return {"name": entry.name}

    snapshot = module.build_snapshot({"one": sample_entry()}, CustomProvider())

    assert snapshot["dashboards"]["one"]["owner"] == "Curriculum Operations"
    assert snapshot["evidence_path_summary"]["mode"] == "unknown"
    assert snapshot["evidence_path_summary"]["human_review_required"] is True


def test_get_provider_default_placeholder_path_requires_no_token() -> None:
    provider = module.get_provider(Namespace(provider="placeholder", api_token=""))

    assert isinstance(provider, module.PlaceholderSnapshotProvider)


def test_get_provider_notion_without_token_fails_safely() -> None:
    with pytest.raises(SystemExit):
        module.get_provider(Namespace(provider="notion", api_token=""))


def test_notion_provider_remains_deferred_to_approved_integration() -> None:
    provider = module.NotionApiSnapshotProvider(api_token="test-token")

    with pytest.raises(NotImplementedError, match="approved B4 read-only"):
        provider.fetch_dashboard(sample_entry())


def test_write_snapshot_creates_timestamped_and_latest_files(tmp_path: Path) -> None:
    snapshot = module.build_snapshot(
        {"one": sample_entry()}, module.PlaceholderSnapshotProvider()
    )

    written = module.write_snapshot(snapshot, tmp_path)

    assert written.exists()
    assert (tmp_path / "latest.json").exists()
    assert json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))[
        "evidence_path_summary"
    ]["mode"] == "placeholder_only"


def test_cli_smoke_uses_local_placeholder_path(tmp_path: Path) -> None:
    config = tmp_path / "dashboards.yaml"
    output_dir = tmp_path / "snapshots"
    config.write_text(
        "\n".join(
            [
                "dashboards:",
                "  example:",
                "    name: Example Dashboard",
                "    notion_id: unknown",
                "    data_source_id: unknown",
                "    owner: Test Owner",
                "    source_of_truth_role: test evidence",
                "    retirement_allowed: false",
                "    human_approval_required: true",
                "    notes: Local fixture.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--config",
            str(config),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))
    assert payload["evidence_path_summary"]["mode"] == "placeholder_only"
    assert payload["dashboards"]["example"]["evidence_path"][
        "requires_network"
    ] is False
