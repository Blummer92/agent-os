from __future__ import annotations

import json
from dataclasses import replace

import pytest

from scripts.agent_os_candidate_packet.planning_stage import (
    PlanningHandoffStageResult,
    PlanningHandoffStageStatus,
    planning_handoff_stage_result_from_dict,
    planning_handoff_stage_result_to_dict,
    prepare_planning_handoff,
    reconstruct_scheduler_planning_handoff,
)
from scripts.agent_os_candidate_packet.readiness_stage import prepare_issue_readiness
from scripts.agent_os_candidate_packet.stage_models import (
    STAGE_SCHEMA_VERSION,
    DependencyEvidence,
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
    EvidenceStatus,
    IssuePlanningContext,
)
from scripts.agent_os_issue_acceptance.planning_binding import PlanningBindingEvidence
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


# --------------------------------------------------------------------------
# Two-phase planning binding (#917).
# --------------------------------------------------------------------------


def _natural_readiness(**context_overrides):
    """Readiness via the explicit pre-planning context -- no ``replace``."""

    values = dict(
        repository="blummer92/agent-os",
        base_branch="main",
        evaluated_repository_sha=_SHA,
        implementation_contract_fingerprint="3" * 64,
        allowed_files=("scripts/agent_os_candidate_packet",),
        forbidden_paths=(".github/workflows",),
        required_tests=("tests/agent_os_candidate_packet",),
        provenance=("issue-917:planning-stage-test",),
    )
    values.update(context_overrides)
    return prepare_issue_readiness(
        _request(governed_field_names=("owner_agent", "source_of_truth")),
        _FakeIssueReader(),
        _FakeRepositoryReader(),
        dependency_identity_evidence=DependencyIdentityEvidence(
            status=DependencyIdentityStatus.ABSENT,
            provenance=("issue-917:none",),
        ),
        planning_context=IssuePlanningContext(**values),
    )


def test_planning_creates_a_binding_from_the_projected_context() -> None:
    result = prepare_planning_handoff(
        _natural_readiness(), evaluator_sha="a" * 40, created_at=_CREATED_AT
    )

    assert result.status is PlanningHandoffStageStatus.READY
    binding = result.planning_binding
    assert isinstance(binding, PlanningBindingEvidence)
    assert binding.graph_digest == result.handoff.graph_digest
    assert binding.planning_result_digest == result.handoff.planning_result_digest
    assert binding.handoff_digest == result.handoff.handoff_digest
    assert binding.supplied_node_ids == result.handoff.supplied_node_ids
    assert binding.issueplan_current_state_evidence_id == (
        result.issueplan_current_state_evidence.evidence_id
    )
    assert binding.execution_authorized is False
    assert binding.side_effects_performed is False


def test_planning_binding_is_deterministic_for_equal_semantic_inputs() -> None:
    first = prepare_planning_handoff(
        _natural_readiness(), evaluator_sha="a" * 40, created_at=_CREATED_AT
    )
    second = prepare_planning_handoff(
        _natural_readiness(), evaluator_sha="a" * 40, created_at=_CREATED_AT
    )
    assert first.planning_binding == second.planning_binding


def test_legacy_result_without_context_carries_no_binding() -> None:
    """A pre-#917 IssuePlan has nothing to bind, and that stays valid."""

    ready = _ready_planning_result()
    assert ready.status is PlanningHandoffStageStatus.READY
    assert ready.issueplan_current_state_evidence.implementation_contract_fingerprint is None
    assert ready.planning_binding is None


def test_invalid_input_result_may_not_carry_a_binding() -> None:
    natural = prepare_planning_handoff(
        _natural_readiness(), evaluator_sha="a" * 40, created_at=_CREATED_AT
    )
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
            planning_binding=natural.planning_binding,
        )


def test_binding_field_rejects_a_foreign_type() -> None:
    ready = _ready_planning_result()
    with pytest.raises(TypeError, match="PlanningBindingEvidence"):
        replace(ready, planning_binding="planning-binding:x")


# --------------------------------------------------------------------------
# PlanningHandoffStageResult transport (#1054).
# --------------------------------------------------------------------------


def _with_binding() -> PlanningHandoffStageResult:
    result = prepare_planning_handoff(
        _natural_readiness(), evaluator_sha="a" * 40, created_at=_CREATED_AT
    )
    assert result.status is PlanningHandoffStageStatus.READY
    assert result.planning_binding is not None
    return result


def test_complete_result_with_binding_round_trips_to_an_identical_payload() -> None:
    result = _with_binding()

    payload = planning_handoff_stage_result_to_dict(result)
    rebuilt = planning_handoff_stage_result_from_dict(payload)

    assert type(rebuilt) is PlanningHandoffStageResult
    assert rebuilt == result
    assert rebuilt.node is rebuilt.graph.nodes[0]
    assert planning_handoff_stage_result_to_dict(rebuilt) == payload
    assert payload["schema_version"] == STAGE_SCHEMA_VERSION
    assert payload["execution_authorized"] is False
    assert payload["side_effects_performed"] is False


def test_legacy_result_without_binding_round_trips() -> None:
    result = _ready_planning_result()
    assert result.planning_binding is None

    payload = planning_handoff_stage_result_to_dict(result)
    rebuilt = planning_handoff_stage_result_from_dict(payload)

    assert rebuilt == result
    assert payload["planning_binding"] is None


def test_invalid_input_result_round_trips_with_every_object_absent() -> None:
    result = prepare_planning_handoff(
        prepare_issue_readiness(
            _request(governed_field_names=("owner_agent", "source_of_truth")),
            _FakeIssueReader(),
            _FakeRepositoryReader(),
        ),
        evaluator_sha=_SHA,
        created_at=_CREATED_AT,
    )
    assert result.status is PlanningHandoffStageStatus.INVALID_INPUT

    payload = planning_handoff_stage_result_to_dict(result)
    rebuilt = planning_handoff_stage_result_from_dict(payload)

    assert rebuilt == result
    for key in ("graph", "planning_result", "handoff", "handoff_validation", "planning_binding"):
        assert payload[key] is None


def test_unsupported_schema_version_is_rejected() -> None:
    payload = planning_handoff_stage_result_to_dict(_ready_planning_result())
    bad = {**payload, "schema_version": "9.9"}

    with pytest.raises(ValueError, match="unsupported stage schema_version"):
        planning_handoff_stage_result_from_dict(bad)


def test_unknown_field_is_rejected() -> None:
    payload = planning_handoff_stage_result_to_dict(_ready_planning_result())
    bad = {**payload, "surprise": 1}

    with pytest.raises(ValueError, match="unsupported field"):
        planning_handoff_stage_result_from_dict(bad)


def test_missing_field_is_rejected() -> None:
    payload = planning_handoff_stage_result_to_dict(_ready_planning_result())
    bad = dict(payload)
    del bad["handoff"]

    with pytest.raises(ValueError, match="missing field"):
        planning_handoff_stage_result_from_dict(bad)


def test_malformed_status_enum_is_rejected() -> None:
    payload = planning_handoff_stage_result_to_dict(_ready_planning_result())
    bad = {**payload, "status": "not-a-real-status"}

    with pytest.raises(ValueError):
        planning_handoff_stage_result_from_dict(bad)


def test_wsc3_suppliable_boolean_misuse_is_rejected() -> None:
    payload = planning_handoff_stage_result_to_dict(_ready_planning_result())
    bad = {**payload, "wsc3_suppliable": 1}

    with pytest.raises(ValueError, match="exact boolean"):
        planning_handoff_stage_result_from_dict(bad)


def test_graph_digest_binding_drift_is_rejected() -> None:
    payload = planning_handoff_stage_result_to_dict(_ready_planning_result())
    tampered_graph = json.loads(json.dumps(payload["graph"]))
    tampered_graph["nodes"][0]["owner"] = "someone-else"
    bad = {**payload, "graph": tampered_graph}

    with pytest.raises(ValueError, match="graph_digest"):
        planning_handoff_stage_result_from_dict(bad)


def test_planning_result_digest_binding_drift_is_rejected() -> None:
    payload = planning_handoff_stage_result_to_dict(_ready_planning_result())
    tampered_planning_result = json.loads(json.dumps(payload["planning_result"]))
    tampered_planning_result["batch_reason_codes"] = ["tampered-reason"]
    bad = {**payload, "planning_result": tampered_planning_result}

    with pytest.raises(ValueError, match="planning_result_digest"):
        planning_handoff_stage_result_from_dict(bad)


def test_handoff_validation_drift_is_rejected() -> None:
    payload = planning_handoff_stage_result_to_dict(_ready_planning_result())
    tampered_validation = dict(payload["handoff_validation"])
    tampered_validation["local_checks_passed"] = False
    bad = {**payload, "handoff_validation": tampered_validation}

    with pytest.raises(ValueError, match="does not match the carried handoff"):
        planning_handoff_stage_result_from_dict(bad)


def test_planning_binding_drift_is_rejected() -> None:
    """A planning binding whose own fingerprint no longer matches its content

    is rejected by the nested PlanningBindingEvidence transport itself before
    this stage's own IssuePlan/handoff cross-check ever runs.
    """
    payload = planning_handoff_stage_result_to_dict(_with_binding())
    tampered_binding = dict(payload["planning_binding"])
    tampered_binding["supplied_node_ids"] = ["issue-999"]
    bad = {**payload, "planning_binding": tampered_binding}

    with pytest.raises(ValueError):
        planning_handoff_stage_result_from_dict(bad)


def test_planning_binding_disagreeing_with_its_own_issueplan_is_rejected() -> None:
    """A self-consistent binding that does not match the carried IssuePlan/handoff.

    is rejected by this stage's cross-object binding check, not by the nested
    binding's own identity check.
    """
    first = _with_binding()
    second = prepare_planning_handoff(
        _natural_readiness(evaluated_repository_sha="f" * 40),
        evaluator_sha="a" * 40,
        created_at=_CREATED_AT,
    )
    assert second.planning_binding is not None
    assert second.planning_binding.binding_id != first.planning_binding.binding_id

    payload = planning_handoff_stage_result_to_dict(first)
    swapped_binding = planning_handoff_stage_result_to_dict(second)["planning_binding"]
    bad = {**payload, "planning_binding": swapped_binding}

    with pytest.raises(
        ValueError, match="does not match the IssuePlan evidence and handoff"
    ):
        planning_handoff_stage_result_from_dict(bad)


def test_wrong_nested_handoff_type_is_rejected() -> None:
    payload = planning_handoff_stage_result_to_dict(_ready_planning_result())
    bad = {**payload, "handoff": "not-an-object"}

    with pytest.raises((ValueError, TypeError)):
        planning_handoff_stage_result_from_dict(bad)


def test_execution_authorized_set_true_is_rejected() -> None:
    payload = planning_handoff_stage_result_to_dict(_ready_planning_result())
    bad = {**payload, "execution_authorized": True}

    with pytest.raises(ValueError, match="execution_authorized must be false"):
        planning_handoff_stage_result_from_dict(bad)


def test_side_effects_performed_set_true_is_rejected() -> None:
    payload = planning_handoff_stage_result_to_dict(_ready_planning_result())
    bad = {**payload, "side_effects_performed": True}

    with pytest.raises(ValueError, match="side_effects_performed must be false"):
        planning_handoff_stage_result_from_dict(bad)


def test_reason_codes_are_canonicalized() -> None:
    result = replace(_ready_planning_result(), reason_codes=("zeta", "alpha", "alpha"))

    payload = planning_handoff_stage_result_to_dict(result)

    assert payload["reason_codes"] == ["alpha", "zeta"]


def test_a_foreign_object_is_rejected_at_serialization() -> None:
    with pytest.raises(TypeError):
        planning_handoff_stage_result_to_dict(_natural_readiness())
