from __future__ import annotations

import ast
import inspect
import socket
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.agent_os_execution_capabilities import (  # noqa: E402
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    WorktreeState,
)
from scripts.agent_os_issue_acceptance import (  # noqa: E402
    ApprovalInvalidationEvent,
    ApprovalKind,
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
DECISION_AT = "2026-07-20T12:00:00Z"


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


def _issueplan(handoff, *, revision="rev-1", **changes):
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
        findings=(),
        adoption_class=AdoptionClass.STRICT_NATIVE,
        candidates=(candidate,),
        strict_valid=True,
        execution_authorized=False,
        evidence=("bounded=true",),
    )
    envelope = SourceEnvelope(
        source_locator="github:Blummer92/agent-os#398",
        source_revision=revision,
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
        "implementation_contract_fingerprint": CONTRACT_DIGEST,
        "allowed_files": (
            "scripts/agent_os_issue_acceptance/approval_records.py",
            "tests/agent_os_issue_acceptance/test_approval_records.py",
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


def _repository_state(handoff):
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
        base_ref=handoff.base_branch,
        base_sha=BASE_SHA,
        head_ref="agent/idb2b-content-bound-approval-records",
        head_sha=handoff.evaluated_repository_sha,
        requested_ref="agent/idb2b-content-bound-approval-records",
        requested_sha=handoff.evaluated_repository_sha,
        observed_sha=handoff.evaluated_repository_sha,
        tested_sha=handoff.evaluated_repository_sha,
        pushed_sha=handoff.evaluated_repository_sha,
        proposed_pr_sha=handoff.evaluated_repository_sha,
        synthetic_merge_sha=None,
        external_build_sha=handoff.evaluated_repository_sha,
        evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        contract_fingerprint=CONTRACT_DIGEST,
        worktree_state=WorktreeState.CLEAN,
        worktree_reason_codes=(),
        observed_at="2026-07-20T11:45:00Z",
        freshness_boundary="workflow-run-1",
    )


def _bundle(*, handoff_changes=None, issueplan_changes=None, created_at=DECISION_AT):
    handoff = _handoff(**(handoff_changes or {}))
    evidence = _issueplan(handoff, **(issueplan_changes or {}))
    result = build_draft_task_proposals(
        handoff,
        evidence,
        _repository_state(handoff),
        created_at=created_at,
    )
    assert result.status == "eligible"
    return result.proposals[0], evidence


def _candidate(*, kind=ApprovalKind.IMPLEMENTATION, expires_at=None):
    proposal, evidence = _bundle()
    return build_approval_candidate(
        proposal,
        evidence,
        approval_kind=kind,
        authorizer_id="operator:zachary",
        decision_id="decision:candidate-1",
        decision_at=DECISION_AT,
        expires_at=expires_at,
    )


def _approved(*, expires_at=None):
    return record_approval_decision(
        _candidate(expires_at=expires_at),
        state=ApprovalState.APPROVED,
        decision_id="decision:approved-1",
        authorizer_id="operator:zachary",
        decision_at="2026-07-20T12:01:00Z",
    )


def test_candidate_identity_is_deterministic_kind_bound_and_frozen():
    first = _candidate()
    second = _candidate()
    publication = _candidate(kind=ApprovalKind.PUBLICATION)
    assert first == second
    assert first.approval_id != publication.approval_id
    assert first.state is ApprovalState.PENDING
    assert first.approval_revision == 1
    assert first.supersedes_approval_id is None
    with pytest.raises(FrozenInstanceError):
        first.state = ApprovalState.APPROVED
    with pytest.raises(FrozenInstanceError):
        first.binding.allowed_files = ()


def test_created_at_is_provenance_not_identity():
    first_proposal, first_evidence = _bundle(
        created_at="2026-07-20T12:00:00Z"
    )
    second_proposal, second_evidence = _bundle(
        created_at="2026-07-20T12:05:00Z"
    )
    assert first_proposal.proposal_id == second_proposal.proposal_id
    first = build_approval_candidate(
        first_proposal,
        first_evidence,
        approval_kind=ApprovalKind.IMPLEMENTATION,
        authorizer_id="operator:zachary",
        decision_id="decision:candidate-1",
        decision_at=DECISION_AT,
    )
    second = build_approval_candidate(
        second_proposal,
        second_evidence,
        approval_kind=ApprovalKind.IMPLEMENTATION,
        authorizer_id="operator:zachary",
        decision_id="decision:candidate-1",
        decision_at=DECISION_AT,
    )
    assert first.approval_id == second.approval_id


def test_candidate_rejects_forged_unsupported_or_incomplete_inputs():
    proposal, evidence = _bundle()
    values = {
        name: getattr(proposal, name) for name in proposal.__dataclass_fields__
    }
    forged = SimpleNamespace(**values)
    forged.proposal_id = "draft-task-proposal:" + "f" * 64
    with pytest.raises(ValueError, match="proposal_id"):
        build_approval_candidate(
            forged,
            evidence,
            approval_kind=ApprovalKind.IMPLEMENTATION,
            authorizer_id="operator:zachary",
            decision_id="decision:candidate-1",
            decision_at=DECISION_AT,
        )
    forged.proposal_version = "9.0.0"
    with pytest.raises(ValueError, match="unsupported WSC3"):
        build_approval_candidate(
            forged,
            evidence,
            approval_kind=ApprovalKind.IMPLEMENTATION,
            authorizer_id="operator:zachary",
            decision_id="decision:candidate-1",
            decision_at=DECISION_AT,
        )
    with pytest.raises(TypeError, match="canonical model"):
        build_approval_candidate(
            proposal,
            object(),
            approval_kind=ApprovalKind.IMPLEMENTATION,
            authorizer_id="operator:zachary",
            decision_id="decision:candidate-1",
            decision_at=DECISION_AT,
        )
    missing_contract = replace(evidence, implementation_contract_fingerprint=None)
    with pytest.raises(ValueError, match="implementation contract"):
        build_approval_candidate(
            proposal,
            missing_contract,
            approval_kind=ApprovalKind.IMPLEMENTATION,
            authorizer_id="operator:zachary",
            decision_id="decision:candidate-1",
            decision_at=DECISION_AT,
        )
    partial_snapshot = replace(
        evidence.source_snapshot,
        completeness_status="partial",
        reason_codes=("source.partial",),
    )
    partial = replace(
        evidence,
        source_snapshot=partial_snapshot,
        reason_codes=("source.partial",),
    )
    with pytest.raises(ValueError, match="complete source"):
        build_approval_candidate(
            proposal,
            partial,
            approval_kind=ApprovalKind.IMPLEMENTATION,
            authorizer_id="operator:zachary",
            decision_id="decision:candidate-1",
            decision_at=DECISION_AT,
        )


@pytest.mark.parametrize(
    ("state", "required_reason"),
    [
        (ApprovalState.APPROVED, None),
        (ApprovalState.REJECTED, None),
        (ApprovalState.EXPIRED, "approval.expired"),
        (ApprovalState.INVALIDATED, "approval.invalidated"),
        (ApprovalState.SUPERSEDED, "approval.superseded"),
    ],
)
def test_decisions_create_distinct_deterministic_revisions(state, required_reason):
    candidate = _candidate()
    kwargs = {
        "state": state,
        "decision_id": f"decision:{state.value}",
        "authorizer_id": "operator:zachary",
        "decision_at": "2026-07-20T12:01:00Z",
    }
    revision = record_approval_decision(candidate, **kwargs)
    assert revision == record_approval_decision(candidate, **kwargs)
    assert revision.approval_id != candidate.approval_id
    assert revision.approval_revision == 2
    assert revision.supersedes_approval_id == candidate.approval_id
    assert candidate.state is ApprovalState.PENDING
    if required_reason:
        assert required_reason in revision.reason_codes


def test_terminal_and_invalid_transitions_fail_closed():
    rejected = record_approval_decision(
        _candidate(),
        state=ApprovalState.REJECTED,
        decision_id="decision:rejected",
        authorizer_id="operator:zachary",
        decision_at="2026-07-20T12:01:00Z",
    )
    with pytest.raises(ValueError, match="terminal"):
        record_approval_decision(
            rejected,
            state=ApprovalState.APPROVED,
            decision_id="decision:copied-text",
            authorizer_id="operator:zachary",
            decision_at="2026-07-20T12:02:00Z",
        )
    with pytest.raises(ValueError, match="state transition"):
        record_approval_decision(
            _approved(),
            state=ApprovalState.REJECTED,
            decision_id="decision:late-reject",
            authorizer_id="operator:zachary",
            decision_at="2026-07-20T12:03:00Z",
        )


def test_approved_unchanged_is_applicable_but_never_execution_authority():
    proposal, evidence = _bundle()
    result = evaluate_approval_applicability(
        _approved(),
        proposal,
        evidence,
        evaluated_at="2026-07-20T12:02:00Z",
    )
    assert result.status == "applicable"
    assert result.approval_applicable is True
    assert result.reason_codes == ()
    assert result.execution_authorized is False
    assert result.side_effects_performed is False
    assert not hasattr(result, "scheduler_task_approved")
    assert not hasattr(result, "validation_passed")
    assert not hasattr(result, "capability_sufficient")


def test_pending_rejected_expired_invalidated_and_superseded_are_blocked():
    proposal, evidence = _bundle()
    records = [_candidate()]
    for state in (
        ApprovalState.REJECTED,
        ApprovalState.EXPIRED,
        ApprovalState.INVALIDATED,
        ApprovalState.SUPERSEDED,
    ):
        records.append(
            record_approval_decision(
                _candidate(),
                state=state,
                decision_id=f"decision:{state.value}",
                authorizer_id="operator:zachary",
                decision_at="2026-07-20T12:01:00Z",
            )
        )
    for record in records:
        result = evaluate_approval_applicability(
            record,
            proposal,
            evidence,
            evaluated_at="2026-07-20T12:02:00Z",
        )
        assert result.status == "blocked"
        assert result.approval_applicable is False


@pytest.mark.parametrize(
    ("handoff_changes", "reason"),
    [
        ({"graph_digest": "4" * 64}, "graph.changed"),
        ({"planning_result_digest": "5" * 64}, "candidate.changed"),
        ({"evaluator_commit_sha": "e" * 40}, "source.revision-changed"),
        ({"repository": "blummer92/agent-os-next"}, "source.revision-changed"),
        ({"base_branch": "develop"}, "source.revision-changed"),
        ({"evaluated_repository_sha": "f" * 40}, "source.revision-changed"),
        (
            {
                "supplied_node_ids": ["issue-398", "issue-399"],
                "cohort_summaries": [
                    {
                        "node_ids": ["issue-398", "issue-399"],
                        "classification": "parallel-candidate",
                        "reason_codes": ["covered-no-deterministic-conflict"],
                    }
                ],
            },
            "graph.changed",
        ),
    ],
)
def test_valid_changed_proposals_are_stale(handoff_changes, reason):
    proposal, evidence = _bundle(handoff_changes=handoff_changes)
    result = evaluate_approval_applicability(
        _approved(),
        proposal,
        evidence,
        evaluated_at="2026-07-20T12:02:00Z",
    )
    assert result.status == "stale"
    assert reason in result.reason_codes


def test_forged_current_proposal_is_invalid():
    proposal, evidence = _bundle()
    forged = SimpleNamespace(
        **{
            name: getattr(proposal, name)
            for name in proposal.__dataclass_fields__
        }
    )
    forged.proposal_id = "draft-task-proposal:" + "f" * 64
    result = evaluate_approval_applicability(
        _approved(),
        forged,
        evidence,
        evaluated_at="2026-07-20T12:02:00Z",
    )
    assert result.status == "invalid"
    assert result.reason_codes == ("candidate.changed",)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("allowed_files", ("different.py",), "contract.allowlist-changed"),
        ("forbidden_paths", ("production/**",), "contract.scope-changed"),
        (
            "required_tests",
            ("python -m pytest different.py",),
            "contract.required-tests-changed",
        ),
        (
            "implementation_contract_fingerprint",
            "9" * 64,
            "contract.scope-changed",
        ),
        ("source_snapshot_fingerprint", "8" * 64, "source.revision-changed"),
        ("scanner_result_fingerprint", "7" * 64, "source.revision-changed"),
        (
            "evidence_id",
            "issueplan-current-state:" + "6" * 64,
            "source.revision-changed",
        ),
    ],
)
def test_issueplan_binding_changes_are_stale(field, value, reason):
    proposal, evidence = _bundle()
    current = replace(evidence, **{field: value})
    result = evaluate_approval_applicability(
        _approved(),
        proposal,
        current,
        evaluated_at="2026-07-20T12:02:00Z",
    )
    assert result.status == "stale"
    assert reason in result.reason_codes


@pytest.mark.parametrize(
    ("reason", "expected_status"),
    [
        ("source.partial", "needs-decision"),
        ("source.inaccessible", "needs-decision"),
        ("source.unknown-pagination", "needs-decision"),
        ("scanner.unknown-governed-field", "needs-decision"),
        ("scanner.multiple-conflicting", "blocked"),
        ("scanner.malformed-candidate", "blocked"),
        ("identity.quarantined", "invalid"),
        ("version.unsupported", "invalid"),
    ],
)
def test_current_source_and_scanner_findings_fail_closed(reason, expected_status):
    proposal, evidence = _bundle()
    snapshot = replace(evidence.source_snapshot, reason_codes=(reason,))
    current = replace(
        evidence,
        source_snapshot=snapshot,
        reason_codes=(reason,),
    )
    result = evaluate_approval_applicability(
        _approved(),
        proposal,
        current,
        evaluated_at="2026-07-20T12:02:00Z",
    )
    assert result.status == expected_status
    assert reason in result.reason_codes


@pytest.mark.parametrize(
    ("event", "reason"),
    [
        (ApprovalInvalidationEvent.DIRECT_HUMAN_EDIT, "candidate.changed"),
        (ApprovalInvalidationEvent.MANUAL_MERGE, "source.revision-changed"),
        (
            ApprovalInvalidationEvent.EXPLICIT_INVALIDATION,
            "approval.invalidated",
        ),
    ],
)
def test_explicit_invalidation_events_use_canonical_reasons(event, reason):
    proposal, evidence = _bundle()
    result = evaluate_approval_applicability(
        _approved(),
        proposal,
        evidence,
        evaluated_at="2026-07-20T12:02:00Z",
        invalidation_events=(event,),
    )
    assert result.status == "stale"
    assert result.reason_codes == (reason,)


def test_causes_are_sorted_deduplicated_and_order_independent():
    proposal, evidence = _bundle()
    first = evaluate_approval_applicability(
        _approved(),
        proposal,
        evidence,
        evaluated_at="2026-07-20T12:02:00Z",
        invalidation_events=(
            ApprovalInvalidationEvent.MANUAL_MERGE,
            ApprovalInvalidationEvent.DIRECT_HUMAN_EDIT,
            ApprovalInvalidationEvent.MANUAL_MERGE,
        ),
    )
    second = evaluate_approval_applicability(
        _approved(),
        proposal,
        evidence,
        evaluated_at="2026-07-20T12:02:00Z",
        invalidation_events=(
            ApprovalInvalidationEvent.DIRECT_HUMAN_EDIT,
            ApprovalInvalidationEvent.MANUAL_MERGE,
        ),
    )
    assert first == second
    assert first.reason_codes == (
        "candidate.changed",
        "source.revision-changed",
    )


@pytest.mark.parametrize(
    ("evaluated_at", "status"),
    [
        ("2026-07-20T12:04:59Z", "applicable"),
        ("2026-07-20T12:05:00Z", "stale"),
        ("2026-07-20T12:05:01Z", "stale"),
    ],
)
def test_expiry_boundary(evaluated_at, status):
    proposal, evidence = _bundle()
    result = evaluate_approval_applicability(
        _approved(expires_at="2026-07-20T12:05:00Z"),
        proposal,
        evidence,
        evaluated_at=evaluated_at,
    )
    assert result.status == status
    assert ("approval.expired" in result.reason_codes) == (status == "stale")


def test_no_expiry_and_malformed_expiry():
    proposal, evidence = _bundle()
    result = evaluate_approval_applicability(
        _approved(),
        proposal,
        evidence,
        evaluated_at="2027-07-20T12:05:00Z",
    )
    assert result.status == "applicable"
    with pytest.raises(ValueError, match="valid UTC timestamp"):
        _candidate(expires_at="tomorrow")


def test_public_functions_perform_no_external_io(monkeypatch):
    proposal, evidence = _bundle()

    def denied(*args, **kwargs):
        raise AssertionError("external I/O was attempted")

    monkeypatch.setattr("builtins.open", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(subprocess, "run", denied)
    candidate = build_approval_candidate(
        proposal,
        evidence,
        approval_kind=ApprovalKind.IMPLEMENTATION,
        authorizer_id="operator:zachary",
        decision_id="decision:candidate-1",
        decision_at=DECISION_AT,
    )
    approved = record_approval_decision(
        candidate,
        state=ApprovalState.APPROVED,
        decision_id="decision:approved-1",
        authorizer_id="operator:zachary",
        decision_at="2026-07-20T12:01:00Z",
    )
    assert evaluate_approval_applicability(
        approved,
        proposal,
        evidence,
        evaluated_at="2026-07-20T12:02:00Z",
    ).status == "applicable"


def test_module_has_no_clock_network_subprocess_or_filesystem_calls():
    tree = ast.parse(inspect.getsource(approval_records))
    imports = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imports.isdisjoint({"os", "pathlib", "socket", "subprocess", "urllib"})
    forbidden = {"now", "utcnow", "open", "connect", "run", "Popen"}
    assert not {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in forbidden
    }
