from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location(
    "build_dependency_graph", SCRIPT_DIR / "build_dependency_graph.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_placeholder_snapshot_marks_unknown_inventory_missing():
    snapshot = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "dashboards": {
            "legacy": {
                "name": "Legacy Dashboard",
                "schema": {"properties": {}},
            }
        },
    }

    nodes = module.extract_snapshot_nodes(snapshot)

    assert any(node.evidence_status == "missing" for node in nodes.values())
    assert any(node.name == "Unknown field inventory" for node in nodes.values())


def test_proposed_change_without_related_nodes_is_high_risk():
    snapshot = {"dashboards": {"legacy": {"name": "Legacy Dashboard"}}}
    nodes = module.extract_snapshot_nodes(snapshot)
    changes = {
        "changes": [
            {
                "action": "archive_database",
                "item_type": "database",
                "source_database": "Missing Dashboard",
                "canonical_database": "Canonical",
                "source_item": "Legacy",
            }
        ]
    }

    module.add_change_nodes(nodes, snapshot, changes)
    proposed = [node for node in nodes.values() if node.type == "proposed_change"]

    assert proposed
    assert proposed[0].risk_level == "high"
    assert proposed[0].evidence_status == "missing"
