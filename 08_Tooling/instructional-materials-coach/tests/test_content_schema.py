"""Round-trip and malformed-response behaviour for the draft schema.

Requires the `genai` extra (pydantic); skips cleanly without it. The
dependency-free drift guard lives in `test_content_schema_drift.py`.
"""
from __future__ import annotations

import pytest

pytest.importorskip("pydantic", reason="requires the `genai` optional extra")

from pydantic import ValidationError  # noqa: E402

from instructional_materials_coach.content_schema import LessonDraft, SlideDraft  # noqa: E402

VALID = {
    "title": "Shot Composition",
    "objectives": ["Frame a subject", "Apply the rule of thirds"],
    "slides": [{"index": 1, "heading": "Welcome", "bullets": ["Hello", "Plan"]}],
    "worksheet_questions": ["What is the rule of thirds?"],
}


def test_draft_round_trips_into_canonical_lesson_content():
    content = LessonDraft(**VALID).to_lesson_content()
    tokens = content.placeholder_tokens()
    assert tokens["title"] == "Shot Composition"
    assert tokens["objective_2"] == "Apply the rule of thirds"
    assert tokens["slide_1_heading"] == "Welcome"
    assert tokens["slide_1_bullet_2"] == "Plan"
    assert tokens["question_1"] == "What is the rule of thirds?"


def test_empty_heading_is_omitted_so_no_blank_token_is_emitted():
    draft = LessonDraft(
        **{**VALID, "slides": [{"index": 1, "heading": "", "bullets": ["only"]}]}
    )
    assert "heading" not in draft.to_dict()["slides"][0]
    assert "slide_1_heading" not in draft.to_lesson_content().placeholder_tokens()


def test_missing_required_field_is_rejected():
    with pytest.raises(ValidationError):
        LessonDraft(**{k: v for k, v in VALID.items() if k != "title"})


def test_wrong_type_is_rejected():
    with pytest.raises(ValidationError):
        LessonDraft(**{**VALID, "objectives": "not a list"})


def test_malformed_slide_is_rejected():
    with pytest.raises(ValidationError):
        LessonDraft(**{**VALID, "slides": [{"heading": "no index"}]})


def test_slide_defaults_allow_a_bare_index():
    slide = SlideDraft(index=3)
    assert slide.heading == "" and slide.bullets == []


def test_draft_with_no_slides_still_converts():
    content = LessonDraft(**{**VALID, "slides": []}).to_lesson_content()
    assert content.placeholder_tokens()["title"] == "Shot Composition"
