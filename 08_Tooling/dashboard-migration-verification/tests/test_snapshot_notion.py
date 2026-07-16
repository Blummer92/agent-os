from argparse import Namespace
from pathlib import Path
import importlib.util
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location(
    "snapshot_notion", SCRIPT_DIR / "snapshot_notion.py"
)
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


def test_placeholder_snapshot_includes_explicit_evidence_path() -> None:
    snapshot = module.PlaceholderSnapshotProvider().fetch_dashboard(sample_entry())

    evidence_path = snapshot["evidence_path"]

    assert evidence_path["mode"] == "placeholder_only"
    assert evidence_path["requires_network"] is False
    assert evidence_path["requires_credentials"] is False
    assert evidence_path["safe_for_fast_agent_context"] is True
    assert evidence_path["safe_for_migration_decision"] is False
    assert evidence_path["safe_for_retirement_decision"] is False
    assert evidence_path["live_verification_required"] is True
    assert evidence_path["human_review_required"] is True


def test_placeholder_snapshot_preserves_dashboard_registry_fields() -> None:
    entry = sample_entry()
    snapshot = module.PlaceholderSnapshotProvider().fetch_dashboard(entry)

    assert snapshot["key"] == entry.key
    assert snapshot["name"] == entry.name
    assert snapshot["notion_id"] == entry.notion_id
    assert snapshot["data_source_id"] == entry.data_source_id
    assert snapshot["owner"] == entry.owner
    assert snapshot["source_of_truth_role"] == entry.source_of_truth_role
    assert snapshot["retirement_allowed"] == entry.retirement_allowed
    assert snapshot["human_approval_required"] == entry.human_approval_required
    assert snapshot["notes"] == entry.notes


def test_placeholder_snapshot_keeps_missing_evidence_missing() -> None:
    snapshot = module.PlaceholderSnapshotProvider().fetch_dashboard(sample_entry())

    for section_name in [
        "schema",
        "views",
        "templates",
        "permissions",
        "automations",
        "buttons",
    ]:
        section = snapshot[section_name]
        assert section["evidence_status"] == "missing"
        assert section["captured"] is False

    assert snapshot["records_summary"]["evidence_status"] == "missing"
    assert snapshot["records_summary"]["unique_records_verified"] is False
    assert snapshot["records_sample"] == []


def test_build_snapshot_includes_evidence_path_summary() -> None:
    registry = {
        "unit_alignment": sample_entry(),
        "daily_generation": module.DashboardEntry(
            key="daily_generation",
            name="Daily Generation Packet Dashboard",
            notion_id="unknown",
            data_source_id="unknown",
            owner="Generation Operations",
            source_of_truth_role="daily generation operations dashboard",
            retirement_allowed=False,
            human_approval_required=True,
            notes="Test fixture.",
        ),
    }

    snapshot = module.build_snapshot(registry, module.PlaceholderSnapshotProvider())

    summary = snapshot["evidence_path_summary"]
    assert summary["mode"] == "placeholder_only"
    assert summary["evidence_speed_tier"] == "local_placeholder"
    assert summary["dashboards_total"] == len(registry)
    assert summary["dashboards_with_live_verification"] == 0
    assert summary["dashboards_safe_for_migration_decision"] == 0
    assert summary["dashboards_safe_for_retirement_decision"] == 0
    assert summary["requires_network"] is False
    assert summary["requires_credentials"] is False
    assert summary["live_verification_required"] is True


def test_get_provider_default_placeholder_path_requires_no_token() -> None:
    provider = module.get_provider(Namespace(provider="placeholder", api_token=""))

    assert isinstance(provider, module.PlaceholderSnapshotProvider)


def test_get_provider_notion_without_token_fails_safely() -> None:
    with pytest.raises(SystemExit):
        module.get_provider(Namespace(provider="notion", api_token=""))


def test_notion_api_provider_remains_deferred() -> None:
    provider = module.NotionApiSnapshotProvider(api_token="test-token")

    with pytest.raises(NotImplementedError) as excinfo:
        provider.fetch_dashboard(sample_entry())

    assert "intentionally deferred" in str(excinfo.value)
