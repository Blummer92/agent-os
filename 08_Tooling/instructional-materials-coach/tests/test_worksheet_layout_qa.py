"""Regression coverage for #2890: rendered QA flags accidental dead space on worksheets."""
import importlib
import inspect

import pytest

from instructional_materials_coach.worksheet_layout_qa import (
    BlankRegion,
    WorksheetLayoutQAError,
    WorksheetPageLayoutEvidence,
    evaluate_worksheet_layout,
)


def _typography_two_page_fixture():
    # Typography Foundations Day 1 two-page worksheet: the teacher circled
    # large unused regions on both pages of the later revision, which had
    # dropped its required visual scaffolds and left the sketch/response
    # areas unbuilt. Evidence is recorded at phone scale per the rendered
    # classroom review gate.
    return (
        WorksheetPageLayoutEvidence(
            page_number=1,
            inspection_scale="phone-scale",
            expected_roles=(
                "section-wayfinding-icon",
                "typography-visual-model",
                "response-space",
            ),
            missing_roles=(
                "section-wayfinding-icon",
                "typography-visual-model",
            ),
            blank_regions=(
                BlankRegion(region_id="page1-lower-half", page_number=1, share_of_page=0.45),
            ),
        ),
        WorksheetPageLayoutEvidence(
            page_number=2,
            inspection_scale="phone-scale",
            expected_roles=("student-sketch-area", "response-space"),
            missing_roles=("student-sketch-area",),
            blank_regions=(
                BlankRegion(region_id="page2-middle-band", page_number=2, share_of_page=0.30),
            ),
        ),
    )


def test_typography_2890_two_page_dead_space_with_missing_roles_fails():
    result = evaluate_worksheet_layout(_typography_two_page_fixture())

    assert not result.passed
    assert not result.manual_review_required
    assert [finding.code for finding in result.findings] == [
        "worksheet-dead-space-with-missing-roles",
        "worksheet-dead-space-with-missing-roles",
    ]
    assert [finding.page_number for finding in result.findings] == [1, 2]
    assert all(finding.severity == "fail" for finding in result.findings)
    assert "section-wayfinding-icon" in result.findings[0].message
    assert "typography-visual-model" in result.findings[0].message
    assert "student-sketch-area" in result.findings[1].message


def test_intentional_whitespace_with_all_roles_satisfied_routes_to_manual_review():
    # Large blank region but every expected role is satisfied: the whitespace
    # may be intentional, so it must not be mechanically rejected.
    pages = (
        WorksheetPageLayoutEvidence(
            page_number=1,
            inspection_scale="phone-scale",
            expected_roles=("response-space",),
            missing_roles=(),
            blank_regions=(
                BlankRegion(region_id="breathing-room", page_number=1, share_of_page=0.25),
            ),
        ),
    )

    result = evaluate_worksheet_layout(pages)

    assert result.passed
    assert result.manual_review_required
    assert [finding.code for finding in result.findings] == [
        "worksheet-large-blank-region-unprovable"
    ]


def test_small_blank_regions_are_never_flagged_even_with_missing_roles():
    # Ordinary breathing room below the large-region bound is not dead space.
    pages = (
        WorksheetPageLayoutEvidence(
            page_number=1,
            inspection_scale="phone-scale",
            expected_roles=("response-space", "section-wayfinding-icon"),
            missing_roles=("section-wayfinding-icon",),
            blank_regions=(
                BlankRegion(region_id="gutter", page_number=1, share_of_page=0.10),
            ),
        ),
    )

    result = evaluate_worksheet_layout(pages)

    assert result.passed
    assert not result.manual_review_required
    assert result.findings == ()


def test_page_without_blank_regions_passes():
    pages = (
        WorksheetPageLayoutEvidence(
            page_number=1,
            inspection_scale="phone-scale",
            expected_roles=("response-space",),
            missing_roles=(),
            blank_regions=(),
        ),
    )

    result = evaluate_worksheet_layout(pages)

    assert result.passed
    assert result.findings == ()


def test_missing_roles_without_blank_regions_pass_layout_qa():
    # Missing roles alone are owned by the visual/section completeness seams;
    # layout QA only flags blank regions that are evidence-backed as dead space.
    pages = (
        WorksheetPageLayoutEvidence(
            page_number=1,
            inspection_scale="phone-scale",
            expected_roles=("response-space", "section-wayfinding-icon"),
            missing_roles=("section-wayfinding-icon",),
            blank_regions=(),
        ),
    )

    result = evaluate_worksheet_layout(pages)

    assert result.passed


@pytest.mark.parametrize(
    "pages",
    [
        # not a tuple
        ["not-a-tuple"],
        # missing role outside expected roles
        (
            WorksheetPageLayoutEvidence(
                page_number=1,
                inspection_scale="phone-scale",
                expected_roles=("response-space",),
                missing_roles=("section-wayfinding-icon",),
                blank_regions=(),
            ),
        ),
        # blank region bound to the wrong page
        (
            WorksheetPageLayoutEvidence(
                page_number=1,
                inspection_scale="phone-scale",
                expected_roles=("response-space",),
                missing_roles=(),
                blank_regions=(BlankRegion(region_id="x", page_number=2, share_of_page=0.5),),
            ),
        ),
        # share out of range
        (
            WorksheetPageLayoutEvidence(
                page_number=1,
                inspection_scale="phone-scale",
                expected_roles=("response-space",),
                missing_roles=(),
                blank_regions=(BlankRegion(region_id="x", page_number=1, share_of_page=0.0),),
            ),
        ),
        # empty inspection scale
        (
            WorksheetPageLayoutEvidence(
                page_number=1,
                inspection_scale=" ",
                expected_roles=("response-space",),
                missing_roles=(),
                blank_regions=(),
            ),
        ),
    ],
)
def test_malformed_layout_evidence_fails_closed(pages):
    with pytest.raises(WorksheetLayoutQAError):
        evaluate_worksheet_layout(pages)


def test_layout_qa_has_no_external_write_surface():
    module = importlib.import_module("instructional_materials_coach.worksheet_layout_qa")
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
