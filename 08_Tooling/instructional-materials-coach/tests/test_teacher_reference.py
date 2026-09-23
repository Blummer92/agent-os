from __future__ import annotations

import json

import pytest

from instructional_materials_coach.teacher_reference import (
    TeacherReferenceError,
    build_unit_vocabulary_reference,
    build_worked_examples_reference,
    render_teacher_reference_markdown,
)


def _assignment(
    role_id: str,
    *,
    role_type: str = "worked-example",
    asset_id: str = "asset-hierarchy",
    material_types: tuple[str, ...] = ("teacher-reference",),
    approved_role_types: tuple[str, ...] | None = None,
):
    """Build bounded governed visual assignment evidence for a reference fixture."""
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
                "material_types": list(material_types),
                "role_types": list(approved_role_types or (role_type,)),
            }
        },
    }


def _vocab_row(
    term: str,
    definition: str,
    *,
    day_lesson: str,
    expectation: str,
    icon_requirement: str = "not-needed",
    icon_role_id: str | None = None,
):
    """Build one bounded Typography vocabulary row with a required definition."""
    row = {
        "kind": "vocabulary",
        "day_lesson": day_lesson,
        "term": term,
        "student_friendly_definition": definition,
        "expectation": expectation,
        "icon_requirement": icon_requirement,
        "source_reference": f"unit-alignment:{term.replace(' ', '-')}",
    }
    if icon_role_id is not None:
        row["icon_role_id"] = icon_role_id
    return row


def _typography_vocab():
    """Return the complete bounded Typography acceptance vocabulary fixture."""
    return [
        _vocab_row(
            "typography",
            "The way type is chosen and arranged to communicate.",
            day_lesson="Day 1",
            expectation="core",
            icon_requirement="required",
            icon_role_id="icon-typography",
        ),
        _vocab_row(
            "hierarchy",
            "Visual order that shows what to notice first, next, and last.",
            day_lesson="Day 2",
            expectation="core",
            icon_requirement="useful",
            icon_role_id="icon-hierarchy",
        ),
        _vocab_row(
            "readability",
            "How easy text is to read and understand.",
            day_lesson="Day 3",
            expectation="core",
        ),
        _vocab_row(
            "display font",
            "A typeface used to attract attention in large or prominent text.",
            day_lesson="Day 1",
            expectation="supporting",
        ),
        _vocab_row(
            "supporting font",
            "A typeface that works with the main display font without competing with it.",
            day_lesson="Day 1",
            expectation="supporting",
        ),
        _vocab_row(
            "contrast",
            "A noticeable difference that helps important information stand out.",
            day_lesson="Day 2",
            expectation="core",
        ),
        _vocab_row(
            "alignment",
            "How text and visual elements line up to create order.",
            day_lesson="Day 2",
            expectation="supporting",
        ),
        _vocab_row(
            "spacing",
            "The amount of room between letters, lines, and design elements.",
            day_lesson="Day 3",
            expectation="supporting",
        ),
        _vocab_row(
            "audience fit",
            "How well a visual choice matches the people who are meant to see it.",
            day_lesson="Day 4",
            expectation="exposure",
        ),
        _vocab_row(
            "revision",
            "A purposeful change made after reviewing how well a design communicates.",
            day_lesson="Day 4",
            expectation="core",
        ),
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


def test_typography_vocabulary_reference_preserves_full_fixture_and_icon_states():
    """All ten required terms retain definitions while scaffolds stay excluded."""
    reference = build_unit_vocabulary_reference(
        unit_title="Typography & Visual Communication",
        vocabulary_rows=_typography_vocab(),
        governed_visual_assignments=[
            _assignment("icon-typography", role_type="icon", asset_id="asset-type-icon")
        ],
    )

    assert [row["term"] for row in reference["rows"]] == [
        "typography",
        "hierarchy",
        "readability",
        "display font",
        "supporting font",
        "contrast",
        "alignment",
        "spacing",
        "audience fit",
        "revision",
    ]
    assert all(row["student_friendly_definition"] for row in reference["rows"])
    assert all(row["day_lesson"] for row in reference["rows"])
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


def test_vocabulary_markdown_is_deterministic_and_includes_clear_key():
    """The renderer-ready vocabulary document is deterministic and explicit."""
    reference = build_unit_vocabulary_reference(
        unit_title="Typography & Visual Communication",
        vocabulary_rows=_typography_vocab(),
        governed_visual_assignments=[
            _assignment("icon-typography", role_type="icon", asset_id="asset-type-icon")
        ],
    )
    first = render_teacher_reference_markdown(reference)
    second = render_teacher_reference_markdown(reference)

    assert first == second
    assert (
        "| Day / lesson | Word / term | Student-friendly definition | Expectation | Icon status | Icon preview |"
        in first
    )
    assert "approved-existing" in first
    assert "drive-asset-type-icon" in first
    assert "**Instructional scaffolds kept out of vocabulary:** font menu" in first
    assert "audience fit" in first
    assert "revision" in first
    assert "grants no readiness" in first


def _modeling_rows():
    """Return bounded modeling coverage for the required Typography use cases."""
    return [
        {
            "day_lesson": "Day 1",
            "skill_learning_purpose": "Connect font personality to an intentional communication choice.",
            "example_role": "worked-example",
            "teacher_modeling_purpose": "Compare two font personalities and explain which better fits the intended audience.",
            "artifact_location": "teacher reference / Day 1 model",
            "tutorial_step": "Choose a display and supporting font intentionally",
            "visual_role_id": "font-personality-example",
            "expected_visual_description": "Two non-UI type treatments with clearly different personalities.",
            "source_constraints": "Teacher-facing modeling reference only.",
        },
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
            "skill_learning_purpose": "Critique a design and make a purposeful revision.",
            "example_role": "worked-example",
            "teacher_modeling_purpose": "Model a critique aloud: name one communication problem, revise it, and explain why the revision improves audience fit.",
            "artifact_location": "critique / revision model",
            "tutorial_step": "Revise after critique",
            "visual_role_id": "revision-example",
            "expected_visual_description": "Before-and-after non-UI typography revision.",
            "source_constraints": "Teacher-facing critique reference only.",
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


def _visual_prompts():
    """Return current caller-supplied prompt evidence for legitimate non-UI rows."""
    return [
        {
            "visual_role_id": "font-personality-example",
            "generative": True,
            "prompt": "Create two non-UI type treatments for the same phrase with intentionally different font personalities.",
            "source_constraints": "Teacher-facing modeling use.",
        },
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
        {
            "visual_role_id": "revision-example",
            "generative": True,
            "prompt": "Create a before-and-after non-UI typography revision that improves audience fit and readability.",
            "source_constraints": "Teacher-facing critique and revision use.",
        },
    ]


def test_worked_example_reference_covers_modeling_prompts_reuse_gaps_and_ui():
    """The first fixture covers all required modeling semantics and visual states."""
    reference = build_worked_examples_reference(
        unit_title="Typography & Visual Communication",
        modeling_rows=_modeling_rows(),
        visual_prompt_rows=_visual_prompts(),
        governed_visual_assignments=[
            _assignment("hierarchy-comparison", asset_id="asset-business-card"),
            _assignment(
                "ui-current-reference",
                role_type="current-ui-reference",
                asset_id="asset-current-ui",
            ),
        ],
    )

    personality, hierarchy, readability, revision, ui = reference["rows"]
    assert "font personality" in personality["skill_learning_purpose"].lower()
    assert personality["visual_status"] == "explicit-gap"
    assert personality["visual_prompt"].startswith("Create two non-UI type treatments")

    assert hierarchy["visual_status"] == "approved-existing"
    assert hierarchy["visual_preview"]["external_file_id"] == "drive-asset-business-card"
    assert hierarchy["visual_prompt"].startswith("Create three clean business-card examples")
    assert "approved_use=" in hierarchy["source_reuse_safe_use_constraints"]

    assert readability["visual_status"] == "explicit-gap"
    assert readability["visual_preview"] is None
    assert readability["visual_prompt"].startswith("Create a non-UI typography example")

    assert "revision" in revision["skill_learning_purpose"].lower()
    assert "critique" in revision["teacher_modeling_purpose"].lower()
    assert revision["visual_status"] == "explicit-gap"
    assert revision["visual_prompt"].startswith("Create a before-and-after")

    assert ui["software_ui"] is True
    assert ui["visual_status"] == "current-ui-reference-required"
    assert ui["visual_preview"]["asset_id"] == "asset-current-ui"
    assert ui["visual_prompt"] is None
    assert not any(reference["authority"].values())


def test_worked_examples_markdown_preserves_tutorial_linkage_and_prompt_verbatim():
    """Exact tutorial linkage and supplied prompt wording survive rendering."""
    prompt = "Create a strong hierarchy comparison; keep it non-UI."
    reference = build_worked_examples_reference(
        unit_title="Typography & Visual Communication",
        modeling_rows=[_modeling_rows()[1]],
        visual_prompt_rows=[
            {
                "visual_role_id": "hierarchy-comparison",
                "generative": True,
                "prompt": prompt,
                "source_constraints": "prompt-source:current",
            }
        ],
        governed_visual_assignments=[
            _assignment("hierarchy-comparison", asset_id="asset-business-card")
        ],
    )
    rendered = render_teacher_reference_markdown(reference)

    assert "Build business-card comparison" in rendered
    assert prompt in rendered
    assert "drive-asset-business-card" in rendered
    assert "Teacher reference only" in rendered


def test_incompatible_approved_use_stays_explicit_and_blocks_identity_reuse():
    """Worksheet-only approval cannot silently become teacher-reference approval."""
    worksheet_icon = _assignment(
        "icon-typography",
        role_type="icon",
        asset_id="asset-worksheet-icon",
        material_types=("worksheet",),
    )
    vocabulary = build_unit_vocabulary_reference(
        unit_title="Typography & Visual Communication",
        vocabulary_rows=[_typography_vocab()[0]],
        governed_visual_assignments=[worksheet_icon],
    )
    assert vocabulary["rows"][0]["icon_status"] == "useful-but-missing"
    assert vocabulary["rows"][0]["icon_preview"] is None

    worksheet_example = _assignment(
        "hierarchy-comparison",
        asset_id="asset-worksheet-example",
        material_types=("worksheet",),
    )
    examples = build_worked_examples_reference(
        unit_title="Typography & Visual Communication",
        modeling_rows=[_modeling_rows()[1]],
        governed_visual_assignments=[worksheet_example],
    )
    row = examples["rows"][0]
    assert row["visual_status"] == "explicit-gap"
    assert row["visual_preview"] is None
    assert '"material_types":["worksheet"]' in row["source_reuse_safe_use_constraints"]


def test_mismatched_approved_role_stays_explicit_and_blocks_identity_reuse():
    """An approval for another role type cannot authorize a teacher visual preview."""
    mismatched = _assignment(
        "hierarchy-comparison",
        asset_id="asset-role-mismatch",
        approved_role_types=("icon",),
    )
    examples = build_worked_examples_reference(
        unit_title="Typography & Visual Communication",
        modeling_rows=[_modeling_rows()[1]],
        governed_visual_assignments=[mismatched],
    )
    row = examples["rows"][0]
    assert row["visual_status"] == "explicit-gap"
    assert row["visual_preview"] is None
    assert '"role_types":["icon"]' in row["source_reuse_safe_use_constraints"]


def test_software_ui_rejects_generative_prompt():
    """Software UI can never enter the generative prompt path."""
    with pytest.raises(TeacherReferenceError, match="software UI"):
        build_worked_examples_reference(
            unit_title="Typography & Visual Communication",
            modeling_rows=[_modeling_rows()[4]],
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
    """Non-generative evidence cannot be relabeled as a generation prompt."""
    with pytest.raises(TeacherReferenceError, match="explicitly generative"):
        build_worked_examples_reference(
            unit_title="Typography & Visual Communication",
            modeling_rows=[_modeling_rows()[1]],
            visual_prompt_rows=[
                {
                    "visual_role_id": "hierarchy-comparison",
                    "generative": False,
                    "prompt": "Do not use this as a generation prompt.",
                }
            ],
        )


def test_reference_rows_are_bounded():
    """Oversized reference collections fail closed before projection."""
    with pytest.raises(TeacherReferenceError, match="exceeds 96 rows"):
        build_unit_vocabulary_reference(
            unit_title="Typography & Visual Communication",
            vocabulary_rows=[_typography_vocab()[0]] * 97,
        )


def test_serialized_assignment_input_from_1416_is_supported():
    """Serialized governed assignment evidence from #1416 remains consumable."""
    encoded = json.dumps(
        [_assignment("icon-typography", role_type="icon", asset_id="asset-type-icon")]
    )
    reference = build_unit_vocabulary_reference(
        unit_title="Typography & Visual Communication",
        vocabulary_rows=[_typography_vocab()[0]],
        governed_visual_assignments=encoded,
    )
    assert reference["rows"][0]["icon_preview"]["asset_id"] == "asset-type-icon"
