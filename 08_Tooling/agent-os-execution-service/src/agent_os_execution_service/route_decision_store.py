"""Durable persist/read-by-id storage for canonical #918 ``ExecutorRouteDecision`` records.

AOS-GCE2E (#1304) closes one of the four durable-recovery gaps blocking
#1303's production ``HostCurrentInvocationSources``. This module reuses the
existing checkpoint-owned content-addressed atomic-write and path-safety
primitives from ``scripts.agent_os_execution_checkpoint.store`` and the
canonical #918 ``ExecutorRouteDecision`` round-trip (``to_dict``/``from_dict``,
``decision_id``) -- it defines no competing route model, identity scheme,
Scheduler, lease, or storage authority. A route decision is persisted as
evidence only: presence here never grants currentness, authorization, or
Scheduler admission.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from scripts.agent_os_execution_checkpoint.identity import canonical_json_bytes
from scripts.agent_os_execution_checkpoint.store import (
    CheckpointStoreCapacityExceeded,
    CheckpointStoreIntegrityConflict,
    CheckpointStoreUnavailable,
    _atomic_write,
    _ensure_dir,
    _existing_records_footprint,
    _reject_symlink,
)

from .executor_routing import ExecutorRouteDecision

MAX_ROUTE_DECISION_BYTES = 64 * 1024
MAX_ROUTE_DECISIONS = 4096
MAX_ROUTE_DECISION_STORE_BYTES = 64 * 1024 * 1024

_ROUTE_DECISION_ID_RE = re.compile(
    r"^executor-route-decision:[0-9a-f]{64}$", re.ASCII
)


class RouteDecisionNotFound(LookupError):
    """Raised when no persisted route decision exists for one exact decision_id."""


@dataclass(frozen=True, slots=True)
class AppendRouteDecisionOutcome:
    decision_id: str
    path: Path
    already_present: bool


def _canonical_decision_id(value: object) -> str:
    if type(value) is not str or not _ROUTE_DECISION_ID_RE.fullmatch(value):
        raise TypeError(
            "decision_id must be the canonical "
            "executor-route-decision:<64-lowercase-hex> identity"
        )
    return value


def _route_decision_directory(store_root: Path | str) -> Path:
    return Path(store_root) / "route-decisions"


def _filename_for_decision_id(decision_id: str) -> str:
    canonical = _canonical_decision_id(decision_id)
    return f"{canonical.rsplit(':', 1)[-1]}.json"


def append_route_decision(
    store_root: Path | str, route_decision: ExecutorRouteDecision
) -> AppendRouteDecisionOutcome:
    """Persist one immutable #918 route decision atomically and idempotently."""

    if type(route_decision) is not ExecutorRouteDecision:
        raise TypeError("route_decision must be an exact ExecutorRouteDecision")
    directory = _route_decision_directory(store_root)
    _reject_symlink(directory)
    _ensure_dir(directory)
    filename = _filename_for_decision_id(route_decision.decision_id)
    payload = canonical_json_bytes(route_decision.to_dict())
    if len(payload) > MAX_ROUTE_DECISION_BYTES:
        raise CheckpointStoreCapacityExceeded(
            "route decision exceeds the per-record size bound"
        )
    destination = directory / filename
    if not destination.exists():
        count, total_bytes = _existing_records_footprint(directory)
        if (
            count + 1 > MAX_ROUTE_DECISIONS
            or total_bytes + len(payload) > MAX_ROUTE_DECISION_STORE_BYTES
        ):
            raise CheckpointStoreCapacityExceeded("route decision store is at capacity")
    path, already_present = _atomic_write(directory, filename, payload)
    return AppendRouteDecisionOutcome(
        decision_id=route_decision.decision_id, path=path, already_present=already_present
    )


def load_route_decision(
    store_root: Path | str, decision_id: str
) -> ExecutorRouteDecision:
    """Load one exact decision-keyed route decision, recomputing every identity."""

    canonical = _canonical_decision_id(decision_id)
    directory = _route_decision_directory(store_root)
    _reject_symlink(directory)
    path = directory / _filename_for_decision_id(canonical)
    _reject_symlink(path)
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise RouteDecisionNotFound(canonical) from exc
    except OSError as exc:
        raise CheckpointStoreUnavailable(f"unable to read {path}") from exc
    if len(payload) > MAX_ROUTE_DECISION_BYTES:
        raise CheckpointStoreIntegrityConflict("route decision exceeds the bounded size")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointStoreIntegrityConflict(
            "route decision is not valid UTF-8 JSON"
        ) from exc
    try:
        route_decision = ExecutorRouteDecision.from_dict(decoded)
    except (TypeError, ValueError) as exc:
        raise CheckpointStoreIntegrityConflict(str(exc)) from exc
    if route_decision.decision_id != canonical:
        raise CheckpointStoreIntegrityConflict(
            "persisted route decision does not match requested decision identity"
        )
    if path.name != _filename_for_decision_id(route_decision.decision_id):
        raise CheckpointStoreIntegrityConflict(
            "decision-keyed filename does not match route decision identity"
        )
    return route_decision
