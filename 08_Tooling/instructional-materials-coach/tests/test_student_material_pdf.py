from pathlib import Path
from unittest.mock import patch

from reportlab.lib.styles import getSampleStyleSheet

import instructional_materials_coach.student_material_pdf as student_pdf
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


def _placement(role_id, *, artifact_id="doc-123", artifact_type="docs", artifact_revision_id="rev-7"):
    return PlacementReceipt(
        asset_id=f"asset-{role_id}",
        drive_file_id=f"drive-{role_id}",
        role_id=role_id,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        artifact_revision_id=artifact_revision_id,
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


def test_default_worksheet_story_uses_compact_header_and_integrated_student_info():
    story = student_pdf._build_story(_source(), getSampleStyleSheet())

    assert story[0].getPlainText() == "Photography Foundations - Worksheet"
    assert story[0].style.fontSize == 14
    assert story[0].style.leading == 16
    meta = story[1].getPlainText()
    assert "Name:" in meta and "Hour:" in meta and "Date:" in meta

    paragraph_text = [item.getPlainText() for item in story if hasattr(item, "getPlainText")]
    assert "Name: ____________________" not in paragraph_text
    assert "Explain aperture in your own words." in paragraph_text


def test_compact_header_reclaims_vertical_space_against_legacy_title_plus_name_line():
    styles = getSampleStyleSheet()
    source = _source()
    compact = student_pdf._compact_worksheet_header_flowables(source, styles)
    legacy = [
        student_pdf.Paragraph(source.title, styles["Title"]),
        student_pdf.Spacer(1, 10),
        student_pdf.Paragraph(source.paragraphs[0], styles["BodyText"]),
        student_pdf.Spacer(1, 7),
    ]

    def height(flowables):
        return sum(item.wrap(468, 1000)[1] for item in flowables)

    assert height(compact) <= height(legacy) - 12


def test_compact_header_can_be_opted_out_without_suppressing_legacy_identification():
    story = student_pdf._build_story(
        _source(compact_worksheet_header=False),
        getSampleStyleSheet(),
    )

    assert story[0].style.name == "Title"
    assert story[2].getPlainText() == "Name: ____________________"


def test_unit_day_and_lesson_sections_stay_below_compact_header_for_1568_coordination():
    source = _source(
        unit_day="1.1",
        paragraphs=(
            "Warm-Up: What do you notice?",
            "Core task: photograph one object five ways.",
            "Exit Ticket: Which choice was strongest and why?",
        ),
    )
    story = student_pdf._build_story(source, getSampleStyleSheet())

    assert "Unit/Day: 1.1" in story[1].getPlainText()
    paragraph_text = [item.getPlainText() for item in story if hasattr(item, "getPlainText")]
    assert paragraph_text[0] == "Photography Foundations - Worksheet"
    assert paragraph_text[1].startswith("Name:")
    assert "Warm-Up: What do you notice?" in paragraph_text[2:]
    assert "Exit Ticket: Which choice was strongest and why?" in paragraph_text[2:]


def test_compact_header_inputs_are_bounded_and_fail_closed(tmp_path):
    cases = (
        _source(compact_worksheet_header="yes"),
        _source(student_identification_labels=("Name",) * 5),
        _source(student_identification_labels=("Name", "Name")),
        _source(unit_day=" " + ("1" * 33)),
    )
    for index, source in enumerate(cases):
        receipt = render_student_material_pdf_preview(
            source,
            tmp_path / f"invalid-header-{index}.pdf",
            expected_revision_id="rev-7",
        )
        assert receipt.state == "blocked" and not receipt.available


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


def test_verified_placements_do_not_claim_rendered_visuals_in_text_only_pdf(tmp_path):
    target = tmp_path / "photography-with-placements.pdf"
    source = _source(
        required_visual_role_ids=("blind-photo-example", "camera-icon"),
        verified_visual_placements=(
            _placement("blind-photo-example"),
            _placement("camera-icon"),
        ),
    )

    receipt = render_student_material_pdf_preview(source, target, expected_revision_id="rev-7")

    assert receipt.state == "blocked" and not receipt.available
    assert receipt.render_verified is False
    assert receipt.unresolved_visual_role_ids == ()
    assert "visual render evidence is unavailable" in receipt.error
    assert not target.exists()


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


def test_verification_failure_does_not_replace_existing_output(tmp_path):
    target = tmp_path / "existing.pdf"
    sentinel = b"previous verified artifact"
    target.write_bytes(sentinel)

    with patch("instructional_materials_coach.student_material_pdf._verify_pdf", side_effect=ValueError("bad render")):
        receipt = render_student_material_pdf_preview(_source(), target, expected_revision_id="rev-7")

    assert receipt.state == "blocked" and not receipt.available
    assert target.read_bytes() == sentinel
    assert list(tmp_path.glob(".existing.pdf.*.tmp")) == []


def test_verification_failure_leaves_no_new_final_output(tmp_path):
    target = tmp_path / "new.pdf"

    with patch("instructional_materials_coach.student_material_pdf._verify_pdf", side_effect=ValueError("bad render")):
        receipt = render_student_material_pdf_preview(_source(), target, expected_revision_id="rev-7")

    assert receipt.state == "blocked"
    assert not target.exists()
    assert list(tmp_path.glob(".new.pdf.*.tmp")) == []


def test_visual_placement_from_older_native_revision_is_rejected(tmp_path):
    source = _source(
        revision="rev-99",
        required_visual_role_ids=("camera-icon",),
        verified_visual_placements=(
            _placement("camera-icon", artifact_revision_id="rev-7"),
        ),
    )

    receipt = render_student_material_pdf_preview(
        source,
        tmp_path / "stale-placement.pdf",
        expected_revision_id="rev-99",
    )

    assert receipt.state == "blocked" and not receipt.available
    assert "exact preview source revision" in receipt.error


def test_unsupported_artifact_roles_fail_closed_without_visual_requirements(tmp_path):
    for role in ("banana", "pdf", "handout"):
        receipt = render_student_material_pdf_preview(
            _source(artifact_role=role),
            tmp_path / f"{role}.pdf",
            expected_revision_id="rev-7",
        )
        assert receipt.state == "blocked" and not receipt.available
        assert "artifact_role does not map" in receipt.error


def test_pdf_verifier_rejects_header_and_eof_garbage(tmp_path):
    import instructional_materials_coach.student_material_pdf as module

    target = tmp_path / "fake.pdf"
    target.write_bytes(b"%PDF-1.7\\n" + (b"X" * 100) + b"\\n%%EOF\\n")

    try:
        module._verify_pdf(target)
    except module.StudentMaterialPdfError as exc:
        assert "verification failed" in str(exc)
    else:
        raise AssertionError("PDF-shaped garbage must not pass verification")


def test_2736_wrapped_mission_prompt_uses_paragraph_owned_height_before_followup() -> None:
    source = _source(
        paragraphs=(
            "You finished a worksheet but are not sure it submitted. " * 4,
            "What should you check?",
        )
    )
    story = student_pdf._build_story(source, getSampleStyleSheet())
    paragraphs = [item for item in story if hasattr(item, "getPlainText")]
    prompt = next(item for item in paragraphs if item.getPlainText().startswith("You finished"))
    followup = next(item for item in paragraphs if item.getPlainText() == "What should you check?")
    assert prompt.wrap(240, 1000)[1] > prompt.style.leading
    assert story.index(followup) > story.index(prompt)
    between = story[story.index(prompt) + 1 : story.index(followup)]
    assert any(isinstance(item, student_pdf.Spacer) and item.height >= 7 for item in between)
