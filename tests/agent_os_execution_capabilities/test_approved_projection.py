from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError, asdict

import pytest

from scripts.agent_os_execution_capabilities import (
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION,
    GovernedProjectionEvidenceResult,
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    WorktreeState,
    consume_approved_projection_evidence,
)
from scripts.agent_os_execution_capabilities import approved_projection as consumer_module
from scripts.agent_os_issue_acceptance.approved_execution_projection import (
    APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION,
    ApprovedExecutionProjection,
)
from scripts.agent_os_issue_acceptance.scheduler_handoff import HandoffCohort

HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40
MERGE_SHA = "c" * 40
OTHER_SHA = "d" * 40
CONTRACT_DIGEST = "1" * 64
OTHER_CONTRACT_DIGEST = "2" * 64


def _identity(**overrides) -> RepositoryIdentity:
    values = {
        "host": "github.com",
        "owner": "blummer92",
        "repository": "agent-os",
        "repository_id": 1289370915,
        "is_fork": False,
        "default_branch": "main",
    }
    values.update(overrides)
    return RepositoryIdentity(**values)


def _state(
    *,
    synthetic: bool = False,
    repository_identity: RepositoryIdentity | None = None,
    contract_fingerprint: str = CONTRACT_DIGEST,
    worktree_state: WorktreeState = WorktreeState.CLEAN,
    worktree_reason_codes: tuple[str, ...] = (),
) -> RepositoryStateEvidence:
    tested_sha = MERGE_SHA if synthetic else HEAD_SHA
    return RepositoryStateEvidence(
        schema_name=CAPABILITY_EVIDENCE_SCHEMA_NAME,
        evidence_schema_version=CAPABILITY_EVIDENCE_SCHEMA_VERSION,
        producer_adapter="fixture-adapter",
        producer_adapter_version="1.0",
        correlation_id="issue-563",
        repository_identity=repository_identity or _identity(),
        base_ref="main",
        base_sha=BASE_SHA,
        head_ref="agent/563-gex1f-correct-bindings",
        head_sha=HEAD_SHA,
        requested_ref="agent/563-gex1f-correct-bindings",
        requested_sha=HEAD_SHA,
        observed_sha=tested_sha,
        tested_sha=tested_sha,
        pushed_sha=HEAD_SHA,
        proposed_pr_sha=HEAD_SHA,
        synthetic_merge_sha=MERGE_SHA if synthetic else None,
        external_build_sha=tested_sha,
        evidence_type=(
            RepositoryEvidenceType.SYNTHETIC_PR_MERGE
            if synthetic
            else RepositoryEvidenceType.BRANCH_HEAD
        ),
        contract_fingerprint=contract_fingerprint,
        worktree_state=worktree_state,
        worktree_reason_codes=worktree_reason_codes,
        observed_at="2026-07-24T12:55:00Z",
        freshness_boundary="workflow-run-563",
    )


def _projection(
    state: RepositoryStateEvidence | None = None,
    **overrides,
) -> ApprovedExecutionProjection:
    state = state or _state()
    values = {
        "schema_version": APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION,
        "projection_id": "",
        "proposal_version": "1.0",
        "proposal_id": f"draft-task-proposal:{'3' * 64}",
        "approval_id": f"approval:{'4' * 64}",
        "approval_revision": f"approval-revision:{'5' * 64}",
        "approval_revision_number": 2,
        "approval_kind": "implementation",
        "approval_state": "approved",
        "approval_authorizer_id": "operator-2",
        "approval_decision_id": "decision-563",
        "approval_decision_at": "2026-07-24T12:40:00Z",
        "approval_expires_at": "2026-07-24T15:00:00Z",
        "approval_supersedes_id": None,
        "handoff_digest": "6" * 64,
        "graph_digest": "7" * 64,
        "planning_result_digest": "8" * 64,
        "repository": "blummer92/agent-os",
        "base_branch": "main",
        "evaluated_repository_sha": BASE_SHA,
        "evaluator_commit_sha": "e" * 40,
        "tested_repository_sha": state.tested_sha,
        "repository_evidence_type": state.evidence_type.value,
        "supplied_node_ids": ("issue-563",),
        "cohort_summaries": (
            HandoffCohort(
                node_ids=("issue-563",),
                classification="parallel-candidate",
                reason_codes=("covered-no-deterministic-conflict",),
            ),
        ),
        "issueplan_current_state_evidence_id": (
            f"issueplan-current-state:{'9' * 64}"
        ),
        "repository_state_evidence_id": state.evidence_id,
        "source_snapshot_fingerprint": "a" * 64,
        "scanner_result_fingerprint": "b" * 64,
        "implementation_contract_fingerprint": state.contract_fingerprint,
        "allowed_files": (
            "scripts/agent_os_execution_capabilities/approved_projection.py",
        ),
        "forbidden_paths": (".github/workflows/**",),
        "required_tests": (
            "python -m pytest tests/agent_os_execution_capabilities/"
            "test_approved_projection.py -q",
        ),
        "projected_at": "2026-07-24T13:00:00Z",
    }
    values.update(overrides)
    return ApprovedExecutionProjection(**values)


def _consume(
    projection: object | None = None,
    state: RepositoryStateEvidence | dict[str, object] | None = None,
    **overrides,
) -> GovernedProjectionEvidenceResult:
    resolved_state = state or _state()
    resolved_projection = projection or _projection(
        resolved_state if isinstance(resolved_state, RepositoryStateEvidence) else None
    )
    canonical_state = (
        resolved_state if isinstance(resolved_state, RepositoryStateEvidence) else _state()
    )
    canonical_projection = (
        resolved_projection
        if isinstance(resolved_projection, ApprovedExecutionProjection)
        else _projection(canonical_state)
    )
    values = {
        "expected_repository": _identity(),
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
        "expected_head_sha": HEAD_SHA,
        "expected_tested_sha": canonical_state.tested_sha,
        "expected_projection_id": canonical_projection.projection_id,
        "expected_approval_id": canonical_projection.approval_id,
        "expected_proposal_id": canonical_projection.proposal_id,
        "expected_repository_state_evidence_id": canonical_state.evidence_id,
        "expected_implementation_contract_fingerprint": (
            canonical_state.contract_fingerprint
        ),
        "expected_repository_evidence_type": canonical_state.evidence_type,
    }
    values.update(overrides)
    return consume_approved_projection_evidence(
        resolved_projection,
        resolved_state,
        **values,
    )


def _state_mapping(state: RepositoryStateEvidence) -> dict[str, object]:
    payload = asdict(state)
    payload["repository_identity"] = asdict(state.repository_identity)
    payload["evidence_type"] = state.evidence_type.value
    payload["worktree_state"] = state.worktree_state.value
    payload.pop("evidence_id", None)
    return payload


def test_valid_branch_head_is_accepted_with_distinct_base_and_source_head():
    state = _state()
    projection = _projection(state)
    result = _consume(projection, state)

    assert BASE_SHA != HEAD_SHA
    assert result.status == "accepted"
    assert result.reason_codes == ()
    assert result.details == ()
    assert result.base_sha == BASE_SHA
    assert result.evaluated_sha == BASE_SHA
    assert result.head_sha == HEAD_SHA
    assert result.tested_sha == HEAD_SHA
    assert result.projection_id == projection.projection_id
    assert result.repository_state_evidence_id == state.evidence_id
    assert result.implementation_contract_fingerprint == CONTRACT_DIGEST
    assert result.authoritative is False
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_valid_synthetic_merge_preserves_three_distinct_sha_roles():
    state = _state(synthetic=True)
    projection = _projection(state)
    result = _consume(projection, state)

    assert len({BASE_SHA, HEAD_SHA, MERGE_SHA}) == 3
    assert result.status == "accepted"
    assert result.evaluated_sha == BASE_SHA
    assert result.head_sha == HEAD_SHA
    assert result.tested_sha == MERGE_SHA
    assert result.repository_evidence_type is RepositoryEvidenceType.SYNTHETIC_PR_MERGE


def test_projection_evaluated_sha_equal_to_head_not_base_is_stale():
    projection = _projection(evaluated_repository_sha=HEAD_SHA)
    result = _consume(projection=projection)

    assert result.status == "stale"
    assert "ref.base-mismatch" in result.reason_codes
    assert "projection-evaluated-sha:mismatch" in result.details


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_base_sha", None),
        ("expected_head_sha", "not-a-sha"),
        ("expected_tested_sha", ""),
        ("expected_projection_id", None),
        ("expected_approval_id", ""),
        ("expected_proposal_id", None),
        ("expected_repository_state_evidence_id", ""),
        ("expected_implementation_contract_fingerprint", "short"),
        ("expected_repository_evidence_type", "branch-head"),
    ],
)
def test_missing_or_malformed_expectations_are_invalid(field, value):
    result = _consume(**{field: value})

    assert result.status == "invalid"
    assert "schema.unknown-field" in result.reason_codes
    assert any(item.startswith("expected-") for item in result.details)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("expected_base_sha", OTHER_SHA, "ref.base-mismatch"),
        ("expected_head_sha", OTHER_SHA, "ref.branch-moved"),
        ("expected_tested_sha", OTHER_SHA, "ref.test-sha-mismatch"),
        ("expected_projection_id", "wrong-projection", "ref.contract-mismatch"),
        ("expected_approval_id", "wrong-approval", "ref.contract-mismatch"),
        ("expected_proposal_id", "wrong-proposal", "ref.contract-mismatch"),
        (
            "expected_repository_state_evidence_id",
            "f" * 64,
            "ref.contract-mismatch",
        ),
        (
            "expected_implementation_contract_fingerprint",
            OTHER_CONTRACT_DIGEST,
            "ref.contract-mismatch",
        ),
        (
            "expected_repository_evidence_type",
            RepositoryEvidenceType.SYNTHETIC_PR_MERGE,
            "ref.test-sha-mismatch",
        ),
    ],
)
def test_well_formed_expectation_mismatches_are_stale(field, value, reason):
    result = _consume(**{field: value})

    assert result.status == "stale"
    assert reason in result.reason_codes


@pytest.mark.parametrize(
    "expected_repository,reason",
    [
        (_identity(owner="different"), "repo.identity-mismatch"),
        (_identity(repository_id=999), "repo.identity-mismatch"),
        (
            _identity(
                is_fork=True,
                upstream_owner="blummer92",
                upstream_repository="agent-os",
                upstream_repository_id=1289370915,
            ),
            "repo.fork-upstream-mismatch",
        ),
    ],
)
def test_repository_identity_mismatches_remain_stale(expected_repository, reason):
    result = _consume(expected_repository=expected_repository)
    assert result.status == "stale"
    assert reason in result.reason_codes


def test_projection_and_repository_evidence_bindings_are_both_checked():
    state = _state(contract_fingerprint=OTHER_CONTRACT_DIGEST)
    projection = _projection(
        state,
        implementation_contract_fingerprint=CONTRACT_DIGEST,
        repository_state_evidence_id="f" * 64,
    )
    result = _consume(
        projection,
        state,
        expected_repository_state_evidence_id=state.evidence_id,
        expected_implementation_contract_fingerprint=OTHER_CONTRACT_DIGEST,
    )

    assert result.status == "stale"
    assert "ref.contract-mismatch" in result.reason_codes
    assert "projection-repository-evidence-id:mismatch" in result.details
    assert "projection-implementation-contract:mismatch" in result.details


@pytest.mark.parametrize(
    "projection",
    [
        {"schema_version": "not-a-version"},
        {"schema_version": "2.0"},
        {
            "schema_version": "1.0",
            "execution_authorized": True,
            "side_effects_performed": True,
            "authoritative": True,
        },
        "not-a-projection",
    ],
)
def test_noncanonical_projection_inputs_fail_invalid_without_field_parsing(projection):
    result = _consume(projection=projection)

    assert result.status == "invalid"
    assert result.reason_codes == ("schema.unknown-field",)
    assert result.details == ("projection:canonical-object-required",)


@pytest.mark.parametrize(
    "state,expected_status,reason",
    [
        (
            _state(
                worktree_state=WorktreeState.DIRTY,
                worktree_reason_codes=("worktree.dirty",),
            ),
            "blocked",
            "worktree.dirty",
        ),
        (
            _state(
                worktree_state=WorktreeState.INDETERMINATE,
                worktree_reason_codes=("worktree.indeterminate",),
            ),
            "needs-decision",
            "worktree.indeterminate",
        ),
    ],
)
def test_worktree_fail_closed_behavior_remains(state, expected_status, reason):
    result = _consume(_projection(state), state)
    assert result.status == expected_status
    assert reason in result.reason_codes


def test_malformed_repository_mapping_remains_invalid():
    payload = _state_mapping(_state())
    payload["worktree_reason_codes"] = ["worktree.future"]
    payload["side_effects_performed"] = True
    result = _consume(state=payload)

    assert result.status == "invalid"
    assert "schema.unknown-field" in result.reason_codes


def test_projection_time_chronology_is_bounded_without_clock_read():
    projection = _projection(
        approval_expires_at="2026-07-24T13:00:00Z",
        projected_at="2026-07-24T13:00:00Z",
    )
    result = _consume(projection=projection)

    assert result.status == "stale"
    assert "ref.contract-mismatch" in result.reason_codes
    assert "approval:expired-at-projection-boundary" in result.details


def test_accepted_result_rejects_missing_bound_fields():
    with pytest.raises(ValueError, match="complete governed bindings"):
        GovernedProjectionEvidenceResult(
            status="accepted",
            schema_version=GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION,
            projection_id=None,
            proposal_id="proposal",
            approval_id="approval",
            repository_identity=_identity(),
            base_branch="main",
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            evaluated_sha=BASE_SHA,
            tested_sha=HEAD_SHA,
            repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
            repository_state_evidence_id="evidence",
            implementation_contract_fingerprint=CONTRACT_DIGEST,
            reason_codes=(),
            details=(),
        )


def test_output_is_deterministic_sorted_and_immutable():
    first = _consume(expected_projection_id="wrong", expected_approval_id="wrong")
    second = _consume(expected_projection_id="wrong", expected_approval_id="wrong")

    assert first == second
    assert first.reason_codes == tuple(sorted(first.reason_codes))
    assert first.details == tuple(sorted(first.details))
    with pytest.raises(FrozenInstanceError):
        first.status = "accepted"  # type: ignore[misc]
    with pytest.raises(TypeError):
        first.details[0] = "changed"  # type: ignore[index]


def test_module_has_no_clock_io_scheduler_or_runtime_side_effect_surface():
    source = inspect.getsource(consumer_module)
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert imported_roots.isdisjoint(
        {"os", "pathlib", "socket", "subprocess", "requests", "urllib", "time"}
    )
    assert "workflow_scheduler" not in source
    assert called_attributes.isdisjoint(
        {"now", "utcnow", "today", "open", "read_text", "write_text"}
    )
