"""Regression for #3566: Day 1 worksheet-quality verification pins.

#3566 stays the single bounded owner of the Day 1 Marketing Detectives
worksheet-quality regression. These tests pin ONLY the mechanically governed
dimensions of its 10-item verification list:

- (6) balanced pagination: reuse of src/worksheet_layout_qa/pagination_balance
  (rendered-evidence side) alongside the #3416 structural keep-with-next check
  pinned in the instructional-materials-coach suite.
- (10) rendered-review gate: unmeasured evidence routes to manual review and
  never receives a mechanical pass; the rubric's Rendered Classroom Review
  Gate is the named human owner.

PARKED (documented, not implemented):
- (4) table/cell spacing and (7-rendered) worksheet rendered placement/scale:
  need the #3258 rendered-layout acceptance ownership determination
  (evidence producer + governed consumer) — not yet named.
- (1) on-grade readability, (2) directions conciseness, (5) response-area
  size: no governed thresholds exist, and inventing universal thresholds is
  forbidden by standing policy.
- (8) grayscale print usability: no standard and no validator exist.
- (3) scaffold appropriateness: inherently comparative judgment; the
  implementable slice is input-assertion plus teacher-review routing, not the
  judgment itself.
- (9-completeness) warm-up/exit-ticket instructional completeness: human-scored
  under the rubric's "Worksheet usability" row; presence is pinned in the
  instructional-materials-coach suite.

No production code is changed by this file; no thresholds are invented.
"""

from pathlib import Path

from worksheet_layout_qa.pagination_balance import (
    PageComposition,
    evaluate_pagination_balance,
)

ROOT = Path(__file__).resolve().parents[2]
MATERIAL_RUBRIC = ROOT / "01_Shared_Standards/instructional-design/material-quality-rubric.md"


# --- (6) Balanced pagination: governed evaluator reuse -----------------------


def test_day1_balanced_four_page_worksheet_passes() -> None:
    """A Day 1 worksheet whose pages have no avoidable unused bands passes the
    governed pagination-balance rule (warm-up, two missions, exit ticket)."""
    result = evaluate_pagination_balance(
        [
            PageComposition(page_index=0, unused_band=40.0, next_block_height=300.0, block_separation=24.0),
            PageComposition(page_index=1, unused_band=90.0, next_block_height=260.0, block_separation=24.0),
            PageComposition(page_index=2, unused_band=70.0, next_block_height=220.0, block_separation=24.0),
            PageComposition(page_index=3, unused_band=150.0, next_block_height=0.0, block_separation=24.0),
        ]
    )
    assert result.balanced
    assert not result.needs_manual_review
    assert not result.findings


def test_day1_avoidable_unused_band_is_flagged() -> None:
    """The Day 1 defect mode for verification item (6): a page whose unused
    band could have held the next mission block must be flagged for reflow."""
    result = evaluate_pagination_balance(
        [
            PageComposition(page_index=0, unused_band=40.0, next_block_height=300.0, block_separation=24.0),
            PageComposition(page_index=1, unused_band=320.0, next_block_height=200.0, block_separation=24.0),
        ]
    )
    assert not result.balanced
    assert not result.needs_manual_review
    assert [finding.page_index for finding in result.findings] == [1]


def test_day1_unmeasured_page_never_gets_a_mechanical_pass() -> None:
    """Verification item (10): when rendered layout facts are unavailable for a
    Day 1 page, the pagination-balance dimension routes to manual review
    instead of passing."""
    result = evaluate_pagination_balance(
        [
            PageComposition(page_index=0, unused_band=40.0, next_block_height=300.0, block_separation=24.0),
            PageComposition(page_index=1, unused_band=0.0, next_block_height=0.0, block_separation=0.0, measured=False),
        ]
    )
    assert result.needs_manual_review
    assert result.unmeasured_pages == (1,)
    assert all(finding.page_index != 1 for finding in result.findings)


# --- Governing standards carry the rules this regression relies on ------------


def test_rubric_carries_pagination_balance_review_dimension() -> None:
    """#3566 verification item (6) relies on the rubric's worksheet vertical
    pagination-balance review dimension existing as a governed ship gate."""
    content = MATERIAL_RUBRIC.read_text(encoding="utf-8")
    assert "### Worksheet vertical pagination balance" in content
    assert "(#2735)" in content


def test_rubric_carries_rendered_classroom_review_gate() -> None:
    """#3566 verification item (10): the Rendered Classroom Review Gate is the
    named human owner of rendered-page judgments; the mechanical components
    here only hook into it."""
    content = MATERIAL_RUBRIC.read_text(encoding="utf-8")
    assert "Rendered Classroom Review Gate" in content
    assert "manual-review-required" in content
