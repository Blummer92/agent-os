from instructional_materials_coach.evaluator_admission import (
    EvaluatorArtifact,
    admit_comparative_evaluator,
)


def artifact(
    arm: str,
    required: str,
    produced: str | None,
    *,
    role: str = "software-tutorial",
    required_role: str = "software-tutorial",
    inspectable: bool = True,
) -> EvaluatorArtifact:
    return EvaluatorArtifact(
        arm_id=arm,
        required_artifact_id=required,
        produced_artifact_id=produced,
        artifact_role=role,
        required_role=required_role,
        inspectable=inspectable,
    )


def test_zero_produced_artifacts_blocks_evaluator_and_attributes_producers():
    result = admit_comparative_evaluator(
        [artifact("A", "deck-a", None), artifact("B", "deck-b", None)]
    )

    assert not result.admitted
    assert result.blocked_arms == ("A", "B")
    assert "A:producer-output-missing" in result.reasons
    assert "B:producer-output-missing" in result.reasons


def test_one_produced_artifact_preserves_success_and_blocks_missing_arm():
    result = admit_comparative_evaluator(
        [artifact("A", "deck-a", "deck-a"), artifact("B", "deck-b", None)]
    )

    assert not result.admitted
    assert result.blocked_arms == ("B",)


def test_two_exact_inspectable_role_valid_artifacts_are_admitted():
    result = admit_comparative_evaluator(
        [artifact("A", "deck-a", "deck-a"), artifact("B", "deck-b", "deck-b")]
    )

    assert result.admitted
    assert result.blocked_arms == ()
    assert result.reasons == ()


def test_plausible_substitute_cannot_satisfy_exact_producer_identity():
    result = admit_comparative_evaluator(
        [
            artifact("A", "new-candy-a", "existing-candy-deck"),
            artifact("B", "new-candy-b", "new-candy-b"),
        ]
    )

    assert not result.admitted
    assert result.blocked_arms == ("A",)
    assert "A:producer-identity-mismatch" in result.reasons


def test_wrong_role_artifact_does_not_admit_tutorial_evaluator():
    result = admit_comparative_evaluator(
        [
            artifact(
                "A",
                "deck-a",
                "deck-a",
                role="conceptual-lesson",
                required_role="software-tutorial",
            ),
            artifact("B", "deck-b", "deck-b"),
        ]
    )

    assert not result.admitted
    assert result.blocked_arms == ("A",)
    assert "A:artifact-role-mismatch" in result.reasons


def test_uninspectable_artifact_blocks_evaluator():
    result = admit_comparative_evaluator(
        [
            artifact("A", "deck-a", "deck-a", inspectable=False),
            artifact("B", "deck-b", "deck-b"),
        ]
    )

    assert not result.admitted
    assert result.blocked_arms == ("A",)
    assert "A:artifact-not-inspectable" in result.reasons


def test_direct_completed_artifacts_can_be_bound_and_compared_without_production():
    result = admit_comparative_evaluator(
        [
            artifact("supplied-A", "uploaded-a", "uploaded-a", role="worksheet", required_role="worksheet"),
            artifact("supplied-B", "uploaded-b", "uploaded-b", role="worksheet", required_role="worksheet"),
        ]
    )

    assert result.admitted
