import pytest

from scripts.agent_os_pr_remediation.ci_evidence_recovery import (
    CIEvidenceIdentity,
    RecoveryObservation,
    plan_ci_evidence_recovery,
)
from scripts.agent_os_pr_remediation.models import EvidenceValidationError

SHA = "a" * 40
NEW_SHA = "b" * 40


def identity(**overrides):
    values = dict(repository="Blummer92/agent-os", pr_number=1016, head_sha=SHA, run_id=31408046628, run_attempt=1, job_id=93600000001)
    values.update(overrides)
    return CIEvidenceIdentity(**values)


def test_direct_recovery_produces_usable_exact_head_evidence_without_authority():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        RecoveryObservation(path="direct-actions-log", succeeded=True, actionable_failure="structural validation: file too long"),
    ))
    assert plan.evidence_usable_for_attribution is True
    assert plan.actionable_failure == "structural validation: file too long"
    assert plan.next_path is None
    assert plan.repair_authorized is False
    assert plan.external_write_authorized is False
    assert plan.side_effects_performed is False


@pytest.mark.parametrize("reason", [
    "cli-unavailable", "cli-unauthenticated", "insufficient-permission",
    "credential-conflict", "wrong-host", "environment-expired", "disk-exhausted",
])
def test_environment_and_cli_failures_advance_to_next_path(reason):
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        RecoveryObservation(path="structured", succeeded=False, reason_code="run-log-unavailable"),
        RecoveryObservation(path="direct-actions-log", succeeded=False, reason_code=reason),
    ))
    assert plan.evidence_usable_for_attribution is False
    assert reason in plan.reason_codes
    assert plan.next_path == "gh-run-log"
    assert plan.user_handoff_required is False


def test_rate_limit_retries_same_path_within_budget():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        RecoveryObservation(path="direct-actions-log", succeeded=False, reason_code="rate-limited"),
    ), retry_count=1, retry_limit=2)
    assert plan.next_path == "direct-actions-log"
    assert plan.user_handoff_required is False


def test_rate_limit_exhaustion_advances_instead_of_looping():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        RecoveryObservation(path="direct-actions-log", succeeded=False, reason_code="rate-limited"),
    ), retry_count=2, retry_limit=2)
    assert plan.next_path == "structured"


def test_run_in_progress_stops_without_treating_logs_as_failed():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        RecoveryObservation(path="structured", succeeded=False, reason_code="run-in-progress", run_complete=False),
    ))
    assert plan.reason_codes == ("run-in-progress",)
    assert plan.next_path is None
    assert plan.user_handoff_required is False


def test_run_log_failure_can_fall_back_to_job_log_and_retain_partial_association():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        RecoveryObservation(path="gh-run-log", succeeded=False, reason_code="run-log-unavailable"),
        RecoveryObservation(path="job-log", succeeded=True, reason_code="log-association-failed", actionable_failure="pytest failed: assertion mismatch"),
    ))
    assert plan.evidence_usable_for_attribution is True
    assert plan.actionable_failure.startswith("pytest failed")
    assert "log-association-failed" in plan.reason_codes


def test_moved_head_fails_closed_before_recovery():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=NEW_SHA, current_run_attempt=1)
    assert plan.reason_codes == ("wrong-head",)
    assert plan.evidence_usable_for_attribution is False
    assert plan.next_path is None
    assert plan.repair_authorized is False


def test_newer_run_attempt_invalidates_old_evidence():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=2)
    assert plan.reason_codes == ("run-attempt-mismatch",)
    assert plan.next_path is None


def test_transient_network_uses_bounded_retry():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        RecoveryObservation(path="job-log", succeeded=False, reason_code="transient-network"),
    ), retry_count=0, retry_limit=1)
    assert plan.next_path == "job-log"


def test_all_paths_exhausted_produces_deterministic_user_handoff():
    observations = tuple(RecoveryObservation(path=path, succeeded=False, reason_code="job-log-unavailable") for path in (
        "structured", "direct-actions-log", "gh-run-log", "job-log", "approved-alternate"
    ))
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=observations)
    assert plan.user_handoff_required is True
    assert plan.next_path is None
    assert plan.reason_codes[-1] == "evidence-unavailable"
    assert plan.repair_authorized is False


def test_no_actionable_failure_does_not_authorize_repair():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        RecoveryObservation(path="structured", succeeded=True),
    ))
    assert plan.evidence_usable_for_attribution is False
    assert plan.repair_authorized is False


def test_identity_requires_exact_repo_and_sha():
    with pytest.raises(EvidenceValidationError):
        identity(repository="agent-os")
    with pytest.raises(EvidenceValidationError):
        identity(head_sha="abc")


def test_plan_is_deterministic():
    kwargs = dict(current_head_sha=SHA, current_run_attempt=1, observations=(
        RecoveryObservation(path="structured", succeeded=False, reason_code="run-log-unavailable"),
    ))
    first = plan_ci_evidence_recovery(identity(), **kwargs)
    second = plan_ci_evidence_recovery(identity(), **kwargs)
    assert first.plan_id == second.plan_id
    assert first.canonical_serialization == second.canonical_serialization
