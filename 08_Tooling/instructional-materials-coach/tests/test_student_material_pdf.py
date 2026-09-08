from pathlib import Path
from unittest.mock import patch

from instructional_materials_coach.student_material_pdf import (
    StudentMaterialPdfSource,
    render_student_material_pdf_preview,
)


def _source(revision="rev-7"):
    return StudentMaterialPdfSource(
        artifact_role="worksheet",
        native_file_id="doc-123",
        native_revision_id=revision,
        target_folder_id="approved-folder",
        title="Photography Foundations - Worksheet",
        paragraphs=("Name: ____________________", "Explain aperture in your own words."),
    )


def test_exact_source_revision_produces_render_verified_noncanonical_preview(tmp_path):
    target = tmp_path / "worksheet-preview.pdf"
    receipt = render_student_material_pdf_preview(_source(), target, expected_revision_id="rev-7")
    assert receipt.available
    assert receipt.state == "preview" and receipt.render_verified and receipt.canonical is False
    assert receipt.source_file_id == "doc-123" and receipt.source_revision_id == "rev-7"
    assert receipt.source_target_folder_id == "approved-folder"
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
