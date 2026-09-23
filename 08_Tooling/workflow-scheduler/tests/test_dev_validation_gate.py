from __future__ import annotations

import json

import pytest

from workflow_scheduler.governance.dev_validation_gate import (
    evaluate_dev_validation_gate,
    main,
)

SHA = "a" * 40
BRANCH = "agent/1552-fast-deterministic-preflight"
VALIDATION_ID = "remote-validation-suite"


def transport(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "status": "accepted",
        "reason": "accepted-dev-validation-envelope",
        "repository": "Blummer92/agent-os",
        "issue_number": 1552,
        "dev_validation_branch_or_none": BRANCH,
        "dev_validation_sha_or_none": SHA,
        "dev_validation_id_or_none": VALIDATION_ID,
    }
    payload.update(overrides)
    return payload


def evidence(status: str = "success", **overrides: object) -> dict[str, object]:
    reason = "validation-passed" if status == "success" else (
        "validation-timeout" if status == "timeout" else "validation-failed"
    )
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "status": status,
        "reason_codes": [reason],
        "repository": "Blummer92/agent-os",
        "issue_number": 1552,
        "branch": BRANCH,
        "tested_sha": SHA,
        "validation_id": VALIDATION_ID,
        "request_id": "dev-validation:test",
        "exit_code": 0 if status == "success" else 1,
        "cleanup_complete": True,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }
    payload.update(overrides)
    return {"dev_validation": payload}


def test_success_is_the_only_passing_dev_validation_state() -> None:
    decision = evaluate_dev_validation_gate(transport(), evidence())
    assert decision.applies is True
    assert decision.passed is True
    assert decision.status == "success"
    assert decision.tested_sha == SHA
    assert decision.validation_id == VALIDATION_ID


@pytest.mark.parametrize("status", ["failure", "timeout", "needs-decision"])
def test_non_success_states_fail_closed(status: str) -> None:
    result = evidence(status, exit_code=None if status != "failure" else 2)
    decision = evaluate_dev_validation_gate(transport(), result)
    assert decision.applies is True
    assert decision.passed is False
    assert decision.status == status
    assert decision.reason == "dev-validation-not-success"


def test_collection_failure_cannot_be_mistaken_for_transport_success() -> None:
    decision = evaluate_dev_validation_gate(
        transport(),
        evidence("failure", exit_code=2, reason_codes=["validation-failed"]),
    )
    assert decision.passed is False
    assert decision.exit_code == 2
    assert decision.tested_sha == SHA


def test_ordinary_test_failure_cannot_be_mistaken_for_transport_success() -> None:
    decision = evaluate_dev_validation_gate(
        transport(),
        evidence("failure", exit_code=1, reason_codes=["validation-failed"]),
    )
    assert decision.passed is False
    assert decision.exit_code == 1


def test_infrastructure_failure_remains_distinct_from_test_failure() -> None:
    decision = evaluate_dev_validation_gate(
        transport(),
        evidence(
            "needs-decision",
            exit_code=None,
            reason_codes=["dev-validation-ssh-failed"],
            cleanup_complete=False,
        ),
    )
    assert decision.passed is False
    assert decision.status == "needs-decision"
    assert decision.exit_code is None


@pytest.mark.parametrize("result", [None, {}, {"dev_validation": "bad"}])
def test_missing_or_malformed_result_fails_closed(result: object) -> None:
    decision = evaluate_dev_validation_gate(transport(), result)  # type: ignore[arg-type]
    assert decision.applies is True
    assert decision.passed is False
    assert decision.reason == "dev-validation-result-missing-or-malformed"


def test_exact_sha_and_validation_identity_must_match_transport() -> None:
    wrong_sha = evaluate_dev_validation_gate(
        transport(), evidence(tested_sha="b" * 40)
    )
    wrong_id = evaluate_dev_validation_gate(
        transport(), evidence(validation_id="other-validation")
    )
    wrong_branch = evaluate_dev_validation_gate(
        transport(), evidence(branch="agent/other")
    )
    assert wrong_sha.reason == "dev-validation-identity-mismatch"
    assert wrong_id.reason == "dev-validation-identity-mismatch"
    assert wrong_branch.reason == "dev-validation-identity-mismatch"


def test_success_with_nonzero_exit_code_fails_closed() -> None:
    decision = evaluate_dev_validation_gate(transport(), evidence(exit_code=1))
    assert decision.passed is False
    assert decision.reason == "dev-validation-success-exit-code-invalid"


def test_success_requires_completed_cleanup() -> None:
    decision = evaluate_dev_validation_gate(
        transport(), evidence(cleanup_complete=False)
    )
    assert decision.passed is False
    assert decision.reason == "dev-validation-success-cleanup-incomplete"


def test_non_dev_validation_ingress_is_not_affected() -> None:
    decision = evaluate_dev_validation_gate(
        transport(reason="accepted-discovery-envelope"), None
    )
    assert decision.applies is False
    assert decision.passed is True
    assert decision.status == "not-applicable"


def test_cli_returns_nonzero_for_failed_dev_validation(tmp_path) -> None:
    transport_path = tmp_path / "transport.json"
    result_path = tmp_path / "result.json"
    transport_path.write_text(json.dumps(transport()), encoding="utf-8")
    result_path.write_text(json.dumps(evidence("failure", exit_code=1)), encoding="utf-8")
    assert main(["--transport", str(transport_path), "--result", str(result_path)]) == 1


def test_cli_returns_zero_for_successful_dev_validation(tmp_path) -> None:
    transport_path = tmp_path / "transport.json"
    result_path = tmp_path / "result.json"
    transport_path.write_text(json.dumps(transport()), encoding="utf-8")
    result_path.write_text(json.dumps(evidence()), encoding="utf-8")
    assert main(["--transport", str(transport_path), "--result", str(result_path)]) == 0


def test_cli_is_noop_for_non_dev_validation_ingress(tmp_path) -> None:
    transport_path = tmp_path / "transport.json"
    transport_path.write_text(
        json.dumps(transport(reason="accepted-discovery-envelope")),
        encoding="utf-8",
    )
    assert main(
        ["--transport", str(transport_path), "--result", str(tmp_path / "missing.json")]
    ) == 0
