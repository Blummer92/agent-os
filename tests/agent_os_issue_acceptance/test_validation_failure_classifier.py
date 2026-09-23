import json

import pytest

from scripts.agent_os_issue_acceptance.validation_failure_classifier import (
    EvidenceState,
    RequirementResult,
    ValidationFailureClassification,
    ValidationFailureEvidence,
    classify_validation_failure,
    render_validation_failure_classification,
    serialize_validation_failure_classification,
)


PR_SHA = "1" * 40
MAIN_SHA = "2" * 40


def evidence(**overrides):
    values = {
        "pr_head_sha": PR_SHA,
        "comparison_main_sha": MAIN_SHA,
        "command": "./scripts/validate-all.sh",
        "failed_requirement": "python -m pytest tests/test_example.py -q",
        "error_excerpt": "1 failed, 12 passed",
        "exit_code": 1,
        "source_identifiers": ("workflow:123", "job:456", "step:aggregate"),
        "evidence_state": EvidenceState.CURRENT,
        "comparable_pr_and_main": True,
        "same_requirement_executed": True,
        "pr_requirement_result": RequirementResult.FAIL,
        "main_requirement_result": RequirementResult.PASS,
        "materially_equivalent_failure": False,
        "pr_scope_attribution_supported": True,
        "infrastructure_configuration_failure_proven": False,
    }
    values.update(overrides)
    return ValidationFailureEvidence(**values)


def test_pr_regression_requires_comparable_main_pass_and_scope_attribution():
    result = classify_validation_failure(evidence())
    assert result.classification is ValidationFailureClassification.PR_REGRESSION
    assert "repair within authorized current scope" in result.recommended_next_action
    assert result.repair_authorized is False
    assert result.merge_authorized is False
    assert result.side_effects_performed is False


def test_inherited_main_failure_requires_materially_equivalent_main_failure():
    result = classify_validation_failure(
        evidence(
            main_requirement_result=RequirementResult.FAIL,
            materially_equivalent_failure=True,
            pr_scope_attribution_supported=False,
        )
    )
    assert (
        result.classification
        is ValidationFailureClassification.INHERITED_MAIN_FAILURE
    )
    assert "do not contaminate the PR" in result.recommended_next_action


def test_explicit_infrastructure_failure_takes_precedence_without_mutation_authority():
    result = classify_validation_failure(
        evidence(
            comparison_main_sha=None,
            comparable_pr_and_main=False,
            same_requirement_executed=False,
            main_requirement_result=RequirementResult.UNAVAILABLE,
            infrastructure_configuration_failure_proven=True,
            infrastructure_authorization_boundary="workflow change requires separate authorization",
        )
    )
    assert (
        result.classification
        is ValidationFailureClassification.CI_INFRASTRUCTURE_CONFIGURATION_FAILURE
    )
    assert result.authorization_boundary == (
        "workflow change requires separate authorization"
    )
    assert result.repair_authorized is False
    assert result.merge_authorized is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"comparison_main_sha": None},
        {"comparable_pr_and_main": False},
        {"same_requirement_executed": False},
        {"failed_requirement": None},
        {"main_requirement_result": RequirementResult.UNAVAILABLE},
        {"pr_scope_attribution_supported": False},
        {"evidence_state": EvidenceState.STALE},
        {"evidence_state": EvidenceState.CONFLICTING},
    ],
)
def test_missing_stale_conflicting_or_noncomparable_evidence_never_guesses(overrides):
    result = classify_validation_failure(evidence(**overrides))
    assert (
        result.classification
        is ValidationFailureClassification.INSUFFICIENT_EVIDENCE_NEEDS_DECISION
    )
    assert result.evidence_completeness == "incomplete"
    assert "do not guess" in result.recommended_next_action


def test_main_failure_without_equivalence_is_insufficient():
    result = classify_validation_failure(
        evidence(
            main_requirement_result=RequirementResult.FAIL,
            materially_equivalent_failure=False,
            pr_scope_attribution_supported=False,
        )
    )
    assert (
        result.classification
        is ValidationFailureClassification.INSUFFICIENT_EVIDENCE_NEEDS_DECISION
    )


def test_output_preserves_supplied_identity_and_is_deterministic():
    supplied = evidence(source_identifiers=("job:456", "workflow:123", "job:456"))
    first = classify_validation_failure(supplied)
    second = classify_validation_failure(supplied)
    assert first == second
    assert first.source_identifiers == ("job:456", "workflow:123")
    payload = json.loads(serialize_validation_failure_classification(first))
    assert payload["pr_head_sha"] == PR_SHA
    assert payload["comparison_main_sha"] == MAIN_SHA
    assert payload["command"] == "./scripts/validate-all.sh"
    assert payload["failed_requirement"] == "python -m pytest tests/test_example.py -q"
    assert payload["error_excerpt"] == "1 failed, 12 passed"
    assert payload["exit_code"] == 1
    assert payload["evidence_id"] == first.evidence_id


def test_human_renderer_matches_machine_classification_and_authority_boundaries():
    result = classify_validation_failure(evidence())
    rendered = render_validation_failure_classification(result)
    assert "Classification: pr_regression" in rendered
    assert f"PR head SHA: {PR_SHA}" in rendered
    assert f"Comparison main SHA: {MAIN_SHA}" in rendered
    assert "repair_authorized: false" in rendered
    assert "merge_authorized: false" in rendered
    assert "side_effects_performed: false" in rendered


def test_bounded_text_and_sha_validation_fail_closed():
    with pytest.raises(ValueError):
        evidence(pr_head_sha="abc")
    with pytest.raises(ValueError):
        evidence(error_excerpt="x" * 4097)
    with pytest.raises(ValueError):
        evidence(source_identifiers=tuple(f"id:{index}" for index in range(33)))
