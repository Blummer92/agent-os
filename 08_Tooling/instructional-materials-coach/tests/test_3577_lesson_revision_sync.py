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

import hashlib
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
from instructional_materials_coach.worksheet_revision_qa import (
    SourceContentReceipt,
    SourcePage,
    bind_source_evidence,
)

_QA_KEY = "k" * 64
_DECK_FILENAME = "Marketing_Foundations_Day1_Convenience_Revised.pdf"
_DRIVE_ID = "drive-deck-convenience-1"
_DRIVE_REVISION = "drv-rev-2026-10-13"


def _spec_dict(*, synced=_DECK_REVISION, with_coverage=True, approximate=False,
               slide_note="exact slide 1", drive_id=_DRIVE_ID, digest=None):
    """Governed spec assertion; evidence comes from an injected receipt."""
    deck = {
        "revision_id": _DECK_REVISION,
        "filename": _DECK_FILENAME,
        "drive_id": drive_id,
        "slide_mapping_source": (
            "issue-3577-body; exact slide mapping pending (approximate)"
            if approximate
            else "independent deck read via Drive"
        ),
    }
    if digest is not None:
        deck["content_digest"] = digest
    spec = {
        "lesson_id": _LESSON_ID,
        "deck": deck,
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
                    "approximate slide; pending teacher read"
                    if approximate
                    else slide_note
                ),
                "worksheet_tasks": [f"task-{target}"],
            }
            for target in _DECK_TARGETS
        ]
    return spec


def _pages(*slide_numbers):
    return tuple(
        SourcePage(
            page_number=i + 1,
            slide_number=n,
            text=f"Slide {n}: convenience content for {target}",
        )
        for i, (n, target) in enumerate(zip(slide_numbers, _DECK_TARGETS))
    )


def _receipt(*, drive_id=_DRIVE_ID, endorsed=True, pages=None, digest=None,
             filename=_DECK_FILENAME, revision_id=_DRIVE_REVISION):
    body = b"%PDF-1.4 fake deck bytes for " + drive_id.encode("utf-8")
    actual_digest = digest if digest is not None else "sha256:" + hashlib.sha256(body).hexdigest()
    return SourceContentReceipt(
        source_drive_id=drive_id,
        source_filename=filename,
        source_revision_id=revision_id,
        content_digest=actual_digest,
        pages=_pages(1, 2, 3, 4, 5) if pages is None else pages,
        retrieved_at="2026-10-16T12:00:00+00:00",
        source_provenance="drive-v3-files-get-media:" + drive_id,
        teacher_owner_identity="teacher@example.org" if endorsed else None,
        teacher_endorsed=endorsed,
    )


def _bind(spec_dict, **receipt_kwargs):
    return bind_source_evidence(parse_lesson_revision_spec(spec_dict),
                                _receipt(**receipt_kwargs))


def _persisted_text(spec_dict=None):
    """Persisted worksheet text carrying the trusted anchors + observed tasks."""
    spec = parse_lesson_revision_spec(spec_dict or _spec_dict())
    tasks = " ".join(task for task, _ in (spec.worksheet_task_coverage or ()))
    return (
        f"Lesson {spec.worksheet_lesson_id} worksheet synchronized against "
        f"{spec.worksheet_synced_deck_revision_id}. Tasks: {tasks}."
    )


def _qa_report(spec_dict_or_none, *, persisted=None, required=False, bind=True,
               **receipt_kwargs):
    spec = None
    if spec_dict_or_none:
        spec = parse_lesson_revision_spec(spec_dict_or_none)
        if bind:
            spec = bind_source_evidence(spec, _receipt(**receipt_kwargs))
    expectations = TerminalQAExpectations(
        idempotency_key=_QA_KEY, lesson_revision=spec,
        lesson_revision_required=required,
    )
    observation = ArtifactObservation(
        artifact_type="docs", artifact_id="doc-1", revision_id="r1",
        full_text=persisted if persisted is not None else _persisted_text(spec_dict_or_none),
    )
    return evaluate_artifact_qa(
        artifact_type="docs", artifact_id="doc-1",
        expectations=expectations, observation=observation,
        placement_records=(), idempotency_key=_QA_KEY,
    )


def _codes(report):
    return [finding.code for finding in report.findings]


# --- Spec parsing: YAML is an assertion, never a read receipt ----------------


def test_typed_yaml_deck_evidence_is_rejected() -> None:
    """A caller-typed ``deck_evidence`` record (``kind:
    teacher-owned-deck-read``) is self-authored fake evidence: YAML can never
    certify a deck read, so the spec is rejected outright, not parsed as
    verified."""
    spec_dict = _spec_dict()
    spec_dict["deck_evidence"] = {
        "kind": "teacher-owned-deck-read",
        "filename": _DECK_FILENAME,
        "verified_at": "2026-10-16T00:00:00Z",
    }
    with pytest.raises(WorksheetRevisionQAError):
        parse_lesson_revision_spec(spec_dict)


def test_typed_yaml_deck_evidence_with_wrong_kind_is_rejected() -> None:
    """Any ``deck_evidence`` mapping shape is rejected: evidence is
    independently injected, never declared in YAML."""
    spec_dict = _spec_dict()
    spec_dict["deck_evidence"] = {"kind": "unverified", "note": "pending read"}
    with pytest.raises(WorksheetRevisionQAError):
        parse_lesson_revision_spec(spec_dict)


def test_approximate_slide_mapping_parses_as_assertion() -> None:
    """Self-authored approximate mappings parse (assertion), but carry no
    source evidence and keep their approximate markers: they can never
    produce a clean acceptance downstream."""
    spec = parse_lesson_revision_spec(_spec_dict(approximate=True))
    assert spec.source_evidence is None
    assert spec.approximate_evidence_refs
    assert spec.deck_drive_id == _DRIVE_ID


def test_exact_slide_refs_are_parsed() -> None:
    spec = parse_lesson_revision_spec(_spec_dict())
    assert sorted(spec.exact_slide_refs) == sorted(
        (target, 1) for target in _DECK_TARGETS
    )
    assert spec.approximate_evidence_refs == ()


def test_coverage_entry_referencing_unknown_target_is_rejected() -> None:
    spec_dict = _spec_dict()
    spec_dict["coverage_matrix"][0]["target_id"] = "not-a-deck-target"
    with pytest.raises(WorksheetRevisionQAError):
        parse_lesson_revision_spec(spec_dict)


def test_missing_coverage_matrix_parses_unmeasured() -> None:
    spec = parse_lesson_revision_spec(_spec_dict(with_coverage=False))
    assert spec.worksheet_task_coverage is None


def test_committed_day1_sample_parses_without_source_evidence() -> None:
    """The committed Day 1 spec's slide mapping is explicitly approximate
    (slide_mapping_source + deck_slides_approx): it parses as an assertion
    with no source evidence and keeps its approximate markers."""
    spec = parse_lesson_revision_spec(_load_day1_spec())
    assert spec.source_evidence is None
    assert "deck.slide_mapping_source" in spec.approximate_evidence_refs
    assert set(spec.deck_learning_target_ids) == set(_DECK_TARGETS)
    assert spec.worksheet_task_coverage is not None


# --- Terminal-QA wiring: the gate actually executes ----------------------------


def test_bound_evidence_with_matching_persisted_tasks_passes_clean() -> None:
    """Positive: independently retrieved valid source content (injected
    receipt), teacher approval, validated slide refs, and persisted
    worksheet carrying the trusted anchors + observed tasks -> verified."""
    report = _qa_report(_spec_dict())
    assert report.state == QA_STATE_VERIFIED
    assert _codes(report) == []


def test_invented_exact_slide_fails_at_binding() -> None:
    """The reproduced slide-9999 counterexample: the spec references an
    invented exact slide absent from the independently retrieved pages, so
    the evidence binding fails before terminal QA."""
    with pytest.raises(WorksheetRevisionQAError):
        _bind(_spec_dict(slide_note="exact slide 9999"))


def test_foreign_deck_id_fails_at_binding() -> None:
    """A wrong/foreign Drive ID in the injected receipt cannot satisfy the
    spec's asserted canonical teacher-owned Drive ID."""
    with pytest.raises(WorksheetRevisionQAError):
        _bind(_spec_dict(), drive_id="drive-some-other-deck")


def test_digest_mismatch_fails_at_binding() -> None:
    """The spec asserts a content digest; retrieved bytes with a different
    digest fail the binding."""
    with pytest.raises(WorksheetRevisionQAError):
        _bind(_spec_dict(digest="sha256:" + "0" * 64))


def test_filename_mismatch_fails_at_binding() -> None:
    with pytest.raises(WorksheetRevisionQAError):
        _bind(_spec_dict(), filename="Some_Other_Deck.pdf")


def test_missing_drive_id_in_spec_fails_at_binding() -> None:
    """Without an asserted canonical Drive ID the retrieved source cannot
    be attributed to the declared deck: binding is refused."""
    with pytest.raises(WorksheetRevisionQAError):
        _bind(_spec_dict(drive_id=None))


def test_unapproved_receipt_routes_to_manual_review() -> None:
    """Content evidence without a teacher ownership/approval assertion stays
    manual-review: hashes bind bytes, never teacher approval."""
    report = _qa_report(_spec_dict(), endorsed=False)
    assert report.state == QA_STATE_LESSON_ALIGNMENT_UNVERIFIED
    assert report.state != QA_STATE_VERIFIED
    assert "qa-worksheet-alignment-teacher-approval-unverified" in _codes(report)


def test_unverifiable_slide_refs_route_to_manual_review() -> None:
    """Exact slide references against a metadata-only receipt (no retrieved
    pages) cannot be validated: manual review, never clean acceptance."""
    report = _qa_report(_spec_dict(), pages=())
    bound = _bind(_spec_dict(), pages=())
    assert not bound.slide_refs_validated
    assert report.state == QA_STATE_LESSON_ALIGNMENT_UNVERIFIED
    assert "qa-worksheet-alignment-slide-refs-unverifiable" in _codes(report)


def test_approximate_evidence_cannot_produce_clean_acceptance() -> None:
    """Approximate slide markers + bound evidence: the alignment gate must
    refuse a clean acceptance and route to manual review."""
    report = _qa_report(_spec_dict(approximate=True))
    assert report.state == QA_STATE_LESSON_ALIGNMENT_UNVERIFIED
    assert report.state != QA_STATE_VERIFIED
    assert "qa-worksheet-alignment-approximate-evidence" in _codes(report)


def test_missing_source_evidence_stays_manual_review() -> None:
    """No injected receipt (the authentic Day-1 PDF is unavailable): the
    alignment gate routes to MANUAL REVIEW — not verified, not failed."""
    report = _qa_report(_spec_dict(), bind=False)
    assert report.state == QA_STATE_LESSON_ALIGNMENT_UNVERIFIED
    assert report.state != QA_STATE_VERIFIED
    assert "qa-worksheet-alignment-source-unverified" in _codes(report)


def test_missing_coverage_evidence_stays_manual_review() -> None:
    """Unmeasured task coverage stays manual-review; it never passes and
    never hard-fails."""
    report = _qa_report(_spec_dict(with_coverage=False))
    assert report.state == QA_STATE_LESSON_ALIGNMENT_UNVERIFIED
    assert "qa-worksheet-alignment-coverage-unmeasured" in _codes(report)


def test_stale_revision_fails_in_terminal_qa() -> None:
    report = _qa_report(_spec_dict(synced="deck-rev-pre-convenience-2026-10-01"))
    assert report.state == QA_STATE_LESSON_REVISION_MISMATCH
    assert "qa-worksheet-stale-deck-revision" in _codes(report)


def test_stale_persisted_worksheet_fails_in_terminal_qa() -> None:
    """The reproduced stale-Day-8 counterexample: the persisted worksheet
    text carries none of the trusted lesson/revision/task anchors, so
    terminal QA fails even though the YAML declarations are internally
    consistent."""
    report = _qa_report(
        _spec_dict(), persisted="Stale Day 8 worksheet: draw a logo."
    )
    assert report.state == QA_STATE_LESSON_REVISION_MISMATCH
    assert "qa-worksheet-persisted-revision-mismatch" in _codes(report)


def test_unobserved_task_fails_in_terminal_qa() -> None:
    """A YAML-declared worksheet task absent from the persisted worksheet
    fails: coverage requires observed tasks, not YAML-declared names."""
    persisted = _persisted_text(_spec_dict()).replace("task-price-convenience-premium", "something-else")
    report = _qa_report(_spec_dict(), persisted=persisted)
    assert report.state == QA_STATE_LESSON_REVISION_MISMATCH
    assert "qa-worksheet-task-not-observed" in _codes(report)


def test_uncovered_target_fails_in_terminal_qa() -> None:
    spec_dict = _spec_dict()
    spec_dict["coverage_matrix"] = spec_dict["coverage_matrix"][:-1]
    report = _qa_report(spec_dict, persisted=_persisted_text(spec_dict))
    assert report.state == QA_STATE_LESSON_REVISION_MISMATCH
    assert "qa-worksheet-learning-target-uncovered" in _codes(report)


def test_required_but_missing_spec_fails_in_terminal_qa() -> None:
    """Defense in depth: expectations armed as required without a spec fail
    terminal QA instead of silently disabling the gate."""
    report = _qa_report(None, required=True)
    assert report.state == QA_STATE_LESSON_REVISION_MISMATCH
    assert "qa-lesson-revision-required-but-missing" in _codes(report)


def test_gate_not_armed_without_spec() -> None:
    """A build with no governed lesson-revision spec and no declared
    dependency gets no alignment findings: the gate is opt-in per build,
    not invented evidence. Unaffected legacy lessons stay unaffected."""
    report = _qa_report(None)
    assert report.state == QA_STATE_VERIFIED
    assert not [code for code in _codes(report) if "alignment" in code or "stale-deck" in code]


def test_gate_armed_for_required_build_without_spec_change() -> None:
    """A required gate stays armed through expectations: required=True is
    bound into the expectations hash so recovered QA cannot cross a
    changed gate."""
    report = _qa_report(_spec_dict(), required=True)
    assert report.state == QA_STATE_VERIFIED
    assert _codes(report) == []


def test_committed_day1_sample_never_passes_clean_in_qa() -> None:
    """End to end on the committed sample: its approximate slide mapping
    and missing independent source receipt can never yield a clean terminal
    acceptance."""
    report = _qa_report(_load_day1_spec(), bind=False,
                        persisted=_persisted_text())
    assert report.state != QA_STATE_VERIFIED
    assert "qa-worksheet-alignment-source-unverified" in _codes(report)
