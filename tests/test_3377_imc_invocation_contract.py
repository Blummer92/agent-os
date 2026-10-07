"""#3377: the Scheduler's Instructional Materials dry-run command plan must
match the current ``imc-build build`` governed-input contract.

The C3A validator renders an inert argv and never imports the Materials Coach
package. This root test is the cross-package guard: it feeds the rendered argv
to the real CLI with credential acquisition stubbed to abort, proving the plan
clears every pre-credential governed-input check, and that dropping either
governed input reproduces the CLI's own fail-closed refusal.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from instructional_materials_coach import cli
from instructional_workflow_contracts.material_requirement import (
    material_requirement_source_fingerprint,
)
from workflow_scheduler.adapters.instructional_materials_contract import (
    CONTRACT_VERSION,
    validate_instructional_materials_contract,
)
from workflow_scheduler.models import ExecutionContext, ExecutionRequest

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "instructional_workflow_contracts"

CONTENT_PATH = "lessons/lesson.yaml"
MATERIAL_REQUIREMENT_PATH = "governed/material-requirement.json"
CURRICULUM_EVIDENCE_PATH = "governed/current-curriculum-evidence.json"

_GATE_KEYS = (
    "unit-generation-approval",
    "packet-generation-gate",
    "instructional-materials-readiness",
    "source-control-gate",
    "production-authorized",
)


class _CredentialBoundaryReached(BaseException):
    """Raised instead of acquiring credentials; escapes ``cli.main``'s handler."""


def _reference(stable_id):
    return {
        "system": "notion",
        "stable_id": stable_id,
        "exact_location": f"collection://fixture/{stable_id}",
        "verification_evidence": "fixture-read-back",
    }


def _owner_evidence(evidence_id, decision_key, value):
    return {
        "evidence_id": evidence_id,
        "owner": "instructional-materials-coach",
        "decision_key": decision_key,
        "value": value,
        "classification": "owner-governed",
        "source_revision": 1,
        "observed_at": "2026-08-28T12:00:00Z",
        "currentness": "current",
        "material": True,
        "relation_resolved": True,
        "reference": _reference(evidence_id),
    }


def _write_governed_inputs(base: Path) -> None:
    (base / "lessons").mkdir()
    (base / "governed").mkdir()
    (base / CONTENT_PATH).write_text(
        "title: Fractions Intro\nobjectives:\n  - Add fractions\nslides:\n"
        "  - index: 1\n    bullets: [Hello]\nworksheet_questions:\n  - Q1?\n",
        encoding="utf-8",
    )
    requirement = json.loads(
        (FIXTURES / "valid_material_requirement_v2.json").read_text(encoding="utf-8")
    )
    requirement["visual_direction"] = {"decision": "no-visuals", "maximum_visual_count": 0, "roles": []}
    requirement["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(requirement)
    (base / MATERIAL_REQUIREMENT_PATH).write_text(json.dumps(requirement), encoding="utf-8")

    owner_evidence = [
        _owner_evidence(f"gate-{index}", key, "ready") for index, key in enumerate(_GATE_KEYS)
    ]
    owner_evidence.append(_owner_evidence("section-directions", "directions", "Follow the worksheet directions."))
    owner_evidence.append(_owner_evidence("section-practice", "practice", "Complete the guided practice."))
    evidence = {
        "contract_version": "curriculum-current-state-evidence-v1",
        "canonical_unit": {"stable_id": "fixture-unit", "status": "active"},
        "request": {
            "action": "make",
            "artifact_type": "worksheet",
            "relative_time": "none",
            "requires_reusable_assets": False,
        },
        "required_decision_keys": list(_GATE_KEYS),
        "owner_evidence": owner_evidence,
        "asset_evidence": [],
    }
    (base / CURRICULUM_EVIDENCE_PATH).write_text(json.dumps(evidence), encoding="utf-8")


def _payload():
    return {
        "contract_version": CONTRACT_VERSION,
        "operation": "build_materials_bundle",
        "dry_run": True,
        "execution_authorized": False,
        "content_path": CONTENT_PATH,
        "material_requirement_path": MATERIAL_REQUIREMENT_PATH,
        "current_curriculum_evidence_path": CURRICULUM_EVIDENCE_PATH,
        "slides_template_id": "slides-template_123",
        "doc_template_id": "doc-template_123",
        "target_drive_folder_id": "folder_123",
        "lessons_dir": "reports/lessons",
        "production_gates": {
            "source_confidence": "approved",
            "unit_readiness": "ready",
            "modeling_readiness": "ready_for_slides",
            "evidence_target": "modeling-handoff-123",
            "blockers": "none",
        },
        "governed_field_risk": False,
        "writes_governed_field": False,
    }


def _rendered_argv() -> list[str]:
    request = ExecutionRequest(
        task_id="build-materials-bundle",
        workflow_id="classroom-artifact-dry-run-v1",
        owner="instructional-materials-coach",
        payload=_payload(),
        idempotency_key="operator-key-123",
        mode="Draft",
        approval_required=False,
        production_ready=False,
        execution_id="exec-1",
        run_id="run-1",
        attempt_number=1,
        created_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
        execution_context=ExecutionContext(),
        batch_id=None,
    )
    result = validate_instructional_materials_contract(request)
    assert result["status"] == "success", result
    command = result["output"]["command"]
    assert command[:2] == ["imc-build", "build"]
    return command[1:]


@pytest.fixture
def governed_workspace(tmp_path, monkeypatch):
    _write_governed_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ALLOW_WRITE", "true")
    return tmp_path


def test_rendered_plan_clears_every_pre_credential_governed_input_check(governed_workspace):
    argv = _rendered_argv()
    parsed = cli.parse_args(argv)
    assert parsed.material_requirement == MATERIAL_REQUIREMENT_PATH
    assert parsed.current_curriculum_evidence == CURRICULUM_EVIDENCE_PATH

    with patch.object(cli, "get_credentials", side_effect=_CredentialBoundaryReached):
        with pytest.raises(_CredentialBoundaryReached):
            cli.main(argv)


@pytest.mark.parametrize(
    ("flag", "refusal"),
    (
        ("--material-requirement", "Governed MaterialRequirement JSON is required"),
        ("--current-curriculum-evidence", "Governed current-curriculum evidence is required"),
    ),
)
def test_dropping_a_governed_input_reproduces_the_cli_refusal(governed_workspace, capsys, flag, refusal):
    argv = _rendered_argv()
    index = argv.index(flag)
    del argv[index : index + 2]

    with patch.object(cli, "get_credentials", side_effect=_CredentialBoundaryReached) as credentials:
        assert cli.main(argv) == 1
    credentials.assert_not_called()
    assert refusal in capsys.readouterr().err
