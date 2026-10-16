"""#3577: cross-artifact lesson-revision alignment regression tests.

Day 1 Marketing Foundations (Marketing Detectives) must stay synchronized
with the revised convenience deck: one shared lesson identity, the worksheet
declaring the exact deck revision it was synchronized against, and every deck
material learning target covered by at least one worksheet task. When the deck
moves to a new revision, a worksheet still declaring the older revision is
stale and fails. Unmeasured task coverage routes to manual review and never
receives a mechanical pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from instructional_materials_coach.worksheet_revision_qa import (
    WorksheetRevisionQAError,
    validate_lesson_revision_alignment,
)

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
DAY1_SPEC = SAMPLES / "marketing_foundations_day1_lesson.yaml"

# The deck revision and learning targets of the 2026-10-13 convenience revision
# (per #3577 body). The stale prior worksheet declared the pre-convenience deck.
_LESSON_ID = "marketing-foundations-day1"
_DECK_REVISION = "deck-rev-convenience-2026-10-13"
_DECK_TARGETS = (
    "product-disposable-vs-reusable",
    "place-shelf-placement",
    "price-convenience-premium",
    "place-vs-price-vs-product",
    "evidence-based-tradeoff",
)
_SYNCED_COVERAGE = (
    ("warm-up", ("product-disposable-vs-reusable",)),
    ("mission-1", ("product-disposable-vs-reusable",)),
    ("mission-2", ("place-shelf-placement", "place-vs-price-vs-product")),
    ("mission-3", ("price-convenience-premium", "evidence-based-tradeoff")),
    ("exit-ticket", ("place-vs-price-vs-product", "evidence-based-tradeoff")),
)


def _aligned(**overrides):
    kwargs = {
        "lesson_id": _LESSON_ID,
        "deck_revision_id": _DECK_REVISION,
        "deck_learning_target_ids": _DECK_TARGETS,
        "worksheet_lesson_id": _LESSON_ID,
        "worksheet_synced_deck_revision_id": _DECK_REVISION,
        "worksheet_task_coverage": _SYNCED_COVERAGE,
    }
    kwargs.update(overrides)
    return validate_lesson_revision_alignment(**kwargs)


def test_synced_worksheet_with_full_coverage_passes() -> None:
    result = _aligned()
    assert result.passed
    assert not result.manual_review_required
    assert result.findings == ()


def test_stale_deck_revision_fails() -> None:
    """Acceptance #3577(7): a worksheet synchronized against the older deck
    revision is rejected once the deck's material learning targets move."""
    result = _aligned(worksheet_synced_deck_revision_id="deck-rev-pre-convenience-2026-10-01")
    assert not result.passed
    codes = [finding.code for finding in result.findings]
    assert codes == ["worksheet-stale-deck-revision"]
    assert _DECK_REVISION in result.findings[0].message


def test_lesson_identity_mismatch_fails() -> None:
    result = _aligned(worksheet_lesson_id="marketing-foundations-day2")
    assert not result.passed
    codes = [finding.code for finding in result.findings]
    assert codes == ["worksheet-lesson-identity-mismatch"]


def test_uncovered_learning_target_fails() -> None:
    coverage = tuple(
        (task_id, tuple(t for t in targets if t != "price-convenience-premium"))
        for task_id, targets in _SYNCED_COVERAGE
    )
    result = _aligned(worksheet_task_coverage=coverage)
    assert not result.passed
    codes = [finding.code for finding in result.findings]
    assert codes == ["worksheet-learning-target-uncovered"]
    assert "price-convenience-premium" in result.findings[0].message


def test_unmeasured_coverage_routes_to_manual_review() -> None:
    result = _aligned(worksheet_task_coverage=None)
    assert result.passed
    assert result.manual_review_required
    codes = [finding.code for finding in result.findings]
    assert codes == ["worksheet-alignment-coverage-unmeasured"]


def test_coverage_of_undeclared_target_is_malformed() -> None:
    coverage = (("mission-1", ("not-a-deck-target",)),)
    with pytest.raises(WorksheetRevisionQAError):
        _aligned(worksheet_task_coverage=coverage)


def test_empty_deck_targets_is_malformed() -> None:
    with pytest.raises(WorksheetRevisionQAError):
        _aligned(deck_learning_target_ids=())


def test_blank_revision_identity_is_malformed() -> None:
    with pytest.raises(WorksheetRevisionQAError):
        _aligned(worksheet_synced_deck_revision_id="  ")


def _load_day1_spec() -> dict:
    return yaml.safe_load(DAY1_SPEC.read_text(encoding="utf-8"))


def _spec_coverage(spec: dict) -> tuple[tuple[str, tuple[str, ...]], ...]:
    by_task: dict[str, list[str]] = {}
    for row in spec["coverage_matrix"]:
        for task in row["worksheet_tasks"]:
            by_task.setdefault(task, []).append(row["concept"])
    return tuple((task, tuple(targets)) for task, targets in sorted(by_task.items()))


def test_governed_day1_spec_validates_clean() -> None:
    """The committed Day 1 lesson-revision spec (objectives, exact revision
    identities, coverage matrix) passes the alignment validator end to end."""
    spec = _load_day1_spec()
    worksheet = spec["worksheet"]
    result = validate_lesson_revision_alignment(
        lesson_id=spec["lesson_id"],
        deck_revision_id=spec["deck"]["revision_id"],
        deck_learning_target_ids=tuple(t["id"] for t in spec["learning_targets"]),
        worksheet_lesson_id=worksheet["lesson_id"],
        worksheet_synced_deck_revision_id=worksheet["synced_deck_revision_id"],
        worksheet_task_coverage=_spec_coverage(spec),
    )
    assert result.passed
    assert not result.manual_review_required


def test_governed_day1_spec_rejects_stale_worksheet_revision() -> None:
    """The same spec with the worksheet declaring the older deck revision
    (the stale Day1_Marketing_Detectives_Print_Ready_Review.docx lineage)
    fails the stale-revision finding."""
    spec = _load_day1_spec()
    worksheet = spec["worksheet"]
    result = validate_lesson_revision_alignment(
        lesson_id=spec["lesson_id"],
        deck_revision_id=spec["deck"]["revision_id"],
        deck_learning_target_ids=tuple(t["id"] for t in spec["learning_targets"]),
        worksheet_lesson_id=worksheet["lesson_id"],
        worksheet_synced_deck_revision_id="deck-rev-pre-convenience-2026-10-01",
        worksheet_task_coverage=_spec_coverage(spec),
    )
    assert not result.passed
    assert [f.code for f in result.findings] == ["worksheet-stale-deck-revision"]
