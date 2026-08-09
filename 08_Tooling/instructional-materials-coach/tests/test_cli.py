import json
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "instructional_workflow_contracts"


def _lesson_file(tmp_path):
    lesson_file = tmp_path / "lesson.yaml"
    lesson_file.write_text(
        "title: Fractions Intro\n"
        "objectives:\n  - Add fractions\n"
        "slides:\n  - index: 1\n    bullets: [Hello]\n"
        "worksheet_questions:\n  - Q1?\n"
    )
    return lesson_file


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _write_json(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _no_visual_requirement_file(tmp_path):
    from instructional_workflow_contracts.material_requirement import (
        material_requirement_source_fingerprint,
    )

    requirement = _fixture("valid_material_requirement_v2.json")
    requirement["visual_direction"] = {
        "decision": "no-visuals",
        "maximum_visual_count": 0,
        "roles": [],
    }
    requirement["identity"]["source_fingerprint"] = (
        material_requirement_source_fingerprint(requirement)
    )
    return _write_json(tmp_path, "no-visual-requirement.json", requirement)


def _base_build_args(lesson_file, requirement_file):
    return [
        "build",
        "--content",
        str(lesson_file),
        "--slides-template",
        "slides-template-id",
        "--doc-template",
        "doc-template-id",
        "--target-folder",
        "folder-id",
        "--material-requirement",
        str(requirement_file),
    ]


def test_main_refuses_without_allow_write(monkeypatch, capsys):
    from instructional_materials_coach import cli

    monkeypatch.delenv("ALLOW_WRITE", raising=False)
    exit_code = cli.main(
        ["build", "--content", "x.yaml", "--slides-template", "a", "--doc-template", "b", "--target-folder", "c"]
    )
    assert exit_code == 1
    assert "ALLOW_WRITE" in capsys.readouterr().err


def test_main_full_flow_mocked_with_no_visual_requirement(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli

    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    requirement_file = _no_visual_requirement_file(tmp_path)

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
        exit_code = cli.main(_base_build_args(lesson_file, requirement_file))

    assert exit_code == 0
    assert dup.call_count == 2
    apply_slides.assert_called_once()
    apply_docs.assert_called_once()
    output = capsys.readouterr().out
    assert "https://example/slides" in output
    assert "https://example/doc" in output


def test_main_requires_material_requirement_before_credentials(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli

    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    lessons_dir = tmp_path / "lessons"

    with patch("instructional_materials_coach.cli.get_credentials") as credentials:
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
                "--lessons-dir",
                str(lessons_dir),
            ]
        )

    assert exit_code == 1
    credentials.assert_not_called()
    assert "MaterialRequirement" in capsys.readouterr().err


def test_main_visual_gap_blocks_before_credentials(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli

    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    requirement_file = _write_json(
        tmp_path,
        "visual-requirement.json",
        _fixture("valid_material_requirement_v2.json"),
    )
    lessons_dir = tmp_path / "lessons"

    with patch("instructional_materials_coach.cli.get_credentials") as credentials:
        exit_code = cli.main(
            _base_build_args(lesson_file, requirement_file)
            + [
                "--visual-source-revision",
                "visual-library-snapshot-v2",
                "--lessons-dir",
                str(lessons_dir),
            ]
        )

    assert exit_code == 1
    credentials.assert_not_called()
    stderr = capsys.readouterr().err
    assert "visual-gap-blocked" in stderr
    assert "image_gap_briefs=1" in stderr


def test_main_complete_visual_plan_preserves_selected_asset_id(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli

    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    requirement_file = _write_json(
        tmp_path,
        "visual-requirement.json",
        _fixture("valid_material_requirement_v2.json"),
    )
    manifests_file = _write_json(
        tmp_path,
        "artifact-manifests.json",
        [_fixture("valid_artifact_manifest.json")],
    )
    candidates_file = _write_json(
        tmp_path,
        "visual-candidates.json",
        [_fixture("valid_visual_asset_compatibility_v2.json")],
    )

    with (
        patch("instructional_materials_coach.cli.get_credentials", return_value="creds"),
        patch("instructional_materials_coach.cli.build_drive_service"),
        patch("instructional_materials_coach.cli.build_slides_service"),
        patch("instructional_materials_coach.cli.build_docs_service"),
        patch(
            "instructional_materials_coach.cli.duplicate_template",
            side_effect=["slides-id", "doc-id"],
        ),
        patch("instructional_materials_coach.cli.apply_slides_requests"),
        patch("instructional_materials_coach.cli.apply_docs_requests"),
        patch(
            "instructional_materials_coach.cli.get_file_link",
            side_effect=["https://example/slides", "https://example/doc"],
        ),
    ):
        exit_code = cli.main(
            _base_build_args(lesson_file, requirement_file)
            + [
                "--artifact-manifests",
                str(manifests_file),
                "--visual-candidates",
                str(candidates_file),
                "--visual-source-revision",
                "visual-library-snapshot-v2",
            ]
        )

    assert exit_code == 0
    assert "Approved visual assets: asset-1" in capsys.readouterr().out


def test_main_build_failure_writes_lesson_record_and_never_touches_notion(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli

    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    requirement_file = _no_visual_requirement_file(tmp_path)
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
            _base_build_args(lesson_file, requirement_file)
            + ["--lessons-dir", str(lessons_dir)]
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
