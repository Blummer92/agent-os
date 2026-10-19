"""Parse lesson content YAML into the placeholder-token dict the request builders use."""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any, Mapping

import yaml

REQUIRED_KEYS = ("title", "objectives", "slides", "worksheet_questions")

# Governed slide-scoped token convention: slide_<index>_heading and
# slide_<index>_bullet_<n>, where <index> is the authored slide["index"].
# This regex is the single source of truth for "slide-scoped" used by the
# request builders (identity threading) and terminal QA (location binding).
_SLIDE_SCOPED_TOKEN_RE = re.compile(r"slide_(\d+)_(?:heading|bullet_\d+)")


def slide_token_index(token_name: str) -> int | None:
    """Return the authored 1-based ``slide["index"]`` for a slide-scoped token name.

    Returns None for presentation-wide tokens (``title``, ``objective_N``,
    ``question_N``, context tokens). The token name is the ``{{...}}``
    interior, e.g. ``slide_2_heading``.
    """
    if not isinstance(token_name, str):
        return None
    match = _SLIDE_SCOPED_TOKEN_RE.fullmatch(token_name.strip())
    if match is None:
        return None
    return int(match.group(1))


@dataclasses.dataclass
class LessonContent:
    title: str
    objectives: list[str]
    slides: list[dict[str, Any]]
    worksheet_questions: list[str]
    context_tokens: dict[str, str] = dataclasses.field(default_factory=dict)

    def placeholder_tokens(self) -> dict[str, str]:
        tokens: dict[str, str] = {"title": self.title}
        for i, objective in enumerate(self.objectives, start=1):
            tokens[f"objective_{i}"] = objective
        for slide in self.slides:
            index = slide["index"]
            if "heading" in slide:
                tokens[f"slide_{index}_heading"] = slide["heading"]
            for bullet_index, bullet in enumerate(slide.get("bullets", []), start=1):
                tokens[f"slide_{index}_bullet_{bullet_index}"] = bullet
        for i, question in enumerate(self.worksheet_questions, start=1):
            tokens[f"question_{i}"] = question
        # Context is additive. It cannot replace authored lesson tokens.
        for key in sorted(self.context_tokens):
            if key in tokens:
                raise ValueError(f"Context token collides with authored lesson token: {key}")
            tokens[key] = self.context_tokens[key]
        return tokens

    def slide_token_indexes(self) -> dict[str, int]:
        """Map each slide-scoped token name to its authored 1-based slide index.

        Derived from the governed ``slides[].index`` values through the same
        token naming as :meth:`placeholder_tokens`; never inferred from any
        observed artifact. Presentation-wide tokens are absent from the map.
        """
        mapping: dict[str, int] = {}
        for name in self.placeholder_tokens():
            index = slide_token_index(name)
            if index is not None:
                mapping[name] = index
        return mapping

    def with_context_tokens(self, values: Mapping[str, str]) -> "LessonContent":
        merged = dict(self.context_tokens)
        for key, value in values.items():
            if not isinstance(key, str) or not key or not isinstance(value, str):
                raise ValueError("Context tokens must be non-empty string keys with string values")
            if key in merged and merged[key] != value:
                raise ValueError(f"Conflicting context token: {key}")
            merged[key] = value
        return dataclasses.replace(self, context_tokens=merged)


def content_from_dict(data: dict[str, Any]) -> LessonContent:
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        raise ValueError(f"Lesson content spec is missing required keys: {', '.join(missing)}")
    return LessonContent(
        title=data["title"],
        objectives=list(data["objectives"]),
        slides=list(data["slides"]),
        worksheet_questions=list(data["worksheet_questions"]),
    )


def load_lesson_content(path: str | Path) -> LessonContent:
    data = yaml.safe_load(Path(path).read_text())
    return content_from_dict(data)
