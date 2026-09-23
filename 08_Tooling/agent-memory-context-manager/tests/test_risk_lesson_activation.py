import json

import pytest

from agent_memory_context_manager.lesson_activation_accountability import (
    LessonAccountabilityError,
    LessonActivationAccountability,
)
from agent_memory_context_manager.risk_lesson_activation import (
    MAX_PROJECTED_LESSONS,
    load_risk_lesson_activation_map,
    project_risks_to_lessons,
)


def test_exact_canonical_risk_projects_expected_lesson_ids():
    result = project_risks_to_lessons(("authorization",))

    assert result.lesson_ids == ("lesson-36", "lesson-37")
    assert result.retrieval_required
    assert result.retrieval_mode == "known-reference"


def test_unrelated_or_unknown_risk_performs_zero_activation():
    result = project_risks_to_lessons(("parser", "unknown-future-risk"))

    assert result.lesson_ids == ()
    assert not result.retrieval_required
    assert result.retrieval_mode == "not-needed"


def test_multiple_risks_form_bounded_deterministic_union():
    first = project_risks_to_lessons(
        ("workflow-ci-authority", "permissions", "authorization")
    )
    second = project_risks_to_lessons(
        ("authorization", "workflow-ci-authority", "permissions")
    )

    assert first == second
    assert first.lesson_ids == ("lesson-36", "lesson-37", "lesson-5")
    assert len(first.lesson_ids) <= MAX_PROJECTED_LESSONS


def test_duplicate_lesson_ids_across_risks_are_deduplicated():
    result = project_risks_to_lessons(("permissions", "authorization"))

    assert result.lesson_ids == ("lesson-36", "lesson-37")


def test_unknown_mapped_lesson_identity_fails_closed():
    with pytest.raises(LessonAccountabilityError, match="unknown lesson identity"):
        project_risks_to_lessons(
            ("authorization",),
            mapping={"authorization": ("lesson-does-not-exist",)},
        )


def test_blocked_ckr12_readiness_produces_no_usable_lesson():
    catalog = (
        LessonActivationAccountability(
            "lesson-36", "signal-activatable", "blocked-provenance"
        ),
    )
    result = project_risks_to_lessons(
        ("authorization",),
        mapping={"authorization": ("lesson-36",)},
        catalog=catalog,
    )

    assert result.lesson_ids == ()
    assert result.blocked_lesson_ids == ("lesson-36",)
    assert result.retrieval_mode == "not-needed"
    assert "blocked-provenance" in result.blocked_reasons[0]


def test_known_reference_only_lesson_cannot_become_signal_activated():
    catalog = (
        LessonActivationAccountability(
            "lesson-4", "known-reference-only", "ready"
        ),
    )
    result = project_risks_to_lessons(
        ("authorization",),
        mapping={"authorization": ("lesson-4",)},
        catalog=catalog,
    )

    assert result.lesson_ids == ()
    assert result.blocked_lesson_ids == ("lesson-4",)
    assert "known-reference-only" in result.blocked_reasons[0]


def test_mapping_loader_rejects_more_than_selected_budget(tmp_path):
    path = tmp_path / "mapping.json"
    path.write_text(
        json.dumps({"authorization": ["lesson-1", "lesson-2", "lesson-3", "lesson-4"]}),
        encoding="utf-8",
    )

    with pytest.raises(LessonAccountabilityError, match="bounded lesson budget"):
        load_risk_lesson_activation_map(path)


def test_projection_does_not_classify_risk_or_create_authority_fields():
    result = project_risks_to_lessons(("authorization",))

    assert not hasattr(result, "review_depth")
    assert not hasattr(result, "execution_authorized")
    assert not hasattr(result, "merge_authorized")
    assert not hasattr(result, "closure_authorized")
    assert not hasattr(result, "production_authorized")
    assert not hasattr(result, "external_write_authorized")


def test_mapping_uses_only_current_ckr12_signal_activatable_ready_lessons():
    mapping = load_risk_lesson_activation_map()
    projected = project_risks_to_lessons(mapping.keys())

    assert projected.blocked_lesson_ids == ()
    assert len(projected.lesson_ids) <= MAX_PROJECTED_LESSONS
