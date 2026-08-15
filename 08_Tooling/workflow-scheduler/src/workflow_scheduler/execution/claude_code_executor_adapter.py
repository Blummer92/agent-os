"""Pure Claude Code invocation binding and bounded result normalization for #722.

This module does not launch a provider, inspect credentials, access the network,
create a worktree, run validation, retry execution, or mutate GitHub. It binds
already-supplied provider evidence and an existing provider-neutral Implementation
Packet to a deterministic non-shell argv tuple for the canonical runtime.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Mapping

CLAUDE_CODE_ADAPTER_SCHEMA_VERSION = "1.0"
MINIMUM_CLAUDE_CODE_VERSION = (2, 1, 233)
MAX_PROMPT_BYTES = 32_768
MAX_JSON_OUTPUT_BYTES = 65_536
MAX_RESULT_TEXT_BYTES = 16_384
MAX_TURNS = 32
ALLOWED_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep")
DISALLOWED_TOOLS = ("Bash", "WebFetch", "WebSearch", "mcp__*")

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECRET_MARKERS = (
    "sk-ant-",
    "ghp_",
    "github_pat_",
    "AKIA",
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
)


class ClaudeCodeAdapterError(ValueError):
    """Raised when provider evidence or packet material fails closed."""


class ClaudeCodeTerminalStatus(str, Enum):
    SUCCEEDED = "succeeded"
    PROVIDER_ERROR = "provider-error"
    NONZERO_EXIT = "nonzero-exit"
    TIMED_OUT = "timed-out"
    MALFORMED_OUTPUT = "malformed-output"
    OUTPUT_REJECTED = "output-rejected"


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ClaudeCodeAdapterError(
            "implementation packet must be canonical-JSON serializable"
        ) from exc


def _sha256(prefix: bytes, payload: bytes) -> str:
    return hashlib.sha256(prefix + payload).hexdigest()


def _bounded_text(value: object, name: str, *, maximum: int) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise ClaudeCodeAdapterError(f"{name} must be non-empty NUL-free text")
    if len(value.encode("utf-8")) > maximum:
        raise ClaudeCodeAdapterError(f"{name} exceeds the bounded byte length")
    return value


def _absolute_path(value: object, name: str) -> str:
    text = _bounded_text(value, name, maximum=4096)
    normalized = os.path.abspath(os.path.normpath(text))
    if text != normalized or not os.path.isabs(text):
        raise ClaudeCodeAdapterError(f"{name} must be a normalized absolute path")
    return text


def _version_tuple(version: object) -> tuple[int, int, int]:
    text = _bounded_text(version, "observed_version", maximum=64)
    match = _VERSION_RE.fullmatch(text)
    if match is None:
        raise ClaudeCodeAdapterError("observed_version must use exact x.y.z syntax")
    parsed = tuple(int(part) for part in match.groups())
    if parsed < MINIMUM_CLAUDE_CODE_VERSION:
        raise ClaudeCodeAdapterError(
            "observed Claude Code version is below the frozen minimum"
        )
    return parsed  # type: ignore[return-value]


def _fingerprint(value: object, name: str) -> str:
    text = _bounded_text(value, name, maximum=128)
    if _SHA256_RE.fullmatch(text) is None:
        raise ClaudeCodeAdapterError(
            f"{name} must be a lowercase SHA-256 hex digest"
        )
    return text


def _packet_prompt(
    packet: Mapping[str, object],
    *,
    packet_source_fingerprint: str,
    source_identity_fingerprint: str,
) -> str:
    if not isinstance(packet, Mapping) or not packet:
        raise ClaudeCodeAdapterError(
            "implementation_packet must be a non-empty mapping"
        )
    packet_json = _canonical_json(dict(packet))
    prompt = (
        "Agent OS bounded implementation task.\n"
        "Treat the following provider-neutral Implementation Packet as the complete task context.\n"
        "Edit only paths permitted by the packet. Do not run shell commands, tests, Git, package installs, "
        "network tools, GitHub operations, workflow operations, or external-system writes. Agent OS performs "
        "validation and publication independently after provider exit.\n"
        f"packet_source_fingerprint={packet_source_fingerprint}\n"
        f"source_identity_fingerprint={source_identity_fingerprint}\n"
        f"implementation_packet={packet_json}"
    )
    return _bounded_text(prompt, "provider_prompt", maximum=MAX_PROMPT_BYTES)


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaudeCodeInvocation:
    schema_version: str
    executable_path: str
    observed_version: str
    working_directory: str
    packet_source_fingerprint: str
    source_identity_fingerprint: str
    max_turns: int
    argv: tuple[str, ...]
    invocation_id: str
    provider_execution_authorized: Literal[False] = field(default=False, init=False)
    validation_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    automatic_retry: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaudeCodeResultEvidence:
    schema_version: str
    invocation_id: str
    terminal_status: ClaudeCodeTerminalStatus
    exit_code: int | None
    timed_out: bool
    response_sha256: str | None
    response_bytes: int
    provider_reported_error: bool | None
    execution_succeeded: bool
    validation_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    automatic_retry: Literal[False] = field(default=False, init=False)
    side_effects_performed: bool


def build_claude_code_invocation(
    *,
    implementation_packet: Mapping[str, object],
    packet_source_fingerprint: str,
    source_identity_fingerprint: str,
    executable_path: str,
    observed_version: str,
    authenticated: bool,
    working_directory: str,
    max_turns: int = 16,
) -> ClaudeCodeInvocation:
    """Bind one offline, non-authorizing Claude Code invocation description."""

    executable = _absolute_path(executable_path, "executable_path")
    if os.path.basename(executable) != "claude":
        raise ClaudeCodeAdapterError(
            "executable_path must identify the claude executable"
        )
    _version_tuple(observed_version)
    if authenticated is not True:
        raise ClaudeCodeAdapterError(
            "Claude Code authentication evidence must be true"
        )
    cwd = _absolute_path(working_directory, "working_directory")
    packet_fp = _fingerprint(
        packet_source_fingerprint, "packet_source_fingerprint"
    )
    source_fp = _fingerprint(
        source_identity_fingerprint, "source_identity_fingerprint"
    )
    if type(max_turns) is not int or not 1 <= max_turns <= MAX_TURNS:
        raise ClaudeCodeAdapterError("max_turns is outside the bounded policy")

    prompt = _packet_prompt(
        implementation_packet,
        packet_source_fingerprint=packet_fp,
        source_identity_fingerprint=source_fp,
    )
    argv = (
        executable,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
        "--max-turns",
        str(max_turns),
        "--no-session-persistence",
        "--no-chrome",
        "--disable-slash-commands",
        "--tools",
        ",".join(ALLOWED_TOOLS),
        "--disallowedTools",
        ",".join(DISALLOWED_TOOLS),
    )
    identity_payload = {
        "schema_version": CLAUDE_CODE_ADAPTER_SCHEMA_VERSION,
        "executable_path": executable,
        "observed_version": observed_version,
        "working_directory": cwd,
        "packet_source_fingerprint": packet_fp,
        "source_identity_fingerprint": source_fp,
        "max_turns": max_turns,
        "argv": argv,
    }
    digest = _sha256(
        b"agent-os-claude-code-invocation:v1\0",
        _canonical_json(identity_payload).encode("utf-8"),
    )
    return ClaudeCodeInvocation(
        schema_version=CLAUDE_CODE_ADAPTER_SCHEMA_VERSION,
        executable_path=executable,
        observed_version=observed_version,
        working_directory=cwd,
        packet_source_fingerprint=packet_fp,
        source_identity_fingerprint=source_fp,
        max_turns=max_turns,
        argv=argv,
        invocation_id=f"claude-code-invocation:{digest}",
    )


def _contains_secret_marker(text: str) -> bool:
    return any(marker in text for marker in _SECRET_MARKERS)


def normalize_claude_code_result(
    *,
    invocation_id: str,
    exit_code: int | None,
    stdout: bytes,
    stderr: bytes,
    timed_out: bool,
) -> ClaudeCodeResultEvidence:
    """Normalize one already-executed provider result without retaining prose."""

    invocation = _bounded_text(invocation_id, "invocation_id", maximum=256)
    if not invocation.startswith("claude-code-invocation:"):
        raise ClaudeCodeAdapterError(
            "invocation_id is not a Claude Code invocation identity"
        )
    if type(stdout) is not bytes or type(stderr) is not bytes:
        raise ClaudeCodeAdapterError("stdout and stderr must be exact bytes")
    if len(stdout) > MAX_JSON_OUTPUT_BYTES or len(stderr) > MAX_JSON_OUTPUT_BYTES:
        return ClaudeCodeResultEvidence(
            schema_version=CLAUDE_CODE_ADAPTER_SCHEMA_VERSION,
            invocation_id=invocation,
            terminal_status=ClaudeCodeTerminalStatus.OUTPUT_REJECTED,
            exit_code=exit_code,
            timed_out=timed_out,
            response_sha256=None,
            response_bytes=len(stdout),
            provider_reported_error=None,
            execution_succeeded=False,
            side_effects_performed=True,
        )
    if timed_out:
        return ClaudeCodeResultEvidence(
            schema_version=CLAUDE_CODE_ADAPTER_SCHEMA_VERSION,
            invocation_id=invocation,
            terminal_status=ClaudeCodeTerminalStatus.TIMED_OUT,
            exit_code=exit_code,
            timed_out=True,
            response_sha256=None,
            response_bytes=len(stdout),
            provider_reported_error=None,
            execution_succeeded=False,
            side_effects_performed=True,
        )

    combined = stdout.decode("utf-8", errors="replace") + stderr.decode(
        "utf-8", errors="replace"
    )
    if _contains_secret_marker(combined):
        return ClaudeCodeResultEvidence(
            schema_version=CLAUDE_CODE_ADAPTER_SCHEMA_VERSION,
            invocation_id=invocation,
            terminal_status=ClaudeCodeTerminalStatus.OUTPUT_REJECTED,
            exit_code=exit_code,
            timed_out=False,
            response_sha256=None,
            response_bytes=len(stdout),
            provider_reported_error=None,
            execution_succeeded=False,
            side_effects_performed=True,
        )
    if exit_code != 0:
        return ClaudeCodeResultEvidence(
            schema_version=CLAUDE_CODE_ADAPTER_SCHEMA_VERSION,
            invocation_id=invocation,
            terminal_status=ClaudeCodeTerminalStatus.NONZERO_EXIT,
            exit_code=exit_code,
            timed_out=False,
            response_sha256=None,
            response_bytes=len(stdout),
            provider_reported_error=None,
            execution_succeeded=False,
            side_effects_performed=True,
        )
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        status = ClaudeCodeTerminalStatus.MALFORMED_OUTPUT
        provider_error = None
        digest = None
    else:
        if type(payload) is not dict:
            status = ClaudeCodeTerminalStatus.MALFORMED_OUTPUT
            provider_error = None
            digest = None
        else:
            result = payload.get("result")
            provider_error = payload.get("is_error")
            if type(result) is not str or type(provider_error) is not bool:
                status = ClaudeCodeTerminalStatus.MALFORMED_OUTPUT
                digest = None
            elif (
                len(result.encode("utf-8")) > MAX_RESULT_TEXT_BYTES
                or _contains_secret_marker(result)
            ):
                status = ClaudeCodeTerminalStatus.OUTPUT_REJECTED
                digest = None
            else:
                digest = _sha256(
                    b"agent-os-claude-code-result:v1\0",
                    result.encode("utf-8"),
                )
                status = (
                    ClaudeCodeTerminalStatus.PROVIDER_ERROR
                    if provider_error
                    else ClaudeCodeTerminalStatus.SUCCEEDED
                )

    return ClaudeCodeResultEvidence(
        schema_version=CLAUDE_CODE_ADAPTER_SCHEMA_VERSION,
        invocation_id=invocation,
        terminal_status=status,
        exit_code=exit_code,
        timed_out=False,
        response_sha256=digest,
        response_bytes=len(stdout),
        provider_reported_error=provider_error,
        execution_succeeded=status is ClaudeCodeTerminalStatus.SUCCEEDED,
        side_effects_performed=True,
    )
