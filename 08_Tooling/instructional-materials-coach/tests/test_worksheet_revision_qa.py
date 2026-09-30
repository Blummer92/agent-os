"""Regression coverage for #2890: worksheet revisions must preserve required visual scaffolds."""
import importlib
import inspect

import pytest

from instructional_materials_coach.worksheet_revision_qa import (
    WorksheetRevisionQAError,
    validate_revision_preserves_required_visual_roles,
    validate_revision_render_visuals,
)


def _typography_prior_roles():
    # Typography Foundations Day 1 prior revision: section wayfinding icons,
    # the worked typography visual model, and the student sketch-area icon.
    return (
        "section-wayfinding-icon",
        "typography-visual-model",
        "student-sketch-area-icon",
    )


def test_typography_2890_revision_dropping_required_visuals_fails():
    # Later Typography revision fixed vocabulary/layout but carried zero
    # required visual roles; the revision cannot be presented as complete.
    result = validate_revision_preserves_required_visual_roles(
        prior_required_role_ids=_typography_prior_roles(),
        revised_required_role_ids=(),
    )

    assert not result.passed
    assert not result.manual_review_required
    assert [finding.code for finding in result.findings] == [
        "worksheet-revision-required-visual-dropped"
    ]
    for role in _typography_prior_roles():
        assert role in result.findings[0].message


def test_typography_2890_revision_dropping_one_role_names_only_that_role():
    result = validate_revision_preserves_required_visual_roles(
        prior_required_role_ids=_typography_prior_roles(),
        revised_required_role_ids=(
            "section-wayfinding-icon",
            "student-sketch-area-icon",
        ),
    )

    assert not result.passed
    assert "typography-visual-model" in result.findings[0].message
    assert "section-wayfinding-icon" not in result.findings[0].message


def test_vocabulary_only_revision_preserving_roles_passes():
    result = validate_revision_preserves_required_visual_roles(
        prior_required_role_ids=_typography_prior_roles(),
        revised_required_role_ids=_typography_prior_roles(),
    )

    assert result.passed
    assert not result.manual_review_required
    assert result.findings == ()


def test_explicit_teacher_removal_is_not_a_silent_drop():
    result = validate_revision_preserves_required_visual_roles(
        prior_required_role_ids=_typography_prior_roles(),
        revised_required_role_ids=("section-wayfinding-icon",),
        teacher_removed_role_ids=(
            "typography-visual-model",
            "student-sketch-area-icon",
        ),
    )

    assert result.passed
    assert result.findings == ()


def test_added_roles_without_drops_pass():
    result = validate_revision_preserves_required_visual_roles(
        prior_required_role_ids=_typography_prior_roles(),
        revised_required_role_ids=_typography_prior_roles() + ("new-diagram",),
    )

    assert result.passed


def test_no_prior_required_roles_has_nothing_to_preserve():
    result = validate_revision_preserves_required_visual_roles(
        prior_required_role_ids=(),
        revised_required_role_ids=(),
    )

    assert result.passed


def test_revision_render_with_zero_required_visuals_cannot_pass_as_complete():
    # #2890 required test 1: a revision whose final render has zero required
    # icons/images cannot pass as complete.
    result = validate_revision_render_visuals(
        required_role_ids=("section-wayfinding-icon", "typography-visual-model"),
        rendered_visual_role_ids=(),
    )

    assert not result.passed
    assert [finding.code for finding in result.findings] == [
        "worksheet-revision-render-missing-required-visuals"
    ]
    assert "section-wayfinding-icon" in result.findings[0].message
    assert "typography-visual-model" in result.findings[0].message


def test_revision_render_missing_one_role_names_only_the_missing_role():
    result = validate_revision_render_visuals(
        required_role_ids=("section-wayfinding-icon", "typography-visual-model"),
        rendered_visual_role_ids=("section-wayfinding-icon",),
    )

    assert not result.passed
    assert "typography-visual-model" in result.findings[0].message
    assert "section-wayfinding-icon" not in result.findings[0].message


def test_revision_render_with_all_required_visuals_passes():
    roles = ("section-wayfinding-icon", "typography-visual-model")
    result = validate_revision_render_visuals(
        required_role_ids=roles,
        rendered_visual_role_ids=roles,
    )

    assert result.passed
    assert not result.manual_review_required


def test_revision_render_with_unresolved_visuals_needs_manual_review():
    result = validate_revision_render_visuals(
        required_role_ids=("section-wayfinding-icon",),
        rendered_visual_role_ids=(),
        unresolved_visual_role_ids=("section-wayfinding-icon",),
    )

    assert result.passed
    assert result.manual_review_required
    assert [finding.code for finding in result.findings] == [
        "worksheet-revision-render-visual-needs-review"
    ]


def test_revision_render_with_no_required_roles_passes():
    result = validate_revision_render_visuals(required_role_ids=())

    assert result.passed
    assert result.findings == ()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"prior_required_role_ids": ["a"], "revised_required_role_ids": ()},
        {"prior_required_role_ids": ("",), "revised_required_role_ids": ()},
        {"prior_required_role_ids": ("a b",), "revised_required_role_ids": ()},
        {"prior_required_role_ids": (), "revised_required_role_ids": (), "teacher_removed_role_ids": "a"},
    ],
)
def test_malformed_revision_inputs_fail_closed(kwargs):
    with pytest.raises(WorksheetRevisionQAError):
        validate_revision_preserves_required_visual_roles(**kwargs)


def test_revision_qa_has_no_external_write_surface():
    module = importlib.import_module("instructional_materials_coach.worksheet_revision_qa")
    source = inspect.getsource(module).lower()
    for forbidden in (
        "googleapiclient",
        "drive_service",
        "files().copy",
        "permissions",
        "allow_write",
        "production_authorized",
        "readiness",
        "approval",
        "notion",
    ):
        assert forbidden not in source
