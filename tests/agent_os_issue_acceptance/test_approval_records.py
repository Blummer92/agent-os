from __future__ import annotations

import ast
import inspect
import socket
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(SCHEDULER_SRC) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_SRC))

from scripts.agent_os_execution_capabilities import (  # noqa: E402
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    WorktreeState,
)
from scripts.agent_os_issue_acceptance import (  # noqa: E402
    APPROVAL_RECORD_SCHEMA_VERSION,
    ApprovalKind,
    ApprovalRecord,
    ApprovalState,
    HandoffCohort,
    SchedulerPlanningHandoff,
    build_approval_candidate,
    build_issueplan_current_state_evidence,
    compute_handoff_digest,
    evaluate_approval_applicability,
    record_approval_decision,
)
from scripts.agent_os_issue_acceptance import approval_records  # noqa: E402
from scripts.agent_os_issue_acceptance.issueplan_scanner import (  # noqa: E402
    AdoptionClass,
    MetadataCandidate,
    ScanFinding,
    ScanResult,
    SourceEnvelope,
)
from workflow_scheduler.planning import build_draft_task_proposals  # noqa: E402

HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40
EVALUATOR_SHA = "d" * 40
GRAPH_DIGEST = "1" * 64
PLANNING_DIGEST = "2" * 64
CONTRACT_DIGEST = "3" * 64
CREATED_AT = "2026-07-20T12:00:00Z"
APPROVED_AT = "2026-07-20T12:10:00Z"
EXPIRES_AT = "2026-07-20T13:00:00Z"


def _handoff(**changes):
    payload = {
        "contract_version": "0.2.0",
        "planning_result_version": "0.1.0",
        "evaluator_commit_sha": EVALUATOR_SHA,
        "repository": "blummer92/agent-os",
        "base_branch": "main",
        "evaluated_repository_sha": HEAD_SHA,
        "supplied_node_ids": ["issue-398"],
        "graph_digest": GRAPH_DIGEST,
        "planning_result_digest": PLANNING_DIGEST,
        "cohort_summaries": [
            {
                "node_ids": ["issue-398"],
                "classification": "parallel-candidate",
                "reason_codes": ["covered-no-deterministic-conflict"],
            }
        ],
        "planning_scope": "supplied-graph-only",
        "execution_authorized": False,
        "created_at": "2026-07-20T11:00:00Z",
        "handoff_digest": "0" * 64,
    }
    payload.update(changes)
    payload["handoff_digest"] = compute_handoff_digest(payload)
    return SchedulerPlanningHandoff(
        contract_version=payload["contract_version"],
        planning_result_version=payload["planning_result_version"],
        evaluator_commit_sha=payload["evaluator_commit_sha"],
        repository=payload["repository"],
        base_branch=payload["base_branch"],
        evaluated_repository_sha=payload["evaluated_repository_sha"],
        supplied_node_ids=tuple(payload["supplied_node_ids"]),
        graph_digest=payload["graph_digest"],
        planning_result_digest=payload["planning_result_digest"],
        cohort_summaries=tuple(
            HandoffCohort(**item) for item in payload["cohort_summaries"]
        ),
        created_at=payload["created_at"],
        handoff_digest=payload["handoff_digest"],
    )


def _issueplan(
    handoff,
    *,
    revision="rev-1",
    findings=(),
    adoption=AdoptionClass.STRICT_NATIVE,
    retrieval_complete=True,
    pagination_complete=True,
    accessible=True,
    **changes,
):
    candidate = MetadataCandidate(
        1,
        "raw",
        {
            "profile_version": "issueplan-core/v1",
            "entity_id": "issue-398",
            "revision": revision,
            "owner_agent": "Integration Manager",
            "required_files": [
                "scripts/agent_os_issue_acceptance/approval_records.py"
            ],
        },
    )
    scan = ScanResult(
        source_locator="github:Blummer92/agent-os#398",
        source_revision=revision,
        findings=findings,
        adoption_class=adoption,
        candidates=(candidate,),
        strict_valid=True,
        execution_authorized=False,
        evidence=("bounded=true",),
    )
    envelope = SourceEnvelope(
        source_locator="github:Blummer92/agent-os#398",
        source_revision=revision,
        content="issue body",
        retrieval_complete=retrieval_complete,
        pagination_complete=pagination_complete,
        accessible=accessible,
        source_family="github-issue",
    )
    values = {
        "repository": handoff.repository,
        "base_branch": handoff.base_branch,
        "evaluated_repository_sha": handoff.evaluated_repository_sha,
        "implementation_contract_fingerprint": CONTRACT_DIGEST,
        "allowed_files": (
            "scripts/agent_os_issue_acceptance/approval_records.py",
        ),
        "forbidden_paths": (".github/workflows/**",),
        "required_tests": (
            "python -m pytest tests/agent_os_issue_acceptance/"
            "test_approval_records.py -q",
        ),
        "graph_reference": handoff.graph_digest,
        "planning_result_reference": handoff.planning_result_digest,
        "handoff_reference": handoff.handoff_digest,
        "supplied_node_ids": handoff.supplied_node_ids,
    }
    values.update(changes)
    return build_issueplan_current_state_evidence(
        envelope,
        scan,
        observed_at="2026-07-20T11:30:00Z",
        freshness_boundary="main@4c1b548a",
        **values,
    )


def _repository_state(
    *,
    head_sha=HEAD_SHA,
    requested_sha=HEAD_SHA,
    tested_sha=HEAD_SHA,
    contract_fingerprint=CONTRACT_DIGEST,
    synthetic=False,
    worktree=WorktreeState.CLEAN,
):
    return RepositoryStateEvidence(
        schema_name=CAPABILITY_EVIDENCE_SCHEMA_NAME,
        evidence_schema_version=CAPABILITY_EVIDENCE_SCHEMA_VERSION,
        producer_adapter="fixture-adapter",
        producer_adapter_version="1.0",
        correlation_id="issue-398",
        repository_identity=RepositoryIdentity(
            host="github.com",
            owner="blummer92",
            repository="agent-os",
            repository_id=123,
            default_branch="main",
        ),
        base_ref="main",
        base_sha=BASE_SHA,
        head_ref="agent/idb2b-approval-records",
        head_sha=head_sha,
        requested_ref="agent/idb2b-approval-records",
        requested_sha=requested_sha,
        observed_sha=tested_sha,
        tested_sha=tested_sha,
        pushed_sha=head_sha,
        proposed_pr_sha=head_sha,
        synthetic_merge_sha=tested_sha if synthetic else None,
        external_build_sha=tested_sha,
        evidence_type=(
            RepositoryEvidenceType.SYNTHETIC_PR_MERGE
            if synthetic
            else RepositoryEvidenceType.BRANCH_HEAD
        ),
        contract_fingerprint=contract_fingerprint,
        worktree_state=worktree,
        worktree_reason_codes=(
            ("worktree.dirty",) if worktree is WorktreeState.DIRTY else ()
        ),
        observed_at="2026-07-20T11:45:00Z",
        freshness_boundary="workflow-run-1",
    )


def _inputs(*, handoff=None, issueplan=None, repository=None, created_at=CREATED_AT):
    handoff = handoff or _handoff()
    issueplan = issueplan or _issueplan(handoff)
    repository = repository or _repository_state(
        head_sha=handoff.evaluated_repository_sha,
        requested_sha=handoff.evaluated_repository_sha,
    )
    result = build_draft_task_proposals(
        handoff,
        issueplan,
        repository,
        created_at=created_at,
    )
    assert result.status == "eligible"
    return result.proposals[0], issueplan, repository


def _candidate(
    *, kind=ApprovalKind.IMPLEMENTATION, expires_at=EXPIRES_AT, **inputs
):
    proposal, issueplan, repository = _inputs(**inputs)
    candidate = build_approval_candidate(
        proposal,
        issueplan,
        repository,
        approval_kind=kind,
        authorizer_id="operator-1",
        decision_id="request-1",
        decision_at=CREATED_AT,
        expires_at=expires_at,
    )
    return candidate, proposal, issueplan, repository


def _approved(**kwargs):
    candidate, proposal, issueplan, repository = _candidate(**kwargs)
    approved = record_approval_decision(
        candidate,
        state=ApprovalState.APPROVED,
        decision_id="decision-approve-1",
        authorizer_id="operator-2",
        decision_at=APPROVED_AT,
    )
    return approved, proposal, issueplan, repository


def test_public_taxonomy_and_schema_are_exact():
    assert APPROVAL_RECORD_SCHEMA_VERSION == "1.0"
    assert tuple(item.value for item in ApprovalKind) == (
        "implementation",
        "source-mutation",
        "repair",
        "publication",
    )
    assert tuple(item.value for item in ApprovalState) == (
        "pending",
        "approved",
        "rejected",
        "expired",
        "invalidated",
        "superseded",
    )


@pytest.mark.parametrize("kind", tuple(ApprovalKind))
def test_each_approval_kind_is_distinct_and_deterministic(kind):
    first, *_ = _candidate(kind=kind)
    second, *_ = _candidate(kind=kind)
    assert first == second
    assert first.approval_kind == kind
    assert first.approval_id.startswith("approval:")
    assert first.approval_revision.startswith("approval-revision:")
    assert first.execution_authorized is False
    assert first.side_effects_performed is False


def test_candidate_identity_excludes_proposal_timestamp_but_includes_expiry():
    first, *_ = _candidate(created_at="2026-07-20T12:00:00Z")
    second, *_ = _candidate(created_at="2026-07-20T12:01:00Z")
    assert first.approval_id == second.approval_id
    later_expiry, *_ = _candidate(expires_at="2026-07-20T14:00:00Z")
    assert later_expiry.approval_id != first.approval_id


def test_false_well_formed_proposal_id_fails_closed():
    proposal, issueplan, repository = _inputs()
    forged = object.__new__(type(proposal))
    for name in proposal.__dataclass_fields__:
        object.__setattr__(forged, name, getattr(proposal, name))
    object.__setattr__(
        forged, "proposal_id", "draft-task-proposal:" + "0" * 64
    )
    with pytest.raises(ValueError, match="current validated inputs"):
        build_approval_candidate(
            forged,
            issueplan,
            repository,
            approval_kind="implementation",
            authorizer_id="operator-1",
            decision_id="request-1",
            decision_at=CREATED_AT,
        )


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (ApprovalState.APPROVED, None),
        (ApprovalState.REJECTED, None),
        (ApprovalState.INVALIDATED, "approval.invalidated"),
        (ApprovalState.SUPERSEDED, "approval.superseded"),
    ],
)
def test_decision_revisions_are_immutable_linked_and_deterministic(
    state, reason
):
    candidate, *_ = _candidate()
    first = record_approval_decision(
        candidate,
        state=state,
        decision_id=f"decision-{state.value}",
        authorizer_id="operator-2",
        decision_at=APPROVED_AT,
    )
    second = record_approval_decision(
        candidate,
        state=state,
        decision_id=f"decision-{state.value}",
        authorizer_id="operator-2",
        decision_at=APPROVED_AT,
    )
    assert first == second
    assert first.approval_id == candidate.approval_id
    assert first.previous_revision == candidate.approval_revision
    assert first.revision_number == 2
    assert first.approval_revision != candidate.approval_revision
    if reason:
        assert reason in first.reason_codes
    with pytest.raises(FrozenInstanceError):
        first.state = ApprovalState.APPROVED


def test_changed_decision_creates_different_revision_and_terminal_cannot_reopen():
    candidate, *_ = _candidate()
    approved = record_approval_decision(
        candidate,
        state="approved",
        decision_id="decision-a",
        authorizer_id="operator-2",
        decision_at=APPROVED_AT,
    )
    rejected = record_approval_decision(
        candidate,
        state="rejected",
        decision_id="decision-b",
        authorizer_id="operator-2",
        decision_at=APPROVED_AT,
    )
    assert approved.approval_revision != rejected.approval_revision
    with pytest.raises(ValueError, match="invalid approval transition"):
        record_approval_decision(
            rejected,
            state="approved",
            decision_id="decision-c",
            authorizer_id="operator-2",
            decision_at="2026-07-20T12:20:00Z",
        )


def test_terminal_replacement_has_new_identity_and_references_prior():
    candidate, proposal, issueplan, repository = _candidate()
    invalidated = record_approval_decision(
        candidate,
        state="invalidated",
        decision_id="decision-invalidated",
        authorizer_id="operator-2",
        decision_at=APPROVED_AT,
    )
    replacement = build_approval_candidate(
        proposal,
        issueplan,
        repository,
        approval_kind="implementation",
        authorizer_id="operator-3",
        decision_id="request-2",
        decision_at="2026-07-20T12:20:00Z",
        expires_at="2026-07-20T14:00:00Z",
        supersedes=invalidated,
    )
    assert replacement.approval_id != invalidated.approval_id
    assert replacement.supersedes_approval_id == invalidated.approval_id


def test_expiry_boundary_is_exact_and_clock_free():
    approved, proposal, issueplan, repository = _approved()
    before = evaluate_approval_applicability(
        approved,
        proposal,
        issueplan,
        repository,
        evaluated_at="2026-07-20T12:59:59Z",
    )
    at = evaluate_approval_applicability(
        approved,
        proposal,
        issueplan,
        repository,
        evaluated_at=EXPIRES_AT,
    )
    after = evaluate_approval_applicability(
        approved,
        proposal,
        issueplan,
        repository,
        evaluated_at="2026-07-20T13:00:01Z",
    )
    assert before.status == "applicable"
    assert at.status == after.status == "stale"
    assert at.reason_codes == ("approval.expired",)


def test_no_expiry_remains_applicable_and_malformed_expiry_fails():
    approved, proposal, issueplan, repository = _approved(expires_at=None)
    assert (
        evaluate_approval_applicability(
            approved,
            proposal,
            issueplan,
            repository,
            evaluated_at="2030-01-01T00:00:00Z",
        ).status
        == "applicable"
    )
    with pytest.raises(ValueError):
        _candidate(expires_at="not-a-time")
    with pytest.raises(ValueError):
        _candidate(expires_at=CREATED_AT)


def test_non_expiry_decision_at_boundary_fails_and_expired_revision_is_allowed():
    candidate, *_ = _candidate()
    with pytest.raises(ValueError, match="before expires_at"):
        record_approval_decision(
            candidate,
            state="approved",
            decision_id="late-approve",
            authorizer_id="operator-2",
            decision_at=EXPIRES_AT,
        )
    expired = record_approval_decision(
        candidate,
        state="expired",
        decision_id="expiry-event",
        authorizer_id="operator-2",
        decision_at=EXPIRES_AT,
    )
    assert expired.reason_codes == ("approval.expired",)


def test_absent_approval_stays_blocked_despite_valid_evidence():
    proposal, issueplan, repository = _inputs()
    result = evaluate_approval_applicability(
        None,
        proposal,
        issueplan,
        repository,
        evaluated_at=APPROVED_AT,
    )
    assert result.status == "blocked"
    assert result.approval_applicable is False
    assert result.execution_authorized is False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("handoff_digest", "4" * 64, "handoff.changed"),
        ("graph_digest", "5" * 64, "graph.changed"),
        ("planning_result_digest", "6" * 64, "graph.changed"),
        ("repository_state_evidence_id", "7" * 64, "candidate.changed"),
        (
            "issueplan_current_state_evidence_id",
            "issueplan-current-state:" + "8" * 64,
            "candidate.changed",
        ),
        (
            "source_snapshot_fingerprint",
            "9" * 64,
            "source.revision-changed",
        ),
        ("scanner_result_fingerprint", "a" * 64, "candidate.changed"),
        (
            "implementation_contract_fingerprint",
            "b" * 64,
            "contract.scope-changed",
        ),
        ("allowed_files", ("different.py",), "contract.allowlist-changed"),
        ("forbidden_paths", ("secrets/**",), "contract.scope-changed"),
        (
            "required_tests",
            ("different test",),
            "contract.required-tests-changed",
        ),
    ],
)
def test_changed_governed_binding_is_stale(field, value, reason):
    approved, proposal, issueplan, repository = _approved()
    changed_binding = replace(approved.binding, **{field: value})
    prior = ApprovalRecord(
        schema_version=approved.schema_version,
        approval_id="",
        approval_revision="",
        revision_number=approved.revision_number,
        previous_revision=approved.previous_revision,
        approval_kind=approved.approval_kind,
        state=approved.state,
        binding=changed_binding,
        authorizer_id=approved.authorizer_id,
        decision_id=approved.decision_id,
        decision_at=approved.decision_at,
        expires_at=approved.expires_at,
        supersedes_approval_id=approved.supersedes_approval_id,
        reason_codes=approved.reason_codes,
    )
    result = evaluate_approval_applicability(
        prior,
        proposal,
        issueplan,
        repository,
        evaluated_at=APPROVED_AT,
    )
    assert result.status == "stale"
    assert field in result.changed_bindings
    assert reason in result.reason_codes


def test_changed_nodes_and_cohorts_are_candidate_change():
    approved, proposal, issueplan, repository = _approved()
    cohort = HandoffCohort(
        node_ids=("issue-399",),
        classification="parallel-candidate",
        reason_codes=("covered-no-deterministic-conflict",),
    )
    changed = replace(
        approved.binding,
        supplied_node_ids=("issue-399",),
        cohort_summaries=(cohort,),
    )
    record = replace(
        approved,
        approval_id="",
        approval_revision="",
        binding=changed,
    )
    result = evaluate_approval_applicability(
        record,
        proposal,
        issueplan,
        repository,
        evaluated_at=APPROVED_AT,
    )
    assert result.status == "stale"
    assert "candidate.changed" in result.reason_codes


@pytest.mark.parametrize(
    ("kwargs", "status", "reason"),
    [
        ({"retrieval_complete": False}, "needs-decision", "source.partial"),
        (
            {"pagination_complete": False},
            "needs-decision",
            "source.unknown-pagination",
        ),
        ({"accessible": False}, "needs-decision", "source.inaccessible"),
        (
            {
                "findings": (ScanFinding.IDENTITY_FINDING_PRESENT,),
                "adoption": AdoptionClass.IDENTITY_QUARANTINED,
            },
            "blocked",
            "identity.quarantined",
        ),
        ({"schema_version": "2.0"}, "invalid", "version.unsupported"),
    ],
)
def test_current_issueplan_failures_preserve_status_and_reason(
    kwargs, status, reason
):
    approved, proposal, _issueplan_old, repository = _approved()
    current = _issueplan(_handoff(), **kwargs)
    result = evaluate_approval_applicability(
        approved,
        proposal,
        current,
        repository,
        evaluated_at=APPROVED_AT,
    )
    assert result.status == status
    assert reason in result.reason_codes


def test_invalidation_events_are_sorted_deduplicated_and_order_independent():
    approved, proposal, issueplan, repository = _approved()
    first = evaluate_approval_applicability(
        approved,
        proposal,
        issueplan,
        repository,
        evaluated_at=APPROVED_AT,
        invalidation_events=(
            "graph.changed",
            "source.revision-changed",
            "graph.changed",
        ),
    )
    second = evaluate_approval_applicability(
        approved,
        proposal,
        issueplan,
        repository,
        evaluated_at=APPROVED_AT,
        invalidation_events=("source.revision-changed", "graph.changed"),
    )
    assert first == second
    assert first.reason_codes == (
        "graph.changed",
        "source.revision-changed",
    )
    assert first.status == "stale"


def test_lifecycle_record_reason_cannot_claim_another_state():
    candidate, *_ = _candidate()
    with pytest.raises(ValueError):
        ApprovalRecord(
            schema_version=candidate.schema_version,
            approval_id="",
            approval_revision="",
            revision_number=2,
            previous_revision=candidate.approval_revision,
            approval_kind=candidate.approval_kind,
            state=ApprovalState.APPROVED,
            binding=candidate.binding,
            authorizer_id="operator-2",
            decision_id="bad-decision",
            decision_at=APPROVED_AT,
            expires_at=candidate.expires_at,
            supersedes_approval_id=None,
            reason_codes=("approval.invalidated",),
        )


def test_no_external_io_or_scheduler_runtime_imports(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external operation attempted")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    approved, proposal, issueplan, repository = _approved()
    assert (
        evaluate_approval_applicability(
            approved,
            proposal,
            issueplan,
            repository,
            evaluated_at=APPROVED_AT,
        ).status
        == "applicable"
    )

    tree = ast.parse(inspect.getsource(approval_records))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(
        module.startswith("workflow_scheduler") for module in imported
    )
