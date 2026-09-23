"""Durable persist/read-by-id storage for the full canonical #918 ``ExecutorHandoff``.

AOS-GCE2E (#1304) closes one of the four durable-recovery gaps blocking
#1303's production ``HostCurrentInvocationSources``. This module reuses the
existing checkpoint-owned content-addressed atomic-write and path-safety
primitives from ``scripts.agent_os_execution_checkpoint.store`` and the
canonical #918 ``ExecutorHandoff`` round-trip (``to_dict``/``from_dict``,
``handoff_id``) -- it defines no competing handoff model, identity scheme,
Scheduler, lease, or storage authority.

This module persists the complete ``ExecutorHandoff`` object so it can be
reacquired by identity on restart; it is distinct from (and does not
duplicate or replace) the existing #1218 ``GovernedInvocationDescriptor``,
which stores only the bounded, non-authorizing set of IDs needed to locate
this and the other three artifacts #1304 covers. A handoff is persisted as
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

from .executor_routing import ExecutorHandoff

MAX_EXECUTOR_HANDOFF_BYTES = 64 * 1024
MAX_EXECUTOR_HANDOFFS = 4096
MAX_EXECUTOR_HANDOFF_STORE_BYTES = 64 * 1024 * 1024

_EXECUTOR_HANDOFF_ID_RE = re.compile(r"^executor-handoff:[0-9a-f]{64}$", re.ASCII)


class ExecutorHandoffNotFound(LookupError):
    """Raised when no persisted full handoff exists for one exact handoff_id."""


@dataclass(frozen=True, slots=True)
class AppendExecutorHandoffOutcome:
    handoff_id: str
    path: Path
    already_present: bool


def _canonical_handoff_id(value: object) -> str:
    if type(value) is not str or not _EXECUTOR_HANDOFF_ID_RE.fullmatch(value):
        raise TypeError(
            "handoff_id must be the canonical executor-handoff:<64-lowercase-hex> identity"
        )
    return value


def _executor_handoff_directory(store_root: Path | str) -> Path:
    return Path(store_root) / "executor-handoffs"


def _filename_for_handoff_id(handoff_id: str) -> str:
    canonical = _canonical_handoff_id(handoff_id)
    return f"{canonical.rsplit(':', 1)[-1]}.json"


def append_executor_handoff(
    store_root: Path | str, handoff: ExecutorHandoff
) -> AppendExecutorHandoffOutcome:
    """Persist one immutable full #918 ExecutorHandoff atomically and idempotently."""

    if type(handoff) is not ExecutorHandoff:
        raise TypeError("handoff must be an exact ExecutorHandoff")
    directory = _executor_handoff_directory(store_root)
    _reject_symlink(directory)
    _ensure_dir(directory)
    filename = _filename_for_handoff_id(handoff.handoff_id)
    payload = canonical_json_bytes(handoff.to_dict())
    if len(payload) > MAX_EXECUTOR_HANDOFF_BYTES:
        raise CheckpointStoreCapacityExceeded(
            "executor handoff exceeds the per-record size bound"
        )
    destination = directory / filename
    if not destination.exists():
        count, total_bytes = _existing_records_footprint(directory)
        if (
            count + 1 > MAX_EXECUTOR_HANDOFFS
            or total_bytes + len(payload) > MAX_EXECUTOR_HANDOFF_STORE_BYTES
        ):
            raise CheckpointStoreCapacityExceeded("executor handoff store is at capacity")
    path, already_present = _atomic_write(directory, filename, payload)
    return AppendExecutorHandoffOutcome(
        handoff_id=handoff.handoff_id, path=path, already_present=already_present
    )


def load_executor_handoff(store_root: Path | str, handoff_id: str) -> ExecutorHandoff:
    """Load one exact handoff-keyed full ExecutorHandoff, recomputing every identity."""

    canonical = _canonical_handoff_id(handoff_id)
    directory = _executor_handoff_directory(store_root)
    _reject_symlink(directory)
    path = directory / _filename_for_handoff_id(canonical)
    _reject_symlink(path)
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise ExecutorHandoffNotFound(canonical) from exc
    except OSError as exc:
        raise CheckpointStoreUnavailable(f"unable to read {path}") from exc
    if len(payload) > MAX_EXECUTOR_HANDOFF_BYTES:
        raise CheckpointStoreIntegrityConflict("executor handoff exceeds the bounded size")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointStoreIntegrityConflict(
            "executor handoff is not valid UTF-8 JSON"
        ) from exc
    try:
        handoff = ExecutorHandoff.from_dict(decoded)
    except (TypeError, ValueError) as exc:
        raise CheckpointStoreIntegrityConflict(str(exc)) from exc
    if handoff.handoff_id != canonical:
        raise CheckpointStoreIntegrityConflict(
            "persisted executor handoff does not match requested handoff identity"
        )
    if path.name != _filename_for_handoff_id(handoff.handoff_id):
        raise CheckpointStoreIntegrityConflict(
            "handoff-keyed filename does not match executor handoff identity"
        )
    return handoff
