import socket

import pytest

from scripts.agent_os_issue_acceptance.batch_graph import (
    IssueBatchGraph,
    IssueBatchNode,
    build_issue_batch_graph,
    load_issue_batch_fixture,
)
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome


def fixture_nodes():
    return [
        {
            "node_id": "issue-2",
            "readiness": "blocked",
            "readiness_evidence": ["b", "a", "a"],
            "owner": "QA / Test Agent",
            "source_of_truth": "GitHub",
            "affected_paths": ["b.py", "a.py"],
            "forbidden_paths": ["production/"],
            "dependency_ids": ["missing", "issue-1", "issue-2"],
            "entity_id": "agent-os-issue:two",
            "provenance": ["fixture:two"],
        },
        {
            "node_id": "issue-1",
            "readiness": ReadinessOutcome.READY,
            "dependency_ids": [],
        },
    ]


def test_equivalent_input_orders_produce_identical_graphs():
    first = build_issue_batch_graph(load_issue_batch_fixture(fixture_nodes()))
    second = build_issue_batch_graph(load_issue_batch_fixture(reversed(fixture_nodes())))

    assert first == second
    assert tuple(node.node_id for node in first.nodes) == ("issue-1", "issue-2")


def test_duplicate_node_ids_are_rejected_deterministically():
    nodes = load_issue_batch_fixture(
        [
            {"node_id": "b", "readiness": "ready"},
            {"node_id": "a", "readiness": "ready"},
            {"node_id": "b", "readiness": "blocked"},
            {"node_id": "a", "readiness": "needs-decision"},
        ]
    )

    with pytest.raises(ValueError, match=r"duplicate node_id values: a, b"):
        build_issue_batch_graph(nodes)


def test_resolved_missing_and_self_dependencies_remain_explicit():
    graph = build_issue_batch_graph(load_issue_batch_fixture(fixture_nodes()))

    assert graph.resolved_dependencies == (
        ("issue-2", "issue-1"),
        ("issue-2", "issue-2"),
    )
    assert graph.unresolved_dependencies == (("issue-2", "missing"),)


def test_empty_input_produces_valid_empty_graph():
    assert build_issue_batch_graph(()) == IssueBatchGraph()


def test_public_collections_are_immutable_and_normalized():
    source_paths = ["b.py", "a.py", "a.py"]
    node = IssueBatchNode(
        node_id=" issue-1 ",
        readiness="ready",
        affected_paths=source_paths,
    )
    source_paths.append("c.py")
    graph = build_issue_batch_graph([node])

    assert graph.nodes == (node,)
    assert node.node_id == "issue-1"
    assert node.affected_paths == ("a.py", "b.py")
    with pytest.raises(AttributeError):
        graph.nodes = ()


def test_readiness_is_preserved_without_reclassification():
    nodes = load_issue_batch_fixture(
        [
            {"node_id": "a", "readiness": "ready", "readiness_evidence": ["pass"]},
            {"node_id": "b", "readiness": "blocked", "readiness_evidence": ["fail"]},
            {
                "node_id": "c",
                "readiness": "needs-decision",
                "readiness_evidence": ["manual"],
            },
        ]
    )

    assert [node.readiness for node in nodes] == [
        ReadinessOutcome.READY,
        ReadinessOutcome.BLOCKED,
        ReadinessOutcome.NEEDS_DECISION,
    ]
    assert nodes[0].readiness_evidence == ("pass",)


def test_malformed_fixture_data_fails_closed():
    with pytest.raises(ValueError, match="unknown fields: surprise"):
        load_issue_batch_fixture(
            [{"node_id": "a", "readiness": "ready", "surprise": True}]
        )
    with pytest.raises(ValueError, match="missing required fields: readiness"):
        load_issue_batch_fixture([{"node_id": "a"}])
    with pytest.raises(ValueError, match="unknown readiness value"):
        load_issue_batch_fixture([{"node_id": "a", "readiness": "maybe"}])
    with pytest.raises(TypeError, match="affected_paths must be an iterable"):
        load_issue_batch_fixture(
            [{"node_id": "a", "readiness": "ready", "affected_paths": "a.py"}]
        )


def test_graph_build_is_offline_and_does_not_open_sockets(monkeypatch):
    def fail_socket(*args, **kwargs):
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(socket, "socket", fail_socket)
    graph = build_issue_batch_graph(load_issue_batch_fixture(fixture_nodes()))

    assert len(graph.nodes) == 2
