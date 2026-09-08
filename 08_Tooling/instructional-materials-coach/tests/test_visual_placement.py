import pytest

from instructional_materials_coach.visual_placement import (
    VisualPlacementError,
    build_placement_request,
    marker_for_role,
    resolve_exact_target,
    retry_is_safe,
    verify_placement_receipt,
)


def _target(kind="slides"):
    role = "visual-role-abc123"
    return resolve_exact_target(
        artifact_type=kind,
        artifact_id="artifact-1",
        role_id=role,
        matches=[{
            "marker": marker_for_role(role),
            "container_id": "slide-1" if kind == "slides" else "body-1",
            "element_id": "marker-1",
            "index": None if kind == "slides" else 3,
            "bounds": {"left": 10, "top": 20, "width": 300, "height": 200} if kind == "slides" else None,
        }],
    )


def _request(kind="slides"):
    return build_placement_request(
        selected_asset={"asset_id": "asset-1", "drive_file_id": "drive-file-1"},
        role_id="visual-role-abc123",
        source_plan_id="visual-plan-1",
        target=_target(kind),
    )


@pytest.mark.parametrize("kind", ["docs", "slides"])
def test_preserves_exact_selected_identity(kind):
    request = _request(kind)
    assert request.asset_id == "asset-1"
    assert request.drive_file_id == "drive-file-1"
    assert request.role_id == "visual-role-abc123"
    assert request.target.artifact_type == kind


def test_exact_single_marker_is_required():
    role = "visual-role-abc123"
    with pytest.raises(VisualPlacementError, match="exactly one"):
        resolve_exact_target(artifact_type="slides", artifact_id="a", role_id=role, matches=[])
    with pytest.raises(VisualPlacementError, match="exactly one"):
        resolve_exact_target(
            artifact_type="slides",
            artifact_id="a",
            role_id=role,
            matches=[{"marker": marker_for_role(role)}, {"marker": marker_for_role(role)}],
        )


def test_marker_must_bind_requested_role():
    with pytest.raises(VisualPlacementError, match="does not bind"):
        resolve_exact_target(
            artifact_type="slides",
            artifact_id="a",
            role_id="visual-role-abc123",
            matches=[{"marker": "{{visual:visual-role-other}}", "container_id": "s", "element_id": "e"}],
        )


def test_receipt_requires_exact_identity_before_verified():
    request = _request()
    receipt = {
        "state": "placed",
        "asset_id": request.asset_id,
        "drive_file_id": request.drive_file_id,
        "role_id": request.role_id,
        "artifact_type": request.target.artifact_type,
        "artifact_id": request.target.artifact_id,
        "marker": request.target.marker,
        "container_id": request.target.container_id,
        "inserted_element_id": "image-1",
    }
    verified = verify_placement_receipt(request, receipt)
    assert verified.state == "verified"
    bad = dict(receipt, asset_id="asset-other")
    with pytest.raises(VisualPlacementError, match="asset_id mismatch"):
        verify_placement_receipt(request, bad)


def test_transport_success_without_placed_state_is_not_verified():
    with pytest.raises(VisualPlacementError, match="not a completed placement"):
        verify_placement_receipt(_request(), {"state": "transport-ok"})


def test_ambiguous_outcome_never_allows_blind_retry():
    request = _request()
    assert retry_is_safe(request=request, receipt=None) is False
    assert retry_is_safe(request=request, receipt={"state": "unknown"}) is False


def test_retry_requires_positive_not_placed_identity_evidence():
    request = _request()
    receipt = {
        "state": "not-placed",
        "asset_id": request.asset_id,
        "drive_file_id": request.drive_file_id,
        "role_id": request.role_id,
        "artifact_type": request.target.artifact_type,
        "artifact_id": request.target.artifact_id,
        "marker": request.target.marker,
        "container_id": request.target.container_id,
        "inserted_element_id": None,
    }
    assert retry_is_safe(request=request, receipt=receipt) is True
    assert retry_is_safe(request=request, receipt=dict(receipt, marker="{{visual:other}}")) is False


def test_coarse_semantic_placement_is_not_an_exact_target():
    with pytest.raises(VisualPlacementError):
        resolve_exact_target(
            artifact_type="slides",
            artifact_id="artifact-1",
            role_id="visual-role-abc123",
            matches=[{"marker": "slide", "container_id": "slide-1", "element_id": "marker-1"}],
        )
