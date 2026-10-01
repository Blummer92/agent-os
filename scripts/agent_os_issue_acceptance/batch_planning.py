from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator, Literal

from .batch_checks import BatchConflictRun, evaluate_base_batch_conflict_run
from .batch_extensions import GraphCheckResult, GraphCheckRun, run_graph_checks
from .batch_graph import IssueBatchGraph
from .batch_identity_checks import entity_id_collision_check
from .batch_scope_checks import evaluate_input_scope_coverage, unresolved_dependency_check
from .models import Status
from .readiness import ReadinessOutcome

Pair = tuple[str, str]


class PlanningClassification(str, Enum):
    PARALLEL_CANDIDATE = "parallel-candidate"
    SEQUENCING_REVIEW = "sequencing-review"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs-decision"


_RANK = {
    PlanningClassification.PARALLEL_CANDIDATE: 0,
    PlanningClassification.SEQUENCING_REVIEW: 1,
    PlanningClassification.NEEDS_DECISION: 2,
    PlanningClassification.BLOCKED: 3,
}
_ORDER = {
    PlanningClassification.BLOCKED: 0,
    PlanningClassification.NEEDS_DECISION: 1,
    PlanningClassification.SEQUENCING_REVIEW: 2,
    PlanningClassification.PARALLEL_CANDIDATE: 3,
}


@dataclass(frozen=True)
class PlanningCohort:
    node_ids: tuple[str, ...]
    classification: PlanningClassification
    reason_codes: tuple[str, ...]
    dependency_pairs: tuple[Pair, ...] = ()
    sequencing_pairs: tuple[Pair, ...] = ()


@dataclass(frozen=True)
class BatchPlanningResult:
    supplied_node_ids: tuple[str, ...]
    overall_classification: PlanningClassification
    cohorts: tuple[PlanningCohort, ...]
    batch_reason_codes: tuple[str, ...] = ()
    cycle_node_groups: tuple[tuple[str, ...], ...] = ()
    planning_scope: Literal["supplied-graph-only"] = field(
        default="supplied-graph-only", init=False
    )
    execution_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        seen = tuple(sorted(n for cohort in self.cohorts for n in cohort.node_ids))
        if seen != self.supplied_node_ids or len(seen) != len(set(seen)):
            raise ValueError("cohorts must contain each supplied node exactly once")
        if self.overall_classification is not _strongest(
            cohort.classification for cohort in self.cohorts
        ):
            raise ValueError("overall classification must match cohort precedence")


class _ResolvedDependencyInspection:
    check_id = "relationships.resolved-dependencies"

    def __call__(self, graph: IssueBatchGraph) -> GraphCheckResult:
        return GraphCheckResult(
            checks=(),
            inspected_dependency_pairs=tuple(sorted(set(graph.resolved_dependencies))),
        )


_resolved_dependency_inspection = _ResolvedDependencyInspection()


def evaluate_batch_plan(graph: IssueBatchGraph) -> BatchPlanningResult:
    """Evaluate one supplied graph without authorizing execution."""
    if not isinstance(graph, IssueBatchGraph):
        raise TypeError("graph must be an IssueBatchGraph")
    supplied = tuple(sorted(node.node_id for node in graph.nodes))
    if not supplied:
        return BatchPlanningResult(
            (), PlanningClassification.NEEDS_DECISION, (), ("empty-supplied-graph",)
        )

    conflicts = evaluate_base_batch_conflict_run(graph)
    run = _run_canonical_graph_checks(graph)
    coverage = evaluate_input_scope_coverage(graph, run)
    self_loops, cycles = _cycles(graph)
    classes, reasons = _classify(
        graph, conflicts, run, coverage.status, self_loops, cycles
    )
    cohorts = _build_cohorts(graph, conflicts, classes, reasons)
    batch_reasons: list[str] = []
    if run.failed_check_ids:
        batch_reasons.append("graph-check-failure")
    if coverage.status is not Status.PASS:
        batch_reasons.append("incomplete-supplied-graph-coverage")
    return BatchPlanningResult(
        supplied,
        _strongest(cohort.classification for cohort in cohorts),
        cohorts,
        tuple(batch_reasons),
        cycles,
    )


def _run_canonical_graph_checks(graph: IssueBatchGraph) -> GraphCheckRun:
    return run_graph_checks(
        graph,
        (
            entity_id_collision_check,
            unresolved_dependency_check,
            _resolved_dependency_inspection,
        ),
    )


def _classify(
    graph: IssueBatchGraph,
    conflicts: BatchConflictRun,
    run: GraphCheckRun,
    coverage: Status,
    self_loops: tuple[str, ...],
    cycles: tuple[tuple[str, ...], ...],
) -> tuple[dict[str, PlanningClassification], dict[str, set[str]]]:
    classes = {n.node_id: PlanningClassification.PARALLEL_CANDIDATE for n in graph.nodes}
    reasons = {n.node_id: set() for n in graph.nodes}
    for node in graph.nodes:
        if node.readiness is ReadinessOutcome.BLOCKED:
            _mark(classes, reasons, (node.node_id,), PlanningClassification.BLOCKED, "readiness-blocked")
        elif node.readiness is ReadinessOutcome.NEEDS_DECISION:
            _mark(classes, reasons, (node.node_id,), PlanningClassification.NEEDS_DECISION, "readiness-needs-decision")

    _mark(
        classes,
        reasons,
        (crossing.affected_node_id for crossing in conflicts.forbidden_crossings),
        PlanningClassification.BLOCKED,
        "forbidden-path-crossing",
    )
    review = (
        (conflicts.malformed_path_node_ids, "malformed-declared-path"),
        (conflicts.owner_conflict_node_ids, "owner-conflict"),
        (conflicts.source_of_truth_conflict_node_ids, "source-of-truth-conflict"),
        (conflicts.missing_owner_node_ids, "missing-owner"),
        (conflicts.missing_source_of_truth_node_ids, "missing-source-of-truth"),
        (run.quarantined_node_ids, "identity-quarantine"),
        (tuple(source for source, _ in graph.unresolved_dependencies), "unresolved-dependency"),
        (self_loops, "self-dependency"),
        (tuple(node for group in cycles for node in group), "dependency-cycle"),
    )
    for nodes, code in review:
        _mark(classes, reasons, nodes, PlanningClassification.NEEDS_DECISION, code)
    if run.failed_check_ids:
        _mark(classes, reasons, classes, PlanningClassification.NEEDS_DECISION, "graph-check-failure")
    if coverage is not Status.PASS:
        _mark(classes, reasons, classes, PlanningClassification.NEEDS_DECISION, "incomplete-supplied-graph-coverage")
    _mark_pairs(classes, reasons, conflicts.sequencing_pairs, "path-overlap")
    _mark_pairs(classes, reasons, graph.resolved_dependencies, "resolved-dependency")
    for codes in reasons.values():
        if not codes:
            codes.add("covered-no-deterministic-conflict")
    return classes, reasons


def _mark_pairs(classes, reasons, pairs: tuple[Pair, ...], code: str) -> None:
    for left, right in pairs:
        _mark(
            classes,
            reasons,
            (left, right),
            PlanningClassification.SEQUENCING_REVIEW,
            code,
        )


def _mark(classes, reasons, nodes, classification, code: str) -> None:
    for node in nodes:
        if node not in classes:
            continue
        reasons[node].add(code)
        if _RANK[classification] > _RANK[classes[node]]:
            classes[node] = classification


def _build_cohorts(graph, conflicts, classes, reasons) -> tuple[PlanningCohort, ...]:
    result: list[PlanningCohort] = []
    for classification in (
        PlanningClassification.BLOCKED,
        PlanningClassification.NEEDS_DECISION,
    ):
        for node in sorted(n for n, value in classes.items() if value is classification):
            result.append(_cohort((node,), classification, reasons, graph, conflicts))
    sequencing = {
        n for n, value in classes.items()
        if value is PlanningClassification.SEQUENCING_REVIEW
    }
    edges = set(conflicts.sequencing_pairs) | set(graph.resolved_dependencies)
    for component in _components(sequencing, edges):
        result.append(
            _cohort(
                component,
                PlanningClassification.SEQUENCING_REVIEW,
                reasons,
                graph,
                conflicts,
            )
        )
    parallel = tuple(sorted(
        n for n, value in classes.items()
        if value is PlanningClassification.PARALLEL_CANDIDATE
    ))
    if parallel:
        result.append(
            _cohort(
                parallel,
                PlanningClassification.PARALLEL_CANDIDATE,
                reasons,
                graph,
                conflicts,
            )
        )
    return tuple(sorted(result, key=lambda item: (_ORDER[item.classification], item.node_ids)))


def _cohort(nodes, classification, reasons, graph, conflicts) -> PlanningCohort:
    members = set(nodes)
    dependencies = tuple(sorted(
        pair
        for pair in (*graph.resolved_dependencies, *graph.unresolved_dependencies)
        if pair[0] in members or pair[1] in members
    ))
    sequencing = tuple(
        pair for pair in conflicts.sequencing_pairs
        if pair[0] in members or pair[1] in members
    )
    return PlanningCohort(
        tuple(sorted(nodes)),
        classification,
        tuple(sorted({code for node in nodes for code in reasons[node]})),
        dependencies,
        sequencing,
    )


def _components(nodes: set[str], edges: set[Pair]) -> tuple[tuple[str, ...], ...]:
    adjacent = {node: set() for node in nodes}
    for left, right in edges:
        if left in nodes and right in nodes:
            adjacent[left].add(right)
            adjacent[right].add(left)
    output = []
    remaining = set(nodes)
    while remaining:
        stack, seen = [min(remaining)], set()
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(sorted(adjacent[node] - seen, reverse=True))
        remaining -= seen
        output.append(tuple(sorted(seen)))
    return tuple(sorted(output))


def _tarjan_scc(adjacent: dict[str, set[str]]) -> list[set[str]]:
    """Iterative Tarjan SCC over a sorted adjacency map.

    Returns the same SCC node sets the previous recursive Kosaraju pass
    produced; traversal order is internal because callers sort every result
    before exposing it. Iterative so deep graphs cannot hit the recursion
    limit (see #2275).
    """
    index_of: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    scc_stack: list[str] = []
    sccs: list[set[str]] = []
    index = 0
    for root in sorted(adjacent):
        if root in index_of:
            continue
        index_of[root] = lowlink[root] = index
        index += 1
        scc_stack.append(root)
        on_stack.add(root)
        work: list[tuple[str, Iterator[str]]] = [(root, iter(sorted(adjacent[root])))]
        while work:
            node, targets = work[-1]
            descended = False
            for target in targets:
                if target not in index_of:
                    index_of[target] = lowlink[target] = index
                    index += 1
                    scc_stack.append(target)
                    on_stack.add(target)
                    work.append((target, iter(sorted(adjacent[target]))))
                    descended = True
                    break
                if target in on_stack and index_of[target] < lowlink[node]:
                    lowlink[node] = index_of[target]
            if descended:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                if lowlink[node] < lowlink[parent]:
                    lowlink[parent] = lowlink[node]
            if lowlink[node] == index_of[node]:
                scc: set[str] = set()
                while True:
                    member = scc_stack.pop()
                    on_stack.discard(member)
                    scc.add(member)
                    if member == node:
                        break
                sccs.append(scc)
    return sccs


def _cycles(graph: IssueBatchGraph):
    adjacent = {node.node_id: set() for node in graph.nodes}
    self_loops = set()
    for source, target in graph.resolved_dependencies:
        adjacent[source].add(target)
        if source == target:
            self_loops.add(source)

    groups = [tuple(sorted(scc)) for scc in _tarjan_scc(adjacent) if len(scc) > 1]
    return tuple(sorted(self_loops)), tuple(sorted(groups))


def _strongest(values) -> PlanningClassification:
    items = tuple(values)
    return max(items, key=_RANK.__getitem__) if items else PlanningClassification.NEEDS_DECISION
