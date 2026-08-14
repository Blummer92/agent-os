from __future__ import annotations

import ast
import inspect
import json
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
    APPROVAL_RECORD_SEMANTIC_SCHEMA_VERSION,
    APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION,
    ApprovalKind,
    ApprovalState,
    HandoffCohort,
    SchedulerPlanningHandoff,
    build_approval_candidate,
    build_approved_execution_projection,
    build_issueplan_current_state_evidence,
    build_planning_binding_evidence,
    compute_handoff_digest,
    evaluate_approval_applicability,
    record_approval_decision,
    serialize_approved_execution_projection,
)
from scripts.agent_os_issue_acceptance import (  # noqa: E402
    approved_execution_projection,
)
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
PROJECTED_AT = "2026-07-20T12:20:00Z"
EXPIRES_AT = "2026-07-20T13:00:00Z"


def _handoff(**changes):
    payload = {
        "contract_version": "0.2.0",
        "planning_result_version": "0.1.0",
        "evaluator_commit_sha": EVALUATOR_SHA,
        "repository": "blummer92/agent-os",
        "base_branch": "main",
        "evaluated_repository_sha": HEAD_SHA,
        "supplied_node_ids": ["issue-407"],
        "graph_digest": GRAPH_DIGEST,
        "planning_result_digest": PLANNING_DIGEST,
        "cohort_summaries": [
            {
                "node_ids": ["issue-407"],
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
    source_family="github-issue",
    **changes,
):
    candidate = MetadataCandidate(
        1,
        "raw",
        {
            "profile_version": "issueplan-core/v1",
            "entity_id": "issue-407",
            "revision": revision,
            "owner_agent": "Integration Manager",
            "required_files": [
                "scripts/agent_os_issue_acceptance/approved_execution_projection.py"
            ],
        },
    )
    scan = ScanResult(
        source_locator="github:Blummer92/agent-os#407",
        source_revision=revision,
        findings=findings,
        adoption_class=adoption,
        candidates=(candidate,),
        strict_valid=True,
        execution_authorized=False,
        evidence=("bounded=true",),
    )
    envelope = SourceEnvelope(
        source_locator="github:Blummer92/agent-os#407",
        source_revision=revision,
        content="issue body",
        retrieval_complete=retrieval_complete,
        pagination_complete=pagination_complete,
        accessible=accessible,
        source_family=source_family,
    )
    values = {
        "repository": handoff.repository,
        "base_branch": handoff.base_branch,
        "evaluated_repository_sha": handoff.evaluated_repository_sha,
        "implementation_contract_fingerprint": CONTRACT_DIGEST,
        "allowed_files": (
            "scripts/agent_os_issue_acceptance/approved_execution_projection.py",
        ),
        "forbidden_paths": (".github/workflows/**",),
        "required_tests": (
            "python -m pytest tests/agent_os_issue_acceptance/"
            "test_approved_execution_projection.py -q",
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
        freshness_boundary="main@ab85a143",
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
        correlation_id="issue-407",
        repository_identity=RepositoryIdentity(
            host="github.com",
            owner="blummer92",
            repository="agent-os",
            repository_id=123,
            default_branch="main",
        ),
        base_ref="main",
        base_sha=BASE_SHA,
        head_ref="agent/idb2d-approved-execution-projection",
        head_sha=head_sha,
        requested_ref="agent/idb2d-approved-execution-projection",
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
        freshness_boundary="workflow-run-407",
    )


def _repository_state_with(base, **changes):
    changes.setdefault("evidence_id", "")
    return replace(base, **changes)


def _proposal_inputs(*, handoff=None, issueplan=None, repository=None):
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
        created_at=CREATED_AT,
    )
    assert result.status == "eligible"
    return result.proposals[0], issueplan, repository


def _approved(*, expires_at=EXPIRES_AT, **inputs):
    proposal, issueplan, repository = _proposal_inputs(**inputs)
    candidate = build_approval_candidate(
        proposal,
        issueplan,
        repository,
        approval_kind=ApprovalKind.IMPLEMENTATION,
        authorizer_id="operator-1",
        decision_id="request-407",
        decision_at=CREATED_AT,
        expires_at=expires_at,
    )
    approved = record_approval_decision(
        candidate,
        state=ApprovalState.APPROVED,
        decision_id="decision-approve-407",
        authorizer_id="operator-2",
        decision_at=APPROVED_AT,
    )
    applicability = evaluate_approval_applicability(
        approved,
        proposal,
        issueplan,
        repository,
        evaluated_at=PROJECTED_AT,
    )
    assert applicability.status == "applicable"
    return approved, applicability, proposal, issueplan, repository


def _build(**changes):
    approved, applicability, proposal, issueplan, repository = _approved()
    values = {
        "proposal": proposal,
        "approval_record": approved,
        "approval_applicability": applicability,
        "issueplan_current_state_evidence": issueplan,
        "repository_state_evidence": repository,
        "projected_at": PROJECTED_AT,
    }
    values.update(changes)
    return build_approved_execution_projection(**values)


def test_public_schema_and_success_flags_are_exact():
    result = _build()

    assert APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION == "1.0"
    assert result.status == "complete"
    assert result.complete is True
    assert result.authoritative is False
    assert result.execution_authorized is False
    assert result.side_effects_performed is False
    projection = result.projection
    assert projection is not None
    assert projection.projection_id.startswith("approved-execution-projection:")
    assert projection.complete is True
    assert projection.authoritative is False
    assert projection.execution_authorized is False
    assert projection.side_effects_performed is False
    assert projection.evaluated_repository_sha == HEAD_SHA
    assert projection.tested_repository_sha == HEAD_SHA
    assert projection.repository_evidence_type == "branch-head"


def test_identity_is_deterministic_and_excludes_projection_timestamp():
    first = _build(projected_at="2026-07-20T12:20:00Z").projection
    second = _build(projected_at="2026-07-20T12:30:00Z").projection

    assert first is not None and second is not None
    assert first.projection_id == second.projection_id
    assert first.projected_at != second.projected_at
    assert serialize_approved_execution_projection(first) != serialize_approved_execution_projection(
        second
    )


def test_serialization_is_canonical_utf8_with_one_trailing_newline():
    projection = _build().projection
    assert projection is not None

    encoded = serialize_approved_execution_projection(projection)
    payload = json.loads(encoded)
    assert encoded.endswith(b"\n")
    assert not encoded.endswith(b"\n\n")
    assert b"\n" not in encoded[:-1]
    assert payload["projection_id"] == projection.projection_id
    assert payload["complete"] is True
    assert payload["authoritative"] is False
    assert list(payload) == sorted(payload)


@pytest.mark.parametrize(
    ("state", "decision_at", "expected_status", "expected_reason"),
    [
        (ApprovalState.PENDING, CREATED_AT, "blocked", "projection.incomplete"),
        (ApprovalState.REJECTED, APPROVED_AT, "blocked", "projection.incomplete"),
        (ApprovalState.EXPIRED, EXPIRES_AT, "stale", "approval.expired"),
        (ApprovalState.INVALIDATED, APPROVED_AT, "stale", "approval.invalidated"),
        (ApprovalState.SUPERSEDED, APPROVED_AT, "stale", "approval.superseded"),
    ],
)
def test_every_non_approved_state_fails_closed(
    state, decision_at, expected_status, expected_reason
):
    approved, _applicability, proposal, issueplan, repository = _approved()
    candidate = build_approval_candidate(
        proposal,
        issueplan,
        repository,
        approval_kind="implementation",
        authorizer_id="operator-1",
        decision_id="request-state",
        decision_at=CREATED_AT,
        expires_at=EXPIRES_AT,
    )
    record = candidate
    if state is not ApprovalState.PENDING:
        record = record_approval_decision(
            candidate,
            state=state,
            decision_id=f"decision-{state.value}",
            authorizer_id="operator-2",
            decision_at=decision_at,
        )
    evaluated_at = EXPIRES_AT if state is ApprovalState.EXPIRED else PROJECTED_AT
    applicability = evaluate_approval_applicability(
        record,
        proposal,
        issueplan,
        repository,
        evaluated_at=evaluated_at,
    )
    result = build_approved_execution_projection(
        proposal,
        record,
        applicability,
        issueplan,
        repository,
        projected_at=evaluated_at,
    )

    assert result.status == expected_status
    assert result.projection is None
    assert expected_reason in result.reason_codes
    assert result.execution_authorized is False


def test_expiry_boundary_revalidates_at_projection_time():
    approved, _applicability, proposal, issueplan, repository = _approved()
    expired = evaluate_approval_applicability(
        approved,
        proposal,
        issueplan,
        repository,
        evaluated_at=EXPIRES_AT,
    )

    result = build_approved_execution_projection(
        proposal,
        approved,
        expired,
        issueplan,
        repository,
        projected_at=EXPIRES_AT,
    )

    assert result.status == "stale"
    assert result.reason_codes == ("approval.expired",)


def test_supplied_applicability_must_match_recomputed_result():
    approved, applicability, proposal, issueplan, repository = _approved()
    forged = replace(applicability, current_proposal_id="draft-task-proposal:" + "0" * 64)

    result = build_approved_execution_projection(
        proposal,
        approved,
        forged,
        issueplan,
        repository,
        projected_at=PROJECTED_AT,
    )

    assert result.status == "invalid"
    assert result.reason_codes == ("projection.incomplete",)


def test_false_well_formed_proposal_id_is_rejected():
    approved, _applicability, proposal, issueplan, repository = _approved()
    forged = object.__new__(type(proposal))
    for name in proposal.__dataclass_fields__:
        object.__setattr__(forged, name, getattr(proposal, name))
    object.__setattr__(forged, "proposal_id", "draft-task-proposal:" + "0" * 64)
    applicability = evaluate_approval_applicability(
        approved,
        forged,
        issueplan,
        repository,
        evaluated_at=PROJECTED_AT,
    )

    result = build_approved_execution_projection(
        forged,
        approved,
        applicability,
        issueplan,
        repository,
        projected_at=PROJECTED_AT,
    )

    assert result.status == "invalid"
    assert "candidate.changed" in result.reason_codes


def test_false_approval_id_or_revision_is_rejected():
    approved, _applicability, proposal, issueplan, repository = _approved()
    for field, value in (
        ("approval_id", "approval:" + "0" * 64),
        ("approval_revision", "approval-revision:" + "0" * 64),
    ):
        forged = object.__new__(type(approved))
        for name in approved.__dataclass_fields__:
            object.__setattr__(forged, name, getattr(approved, name))
        object.__setattr__(forged, field, value)
        applicability = evaluate_approval_applicability(
            forged,
            proposal,
            issueplan,
            repository,
            evaluated_at=PROJECTED_AT,
        )
        result = build_approved_execution_projection(
            proposal,
            forged,
            applicability,
            issueplan,
            repository,
            projected_at=PROJECTED_AT,
        )
        assert result.status == "invalid"
        assert "projection.incomplete" in result.reason_codes


@pytest.mark.parametrize(
    ("issueplan_changes", "expected_status", "expected_reason"),
    [
        ({"retrieval_complete": False}, "needs-decision", "source.partial"),
        ({"pagination_complete": False}, "needs-decision", "source.unknown-pagination"),
        ({"accessible": False}, "needs-decision", "source.inaccessible"),
        ({"source_family": "notion-page"}, "blocked", "source.unsupported"),
        (
            {
                "findings": (ScanFinding.IDENTITY_FINDING_PRESENT,),
                "adoption": AdoptionClass.IDENTITY_QUARANTINED,
            },
            "blocked",
            "identity.quarantined",
        ),
    ],
)
def test_incomplete_or_unsupported_issueplan_evidence_fails_closed(
    issueplan_changes, expected_status, expected_reason
):
    approved, _old_applicability, proposal, _old_issueplan, repository = _approved()
    current = _issueplan(_handoff(), **issueplan_changes)
    applicability = evaluate_approval_applicability(
        approved,
        proposal,
        current,
        repository,
        evaluated_at=PROJECTED_AT,
    )

    result = build_approved_execution_projection(
        proposal,
        approved,
        applicability,
        current,
        repository,
        projected_at=PROJECTED_AT,
    )

    assert result.status == expected_status
    assert expected_reason in result.reason_codes


def test_changed_repository_evidence_and_contract_fail_closed():
    approved, _applicability, proposal, issueplan, _repository = _approved()
    changed_repository = _repository_state(
        head_sha=HEAD_SHA,
        requested_sha=HEAD_SHA,
        tested_sha="c" * 40,
    )
    applicability = evaluate_approval_applicability(
        approved,
        proposal,
        issueplan,
        changed_repository,
        evaluated_at=PROJECTED_AT,
    )

    result = build_approved_execution_projection(
        proposal,
        approved,
        applicability,
        issueplan,
        changed_repository,
        projected_at=PROJECTED_AT,
    )

    assert result.status == "stale"
    assert "candidate.changed" in result.reason_codes


def test_changed_allowlist_fails_closed_with_existing_reason_code():
    approved, _applicability, proposal, _old_issueplan, repository = _approved()
    changed = _issueplan(_handoff(), allowed_files=("different.py",))
    applicability = evaluate_approval_applicability(
        approved,
        proposal,
        changed,
        repository,
        evaluated_at=PROJECTED_AT,
    )

    result = build_approved_execution_projection(
        proposal,
        approved,
        applicability,
        changed,
        repository,
        projected_at=PROJECTED_AT,
    )

    assert result.status == "stale"
    assert "candidate.changed" in result.reason_codes or (
        "contract.allowlist-changed" in result.reason_codes
    )


def test_missing_child_objects_and_unsupported_version_fail_closed():
    approved, applicability, proposal, issueplan, repository = _approved()

    missing_approval = build_approved_execution_projection(
        proposal,
        None,
        applicability,
        issueplan,
        repository,
        projected_at=PROJECTED_AT,
    )
    missing_issueplan = build_approved_execution_projection(
        proposal,
        approved,
        applicability,
        None,
        repository,
        projected_at=PROJECTED_AT,
    )
    unsupported = build_approved_execution_projection(
        proposal,
        approved,
        applicability,
        issueplan,
        repository,
        projected_at=PROJECTED_AT,
        schema_version="2.0",
    )

    assert missing_approval.status == "needs-decision"
    assert "projection.lookup-failed" in missing_approval.reason_codes
    assert missing_issueplan.status == "needs-decision"
    assert "projection.incomplete" in missing_issueplan.reason_codes
    assert unsupported.status == "invalid"
    assert unsupported.reason_codes == ("version.unsupported",)


def test_projection_is_immutable_and_forged_projection_id_cannot_serialize():
    projection = _build().projection
    assert projection is not None
    with pytest.raises(FrozenInstanceError):
        projection.repository = "other/repo"

    forged = object.__new__(type(projection))
    for name in projection.__dataclass_fields__:
        object.__setattr__(forged, name, getattr(projection, name))
    object.__setattr__(
        forged,
        "projection_id",
        "approved-execution-projection:" + "0" * 64,
    )
    with pytest.raises(ValueError, match="projection_id"):
        serialize_approved_execution_projection(forged)


def test_no_clock_network_subprocess_filesystem_or_scheduler_runtime_dependency(
    monkeypatch,
):
    def forbidden(*args, **kwargs):
        raise AssertionError("external operation attempted")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    result = _build()
    assert result.status == "complete"

    tree = ast.parse(inspect.getsource(approved_execution_projection))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(module.startswith("workflow_scheduler") for module in imports)
    source = inspect.getsource(approved_execution_projection)
    assert "datetime.now" not in source
    assert "datetime.utcnow" not in source
    assert "subprocess" not in source
    assert "socket" not in source
    assert "sqlite" not in source.lower()


def test_projection_transport_round_trip_is_byte_stable():
    projection = _build().projection
    assert projection is not None
    encoded = serialize_approved_execution_projection(projection)

    restored = approved_execution_projection.reconstruct_approved_execution_projection(
        encoded
    )

    assert restored == projection
    assert serialize_approved_execution_projection(restored) == encoded


def test_projection_transport_rejects_schema_identity_type_and_fixed_flag_drift():
    projection = _build().projection
    assert projection is not None
    original = json.loads(serialize_approved_execution_projection(projection))

    missing = dict(original)
    missing.pop("proposal_id")
    with pytest.raises(ValueError, match="missing fields"):
        approved_execution_projection.reconstruct_approved_execution_projection(missing)

    unknown = dict(original)
    unknown["unexpected"] = True
    with pytest.raises(ValueError, match="unknown fields"):
        approved_execution_projection.reconstruct_approved_execution_projection(unknown)

    unsupported = dict(original)
    unsupported["schema_version"] = "2.0"
    with pytest.raises(ValueError, match="unsupported projection schema version"):
        approved_execution_projection.reconstruct_approved_execution_projection(unsupported)

    boolean_revision = dict(original)
    boolean_revision["approval_revision_number"] = True
    with pytest.raises(ValueError, match="approval_revision_number"):
        approved_execution_projection.reconstruct_approved_execution_projection(
            boolean_revision
        )

    tampered_id = dict(original)
    tampered_id["projection_id"] = "approved-execution-projection:" + "0" * 64
    with pytest.raises(ValueError, match="projection_id"):
        approved_execution_projection.reconstruct_approved_execution_projection(tampered_id)

    for field, value in (
        ("complete", False),
        ("authoritative", True),
        ("execution_authorized", True),
        ("side_effects_performed", True),
    ):
        payload = dict(original)
        payload[field] = value
        with pytest.raises(ValueError):
            approved_execution_projection.reconstruct_approved_execution_projection(
                payload
            )


def test_projection_transport_rejects_governed_binding_drift():
    projection = _build().projection
    assert projection is not None
    original = json.loads(serialize_approved_execution_projection(projection))

    mutations = (
        ("allowed_files", ["different.py"]),
        ("forbidden_paths", ["secrets/**"]),
        ("required_tests", ["different test"]),
    )
    for field, value in mutations:
        payload = json.loads(json.dumps(original))
        payload[field] = value
        with pytest.raises(ValueError, match="projection_id"):
            approved_execution_projection.reconstruct_approved_execution_projection(
                payload
            )

    node_drift = json.loads(json.dumps(original))
    node_drift["supplied_node_ids"] = ["issue-999"]
    node_drift["cohort_summaries"][0]["node_ids"] = ["issue-999"]
    with pytest.raises(ValueError, match="projection_id"):
        approved_execution_projection.reconstruct_approved_execution_projection(
            node_drift
        )

    malformed_cohort = json.loads(json.dumps(original))
    malformed_cohort["cohort_summaries"][0]["unexpected"] = True
    with pytest.raises(ValueError, match="unknown fields"):
        approved_execution_projection.reconstruct_approved_execution_projection(
            malformed_cohort
        )


def test_projection_result_transport_round_trips_complete_and_failure_results():
    complete = _build()
    encoded = approved_execution_projection.serialize_approved_execution_projection_result(
        complete
    )
    restored = approved_execution_projection.reconstruct_approved_execution_projection_result(
        encoded
    )
    assert restored == complete
    assert (
        approved_execution_projection.serialize_approved_execution_projection_result(
            restored
        )
        == encoded
    )

    failure = approved_execution_projection.ApprovedExecutionProjectionResult(
        "stale",
        None,
        ("candidate.changed",),
        ("drift",),
    )
    failure_encoded = (
        approved_execution_projection.serialize_approved_execution_projection_result(
            failure
        )
    )
    failure_restored = (
        approved_execution_projection.reconstruct_approved_execution_projection_result(
            failure_encoded
        )
    )
    assert failure_restored == failure


def test_projection_result_transport_rejects_invalid_envelopes():
    result = _build()
    original = json.loads(
        approved_execution_projection.serialize_approved_execution_projection_result(
            result
        )
    )

    for field, value in (
        ("authoritative", True),
        ("execution_authorized", True),
        ("side_effects_performed", True),
        ("complete", False),
    ):
        payload = json.loads(json.dumps(original))
        payload[field] = value
        with pytest.raises(ValueError):
            approved_execution_projection.reconstruct_approved_execution_projection_result(
                payload
            )

    reasons_on_complete = json.loads(json.dumps(original))
    reasons_on_complete["reason_codes"] = ["candidate.changed"]
    with pytest.raises(ValueError, match="cannot carry reason codes"):
        approved_execution_projection.reconstruct_approved_execution_projection_result(
            reasons_on_complete
        )

    missing_projection = json.loads(json.dumps(original))
    missing_projection["projection"] = None
    with pytest.raises(ValueError, match="requires one projection"):
        approved_execution_projection.reconstruct_approved_execution_projection_result(
            missing_projection
        )

    failure = {
        "status": "stale",
        "projection": None,
        "reason_codes": [],
        "details": [],
        "complete": False,
        "authoritative": False,
        "execution_authorized": False,
        "side_effects_performed": False,
    }
    with pytest.raises(ValueError, match="requires reason codes"):
        approved_execution_projection.reconstruct_approved_execution_projection_result(
            failure
        )


# --------------------------------------------------------------------------
# #407 semantic carry-forward: projection binds CURRENT exact identities
# rather than replaying stale prior-attempt IDs from the ApprovalBinding
# (#1115).
# --------------------------------------------------------------------------


def _semantic_two_phase_approved():
    handoff = _handoff()
    issueplan = _issueplan(
        handoff,
        graph_reference=None,
        planning_result_reference=None,
        handoff_reference=None,
        supplied_node_ids=(),
    )
    repository = _repository_state(
        head_sha=handoff.evaluated_repository_sha,
        requested_sha=handoff.evaluated_repository_sha,
    )
    binding = build_planning_binding_evidence(
        issueplan, handoff, created_at=CREATED_AT
    )
    result = build_draft_task_proposals(
        handoff,
        issueplan,
        repository,
        created_at=CREATED_AT,
        planning_binding=binding,
    )
    assert result.status == "eligible"
    proposal = result.proposals[0]
    candidate = build_approval_candidate(
        proposal,
        issueplan,
        repository,
        approval_kind=ApprovalKind.IMPLEMENTATION,
        authorizer_id="operator-1",
        decision_id="request-1115-projection",
        decision_at=CREATED_AT,
        expires_at=EXPIRES_AT,
        planning_binding=binding,
        schema_version=APPROVAL_RECORD_SEMANTIC_SCHEMA_VERSION,
    )
    approved = record_approval_decision(
        candidate,
        state=ApprovalState.APPROVED,
        decision_id="decision-1115-projection",
        authorizer_id="operator-2",
        decision_at=APPROVED_AT,
    )
    return approved, proposal, issueplan, repository, binding


def test_projection_binds_current_exact_identities_after_semantic_carry_forward():
    approved, original_proposal, issueplan, repository, _binding = (
        _semantic_two_phase_approved()
    )

    retry_handoff = _handoff(created_at="2026-07-20T11:10:00Z")
    retry_binding = build_planning_binding_evidence(
        issueplan, retry_handoff, created_at="2026-07-20T11:11:00Z"
    )
    retry_repository = _repository_state_with(
        repository,
        observed_at="2026-07-20T11:12:00Z",
        correlation_id="dns-retry-attempt-2",
    )
    retry_result = build_draft_task_proposals(
        retry_handoff,
        issueplan,
        retry_repository,
        created_at="2026-07-20T11:13:00Z",
        planning_binding=retry_binding,
    )
    assert retry_result.status == "eligible"
    retry_proposal = retry_result.proposals[0]
    assert retry_proposal.proposal_id != original_proposal.proposal_id
    assert retry_proposal.handoff_digest != original_proposal.handoff_digest
    assert (
        retry_proposal.repository_state_evidence_id
        != original_proposal.repository_state_evidence_id
    )

    applicability = evaluate_approval_applicability(
        approved,
        retry_proposal,
        issueplan,
        retry_repository,
        evaluated_at="2026-07-20T11:14:00Z",
        planning_binding=retry_binding,
    )
    assert applicability.status == "applicable"

    result = build_approved_execution_projection(
        retry_proposal,
        approved,
        applicability,
        issueplan,
        retry_repository,
        projected_at="2026-07-20T11:14:00Z",
        planning_binding=retry_binding,
    )
    assert result.status == "complete"
    projection = result.projection
    assert projection is not None

    # CURRENT exact identities, not the stale prior-attempt ones.
    assert projection.proposal_id == retry_proposal.proposal_id
    assert projection.proposal_id != original_proposal.proposal_id
    assert projection.repository_state_evidence_id == retry_repository.evidence_id
    assert (
        projection.repository_state_evidence_id
        != approved.binding.repository_state_evidence_id
    )
    assert projection.handoff_digest == retry_proposal.handoff_digest
    assert projection.handoff_digest != approved.binding.handoff_digest

    # ORIGINAL human approval identity/revision, unchanged.
    assert projection.approval_id == approved.approval_id
    assert projection.approval_revision == approved.approval_revision

    # Never authoritative or execution-authorizing.
    assert projection.authoritative is False
    assert projection.execution_authorized is False
    assert projection.side_effects_performed is False


def test_projection_still_fails_closed_for_semantic_schema_on_authority_change():
    approved, proposal, _original_issueplan, repository, binding = (
        _semantic_two_phase_approved()
    )
    changed_issueplan = _issueplan(
        _handoff(),
        graph_reference=None,
        planning_result_reference=None,
        handoff_reference=None,
        supplied_node_ids=(),
        allowed_files=("different.py",),
    )
    applicability = evaluate_approval_applicability(
        approved,
        proposal,
        changed_issueplan,
        repository,
        evaluated_at=PROJECTED_AT,
        planning_binding=binding,
    )
    result = build_approved_execution_projection(
        proposal,
        approved,
        applicability,
        changed_issueplan,
        repository,
        projected_at=PROJECTED_AT,
        planning_binding=binding,
    )
    assert result.status != "complete"
    assert result.projection is None
