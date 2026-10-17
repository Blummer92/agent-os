"""Parse lesson content YAML into the placeholder-token dict the request builders use."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Mapping

import yaml

REQUIRED_KEYS = ("title", "objectives", "slides", "worksheet_questions")


@dataclasses.dataclass
class LessonContent:
    title: str
    objectives: list[str]
    slides: list[dict[str, Any]]
    worksheet_questions: list[str]
    context_tokens: dict[str, str] = dataclasses.field(default_factory=dict)
    # #3215: prerequisite tutorial ids (e.g. "tutorial-0") the lesson's
    # tool moves transfer from. Resolved against the typed tutorial
    # registry in tutorial_connection.py -- never prose convention.
    prerequisite_tutorials: tuple[str, ...] = dataclasses.field(default_factory=tuple)

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
        prerequisite_tutorials=_parse_prerequisite_tutorials(data.get("prerequisite_tutorials")),
    )


def _parse_prerequisite_tutorials(value: object) -> tuple[str, ...]:
    """Parse the optional ``prerequisite_tutorials`` lesson declaration (#3215).

    Fail closed on malformed declarations: a mistyped tutorial id must
    never silently drop the tutorial-day connection.
    """
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("Lesson content 'prerequisite_tutorials' must be a list")
    tutorials: list[str] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(
                f"prerequisite_tutorials[{index}] must be a non-empty tutorial id"
            )
        tutorials.append(entry.strip())
    return tuple(tutorials)


def load_lesson_content(path: str | Path) -> LessonContent:
    data = yaml.safe_load(Path(path).read_text())
    return content_from_dict(data)
