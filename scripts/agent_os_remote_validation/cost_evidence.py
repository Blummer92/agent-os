from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import Literal

from .dispatch_guard import (
    DispatchDecision,
    serialize_dispatch_decision,
    validation_dispatch_identity,
)
from .models import ValidationPlan
from .selector import validate_validation_plan, validation_plan_id

COMPUTE_EVIDENCE_SCHEMA_NAME = "agent-os-compute-evidence-summary"
COMPUTE_EVIDENCE_SCHEMA_VERSION = "1.0"
MAX_COMPUTE_RECORDS = 64
MAX_COMPUTE_STRING_LENGTH = 4096
MAX_COMPUTE_REASON_CODES = 32
MAX_COMPUTE_SERIALIZED_BYTES = 262_144

ComputeEvidenceStatus = Literal["within-policy", "warning", "manual-review"]
BuildTerminalStatus = Literal[
    "succeeded",
    "failed",
    "cancelled",
    "timed-out",
    "infrastructure-error",
    "unavailable",
]

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_BUILD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_PLAN_ID = re.compile(r"^validation-plan:[0-9a-f]{64}$")
_DECISION_ID = re.compile(r"^validation-dispatch-decision:[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SECRET = re.compile(
    r"(?i)(authorization\s*:|bearer\s+[A-Za-z0-9._-]{8,}|"
    r"(?:token|password|secret|api[_-]?key|private[_-]?key)\s*[:=])"
)
_TERMINAL_STATUSES = frozenset(
    {
        "succeeded",
        "failed",
        "cancelled",
        "timed-out",
        "infrastructure-error",
        "unavailable",
    }
)
_DISPATCH_STATUSES = frozenset(
    {
        "launch-eligible",
        "reused",
        "duplicate-no-op",
        "stale-skipped",
        "supersede-required",
        "manual-review",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SuppliedComputeRecord:
    record_id: str
    dispatch_decision: DispatchDecision
    remote_build_triggered: bool
    build_id: str = "unavailable"
    terminal_status: BuildTerminalStatus = "unavailable"
    machine_type: str = "unavailable"
    elapsed_seconds: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ComputeEvidenceSummary:
    schema_name: str
    schema_version: str
    status: ComputeEvidenceStatus
    summary_id: str
    repository: str | None
    pull_request: int | None
    head_sha: str | None
    profile: str | None
    selector_version: str | None
    command_set_digest: str | None
    plan_id: str | None
    remote_builds_triggered: int
    duplicate_builds_avoided: int
    stale_proposals_skipped: int
    superseded_proposals_identified: int
    retry_count: int
    aggregate_runs_for_exact_sha: int
    record_ids: tuple[str, ...]
    build_ids: tuple[str, ...]
    terminal_statuses: tuple[str, ...]
    machine_type: str
    elapsed_seconds: int | Literal["unavailable"]
    reason_codes: tuple[str, ...]
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def build_compute_evidence_summary(
    validation_plan: object,
    supplied_records: object,
    *,
    schema_version: object = COMPUTE_EVIDENCE_SCHEMA_VERSION,
) -> ComputeEvidenceSummary:
    """Summarize supplied compute evidence without discovery or external I/O."""
    invalid: set[str] = set()
    warnings: set[str] = set()
    manual: set[str] = set()

    plan = validation_plan if isinstance(validation_plan, ValidationPlan) else None
    plan_reasons = _plan_boundary_reasons(validation_plan)
    if plan_reasons:
        invalid.add("plan.invalid")
        invalid.update(f"plan-detail.{reason}" for reason in plan_reasons)

    if schema_version != COMPUTE_EVIDENCE_SCHEMA_VERSION:
        invalid.add("summary.schema-version")

    records: tuple[SuppliedComputeRecord, ...] = ()
    if not isinstance(supplied_records, tuple):
        invalid.add("records.invalid-collection")
    elif len(supplied_records) > MAX_COMPUTE_RECORDS:
        invalid.add("records.collection-limit")
    elif any(not isinstance(item, SuppliedComputeRecord) for item in supplied_records):
        invalid.add("records.invalid-record-type")
    else:
        records = supplied_records

    normalized: list[SuppliedComputeRecord] = []
    seen_record_ids: set[str] = set()
    seen_decision_ids: dict[str, bool] = {}
    seen_build_ids: set[str] = set()
    for record in records:
        record_reasons = _record_reasons(record, plan)
        if record_reasons:
            invalid.update(record_reasons)
            continue
        if record.record_id in seen_record_ids:
            invalid.add("records.duplicate-record-id")
        seen_record_ids.add(record.record_id)
        decision_id = record.dispatch_decision.decision_id
        if decision_id in seen_decision_ids:
            if not (seen_decision_ids[decision_id] and record.remote_build_triggered):
                invalid.add("records.duplicate-decision-id")
        else:
            seen_decision_ids[decision_id] = record.remote_build_triggered
        if record.build_id != "unavailable":
            if record.build_id in seen_build_ids:
                invalid.add("records.duplicate-build-id")
            seen_build_ids.add(record.build_id)
        normalized.append(record)

    normalized.sort(key=lambda item: item.record_id)
    valid_plan = plan if not plan_reasons else None

    if invalid:
        return _summary(
            plan=valid_plan,
            status="manual-review",
            remote_builds_triggered=0,
            duplicate_builds_avoided=0,
            stale_proposals_skipped=0,
            superseded_proposals_identified=0,
            retry_count=0,
            aggregate_runs_for_exact_sha=0,
            record_ids=(),
            build_ids=(),
            terminal_statuses=(),
            machine_type="unavailable",
            elapsed_seconds="unavailable",
            reason_codes=_bounded_reasons(invalid),
        )

    remote_builds = sum(record.remote_build_triggered for record in normalized)
    duplicate_avoided = sum(
        record.dispatch_decision.status in {"reused", "duplicate-no-op"}
        for record in normalized
    )
    stale_skipped = sum(
        record.dispatch_decision.status == "stale-skipped" for record in normalized
    )
    superseded = sum(
        record.dispatch_decision.status == "supersede-required"
        for record in normalized
    )
    retry_count = sum(
        record.remote_build_triggered
        and record.dispatch_decision.retry_recommended
        and record.dispatch_decision.retry_attempt == 1
        for record in normalized
    )
    aggregate_runs = (
        remote_builds
        if valid_plan is not None and valid_plan.profile == "aggregate"
        else 0
    )

    if valid_plan is not None and valid_plan.profile == "static" and remote_builds:
        invalid.add("policy.static-build-triggered")
    if retry_count > 1:
        manual.add("policy.retry-limit")
    if aggregate_runs > 1:
        warnings.add("policy.aggregate-repeat")
    if not normalized:
        warnings.add("evidence.empty")

    for record in normalized:
        decision = record.dispatch_decision
        if decision.status == "manual-review":
            manual.add("dispatch.manual-review")
        if decision.status == "supersede-required":
            warnings.add("dispatch.supersede-required")
        if decision.status == "launch-eligible" and not record.remote_build_triggered:
            warnings.add("build.launch-not-observed")
        if record.remote_build_triggered and (
            record.build_id == "unavailable"
            or record.terminal_status == "unavailable"
            or record.machine_type == "unavailable"
            or record.elapsed_seconds is None
        ):
            warnings.add("build.metadata-unavailable")

    launched = [record for record in normalized if record.remote_build_triggered]
    concrete_machine_types = {
        record.machine_type
        for record in launched
        if record.machine_type != "unavailable"
    }
    machine_type = (
        next(iter(concrete_machine_types))
        if launched
        and len(concrete_machine_types) == 1
        and all(record.machine_type != "unavailable" for record in launched)
        else "unavailable"
    )
    if len(concrete_machine_types) > 1:
        warnings.add("build.machine-type-mixed")

    elapsed_seconds: int | Literal["unavailable"] = "unavailable"
    if launched and all(record.elapsed_seconds is not None for record in launched):
        elapsed_seconds = sum(int(record.elapsed_seconds) for record in launched)

    status: ComputeEvidenceStatus
    reasons = set(invalid)
    if invalid or manual:
        status = "manual-review"
        reasons.update(manual)
    elif warnings:
        status = "warning"
        reasons.update(warnings)
    else:
        status = "within-policy"

    return _summary(
        plan=valid_plan,
        status=status,
        remote_builds_triggered=remote_builds,
        duplicate_builds_avoided=duplicate_avoided,
        stale_proposals_skipped=stale_skipped,
        superseded_proposals_identified=superseded,
        retry_count=retry_count,
        aggregate_runs_for_exact_sha=aggregate_runs,
        record_ids=tuple(record.record_id for record in normalized),
        build_ids=tuple(record.build_id for record in launched),
        terminal_statuses=tuple(record.terminal_status for record in launched),
        machine_type=machine_type,
        elapsed_seconds=elapsed_seconds,
        reason_codes=_bounded_reasons(reasons),
    )


def serialize_compute_evidence_summary(
    summary: ComputeEvidenceSummary,
) -> dict[str, object]:
    """Return canonical summary data after verifying its semantic identity."""
    if not isinstance(summary, ComputeEvidenceSummary):
        raise TypeError("summary must be ComputeEvidenceSummary")
    payload = _summary_payload(summary)
    expected = "compute-evidence-summary:" + _semantic_digest(
        "agent-os-compute-evidence-summary:v1", payload
    )
    if summary.summary_id != expected:
        raise ValueError("compute evidence summary ID mismatch")
    serialized = dict(payload)
    serialized["summary_id"] = summary.summary_id
    if len(_canonical_bytes(serialized)) > MAX_COMPUTE_SERIALIZED_BYTES:
        raise ValueError("compute evidence summary exceeds canonical size limit")
    return serialized


def compute_evidence_summary_id(summary: ComputeEvidenceSummary) -> str:
    """Return the verified domain-separated semantic summary identity."""
    return str(serialize_compute_evidence_summary(summary)["summary_id"])


def _summary(
    *,
    plan: ValidationPlan | None,
    status: ComputeEvidenceStatus,
    remote_builds_triggered: int,
    duplicate_builds_avoided: int,
    stale_proposals_skipped: int,
    superseded_proposals_identified: int,
    retry_count: int,
    aggregate_runs_for_exact_sha: int,
    record_ids: tuple[str, ...],
    build_ids: tuple[str, ...],
    terminal_statuses: tuple[str, ...],
    machine_type: str,
    elapsed_seconds: int | Literal["unavailable"],
    reason_codes: tuple[str, ...],
) -> ComputeEvidenceSummary:
    preliminary = ComputeEvidenceSummary(
        schema_name=COMPUTE_EVIDENCE_SCHEMA_NAME,
        schema_version=COMPUTE_EVIDENCE_SCHEMA_VERSION,
        status=status,
        summary_id="",
        repository=plan.repository if plan is not None else None,
        pull_request=plan.pull_request if plan is not None else None,
        head_sha=plan.head_sha if plan is not None else None,
        profile=plan.profile if plan is not None else None,
        selector_version=plan.selector_version if plan is not None else None,
        command_set_digest=plan.command_set_digest if plan is not None else None,
        plan_id=validation_plan_id(plan) if plan is not None else None,
        remote_builds_triggered=remote_builds_triggered,
        duplicate_builds_avoided=duplicate_builds_avoided,
        stale_proposals_skipped=stale_proposals_skipped,
        superseded_proposals_identified=superseded_proposals_identified,
        retry_count=retry_count,
        aggregate_runs_for_exact_sha=aggregate_runs_for_exact_sha,
        record_ids=record_ids,
        build_ids=build_ids,
        terminal_statuses=terminal_statuses,
        machine_type=machine_type,
        elapsed_seconds=elapsed_seconds,
        reason_codes=reason_codes,
    )
    digest = _semantic_digest(
        "agent-os-compute-evidence-summary:v1", _summary_payload(preliminary)
    )
    return replace(preliminary, summary_id=f"compute-evidence-summary:{digest}")


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


def _record_reasons(
    record: SuppliedComputeRecord,
    plan: ValidationPlan | None,
) -> tuple[str, ...]:
    reasons: set[str] = set()
    if not _identifier(record.record_id, _RECORD_ID):
        reasons.add("records.record-id")
    if not isinstance(record.remote_build_triggered, bool):
        reasons.add("records.remote-build-triggered")
    if not _unavailable_or_identifier(record.build_id, _BUILD_ID):
        reasons.add("records.build-id")
    if (
        not isinstance(record.terminal_status, str)
        or record.terminal_status not in _TERMINAL_STATUSES
    ):
        reasons.add("records.terminal-status")
    if not _unavailable_or_text(record.machine_type):
        reasons.add("records.machine-type")
    if record.elapsed_seconds is not None and (
        not isinstance(record.elapsed_seconds, int)
        or isinstance(record.elapsed_seconds, bool)
        or record.elapsed_seconds < 0
    ):
        reasons.add("records.elapsed-seconds")
    if not _valid_decision(record.dispatch_decision):
        reasons.add("records.dispatch-decision")

    if reasons or not isinstance(record.dispatch_decision, DispatchDecision):
        return tuple(sorted(reasons))

    decision = record.dispatch_decision
    if plan is not None and not _plan_boundary_reasons(plan):
        expected = {
            "repository": plan.repository,
            "pull_request": plan.pull_request,
            "head_sha": plan.head_sha,
            "profile": plan.profile,
            "selector_version": plan.selector_version,
            "command_set_digest": plan.command_set_digest,
            "plan_id": validation_plan_id(plan),
            "dispatch_identity": validation_dispatch_identity(plan),
        }
        actual = {
            "repository": decision.repository,
            "pull_request": decision.pull_request,
            "head_sha": decision.head_sha,
            "profile": decision.profile,
            "selector_version": decision.selector_version,
            "command_set_digest": decision.command_set_digest,
            "plan_id": decision.plan_id,
            "dispatch_identity": decision.dispatch_identity,
        }
        if actual != expected:
            reasons.add("records.identity-mismatch")

    if record.remote_build_triggered:
        if decision.status != "launch-eligible" or decision.launch_recommended is not True:
            reasons.add("records.unexpected-build")
    elif (
        record.build_id != "unavailable"
        or record.terminal_status != "unavailable"
        or record.machine_type != "unavailable"
        or record.elapsed_seconds is not None
    ):
        reasons.add("records.no-build-metadata-contradiction")

    return tuple(sorted(reasons))


def _valid_decision(decision: object) -> bool:
    if not isinstance(decision, DispatchDecision):
        return False
    if not _runtime_safe_decision(decision):
        return False
    if decision.schema_name != "agent-os-validation-dispatch-decision":
        return False
    if decision.schema_version != "1.0":
        return False
    if decision.status not in _DISPATCH_STATUSES:
        return False
    if decision.status == "launch-eligible":
        if decision.launch_recommended is not True:
            return False
    elif decision.launch_recommended is not False:
        return False
    if decision.retry_recommended:
        if decision.status != "launch-eligible" or decision.retry_attempt != 1:
            return False
    elif decision.retry_attempt is not None:
        return False
    try:
        serialize_dispatch_decision(decision)
    except (TypeError, ValueError):
        return False
    return True


def _runtime_safe_decision(decision: DispatchDecision) -> bool:
    return (
        isinstance(decision.schema_name, str)
        and isinstance(decision.schema_version, str)
        and isinstance(decision.status, str)
        and isinstance(decision.decision_id, str)
        and _fullmatch(_DECISION_ID, decision.decision_id)
        and (
            decision.dispatch_identity is None
            or isinstance(decision.dispatch_identity, str)
        )
        and (decision.repository is None or isinstance(decision.repository, str))
        and (
            decision.pull_request is None
            or (
                isinstance(decision.pull_request, int)
                and not isinstance(decision.pull_request, bool)
            )
        )
        and (decision.head_sha is None or _fullmatch(_SHA40, decision.head_sha))
        and (decision.profile is None or isinstance(decision.profile, str))
        and (
            decision.selector_version is None
            or isinstance(decision.selector_version, str)
        )
        and (
            decision.command_set_digest is None
            or decision.command_set_digest == "unavailable"
            or _fullmatch(_HEX64, decision.command_set_digest)
        )
        and (decision.plan_id is None or _fullmatch(_PLAN_ID, decision.plan_id))
        and isinstance(decision.launch_recommended, bool)
        and isinstance(decision.retry_recommended, bool)
        and (
            decision.retry_attempt is None
            or (
                isinstance(decision.retry_attempt, int)
                and not isinstance(decision.retry_attempt, bool)
            )
        )
        and isinstance(decision.matched_record_ids, tuple)
        and all(isinstance(value, str) for value in decision.matched_record_ids)
        and isinstance(decision.reason_codes, tuple)
        and all(isinstance(value, str) for value in decision.reason_codes)
        and decision.execution_authorized is False
        and decision.side_effects_performed is False
    )


def _summary_payload(summary: ComputeEvidenceSummary) -> dict[str, object]:
    return {
        "schema_name": summary.schema_name,
        "schema_version": summary.schema_version,
        "status": summary.status,
        "repository": summary.repository,
        "pull_request": summary.pull_request,
        "head_sha": summary.head_sha,
        "profile": summary.profile,
        "selector_version": summary.selector_version,
        "command_set_digest": summary.command_set_digest,
        "plan_id": summary.plan_id,
        "remote_builds_triggered": summary.remote_builds_triggered,
        "duplicate_builds_avoided": summary.duplicate_builds_avoided,
        "stale_proposals_skipped": summary.stale_proposals_skipped,
        "superseded_proposals_identified": summary.superseded_proposals_identified,
        "retry_count": summary.retry_count,
        "aggregate_runs_for_exact_sha": summary.aggregate_runs_for_exact_sha,
        "record_ids": list(summary.record_ids),
        "build_ids": list(summary.build_ids),
        "terminal_statuses": list(summary.terminal_statuses),
        "machine_type": summary.machine_type,
        "elapsed_seconds": summary.elapsed_seconds,
        "reason_codes": list(summary.reason_codes),
        "authoritative": False,
        "execution_authorized": False,
        "merge_authorized": False,
        "side_effects_performed": False,
    }


def _bounded_reasons(reasons: set[str]) -> tuple[str, ...]:
    ordered = sorted(reasons)
    if len(ordered) <= MAX_COMPUTE_REASON_CODES:
        return tuple(ordered)
    return tuple(
        ordered[: MAX_COMPUTE_REASON_CODES - 1] + ["evidence.reason-limit"]
    )


def _semantic_digest(domain: str, payload: dict[str, object]) -> str:
    return hashlib.sha256(
        domain.encode("ascii") + b"\0" + _canonical_bytes(payload)
    ).hexdigest()


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _identifier(value: object, pattern: re.Pattern[str]) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= MAX_COMPUTE_STRING_LENGTH
        and _CONTROL.search(value) is None
        and _SECRET.search(value) is None
        and pattern.fullmatch(value) is not None
    )


def _unavailable_or_identifier(value: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and (
        value == "unavailable" or _identifier(value, pattern)
    )


def _unavailable_or_text(value: object) -> bool:
    return isinstance(value, str) and (
        value == "unavailable"
        or (
            bool(value)
            and len(value) <= MAX_COMPUTE_STRING_LENGTH
            and _CONTROL.search(value) is None
            and _SECRET.search(value) is None
        )
    )


def _fullmatch(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None
