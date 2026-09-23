from __future__ import annotations

import json
from types import SimpleNamespace

from workflow_scheduler.governance.dev_validation import build_dev_validation_request
import workflow_scheduler.governance.first_run_dev_validation_gce as live
from workflow_scheduler.governance.first_run_validation_observation import FIXED_GCE_RUNNER_ID

SHA = "a" * 40
BRANCH = "agent/1972-first-run-host-composition"


def request():
    return build_dev_validation_request(
        repository="Blummer92/agent-os",
        issue_number=1972,
        branch=BRANCH,
        source_sha=SHA,
        validation_id="remote-validation-suite",
    )


def payload(req):
    return {
        "schema_version": "1.0",
        "status": "success",
        "reason_codes": ["validation-passed"],
        "repository": req.repository,
        "issue_number": req.issue_number,
        "branch": req.branch,
        "tested_sha": req.source_sha,
        "validation_id": req.validation_id,
        "request_id": req.request_id,
        "runner_id": FIXED_GCE_RUNNER_ID,
        "started_at": "2026-09-12T14:00:00.000001Z",
        "completed_at": "2026-09-12T14:00:01.000001Z",
        "exit_code": 0,
        "stdout_tail": "ok",
        "stderr_tail": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "cleanup_complete": True,
        "workspace_side_effects_performed": True,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }


class Adapter:
    def __init__(self, value):
        self.value = value
        self.commands = []

    def _ssh(self, resource, command):
        self.commands.append(command)
        body = json.dumps(self.value, sort_keys=True, separators=(",", ":"))
        return SimpleNamespace(
            returncode=0,
            stdout=live._OBSERVED_FRAME_START + "\n" + body + "\n" + live._OBSERVED_FRAME_END + "\n",
            stderr="",
        )


def test_wrapper_executes_only_existing_fixed_runner_command():
    req = request()
    command = live._observed_host_command(req)
    assert live._HOST_OBSERVER_SOURCE in command
    assert "tests/agent_os_remote_validation" in command
    assert BRANCH in command
    assert SHA in command
    assert "--command" not in command
    assert "pip install" not in live._HOST_OBSERVER_SOURCE
    assert "shell=True" not in live._HOST_OBSERVER_SOURCE


def test_observed_wrapper_requires_fixed_identity_and_timing():
    req = request()
    adapter = Adapter(payload(req))
    result = live.run_observed_dev_validation_over_ssh(adapter, req)
    assert result["runner_id"] == FIXED_GCE_RUNNER_ID
    assert result["started_at"].endswith("Z")
    assert result["completed_at"].endswith("Z")
    assert result["execution_authorized"] is False
    assert result["scheduler_invoked"] is False
    assert result["publication_invoked"] is False
    assert len(adapter.commands) == 1


def test_missing_timing_fails_closed():
    req = request()
    value = payload(req)
    value.pop("started_at")
    result = live.run_observed_dev_validation_over_ssh(Adapter(value), req)
    assert result["reason_codes"] == ["first-run-dev-validation-timing-missing"]


def test_caller_cannot_override_runner_identity():
    req = request()
    value = payload(req)
    value["runner_id"] = "caller-selected"
    result = live.run_observed_dev_validation_over_ssh(Adapter(value), req)
    assert result["reason_codes"] == ["first-run-dev-validation-evidence-identity-mismatch"]
