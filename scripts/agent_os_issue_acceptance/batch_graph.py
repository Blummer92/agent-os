from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .readiness import ReadinessOutcome

_FIXTURE_KEYS = {
    "node_id",
    "readiness",
    "readiness_evidence",
    "owner",
    "source_of_truth",
    "affected_paths",
    "forbidden_paths",
    "dependency_ids",
    "entity_id",
    "provenance",
}


@dataclass(frozen=True)
class IssueBatchNode:
    node_id: str
    readiness: ReadinessOutcome
    readiness_evidence: tuple[str, ...] = field(default_factory=tuple)
    owner: str | None = None
    source_of_truth: str | None = None
    affected_paths: tuple[str, ...] = field(default_factory=tuple)
    forbidden_paths: tuple[str, ...] = field(default_factory=tuple)
    dependency_ids: tuple[str, ...] = field(default_factory=tuple)
    entity_id: str | None = None
    provenance: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _required_string(self.node_id, "node_id"))
        object.__setattr__(self, "readiness", _readiness(self.readiness))
        object.__setattr__(
            self,
            "readiness_evidence",
            _string_tuple(self.readiness_evidence, "readiness_evidence"),
        )
        object.__setattr__(self, "owner", _optional_string(self.owner, "owner"))
        object.__setattr__(
            self,
            "source_of_truth",
            _optional_string(self.source_of_truth, "source_of_truth"),
        )
        object.__setattr__(
            self,
            "affected_paths",
            _string_tuple(self.affected_paths, "affected_paths"),
        )
        object.__setattr__(
            self,
            "forbidden_paths",
            _string_tuple(self.forbidden_paths, "forbidden_paths"),
        )
        object.__setattr__(
            self,
            "dependency_ids",
            _string_tuple(self.dependency_ids, "dependency_ids"),
        )
        object.__setattr__(
            self,
            "entity_id",
            _optional_string(self.entity_id, "entity_id"),
        )
        object.__setattr__(
            self,
            "provenance",
            _string_tuple(self.provenance, "provenance"),
        )


@dataclass(frozen=True)
class IssueBatchGraph:
    nodes: tuple[IssueBatchNode, ...] = field(default_factory=tuple)
    resolved_dependencies: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    unresolved_dependencies: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        nodes = tuple(self.nodes)
        if any(not isinstance(node, IssueBatchNode) for node in nodes):
            raise TypeError("nodes must contain only IssueBatchNode values")
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(
            self,
            "resolved_dependencies",
            _dependency_pairs(self.resolved_dependencies, "resolved_dependencies"),
        )
        object.__setattr__(
            self,
            "unresolved_dependencies",
            _dependency_pairs(self.unresolved_dependencies, "unresolved_dependencies"),
        )


def load_issue_batch_fixture(
    data: Iterable[Mapping[str, Any]],
) -> tuple[IssueBatchNode, ...]:
    """Load normalized local fixture data without parsing or external I/O."""
    if isinstance(data, (str, bytes, Mapping)) or not isinstance(data, Iterable):
        raise TypeError("fixture data must be an iterable of mappings")

    nodes: list[IssueBatchNode] = []
    for index, item in enumerate(data):
        if not isinstance(item, Mapping):
            raise TypeError(f"fixture item {index} must be a mapping")
        unknown = sorted(set(item) - _FIXTURE_KEYS)
        if unknown:
            raise ValueError(
                f"fixture item {index} has unknown fields: {', '.join(unknown)}"
            )
        missing = [key for key in ("node_id", "readiness") if key not in item]
        if missing:
            raise ValueError(
                f"fixture item {index} is missing required fields: {', '.join(missing)}"
            )
        nodes.append(
            IssueBatchNode(
                node_id=item["node_id"],
                readiness=item["readiness"],
                readiness_evidence=item.get("readiness_evidence", ()),
                owner=item.get("owner"),
                source_of_truth=item.get("source_of_truth"),
                affected_paths=item.get("affected_paths", ()),
                forbidden_paths=item.get("forbidden_paths", ()),
                dependency_ids=item.get("dependency_ids", ()),
                entity_id=item.get("entity_id"),
                provenance=item.get("provenance", ()),
            )
        )
    return tuple(nodes)


def build_issue_batch_graph(
    nodes: Iterable[IssueBatchNode],
) -> IssueBatchGraph:
    """Build one deterministic immutable graph from normalized local nodes."""
    if isinstance(nodes, (str, bytes, Mapping)) or not isinstance(nodes, Iterable):
        raise TypeError("nodes must be an iterable of IssueBatchNode values")

    supplied = tuple(nodes)
    if any(not isinstance(node, IssueBatchNode) for node in supplied):
        raise TypeError("nodes must contain only IssueBatchNode values")

    counts: dict[str, int] = {}
    for node in supplied:
        counts[node.node_id] = counts.get(node.node_id, 0) + 1
    duplicates = sorted(node_id for node_id, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate node_id values: {', '.join(duplicates)}")

    ordered_nodes = tuple(sorted(supplied, key=lambda node: node.node_id))
    known_ids = {node.node_id for node in ordered_nodes}
    resolved: list[tuple[str, str]] = []
    unresolved: list[tuple[str, str]] = []

    for node in ordered_nodes:
        for dependency_id in node.dependency_ids:
            pair = (node.node_id, dependency_id)
            if dependency_id in known_ids:
                resolved.append(pair)
            else:
                unresolved.append(pair)

    return IssueBatchGraph(
        nodes=ordered_nodes,
        resolved_dependencies=tuple(resolved),
        unresolved_dependencies=tuple(unresolved),
    )


def _readiness(value: object) -> ReadinessOutcome:
    if isinstance(value, ReadinessOutcome):
        return value
    if isinstance(value, str):
        try:
            return ReadinessOutcome(value)
        except ValueError as exc:
            raise ValueError(f"unknown readiness value: {value}") from exc
    raise TypeError("readiness must be a ReadinessOutcome or canonical string")


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, field_name)


def _string_tuple(values: object, field_name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, Mapping)) or not isinstance(values, Iterable):
        raise TypeError(f"{field_name} must be an iterable of strings")
    normalized = {_required_string(value, field_name) for value in values}
    return tuple(sorted(normalized))


def _dependency_pairs(values: object, field_name: str) -> tuple[tuple[str, str], ...]:
    if isinstance(values, (str, bytes, Mapping)) or not isinstance(values, Iterable):
        raise TypeError(f"{field_name} must be an iterable of string pairs")
    normalized: set[tuple[str, str]] = set()
    for value in values:
        if not isinstance(value, tuple) or len(value) != 2:
            raise TypeError(f"{field_name} must contain only two-string tuples")
        normalized.add(
            (
                _required_string(value[0], field_name),
                _required_string(value[1], field_name),
            )
        )
    return tuple(sorted(normalized))
