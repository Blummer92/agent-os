from __future__ import annotations

import ast
import inspect
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEDULER_SRC = ROOT / "08_Tooling/workflow-scheduler/src"
for path in (ROOT, SCHEDULER_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.agent_os_execution_capabilities import (  # noqa: E402
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    WorktreeState,
)
from scripts.agent_os_issue_acceptance import (  # noqa: E402
    MERGE_AUTHORIZATION_SCHEMA_VERSION,
    MERGE_EXECUTION_OBSERVATION_SCHEMA_VERSION,
    ApprovalKind,
    ApprovalState,
    HandoffCohort,
    MergeAuthorizationApplicabilityResult,
    MergeAuthorizationState,
    MergeCheckEvidence,
    MergeReviewEvidence,
    PullRequestMergeEvidence,
    SchedulerPlanningHandoff,
    approval_applicability_identity,
    build_approval_candidate,
    build_approved_execution_projection,
    build_issueplan_current_state_evidence,
    build_merge_authorization_candidate,
    compute_handoff_digest,
    evaluate_approval_applicability,
    evaluate_merge_authorization_applicability,
    record_approval_decision,
    record_merge_authorization_decision,
    record_merge_execution_observation,
)
from scripts.agent_os_issue_acceptance import merge_authorization  # noqa: E402
from scripts.agent_os_issue_acceptance.issueplan_scanner import (  # noqa: E402
    AdoptionClass,
    MetadataCandidate,
    ScanResult,
    SourceEnvelope,
)
from workflow_scheduler.planning import build_draft_task_proposals  # noqa: E402

HEAD = "a" * 40
BASE = "b" * 40
MERGE = "c" * 40
EVALUATOR = "d" * 40
GRAPH = "1" * 64
PLANNING = "2" * 64
CONTRACT = "3" * 64
CREATED = "2026-07-26T14:00:00Z"
APPROVED = "2026-07-26T14:10:00Z"
PROJECTED = "2026-07-26T14:20:00Z"
CANDIDATE = "2026-07-26T14:25:00Z"
AUTHORIZED = "2026-07-26T14:30:00Z"
MERGE_EXPIRES = "2026-07-26T15:00:00Z"
APPROVAL_EXPIRES = "2026-07-26T16:00:00Z"


def _handoff(**changes):
    data = {
        "contract_version": "0.2.0",
        "planning_result_version": "0.1.0",
        "evaluator_commit_sha": EVALUATOR,
        "repository": "blummer92/agent-os",
        "base_branch": "main",
        "evaluated_repository_sha": HEAD,
        "supplied_node_ids": ["issue-629"],
        "graph_digest": GRAPH,
        "planning_result_digest": PLANNING,
        "cohort_summaries": [{
            "node_ids": ["issue-629"],
            "classification": "parallel-candidate",
            "reason_codes": ["covered-no-deterministic-conflict"],
        }],
        "planning_scope": "supplied-graph-only",
        "execution_authorized": False,
        "created_at": "2026-07-26T13:00:00Z",
        "handoff_digest": "0" * 64,
    }
    data.update(changes)
    data["handoff_digest"] = compute_handoff_digest(data)
    return SchedulerPlanningHandoff(
        contract_version=data["contract_version"],
        planning_result_version=data["planning_result_version"],
        evaluator_commit_sha=data["evaluator_commit_sha"],
        repository=data["repository"],
        base_branch=data["base_branch"],
        evaluated_repository_sha=data["evaluated_repository_sha"],
        supplied_node_ids=tuple(data["supplied_node_ids"]),
        graph_digest=data["graph_digest"],
        planning_result_digest=data["planning_result_digest"],
        cohort_summaries=tuple(HandoffCohort(**item) for item in data["cohort_summaries"]),
        created_at=data["created_at"],
        handoff_digest=data["handoff_digest"],
    )


def _issueplan(handoff, **changes):
    scan = ScanResult(
        source_locator="github:Blummer92/agent-os#629",
        source_revision="rev-1",
        findings=(),
        adoption_class=AdoptionClass.STRICT_NATIVE,
        candidates=(MetadataCandidate(1, "raw", {
            "profile_version": "issueplan-core/v1",
            "entity_id": "issue-629",
            "revision": "rev-1",
            "owner_agent": "Integration Manager",
            "required_files": ["scripts/agent_os_issue_acceptance/merge_authorization.py"],
        }),),
        strict_valid=True,
        execution_authorized=False,
        evidence=("bounded=true",),
    )
    envelope = SourceEnvelope(
        source_locator="github:Blummer92/agent-os#629",
        source_revision="rev-1",
        content="issue body",
        retrieval_complete=True,
        pagination_complete=True,
        accessible=True,
        source_family="github-issue",
    )
    values = {
        "repository": handoff.repository,
        "base_branch": handoff.base_branch,
        "evaluated_repository_sha": handoff.evaluated_repository_sha,
        "implementation_contract_fingerprint": CONTRACT,
        "allowed_files": ("scripts/agent_os_issue_acceptance/merge_authorization.py",),
        "forbidden_paths": (".github/workflows/**",),
        "required_tests": ("python -m pytest tests/agent_os_issue_acceptance/test_merge_authorization.py -q",),
        "graph_reference": handoff.graph_digest,
        "planning_result_reference": handoff.planning_result_digest,
        "handoff_reference": handoff.handoff_digest,
        "supplied_node_ids": handoff.supplied_node_ids,
    }
    values.update(changes)
    return build_issueplan_current_state_evidence(
        envelope,
        scan,
        observed_at="2026-07-26T13:30:00Z",
        freshness_boundary="main@5011d996",
        **values,
    )


def _repo(*, head=HEAD, tested=HEAD, contract=CONTRACT):
    return RepositoryStateEvidence(
        schema_name=CAPABILITY_EVIDENCE_SCHEMA_NAME,
        evidence_schema_version=CAPABILITY_EVIDENCE_SCHEMA_VERSION,
        producer_adapter="fixture-adapter",
        producer_adapter_version="1.0",
        correlation_id="issue-629",
        repository_identity=RepositoryIdentity(
            host="github.com", owner="blummer92", repository="agent-os",
            repository_id=123, default_branch="main",
        ),
        base_ref="main", base_sha=BASE,
        head_ref="agent/629-content-bound-merge-authorization", head_sha=head,
        requested_ref="agent/629-content-bound-merge-authorization", requested_sha=head,
        observed_sha=tested, tested_sha=tested, pushed_sha=head,
        proposed_pr_sha=head, synthetic_merge_sha=None, external_build_sha=tested,
        evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        contract_fingerprint=contract,
        worktree_state=WorktreeState.CLEAN,
        worktree_reason_codes=(),
        observed_at="2026-07-26T13:45:00Z",
        freshness_boundary="workflow-run-629",
    )


def _bundle(*, approval_expires=APPROVAL_EXPIRES):
    handoff = _handoff()
    issueplan = _issueplan(handoff)
    repository = _repo()
    proposals = build_draft_task_proposals(handoff, issueplan, repository, created_at=CREATED)
    assert proposals.status == "eligible"
    proposal = proposals.proposals[0]
    candidate = build_approval_candidate(
        proposal, issueplan, repository,
        approval_kind=ApprovalKind.IMPLEMENTATION,
        authorizer_id="operator-requester", decision_id="approval-request",
        decision_at=CREATED, expires_at=approval_expires,
    )
    approval = record_approval_decision(
        candidate, state=ApprovalState.APPROVED,
        decision_id="approval-decision", authorizer_id="repository-owner",
        decision_at=APPROVED,
    )
    applicability = evaluate_approval_applicability(
        approval, proposal, issueplan, repository, evaluated_at=PROJECTED,
    )
    projection_result = build_approved_execution_projection(
        proposal, approval, applicability, issueplan, repository, projected_at=PROJECTED,
    )
    assert applicability.status == "applicable"
    assert projection_result.status == "complete" and projection_result.projection
    return approval, applicability, projection_result.projection, proposal, issueplan, repository


def _check(**changes):
    values = dict(context="Agent OS Validation Gate", app_identity="github-actions",
                  tested_sha=HEAD, evidence_id="", state="success")
    values.update(changes)
    return MergeCheckEvidence(**values)


def _review(**changes):
    values = dict(blocking_review_present=False, unresolved_conversation_count=0,
                  exact_head_reviewed=True)
    values.update(changes)
    return MergeReviewEvidence(**values)


def _pr(bundle=None, **changes):
    bundle = bundle or _bundle()
    projection = bundle[2]
    values = dict(
        repository=projection.repository, pull_request_number=630,
        head_sha=projection.tested_repository_sha, base_branch=projection.base_branch,
        base_sha_or_evidence_id=BASE, draft=False, ready_for_review=True,
        proposed_merge_method="squash", changed_scope_fingerprint=CONTRACT,
        allowed_files=projection.allowed_files, forbidden_paths=projection.forbidden_paths,
        required_tests=projection.required_tests,
        required_checks=(_check(tested_sha=projection.tested_repository_sha),),
        review_evidence=_review(), evidence_id="",
    )
    values.update(changes)
    return PullRequestMergeEvidence(**values)


def _candidate(bundle=None, pr=None, **changes):
    bundle = bundle or _bundle()
    approval, applicability, projection, proposal, issueplan, repository = bundle
    values = dict(
        current_proposal=proposal, current_issueplan_evidence=issueplan,
        current_repository_state_evidence=repository,
        authorizer_id="repository-owner", decision_id="merge-request",
        decision_at=CANDIDATE, expires_at=MERGE_EXPIRES,
        permitted_merge_method="squash",
    )
    values.update(changes)
    return build_merge_authorization_candidate(
        approval, applicability, projection, pr or _pr(bundle), **values,
    )


def _authorized(bundle=None, **changes):
    bundle = bundle or _bundle()
    record = record_merge_authorization_decision(
        _candidate(bundle, **changes), state="authorized",
        decision_id="merge-authorized", authorizer_id="repository-owner",
        decision_at=AUTHORIZED,
    )
    return record, bundle


def _evaluate(record, bundle=None, pr=None, at="2026-07-26T14:40:00Z", events=()):
    bundle = bundle or _bundle()
    approval, applicability, projection, proposal, issueplan, repository = bundle
    return evaluate_merge_authorization_applicability(
        record, approval, applicability, projection, pr or _pr(bundle),
        current_proposal=proposal, current_issueplan_evidence=issueplan,
        current_repository_state_evidence=repository,
        evaluated_at=at, invalidation_events=events,
    )


def test_public_schema_state_and_canonical_end_to_end_path():
    assert MERGE_AUTHORIZATION_SCHEMA_VERSION == "1.0"
    assert MERGE_EXECUTION_OBSERVATION_SCHEMA_VERSION == "1.0"
    assert tuple(item.value for item in MergeAuthorizationState) == (
        "pending", "authorized", "rejected", "expired", "invalidated",
        "consumed", "superseded",
    )
    authorized, bundle = _authorized()
    result = _evaluate(authorized, bundle)
    assert result.status == "applicable" and result.merge_authorized
    assert authorized.binding.approval_applicability_identity == approval_applicability_identity(bundle[1])
    assert authorized.binding.approved_execution_projection_id == bundle[2].projection_id


def test_determinism_immutability_and_content_bound_evidence():
    bundle = _bundle()
    assert _candidate(bundle) == _candidate(bundle)
    authorized, _ = _authorized(bundle)
    assert authorized.authorization_id == _candidate(bundle).authorization_id
    with pytest.raises(FrozenInstanceError):
        authorized.state = MergeAuthorizationState.REJECTED
    check = _check()
    with pytest.raises(ValueError, match="does not match"):
        replace(check, evidence_id="merge-check:" + "0" * 64)
    extra = _check(context="Navigation Registry Offline Tests")
    assert _pr(bundle, required_checks=(check, extra)) == _pr(bundle, required_checks=(extra, check))


def test_fabricated_applicability_and_recomputed_forged_projection_fail():
    bundle = _bundle()
    approval, applicability, projection, proposal, issueplan, repository = bundle
    fabricated = replace(applicability, current_proposal_id="draft-task-proposal:" + "f" * 64)
    with pytest.raises(ValueError, match="approval.changed"):
        build_merge_authorization_candidate(
            approval, fabricated, projection, _pr(bundle),
            current_proposal=proposal, current_issueplan_evidence=issueplan,
            current_repository_state_evidence=repository,
            authorizer_id="repository-owner", decision_id="fabricated",
            decision_at=CANDIDATE, expires_at=MERGE_EXPIRES,
        )
    forged = replace(projection, projection_id="", tested_repository_sha="e" * 40)
    forged_pr = _pr(bundle, head_sha="e" * 40, required_checks=(_check(tested_sha="e" * 40),))
    with pytest.raises(ValueError, match="projection.changed"):
        build_merge_authorization_candidate(
            approval, applicability, forged, forged_pr,
            current_proposal=proposal, current_issueplan_evidence=issueplan,
            current_repository_state_evidence=repository,
            authorizer_id="repository-owner", decision_id="forged",
            decision_at=CANDIDATE, expires_at=MERGE_EXPIRES,
        )


@pytest.mark.parametrize("change", [
    {"proposal_id": "draft-task-proposal:" + "f" * 64},
    {"repository": "other/repo"}, {"base_branch": "release"},
    {"evaluated_repository_sha": "e" * 40},
    {"source_snapshot_fingerprint": "e" * 64},
    {"scanner_result_fingerprint": "e" * 64},
    {"implementation_contract_fingerprint": "e" * 64},
    {"allowed_files": ("other.py",)}, {"forbidden_paths": ("secrets/**",)},
    {"required_tests": ("other-test",)},
])
def test_copied_approval_ids_do_not_transfer_through_self_consistent_projection(change):
    bundle = _bundle()
    forged = replace(bundle[2], projection_id="", **change)
    with pytest.raises(ValueError, match="projection.changed"):
        build_merge_authorization_candidate(
            bundle[0], bundle[1], forged, _pr(bundle),
            current_proposal=bundle[3], current_issueplan_evidence=bundle[4],
            current_repository_state_evidence=bundle[5],
            authorizer_id="repository-owner", decision_id="forged-projection",
            decision_at=CANDIDATE, expires_at=MERGE_EXPIRES,
        )


def test_changed_nodes_and_cohorts_do_not_transfer():
    bundle = _bundle()
    forged = replace(
        bundle[2], projection_id="", supplied_node_ids=("issue-999",),
        cohort_summaries=(HandoffCohort(
            node_ids=("issue-999",), classification="parallel-candidate",
            reason_codes=("covered-no-deterministic-conflict",),
        ),),
    )
    with pytest.raises(ValueError, match="projection.changed"):
        build_merge_authorization_candidate(
            bundle[0], bundle[1], forged, _pr(bundle),
            current_proposal=bundle[3], current_issueplan_evidence=bundle[4],
            current_repository_state_evidence=bundle[5],
            authorizer_id="repository-owner", decision_id="forged-nodes",
            decision_at=CANDIDATE, expires_at=MERGE_EXPIRES,
        )


def test_expiry_is_mandatory_bounded_by_approval_and_exact_at_evaluation():
    bundle = _bundle(approval_expires="2026-07-26T14:50:00Z")
    with pytest.raises(ValueError, match="requires expires_at"):
        _candidate(bundle, expires_at=None)
    with pytest.raises(ValueError, match="cannot outlive approval"):
        _candidate(bundle, expires_at="2026-07-26T14:55:00Z")
    candidate = _candidate(bundle, expires_at="2026-07-26T14:50:00Z")
    authorized = record_merge_authorization_decision(
        candidate, state="authorized", decision_id="authorized",
        authorizer_id="repository-owner", decision_at="2026-07-26T14:49:59Z",
    )
    assert _evaluate(authorized, bundle, at="2026-07-26T14:49:59Z").status == "applicable"
    at = _evaluate(authorized, bundle, at="2026-07-26T14:50:00Z")
    assert at.status == "stale" and "approval.expired" in at.reason_codes


def test_candidate_and_decision_at_approval_expiry_fail():
    bundle = _bundle(approval_expires=CANDIDATE)
    with pytest.raises(ValueError, match="canonical eligible evidence"):
        _candidate(bundle, expires_at=CANDIDATE)
    bundle = _bundle(approval_expires="2026-07-26T14:50:00Z")
    candidate = _candidate(bundle, expires_at="2026-07-26T14:50:00Z")
    with pytest.raises(ValueError, match="before expires_at"):
        record_merge_authorization_decision(
            candidate, state="authorized", decision_id="late",
            authorizer_id="repository-owner", decision_at="2026-07-26T14:50:00Z",
        )


def test_observation_returns_linked_consumed_successor_and_prevents_replay():
    authorized, bundle = _authorized()
    applicable = _evaluate(authorized, bundle)
    kwargs = dict(
        observed_merge_commit_sha=MERGE, observed_actor_id="repository-owner",
        observed_at="2026-07-26T14:45:00Z", audit_location="github:pull/630",
        observed_merge_method="squash",
    )
    first = record_merge_execution_observation(authorized, applicable, _pr(bundle), **kwargs)
    second = record_merge_execution_observation(authorized, applicable, _pr(bundle), **kwargs)
    assert first == second
    observation, consumed = first
    assert consumed.state is MergeAuthorizationState.CONSUMED
    assert consumed.consumed_observation_id == observation.observation_id
    assert _evaluate(consumed, bundle).status == "consumed"
    with pytest.raises(ValueError, match="authorized current revision"):
        record_merge_execution_observation(consumed, applicable, _pr(bundle), **kwargs)
    with pytest.raises(ValueError, match="invalid merge authorization transition"):
        record_merge_authorization_decision(
            authorized, state="consumed", decision_id="manual",
            authorizer_id="repository-owner", decision_at=kwargs["observed_at"],
        )


def test_observation_rejects_expired_approval_and_mismatched_method():
    bundle = _bundle(approval_expires="2026-07-26T14:50:00Z")
    candidate = _candidate(bundle, expires_at="2026-07-26T14:50:00Z")
    authorized = record_merge_authorization_decision(
        candidate, state="authorized", decision_id="authorized",
        authorizer_id="repository-owner", decision_at="2026-07-26T14:49:00Z",
    )
    applicable = _evaluate(authorized, bundle, at="2026-07-26T14:49:30Z")
    with pytest.raises(ValueError, match="expired"):
        record_merge_execution_observation(
            authorized, applicable, _pr(bundle), observed_merge_commit_sha=MERGE,
            observed_actor_id="repository-owner", observed_at="2026-07-26T14:50:00Z",
            audit_location="github:pull/630", observed_merge_method="squash",
        )
    authorized, bundle = _authorized()
    with pytest.raises(ValueError, match="does not match"):
        record_merge_execution_observation(
            authorized, _evaluate(authorized, bundle), _pr(bundle),
            observed_merge_commit_sha=MERGE, observed_actor_id="repository-owner",
            observed_at="2026-07-26T14:45:00Z", audit_location="github:pull/630",
            observed_merge_method="merge",
        )


@pytest.mark.parametrize(("state", "status", "reason"), [
    ("pending", "needs-decision", "checks.pending"),
    ("failure", "blocked", "checks.failed"),
    ("cancelled", "blocked", "checks.cancelled"),
    ("skipped", "blocked", "checks.skipped"),
    ("not-triggered", "needs-decision", "checks.not-triggered"),
    ("unknown", "needs-decision", "checks.unknown"),
])
def test_non_success_check_states_remain_distinct(state, status, reason):
    authorized, bundle = _authorized()
    result = _evaluate(authorized, bundle, _pr(bundle, required_checks=(_check(state=state),)))
    assert result.status == status and reason in result.reason_codes


@pytest.mark.parametrize(("change", "reason"), [
    ({"repository": "other/repo"}, "pull-request.identity-changed"),
    ({"pull_request_number": 631}, "pull-request.identity-changed"),
    ({"base_branch": "release"}, "pull-request.base-changed"),
    ({"base_sha_or_evidence_id": "f" * 40}, "pull-request.base-changed"),
    ({"proposed_merge_method": "merge"}, "merge.method-changed"),
    ({"changed_scope_fingerprint": "e" * 64}, "contract.scope-changed"),
    ({"allowed_files": ("other.py",)}, "contract.allowlist-changed"),
    ({"review_evidence": _review(blocking_review_present=True)}, "review.blocked"),
    ({"draft": True, "ready_for_review": False}, "pull-request.draft"),
])
def test_material_pr_drift_fails_closed(change, reason):
    authorized, bundle = _authorized()
    result = _evaluate(authorized, bundle, _pr(bundle, **change))
    assert not result.merge_authorized and reason in result.reason_codes


def test_missing_check_and_duplicate_reason_inputs_are_stable():
    bundle = _bundle()
    candidate = _candidate(bundle, pr=_pr(bundle, required_checks=(
        _check(), _check(context="Navigation Registry Offline Tests"),
    )))
    authorized = record_merge_authorization_decision(
        candidate, state="authorized", decision_id="authorized",
        authorizer_id="repository-owner", decision_at=AUTHORIZED,
    )
    result = _evaluate(authorized, bundle, events=("checks.changed", "checks.changed"))
    assert result.status == "needs-decision" and "checks.missing" in result.reason_codes
    assert result.reason_codes == tuple(sorted(set(result.reason_codes)))


@pytest.mark.parametrize(("field", "value"), [
    ("repository", " / "), ("base_branch", "   "),
    ("base_sha_or_evidence_id", "not-an-identity"),
])
def test_pr_identity_validation_is_canonical(field, value):
    with pytest.raises(ValueError):
        _pr(**{field: value})


@pytest.mark.parametrize(("field", "value"), [
    ("authorizer_id", "   "), ("decision_id", "   "),
])
def test_candidate_identity_validation_rejects_whitespace(field, value):
    with pytest.raises(ValueError):
        _candidate(**{field: value})


def test_applicable_result_requires_exact_identifiers_and_no_drift():
    with pytest.raises(ValueError, match="exact identifiers"):
        MergeAuthorizationApplicabilityResult(
            status="applicable", authorization_id=None, authorization_revision=None,
            current_pull_request_evidence_id=None, changed_bindings=(), reason_codes=(),
            merge_authorized=True,
        )


def test_module_has_no_external_io_or_authority_imports():
    source = inspect.getsource(merge_authorization)
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert imported.isdisjoint({
        "asyncio", "httpx", "os", "pathlib", "requests", "socket",
        "sqlite3", "subprocess", "urllib",
    })
    assert all(token not in source.lower() for token in (
        "datetime.now", "datetime.utcnow", "merge_pull_request",
        "scheduler_execution_concurrency",
    ))


# --- NO-GO repair: state/reason invariants and bounded diagnostics -----------

BLOCKING_REASONS = [
    ("checks.failed",), ("checks.pending",), ("checks.missing",),
    ("approval.not-applicable",), ("evidence.malformed",),
    ("authorization.rejected",), ("checks.failed", "review.blocked"),
    ("review.unresolved",), ("projection.incomplete",),
]


@pytest.mark.parametrize("reasons", BLOCKING_REASONS)
def test_authorized_revision_rejects_every_non_empty_reason_code_set(reasons):
    with pytest.raises(ValueError, match="cannot carry"):
        record_merge_authorization_decision(
            _candidate(), state="authorized", decision_id="contradiction",
            authorizer_id="repository-owner", decision_at=AUTHORIZED,
            reason_codes=reasons,
        )


def test_valid_authorized_revision_is_exactly_empty_reasons_and_merge_authorized():
    authorized, _ = _authorized()
    assert authorized.state is MergeAuthorizationState.AUTHORIZED
    assert authorized.reason_codes == ()
    assert authorized.merge_authorized is True


def test_pending_candidate_rejects_reason_codes():
    candidate = _candidate()
    assert candidate.state is MergeAuthorizationState.PENDING
    assert candidate.reason_codes == () and candidate.merge_authorized is False
    with pytest.raises(ValueError, match="cannot carry reason codes"):
        replace(candidate, authorization_revision="", reason_codes=("checks.failed",))


def test_rejected_revision_requires_at_least_one_reason():
    with pytest.raises(ValueError, match="requires at least one reason"):
        record_merge_authorization_decision(
            _candidate(), state="rejected", decision_id="no-reason",
            authorizer_id="repository-owner", decision_at=AUTHORIZED,
        )
    rejected = record_merge_authorization_decision(
        _candidate(), state="rejected", decision_id="explained",
        authorizer_id="repository-owner", decision_at=AUTHORIZED,
        reason_codes=("checks.failed",),
    )
    assert rejected.reason_codes == ("checks.failed",)
    assert rejected.merge_authorized is False


@pytest.mark.parametrize(("state", "at", "required"), [
    ("expired", "2026-07-26T15:05:00Z", "authorization.expired"),
    ("invalidated", AUTHORIZED, "authorization.invalidated"),
    ("superseded", AUTHORIZED, "authorization.superseded"),
])
def test_lifecycle_states_carry_only_their_required_reason(state, at, required):
    record = record_merge_authorization_decision(
        _candidate(), state=state, decision_id=f"to-{state}",
        authorizer_id="repository-owner", decision_at=at,
    )
    assert record.state.value == state
    assert required in record.reason_codes
    assert record.merge_authorized is False


def test_invalidated_preserves_revocation_and_consumed_preserves_observation():
    invalidated = record_merge_authorization_decision(
        _candidate(), state="invalidated", decision_id="revoke",
        authorizer_id="repository-owner", decision_at=AUTHORIZED,
    )
    assert invalidated.revoked_authorization_id == invalidated.authorization_id
    assert "authorization.invalidated" in invalidated.reason_codes

    bundle = _bundle()
    authorized, _ = _authorized(bundle)
    _, consumed = record_merge_execution_observation(
        authorized, _evaluate(authorized, bundle), _pr(bundle),
        observed_merge_commit_sha=MERGE, observed_actor_id="repository-owner",
        observed_at="2026-07-26T14:45:00Z", audit_location="audit://merge/630",
        observed_merge_method="squash",
    )
    assert consumed.state is MergeAuthorizationState.CONSUMED
    assert consumed.consumed_observation_id is not None
    assert "authorization.consumed" in consumed.reason_codes
    assert consumed.merge_authorized is False


@pytest.mark.parametrize("reasons", [
    ("authorization.expired", "authorization.consumed"),
    ("authorization.invalidated",),
    ("authorization.superseded",),
    ("authorization.pending",),
])
def test_contradictory_lifecycle_reasons_fail_closed(reasons):
    rejected = record_merge_authorization_decision(
        _candidate(), state="rejected", decision_id="explained",
        authorizer_id="repository-owner", decision_at=AUTHORIZED,
        reason_codes=("checks.failed",),
    )
    with pytest.raises(ValueError):
        replace(rejected, authorization_revision="", reason_codes=reasons)


def test_no_non_authorized_state_reports_merge_authorized():
    records = [_candidate()]
    for state, at in (("rejected", AUTHORIZED), ("expired", "2026-07-26T15:05:00Z"),
                      ("invalidated", AUTHORIZED), ("superseded", AUTHORIZED)):
        records.append(record_merge_authorization_decision(
            _candidate(), state=state, decision_id=f"to-{state}",
            authorizer_id="repository-owner", decision_at=at,
            reason_codes=("checks.failed",) if state == "rejected" else (),
        ))
    for record in records:
        assert record.merge_authorized is (
            record.state is MergeAuthorizationState.AUTHORIZED
        )
        assert record.merge_authorized is False


def test_applicability_cannot_ignore_contradictory_record_local_reasons():
    bundle = _bundle()
    authorized, _ = _authorized(bundle)
    assert _evaluate(authorized, bundle).merge_authorized is True
    # Controlled hostile boundary: inject reasons past the corrected
    # constructor without adding any production construction path.
    object.__setattr__(authorized, "reason_codes", ("checks.failed",))
    result = _evaluate(authorized, bundle)
    assert result.status == "invalid" and result.merge_authorized is False
    assert "evidence.malformed" in result.reason_codes
    local = merge_authorization._record_local_reasons(authorized)
    assert {"checks.failed", "evidence.malformed"} <= local


def test_public_details_are_bounded_sanitized_and_deterministic():
    class Hostile:
        def __str__(self):
            return "SENTINEL-SECRET-" + "x" * 100_000
        __repr__ = __str__

    values = ["ok", Hostile(), "SENTINEL-SECRET-" * 2_000, "ctrl\x00\x07here"]
    details = merge_authorization._details(values)
    assert details == merge_authorization._details(values)
    assert details[1] == "<Hostile>"
    assert "\x00" not in details[3] and "\x07" not in details[3]
    assert all(len(item.encode("utf-8")) <= merge_authorization._MAX_DETAIL_BYTES
               for item in details)

    many = merge_authorization._details(f"detail-{index}" for index in range(500))
    assert len(many) == merge_authorization._MAX_DETAILS
    assert many[-1] == merge_authorization._DETAILS_TRUNCATED


def test_exception_details_never_propagate_message_text():
    try:
        raise ValueError("token=ghp_SENTINELSECRETVALUE must not leak")
    except ValueError as exc:
        detail = merge_authorization._exception_detail("current-evidence", exc)
    assert detail == "current-evidence:ValueError"
    assert "SENTINELSECRET" not in detail

    bundle = _bundle()
    authorized, _ = _authorized(bundle)
    object.__setattr__(authorized, "reason_codes", ("checks.failed",))
    result = _evaluate(authorized, bundle)
    assert all("SENTINELSECRET" not in item for item in result.details)
    assert all(len(item.encode("utf-8")) <= merge_authorization._MAX_DETAIL_BYTES
               for item in result.details)
    assert len(result.details) <= merge_authorization._MAX_DETAILS
