"""Parse lesson content YAML into text tokens plus optional approved visual references."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import yaml

REQUIRED_KEYS = ("title", "objectives", "slides", "worksheet_questions")
VISUAL_ROLE_TYPES = {
    "teacher-model", "worked-example", "non-example", "process-sequence", "comparison",
    "annotated-evidence", "navigation-orientation", "accessibility-support", "repeated-reference",
    "critique-exemplar",
}


@dataclasses.dataclass(frozen=True)
class VisualReference:
    role_type: str
    asset_id: str
    target_object_id: str


@dataclasses.dataclass
class LessonContent:
    title: str
    objectives: list[str]
    slides: list[dict[str, Any]]
    worksheet_questions: list[str]
    visuals: list[VisualReference] = dataclasses.field(default_factory=list)

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
        return tokens


def _visual_from_dict(value: Any) -> VisualReference:
    if type(value) is not dict:
        raise ValueError("visual reference must be a mapping")
    required = {"role_type", "asset_id", "target_object_id"}
    if set(value) != required:
        raise ValueError("visual reference must contain exactly role_type, asset_id, target_object_id")
    if value["role_type"] not in VISUAL_ROLE_TYPES:
        raise ValueError("visual reference uses unsupported MaterialRequirement v2 role")
    if any(not isinstance(value[key], str) or not value[key].strip() for key in required):
        raise ValueError("visual reference fields must be non-empty strings")
    return VisualReference(
        role_type=value["role_type"].strip(),
        asset_id=value["asset_id"].strip(),
        target_object_id=value["target_object_id"].strip(),
    )


def content_from_dict(data: dict[str, Any]) -> LessonContent:
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        raise ValueError(f"Lesson content spec is missing required keys: {', '.join(missing)}")
    visuals = data.get("visuals", [])
    if type(visuals) is not list:
        raise ValueError("visuals must be a list when supplied")
    return LessonContent(
        title=data["title"],
        objectives=list(data["objectives"]),
        slides=list(data["slides"]),
        worksheet_questions=list(data["worksheet_questions"]),
        visuals=[_visual_from_dict(value) for value in visuals],
    )


def load_lesson_content(path: str | Path) -> LessonContent:
    data = yaml.safe_load(Path(path).read_text())
    return content_from_dict(data)
