from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.agent_os_pr_remediation.cli import evaluate, main, render_text
from scripts.agent_os_pr_remediation.models import (
    AUTHORITY_FIELDS,
    EvidenceValidationError,
    canonical_json,
)

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "agent_os_pr_remediation" / "e2e.json"
CLI_PATH = Path(__file__).parents[2] / "scripts" / "agent_os_pr_remediation" / "cli.py"


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _assert_authority_false(value: object) -> None:
    if type(value) is dict:
        for field in AUTHORITY_FIELDS:
            if field in value:
                assert value[field] is False
        for item in value.values():
            _assert_authority_false(item)
    elif type(value) in {list, tuple}:
        for item in value:
            _assert_authority_false(item)


def test_exact_head_e2e_composes_existing_contracts() -> None:
    report = evaluate(_fixture())

    assert report["contract_version"] == "agent-os-pr-remediation-cli/v1"
    assert report["preflight"]["overall_status"] == "pass"
    assert len(report["remediation_plan"]["findings"]) == 1
    assert report["remediation_plan"]["findings"][0]["classification"] == "actionable"
    assert len(report["resolution_plan"]["thread_results"]) == 1

    thread = report["resolution_plan"]["thread_results"][0]
    assert thread["validation_state"] == "validation-passed"
    assert thread["resolution_eligible"] is True
    assert thread["suggested_action"] == "eligible-to-resolve"
    assert report["remediation_plan"]["optional_failure_evidence_id"] is not None
    assert report["remediation_plan"]["optional_repair_handoff_id"] is not None
    _assert_authority_false(report)


def test_json_and_text_output_are_deterministic() -> None:
    first = evaluate(_fixture())
    second = evaluate(deepcopy(_fixture()))

    assert canonical_json(first) == canonical_json(second)
    text = render_text(first)
    assert "preflight: pass" in text
    assert "validation-passed -> eligible-to-resolve" in text
    assert "authority: execution=false external-write=false merge=false side-effects=false" in text


def test_moved_expected_head_fails_closed_without_side_effect() -> None:
    payload = _fixture()
    payload["expected_head"] = "3333333333333333333333333333333333333333"

    report = evaluate(payload)
    thread = report["resolution_plan"]["thread_results"][0]

    assert report["preflight"]["overall_status"] == "fail"
    assert thread["resolution_eligible"] is False
    assert "preflight-fail" in thread["ineligibility_reason_codes"]
    _assert_authority_false(report)


def test_out_of_scope_finding_is_routed_not_executed() -> None:
    payload = _fixture()
    payload["candidates"][0]["affected_files"] = ["forbidden/example.py"]
    payload["finding_fixes"] = []

    report = evaluate(payload)
    finding = report["remediation_plan"]["findings"][0]
    thread = report["resolution_plan"]["thread_results"][0]

    assert finding["classification"] == "out-of-scope"
    assert thread["resolution_eligible"] is False
    assert thread["suggested_action"] == "route-out-of-scope"
    _assert_authority_false(report)


def test_focused_pass_with_aggregate_pending_stays_incomplete() -> None:
    payload = _fixture()
    binding = payload["validation_evidence"][0]
    binding["profile"] = "focused"
    binding["execution_status"] = "focused-pass-aggregate-pending"
    binding["aggregate_pending"] = True

    report = evaluate(payload)
    thread = report["resolution_plan"]["thread_results"][0]

    assert thread["resolution_eligible"] is False
    assert thread["validation_state"] == "validation-incomplete"
    assert thread["suggested_action"] == "request-more-evidence"
    assert "aggregate-validation-pending" in thread["ineligibility_reason_codes"]


def test_unknown_malformed_and_oversized_input_fail_closed() -> None:
    unknown = _fixture()
    unknown["unexpected"] = True
    with pytest.raises(EvidenceValidationError):
        evaluate(unknown)

    malformed = _fixture()
    malformed["snapshot"]["head_sha"] = "not-a-sha"
    with pytest.raises(EvidenceValidationError):
        evaluate(malformed)

    oversized = _fixture()
    oversized["candidates"][0]["requested_summary"] = "x" * 10_001
    with pytest.raises(EvidenceValidationError):
        evaluate(oversized)


def test_cli_entrypoint_emits_canonical_json_and_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--input", str(FIXTURE_PATH), "--format", "json"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.strip() == canonical_json(evaluate(_fixture()))

    assert main(["--input", str(FIXTURE_PATH), "--format", "text"]) == 0
    captured = capsys.readouterr()
    assert "Agent OS PR remediation evaluation" in captured.out
    assert "eligible-to-resolve" in captured.out
    assert captured.err == ""


def test_cli_has_no_network_execution_model_or_mutating_path() -> None:
    tree = ast.parse(CLI_PATH.read_text(encoding="utf-8"))
    forbidden_import_roots = {
        "requests",
        "urllib",
        "socket",
        "subprocess",
        "github",
        "openai",
        "anthropic",
    }
    forbidden_calls = {
        "system",
        "popen",
        "run",
        "call",
        "check_call",
        "check_output",
        "eval",
        "exec",
        "__import__",
        "write_text",
        "write_bytes",
        "update_file",
        "create_file",
        "resolve_review_thread",
        "merge_pull_request",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] not in forbidden_import_roots for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_import_roots
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls
