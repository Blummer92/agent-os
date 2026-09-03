"""WSC5R quarantine evidence and operator review workflow.

Consumes an existing, immutable ``SingleIssuePilotResult`` (from
``single_issue_pilot.py``, frozen under PR #578) whose ``status`` is
``"quarantined"`` and produces:

1. an immutable quarantine evidence packet bound to that result's identity;
2. append-only review events with deterministic, domain-separated identity;
3. bounded review-capacity and pause observations;
4. a manual recovery handoff packet for the "recommend fresh invocation"
   disposition.

This module performs no I/O. It opens no network connection, spawns no
subprocess, touches no clock, persists nothing, mutates no lease, mutates no
GitHub state, and dispatches no Scheduler work. It does not import the
legacy executor, retry manager, request dispatch, or any persistence,
network, or GitHub client. Every disposition it can record is evidence only;
none of them execute cleanup, rollback, retry, dispatch, or publication.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Literal

from workflow_scheduler.execution.single_issue_pilot import SingleIssuePilotResult

QUARANTINE_REVIEW_SCHEMA_NAME = "agent-os-wsc5r-quarantine-review"
QUARANTINE_REVIEW_SCHEMA_VERSION = "1.0"

MAX_FIELD_LENGTH = 2048
MAX_BOUNDED_ITEMS = 64
MAX_PACKET_SERIALIZED_BYTES = 131_072
MAX_EVENT_SERIALIZED_BYTES = 16_384
MAX_OPEN_REVIEWS = 25
MAX_REVIEW_AGE_EVENTS = 50

QuarantineReviewState = Literal[
    "contained-evidence-incomplete",
    "contained-no-effects-proven",
    "manual-cleanup-required",
    "lease-ownership-unresolved",
    "repository-state-unresolved",
    "partial-effects-confirmed",
    "termination-unresolved",
    "recovery-completed",
    "stop-all-scheduler-execution",
]

QUARANTINE_REVIEW_STATES: frozenset[str] = frozenset(
    {
        "contained-evidence-incomplete",
        "contained-no-effects-proven",
        "manual-cleanup-required",
        "lease-ownership-unresolved",
        "repository-state-unresolved",
        "partial-effects-confirmed",
        "termination-unresolved",
        "recovery-completed",
        "stop-all-scheduler-execution",
    }
)

ReviewDisposition = Literal[
    "preserve-and-investigate",
    "confirm-no-effects-with-evidence",
    "require-repository-inspection",
    "require-workspace-inspection",
    "require-lease-inspection",
    "request-authorized-cleanup",
    "request-authorized-rollback",
    "record-manual-remediation-evidence",
    "permanently-block-candidate",
    "pause-all-scheduler-execution",
    "recommend-fresh-invocation",
]

ALLOWED_REVIEW_DISPOSITIONS: frozenset[str] = frozenset(
    {
        "preserve-and-investigate",
        "confirm-no-effects-with-evidence",
        "require-repository-inspection",
        "require-workspace-inspection",
        "require-lease-inspection",
        "request-authorized-cleanup",
        "request-authorized-rollback",
        "record-manual-remediation-evidence",
        "permanently-block-candidate",
        "pause-all-scheduler-execution",
        "recommend-fresh-invocation",
    }
)

# Dispositions that may resolve containment into recovery-completed once
# machine-verified. All others leave the review state unchanged (evidence
# only; no execution authorization).
_RESOLVING_DISPOSITIONS: frozenset[str] = frozenset(
    {"record-manual-remediation-evidence", "recommend-fresh-invocation"}
)

# States from which downgrading to a less-severe state without independent
# machine-verified evidence is forbidden.
_NON_DOWNGRADABLE_STATES: frozenset[str] = frozenset(
    {"termination-unresolved", "partial-effects-confirmed", "stop-all-scheduler-execution"}
)

_STOP_ALL_REASON_CODES: frozenset[str] = frozenset(
    {
        "lease.release-forced",
        "workspace.force-cleanup-forbidden",
        "executor.duplicate-dispatch",
        "executor.exception",
        "changed-paths.forbidden",
        "changed-paths.out-of-allowlist",
        "pilot.unexpected-error",
    }
)

_TERMINATION_REASON_CODES: frozenset[str] = frozenset(
    {
        "executor.termination-unconfirmed",
        "cancellation.unconfirmed",
        # A lease held back because termination was never proven is a
        # termination question first. It must not be downgraded to the
        # narrower lease-ownership state, which is downgradable and would
        # lose the reason the ownership is still held.
        "lease.release-withheld-unproven-termination",
    }
)

_PARTIAL_EFFECTS_REASON_CODES: frozenset[str] = frozenset({"executor.possible-partial-effects"})

_LEASE_REASON_CODES: frozenset[str] = frozenset(
    {
        "lease.duplicate-request",
        "lease.acquisition-failed",
        "lease.identity-mismatch",
        "lease.holder-drift",
        "lease.generation-drift",
        "lease.release-failed",
        "lease.release-ambiguous",
    }
)

_WORKSPACE_REASON_CODES: frozenset[str] = frozenset(
    {
        "workspace.creation-failed",
        "workspace.repository-mismatch",
        "workspace.branch-mismatch",
        "workspace.dirty",
        "workspace.detached",
        "workspace.reused",
        "workspace.missing",
        "workspace.prunable",
        "workspace.locked",
        "workspace.revision-mismatch",
        "workspace.unresolved",
    }
)

_CLEANUP_REASON_CODES: frozenset[str] = frozenset(
    {"workspace.filesystem-cleanup-failed", "workspace.metadata-cleanup-failed"}
)

_VALIDATION_REASON_CODES: frozenset[str] = frozenset(
    {"validation.failed", "validation.error", "validation.required-tests-missing"}
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)ghp_[a-z0-9]{20,}"),
    re.compile(r"(?i)gho_[a-z0-9]{20,}"),
    re.compile(r"(?i)AKIA[0-9A-Z]{12,}"),
    re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bsk-[a-z0-9]{16,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret|password|token)\b\s*[:=]\s*\S+"),
)


class QuarantineReviewError(ValueError):
    """Raised whenever quarantine evidence would otherwise fail closed."""


# --------------------------------------------------------------------------
# Canonical identity helpers (local, domain-separated; mirrors the pattern
# used by single_issue_pilot.py without importing its private helpers).
# --------------------------------------------------------------------------


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _semantic_digest(domain: str, payload: object) -> str:
    return hashlib.sha256(
        f"{domain}:v1".encode("utf-8") + b"\0" + _canonical_bytes(payload)
    ).hexdigest()


def _bounded_text(value: object, name: str, *, maximum: int = MAX_FIELD_LENGTH) -> str:
    if not isinstance(value, str) or not value:
        raise QuarantineReviewError(f"{name} must be a non-empty string")
    if len(value) > maximum:
        raise QuarantineReviewError(f"{name} exceeds the bounded length")
    return value


def _bounded_optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, name)


def _bounded_strings(values: object, name: str, *, maximum: int = MAX_BOUNDED_ITEMS) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise QuarantineReviewError(f"{name} must be an iterable of strings")
    items = tuple(str(item) for item in values)
    if len(items) > maximum:
        raise QuarantineReviewError(f"{name} exceeds the bounded item count")
    for item in items:
        if not item or len(item) > MAX_FIELD_LENGTH:
            raise QuarantineReviewError(f"{name} contains an unbounded or empty value")
    return items


def redact_text(value: str, *, name: str, maximum: int = MAX_FIELD_LENGTH) -> str:
    """Return a bounded, secret-redacted copy of ``value``.

    Preserves a stable digest and explicit truncation/redaction markers so
    tampering with the original content is detectable, while never
    retaining the raw secret-like substring or unbounded output.
    """
    if not isinstance(value, str):
        raise QuarantineReviewError(f"{name} must be a string")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    text = value
    redacted = False
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            text = pattern.sub("[redacted]", text)
            redacted = True
    truncated = False
    if len(text) > maximum:
        text = text[:maximum]
        truncated = True
    marker = []
    if redacted:
        marker.append("redacted")
    if truncated:
        marker.append(f"truncated:{len(value)}")
    suffix = f"[[{','.join(marker)}|sha256:{digest}]]" if marker else f"[[sha256:{digest}]]"
    return f"{text}{suffix}"


def reject_if_secret_like(value: str, *, name: str) -> str:
    """Return ``value`` unchanged, or raise if it contains secret-like content."""
    if not isinstance(value, str):
        raise QuarantineReviewError(f"{name} must be a string")
    for pattern in _SECRET_PATTERNS:
        if pattern.search(value):
            raise QuarantineReviewError(f"{name} appears to contain secret-like content")
    if len(value) > MAX_FIELD_LENGTH:
        raise QuarantineReviewError(f"{name} exceeds the bounded length")
    return value


# --------------------------------------------------------------------------
# Frozen operator-state classification
# --------------------------------------------------------------------------


def classify_quarantine_state(result: SingleIssuePilotResult) -> QuarantineReviewState:
    """Deterministically map a quarantined pilot result to exactly one state.

    Uses the result's own bounded evidence fields as the primary signal and
    its ``reason_codes`` as corroborating/escalating evidence. Any condition
    listed in the WSC5R pause rules as requiring ``stop-all-scheduler-execution``
    dominates every narrower classification.
    """
    if not isinstance(result, SingleIssuePilotResult):
        raise QuarantineReviewError("result must be SingleIssuePilotResult")
    if result.status != "quarantined":
        raise QuarantineReviewError("only a quarantined pilot result may be classified")

    codes = set(result.reason_codes)

    stop_all = bool(codes & _STOP_ALL_REASON_CODES) or any(
        code.startswith("evidence.") or code.startswith("identity.") for code in codes
    )
    if stop_all:
        return "stop-all-scheduler-execution"

    if (
        not result.termination_confirmed
        or bool(codes & _TERMINATION_REASON_CODES)
    ):
        return "termination-unresolved"

    if result.possible_partial_effects or bool(codes & _PARTIAL_EFFECTS_REASON_CODES):
        return "partial-effects-confirmed"

    if bool(codes & _LEASE_REASON_CODES) or (
        result.lease_acquired and not result.lease_released
    ):
        return "lease-ownership-unresolved"

    if bool(codes & _WORKSPACE_REASON_CODES) or (
        result.workspace_created and not result.workspace_inspected
    ):
        return "repository-state-unresolved"

    if bool(codes & _CLEANUP_REASON_CODES) or (
        result.workspace_created
        and not (result.workspace_filesystem_cleaned and result.workspace_metadata_cleaned)
    ):
        return "manual-cleanup-required"

    if not result.executor_called:
        return "contained-no-effects-proven"

    if bool(codes & _VALIDATION_REASON_CODES) or not result.validation_passed:
        return "contained-evidence-incomplete"

    return "contained-evidence-incomplete"


def requires_pause(state: QuarantineReviewState) -> bool:
    """Return True when the review state requires pausing the affected scope."""
    return state in {
        "manual-cleanup-required",
        "lease-ownership-unresolved",
        "repository-state-unresolved",
        "partial-effects-confirmed",
        "termination-unresolved",
        "stop-all-scheduler-execution",
    }


# --------------------------------------------------------------------------
# Quarantine evidence packet
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class QuarantineEvidencePacket:
    """Immutable, deterministic quarantine evidence bound to one pilot result."""

    schema_name: str
    schema_version: str
    packet_id: str
    result_id: str
    repository: str
    issue_numbers: tuple[int, ...]
    invocation_id: str
    base_sha: str
    source_head_sha: str
    tested_sha: str
    projection_id: str | None
    proposal_id: str | None
    approval_id: str | None
    approval_revision: str | None
    issueplan_evidence_id: str | None
    plan_id: str | None
    bundle_id: str | None
    advisory_result_id: str | None
    advisory_render_id: str | None
    primary_status: str
    status: str
    initial_review_state: QuarantineReviewState
    paused: bool
    executor_called: bool
    executor_started: bool
    cancellation_requested: bool
    termination_confirmed: bool
    possible_partial_effects: bool
    lease_identity: str | None
    lease_holder_identity: str | None
    lease_generation: int | None
    lease_acquired: bool
    lease_released: bool
    workspace_identity: str | None
    workspace_created: bool
    workspace_inspected: bool
    workspace_filesystem_cleaned: bool
    workspace_metadata_cleaned: bool
    changed_paths: tuple[str, ...]
    reason_codes: tuple[str, ...]
    details: tuple[str, ...]
    primary_error: str | None
    cleanup_errors: tuple[str, ...]
    release_errors: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_name != QUARANTINE_REVIEW_SCHEMA_NAME:
            raise QuarantineReviewError("unsupported quarantine review schema name")
        if self.schema_version != QUARANTINE_REVIEW_SCHEMA_VERSION:
            raise QuarantineReviewError("unsupported quarantine review schema version")
        if self.status != "quarantined":
            raise QuarantineReviewError("packet must bind a quarantined pilot result")
        if self.initial_review_state not in QUARANTINE_REVIEW_STATES:
            raise QuarantineReviewError("unsupported initial review state")
        if requires_pause(self.initial_review_state) and not self.paused:
            raise QuarantineReviewError(
                f"{self.initial_review_state} requires a mandatory pause; paused cannot be False"
            )
        object.__setattr__(self, "issue_numbers", tuple(self.issue_numbers))
        object.__setattr__(
            self, "projection_id", _bounded_optional_text(self.projection_id, "projection_id")
        )
        object.__setattr__(
            self, "proposal_id", _bounded_optional_text(self.proposal_id, "proposal_id")
        )
        object.__setattr__(
            self, "approval_id", _bounded_optional_text(self.approval_id, "approval_id")
        )
        object.__setattr__(
            self,
            "approval_revision",
            _bounded_optional_text(self.approval_revision, "approval_revision"),
        )
        object.__setattr__(
            self,
            "issueplan_evidence_id",
            _bounded_optional_text(self.issueplan_evidence_id, "issueplan_evidence_id"),
        )
        object.__setattr__(self, "plan_id", _bounded_optional_text(self.plan_id, "plan_id"))
        object.__setattr__(self, "bundle_id", _bounded_optional_text(self.bundle_id, "bundle_id"))
        object.__setattr__(
            self,
            "advisory_result_id",
            _bounded_optional_text(self.advisory_result_id, "advisory_result_id"),
        )
        object.__setattr__(
            self,
            "advisory_render_id",
            _bounded_optional_text(self.advisory_render_id, "advisory_render_id"),
        )
        object.__setattr__(self, "changed_paths", _bounded_strings(self.changed_paths, "changed_paths"))
        object.__setattr__(self, "reason_codes", _bounded_strings(self.reason_codes, "reason_codes"))
        object.__setattr__(self, "details", _bounded_strings(self.details, "details"))
        object.__setattr__(self, "cleanup_errors", _bounded_strings(self.cleanup_errors, "cleanup_errors"))
        object.__setattr__(self, "release_errors", _bounded_strings(self.release_errors, "release_errors"))
        object.__setattr__(
            self, "primary_error", _bounded_optional_text(self.primary_error, "primary_error")
        )


def _packet_payload(packet: QuarantineEvidencePacket) -> dict[str, object]:
    return {
        "schema_name": packet.schema_name,
        "schema_version": packet.schema_version,
        "result_id": packet.result_id,
        "repository": packet.repository,
        "issue_numbers": list(packet.issue_numbers),
        "invocation_id": packet.invocation_id,
        "base_sha": packet.base_sha,
        "source_head_sha": packet.source_head_sha,
        "tested_sha": packet.tested_sha,
        "projection_id": packet.projection_id,
        "proposal_id": packet.proposal_id,
        "approval_id": packet.approval_id,
        "approval_revision": packet.approval_revision,
        "issueplan_evidence_id": packet.issueplan_evidence_id,
        "plan_id": packet.plan_id,
        "bundle_id": packet.bundle_id,
        "advisory_result_id": packet.advisory_result_id,
        "advisory_render_id": packet.advisory_render_id,
        "primary_status": packet.primary_status,
        "status": packet.status,
        "initial_review_state": packet.initial_review_state,
        "paused": packet.paused,
        "executor_called": packet.executor_called,
        "executor_started": packet.executor_started,
        "cancellation_requested": packet.cancellation_requested,
        "termination_confirmed": packet.termination_confirmed,
        "possible_partial_effects": packet.possible_partial_effects,
        "lease_identity": packet.lease_identity,
        "lease_holder_identity": packet.lease_holder_identity,
        "lease_generation": packet.lease_generation,
        "lease_acquired": packet.lease_acquired,
        "lease_released": packet.lease_released,
        "workspace_identity": packet.workspace_identity,
        "workspace_created": packet.workspace_created,
        "workspace_inspected": packet.workspace_inspected,
        "workspace_filesystem_cleaned": packet.workspace_filesystem_cleaned,
        "workspace_metadata_cleaned": packet.workspace_metadata_cleaned,
        "changed_paths": list(packet.changed_paths),
        "reason_codes": list(packet.reason_codes),
        "details": list(packet.details),
        "primary_error": packet.primary_error,
        "cleanup_errors": list(packet.cleanup_errors),
        "release_errors": list(packet.release_errors),
    }


def quarantine_evidence_packet_id(packet: QuarantineEvidencePacket) -> str:
    """Return the domain-separated identity derived from the full packet content."""
    return "quarantine-evidence:" + _semantic_digest(
        "agent-os-wsc5r-quarantine-evidence", _packet_payload(packet)
    )


def serialize_quarantine_evidence_packet(packet: QuarantineEvidencePacket) -> dict[str, object]:
    """Return verified, JSON-compatible, tamper-checked packet evidence."""
    if not isinstance(packet, QuarantineEvidencePacket):
        raise QuarantineReviewError("packet must be QuarantineEvidencePacket")
    expected = quarantine_evidence_packet_id(packet)
    if packet.packet_id != expected:
        raise QuarantineReviewError("quarantine evidence packet identity mismatch (tampered or stale)")
    serialized = _packet_payload(packet)
    serialized["packet_id"] = packet.packet_id
    if len(_canonical_bytes(serialized)) > MAX_PACKET_SERIALIZED_BYTES:
        raise QuarantineReviewError("quarantine evidence packet exceeds the canonical size limit")
    return serialized


def build_quarantine_evidence_packet(
    result: SingleIssuePilotResult, *, paused: bool | None = None
) -> QuarantineEvidencePacket:
    """Build the one immutable quarantine evidence packet for ``result``.

    ``result`` must already be an immutable ``SingleIssuePilotResult`` with
    ``status == "quarantined"``; this function never mutates it and derives
    every field from its existing public attributes only.
    """
    initial_state = classify_quarantine_state(result)
    resolved_paused = requires_pause(initial_state) if paused is None else bool(paused)

    payload = {
        "schema_name": QUARANTINE_REVIEW_SCHEMA_NAME,
        "schema_version": QUARANTINE_REVIEW_SCHEMA_VERSION,
        "result_id": result.result_id,
        "repository": result.repository,
        "issue_numbers": list(result.issue_numbers),
        "invocation_id": result.invocation_id,
        "base_sha": result.base_sha,
        "source_head_sha": result.source_head_sha,
        "tested_sha": result.tested_sha,
        "projection_id": result.projection_id,
        "proposal_id": result.proposal_id,
        "approval_id": result.approval_id,
        "approval_revision": result.approval_revision,
        "issueplan_evidence_id": result.issueplan_evidence_id,
        "plan_id": result.plan_id,
        "bundle_id": result.bundle_id,
        "advisory_result_id": result.advisory_result_id,
        "advisory_render_id": result.advisory_render_id,
        "primary_status": result.primary_status,
        "status": result.status,
        "initial_review_state": initial_state,
        "paused": resolved_paused,
        "executor_called": result.executor_called,
        "executor_started": result.executor_started,
        "cancellation_requested": result.cancellation_requested,
        "termination_confirmed": result.termination_confirmed,
        "possible_partial_effects": result.possible_partial_effects,
        "lease_identity": result.lease_identity,
        "lease_holder_identity": result.lease_holder_identity,
        "lease_generation": result.lease_generation,
        "lease_acquired": result.lease_acquired,
        "lease_released": result.lease_released,
        "workspace_identity": result.workspace_identity,
        "workspace_created": result.workspace_created,
        "workspace_inspected": result.workspace_inspected,
        "workspace_filesystem_cleaned": result.workspace_filesystem_cleaned,
        "workspace_metadata_cleaned": result.workspace_metadata_cleaned,
        "changed_paths": list(result.changed_paths),
        "reason_codes": list(result.reason_codes),
        "details": list(result.details),
        "primary_error": result.primary_error,
        "cleanup_errors": list(result.cleanup_errors),
        "release_errors": list(result.release_errors),
    }
    packet_id = "quarantine-evidence:" + _semantic_digest(
        "agent-os-wsc5r-quarantine-evidence", payload
    )
    return QuarantineEvidencePacket(packet_id=packet_id, **payload)


# --------------------------------------------------------------------------
# Append-only review events
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewEvent:
    """One append-only, domain-separated review observation.

    Binds the exact packet identity plus the identity of the prior event (or
    the packet identity itself for the first event), so deletion or
    reordering of the append-only chain is detectable.
    """

    schema_name: str
    schema_version: str
    event_id: str
    packet_id: str
    prior_event_id: str
    sequence: int
    reviewer_identity: str
    review_timestamp: str
    disposition: ReviewDisposition
    rationale: str
    machine_verified: bool
    resulting_state: QuarantineReviewState
    new_invocation_id: str | None
    stop_all_recovery_verification: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_name != QUARANTINE_REVIEW_SCHEMA_NAME:
            raise QuarantineReviewError("unsupported quarantine review schema name")
        if self.schema_version != QUARANTINE_REVIEW_SCHEMA_VERSION:
            raise QuarantineReviewError("unsupported quarantine review schema version")
        if self.disposition not in ALLOWED_REVIEW_DISPOSITIONS:
            raise QuarantineReviewError("unsupported review disposition")
        if self.resulting_state not in QUARANTINE_REVIEW_STATES:
            raise QuarantineReviewError("unsupported resulting review state")
        if self.sequence < 1:
            raise QuarantineReviewError("event sequence must be positive")
        _bounded_text(self.reviewer_identity, "reviewer_identity")
        _bounded_text(self.review_timestamp, "review_timestamp")
        object.__setattr__(self, "rationale", reject_if_secret_like(self.rationale, name="rationale"))
        object.__setattr__(
            self, "new_invocation_id", _bounded_optional_text(self.new_invocation_id, "new_invocation_id")
        )
        object.__setattr__(
            self,
            "stop_all_recovery_verification",
            _bounded_verification_facts(self.stop_all_recovery_verification),
        )


def _bounded_verification_facts(values: object) -> tuple[str, ...]:
    facts = _bounded_strings(values, "stop_all_recovery_verification", maximum=MAX_BOUNDED_ITEMS)
    return tuple(
        reject_if_secret_like(fact, name="stop_all_recovery_verification") for fact in facts
    )


def _event_payload(event: ReviewEvent) -> dict[str, object]:
    return {
        "schema_name": event.schema_name,
        "schema_version": event.schema_version,
        "packet_id": event.packet_id,
        "prior_event_id": event.prior_event_id,
        "sequence": event.sequence,
        "reviewer_identity": event.reviewer_identity,
        "review_timestamp": event.review_timestamp,
        "disposition": event.disposition,
        "rationale": event.rationale,
        "machine_verified": event.machine_verified,
        "resulting_state": event.resulting_state,
        "new_invocation_id": event.new_invocation_id,
        "stop_all_recovery_verification": list(event.stop_all_recovery_verification),
    }


def review_event_id(event: ReviewEvent) -> str:
    """Return the domain-separated identity derived from the full event content."""
    return "quarantine-review-event:" + _semantic_digest(
        "agent-os-wsc5r-quarantine-review-event", _event_payload(event)
    )


def serialize_review_event(event: ReviewEvent) -> dict[str, object]:
    """Return verified, JSON-compatible, tamper-checked event evidence."""
    if not isinstance(event, ReviewEvent):
        raise QuarantineReviewError("event must be ReviewEvent")
    expected = review_event_id(event)
    if event.event_id != expected:
        raise QuarantineReviewError("review event identity mismatch (tampered or stale)")
    serialized = _event_payload(event)
    serialized["event_id"] = event.event_id
    if len(_canonical_bytes(serialized)) > MAX_EVENT_SERIALIZED_BYTES:
        raise QuarantineReviewError("review event exceeds the canonical size limit")
    return serialized


def _next_resulting_state(
    prior_state: QuarantineReviewState,
    disposition: ReviewDisposition,
    *,
    machine_verified: bool,
    new_invocation_id: str | None,
    original_invocation_id: str,
    stop_all_recovery_verification: tuple[str, ...] = (),
) -> QuarantineReviewState:
    if disposition == "pause-all-scheduler-execution":
        return "stop-all-scheduler-execution"

    if prior_state == "stop-all-scheduler-execution":
        # stop-all dominates every narrower disposition. Only an explicit,
        # machine-verified, resolving disposition backed by non-empty
        # structured verification evidence may move past it -- machine
        # verification alone is never sufficient.
        if disposition not in _RESOLVING_DISPOSITIONS:
            return "stop-all-scheduler-execution"
        if not machine_verified or not stop_all_recovery_verification:
            return "stop-all-scheduler-execution"
        if disposition == "recommend-fresh-invocation":
            if new_invocation_id is None:
                raise QuarantineReviewError("recommend-fresh-invocation requires a new invocation ID")
            if new_invocation_id == original_invocation_id:
                raise QuarantineReviewError(
                    "a fresh invocation recommendation cannot reuse the original invocation identity"
                )
        return "recovery-completed"

    if disposition == "recommend-fresh-invocation":
        if new_invocation_id is None:
            raise QuarantineReviewError("recommend-fresh-invocation requires a new invocation ID")
        if new_invocation_id == original_invocation_id:
            raise QuarantineReviewError(
                "a fresh invocation recommendation cannot reuse the original invocation identity"
            )
        if not machine_verified:
            return prior_state
        return "recovery-completed"

    if disposition == "confirm-no-effects-with-evidence":
        if prior_state in _NON_DOWNGRADABLE_STATES:
            raise QuarantineReviewError(
                f"cannot downgrade {prior_state} to contained-no-effects-proven without "
                "independent machine-verified evidence resolving it first"
            )
        if not machine_verified:
            raise QuarantineReviewError(
                "confirm-no-effects-with-evidence requires independent machine verification"
            )
        return "contained-no-effects-proven"

    if disposition in _RESOLVING_DISPOSITIONS:
        if prior_state in _NON_DOWNGRADABLE_STATES:
            raise QuarantineReviewError(
                f"cannot resolve {prior_state} without independent machine-verified evidence"
            )
        if not machine_verified:
            return prior_state
        return "recovery-completed"

    # preserve-and-investigate, require-*-inspection, request-authorized-*,
    # permanently-block-candidate: evidence only, no containment change.
    return prior_state


def append_review_event(
    *,
    packet: QuarantineEvidencePacket,
    prior_events: tuple[ReviewEvent, ...],
    reviewer_identity: str,
    review_timestamp: str,
    disposition: ReviewDisposition,
    rationale: str,
    machine_verified: bool,
    new_invocation_id: str | None = None,
    stop_all_recovery_verification: tuple[str, ...] = (),
    max_open_reviews: int = MAX_OPEN_REVIEWS,
) -> ReviewEvent:
    """Append exactly one new, deterministic review event.

    Fails closed on identity mismatch (a prior event bound to a different
    packet), duplicate/out-of-order sequencing, disposition downgrade
    attempts, and review-capacity breach (which itself escalates to
    ``stop-all-scheduler-execution`` rather than being silently dropped).
    """
    if not isinstance(packet, QuarantineEvidencePacket):
        raise QuarantineReviewError("packet must be QuarantineEvidencePacket")
    serialize_quarantine_evidence_packet(packet)  # tamper check

    for prior in prior_events:
        if prior.packet_id != packet.packet_id:
            raise QuarantineReviewError("prior review event is bound to a different packet identity")
        serialize_review_event(prior)  # tamper check on the whole chain

    if len(prior_events) >= max_open_reviews:
        prior_state: QuarantineReviewState = "stop-all-scheduler-execution"
        disposition = "pause-all-scheduler-execution"
    elif prior_events:
        ordered = sorted(prior_events, key=lambda event: event.sequence)
        expected_sequence = tuple(range(1, len(ordered) + 1))
        if tuple(event.sequence for event in ordered) != expected_sequence:
            raise QuarantineReviewError("review events are missing, duplicated, or out of order")
        prior_state = ordered[-1].resulting_state
        prior_event_id = ordered[-1].event_id
    else:
        prior_state = packet.initial_review_state
        prior_event_id = packet.packet_id

    if not prior_events:
        prior_event_id = packet.packet_id
    else:
        prior_event_id = sorted(prior_events, key=lambda event: event.sequence)[-1].event_id

    resulting_state = _next_resulting_state(
        prior_state,
        disposition,
        machine_verified=machine_verified,
        new_invocation_id=new_invocation_id,
        original_invocation_id=packet.invocation_id,
        stop_all_recovery_verification=stop_all_recovery_verification,
    )

    sequence = len(prior_events) + 1
    payload = {
        "schema_name": QUARANTINE_REVIEW_SCHEMA_NAME,
        "schema_version": QUARANTINE_REVIEW_SCHEMA_VERSION,
        "packet_id": packet.packet_id,
        "prior_event_id": prior_event_id,
        "sequence": sequence,
        "reviewer_identity": reviewer_identity,
        "review_timestamp": review_timestamp,
        "disposition": disposition,
        "rationale": rationale,
        "machine_verified": machine_verified,
        "resulting_state": resulting_state,
        "new_invocation_id": new_invocation_id,
        "stop_all_recovery_verification": tuple(stop_all_recovery_verification),
    }
    event_id = "quarantine-review-event:" + _semantic_digest(
        "agent-os-wsc5r-quarantine-review-event", payload
    )
    return ReviewEvent(event_id=event_id, **payload)


# --------------------------------------------------------------------------
# Bounded capacity/pause observation
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewCapacityObservation:
    """A bounded, deterministic snapshot of review backlog and age."""

    open_review_count: int
    unresolved_stop_all_count: int
    oldest_open_sequence_age: int
    breach: bool

    def __post_init__(self) -> None:
        for name in ("open_review_count", "unresolved_stop_all_count", "oldest_open_sequence_age"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise QuarantineReviewError(f"{name} must be a non-negative integer")


def evaluate_review_capacity(
    *,
    open_review_count: int,
    unresolved_stop_all_count: int,
    oldest_open_sequence_age: int,
    max_open_reviews: int = MAX_OPEN_REVIEWS,
    max_review_age: int = MAX_REVIEW_AGE_EVENTS,
) -> ReviewCapacityObservation:
    """Deterministically evaluate bounded review-capacity thresholds.

    A breach never silently drops or auto-resolves evidence; callers must
    route a breach into ``pause-all-scheduler-execution`` via
    ``append_review_event``.
    """
    breach = (
        open_review_count > max_open_reviews
        or unresolved_stop_all_count > 0
        or oldest_open_sequence_age > max_review_age
    )
    return ReviewCapacityObservation(
        open_review_count=open_review_count,
        unresolved_stop_all_count=unresolved_stop_all_count,
        oldest_open_sequence_age=oldest_open_sequence_age,
        breach=breach,
    )


# --------------------------------------------------------------------------
# Manual recovery handoff packet
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ManualRecoveryHandoffPacket:
    """Bounded recommendation-only handoff for a possible fresh invocation.

    Recording this packet never authorizes or performs a rerun; the frozen
    original result's ``result_id``/``invocation_id`` are preserved and a
    distinct ``new_invocation_id`` is required, matching the WSC5R rule that
    any fresh invocation needs a new identity and separate authorization.
    """

    schema_name: str
    schema_version: str
    handoff_id: str
    packet_id: str
    last_event_id: str
    original_result_id: str
    original_invocation_id: str
    new_invocation_id: str
    recommended_by: str
    rationale: str

    def __post_init__(self) -> None:
        if self.schema_name != QUARANTINE_REVIEW_SCHEMA_NAME:
            raise QuarantineReviewError("unsupported quarantine review schema name")
        if self.schema_version != QUARANTINE_REVIEW_SCHEMA_VERSION:
            raise QuarantineReviewError("unsupported quarantine review schema version")
        if self.new_invocation_id == self.original_invocation_id:
            raise QuarantineReviewError(
                "manual recovery handoff cannot reuse the original invocation identity"
            )
        _bounded_text(self.recommended_by, "recommended_by")
        object.__setattr__(self, "rationale", reject_if_secret_like(self.rationale, name="rationale"))


def build_manual_recovery_handoff_packet(
    *,
    packet: QuarantineEvidencePacket,
    resolving_event: ReviewEvent,
    new_invocation_id: str,
    recommended_by: str,
    rationale: str,
) -> ManualRecoveryHandoffPacket:
    """Build the one bounded handoff packet for a machine-verified recovery event."""
    if resolving_event.packet_id != packet.packet_id:
        raise QuarantineReviewError("resolving event is bound to a different packet identity")
    if resolving_event.disposition != "recommend-fresh-invocation":
        raise QuarantineReviewError("handoff requires a recommend-fresh-invocation event")
    if resolving_event.resulting_state != "recovery-completed":
        raise QuarantineReviewError("handoff requires a machine-verified recovery-completed event")
    if resolving_event.new_invocation_id != new_invocation_id:
        raise QuarantineReviewError("handoff invocation ID must match the resolving event")

    payload = {
        "schema_name": QUARANTINE_REVIEW_SCHEMA_NAME,
        "schema_version": QUARANTINE_REVIEW_SCHEMA_VERSION,
        "packet_id": packet.packet_id,
        "last_event_id": resolving_event.event_id,
        "original_result_id": packet.result_id,
        "original_invocation_id": packet.invocation_id,
        "new_invocation_id": new_invocation_id,
        "recommended_by": recommended_by,
        "rationale": rationale,
    }
    handoff_id = "quarantine-recovery-handoff:" + _semantic_digest(
        "agent-os-wsc5r-quarantine-recovery-handoff", payload
    )
    return ManualRecoveryHandoffPacket(handoff_id=handoff_id, **payload)
