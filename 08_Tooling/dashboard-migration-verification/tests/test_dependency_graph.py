from pathlib import Path
import importlib.util
import sys

import pytest

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


def test_duplicate_node_merge_preserves_highest_risk_and_weakest_evidence():
    nodes = {}
    first = module.Node(
        id="field:legacy:status",
        type="field",
        name="Status",
        dashboard="legacy",
        depends_on=["dashboard:legacy:legacy_dashboard"],
        depended_on_by=[],
        risk_level="medium",
        evidence_status="verified",
    )
    second = module.Node(
        id=first.id,
        type="field",
        name="Status",
        dashboard="legacy",
        depends_on=["formula:legacy:status_formula"],
        depended_on_by=["proposed_change:manifest:1"],
        risk_level="critical",
        evidence_status="contradictory",
    )

    module.add_node(nodes, first)
    module.add_node(nodes, second)

    merged = nodes[first.id]
    assert merged.risk_level == "critical"
    assert merged.evidence_status == "contradictory"
    assert merged.depends_on == sorted(
        ["dashboard:legacy:legacy_dashboard", "formula:legacy:status_formula"]
    )
    assert merged.depended_on_by == ["proposed_change:manifest:1"]


def test_dependency_links_are_symmetric_and_deduplicated():
    source = module.Node(
        id="formula:legacy:score_total",
        type="formula",
        name="Score -> Total",
        dashboard="legacy",
        depends_on=[],
        depended_on_by=[],
        risk_level="high",
        evidence_status="verified",
    )
    target = module.Node(
        id="field:legacy:score",
        type="field",
        name="Score",
        dashboard="legacy",
        depends_on=[],
        depended_on_by=[],
        risk_level="medium",
        evidence_status="verified",
    )
    nodes = {source.id: source, target.id: target}

    module.ensure_dependency(nodes, source.id, target.id)
    module.ensure_dependency(nodes, source.id, target.id)

    assert source.depends_on == [target.id]
    assert target.depended_on_by == [source.id]


def test_field_relationships_and_missing_sections_are_conservative():
    snapshot = {
        "dashboards": {
            "legacy": {
                "name": "Legacy Dashboard",
                "schema": {
                    "evidence_status": "verified",
                    "properties": {
                        "Status": {
                            "status_values": ["Draft", "Published"],
                            "formula_dependencies": ["Score"],
                            "relation_targets": ["Projects"],
                            "rollup_targets": ["Project Count"],
                        }
                    },
                },
            }
        }
    }

    nodes = module.extract_snapshot_nodes(snapshot)
    types = {node.type for node in nodes.values()}

    assert {"dashboard", "field", "status_value", "formula", "relation", "rollup"} <= types
    status = next(node for node in nodes.values() if node.type == "field")
    formula = next(node for node in nodes.values() if node.type == "formula")
    assert status.id in formula.depends_on
    assert any(
        node.type == "automation" and node.evidence_status == "missing"
        for node in nodes.values()
    )


def test_invalid_snapshot_and_change_shapes_fail_clearly():
    with pytest.raises(ValueError, match="dashboards.*mapping"):
        module.extract_snapshot_nodes({"dashboards": []})

    with pytest.raises(ValueError, match="changes.*list"):
        module.add_change_nodes({}, {"dashboards": {}}, {"changes": {}})


def test_serialized_graph_is_deterministic_and_sorted():
    first = module.Node(
        id="z:last",
        type="field",
        name="Last",
        dashboard="legacy",
        depends_on=[],
        depended_on_by=[],
        risk_level="low",
        evidence_status="verified",
    )
    second = module.Node(
        id="a:first",
        type="field",
        name="First",
        dashboard="legacy",
        depends_on=[],
        depended_on_by=[],
        risk_level="low",
        evidence_status="verified",
    )
    nodes = {first.id: first, second.id: second}
    snapshot = {"generated_at": "2026-01-01T00:00:00Z"}

    one = module.serialise_graph(snapshot, Path("changes.yaml"), nodes)
    two = module.serialise_graph(snapshot, Path("changes.yaml"), nodes)

    assert one == two
    assert [node["id"] for node in one["nodes"]] == ["a:first", "z:last"]
