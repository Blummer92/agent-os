from __future__ import annotations

from dataclasses import replace

from scripts.agent_os_candidate_packet.planning_stage import (
    prepare_planning_handoff,
    reconstruct_scheduler_planning_handoff,
)
from scripts.agent_os_candidate_packet.readiness_stage import prepare_issue_readiness
from scripts.agent_os_candidate_packet.stage_models import (
    DependencyEvidence,
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
    EvidenceStatus,
)
from tests.agent_os_candidate_packet.test_readiness_stage import (
    _FakeIssueReader,
    _FakeRepositoryReader,
    _request,
)

_SHA = "b89de18da472a3cd79877c4f7ee13b49bd7014eb"
_CREATED_AT = "2026-08-03T18:00:00Z"


def _readiness(*, dependency=None, dependency_identity=None):
    result = prepare_issue_readiness(
        _request(governed_field_names=("owner_agent", "source_of_truth")),
        _FakeIssueReader(),
        _FakeRepositoryReader(dependency=dependency),
        dependency_identity_evidence=dependency_identity,
    )
    return replace(
        result,
        issueplan_current_state_evidence=replace(
            result.issueplan_current_state_evidence,
            base_branch="main",
            evaluated_repository_sha=_SHA,
        ),
    )


def test_ready_result_builds_complete_deterministic_handoff() -> None:
    identity = DependencyIdentityEvidence(
        status=DependencyIdentityStatus.ABSENT,
        provenance=("fixture:no-dependencies",),
    )
    first = prepare_planning_handoff(
        _readiness(dependency_identity=identity),
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )
    second = prepare_planning_handoff(
        _readiness(dependency_identity=identity),
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )

    assert first.status.value == "ready"
    assert first.node is not None
    assert first.graph is not None
    assert first.planning_result is not None
    assert first.handoff is not None
    assert first.serialized_handoff
    assert first.wsc3_suppliable is True
    assert first.serialized_handoff == second.serialized_handoff
    assert first.handoff.handoff_digest == second.handoff.handoff_digest
    assert first.execution_authorized is False
    assert first.side_effects_performed is False


def test_missing_dependency_identity_preserves_needs_decision() -> None:
    result = prepare_planning_handoff(
        _readiness(),
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )

    assert result.status.value == "needs-decision"
    assert "dependency-identity-incomplete" in result.reason_codes
    assert result.planning_result.overall_classification.value == "needs-decision"
    assert result.wsc3_suppliable is True
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_blocked_readiness_remains_blocked() -> None:
    dependency = DependencyEvidence(
        EvidenceStatus.RESOLVED_BLOCKED,
        reason_codes=("dependency.explicitly-blocked",),
    )
    identity = DependencyIdentityEvidence(
        status=DependencyIdentityStatus.ABSENT,
        provenance=("fixture:no-dependencies",),
    )
    result = prepare_planning_handoff(
        _readiness(
            dependency=dependency,
            dependency_identity=identity,
        ),
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )

    assert result.status.value == "blocked"
    assert result.node.readiness.value == "blocked"
    assert result.planning_result.overall_classification.value == "blocked"
    assert result.wsc3_suppliable is True
    assert result.execution_authorized is False


def test_serialized_handoff_reconstructs_without_drift() -> None:
    identity = DependencyIdentityEvidence(
        status=DependencyIdentityStatus.ABSENT,
        provenance=("fixture:no-dependencies",),
    )
    result = prepare_planning_handoff(
        _readiness(dependency_identity=identity),
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )

    reconstructed = reconstruct_scheduler_planning_handoff(
        result.serialized_handoff
    )

    assert reconstructed == result.handoff
    assert reconstructed.handoff_digest == result.handoff.handoff_digest


def test_missing_repository_binding_fails_closed() -> None:
    result = prepare_issue_readiness(
        _request(governed_field_names=("owner_agent", "source_of_truth")),
        _FakeIssueReader(),
        _FakeRepositoryReader(),
    )
    planning = prepare_planning_handoff(
        result,
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )

    assert planning.status.value == "invalid-input"
    assert planning.reason_codes == ("missing-base-branch",)
    assert planning.node is None
    assert planning.handoff is None
    assert planning.execution_authorized is False
    assert planning.side_effects_performed is False
