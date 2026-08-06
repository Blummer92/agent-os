from __future__ import annotations

import json
from dataclasses import replace

import pytest

from scripts.agent_os_candidate_packet.planning_stage import (
    PlanningHandoffStageResult,
    PlanningHandoffStageStatus,
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


def _replace_governed_field(result, field_name, state, canonical_value):
    evidence = result.issueplan_current_state_evidence
    snapshot = evidence.source_snapshot
    fields = tuple(
        (name, state, canonical_value) if name == field_name else (name, old_state, value)
        for name, old_state, value in snapshot.governed_fields
    )
    if not any(name == field_name for name, _, _ in fields):
        fields = (*fields, (field_name, state, canonical_value))
    return replace(
        result,
        issueplan_current_state_evidence=replace(
            evidence,
            source_snapshot=replace(snapshot, governed_fields=fields),
        ),
    )


def _no_dependencies():
    return DependencyIdentityEvidence(
        status=DependencyIdentityStatus.ABSENT,
        provenance=("fixture:no-dependencies",),
    )


def _ready_planning_result() -> PlanningHandoffStageResult:
    return prepare_planning_handoff(
        _readiness(dependency_identity=_no_dependencies()),
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )


def test_ready_result_builds_complete_deterministic_handoff() -> None:
    first = _ready_planning_result()
    second = _ready_planning_result()

    assert first.status.value == "ready"
    assert first.node is not None
    assert first.node.owner == "candidate-packet-agent"
    assert first.node.source_of_truth == "scripts/agent_os_candidate_packet/"
    assert first.graph is not None
    assert first.planning_result is not None
    assert first.handoff is not None
    assert first.serialized_handoff
    assert first.wsc3_suppliable is True
    assert first.serialized_handoff == second.serialized_handoff
    assert first.handoff.handoff_digest == second.handoff.handoff_digest
    assert first.execution_authorized is False
    assert first.side_effects_performed is False


def test_governed_values_preserve_interior_quotes_and_unicode() -> None:
    readiness = _readiness(dependency_identity=_no_dependencies())
    readiness = _replace_governed_field(
        readiness,
        "owner_agent",
        "present",
        json.dumps('Team "Alpha" – 東京', ensure_ascii=False),
    )
    readiness = _replace_governed_field(
        readiness,
        "source_of_truth",
        "present",
        json.dumps("docs/Équipe/", ensure_ascii=False),
    )

    result = prepare_planning_handoff(
        readiness,
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )

    assert result.status.value == "ready"
    assert result.node.owner == 'Team "Alpha" – 東京'
    assert result.node.source_of_truth == "docs/Équipe/"
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


@pytest.mark.parametrize("state", ["absent", "null", "intentionally-omitted"])
def test_optional_governed_owner_states_decode_to_none(state) -> None:
    readiness = _replace_governed_field(
        _readiness(dependency_identity=_no_dependencies()),
        "owner_agent",
        state,
        "null" if state == "null" else None,
    )

    result = prepare_planning_handoff(
        readiness,
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )

    assert result.status.value == "needs-decision"
    assert result.node.owner is None
    assert result.planning_result.overall_classification.value == "needs-decision"
    assert "missing-owner" in result.planning_result.cohorts[0].reason_codes
    assert result.wsc3_suppliable is True
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


@pytest.mark.parametrize(
    ("state", "canonical_value", "reason"),
    [
        ("present", "not-json", "owner_agent-governed-value-malformed"),
        ("present", "123", "owner_agent-governed-value-not-string"),
        ("present", '""', "owner_agent-governed-value-empty"),
        ("ambiguous", None, "owner_agent-governed-value-ambiguous"),
        ("malformed", None, "owner_agent-governed-value-malformed"),
        ("unavailable", None, "owner_agent-governed-value-unavailable"),
    ],
)
def test_invalid_governed_owner_fails_closed(state, canonical_value, reason) -> None:
    readiness = _replace_governed_field(
        _readiness(dependency_identity=_no_dependencies()),
        "owner_agent",
        state,
        canonical_value,
    )

    result = prepare_planning_handoff(
        readiness,
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )

    assert result.status.value == "invalid-input"
    assert result.reason_codes == (reason,)
    assert result.node is None
    assert result.graph is None
    assert result.planning_result is None
    assert result.handoff is None
    assert result.serialized_handoff is None
    assert result.wsc3_suppliable is False
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_missing_dependency_identity_preserves_needs_decision_and_evidence() -> None:
    result = prepare_planning_handoff(
        _readiness(),
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )

    assert result.status.value == "needs-decision"
    assert "dependency-identity-incomplete" in result.reason_codes
    assert "dependency-identity-incomplete" in result.node.readiness_evidence
    assert "dependency-identity.not-supplied" in result.node.readiness_evidence
    assert result.planning_result.overall_classification.value == "needs-decision"
    assert result.wsc3_suppliable is True
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_blocked_readiness_remains_blocked() -> None:
    dependency = DependencyEvidence(
        EvidenceStatus.RESOLVED_BLOCKED,
        reason_codes=("dependency.explicitly-blocked",),
    )
    result = prepare_planning_handoff(
        _readiness(
            dependency=dependency,
            dependency_identity=_no_dependencies(),
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
    result = _ready_planning_result()

    reconstructed = reconstruct_scheduler_planning_handoff(
        result.serialized_handoff
    )

    assert reconstructed == result.handoff
    assert reconstructed.handoff_digest == result.handoff.handoff_digest


def test_reconstruction_rejects_invalid_utf8() -> None:
    with pytest.raises(ValueError, match="canonical UTF-8 JSON"):
        reconstruct_scheduler_planning_handoff(b"\xff")


def test_reconstruction_rejects_non_mapping_json() -> None:
    with pytest.raises(ValueError, match="must be a mapping"):
        reconstruct_scheduler_planning_handoff("[]")


def test_reconstruction_rejects_tampered_handoff_digest() -> None:
    result = _ready_planning_result()
    payload = json.loads(result.serialized_handoff)
    payload["handoff_digest"] = "0" * 64

    with pytest.raises(ValueError, match="invalid SchedulerPlanningHandoff"):
        reconstruct_scheduler_planning_handoff(payload)


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


# --------------------------------------------------------------------------
# IssuePlan current-state evidence preservation (#752).
# --------------------------------------------------------------------------


def test_complete_result_preserves_the_exact_issueplan_evidence_object() -> None:
    readiness = _readiness(dependency_identity=_no_dependencies())

    result = prepare_planning_handoff(
        readiness,
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )

    # Identity, not equality: a rebuilt equivalent would defeat the point.
    assert (
        result.issueplan_current_state_evidence
        is readiness.issueplan_current_state_evidence
    )


@pytest.mark.parametrize(
    "dependency_identity",
    [_no_dependencies(), None],
    ids=["ready", "needs-decision"],
)
def test_every_complete_outcome_carries_the_consumed_evidence(
    dependency_identity,
) -> None:
    readiness = _readiness(dependency_identity=dependency_identity)

    result = prepare_planning_handoff(
        readiness,
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )

    assert result.status != PlanningHandoffStageStatus.INVALID_INPUT
    assert (
        result.issueplan_current_state_evidence
        is readiness.issueplan_current_state_evidence
    )


def test_invalid_input_results_retain_none_for_issueplan_evidence() -> None:
    readiness = _replace_governed_field(
        _readiness(dependency_identity=_no_dependencies()),
        "owner_agent",
        "present",
        "not-json",
    )

    result = prepare_planning_handoff(
        readiness,
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )

    assert result.status is PlanningHandoffStageStatus.INVALID_INPUT
    assert result.issueplan_current_state_evidence is None


def test_complete_results_cannot_drop_issueplan_evidence() -> None:
    ready = _ready_planning_result()

    with pytest.raises(ValueError, match="every canonical object"):
        replace(ready, issueplan_current_state_evidence=None)


def test_invalid_input_results_cannot_carry_issueplan_evidence() -> None:
    ready = _ready_planning_result()

    with pytest.raises(ValueError, match="must not carry partial objects"):
        PlanningHandoffStageResult(
            status=PlanningHandoffStageStatus.INVALID_INPUT,
            node=None,
            graph=None,
            planning_result=None,
            handoff=None,
            serialized_handoff=None,
            handoff_validation=None,
            wsc3_suppliable=False,
            issueplan_current_state_evidence=(
                ready.issueplan_current_state_evidence
            ),
        )


def test_preserved_evidence_leaves_handoff_bytes_and_digests_untouched() -> None:
    first = _ready_planning_result()
    second = _ready_planning_result()

    assert first.serialized_handoff == second.serialized_handoff
    assert first.handoff == second.handoff
    assert "issueplan_current_state_evidence" not in json.loads(
        first.serialized_handoff
    )

    unrelated = prepare_issue_readiness(
        _request(governed_field_names=("owner_agent", "source_of_truth")),
        _FakeIssueReader(),
        _FakeRepositoryReader(),
    ).issueplan_current_state_evidence
    assert unrelated is not first.issueplan_current_state_evidence

    swapped = replace(first, issueplan_current_state_evidence=unrelated)

    assert swapped.serialized_handoff == first.serialized_handoff
    assert swapped.handoff.handoff_digest == first.handoff.handoff_digest
    assert swapped.handoff.graph_digest == first.handoff.graph_digest
    assert swapped.handoff.planning_result_digest == (
        first.handoff.planning_result_digest
    )
    assert swapped.graph is first.graph
    assert swapped.planning_result is first.planning_result
    assert swapped.status is first.status


def test_pre_752_positional_callers_still_bind() -> None:
    legacy = PlanningHandoffStageResult(
        PlanningHandoffStageStatus.INVALID_INPUT,
        None,
        None,
        None,
        None,
        None,
        None,
        False,
        ("legacy-caller",),
    )

    assert legacy.issueplan_current_state_evidence is None
    assert legacy.reason_codes == ("legacy-caller",)
    assert legacy.execution_authorized is False
    assert legacy.side_effects_performed is False


def test_a_complete_result_built_positionally_now_requires_the_evidence() -> None:
    """The one shape #752 does change, asserted rather than left implicit.

    A pre-#752 caller assembling a *complete* result by hand gets the new field
    defaulted to None and is rejected -- the same invariant every other
    canonical object on this result already carries. `prepare_planning_handoff`
    supplies it, so only direct constructor use is affected.
    """
    ready = _ready_planning_result()

    with pytest.raises(ValueError, match="every canonical object"):
        PlanningHandoffStageResult(
            ready.status,
            ready.node,
            ready.graph,
            ready.planning_result,
            ready.handoff,
            ready.serialized_handoff,
            ready.handoff_validation,
            ready.wsc3_suppliable,
            ready.reason_codes,
        )

    # Supplying it positionally as the tenth argument is accepted.
    rebuilt = PlanningHandoffStageResult(
        ready.status,
        ready.node,
        ready.graph,
        ready.planning_result,
        ready.handoff,
        ready.serialized_handoff,
        ready.handoff_validation,
        ready.wsc3_suppliable,
        ready.reason_codes,
        ready.issueplan_current_state_evidence,
    )
    assert rebuilt.issueplan_current_state_evidence is (
        ready.issueplan_current_state_evidence
    )


def test_evidence_field_rejects_a_foreign_object() -> None:
    ready = _ready_planning_result()

    with pytest.raises(TypeError, match="IssuePlanCurrentStateEvidence"):
        replace(ready, issueplan_current_state_evidence="issueplan-current-state:x")
