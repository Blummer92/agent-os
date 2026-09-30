"""Terminal reconciliation for the Safe Implementation Lane post-PR step (#2791).

Pure-local planning adapter consumed after the issue-linked Draft PR is
created and canonically read back. It reconciles the implementation issue to
its expected post-PR disposition (no longer open+ready): the stale Ready
projection is removed when the issue becomes non-actionable, an authorized
close is projected when the mission supplies closure authority, and missing
closure authority is surfaced visibly instead of silently leaving the issue
looking actionable.

Draft PR creation cannot be reported as fully reconciled while the linked
implementation issue has an unresolved expected terminal disposition: the
caller must run ``evaluate_lane_post_pr_issue_readback`` after the admitted
mutations and may advance the finite batch cursor only on a reconciled proof.

Expected mutations reuse the existing lifecycle-mutation vocabulary owned by
``lifecycle_mutation_guard`` (admission stays with that contract); no second
issue state machine, lifecycle, queue, or scheduler is introduced. The plan
never grants merge or Ready-for-Review authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

READY_LABEL = "status:ready"
PR_STATES = frozenset({"draft", "ready"})
_MUTATION_REMOVE_READY = "remove-lifecycle-label"
_MUTATION_CLOSE_ISSUE = "close-issue"


class LanePostPrIssueDisposition(str, Enum):
    RECONCILE_READY_AND_CLOSE = "reconcile-ready-and-close"
    RECONCILE_READY_AWAITING_CLOSURE_AUTHORITY = (
        "reconcile-ready-awaiting-closure-authority"
    )
    ALREADY_RECONCILED = "already-reconciled"
    NEEDS_DECISION = "needs-decision"


@dataclass(frozen=True, slots=True)
class LanePostPrIssueEvidence:
    issue_number: int
    issue_open: bool
    lifecycle_labels: tuple[str, ...]
    linked_pull_request_number: int
    pr_state: Literal["draft", "ready", "merged", "closed-superseded"]
    pr_head_sha: str
    pr_readback_current: bool
    closure_authorized: bool
    evidence_current: bool

    def __post_init__(self) -> None:
        for name in ("issue_number", "linked_pull_request_number"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "issue_open",
            "pr_readback_current",
            "closure_authorized",
            "evidence_current",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a built-in bool")
        if type(self.lifecycle_labels) is not tuple or any(
            type(label) is not str or not label for label in self.lifecycle_labels
        ):
            raise TypeError("lifecycle_labels must be an exact tuple of non-empty strings")
        if (
            type(self.pr_head_sha) is not str
            or len(self.pr_head_sha) != 40
            or any(char not in "0123456789abcdef" for char in self.pr_head_sha)
        ):
            raise ValueError("pr_head_sha must be a lowercase 40-character SHA")


@dataclass(frozen=True, slots=True)
class LanePostPrIssueReconciliation:
    disposition: LanePostPrIssueDisposition
    issue_number: int
    linked_pull_request_number: int
    expected_mutations: tuple[str, ...]
    ready_label: str | None
    reason_codes: tuple[str, ...]
    readback_required: bool
    fully_reconciled: bool
    merge_authorized: Literal[False] = field(default=False, init=False)
    ready_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.disposition) is not LanePostPrIssueDisposition:
            raise TypeError("disposition must be LanePostPrIssueDisposition")
        if type(self.expected_mutations) is not tuple or any(
            mutation not in {_MUTATION_REMOVE_READY, _MUTATION_CLOSE_ISSUE}
            for mutation in self.expected_mutations
        ):
            raise ValueError("expected_mutations must use the existing lifecycle-mutation vocabulary")
        if self.ready_label is not None and self.ready_label != READY_LABEL:
            raise ValueError("ready_label must identify the stale Ready projection")
        if (_MUTATION_REMOVE_READY in self.expected_mutations) != (
            self.ready_label is not None
        ):
            raise ValueError("ready-label removal and ready_label must agree")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str or not code for code in self.reason_codes
        ):
            raise TypeError("reason_codes must be an exact tuple of non-empty strings")
        if type(self.readback_required) is not bool or type(self.fully_reconciled) is not bool:
            raise TypeError("readback_required and fully_reconciled must be built-in bools")
        if self.disposition is LanePostPrIssueDisposition.ALREADY_RECONCILED and (
            self.expected_mutations or not self.fully_reconciled
        ):
            raise ValueError("already-reconciled plans project no mutations")
        if self.merge_authorized or self.ready_authorized or self.side_effects_performed:
            raise ValueError("reconciliation cannot grant merge/Ready authority or perform side effects")


@dataclass(frozen=True, slots=True)
class LanePostPrIssueTerminalProof:
    disposition: LanePostPrIssueDisposition
    issue_number: int
    fully_reconciled: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.disposition) is not LanePostPrIssueDisposition:
            raise TypeError("disposition must be LanePostPrIssueDisposition")
        if type(self.fully_reconciled) is not bool:
            raise TypeError("fully_reconciled must be a built-in bool")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str or not code for code in self.reason_codes
        ):
            raise TypeError("reason_codes must be an exact tuple of non-empty strings")


def _plan(
    evidence: LanePostPrIssueEvidence,
    disposition: LanePostPrIssueDisposition,
    expected_mutations: tuple[str, ...],
    ready_label: str | None,
    reason_codes: tuple[str, ...],
    readback_required: bool,
    fully_reconciled: bool,
) -> LanePostPrIssueReconciliation:
    return LanePostPrIssueReconciliation(
        disposition=disposition,
        issue_number=evidence.issue_number,
        linked_pull_request_number=evidence.linked_pull_request_number,
        expected_mutations=expected_mutations,
        ready_label=ready_label,
        reason_codes=reason_codes,
        readback_required=readback_required,
        fully_reconciled=fully_reconciled,
    )


def project_lane_post_pr_issue_reconciliation(
    evidence: LanePostPrIssueEvidence,
) -> LanePostPrIssueReconciliation:
    """Project the implementation issue's expected post-PR disposition."""
    if type(evidence) is not LanePostPrIssueEvidence:
        raise TypeError("evidence must be an exact LanePostPrIssueEvidence")
    if not evidence.evidence_current:
        return _plan(
            evidence,
            LanePostPrIssueDisposition.NEEDS_DECISION,
            (),
            None,
            ("lane-post-pr.evidence-not-current",),
            False,
            False,
        )
    if not evidence.pr_readback_current:
        return _plan(
            evidence,
            LanePostPrIssueDisposition.NEEDS_DECISION,
            (),
            None,
            ("lane-post-pr.pr-readback-not-current",),
            False,
            False,
        )
    if evidence.pr_state not in PR_STATES:
        return _plan(
            evidence,
            LanePostPrIssueDisposition.NEEDS_DECISION,
            (),
            None,
            ("lane-post-pr.pr-not-draft-ready",),
            False,
            False,
        )
    if not evidence.issue_open:
        return _plan(
            evidence,
            LanePostPrIssueDisposition.ALREADY_RECONCILED,
            (),
            None,
            ("lane-post-pr.issue-already-closed",),
            False,
            True,
        )
    stale_ready = READY_LABEL in evidence.lifecycle_labels
    mutations: list[str] = []
    reasons: list[str] = []
    if stale_ready:
        mutations.append(_MUTATION_REMOVE_READY)
        reasons.append("lane-post-pr.ready-stale")
    if evidence.closure_authorized:
        mutations.append(_MUTATION_CLOSE_ISSUE)
        reasons.append("lane-post-pr.close-authorized")
        return _plan(
            evidence,
            LanePostPrIssueDisposition.RECONCILE_READY_AND_CLOSE,
            tuple(mutations),
            READY_LABEL if stale_ready else None,
            tuple(reasons),
            True,
            False,
        )
    reasons.append("lane-post-pr.closure-authority-missing")
    return _plan(
        evidence,
        LanePostPrIssueDisposition.RECONCILE_READY_AWAITING_CLOSURE_AUTHORITY,
        tuple(mutations),
        READY_LABEL if stale_ready else None,
        tuple(reasons),
        stale_ready,
        False,
    )


def evaluate_lane_post_pr_issue_readback(
    plan: LanePostPrIssueReconciliation,
    *,
    issue_number: int,
    issue_open: bool,
    lifecycle_labels: tuple[str, ...],
    evidence_current: bool,
) -> LanePostPrIssueTerminalProof:
    """Prove the terminal disposition from the canonical post-mutation readback.

    The lane may report the Draft PR as fully reconciled (and advance the
    finite batch cursor) only when this proof returns ``fully_reconciled``.
    """
    if type(plan) is not LanePostPrIssueReconciliation:
        raise TypeError("plan must be an exact LanePostPrIssueReconciliation")
    if issue_number != plan.issue_number:
        raise ValueError("readback does not match the reconciled issue")
    if type(issue_open) is not bool or type(evidence_current) is not bool:
        raise TypeError("issue_open and evidence_current must be built-in bools")
    if type(lifecycle_labels) is not tuple or any(
        type(label) is not str or not label for label in lifecycle_labels
    ):
        raise TypeError("lifecycle_labels must be an exact tuple of non-empty strings")

    def proof(fully_reconciled: bool, reason_codes: tuple[str, ...]) -> LanePostPrIssueTerminalProof:
        return LanePostPrIssueTerminalProof(
            disposition=plan.disposition,
            issue_number=plan.issue_number,
            fully_reconciled=fully_reconciled,
            reason_codes=reason_codes,
        )

    if not evidence_current:
        return proof(False, ("lane-post-pr.readback-not-current",))
    if plan.disposition is LanePostPrIssueDisposition.ALREADY_RECONCILED:
        if issue_open:
            return proof(False, ("lane-post-pr.issue-reopened",))
        return proof(True, ("lane-post-pr.issue-closed",))
    if plan.disposition is LanePostPrIssueDisposition.NEEDS_DECISION:
        return proof(False, ("lane-post-pr.plan-was-needs-decision",))
    if plan.disposition is LanePostPrIssueDisposition.RECONCILE_READY_AND_CLOSE:
        if issue_open:
            return proof(False, ("lane-post-pr.issue-still-open",))
        return proof(True, ("lane-post-pr.issue-closed",))
    ready_gone = READY_LABEL not in lifecycle_labels
    if not issue_open:
        return proof(True, ("lane-post-pr.issue-closed",))
    if not ready_gone:
        return proof(False, ("lane-post-pr.ready-still-present",))
    return proof(False, ("lane-post-pr.closure-authority-still-missing",))
