from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location(
    "validate_changes", SCRIPT_DIR / "validate_changes.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def sample_change(action="archive_database"):
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
        "approval_required": True,
        "notes": "Test only.",
    }


def test_missing_evidence_blocks_approval():
    registry = {}
    snapshot = {"dashboards": {}}
    graph = {"nodes": []}

    result = module.evaluate_change(sample_change(), registry, snapshot, graph)

    assert result["classification"] == "Blocked by missing information"
    assert result["blockers"]


def test_destructive_retirement_with_unverified_records_is_blocked():
    registry = {
        "Legacy Dashboard": {
            "key": "legacy",
            "retirement_allowed": True,
            "human_approval_required": True,
        },
        "Canonical Dashboard": {
            "key": "canonical",
            "retirement_allowed": False,
            "human_approval_required": True,
        },
    }
    snapshot = {
        "dashboards": {
            "legacy": {
                "name": "Legacy Dashboard",
                "records_summary": {"unique_records_verified": False},
            },
            "canonical": {"name": "Canonical Dashboard"},
        }
    }
    graph = {
        "nodes": [
            {"dashboard": "legacy", "type": "field", "evidence_status": "verified"}
        ]
    }

    result = module.evaluate_change(sample_change(), registry, snapshot, graph)

    assert "Unique records have not been verified for the retirement target." in result[
        "blockers"
    ]


def test_validation_report_preserves_required_sections():
    template = (ROOT / "templates" / "validation_report.md").read_text(
        encoding="utf-8"
    )
    results = [
        module.evaluate_change(sample_change(), {}, {"dashboards": {}}, {"nodes": []})
    ]
    decision = module.determine_final_decision(results)

    report = module.render_report(template, results, decision)

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
        assert heading in report
    assert "Do Not Retire Yet" in report
