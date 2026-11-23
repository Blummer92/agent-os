"""Regression tests for #3213: teacher-guide voice fails closed on student pages."""
from __future__ import annotations

import pytest

from instructional_materials_coach.student_material_pdf import (
    StudentMaterialPdfError,
    StudentMaterialPdfSource,
    render_student_material_pdf_preview,
)
from instructional_materials_coach.student_voice import (
    TEACHER_VOICE_PHRASES,
    known_teacher_voice_phrases,
    normalize_phrase,
    scan_teacher_voice,
)

# Exact teacher-talk examples quoted from the leaked Motion Spot student
# pages (#3213). Each must be caught by the scan.
LEAKED_EXAMPLES = (
    "Early stage (Days 1-2): name and plan the feeling change. Heavy modeling, "
    "sentence frames, and the ZAP! example carry the thinking - use them.",
    "Middle stage (Days 3-5): build, check, and choose purposeful motion.",
    "Late stage (Days 6-8): use critique, revise, export, and explain.",
    "One revision focus: fixing one thing keeps revision manageable and visible.",
    "Gate rule: you do not move into the next production step until the current gate is clear.",
    "Recovery rule: recovery means getting back into the project - not redoing the unit.",
    "Teacher model: Notice: the change names feelings, not vague words like cool or fun.",
)

STUDENT_VOICE_COPY = (
    "Name: ____________________    Hour: ________    Date: ________",
    "Today's move: pick ONE motion for your candy and make it match your feeling word.",
    "Worked example: here's how ZAP! did it - copy the move, not the words.",
    "Exit ticket: what is one motion choice you made today that you can explain?",
)


def _source(**overrides):
    values = dict(
        artifact_role="worksheet",
        native_file_id="doc-3213",
        native_revision_id="rev-1",
        target_folder_id="approved-folder",
        title="Candy Brand Motion Spot - Day 3",
        paragraphs=STUDENT_VOICE_COPY,
    )
    values.update(overrides)
    return StudentMaterialPdfSource(**values)


def test_scan_catches_every_leaked_teacher_voice_example():
    for leaked in LEAKED_EXAMPLES:
        found = scan_teacher_voice((leaked,))
        assert found, f"teacher voice not caught: {leaked!r}"


def test_scan_is_case_and_whitespace_insensitive():
    assert scan_teacher_voice(("  HEAVY\n\tMODELING  ",)) == ("heavy modeling",)


def test_scan_passes_clean_student_voice_copy():
    assert scan_teacher_voice(STUDENT_VOICE_COPY) == ()
    assert scan_teacher_voice(("Use the sentence frames to start your plan.",)) == ()


def test_scan_labels_are_stable_and_deduplicated():
    found = scan_teacher_voice(
        ("Early stage work. Middle stage work. Gate rule: ask first.",)
    )
    assert found == ("rigor-ramp stage label", "teacher-phrased rule")


def test_scan_allowed_phrases_are_treated_as_deliberate():
    found = scan_teacher_voice(("Heavy modeling helps here.",), allowed=("heavy modeling",))
    assert found == ()


def test_known_phrases_bound_the_explicit_declaration_vocabulary():
    known = known_teacher_voice_phrases()
    assert known == {phrase for _, phrase in TEACHER_VOICE_PHRASES}
    assert "heavy modeling" in known
    assert normalize_phrase("  Gate\nRULE ") == "gate rule"


def test_pdf_preview_blocks_leaked_teacher_voice(tmp_path):
    target = tmp_path / "blocked.pdf"
    receipt = render_student_material_pdf_preview(
        _source(paragraphs=STUDENT_VOICE_COPY + (LEAKED_EXAMPLES[0],)),
        target,
        expected_revision_id="rev-1",
    )
    assert receipt.state == "blocked"
    assert not receipt.available
    assert "teacher-guide modeling voice" in receipt.error
    assert not target.exists()


def test_pdf_preview_blocks_teacher_voice_in_title(tmp_path):
    target = tmp_path / "blocked.pdf"
    receipt = render_student_material_pdf_preview(
        _source(title="Day 3 - Teacher model walkthrough"),
        target,
        expected_revision_id="rev-1",
    )
    assert receipt.state == "blocked"
    assert "teacher modeling script" in receipt.error


def test_pdf_preview_renders_clean_student_voice(tmp_path):
    target = tmp_path / "clean.pdf"
    receipt = render_student_material_pdf_preview(
        _source(), target, expected_revision_id="rev-1"
    )
    assert receipt.available
    assert target.read_bytes().startswith(b"%PDF-")


def test_explicit_declaration_allows_deliberate_teacher_voice_use(tmp_path):
    target = tmp_path / "declared.pdf"
    receipt = render_student_material_pdf_preview(
        _source(
            paragraphs=STUDENT_VOICE_COPY + ("Heavy modeling is our shared word for demo day.",),
            explicit_student_copy_teacher_voice_phrases=("heavy modeling",),
        ),
        target,
        expected_revision_id="rev-1",
    )
    assert receipt.available


def test_unknown_explicit_declaration_fails_closed(tmp_path):
    target = tmp_path / "blocked.pdf"
    receipt = render_student_material_pdf_preview(
        _source(explicit_student_copy_teacher_voice_phrases=("hevy modeling",)),
        target,
        expected_revision_id="rev-1",
    )
    assert receipt.state == "blocked"
    assert "unknown student-copy teacher-voice phrase" in receipt.error


def test_duplicate_explicit_declaration_fails_closed(tmp_path):
    target = tmp_path / "blocked.pdf"
    receipt = render_student_material_pdf_preview(
        _source(
            explicit_student_copy_teacher_voice_phrases=("gate rule", "Gate Rule"),
        ),
        target,
        expected_revision_id="rev-1",
    )
    assert receipt.state == "blocked"
    assert "must be unique" in receipt.error


def test_explicit_declaration_must_be_tuple(tmp_path):
    target = tmp_path / "blocked.pdf"
    receipt = render_student_material_pdf_preview(
        _source(explicit_student_copy_teacher_voice_phrases=["gate rule"]),
        target,
        expected_revision_id="rev-1",
    )
    assert receipt.state == "blocked"
    assert "must be a tuple" in receipt.error
