from __future__ import annotations

import ast
import inspect
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.agent_os_issue_acceptance import (  # noqa: E402
    APPROVAL_RECORD_SCHEMA_VERSION,
    MERGE_AUTHORIZATION_SCHEMA_VERSION,
    MERGE_EXECUTION_OBSERVATION_SCHEMA_VERSION,
    ApprovalApplicabilityResult,
    ApprovalBinding,
    ApprovalKind,
    ApprovalRecord,
    ApprovalState,
    ApprovedExecutionProjection,
    HandoffCohort,
    MergeAuthorizationState,
    MergeCheckEvidence,
    MergeReviewEvidence,
    PullRequestMergeEvidence,
    approval_applicability_identity,
    build_merge_authorization_candidate,
    evaluate_merge_authorization_applicability,
    record_approval_decision,
    record_merge_authorization_decision,
    record_merge_execution_observation,
)
from scripts.agent_os_issue_acceptance import merge_authorization  # noqa: E402

HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40
MERGE_SHA = "c" * 40
DIGEST = "1" * 64
PROPOSAL_ID = "draft-task-proposal:" + "2" * 64
ISSUEPLAN_ID = "issueplan-current-state:" + "3" * 64
CREATED_AT = "2026-07-26T14:00:00Z"
AUTHORIZED_AT = "2026-07-26T14:10:00Z"
EXPIRES_AT = "2026-07-26T15:00:00Z"


def _approval_binding(**changes):
    values = {
        "proposal_version": "1.0",
        "proposal_id": PROPOSAL_ID,
        "handoff_digest": "4" * 64,
        "graph_digest": "5" * 64,
        "planning_result_digest": "6" * 64,
        "repository": "blummer92/agent-os",
        "base_branch": "main",
        "evaluated_repository_sha": HEAD_SHA,
        "evaluator_commit_sha": "d" * 40,
        "supplied_node_ids": ("issue-629",),
        "cohort_summaries": (
            HandoffCohort(
                node_ids=("issue-629",),
                classification="parallel-candidate",
                reason_codes=("covered-no-deterministic-conflict",),
            ),
        ),
        "issueplan_current_state_evidence_id": ISSUEPLAN_ID,
        "repository_state_evidence_id": "7" * 64,
        "repository_evidence_type": "branch-head",
        "tested_repository_sha": HEAD_SHA,
        "source_snapshot_fingerprint": "8" * 64,
        "scanner_result_fingerprint": "9" * 64,
        "implementation_contract_fingerprint": DIGEST,
        "allowed_files": ("scripts/agent_os_issue_acceptance/merge_authorization.py",),
        "forbidden_paths": (".github/workflows/**",),
        "required_tests": (
            "python -m pytest tests/agent_os_issue_acceptance/"
            "test_merge_authorization.py -q",
        ),
    }
    values.update(changes)
    return ApprovalBinding(**values)


def _approved(**changes):
    candidate = ApprovalRecord(
        schema_version=APPROVAL_RECORD_SCHEMA_VERSION,
        approval_id="",
        approval_revision="",
        revision_number=1,
        previous_revision=None,
        approval_kind=ApprovalKind.IMPLEMENTATION,
        state=ApprovalState.PENDING,
        binding=_approval_binding(**changes),
        authorizer_id="operator-requester",
        decision_id="approval-request",
        decision_at="2026-07-26T13:50:00Z",
        expires_at="2026-07-26T16:00:00Z",
        supersedes_approval_id=None,
        reason_codes=(),
    )
    return record_approval_decision(
        candidate,
        state=ApprovalState.APPROVED,
        decision_id="approval-decision",
        authorizer_id="repository-owner",
        decision_at=CREATED_AT,
    )


def _applicability(approval=None, **changes):
    approval = approval or _approved()
    values = {
        "status": "applicable",
        "approval_id": approval.approval_id,
        "approval_revision": approval.approval_revision,
        "current_proposal_id": PROPOSAL_ID,
        "reason_codes": (),
        "changed_bindings": (),
        "approval_applicable": True,
        "details": (),
    }
    values.update(changes)
    return ApprovalApplicabilityResult(**values)


def _projection(approval=None, **changes):
    approval = approval or _approved()
    binding = approval.binding
    values = {
        "schema_version": "1.0",
        "projection_id": "",
        "proposal_version": binding.proposal_version,
        "proposal_id": binding.proposal_id,
        "approval_id": approval.approval_id,
        "approval_revision": approval.approval_revision,
        "approval_revision_number": approval.revision_number,
        "approval_kind": approval.approval_kind.value,
        "approval_state": "approved",
        "approval_authorizer_id": approval.authorizer_id,
        "approval_decision_id": approval.decision_id,
        "approval_decision_at": approval.decision_at,
        "approval_expires_at": approval.expires_at,
        "approval_supersedes_id": approval.supersedes_approval_id,
        "handoff_digest": binding.handoff_digest,
        "graph_digest": binding.graph_digest,
        "planning_result_digest": binding.planning_result_digest,
        "repository": binding.repository,
        "base_branch": binding.base_branch,
        "evaluated_repository_sha": binding.evaluated_repository_sha,
        "evaluator_commit_sha": binding.evaluator_commit_sha,
        "tested_repository_sha": binding.tested_repository_sha,
        "repository_evidence_type": binding.repository_evidence_type,
        "supplied_node_ids": binding.supplied_node_ids,
        "cohort_summaries": binding.cohort_summaries,
        "issueplan_current_state_evidence_id": (
            binding.issueplan_current_state_evidence_id
        ),
        "repository_state_evidence_id": binding.repository_state_evidence_id,
        "source_snapshot_fingerprint": binding.source_snapshot_fingerprint,
        "scanner_result_fingerprint": binding.scanner_result_fingerprint,
        "implementation_contract_fingerprint": (
            binding.implementation_contract_fingerprint
        ),
        "allowed_files": binding.allowed_files,
        "forbidden_paths": binding.forbidden_paths,
        "required_tests": binding.required_tests,
        "projected_at": "2026-07-26T14:01:00Z",
    }
    values.update(changes)
    return ApprovedExecutionProjection(**values)


def _check(**changes):
    values = {
        "context": "Agent OS Validation Gate",
        "app_identity": "github-actions",
        "tested_sha": HEAD_SHA,
        "evidence_id": "",
        "state": "success",
    }
    values.update(changes)
    return MergeCheckEvidence(**values)


def _review(**changes):
    values = {
        "blocking_review_present": False,
        "unresolved_conversation_count": 0,
        "exact_head_reviewed": True,
    }
    values.update(changes)
    return MergeReviewEvidence(**values)


def _pr(**changes):
    values = {
        "repository": "blummer92/agent-os",
        "pull_request_number": 630,
        "head_sha": HEAD_SHA,
        "base_branch": "main",
        "base_sha_or_evidence_id": BASE_SHA,
        "draft": False,
        "ready_for_review": True,
        "proposed_merge_method": "squash",
        "changed_scope_fingerprint": DIGEST,
        "allowed_files": (
            "scripts/agent_os_issue_acceptance/merge_authorization.py",
        ),
        "forbidden_paths": (".github/workflows/**",),
        "required_tests": (
            "python -m pytest tests/agent_os_issue_acceptance/"
            "test_merge_authorization.py -q",
        ),
        "required_checks": (_check(),),
        "review_evidence": _review(),
        "evidence_id": "",
    }
    values.update(changes)
    return PullRequestMergeEvidence(**values)


def _candidate(*, approval=None, applicability=None, projection=None, pr=None, **changes):
    approval = approval or _approved()
    applicability = applicability or _applicability(approval)
    projection = projection or _projection(approval)
    pr = pr or _pr()
    values = {
        "authorizer_id": "repository-owner",
        "decision_id": "merge-request",
        "decision_at": "2026-07-26T14:05:00Z",
        "expires_at": EXPIRES_AT,
        "permitted_merge_method": "squash",
    }
    values.update(changes)
    return build_merge_authorization_candidate(
        approval,
        applicability,
        projection,
        pr,
        **values,
    )


def _authorized(**changes):
    candidate = _candidate(**changes)
    return record_merge_authorization_decision(
        candidate,
        state=MergeAuthorizationState.AUTHORIZED,
        decision_id="merge-authorized",
        authorizer_id="repository-owner",
        decision_at=AUTHORIZED_AT,
    )


def _evaluate(
    record,
    *,
    approval=None,
    applicability=None,
    projection=None,
    pr=None,
    at="2026-07-26T14:20:00Z",
    events=(),
):
    approval = approval or _approved()
    applicability = applicability or _applicability(approval)
    projection = projection or _projection(approval)
    pr = pr or _pr()
    return evaluate_merge_authorization_applicability(
        record,
        approval,
        applicability,
        projection,
        pr,
        evaluated_at=at,
        invalidation_events=events,
    )


def test_public_schema_and_state_taxonomy_are_exact():
    assert MERGE_AUTHORIZATION_SCHEMA_VERSION == "1.0"
    assert MERGE_EXECUTION_OBSERVATION_SCHEMA_VERSION == "1.0"
    assert tuple(item.value for item in MergeAuthorizationState) == (
        "pending",
        "authorized",
        "rejected",
        "expired",
        "invalidated",
        "consumed",
        "superseded",
    )


def test_candidate_and_decision_identities_are_deterministic_and_immutable():
    first = _candidate()
    second = _candidate()
    assert first == second
    assert first.authorization_id.startswith("merge-authorization:")
    assert first.authorization_revision.startswith("merge-authorization-revision:")
    assert first.merge_authorized is False
    authorized = _authorized()
    assert authorized.authorization_id == first.authorization_id
    assert authorized.authorization_revision != first.authorization_revision
    assert authorized.merge_authorized is True
    assert authorized.side_effects_performed is False
    with pytest.raises(FrozenInstanceError):
        authorized.state = MergeAuthorizationState.REJECTED


def test_check_and_pr_evidence_ids_are_content_bound_and_order_independent():
    first = _check()
    second = _check()
    assert first == second
    with pytest.raises(ValueError, match="does not match"):
        replace(first, evidence_id="merge-check:" + "0" * 64)
    extra = _check(context="Navigation Registry Offline Tests")
    a = _pr(required_checks=(first, extra))
    b = _pr(required_checks=(extra, first))
    assert a == b
    assert a.evidence_id == b.evidence_id
    with pytest.raises(ValueError, match="unique"):
        _pr(required_checks=(first, first))


@pytest.mark.parametrize(
    "target",
    [
        MergeAuthorizationState.AUTHORIZED,
        MergeAuthorizationState.REJECTED,
        MergeAuthorizationState.INVALIDATED,
        MergeAuthorizationState.SUPERSEDED,
    ],
)
def test_pending_decisions_are_linked_and_deterministic(target):
    candidate = _candidate()
    first = record_merge_authorization_decision(
        candidate,
        state=target,
        decision_id=f"decision-{target.value}",
        authorizer_id="repository-owner",
        decision_at=AUTHORIZED_AT,
    )
    second = record_merge_authorization_decision(
        candidate,
        state=target,
        decision_id=f"decision-{target.value}",
        authorizer_id="repository-owner",
        decision_at=AUTHORIZED_AT,
    )
    assert first == second
    assert first.previous_revision == candidate.authorization_revision
    assert first.revision_number == 2


def test_expiry_boundary_is_exact_and_clock_free():
    authorized = _authorized()
    assert _evaluate(authorized, at="2026-07-26T14:59:59Z").status == "applicable"
    at = _evaluate(authorized, at=EXPIRES_AT)
    after = _evaluate(authorized, at="2026-07-26T15:00:01Z")
    assert at.status == after.status == "stale"
    assert at.reason_codes == ("authorization.expired",)
    expired = record_merge_authorization_decision(
        _candidate(),
        state="expired",
        decision_id="expiry-event",
        authorizer_id="repository-owner",
        decision_at=EXPIRES_AT,
    )
    assert expired.reason_codes == ("authorization.expired",)


def test_green_checks_ready_review_and_mergeability_do_not_create_authorization():
    result = _evaluate(None)
    assert result.status == "blocked"
    assert result.merge_authorized is False
    assert result.reason_codes == ("authorization.pending",)


@pytest.mark.parametrize(
    ("pr", "reason"),
    [
        (_pr(repository="other/repo"), "pull-request.identity-changed"),
        (_pr(pull_request_number=631), "pull-request.identity-changed"),
        (
            _pr(
                head_sha="e" * 40,
                required_checks=(_check(tested_sha="e" * 40),),
            ),
            "pull-request.head-changed",
        ),
        (_pr(base_branch="release"), "pull-request.base-changed"),
        (_pr(base_sha_or_evidence_id="f" * 40), "pull-request.base-changed"),
        (_pr(proposed_merge_method="merge"), "merge.method-changed"),
        (_pr(changed_scope_fingerprint="a" * 64), "contract.scope-changed"),
        (_pr(allowed_files=("other.py",)), "contract.allowlist-changed"),
        (_pr(forbidden_paths=("secrets/**",)), "contract.forbidden-paths-changed"),
        (_pr(required_tests=("other-test",)), "contract.required-tests-changed"),
        (
            _pr(required_checks=(_check(app_identity="other-app"),)),
            "checks.changed",
        ),
        (
            _pr(review_evidence=_review(blocking_review_present=True)),
            "review.blocked",
        ),
        (
            _pr(review_evidence=_review(unresolved_conversation_count=1)),
            "review.unresolved",
        ),
        (
            _pr(review_evidence=_review(exact_head_reviewed=False)),
            "review.head-stale",
        ),
        (
            _pr(draft=True, ready_for_review=False),
            "pull-request.draft",
        ),
    ],
)
def test_material_pull_request_drift_fails_closed(pr, reason):
    result = _evaluate(_authorized(), pr=pr)
    assert result.status != "applicable"
    assert result.merge_authorized is False
    assert reason in result.reason_codes


@pytest.mark.parametrize(
    ("state", "status", "reason"),
    [
        ("pending", "needs-decision", "checks.pending"),
        ("failure", "blocked", "checks.failed"),
        ("cancelled", "blocked", "checks.cancelled"),
        ("skipped", "blocked", "checks.skipped"),
        ("not-triggered", "needs-decision", "checks.not-triggered"),
        ("unknown", "needs-decision", "checks.unknown"),
    ],
)
def test_non_success_check_states_remain_distinct(state, status, reason):
    pr = _pr(required_checks=(_check(state=state),))
    result = _evaluate(_authorized(), pr=pr)
    assert result.status == status
    assert reason in result.reason_codes


def test_missing_check_is_needs_decision_and_duplicate_events_are_stable():
    authorized = _authorized(
        pr=_pr(
            required_checks=(
                _check(),
                _check(context="Navigation Registry Offline Tests"),
            )
        )
    )
    result = _evaluate(
        authorized,
        pr=_pr(),
        events=("checks.changed", "checks.changed", "approval.changed"),
    )
    assert result.status == "needs-decision"
    assert result.reason_codes == tuple(sorted(set(result.reason_codes)))
    assert "checks.missing" in result.reason_codes


def test_approval_projection_and_applicability_drift_fail_closed():
    authorized = _authorized()
    changed_approval = _approved(allowed_files=("other.py",))
    changed_applicability = _applicability(changed_approval)
    changed_projection = _projection(changed_approval)
    result = _evaluate(
        authorized,
        approval=changed_approval,
        applicability=changed_applicability,
        projection=changed_projection,
    )
    assert result.status == "stale"
    assert "approval.changed" in result.reason_codes
    assert "projection.changed" in result.reason_codes

    needs = _applicability(
        status="needs-decision",
        approval_applicable=False,
        reason_codes=("source.inaccessible",),
    )
    result = _evaluate(authorized, applicability=needs)
    assert result.status == "needs-decision"
    assert "approval.needs-decision" in result.reason_codes


def test_false_well_shaped_projection_and_record_ids_fail_closed():
    approval = _approved()
    projection = _projection(approval)
    forged_projection = object.__new__(ApprovedExecutionProjection)
    for item in projection.__dataclass_fields__:
        object.__setattr__(forged_projection, item, getattr(projection, item))
    object.__setattr__(
        forged_projection,
        "projection_id",
        "approved-execution-projection:" + "0" * 64,
    )
    result = _evaluate(_authorized(), projection=forged_projection)
    assert result.status == "invalid"
    assert result.reason_codes == ("evidence.malformed",)

    authorized = _authorized()
    forged_record = object.__new__(type(authorized))
    for item in authorized.__dataclass_fields__:
        object.__setattr__(forged_record, item, getattr(authorized, item))
    object.__setattr__(
        forged_record,
        "authorization_revision",
        "merge-authorization-revision:" + "0" * 64,
    )
    result = _evaluate(forged_record)
    assert result.status == "invalid"


def test_emergency_override_requires_complete_time_bounded_evidence():
    with pytest.raises(ValueError, match="paired"):
        _candidate(emergency_override_reason="urgent")
    with pytest.raises(ValueError, match="time-bounded"):
        _candidate(
            expires_at=None,
            emergency_override_reason="urgent recovery",
            emergency_override_audit_location="audit:629",
        )
    candidate = _candidate(
        emergency_override_reason="urgent recovery",
        emergency_override_audit_location="audit:629",
    )
    assert candidate.emergency_override_reason == "urgent recovery"


def test_merge_observation_requires_matching_applicable_authorization():
    authorized = _authorized()
    applicability = _evaluate(authorized)
    observation = record_merge_execution_observation(
        authorized,
        applicability,
        _pr(),
        observed_merge_commit_sha=MERGE_SHA,
        observed_actor_id="repository-owner",
        observed_at="2026-07-26T14:30:00Z",
        audit_location="github:pull/630",
        observed_merge_method="squash",
        linked_issue_closure_observed=True,
    )
    assert observation.authorization_consumed is True
    assert observation.side_effects_performed is True
    assert observation.observation_id.startswith("merge-execution-observation:")

    with pytest.raises(ValueError, match="does not match"):
        record_merge_execution_observation(
            authorized,
            applicability,
            _pr(),
            observed_merge_commit_sha=MERGE_SHA,
            observed_actor_id="repository-owner",
            observed_at="2026-07-26T14:30:00Z",
            audit_location="github:pull/630",
            observed_merge_method="merge",
        )


def test_consumed_authorization_cannot_replay():
    authorized = _authorized()
    consumed = record_merge_authorization_decision(
        authorized,
        state="consumed",
        decision_id="merge-observed",
        authorizer_id="repository-owner",
        decision_at="2026-07-26T14:31:00Z",
    )
    result = _evaluate(consumed)
    assert result.status == "consumed"
    assert result.merge_authorized is False
    with pytest.raises(ValueError, match="invalid merge authorization transition"):
        record_merge_authorization_decision(
            consumed,
            state="authorized",
            decision_id="replay",
            authorizer_id="repository-owner",
            decision_at="2026-07-26T14:32:00Z",
        )


def test_applicability_identity_is_deterministic_and_content_bound():
    first = _applicability()
    second = _applicability()
    assert approval_applicability_identity(first) == approval_applicability_identity(
        second
    )
    changed = replace(first, status="blocked", approval_applicable=False)
    assert approval_applicability_identity(changed) != approval_applicability_identity(
        first
    )


def test_module_has_no_external_io_or_authority_imports():
    source = inspect.getsource(merge_authorization)
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert imported.isdisjoint(
        {
            "asyncio",
            "httpx",
            "os",
            "pathlib",
            "requests",
            "socket",
            "sqlite3",
            "subprocess",
            "urllib",
        }
    )
    for prohibited in (
        "datetime.now",
        "datetime.utcnow",
        "github",
        "check_run",
        "merge_pull_request",
        "scheduler_execution_concurrency",
    ):
        assert prohibited not in source.lower()
