"""#3258 D3: slide-location integrity for text content expectations.

Drives the real Slides request builder (identity threading), the real
``TerminalQAExpectations.build_from_requests()``, and the real
``evaluate_artifact_qa()`` -- no mocks of the functions under test.

Covered: slide-scoped expectations carry ``location_hint`` bound from the
authored ``LessonContent.slides[].index``; correctly-ordered decks stay
VERIFIED; swapped slide content fails closed; missing content is
content-missing; a slide-scoped expectation whose hint is absent or
unresolvable fails closed (``qa-location-hint-invalid`` /
``evidence-incomplete``) instead of silently widening scope; and the
QA-only request metadata never reaches the Slides API.
"""
from __future__ import annotations

from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_CONTENT_MISSING,
    QA_STATE_EVIDENCE_INCOMPLETE,
    QA_STATE_VERIFIED,
    ArtifactObservation,
    ContentExpectation,
    TerminalQAExpectations,
    evaluate_artifact_qa,
    normalize_text,
)
from instructional_materials_coach.content_spec import content_from_dict
from instructional_materials_coach.slides_requests import (
    QA_SLIDE_INDEX_KEY,
    build_slides_replace_requests,
)
from instructional_materials_coach.workspace_clients import apply_slides_requests

IDEMPOTENCY = "d3-slide-location-tests"
ARTIFACT_ID = "pres-d3"
REVISION = "rev-d3"

CONTENT = {
    "title": "Candy Branding",
    "objectives": [],
    "slides": [
        {
            "index": 1,
            "heading": "Slide One: Brand Voice",
            "bullets": ["Speak with playful confidence", "Never promise sugar-free magic"],
        },
        {
            "index": 2,
            "heading": "Slide Two: Packaging Rules",
            "bullets": ["Seal every wrapper airtight", "Stamp the batch code on the base"],
        },
    ],
    "worksheet_questions": [],
}

TITLE_TEXT = "Candy Branding"
SLIDE1_TEXT = (
    "Slide One: Brand Voice Speak with playful confidence Never promise sugar-free magic"
)
SLIDE2_TEXT = (
    "Slide Two: Packaging Rules Seal every wrapper airtight Stamp the batch code on the base"
)


def _expectations() -> TerminalQAExpectations:
    lesson = content_from_dict(CONTENT)
    requests = build_slides_replace_requests(lesson)
    return TerminalQAExpectations.build_from_requests(
        idempotency_key=IDEMPOTENCY,
        slides_requests=tuple(requests),
    )


def _observe(*, slide_texts: tuple[str, ...]) -> ArtifactObservation:
    full_text = " ".join(slide_texts)
    return ArtifactObservation(
        artifact_type="slides",
        artifact_id=ARTIFACT_ID,
        revision_id=REVISION,
        full_text=normalize_text(full_text),
        slide_texts=tuple(normalize_text(t) for t in slide_texts),
    )


def _codes(report) -> list[str]:  # noqa: ANN001
    return [finding.code for finding in report.findings]


# ---------------------------------------------------------------------------
# Identity threading: builder -> expectations
# ---------------------------------------------------------------------------


def test_slide_scoped_expectations_carry_authored_location_hints():
    expectations = _expectations()
    assert len(expectations.slides_content) == 7
    by_token = {e.token: e for e in expectations.slides_content}
    # Slide-scoped tokens are bound to their authored slide index.
    assert by_token["{{slide_1_heading}}"].location_hint == {"slide_index": 1}
    assert by_token["{{slide_1_bullet_1}}"].location_hint == {"slide_index": 1}
    assert by_token["{{slide_1_bullet_2}}"].location_hint == {"slide_index": 1}
    assert by_token["{{slide_2_heading}}"].location_hint == {"slide_index": 2}
    assert by_token["{{slide_2_bullet_1}}"].location_hint == {"slide_index": 2}
    assert by_token["{{slide_2_bullet_2}}"].location_hint == {"slide_index": 2}
    # Presentation-wide tokens stay global.
    assert by_token["{{title}}"].location_hint is None


def test_qa_metadata_key_is_qa_only_and_threaded():
    lesson = content_from_dict(CONTENT)
    requests = build_slides_replace_requests(lesson)
    keyed = [r for r in requests if QA_SLIDE_INDEX_KEY in r]
    assert len(keyed) == 6
    assert all(r[QA_SLIDE_INDEX_KEY] in (1, 2) for r in keyed)
    # The API shape is untouched: replaceAllText carries no QA metadata.
    for request in requests:
        assert QA_SLIDE_INDEX_KEY not in request["replaceAllText"]


def test_apply_slides_requests_strips_qa_metadata_before_api_call():
    lesson = content_from_dict(CONTENT)
    requests = build_slides_replace_requests(lesson)
    assert any(QA_SLIDE_INDEX_KEY in r for r in requests)
    captured: dict = {}

    class _Batch:
        def __init__(self, body):
            self._body = body

        def execute(self):  # noqa: ANN202
            captured.update(self._body)
            return {
                "replies": [
                    {"replaceAllText": {"occurrencesChanged": 1}}
                    for _ in self._body["requests"]
                ]
            }

    class _Presentations:
        def batchUpdate(self, *, presentationId, body):  # noqa: ANN202, N803
            assert presentationId == "pres-1"
            return _Batch(body)

    class _Service:
        def presentations(self):  # noqa: ANN202
            return _Presentations()

    apply_slides_requests(_Service(), "pres-1", list(requests))
    sent = captured["requests"]
    assert len(sent) == len(requests)
    assert all(QA_SLIDE_INDEX_KEY not in r for r in sent)
    assert all(set(r) == {"replaceAllText"} for r in sent)


# ---------------------------------------------------------------------------
# Location-bound evaluation
# ---------------------------------------------------------------------------


def test_correctly_ordered_deck_stays_verified():
    report = evaluate_artifact_qa(
        artifact_type="slides",
        artifact_id=ARTIFACT_ID,
        expectations=_expectations(),
        observation=_observe(slide_texts=(TITLE_TEXT, SLIDE1_TEXT, SLIDE2_TEXT)),
        placement_records=(),
        idempotency_key=IDEMPOTENCY,
    )
    assert report.state == QA_STATE_VERIFIED
    assert report.findings == ()


def test_swapped_slide_content_fails_closed():
    report = evaluate_artifact_qa(
        artifact_type="slides",
        artifact_id=ARTIFACT_ID,
        expectations=_expectations(),
        observation=_observe(slide_texts=(TITLE_TEXT, SLIDE2_TEXT, SLIDE1_TEXT)),
        placement_records=(),
        idempotency_key=IDEMPOTENCY,
    )
    assert report.state == QA_STATE_CONTENT_MISSING
    assert report.state != QA_STATE_VERIFIED
    assert "qa-content-missing" in _codes(report)


def test_missing_slide_content_is_content_missing():
    rendered = [TITLE_TEXT, SLIDE1_TEXT, SLIDE2_TEXT]
    rendered = [t.replace("Stamp the batch code on the base", "") for t in rendered]
    report = evaluate_artifact_qa(
        artifact_type="slides",
        artifact_id=ARTIFACT_ID,
        expectations=_expectations(),
        observation=_observe(slide_texts=tuple(rendered)),
        placement_records=(),
        idempotency_key=IDEMPOTENCY,
    )
    assert report.state == QA_STATE_CONTENT_MISSING
    assert "qa-content-missing" in _codes(report)


def test_slide_scoped_expectation_without_hint_fails_closed():
    """A slide-scoped expectation that lost its hint (legacy/hand-built
    requests) must fail closed, never silently widen to the whole deck."""
    legacy_requests = (
        {
            "replaceAllText": {
                "containsText": {"text": "{{slide_1_heading}}", "matchCase": True},
                "replaceText": "Slide One: Brand Voice",
            }
        },
    )
    expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key=IDEMPOTENCY, slides_requests=legacy_requests
    )
    assert expectations.slides_content[0].location_hint is None
    # The content IS present on slide 1 -- a scope-widening evaluator would
    # verify; the fail-closed evaluator must refuse instead.
    report = evaluate_artifact_qa(
        artifact_type="slides",
        artifact_id=ARTIFACT_ID,
        expectations=expectations,
        observation=_observe(slide_texts=(TITLE_TEXT, SLIDE1_TEXT, SLIDE2_TEXT)),
        placement_records=(),
        idempotency_key=IDEMPOTENCY,
    )
    assert report.state == QA_STATE_EVIDENCE_INCOMPLETE
    assert "qa-location-hint-invalid" in _codes(report)


def test_unresolvable_hint_index_fails_closed():
    expectations = TerminalQAExpectations(
        idempotency_key=IDEMPOTENCY,
        slides_content=(
            ContentExpectation(
                artifact_type="slides",
                token="{{slide_9_heading}}",
                expected_text="Slide Nine",
                location_hint={"slide_index": 9},
            ),
        ),
    )
    report = evaluate_artifact_qa(
        artifact_type="slides",
        artifact_id=ARTIFACT_ID,
        expectations=expectations,
        observation=_observe(slide_texts=(TITLE_TEXT, SLIDE1_TEXT, SLIDE2_TEXT)),
        placement_records=(),
        idempotency_key=IDEMPOTENCY,
    )
    assert report.state == QA_STATE_EVIDENCE_INCOMPLETE
    assert "qa-location-hint-invalid" in _codes(report)


def test_presentation_wide_title_expectation_stays_global():
    expectations = TerminalQAExpectations(
        idempotency_key=IDEMPOTENCY,
        slides_content=(
            ContentExpectation(
                artifact_type="slides", token="<redacted>",
                expected_text="Candy Branding",
            ),
        ),
    )
    report = evaluate_artifact_qa(
        artifact_type="slides",
        artifact_id=ARTIFACT_ID,
        expectations=expectations,
        observation=_observe(slide_texts=(TITLE_TEXT, SLIDE1_TEXT, SLIDE2_TEXT)),
        placement_records=(),
        idempotency_key=IDEMPOTENCY,
    )
    assert report.state == QA_STATE_VERIFIED


def test_docs_slide_tokens_are_not_location_scoped():
    """Docs have no slide structure: slide_* tokens there keep whole-doc
    scope (behavior preserved)."""
    expectations = TerminalQAExpectations(
        idempotency_key=IDEMPOTENCY,
        docs_content=(
            ContentExpectation(
                artifact_type="docs", token="{{slide_1_heading}}",
                expected_text="Slide One: Brand Voice",
            ),
        ),
    )
    observation = ArtifactObservation(
        artifact_type="docs",
        artifact_id="doc-1",
        revision_id=REVISION,
        full_text="Worksheet opener. Slide One: Brand Voice. Questions follow.",
    )
    report = evaluate_artifact_qa(
        artifact_type="docs",
        artifact_id="doc-1",
        expectations=expectations,
        observation=observation,
        placement_records=(),
        idempotency_key=IDEMPOTENCY,
    )
    assert report.state == QA_STATE_VERIFIED
