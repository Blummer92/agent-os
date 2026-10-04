"""Workflow-structure tests for the #3114 terminal aggregator gate.

The gate job must survive future workflow edits: it runs whenever authoritative
aggregate validation is required, while ordinary Draft PR events intentionally
defer both the aggregate and its terminal gate. Once admitted, the gate waits on
the validation jobs and enforces the authoritative aggregate disposition through
the tested ``scripts/agent_os_aggregate_gate.py`` decision module. These tests
pin that shape; the decision semantics themselves are unit-tested in
``tests/test_agent_os_aggregate_gate.py``.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"
GATE_SCRIPT = "scripts/agent_os_aggregate_gate.py"


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _gate_job() -> dict:
    jobs = _load_workflow()["jobs"]
    assert "aggregate-gate" in jobs, "aggregate-gate job is missing"
    return jobs["aggregate-gate"]


def test_aggregate_gate_job_exists_and_is_not_a_renamed_existing_job():
    jobs = _load_workflow()["jobs"]
    # Existing jobs keep their identities: a rename would desync any consumer
    # referencing them, including branch-protection contexts.
    assert "plan" in jobs
    assert "validate" in jobs
    assert "aggregate-gate" in jobs


def test_gate_runs_when_authoritative_aggregate_is_required():
    job = _gate_job()
    condition = str(job.get("if", ""))
    assert "always()" in condition
    assert "github.event_name != 'pull_request'" in condition
    assert "github.event.pull_request.draft == false" in condition


def test_gate_skips_ordinary_draft_pull_request_events():
    job = _gate_job()
    condition = str(job.get("if", ""))
    assert "github.event.pull_request.draft == false" in condition, (
        "ordinary Draft PR events intentionally defer aggregate authority and "
        "must not publish a false terminal-gate failure"
    )


def test_gate_waits_on_both_validation_jobs():
    job = _gate_job()
    needs = job.get("needs")
    needs = [needs] if isinstance(needs, str) else list(needs or [])
    assert "validate" in needs, "the gate must wait on the authoritative aggregate job"
    assert "plan" in needs, "the gate must wait on the developer-loop plan job"


def test_gate_enforces_disposition_through_the_tested_decision_module():
    job = _gate_job()
    steps = job.get("steps") or []
    enforcing = [
        step
        for step in steps
        if GATE_SCRIPT in str(step.get("run", ""))
    ]
    assert enforcing, "no step invokes the aggregate-gate decision module"
    step = enforcing[0]
    env = step.get("env") or {}
    validate_result = str(env.get("VALIDATE_RESULT", ""))
    assert "needs.validate.result" in validate_result, (
        "the gate must decide on the aggregate job's own result, "
        "not the enclosing workflow conclusion"
    )


def test_gate_is_a_plain_job_not_a_reusable_workflow_call():
    # The gate must be a first-class job in this workflow so its disposition
    # is reported as a check run on the PR; delegating to a reusable workflow
    # would change the reported check identity.
    job = _gate_job()
    assert "uses" not in job
    assert job.get("steps"), "the gate job must define its own steps"
