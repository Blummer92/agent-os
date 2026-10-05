from __future__ import annotations

import pytest

from workflow_scheduler.governance.first_run_validation_observation import (
    CODESPACES_RUNNER_ID,
    FIXED_GCE_RUNNER_ID,
    FirstRunValidationObservationError,
    observed_command_from_codespaces_evidence,
    observed_command_from_fixed_gce_evidence,
)

SHA = "a" * 40
REQUEST = "dev-validation:" + "b" * 64


def evidence(**updates):
    value = {
        "repository": "Blummer92/agent-os",
        "issue_number": 1972,
        "tested_sha": SHA,
        "validation_id": "remote-validation-suite",
        "profile_id": "remote-validation",
        "request_id": REQUEST,
        "runner_id": FIXED_GCE_RUNNER_ID,
        "started_at": "2026-09-12T14:00:00Z",
        "completed_at": "2026-09-12T14:00:02Z",
        "status": "success",
        "exit_code": 0,
        "stdout_tail": "ok",
        "stderr_tail": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
    }
    value.update(updates)
    return value


def observe(value):
    return observed_command_from_fixed_gce_evidence(
        value,
        expected_repository="Blummer92/agent-os",
        expected_issue_number=1972,
        expected_sha=SHA,
        expected_profile_id="remote-validation",
        expected_request_id=REQUEST,
    )


def test_valid_fixed_runner_evidence_projects_to_1985_observation():
    result = observe(evidence())
    assert result.runner_id == FIXED_GCE_RUNNER_ID
    assert result.profile_id == "remote-validation"
    assert result.started_at == "2026-09-12T14:00:00Z"
    assert result.completed_at == "2026-09-12T14:00:02Z"
    assert result.status == "passed"


@pytest.mark.parametrize("field", ["runner_id", "started_at", "completed_at"])
def test_missing_observed_runner_fields_fail_closed(field):
    value = evidence()
    value.pop(field)
    with pytest.raises(FirstRunValidationObservationError):
        observe(value)


def test_wrong_runner_identity_fails_closed():
    with pytest.raises(FirstRunValidationObservationError, match="runner-id-invalid"):
        observe(evidence(runner_id="caller-selected"))


def test_completion_before_start_fails_closed():
    with pytest.raises(FirstRunValidationObservationError, match="runner-time-order-invalid"):
        observe(evidence(completed_at="2026-09-12T13:59:59Z"))


@pytest.mark.parametrize(
    "updates",
    [
        {"repository": "other/repo"},
        {"issue_number": 1},
        {"tested_sha": "c" * 40},
        {"request_id": "dev-validation:" + "d" * 64},
        {"profile_id": "issue-acceptance"},
    ],
)
def test_runner_evidence_identity_drift_fails_closed(updates):
    with pytest.raises(FirstRunValidationObservationError):
        observe(evidence(**updates))


def test_runner_status_is_projected_without_authority_input():
    assert observe(evidence(status="failure", exit_code=1)).status == "failed"
    assert observe(evidence(status="timeout", exit_code=None)).status == "timed-out"
    assert observe(evidence(status="needs-decision", exit_code=None)).status == "infrastructure-error"


def codespaces_evidence(**updates):
    value = evidence(runner_id=CODESPACES_RUNNER_ID)
    value.update(updates)
    return value


def observe_codespaces(value):
    return observed_command_from_codespaces_evidence(
        value,
        expected_repository="Blummer92/agent-os",
        expected_issue_number=1972,
        expected_sha=SHA,
        expected_profile_id="remote-validation",
        expected_request_id=REQUEST,
    )


def test_valid_codespaces_runner_evidence_projects_to_1985_observation():
    result = observe_codespaces(codespaces_evidence())
    assert result.runner_id == CODESPACES_RUNNER_ID
    assert result.profile_id == "remote-validation"
    assert result.started_at == "2026-09-12T14:00:00Z"
    assert result.completed_at == "2026-09-12T14:00:02Z"
    assert result.status == "passed"


def test_codespaces_runner_rejects_gce_runner_id():
    with pytest.raises(FirstRunValidationObservationError, match="runner-id-invalid"):
        observe_codespaces(codespaces_evidence(runner_id=FIXED_GCE_RUNNER_ID))


def test_gce_runner_rejects_codespaces_runner_id():
    with pytest.raises(FirstRunValidationObservationError, match="runner-id-invalid"):
        observe(evidence(runner_id=CODESPACES_RUNNER_ID))


def test_unknown_runner_id_fails_closed():
    with pytest.raises(FirstRunValidationObservationError, match="runner-id-invalid"):
        observe_codespaces(codespaces_evidence(runner_id="caller-selected"))


def test_codespaces_completion_before_start_fails_closed():
    with pytest.raises(FirstRunValidationObservationError, match="runner-time-order-invalid"):
        observe_codespaces(codespaces_evidence(completed_at="2026-09-12T13:59:59Z"))


@pytest.mark.parametrize(
    "updates",
    [
        {"repository": "other/repo"},
        {"issue_number": 1},
        {"tested_sha": "c" * 40},
        {"request_id": "dev-validation:" + "d" * 64},
        {"profile_id": "issue-acceptance"},
    ],
)
def test_codespaces_evidence_identity_drift_fails_closed(updates):
    with pytest.raises(FirstRunValidationObservationError):
        observe_codespaces(codespaces_evidence(**updates))


def test_codespaces_runner_status_is_projected_without_authority_input():
    assert observe_codespaces(codespaces_evidence(status="failure", exit_code=1)).status == "failed"
    assert observe_codespaces(codespaces_evidence(status="timeout", exit_code=None)).status == "timed-out"
    assert (
        observe_codespaces(codespaces_evidence(status="needs-decision", exit_code=None)).status
        == "infrastructure-error"
    )
