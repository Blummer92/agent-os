import pytest

from instructional_materials_coach.content_spec import content_from_dict, load_lesson_content


def test_content_from_dict_builds_placeholder_tokens():
    content = content_from_dict(
        {
            "title": "Fractions Intro",
            "objectives": ["Add fractions", "Compare fractions"],
            "slides": [{"index": 1, "heading": "Welcome", "bullets": ["Hello", "Today's plan"]}],
            "worksheet_questions": ["What is 1/2 + 1/4?"],
        }
    )
    tokens = content.placeholder_tokens()
    assert tokens["title"] == "Fractions Intro"
    assert tokens["objective_1"] == "Add fractions"
    assert tokens["objective_2"] == "Compare fractions"
    assert tokens["slide_1_heading"] == "Welcome"
    assert tokens["slide_1_bullet_1"] == "Hello"
    assert tokens["slide_1_bullet_2"] == "Today's plan"
    assert tokens["question_1"] == "What is 1/2 + 1/4?"


def test_content_from_dict_missing_keys_raises():
    with pytest.raises(ValueError, match="missing required keys"):
        content_from_dict({"title": "Only a title"})


def test_load_lesson_content_reads_yaml_file(tmp_path):
    lesson_file = tmp_path / "lesson.yaml"
    lesson_file.write_text(
        "title: Fractions Intro\n"
        "objectives:\n  - Add fractions\n"
        "slides:\n  - index: 1\n    heading: Welcome\n    bullets: [Hello]\n"
        "worksheet_questions:\n  - What is 1/2 + 1/4?\n"
    )
    content = load_lesson_content(lesson_file)
    assert content.title == "Fractions Intro"
    assert content.placeholder_tokens()["slide_1_heading"] == "Welcome"
