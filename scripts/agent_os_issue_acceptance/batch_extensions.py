from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .batch_graph import IssueBatchGraph
from .models import CheckResult, Status

DependencyPair = tuple[str, str]


@dataclass(frozen=True)
class GraphCheckResult:
    checks: tuple[CheckResult, ...]
    quarantined_node_ids: tuple[str, ...] = field(default_factory=tuple)
    inspected_node_ids: tuple[str, ...] = field(default_factory=tuple)
    inspected_dependency_pairs: tuple[DependencyPair, ...] = field(
        default_factory=tuple
    )


class GraphCheck(Protocol):
    check_id: str

    def __call__(self, graph: IssueBatchGraph) -> GraphCheckResult: ...


@dataclass(frozen=True)
class GraphCheckRun:
    checks: tuple[CheckResult, ...]
    quarantined_node_ids: tuple[str, ...]
    inspected_node_ids: tuple[str, ...]
    inspected_dependency_pairs: tuple[DependencyPair, ...]
    failed_check_ids: tuple[str, ...]


def run_graph_checks(
    graph: IssueBatchGraph,
    checks: tuple[GraphCheck, ...],
) -> GraphCheckRun:
    """Run graph checks deterministically and return a bounded snapshot."""
    if not isinstance(graph, IssueBatchGraph):
        raise TypeError("graph must be an IssueBatchGraph")
    if not isinstance(checks, tuple):
        raise TypeError("checks must be a tuple of GraphCheck values")

    identified: list[tuple[str, GraphCheck]] = []
    for check in checks:
        check_id = getattr(check, "check_id", None)
        if not isinstance(check_id, str) or not check_id.strip():
            raise ValueError(
                "each graph check must declare a non-empty check_id"
            )
        if not callable(check):
            raise TypeError(f"graph check {check_id!r} must be callable")
        identified.append((check_id, check))

    check_ids = [check_id for check_id, _ in identified]
    duplicates = sorted(
        check_id for check_id in set(check_ids) if check_ids.count(check_id) > 1
    )
    if duplicates:
        raise ValueError(f"duplicate check_id values: {', '.join(duplicates)}")

    known_node_ids = {node.node_id for node in graph.nodes}
    known_pairs = set(graph.resolved_dependencies) | set(
        graph.unresolved_dependencies
    )
    output_checks: list[CheckResult] = []
    quarantined: set[str] = set()
    inspected_nodes: set[str] = set()
    inspected_pairs: set[DependencyPair] = set()
    failed_ids: set[str] = set()

    for check_id, check in sorted(identified, key=lambda item: item[0]):
        try:
            result = check(graph)
        except Exception as exc:  # noqa: BLE001 - extension safety boundary
            failed_ids.add(check_id)
            output_checks.append(
                _failure_result(
                    check_id,
                    "exception",
                    extra=f"exception_type={type(exc).__name__}",
                )
            )
            continue

        failure = _validate_result(result, known_node_ids, known_pairs)
        if failure is not None:
            failed_ids.add(check_id)
            output_checks.append(_failure_result(check_id, failure))
            continue

        assert isinstance(result, GraphCheckResult)
        output_checks.extend(_copy_check_result(item) for item in result.checks)
        quarantined.update(result.quarantined_node_ids)
        inspected_nodes.update(result.inspected_node_ids)
        inspected_pairs.update(result.inspected_dependency_pairs)

    return GraphCheckRun(
        checks=tuple(output_checks),
        quarantined_node_ids=tuple(sorted(quarantined)),
        inspected_node_ids=tuple(sorted(inspected_nodes)),
        inspected_dependency_pairs=tuple(sorted(inspected_pairs)),
        failed_check_ids=tuple(sorted(failed_ids)),
    )


def _validate_result(
    result: object,
    known_node_ids: set[str],
    known_pairs: set[DependencyPair],
) -> str | None:
    if not isinstance(result, GraphCheckResult):
        return "malformed-output"
    if not isinstance(result.checks, tuple) or any(
        not _valid_check_result(item) for item in result.checks
    ):
        return "malformed-output"

    for values in (
        result.quarantined_node_ids,
        result.inspected_node_ids,
    ):
        if not isinstance(values, tuple) or any(
            not isinstance(value, str) or not value for value in values
        ):
            return "malformed-output"
        if any(value not in known_node_ids for value in values):
            return "unknown-node-id"

    if not isinstance(result.inspected_dependency_pairs, tuple):
        return "malformed-output"
    for pair in result.inspected_dependency_pairs:
        if (
            not isinstance(pair, tuple)
            or len(pair) != 2
            or any(not isinstance(value, str) or not value for value in pair)
        ):
            return "malformed-output"
        if pair not in known_pairs:
            return "unknown-dependency-pair"
    return None


def _valid_check_result(result: object) -> bool:
    return (
        isinstance(result, CheckResult)
        and isinstance(result.name, str)
        and bool(result.name)
        and isinstance(result.status, Status)
        and isinstance(result.message, str)
        and bool(result.message)
        and isinstance(result.evidence, list)
        and all(isinstance(value, str) for value in result.evidence)
    )


def _copy_check_result(result: CheckResult) -> CheckResult:
    return CheckResult(
        name=result.name,
        status=result.status,
        message=result.message,
        evidence=list(result.evidence),
    )


def _failure_result(
    check_id: str,
    failure: str,
    *,
    extra: str | None = None,
) -> CheckResult:
    evidence = [f"check_id={check_id}", f"failure={failure}"]
    if extra is not None:
        evidence.append(extra)
    return CheckResult(
        name=f"graph check {check_id}",
        status=Status.MANUAL_REVIEW,
        message="Graph check failed safely and requires review.",
        evidence=evidence,
    )
