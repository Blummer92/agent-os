from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import workflow_scheduler.governance.dev_validation_gce as live
from workflow_scheduler.governance.dev_validation import build_dev_validation_request
from workflow_scheduler.governance.gce_control_path import VmState
from workflow_scheduler.governance.github_issue_comment_ingress import IssueCommentIngressResult

SHA = "a" * 40
BRANCH = "agent/1271-validation-profile-path-coverage"


def request():
    return build_dev_validation_request(
        repository="Blummer92/agent-os",
        issue_number=1271,
        branch=BRANCH,
        source_sha=SHA,
        validation_id="remote-validation-suite",
    )


def ingress() -> IssueCommentIngressResult:
    return IssueCommentIngressResult(
        schema_version="1.0",
        status="accepted",
        reason="accepted-dev-validation-envelope",
        repository="Blummer92/agent-os",
        issue_number=1271,
        comment_id=1,
        actor="Blummer92",
        handoff_id_or_none=None,
        logical_trigger_id_or_none="issue-comment-trigger:" + "b" * 64,
        run_attempt=1,
        dev_validation_branch_or_none=BRANCH,
        dev_validation_sha_or_none=SHA,
        dev_validation_id_or_none="remote-validation-suite",
    )


def claims(**overrides):
    values = {
        "repository": "Blummer92/agent-os",
        "repository_owner": "Blummer92",
        "workflow_ref": live._policy().workflow_ref,
        "ref": "refs/heads/main",
        "aud": live._policy().audience,
    }
    values.update(overrides)
    return values


def payload(req, *, status="success", exit_code=0):
    return {
        "schema_version": "1.0",
        "status": status,
        "reason_codes": ["validation-passed" if status == "success" else "validation-failed"],
        "repository": req.repository,
        "issue_number": req.issue_number,
        "branch": req.branch,
        "tested_sha": req.source_sha,
        "validation_id": req.validation_id,
        "request_id": req.request_id,
        "exit_code": exit_code,
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
    def __init__(self, *, state=VmState.RUNNING, result=None):
        self.state = state
        self.result = result
        self.calls = []

    def observe_state(self, resource):
        self.calls.append("observe")
        return self.state

    def _ssh(self, resource, command):
        self.calls.append(("ssh", command))
        req = request()
        body = payload(req) if self.result is None else self.result
        stdout = live._FRAME_START + "\n" + json.dumps(body) + "\n" + live._FRAME_END + "\n"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def test_host_command_contains_only_fixed_runner_and_validated_identity() -> None:
    command = live._host_command(request())
    assert "tests/agent_os_remote_validation" in command
    assert "remote-validation-suite" in command
    assert BRANCH in command
    assert SHA in command
    assert "shell=True" not in command
    assert "sudo" not in command
    assert "pip install" not in command


def test_successful_transport_uses_one_ssh_and_remains_non_authorizing() -> None:
    adapter = Adapter()
    result = live.execute_dev_validation_transport(ingress(), claims=claims(), adapter=adapter)
    assert adapter.calls[0] == "observe"
    assert adapter.calls[1][0] == "ssh"
    evidence = result["dev_validation"]
    assert evidence["status"] == "success"
    assert evidence["tested_sha"] == SHA
    assert evidence["cleanup_complete"] is True
    assert evidence["scheduler_invoked"] is False
    assert evidence["execution_authorized"] is False
    assert evidence["publication_invoked"] is False
    assert evidence["merge_authorized"] is False


def test_wrong_claims_fail_before_ssh() -> None:
    adapter = Adapter()
    result = live.execute_dev_validation_transport(
        ingress(), claims=claims(repository="other/repo"), adapter=adapter
    )
    assert adapter.calls == []
    assert result["dev_validation"]["reason_codes"] == ["claims-rejected"]


def test_stopped_host_does_not_start_for_dev_validation() -> None:
    adapter = Adapter(state=VmState.STOPPED)
    result = live.execute_dev_validation_transport(ingress(), claims=claims(), adapter=adapter)
    assert adapter.calls == ["observe"]
    assert result["dev_validation"]["reason_codes"] == ["host-not-running"]


def test_identity_mismatch_in_host_evidence_fails_closed() -> None:
    req = request()
    bad = payload(req)
    bad["tested_sha"] = "b" * 40
    adapter = Adapter(result=bad)
    result = live.execute_dev_validation_transport(ingress(), claims=claims(), adapter=adapter)
    assert result["dev_validation"]["status"] == "needs-decision"
    assert result["dev_validation"]["reason_codes"] == ["dev-validation-evidence-identity-mismatch"]


def test_unframed_ssh_output_is_not_trusted() -> None:
    class BadAdapter(Adapter):
        def _ssh(self, resource, command):
            self.calls.append(("ssh", command))
            return SimpleNamespace(returncode=0, stdout='{"status":"success"}', stderr="")

    result = live.execute_dev_validation_transport(ingress(), claims=claims(), adapter=BadAdapter())
    assert result["dev_validation"]["reason_codes"] == ["dev-validation-frame-invalid"]


def test_log_over_bound_is_rejected() -> None:
    req = request()
    bad = payload(req)
    bad["stdout_tail"] = "x" * (live.MAX_RESULT_LOG_CHARS + 1)
    result = live.execute_dev_validation_transport(ingress(), claims=claims(), adapter=Adapter(result=bad))
    assert result["dev_validation"]["reason_codes"] == ["dev-validation-log-bound-invalid"]


def test_host_runner_source_has_fixed_validation_and_no_privileged_mutation() -> None:
    source = live._HOST_RUNNER_SOURCE
    assert 'TEST_ARGS=("-m","pytest","tests/agent_os_remote_validation")' in source
    assert "shell=True" not in source
    assert "sudo" not in source
    assert "pip install" not in source
    assert "git push" not in source
    assert "gh " not in source
    assert "shutil.rmtree(root)" in source
    assert "remote_head.stdout.strip()!=sha" in source
