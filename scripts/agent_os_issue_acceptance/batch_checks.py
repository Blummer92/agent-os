from __future__ import annotations

from fnmatch import fnmatch
from itertools import combinations

from .batch_graph import IssueBatchGraph, IssueBatchNode
from .models import CheckResult, Status


def evaluate_base_batch_conflicts(graph: IssueBatchGraph) -> tuple[CheckResult, ...]:
    """Return deterministic, report-only conflict evidence for one issue batch."""
    if not isinstance(graph, IssueBatchGraph):
        raise TypeError("graph must be an IssueBatchGraph")

    nodes = tuple(sorted(graph.nodes, key=lambda node: node.node_id))
    return (
        _check_exact_path_overlap(nodes),
        _check_directory_path_overlap(nodes),
        _check_forbidden_path_conflicts(nodes),
        _check_owner_compatibility(nodes),
        _check_source_of_truth_compatibility(nodes),
        _check_required_metadata(nodes),
    )


def _check_exact_path_overlap(nodes: tuple[IssueBatchNode, ...]) -> CheckResult:
    evidence: set[str] = set()
    for left, right in combinations(nodes, 2):
        overlaps = _normalized_paths(left.affected_paths) & _normalized_paths(
            right.affected_paths
        )
        evidence.update(
            f"nodes={left.node_id},{right.node_id}; path={path}"
            for path in overlaps
        )
    return _result(
        name="batch exact path overlap",
        status=Status.WARN if evidence else Status.PASS,
        conflict_message="Exact affected-path overlap requires sequencing review.",
        pass_message="No exact affected-path overlap was found.",
        evidence=evidence,
    )


def _check_directory_path_overlap(nodes: tuple[IssueBatchNode, ...]) -> CheckResult:
    evidence: set[str] = set()
    for left, right in combinations(nodes, 2):
        for left_path in _normalized_paths(left.affected_paths):
            for right_path in _normalized_paths(right.affected_paths):
                if left_path == right_path or not _directory_overlap(
                    left_path, right_path
                ):
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
) -> CheckResult:
    evidence: set[str] = set()
    for affected_node in nodes:
        for path in _normalized_paths(affected_node.affected_paths):
            for boundary_node in nodes:
                for pattern in _normalized_paths(boundary_node.forbidden_paths):
                    if _forbidden_path_matches(path, pattern):
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


def _normalized_paths(paths: tuple[str, ...]) -> set[str]:
    return {_normalize_path(path) for path in paths}


def _normalize_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = "/".join(part for part in normalized.split("/") if part)
    return normalized or "/"


def _directory_overlap(left: str, right: str) -> bool:
    return left.startswith(right.rstrip("/") + "/") or right.startswith(
        left.rstrip("/") + "/"
    )


def _forbidden_path_matches(path: str, pattern: str) -> bool:
    if any(character in pattern for character in "*?["):
        return fnmatch(path, pattern)
    return path == pattern or _directory_overlap(path, pattern)
