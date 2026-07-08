from unittest.mock import patch


def test_main_refuses_without_allow_write(monkeypatch, capsys):
    from instructional_materials_coach import cli

    monkeypatch.delenv("ALLOW_WRITE", raising=False)
    exit_code = cli.main(
        ["--content", "x.yaml", "--slides-template", "a", "--doc-template", "b", "--target-folder", "c"]
    )
    assert exit_code == 1
    assert "ALLOW_WRITE" in capsys.readouterr().err


def test_main_full_flow_mocked(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli

    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = tmp_path / "lesson.yaml"
    lesson_file.write_text(
        "title: Fractions Intro\n"
        "objectives:\n  - Add fractions\n"
        "slides:\n  - index: 1\n    bullets: [Hello]\n"
        "worksheet_questions:\n  - Q1?\n"
    )

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
