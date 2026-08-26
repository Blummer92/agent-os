"""Pure deterministic compute-control decision projection (#1419).

This module composes caller-supplied canonical Agent OS evidence into one
bounded, non-authorizing statement of whether compute is currently justified
and what the cheapest valid governed next validation step is. It performs no
GitHub, network, filesystem, subprocess, Scheduler, provider, or Notion I/O;
executes, dispatches, or cancels nothing; and creates no authority.

It owns composition only. Executor routing, validation selection and
classification, evidence applicability, authorization, active-run ownership,
Scheduler behavior, and compute measurement all remain with their existing
canonical owners; this projection reads their already-computed results and
never re-derives or overrides them.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from scripts.agent_os_remote_validation.models import ValidationPlan
from scripts.agent_os_remote_validation.provenance import (
    EvidenceApplicabilityProjection,
    serialize_evidence_applicability,
)

from .coding_command_center_handoff import CodingCommandCenterHandoff
from .issue_operational_state import (
    IssueOperationalState,
    LifecycleStage,
    OperationalOutcome,
)

COMPUTE_CONTROL_PROJECTION_SCHEMA_NAME = "agent-os-compute-control-projection"
COMPUTE_CONTROL_PROJECTION_SCHEMA_VERSION = "1.0"
MAX_TEXT_BYTES = 4096
MAX_REASON_CODES = 32
MAX_SERIALIZED_BYTES = 64 * 1024
_UNAVAILABLE = "unavailable"
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

# Mirrors the canonical validation-head disposition vocabulary owned by
# ``agent_os_execution_service.validation_supersession``. That module is
# deliberately not imported: it lives in a separately installed distribution
# that is absent from the root developer environment, and it imports this
# package, so a direct import would both break root validation and invert the
# dependency direction. Only its already-projected decision is consumed here,
# by reference; no supersession semantics are re-derived.
VALIDATION_HEAD_DISPOSITIONS = frozenset(
    {
        "passed",
        "failed",
        "pending",
        "stale-head",
        "superseded-by-new-head",
        "cancelled-by-user-or-external-action",
        "timed-out",
        "infrastructure-failure",
        "quarantined",
        "blocked",
        "needs-decision",
    }
)
_STALE_HEAD_DISPOSITIONS = frozenset({"stale-head", "superseded-by-new-head"})
_ACTIVE_EXECUTION_PHASES = frozenset({"queued", "in-progress"})
# Canonical validation profiles owned by agent_os_remote_validation.models.
_PROFILE_DISPOSITIONS = {
    "static": "run-now",
    "focused": "focused-validation-first",
    "aggregate": "final-cloud-validation-required",
    "manual-review": "do-not-spend-compute-yet",
}


class ComputeDisposition(str, Enum):
    """The finite non-authorizing compute-control vocabulary frozen by #1419."""

    RUN_NOW = "run-now"
    DO_NOT_SPEND_COMPUTE_YET = "do-not-spend-compute-yet"
    FOCUSED_VALIDATION_FIRST = "focused-validation-first"
    FINAL_CLOUD_VALIDATION_REQUIRED = "final-cloud-validation-required"
    REUSE_EXISTING_EVIDENCE = "reuse-existing-evidence"
    DUPLICATE_OR_OBSOLETE_RUN_RISK = "duplicate-or-obsolete-run-risk"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ActiveExecutionReference:
    """A bounded reference to an execution the caller already observed as active.

    This is a reference only. It confers no ownership of the run, no lease, and
    no cancellation authority.
    """

    reference: str
    head_sha: str
    phase: Literal["queued", "in-progress"]

    def __post_init__(self) -> None:
        _required_text(self.reference, "reference")
        _sha40(self.head_sha, "head_sha")
        if self.phase not in _ACTIVE_EXECUTION_PHASES:
            raise ValueError("phase must be a non-terminal active execution phase")


@dataclass(frozen=True, slots=True)
class ValidationHeadReference:
    """A bounded reference to an already-projected canonical head decision."""

    decision_id: str
    disposition: str
    prior_head_sha: str
    current_head_sha: str
    satisfies_current_head: bool

    def __post_init__(self) -> None:
        _required_text(self.decision_id, "decision_id")
        if self.disposition not in VALIDATION_HEAD_DISPOSITIONS:
            raise ValueError("disposition must use the canonical validation-head vocabulary")
        _sha40(self.prior_head_sha, "prior_head_sha")
        _sha40(self.current_head_sha, "current_head_sha")
        if type(self.satisfies_current_head) is not bool:
            raise TypeError("satisfies_current_head must be a built-in bool")


@dataclass(frozen=True, slots=True)
class ComputeControlEvidence:
    """Canonical projections supplied by the caller for one exact identity."""

    handoff: CodingCommandCenterHandoff
    operational_state: IssueOperationalState
    current_head_sha: str | None = None
    validation_plan: ValidationPlan | None = None
    evidence_applicability: EvidenceApplicabilityProjection | None = None
    validation_head_reference: ValidationHeadReference | None = None
    active_execution: ActiveExecutionReference | None = None
    measured_compute_metadata_reference: str | None = None

    def __post_init__(self) -> None:
        if type(self.handoff) is not CodingCommandCenterHandoff:
            raise TypeError("handoff must be exact CodingCommandCenterHandoff")
        if type(self.operational_state) is not IssueOperationalState:
            raise TypeError("operational_state must be exact IssueOperationalState")
        # One identity's evidence can never satisfy another; a mismatched pair is
        # not a disposition, it is malformed input.
        state = self.operational_state
        if (
            self.handoff.repository != state.repository
            or self.handoff.issue_number != state.issue_number
            or self.handoff.source_revision != state.source_revision
            or self.handoff.canonical_state_reference != state.state_id
        ):
            raise ValueError("handoff and operational state describe different identities")
        if self.current_head_sha is not None:
            _sha40(self.current_head_sha, "current_head_sha")
        if self.validation_plan is not None and type(self.validation_plan) is not ValidationPlan:
            raise TypeError("validation_plan must be exact ValidationPlan or None")
        if self.evidence_applicability is not None and type(self.evidence_applicability) is not EvidenceApplicabilityProjection:
            raise TypeError("evidence_applicability must be exact EvidenceApplicabilityProjection or None")
        if self.validation_head_reference is not None and type(self.validation_head_reference) is not ValidationHeadReference:
            raise TypeError("validation_head_reference must be exact ValidationHeadReference or None")
        if self.active_execution is not None and type(self.active_execution) is not ActiveExecutionReference:
            raise TypeError("active_execution must be exact ActiveExecutionReference or None")
        _optional_text(self.measured_compute_metadata_reference, "measured_compute_metadata_reference")


@dataclass(frozen=True, slots=True)
class ComputeControlProjection:
    schema_name: Literal["agent-os-compute-control-projection"]
    schema_version: Literal["1.0"]
    repository: str
    issue_number: int
    pull_request_number: int | None
    current_head_sha: str | None
    base_handoff_projection_reference: str
    compute_disposition: ComputeDisposition
    recommended_validation_or_execution_class: str | None
    primary_blocker: str | None
    duplicate_or_stale_risk: bool
    active_execution_reference: str | None
    last_applicable_validation_reference: str | None
    measured_compute_metadata_reference: str | None
    reason_codes: tuple[str, ...]
    source_revision: str
    projection_id: str = ""
    authority_created: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)
    notion_write_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_name != COMPUTE_CONTROL_PROJECTION_SCHEMA_NAME
            or self.schema_version != COMPUTE_CONTROL_PROJECTION_SCHEMA_VERSION
        ):
            raise ValueError("unsupported compute-control projection schema")
        _required_text(self.repository, "repository")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise TypeError("issue_number must be a positive built-in integer")
        if self.pull_request_number is not None and (
            type(self.pull_request_number) is not int or self.pull_request_number < 1
        ):
            raise TypeError("pull_request_number must be a positive built-in integer or None")
        if self.current_head_sha is not None:
            _sha40(self.current_head_sha, "current_head_sha")
        _required_text(self.base_handoff_projection_reference, "base_handoff_projection_reference")
        if type(self.compute_disposition) is not ComputeDisposition:
            raise TypeError("compute_disposition must be an exact ComputeDisposition")
        for name in (
            "recommended_validation_or_execution_class",
            "primary_blocker",
            "active_execution_reference",
            "last_applicable_validation_reference",
            "measured_compute_metadata_reference",
        ):
            _optional_text(getattr(self, name), name)
        if type(self.duplicate_or_stale_risk) is not bool:
            raise TypeError("duplicate_or_stale_risk must be a built-in bool")
        _sha40(self.source_revision, "source_revision")
        object.__setattr__(self, "reason_codes", _canonical_reasons(self.reason_codes))
        expected = "compute-control-projection:" + hashlib.sha256(
            b"agent-os-compute-control-projection:v1\0" + _canonical_json(self._payload()).encode("utf-8")
        ).hexdigest()
        if self.projection_id and self.projection_id != expected:
            raise ValueError("projection_id does not match canonical content")
        object.__setattr__(self, "projection_id", expected)
        if len(_canonical_json(self.to_dict()).encode("utf-8")) > MAX_SERIALIZED_BYTES:
            raise ValueError("compute-control projection exceeds serialized bound")

    def _payload(self) -> dict[str, object]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "pull_request_number": self.pull_request_number,
            "current_head_sha": self.current_head_sha,
            "base_handoff_projection_reference": self.base_handoff_projection_reference,
            "compute_disposition": self.compute_disposition.value,
            "recommended_validation_or_execution_class": self.recommended_validation_or_execution_class,
            "primary_blocker": self.primary_blocker,
            "duplicate_or_stale_risk": self.duplicate_or_stale_risk,
            "active_execution_reference": self.active_execution_reference,
            "last_applicable_validation_reference": self.last_applicable_validation_reference,
            "measured_compute_metadata_reference": self.measured_compute_metadata_reference,
            "reason_codes": list(self.reason_codes),
            "source_revision": self.source_revision,
            "authority_created": False,
            "side_effects_performed": False,
            "notion_write_performed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "projection_id": self.projection_id}


def build_compute_control_projection(
    evidence: ComputeControlEvidence,
) -> ComputeControlProjection:
    """Compose canonical evidence into one finite compute disposition.

    Precedence is fail-closed and fixed: currentness before prerequisites,
    prerequisites before duplicate risk, duplicate risk before reuse, and reuse
    before any instruction to spend compute. Missing evidence never becomes
    compute admission.
    """
    if type(evidence) is not ComputeControlEvidence:
        raise TypeError("evidence must be exact ComputeControlEvidence")
    state = evidence.operational_state
    handoff = evidence.handoff
    # Re-run each supplied record's own invariant so tampered frozen objects fail closed.
    for record, label in ((state, "operational state"), (handoff, "handoff projection")):
        try:
            record.__post_init__()
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} validation failed") from exc

    reasons: set[str] = set()
    head = evidence.current_head_sha
    plan = evidence.validation_plan
    applicability = evidence.evidence_applicability
    head_reference = evidence.validation_head_reference
    active = evidence.active_execution
    primary_pr = state.primary_pr_numbers[0] if len(state.primary_pr_numbers) == 1 else None
    blocker = state.blocker_codes[0] if state.blocker_codes else None

    if applicability is not None:
        # Verifies the projection's own content-addressed identity.
        try:
            serialize_evidence_applicability(applicability)
        except (TypeError, ValueError) as exc:
            raise ValueError("evidence applicability validation failed") from exc

    duplicate_or_stale_risk = active is not None or (
        head_reference is not None and head_reference.disposition in _STALE_HEAD_DISPOSITIONS
    )
    if duplicate_or_stale_risk:
        reasons.add("compute.duplicate-or-stale-risk-observed")

    disposition = _decide(
        state=state,
        handoff=handoff,
        head=head,
        plan=plan,
        applicability=applicability,
        head_reference=head_reference,
        active=active,
        reasons=reasons,
    )

    recommended = plan.profile if plan is not None and disposition is not ComputeDisposition.UNAVAILABLE else None
    return ComputeControlProjection(
        schema_name=COMPUTE_CONTROL_PROJECTION_SCHEMA_NAME,
        schema_version=COMPUTE_CONTROL_PROJECTION_SCHEMA_VERSION,
        repository=state.repository,
        issue_number=state.issue_number,
        pull_request_number=primary_pr,
        current_head_sha=head,
        base_handoff_projection_reference=handoff.handoff_id,
        compute_disposition=disposition,
        recommended_validation_or_execution_class=recommended,
        primary_blocker=blocker,
        duplicate_or_stale_risk=duplicate_or_stale_risk,
        active_execution_reference=active.reference if active is not None else None,
        last_applicable_validation_reference=(
            applicability.applicability_id if applicability is not None else None
        ),
        measured_compute_metadata_reference=evidence.measured_compute_metadata_reference,
        reason_codes=tuple(sorted(reasons)),
        source_revision=state.source_revision,
    )


def _decide(
    *,
    state: IssueOperationalState,
    handoff: CodingCommandCenterHandoff,
    head: str | None,
    plan: ValidationPlan | None,
    applicability: EvidenceApplicabilityProjection | None,
    head_reference: ValidationHeadReference | None,
    active: ActiveExecutionReference | None,
    reasons: set[str],
) -> ComputeDisposition:
    # 1. Currentness and exact identity fail closed before anything else.
    if state.outcome in {
        OperationalOutcome.STALE,
        OperationalOutcome.CONFLICTING,
        OperationalOutcome.INVALID,
    }:
        reasons.add("compute.fail-closed-currentness")
        return ComputeDisposition.UNAVAILABLE
    if "handoff.fail-closed-currentness" in handoff.reason_codes:
        reasons.add("compute.fail-closed-currentness")
        return ComputeDisposition.UNAVAILABLE
    if handoff.observed_head_sha is not None and handoff.observed_head_sha != head:
        reasons.add("compute.head-identity-conflict")
        return ComputeDisposition.UNAVAILABLE
    if head_reference is not None and head_reference.current_head_sha != head:
        reasons.add("compute.head-identity-conflict")
        return ComputeDisposition.UNAVAILABLE
    if plan is not None and not _plan_binds_identity(plan, state, head):
        reasons.add("compute.plan-identity-mismatch")
        return ComputeDisposition.UNAVAILABLE

    # 2. Non-compute prerequisites: the next legitimate step is not compute.
    if state.outcome is OperationalOutcome.TERMINAL:
        reasons.add("compute.terminal-no-compute")
        return ComputeDisposition.DO_NOT_SPEND_COMPUTE_YET
    if state.lifecycle_stage is LifecycleStage.PLANNING:
        reasons.add("compute.roadmap-only-coordination")
        return ComputeDisposition.DO_NOT_SPEND_COMPUTE_YET
    if state.outcome in {OperationalOutcome.BLOCKED, OperationalOutcome.NEEDS_DECISION}:
        # The canonical primary blocker owns ordering; this only reads it. A
        # missing implementation authorization is already folded into the
        # canonical outcome, so it is refined here rather than re-gated.
        primary = state.blocker_codes[0] if state.blocker_codes else None
        if primary is not None and primary.startswith("authorization.implementation"):
            reasons.add("compute.implementation-not-authorized")
        elif state.outcome is OperationalOutcome.BLOCKED:
            reasons.add("compute.blocked-prerequisite")
        else:
            reasons.add("compute.human-decision-prerequisite")
        return ComputeDisposition.DO_NOT_SPEND_COMPUTE_YET

    # 3. An already-active execution: spending more compute now would duplicate it.
    if active is not None:
        reasons.add(
            "compute.active-execution-obsolete-head"
            if active.head_sha != head
            else "compute.active-execution-duplicate"
        )
        return ComputeDisposition.DUPLICATE_OR_OBSOLETE_RUN_RISK

    # 4. Reuse only where both canonical owners explicitly prove it for this head.
    if _reuse_proven(applicability, head_reference):
        reasons.add("compute.exact-identity-reuse-proven")
        return ComputeDisposition.REUSE_EXISTING_EVIDENCE

    # 5. The canonical plan profile names the cheapest valid governed next step.
    if plan is None:
        reasons.add("compute.validation-plan-unavailable")
        return ComputeDisposition.UNAVAILABLE
    reasons.add(f"compute.profile-{plan.profile}")
    return ComputeDisposition(_PROFILE_DISPOSITIONS[plan.profile])


def _plan_binds_identity(
    plan: ValidationPlan, state: IssueOperationalState, head: str | None
) -> bool:
    if plan.repository != state.repository or plan.head_sha != head:
        return False
    return state.primary_pr_numbers == () or plan.pull_request in state.primary_pr_numbers


def _reuse_proven(
    applicability: EvidenceApplicabilityProjection | None,
    head_reference: ValidationHeadReference | None,
) -> bool:
    """Reuse requires both canonical owners to say yes for the exact current head.

    Applicability alone never authorizes skipping a required check, and a head
    decision alone never proves the evidence is applicable.
    """
    if applicability is None or head_reference is None:
        return False
    return (
        applicability.applicability == "fresh-and-applicable"
        and head_reference.satisfies_current_head
        and head_reference.disposition == "passed"
    )


def render_compute_control_projection(projection: ComputeControlProjection) -> str:
    """Render #926-compatible operator ordering without adding new semantics."""
    payload = serialize_compute_control_projection(projection)
    lines = (
        f"Current target: {payload['repository']}#{payload['issue_number']}",
        f"Compute disposition: {payload['compute_disposition']}",
        f"Recommended validation class: {payload['recommended_validation_or_execution_class'] or _UNAVAILABLE}",
        f"Blocker evidence: {payload['primary_blocker'] or _UNAVAILABLE}",
        f"Duplicate or stale risk: {'true' if payload['duplicate_or_stale_risk'] else 'false'}",
        f"Active execution: {payload['active_execution_reference'] or _UNAVAILABLE}",
        f"Base handoff projection: {payload['base_handoff_projection_reference']}",
        f"Last applicable validation: {payload['last_applicable_validation_reference'] or _UNAVAILABLE}",
        f"Measured compute metadata: {payload['measured_compute_metadata_reference'] or _UNAVAILABLE}",
        f"Current head: {payload['current_head_sha'] or _UNAVAILABLE}",
        f"Source revision: {payload['source_revision']}",
        "authority_created: false",
        "side_effects_performed: false",
        "notion_write_performed: false",
    )
    return "\n".join(lines)


def serialize_compute_control_projection(
    projection: ComputeControlProjection,
) -> dict[str, object]:
    if type(projection) is not ComputeControlProjection:
        raise TypeError("projection must be exact ComputeControlProjection")
    projection.__post_init__()
    return projection.to_dict()


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _required_text(value: object, name: str) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > MAX_TEXT_BYTES or _CONTROL_RE.search(value):
        raise ValueError(f"{name} is outside bounds")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, name)


def _sha40(value: object, name: str) -> str:
    text = _required_text(value, name)
    if not _SHA40_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase 40-character SHA")
    return text


def _canonical_reasons(values: object) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError("reason_codes must be an exact tuple")
    if len(values) > MAX_REASON_CODES:
        raise ValueError("reason_codes exceeds bound")
    checked = tuple(_required_text(item, "reason_code") for item in values)
    if len(set(checked)) != len(checked):
        raise ValueError("reason_codes contains duplicates")
    return tuple(sorted(checked))
