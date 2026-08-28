from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image as PillowImage
from pypdf import PdfReader

from instructional_materials_coach.teacher_reference import (
    build_unit_vocabulary_reference,
    build_worked_examples_reference,
)
from instructional_materials_coach.teacher_reference_pdf import (
    TeacherReferencePdfError,
    render_teacher_reference_pdf,
)


def _png_bytes() -> bytes:
    image = PillowImage.new("RGB", (120, 80), "white")
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _assignment(role_id: str, *, role_type: str, asset_id: str):
    return {
        "role_id": role_id,
        "role_type": role_type,
        "selected_candidate": {
            "asset_reference": {
                "asset_id": asset_id,
                "stable_ref": f"stable-{asset_id}",
                "content_fingerprint": "c" * 64,
            },
            "manifest_reference": {
                "external_file_id": f"drive-{asset_id}",
                "manifest_id": f"manifest-{asset_id}",
                "record_revision": 1,
                "fingerprint": "d" * 64,
                "verified_at": "2026-08-28T12:00:00Z",
            },
        },
        "compatibility_evidence": {
            "approved_use": {
                "state": "approved",
                "material_types": ["teacher-reference"],
                "role_types": [role_type],
            }
        },
    }


def test_renders_vocabulary_pdf_with_supplied_governed_icon(tmp_path):
    reference = build_unit_vocabulary_reference(
        unit_title="Typography & Visual Communication",
        vocabulary_rows=[
            {
                "kind": "vocabulary",
                "day_lesson": "Day 1",
                "term": "typography",
                "student_friendly_definition": "The way type is chosen and arranged to communicate.",
                "expectation": "core",
                "icon_requirement": "required",
                "icon_role_id": "icon-typography",
            }
        ],
        governed_visual_assignments=[
            _assignment("icon-typography", role_type="icon", asset_id="asset-type-icon")
        ],
    )
    target = render_teacher_reference_pdf(
        reference,
        tmp_path / "vocabulary.pdf",
        asset_content={"asset-type-icon": _png_bytes()},
    )
    reader = PdfReader(str(target))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "%PDF" in target.read_bytes()[:8].decode("latin-1")
    assert "Unit Vocabulary Map" in text
    assert "typography" in text
    assert "grants no readiness" in text


def test_renders_worked_examples_pdf_and_preserves_explicit_gap(tmp_path):
    reference = build_worked_examples_reference(
        unit_title="Typography & Visual Communication",
        modeling_rows=[
            {
                "day_lesson": "Day 2",
                "skill_learning_purpose": "Compare hierarchy.",
                "example_role": "comparison",
                "teacher_modeling_purpose": "Explain what the eye notices first.",
                "artifact_location": "teacher reference",
                "tutorial_step": "Build business-card comparison",
                "visual_role_id": "hierarchy-comparison",
                "expected_visual_description": "Strong and weak hierarchy examples.",
            },
            {
                "day_lesson": "Day 3",
                "skill_learning_purpose": "Diagnose readability.",
                "example_role": "non-example",
                "teacher_modeling_purpose": "Show a readability problem.",
                "artifact_location": "teacher reference",
                "visual_role_id": "readability-gap",
                "expected_visual_description": "A difficult-to-read non-example.",
            },
        ],
        governed_visual_assignments=[
            _assignment("hierarchy-comparison", role_type="worked-example", asset_id="asset-business-card")
        ],
    )
    target = render_teacher_reference_pdf(
        reference,
        tmp_path / "examples.pdf",
        asset_content={"drive-asset-business-card": _png_bytes()},
    )
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(target)).pages)
    assert "Worked Examples + Visual Prompt Reference" in text
    assert "Build business-card comparison" in text
    assert "Explicit gap" in text


def test_asset_identity_collision_fails_closed(tmp_path):
    reference = build_unit_vocabulary_reference(
        unit_title="Typography",
        vocabulary_rows=[
            {
                "kind": "vocabulary",
                "day_lesson": "Day 1",
                "term": "typography",
                "student_friendly_definition": "Type arranged to communicate.",
                "expectation": "core",
                "icon_requirement": "required",
                "icon_role_id": "icon-typography",
            }
        ],
        governed_visual_assignments=[
            _assignment("icon-typography", role_type="icon", asset_id="asset-type-icon")
        ],
    )
    with pytest.raises(TeacherReferencePdfError, match="disagree"):
        render_teacher_reference_pdf(
            reference,
            tmp_path / "bad.pdf",
            asset_content={
                "asset-type-icon": _png_bytes(),
                "stable-asset-type-icon": _png_bytes() + b"different",
            },
        )
