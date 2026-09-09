from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.agent_os_remote_validation.main_health import (
    main_health_result_id,
    project_main_health,
    serialize_main_health,
)

REPOSITORY = "Blummer92/agent-os"
MAIN_A = "a" * 40
MAIN_B = "b" * 40


def health(*, current=MAIN_A, evidence=MAIN_A, conclusion="success", recovery=False):
    return project_main_health(
        repository=REPOSITORY,
        current_main_sha=current,
        evidence_sha=evidence,
        validation_conclusion=conclusion,
        recovery_requested=recovery,
    )


def test_exact_current_main_green_opens_ordinary_admission():
    result = health()
    assert result.health == "healthy"
    assert result.ordinary_admission_allowed is True
    assert result.disposition == "ordinary-open"
    assert result.reason_codes == ("main-health.exact-main-green",)


def test_exact_current_main_repository_failure_freezes_ordinary_admission():
    result = health(conclusion="repository-failure")
    assert result.health == "unhealthy"
    assert result.ordinary_admission_allowed is False
    assert result.disposition == "ordinary-frozen"
    assert result.reason_codes == ("main-health.exact-main-red",)


def test_green_candidate_cannot_override_red_main_health():
    result = health(conclusion="repository-failure")
    # Candidate evidence belongs to #2235; repository health remains an independent input.
    assert result.ordinary_admission_allowed is False


def test_infrastructure_failure_is_unknown_not_repository_failure():
    result = health(conclusion="infrastructure-failure")
    assert result.health == "unknown"
    assert result.ordinary_admission_allowed is False
    assert result.reason_codes == ("main-health.infrastructure-unproven",)


def test_historical_green_evidence_is_stale_after_main_advances():
    result = health(current=MAIN_B, evidence=MAIN_A, conclusion="success")
    assert result.health == "unknown"
    assert result.ordinary_admission_allowed is False
    assert result.reason_codes == ("main-health.evidence-stale",)


def test_missing_evidence_fails_closed():
    result = health(evidence=None, conclusion="missing")
    assert result.health == "unknown"
    assert result.ordinary_admission_allowed is False
    assert result.reason_codes == ("main-health.evidence-missing",)


@pytest.mark.parametrize(
    ("conclusion", "reason"),
    [
        ("pending", "main-health.validation-pending"),
        ("cancelled", "main-health.validation-cancelled"),
        ("missing", "main-health.validation-missing"),
        ("unexpected", "main-health.validation-invalid"),
    ],
)
def test_unproven_exact_main_states_fail_closed(conclusion, reason):
    result = health(conclusion=conclusion)
    assert result.health == "unknown"
    assert result.ordinary_admission_allowed is False
    assert result.reason_codes == (reason,)


def test_bounded_recovery_lane_remains_available_while_main_red():
    result = health(conclusion="repository-failure", recovery=True)
    assert result.health == "unhealthy"
    assert result.ordinary_admission_allowed is False
    assert result.recovery_admission_allowed is True
    assert result.disposition == "recovery-only"
    assert result.merge_authorized is False
    assert result.revert_authorized is False


def test_recovery_request_does_not_turn_unknown_main_healthy():
    result = health(conclusion="pending", recovery=True)
    assert result.health == "unknown"
    assert result.ordinary_admission_allowed is False
    assert result.recovery_admission_allowed is True
    assert result.disposition == "recovery-only"


def test_repaired_exact_main_green_reopens_ordinary_admission():
    red = health(current=MAIN_A, evidence=MAIN_A, conclusion="repository-failure", recovery=True)
    repaired = health(current=MAIN_B, evidence=MAIN_B, conclusion="success")
    assert red.ordinary_admission_allowed is False
    assert repaired.health == "healthy"
    assert repaired.ordinary_admission_allowed is True


def test_two_sequential_main_shas_require_new_health_evidence():
    first = health(current=MAIN_A, evidence=MAIN_A, conclusion="repository-failure")
    second_without_evidence = health(current=MAIN_B, evidence=MAIN_A, conclusion="success")
    assert first.ordinary_admission_allowed is False
    assert second_without_evidence.ordinary_admission_allowed is False
    assert second_without_evidence.health == "unknown"


def test_health_result_does_not_attribute_main_failure_to_candidate():
    result = health(conclusion="repository-failure")
    payload = serialize_main_health(result)
    assert "pull_request" not in payload
    assert "candidate" not in payload
    assert result.reason_codes == ("main-health.exact-main-red",)


def test_result_is_content_addressed_and_non_authorizing():
    result = health()
    payload = serialize_main_health(result)
    assert main_health_result_id(result) == result.result_id
    assert payload["authoritative"] is False
    assert payload["merge_authorized"] is False
    assert payload["revert_authorized"] is False
    assert payload["side_effects_performed"] is False
    with pytest.raises(ValueError, match="result ID mismatch"):
        serialize_main_health(replace(result, health="unhealthy"))


def test_invalid_identity_fails_closed():
    result = project_main_health(
        repository="",
        current_main_sha="not-a-sha",
        evidence_sha=None,
        validation_conclusion="success",
    )
    assert result.health == "unknown"
    assert result.ordinary_admission_allowed is False
    assert result.reason_codes == ("main-health.identity-invalid",)
