"""Parse lesson content YAML into the placeholder-token dict the request builders use."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Mapping

import yaml

REQUIRED_KEYS = ("title", "objectives", "slides", "worksheet_questions")

# #3259 D1: slide indexes become dictionary-key components in
# placeholder_tokens(). Duplicate or unusable indexes silently erase authored
# content before terminal QA builds its expectations, so they must fail
# closed at parse time -- the earliest point where the full slide list is
# visible, before the lossy dict conversion.


def _canonical_slide_index(raw: Any, position: int) -> int:
    """Canonicalize a slide's authored ``index`` to a positive int.

    Accepts ``int`` (excluding ``bool``) or a string that parses as a
    base-10 integer (``"1"`` -> ``1``), closing the f-string type-erasure
    collision between ``"1"`` and ``1``. Everything else (missing, ``bool``,
    ``None``, float, blank/non-numeric string, non-positive) fails closed.
    """
    if isinstance(raw, bool):
        canonical = None
    elif isinstance(raw, int):
        canonical = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            canonical = int(raw.strip(), 10)
        except ValueError:
            canonical = None
    else:
        canonical = None
    if canonical is None or canonical < 1:
        raise ValueError(
            "content-spec-slide-index-invalid: "
            f"slide #{position} must carry a positive integer 'index'"
        )
    return canonical


def _validate_slide_indexes(slides: list[dict[str, Any]]) -> None:
    """Reject duplicate or invalid slide indexes before token conversion.

    Duplicate canonical indexes would let the later slide silently overwrite
    the earlier slide's placeholder tokens in placeholder_tokens(); invalid
    indexes (missing, bool, None, float, blank, non-positive) would either
    raise an unhandled KeyError downstream or produce template-unsupported
    token names. Both fail closed here instead.
    """
    seen: dict[int, int] = {}
    for position, slide in enumerate(slides, start=1):
        canonical = _canonical_slide_index(slide.get("index"), position)
        if canonical in seen:
            raise ValueError(
                "content-spec-duplicate-slide-index: "
                f"slide #{position} duplicates index {canonical} "
                f"already used by slide #{seen[canonical]}"
            )
        seen[canonical] = position


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
                key = f"slide_{index}_heading"
                # #3259 D1: a slide-derived key must never silently overwrite an
                # existing token. content_from_dict() rejects duplicates at
                # parse time; this guard protects direct LessonContent
                # construction that bypasses parse validation.
                if key in tokens:
                    raise ValueError(
                        f"content-spec-token-collision: slide token '{key}' "
                        "collides with an existing authored token"
                    )
                tokens[key] = slide["heading"]
            for bullet_index, bullet in enumerate(slide.get("bullets", []), start=1):
                key = f"slide_{index}_bullet_{bullet_index}"
                if key in tokens:
                    raise ValueError(
                        f"content-spec-token-collision: slide token '{key}' "
                        "collides with an existing authored token"
                    )
                tokens[key] = bullet
        for i, question in enumerate(self.worksheet_questions, start=1):
            tokens[f"question_{i}"] = question
        # Context is additive. It cannot replace authored lesson tokens.
        for key in sorted(self.context_tokens):
            if key in tokens:
                raise ValueError(f"Context token collides with authored lesson token: {key}")
            tokens[key] = self.context_tokens[key]
        return tokens

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
    slides = list(data["slides"])
    # #3259 D1: reject duplicate or invalid slide indexes before the lossy
    # placeholder-token conversion can erase authored content.
    _validate_slide_indexes(slides)
    return LessonContent(
        title=data["title"],
        objectives=list(data["objectives"]),
        slides=slides,
        worksheet_questions=list(data["worksheet_questions"]),
    )


def load_lesson_content(path: str | Path) -> LessonContent:
    data = yaml.safe_load(Path(path).read_text())
    return content_from_dict(data)
