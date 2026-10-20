"""Parse lesson content YAML into the placeholder-token dict the request builders use."""
from __future__ import annotations

import dataclasses
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping

import yaml

REQUIRED_KEYS = ("title", "objectives", "slides", "worksheet_questions")
#: Optional authored lesson-identity binding (#3582). When the authored
#: objectives are explicitly empty, the lesson-content adapter fills them from
#: the verified lesson only if this binding exactly names the selected lesson.
#: The title is not canonical identity and is never used as the matching rule.
LESSON_IDENTITY_KEY = "lesson_identity"
LESSON_IDENTITY_KEYS = frozenset({"day_lesson_number"})


def _visible_text(value: object) -> bool:
    """True for text carrying at least one visible character.

    Zero-width/format characters (Unicode category Cf) are invisible: a
    "non-empty" string of only ``\\u200b``/``\\u200c``/``\\u200d``/``\\ufeff``
    carries no readable content and must not satisfy a required-text rule.
    """
    if not isinstance(value, str):
        return False
    return bool("".join(char for char in value if unicodedata.category(char) != "Cf").strip())

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
        if not isinstance(slide, Mapping):
            raise ValueError(
                f"content-spec-slide-index-invalid: slide #{position} must be a mapping"
            )
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
    #: Independent authored lesson-identity binding, e.g.
    #: ``{"day_lesson_number": "Day 1"}``. Optional; when the authored
    #: objectives are empty, the #3582 adapter requires it to exactly match
    #: the selected lesson before adopting governed objectives.
    lesson_identity: dict[str, str] | None = None

    def placeholder_tokens(self) -> dict[str, str]:
        tokens: dict[str, str] = {"title": self.title}
        for i, objective in enumerate(self.objectives, start=1):
            tokens[f"objective_{i}"] = objective
        for position, slide in enumerate(self.slides, start=1):
            index = _canonical_slide_index(slide.get("index"), position)
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


def _require_text_list(value: object, field: str) -> list[str]:
    """Reject scalar (or otherwise non-list) authored text fields.

    A YAML scalar such as ``worksheet_questions: "Why?"`` must not be split
    into characters; it is malformed input, not a one-question list.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise ValueError(f"Lesson content spec field {field!r} must be a list of text")
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"Lesson content spec field {field!r} must be a list of text")
    return list(value)


def _require_slide_list(value: object) -> list[dict[str, Any]]:
    """Reject scalar or structurally malformed authored slide lists.

    An empty list parses (other Coach paths accept slide-less content); the
    #3582 adapter requires non-empty slides separately. Each present slide
    must be a mapping with a usable index and text bullets so composition
    never raises mid-build.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise ValueError("Lesson content spec field 'slides' must be a list of slide mappings")
    _validate_slide_indexes(value)
    slides: list[dict[str, Any]] = []
    for position, slide in enumerate(value):
        if not isinstance(slide, Mapping):
            raise ValueError(f"Lesson content spec slide #{position + 1} must be a mapping")
        index = slide.get("index")
        if isinstance(index, bool) or not isinstance(index, (int, str)) or (
            isinstance(index, str) and not index.strip()
        ):
            raise ValueError(f"Lesson content spec slide #{position + 1} must carry a usable 'index'")
        heading = slide.get("heading")
        if "heading" in slide and not isinstance(heading, str):
            raise ValueError(f"Lesson content spec slide #{position + 1} 'heading' must be text")
        bullets = slide.get("bullets", [])
        if (
            isinstance(bullets, (str, bytes))
            or not isinstance(bullets, list)
            or any(not isinstance(bullet, str) for bullet in bullets)
        ):
            raise ValueError(f"Lesson content spec slide #{position + 1} 'bullets' must be a list of text")
        slides.append({**slide, "index": _canonical_slide_index(index, position + 1)})
    return slides


def _require_lesson_identity(value: object) -> dict[str, str] | None:
    """Parse the optional independent authored lesson-identity binding."""
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value.keys()) != LESSON_IDENTITY_KEYS:
        raise ValueError(
            "Lesson content spec 'lesson_identity' must carry exactly 'day_lesson_number'"
        )
    day = value.get("day_lesson_number")
    if not isinstance(day, str) or not day.strip():
        raise ValueError("Lesson content spec 'lesson_identity.day_lesson_number' must be non-empty text")
    return {"day_lesson_number": day}


def content_from_dict(data: dict[str, Any]) -> LessonContent:
    if not isinstance(data, Mapping):
        raise ValueError("Lesson content spec must be a mapping of the required lesson keys")
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        raise ValueError(f"Lesson content spec is missing required keys: {', '.join(missing)}")
    title = data["title"]
    if not _visible_text(title):
        raise ValueError("Lesson content spec field 'title' must be non-empty text")
    identity = _require_lesson_identity(data[LESSON_IDENTITY_KEY]) if LESSON_IDENTITY_KEY in data else None
    return LessonContent(
        title=title,
        objectives=_require_text_list(data["objectives"], "objectives"),
        slides=_require_slide_list(data["slides"]),
        worksheet_questions=_require_text_list(data["worksheet_questions"], "worksheet_questions"),
        lesson_identity=identity,
    )


def load_lesson_content(path: str | Path) -> LessonContent:
    data = yaml.safe_load(Path(path).read_text())
    return content_from_dict(data)

