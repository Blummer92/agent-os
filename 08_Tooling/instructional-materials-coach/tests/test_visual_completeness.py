from instructional_materials_coach.visual_completeness import validate_visual_completeness


def test_no_required_visuals_allows_text_only_material():
    assert validate_visual_completeness(required_roles=(), verified_roles=()).status == "pass"


def test_required_visual_without_verified_placement_fails_and_names_role():
    result = validate_visual_completeness(required_roles=("composition-example",), verified_roles=())
    assert result.status == "fail"
    assert result.missing_roles == ("composition-example",)


def test_required_icon_with_verified_placement_passes():
    result = validate_visual_completeness(required_roles=("camera-icon",), verified_roles=("camera-icon",))
    assert result.status == "pass"


def test_explicit_unresolved_visual_routes_to_manual_review():
    result = validate_visual_completeness(required_roles=("editing-before-after",), verified_roles=(), unresolved_roles=("editing-before-after",))
    assert result.status == "manual-review"
    assert result.unresolved_roles == ("editing-before-after",)


def test_photography_style_multiple_required_roles_cannot_disappear_silently():
    result = validate_visual_completeness(required_roles=("blind-photo-example", "critique-image", "portfolio-example"), verified_roles=())
    assert result.status == "fail"
    assert result.missing_roles == ("blind-photo-example", "critique-image", "portfolio-example")
