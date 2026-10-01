"""Tests for the terminal aggregator-gate decision (#3114).

The gate is the CI-level backstop for the workflow-vs-aggregate confusion:
GitHub reports skipped jobs as Success on the enclosing workflow, so the
gate must fail unless the authoritative aggregate job itself reports exactly
``success``. These tests simulate each upstream disposition — including the
#3105/#3106/#3108 skipped-aggregate shape — and assert the gate outcome.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.agent_os_aggregate_gate import evaluate_aggregate_gate, main

ROOT = Path(__file__).resolve().parents[1]


def test_skipped_aggregate_closes_the_gate():
    gate_open, message = evaluate_aggregate_gate("skipped")
    assert gate_open is False
    assert "skipped" in message


@pytest.mark.parametrize("result", ["failure", "cancelled", "timed_out", ""])
def test_non_success_dispositions_close_the_gate(result):
    gate_open, _ = evaluate_aggregate_gate(result)
    assert gate_open is False


def test_exact_success_opens_the_gate():
    gate_open, message = evaluate_aggregate_gate("success")
    assert gate_open is True
    assert "gate open" in message


def test_near_success_values_do_not_open_the_gate():
    for result in ["Success", "SUCCESS", "successful", "success "]:
        assert evaluate_aggregate_gate(result)[0] is False


def test_non_string_result_is_rejected():
    with pytest.raises(TypeError):
        evaluate_aggregate_gate(None)


def test_main_exits_nonzero_for_skipped_aggregate(monkeypatch):
    monkeypatch.setenv("VALIDATE_RESULT", "skipped")
    monkeypatch.setenv("PLAN_RESULT", "success")
    assert main() == 1


def test_main_exits_zero_for_successful_aggregate(monkeypatch):
    monkeypatch.setenv("VALIDATE_RESULT", "success")
    monkeypatch.setenv("PLAN_RESULT", "skipped")
    assert main() == 0


def test_script_entrypoint_skipped_aggregate_exits_nonzero():
    env = dict(os.environ, VALIDATE_RESULT="skipped", PLAN_RESULT="success")
    completed = subprocess.run(
        [sys.executable, "scripts/agent_os_aggregate_gate.py"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert completed.returncode == 1
    assert "gate is closed" in completed.stderr
