from scripts.agent_os_issue_acceptance.batch_repair_regression_admission import (
    RegressionAdmission,
    RegressionEvidence,
    RegressionEvidenceKind,
    evaluate_regression_admission,
)


def test_incidental_prose_existence_is_repair_required():
    result = evaluate_regression_admission(
        RegressionEvidence(RegressionEvidenceKind.PROSE_EXISTENCE, changed_test_only=True)
    )
    assert result.admission is RegressionAdmission.REPAIR_REQUIRED
    assert result.merge_authorized is False
    assert result.side_effects_performed is False


def test_governed_policy_structure_can_be_legitimate_regression():
    result = evaluate_regression_admission(
        RegressionEvidence(
            RegressionEvidenceKind.POLICY_STRUCTURE,
            changed_test_only=True,
            governed_contract_is_prose=True,
        )
    )
    assert result.admission is RegressionAdmission.ADMISSIBLE


def test_executable_contract_must_actually_be_exercised():
    weak = evaluate_regression_admission(
        RegressionEvidence(RegressionEvidenceKind.EXECUTABLE_CONTRACT, changed_test_only=True)
    )
    strong = evaluate_regression_admission(
        RegressionEvidence(
            RegressionEvidenceKind.EXECUTABLE_CONTRACT,
            changed_test_only=True,
            executable_contract_exercised=True,
        )
    )
    assert weak.admission is RegressionAdmission.REPAIR_REQUIRED
    assert strong.admission is RegressionAdmission.ADMISSIBLE


def test_external_host_behavior_requires_conformance_fixture_or_handoff():
    missing = evaluate_regression_admission(
        RegressionEvidence(
            RegressionEvidenceKind.EXTERNAL_CONFORMANCE,
            changed_test_only=True,
            external_owner_confirmed=True,
        )
    )
    present = evaluate_regression_admission(
        RegressionEvidence(
            RegressionEvidenceKind.EXTERNAL_CONFORMANCE,
            changed_test_only=True,
            external_owner_confirmed=True,
            conformance_fixture_present=True,
        )
    )
    assert missing.admission is RegressionAdmission.CONFORMANCE_HANDOFF_REQUIRED
    assert present.admission is RegressionAdmission.ADMISSIBLE


def test_unresolved_behavioral_ownership_fails_closed():
    result = evaluate_regression_admission(
        RegressionEvidence(RegressionEvidenceKind.UNKNOWN, changed_test_only=True)
    )
    assert result.admission is RegressionAdmission.MANUAL_REVIEW
