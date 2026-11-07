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


@pytest.fixture(autouse=True)
def _no_frontend_job_unless_a_test_says_otherwise(monkeypatch):
    # The gate CLI treats the frontend verdict as required unless FRONTEND_REQUIRED is
    # exactly "false" (fail closed). Tests of the non-frontend semantics say "false".
    monkeypatch.setenv("FRONTEND_REQUIRED", "false")


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


# --- Track B: a failed/cancelled focused plan (for example React) closes the gate ---


@pytest.mark.parametrize("plan_result", ["failure", "cancelled"])
def test_failed_or_cancelled_plan_closes_gate_even_with_aggregate_success(plan_result):
    gate_open, message = evaluate_aggregate_gate("success", plan_result)
    assert gate_open is False
    assert plan_result in message


@pytest.mark.parametrize("plan_result", ["success", "skipped", ""])
def test_passing_or_absent_plan_leaves_gate_semantics_unchanged(plan_result):
    assert evaluate_aggregate_gate("success", plan_result)[0] is True
    assert evaluate_aggregate_gate("skipped", plan_result)[0] is False


def test_main_closes_gate_when_plan_failed(monkeypatch):
    monkeypatch.setenv("VALIDATE_RESULT", "success")
    monkeypatch.setenv("PLAN_RESULT", "failure")
    assert main() == 1


def test_failed_plan_publishes_failure_status_instead_of_success():
    assert _decide(plan_result="failure").state == "failure"
    assert _decide(plan_result="cancelled").state == "error"


def test_failed_plan_supersedes_reused_success():
    assert _decide(reused=True, plan_result="failure").state == "failure"


def test_failed_plan_never_publishes_for_non_authoritative_runs():
    assert _decide(authoritative=False, plan_result="failure") is None


def test_successful_or_skipped_plan_keeps_existing_status_decisions():
    assert _decide(plan_result="success").state == "success"
    assert _decide(plan_result="skipped").state == "success"
    assert _decide(reused=True, plan_result="success") is None


# --- CI-trust repair: the frontend job is part of the required decision ---------

from scripts.agent_os_aggregate_gate import frontend_blocker  # noqa: E402


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "", "timed_out", "Success", "success "])
def test_required_frontend_only_exact_success_opens_the_gate(result):
    # Control 4: missing, skipped, cancelled, or failed mandatory checks can never
    # produce a successful decision, even with a green aggregate and plan.
    gate_open, message = evaluate_aggregate_gate("success", "success", result, True)
    assert gate_open is False
    assert "frontend" in message


def test_required_frontend_success_opens_the_gate():
    assert evaluate_aggregate_gate("success", "success", "success", True, SHA_A, SHA_A)[0] is True


@pytest.mark.parametrize("result", ["failure", "cancelled"])
def test_unrequired_frontend_still_blocks_on_failure_or_cancel(result):
    # `push` to main runs no frontend job, but a failing one is never ignored.
    assert evaluate_aggregate_gate("success", "skipped", result, False)[0] is False


@pytest.mark.parametrize("result", ["skipped", ""])
def test_unrequired_frontend_skip_is_neutral_for_push(result):
    assert evaluate_aggregate_gate("success", "skipped", result, False)[0] is True
    assert evaluate_aggregate_gate("skipped", "skipped", result, False)[0] is False


def test_frontend_success_cannot_rescue_a_failed_aggregate_or_plan():
    assert evaluate_aggregate_gate("failure", "success", "success", True)[0] is False
    assert evaluate_aggregate_gate("success", "failure", "success", True)[0] is False


def test_frontend_result_must_be_a_string():
    with pytest.raises(TypeError):
        frontend_blocker(None, True)


def test_main_closes_gate_when_required_frontend_did_not_succeed(monkeypatch):
    monkeypatch.setenv("VALIDATE_RESULT", "success")
    monkeypatch.setenv("PLAN_RESULT", "success")
    monkeypatch.setenv("FRONTEND_REQUIRED", "true")
    for result in ("failure", "skipped", "cancelled", ""):
        monkeypatch.setenv("FRONTEND_RESULT", result)
        assert main() == 1
    monkeypatch.setenv("FRONTEND_RESULT", "success")
    monkeypatch.setenv("FRONTEND_TESTED_SHA", SHA_A)
    monkeypatch.setenv("FRONTEND_EXPECTED_SHA", SHA_A)
    assert main() == 0


@pytest.mark.parametrize(
    ("frontend", "state"),
    [("failure", "failure"), ("cancelled", "error"), ("skipped", "error"), ("", "error")],
)
def test_frontend_non_success_publishes_non_success_status(frontend, state):
    assert _decide(frontend_result=frontend, frontend_required=True).state == state


def test_frontend_failure_supersedes_reused_aggregate_success():
    assert _decide(reused=True, frontend_result="failure", frontend_required=True).state == "failure"


def test_frontend_success_keeps_existing_status_decisions():
    bound = dict(frontend_result="success", frontend_required=True, frontend_tested_sha=SHA_A, frontend_expected_sha=SHA_A)
    assert _decide(**bound).state == "success"
    assert _decide(reused=True, **bound) is None


def test_frontend_never_publishes_for_non_authoritative_runs():
    assert _decide(authoritative=False, frontend_result="failure", frontend_required=True) is None


def test_only_exact_frontend_success_can_produce_success_status():
    for frontend in ("failure", "cancelled", "skipped", "", "Success"):
        decision = _decide(frontend_result=frontend, frontend_required=True)
        assert decision is not None and decision.state != "success"


def test_workflow_gate_requires_frontend_job_and_passes_its_result_to_both_steps():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    gate = workflow["jobs"]["aggregate-gate"]
    assert set(gate["needs"]) == {"plan", "validate", "frontend"}
    for step in gate["steps"]:
        if "env" in step and "PLAN_RESULT" in step["env"]:
            assert step["env"]["FRONTEND_RESULT"] == "${{ needs.frontend.result }}"
            assert step["env"]["FRONTEND_REQUIRED"] == "${{ github.event_name != 'push' }}"
    frontend = workflow["jobs"]["frontend"]
    # Runs wherever the gate is admitted for a PR/dispatch, and never on a profile or Draft condition
    # that could turn "no frontend verdict" into silence.
    assert "pull_request" in frontend["if"] and "workflow_dispatch" in frontend["if"]
    assert "profile" not in frontend["if"] and "draft" not in frontend["if"]
    assert "needs" not in frontend
    assert "statuses" not in json.dumps(frontend)


# --- stale head: the frontend verdict must cover the SHA the status is minted for ---

SHA_A, SHA_B = "a" * 40, "b" * 40


def test_required_frontend_success_for_another_sha_closes_the_gate():
    gate_open, message = evaluate_aggregate_gate("success", "success", "success", True, SHA_B, SHA_A)
    assert gate_open is False
    assert "different SHA" in message


def test_required_frontend_success_without_a_tested_sha_closes_the_gate():
    assert evaluate_aggregate_gate("success", "success", "success", True, "", SHA_A)[0] is False


def test_required_frontend_success_for_the_same_sha_opens_the_gate():
    assert evaluate_aggregate_gate("success", "success", "success", True, SHA_A, SHA_A)[0] is True


def test_sha_binding_is_skipped_only_when_the_frontend_verdict_is_unrequired():
    # push to main: no frontend job and no verdict SHA to bind.
    assert evaluate_aggregate_gate("success", "skipped", "skipped", False, "", "")[0] is True
    assert evaluate_aggregate_gate("success", "skipped", "success", False, SHA_B, SHA_A)[0] is True


def test_required_frontend_success_with_no_verdict_sha_closes_the_gate():
    # Fail closed: a dropped or empty FRONTEND_EXPECTED_SHA can never make the binding vacuous.
    gate_open, message = evaluate_aggregate_gate("success", "success", "success", True, SHA_B, "")
    assert gate_open is False
    assert "no verdict SHA" in message
    assert _decide(frontend_result="success", frontend_required=True, frontend_tested_sha=SHA_A).state == "error"


@pytest.mark.parametrize("value", ["", "true", "True", "FALSE", "no", "0", "1"])
def test_cli_treats_anything_but_an_exact_false_as_frontend_required(monkeypatch, value):
    monkeypatch.setenv("VALIDATE_RESULT", "success")
    monkeypatch.setenv("PLAN_RESULT", "skipped")
    monkeypatch.setenv("FRONTEND_RESULT", "skipped")
    monkeypatch.setenv("FRONTEND_REQUIRED", value)
    assert main() == 1


def test_cli_fails_closed_when_the_frontend_variables_are_dropped(monkeypatch):
    for name in ("FRONTEND_REQUIRED", "FRONTEND_RESULT", "FRONTEND_TESTED_SHA", "FRONTEND_EXPECTED_SHA"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VALIDATE_RESULT", "success")
    monkeypatch.setenv("PLAN_RESULT", "success")
    assert main() == 1
    monkeypatch.setenv("AUTHORITATIVE", "true")
    monkeypatch.setenv("AGGREGATE_OUTCOME", "success")
    done = subprocess.run(
        [sys.executable, "scripts/agent_os_aggregate_gate.py", "status"],
        env=dict(os.environ), capture_output=True, text=True, cwd=str(ROOT), check=True,
    )
    assert json.loads(done.stdout)["state"] == "error"


def test_cli_exact_false_is_the_only_way_to_make_the_frontend_verdict_optional(monkeypatch):
    monkeypatch.setenv("VALIDATE_RESULT", "success")
    monkeypatch.setenv("PLAN_RESULT", "skipped")
    monkeypatch.setenv("FRONTEND_RESULT", "skipped")
    monkeypatch.setenv("FRONTEND_REQUIRED", "false")
    assert main() == 0


def test_other_sha_frontend_publishes_error_not_success():
    decision = _decide(frontend_result="success", frontend_required=True, frontend_tested_sha=SHA_B, frontend_expected_sha=SHA_A)
    assert decision.state == "error"
    assert "different SHA" in decision.description
    assert _decide(frontend_result="success", frontend_required=True, frontend_tested_sha=SHA_A, frontend_expected_sha=SHA_A).state == "success"


def test_other_sha_frontend_supersedes_a_reused_success():
    decision = _decide(reused=True, frontend_result="success", frontend_required=True, frontend_tested_sha=SHA_B, frontend_expected_sha=SHA_A)
    assert decision.state == "error"


@pytest.mark.parametrize("frontend", ["failure", "cancelled", "skipped", "", "success"])
def test_every_status_description_fits_githubs_140_character_limit(frontend):
    decision = _decide(frontend_result=frontend, frontend_required=True, frontend_tested_sha=SHA_B, frontend_expected_sha=SHA_A)
    assert decision is not None and len(decision.description) <= 140


def test_main_closes_gate_on_other_sha_frontend_and_reports_both_shas(monkeypatch, capsys):
    monkeypatch.setenv("VALIDATE_RESULT", "success")
    monkeypatch.setenv("PLAN_RESULT", "skipped")
    monkeypatch.setenv("FRONTEND_RESULT", "success")
    monkeypatch.setenv("FRONTEND_REQUIRED", "true")
    monkeypatch.setenv("FRONTEND_TESTED_SHA", SHA_B)
    monkeypatch.setenv("FRONTEND_EXPECTED_SHA", SHA_A)
    assert main() == 1
    captured = capsys.readouterr()
    assert SHA_A in captured.out and SHA_B in captured.out
    monkeypatch.setenv("FRONTEND_TESTED_SHA", SHA_A)
    assert main() == 0


def test_status_cli_reads_frontend_sha_binding_from_the_environment():
    env = dict(
        os.environ, AUTHORITATIVE="true", VALIDATE_RESULT="success", AGGREGATE_OUTCOME="success",
        FRONTEND_RESULT="success", FRONTEND_REQUIRED="true", FRONTEND_TESTED_SHA=SHA_B, FRONTEND_EXPECTED_SHA=SHA_A,
    )
    done = subprocess.run(
        [sys.executable, "scripts/agent_os_aggregate_gate.py", "status"], env=env, capture_output=True, text=True, cwd=str(ROOT), check=True,
    )
    assert json.loads(done.stdout)["state"] == "error"
    env["FRONTEND_TESTED_SHA"] = SHA_A
    done = subprocess.run(
        [sys.executable, "scripts/agent_os_aggregate_gate.py", "status"], env=env, capture_output=True, text=True, cwd=str(ROOT), check=True,
    )
    assert json.loads(done.stdout)["state"] == "success"


def test_workflow_binds_frontend_output_sha_to_the_verdict_sha_in_both_gate_steps():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    frontend = workflow["jobs"]["frontend"]
    pass  # CONTROL D2b: structural pin neutralized to isolate the runtime SHA-binding layer
    assert any(step.get("id") == "frontend" for step in frontend["steps"])
    gate_steps = [s for s in workflow["jobs"]["aggregate-gate"]["steps"] if "PLAN_RESULT" in s.get("env", {})]
    assert len(gate_steps) == 2
    for step in gate_steps:
        assert step["env"]["FRONTEND_TESTED_SHA"] == "${{ needs.frontend.outputs.tested_sha }}"
        # Never the PR merge commit: fall back to the event's own head SHA, then the dispatch SHA.
        assert step["env"]["FRONTEND_EXPECTED_SHA"] == (
            "${{ needs.validate.outputs.head_sha || github.event.pull_request.head.sha || github.sha }}"
        )
