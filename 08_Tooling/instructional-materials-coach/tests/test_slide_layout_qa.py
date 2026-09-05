from instructional_materials_coach.slide_layout_qa import (
    Box,
    SlideElement,
    SlidePlan,
    evaluate_slide_layout,
    finding_codes,
)


def element(element_id, role, box, **kwargs):
    return SlideElement(element_id=element_id, role=role, box=Box(*box), **kwargs)


def test_typography_challenge_fixture_detects_four_consolidated_defect_classes():
    plan = SlidePlan(
        width=10,
        height=7.5,
        elements=(
            element("title", "title", (0.5, 0.3, 9, 0.7), text="Typography Challenge", foreground="#FFFFFF", background="#FFFFFF"),
            element("directions", "directions", (0.5, 1.2, 4.5, 2), text="Compare hierarchy and spacing.", foreground="#111111", background="#FFFFFF"),
            element("task", "task", (4.0, 1.4, 4.5, 2), text="Choose and explain.", foreground="#111111", background="#FFFFFF"),
            element("blank-card", "accent", (0.4, 1.1, 4.8, 2.2), z_index=10, opaque=True, placeholder=True),
            element("preview", "supporting-preview", (5.0, 3.8, 5.0, 3.7)),
        ),
    )

    codes = finding_codes(evaluate_slide_layout(plan))

    assert "opaque-placeholder-occlusion" in codes
    assert "unsafe-required-text-contrast" in codes
    assert "required-region-collision" in codes
    assert "supporting-preview-overscale" in codes


def test_safe_required_regions_pass_structural_checks():
    plan = SlidePlan(
        width=10,
        height=7.5,
        elements=(
            element("title", "title", (0.5, 0.3, 9, 0.7), text="Typography Challenge", foreground="#111111", background="#FFFFFF"),
            element("directions", "directions", (0.5, 1.3, 4.0, 1.5), text="Compare hierarchy.", foreground="#111111", background="#FFFFFF"),
            element("task", "task", (5.0, 1.3, 4.0, 1.5), text="Choose and explain.", foreground="#111111", background="#FFFFFF"),
            element("preview", "supporting-preview", (6.5, 4.2, 2.5, 2.0)),
        ),
    )

    result = evaluate_slide_layout(plan)

    assert result.passed
    assert not result.manual_review_required
    assert result.findings == ()


def test_unknown_required_text_colors_route_to_manual_review_not_false_pass():
    plan = SlidePlan(
        width=10,
        height=7.5,
        elements=(element("directions", "directions", (0.5, 1, 9, 1), text="Do the task."),),
    )

    result = evaluate_slide_layout(plan)

    assert result.passed
    assert result.manual_review_required
    assert finding_codes(result) == {"contrast-unprovable"}


def test_intentional_layering_does_not_trigger_region_collision():
    plan = SlidePlan(
        width=10,
        height=7.5,
        elements=(
            element("model", "model", (1, 1, 6, 5), intentional_layering=True),
            element("teacher-cue", "teacher-cue", (5, 4, 3, 1), text="Notice spacing", foreground="#111111", background="#FFFFFF"),
        ),
        focal_model=True,
    )

    assert "required-region-collision" not in finding_codes(evaluate_slide_layout(plan))


def test_focal_model_can_be_dominant_without_global_visual_shrink():
    plan = SlidePlan(
        width=10,
        height=7.5,
        elements=(element("model", "model", (0.5, 1.0, 7.0, 5.0)),),
        focal_model=True,
    )

    assert "focal-model-underdominant" not in finding_codes(evaluate_slide_layout(plan))


def test_small_focal_model_is_rejected():
    plan = SlidePlan(
        width=10,
        height=7.5,
        elements=(element("model", "model", (1, 1, 3, 2)),),
        focal_model=True,
    )

    assert "focal-model-underdominant" in finding_codes(evaluate_slide_layout(plan))
