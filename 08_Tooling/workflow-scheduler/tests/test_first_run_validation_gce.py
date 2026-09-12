"""#1972 regressions for the fixed first-run validation transport.

These cover the transport boundary only: candidate-identity survival across
transport reconstruction, routing to exactly the fixed first-run host operation,
fail-closed behavior on bad identity/claims/reruns/host evidence, and proof that
no arbitrary argv, Scheduler, publication, or shutdown path is reachable.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import workflow_scheduler.governance.first_run_validation_gce as live
from workflow_scheduler.governance.gce_control_path import VmState
from workflow_scheduler.governance.gce_gcloud_adapter import (
    FIRST_RUN_VALIDATION_MODULE,
    GcloudCommandError,
    GcloudIapAdapter,
    RESOURCE,
    WIF_PROVIDER,
    WORKFLOW_REF,
    _first_run_validation_command,
    _ingress_from_file,
    execute_transport,
)
from workflow_scheduler.governance.github_issue_comment_ingress import (
    admit_issue_comment_event,
)

REPOSITORY = "Blummer92/agent-os"
ACTOR = "Blummer92"
ISSUE = 1972
SHA = "b" * 40
CLAIMS = {
    "repository": REPOSITORY,
    "repository_owner": "Blummer92",
    "workflow_ref": WORKFLOW_REF,
    "ref": "refs/heads/main",
    "aud": WIF_PROVIDER,
}


def _event(body: str, *, issue_number: int = ISSUE) -> dict:
    return {
        "action": "created",
        "repository": {"full_name": REPOSITORY},
        "issue": {"number": issue_number},
        "comment": {"id": 4242, "user": {"login": ACTOR}, "body": body},
        "sender": {"login": ACTOR},
    }


def _ingress(body: str = f"/agent-os validate-first-run {SHA}", *, run_attempt: int = 1):
    return admit_issue_comment_event(
        _event(body),
        expected_repository=REPOSITORY,
        allowed_actor=ACTOR,
        run_attempt=run_attempt,
    )


def _host_evidence(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "repository": REPOSITORY,
        "issue_number": ISSUE,
        "candidate_sha": SHA,
        "validation_id": "remote-validation-suite",
        "profile_id": "remote-validation",
        "dev_validation_request_id": "dev-validation:" + "c" * 64,
        "validation_plan_id": "pre-pr-validation-plan:" + "d" * 64,
        "validation_bundle_id": "validation-evidence-bundle:" + "e" * 64,
        "pull_request": None,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "execution_lease_acquired": False,
        "resume_invoked": False,
        "retry_attempted": False,
        "merge_authorized": False,
    }
    payload.update(overrides)
    return payload


class Adapter:
    """Records every adapter touch so forbidden paths are provable, not assumed."""

    FORBIDDEN = (
        "invoke",
        "start",
        "stop",
        "wait_until_running",
        "activate_first_publication",
        "probe_activation_ready",
        "discover",
    )

    def __init__(self, *, state=VmState.RUNNING, ready=True, evidence=None, ssh_result=None):
        self.state = state
        self.ready = ready
        self.evidence = evidence if evidence is not None else _host_evidence()
        self.ssh_result = ssh_result
        self.calls: list[str] = []
        self.commands: list[str] = []

    def observe_state(self, resource):
        assert resource == RESOURCE
        self.calls.append("observe_state")
        return self.state

    def probe_first_run_validation_ready(self, resource):
        self.calls.append("probe_first_run_validation_ready")
        return self.ready

    def _ssh(self, resource, command):
        self.calls.append("_ssh")
        self.commands.append(command)
        if self.ssh_result is not None:
            return self.ssh_result
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(self.evidence, sort_keys=True, separators=(",", ":")),
            stderr="",
        )

    def validate_first_run(self, resource, *, repository, issue_number, candidate_sha):
        self.calls.append("validate_first_run")
        return GcloudIapAdapter.validate_first_run(
            self,
            resource,
            repository=repository,
            issue_number=issue_number,
            candidate_sha=candidate_sha,
        )

    def __getattr__(self, name):
        if name in self.FORBIDDEN:
            def forbidden(*args, **kwargs):
                raise AssertionError(f"forbidden adapter path reached: {name}")

            return forbidden
        raise AttributeError(name)


def test_first_run_candidate_identity_survives_transport_reconstruction(tmp_path: Path) -> None:
    ingress = _ingress()
    assert ingress.first_run_candidate_sha_or_none == SHA

    path = tmp_path / "transport.json"
    path.write_text(json.dumps(ingress.to_dict()), encoding="utf-8")
    rebuilt = _ingress_from_file(path)

    assert rebuilt.first_run_candidate_sha_or_none == SHA
    assert rebuilt.reason == "accepted-first-run-validation-envelope"
    assert rebuilt.logical_trigger_id_or_none == ingress.logical_trigger_id_or_none


def test_valid_first_run_ingress_reaches_only_the_fixed_first_run_path() -> None:
    adapter = Adapter()

    response = execute_transport(_ingress(), claims=CLAIMS, adapter=adapter)

    assert set(response) == {"first_run_validation", "logical_trigger_id"}
    assert response["first_run_validation"]["candidate_sha"] == SHA
    assert "binding" not in response and "control" not in response
    assert adapter.calls == [
        "observe_state",
        "probe_first_run_validation_ready",
        "validate_first_run",
        "_ssh",
    ]
    assert len(adapter.commands) == 1
    assert adapter.commands[0] == (
        f"/usr/bin/python3 -m {FIRST_RUN_VALIDATION_MODULE} "
        f"--repository {REPOSITORY} --issue-number {ISSUE} --candidate-sha {SHA}"
    )


def test_no_scheduler_publication_or_shutdown_path_is_reached() -> None:
    adapter = Adapter()

    response = execute_transport(_ingress(), claims=CLAIMS, adapter=adapter)
    evidence = response["first_run_validation"]

    assert evidence["scheduler_invoked"] is False
    assert evidence["publication_invoked"] is False
    assert evidence["execution_lease_acquired"] is False
    assert evidence["resume_invoked"] is False
    assert evidence["execution_authorized"] is False
    assert evidence["retry_attempted"] is False
    for forbidden in Adapter.FORBIDDEN:
        assert forbidden not in adapter.calls


@pytest.mark.parametrize(
    "body",
    [
        "/agent-os validate-first-run",
        "/agent-os validate-first-run " + "b" * 39,
        "/agent-os validate-first-run " + "b" * 41,
        "/agent-os validate-first-run " + "B" * 40,
        "/agent-os validate-first-run " + "z" * 40,
        f"/agent-os validate-first-run {SHA} --extra",
    ],
)
def test_malformed_candidate_sha_never_becomes_a_first_run_envelope(body: str) -> None:
    ingress = _ingress(body)

    assert ingress.reason != "accepted-first-run-validation-envelope"
    assert ingress.first_run_candidate_sha_or_none is None


def test_missing_candidate_sha_on_accepted_envelope_fails_closed() -> None:
    from dataclasses import replace

    adapter = Adapter()
    stripped = replace(_ingress(), first_run_candidate_sha_or_none=None)

    response = live.execute_first_run_validation_transport(
        stripped, claims=CLAIMS, adapter=adapter
    )

    assert response["first_run_validation"]["status"] == "blocked"
    assert response["first_run_validation"]["reason_codes"] == [
        "first-run-candidate-sha-invalid"
    ]
    assert adapter.calls == []


def test_mismatched_repository_never_reaches_the_host() -> None:
    event = _event(f"/agent-os validate-first-run {SHA}")
    event["repository"]["full_name"] = "someone-else/agent-os"
    ingress = admit_issue_comment_event(
        event, expected_repository=REPOSITORY, allowed_actor=ACTOR, run_attempt=1
    )

    assert ingress.status == "blocked"
    assert ingress.reason == "repository-mismatch"
    assert ingress.first_run_candidate_sha_or_none is None


def test_wrong_claims_fail_before_host_execution() -> None:
    adapter = Adapter()
    claims = dict(CLAIMS, workflow_ref="Blummer92/agent-os/.github/workflows/other.yml@refs/heads/main")

    response = live.execute_first_run_validation_transport(
        _ingress(), claims=claims, adapter=adapter
    )

    assert response["first_run_validation"]["status"] == "blocked"
    assert response["first_run_validation"]["reason_codes"] == ["claims-rejected"]
    assert adapter.calls == []


def test_workflow_rerun_fails_before_host_execution() -> None:
    rerun = _ingress(run_attempt=2)

    assert rerun.status == "blocked"
    assert rerun.reason == "workflow-rerun"
    with pytest.raises(ValueError, match="accepted canonical ingress evidence"):
        live.execute_first_run_validation_transport(
            rerun, claims=CLAIMS, adapter=Adapter()
        )


def test_host_not_running_or_entrypoint_missing_fails_closed() -> None:
    stopped = Adapter(state=VmState.STOPPED)
    response = live.execute_first_run_validation_transport(
        _ingress(), claims=CLAIMS, adapter=stopped
    )
    assert response["first_run_validation"]["reason_codes"] == ["host-not-running"]
    assert "validate_first_run" not in stopped.calls

    unready = Adapter(ready=False)
    response = live.execute_first_run_validation_transport(
        _ingress(), claims=CLAIMS, adapter=unready
    )
    assert response["first_run_validation"]["reason_codes"] == [
        "first-run-validation-entrypoint-unavailable"
    ]
    assert "validate_first_run" not in unready.calls


@pytest.mark.parametrize(
    "overrides",
    [
        {"candidate_sha": "a" * 40},
        {"issue_number": 1971},
        {"repository": "someone-else/agent-os"},
        {"scheduler_invoked": True},
        {"publication_invoked": True},
        {"execution_lease_acquired": True},
        {"resume_invoked": True},
    ],
)
def test_host_evidence_must_stay_candidate_and_boundary_bound(overrides: dict) -> None:
    adapter = Adapter(evidence=_host_evidence(**overrides))

    response = live.execute_first_run_validation_transport(
        _ingress(), claims=CLAIMS, adapter=adapter
    )

    assert response["first_run_validation"]["reason_codes"] == [
        "first-run-validation-host-failed"
    ]


@pytest.mark.parametrize(
    "ssh_result",
    [
        SimpleNamespace(returncode=1, stdout="", stderr="boom"),
        SimpleNamespace(returncode=0, stdout="not json", stderr=""),
        SimpleNamespace(returncode=0, stdout="[]", stderr=""),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
    ],
)
def test_malformed_host_evidence_fails_closed(ssh_result) -> None:
    adapter = Adapter(ssh_result=ssh_result)

    response = live.execute_first_run_validation_transport(
        _ingress(), claims=CLAIMS, adapter=adapter
    )

    assert response["first_run_validation"]["status"] == "needs-decision"
    assert response["first_run_validation"]["reason_codes"] == [
        "first-run-validation-host-failed"
    ]


def test_pr_less_host_evidence_carries_no_fabricated_pull_request() -> None:
    adapter = Adapter()

    evidence = live.execute_first_run_validation_transport(
        _ingress(), claims=CLAIMS, adapter=adapter
    )["first_run_validation"]

    assert "pull_request" in evidence
    assert evidence["pull_request"] is None


def test_no_arbitrary_argv_path_exists() -> None:
    with pytest.raises(GcloudCommandError):
        _first_run_validation_command(
            repository=REPOSITORY, issue_number=ISSUE, candidate_sha="; rm -rf /"
        )
    with pytest.raises(GcloudCommandError):
        _first_run_validation_command(
            repository="attacker/repo", issue_number=ISSUE, candidate_sha=SHA
        )
    with pytest.raises(GcloudCommandError):
        _first_run_validation_command(
            repository=REPOSITORY, issue_number=0, candidate_sha=SHA
        )

    source = inspect.getsource(live)
    assert "shell=True" not in source
    assert "--command" not in source
    signature = inspect.signature(GcloudIapAdapter.validate_first_run)
    assert set(signature.parameters) == {
        "self",
        "resource",
        "repository",
        "issue_number",
        "candidate_sha",
    }


def test_ordinary_dev_validation_behaviour_is_unchanged(tmp_path: Path) -> None:
    """The added first-run branch must not disturb the existing dev-validate lane."""
    branch = "agent/1972-first-run-host-composition"
    body = f"/agent-os dev-validate {branch} {SHA} remote-validation-suite"
    ingress = _ingress(body)

    assert ingress.reason == "accepted-dev-validation-envelope"
    assert ingress.dev_validation_branch_or_none == branch
    assert ingress.dev_validation_sha_or_none == SHA
    assert ingress.dev_validation_id_or_none == "remote-validation-suite"
    assert ingress.first_run_candidate_sha_or_none is None

    path = tmp_path / "transport.json"
    path.write_text(json.dumps(ingress.to_dict()), encoding="utf-8")
    rebuilt = _ingress_from_file(path)
    assert rebuilt.dev_validation_branch_or_none == branch
    assert rebuilt.dev_validation_sha_or_none == SHA
    assert rebuilt.dev_validation_id_or_none == "remote-validation-suite"
    assert rebuilt.first_run_candidate_sha_or_none is None

    seen: list[str] = []

    class DevAdapter(Adapter):
        def observe_state(self, resource):
            seen.append("observe_state")
            return VmState.RUNNING

        def _ssh(self, resource, command):
            seen.append("_ssh")
            raise AssertionError("dev-validation must not reach the first-run host command")

    with pytest.raises(AssertionError, match="must not reach the first-run host command"):
        execute_transport(rebuilt, claims=CLAIMS, adapter=DevAdapter())
    assert seen == ["observe_state", "_ssh"]


def test_other_accepted_operations_are_not_routed_to_first_run() -> None:
    for body in ("/agent-os discover", "/agent-os inspect-runtime"):
        ingress = _ingress(body)
        with pytest.raises(ValueError, match="accepted canonical ingress evidence"):
            live.execute_first_run_validation_transport(
                ingress, claims=CLAIMS, adapter=Adapter()
            )
