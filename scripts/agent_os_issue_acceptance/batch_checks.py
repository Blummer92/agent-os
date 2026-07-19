from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from .batch_graph import IssueBatchGraph, IssueBatchNode
from .models import CheckResult, Status
from .path_contract import (
    DeclaredPathError,
    declared_path_matches,
    normalize_declared_path,
    normalize_declared_pattern,
)

NodePair = tuple[str, str]


@dataclass(frozen=True, order=True)
class ForbiddenPathCrossing:
    affected_node_id: str
    forbidden_node_id: str
    path: str
    pattern: str


@dataclass(frozen=True)
class BatchConflictRun:
    checks: tuple[CheckResult, ...]
    malformed_path_node_ids: tuple[str, ...]
    sequencing_pairs: tuple[NodePair, ...]
    forbidden_crossings: tuple[ForbiddenPathCrossing, ...]
    owner_conflict_node_ids: tuple[str, ...]
    source_of_truth_conflict_node_ids: tuple[str, ...]
    missing_owner_node_ids: tuple[str, ...]
    missing_source_of_truth_node_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "checks",
            tuple(_copy_check_result(result) for result in self.checks),
        )


def evaluate_base_batch_conflict_run(graph: IssueBatchGraph) -> BatchConflictRun:
    """Return deterministic conflict checks and machine-readable planning facts."""
    if not isinstance(graph, IssueBatchGraph):
        raise TypeError("graph must be an IssueBatchGraph")

    nodes = tuple(sorted(graph.nodes, key=lambda node: node.node_id))
    syntax, affected, forbidden, malformed = _validate_declared_paths(nodes)
    exact, exact_pairs = _check_exact_path_overlap(nodes, affected)
    directory, directory_pairs = _check_directory_path_overlap(nodes, affected)
    forbidden_check, crossings = _check_forbidden_path_conflicts(
        nodes, affected, forbidden
    )
    owner, owner_conflicts = _check_owner_compatibility(nodes)
    source, source_conflicts = _check_source_of_truth_compatibility(nodes)
    metadata, missing_owner, missing_source = _check_required_metadata(nodes)

    return BatchConflictRun(
        checks=(
            syntax,
            exact,
            directory,
            forbidden_check,
            owner,
            source,
            metadata,
        ),
        malformed_path_node_ids=tuple(sorted(malformed)),
        sequencing_pairs=tuple(sorted(exact_pairs | directory_pairs)),
        forbidden_crossings=tuple(sorted(crossings)),
        owner_conflict_node_ids=tuple(sorted(owner_conflicts)),
        source_of_truth_conflict_node_ids=tuple(sorted(source_conflicts)),
        missing_owner_node_ids=tuple(sorted(missing_owner)),
        missing_source_of_truth_node_ids=tuple(sorted(missing_source)),
    )


def evaluate_base_batch_conflicts(graph: IssueBatchGraph) -> tuple[CheckResult, ...]:
    """Return the backward-compatible seven-result conflict evidence contract."""
    return evaluate_base_batch_conflict_run(graph).checks


def _validate_declared_paths(
    nodes: tuple[IssueBatchNode, ...],
) -> tuple[
    CheckResult,
    dict[str, set[str]],
    dict[str, set[str]],
    set[str],
]:
    evidence: set[str] = set()
    affected: dict[str, set[str]] = {}
    forbidden: dict[str, set[str]] = {}
    malformed_node_ids: set[str] = set()

    for node in nodes:
        affected[node.node_id] = set()
        forbidden[node.node_id] = set()
        for value in node.affected_paths:
            try:
                affected[node.node_id].add(normalize_declared_path(value))
            except DeclaredPathError as error:
                malformed_node_ids.add(node.node_id)
                evidence.add(
                    _syntax_evidence(
                        node.node_id, "affected_paths", value, error.code
                    )
                )
        for value in node.forbidden_paths:
            try:
                forbidden[node.node_id].add(normalize_declared_pattern(value))
            except DeclaredPathError as error:
                malformed_node_ids.add(node.node_id)
                evidence.add(
                    _syntax_evidence(
                        node.node_id, "forbidden_paths", value, error.code
                    )
                )

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
        malformed_node_ids,
    )


def _check_exact_path_overlap(
    nodes: tuple[IssueBatchNode, ...], affected: dict[str, set[str]]
) -> tuple[CheckResult, set[NodePair]]:
    evidence: set[str] = set()
    pairs: set[NodePair] = set()
    for left, right in combinations(nodes, 2):
        overlaps = affected[left.node_id] & affected[right.node_id]
        if overlaps:
            pairs.add(_canonical_pair(left.node_id, right.node_id))
        evidence.update(
            f"nodes={left.node_id},{right.node_id}; path={path}" for path in overlaps
        )
    return (
        _result(
            name="batch exact path overlap",
            status=Status.WARN if evidence else Status.PASS,
            conflict_message="Exact affected-path overlap requires sequencing review.",
            pass_message="No exact affected-path overlap was found.",
            evidence=evidence,
        ),
        pairs,
    )


def _check_directory_path_overlap(
    nodes: tuple[IssueBatchNode, ...], affected: dict[str, set[str]]
) -> tuple[CheckResult, set[NodePair]]:
    evidence: set[str] = set()
    pairs: set[NodePair] = set()
    for left, right in combinations(nodes, 2):
        pair_has_overlap = False
        for left_path in affected[left.node_id]:
            for right_path in affected[right.node_id]:
                if left_path == right_path or not _directory_overlap(
                    left_path, right_path
                ):
                    continue
                pair_has_overlap = True
                first, second = sorted((left_path, right_path))
                evidence.add(
                    f"nodes={left.node_id},{right.node_id}; paths={first},{second}"
                )
        if pair_has_overlap:
            pairs.add(_canonical_pair(left.node_id, right.node_id))
    return (
        _result(
            name="batch directory path overlap",
            status=Status.WARN if evidence else Status.PASS,
            conflict_message="Directory-prefix overlap requires sequencing review.",
            pass_message="No directory-prefix overlap was found.",
            evidence=evidence,
        ),
        pairs,
    )


def _check_forbidden_path_conflicts(
    nodes: tuple[IssueBatchNode, ...],
    affected: dict[str, set[str]],
    forbidden: dict[str, set[str]],
) -> tuple[CheckResult, set[ForbiddenPathCrossing]]:
    evidence: set[str] = set()
    crossings: set[ForbiddenPathCrossing] = set()
    for affected_node in nodes:
        for path in affected[affected_node.node_id]:
            for boundary_node in nodes:
                for pattern in forbidden[boundary_node.node_id]:
                    if declared_path_matches(path, pattern):
                        crossing = ForbiddenPathCrossing(
                            affected_node_id=affected_node.node_id,
                            forbidden_node_id=boundary_node.node_id,
                            path=path,
                            pattern=pattern,
                        )
                        crossings.add(crossing)
                        evidence.add(
                            "affected_node="
                            f"{crossing.affected_node_id}; forbidden_node="
                            f"{crossing.forbidden_node_id}; path={crossing.path}; "
                            f"pattern={crossing.pattern}"
                        )
    return (
        _result(
            name="batch forbidden path conflict",
            status=Status.FAIL if evidence else Status.PASS,
            conflict_message="Affected paths cross an explicit forbidden-path boundary.",
            pass_message="No affected path crosses a forbidden-path boundary.",
            evidence=evidence,
        ),
        crossings,
    )


def _check_owner_compatibility(
    nodes: tuple[IssueBatchNode, ...],
) -> tuple[CheckResult, set[str]]:
    observed = {node.owner for node in nodes if node.owner is not None}
    evidence = {
        f"node={node.node_id}; owner={node.owner}"
        for node in nodes
        if node.owner is not None
    }
    conflict_node_ids = (
        {node.node_id for node in nodes if node.owner is not None}
        if len(observed) > 1
        else set()
    )
    return (
        _result(
            name="batch owner compatibility",
            status=Status.MANUAL_REVIEW if len(observed) > 1 else Status.PASS,
            conflict_message="Differing owners require a compatibility decision.",
            pass_message="Non-empty owner evidence is compatible.",
            evidence=evidence if len(observed) > 1 else set(),
        ),
        conflict_node_ids,
    )


def _check_source_of_truth_compatibility(
    nodes: tuple[IssueBatchNode, ...],
) -> tuple[CheckResult, set[str]]:
    observed = {
        node.source_of_truth for node in nodes if node.source_of_truth is not None
    }
    evidence = {
        f"node={node.node_id}; source_of_truth={node.source_of_truth}"
        for node in nodes
        if node.source_of_truth is not None
    }
    conflict_node_ids = (
        {node.node_id for node in nodes if node.source_of_truth is not None}
        if len(observed) > 1
        else set()
    )
    return (
        _result(
            name="batch source-of-truth compatibility",
            status=Status.MANUAL_REVIEW if len(observed) > 1 else Status.PASS,
            conflict_message="Differing sources of truth require a compatibility decision.",
            pass_message="Non-empty source-of-truth evidence is compatible.",
            evidence=evidence if len(observed) > 1 else set(),
        ),
        conflict_node_ids,
    )


def _check_required_metadata(
    nodes: tuple[IssueBatchNode, ...],
) -> tuple[CheckResult, set[str], set[str]]:
    evidence: set[str] = set()
    missing_owner: set[str] = set()
    missing_source: set[str] = set()
    for node in nodes:
        if node.owner is None:
            missing_owner.add(node.node_id)
            evidence.add(f"node={node.node_id}; missing=owner")
        if node.source_of_truth is None:
            missing_source.add(node.node_id)
            evidence.add(f"node={node.node_id}; missing=source_of_truth")
    return (
        _result(
            name="batch required metadata",
            status=Status.MANUAL_REVIEW if evidence else Status.PASS,
            conflict_message="Required batch-planning metadata is missing.",
            pass_message="Required owner and source-of-truth metadata is present.",
            evidence=evidence,
        ),
        missing_owner,
        missing_source,
    )


def _copy_check_result(result: CheckResult) -> CheckResult:
    return CheckResult(
        name=result.name,
        status=result.status,
        message=result.message,
        evidence=list(result.evidence),
    )


def _canonical_pair(left: str, right: str) -> NodePair:
    first, second = sorted((left, right))
    return first, second


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
