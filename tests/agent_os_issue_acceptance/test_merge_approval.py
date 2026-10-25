"""Tests for the #3463 merge-approval repair (Option A / design A1).

Risk-based, not exhaustive: each test maps to a Phase 6 priority.
Existing suites (approval records, projections, merge authorization,
dispatch) cover the unchanged invariants; these tests cover only
what is new: constructing a merge-specific canonical approval
without synthetic task-planning evidence.

All approval-source interaction in the revocation test is faked
in-memory. No live GitHub call is made by any test here.
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

REPO = "Blummer92/agent-os"
PR = 4000
HEAD = "a" * 40
HEAD2 = "e" * 40
BASE = "b" * 40
DECISION_AT = "2026-07-26T14:00:00Z"
EVALUATED_AT = "2026-07-26T14:10:00Z"
EXPIRES_AT = "2026-07-26T16:00:00Z"


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
    """One in-memory owner-authored approval conversation for revocation tests."""

    def __init__(self) -> None:
        self.approval_comments: list[dict] = []
        self._next_id = 1
        self._clock = 0

    def _stamp(self) -> str:
        self._clock += 1
        return f"2026-07-26T14:{10 + self._clock:02d}:00Z"

    def post_comment(self, *, repository: str, pr_number: int, body: str):
        comment_id = self._next_id
        self._next_id += 1
        entry = {
            "comment_id": comment_id,
            "author_login": "Blummer92",
            "created_at": self._stamp(),
            "body": body,
        }
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




@pytest.mark.parametrize("method,expected", [
    ("merge", "1d370916b7f86e9a575ca5f6a3ab6dc371f8d913eda59e80ba0282b572e112a2"),
    ("squash", "beed5d2be2e601ac51d468c1c04031eda843bc0e44e1284b995038eec5b8afde"),
    ("rebase", "ca65a7d69ef6dfd530eef58f435799a7038a04dce6b797981cbc2c9f9e1582c5"),
])
def test_serialized_triple_preserves_pre_simplification_identity(method, expected):
    # Captured from a6101cc6, independently of the simplified implementation.
    from scripts.agent_os_issue_acceptance.approved_execution_projection import (
        serialize_approved_execution_projection,
    )

    evidence = make_evidence(proposed_merge_method=method)
    approval, applicability, projection = build_merge_approval_triple(
        make_decision(evidence), evidence, evaluated_at=EVALUATED_AT
    )
    payload = (serialize_approval_record(approval)
               + serialize_approval_applicability_result(applicability)
               + serialize_approved_execution_projection(projection))
    assert hashlib.sha256(payload).hexdigest() == expected
