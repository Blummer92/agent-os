"""Pure-local BR5 post-merge lifecycle reconciliation projection.

This module does not mutate GitHub and does not create lifecycle authority. It
consumes current evidence from the existing lifecycle/operational owners and
projects the bounded next actions for a finite Bulk Repair batch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class TerminalLifecycleDisposition(str, Enum):
    CLOSED_COMPLETED = "closed-completed"
    MERGED_AWAITING_CLOSURE_AUTHORIZATION = "merged-awaiting-closure-authorization"
    MERGED_ISSUE_NOT_COMPLETE = "merged-issue-not-complete"
    CLOSED_READY_CLEANUP_REQUIRED = "closed-ready-cleanup-required"
    MANUAL_REVIEW = "manual-review"


class AdmissionState(str, Enum):
    ADMITTED = "admitted"
    BLOCKED = "blocked"
    STALE = "stale"
    INVALID = "invalid"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class LifecycleAdmissionEvidence:
    """Normalized result from the canonical lifecycle mutation guard."""

    mutation: Literal["close-issue", "remove-lifecycle-label"]
    state: AdmissionState
    result_id: str | None
    snapshot_id: str | None

    def __post_init__(self) -> None:
        if self.mutation not in {"close-issue", "remove-lifecycle-label"}:
            raise ValueError("unsupported lifecycle mutation")
        if type(self.state) is not AdmissionState:
            raise TypeError("state must be AdmissionState")
        if self.state is AdmissionState.MISSING:
            if self.result_id is not None or self.snapshot_id is not None:
                raise ValueError("missing admission cannot carry result/snapshot identity")
        else:
            if type(self.result_id) is not str or not self.result_id.strip():
                raise ValueError("non-missing admission requires result_id")
            if type(self.snapshot_id) is not str or not self.snapshot_id.strip():
                raise ValueError("non-missing admission requires snapshot_id")

    @property
    def admitted(self) -> bool:
        return self.state is AdmissionState.ADMITTED


@dataclass(frozen=True, slots=True)
class PostMergeCandidateEvidence:
    repository: str
    pull_request_number: int
    issue_number: int
    pr_merged: bool
    merge_commit_sha: str | None
    current_main_sha: str
    issue_state: Literal["open", "closed"]
    issue_complete: bool
    issue_kind: Literal["implementation", "parent", "tracking", "investigation"]
    remaining_scope: bool
    status_ready_present: bool
    lifecycle_snapshot_id: str
    operational_state_id: str
    closure_authorization_state: Literal[
        "authorized", "not-authorized", "stale", "needs-decision", "not-applicable"
    ]
    close_admission: LifecycleAdmissionEvidence
    ready_cleanup_admission: LifecycleAdmissionEvidence
    final_disposition_already_published: bool = False
    final_readback_pr_merged: bool | None = None
    final_readback_issue_state: Literal["open", "closed"] | None = None
    final_readback_status_ready_present: bool | None = None
    evidence_conflicting: bool = False

    def __post_init__(self) -> None:
        if type(self.repository) is not str or "/" not in self.repository:
            raise ValueError("repository must be owner/name")
        for name in ("pull_request_number", "issue_number"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.pr_merged) is not bool or type(self.issue_complete) is not bool:
            raise TypeError("boolean evidence must use built-in bool")
        if type(self.remaining_scope) is not bool or type(self.status_ready_present) is not bool:
            raise TypeError("boolean evidence must use built-in bool")
        if type(self.final_disposition_already_published) is not bool:
            raise TypeError("final_disposition_already_published must use built-in bool")
        if type(self.evidence_conflicting) is not bool:
            raise TypeError("evidence_conflicting must use built-in bool")
        if self.pr_merged:
            _sha40(self.merge_commit_sha, "merge_commit_sha")
        elif self.merge_commit_sha is not None:
            raise ValueError("unmerged PR cannot carry merge_commit_sha")
        _sha40(self.current_main_sha, "current_main_sha")
        for value, name in (
            (self.lifecycle_snapshot_id, "lifecycle_snapshot_id"),
            (self.operational_state_id, "operational_state_id"),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if self.close_admission.mutation != "close-issue":
            raise ValueError("close_admission must describe close-issue")
        if self.ready_cleanup_admission.mutation != "remove-lifecycle-label":
            raise ValueError("ready_cleanup_admission must describe remove-lifecycle-label")
        for admission in (self.close_admission, self.ready_cleanup_admission):
            if admission.snapshot_id is not None and admission.snapshot_id != self.lifecycle_snapshot_id:
                raise ValueError("lifecycle admission must bind the current lifecycle snapshot")
        if self.final_readback_pr_merged is not None and type(self.final_readback_pr_merged) is not bool:
            raise TypeError("final_readback_pr_merged must use built-in bool when supplied")
        if self.final_readback_status_ready_present is not None and type(self.final_readback_status_ready_present) is not bool:
            raise TypeError("final_readback_status_ready_present must use built-in bool when supplied")


@dataclass(frozen=True, slots=True)
class PostMergeCandidateProjection:
    pull_request_number: int
    issue_number: int
    disposition: TerminalLifecycleDisposition
    reason_codes: tuple[str, ...]
    publish_final_disposition: bool
    remove_status_ready: bool
    close_issue: bool
    requires_final_readback: bool
    converged: bool
    lifecycle_snapshot_id: str
    operational_state_id: str
    side_effects_performed: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class BulkPostMergeReconciliationProjection:
    candidates: tuple[PostMergeCandidateProjection, ...]
    closed_completed_issue_numbers: tuple[int, ...]
    awaiting_closure_issue_numbers: tuple[int, ...]
    incomplete_issue_numbers: tuple[int, ...]
    ready_cleanup_issue_numbers: tuple[int, ...]
    manual_review_issue_numbers: tuple[int, ...]
    next_action: str
    mutation_authorized: Literal[False] = field(default=False, init=False)
    closure_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def evaluate_post_merge_candidate(evidence: PostMergeCandidateEvidence) -> PostMergeCandidateProjection:
    if type(evidence) is not PostMergeCandidateEvidence:
        raise TypeError("evidence must be PostMergeCandidateEvidence")

    if evidence.evidence_conflicting or not evidence.pr_merged:
        return _projection(
            evidence,
            TerminalLifecycleDisposition.MANUAL_REVIEW,
            ("merged-state-unproven-or-conflicting",),
        )

    issue_is_complete = (
        evidence.issue_complete
        and not evidence.remaining_scope
        and evidence.issue_kind == "implementation"
    )

    if not issue_is_complete:
        return _projection(
            evidence,
            TerminalLifecycleDisposition.MERGED_ISSUE_NOT_COMPLETE,
            ("issue-definition-of-done-not-satisfied",),
        )

    if evidence.issue_state == "closed":
        if evidence.status_ready_present:
            cleanup_admitted = evidence.ready_cleanup_admission.admitted
            return _projection(
                evidence,
                TerminalLifecycleDisposition.CLOSED_READY_CLEANUP_REQUIRED,
                (
                    "closed-issue-retains-status-ready",
                    "ready-cleanup-admitted" if cleanup_admitted else "ready-cleanup-not-admitted",
                ),
                publish=not evidence.final_disposition_already_published,
                remove_ready=cleanup_admitted,
                readback=cleanup_admitted,
            )
        return _projection(
            evidence,
            TerminalLifecycleDisposition.CLOSED_COMPLETED,
            ("already-converged",),
            converged=_readback_converged(evidence) or _readback_absent(evidence),
        )

    if evidence.closure_authorization_state != "authorized" or not evidence.close_admission.admitted:
        return _projection(
            evidence,
            TerminalLifecycleDisposition.MERGED_AWAITING_CLOSURE_AUTHORIZATION,
            ("close-issue-not-currently-admitted",),
        )

    if evidence.status_ready_present and not evidence.ready_cleanup_admission.admitted:
        return _projection(
            evidence,
            TerminalLifecycleDisposition.MANUAL_REVIEW,
            ("ready-label-cleanup-not-currently-admitted",),
        )

    needs_readback = True
    remove_ready = evidence.status_ready_present and evidence.ready_cleanup_admission.admitted
    close_issue = evidence.close_admission.admitted
    converged = _readback_converged(evidence)
    return _projection(
        evidence,
        TerminalLifecycleDisposition.CLOSED_COMPLETED,
        ("terminal-mutations-admitted", "final-readback-converged" if converged else "final-readback-required"),
        publish=not evidence.final_disposition_already_published,
        remove_ready=remove_ready and not converged,
        close=close_issue and not converged,
        readback=needs_readback and not converged,
        converged=converged,
    )


def evaluate_bulk_post_merge_reconciliation(
    evidence: tuple[PostMergeCandidateEvidence, ...],
) -> BulkPostMergeReconciliationProjection:
    if type(evidence) is not tuple or not evidence:
        raise ValueError("evidence must be a non-empty tuple")
    if any(type(item) is not PostMergeCandidateEvidence for item in evidence):
        raise TypeError("evidence must contain PostMergeCandidateEvidence")
    issue_numbers = tuple(item.issue_number for item in evidence)
    if len(set(issue_numbers)) != len(issue_numbers):
        raise ValueError("each issue may appear at most once per projection")

    candidates = tuple(evaluate_post_merge_candidate(item) for item in evidence)
    by = lambda disposition: tuple(
        item.issue_number for item in candidates if item.disposition is disposition
    )
    manual = by(TerminalLifecycleDisposition.MANUAL_REVIEW)
    cleanup = by(TerminalLifecycleDisposition.CLOSED_READY_CLEANUP_REQUIRED)
    awaiting = by(TerminalLifecycleDisposition.MERGED_AWAITING_CLOSURE_AUTHORIZATION)
    incomplete = by(TerminalLifecycleDisposition.MERGED_ISSUE_NOT_COMPLETE)
    completed = by(TerminalLifecycleDisposition.CLOSED_COMPLETED)

    if any(item.requires_final_readback for item in candidates):
        next_action = "perform-admitted-lifecycle-mutations-then-reacquire"
    elif manual:
        next_action = "manual-review-item-local-candidates"
    elif cleanup:
        next_action = "await-ready-label-cleanup-admission"
    elif awaiting:
        next_action = "await-closure-authorization"
    elif all(item.converged for item in candidates):
        next_action = "report-converged-batch"
    else:
        next_action = "report-nonterminal-item-local-dispositions"

    return BulkPostMergeReconciliationProjection(
        candidates=candidates,
        closed_completed_issue_numbers=completed,
        awaiting_closure_issue_numbers=awaiting,
        incomplete_issue_numbers=incomplete,
        ready_cleanup_issue_numbers=cleanup,
        manual_review_issue_numbers=manual,
        next_action=next_action,
    )


def _projection(
    evidence: PostMergeCandidateEvidence,
    disposition: TerminalLifecycleDisposition,
    reasons: tuple[str, ...],
    *,
    publish: bool = False,
    remove_ready: bool = False,
    close: bool = False,
    readback: bool = False,
    converged: bool = False,
) -> PostMergeCandidateProjection:
    return PostMergeCandidateProjection(
        pull_request_number=evidence.pull_request_number,
        issue_number=evidence.issue_number,
        disposition=disposition,
        reason_codes=reasons,
        publish_final_disposition=publish,
        remove_status_ready=remove_ready,
        close_issue=close,
        requires_final_readback=readback,
        converged=converged,
        lifecycle_snapshot_id=evidence.lifecycle_snapshot_id,
        operational_state_id=evidence.operational_state_id,
    )


def _readback_absent(evidence: PostMergeCandidateEvidence) -> bool:
    return (
        evidence.final_readback_pr_merged is None
        and evidence.final_readback_issue_state is None
        and evidence.final_readback_status_ready_present is None
    )


def _readback_converged(evidence: PostMergeCandidateEvidence) -> bool:
    return (
        evidence.final_readback_pr_merged is True
        and evidence.final_readback_issue_state == "closed"
        and evidence.final_readback_status_ready_present is False
    )


def _sha40(value: str | None, name: str) -> None:
    if type(value) is not str or len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{name} must be a lowercase 40-character SHA")
