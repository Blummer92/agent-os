"""AB-M02: duplicate arm IDs are not two independent producers."""
from instructional_materials_coach.evaluator_admission import EvaluatorArtifact, admit_comparative_evaluator


def test_ab_m02_two_exact_artifacts_cannot_share_comparison_arm_id():
    first = EvaluatorArtifact("A", "deck-a", "deck-a", "tutorial", "tutorial", True)
    second = EvaluatorArtifact("A", "deck-b", "deck-b", "tutorial", "tutorial", True)
    result = admit_comparative_evaluator((first, second))
    assert result.admitted is False
    assert result.status == "blocked"
    assert "invalid-arm-binding:A" in result.reasons
    assert result.blocked_arms == ("A",)
