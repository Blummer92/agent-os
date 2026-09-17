from __future__ import annotations

import json

import pytest

from agent_os_execution_service.coding_worker_claude_adapter import (
    ClaudeCodingWorkerAdapterError,
    build_claude_coding_worker_invocation,
    normalize_claude_coding_worker_result,
)
from agent_os_execution_service.coding_worker_contract import (
    CODING_WORKER_SCHEMA_VERSION,
    CodingWorkerOperation,
    CodingWorkerRequest,
    CodingWorkerResult,
    CodingWorkerStatus,
)

BASE_SHA = "a" * 40
REQUEST_IDENTITY = "packet:source:2319"
INVOCATION_ID = "claude-code-invocation:" + "b" * 64


def _request(*, operation: CodingWorkerOperation = CodingWorkerOperation.IMPLEMENT) -> CodingWorkerRequest:
    return CodingWorkerRequest(
        schema_version=CODING_WORKER_SCHEMA_VERSION,
        task_id="issue-2319",
        repository="Blummer92/agent-os",
        issue_or_handoff_identity="issue:2319",
        base_sha=BASE_SHA,
        workspace_identity="workspace:issue-2319",
        operation=operation,
        implementation_packet_source_identity=REQUEST_IDENTITY,
        executor_handoff_id="executor-handoff:2319",
        allowed_paths=("08_Tooling/agent-os-execution-service",),
        forbidden_paths=(".github", "00_Governance"),
    )


def _result(
    request: CodingWorkerRequest,
    *,
    status: CodingWorkerStatus = CodingWorkerStatus.COMPLETED,
    files_inspected: tuple[str, ...] = (
        "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/coding_worker_contract.py",
    ),
    files_changed: tuple[str, ...] = (
        "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/example.py",
    ),
    commands_run: tuple[str, ...] = (),
    tests_run: tuple[str, ...] = (),
) -> CodingWorkerResult:
    return CodingWorkerResult(
        schema_version=CODING_WORKER_SCHEMA_VERSION,
        request_id=request.request_id,
        task_id=request.task_id,
        repository=request.repository,
        base_sha=request.base_sha,
        workspace_identity=request.workspace_identity,
        status=status,
        summary="bounded provider result",
        files_inspected=files_inspected,
        files_changed=files_changed,
        commands_run=commands_run,
        tests_run=tests_run,
        test_result_ids=(),
        diagnostic_ids=(),
        assumption_ids=(),
        unresolved_question_ids=(),
        scope_violation_paths=(),
        blocked_reason_or_none=None,
        patch_identity_or_none="patch:2319",
        result_sha_or_none="c" * 40,
    )


def _stdout(result: CodingWorkerResult, *, is_error: bool = False) -> bytes:
    return json.dumps(
        {"result": json.dumps(result.to_dict(), sort_keys=True), "is_error": is_error}
    ).encode("utf-8")


def test_build_translates_canonical_request_into_existing_claude_invocation() -> None:
    request = _request()
    invocation = build_claude_coding_worker_invocation(
        request=request,
        implementation_packet={"objective": "add one bounded adapter"},
        packet_source_fingerprint="1" * 64,
        source_identity_fingerprint="2" * 64,
        executable_path="/usr/local/bin/claude",
        observed_version="2.1.233",
        authenticated=True,
        working_directory="/workspace/agent-os",
        max_turns=8,
    )

    assert invocation.request_id == request.request_id
    assert invocation.provider == "claude-code"
    assert invocation.native_invocation.argv[0] == "/usr/local/bin/claude"
    assert invocation.native_invocation.argv[1] == "-p"
    prompt = invocation.native_invocation.argv[2]
    assert request.request_id in prompt
    assert '"operation":"implement"' in prompt
    assert '"authority_fields_must_be_false":true' in prompt
    assert invocation.native_invocation.provider_execution_authorized is False


def test_test_operation_fails_closed_because_existing_claude_adapter_disables_bash() -> None:
    with pytest.raises(ClaudeCodingWorkerAdapterError, match="cannot satisfy the test operation"):
        build_claude_coding_worker_invocation(
            request=_request(operation=CodingWorkerOperation.TEST),
            implementation_packet={"objective": "run tests"},
            packet_source_fingerprint="1" * 64,
            source_identity_fingerprint="2" * 64,
            executable_path="/usr/local/bin/claude",
            observed_version="2.1.233",
            authenticated=True,
            working_directory="/workspace/agent-os",
        )


def test_successful_provider_result_reconstructs_canonical_worker_result() -> None:
    request = _request()
    expected = _result(request)

    result = normalize_claude_coding_worker_result(
        request=request,
        invocation_id=INVOCATION_ID,
        exit_code=0,
        stdout=_stdout(expected),
        stderr=b"",
        timed_out=False,
    )

    assert result == expected
    assert result.execution_authorized is False
    assert result.validation_authorized is False
    assert result.merge_authorized is False


def test_nonzero_provider_exit_maps_to_execution_failure_without_provider_prose() -> None:
    request = _request()

    result = normalize_claude_coding_worker_result(
        request=request,
        invocation_id=INVOCATION_ID,
        exit_code=2,
        stdout=b"",
        stderr=b"provider failed",
        timed_out=False,
    )

    assert result.status is CodingWorkerStatus.EXECUTION_FAILURE
    assert result.files_changed == ()
    assert result.commands_run == ()
    assert len(result.diagnostic_ids) == 1
    assert "nonzero-exit" in result.summary


def test_provider_binding_mismatch_is_rejected() -> None:
    request = _request()
    payload = _result(request).to_dict()
    payload["repository"] = "other/repo"
    payload["result_id"] = ""
    forged = CodingWorkerResult.from_dict(payload)

    with pytest.raises(ClaudeCodingWorkerAdapterError, match="repository does not match"):
        normalize_claude_coding_worker_result(
            request=request,
            invocation_id=INVOCATION_ID,
            exit_code=0,
            stdout=_stdout(forged),
            stderr=b"",
            timed_out=False,
        )


def test_out_of_scope_provider_paths_are_preserved_as_scope_violation() -> None:
    request = _request()
    provider_result = _result(
        request,
        files_inspected=("08_Tooling/agent-os-execution-service/README.md",),
        files_changed=("00_Governance/write-authorization-policy.md",),
    )

    result = normalize_claude_coding_worker_result(
        request=request,
        invocation_id=INVOCATION_ID,
        exit_code=0,
        stdout=_stdout(provider_result),
        stderr=b"",
        timed_out=False,
    )

    assert result.status is CodingWorkerStatus.SCOPE_VIOLATION
    assert result.scope_violation_paths == ("00_Governance/write-authorization-policy.md",)
    assert result.files_changed == provider_result.files_changed
    assert result.merge_authorized is False


def test_provider_cannot_claim_shell_commands_or_tests_on_bounded_claude_route() -> None:
    request = _request()
    provider_result = _result(
        request,
        commands_run=("pytest -q",),
        tests_run=("pytest -q",),
    )

    with pytest.raises(ClaudeCodingWorkerAdapterError, match="disables Bash"):
        normalize_claude_coding_worker_result(
            request=request,
            invocation_id=INVOCATION_ID,
            exit_code=0,
            stdout=_stdout(provider_result),
            stderr=b"",
            timed_out=False,
        )


def test_malformed_semantic_result_fails_closed_after_native_success() -> None:
    request = _request()
    stdout = json.dumps({"result": "not-json", "is_error": False}).encode("utf-8")

    with pytest.raises(ClaudeCodingWorkerAdapterError, match="not canonical CodingWorkerResult JSON"):
        normalize_claude_coding_worker_result(
            request=request,
            invocation_id=INVOCATION_ID,
            exit_code=0,
            stdout=stdout,
            stderr=b"",
            timed_out=False,
        )
