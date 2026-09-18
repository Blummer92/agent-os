from __future__ import annotations

import pytest

from scripts.agent_os_issue_labels.self_defect import (
    DefectObservation,
    IssueCandidate,
    SelfDefectAction,
    SelfDefectClass,
    build_defect_identity,
    build_evidence_signature,
    decide_self_defect,
    mutation_identity_for,
)


def observation(**overrides):
    values = dict(
        repository="Blummer92/agent-os",
        mission_identity="issue:1621",
        governing_contract="01_Shared_Standards/github/tool-discovery-continuation.md",
        failure_signature="tool-discovery-silent-stop",
        expected_behavior="continue or return an explicit blocker",
        observed_behavior="stopped after capability discovery",
        evidence_sufficient=True,
        original_mission_actionable=True,
    )
    values.update(overrides)
    return DefectObservation(**values)


def test_known_defect_hardens_existing_issue_and_continues():
    obs = observation()
    candidate = IssueCandidate(
        issue_number=1608,
        governing_contract=obs.governing_contract,
        failure_signature=obs.failure_signature,
    )
    result = decide_self_defect(
        obs,
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
        candidates=(candidate,),
    )
    assert result.action is SelfDefectAction.HARDEN_EXISTING_ISSUE
    assert result.existing_issue_number == 1608
    assert result.mutation_allowed is True
    assert result.continue_original_mission is True


def test_novel_defect_routes_one_focused_issue_creation():
    result = decide_self_defect(
        observation(failure_signature="novel-contract-violation"),
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
    )
    assert result.action is SelfDefectAction.CREATE_FOCUSED_ISSUE
    assert result.existing_issue_number is None
    assert result.mutation_allowed is True
    assert "github-service-agent-write-owner" in result.reason_codes


def test_equivalent_mutation_is_idempotent_and_mission_can_continue():
    obs = observation()
    candidate = IssueCandidate(1608, obs.governing_contract, obs.failure_signature)
    first = decide_self_defect(
        obs,
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
        candidates=(candidate,),
    )
    mutation_identity = mutation_identity_for(first, obs)
    assert mutation_identity is not None
    repeated = decide_self_defect(
        obs,
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
        candidates=(candidate,),
        prior_mutation_identities=(mutation_identity,),
    )
    assert repeated.mutation_allowed is False
    assert repeated.continue_original_mission is True
    assert repeated.reason_codes == ("equivalent-mutation-already-recorded",)


def test_same_root_cause_with_different_observation_wording_deduplicates():
    first = observation(observed_behavior="stopped after discovery")
    second = observation(observed_behavior="returned status after loading tool schema")
    assert build_defect_identity(first) == build_defect_identity(second)


def test_similar_wording_different_failure_signature_does_not_deduplicate():
    first = observation(failure_signature="tool-discovery-silent-stop")
    second = observation(failure_signature="diagnostic-evidence-unavailable")
    assert build_defect_identity(first) != build_defect_identity(second)


def test_multiple_matching_issue_owners_fail_to_manual_review():
    obs = observation()
    candidates = (
        IssueCandidate(1608, obs.governing_contract, obs.failure_signature),
        IssueCandidate(9999, obs.governing_contract, obs.failure_signature),
    )
    result = decide_self_defect(
        obs,
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
        candidates=candidates,
    )
    assert result.action is SelfDefectAction.MANUAL_REVIEW
    assert result.mutation_allowed is False
    assert result.continue_original_mission is False


def test_closed_matching_issue_requires_explicit_regression_lifecycle_decision():
    obs = observation()
    result = decide_self_defect(
        obs,
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
        candidates=(
            IssueCandidate(
                1608,
                obs.governing_contract,
                obs.failure_signature,
                state="closed",
            ),
        ),
    )
    assert result.action is SelfDefectAction.MANUAL_REVIEW
    assert result.mutation_allowed is False
    assert result.reason_codes == (
        "closed-match-requires-regression-lifecycle-decision",
    )


def test_environment_failure_with_correct_handling_creates_no_meta_bug():
    result = decide_self_defect(
        observation(),
        classification=SelfDefectClass.EXECUTION_SURFACE_CAPABILITY,
    )
    assert result.action is SelfDefectAction.ROUTE_EXISTING_CAPABILITY
    assert result.mutation_allowed is False
    assert result.reason_codes == ("consume-1237",)


def test_insufficient_contract_evidence_fails_closed():
    result = decide_self_defect(
        observation(evidence_sufficient=False),
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
    )
    assert result.classification is SelfDefectClass.INSUFFICIENT_EVIDENCE
    assert result.action is SelfDefectAction.MANUAL_REVIEW
    assert result.mutation_allowed is False


def test_authorization_blocker_stops_without_issue_mutation():
    result = decide_self_defect(
        observation(),
        classification=SelfDefectClass.AUTHORIZATION_OR_GOVERNANCE_BLOCKER,
    )
    assert result.action is SelfDefectAction.STOP_EXPLICITLY
    assert result.continue_original_mission is False
    assert result.mutation_allowed is False


def test_recorded_side_defect_does_not_claim_continuation_when_mission_blocked():
    result = decide_self_defect(
        observation(original_mission_actionable=False),
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
    )
    assert result.action is SelfDefectAction.CREATE_FOCUSED_ISSUE
    assert result.continue_original_mission is False


def test_invalid_candidate_and_classification_fail_closed():
    obs = observation()
    with pytest.raises(ValueError):
        decide_self_defect(obs, classification="agent-os-contract-violation")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        decide_self_defect(
            obs,
            classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
            candidates=(IssueCandidate(0, obs.governing_contract, obs.failure_signature),),
        )


def test_create_then_rediscover_same_evidence_is_one_mutation():
    obs = observation(failure_signature="create-rediscover")
    created = decide_self_defect(
        obs,
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
    )
    prior = mutation_identity_for(created, obs)
    assert prior is not None

    rediscovered = decide_self_defect(
        obs,
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
        candidates=(IssueCandidate(4242, obs.governing_contract, obs.failure_signature),),
        prior_mutation_identities=(prior,),
    )
    assert rediscovered.action is SelfDefectAction.HARDEN_EXISTING_ISSUE
    assert rediscovered.existing_issue_number == 4242
    assert rediscovered.mutation_allowed is False
    assert rediscovered.reason_codes == ("equivalent-mutation-already-recorded",)


def test_new_material_evidence_can_harden_existing_issue_once():
    first = observation(failure_signature="material-evidence")
    candidate = IssueCandidate(4242, first.governing_contract, first.failure_signature)
    created = decide_self_defect(
        first,
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
        candidates=(candidate,),
    )
    prior = mutation_identity_for(created, first)
    assert prior is not None

    second = observation(
        failure_signature="material-evidence",
        observed_behavior="same defect reproduced on a second independent path",
    )
    hardened = decide_self_defect(
        second,
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
        candidates=(candidate,),
        prior_mutation_identities=(prior,),
    )
    assert hardened.action is SelfDefectAction.HARDEN_EXISTING_ISSUE
    assert hardened.mutation_allowed is True

    second_identity = mutation_identity_for(hardened, second)
    repeated = decide_self_defect(
        second,
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
        candidates=(candidate,),
        prior_mutation_identities=(prior, second_identity),
    )
    assert repeated.mutation_allowed is False


def test_identical_evidence_always_yields_the_same_identity():
    assert build_evidence_signature(observation()) == build_evidence_signature(observation())


def test_rewrapped_evidence_normalizes_to_the_same_identity():
    """Re-wrapping the same reproduction is not new material evidence."""
    rewrapped = observation(observed_behavior="stopped   after\n\tcapability discovery")
    assert build_evidence_signature(rewrapped) == build_evidence_signature(observation())


def test_different_material_evidence_yields_a_different_identity():
    other = observation(observed_behavior="crashed while resolving the alias registry")
    assert build_evidence_signature(other) != build_evidence_signature(observation())


def test_a_caller_cannot_relabel_equivalent_evidence_into_a_second_write():
    """#2680: the identity is derived, so no caller-supplied label can bypass it."""
    obs = observation(failure_signature="relabel-attempt")
    candidate = IssueCandidate(4242, obs.governing_contract, obs.failure_signature)
    created = decide_self_defect(
        obs,
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
        candidates=(candidate,),
    )
    prior = mutation_identity_for(created, obs)
    repeated = decide_self_defect(
        obs,
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
        candidates=(candidate,),
        prior_mutation_identities=(prior,),
    )
    assert repeated.mutation_allowed is False
    assert repeated.reason_codes == ("equivalent-mutation-already-recorded",)


def test_new_evidence_cannot_be_suppressed_by_reusing_an_old_identity():
    obs = observation(failure_signature="suppression-attempt")
    candidate = IssueCandidate(4242, obs.governing_contract, obs.failure_signature)
    created = decide_self_defect(
        obs,
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
        candidates=(candidate,),
    )
    prior = mutation_identity_for(created, obs)
    genuinely_new = observation(
        failure_signature="suppression-attempt",
        observed_behavior="null dereference in the alias resolver on the same path",
    )
    hardened = decide_self_defect(
        genuinely_new,
        classification=SelfDefectClass.AGENT_OS_CONTRACT_VIOLATION,
        candidates=(candidate,),
        prior_mutation_identities=(prior,),
    )
    assert hardened.mutation_allowed is True


def test_unrelated_evidence_identities_do_not_collide():
    identities = {
        build_evidence_signature(observation(observed_behavior=text))
        for text in ("a", "b", "a b", "ab", "")
        if text
    }
    assert len(identities) == 4
