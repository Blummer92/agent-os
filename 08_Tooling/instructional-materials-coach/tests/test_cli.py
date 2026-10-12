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
    gate_keys = ("unit-generation-approval", "packet-generation-gate", "instructional-materials-readiness", "source-control-gate", "production-authorized")

    def reference(stable_id):
        return {"system": "notion", "stable_id": stable_id, "exact_location": f"collection://fixture/{stable_id}", "verification_evidence": "fixture-read-back"}

    owner_evidence = []
    for index, decision_key in enumerate(gate_keys):
        evidence_id = f"gate-{index}"
        owner_evidence.append({"evidence_id": evidence_id, "owner": "instructional-materials-coach", "decision_key": decision_key, "value": "ready", "classification": "owner-governed", "source_revision": 1, "observed_at": "2026-08-28T12:00:00Z", "currentness": "current", "material": True, "relation_resolved": True, "reference": reference(evidence_id)})
    for decision_key, value in (
        ("directions", "Follow the worksheet directions."),
        ("practice", "Complete the guided practice."),
    ):
        evidence_id = f"section-{decision_key}"
        owner_evidence.append({"evidence_id": evidence_id, "owner": "instructional-materials-coach", "decision_key": decision_key, "value": value, "classification": "owner-governed", "source_revision": 1, "observed_at": "2026-08-28T12:00:00Z", "currentness": "current", "material": True, "relation_resolved": True, "reference": reference(evidence_id)})

    # #3254: asset evidence is produced by the real governed projection from
    # a raw Notion page fixture, not hand-injected. The raw page carries the
    # governed Asset ID, Drive File ID, and approval fields; the projection
    # (not the test) builds the library_reference join.
    asset_evidence = [_projected_cli_asset_evidence()]

    return _write_json(tmp_path, "current-curriculum-evidence.json", {"contract_version": "curriculum-current-state-evidence-v1", "canonical_unit": {"stable_id": "photography-foundations", "status": "active"}, "request": {"action": "make", "artifact_type": "worksheet", "relative_time": "none", "requires_reusable_assets": False}, "required_decision_keys": list(gate_keys), "owner_evidence": owner_evidence, "asset_evidence": asset_evidence})


def _projected_cli_asset_evidence():
    """Build CLI asset evidence via the real #3254 projection.

    The raw page fixture mirrors a Visual Asset Library record with governed
    fields populated. The projection output (not a hand-injected dict) is
    what the CLI consumes, so the test exercises the real producer chain.
    """
    from navigation_registry.connectors.notion_asset_evidence_projection import (
        project_notion_asset_page,
    )
    page = {
        # page-1 matches the valid_visual_asset_compatibility_v2.json fixture's
        # library_reference so the tuple-scoping join succeeds in the CLI test.
        "id": "page-1",
        "properties": {
            "Asset Title": {"type": "title", "title": [{"plain_text": "CLI Fixture Asset"}]},
            "Asset ID": {"type": "rich_text", "rich_text": [{"plain_text": "asset-1"}]},
            "Drive File ID": {"type": "rich_text", "rich_text": [{"plain_text": "file-1"}]},
            "Reuse status": {"type": "status", "status": {"name": "approved"}},
            "Approved use": {"type": "multi_select", "multi_select": [{"name": "student-facing"}]},
            "Canonical Unit": {"type": "relation", "relation": [{"id": "unit-page"}]},
        },
    }
    projected = project_notion_asset_page(page, relation_first=True, reuse_scope="unit-specific")
    assert projected.kind == "evidence" and projected.evidence is not None
    evidence = dict(projected.evidence)
    # The CLI fixture needs the page UUID for the library join; the governed
    # asset_id ("asset-1") is what joins to candidates.
    assert evidence["library_reference"] == {
        "page_id": "page-1",
        "drive_file_id": "file-1",
    }
    return evidence


def test_cli_asset_evidence_comes_from_real_projection():
    """#3254: the CLI fixture's library_reference is projection output, not an
    injected dict. A raw page without governed identity/Drive binding yields
    explicit incomplete-evidence instead of a silent join."""
    from navigation_registry.connectors.notion_asset_evidence_projection import (
        project_notion_asset_page,
    )
    # Negative: no Asset ID, no Drive File ID -> incomplete-evidence.
    bare = project_notion_asset_page(
        {"id": "3907ac78-3131-8111-9999-dddddddddddd", "properties": {}},
        relation_first=True,
        reuse_scope="unit-specific",
    )
    assert bare.kind == "incomplete-evidence"
    assert bare.evidence is None
    # Join: governed identity + drive binding -> library_reference joins.
    joined = _projected_cli_asset_evidence()
    assert joined["asset_id"] == "asset-1"
    assert joined["library_reference"]["drive_file_id"] == "file-1"


def _base_build_args(lesson_file, requirement_file):
    return ["build", "--content", str(lesson_file), "--slides-template", "slides-template-id", "--doc-template", "doc-template-id", "--target-folder", "folder-id", "--material-requirement", str(requirement_file)]


def _success_receipt():
    return SimpleNamespace(succeeded=True, slides=SimpleNamespace(web_view_link="https://example/slides"), worksheet=SimpleNamespace(web_view_link="https://example/doc"))


def test_main_refuses_without_allow_write(monkeypatch, capsys):
    from instructional_materials_coach import cli
    monkeypatch.delenv("ALLOW_WRITE", raising=False)
    assert cli.main(["build", "--content", "x.yaml", "--slides-template", "a", "--doc-template", "b", "--target-folder", "c"]) == 1
    assert "ALLOW_WRITE" in capsys.readouterr().err


def test_main_full_flow_delegates_to_live_build_and_labels_native_finals(monkeypatch, tmp_path, capsys):
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
    assert "Slides final (native Google Slides, canonical editable): https://example/slides" in output
    assert "Worksheet final (native Google Docs, canonical editable): https://example/doc" in output


def test_idempotency_key_uses_loaded_requirement_snapshot_without_reread(tmp_path):
    from instructional_materials_coach import cli
    requirement_file = _no_visual_requirement_file(tmp_path)
    loaded = json.loads(requirement_file.read_text(encoding="utf-8"))
    args = SimpleNamespace(material_requirement=str(requirement_file), slides_template="slides-template-id", doc_template="doc-template-id", target_folder="folder-id")
    requirement_file.unlink()
    key = cli._build_idempotency_key(args, "Fractions Intro", loaded)
    assert len(key) == 64


def test_idempotency_key_changes_with_requirement_identity(tmp_path):
    from instructional_materials_coach import cli
    requirement_file = _no_visual_requirement_file(tmp_path)
    first = json.loads(requirement_file.read_text(encoding="utf-8"))
    second = json.loads(requirement_file.read_text(encoding="utf-8"))
    second["identity"]["record_revision"] = first["identity"]["record_revision"] + 1
    args = SimpleNamespace(material_requirement=str(requirement_file), slides_template="slides-template-id", doc_template="doc-template-id", target_folder="folder-id")
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
    lessons_dir = tmp_path / "lessons"
    with patch("instructional_materials_coach.cli.get_credentials") as credentials:
        exit_code = cli.main(_base_build_args(lesson_file, requirement_file) + ["--lessons-dir", str(lessons_dir)])
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


def test_main_selected_visual_blocks_before_credentials_and_live_build(monkeypatch, tmp_path, capsys):
    """#3257: a selection with no placement runtime fails closed before credentials.

    The old dead-end refusal ("no verified image-placement operation") is
    replaced by the explicit placement-runtime-unavailable blocked state.
    """
    from instructional_materials_coach import cli
    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    requirement_file = _write_json(tmp_path, "visual-requirement.json", _fixture("valid_material_requirement_v2.json"))
    evidence_file = _current_curriculum_evidence_file(tmp_path)
    manifests_file = _write_json(tmp_path, "artifact-manifests.json", [_fixture("valid_artifact_manifest.json")])
    candidates_file = _write_json(tmp_path, "visual-candidates.json", [_fixture("valid_visual_asset_compatibility_v2.json")])
    lessons_dir = tmp_path / "lessons"
    with patch("instructional_materials_coach.cli.get_credentials") as credentials, patch("instructional_materials_coach.cli.build_live_materials") as live:
        exit_code = cli.main(_base_build_args(lesson_file, requirement_file) + ["--current-curriculum-evidence", str(evidence_file), "--artifact-manifests", str(manifests_file), "--visual-candidates", str(candidates_file), "--visual-source-revision", "visual-library-snapshot-v2", "--lessons-dir", str(lessons_dir)])
    assert exit_code == 1
    credentials.assert_not_called()
    live.assert_not_called()
    captured = capsys.readouterr()
    assert "placement-runtime-unavailable" in captured.err
    assert "selected_asset_ids=asset-1" in captured.err
    assert "Approved visual assets" not in captured.out
    record = yaml.safe_load(next(lessons_dir.glob("*.yaml")).read_text())
    assert "placement-runtime-unavailable" in record["what_happened"]
    assert "asset-1" in record["what_happened"]


def test_main_selected_visual_proceeds_with_configured_placement_runtime(monkeypatch, tmp_path, capsys):
    """#3257: the dead-end refusal is gone -- a configured runtime lets the selection through.

    The gate no longer kills the build; placement bindings reach the normal
    connected build composition (build_live_materials, mocked here).
    """
    from instructional_materials_coach import cli
    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    requirement_file = _write_json(tmp_path, "visual-requirement.json", _fixture("valid_material_requirement_v2.json"))
    evidence_file = _current_curriculum_evidence_file(tmp_path)
    manifests_file = _write_json(tmp_path, "artifact-manifests.json", [_fixture("valid_artifact_manifest.json")])
    candidates_file = _write_json(tmp_path, "visual-candidates.json", [_fixture("valid_visual_asset_compatibility_v2.json")])
    lessons_dir = tmp_path / "lessons"
    with (
        patch("instructional_materials_coach.cli.get_credentials", return_value="creds"),
        patch("instructional_materials_coach.cli.build_drive_service", return_value="drive"),
        patch("instructional_materials_coach.cli.build_slides_service", return_value="slides"),
        patch("instructional_materials_coach.cli.build_docs_service", return_value="docs"),
        patch("instructional_materials_coach.cli.get_file_metadata",
              return_value={"id": "file-1", "trashed": False, "sha256Checksum": "c" * 64}),
        patch("instructional_materials_coach.cli.build_placement_transport", return_value="transport") as transport_factory,
        patch("instructional_materials_coach.cli.build_live_materials", return_value=_success_receipt()) as live,
    ):
        exit_code = cli.main(_base_build_args(lesson_file, requirement_file) + ["--current-curriculum-evidence", str(evidence_file), "--artifact-manifests", str(manifests_file), "--visual-candidates", str(candidates_file), "--visual-source-revision", "visual-library-snapshot-v2", "--lessons-dir", str(lessons_dir), "--placement-script-id", "script-123", "--placement-receipts-dir", str(tmp_path / "receipts")])
    assert exit_code == 0
    transport_factory.assert_called_once()
    live.assert_called_once()
    build_input = live.call_args.args[0]
    assert len(build_input.visual_placements) == 1
    binding = build_input.visual_placements[0]
    assert binding.asset_id == "asset-1" and binding.drive_file_id == "file-1"
    assert binding.content_identity["value"] == "c" * 64
    assert live.call_args.kwargs["placement_transport"] == "transport"
    assert "no verified image-placement operation" not in capsys.readouterr().err



def _visual_build_args(tmp_path):
    lesson_file = _lesson_file(tmp_path)
    requirement_file = _write_json(tmp_path, "visual-requirement.json", _fixture("valid_material_requirement_v2.json"))
    evidence_file = _current_curriculum_evidence_file(tmp_path)
    manifests_file = _write_json(tmp_path, "artifact-manifests.json", [_fixture("valid_artifact_manifest.json")])
    candidates_file = _write_json(tmp_path, "visual-candidates.json", [_fixture("valid_visual_asset_compatibility_v2.json")])
    lessons_dir = tmp_path / "lessons"
    return _base_build_args(lesson_file, requirement_file) + ["--current-curriculum-evidence", str(evidence_file), "--artifact-manifests", str(manifests_file), "--visual-candidates", str(candidates_file), "--visual-source-revision", "visual-library-snapshot-v2", "--lessons-dir", str(lessons_dir)]


def test_main_unresolvable_asset_slot_blocks_before_live_build(monkeypatch, tmp_path, capsys):
    """#3130: when a selected asset slot has no live Drive file, no build requests are emitted."""
    from instructional_materials_coach import cli
    monkeypatch.setenv("ALLOW_WRITE", "true")
    with (
        patch("instructional_materials_coach.cli.get_credentials", return_value="creds"),
        patch("instructional_materials_coach.cli.build_drive_service", return_value="drive"),
        patch("instructional_materials_coach.cli.build_slides_service", return_value="slides"),
        patch("instructional_materials_coach.cli.build_docs_service", return_value="docs"),
        # A future verified image-placement operation would pass this gate; the
        # asset-slot gate must still fail closed before any connected write.
        patch("instructional_materials_coach.cli._require_visual_placement_support"),
        patch("instructional_materials_coach.cli.get_file_metadata", side_effect=RuntimeError("drive lookup failed")),
        patch("instructional_materials_coach.cli.build_live_materials") as live,
    ):
        exit_code = cli.main(_visual_build_args(tmp_path))
    assert exit_code == 1
    live.assert_not_called()
    captured = capsys.readouterr()
    assert "unresolvable_asset_slots=asset-1" in captured.err
    assert "labeled image placeholders" in captured.err


def test_main_resolvable_asset_slot_allows_build(monkeypatch, tmp_path, capsys):
    """The asset-slot gate lets the build through when every selected slot resolves."""
    from instructional_materials_coach import cli
    monkeypatch.setenv("ALLOW_WRITE", "true")
    with (
        patch("instructional_materials_coach.cli.get_credentials", return_value="creds"),
        patch("instructional_materials_coach.cli.build_drive_service", return_value="drive"),
        patch("instructional_materials_coach.cli.build_slides_service", return_value="slides"),
        patch("instructional_materials_coach.cli.build_docs_service", return_value="docs"),
        patch("instructional_materials_coach.cli._require_visual_placement_support"),
        patch("instructional_materials_coach.cli.get_file_metadata",
              return_value={"id": "file-1", "trashed": False, "sha256Checksum": "c" * 64}),
        patch("instructional_materials_coach.cli.build_live_materials", return_value=_success_receipt()) as live,
    ):
        exit_code = cli.main(_visual_build_args(tmp_path))
    assert exit_code == 0
    live.assert_called_once()
    assert "unresolvable" not in capsys.readouterr().err


def test_main_required_worksheet_section_missing_from_plan_blocks_before_credentials(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli
    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    requirement_file = _no_visual_requirement_file(tmp_path)
    evidence_file = _current_curriculum_evidence_file(tmp_path)
    lessons_dir = tmp_path / "lessons"
    original_builder = cli.build_docs_replace_requests

    def missing_practice(content):
        return [
            request
            for request in original_builder(content)
            if request["replaceAllText"]["containsText"]["text"] != "{{curriculum_practice}}"
        ]

    with patch("instructional_materials_coach.cli.build_docs_replace_requests", side_effect=missing_practice), patch("instructional_materials_coach.cli.get_credentials") as credentials, patch("instructional_materials_coach.cli.build_live_materials") as live:
        exit_code = cli.main(_base_build_args(lesson_file, requirement_file) + ["--current-curriculum-evidence", str(evidence_file), "--lessons-dir", str(lessons_dir)])
    assert exit_code == 1
    credentials.assert_not_called()
    live.assert_not_called()
    assert "fail" in capsys.readouterr().err
    record = yaml.safe_load(next(lessons_dir.glob("*.yaml")).read_text())
    assert "practice" in record["what_happened"]


def test_main_unobservable_required_worksheet_section_blocks_for_manual_review(monkeypatch, tmp_path, capsys):
    from instructional_materials_coach import cli
    from instructional_workflow_contracts.material_requirement import material_requirement_source_fingerprint

    monkeypatch.setenv("ALLOW_WRITE", "true")
    lesson_file = _lesson_file(tmp_path)
    requirement = json.loads(_no_visual_requirement_file(tmp_path).read_text(encoding="utf-8"))
    requirement["instructional"]["required_sections"].append("worked-example")
    requirement["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(requirement)
    requirement_file = _write_json(tmp_path, "manual-review-requirement.json", requirement)
    evidence_file = _current_curriculum_evidence_file(tmp_path)
    lessons_dir = tmp_path / "lessons"

    with patch("instructional_materials_coach.cli.get_credentials") as credentials, patch("instructional_materials_coach.cli.build_live_materials") as live:
        exit_code = cli.main(_base_build_args(lesson_file, requirement_file) + ["--current-curriculum-evidence", str(evidence_file), "--lessons-dir", str(lessons_dir)])
    assert exit_code == 1
    credentials.assert_not_called()
    live.assert_not_called()
    assert "manual-review" in capsys.readouterr().err

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


def _admission_build_input(key, visual_placements=()):
    from instructional_materials_coach.live_build import LiveBuildInput
    return LiveBuildInput(
        slides_template_id="st", doc_template_id="dt", target_folder_id="folder",
        slides_name="S", doc_name="W", idempotency_key=key,
        slides_requests=(), docs_requests=(), visual_placements=tuple(visual_placements),
    )


def _admission_live_receipt(key):
    from instructional_materials_coach.artifact_content_qa import ArtifactQAReport, TerminalQAReport
    from instructional_materials_coach.drive_client import GOOGLE_DOCS_MIME, GOOGLE_SLIDES_MIME
    from instructional_materials_coach.live_build import ArtifactReceipt, LiveBuildReceipt

    def artifact(role, file_id, mime):
        return ArtifactReceipt(
            role=role, state="updated", file_id=file_id, mime_type=mime,
            parents=("folder",), persistence_verified=True, canonical_editable=True,
            delivery_kind="final", terminal_qa_state="verified",
        )

    qa = TerminalQAReport(
        idempotency_key=key,
        slides=ArtifactQAReport(
            artifact_type="slides", artifact_id="sf", revision_id="sr",
            idempotency_key=key, state="verified"),
        worksheet=ArtifactQAReport(
            artifact_type="worksheet", artifact_id="df", revision_id="dr",
            idempotency_key=key, state="verified"),
        state="verified",
    )
    return LiveBuildReceipt(
        slides=artifact("slides", "sf", GOOGLE_SLIDES_MIME),
        worksheet=artifact("worksheet", "df", GOOGLE_DOCS_MIME),
        terminal_qa=qa,
    )


def test_admission_out_writes_non_authorizing_verdict(tmp_path, capsys):
    """#3556: --admission-out surfaces the D8 verdict as evidence, never a claim."""
    from instructional_materials_coach import cli
    from instructional_materials_coach.build_receipt import build_receipt_record
    from instructional_materials_coach.connected_visual_placement import VisualPlacementBinding
    from instructional_materials_coach.placement_receipts import append_placement_record

    key = "cli-admission-key"
    requirement_identity = {
        "requirement_id": "req-cli", "contract_version": "material-requirement-v1",
        "record_revision": "r1", "source_fingerprint": "fp1",
    }
    template_revisions = {"slides": "ts1", "worksheet": "tw1"}
    binding = VisualPlacementBinding(
        role_id="inline-analysis-diagram", asset_id="asset-1", drive_file_id="drive-1",
        content_identity={"asset_id": "asset-1", "revision": "v1"},
        source_plan_id="plan-1", required=True, slot_id="0",
    )
    build_input = _admission_build_input(key, (binding,))
    receipt = _admission_live_receipt(key)
    record = build_receipt_record(
        build_input, receipt, requirement_identity=requirement_identity,
        template_revisions=template_revisions,
    )
    placement_dir = tmp_path / "placement-receipts"
    append_placement_record(
        placement_dir, key,
        {
            "asset_id": "asset-1", "drive_file_id": "drive-1",
            "role_id": "inline-analysis-diagram", "slot_id": "0",
            "artifact_type": "slides", "artifact_id": "sf",
            "artifact_revision_id": "sr", "state": "verified",
            "content_identity": {"asset_id": "asset-1", "revision": "v1"},
            "source_plan_id": "plan-1", "required": True,
            "eligibility_evidence": None, "transport": "test",
            "post_insertion_revision_id": "sr",
        },
    )
    args = SimpleNamespace(
        admission_out=str(tmp_path / "verdict.json"),
        placement_receipts_dir=str(placement_dir),
    )
    result = cli._write_classroom_admission_verdict(
        args, build_input, receipt, requirement_identity, template_revisions, record)
    assert result.status.value == "admitted"
    verdict = json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["status"] == "admitted"
    assert verdict["reason_codes"] == ["classroom.evidence-complete"]
    assert verdict["classroom_ready_granted"] is False
    assert verdict["authoritative"] is False
    assert verdict["execution_authorized"] is False
    assert verdict["production_authorized"] is False
    assert verdict["side_effects_performed"] is False
    assert "non-authorizing" in capsys.readouterr().out


def test_admission_out_fails_closed_without_placement_evidence(tmp_path, capsys):
    """#3556: a required visual with no verified placement record is not admitted."""
    from instructional_materials_coach import cli
    from instructional_materials_coach.build_receipt import build_receipt_record
    from instructional_materials_coach.connected_visual_placement import VisualPlacementBinding

    key = "cli-admission-key-2"
    requirement_identity = {
        "requirement_id": "req-cli", "contract_version": "material-requirement-v1",
        "record_revision": "r1", "source_fingerprint": "fp1",
    }
    template_revisions = {"slides": "ts1", "worksheet": "tw1"}
    binding = VisualPlacementBinding(
        role_id="inline-analysis-diagram", asset_id="asset-1", drive_file_id="drive-1",
        content_identity={"asset_id": "asset-1", "revision": "v1"},
        source_plan_id="plan-1", required=True, slot_id="0",
    )
    build_input = _admission_build_input(key, (binding,))
    receipt = _admission_live_receipt(key)
    record = build_receipt_record(
        build_input, receipt, requirement_identity=requirement_identity,
        template_revisions=template_revisions,
    )
    args = SimpleNamespace(
        admission_out=str(tmp_path / "verdict.json"),
        placement_receipts_dir=str(tmp_path / "empty-placement-receipts"),
    )
    result = cli._write_classroom_admission_verdict(
        args, build_input, receipt, requirement_identity, template_revisions, record)
    assert result.status.value == "not-admitted"
    verdict = json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["status"] == "not-admitted"
    assert "classroom.placement-receipt-missing" in verdict["reason_codes"]
    assert verdict["classroom_ready_granted"] is False
