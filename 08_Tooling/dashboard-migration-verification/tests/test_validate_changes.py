from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_changes.py"

spec = importlib.util.spec_from_file_location("validate_changes", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def write_changes(path: Path, action: str = "archive_database") -> None:
    path.write_text(
        f"""
version: 1
changes:
  - action: {action}
    item_type: database
    source_database: Legacy Dashboard
    source_item: Legacy Dashboard
    canonical_database: Canonical Dashboard
    canonical_item: Canonical Dashboard
    current_name: Legacy Dashboard
    proposed_name: Canonical Dashboard
    migration_method: Verify first.
    rollback_method: Keep legacy dashboard untouched.
    owner: Modeling & Dashboard Governance Agent
    approval_required: true
    notes: Test only.
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_missing_evidence_blocks_approval(tmp_path):
    changes = tmp_path / "changes.yaml"
    snapshot = tmp_path / "latest.json"
    graph = tmp_path / "dependency_graph.json"
    write_changes(changes)
    snapshot.write_text('{"placeholder": true}\n', encoding="utf-8")
    graph.write_text('{"nodes": [{"evidence_status": "missing"}]}\n', encoding="utf-8")

    validation = module.validate_changes(changes, snapshot, graph)

    result = validation["results"][0]
    assert result["classification"] == "Blocked by missing information"
    assert validation["final_decision"] == "Do Not Retire Yet"


def test_placeholder_snapshot_is_not_verified_evidence(tmp_path):
    changes = tmp_path / "changes.yaml"
    snapshot = tmp_path / "latest.json"
    graph = tmp_path / "dependency_graph.json"
    write_changes(changes, action="rename_field")
    snapshot.write_text('{"placeholder": true}\n', encoding="utf-8")
    graph.write_text('{"nodes": []}\n', encoding="utf-8")

    validation = module.validate_changes(changes, snapshot, graph)

    assert validation["results"][0]["classification"] != "Safe to automate"


def test_destructive_retirement_with_unknown_dependencies_is_blocked(tmp_path):
    changes = tmp_path / "changes.yaml"
    snapshot = tmp_path / "latest.json"
    graph = tmp_path / "dependency_graph.json"
    write_changes(changes, action="archive_database")
    snapshot.write_text('{"placeholder": false, "evidence_status": "inferred"}\n', encoding="utf-8")
    graph.write_text('{"nodes": [{"evidence_status": "missing"}]}\n', encoding="utf-8")

    validation = module.validate_changes(changes, snapshot, graph)

    blockers = validation["results"][0]["blockers"]
    assert any("Destructive action" in blocker for blocker in blockers)


def test_validation_report_preserves_required_sections(tmp_path):
    validation = {
        "results": [
            {
                "change_id": "archive_database::Legacy::Legacy",
                "classification": "Blocked by missing information",
                "migration_status": "Requires Record Migration",
                "blockers": ["Missing evidence."],
            }
        ],
        "final_decision": "Do Not Retire Yet",
    }

    report = module.render_report(validation)

    for section in module.REPORT_SECTIONS:
        assert section in report
    assert "Do Not Retire Yet" in report
