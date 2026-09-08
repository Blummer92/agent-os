from __future__ import annotations

from copy import deepcopy

from instructional_materials_coach.artifact_structure import (
    FAIL,
    MANUAL_REVIEW,
    PASS,
    validate_artifact_structure,
)


def _regions(*, check: bool = False) -> dict[str, list[float]]:
    regions = {
        "title": [0.05, 0.04, 0.90, 0.10],
        "body": [0.05, 0.18, 0.40, 0.62],
        "action": [0.50, 0.18, 0.45, 0.62],
    }
    if check:
        regions.pop("action")
        regions["check"] = [0.50, 0.18, 0.45, 0.62]
    return regions


def typography_business_card_fixture() -> dict:
    return {
        "requirements": {
            "warm_up": True,
            "exit_ticket": True,
            "finalization": True,
            "plan_worksheet_ref": "typography-business-card-planning-worksheet-v1",
            "required_concept_tags": ["hierarchy", "grouping", "legibility", "purpose"],
        },
        "instructional_concept_tags": ["hierarchy", "grouping", "legibility", "purpose"],
        "learning_target_mode": "concept",
        "slides": [
            {"index": 1, "kind": "warm-up", "regions": _regions()},
            {"index": 2, "kind": "focus", "regions": _regions()},
            {"index": 3, "kind": "vocabulary", "regions": _regions()},
            {
                "index": 4,
                "kind": "plan",
                "worksheet_ref": "typography-business-card-planning-worksheet-v1",
                "regions": _regions(),
            },
            {
                "index": 5,
                "kind": "model",
                "teaching_move_ids": ["group-contact-info"],
                "paragraph_blocks": 0,
                "bullet_count": 2,
                "visual_role": "dominant",
                "rendered_visual_scale_verified": True,
                "regions": _regions(),
            },
            {
                "index": 6,
                "kind": "tutorial",
                "teaching_move_ids": ["choose-legible-type"],
                "paragraph_blocks": 0,
                "bullet_count": 2,
                "visual_role": "dominant",
                "rendered_visual_scale_verified": True,
                "regions": _regions(),
            },
            {"index": 7, "kind": "check", "regions": _regions(check=True)},
            {"index": 8, "kind": "revise", "regions": _regions()},
            {"index": 9, "kind": "exit-ticket", "regions": _regions(check=True)},
            {"index": 10, "kind": "finalization", "regions": _regions()},
        ],
    }


def hamburger_fixture() -> dict:
    fixture = typography_business_card_fixture()
    fixture["requirements"] = {
        "warm_up": True,
        "exit_ticket": True,
        "finalization": True,
        "required_concept_tags": ["sequence", "visual-role"],
    }
    fixture["instructional_concept_tags"] = ["sequence", "visual-role"]
    fixture["slides"] = [slide for slide in fixture["slides"] if slide["kind"] != "plan"]
    return fixture


def _codes(result) -> set[str]:
    return {finding.code for finding in result.findings}


def test_typography_fixture_passes_structural_checks() -> None:
    result = validate_artifact_structure(typography_business_card_fixture())
    assert result.status == PASS
    assert result.findings == ()


def test_hamburger_fixture_passes_structural_checks() -> None:
    result = validate_artifact_structure(hamburger_fixture())
    assert result.status == PASS


def test_required_warm_up_exit_and_finalization_omissions_fail() -> None:
    for omitted_kind, expected_code in [
        ("warm-up", "artifact-required-warm-up-missing"),
        ("exit-ticket", "artifact-required-exit-ticket-missing"),
        ("finalization", "artifact-required-finalization-missing"),
    ]:
        fixture = hamburger_fixture()
        fixture["slides"] = [slide for slide in fixture["slides"] if slide["kind"] != omitted_kind]
        result = validate_artifact_structure(fixture)
        assert result.status == FAIL
        assert expected_code in _codes(result)


def test_cross_step_instructional_leakage_fails() -> None:
    fixture = typography_business_card_fixture()
    fixture["slides"][4]["teaching_move_ids"] = ["group-contact-info", "choose-legible-type"]
    result = validate_artifact_structure(fixture)
    assert result.status == FAIL
    assert "artifact-multiple-teaching-moves" in _codes(result)


def test_tutorial_visual_role_and_text_density_are_mechanically_guarded() -> None:
    fixture = typography_business_card_fixture()
    fixture["slides"][5]["visual_role"] = "supporting"
    fixture["slides"][5]["paragraph_blocks"] = 1
    fixture["slides"][5]["bullet_count"] = 5
    result = validate_artifact_structure(fixture)
    assert result.status == FAIL
    assert {
        "artifact-model-visual-not-dominant",
        "artifact-paragraph-block-on-student-slide",
        "artifact-student-slide-too-dense",
    }.issubset(_codes(result))


def test_unproven_rendered_scale_routes_to_manual_review() -> None:
    fixture = typography_business_card_fixture()
    fixture["slides"][4]["rendered_visual_scale_verified"] = False
    result = validate_artifact_structure(fixture)
    assert result.status == MANUAL_REVIEW
    assert "artifact-rendered-visual-scale-needs-review" in _codes(result)


def test_planning_worksheet_reference_is_preserved() -> None:
    fixture = typography_business_card_fixture()
    fixture["slides"][3]["worksheet_ref"] = "generic-planning-icon"
    result = validate_artifact_structure(fixture)
    assert result.status == FAIL
    assert "artifact-plan-worksheet-mismatch" in _codes(result)


def test_broader_typography_purpose_cannot_collapse_to_clicks() -> None:
    fixture = typography_business_card_fixture()
    fixture["learning_target_mode"] = "click-sequence"
    fixture["instructional_concept_tags"] = ["click-text-tool"]
    result = validate_artifact_structure(fixture)
    assert result.status == FAIL
    assert "artifact-learning-target-collapsed-to-clicks" in _codes(result)
    assert "artifact-approved-purpose-not-preserved" in _codes(result)


def test_section_hierarchy_overlap_fails() -> None:
    fixture = typography_business_card_fixture()
    fixture["slides"][4]["regions"]["action"] = [0.30, 0.18, 0.45, 0.62]
    result = validate_artifact_structure(fixture)
    assert result.status == FAIL
    assert "artifact-section-regions-overlap" in _codes(result)


def test_missing_region_bounds_routes_to_manual_review_instead_of_false_pass() -> None:
    fixture = hamburger_fixture()
    fixture["slides"][0].pop("regions")
    result = validate_artifact_structure(fixture)
    assert result.status == MANUAL_REVIEW
    assert "artifact-section-hierarchy-unverifiable" in _codes(result)


def test_fixture_mutations_do_not_cross_contaminate() -> None:
    first = typography_business_card_fixture()
    second = deepcopy(first)
    second["slides"][4]["teaching_move_ids"].append("later-step")
    assert validate_artifact_structure(first).status == PASS
    assert validate_artifact_structure(second).status == FAIL
