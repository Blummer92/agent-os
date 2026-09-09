from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Literal

from .advisory_gate import AdvisoryEvidenceResult
from .models import ValidationPlan
from .selector import validate_validation_plan, validation_plan_id

MERGE_ADMISSION_SCHEMA_NAME = "agent-os-merge-admission"
MERGE_ADMISSION_SCHEMA_VERSION = "1.0"
MAX_ADMISSION_REASON_CODES = 32
MAX_ADMISSION_SERIALIZED_BYTES = 131_072

AdmissionStatus = Literal["admit", "require-aggregate", "block", "manual-review"]


@dataclass(frozen=True, slots=True, kw_only=True)
class MergeAdmissionResult:
    schema_name: str = MERGE_ADMISSION_SCHEMA_NAME
    schema_version: str = MERGE_ADMISSION_SCHEMA_VERSION
    status: AdmissionStatus
    result_id: str
    repository: str
    pull_request: int
    base_sha: str
    head_sha: str
    profile: str
    plan_id: str
    evidence_result_id: str | None
    reason_codes: tuple[str, ...]
    authoritative: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def evaluate_merge_admission(
    plan: object,
    evidence: object | None,
    *,
    current_base_sha: object,
    current_head_sha: object,
    schema_version: object = MERGE_ADMISSION_SCHEMA_VERSION,
) -> MergeAdmissionResult:
    """Evaluate validation sufficiency for one exact candidate without granting merge authority.

    The existing validation selector remains the sole changed-surface classifier.
    This evaluator only consumes its canonical plan and current evidence.
    """
    if not isinstance(plan, ValidationPlan) or validate_validation_plan(plan):
        return _result(plan, None, "block", ("admission.plan-invalid",))
    if schema_version != MERGE_ADMISSION_SCHEMA_VERSION:
        return _result(plan, None, "block", ("admission.schema-version",))
    if current_head_sha != plan.head_sha:
        return _result(plan, _evidence(evidence), "block", ("revision.head-sha-stale",))
    if current_base_sha != plan.base_sha:
        return _result(plan, _evidence(evidence), "block", ("revision.base-sha-stale",))

    if plan.profile == "manual-review":
        return _result(plan, _evidence(evidence), "manual-review", ("admission.selector-manual-review",))

    if plan.profile == "static":
        # Static/documentation selection is itself the required deterministic proof.
        # It remains non-authorizing and can be composed with other release gates.
        return _result(plan, None, "admit", ("admission.static-plan-sufficient",))

    advisory = _evidence(evidence)
    if advisory is None:
        status = "require-aggregate" if plan.profile == "aggregate" else "block"
        reason = "admission.aggregate-required" if plan.profile == "aggregate" else "admission.focused-evidence-missing"
        return _result(plan, None, status, (reason,))

    mismatch = _evidence_mismatch(plan, advisory)
    if mismatch:
        return _result(plan, advisory, "block", mismatch)

    if advisory.status == "passed":
        if plan.profile == "aggregate":
            return _result(plan, advisory, "admit", ("admission.aggregate-passed",))
        return _result(plan, advisory, "admit", ("admission.focused-passed",))

    if advisory.status == "needs-decision":
        return _result(plan, advisory, "manual-review", ("admission.evidence-needs-decision",))
    if advisory.status == "stale":
        return _result(plan, advisory, "block", ("admission.evidence-stale",))
    if advisory.status == "incomplete":
        if plan.profile == "focused":
            return _result(plan, advisory, "require-aggregate", ("admission.focused-incomplete",))
        return _result(plan, advisory, "block", ("admission.aggregate-incomplete",))
    if advisory.status == "failed":
        return _result(plan, advisory, "block", (f"admission.{plan.profile}-failed",))
    return _result(plan, advisory, "block", ("admission.evidence-invalid",))


def serialize_merge_admission(result: MergeAdmissionResult) -> dict[str, object]:
    if not isinstance(result, MergeAdmissionResult):
        raise TypeError("result must be MergeAdmissionResult")
    payload = _payload(result)
    expected = "merge-admission:" + _digest(payload)
    if result.result_id != expected:
        raise ValueError("merge admission result ID mismatch")
    serialized = dict(payload)
    serialized["result_id"] = result.result_id
    if len(json.dumps(serialized, sort_keys=True, separators=(",", ":")).encode()) > MAX_ADMISSION_SERIALIZED_BYTES:
        raise ValueError("merge admission result exceeds size limit")
    return serialized


def merge_admission_result_id(result: MergeAdmissionResult) -> str:
    return str(serialize_merge_admission(result)["result_id"])


def _evidence(value: object | None) -> AdvisoryEvidenceResult | None:
    return value if isinstance(value, AdvisoryEvidenceResult) else None


def _evidence_mismatch(plan: ValidationPlan, evidence: AdvisoryEvidenceResult) -> tuple[str, ...]:
    reasons: set[str] = set()
    checks = (
        (evidence.pull_request, plan.pull_request, "identity.pull-request-mismatch"),
        (evidence.base_sha, plan.base_sha, "identity.base-sha-mismatch"),
        (evidence.source_head_sha, plan.head_sha, "identity.head-sha-mismatch"),
        (evidence.tested_sha, plan.head_sha, "identity.tested-sha-mismatch"),
        (evidence.selector_version, plan.selector_version, "identity.selector-version-mismatch"),
        (evidence.profile, plan.profile, "identity.profile-mismatch"),
        (evidence.command_set_digest, plan.command_set_digest, "identity.command-digest-mismatch"),
        (evidence.plan_id, validation_plan_id(plan), "identity.plan-id-mismatch"),
    )
    for actual, expected, reason in checks:
        if actual != expected:
            reasons.add(reason)
    return tuple(sorted(reasons))


def _result(
    plan: object,
    evidence: AdvisoryEvidenceResult | None,
    status: AdmissionStatus,
    reasons: tuple[str, ...],
) -> MergeAdmissionResult:
    valid = plan if isinstance(plan, ValidationPlan) else None
    preliminary = MergeAdmissionResult(
        status=status,
        result_id="",
        repository=valid.repository if valid is not None else "unavailable",
        pull_request=valid.pull_request if valid is not None else 0,
        base_sha=valid.base_sha if valid is not None else "unavailable",
        head_sha=valid.head_sha if valid is not None else "unavailable",
        profile=valid.profile if valid is not None else "unavailable",
        plan_id=validation_plan_id(valid) if valid is not None and not validate_validation_plan(valid) else "unavailable",
        evidence_result_id=evidence.result_id if evidence is not None else None,
        reason_codes=tuple(sorted(set(reasons)))[:MAX_ADMISSION_REASON_CODES],
    )
    return replace(preliminary, result_id="merge-admission:" + _digest(_payload(preliminary)))


def _payload(result: MergeAdmissionResult) -> dict[str, object]:
    return {
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "status": result.status,
        "repository": result.repository,
        "pull_request": result.pull_request,
        "base_sha": result.base_sha,
        "head_sha": result.head_sha,
        "profile": result.profile,
        "plan_id": result.plan_id,
        "evidence_result_id": result.evidence_result_id,
        "reason_codes": list(result.reason_codes),
        "authoritative": False,
        "merge_authorized": False,
        "side_effects_performed": False,
    }


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(b"agent-os-merge-admission:v1\0" + encoded).hexdigest()
