"""Pin the CKR7 receipt-barrier workflow binding (#3418 H1).

The refinement step must read the cited receipt/result comments through the
trusted read-only GitHub path. That read is bound to the job's already-present
repo-scoped ``github.token`` - the same token the postback step already uses -
with NO change to the job's permissions block and no new credential or scope.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "agent-os-ckr6.yml"
STEP_NAME = "Execute read-only Lessons Learned CKR6 request"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _execute_job(workflow: dict) -> dict:
    return workflow["jobs"]["execute"]


def _step(job: dict) -> dict:
    matches = [s for s in job["steps"] if s.get("name") == STEP_NAME]
    assert len(matches) == 1, "exactly one read-only CKR6 execute step"
    return matches[0]


def test_refinement_step_binds_the_existing_github_token():
    step = _step(_execute_job(_workflow()))
    token = re.sub(r"\s", "", str(step.get("env", {}).get("GITHUB_TOKEN", "")))
    assert token == "${{github.token}}"


def test_binding_adds_no_permission_or_credential_scope():
    job = _execute_job(_workflow())
    # Unchanged from the postback contract: read-only contents plus the two
    # comment-write scopes the result postback already requires.
    assert job["permissions"] == {
        "contents": "read",
        "issues": "write",
        "pull-requests": "write",
    }
    step = _step(job)
    # The barrier consumes github.token only; no App credential, PAT secret,
    # or new secret surface may be bound to this step.
    assert set(step["env"]) == {
        "AGENT_OS_EVENT",
        "AGENT_OS_REPOSITORY",
        "NOTION_TOKEN",
        "AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID",
        "GITHUB_TOKEN",
    }


def test_zero_read_step_does_not_get_the_token():
    job = _execute_job(_workflow())
    zero_read = [s for s in job["steps"] if s.get("name") == "Execute zero-read CKR6 request"]
    assert len(zero_read) == 1
    assert "GITHUB_TOKEN" not in zero_read[0].get("env", {})
