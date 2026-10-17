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
    parse_lesson_revision_spec,
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


# ---------------------------------------------------------------------------
# Integration repair: governed spec parsing + terminal-QA wiring.
#
# The validator must actually execute in the production terminal-QA path
# (cli.py build --lesson-revision-spec -> build_from_requests ->
# evaluate_artifact_qa on the worksheet artifact), and the false-confidence
# conditions must hold: approximate/self-authored slide mappings are NOT
# verified teacher-owned deck evidence, approximate slide numbers never
# produce a clean acceptance, and missing evidence stays manual-review.
# ---------------------------------------------------------------------------

from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_LESSON_ALIGNMENT_UNVERIFIED,
    QA_STATE_LESSON_REVISION_MISMATCH,
    QA_STATE_VERIFIED,
    ArtifactObservation,
    TerminalQAExpectations,
    evaluate_artifact_qa,
)

_QA_KEY = "k" * 64
_DECK_FILENAME = "Marketing_Foundations_Day1_Convenience_Revised.pdf"


def _spec_dict(*, verified=False, synced=_DECK_REVISION, with_coverage=True):
    """Minimal governed spec; approximate markers unless verified=True."""
    spec = {
        "lesson_id": _LESSON_ID,
        "deck": {
            "revision_id": _DECK_REVISION,
            "filename": _DECK_FILENAME,
            "slide_mapping_source": (
                "teacher-owned deck read 2026-10-16"
                if verified
                else "issue-3577-body; exact slide read pending (approximate)"
            ),
        },
        "learning_targets": [{"id": target, "concept": target} for target in _DECK_TARGETS],
        "worksheet": {
            "lesson_id": _LESSON_ID,
            "synced_deck_revision_id": synced,
        },
    }
    if with_coverage:
        spec["coverage_matrix"] = [
            {
                "target_id": target,
                "deck_slide_note": (
                    "read from teacher-owned deck" if verified else "approximate slide"
                ),
                "worksheet_tasks": [f"task-{target}"],
            }
            for target in _DECK_TARGETS
        ]
    if verified:
        spec["deck_evidence"] = {
            "kind": "teacher-owned-deck-read",
            "filename": _DECK_FILENAME,
            "verified_at": "2026-10-16T00:00:00Z",
        }
    return spec


def _qa_report(spec_dict_or_none):
    spec = parse_lesson_revision_spec(spec_dict_or_none) if spec_dict_or_none else None
    expectations = TerminalQAExpectations(idempotency_key=_QA_KEY, lesson_revision=spec)
    observation = ArtifactObservation(
        artifact_type="docs", artifact_id="doc-1", revision_id="r1",
        full_text="worksheet text",
    )
    return evaluate_artifact_qa(
        artifact_type="docs", artifact_id="doc-1",
        expectations=expectations, observation=observation,
        placement_records=(), idempotency_key=_QA_KEY,
    )


def _codes(report):
    return [finding.code for finding in report.findings]


# --- Spec parsing: evidence provenance ---------------------------------------


def test_verified_deck_read_parses_verified() -> None:
    spec = parse_lesson_revision_spec(_spec_dict(verified=True))
    assert spec.deck_evidence_verified
    assert spec.approximate_evidence_refs == ()
    assert spec.deck_learning_target_ids == _DECK_TARGETS
    assert spec.worksheet_task_coverage is not None


def test_approximate_slide_mapping_is_not_verified_evidence() -> None:
    """Self-authored approximate mappings never count as verified
    teacher-owned deck evidence."""
    spec = parse_lesson_revision_spec(_spec_dict(verified=False))
    assert not spec.deck_evidence_verified
    assert spec.approximate_evidence_refs


def test_verified_claim_with_approximate_markers_is_rejected() -> None:
    """A spec claiming a verified teacher-owned deck read while carrying
    approximate slide markers is contradictory evidence: rejected, not
    silently downgraded."""
    spec_dict = _spec_dict(verified=False)
    spec_dict["deck_evidence"] = {
        "kind": "teacher-owned-deck-read",
        "filename": _DECK_FILENAME,
    }
    with pytest.raises(WorksheetRevisionQAError):
        parse_lesson_revision_spec(spec_dict)


def test_deck_evidence_naming_wrong_file_is_rejected() -> None:
    spec_dict = _spec_dict(verified=True)
    spec_dict["deck_evidence"]["filename"] = "Some_Other_Deck.pdf"
    with pytest.raises(WorksheetRevisionQAError):
        parse_lesson_revision_spec(spec_dict)


def test_coverage_entry_referencing_unknown_target_is_rejected() -> None:
    spec_dict = _spec_dict()
    spec_dict["coverage_matrix"][0]["target_id"] = "not-a-deck-target"
    with pytest.raises(WorksheetRevisionQAError):
        parse_lesson_revision_spec(spec_dict)


def test_missing_coverage_matrix_parses_unmeasured() -> None:
    spec = parse_lesson_revision_spec(_spec_dict(with_coverage=False))
    assert spec.worksheet_task_coverage is None


def test_committed_day1_sample_parses_as_unverified_evidence() -> None:
    """The committed Day 1 spec's slide mapping is explicitly approximate
    (slide_mapping_source + deck_slides_approx): it must parse as
    unverified evidence, never as verified deck evidence."""
    spec = parse_lesson_revision_spec(_load_day1_spec())
    assert not spec.deck_evidence_verified
    assert "deck.slide_mapping_source" in spec.approximate_evidence_refs
    assert set(spec.deck_learning_target_ids) == set(_DECK_TARGETS)
    assert spec.worksheet_task_coverage is not None


# --- Terminal-QA wiring: the gate actually executes ----------------------------


def test_verified_spec_with_full_coverage_can_pass_clean() -> None:
    report = _qa_report(_spec_dict(verified=True))
    assert report.state == QA_STATE_VERIFIED
    assert _codes(report) == []


def test_approximate_evidence_cannot_produce_clean_acceptance() -> None:
    """Approximate slide numbers + full coverage: the alignment gate must
    refuse a clean acceptance and route to manual review."""
    report = _qa_report(_spec_dict(verified=False))
    assert report.state == QA_STATE_LESSON_ALIGNMENT_UNVERIFIED
    assert report.state != QA_STATE_VERIFIED
    assert "qa-worksheet-alignment-deck-evidence-unverified" in _codes(report)


def test_missing_coverage_evidence_stays_manual_review() -> None:
    """Missing revised-PDF / unmeasured coverage evidence stays
    manual-review; it never passes and never hard-fails."""
    report = _qa_report(_spec_dict(with_coverage=False))
    assert report.state == QA_STATE_LESSON_ALIGNMENT_UNVERIFIED
    assert "qa-worksheet-alignment-coverage-unmeasured" in _codes(report)


def test_stale_revision_fails_in_terminal_qa() -> None:
    report = _qa_report(_spec_dict(synced="deck-rev-pre-convenience-2026-10-01"))
    assert report.state == QA_STATE_LESSON_REVISION_MISMATCH
    assert "qa-worksheet-stale-deck-revision" in _codes(report)


def test_uncovered_target_fails_in_terminal_qa() -> None:
    spec_dict = _spec_dict(verified=True)
    spec_dict["coverage_matrix"] = spec_dict["coverage_matrix"][:-1]
    report = _qa_report(spec_dict)
    assert report.state == QA_STATE_LESSON_REVISION_MISMATCH
    assert "qa-worksheet-learning-target-uncovered" in _codes(report)


def test_gate_not_armed_without_spec() -> None:
    """A build with no governed lesson-revision spec gets no alignment
    findings: the gate is opt-in per build, not invented evidence."""
    report = _qa_report(None)
    assert report.state == QA_STATE_VERIFIED
    assert not [code for code in _codes(report) if "alignment" in code or "stale-deck" in code]


def test_committed_day1_sample_never_passes_clean_in_qa() -> None:
    """End to end on the committed sample: its approximate slide mapping
    can never yield a clean terminal acceptance without a verified
    teacher-owned deck read."""
    report = _qa_report(_load_day1_spec())
    assert report.state != QA_STATE_VERIFIED
    assert "qa-worksheet-alignment-deck-evidence-unverified" in _codes(report)
