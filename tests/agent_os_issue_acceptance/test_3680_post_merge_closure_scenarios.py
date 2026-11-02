"""Residual Lane D scenarios for #3680 (post-merge closure continuation).

The two #3680 seams themselves — satisfaction consumption in lifecycle
reconciliation and verbatim satisfaction citation in the closure-admission
judgment packet — are implemented on main by PR #3684 and covered by
``test_3680_satisfaction_closure_integration.py``. This file locks the
remaining scenarios the Lane D brief requires, which that file does not
exercise:

* a complete satisfaction record whose linked PR is **not merged**
  (draft or ready) projects no closure of any kind;
* a complete record for an **already-closed** issue is a safe no-op;
* **duplicate delivery is idempotent** at every pure layer (reconciliation
  result, closure receipt, lane post-PR projection) and a duplicate issue
  in one closure set is refused before any write;
* a missing GitHub execution capability (reader or writer failure)
  surfaces **explicit failure evidence** — a blocked / write-failed
  outcome naming the failure — never a silent success, and the complete
  record is still cited verbatim in the receipt;
* the Safe Implementation Lane post-PR surface (#2791) never projects a
  closure for a merged PR, even when closure is authorized there: the
  post-merge disposition stays with lifecycle reconciliation.

These are behavior-locking tests: they pass against the merged #3684
implementation, which is the proof that implementation already satisfies
these scenarios. Fixture builders follow the established patterns of
``test_3680_satisfaction_closure_integration.py``; satisfaction snapshots
use the exact Option B block shape (plain mappings, no producer imports).
"""

from __future__ import annotations

import pytest

from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    ClosureAcceptanceEvidence,
    ClosureIssueReadback,
    IssueClosureRequest,
    evaluate_issue_closure,
    run_closure_batch,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    DependencyState,
    FreshnessState,
    IssueOperationalEvidence,
    IssueState,
    LifecycleStage,
    PrimaryIssueClaim,
    ReadinessState,
    SourceState,
    TerminalDisposition,
    ValidationState,
    build_issue_operational_state,
)
from scripts.agent_os_issue_acceptance.lane_post_pr_issue_reconciliation import (
    LanePostPrIssueDisposition,
    LanePostPrIssueEvidence,
    project_lane_post_pr_issue_reconciliation,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    LifecycleStateSnapshot,
)
from scripts.agent_os_issue_acceptance.lifecycle_reconciliation import (
    LifecycleReconciliationInput,
    PullRequestEvidence,
    PullRequestState,
    ReconciliationOutcome,
    reconcile_lifecycle,
    serialize_lifecycle_reconciliation_result,
)

REPO = "Blummer92/agent-os"
DIGEST = "c" * 64
SOURCE = "a" * 40
HEAD = "b" * 40
APPROVAL = "approval:" + "1" * 64
EVIDENCE = "issueplan-current-state:" + "2" * 64


# ---------------------------------------------------------------------------
# Satisfaction snapshots (Option B block shape, as in the #3680 suite).
# ---------------------------------------------------------------------------


def criterion(index, disposition):
    return {
        "index": index,
        "identity": f"criterion-{index}-a1b2c3",
        "disposition": disposition,
        "reason_code": f"reason-{disposition}",
        "evidence": [f"pr:997@{'b' * 40}/qa-verdict-{index}"],
    }


def complete_snapshot(issue_number=996):
    return {
        "repository": REPO,
        "issue_number": issue_number,
        "issue_body_digest": DIGEST,
        "status": "complete",
        "criteria": [criterion(i, "satisfied") for i in (1, 2, 3)],
    }


# ---------------------------------------------------------------------------
# Reconciliation fixtures (pattern: test_3680_satisfaction_closure_integration).
# ---------------------------------------------------------------------------


def authority(state: AuthorizationState) -> AuthorityProjection:
    return AuthorityProjection(
        state=state,
        evidence_id=(
            APPROVAL
            if state in {AuthorizationState.AUTHORIZED, AuthorizationState.STALE}
            else None
        ),
    )


def op_state(
    *,
    issue_state=IssueState.OPEN,
    terminal=TerminalDisposition.NONE,
    claim_state="merged",
    stage=LifecycleStage.IMPLEMENTATION,
    labels=("status:ready",),
):
    return build_issue_operational_state(
        IssueOperationalEvidence(
            repository=REPO,
            issue_number=996,
            source_revision=SOURCE,
            observed_at="2026-08-09T17:10:00Z",
            evidence_ids=(EVIDENCE,),
            source_state=SourceState.COMPLETE,
            issue_state=issue_state,
            lifecycle_stage=stage,
            terminal_disposition=terminal,
            readiness=ReadinessState.READY,
            implementation_authorization=authority(AuthorizationState.AUTHORIZED),
            ready_for_review_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            execution_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            merge_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            closure_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            external_write_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            dependency_state=DependencyState.CLEAR,
            primary_claims=(
                PrimaryIssueClaim(
                    pull_request_number=997,
                    branch="agent/996-lifecycle-reconciliation",
                    head_sha=HEAD,
                    state=claim_state,
                ),
            ),
            validation_state=ValidationState.NOT_RUN,
            freshness_state=FreshnessState.CURRENT,
            observed_labels=labels,
        )
    )


def lifecycle_snapshot(*, pr_state, merged, issue_state="open", labels=("status:ready",)):
    return LifecycleStateSnapshot(
        repository=REPO, issue_number=996,
        pull_request_number=997, source_head=HEAD, base_head=SOURCE,
        pr_state=pr_state, merged=merged, issue_state=issue_state,
        review_state="clear", unresolved_threads=0,
        lifecycle_labels=labels, observed_revision="revision-1",
    )


def unmerged_input(pr_state: PullRequestState, claim_state: str, snap_pr_state: str):
    return LifecycleReconciliationInput(
        repository=REPO, issue_number=996,
        operational_state=op_state(
            claim_state=claim_state,
            stage=(
                LifecycleStage.DRAFT_PR
                if pr_state is PullRequestState.DRAFT
                else LifecycleStage.REVIEW
            ),
        ),
        lifecycle_snapshot=lifecycle_snapshot(pr_state=snap_pr_state, merged=False),
        current_pull_request=PullRequestEvidence(
            997, "agent/996-lifecycle-reconciliation", HEAD, pr_state, "pr:997"
        ),
        satisfaction=complete_snapshot(),
    )


def merged_input(satisfaction=None):
    return LifecycleReconciliationInput(
        repository=REPO, issue_number=996,
        operational_state=op_state(),
        lifecycle_snapshot=lifecycle_snapshot(pr_state="ready", merged=True),
        current_pull_request=PullRequestEvidence(
            997, "agent/996-lifecycle-reconciliation", HEAD,
            PullRequestState.MERGED, "pr:997",
        ),
        satisfaction=satisfaction,
    )


def close_actions(result):
    return [
        item
        for item in result.actions
        if item.reason_code == "lifecycle.merged-pr-open-issue"
    ]


# ---------------------------------------------------------------------------
# Not merged: a complete record alone projects no closure.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pr_state,claim_state,snap_pr_state",
    [
        (PullRequestState.DRAFT, "draft", "draft"),
        (PullRequestState.READY, "ready", "ready"),
    ],
)
def test_complete_record_with_unmerged_pr_projects_no_closure(
    pr_state, claim_state, snap_pr_state
):
    result = reconcile_lifecycle(
        unmerged_input(pr_state, claim_state, snap_pr_state)
    )
    # The evidence signal is reported, but it is only a signal: no
    # merged-PR closure reason fires and no action projects a closure.
    assert result.to_dict()["satisfaction"]["closure_ready"] is True
    assert "lifecycle.merged-pr-open-issue" not in result.reason_codes
    assert close_actions(result) == []
    assert not any(
        item.required_mutation == "close-issue" for item in result.actions
    )
    assert result.closure_authorization is AuthorizationState.NOT_AUTHORIZED


# ---------------------------------------------------------------------------
# Already closed: a complete record is a safe no-op.
# ---------------------------------------------------------------------------


def test_complete_record_for_already_closed_issue_is_a_safe_noop():
    closed_input = LifecycleReconciliationInput(
        repository=REPO, issue_number=996,
        operational_state=op_state(
            issue_state=IssueState.CLOSED,
            terminal=TerminalDisposition.COMPLETED,
            stage=LifecycleStage.CLOSED,
            labels=(),
        ),
        lifecycle_snapshot=lifecycle_snapshot(
            pr_state="ready", merged=True, issue_state="closed", labels=()
        ),
        current_pull_request=PullRequestEvidence(
            997, "agent/996-lifecycle-reconciliation", HEAD,
            PullRequestState.MERGED, "pr:997",
        ),
        satisfaction=complete_snapshot(),
    )
    result = reconcile_lifecycle(closed_input)
    # Converged: nothing to do, nothing projected, nothing resurrected.
    assert result.outcome is ReconciliationOutcome.CONSISTENT
    assert result.actions == ()
    assert not any(
        item.required_mutation == "close-issue" for item in result.actions
    )
    assert result.to_dict()["satisfaction"]["closure_ready"] is True


# ---------------------------------------------------------------------------
# Duplicate delivery: idempotent at every pure layer.
# ---------------------------------------------------------------------------


def test_duplicate_reconciliation_delivery_is_idempotent():
    first_input = merged_input(complete_snapshot())
    second_input = merged_input(complete_snapshot())
    assert first_input.input_id == second_input.input_id
    first = reconcile_lifecycle(first_input)
    second = reconcile_lifecycle(second_input)
    redelivered = reconcile_lifecycle(first_input)
    assert serialize_lifecycle_reconciliation_result(first) == (
        serialize_lifecycle_reconciliation_result(second)
    )
    assert serialize_lifecycle_reconciliation_result(first) == (
        serialize_lifecycle_reconciliation_result(redelivered)
    )
    assert first.result_id == second.result_id == redelivered.result_id


def test_duplicate_packet_evaluation_is_idempotent():
    request = closure_request(satisfaction=complete_snapshot(3432))
    snap = closure_snapshot()
    first = evaluate_issue_closure(request, snap)
    second = evaluate_issue_closure(request, snap)
    assert first == second
    assert first["receipt_id"] == second["receipt_id"]
    assert first["satisfaction"] == complete_snapshot(3432)


# ---------------------------------------------------------------------------
# Closure packet / batch fixtures (pattern: the #3680 suite).
# ---------------------------------------------------------------------------


def closure_snapshot(issue=3432, **changes):
    data = dict(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        source_head=None,
        base_head=None,
        pr_state="none",
        merged=False,
        issue_state="open",
        review_state="clear",
        unresolved_threads=0,
        lifecycle_labels=(),
        observed_revision=f"rev-{issue}-1",
    )
    data.update(changes)
    return LifecycleStateSnapshot(**data)


def closure_request(issue=3432, *, satisfaction=None):
    decision = LifecycleOwnerDecision(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        requested_mutations=("close-issue",),
        authorizer_id="repository-owner",
        decision_id=f"owner-decision-{issue}",
        decision_recorded=True,
    )
    acceptance = ClosureAcceptanceEvidence(
        verdict="pass",
        evidence_id=f"qa-evidence-{issue}",
        evaluator_id="independent-qa",
    )
    return IssueClosureRequest(
        decision=decision, acceptance=acceptance, satisfaction=satisfaction
    )


class FakeReader:
    def __init__(self, snapshots, *, closed_state_reasons=None):
        self._snapshots = dict(snapshots)
        self._closed_state_reasons = dict(closed_state_reasons or {})
        self.reads = []

    def read_issue_snapshot(self, repository, issue_number):
        self.reads.append(issue_number)
        return self._snapshots[issue_number]

    def read_issue_readback(self, repository, issue_number):
        snap = self.read_issue_snapshot(repository, issue_number)
        reason = (
            self._closed_state_reasons.get(issue_number, "completed")
            if snap.issue_state == "closed"
            else None
        )
        return ClosureIssueReadback(snapshot=snap, state_reason=reason)

    def set(self, snap):
        self._snapshots[snap.issue_number] = snap


class FakeWriter:
    def __init__(self, reader, *, fail_for=()):
        self.reader = reader
        self.calls = []
        self.fail_for = set(fail_for)

    def close_issue(self, repository, issue_number, *, state_reason):
        self.calls.append((issue_number, state_reason))
        if issue_number in self.fail_for:
            raise RuntimeError("github-write-failed")
        current = self.reader._snapshots[issue_number]
        self.reader.set(
            closure_snapshot(
                issue_number,
                issue_state="closed",
                observed_revision=current.observed_revision + "-closed",
            )
        )


class UnavailableReader:
    """The host reader capability is missing: every read fails."""

    def __init__(self):
        self.reads = []

    def read_issue_snapshot(self, repository, issue_number):
        self.reads.append(issue_number)
        raise RuntimeError("github-read-unavailable")

    def read_issue_readback(self, repository, issue_number):
        self.reads.append(issue_number)
        raise RuntimeError("github-read-unavailable")


# ---------------------------------------------------------------------------
# Batch: duplicate delivery, already-closed, missing capability.
# ---------------------------------------------------------------------------


def test_batch_refuses_a_duplicate_issue_before_any_write():
    request = closure_request(satisfaction=complete_snapshot(3432))
    reader = FakeReader({3432: closure_snapshot()})
    writer = FakeWriter(reader)
    with pytest.raises(ValueError, match="duplicate issue"):
        run_closure_batch((request, request), reader=reader, writer=writer)
    assert writer.calls == []


def test_batch_already_closed_issue_with_complete_record_never_writes():
    request = closure_request(satisfaction=complete_snapshot(3432))
    reader = FakeReader(
        {3432: closure_snapshot(issue_state="closed")}
    )
    writer = FakeWriter(reader)
    outcomes = run_closure_batch((request,), reader=reader, writer=writer)
    assert [o.status for o in outcomes] == ["already-closed"]
    assert outcomes[0].readback_verified is True
    assert writer.calls == []


def test_batch_unavailable_reader_is_explicit_failure_evidence():
    request = closure_request(satisfaction=complete_snapshot(3432))
    reader = UnavailableReader()
    writer = FakeWriter(FakeReader({3432: closure_snapshot()}))
    outcomes = run_closure_batch((request,), reader=reader, writer=writer)
    assert [o.status for o in outcomes] == ["blocked"]
    assert outcomes[0].reason_codes == ("closure.evidence-unavailable",)
    assert outcomes[0].readback_verified is False
    assert writer.calls == []


def test_batch_writer_failure_is_explicit_and_never_a_success():
    request = closure_request(satisfaction=complete_snapshot(3432))
    reader = FakeReader({3432: closure_snapshot()})
    writer = FakeWriter(reader, fail_for={3432})
    outcomes = run_closure_batch((request,), reader=reader, writer=writer)
    assert [o.status for o in outcomes] == ["write-failed"]
    # The failure evidence names the failure; the receipt still cites
    # the complete record verbatim; nothing reports the issue closed.
    assert outcomes[0].reason_codes == ("closure.write-failed:RuntimeError",)
    assert outcomes[0].receipt["satisfaction"] == complete_snapshot(3432)
    assert outcomes[0].readback_verified is False
    assert writer.calls == [(3432, "completed")]


# ---------------------------------------------------------------------------
# Lane post-PR surface: a merged PR is never closed from this surface.
# ---------------------------------------------------------------------------


def test_lane_post_pr_surface_never_projects_closure_for_a_merged_pr():
    evidence = LanePostPrIssueEvidence(
        issue_number=996,
        issue_open=True,
        lifecycle_labels=("status:ready",),
        linked_pull_request_number=997,
        pr_state="merged",
        pr_head_sha=HEAD,
        pr_readback_current=True,
        closure_authorized=True,
        evidence_current=True,
    )
    first = project_lane_post_pr_issue_reconciliation(evidence)
    redelivered = project_lane_post_pr_issue_reconciliation(evidence)
    # Even with closure authorized at this surface, a merged PR is out
    # of its draft/ready scope: needs-decision, zero mutations, and the
    # projection is deterministic across duplicate delivery.
    assert first.disposition is LanePostPrIssueDisposition.NEEDS_DECISION
    assert first.reason_codes == ("lane-post-pr.pr-not-draft-ready",)
    assert first.expected_mutations == ()
    assert first.fully_reconciled is False
    assert first.side_effects_performed is False
    assert first == redelivered
