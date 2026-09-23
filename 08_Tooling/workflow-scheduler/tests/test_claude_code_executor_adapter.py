import json
from pathlib import Path

import pytest

from workflow_scheduler.execution.claude_code_executor_adapter import (
    ALLOWED_TOOLS,
    DISALLOWED_TOOLS,
    ClaudeCodeAdapterError,
    ClaudeCodeTerminalStatus,
    build_claude_code_invocation,
    normalize_claude_code_result,
)

FP1 = "a" * 64
FP2 = "b" * 64
PACKET = {
    "objective": "Change one bounded adapter",
    "allowed_inspect_first": ["x.py"],
    "forbidden_unless_needed": [".github/workflows/**"],
    "validation_commands": ["pytest -q tests/test_x.py"],
}


def make(**overrides):
    args = dict(
        implementation_packet=PACKET,
        packet_source_fingerprint=FP1,
        source_identity_fingerprint=FP2,
        executable_path="/home/user/.local/bin/claude",
        observed_version="2.1.233",
        authenticated=True,
        working_directory="/work/agent-os",
        max_turns=12,
    )
    args.update(overrides)
    return build_claude_code_invocation(**args)


def test_invocation_is_deterministic_and_non_authorizing():
    one = make()
    two = make()
    assert one == two
    assert one.invocation_id == two.invocation_id
    assert one.provider_execution_authorized is False
    assert one.validation_authorized is False
    assert one.github_writes_authorized is False
    assert one.merge_authorized is False
    assert one.automatic_retry is False
    assert one.side_effects_performed is False


def test_exact_argv_is_non_shell_and_bounded():
    invocation = make()
    assert invocation.argv[0] == "/home/user/.local/bin/claude"
    assert invocation.argv[1] == "-p"
    assert "--output-format" in invocation.argv
    assert "json" in invocation.argv
    assert "--permission-mode" in invocation.argv
    assert "acceptEdits" in invocation.argv
    assert "--no-session-persistence" in invocation.argv
    assert "--no-chrome" in invocation.argv
    assert "--disable-slash-commands" in invocation.argv
    assert invocation.argv[invocation.argv.index("--tools") + 1] == ",".join(ALLOWED_TOOLS)
    assert invocation.argv[invocation.argv.index("--disallowedTools") + 1] == ",".join(DISALLOWED_TOOLS)
    assert "Bash" not in ALLOWED_TOOLS
    assert "mcp__*" in DISALLOWED_TOOLS
    assert all("$(" not in item and "`" not in item for item in invocation.argv)


def test_packet_and_source_identity_are_fingerprint_sensitive():
    base = make()
    changed_packet = make(implementation_packet={**PACKET, "objective": "different"})
    changed_source = make(source_identity_fingerprint="c" * 64)
    assert base.invocation_id != changed_packet.invocation_id
    assert base.invocation_id != changed_source.invocation_id


@pytest.mark.parametrize(
    "override",
    [
        {"executable_path": "claude"},
        {"executable_path": "/usr/bin/python"},
        {"observed_version": "2.1.232"},
        {"observed_version": "latest"},
        {"authenticated": False},
        {"working_directory": "relative/path"},
        {"packet_source_fingerprint": "not-a-digest"},
        {"max_turns": 0},
        {"max_turns": 33},
    ],
)
def test_invalid_provider_evidence_fails_closed(override):
    with pytest.raises(ClaudeCodeAdapterError):
        make(**override)


def test_prompt_is_bounded():
    with pytest.raises(ClaudeCodeAdapterError):
        make(implementation_packet={"objective": "x" * 40_000})


def result(**overrides):
    args = dict(
        invocation_id=make().invocation_id,
        exit_code=0,
        stdout=json.dumps({"result": "done", "is_error": False}).encode(),
        stderr=b"",
        timed_out=False,
    )
    args.update(overrides)
    return normalize_claude_code_result(**args)


def test_success_retains_only_digest_not_provider_prose():
    evidence = result()
    assert evidence.terminal_status is ClaudeCodeTerminalStatus.SUCCEEDED
    assert evidence.execution_succeeded is True
    assert evidence.response_sha256 is not None
    assert not hasattr(evidence, "result")
    assert evidence.validation_authorized is False
    assert evidence.github_writes_authorized is False
    assert evidence.merge_authorized is False
    assert evidence.automatic_retry is False
    assert evidence.side_effects_performed is True


def test_provider_reported_error_is_non_authorizing():
    evidence = result(stdout=json.dumps({"result": "failed", "is_error": True}).encode())
    assert evidence.terminal_status is ClaudeCodeTerminalStatus.PROVIDER_ERROR
    assert evidence.execution_succeeded is False


@pytest.mark.parametrize(
    ("override", "status"),
    [
        ({"exit_code": 2}, ClaudeCodeTerminalStatus.NONZERO_EXIT),
        ({"timed_out": True}, ClaudeCodeTerminalStatus.TIMED_OUT),
        ({"stdout": b"not-json"}, ClaudeCodeTerminalStatus.MALFORMED_OUTPUT),
        ({"stdout": json.dumps(["not", "object"]).encode()}, ClaudeCodeTerminalStatus.MALFORMED_OUTPUT),
        ({"stdout": json.dumps({"result": "missing error flag"}).encode()}, ClaudeCodeTerminalStatus.MALFORMED_OUTPUT),
        ({"stdout": b"x" * 70_000}, ClaudeCodeTerminalStatus.OUTPUT_REJECTED),
        ({"stdout": json.dumps({"result": "sk-ant-secret", "is_error": False}).encode()}, ClaudeCodeTerminalStatus.OUTPUT_REJECTED),
    ],
)
def test_terminal_failures_are_bounded_and_fail_closed(override, status):
    evidence = result(**override)
    assert evidence.terminal_status is status
    assert evidence.execution_succeeded is False
    assert evidence.validation_authorized is False
    assert evidence.merge_authorized is False


def test_architecture_module_has_no_execution_or_network_imports():
    source = Path(__file__).parents[1] / "src/workflow_scheduler/execution/claude_code_executor_adapter.py"
    text = source.read_text()
    forbidden = ("subprocess", "requests", "urllib", "socket", "github", "boto", "httpx")
    assert all(f"import {name}" not in text for name in forbidden)
