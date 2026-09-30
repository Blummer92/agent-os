"""Regression for #2735: worksheet pagination must not strand large avoidable
vertical bands while the next bounded mission block would fit safely."""

from pathlib import Path

import pytest

from worksheet_layout_qa.pagination_balance import (
    PageComposition,
    evaluate_pagination_balance,
)

ROOT = Path(__file__).resolve().parents[2]
MATERIAL_RUBRIC = ROOT / "01_Shared_Standards/instructional-design/material-quality-rubric.md"
DESIGN_SYSTEM = (
    ROOT / "01_Shared_Standards/instructional-design/instructional-materials-design-system.md"
)


# --- Mechanical QA rule: the #2735 failure mode -------------------------------


def test_large_band_with_fitting_next_block_is_flagged() -> None:
    """A page with a large unused band after the Grades mission while the next
    mission would fit safely must be flagged for reflow."""
    result = evaluate_pagination_balance(
        [
            PageComposition(
                page_index=2,
                unused_band=300.0,
                next_block_height=200.0,
                block_separation=24.0,
            ),
        ]
    )
    assert not result.balanced
    assert not result.needs_manual_review
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.page_index == 2
    assert finding.unused_band == 300.0
    assert finding.next_block_height == 200.0


def test_exact_safe_fit_is_flagged() -> None:
    """A band that exactly fits the next block plus its separation is avoidable."""
    result = evaluate_pagination_balance(
        [PageComposition(page_index=0, unused_band=224.0, next_block_height=200.0, block_separation=24.0)]
    )
    assert len(result.findings) == 1


def test_block_that_does_not_fit_is_not_flagged() -> None:
    """A small band that cannot hold the next block is not a defect."""
    result = evaluate_pagination_balance(
        [PageComposition(page_index=0, unused_band=100.0, next_block_height=200.0, block_separation=24.0)]
    )
    assert result.balanced
    assert not result.findings


def test_no_following_block_is_not_flagged() -> None:
    """The last page of a worksheet has no next block and must pass."""
    result = evaluate_pagination_balance(
        [PageComposition(page_index=3, unused_band=500.0, next_block_height=0.0, block_separation=24.0)]
    )
    assert result.balanced


def test_balanced_worksheet_passes() -> None:
    """Evenly composed pages with no avoidable bands pass."""
    result = evaluate_pagination_balance(
        [
            PageComposition(page_index=0, unused_band=60.0, next_block_height=400.0, block_separation=24.0),
            PageComposition(page_index=1, unused_band=80.0, next_block_height=350.0, block_separation=24.0),
            PageComposition(page_index=2, unused_band=120.0, next_block_height=0.0, block_separation=24.0),
        ]
    )
    assert result.balanced
    assert not result.needs_manual_review


def test_unmeasured_page_is_not_passed() -> None:
    """When block heights cannot be established, the dimension must go to
    manual review instead of getting a mechanical pass."""
    result = evaluate_pagination_balance(
        [
            PageComposition(page_index=0, unused_band=60.0, next_block_height=400.0, block_separation=24.0),
            PageComposition(page_index=1, unused_band=0.0, next_block_height=0.0, block_separation=0.0, measured=False),
        ]
    )
    assert result.needs_manual_review
    assert result.unmeasured_pages == (1,)
    assert all(finding.page_index != 1 for finding in result.findings)


@pytest.mark.parametrize(
    "field,value",
    (
        ("unused_band", -1.0),
        ("next_block_height", -5.0),
        ("block_separation", -0.5),
    ),
)
def test_negative_heights_are_rejected(field: str, value: float) -> None:
    kwargs = {"page_index": 0, "unused_band": 0.0, "next_block_height": 0.0, "block_separation": 0.0}
    kwargs[field] = value
    with pytest.raises(ValueError):
        evaluate_pagination_balance([PageComposition(**kwargs)])


def test_negative_page_index_is_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate_pagination_balance(
            [PageComposition(page_index=-1, unused_band=0.0, next_block_height=0.0, block_separation=0.0)]
        )


# --- Standard documents carry the rule --------------------------------------


RUBRIC_PHRASES = (
    "### Worksheet vertical pagination balance",
    "Use\navailable vertical page space before introducing a page break",
    "A band is *avoidable* when it equals or exceeds the\nnext block's height plus the separation that block needs",
    "screenshots remain readable at their instructional size",
    "Kami writing and annotation response areas stay large enough for student\n  use",
    "no crowding, clipping, or overlap is introduced",
    "balance\ndensity across pages instead of moving the compression downstream",
    "Intentional whitespace that serves pacing, transitions,\nor readability is not a defect",
    "route the pagination-balance\ndimension to rendered/manual review",
)


def test_rubric_carries_pagination_balance_review_dimension() -> None:
    content = MATERIAL_RUBRIC.read_text(encoding="utf-8")
    for phrase in RUBRIC_PHRASES:
        assert phrase in content, f"missing rubric pagination-balance rule: {phrase!r}"


def test_rubric_changelog_records_2735() -> None:
    content = MATERIAL_RUBRIC.read_text(encoding="utf-8")
    assert "(#2735)" in content


def test_design_system_checks_vertical_page_space() -> None:
    content = DESIGN_SYSTEM.read_text(encoding="utf-8")
    assert "Does it use available vertical page space before introducing a page break" in content
    assert "(#2735)" in content
