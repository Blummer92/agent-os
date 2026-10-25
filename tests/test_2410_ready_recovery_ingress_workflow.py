"""Contract regressions for the #2410 ingress Ready-recovery workflow wiring.

These tests assert the production connection, not only test fixtures: the
governed ingress job, the validation workflow inputs and admission branch,
and the independent receipt verification call. They do not grant workflow,
merge, or lifecycle authority.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GOVERNED = ROOT / ".github/workflows/agent-os-governed-invocation.yml"
VALIDATION = ROOT / ".github/workflows/agent-os-validation.yml"


def governed_data() -> dict:
    return yaml.safe_load(GOVERNED.read_text(encoding="utf-8"))


def validation_data() -> dict:
    return yaml.safe_load(VALIDATION.read_text(encoding="utf-8"))


def governed_text() -> str:
    return GOVERNED.read_text(encoding="utf-8")


def validation_text() -> str:
    return VALIDATION.read_text(encoding="utf-8")


def test_ready_recovery_job_is_confined_to_one_actions_write_job() -> None:
    jobs = governed_data()["jobs"]
    job = jobs["ready_recovery_dispatch"]
    assert job["permissions"] == {
        "actions": "write",
        "contents": "read",
        "pull-requests": "read",
    }
    condition = job["if"]
    assert "github.ref == 'refs/heads/main'" in condition
    assert "32861845" in condition and "199175422" in condition
    assert "/agent-os recover-ready " in condition
    assert "github.event.issue.pull_request == null" in condition
    step_text = "\n".join(str(step) for step in job["steps"])
    assert "github_issue_comment_ingress" in step_text
    assert "--ready-recovery-service-actor" in step_text
    assert "ready_recovery_dispatch" in step_text
    assert "agent-os-ready-recovery-" in step_text
    assert "issues" not in job["permissions"]


def test_generic_ingress_job_excludes_recover_ready() -> None:
    jobs = governed_data()["jobs"]
    assert "/agent-os recover-ready" in jobs["ingress"]["if"]


def test_validation_inputs_are_optional_ingress_correlation_only() -> None:
    inputs = validation_data()[True]["workflow_dispatch"]["inputs"]
    assert inputs["ingress_run_id"]["required"] is False
    assert inputs["ingress_trigger_id"]["required"] is False


def test_validation_candidate_step_carries_ingress_env_and_verification() -> None:
    validate = validation_data()["jobs"]["validate"]
    assert validate["permissions"]["actions"] == "read"
    steps = validate["steps"]
    candidate = next(step for step in steps if step["name"] == "Admit exact-head Draft final candidate")
    env = candidate["env"]
    assert env["INGRESS_RUN_ID"] == "${{ inputs.ingress_run_id }}"
    assert env["INGRESS_TRIGGER_ID"] == "${{ inputs.ingress_trigger_id }}"
    body = candidate["run"]
    # Direct owner rule is preserved, not replaced.
    assert "Ready recovery requires repository-owner dispatch" in body
    # Ingress branch requires the token identity plus verified evidence.
    assert "Ingress recovery requires the governed ingress token identity" in body
    # #3732 race repair: the ingress block waits for the identified run
    # and artifact via one wait-and-verify call instead of a single fetch.
    assert "agent_os_ready_recovery_ingress.py wait-and-verify" in body
    assert "--governed-workflow-id" in body
    assert "--validation-run-id" in body
    # The receipt-artifact naming now lives in the wait module: the CLI
    # derives the prefix from the ingress run id it is passed.
    assert "--ingress-run-id" in body
    script = (ROOT / "scripts/agent_os_ready_recovery_ingress.py").read_text()
    assert 'f"agent-os-ready-recovery-{ingress_run_id}-"' in script
    # The old single-fetch gate is gone (its failure was the race).
    assert "Ingress recovery requires exactly one ready-recovery receipt artifact" not in body
    assert "Ingress receipt artifact is missing receipt or transport evidence" not in body
    # QA F1: the ingress fork check moved into wait_and_verify_ingress
    # (after verification, same position); it is covered behaviorally by
    # the wait suite, not by a shell string, without changing direct
    # owner dispatch.
    assert "Ingress recovery rejects fork pull requests" not in body


def test_ingress_verification_checkout_is_scoped_to_ingress_dispatches() -> None:
    steps = validation_data()["jobs"]["validate"]["steps"]
    checkout = next(
        step for step in steps if step["name"] == "Check out workflow source for ingress verification"
    )
    assert "inputs.ingress_run_id" in checkout["if"]
    assert checkout["with"]["persist-credentials"] is False


def test_ready_recovery_run_name_format_is_unchanged() -> None:
    data = validation_data()
    assert "agent-os-ready-recovery:" in data["run-name"]
