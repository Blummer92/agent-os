import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "instructional_workflow_contracts"


def _lesson_file(tmp_path):
    lesson_file = tmp_path / "lesson.yaml"
    lesson_file.write_text("title: Fractions Intro\nobjectives:\n  - Add fractions\nslides:\n  - index: 1\n    bullets: [Hello]\nworksheet_questions:\n  - Q1?\n")
    return lesson_file


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _write_json(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _no_visual_requirement_file(tmp_path):
    from instructional_workflow_contracts.material_requirement import material_requirement_source_fingerprint
    requirement = _fixture("valid_material_requirement_v2.json")
    requirement["visual_direction"] = {"decision": "no-visuals", "maximum_visual_count": 0, "roles": []}
    requirement["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(requirement)
    return _write_json(tmp_path, "no-visual-requirement.json", requirement)


def _current_curriculum_evidence_file(tmp_path):
    gate_keys = (
        "unit-generation-approval",
        "packet-generation-gate",
        "instructional-materials-readiness",
        "source-control-gate",
        "production-authorized",
    )

    def reference(stable_id):
        return {
            "system": "notion",
            "stable_id": stable_id,
            "exact_location": f"collection://fixture/{stable_id}",
            "verification_evidence": "fixture-read-back",
        }

    owner_evidence = []
    for index, decision_key in enumerate(gate_keys):
        evidence_id = f"gate-{index}"
        owner_evidence.append(
            {
                "evidence_id": evidence_id,
                "owner": "instructional-materials-coach",
                "decision_key": decision_key,
                "value": "ready",
                "classification": "owner-governed",
                "source_revision": 1,
                "observed_at": "2026-08-28T12:00:00Z",
                "currentness": "current",
                "material": True,
                "relation_resolved": True,
                "reference": reference(evidence_id),
            }
        )

    return _write_json(
        tmp_path,
        "current-curriculum-evidence.json",
        {
            "contract_version": "curriculum-current-state-evidence-v1",
            "canonical_unit": {"stable_id": "photography-foundations", "status": "active"},
            "request": {
                "action": "make",
                "artifact_type": "worksheet",
                "relative_time": "none",
                "requires_reusable_assets": False,
            },
            "required_decision_keys": list(gate_keys),
            "owner_evidence": owner_evidence,
            "asset_evidence": [],
        },
    )


def _base_build_args(lesson_file, requirement_file):
    return ["build", "--content", str(lesson_file), "--slides-template", "slides-template-id", "--doc-template", "doc-template-id", "--target-folder", "folder-id", "--material-requirement", str(requirement_file)]


def _success_receipt():
    return SimpleNamespace(succeeded=True, slides=SimpleNamespace(web_view_link="https://example/slides"), worksheet=SimpleNamespace(web_view_link="https://example/doc"))


def test_main_refuses_without_allow_write(monkeypatch, capsys):
    from instructional_materials_coach import cli
    monkeypatch.delenv("ALLOW_WRITE", raising=False)
    assert cli.main(["build", "--content", "x.yaml", "--slides-template", "a", "--doc-template", "b", "--target-folder", "c"]) == 1
    assert "ALLOW_WRITE" in capsys.readouterr().err


def test_main_full_flow_delegates_to_live_build(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli
    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    requirement_file = _no_visual_requirement_file(tmp_path)
    evidence_file = _current_curriculum_evidence_file(tmp_path)
    with patch("instructional_materials_coach.cli.get_credentials", return_value="creds"), patch("instructional_materials_coach.cli.build_drive_service", return_value="drive"), patch("instructional_materials_coach.cli.build_slides_service", return_value="slides"), patch("instructional_materials_coach.cli.build_docs_service", return_value="docs"), patch("instructional_materials_coach.cli.build_live_materials", return_value=_success_receipt()) as live:
        exit_code = cli.main(_base_build_args(lesson_file, requirement_file) + ["--current-curriculum-evidence", str(evidence_file)])
    assert exit_code == 0
    live.assert_called_once()
    assert live.call_args.args[0].target_folder_id == "folder-id"
    assert len(live.call_args.args[0].idempotency_key) == 64
    output = capsys.readouterr().out
    assert "https://example/slides" in output and "https://example/doc" in output


def test_idempotency_key_uses_loaded_requirement_snapshot_without_reread(tmp_path):
    from instructional_materials_coach import cli
    requirement_file = _no_visual_requirement_file(tmp_path)
    loaded = json.loads(requirement_file.read_text(encoding="utf-8"))
    args = SimpleNamespace(
        material_requirement=str(requirement_file),
        slides_template="slides-template-id",
        doc_template="doc-template-id",
        target_folder="folder-id",
    )
    requirement_file.unlink()
    key = cli._build_idempotency_key(args, "Fractions Intro", loaded)
    assert len(key) == 64


def test_idempotency_key_changes_with_requirement_identity(tmp_path):
    from instructional_materials_coach import cli
    requirement_file = _no_visual_requirement_file(tmp_path)
    first = json.loads(requirement_file.read_text(encoding="utf-8"))
    second = json.loads(requirement_file.read_text(encoding="utf-8"))
    second["identity"]["record_revision"] = first["identity"]["record_revision"] + 1
    args = SimpleNamespace(
        material_requirement=str(requirement_file),
        slides_template="slides-template-id",
        doc_template="doc-template-id",
        target_folder="folder-id",
    )
    assert cli._build_idempotency_key(args, "Fractions Intro", first) != cli._build_idempotency_key(args, "Fractions Intro", second)


def test_main_requires_material_requirement_before_credentials(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli
    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    lessons_dir = tmp_path / "lessons"
    with patch("instructional_materials_coach.cli.get_credentials") as credentials:
        exit_code = cli.main(["build", "--content", str(lesson_file), "--slides-template", "slides-template-id", "--doc-template", "doc-template-id", "--target-folder", "folder-id", "--lessons-dir", str(lessons_dir)])
    assert exit_code == 1
    credentials.assert_not_called()
    assert "MaterialRequirement" in capsys.readouterr().err


def test_main_requires_current_curriculum_evidence_before_credentials(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli
    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    requirement_file = _no_visual_requirement_file(tmp_path)
    with patch("instructional_materials_coach.cli.get_credentials") as credentials:
        exit_code = cli.main(_base_build_args(lesson_file, requirement_file))
    assert exit_code == 1
    credentials.assert_not_called()
    assert "current-curriculum evidence is required" in capsys.readouterr().err


def test_main_visual_gap_blocks_before_credentials(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli
    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    requirement_file = _write_json(tmp_path, "visual-requirement.json", _fixture("valid_material_requirement_v2.json"))
    evidence_file = _current_curriculum_evidence_file(tmp_path)
    lessons_dir = tmp_path / "lessons"
    with patch("instructional_materials_coach.cli.get_credentials") as credentials:
        exit_code = cli.main(_base_build_args(lesson_file, requirement_file) + ["--current-curriculum-evidence", str(evidence_file), "--visual-source-revision", "visual-library-snapshot-v2", "--lessons-dir", str(lessons_dir)])
    assert exit_code == 1
    credentials.assert_not_called()
    stderr = capsys.readouterr().err
    assert "visual-gap-blocked" in stderr and "image_gap_briefs=1" in stderr


def test_main_complete_visual_plan_preserves_selected_asset_id(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli
    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    requirement_file = _write_json(tmp_path, "visual-requirement.json", _fixture("valid_material_requirement_v2.json"))
    evidence_file = _current_curriculum_evidence_file(tmp_path)
    manifests_file = _write_json(tmp_path, "artifact-manifests.json", [_fixture("valid_artifact_manifest.json")])
    candidates_file = _write_json(tmp_path, "visual-candidates.json", [_fixture("valid_visual_asset_compatibility_v2.json")])
    with patch("instructional_materials_coach.cli.get_credentials", return_value="creds"), patch("instructional_materials_coach.cli.build_drive_service"), patch("instructional_materials_coach.cli.build_slides_service"), patch("instructional_materials_coach.cli.build_docs_service"), patch("instructional_materials_coach.cli.build_live_materials", return_value=_success_receipt()):
        exit_code = cli.main(_base_build_args(lesson_file, requirement_file) + ["--current-curriculum-evidence", str(evidence_file), "--artifact-manifests", str(manifests_file), "--visual-candidates", str(candidates_file), "--visual-source-revision", "visual-library-snapshot-v2"])
    assert exit_code == 0
    assert "Approved visual assets: asset-1" in capsys.readouterr().out


def test_main_build_failure_writes_lesson_record_and_never_touches_notion(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli
    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    requirement_file = _no_visual_requirement_file(tmp_path)
    evidence_file = _current_curriculum_evidence_file(tmp_path)
    lessons_dir = tmp_path / "lessons"
    with patch("instructional_materials_coach.cli.get_credentials", return_value="creds"), patch("instructional_materials_coach.cli.build_drive_service"), patch("instructional_materials_coach.cli.build_slides_service"), patch("instructional_materials_coach.cli.build_docs_service"), patch("instructional_materials_coach.cli.build_live_materials", side_effect=RuntimeError("Drive API rejected the template ID")):
        exit_code = cli.main(_base_build_args(lesson_file, requirement_file) + ["--current-curriculum-evidence", str(evidence_file), "--lessons-dir", str(lessons_dir)])
    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "Build failed" in stderr and "Lesson recorded" in stderr
    record = yaml.safe_load(next(lessons_dir.glob("*.yaml")).read_text())
    assert "Drive API rejected the template ID" in record["what_happened"]
    assert not any("notion" in line.lower() and "import" in line.lower() for line in open(cli.__file__))


def test_log_lesson_writes_record_without_building(tmp_path, capsys):
    from instructional_materials_coach import cli
    lessons_dir = tmp_path / "lessons"
    assert cli.main(["log-lesson", "--title", "Template had a stale placeholder", "--what-happened", "QA caught {{objective_2}} left unreplaced in a delivered deck.", "--what-to-do-next-time", "Validate all tokens are replaced before sharing the link.", "--severity", "Medium", "--learning-type", "QA feedback", "--lessons-dir", str(lessons_dir)]) == 0
    assert len(list(lessons_dir.glob("*.yaml"))) == 1