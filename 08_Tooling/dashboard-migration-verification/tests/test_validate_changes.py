from pathlib import Path
import importlib.util
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location(
    "validate_changes", SCRIPT_DIR / "validate_changes.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def sample_change(action="archive_database", approval_required=True):
    return {
        "action": action,
        "item_type": "database" if action == "archive_database" else "field",
        "source_database": "Legacy Dashboard",
        "source_item": "Legacy Item",
        "canonical_database": "Canonical Dashboard",
        "canonical_item": "Canonical Item",
        "current_name": "Legacy",
        "proposed_name": "Canonical",
        "migration_method": "Verify first.",
        "rollback_method": "Keep source unchanged.",
        "owner": "Dashboard Governance",
        "approval_required": approval_required,
        "notes": "Test only.",
    }


def verified_evidence():
    registry = {
        "Legacy Dashboard": {
            "key": "legacy",
            "retirement_allowed": True,
            "human_approval_required": False,
        },
        "Canonical Dashboard": {
            "key": "canonical",
            "retirement_allowed": False,
            "human_approval_required": False,
        },
    }
    snapshot = {
        "dashboards": {
            "legacy": {
                "name": "Legacy Dashboard",
                "records_summary": {"unique_records_verified": True},
            },
            "canonical": {
                "name": "Canonical Dashboard",
                "records_summary": {"unique_records_verified": True},
            },
        }
    }
    graph = {
        "nodes": [
            {
                "dashboard": "legacy",
                "type": "field",
                "evidence_status": "verified",
            },
            {
                "dashboard": "canonical",
                "type": "field",
                "evidence_status": "verified",
            },
        ]
    }
    return registry, snapshot, graph


def test_missing_evidence_blocks_approval():
    result = module.evaluate_change(sample_change(), {}, {"dashboards": {}}, {"nodes": []})

    assert result["classification"] == "Blocked by missing information"
    assert result["blockers"]


def test_destructive_retirement_with_unverified_records_is_blocked():
    registry, snapshot, graph = verified_evidence()
    snapshot["dashboards"]["legacy"]["records_summary"][
        "unique_records_verified"
    ] = False

    result = module.evaluate_change(sample_change(), registry, snapshot, graph)

    assert "Unique records have not been verified for the retirement target." in result[
        "blockers"
    ]
    assert result["migration_status"] == "Requires Dependency Cleanup"


def test_verified_retirement_is_safe_only_without_approval_requirements():
    registry, snapshot, graph = verified_evidence()

    result = module.evaluate_change(
        sample_change(approval_required=False), registry, snapshot, graph
    )

    assert result["classification"] == "Safe to automate"
    assert result["migration_status"] == "Safe to Retire"
    assert result["blockers"] == []
    assert result["review_reasons"] == []


def test_approval_requirement_remains_manual_review_evidence():
    registry, snapshot, graph = verified_evidence()

    result = module.evaluate_change(sample_change(), registry, snapshot, graph)

    assert result["classification"] == "Requires manual review"
    assert result["migration_status"] == "Requires Record Migration"
    assert any("Human approval is required" in reason for reason in result["review_reasons"])


def test_unresolved_active_workflow_is_a_blocker_and_raises_workflow_risk():
    registry, snapshot, graph = verified_evidence()
    graph["nodes"].append(
        {
            "dashboard": "legacy",
            "type": "automation",
            "evidence_status": "stale",
        }
    )

    result = module.evaluate_change(
        sample_change(approval_required=False), registry, snapshot, graph
    )

    assert any("Active workflows" in blocker for blocker in result["blockers"])
    assert result["risk_ratings"]["Workflow Risk"] == "Medium"
    assert result["classification"] == "Blocked by missing information"


def test_final_decision_transitions_are_conservative():
    assert module.determine_final_decision(
        [{"classification": "Blocked by missing information", "migration_status": "Requires Dependency Cleanup"}]
    ) == "Do Not Retire Yet"
    assert module.determine_final_decision(
        [{"classification": "Requires manual review", "migration_status": "Requires Record Migration"}]
    ) == "Ready After Migration"
    assert module.determine_final_decision(
        [{"classification": "Safe to automate", "migration_status": "Safe to Retire"}]
    ) == "Ready for Retirement"


def test_risk_levels_are_bounded_and_deterministic():
    change = sample_change("merge_database", approval_required=False)
    unresolved = [
        {"type": "synced_database"},
        {"type": "automation"},
        {"type": "formula"},
        {"type": "relation"},
    ]

    first = module.compute_risk_ratings(change, ["blocked"], ["review"], unresolved)
    second = module.compute_risk_ratings(change, ["blocked"], ["review"], unresolved)

    assert first == second
    assert set(first.values()) <= {"Low", "Medium", "High", "Critical"}
    assert first["Dependency Risk"] == "Critical"


def test_malformed_registry_and_graph_shapes_fail_conservatively():
    with pytest.raises(ValueError, match="dashboards.*mapping"):
        module.build_registry_name_index({"dashboards": []})

    assert module.get_graph_nodes_by_dashboard({"nodes": {}}, ["legacy"]) == []
    assert module.get_snapshot_by_name({"dashboards": []}, "Legacy Dashboard") == (
        None,
        None,
    )


def test_validation_report_preserves_required_sections_and_is_deterministic():
    template = (ROOT / "templates" / "validation_report.md").read_text(
        encoding="utf-8"
    )
    results = [
        module.evaluate_change(sample_change(), {}, {"dashboards": {}}, {"nodes": []})
    ]
    decision = module.determine_final_decision(results)

    first = module.render_report(template, results, decision)
    second = module.render_report(template, results, decision)

    assert first == second
    for heading in [
        "## 1. Executive Summary",
        "## 2. Migration Readiness Table",
        "## 3. Data Integrity Review",
        "## 4. Dependency Review",
        "## 5. Migration Tasks",
        "## 6. Retirement Order",
        "## 7. Items That Must Not Be Retired",
        "## 8. Final Decision",
    ]:
        assert heading in first
    assert "Do Not Retire Yet" in first
