"""#3690 AC6: executable conformance pin for the Claude Code Stop-hook seam.

The repository-owned Stop seam (``hook_adapter.run_stop_hook``) can block one
premature Stop, but only when the HOST supplies a structured
``agent_os_continuation`` observation in the hook payload (#2826, documented in
``continuation_driver``). These tests drive the REAL hook entrypoint as a
subprocess with a payload shaped like Claude Code's documented Stop input and
pin both halves of the boundary:

* repository side, conforming: a host-supplied nonterminal observation blocks
  exactly once with the exact action, never twice, and a terminal / blocked /
  stalled / malformed observation never blocks;
* host side, NOT closable from this repository: a Stop payload that carries no
  ``agent_os_continuation`` (what Claude Code sends) is a no-op, so an
  authorized nonterminal result that nothing forwarded to the Stop event cannot
  be turned into a next action by repository code.

The second half is deliberately a pin, not a fix: emitting the field from
repository code would be a fake continuation dispatcher. It documents the
externally owned seam (the host/MCP layer that produces the observation).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "scripts" / "agent-os-execution-interface-preflight.py"

# Shape of Claude Code's documented Stop hook input (no continuation field).
HOST_STOP_PAYLOAD = {
    "session_id": "abc123",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": str(REPO_ROOT),
    "permission_mode": "default",
    "hook_event_name": "Stop",
    "stop_hook_active": False,
}

NONTERMINAL = {
    "action": "reinvoke-governed-exact-head-validation",
    "terminal": False,
    "blocked": False,
    "stalled": False,
    "reason_codes": ["authorized-next-action"],
}


def run_stop(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ENTRYPOINT), "--hook", "stop"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
    )


def test_host_payload_without_structured_observation_is_a_no_op() -> None:
    # What Claude Code actually sends: nothing here can name an authorized next
    # action, so the seam must neither block nor invent one.
    done = run_stop(HOST_STOP_PAYLOAD)
    assert done.returncode == 0
    assert done.stdout == ""


def test_host_supplied_nonterminal_observation_blocks_exactly_once() -> None:
    first = run_stop({**HOST_STOP_PAYLOAD, "agent_os_continuation": NONTERMINAL})
    assert first.returncode == 0
    decoded = json.loads(first.stdout)
    assert decoded["decision"] == "block"
    assert "reinvoke-governed-exact-head-validation" in decoded["reason"]
    # Fixed non-authority statement travels with every block reason.
    assert "grant no implementation" in decoded["reason"]
    # The host's re-entry marker releases the Stop: the hook can never trap a turn.
    second = run_stop(
        {**HOST_STOP_PAYLOAD, "stop_hook_active": True, "agent_os_continuation": NONTERMINAL}
    )
    assert (second.returncode, second.stdout) == (0, "")


@pytest.mark.parametrize(
    "observation",
    [
        {**NONTERMINAL, "terminal": True, "action": ""},
        # terminal must win even when a leftover executable action is present
        {**NONTERMINAL, "terminal": True},
        {**NONTERMINAL, "blocked": True, "reason_codes": ["authorization-boundary"]},
        {**NONTERMINAL, "stalled": True},
        {**NONTERMINAL, "action": ""},  # no executable next action
        {**NONTERMINAL, "action": 7},  # malformed
        {**NONTERMINAL, "terminal": "yes"},  # malformed flag
        {**NONTERMINAL, "reason_codes": "not-a-list"},  # malformed reasons
        ["not", "a", "mapping"],
    ],
    ids=[
        "terminal",
        "terminal-with-leftover-action",
        "blocked",
        "stalled",
        "no-action",
        "bad-action",
        "bad-flag",
        "bad-reasons",
        "not-a-mapping",
    ],
)
def test_no_unauthorized_or_malformed_observation_ever_blocks(observation: object) -> None:
    done = run_stop({**HOST_STOP_PAYLOAD, "agent_os_continuation": observation})
    assert (done.returncode, done.stdout) == (0, "")


def test_non_governed_checkout_is_never_touched() -> None:
    done = run_stop({**HOST_STOP_PAYLOAD, "cwd": "/", "agent_os_continuation": NONTERMINAL})
    assert (done.returncode, done.stdout) == (0, "")
