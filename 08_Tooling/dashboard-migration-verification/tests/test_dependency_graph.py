from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
SCRIPT = SCRIPT_DIR / "build_dependency_graph.py"
sys.path.insert(0, str(SCRIPT_DIR))

spec = importlib.util.spec_from_file_location("build_dependency_graph", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_placeholder_snapshot_marks_dependencies_missing(tmp_path):
    changes = tmp_path / "changes.yaml"
    changes.write_text(
        """
version: 1
changes:
  - action: archive_database
    item_type: database
    source_database: Legacy
    source_item: Legacy
    canonical_database: Canonical
    canonical_item: Canonical
    current_name: Legacy
    proposed_name: Canonical
    migration_method: Verify first.
    rollback_method: Keep source unchanged.
    owner: Modeling & Dashboard Governance Agent
    approval_required: true
    notes: Test only.
""".strip()
        + "\n",
        encoding="utf-8",
    )
    snapshot = tmp_path / "latest.json"
    snapshot.write_text('{"placeholder": true, "dashboards": {}}\n', encoding="utf-8")

    graph = module.build_graph(changes, snapshot)

    assert graph["placeholder_snapshot"] is True
    assert any(node["evidence_status"] == "missing" for node in graph["nodes"])
    assert any(edge["type"] == "unknown_dependency" for edge in graph["edges"])
