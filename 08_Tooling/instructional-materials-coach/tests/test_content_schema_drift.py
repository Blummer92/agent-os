"""Prove `content_schema` cannot drift from the canonical `content_spec`.

Parsed with `ast` rather than imported, so this runs with no pydantic and no
google-genai installed. Schema drift is the highest long-term maintenance risk
in the generation layer, so its guard must never be skipped in CI.
"""
from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

from instructional_materials_coach.content_spec import REQUIRED_KEYS, LessonContent

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "instructional_materials_coach"
    / "content_schema.py"
)


def _class_fields(source: str, class_name: str) -> list[str]:
    """Annotated field names of a class, without importing the module."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            ]
    raise AssertionError(f"class {class_name} not found in {SCHEMA_PATH}")


def test_lesson_draft_fields_match_lesson_content_exactly():
    schema_fields = _class_fields(SCHEMA_PATH.read_text(encoding="utf-8"), "LessonDraft")
    canonical = [field.name for field in dataclasses.fields(LessonContent)]
    assert schema_fields == canonical, (
        "LessonDraft drifted from the canonical LessonContent. content_spec.py is "
        f"canonical: {canonical}, but content_schema.py declares {schema_fields}."
    )


def test_lesson_draft_covers_every_required_key():
    schema_fields = set(_class_fields(SCHEMA_PATH.read_text(encoding="utf-8"), "LessonDraft"))
    assert set(REQUIRED_KEYS) <= schema_fields


def test_slide_draft_fields_match_the_slide_dict_content_spec_reads():
    # content_spec.placeholder_tokens() reads exactly these keys off each slide.
    schema_fields = _class_fields(SCHEMA_PATH.read_text(encoding="utf-8"), "SlideDraft")
    assert schema_fields == ["index", "heading", "bullets"]


def test_schema_avoids_constructs_gemini_response_schema_rejects():
    source = SCHEMA_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    annotations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in {"LessonDraft", "SlideDraft"}:
            annotations.extend(
                ast.unparse(stmt.annotation)
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign)
            )
    for annotation in annotations:
        assert "Optional" not in annotation, f"union in response_schema: {annotation}"
        assert "|" not in annotation, f"union in response_schema: {annotation}"
        assert not annotation.startswith("dict"), f"bare dict in response_schema: {annotation}"
