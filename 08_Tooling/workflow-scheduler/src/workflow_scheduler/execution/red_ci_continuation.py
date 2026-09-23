"""Durable red-CI continuation planning for the Safe Implementation Lane.

This module extends the existing Workflow Scheduler continuation seam from #1188
with the #1251 red-CI checkpoint contract. It is pure, deterministic, and
caller-supplied-evidence-only: it performs no GitHub access, CI retrieval,
checkpoint persistence, lease mutation, repair, validation, retry, or external
I/O.

The existing branch/PR/checkpoint/Scheduler lineage remains authoritative. This
module only classifies the next bounded lifecycle action after authoritative CI
is red on a current head. It does not grant implementation, merge, issue-closure,
retry, protected-setting, workflow, credential, cloud, production, or external-
write authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

RED_CI_SCHEMA_VERSION = "1.0"
_MAX_TEXT = 512
_MAX_DIAGNOSTIC_ATTEMPTS = 2
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)


class RedCiFailureClass(str, Enum):
    REPOSITORY_REPAIRABLE = "repository-repairable"
    STALE_HEAD = "stale-head"
    DIAGNOSTIC_SURFACE_UNAVAILABLE = "diagnostic-surface-unavailable"
    INFRASTRUCTURE_OR_TOOLING = "infrastructure-or-tooling"
    EXCLUDED_OR_SCOPE_EXPANSION = "excluded-or-scope-expansion"
    AMBIGUOUS = "ambiguous"


class RedCiNextAction(str, Enum):
    DIAGNOSE_EXISTING_FAILURE = "diagnose-existing-failure"
    REPAIR_EXISTING_LINEAGE = "repair-existing-lineage"
    RUN_FOCUSED_VALIDATION = "run-focused-validation"
    REACQUIRE_HEAD = "reacquire-head"
    RUN_EXACT_HEAD_AGGREGATE = "run-exact-head-aggregate"
    READY_FOR_REVIEW = "ready-for-review"
    BLOCKED_DIAGNOSTIC_SURFACE = "blocked-diagnostic-surface"
    NEEDS_DECISION = "needs-decision"


class ValidationState(str, Enum):
    NOT_RUN = "not-run"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, kw_only=True)
class RedCiCheckpoint:
    """Exact resumable identity for one authoritative red-CI observation."""

    repository: str
    issue_number: int
    pull_request_number: int
    branch: str
    head_sha: str
    failing_check_identity: str
    failing_run_identity: str
    failing_conclusion: str
    last_completed_lifecycle_action: str
    checkpoint_lineage_identity: str
    scheduler_execution_identity: str | None = None
    scheduler_lease_identity: str | None = None
    scheduler_lease_generation: int | None = None

    def __post_init__(self) -> None:
        _bounded_text(self.repository, "repository")
        _positive_int(self.issue_number, "issue_number")
        _positive_int(self.pull_request_number, "pull_request_number")
        _bounded_text(self.branch, "branch")
        _sha40(self.head_sha, "head_sha")
        for name in (
            "failing_check_identity",
            "failing_run_identity",
            "failing_conclusion",
            "last_completed_lifecycle_action",
            "checkpoint_lineage_identity",
        ):
            _bounded_text(getattr(self, name), name)
        for name in ("scheduler_execution_identity", "scheduler_lease_identity"):
            value = getattr(self, name)
            if value is not None:
                _bounded_text(value, name)
        if self.scheduler_lease_generation is not None and (
            type(self.scheduler_lease_generation) is not int
            or isinstance(self.scheduler_lease_generation, bool)
            or self.scheduler_lease_generation < 0
        ):
            raise TypeError("scheduler_lease_generation must be a non-negative exact integer or None")


@dataclass(frozen=True, slots=True, kw_only=True)
class RedCiEvidence:
    """Current caller-supplied facts used to classify one red-CI checkpoint."""

    checkpoint: RedCiCheckpoint
    current_head_sha: str
    authorization_current: bool
    scope_current: bool
    excluded_surface_required: bool
    evidence_ambiguous: bool
    infrastructure_or_tooling_failure: bool
    repository_failure_attributable: bool
    diagnostic_actionable_evidence: bool
    alternate_diagnostic_surface_available: bool
    diagnostic_surface_attempts: tuple[str, ...] = ()
    repair_applied: bool = False
    focused_validation: ValidationState = ValidationState.NOT_RUN
    aggregate_validation: ValidationState = ValidationState.NOT_RUN
    aggregate_head_sha: str | None = None
    blocking_review_conversation: bool = False

    def __post_init__(self) -> None:
        if type(self.checkpoint) is not RedCiCheckpoint:
            raise TypeError("checkpoint must be exact RedCiCheckpoint")
        _sha40(self.current_head_sha, "current_head_sha")
        for name in (
            "authorization_current",
            "scope_current",
            "excluded_surface_required",
            "evidence_ambiguous",
            "infrastructure_or_tooling_failure",
            "repository_failure_attributable",
            "diagnostic_actionable_evidence",
            "alternate_diagnostic_surface_available",
            "repair_applied",
            "blocking_review_conversation",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        if type(self.diagnostic_surface_attempts) is not tuple:
            raise TypeError("diagnostic_surface_attempts must be an exact tuple")
        if len(self.diagnostic_surface_attempts) > _MAX_DIAGNOSTIC_ATTEMPTS:
            raise ValueError("diagnostic surface discovery exceeds the bounded attempt count")
        if len(set(self.diagnostic_surface_attempts)) != len(self.diagnostic_surface_attempts):
            raise ValueError("diagnostic surface attempts must not repeat the same surface")
        for attempt in self.diagnostic_surface_attempts:
            _bounded_text(attempt, "diagnostic_surface_attempt")
        if type(self.focused_validation) is not ValidationState:
            raise TypeError("focused_validation must be exact ValidationState")
        if type(self.aggregate_validation) is not ValidationState:
            raise TypeError("aggregate_validation must be exact ValidationState")
        if self.aggregate_head_sha is not None:
            _sha40(self.aggregate_head_sha, "aggregate_head_sha")


@dataclass(frozen=True, slots=True, kw_only=True)
class RedCiContinuationDecision:
    schema_version: Literal["1.0"]
    failure_class: RedCiFailureClass
    next_action: RedCiNextAction
    repository: str
    issue_number: int
    pull_request_number: int
    branch: str
    checkpoint_head_sha: str
    current_head_sha: str
    failing_check_identity: str
    failing_run_identity: str
    checkpoint_lineage_identity: str
    scheduler_execution_identity: str | None
    scheduler_lease_identity: str | None
    scheduler_lease_generation: int | None
    last_completed_lifecycle_action: str
    reason_codes: tuple[str, ...]
    recommended_action: str
    decision_id: str = field(init=False)
    continuation_authorized: Literal[False] = field(default=False, init=False)
    retry_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != RED_CI_SCHEMA_VERSION:
            raise ValueError("unsupported red-CI schema version")
        if type(self.failure_class) is not RedCiFailureClass:
            raise TypeError("failure_class must be exact RedCiFailureClass")
        if type(self.next_action) is not RedCiNextAction:
            raise TypeError("next_action must be exact RedCiNextAction")
        _bounded_text(self.repository, "repository")
        _positive_int(self.issue_number, "issue_number")
        _positive_int(self.pull_request_number, "pull_request_number")
        _bounded_text(self.branch, "branch")
        _sha40(self.checkpoint_head_sha, "checkpoint_head_sha")
        _sha40(self.current_head_sha, "current_head_sha")
        for name in (
            "failing_check_identity",
            "failing_run_identity",
            "checkpoint_lineage_identity",
            "last_completed_lifecycle_action",
            "recommended_action",
        ):
            _bounded_text(getattr(self, name), name)
        if type(self.reason_codes) is not tuple or tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("reason_codes must be a sorted unique tuple")
        payload = {
            "schema_version": self.schema_version,
            "failure_class": self.failure_class.value,
            "next_action": self.next_action.value,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "pull_request_number": self.pull_request_number,
            "branch": self.branch,
            "checkpoint_head_sha": self.checkpoint_head_sha,
            "current_head_sha": self.current_head_sha,
            "failing_check_identity": self.failing_check_identity,
            "failing_run_identity": self.failing_run_identity,
            "checkpoint_lineage_identity": self.checkpoint_lineage_identity,
            "scheduler_execution_identity": self.scheduler_execution_identity,
            "scheduler_lease_identity": self.scheduler_lease_identity,
            "scheduler_lease_generation": self.scheduler_lease_generation,
            "last_completed_lifecycle_action": self.last_completed_lifecycle_action,
            "reason_codes": list(self.reason_codes),
            "recommended_action": self.recommended_action,
            "continuation_authorized": False,
            "retry_authorized": False,
            "merge_authorized": False,
            "issue_closure_authorized": False,
            "external_writes_authorized": False,
        }
        object.__setattr__(
            self,
            "decision_id",
            "red-ci-continuation:"
            + hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        )


def plan_red_ci_continuation(evidence: RedCiEvidence) -> RedCiContinuationDecision:
    """Return the single bounded next action for a current red-CI checkpoint."""

    if type(evidence) is not RedCiEvidence:
        raise TypeError("evidence must be exact RedCiEvidence")

    checkpoint = evidence.checkpoint
    if checkpoint.head_sha != evidence.current_head_sha:
        return _decision(
            evidence,
            RedCiFailureClass.STALE_HEAD,
            RedCiNextAction.REACQUIRE_HEAD,
            ("head.current-differs-from-checkpoint", "head.bound-evidence-invalid"),
            "reacquire the live PR head and current check/run evidence before diagnosis or repair",
        )

    if evidence.excluded_surface_required or not evidence.authorization_current or not evidence.scope_current:
        return _decision(
            evidence,
            RedCiFailureClass.EXCLUDED_OR_SCOPE_EXPANSION,
            RedCiNextAction.NEEDS_DECISION,
            _scope_reasons(evidence),
            "preserve the existing lineage and request only the separately governed authority or scope decision",
        )

    if evidence.evidence_ambiguous:
        return _decision(
            evidence,
            RedCiFailureClass.AMBIGUOUS,
            RedCiNextAction.NEEDS_DECISION,
            ("failure.evidence-ambiguous",),
            "preserve the checkpoint and route conflicting or insufficient evidence for manual review",
        )

    if evidence.infrastructure_or_tooling_failure:
        return _decision(
            evidence,
            RedCiFailureClass.INFRASTRUCTURE_OR_TOOLING,
            RedCiNextAction.NEEDS_DECISION,
            ("failure.infrastructure-or-tooling",),
            "do not fabricate a repository-code workaround; route the infrastructure/tooling failure to its existing owner",
        )

    if not evidence.diagnostic_actionable_evidence:
        if evidence.alternate_diagnostic_surface_available and len(evidence.diagnostic_surface_attempts) < _MAX_DIAGNOSTIC_ATTEMPTS:
            return _decision(
                evidence,
                RedCiFailureClass.DIAGNOSTIC_SURFACE_UNAVAILABLE,
                RedCiNextAction.DIAGNOSE_EXISTING_FAILURE,
                ("diagnostic.alternate-authorized-surface-available",),
                "switch boundedly to the already-authorized alternate diagnostic surface and extract the first actionable failure",
            )
        return _decision(
            evidence,
            RedCiFailureClass.DIAGNOSTIC_SURFACE_UNAVAILABLE,
            RedCiNextAction.BLOCKED_DIAGNOSTIC_SURFACE,
            ("diagnostic.no-actionable-surface",),
            "preserve the checkpoint and report one explicit diagnostic-surface blocker and clearing condition",
        )

    if not evidence.repository_failure_attributable:
        return _decision(
            evidence,
            RedCiFailureClass.AMBIGUOUS,
            RedCiNextAction.NEEDS_DECISION,
            ("failure.repository-attribution-unproven",),
            "do not guess a repository repair without attributable current-head failure evidence",
        )

    if not evidence.repair_applied:
        return _decision(
            evidence,
            RedCiFailureClass.REPOSITORY_REPAIRABLE,
            RedCiNextAction.REPAIR_EXISTING_LINEAGE,
            ("failure.repository-repairable", "lineage.preserve-existing"),
            "repair only the smallest in-scope cause on the existing branch and PR lineage",
        )

    if evidence.focused_validation is ValidationState.NOT_RUN:
        return _decision(
            evidence,
            RedCiFailureClass.REPOSITORY_REPAIRABLE,
            RedCiNextAction.RUN_FOCUSED_VALIDATION,
            ("repair.applied", "validation.focused-required"),
            "run the smallest deterministic focused validation that exercises the repaired failure",
        )

    if evidence.focused_validation is ValidationState.FAILED:
        return _decision(
            evidence,
            RedCiFailureClass.REPOSITORY_REPAIRABLE,
            RedCiNextAction.DIAGNOSE_EXISTING_FAILURE,
            ("validation.focused-failed",),
            "keep the same lineage and diagnose the focused failure before any broader validation",
        )

    if evidence.aggregate_validation is ValidationState.NOT_RUN:
        return _decision(
            evidence,
            RedCiFailureClass.REPOSITORY_REPAIRABLE,
            RedCiNextAction.RUN_EXACT_HEAD_AGGREGATE,
            ("validation.focused-passed", "validation.aggregate-required"),
            "reacquire the live exact head and run or observe one authoritative aggregate bound to that head",
        )

    if evidence.aggregate_head_sha != evidence.current_head_sha:
        return _decision(
            evidence,
            RedCiFailureClass.STALE_HEAD,
            RedCiNextAction.REACQUIRE_HEAD,
            ("validation.aggregate-head-stale",),
            "discard stale aggregate evidence and reacquire validation for the current exact head",
        )

    if evidence.aggregate_validation is ValidationState.FAILED:
        return _decision(
            evidence,
            RedCiFailureClass.REPOSITORY_REPAIRABLE,
            RedCiNextAction.DIAGNOSE_EXISTING_FAILURE,
            ("validation.aggregate-current-head-failed",),
            "treat the new red exact-head aggregate as the next durable checkpoint on the same lineage",
        )

    if evidence.blocking_review_conversation:
        return _decision(
            evidence,
            RedCiFailureClass.REPOSITORY_REPAIRABLE,
            RedCiNextAction.NEEDS_DECISION,
            ("review.blocking-conversation",),
            "preserve green exact-head evidence but do not mark Ready-for-Review until the blocking review conversation is resolved",
        )

    return _decision(
        evidence,
        RedCiFailureClass.REPOSITORY_REPAIRABLE,
        RedCiNextAction.READY_FOR_REVIEW,
        ("validation.aggregate-current-head-passed", "validation.focused-passed"),
        "mark the existing PR Ready-for-Review through the normal governed lifecycle; no merge authority is implied",
    )


def _decision(
    evidence: RedCiEvidence,
    failure_class: RedCiFailureClass,
    next_action: RedCiNextAction,
    reasons: tuple[str, ...],
    recommended_action: str,
) -> RedCiContinuationDecision:
    checkpoint = evidence.checkpoint
    return RedCiContinuationDecision(
        schema_version=RED_CI_SCHEMA_VERSION,
        failure_class=failure_class,
        next_action=next_action,
        repository=checkpoint.repository,
        issue_number=checkpoint.issue_number,
        pull_request_number=checkpoint.pull_request_number,
        branch=checkpoint.branch,
        checkpoint_head_sha=checkpoint.head_sha,
        current_head_sha=evidence.current_head_sha,
        failing_check_identity=checkpoint.failing_check_identity,
        failing_run_identity=checkpoint.failing_run_identity,
        checkpoint_lineage_identity=checkpoint.checkpoint_lineage_identity,
        scheduler_execution_identity=checkpoint.scheduler_execution_identity,
        scheduler_lease_identity=checkpoint.scheduler_lease_identity,
        scheduler_lease_generation=checkpoint.scheduler_lease_generation,
        last_completed_lifecycle_action=checkpoint.last_completed_lifecycle_action,
        reason_codes=tuple(sorted(set(reasons))),
        recommended_action=recommended_action,
    )


def _scope_reasons(evidence: RedCiEvidence) -> tuple[str, ...]:
    reasons: list[str] = []
    if not evidence.authorization_current:
        reasons.append("authorization.not-current")
    if not evidence.scope_current:
        reasons.append("scope.not-current")
    if evidence.excluded_surface_required:
        reasons.append("scope.excluded-surface-required")
    return tuple(reasons)


def _bounded_text(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise TypeError(f"{name} must be a non-empty exact string")
    if len(value) > _MAX_TEXT:
        raise ValueError(f"{name} exceeds the bounded length")
    return value


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1:
        raise TypeError(f"{name} must be a positive exact integer")
    return value


def _sha40(value: object, name: str) -> str:
    if type(value) is not str or _SHA40_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase 40-character SHA")
    return value
