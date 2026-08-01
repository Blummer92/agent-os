"""Typed schema Gemini fills, mirroring the canonical `content_spec.LessonContent`.

`content_spec.py` is canonical. These models exist only so the model returns
structured output that converts cleanly back into `LessonContent`; they must
never grow fields of their own. `tests/test_content_schema_drift.py` fails the
build if the two diverge.

Deliberately avoids unions, bare dicts, and recursion, which Gemini's
`response_schema` does not reliably support.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .content_spec import LessonContent, content_from_dict

# Explicit policy: an unexpected field is a signal the model misunderstood the
# contract, so reject it rather than silently dropping it (pydantic's default).
STRICT_FIELDS = ConfigDict(extra="forbid")


class SlideDraft(BaseModel):
    """One slide. Mirrors the dicts `content_spec` expects in `slides`."""

    model_config = STRICT_FIELDS

    index: int = Field(description="1-based slide position in the deck.")
    heading: str = Field(default="", description="Slide heading. Empty means no heading.")
    bullets: list[str] = Field(default_factory=list, description="Bullet lines for this slide.")


class LessonDraft(BaseModel):
    """Draft lesson content produced by a model.

    Field names match `content_spec.LessonContent` exactly and are checked by
    the drift test. Draft content only -- never an approved artifact.
    """

    model_config = STRICT_FIELDS

    title: str = Field(description="Lesson title.")
    objectives: list[str] = Field(description="Student-facing learning objectives.")
    slides: list[SlideDraft] = Field(description="Slides in presentation order.")
    worksheet_questions: list[str] = Field(description="Worksheet questions for students.")

    def to_dict(self) -> dict[str, Any]:
        """Plain dict in the shape `content_spec.content_from_dict` accepts."""
        return {
            "title": self.title,
            "objectives": list(self.objectives),
            "slides": [_slide_to_dict(slide) for slide in self.slides],
            "worksheet_questions": list(self.worksheet_questions),
        }

    def to_lesson_content(self) -> LessonContent:
        """Convert into the canonical `LessonContent` used by the renderers."""
        return content_from_dict(self.to_dict())


def _slide_to_dict(slide: SlideDraft) -> dict[str, Any]:
    data: dict[str, Any] = {"index": slide.index}
    if slide.heading:
        data["heading"] = slide.heading
    if slide.bullets:
        data["bullets"] = list(slide.bullets)
    return data
