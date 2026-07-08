import yaml
import pytest

from instructional_materials_coach.lesson_record import (
    LessonRecord,
    lesson_from_exception,
    record_lesson,
)


def test_lesson_record_rejects_invalid_severity():
    with pytest.raises(ValueError, match="severity"):
        LessonRecord(lesson_learned="x", what_happened="y", severity="Extreme")


def test_lesson_record_rejects_invalid_learning_type():
    with pytest.raises(ValueError, match="learning_type"):
        LessonRecord(lesson_learned="x", what_happened="y", learning_type="Whoopsie")


def test_lesson_record_defaults_are_valid():
    record = LessonRecord(lesson_learned="x", what_happened="y")
    assert record.severity == "Low"
    assert record.area == "Curriculum"
    assert record.applies_to == ["Instructional Materials"]


def test_lesson_from_exception_captures_context():
    exc = RuntimeError("template not found")
    context = {"content_title": "Fractions Intro", "slides_template": "abc123"}
    record = lesson_from_exception(exc, context)
    assert record.learning_type == "Mistake"
    assert record.severity == "Medium"
    assert "Fractions Intro" in record.lesson_learned
    assert "template not found" in record.what_happened
    assert "abc123" in record.what_happened
    assert record.follow_up_needed is True
    assert record.surface_before_work is True


def test_lesson_from_exception_falls_back_when_no_title_in_context():
    record = lesson_from_exception(ValueError("bad yaml"), {})
    assert "Instructional materials build" in record.lesson_learned


def test_record_lesson_writes_yaml_matching_notion_schema_fields(tmp_path):
    record = LessonRecord(
        lesson_learned="Build failure: Fractions Intro",
        what_happened="Drive API rejected the template ID",
        what_to_do_next_time="Confirm template ID before retrying",
        severity="Medium",
        source_link="https://example/log",
    )
    path = record_lesson(record, tmp_path)

    assert path.exists()
    assert path.parent == tmp_path
    data = yaml.safe_load(path.read_text())
    assert data["lesson_learned"] == "Build failure: Fractions Intro"
    assert data["owner_agent"] == "Instructional Materials Coach"
    assert set(data.keys()) == {
        "lesson_learned",
        "what_happened",
        "what_to_do_next_time",
        "guardrail",
        "owner_agent",
        "severity",
        "learning_type",
        "area",
        "applies_to",
        "source_type",
        "source_link",
        "follow_up_needed",
        "surface_before_work",
    }


def test_record_lesson_creates_output_dir_if_missing(tmp_path):
    output_dir = tmp_path / "does" / "not" / "exist" / "yet"
    record = LessonRecord(lesson_learned="x", what_happened="y")
    path = record_lesson(record, output_dir)
    assert path.exists()


def test_record_lesson_filenames_are_unique_per_call(tmp_path):
    record = LessonRecord(lesson_learned="Same title", what_happened="y")
    path_a = record_lesson(record, tmp_path)
    path_b = record_lesson(record, tmp_path)
    assert path_a != path_b
