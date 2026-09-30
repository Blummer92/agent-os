"""Fixed GCE PPUX prompt-projection transport coverage (#2673).

The projection trigger carries an exact branch/SHA/input-ref; the host runs
only the fixed promptProjectionEntrypoint; the structured recorder validates
the picture-perfect-prompt-projection-result-v1 payload. Violations fail
closed with finite reasons; the canonical result is never truncated.
"""
from __future__ import annotations

import json
import shlex
import subprocess
from copy import deepcopy

import pytest

from workflow_scheduler.governance.gce_control_path import VmState
from workflow_scheduler.governance.github_issue_comment_ingress import IssueCommentIngressResult
from workflow_scheduler.governance.ppux_projection_gce import (
    HOST_PYTHON,
    MAX_DIAGNOSTIC_CHARS,
    MAX_PROJECTION_CARDS,
    PPUX_PROJECTION_ENTRYPOINT_MODULE,
    PPUX_PROJECTION_OPERATION_ID,
    PpuxProjectionRecorderError,
    _ingress_from_file,
    build_ppux_projection_request,
    execute_ppux_projection_transport,
    ppux_projection_host_command,
    record_ppux_projection_result,
    run_ppux_projection_over_ssh,
)

REPOSITORY = "Blummer92/agent-os"
BRANCH = "agent/2673-ppux-projection-transport"
SHA = "a" * 40
INPUT_REF = "b" * 64
REQUEST_ID = "ppux-projection-abcdef123456"


def make_request(**overrides):
    kwargs = {
        "repository": REPOSITORY,
        "issue_number": 2673,
        "branch": BRANCH,
        "source_sha": SHA,
        "input_ref": INPUT_REF,
        "request_id": REQUEST_ID,
    }
    kwargs.update(overrides)
    return build_ppux_projection_request(**kwargs)


def make_host_payload(**overrides):
    request = make_request()
    payload = {
        "schema_version": "1.0",
        "operation_id": PPUX_PROJECTION_OPERATION_ID,
        "status": "success",
        "reason_codes": ["projection-result-ready"],
        "repository": request.repository,
        "issue_number": request.issue_number,
        "branch": request.branch,
        "tested_sha": request.source_sha,
        "input_ref": request.input_ref,
        "request_id": request.request_id,
        "projection_result": {
            "formatVersion": "picture-perfect-prompt-projection-result-v1",
            "status": "valid",
            "package": {
                "packageVersion": "picture-perfect-tutorial-package-v1",
                "routeId": "route-1",
                "cards": [{"cardId": "card-1"}, {"cardId": "card-2"}],
                "executionAuthorized": False,
                "externalWriteAuthorized": False,
                "productionAuthorized": False,
            },
            "blockers": [],
        },
        "projection_result_sha256": "c" * 64,
        "diagnostics": {"invoke_stdout_tail": "ok"},
        "cleanup_complete": True,
        "workspace_side_effects_performed": False,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }
    payload.update(overrides)
    return request, payload


def make_ingress(**overrides):
    kwargs = {
        "schema_version": "1.0",
        "status": "accepted",
        "reason": "accepted-ppux-projection-envelope",
        "repository": REPOSITORY,
        "issue_number": 2673,
        "comment_id": 4001,
        "actor": "Blummer92",
        "handoff_id_or_none": None,
        "logical_trigger_id_or_none": "issue-comment-trigger:" + "d" * 64,
        "run_attempt": 1,
        "dev_validation_branch_or_none": None,
        "dev_validation_sha_or_none": None,
        "dev_validation_id_or_none": None,
        "ppux_projection_branch_or_none": BRANCH,
        "ppux_projection_sha_or_none": SHA,
        "ppux_projection_input_ref_or_none": INPUT_REF,
        "source_capsule_id_or_none": None,
        "first_run_candidate_sha_or_none": None,
        "notion_read_request_id_or_none": None,
        "diagnostic_id_or_none": None,
        "diagnostic_request_id_or_none": None,
        "ruleset_prestate_sha256_or_none": None,
    }
    kwargs.update(overrides)
    return IssueCommentIngressResult(**kwargs)


# --- request validation ----------------------------------------------------

def test_request_validation_accepts_exact_identities() -> None:
    request = make_request()
    assert request.operation_id == PPUX_PROJECTION_OPERATION_ID


@pytest.mark.parametrize(
    "kwargs",
    [
        {"repository": "other/repo"},
        {"issue_number": 0},
        {"issue_number": True},
        {"branch": "main"},
        {"branch": "agent/main"},
        {"branch": "agent/"},
        {"branch": "agent/x/../y"},
        {"branch": "agent/x//y"},
        {"source_sha": "a" * 39},
        {"source_sha": "A" * 40},
        {"input_ref": "b" * 63},
        {"input_ref": "B" * 64},
        {"request_id": "wrong-prefix"},
        {"request_id": "ppux-projection-"},
    ],
)
def test_request_validation_rejects_deviations(kwargs) -> None:
    with pytest.raises(ValueError, match="Invalid PPUX projection request"):
        make_request(**kwargs)


# --- fixed host command ----------------------------------------------------

def test_host_command_is_fixed_argv_with_only_validated_identities() -> None:
    request = make_request()
    command = ppux_projection_host_command(request)

    argv = shlex.split(command)
    assert argv[:3] == [HOST_PYTHON, "-m", PPUX_PROJECTION_ENTRYPOINT_MODULE]
    assert "--branch" in argv and argv[argv.index("--branch") + 1] == BRANCH
    assert "--source-sha" in argv and argv[argv.index("--source-sha") + 1] == SHA
    assert "--input-ref" in argv and argv[argv.index("--input-ref") + 1] == INPUT_REF
    assert "--operation-id" in argv
    assert argv[argv.index("--operation-id") + 1] == PPUX_PROJECTION_OPERATION_ID
    # No caller-controlled module, script, or shell fragment can ride along.
    assert "vite" not in command
    assert "node" not in command.replace(PPUX_PROJECTION_ENTRYPOINT_MODULE, "")
    assert ";" not in command and "&&" not in command


# --- structured recorder ---------------------------------------------------

def test_recorder_preserves_canonical_result_verbatim() -> None:
    request, payload = make_host_payload()
    before = deepcopy(payload["projection_result"])

    recorded = record_ppux_projection_result(payload, request)

    assert recorded["projection_result"] == before
    assert recorded["status"] == "success"
    assert recorded["reason_codes"] == ["projection-result-ready"]
    for authority in (
        "execution_authorized",
        "scheduler_invoked",
        "publication_invoked",
        "merge_authorized",
        "workspace_side_effects_performed",
        "external_side_effects_performed",
        "production_state_mutated",
    ):
        assert recorded[authority] is False


def test_recorder_preserves_blocked_host_payload() -> None:
    request, payload = make_host_payload(
        status="blocked",
        reason_codes=["projection-input-unresolved"],
        projection_result=None,
        projection_result_sha256=None,
    )

    recorded = record_ppux_projection_result(payload, request)

    assert recorded["status"] == "blocked"
    assert recorded["reason_codes"] == ["projection-input-unresolved"]
    assert recorded["projection_result"] is None


def test_recorder_rejects_identity_mismatch() -> None:
    request, payload = make_host_payload(tested_sha="f" * 40)

    with pytest.raises(PpuxProjectionRecorderError) as exc:
        record_ppux_projection_result(payload, request)
    assert exc.value.reason == "projection-evidence-identity-mismatch"


def test_recorder_rejects_wrong_result_version() -> None:
    request, payload = make_host_payload()
    payload["projection_result"]["formatVersion"] = "picture-perfect-prompt-projection-result-v0"

    with pytest.raises(PpuxProjectionRecorderError) as exc:
        record_ppux_projection_result(payload, request)
    assert exc.value.reason == "projection-result-invalid"


def test_recorder_rejects_oversize_canonical_payload() -> None:
    request, payload = make_host_payload()
    payload["projection_result"]["package"]["cards"] = [
        {"cardId": f"card-{index}", "filler": "x" * 4096}
        for index in range(MAX_PROJECTION_CARDS - 1)
    ]

    with pytest.raises(PpuxProjectionRecorderError) as exc:
        record_ppux_projection_result(payload, request)
    assert exc.value.reason == "projection-output-oversize"


def test_recorder_rejects_too_many_cards() -> None:
    request, payload = make_host_payload()
    payload["projection_result"]["package"]["cards"] = [
        {"cardId": f"card-{index}"} for index in range(MAX_PROJECTION_CARDS + 1)
    ]

    with pytest.raises(PpuxProjectionRecorderError) as exc:
        record_ppux_projection_result(payload, request)
    assert exc.value.reason == "projection-output-oversize"


def test_recorder_rejects_authority_violation() -> None:
    request, payload = make_host_payload()
    payload["projection_result"]["package"]["executionAuthorized"] = True

    with pytest.raises(PpuxProjectionRecorderError) as exc:
        record_ppux_projection_result(payload, request)
    assert exc.value.reason == "projection-authority-violation"


def test_recorder_keeps_diagnostics_separate_from_canonical_result() -> None:
    request, payload = make_host_payload()
    payload["projection_result"]["diagnostics"] = {"invoke_stdout_tail": "ok"}

    with pytest.raises(PpuxProjectionRecorderError) as exc:
        record_ppux_projection_result(payload, request)
    assert exc.value.reason == "projection-diagnostic-invalid"


def test_recorder_rejects_oversize_diagnostic() -> None:
    request, payload = make_host_payload()
    payload["diagnostics"] = {"invoke_stdout_tail": "x" * (MAX_DIAGNOSTIC_CHARS + 1)}

    with pytest.raises(PpuxProjectionRecorderError) as exc:
        record_ppux_projection_result(payload, request)
    assert exc.value.reason == "projection-diagnostic-oversize"


def test_recorder_rejects_authorized_envelope() -> None:
    request, payload = make_host_payload(execution_authorized=True)

    with pytest.raises(PpuxProjectionRecorderError) as exc:
        record_ppux_projection_result(payload, request)
    assert exc.value.reason == "projection-authority-violation"


# --- transport entry point ---------------------------------------------------

REJECTED_CLAIMS = {"repository": "other/repo"}


class FakeAdapter:
    """Minimal adapter double: VM already running, host emits one framed payload."""

    def __init__(self, *, payload: dict, exit_code: int = 0):
        self.payload = payload
        self.exit_code = exit_code
        self.ssh_commands: list[str] = []

    def observe_state(self, resource):
        return VmState.RUNNING

    def _ssh(self, resource, command: str, *, timeout: int = 180):
        self.ssh_commands.append(command)
        framed = (
            "PPUX-PROJECTION-FRAME-START\n"
            + json.dumps(self.payload)
            + "\nPPUX-PROJECTION-FRAME-END\n"
        )
        return subprocess.CompletedProcess(
            args=command, returncode=self.exit_code, stdout=framed, stderr=""
        )


ACCEPTED_CLAIMS = {
    "repository": REPOSITORY,
    "repository_owner": "Blummer92",
    "workflow_ref": "Blummer92/agent-os/.github/workflows/agent-os-governed-invocation.yml@refs/heads/main",
    "ref": "refs/heads/main",
    "aud": "//iam.googleapis.com/projects/966859826758/locations/global/workloadIdentityPools/agent-os-github/providers/agent-os-main",
}


def test_transport_rejects_wrong_selector_identity() -> None:
    with pytest.raises(ValueError, match="accepted canonical ingress"):
        execute_ppux_projection_transport(
            make_ingress(reason="accepted-dev-validation-envelope"),
            claims=ACCEPTED_CLAIMS,
            adapter=FakeAdapter(payload={}),
        )


def test_transport_rejects_incomplete_identity() -> None:
    with pytest.raises(ValueError, match="identity incomplete"):
        execute_ppux_projection_transport(
            make_ingress(ppux_projection_input_ref_or_none=None),
            claims=ACCEPTED_CLAIMS,
            adapter=FakeAdapter(payload={}),
        )


def test_transport_blocks_on_rejected_claims_without_touching_ssh() -> None:
    adapter = FakeAdapter(payload={})

    evidence = execute_ppux_projection_transport(
        make_ingress(), claims=REJECTED_CLAIMS, adapter=adapter
    )

    assert evidence["ppux_projection"]["status"] == "needs-decision"
    assert evidence["ppux_projection"]["reason_codes"] == ["claims-rejected"]
    assert adapter.ssh_commands == []
    assert evidence["ppux_projection"]["execution_authorized"] is False


def test_transport_records_framed_host_payload() -> None:
    request = make_request()
    _, payload = make_host_payload(
        repository=request.repository,
        issue_number=request.issue_number,
        branch=request.branch,
        tested_sha=request.source_sha,
        input_ref=request.input_ref,
    )
    # request_id is derived from the ingress inside the transport; the host
    # payload must echo it back.
    adapter = FakeAdapter(payload={})

    evidence = execute_ppux_projection_transport(
        make_ingress(), claims=ACCEPTED_CLAIMS, adapter=adapter
    )
    derived_request_id = evidence["ppux_projection"].get("request_id")
    payload["request_id"] = derived_request_id
    adapter.payload = payload

    evidence = execute_ppux_projection_transport(
        make_ingress(), claims=ACCEPTED_CLAIMS, adapter=adapter
    )

    recorded = evidence["ppux_projection"]
    assert recorded["status"] == "success"
    assert recorded["projection_result"]["package"]["cards"][0]["cardId"] == "card-1"
    assert recorded["vm_initial_state"] == VmState.RUNNING.value
    assert recorded["start_issued"] is False
    # The fixed host command is what ran on the VM.
    assert len(adapter.ssh_commands) == 2
    assert PPUX_PROJECTION_ENTRYPOINT_MODULE in adapter.ssh_commands[1]


def test_transport_converts_recorder_violation_to_failure_envelope() -> None:
    request = make_request()
    _, payload = make_host_payload()
    payload["tested_sha"] = "f" * 40  # identity mismatch
    adapter = FakeAdapter(payload={})

    evidence = execute_ppux_projection_transport(
        make_ingress(), claims=ACCEPTED_CLAIMS, adapter=adapter
    )
    derived_request_id = evidence["ppux_projection"].get("request_id")
    payload["request_id"] = derived_request_id
    adapter.payload = payload

    evidence = execute_ppux_projection_transport(
        make_ingress(), claims=ACCEPTED_CLAIMS, adapter=adapter
    )

    assert evidence["ppux_projection"]["status"] == "needs-decision"
    assert evidence["ppux_projection"]["reason_codes"] == [
        "projection-evidence-identity-mismatch"
    ]


def test_transport_rejects_non_running_vm() -> None:
    class StoppedAdapter(FakeAdapter):
        def observe_state(self, resource):
            return VmState.STOPPED

        def start(self, resource):
            return False

    evidence = execute_ppux_projection_transport(
        make_ingress(), claims=ACCEPTED_CLAIMS, adapter=StoppedAdapter(payload={})
    )

    assert evidence["ppux_projection"]["status"] == "needs-decision"
    assert evidence["ppux_projection"]["reason_codes"] == ["vm-start-failed"]


# --- dispatch + reconstruction ---------------------------------------------

def test_execute_transport_routes_projection_envelope() -> None:
    from workflow_scheduler.governance.gce_gcloud_adapter import execute_transport

    adapter = FakeAdapter(payload={})
    evidence = execute_transport(
        make_ingress(), claims=REJECTED_CLAIMS, adapter=adapter
    )

    assert "ppux_projection" in evidence
    assert evidence["ppux_projection"]["reason_codes"] == ["claims-rejected"]


def test_ingress_from_file_preserves_projection_selector_identity(tmp_path) -> None:
    from workflow_scheduler.governance.github_issue_comment_ingress import (
        admit_issue_comment_event,
    )

    result = admit_issue_comment_event(
        {
            "action": "created",
            "repository": {"full_name": REPOSITORY},
            "issue": {"number": 2673},
            "comment": {
                "id": 4001,
                "body": f"/agent-os project-ppux-prompts {BRANCH} {SHA} {INPUT_REF}",
                "user": {"login": "Blummer92"},
            },
            "sender": {"login": "Blummer92"},
        },
        expected_repository=REPOSITORY,
        allowed_actor="Blummer92",
        run_attempt=1,
    )
    path = tmp_path / "ingress.json"
    path.write_text(json.dumps(result.to_dict()), encoding="utf-8")

    reconstructed = _ingress_from_file(path)

    assert reconstructed.reason == "accepted-ppux-projection-envelope"
    assert reconstructed.ppux_projection_branch_or_none == BRANCH
    assert reconstructed.ppux_projection_sha_or_none == SHA
    assert reconstructed.ppux_projection_input_ref_or_none == INPUT_REF
