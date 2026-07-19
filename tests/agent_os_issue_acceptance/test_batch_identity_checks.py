import builtins
import socket

import pytest

from scripts.agent_os_issue_acceptance import (
    entity_id_collision_check,
    run_graph_checks,
)
from scripts.agent_os_issue_acceptance.batch_graph import (
    IssueBatchGraph,
    IssueBatchNode,
)
from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome


def node(node_id: str, entity_id: str | None = None) -> IssueBatchNode:
    return IssueBatchNode(
        node_id=node_id,
        readiness=ReadinessOutcome.READY,
        entity_id=entity_id,
    )


def graph(*nodes: IssueBatchNode) -> IssueBatchGraph:
    return IssueBatchGraph(nodes=tuple(nodes))


def test_empty_single_distinct_and_missing_id_graphs_pass():
    for supplied in (
        graph(),
        graph(node("a", "id-1")),
        graph(node("a", "id-1"), node("b", "id-2")),
        graph(node("a"), node("b")),
    ):
        result = entity_id_collision_check(supplied)
        assert result.checks[0].status == Status.PASS
        assert result.quarantined_node_ids == ()


def test_duplicate_pair_and_triple_quarantine_every_node():
    pair = entity_id_collision_check(
        graph(node("b", "same"), node("a", "same"))
    )
    assert pair.checks[0].status == Status.MANUAL_REVIEW
    assert pair.quarantined_node_ids == ("a", "b")
    assert pair.checks[0].evidence == ["entity_id=same; nodes=a,b"]

    triple = entity_id_collision_check(
        graph(
            node("c", "same"),
            node("a", "same"),
            node("b", "same"),
        )
    )
    assert triple.quarantined_node_ids == ("a", "b", "c")


def test_multiple_collision_groups_are_sorted_and_deterministic():
    supplied = graph(
        node("d", "z-id"),
        node("a", "a-id"),
        node("c", "z-id"),
        node("b", "a-id"),
    )
    first = entity_id_collision_check(supplied)
    second = entity_id_collision_check(supplied)
    assert first == second
    assert first.checks[0].evidence == [
        "entity_id=a-id; nodes=a,b",
        "entity_id=z-id; nodes=c,d",
    ]
    assert first.quarantined_node_ids == ("a", "b", "c", "d")


def test_check_reports_complete_node_coverage_and_no_pair_coverage():
    result = entity_id_collision_check(
        graph(node("b"), node("a", "id"))
    )
    assert result.inspected_node_ids == ("a", "b")
    assert result.inspected_dependency_pairs == ()


def test_check_runs_through_graph_extension_protocol():
    run = run_graph_checks(
        graph(node("b", "same"), node("a", "same")),
        (entity_id_collision_check,),
    )
    assert run.failed_check_ids == ()
    assert run.quarantined_node_ids == ("a", "b")
    assert run.checks[0].name == "batch entity-id collision"


def test_check_is_offline_and_does_not_mutate_graph(monkeypatch):
    supplied = graph(node("b", "same"), node("a", "same"))
    before = repr(supplied)
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *args, **kwargs: pytest.fail("unexpected socket use"),
    )
    monkeypatch.setattr(
        builtins,
        "open",
        lambda *args, **kwargs: pytest.fail("unexpected file access"),
    )
    entity_id_collision_check(supplied)
    assert repr(supplied) == before
