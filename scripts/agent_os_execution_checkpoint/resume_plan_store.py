"""Durable persist/read-by-id storage for immutable #895 ``ResumePlan`` records.

AOS-GCE2E (#1304) closes one of the four durable-recovery gaps blocking
#1303's production ``HostCurrentInvocationSources``. This module reuses the
existing checkpoint-owned content-addressed atomic-write and path-safety
primitives from ``store.py`` and the canonical ``ResumePlan`` round-trip
(``to_dict``/``resume_plan_from_dict``, ``plan_id``) from ``resume_planner.py``.
It defines no competing ResumePlan model, identity scheme, Scheduler, lease,
or storage authority. A plan is persisted as evidence only: presence here
never grants currentness, authorization, or Scheduler admission.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .resume_planner import ResumePlan, deserialize_resume_plan, serialize_resume_plan
from .store import (
    CheckpointStoreCapacityExceeded,
    CheckpointStoreIntegrityConflict,
    CheckpointStoreUnavailable,
    _atomic_write,
    _ensure_dir,
    _existing_records_footprint,
    _reject_symlink,
)

MAX_RESUME_PLAN_BYTES = 64 * 1024
MAX_RESUME_PLANS = 4096
MAX_RESUME_PLAN_STORE_BYTES = 64 * 1024 * 1024

_PLAN_ID_RE = re.compile(
    r"^agent-os\.execution-checkpoint\.resume-plan:[0-9a-f]{64}$", re.ASCII
)


class ResumePlanNotFound(LookupError):
    """Raised when no persisted resume plan exists for one exact plan_id."""


@dataclass(frozen=True, slots=True)
class AppendResumePlanOutcome:
    plan_id: str
    path: Path
    already_present: bool


def _canonical_plan_id(value: object) -> str:
    if type(value) is not str or not _PLAN_ID_RE.fullmatch(value):
        raise TypeError(
            "plan_id must be the canonical "
            "agent-os.execution-checkpoint.resume-plan:<64-lowercase-hex> identity"
        )
    return value


def _resume_plan_directory(store_root: Path | str) -> Path:
    return Path(store_root) / "resume-plans"


def _filename_for_plan_id(plan_id: str) -> str:
    canonical = _canonical_plan_id(plan_id)
    return f"{canonical.rsplit(':', 1)[-1]}.json"


def append_resume_plan(
    store_root: Path | str, plan: ResumePlan
) -> AppendResumePlanOutcome:
    """Persist one immutable ResumePlan atomically and idempotently."""

    if type(plan) is not ResumePlan:
        raise TypeError("plan must be an exact ResumePlan")
    directory = _resume_plan_directory(store_root)
    _reject_symlink(directory)
    _ensure_dir(directory)
    filename = _filename_for_plan_id(plan.plan_id)
    payload = serialize_resume_plan(plan)
    if len(payload) > MAX_RESUME_PLAN_BYTES:
        raise CheckpointStoreCapacityExceeded(
            "resume plan exceeds the per-record size bound"
        )
    destination = directory / filename
    if not destination.exists():
        count, total_bytes = _existing_records_footprint(directory)
        if (
            count + 1 > MAX_RESUME_PLANS
            or total_bytes + len(payload) > MAX_RESUME_PLAN_STORE_BYTES
        ):
            raise CheckpointStoreCapacityExceeded("resume plan store is at capacity")
    path, already_present = _atomic_write(directory, filename, payload)
    return AppendResumePlanOutcome(
        plan_id=plan.plan_id, path=path, already_present=already_present
    )


def load_resume_plan(store_root: Path | str, plan_id: str) -> ResumePlan:
    """Load one exact plan-keyed ResumePlan, recomputing every identity."""

    canonical = _canonical_plan_id(plan_id)
    directory = _resume_plan_directory(store_root)
    _reject_symlink(directory)
    path = directory / _filename_for_plan_id(canonical)
    _reject_symlink(path)
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise ResumePlanNotFound(canonical) from exc
    except OSError as exc:
        raise CheckpointStoreUnavailable(f"unable to read {path}") from exc
    try:
        plan = deserialize_resume_plan(payload)
    except (TypeError, ValueError) as exc:
        raise CheckpointStoreIntegrityConflict(str(exc)) from exc
    if plan.plan_id != canonical:
        raise CheckpointStoreIntegrityConflict(
            "persisted resume plan does not match requested plan identity"
        )
    if path.name != _filename_for_plan_id(plan.plan_id):
        raise CheckpointStoreIntegrityConflict(
            "plan-keyed filename does not match resume plan identity"
        )
    return plan
