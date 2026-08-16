"""Exact-head validation supersession projection for execution continuation.

This module adds no lower-level validation status and rewrites no historical
result. It consumes the existing #761 ``ValidationLifecycleResult`` together
with bounded run/head/concurrency evidence. A cancelled stale-head run is
classified as superseded only when a newer run in the same validation lane and
concurrency group is bound to the current PR head and replacement is explicitly
proven. Genuine failures remain failures even after a newer head exists.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from scripts.agent_os_issue_acceptance.validation_failure_classifier import (
    ValidationFailureClassification,
    ValidationFailureClassificationResult,
)

from .models import parse_canonical_utc
from .validation_lifecycle_evidence import (
    ValidationLifecycleResult,
    ValidationLifecycleTerminalStatus,
)

VALIDATION_SUPERSESSION_SCHEMA_VERSION = "1.0"
_MAX_TEXT = 512
_MAX_REPLACEMENTS = 16
_MAX_REASONS = 16
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)


class ValidationRunPhase(str, Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in-progress"
    TERMINAL = "terminal"


class ValidationHeadDisposition(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    PENDING = "pending"
    STALE_HEAD = "stale-head"
    SUPERSEDED_BY_NEW_HEAD = "superseded-by-new-head"
    CANCELLED_BY_USER_OR_EXTERNAL_ACTION = "cancelled-by-user-or-external-action"
    TIMED_OUT = "timed-out"
    INFRASTRUCTURE_FAILURE = "infrastructure-failure"
    QUARANTINED = "quarantined"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs-decision"


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationRunEvidence:
    """Bounded identity wrapper around existing lifecycle evidence."""

    run_id: str
    validation_lane: str
    concurrency_group: str
    head_sha: str
    phase: ValidationRunPhase
    lifecycle_result: ValidationLifecycleResult | None = None

    def __post_init__(self) -> None:
        _bounded_text(self.run_id, "run_id")
        _bounded_text(self.validation_lane, "validation_lane")
        _bounded_text(self.concurrency_group, "concurrency_group")
        _sha40(self.head_sha, "head_sha")
        if type(self.phase) is not ValidationRunPhase:
            raise TypeError("phase must be an exact ValidationRunPhase")
        if self.phase is ValidationRunPhase.TERMINAL:
            if type(self.lifecycle_result) is not ValidationLifecycleResult:
                raise TypeError("terminal run evidence requires exact ValidationLifecycleResult")
        elif self.lifecycle_result is not None:
            raise ValueError("queued/in-progress run evidence must not carry terminal lifecycle_result")


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationSupersessionEvidence:
    current_head_sha: str
    observed_at: str
    evidence_current: bool
    prior_run: ValidationRunEvidence
    replacement_runs: tuple[ValidationRunEvidence, ...] = ()
    concurrency_replacement_proven: bool = False
    user_or_external_cancellation_proven: bool = False
    failure_classification: ValidationFailureClassificationResult | None = None

    def __post_init__(self) -> None:
        _sha40(self.current_head_sha, "current_head_sha")
        parse_canonical_utc(self.observed_at)
        if type(self.evidence_current) is not bool:
            raise TypeError("evidence_current must be an exact boolean")
        if type(self.prior_run) is not ValidationRunEvidence:
            raise TypeError("prior_run must be exact ValidationRunEvidence")
        if type(self.replacement_runs) is not tuple:
            raise TypeError("replacement_runs must be an exact tuple")
        if len(self.replacement_runs) > _MAX_REPLACEMENTS:
            raise ValueError("replacement_runs exceeds the bounded count")
        if any(type(item) is not ValidationRunEvidence for item in self.replacement_runs):
            raise TypeError("replacement_runs must contain exact ValidationRunEvidence values")
        run_ids = tuple(item.run_id for item in self.replacement_runs)
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("replacement run IDs must be unique")
        for name in ("concurrency_replacement_proven", "user_or_external_cancellation_proven"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        if self.failure_classification is not None:
            if type(self.failure_classification) is not ValidationFailureClassificationResult:
                raise TypeError(
                    "failure_classification must be exact ValidationFailureClassificationResult or None"
                )
            if self.failure_classification.pr_head_sha != self.prior_run.head_sha:
                raise ValueError("failure classification must bind the prior validation head")


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationHeadDecision:
    schema_version: Literal["1.0"]
    disposition: ValidationHeadDisposition
    prior_run_id: str
    observed_at: str
    prior_head_sha: str
    current_head_sha: str
    replacement_run_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    recommended_action: str
    satisfies_current_head: bool
    decision_id: str = field(init=False)
    retry_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != VALIDATION_SUPERSESSION_SCHEMA_VERSION:
            raise ValueError("unsupported validation supersession schema version")
        if type(self.disposition) is not ValidationHeadDisposition:
            raise TypeError("disposition must be exact ValidationHeadDisposition")
        _bounded_text(self.prior_run_id, "prior_run_id")
        parse_canonical_utc(self.observed_at)
        _sha40(self.prior_head_sha, "prior_head_sha")
        _sha40(self.current_head_sha, "current_head_sha")
        if type(self.replacement_run_ids) is not tuple:
            raise TypeError("replacement_run_ids must be an exact tuple")
        if tuple(sorted(set(self.replacement_run_ids))) != self.replacement_run_ids:
            raise ValueError("replacement_run_ids must be sorted and unique")
        if len(self.replacement_run_ids) > _MAX_REPLACEMENTS:
            raise ValueError("replacement_run_ids exceeds the bounded count")
        for item in self.replacement_run_ids:
            _bounded_text(item, "replacement_run_id")
        if type(self.reason_codes) is not tuple:
            raise TypeError("reason_codes must be an exact tuple")
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("reason_codes must be sorted and unique")
        if len(self.reason_codes) > _MAX_REASONS:
            raise ValueError("reason_codes exceeds the bounded count")
        for item in self.reason_codes:
            _bounded_text(item, "reason_code")
        _bounded_text(self.recommended_action, "recommended_action")
        if type(self.satisfies_current_head) is not bool:
            raise TypeError("satisfies_current_head must be an exact boolean")
        if self.satisfies_current_head and self.disposition is not ValidationHeadDisposition.PASSED:
            raise ValueError("only a current exact-head pass may satisfy current-head validation")
        payload = {
            "schema_version": self.schema_version,
            "disposition": self.disposition.value,
            "prior_run_id": self.prior_run_id,
            "observed_at": self.observed_at,
            "prior_head_sha": self.prior_head_sha,
            "current_head_sha": self.current_head_sha,
            "replacement_run_ids": list(self.replacement_run_ids),
            "reason_codes": list(self.reason_codes),
            "recommended_action": self.recommended_action,
            "satisfies_current_head": self.satisfies_current_head,
            "retry_authorized": False,
            "merge_authorized": False,
            "issue_closure_authorized": False,
            "side_effects_performed": False,
        }
        object.__setattr__(
            self,
            "decision_id",
            "validation-head-decision:" + hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        )


_ACTIONS = {
    ValidationHeadDisposition.PASSED: "current exact-head validation is satisfied",
    ValidationHeadDisposition.FAILED: (
        "preserve the failure evidence; classify/repair only through the existing governed validation-failure path"
    ),
    ValidationHeadDisposition.PENDING: "await the already-started current-head validation; do not start a duplicate run",
    ValidationHeadDisposition.STALE_HEAD: "invalidate this run as satisfaction evidence and validate the current exact head",
    ValidationHeadDisposition.SUPERSEDED_BY_NEW_HEAD: (
        "invalidate the cancelled stale-head run as satisfaction evidence and use only the replacement current-head run"
    ),
    ValidationHeadDisposition.CANCELLED_BY_USER_OR_EXTERNAL_ACTION: (
        "preserve the cancellation as terminal evidence and require a separately governed next action"
    ),
    ValidationHeadDisposition.TIMED_OUT: "preserve timeout evidence; no automatic retry",
    ValidationHeadDisposition.INFRASTRUCTURE_FAILURE: (
        "preserve repository state and follow the existing infrastructure/configuration authorization boundary"
    ),
    ValidationHeadDisposition.QUARANTINED: "preserve quarantine evidence and route to manual recovery",
    ValidationHeadDisposition.BLOCKED: "preserve the blocking evidence and do not execute validation",
    ValidationHeadDisposition.NEEDS_DECISION: "do not guess; reacquire the missing supersession/cancellation evidence",
}


def project_validation_head_disposition(
    evidence: ValidationSupersessionEvidence,
) -> ValidationHeadDecision:
    """Project exact-head applicability without rewriting lifecycle history."""
    if type(evidence) is not ValidationSupersessionEvidence:
        raise TypeError("evidence must be exact ValidationSupersessionEvidence")

    prior = evidence.prior_run
    if not evidence.evidence_current:
        return _decision(
            evidence,
            ValidationHeadDisposition.NEEDS_DECISION,
            replacement_ids=(),
            reasons=("supersession.evidence-stale",),
        )
    replacements = tuple(
        item
        for item in evidence.replacement_runs
        if item.head_sha == evidence.current_head_sha
        and item.validation_lane == prior.validation_lane
        and item.concurrency_group == prior.concurrency_group
    )
    replacement_ids = tuple(sorted(item.run_id for item in replacements))

    if prior.phase is not ValidationRunPhase.TERMINAL:
        disposition = (
            ValidationHeadDisposition.PENDING
            if prior.head_sha == evidence.current_head_sha
            else ValidationHeadDisposition.STALE_HEAD
        )
        return _decision(
            evidence,
            disposition,
            replacement_ids=replacement_ids,
            reasons=(
                "run.current-head-pending"
                if disposition is ValidationHeadDisposition.PENDING
                else "run.nonterminal-stale-head",
            ),
        )

    status = prior.lifecycle_result.status
    if status is ValidationLifecycleTerminalStatus.CANCELLED:
        if (
            prior.head_sha != evidence.current_head_sha
            and evidence.concurrency_replacement_proven
            and replacement_ids
        ):
            return _decision(
                evidence,
                ValidationHeadDisposition.SUPERSEDED_BY_NEW_HEAD,
                replacement_ids=replacement_ids,
                reasons=(
                    "cancelled.stale-head",
                    "replacement.current-head-present",
                    "replacement.concurrency-proven",
                ),
            )
        if evidence.user_or_external_cancellation_proven:
            return _decision(
                evidence,
                ValidationHeadDisposition.CANCELLED_BY_USER_OR_EXTERNAL_ACTION,
                replacement_ids=replacement_ids,
                reasons=("cancellation.user-or-external-proven",),
            )
        return _decision(
            evidence,
            ValidationHeadDisposition.NEEDS_DECISION,
            replacement_ids=replacement_ids,
            reasons=("cancellation.cause-unproven",),
        )

    if status is ValidationLifecycleTerminalStatus.SUCCEEDED:
        if prior.head_sha == evidence.current_head_sha:
            return _decision(
                evidence,
                ValidationHeadDisposition.PASSED,
                replacement_ids=replacement_ids,
                reasons=("validation.current-exact-head-pass",),
                satisfies_current_head=True,
            )
        return _decision(
            evidence,
            ValidationHeadDisposition.STALE_HEAD,
            replacement_ids=replacement_ids,
            reasons=("validation.prior-pass-stale-head",),
        )

    if _is_infrastructure_failure(evidence):
        return _decision(
            evidence,
            ValidationHeadDisposition.INFRASTRUCTURE_FAILURE,
            replacement_ids=replacement_ids,
            reasons=("validation.infrastructure-configuration-failure",),
        )
    if status is ValidationLifecycleTerminalStatus.VALIDATION_FAILED:
        return _decision(
            evidence,
            ValidationHeadDisposition.FAILED,
            replacement_ids=replacement_ids,
            reasons=(
                "validation.failure-preserved",
                *(() if prior.head_sha == evidence.current_head_sha else ("validation.failure-on-prior-head",)),
            ),
        )
    if status is ValidationLifecycleTerminalStatus.TIMED_OUT:
        return _decision(
            evidence,
            ValidationHeadDisposition.TIMED_OUT,
            replacement_ids=replacement_ids,
            reasons=("validation.timed-out",),
        )
    if status is ValidationLifecycleTerminalStatus.QUARANTINED:
        return _decision(
            evidence,
            ValidationHeadDisposition.QUARANTINED,
            replacement_ids=replacement_ids,
            reasons=("validation.quarantined",),
        )
    if status is ValidationLifecycleTerminalStatus.BLOCKED:
        return _decision(
            evidence,
            ValidationHeadDisposition.BLOCKED,
            replacement_ids=replacement_ids,
            reasons=("validation.blocked",),
        )
    if status is ValidationLifecycleTerminalStatus.STALE:
        return _decision(
            evidence,
            ValidationHeadDisposition.STALE_HEAD,
            replacement_ids=replacement_ids,
            reasons=("validation.lifecycle-stale",),
        )

    return _decision(
        evidence,
        ValidationHeadDisposition.NEEDS_DECISION,
        replacement_ids=replacement_ids,
        reasons=(f"validation.lifecycle:{status.value}",),
    )


def _is_infrastructure_failure(evidence: ValidationSupersessionEvidence) -> bool:
    classification = evidence.failure_classification
    return (
        classification is not None
        and classification.classification
        is ValidationFailureClassification.CI_INFRASTRUCTURE_CONFIGURATION_FAILURE
    )


def _decision(
    evidence: ValidationSupersessionEvidence,
    disposition: ValidationHeadDisposition,
    *,
    replacement_ids: tuple[str, ...],
    reasons: tuple[str, ...],
    satisfies_current_head: bool = False,
) -> ValidationHeadDecision:
    return ValidationHeadDecision(
        schema_version=VALIDATION_SUPERSESSION_SCHEMA_VERSION,
        disposition=disposition,
        prior_run_id=evidence.prior_run.run_id,
        observed_at=evidence.observed_at,
        prior_head_sha=evidence.prior_run.head_sha,
        current_head_sha=evidence.current_head_sha,
        replacement_run_ids=tuple(sorted(set(replacement_ids))),
        reason_codes=tuple(sorted(set(reasons))),
        recommended_action=_ACTIONS[disposition],
        satisfies_current_head=satisfies_current_head,
    )


def _bounded_text(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise TypeError(f"{name} must be a non-empty exact string")
    if len(value) > _MAX_TEXT:
        raise ValueError(f"{name} exceeds the bounded length")
    return value


def _sha40(value: object, name: str) -> str:
    if type(value) is not str or _SHA40_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase 40-character SHA")
    return value
