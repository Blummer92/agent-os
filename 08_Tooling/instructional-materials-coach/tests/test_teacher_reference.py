from __future__ import annotations

import json

import pytest

from instructional_materials_coach.teacher_reference import (
    TeacherReferenceError,
    build_unit_vocabulary_reference,
    build_worked_examples_reference,
    render_teacher_reference_markdown,
)


def _assignment(role_id: str, *, role_type: str = "worked-example", asset_id: str = "asset-hierarchy"):
    return {
        "role_id": role_id,
        "role_type": role_type,
        "requirement_state": "required",
        "instructional_purpose": "Support the taught comparison.",
        "intended_placement": "teacher reference",
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


def _typography_vocab():
    return [
        {
            "kind": "vocabulary",
            "day_lesson": "Day 1",
            "term": "typography",
            "student_friendly_definition": "The way type is chosen and arranged to communicate.",
            "expectation": "core",
            "icon_requirement": "required",
            "icon_role_id": "icon-typography",
            "source_reference": "unit-alignment:typography",
        },
        {
            "kind": "vocabulary",
            "day_lesson": "Day 2",
            "term": "hierarchy",
            "student_friendly_definition": "Visual order that shows what to notice first, next, and last.",
            "expectation": "core",
            "icon_requirement": "useful",
            "icon_role_id": "icon-hierarchy",
            "source_reference": "unit-alignment:hierarchy",
        },
        {
            "kind": "vocabulary",
            "day_lesson": "Day 3",
            "term": "readability",
            "student_friendly_definition": "How easy text is to read and understand.",
            "expectation": "supporting",
            "icon_requirement": "not-needed",
            "source_reference": "unit-alignment:readability",
        },
        {
            "kind": "scaffold",
            "day_lesson": "Day 1",
            "term": "font menu",
            "student_friendly_definition": "A bounded set of fonts students may choose from.",
            "expectation": "unspecified",
            "icon_requirement": "not-needed",
            "source_reference": "modeling:font-menu",
        },
    ]


def test_typography_vocabulary_reference_preserves_definitions_levels_and_icon_states():
    reference = build_unit_vocabulary_reference(
        unit_title="Typography & Visual Communication",
        vocabulary_rows=_typography_vocab(),
        governed_visual_assignments=[_assignment("icon-typography", role_type="icon", asset_id="asset-type-icon")],
    )

    assert [row["term"] for row in reference["rows"]] == ["typography", "hierarchy", "readability"]
    assert all(row["student_friendly_definition"] for row in reference["rows"])
    assert reference["rows"][0]["expectation"] == "core"
    assert reference["rows"][0]["icon_status"] == "approved-existing"
    assert reference["rows"][0]["icon_preview"] == {
        "role_id": "icon-typography",
        "role_type": "icon",
        "asset_id": "asset-type-icon",
        "stable_ref": "stable-asset-type-icon",
        "external_file_id": "drive-asset-type-icon",
    }
    assert reference["rows"][1]["icon_status"] == "useful-but-missing"
    assert reference["rows"][1]["icon_preview"] is None
    assert reference["rows"][2]["icon_status"] == "no-icon-needed"
    assert reference["excluded_scaffolds"] == ["font menu"]
    assert not any(reference["authority"].values())


def test_vocabulary_markdown_is_pdf_ready_and_includes_clear_key():
    reference = build_unit_vocabulary_reference(
        unit_title="Typography & Visual Communication",
        vocabulary_rows=_typography_vocab(),
        governed_visual_assignments=[_assignment("icon-typography", role_type="icon", asset_id="asset-type-icon")],
    )
    first = render_teacher_reference_markdown(reference)
    second = render_teacher_reference_markdown(reference)
    assert first == second
    assert "| Day / lesson | Word / term | Student-friendly definition | Expectation | Icon status | Icon preview |" in first
    assert "approved-existing" in first
    assert "drive-asset-type-icon" in first
    assert "Instructional scaffolds kept out of vocabulary: font menu" in first
    assert "grants no readiness" in first


def _modeling_rows():
    return [
        {
            "day_lesson": "Day 2",
            "skill_learning_purpose": "Compare strong and weak visual hierarchy on a business card.",
            "example_role": "comparison",
            "teacher_modeling_purpose": "Think aloud about what the eye notices first and why.",
            "artifact_location": "tutorial step 3 / teacher reference",
            "tutorial_step": "Build business-card comparison",
            "visual_role_id": "hierarchy-comparison",
            "expected_visual_description": "Strong, weak, and almost-there hierarchy examples.",
            "source_constraints": "Teacher-facing reference; preserve approved asset identity.",
        },
        {
            "day_lesson": "Day 3",
            "skill_learning_purpose": "Diagnose readability problems.",
            "example_role": "non-example",
            "teacher_modeling_purpose": "Show how spacing and contrast can make text harder to read.",
            "artifact_location": "worksheet model",
            "visual_role_id": "readability-gap",
            "expected_visual_description": "A deliberately difficult-to-read non-example.",
            "source_constraints": "Non-UI instructional visual only.",
        },
        {
            "day_lesson": "Day 4",
            "skill_learning_purpose": "Follow the current application interface during a tool step.",
            "example_role": "model",
            "teacher_modeling_purpose": "Point to the current interface without recreating it.",
            "artifact_location": "tutorial step 5",
            "tutorial_step": "Open the current type controls",
            "visual_role_id": "ui-current-reference",
            "expected_visual_description": "Current verified application UI reference.",
            "source_constraints": "Use current-application visual-reference architecture only.",
            "software_ui": True,
        },
    ]


def test_worked_example_reference_reuses_current_asset_and_prompt_and_keeps_gaps_explicit():
    reference = build_worked_examples_reference(
        unit_title="Typography & Visual Communication",
        modeling_rows=_modeling_rows(),
        visual_prompt_rows=[
            {
                "visual_role_id": "hierarchy-comparison",
                "generative": True,
                "prompt": "Create three clean business-card examples showing strong, weak, and almost-there visual hierarchy.",
                "source_constraints": "Current Digital Media Visual Prompt System evidence.",
            },
            {
                "visual_role_id": "readability-gap",
                "generative": True,
                "prompt": "Create a non-UI typography example with cramped spacing and weak contrast for readability diagnosis.",
                "source_constraints": "Teacher-facing modeling use.",
            },
        ],
        governed_visual_assignments=[
            _assignment("hierarchy-comparison", asset_id="asset-business-card"),
            _assignment("ui-current-reference", role_type="current-ui-reference", asset_id="asset-current-ui"),
        ],
    )

    first, second, third = reference["rows"]
    assert first["visual_status"] == "approved-existing"
    assert first["visual_preview"]["external_file_id"] == "drive-asset-business-card"
    assert first["visual_prompt"].startswith("Create three clean business-card examples")
    assert "approved_use=" in first["source_reuse_safe_use_constraints"]

    assert second["visual_status"] == "explicit-gap"
    assert second["visual_preview"] is None
    assert second["visual_prompt"].startswith("Create a non-UI typography example")

    assert third["software_ui"] is True
    assert third["visual_status"] == "current-ui-reference-required"
    assert third["visual_preview"]["asset_id"] == "asset-current-ui"
    assert third["visual_prompt"] is None
    assert not any(reference["authority"].values())


def test_worked_examples_markdown_preserves_tutorial_linkage_and_prompt_verbatim():
    prompt = "Create a strong hierarchy comparison; keep it non-UI."
    reference = build_worked_examples_reference(
        unit_title="Typography & Visual Communication",
        modeling_rows=[_modeling_rows()[0]],
        visual_prompt_rows=[
            {
                "visual_role_id": "hierarchy-comparison",
                "generative": True,
                "prompt": prompt,
                "source_constraints": "prompt-source:current",
            }
        ],
        governed_visual_assignments=[_assignment("hierarchy-comparison", asset_id="asset-business-card")],
    )
    rendered = render_teacher_reference_markdown(reference)
    assert "Build business-card comparison" in rendered
    assert prompt in rendered
    assert "drive-asset-business-card" in rendered
    assert "Teacher reference only" in rendered


def test_software_ui_rejects_generative_prompt():
    with pytest.raises(TeacherReferenceError, match="software UI"):
        build_worked_examples_reference(
            unit_title="Typography & Visual Communication",
            modeling_rows=[_modeling_rows()[2]],
            visual_prompt_rows=[
                {
                    "visual_role_id": "ui-current-reference",
                    "generative": True,
                    "prompt": "Recreate the application toolbar.",
                    "source_constraints": "invalid",
                }
            ],
        )


def test_visual_prompt_must_be_explicitly_generative_and_currently_supplied():
    with pytest.raises(TeacherReferenceError, match="explicitly generative"):
        build_worked_examples_reference(
            unit_title="Typography & Visual Communication",
            modeling_rows=[_modeling_rows()[0]],
            visual_prompt_rows=[
                {
                    "visual_role_id": "hierarchy-comparison",
                    "generative": False,
                    "prompt": "Do not use this as a generation prompt.",
                }
            ],
        )


def test_reference_rows_are_bounded():
    with pytest.raises(TeacherReferenceError, match="exceeds 96 rows"):
        build_unit_vocabulary_reference(
            unit_title="Typography & Visual Communication",
            vocabulary_rows=[_typography_vocab()[0]] * 97,
        )


def test_serialized_assignment_input_from_1416_is_supported():
    encoded = json.dumps([_assignment("icon-typography", role_type="icon", asset_id="asset-type-icon")])
    reference = build_unit_vocabulary_reference(
        unit_title="Typography & Visual Communication",
        vocabulary_rows=[_typography_vocab()[0]],
        governed_visual_assignments=encoded,
    )
    assert reference["rows"][0]["icon_preview"]["asset_id"] == "asset-type-icon"
