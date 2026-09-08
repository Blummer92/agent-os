from pathlib import Path
from unittest.mock import patch

from instructional_materials_coach.student_material_pdf import (
    StudentMaterialPdfSource,
    render_student_material_pdf_preview,
)
from instructional_materials_coach.visual_placement import PlacementReceipt


def _source(revision="rev-7", **overrides):
    values = dict(
        artifact_role="worksheet",
        native_file_id="doc-123",
        native_revision_id=revision,
        target_folder_id="approved-folder",
        title="Photography Foundations - Worksheet",
        paragraphs=("Name: ____________________", "Explain aperture in your own words."),
    )
    values.update(overrides)
    return StudentMaterialPdfSource(**values)


def _placement(role_id, *, artifact_id="doc-123", artifact_type="docs"):
    return PlacementReceipt(
        asset_id=f"asset-{role_id}",
        drive_file_id=f"drive-{role_id}",
        role_id=role_id,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        marker=f"{{{{visual:{role_id}}}}}",
        container_id="body",
        inserted_element_id=f"inserted-{role_id}",
        state="verified",
    )


def test_exact_source_revision_produces_render_verified_noncanonical_preview(tmp_path):
    target = tmp_path / "worksheet-preview.pdf"
    receipt = render_student_material_pdf_preview(_source(), target, expected_revision_id="rev-7")
    assert receipt.available
    assert receipt.state == "preview" and receipt.render_verified and receipt.canonical is False
    assert receipt.source_file_id == "doc-123" and receipt.source_revision_id == "rev-7"
    assert receipt.source_target_folder_id == "approved-folder"
    assert receipt.unresolved_visual_role_ids == ()
    assert Path(receipt.path).read_bytes().startswith(b"%PDF-")


def test_stale_source_revision_is_blocked_without_pdf(tmp_path):
    target = tmp_path / "stale.pdf"
    receipt = render_student_material_pdf_preview(_source("rev-6"), target, expected_revision_id="rev-7")
    assert receipt.state == "blocked" and not receipt.available and not target.exists()
    assert "stale or mismatched" in receipt.error


def test_render_verification_failure_returns_blocked_not_false_preview(tmp_path):
    target = tmp_path / "broken.pdf"
    with patch("instructional_materials_coach.student_material_pdf._verify_pdf", side_effect=ValueError("bad render")):
        receipt = render_student_material_pdf_preview(_source(), target, expected_revision_id="rev-7")
    assert receipt.state == "blocked" and not receipt.render_verified and not receipt.available
    assert "bad render" in receipt.error


def test_preview_contract_has_no_drive_acl_readiness_or_authority_mutation():
    import inspect
    import instructional_materials_coach.student_material_pdf as module
    source = inspect.getsource(module).lower()
    for forbidden in ("googleapiclient", "drive_service", "files().copy", "permissions", "allow_write", "production_authorized", "readiness", "approval"):
        assert forbidden not in source


def test_empty_source_identity_fails_closed(tmp_path):
    source = StudentMaterialPdfSource("worksheet", "", "rev-7", "approved-folder", "Worksheet", ("Question",))
    receipt = render_student_material_pdf_preview(source, tmp_path / "empty.pdf", expected_revision_id="rev-7")
    assert receipt.state == "blocked" and not receipt.available


def test_generated_preview_never_claims_canonical_final(tmp_path):
    receipt = render_student_material_pdf_preview(_source(), tmp_path / "preview.pdf", expected_revision_id="rev-7")
    assert receipt.available and receipt.canonical is False
    assert "preview" in receipt.state


def test_photography_required_image_and_icon_roles_block_text_only_preview(tmp_path):
    target = tmp_path / "photography-text-only.pdf"
    source = _source(required_visual_role_ids=("blind-photo-example", "camera-icon"))

    receipt = render_student_material_pdf_preview(source, target, expected_revision_id="rev-7")

    assert receipt.state == "blocked" and not receipt.available and not target.exists()
    assert receipt.render_verified is False
    assert receipt.unresolved_visual_role_ids == ("blind-photo-example", "camera-icon")
    assert "required visual placement is unresolved" in receipt.error
    assert "blind-photo-example" in receipt.error and "camera-icon" in receipt.error


def test_all_required_visual_roles_with_verified_source_bound_placements_allow_preview(tmp_path):
    target = tmp_path / "photography-with-placements.pdf"
    source = _source(
        required_visual_role_ids=("blind-photo-example", "camera-icon"),
        verified_visual_placements=(
            _placement("blind-photo-example"),
            _placement("camera-icon"),
        ),
    )

    receipt = render_student_material_pdf_preview(source, target, expected_revision_id="rev-7")

    assert receipt.available and receipt.render_verified
    assert receipt.unresolved_visual_role_ids == ()
    assert target.exists()


def test_partial_visual_placement_names_only_unresolved_required_role(tmp_path):
    target = tmp_path / "photography-partial.pdf"
    source = _source(
        required_visual_role_ids=("blind-photo-example", "camera-icon"),
        verified_visual_placements=(_placement("blind-photo-example"),),
    )

    receipt = render_student_material_pdf_preview(source, target, expected_revision_id="rev-7")

    assert receipt.state == "blocked" and not target.exists()
    assert receipt.unresolved_visual_role_ids == ("camera-icon",)
    assert "camera-icon" in receipt.error
    assert "blind-photo-example" not in receipt.error


def test_visual_placement_for_different_native_artifact_is_rejected(tmp_path):
    source = _source(
        required_visual_role_ids=("camera-icon",),
        verified_visual_placements=(_placement("camera-icon", artifact_id="other-doc"),),
    )

    receipt = render_student_material_pdf_preview(source, tmp_path / "wrong-source.pdf", expected_revision_id="rev-7")

    assert receipt.state == "blocked" and not receipt.available
    assert "does not bind the preview source artifact" in receipt.error


def test_duplicate_placement_evidence_for_required_role_fails_closed(tmp_path):
    source = _source(
        required_visual_role_ids=("camera-icon",),
        verified_visual_placements=(_placement("camera-icon"), _placement("camera-icon")),
    )

    receipt = render_student_material_pdf_preview(source, tmp_path / "ambiguous.pdf", expected_revision_id="rev-7")

    assert receipt.state == "blocked" and not receipt.available
    assert "ambiguous placement evidence" in receipt.error
