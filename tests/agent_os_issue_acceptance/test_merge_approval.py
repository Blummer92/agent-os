"""Tests for the #3463 merge-approval repair (Option A / design A1).

Risk-based, not exhaustive: each test maps to a Phase 6 priority.
Existing suites (approval records, projections, merge authorization,
dispatch) cover the unchanged invariants; these tests cover only
what is new: the adapter, the producer's posting-to-reader
connection, and the executor's both-gates rule plus exact-head
merge and consumption.

All GitHub interaction is faked in-memory. No live GitHub call is
made by any test here.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEDULER_SRC = ROOT / "08_Tooling/workflow-scheduler/src"
for path in (ROOT, SCHEDULER_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.agent_os_issue_acceptance import (  # noqa: E402
    ApprovalKind,
    ApprovalState,
    MergeAuthorizationState,
    MergeCheckEvidence,
    MergeReviewEvidence,
    PullRequestMergeEvidence,
    evaluate_approval_applicability,
    record_approval_decision,
    serialize_approval_applicability_result,
    serialize_approval_record,
    serialize_approved_execution_projection,
)
from scripts.agent_os_issue_acceptance.merge_approval import (  # noqa: E402
    MergeApprovalDecision,
    build_merge_approval_triple,
    merge_decision_id,
)
from scripts.agent_os_issue_acceptance.merge_executor import execute_merge  # noqa: E402
from scripts.agent_os_issue_acceptance.merge_producer import (  # noqa: E402
    produce_merge_authorization,
)
from scripts.agent_os_issue_acceptance.approval_source import (  # noqa: E402
    reacquire_approval_source,
    serialize_approval_comment,
)
from scripts.agent_os_issue_acceptance.approval_source import (  # noqa: E402
    APPLICABILITY_MARKER,
    APPROVAL_MARKER,
    PROJECTION_MARKER,
    ApprovalCommentSnapshot,
    ApprovalSourceSnapshot,
)
from scripts.agent_os_issue_acceptance.merge_authorization import (  # noqa: E402
    build_merge_proposal as _build_merge_proposal_direct,
)
from scripts.agent_os_issue_acceptance.merge_authorization_source import (  # noqa: E402
    AUTHORIZATION_MARKER,
    MergeAuthorizationCommentSnapshot,
    MergeAuthorizationSourceSnapshot,
    serialize_merge_authorization_comment,
)

REPO = "Blummer92/agent-os"
PR = 4000
HEAD = "a" * 40
HEAD2 = "e" * 40
BASE = "b" * 40
MERGE_COMMIT = "c" * 40
DECISION_AT = "2026-07-26T14:00:00Z"
EVALUATED_AT = "2026-07-26T14:10:00Z"
EXPIRES_AT = "2026-07-26T16:00:00Z"
BODY_SHA = "d" * 64


def _scope() -> str:
    return hashlib.sha256(b"merge-approval-test-scope").hexdigest()


def make_evidence(**overrides) -> PullRequestMergeEvidence:
    values = dict(
        repository=REPO,
        pull_request_number=PR,
        head_sha=HEAD,
        base_branch="main",
        base_sha_or_evidence_id=BASE,
        draft=False,
        ready_for_review=True,
        proposed_merge_method="merge",
        changed_scope_fingerprint=_scope(),
        allowed_files=("src/a.py",),
        forbidden_paths=(),
        required_tests=("tests/test_a.py",),
        required_checks=(
            MergeCheckEvidence(
                context="ci",
                app_identity="github-actions",
                tested_sha=HEAD,
                evidence_id="",
                state="success",
            ),
        ),
        review_evidence=MergeReviewEvidence(
            blocking_review_present=False,
            unresolved_conversation_count=0,
            exact_head_reviewed=True,
        ),
        pr_title="Merge approval test",
        pr_body="Merge approval test body",
        pr_metadata_sha256="",
        closure_admissions=(),
        evidence_id="",
    )
    values.update(overrides)
    if "required_checks" in overrides and overrides["required_checks"]:
        # Keep check shas consistent with an overridden head unless
        # the test overrides checks explicitly for that purpose.
        pass
    return PullRequestMergeEvidence(**values)


def make_decision(evidence: PullRequestMergeEvidence, **overrides) -> MergeApprovalDecision:
    values = dict(
        repository=evidence.repository,
        pr_number=evidence.pull_request_number,
        head_sha=evidence.head_sha,
        base_branch=evidence.base_branch,
        base_sha_or_evidence_id=evidence.base_sha_or_evidence_id,
        merge_method=evidence.proposed_merge_method,
        authorizer_id="32861845",
        decision_id="",
        decision_at=DECISION_AT,
        expires_at=EXPIRES_AT,
    )
    values.update(overrides)
    if not values["decision_id"]:
        values["decision_id"] = merge_decision_id(
            repository=values["repository"],
            pr_number=values["pr_number"],
            head_sha=values["head_sha"],
            base_branch=values["base_branch"],
            base_sha_or_evidence_id=values["base_sha_or_evidence_id"],
            merge_method=values["merge_method"],
            changed_scope_fingerprint=evidence.changed_scope_fingerprint,
            pr_metadata_sha256=evidence.pr_metadata_sha256,
            expires_at=values["expires_at"],
        )
    return MergeApprovalDecision(**values)


class FakeConversation:
    """One fake PR conversation backing both trusted-source transports.

    ``post_comment`` routes by marker; both read methods serve the
    same store, which is exactly what makes the producer test a
    posting-to-reader connection test rather than a serialization
    test.
    """

    def __init__(self) -> None:
        self.approval_comments: list[dict] = []
        self.authorization_comments: list[dict] = []
        self._next_id = 1
        self._clock = 0
        self.posted_bodies: list[str] = []
        self.fail_posts_after: int | None = None

    def _stamp(self) -> str:
        self._clock += 1
        return f"2026-07-26T14:{10 + self._clock:02d}:00Z"

    def post_comment(self, *, repository: str, pr_number: int, body: str):
        if self.fail_posts_after is not None and len(self.posted_bodies) >= self.fail_posts_after:
            raise RuntimeError("fake post failure")
        comment_id = self._next_id
        self._next_id += 1
        self.posted_bodies.append(body)
        entry = {
            "comment_id": comment_id,
            "author_login": "Blummer92",
            "created_at": self._stamp(),
            "body": body,
        }
        if body.startswith(AUTHORIZATION_MARKER + "\n"):
            self.authorization_comments.append(entry)
        else:
            self.approval_comments.append(entry)
        return comment_id

    def read_approval_source(self, repository: str, pr_number: int):
        return ApprovalSourceSnapshot(
            repository=repository,
            pr_number=pr_number,
            owner_login="Blummer92",
            owner_type="User",
            comments_complete=True,
            comments=tuple(
                ApprovalCommentSnapshot(**entry) for entry in self.approval_comments
            ),
        )

    def read_merge_authorization_source(self, repository: str, pr_number: int):
        return MergeAuthorizationSourceSnapshot(
            repository=repository,
            pr_number=pr_number,
            owner_login="Blummer92",
            owner_type="User",
            comments_complete=True,
            comments=tuple(
                MergeAuthorizationCommentSnapshot(**entry)
                for entry in self.authorization_comments
            ),
        )


def make_trigger(method: str = "merge", head: str = HEAD) -> dict:
    return {
        "body": f"/agent-os merge-admit {PR} {head} {BODY_SHA} {method}",
        "author_login": "Blummer92",
        "author_id": 32861845,
    }


def make_receipt(authorization_id: str, approval_id: str, **overrides) -> dict:
    receipt = {
        "schema_version": "1.0",
        "operation": "merge-dispatch-applicability",
        "repository": REPO,
        "pr_number": PR,
        "logical_trigger_id": "issue-comment-trigger:" + "f" * 64,
        "expected_head_sha": HEAD,
        "expected_method": "merge",
        "observed_head_sha": HEAD,
        "observed_base_sha": BASE,
        "evaluated_at": EVALUATED_AT,
        "authorization_id": authorization_id,
        "approval_id": approval_id,
        "dispatch_checks_passed": True,
        "verified": ["canonical-applicability"],
        "reason_codes": [],
        "missing_interfaces": [],
        "canonical_applicability_evaluated": True,
        "status": "applicable",
        "merge_authorized": True,
    }
    receipt.update(overrides)
    return receipt


def produced(conversation: FakeConversation, evidence=None):
    evidence = evidence or make_evidence()
    decision = make_decision(evidence)
    result = produce_merge_authorization(
        decision,
        evidence,
        evaluated_at=EVALUATED_AT,
        post_comment=conversation.post_comment,
        approval_transport=conversation,
        authorization_transport=conversation,
    )
    return decision, evidence, result


def executor_kwargs(conversation, evidence, receipt, **overrides):
    calls: dict = {"merges": [], "states": []}
    state = {"merged": False, "merge_commit_sha": None, "head_sha": HEAD}

    def merge_pull_request(*, repository, pr_number, sha, method):
        calls["merges"].append((repository, pr_number, sha, method))
        state["merged"] = True
        state["merge_commit_sha"] = MERGE_COMMIT
        return {"merge_commit_sha": MERGE_COMMIT, "actor_id": 32861845}

    def read_pr_state(repository, pr_number):
        calls["states"].append((repository, pr_number))
        return {
            "merged": state["merged"],
            "merge_commit_sha": state["merge_commit_sha"],
            "head_sha": state["head_sha"],
        }

    kwargs = dict(
        repository=REPO,
        pr_number=PR,
        trigger_comment=make_trigger(),
        dispatch_receipt=receipt,
        read_pr_evidence=lambda repository, pr_number: evidence,
        approval_transport=conversation,
        authorization_transport=conversation,
        merge_pull_request=merge_pull_request,
        post_comment=conversation.post_comment,
        read_pr_state=read_pr_state,
        evaluated_at=EVALUATED_AT,
    )
    kwargs.update(overrides)
    return kwargs, calls, state


# Priority 1: the adapter cannot authorize unrelated operations,
# and its records are merge-bound.

def test_adapter_builds_valid_merge_triple():
    evidence = make_evidence()
    decision = make_decision(evidence)
    approval, applicability, projection = build_merge_approval_triple(
        decision, evidence, evaluated_at=EVALUATED_AT
    )
    assert approval.binding.proposal_id.startswith("merge-approval:")
    assert approval.binding.proposal_version == "merge-approval/1"
    assert approval.approval_kind is ApprovalKind.SOURCE_MUTATION
    assert approval.schema_version == "1.0"
    assert approval.semantic_subject_id is None
    assert approval.state is ApprovalState.APPROVED
    assert approval.revision_number == 2
    assert approval.binding.cohort_summaries[0].classification == "merge"
    assert approval.binding.supplied_node_ids == (f"merge:{REPO}:{PR}",)
    assert applicability.status == "applicable"
    assert applicability.approval_applicable is True
    assert applicability.approval_id == approval.approval_id
    assert applicability.approval_revision == approval.approval_revision
    assert applicability.current_proposal_id == approval.binding.proposal_id
    assert projection.approval_state == "approved"
    assert projection.approval_revision_number == 2
    assert projection.tested_repository_sha == HEAD
    assert projection.allowed_files == evidence.allowed_files
    assert projection.required_tests == evidence.required_tests
    assert projection.repository_evidence_type == "branch-head"


@pytest.mark.parametrize(
    "field,value",
    [
        ("head_sha", HEAD2),
        ("base_branch", "other"),
        ("base_sha_or_evidence_id", "f" * 40),
        ("merge_method", "squash"),
        ("repository", "Blummer92/other"),
        ("pr_number", 4001),
        ("authorizer_id", "999"),
        ("decision_id", "0" * 64),
    ],
)
def test_adapter_rejects_mismatched_decision(field, value):
    evidence = make_evidence()
    decision = make_decision(evidence, **{field: value})
    with pytest.raises(ValueError):
        build_merge_approval_triple(decision, evidence, evaluated_at=EVALUATED_AT)


def test_adapter_rejects_expired_and_early_and_draft():
    evidence = make_evidence()
    decision = make_decision(evidence)
    with pytest.raises(ValueError):
        build_merge_approval_triple(decision, evidence, evaluated_at=EXPIRES_AT)
    with pytest.raises(ValueError):
        build_merge_approval_triple(decision, evidence, evaluated_at="2026-07-26T13:00:00Z")
    draft = make_evidence(draft=True, ready_for_review=False)
    with pytest.raises(ValueError):
        build_merge_approval_triple(make_decision(draft), draft, evaluated_at=EVALUATED_AT)


def test_adapter_rejects_non_sha40_base_identity():
    with pytest.raises(ValueError):
        MergeApprovalDecision(
            repository=REPO,
            pr_number=PR,
            head_sha=HEAD,
            base_branch="main",
            base_sha_or_evidence_id="base-evidence:" + "0" * 64,
            merge_method="merge",
            authorizer_id="32861845",
            decision_id="0" * 64,
            decision_at=DECISION_AT,
            expires_at=EXPIRES_AT,
        )


def test_adapter_triple_is_bound_to_exact_evidence():
    evidence = make_evidence()
    triple = build_merge_approval_triple(
        make_decision(evidence), evidence, evaluated_at=EVALUATED_AT
    )
    moved = make_evidence(
        head_sha=HEAD2,
        required_checks=(
            MergeCheckEvidence(
                context="ci",
                app_identity="github-actions",
                tested_sha=HEAD2,
                evidence_id="",
                state="success",
            ),
        ),
    )
    with pytest.raises((TypeError, ValueError)):
        _build_merge_proposal_direct(triple[0], triple[1], triple[2], moved)


def test_merge_triple_fails_planning_evaluation_closed():
    # A merge approval fed to the planning evaluator must never
    # come out applicable: the planning path recomputes a binding
    # from a planning proposal, which a merge approval cannot
    # supply. Any non-applicable outcome (or a type error from the
    # proposal verifier) is fail-closed; "applicable" would be a
    # cross-use hole.
    evidence = make_evidence()
    approval, _applicability, _projection = build_merge_approval_triple(
        make_decision(evidence), evidence, evaluated_at=EVALUATED_AT
    )
    proposal = _build_merge_proposal_direct(
        approval, _applicability, _projection, evidence
    )
    try:
        result = evaluate_approval_applicability(
            approval,
            proposal,
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            evaluated_at=EVALUATED_AT,
        )
    except (TypeError, ValueError):
        return
    assert result.status != "applicable"


def test_revocation_blocks_via_needs_decision_not_stale():
    # Phase 4 QA B-1: posting a revocation revision alongside the
    # approved revision makes the approval reader return
    # NEEDS_DECISION (conflicting artifact), NOT STALE. Dispatch
    # still blocks (non-current), but tests must assert the true
    # behavior.
    conversation = FakeConversation()
    evidence = make_evidence()
    approval, applicability, projection = build_merge_approval_triple(
        make_decision(evidence), evidence, evaluated_at=EVALUATED_AT
    )
    conversation.post_comment(
        repository=REPO,
        pr_number=PR,
        body=serialize_approval_comment(APPROVAL_MARKER, serialize_approval_record(approval)),
    )
    conversation.post_comment(
        repository=REPO,
        pr_number=PR,
        body=serialize_approval_comment(
            APPLICABILITY_MARKER, serialize_approval_applicability_result(applicability)
        ),
    )
    conversation.post_comment(
        repository=REPO,
        pr_number=PR,
        body=serialize_approval_comment(
            PROJECTION_MARKER, serialize_approved_execution_projection(projection)
        ),
    )
    revoked = record_approval_decision(
        approval,
        state=ApprovalState.INVALIDATED,
        decision_id="0" * 64,
        authorizer_id="32861845",
        decision_at=EVALUATED_AT,
    )
    conversation.post_comment(
        repository=REPO,
        pr_number=PR,
        body=serialize_approval_comment(APPROVAL_MARKER, serialize_approval_record(revoked)),
    )
    result = reacquire_approval_source(
        transport=conversation,
        repository=REPO,
        pr_number=PR,
        expected_approval_id=approval.approval_id,
    )
    assert result.status.value == "needs-decision"
    assert "source.trusted-record-malformed" in result.reason_codes


# Priority 4: the producer connects to a real trusted posting consumer.

def test_producer_posts_triple_and_authorization_with_readback():
    conversation = FakeConversation()
    _decision, evidence, result = produced(conversation)
    assert result.approval_source_status == "current"
    assert result.authorization_source_status == "current"
    assert len(conversation.posted_bodies) == 4
    assert conversation.posted_bodies[0].startswith(APPROVAL_MARKER + "\n")
    assert conversation.posted_bodies[3].startswith(AUTHORIZATION_MARKER + "\n")
    approval_result = reacquire_approval_source(
        transport=conversation,
        repository=REPO,
        pr_number=PR,
        expected_approval_id=result.approval_id,
    )
    assert approval_result.status.value == "current"
    assert approval_result.approval is not None
    assert approval_result.approval.binding.tested_repository_sha == HEAD


def test_producer_readback_failure_raises():
    posted = FakeConversation()
    empty = FakeConversation()
    decision = make_decision(make_evidence())
    evidence = make_evidence()
    with pytest.raises(ValueError, match="readback failed"):
        produce_merge_authorization(
            decision,
            evidence,
            evaluated_at=EVALUATED_AT,
            post_comment=posted.post_comment,
            approval_transport=empty,
            authorization_transport=empty,
        )


# Priority 5 + 6: the executor requires both gates; exact-head merge
# and post-merge consumption.

def test_executor_dry_run_applicable_without_merge():
    conversation = FakeConversation()
    _decision, _evidence, result = produced(conversation)
    receipt = make_receipt(result.authorization_id, result.approval_id)
    kwargs, calls, _state = executor_kwargs(
        conversation, make_evidence(), receipt, dry_run=True
    )
    outcome = execute_merge(**kwargs)
    assert outcome.status == "dry-run-applicable"
    assert outcome.reason_codes == ()
    assert calls["merges"] == []


def test_executor_live_merges_and_consumes():
    conversation = FakeConversation()
    _decision, _evidence, result = produced(conversation)
    receipt = make_receipt(result.authorization_id, result.approval_id)
    kwargs, calls, _state = executor_kwargs(conversation, make_evidence(), receipt)
    outcome = execute_merge(**kwargs)
    assert outcome.status == "merged"
    assert outcome.merge_commit_sha == MERGE_COMMIT
    assert outcome.consumed_authorization_revision is not None
    assert calls["merges"] == [(REPO, PR, HEAD, "merge")]
    # The authorization is now consumed: a second run blocks.
    kwargs2, calls2, _state2 = executor_kwargs(
        conversation, make_evidence(), receipt
    )
    outcome2 = execute_merge(**kwargs2)
    assert outcome2.status == "blocked"
    assert calls2["merges"] == []


@pytest.mark.parametrize(
    "receipt_override,reason",
    [
        ({"status": "blocked"}, "receipt.not-applicable"),
        ({"merge_authorized": False}, "receipt.not-authorized"),
        ({"expected_head_sha": HEAD2}, "receipt.head-mismatch"),
        ({"expected_method": "squash"}, "receipt.method-mismatch"),
        ({"dispatch_checks_passed": False}, "receipt.checks-not-passed"),
        ({"canonical_applicability_evaluated": False}, "receipt.canonical-not-evaluated"),
        ({"reason_codes": ["checks.failed"]}, "receipt.has-reasons"),
        ({"logical_trigger_id": "bogus"}, "receipt.trigger-id-malformed"),
    ],
)
def test_executor_blocks_on_bad_receipt(receipt_override, reason):
    conversation = FakeConversation()
    _decision, _evidence, result = produced(conversation)
    receipt = make_receipt(
        result.authorization_id, result.approval_id, **receipt_override
    )
    kwargs, calls, _state = executor_kwargs(conversation, make_evidence(), receipt)
    outcome = execute_merge(**kwargs)
    assert outcome.status == "blocked"
    assert outcome.reason_codes == (reason,)
    assert calls["merges"] == []


def test_executor_blocks_on_bad_trigger_and_wrong_authorization():
    conversation = FakeConversation()
    _decision, _evidence, result = produced(conversation)
    receipt = make_receipt(result.authorization_id, result.approval_id)
    bad_trigger = make_trigger()
    bad_trigger["author_id"] = 999
    kwargs, calls, _state = executor_kwargs(
        conversation, make_evidence(), receipt, trigger_comment=bad_trigger
    )
    assert execute_merge(**kwargs).status == "blocked"
    assert calls["merges"] == []
    wrong_receipt = make_receipt("merge-authorization:" + "0" * 64, result.approval_id)
    kwargs, calls, _state = executor_kwargs(conversation, make_evidence(), wrong_receipt)
    outcome = execute_merge(**kwargs)
    assert outcome.status == "blocked"
    assert calls["merges"] == []


def test_executor_blocks_on_drifted_live_evidence_and_failing_checks():
    conversation = FakeConversation()
    _decision, _evidence, result = produced(conversation)
    receipt = make_receipt(result.authorization_id, result.approval_id)
    drifted = make_evidence(
        head_sha=HEAD2,
        required_checks=(
            MergeCheckEvidence(
                context="ci",
                app_identity="github-actions",
                tested_sha=HEAD2,
                evidence_id="",
                state="success",
            ),
        ),
    )
    kwargs, calls, _state = executor_kwargs(conversation, drifted, receipt)
    outcome = execute_merge(**kwargs)
    assert outcome.status == "blocked"
    assert outcome.reason_codes == ("evidence.mismatch",)
    assert calls["merges"] == []
    failing = make_evidence(
        required_checks=(
            MergeCheckEvidence(
                context="ci",
                app_identity="github-actions",
                tested_sha=HEAD,
                evidence_id="",
                state="failure",
            ),
        )
    )
    kwargs, calls, _state = executor_kwargs(conversation, failing, receipt)
    outcome = execute_merge(**kwargs)
    assert outcome.status == "blocked"
    assert outcome.reason_codes == ("canonical-not-applicable",)
    assert calls["merges"] == []


def test_executor_blocks_when_approval_revoked_after_production():
    conversation = FakeConversation()
    _decision, evidence, result = produced(conversation)
    # Revoke the approval after production: post an INVALIDATED
    # revision next to the approved one (B-1 true behavior: the
    # reader returns NEEDS_DECISION, and dispatch blocks).
    approval_result = reacquire_approval_source(
        transport=conversation,
        repository=REPO,
        pr_number=PR,
        expected_approval_id=result.approval_id,
    )
    assert approval_result.approval is not None
    revoked = record_approval_decision(
        approval_result.approval,
        state=ApprovalState.INVALIDATED,
        decision_id="0" * 64,
        authorizer_id="32861845",
        decision_at=EVALUATED_AT,
    )
    conversation.post_comment(
        repository=REPO,
        pr_number=PR,
        body=serialize_approval_comment(APPROVAL_MARKER, serialize_approval_record(revoked)),
    )
    receipt = make_receipt(result.authorization_id, result.approval_id)
    kwargs, calls, _state = executor_kwargs(conversation, evidence, receipt)
    outcome = execute_merge(**kwargs)
    assert outcome.status == "blocked"
    assert outcome.reason_codes == ("approval-source-not-current",)
    assert calls["merges"] == []


def test_executor_failed_when_consumption_post_fails():
    conversation = FakeConversation()
    _decision, _evidence, result = produced(conversation)
    receipt = make_receipt(result.authorization_id, result.approval_id)
    kwargs, calls, _state = executor_kwargs(conversation, make_evidence(), receipt)
    # The producer posted 4 comments; fail the 5th post (the CONSUMED
    # revision) so the merge happens but consumption cannot post.
    conversation.fail_posts_after = 4
    outcome = execute_merge(**kwargs)
    assert outcome.status == "failed"
    assert outcome.reason_codes == ("merge.consumed-post-failed",)
    assert len(calls["merges"]) == 1


# Priority 7: one end-to-end fake-provider integration test using the
# actual production functions.

def test_end_to_end_producer_to_consumed_merge():
    conversation = FakeConversation()
    evidence = make_evidence()
    decision = make_decision(evidence)
    produced_result = produce_merge_authorization(
        decision,
        evidence,
        evaluated_at=EVALUATED_AT,
        post_comment=conversation.post_comment,
        approval_transport=conversation,
        authorization_transport=conversation,
    )
    receipt = make_receipt(
        produced_result.authorization_id, produced_result.approval_id
    )
    kwargs, calls, _state = executor_kwargs(
        conversation, evidence, receipt, dry_run=True
    )
    dry = execute_merge(**kwargs)
    assert dry.status == "dry-run-applicable"
    assert calls["merges"] == []
    kwargs, calls, _state = executor_kwargs(conversation, evidence, receipt)
    live = execute_merge(**kwargs)
    assert live.status == "merged"
    assert live.merge_commit_sha == MERGE_COMMIT
    assert calls["merges"] == [(REPO, PR, HEAD, "merge")]
    # Authorization is consumed: any further dispatch blocks.
    kwargs, calls, _state = executor_kwargs(conversation, evidence, receipt)
    again = execute_merge(**kwargs)
    assert again.status == "blocked"
    assert calls["merges"] == []
