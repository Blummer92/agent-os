"""AB-M01: one perfectly valid artifact is still not a comparative pair."""
from instructional_materials_coach.evaluator_admission import EvaluatorArtifact, admit_comparative_evaluator


def test_ab_m01_single_complete_arm_fails_default_two_arm_minimum():
    arm = EvaluatorArtifact("A", "deck-a", "deck-a", "tutorial", "tutorial", True)
    result = admit_comparative_evaluator((arm,))
    assert result.admitted is False
    assert result.status == "blocked"
    assert "insufficient-artifacts: expected at least 2, got 1" in result.reasons
