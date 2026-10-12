import pytest

from instructional_materials_coach.visual_placement import (
    VisualPlacementError,
    build_placement_request,
    marker_for_role,
    resolve_exact_target,
    retry_is_safe,
    verify_placement_receipt,
    verify_request_content_identity,
)


CONTENT_IDENTITY = {
    "contract_version": "governed-asset-content-identity-v1",
    "source": "drive-sha256",
    "algorithm": "sha256",
    "value": "a" * 64,
}


def _target(kind="slides"):
    role = "visual-role-abc123"
    return resolve_exact_target(
        artifact_type=kind,
        artifact_id="artifact-1",
        artifact_revision_id="revision-1",
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
        selected_asset={"asset_id": "asset-1", "drive_file_id": "drive-file-1", "content_identity": dict(CONTENT_IDENTITY)},
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
    assert request.target.artifact_revision_id == "revision-1"


def test_exact_single_marker_is_required():
    role = "visual-role-abc123"
    with pytest.raises(VisualPlacementError, match="exactly one"):
        resolve_exact_target(artifact_type="slides", artifact_id="a", artifact_revision_id="revision-1", role_id=role, matches=[])
    with pytest.raises(VisualPlacementError, match="exactly one"):
        resolve_exact_target(
            artifact_type="slides",
            artifact_id="a",
            artifact_revision_id="revision-1",
            role_id=role,
            matches=[{"marker": marker_for_role(role)}, {"marker": marker_for_role(role)}],
        )


def test_marker_must_bind_requested_role():
    with pytest.raises(VisualPlacementError, match="does not bind"):
        resolve_exact_target(
            artifact_type="slides",
            artifact_id="a",
            artifact_revision_id="revision-1",
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
        "slot_id": request.slot_id,
        "artifact_type": request.target.artifact_type,
        "artifact_id": request.target.artifact_id,
        "artifact_revision_id": request.target.artifact_revision_id,
        "marker": request.target.marker,
        "container_id": request.target.container_id,
        "content_identity": dict(CONTENT_IDENTITY),
        "inserted_element_id": "image-1",
    }
    verified = verify_placement_receipt(request, receipt)
    assert verified.state == "verified"
    assert verified.slot_id == request.slot_id
    bad = dict(receipt, asset_id="asset-other")
    with pytest.raises(VisualPlacementError, match="asset_id mismatch"):
        verify_placement_receipt(request, bad)
    stale = dict(receipt, artifact_revision_id="revision-old")
    with pytest.raises(VisualPlacementError, match="artifact_revision_id mismatch"):
        verify_placement_receipt(request, stale)
    wrong_bytes = dict(receipt, content_identity=dict(CONTENT_IDENTITY, value="b" * 64))
    with pytest.raises(VisualPlacementError, match="content_identity mismatch"):
        verify_placement_receipt(request, wrong_bytes)


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
        "artifact_revision_id": request.target.artifact_revision_id,
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
            artifact_revision_id="revision-1",
            role_id="visual-role-abc123",
            matches=[{"marker": "slide", "container_id": "slide-1", "element_id": "marker-1"}],
        )


def test_instructional_visual_rejects_crop_fit_mode():
    role = "visual-role-abc123"
    with pytest.raises(VisualPlacementError, match="preserve the complete asset"):
        resolve_exact_target(
            artifact_type="slides",
            artifact_id="artifact-1",
            artifact_revision_id="revision-1",
            role_id=role,
            matches=[{
                "marker": marker_for_role(role),
                "container_id": "slide-1",
                "element_id": "marker-1",
                "bounds": {"left": 10, "top": 20, "width": 300, "height": 200},
                "fit_mode": "cover",
                "source_width": 1200,
                "source_height": 800,
            }],
        )


def test_instructional_visual_accepts_complete_asset_contain_mode():
    role = "visual-role-abc123"
    target = resolve_exact_target(
        artifact_type="docs",
        artifact_id="artifact-1",
        artifact_revision_id="revision-1",
        role_id=role,
        matches=[{
            "marker": marker_for_role(role),
            "container_id": "body-1",
            "element_id": "marker-1",
            "index": 3,
            "fit_mode": "contain",
            "source_width": 1200,
            "source_height": 800,
        }],
    )
    assert target.fit_mode == "contain"
    assert (target.source_width, target.source_height) == (1200, 800)


def test_source_dimensions_must_be_complete_positive_pair():
    role = "visual-role-abc123"
    with pytest.raises(VisualPlacementError, match="supplied together"):
        resolve_exact_target(
            artifact_type="docs", artifact_id="a", artifact_revision_id="revision-1", role_id=role,
            matches=[{"marker": marker_for_role(role), "container_id": "b", "element_id": "e", "source_width": 100}],
        )


# --- #3256 content identity -------------------------------------------------

def test_placement_request_requires_content_identity():
    with pytest.raises(VisualPlacementError, match="content identity"):
        build_placement_request(
            selected_asset={"asset_id": "asset-1", "drive_file_id": "drive-file-1"},
            role_id="visual-role-abc123",
            source_plan_id="visual-plan-1",
            target=_target(),
        )


def test_placement_request_rejects_malformed_content_identity():
    with pytest.raises(VisualPlacementError, match="content identity"):
        build_placement_request(
            selected_asset={"asset_id": "asset-1", "drive_file_id": "drive-file-1",
                            "content_identity": {"source": "drive-sha256"}},
            role_id="visual-role-abc123",
            source_plan_id="visual-plan-1",
            target=_target(),
        )


def test_placement_request_binds_content_identity():
    request = _request()
    assert request.content_identity == CONTENT_IDENTITY


def test_verify_request_content_identity_against_fresh_metadata():
    request = _request()
    assert verify_request_content_identity(
        request=request, drive_metadata={"id": "drive-file-1", "sha256Checksum": "a" * 64}) == "content-identity-match"
    assert verify_request_content_identity(
        request=request, drive_metadata={"id": "drive-file-1", "sha256Checksum": "b" * 64}) == "content-identity-mismatch"
    assert verify_request_content_identity(
        request=request, drive_metadata={"id": "drive-file-1"}) == "content-identity-unverifiable"
