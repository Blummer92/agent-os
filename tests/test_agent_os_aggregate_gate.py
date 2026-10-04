"""Tests for the terminal aggregator-gate decision (#3114).

The gate is the CI-level backstop for the workflow-vs-aggregate confusion:
GitHub reports skipped jobs as Success on the enclosing workflow, so the
gate must fail unless the authoritative aggregate job itself reports exactly
``success``. These tests simulate each upstream disposition — including the
#3105/#3106/#3108 skipped-aggregate shape — and assert the gate outcome.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.agent_os_aggregate_gate import evaluate_aggregate_gate, main

ROOT = Path(__file__).resolve().parents[1]


def test_skipped_aggregate_closes_the_gate():
    gate_open, message = evaluate_aggregate_gate("skipped")
    assert gate_open is False
    assert "skipped" in message


@pytest.mark.parametrize("result", ["failure", "cancelled", "timed_out", ""])
def test_non_success_dispositions_close_the_gate(result):
    gate_open, _ = evaluate_aggregate_gate(result)
    assert gate_open is False


def test_exact_success_opens_the_gate():
    gate_open, message = evaluate_aggregate_gate("success")
    assert gate_open is True
    assert "gate open" in message


def test_near_success_values_do_not_open_the_gate():
    for result in ["Success", "SUCCESS", "successful", "success "]:
        assert evaluate_aggregate_gate(result)[0] is False


def test_non_string_result_is_rejected():
    with pytest.raises(TypeError):
        evaluate_aggregate_gate(None)


def test_main_exits_nonzero_for_skipped_aggregate(monkeypatch):
    monkeypatch.setenv("VALIDATE_RESULT", "skipped")
    monkeypatch.setenv("PLAN_RESULT", "success")
    assert main() == 1


def test_main_exits_zero_for_successful_aggregate(monkeypatch):
    monkeypatch.setenv("VALIDATE_RESULT", "success")
    monkeypatch.setenv("PLAN_RESULT", "skipped")
    assert main() == 0


def test_script_entrypoint_skipped_aggregate_exits_nonzero():
    env = dict(os.environ, VALIDATE_RESULT="skipped", PLAN_RESULT="success")
    completed = subprocess.run(
        [sys.executable, "scripts/agent_os_aggregate_gate.py"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert completed.returncode == 1
    assert "gate is closed" in completed.stderr


# --- #2589 authoritative commit-status decision matrix ----------------------

import json  # noqa: E402

import yaml  # noqa: E402

from scripts.agent_os_aggregate_gate import (  # noqa: E402
    AUTHORITATIVE_STATUS_CONTEXT,
    decide_terminal_status,
)

WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"


def _decide(**kw):
    base = dict(authoritative=True, reused=False, validate_result="success", aggregate_outcome="success")
    base.update(kw)
    return decide_terminal_status(**base)


def test_canonical_context_identity():
    assert AUTHORITATIVE_STATUS_CONTEXT == "agent-os/authoritative-aggregate"


def test_non_authoritative_runs_never_publish():
    # Ordinary Draft / diagnostic / main-push runs: no status, in every disposition.
    for result in ("success", "failure", "cancelled", "skipped", ""):
        assert _decide(authoritative=False, validate_result=result) is None


def test_real_aggregate_success_publishes_success():
    assert _decide().state == "success"


def test_success_without_successful_aggregate_step_is_not_success():
    assert _decide(aggregate_outcome="skipped").state == "error"
    assert _decide(aggregate_outcome="").state == "error"


def test_reused_success_republishes_nothing():
    assert _decide(reused=True, aggregate_outcome="skipped") is None


def test_aggregate_failure_publishes_failure():
    assert _decide(validate_result="failure", aggregate_outcome="failure").state == "failure"


def test_infrastructure_failure_publishes_error():
    assert _decide(validate_result="failure", aggregate_outcome="skipped").state == "error"


@pytest.mark.parametrize("result", ["cancelled", "skipped", "timed_out", ""])
def test_cancelled_or_unreported_never_publishes_success(result):
    assert _decide(validate_result=result, aggregate_outcome="").state == "error"


def test_main_health_withheld_is_pending_not_failure():
    for key in ("main_health_outcome", "main_recovery_stop_outcome"):
        decision = _decide(validate_result="failure", aggregate_outcome="skipped", **{key: "failure"})
        assert decision.state == "pending"


def test_only_exact_success_inputs_can_produce_success():
    for result in ("failure", "cancelled", "skipped", "", "Success"):
        for outcome in ("success", "failure", "cancelled", "skipped", ""):
            for health in ("", "failure"):
                decision = _decide(validate_result=result, aggregate_outcome=outcome, main_health_outcome=health)
                assert decision is None or decision.state != "success"


def test_status_cli_prints_json_or_nothing():
    base = dict(os.environ, AUTHORITATIVE="true", VALIDATE_RESULT="failure", AGGREGATE_OUTCOME="failure")
    done = subprocess.run(
        [sys.executable, "scripts/agent_os_aggregate_gate.py", "status"],
        env=base, capture_output=True, text=True, cwd=str(ROOT), check=True,
    )
    assert json.loads(done.stdout)["state"] == "failure"
    base["AUTHORITATIVE"] = "false"
    done = subprocess.run(
        [sys.executable, "scripts/agent_os_aggregate_gate.py", "status"],
        env=base, capture_output=True, text=True, cwd=str(ROOT), check=True,
    )
    assert done.stdout == ""


def test_statuses_write_is_granted_only_to_validate_and_aggregate_gate():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert "statuses" not in workflow["permissions"]
    granted = {name for name, job in workflow["jobs"].items() if job.get("permissions", {}).get("statuses") == "write"}
    assert granted == {"validate", "aggregate-gate"}
    for name in granted:
        assert workflow["jobs"][name]["permissions"]["contents"] == "read"
        assert not any(v == "write" for k, v in workflow["jobs"][name]["permissions"].items() if k != "statuses")


def test_pending_is_published_before_expensive_work_and_only_when_authoritative():
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["validate"]["steps"]
    names = [s.get("name") for s in steps]
    pending = names.index("Publish authoritative aggregate pending status")
    assert pending < names.index("Check out repository")
    assert pending < names.index("Run aggregate validation")
    assert pending > names.index("Reuse valid exact-head aggregate evidence")
    cond = steps[pending]["if"]
    assert "authoritative == 'true'" in cond and "run_required != 'false'" in cond
    assert "-f state=pending" in steps[pending]["run"]
    assert "agent-os/authoritative-aggregate" in steps[pending]["run"]


def test_ordinary_draft_publishes_no_status_by_job_conditions():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job in ("validate", "aggregate-gate"):
        assert "pull_request.draft == false" in workflow["jobs"][job]["if"]
    # plan job (the only Draft-running job) must never touch commit statuses.
    assert "statuses" not in json.dumps(workflow["jobs"]["plan"])
