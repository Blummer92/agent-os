from __future__ import annotations

from itertools import combinations

from .batch_graph import IssueBatchGraph, IssueBatchNode
from .models import CheckResult, Status
from .path_contract import (
    DeclaredPathError,
    declared_path_matches,
    normalize_declared_path,
    normalize_declared_pattern,
)


def evaluate_base_batch_conflicts(graph: IssueBatchGraph) -> tuple[CheckResult, ...]:
    """Return deterministic, report-only conflict evidence for one issue batch."""
    if not isinstance(graph, IssueBatchGraph):
        raise TypeError("graph must be an IssueBatchGraph")

    nodes = tuple(sorted(graph.nodes, key=lambda node: node.node_id))
    syntax, affected, forbidden = _validate_declared_paths(nodes)
    return (
        syntax,
        _check_exact_path_overlap(nodes, affected),
        _check_directory_path_overlap(nodes, affected),
        _check_forbidden_path_conflicts(nodes, affected, forbidden),
        _check_owner_compatibility(nodes),
        _check_source_of_truth_compatibility(nodes),
        _check_required_metadata(nodes),
    )


def _validate_declared_paths(
    nodes: tuple[IssueBatchNode, ...],
) -> tuple[CheckResult, dict[str, set[str]], dict[str, set[str]]]:
    evidence: set[str] = set()
    affected: dict[str, set[str]] = {}
    forbidden: dict[str, set[str]] = {}

    for node in nodes:
        affected[node.node_id] = set()
        forbidden[node.node_id] = set()
        for value in node.affected_paths:
            try:
                affected[node.node_id].add(normalize_declared_path(value))
            except DeclaredPathError as error:
                evidence.add(_syntax_evidence(node.node_id, "affected_paths", value, error.code))
        for value in node.forbidden_paths:
            try:
                forbidden[node.node_id].add(normalize_declared_pattern(value))
            except DeclaredPathError as error:
                evidence.add(_syntax_evidence(node.node_id, "forbidden_paths", value, error.code))

    return (
        _result(
            name="batch declared path syntax",
            status=Status.MANUAL_REVIEW if evidence else Status.PASS,
            conflict_message="Malformed declared paths or patterns require human review.",
            pass_message="Declared paths and patterns use the approved bounded syntax.",
            evidence=evidence,
        ),
        affected,
        forbidden,
    )


def _check_exact_path_overlap(
    nodes: tuple[IssueBatchNode, ...], affected: dict[str, set[str]]
) -> CheckResult:
    evidence: set[str] = set()
    for left, right in combinations(nodes, 2):
        overlaps = affected[left.node_id] & affected[right.node_id]
        evidence.update(
            f"nodes={left.node_id},{right.node_id}; path={path}" for path in overlaps
        )
    return _result(
        name="batch exact path overlap",
        status=Status.WARN if evidence else Status.PASS,
        conflict_message="Exact affected-path overlap requires sequencing review.",
        pass_message="No exact affected-path overlap was found.",
        evidence=evidence,
    )


def _check_directory_path_overlap(
    nodes: tuple[IssueBatchNode, ...], affected: dict[str, set[str]]
) -> CheckResult:
    evidence: set[str] = set()
    for left, right in combinations(nodes, 2):
        for left_path in affected[left.node_id]:
            for right_path in affected[right.node_id]:
                if left_path == right_path or not _directory_overlap(left_path, right_path):
                    continue
                first, second = sorted((left_path, right_path))
                evidence.add(
                    f"nodes={left.node_id},{right.node_id}; paths={first},{second}"
                )
    return _result(
        name="batch directory path overlap",
        status=Status.WARN if evidence else Status.PASS,
        conflict_message="Directory-prefix overlap requires sequencing review.",
        pass_message="No directory-prefix overlap was found.",
        evidence=evidence,
    )


def _check_forbidden_path_conflicts(
    nodes: tuple[IssueBatchNode, ...],
    affected: dict[str, set[str]],
    forbidden: dict[str, set[str]],
) -> CheckResult:
    evidence: set[str] = set()
    for affected_node in nodes:
        for path in affected[affected_node.node_id]:
            for boundary_node in nodes:
                for pattern in forbidden[boundary_node.node_id]:
                    if declared_path_matches(path, pattern):
                        evidence.add(
                            "affected_node="
                            f"{affected_node.node_id}; forbidden_node="
                            f"{boundary_node.node_id}; path={path}; pattern={pattern}"
                        )
    return _result(
        name="batch forbidden path conflict",
        status=Status.FAIL if evidence else Status.PASS,
        conflict_message="Affected paths cross an explicit forbidden-path boundary.",
        pass_message="No affected path crosses a forbidden-path boundary.",
        evidence=evidence,
    )


def _check_owner_compatibility(nodes: tuple[IssueBatchNode, ...]) -> CheckResult:
    observed = {node.owner for node in nodes if node.owner is not None}
    evidence = {
        f"node={node.node_id}; owner={node.owner}"
        for node in nodes
        if node.owner is not None
    }
    return _result(
        name="batch owner compatibility",
        status=Status.MANUAL_REVIEW if len(observed) > 1 else Status.PASS,
        conflict_message="Differing owners require a compatibility decision.",
        pass_message="Non-empty owner evidence is compatible.",
        evidence=evidence if len(observed) > 1 else set(),
    )


def _check_source_of_truth_compatibility(
    nodes: tuple[IssueBatchNode, ...],
) -> CheckResult:
    observed = {
        node.source_of_truth for node in nodes if node.source_of_truth is not None
    }
    evidence = {
        f"node={node.node_id}; source_of_truth={node.source_of_truth}"
        for node in nodes
        if node.source_of_truth is not None
    }
    return _result(
        name="batch source-of-truth compatibility",
        status=Status.MANUAL_REVIEW if len(observed) > 1 else Status.PASS,
        conflict_message="Differing sources of truth require a compatibility decision.",
        pass_message="Non-empty source-of-truth evidence is compatible.",
        evidence=evidence if len(observed) > 1 else set(),
    )


def _check_required_metadata(nodes: tuple[IssueBatchNode, ...]) -> CheckResult:
    evidence: set[str] = set()
    for node in nodes:
        if node.owner is None:
            evidence.add(f"node={node.node_id}; missing=owner")
        if node.source_of_truth is None:
            evidence.add(f"node={node.node_id}; missing=source_of_truth")
    return _result(
        name="batch required metadata",
        status=Status.MANUAL_REVIEW if evidence else Status.PASS,
        conflict_message="Required batch-planning metadata is missing.",
        pass_message="Required owner and source-of-truth metadata is present.",
        evidence=evidence,
    )


def _result(
    *,
    name: str,
    status: Status,
    conflict_message: str,
    pass_message: str,
    evidence: set[str],
) -> CheckResult:
    return CheckResult(
        name=name,
        status=status,
        message=pass_message if status == Status.PASS else conflict_message,
        evidence=sorted(evidence),
    )


def _directory_overlap(left: str, right: str) -> bool:
    return left.startswith(f"{right}/") or right.startswith(f"{left}/")


def _syntax_evidence(node_id: str, field: str, value: object, code: str) -> str:
    bounded_value = repr(value)
    if len(bounded_value) > 120:
        bounded_value = f"{bounded_value[:117]}..."
    return f"node={node_id}; field={field}; value={bounded_value}; code={code}"
