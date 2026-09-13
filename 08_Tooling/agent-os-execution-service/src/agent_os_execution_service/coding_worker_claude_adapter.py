"""Thin Claude Code adapter for the provider-neutral coding-worker contract (#2319).

This module composes the canonical #2318 ``CodingWorkerRequest`` / ``CodingWorkerResult``
with the already-governed #722 Claude Code CLI adapter. It does not launch Claude Code,
inspect credentials, select a runtime, authorize execution, run validation, retry work,
or mutate GitHub. Provider execution remains an external runtime concern.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

from workflow_scheduler.execution.claude_code_executor_adapter import (
    ClaudeCodeAdapterError,
    ClaudeCodeInvocation,
    ClaudeCodeTerminalStatus,
    build_claude_code_invocation,
    normalize_claude_code_result,
)

from .coding_worker_contract import (
    CODING_WORKER_SCHEMA_VERSION,
    CodingWorkerOperation,
    CodingWorkerRequest,
    CodingWorkerResult,
    CodingWorkerStatus,
)

CLAUDE_CODING_WORKER_ADAPTER_SCHEMA_VERSION = "1.0"
_PROVIDER_NAME = "claude-code"
_UNSUPPORTED_OPERATIONS = {CodingWorkerOperation.TEST}


class ClaudeCodingWorkerAdapterError(ValueError):
    """Raised when request/provider evidence cannot be translated safely."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaudeCodingWorkerInvocation:
    """Binding between one canonical worker request and one native Claude invocation."""

    schema_version: str
    request_id: str
    provider: str
    native_invocation: ClaudeCodeInvocation


def _diagnostic_id(invocation_id: str, terminal_status: ClaudeCodeTerminalStatus) -> str:
    material = f"{invocation_id}\0{terminal_status.value}".encode("utf-8")
    return f"claude-code-diagnostic:{hashlib.sha256(material).hexdigest()}"


def _provider_payload(
    request: CodingWorkerRequest,
    implementation_packet: Mapping[str, object],
) -> dict[str, object]:
    if type(request) is not CodingWorkerRequest:
        raise ClaudeCodingWorkerAdapterError("request must be an exact CodingWorkerRequest")
    if request.operation in _UNSUPPORTED_OPERATIONS:
        raise ClaudeCodingWorkerAdapterError(
            "Claude Code adapter cannot satisfy the test operation because #722 disables Bash; "
            "capability routing must select another surface"
        )
    if not isinstance(implementation_packet, Mapping) or not implementation_packet:
        raise ClaudeCodingWorkerAdapterError("implementation_packet must be a non-empty mapping")

    return {
        "implementation_packet": dict(implementation_packet),
        "coding_worker_request": request.to_dict(),
        "provider_response_contract": {
            "format": "CodingWorkerResult JSON encoded as the Claude JSON result string",
            "schema_version": CODING_WORKER_SCHEMA_VERSION,
            "request_id": request.request_id,
            "task_id": request.task_id,
            "repository": request.repository,
            "base_sha": request.base_sha,
            "workspace_identity": request.workspace_identity,
            "commands_run_must_be_empty": True,
            "tests_run_must_be_empty": True,
            "authority_fields_must_be_false": True,
            "scope_rule": (
                "files_changed and files_inspected must stay inside allowed_paths and outside "
                "forbidden_paths; report scope-violation with explicit paths if this is not true"
            ),
        },
    }


def build_claude_coding_worker_invocation(
    *,
    request: CodingWorkerRequest,
    implementation_packet: Mapping[str, object],
    packet_source_fingerprint: str,
    source_identity_fingerprint: str,
    executable_path: str,
    observed_version: str,
    authenticated: bool,
    working_directory: str,
    max_turns: int = 16,
) -> ClaudeCodingWorkerInvocation:
    """Translate one canonical coding-worker request to the existing Claude CLI adapter."""

    payload = _provider_payload(request, implementation_packet)
    try:
        native = build_claude_code_invocation(
            implementation_packet=payload,
            packet_source_fingerprint=packet_source_fingerprint,
            source_identity_fingerprint=source_identity_fingerprint,
            executable_path=executable_path,
            observed_version=observed_version,
            authenticated=authenticated,
            working_directory=working_directory,
            max_turns=max_turns,
        )
    except ClaudeCodeAdapterError as exc:
        raise ClaudeCodingWorkerAdapterError(str(exc)) from exc

    return ClaudeCodingWorkerInvocation(
        schema_version=CLAUDE_CODING_WORKER_ADAPTER_SCHEMA_VERSION,
        request_id=request.request_id,
        provider=_PROVIDER_NAME,
        native_invocation=native,
    )


def _path_within(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _scope_violations(request: CodingWorkerRequest, paths: tuple[str, ...]) -> tuple[str, ...]:
    violations: list[str] = []
    for path in paths:
        allowed = any(_path_within(path, root) for root in request.allowed_paths)
        forbidden = any(_path_within(path, root) or _path_within(root, path) for root in request.forbidden_paths)
        if not allowed or forbidden:
            violations.append(path)
    return tuple(dict.fromkeys(violations))


def _failure_result(
    *,
    request: CodingWorkerRequest,
    invocation_id: str,
    terminal_status: ClaudeCodeTerminalStatus,
) -> CodingWorkerResult:
    return CodingWorkerResult(
        schema_version=CODING_WORKER_SCHEMA_VERSION,
        request_id=request.request_id,
        task_id=request.task_id,
        repository=request.repository,
        base_sha=request.base_sha,
        workspace_identity=request.workspace_identity,
        status=CodingWorkerStatus.EXECUTION_FAILURE,
        summary=f"Claude Code execution did not produce canonical worker evidence: {terminal_status.value}",
        files_inspected=(),
        files_changed=(),
        commands_run=(),
        tests_run=(),
        test_result_ids=(),
        diagnostic_ids=(_diagnostic_id(invocation_id, terminal_status),),
        assumption_ids=(),
        unresolved_question_ids=(),
        scope_violation_paths=(),
        blocked_reason_or_none=None,
        patch_identity_or_none=None,
        result_sha_or_none=None,
    )


def _extract_provider_result(stdout: bytes) -> CodingWorkerResult:
    try:
        envelope = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClaudeCodingWorkerAdapterError("Claude Code stdout is not valid JSON") from exc
    if type(envelope) is not dict or type(envelope.get("result")) is not str:
        raise ClaudeCodingWorkerAdapterError("Claude Code output is missing the result string")
    try:
        payload = json.loads(envelope["result"])
    except json.JSONDecodeError as exc:
        raise ClaudeCodingWorkerAdapterError(
            "Claude Code result string is not canonical CodingWorkerResult JSON"
        ) from exc
    try:
        return CodingWorkerResult.from_dict(payload)
    except (TypeError, ValueError) as exc:
        raise ClaudeCodingWorkerAdapterError(
            "Claude Code result does not satisfy CodingWorkerResult"
        ) from exc


def normalize_claude_coding_worker_result(
    *,
    request: CodingWorkerRequest,
    invocation_id: str,
    exit_code: int | None,
    stdout: bytes,
    stderr: bytes,
    timed_out: bool,
) -> CodingWorkerResult:
    """Translate native Claude terminal evidence back into canonical worker evidence."""

    if type(request) is not CodingWorkerRequest:
        raise ClaudeCodingWorkerAdapterError("request must be an exact CodingWorkerRequest")

    try:
        native = normalize_claude_code_result(
            invocation_id=invocation_id,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
        )
    except ClaudeCodeAdapterError as exc:
        raise ClaudeCodingWorkerAdapterError(str(exc)) from exc

    if native.terminal_status is not ClaudeCodeTerminalStatus.SUCCEEDED:
        return _failure_result(
            request=request,
            invocation_id=invocation_id,
            terminal_status=native.terminal_status,
        )

    result = _extract_provider_result(stdout)
    bindings = (
        ("request_id", result.request_id, request.request_id),
        ("task_id", result.task_id, request.task_id),
        ("repository", result.repository, request.repository),
        ("base_sha", result.base_sha, request.base_sha),
        ("workspace_identity", result.workspace_identity, request.workspace_identity),
    )
    for name, actual, expected in bindings:
        if actual != expected:
            raise ClaudeCodingWorkerAdapterError(f"provider result {name} does not match request")

    if result.commands_run or result.tests_run:
        raise ClaudeCodingWorkerAdapterError(
            "provider claimed command/test execution although the bounded Claude adapter disables Bash"
        )

    violations = _scope_violations(
        request,
        tuple(dict.fromkeys(result.files_inspected + result.files_changed)),
    )
    if violations:
        return CodingWorkerResult(
            schema_version=CODING_WORKER_SCHEMA_VERSION,
            request_id=request.request_id,
            task_id=request.task_id,
            repository=request.repository,
            base_sha=request.base_sha,
            workspace_identity=request.workspace_identity,
            status=CodingWorkerStatus.SCOPE_VIOLATION,
            summary="Claude Code reported repository paths outside the authorized worker scope",
            files_inspected=result.files_inspected,
            files_changed=result.files_changed,
            commands_run=(),
            tests_run=(),
            test_result_ids=(),
            diagnostic_ids=result.diagnostic_ids,
            assumption_ids=result.assumption_ids,
            unresolved_question_ids=result.unresolved_question_ids,
            scope_violation_paths=violations,
            blocked_reason_or_none=None,
            patch_identity_or_none=result.patch_identity_or_none,
            result_sha_or_none=result.result_sha_or_none,
        )

    return result


__all__ = [
    "CLAUDE_CODING_WORKER_ADAPTER_SCHEMA_VERSION",
    "ClaudeCodingWorkerAdapterError",
    "ClaudeCodingWorkerInvocation",
    "build_claude_coding_worker_invocation",
    "normalize_claude_coding_worker_result",
]
