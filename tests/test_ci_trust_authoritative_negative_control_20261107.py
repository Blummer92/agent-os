"""Disposable 20-case CI trust negative-control campaign — NEVER MERGE.

Each parametrized pytest case deliberately asserts an *unsafe* success for a
specific invalid gate input. Correct fail-closed behavior makes all 20 tests
FAIL, proving pytest discovers each case and the hosted aggregate rejects the
head. Not a permanent test suite or evidence of 20 distinct workflow lanes.
"""
import pytest

from scripts.agent_os_aggregate_gate import (
    AUTHORITATIVE_STATUS_CONTEXT,
    decide_terminal_status,
    evaluate_aggregate_gate,
    evaluate_reuse,
)

SHA_A = "a" * 40
SHA_B = "b" * 40


def _gate(validate="success", plan="success", frontend="success",
          tested_sha=SHA_A, expected_sha=SHA_A):
    return evaluate_aggregate_gate(
        validate, plan, frontend, True, tested_sha, expected_sha
    )[0]


def _status_success(**overrides):
    inputs = {
        "authoritative": True,
        "reused": False,
        "validate_result": "success",
        "aggregate_outcome": "success",
        "plan_result": "success",
        "frontend_result": "success",
        "frontend_required": True,
        "frontend_tested_sha": SHA_A,
        "frontend_expected_sha": SHA_A,
    }
    inputs.update(overrides)
    decision = decide_terminal_status(**inputs)
    return decision is not None and decision.state == "success"


def _unsafe_reuse_after_newer_failure():
    statuses = [
        {"context": AUTHORITATIVE_STATUS_CONTEXT, "id": 10, "state": "success"},
        {"context": AUTHORITATIVE_STATUS_CONTEXT, "id": 11, "state": "failure"},
    ]
    return evaluate_reuse(statuses)[0]


@pytest.mark.parametrize(
    ("case_name", "unsafe_acceptance"),
    [
        pytest.param("01-aggregate-skipped", lambda: _gate(validate='skipped'), id="01-aggregate-skipped"),
        pytest.param("02-aggregate-failure", lambda: _gate(validate='failure'), id="02-aggregate-failure"),
        pytest.param("03-aggregate-cancelled", lambda: _gate(validate='cancelled'), id="03-aggregate-cancelled"),
        pytest.param("04-aggregate-missing", lambda: _gate(validate=''), id="04-aggregate-missing"),
        pytest.param("05-aggregate-timed-out", lambda: _gate(validate='timed_out'), id="05-aggregate-timed-out"),
        pytest.param("06-aggregate-wrong-case", lambda: _gate(validate='Success'), id="06-aggregate-wrong-case"),
        pytest.param("07-focused-plan-failure", lambda: _gate(plan='failure'), id="07-focused-plan-failure"),
        pytest.param("08-focused-plan-cancelled", lambda: _gate(plan='cancelled'), id="08-focused-plan-cancelled"),
        pytest.param("09-frontend-failure", lambda: _gate(frontend='failure'), id="09-frontend-failure"),
        pytest.param("10-frontend-skipped", lambda: _gate(frontend='skipped'), id="10-frontend-skipped"),
        pytest.param("11-frontend-cancelled", lambda: _gate(frontend='cancelled'), id="11-frontend-cancelled"),
        pytest.param("12-frontend-missing", lambda: _gate(frontend=''), id="12-frontend-missing"),
        pytest.param("13-frontend-timed-out", lambda: _gate(frontend='timed_out'), id="13-frontend-timed-out"),
        pytest.param("14-frontend-wrong-case", lambda: _gate(frontend='Success'), id="14-frontend-wrong-case"),
        pytest.param("15-frontend-wrong-sha", lambda: _gate(tested_sha=SHA_B), id="15-frontend-wrong-sha"),
        pytest.param("16-frontend-missing-tested-sha", lambda: _gate(tested_sha=''), id="16-frontend-missing-tested-sha"),
        pytest.param("17-frontend-missing-verdict-sha", lambda: _gate(expected_sha=''), id="17-frontend-missing-verdict-sha"),
        pytest.param("18-aggregate-step-skipped-despite-job-success", lambda: _status_success(aggregate_outcome='skipped'), id="18-aggregate-step-skipped-despite-job-success"),
        pytest.param("19-reused-status-with-plan-failure", lambda: _status_success(reused=True, plan_result='failure'), id="19-reused-status-with-plan-failure"),
        pytest.param("20-older-success-overridden-by-newer-failure", lambda: _unsafe_reuse_after_newer_failure(), id="20-older-success-overridden-by-newer-failure"),
    ],
)
def test_ci_20x_rejected_evidence_must_not_appear_green(case_name, unsafe_acceptance):
    actually_accepted = unsafe_acceptance()
    # INTENTIONALLY INVERTED ASSERTION: a safe gate rejects each bad input.
    # Every expected failure has a unique marker for exact-head hosted log QA.
    assert actually_accepted, (
        f"CI_TRUST_20X_EXPECTED_FAILURE:{case_name}: "
        "correctly refused unsafe acceptance"
    )
