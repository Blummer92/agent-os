"""Workflow wiring contract for the fixed Ready-for-Review admission job (#3446)."""
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).parents[1] / ".github/workflows/agent-os-governed-invocation.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_ingress_job_skips_ready_admission_trigger():
    condition = _workflow()["jobs"]["ingress"]["if"]
    assert "!startsWith(github.event.comment.body, '/agent-os ready-admit')" in condition
    assert "github.event.issue.pull_request == null" in condition


def test_ready_admission_job_is_read_only_and_owner_scoped():
    job = _workflow()["jobs"]["ready_admission"]
    assert job["permissions"] == {
        "contents": "read", "pull-requests": "read", "checks": "read", "statuses": "read"}
    condition = job["if"]
    assert "github.event.issue.pull_request == null" in condition
    assert "github.event.comment.user.id == 32861845" in condition
    assert "startsWith(github.event.comment.body, '/agent-os ready-admit ')" in condition


def test_ready_admission_job_has_no_write_steps_or_generic_execution():
    text = yaml.safe_dump(_workflow()["jobs"]["ready_admission"])
    for forbidden in ("gh pr", "gh api", "mark_pull_request_ready", "gcloud", "secrets.", "id-token",
                      "--command", "eval ", "bash -c"):
        assert forbidden not in text
    assert "scripts.agent_os_issue_labels.ready_admission_actions" in text
    assert "workflow_scheduler.governance.github_issue_comment_ingress" in text


def test_existing_jobs_unchanged_in_shape():
    assert list(_workflow()["jobs"]) == ["ingress", "refresh_pr", "ready_admission"]
