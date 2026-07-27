from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import Literal

from .models import ValidationPlan
from .selector import validate_validation_plan, validation_plan_id

VALIDATION_DISPATCH_DECISION_SCHEMA_NAME = "agent-os-validation-dispatch-decision"
VALIDATION_DISPATCH_DECISION_SCHEMA_VERSION = "1.0"
MAX_DISPATCH_RECORDS = 64
MAX_DISPATCH_STRING_LENGTH = 4096
MAX_DISPATCH_REASON_CODES = 32
MAX_DISPATCH_MATCHED_RECORDS = 64
MAX_DISPATCH_SERIALIZED_BYTES = 262_144

DispatchStatus = Literal[
    "launch-eligible",
    "reused",
    "duplicate-no-op",
    "stale-skipped",
    "supersede-required",
    "manual-review",
]
DispatchState = Literal["active", "succeeded", "failed"]
FailureClass = Literal[
    "none",
    "transient-infrastructure",
    "test",
    "configuration",
    "permission",
    "policy",
    "malformed-input",
]

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SECRET = re.compile(
    r"(?i)(authorization\s*:|bearer\s+[A-Za-z0-9._-]{8,}|"
    r"(?:token|password|secret|api[_-]?key|private[_-]?key)\s*[:=])"
)
_STATES = frozenset({"active", "succeeded", "failed"})
_FAILURE_CLASSES = frozenset(
    {
        "none",
        "transient-infrastructure",
        "test",
        "configuration",
        "permission",
        "policy",
        "malformed-input",
    }
)
_EXECUTABLE_PROFILES = frozenset({"focused", "aggregate"})
_NON_RETRYABLE = frozenset(
    {"test", "configuration", "permission", "policy", "malformed-input"}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class DispatchEvidence:
    record_id: str
    validation_plan: ValidationPlan
    attempt: int
    state: DispatchState
    failure_class: FailureClass = "none"


@dataclass(frozen=True, slots=True, kw_only=True)
class DispatchDecision:
    schema_name: str
    schema_version: str
    status: DispatchStatus
    decision_id: str
    dispatch_identity: str | None
    repository: str | None
    pull_request: int | None
    head_sha: str | None
    profile: str | None
    selector_version: str | None
    command_set_digest: str | None
    plan_id: str | None
    launch_recommended: bool
    retry_recommended: bool
    retry_attempt: int | None
    matched_record_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def validation_dispatch_identity(plan: ValidationPlan) -> str:
    """Return the exact canonical identity for one valid validation plan."""
    reasons = _plan_boundary_reasons(plan)
    if reasons:
        raise ValueError("invalid validation plan: " + ",".join(reasons))
    return _identity(
        repository=plan.repository,
        head_sha=plan.head_sha,
        profile=plan.profile,
        selector_version=plan.selector_version,
        command_set_digest=plan.command_set_digest,
        plan_id=validation_plan_id(plan),
    )


def evaluate_dispatch_decision(
    validation_plan: object,
    supplied_evidence: object,
    *,
    current_pr_head_sha: object,
    schema_version: object = VALIDATION_DISPATCH_DECISION_SCHEMA_VERSION,
) -> DispatchDecision:
    """Return a deterministic, non-authorizing remote-dispatch recommendation."""
    reasons: set[str] = set()
    plan = validation_plan if isinstance(validation_plan, ValidationPlan) else None
    plan_reasons = _plan_boundary_reasons(validation_plan)
    if plan_reasons:
        reasons.add("plan.invalid")
        reasons.update(f"plan-detail.{reason}" for reason in plan_reasons)

    if schema_version != VALIDATION_DISPATCH_DECISION_SCHEMA_VERSION:
        reasons.add("decision.schema-version")
    if not _fullmatch(_SHA40, current_pr_head_sha):
        reasons.add("decision.current-head")

    records: tuple[DispatchEvidence, ...] = ()
    if not isinstance(supplied_evidence, tuple):
        reasons.add("evidence.invalid-collection")
    elif len(supplied_evidence) > MAX_DISPATCH_RECORDS:
        reasons.add("evidence.collection-limit")
    elif any(not isinstance(item, DispatchEvidence) for item in supplied_evidence):
        reasons.add("evidence.invalid-record-type")
    else:
        records = supplied_evidence
        reasons.update(_validate_records(records, plan))

    if reasons:
        return _decision(
            plan=plan,
            status="manual-review",
            reason_codes=tuple(sorted(reasons)),
        )

    assert plan is not None
    dispatch_identity = validation_dispatch_identity(plan)

    if plan.profile == "manual-review":
        return _decision(
            plan=plan,
            status="manual-review",
            reason_codes=("plan.manual-review",),
        )
    if current_pr_head_sha != plan.head_sha:
        return _decision(
            plan=plan,
            status="stale-skipped",
            reason_codes=("head.stale",),
        )
    if plan.remote_build_required is False:
        return _decision(
            plan=plan,
            status="duplicate-no-op",
            reason_codes=("plan.remote-build-not-required",),
        )

    active = tuple(record for record in records if record.state == "active")
    if len(active) > 1:
        return _decision(
            plan=plan,
            status="manual-review",
            matched_record_ids=tuple(sorted(record.record_id for record in active)),
            reason_codes=("active.multiple",),
        )
    if active:
        if _record_identity(active[0]) == dispatch_identity:
            return _decision(
                plan=plan,
                status="duplicate-no-op",
                matched_record_ids=(active[0].record_id,),
                reason_codes=("active.exact-duplicate",),
            )
        return _decision(
            plan=plan,
            status="supersede-required",
            matched_record_ids=(active[0].record_id,),
            reason_codes=("active.different-identity",),
        )

    exact = tuple(
        record for record in records if _record_identity(record) == dispatch_identity
    )
    successes = tuple(record for record in exact if record.state == "succeeded")
    if successes:
        winner = max(successes, key=lambda item: item.attempt)
        return _decision(
            plan=plan,
            status="reused",
            matched_record_ids=(winner.record_id,),
            reason_codes=("terminal.exact-success",),
        )

    failures = tuple(record for record in exact if record.state == "failed")
    if failures:
        latest = max(failures, key=lambda item: item.attempt)
        matched = (latest.record_id,)
        if latest.failure_class in _NON_RETRYABLE:
            return _decision(
                plan=plan,
                status="manual-review",
                matched_record_ids=matched,
                reason_codes=(f"retry.disallowed-{latest.failure_class}",),
            )
        if latest.failure_class == "transient-infrastructure" and latest.attempt == 0:
            return _decision(
                plan=plan,
                status="launch-eligible",
                launch_recommended=True,
                retry_recommended=True,
                retry_attempt=1,
                matched_record_ids=matched,
                reason_codes=("retry.transient-once",),
            )
        return _decision(
            plan=plan,
            status="manual-review",
            matched_record_ids=matched,
            reason_codes=("retry.limit-reached",),
        )

    return _decision(
        plan=plan,
        status="launch-eligible",
        launch_recommended=True,
        reason_codes=("dispatch.no-prior-exact-result",),
    )


def serialize_dispatch_decision(decision: DispatchDecision) -> dict[str, object]:
    """Return canonical decision data after verifying its semantic identity."""
    if not isinstance(decision, DispatchDecision):
        raise TypeError("decision must be DispatchDecision")
    payload = _decision_payload(decision)
    expected = "validation-dispatch-decision:" + _semantic_digest(
        "agent-os-validation-dispatch-decision:v1", payload
    )
    if decision.decision_id != expected:
        raise ValueError("validation dispatch decision ID mismatch")
    serialized = dict(payload)
    serialized["decision_id"] = decision.decision_id
    if len(_canonical_bytes(serialized)) > MAX_DISPATCH_SERIALIZED_BYTES:
        raise ValueError("validation dispatch decision exceeds canonical size limit")
    return serialized


def dispatch_decision_id(decision: DispatchDecision) -> str:
    """Return the verified domain-separated semantic decision identity."""
    return str(serialize_dispatch_decision(decision)["decision_id"])


def _decision(
    *,
    plan: ValidationPlan | None,
    status: DispatchStatus,
    reason_codes: tuple[str, ...],
    launch_recommended: bool = False,
    retry_recommended: bool = False,
    retry_attempt: int | None = None,
    matched_record_ids: tuple[str, ...] = (),
) -> DispatchDecision:
    if len(reason_codes) == 0 or len(reason_codes) > MAX_DISPATCH_REASON_CODES:
        raise ValueError("reason codes outside bounded contract")
    if len(matched_record_ids) > MAX_DISPATCH_MATCHED_RECORDS:
        raise ValueError("matched records outside bounded contract")

    valid_plan = plan if not _plan_boundary_reasons(plan) else None
    plan_id = validation_plan_id(valid_plan) if valid_plan is not None else None
    dispatch_identity = (
        validation_dispatch_identity(valid_plan) if valid_plan is not None else None
    )
    preliminary = DispatchDecision(
        schema_name=VALIDATION_DISPATCH_DECISION_SCHEMA_NAME,
        schema_version=VALIDATION_DISPATCH_DECISION_SCHEMA_VERSION,
        status=status,
        decision_id="",
        dispatch_identity=dispatch_identity,
        repository=valid_plan.repository if valid_plan is not None else None,
        pull_request=valid_plan.pull_request if valid_plan is not None else None,
        head_sha=valid_plan.head_sha if valid_plan is not None else None,
        profile=valid_plan.profile if valid_plan is not None else None,
        selector_version=valid_plan.selector_version if valid_plan is not None else None,
        command_set_digest=(
            valid_plan.command_set_digest if valid_plan is not None else None
        ),
        plan_id=plan_id,
        launch_recommended=launch_recommended,
        retry_recommended=retry_recommended,
        retry_attempt=retry_attempt,
        matched_record_ids=tuple(sorted(matched_record_ids)),
        reason_codes=tuple(sorted(reason_codes)),
    )
    digest = _semantic_digest(
        "agent-os-validation-dispatch-decision:v1", _decision_payload(preliminary)
    )
    return replace(
        preliminary,
        decision_id=f"validation-dispatch-decision:{digest}",
    )


def _plan_boundary_reasons(plan: object) -> tuple[str, ...]:
    if not isinstance(plan, ValidationPlan):
        return ("plan.invalid-type",)
    if not _runtime_safe_plan(plan):
        return ("plan.malformed-runtime",)
    reasons = set(validate_validation_plan(plan))
    if not _identifier(plan.repository, _REPOSITORY):
        reasons.add("plan.repository-boundary")
    return tuple(sorted(reasons))


def _runtime_safe_plan(plan: ValidationPlan) -> bool:
    return (
        isinstance(plan.selector_version, str)
        and isinstance(plan.repository, str)
        and isinstance(plan.pull_request, int)
        and not isinstance(plan.pull_request, bool)
        and isinstance(plan.base_sha, str)
        and isinstance(plan.head_sha, str)
        and isinstance(plan.profile, str)
        and isinstance(plan.commands, tuple)
        and all(isinstance(command, str) for command in plan.commands)
        and isinstance(plan.command_set_digest, str)
        and isinstance(plan.reason_codes, tuple)
        and all(isinstance(reason, str) for reason in plan.reason_codes)
        and isinstance(plan.remote_build_required, bool)
        and isinstance(plan.execution_authorized, bool)
        and isinstance(plan.side_effects_performed, bool)
    )


def _validate_records(
    records: tuple[DispatchEvidence, ...], plan: ValidationPlan | None
) -> tuple[str, ...]:
    invalid: set[str] = set()
    seen_record_ids: set[str] = set()
    seen_attempts: set[tuple[str, int]] = set()
    by_identity: dict[str, list[DispatchEvidence]] = {}

    for record in records:
        if not _valid_record(record):
            invalid.add("evidence.record-invalid")
            continue
        if record.record_id in seen_record_ids:
            invalid.add("evidence.duplicate-record-id")
        seen_record_ids.add(record.record_id)
        identity = _record_identity(record)
        attempt_key = (identity, record.attempt)
        if attempt_key in seen_attempts:
            invalid.add("evidence.duplicate-attempt")
        seen_attempts.add(attempt_key)
        by_identity.setdefault(identity, []).append(record)
        if plan is not None and (
            record.validation_plan.repository != plan.repository
            or record.validation_plan.pull_request != plan.pull_request
        ):
            invalid.add("evidence.scope-mismatch")

    for identity_records in by_identity.values():
        ordered = sorted(identity_records, key=lambda item: item.attempt)
        attempts = [item.attempt for item in ordered]
        if attempts and attempts != list(range(attempts[-1] + 1)):
            invalid.add("evidence.attempt-sequence")
            continue
        if len(ordered) > 2:
            invalid.add("evidence.attempt-limit")
            continue
        if len(ordered) == 2:
            first, second = ordered
            if not (
                first.state == "failed"
                and first.failure_class == "transient-infrastructure"
                and second.attempt == 1
            ):
                invalid.add("evidence.retry-sequence")
        if any(item.state == "succeeded" for item in ordered[:-1]):
            invalid.add("evidence.terminal-sequence")
        if any(item.state == "active" for item in ordered[:-1]):
            invalid.add("evidence.active-sequence")

    return tuple(sorted(invalid))


def _valid_record(record: DispatchEvidence) -> bool:
    if not _identifier(record.record_id, _RECORD_ID):
        return False
    if _plan_boundary_reasons(record.validation_plan):
        return False
    if record.validation_plan.profile not in _EXECUTABLE_PROFILES:
        return False
    if not isinstance(record.attempt, int) or isinstance(record.attempt, bool):
        return False
    if record.attempt not in {0, 1}:
        return False
    if not isinstance(record.state, str) or record.state not in _STATES:
        return False
    if not isinstance(record.failure_class, str):
        return False
    if record.failure_class not in _FAILURE_CLASSES:
        return False
    if record.state in {"active", "succeeded"}:
        return record.failure_class == "none"
    return record.failure_class != "none"


def _record_identity(record: DispatchEvidence) -> str:
    return validation_dispatch_identity(record.validation_plan)


def _identity(
    *,
    repository: str,
    head_sha: str,
    profile: str,
    selector_version: str,
    command_set_digest: str,
    plan_id: str,
) -> str:
    payload = {
        "repository": repository,
        "head_sha": head_sha,
        "profile": profile,
        "selector_version": selector_version,
        "command_set_digest": command_set_digest,
        "plan_id": plan_id,
    }
    return "validation-dispatch:" + _semantic_digest(
        "agent-os-validation-dispatch:v1", payload
    )


def _decision_payload(decision: DispatchDecision) -> dict[str, object]:
    return {
        "schema_name": decision.schema_name,
        "schema_version": decision.schema_version,
        "status": decision.status,
        "dispatch_identity": decision.dispatch_identity,
        "repository": decision.repository,
        "pull_request": decision.pull_request,
        "head_sha": decision.head_sha,
        "profile": decision.profile,
        "selector_version": decision.selector_version,
        "command_set_digest": decision.command_set_digest,
        "plan_id": decision.plan_id,
        "launch_recommended": decision.launch_recommended,
        "retry_recommended": decision.retry_recommended,
        "retry_attempt": decision.retry_attempt,
        "matched_record_ids": list(decision.matched_record_ids),
        "reason_codes": list(decision.reason_codes),
        "execution_authorized": False,
        "side_effects_performed": False,
    }


def _semantic_digest(domain: str, payload: dict[str, object]) -> str:
    return hashlib.sha256(
        domain.encode("ascii") + b"\0" + _canonical_bytes(payload)
    ).hexdigest()


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _identifier(value: object, pattern: re.Pattern[str]) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= MAX_DISPATCH_STRING_LENGTH
        and _CONTROL.search(value) is None
        and _SECRET.search(value) is None
        and pattern.fullmatch(value) is not None
    )


def _fullmatch(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None
