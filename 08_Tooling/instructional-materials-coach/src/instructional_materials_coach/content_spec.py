"""Parse lesson content YAML into the placeholder-token dict the request builders use."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Mapping

import yaml

REQUIRED_KEYS = ("title", "objectives", "slides", "worksheet_questions")


@dataclasses.dataclass(frozen=True)
class VisualExample:
    """One unit-declared visual example the worksheet must carry (#3212).

    The unit's per-section image needs (worked examples, before/after
    frames, clear-vs-confusing comparisons) declared as build-time
    obligations: every entry must be covered by the governed visual plan
    before generation, so a worksheet whose unit requires visual examples
    can never be generated text-only.
    """

    section: str
    role_id: str
    slot_id: str = "0"
    caption: str = ""


@dataclasses.dataclass
class LessonContent:
    title: str
    objectives: list[str]
    slides: list[dict[str, Any]]
    worksheet_questions: list[str]
    context_tokens: dict[str, str] = dataclasses.field(default_factory=dict)
    visual_examples: tuple[VisualExample, ...] = dataclasses.field(default_factory=tuple)

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
        # Declared visual-example captions project as figure labels the Doc
        # template can place beside the governed visual slot (#3212).
        for i, example in enumerate(self.visual_examples, start=1):
            if example.caption.strip():
                tokens[f"visual_example_{i}_caption"] = example.caption
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
    return LessonContent(
        title=data["title"],
        objectives=list(data["objectives"]),
        slides=list(data["slides"]),
        worksheet_questions=list(data["worksheet_questions"]),
        visual_examples=_parse_visual_examples(data.get("visual_examples")),
    )


def _parse_visual_examples(value: object) -> tuple[VisualExample, ...]:
    """Parse the optional ``visual_examples`` lesson declarations (#3212).

    Fail closed on malformed declarations: a misspelled role id must never
    silently weaken the visual-example obligation into a text-only build.
    """
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("Lesson content 'visual_examples' must be a list")
    examples: list[VisualExample] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping):
            raise ValueError(f"visual_examples[{index}] must be a mapping")
        section = entry.get("section")
        role_id = entry.get("role_id")
        if not isinstance(section, str) or not section.strip():
            raise ValueError(f"visual_examples[{index}] needs a non-empty 'section'")
        if not isinstance(role_id, str) or not role_id.strip():
            raise ValueError(f"visual_examples[{index}] needs a non-empty 'role_id'")
        slot_id = entry.get("slot_id", "0")
        if not isinstance(slot_id, str) or not slot_id.strip():
            raise ValueError(f"visual_examples[{index}] 'slot_id' must be non-empty text")
        caption = entry.get("caption", "")
        if not isinstance(caption, str):
            raise ValueError(f"visual_examples[{index}] 'caption' must be text")
        examples.append(
            VisualExample(
                section=section.strip(),
                role_id=role_id.strip(),
                slot_id=slot_id.strip(),
                caption=caption,
            )
        )
    return tuple(examples)


def load_lesson_content(path: str | Path) -> LessonContent:
    data = yaml.safe_load(Path(path).read_text())
    return content_from_dict(data)
