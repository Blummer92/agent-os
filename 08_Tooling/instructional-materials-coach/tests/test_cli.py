import yaml
from unittest.mock import patch


def _lesson_file(tmp_path):
    lesson_file = tmp_path / "lesson.yaml"
    lesson_file.write_text(
        "title: Fractions Intro\n"
        "objectives:\n  - Add fractions\n"
        "slides:\n  - index: 1\n    bullets: [Hello]\n"
        "worksheet_questions:\n  - Q1?\n"
    )
    return lesson_file


def test_main_refuses_without_allow_write(monkeypatch, capsys):
    from instructional_materials_coach import cli

    monkeypatch.delenv("ALLOW_WRITE", raising=False)
    exit_code = cli.main(
        ["build", "--content", "x.yaml", "--slides-template", "a", "--doc-template", "b", "--target-folder", "c"]
    )
    assert exit_code == 1
    assert "ALLOW_WRITE" in capsys.readouterr().err


def test_main_full_flow_mocked(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli

    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)

    with (
        patch("instructional_materials_coach.cli.get_credentials", return_value="creds"),
        patch("instructional_materials_coach.cli.build_drive_service"),
        patch("instructional_materials_coach.cli.build_slides_service"),
        patch("instructional_materials_coach.cli.build_docs_service"),
        patch(
            "instructional_materials_coach.cli.duplicate_template",
            side_effect=["slides-id", "doc-id"],
        ) as dup,
        patch("instructional_materials_coach.cli.apply_slides_requests") as apply_slides,
        patch("instructional_materials_coach.cli.apply_docs_requests") as apply_docs,
        patch(
            "instructional_materials_coach.cli.get_file_link",
            side_effect=["https://example/slides", "https://example/doc"],
        ),
    ):
        exit_code = cli.main(
            [
                "build",
                "--content",
                str(lesson_file),
                "--slides-template",
                "slides-template-id",
                "--doc-template",
                "doc-template-id",
                "--target-folder",
                "folder-id",
            ]
        )

    assert exit_code == 0
    assert dup.call_count == 2
    apply_slides.assert_called_once()
    apply_docs.assert_called_once()
    output = capsys.readouterr().out
    assert "https://example/slides" in output
    assert "https://example/doc" in output


def test_main_build_failure_writes_lesson_record_and_never_touches_notion(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli

    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    lessons_dir = tmp_path / "lessons"

    with (
        patch("instructional_materials_coach.cli.get_credentials", return_value="creds"),
        patch("instructional_materials_coach.cli.build_drive_service"),
        patch(
            "instructional_materials_coach.cli.duplicate_template",
            side_effect=RuntimeError("Drive API rejected the template ID"),
        ),
    ):
        exit_code = cli.main(
            [
                "build",
                "--content",
                str(lesson_file),
                "--slides-template",
                "bad-template-id",
                "--doc-template",
                "doc-template-id",
                "--target-folder",
                "folder-id",
                "--lessons-dir",
                str(lessons_dir),
            ]
        )

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "Build failed" in stderr
    assert "Lesson recorded" in stderr

    lesson_files = list(lessons_dir.glob("*.yaml"))
    assert len(lesson_files) == 1
    record = yaml.safe_load(lesson_files[0].read_text())
    assert record["learning_type"] == "Mistake"
    assert "Drive API rejected the template ID" in record["what_happened"]
    assert record["applies_to"] == ["Instructional Materials"]
    # This module never imports a Notion client -- the only output is the
    # local YAML file (the docstring mentions Notion in prose, which is fine).
    assert "notion" not in cli.__file__.lower()
    assert not any("notion" in line.lower() and "import" in line.lower() for line in open(cli.__file__))


def test_log_lesson_writes_record_without_building(tmp_path, capsys):
    from instructional_materials_coach import cli

    lessons_dir = tmp_path / "lessons"
    exit_code = cli.main(
        [
            "log-lesson",
            "--title",
            "Template had a stale placeholder",
            "--what-happened",
            "QA caught {{objective_2}} left unreplaced in a delivered deck.",
            "--what-to-do-next-time",
            "Validate all tokens are replaced before sharing the link.",
            "--severity",
            "Medium",
            "--learning-type",
            "QA feedback",
            "--lessons-dir",
            str(lessons_dir),
        ]
    )

    assert exit_code == 0
    assert "Lesson recorded" in capsys.readouterr().out
    lesson_files = list(lessons_dir.glob("*.yaml"))
    assert len(lesson_files) == 1
    record = yaml.safe_load(lesson_files[0].read_text())
    assert record["learning_type"] == "QA feedback"
    assert record["severity"] == "Medium"
