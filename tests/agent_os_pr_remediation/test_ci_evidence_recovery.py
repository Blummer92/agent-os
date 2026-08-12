import pytest

from scripts.agent_os_pr_remediation.ci_evidence_recovery import (
    DEFAULT_DIAGNOSTIC_EXCERPT_LINES,
    MAX_DIAGNOSTIC_EXCERPT_LINES,
    MIN_DIAGNOSTIC_EXCERPT_LINES,
    CIEvidenceIdentity,
    CIEvidenceRecoveryPlan,
    RecoveryObservation,
    diagnostic_excerpt_lines,
    expand_diagnostic_excerpt_lines,
    plan_ci_evidence_recovery,
)
from scripts.agent_os_pr_remediation.models import EvidenceValidationError

SHA = "a" * 40
NEW_SHA = "b" * 40


def identity(**overrides):
    values = dict(repository="Blummer92/agent-os", pr_number=1016, head_sha=SHA, run_id=31408046628, run_attempt=1, job_id=93600000001)
    values.update(overrides)
    return CIEvidenceIdentity(**values)


def observation(*, observed_identity=None, **kwargs):
    return RecoveryObservation(identity=observed_identity or identity(), **kwargs)


def test_diagnostic_excerpt_policy_exposes_exact_bounds_and_default():
    assert MIN_DIAGNOSTIC_EXCERPT_LINES == 50
    assert DEFAULT_DIAGNOSTIC_EXCERPT_LINES == 50
    assert MAX_DIAGNOSTIC_EXCERPT_LINES == 150
    assert diagnostic_excerpt_lines() == 50
    assert diagnostic_excerpt_lines(50) == 50
    assert diagnostic_excerpt_lines(150) == 150


def test_diagnostic_excerpt_expansion_is_deterministic_and_capped():
    assert expand_diagnostic_excerpt_lines(50) == 100
    assert expand_diagnostic_excerpt_lines(100) == 150
    assert expand_diagnostic_excerpt_lines(150) == 150
    assert expand_diagnostic_excerpt_lines(50, increment=125) == 150


@pytest.mark.parametrize("value", [49, 151, 0, -1, 50.0, True, None, "50"])
def test_diagnostic_excerpt_policy_rejects_out_of_range_or_non_integer_values(value):
    with pytest.raises(EvidenceValidationError):
        diagnostic_excerpt_lines(value)


@pytest.mark.parametrize("increment", [0, -1, 1.0, True, None])
def test_diagnostic_excerpt_expansion_rejects_invalid_increment(increment):
    with pytest.raises(EvidenceValidationError):
        expand_diagnostic_excerpt_lines(50, increment=increment)


def test_plan_carries_default_or_explicit_bounded_excerpt_target():
    default_plan = plan_ci_evidence_recovery(
        identity(), current_head_sha=SHA, current_run_attempt=1
    )
    expanded_plan = plan_ci_evidence_recovery(
        identity(),
        current_head_sha=SHA,
        current_run_attempt=1,
        diagnostic_excerpt_target_lines=150,
    )
    assert default_plan.diagnostic_excerpt_target_lines == 50
    assert expanded_plan.diagnostic_excerpt_target_lines == 150
    with pytest.raises(EvidenceValidationError):
        plan_ci_evidence_recovery(
            identity(),
            current_head_sha=SHA,
            current_run_attempt=1,
            diagnostic_excerpt_target_lines=151,
        )


def test_direct_recovery_produces_usable_exact_head_evidence_without_authority():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        observation(path="direct-actions-log", succeeded=True, actionable_failure="structural validation: file too long"),
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
        observation(path="structured", succeeded=False, reason_code="run-log-unavailable"),
        observation(path="direct-actions-log", succeeded=False, reason_code=reason),
    ))
    assert plan.evidence_usable_for_attribution is False
    assert reason in plan.reason_codes
    assert plan.next_path == "gh-run-log"
    assert plan.user_handoff_required is False


def test_rate_limit_retries_same_path_within_budget():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        observation(path="direct-actions-log", succeeded=False, reason_code="rate-limited"),
    ), retry_count=1, retry_limit=2)
    assert plan.next_path == "direct-actions-log"


def test_run_in_progress_stops_without_treating_logs_as_failed():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        observation(path="structured", succeeded=False, reason_code="run-in-progress", run_complete=False),
    ))
    assert plan.reason_codes == ("run-in-progress",)
    assert plan.next_path is None


def test_run_log_failure_can_fall_back_to_job_log_and_retain_partial_association():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        observation(path="gh-run-log", succeeded=False, reason_code="run-log-unavailable"),
        observation(path="job-log", succeeded=True, reason_code="log-association-failed", actionable_failure="pytest failed: assertion mismatch"),
    ))
    assert plan.evidence_usable_for_attribution is True
    assert "log-association-failed" in plan.reason_codes


def test_moved_head_and_new_attempt_fail_closed_before_recovery():
    moved = plan_ci_evidence_recovery(identity(), current_head_sha=NEW_SHA, current_run_attempt=1)
    rerun = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=2)
    assert moved.reason_codes == ("wrong-head",)
    assert rerun.reason_codes == ("run-attempt-mismatch",)
    assert moved.next_path is rerun.next_path is None


@pytest.mark.parametrize("reason", ["wrong-head", "run-attempt-mismatch"])
def test_observed_stale_identity_reason_fails_closed(reason):
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        observation(path="structured", succeeded=False, reason_code=reason),
        observation(path="direct-actions-log", succeeded=True, actionable_failure="must not be accepted"),
    ))
    assert plan.evidence_usable_for_attribution is False
    assert plan.actionable_failure is None
    assert plan.next_path is None


@pytest.mark.parametrize("overrides", [
    {"repository": "Other/repo"}, {"head_sha": NEW_SHA}, {"run_id": 999},
    {"run_attempt": 2}, {"job_id": 999},
])
def test_observation_identity_mismatch_fails_closed(overrides):
    observed = identity(**overrides)
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        observation(observed_identity=observed, path="direct-actions-log", succeeded=True, actionable_failure="wrong evidence"),
    ))
    assert plan.evidence_usable_for_attribution is False
    assert plan.actionable_failure is None
    assert plan.next_path is None


def test_transient_network_uses_bounded_retry():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        observation(path="job-log", succeeded=False, reason_code="transient-network"),
    ), retry_count=0, retry_limit=1)
    assert plan.next_path == "job-log"


def test_all_paths_exhausted_produces_deterministic_user_handoff():
    observations = tuple(observation(path=path, succeeded=False, reason_code="job-log-unavailable") for path in (
        "structured", "direct-actions-log", "gh-run-log", "job-log", "approved-alternate"
    ))
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=observations)
    assert plan.user_handoff_required is True
    assert plan.reason_codes[-1] == "evidence-unavailable"


def test_no_actionable_failure_does_not_authorize_repair():
    plan = plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=(
        observation(path="structured", succeeded=True),
    ))
    assert plan.evidence_usable_for_attribution is False
    assert plan.repair_authorized is False


@pytest.mark.parametrize("field,value", [
    ("repair_authorized", True), ("external_write_authorized", True),
    ("side_effects_performed", True), ("repair_authorized", 0),
])
def test_plan_direct_construction_rejects_authority_override(field, value):
    kwargs = dict(
        identity=identity(), current_head_sha=SHA, current_run_attempt=1,
        attempted_paths=(), next_path=None, reason_codes=(), actionable_failure=None,
        evidence_usable_for_attribution=False, retry_count=0, retry_limit=2,
        user_handoff_required=False,
    )
    kwargs[field] = value
    with pytest.raises(EvidenceValidationError):
        CIEvidenceRecoveryPlan(**kwargs)


def test_planner_rejects_invalid_model_types_before_dereference():
    with pytest.raises(EvidenceValidationError):
        plan_ci_evidence_recovery({}, current_head_sha=SHA, current_run_attempt=1)
    with pytest.raises(EvidenceValidationError):
        plan_ci_evidence_recovery(identity(), current_head_sha=SHA, current_run_attempt=1, observations=({},))


def test_identity_requires_exact_repo_and_sha():
    with pytest.raises(EvidenceValidationError):
        identity(repository="agent-os")
    with pytest.raises(EvidenceValidationError):
        identity(head_sha="abc")


def test_plan_is_deterministic():
    kwargs = dict(current_head_sha=SHA, current_run_attempt=1, observations=(
        observation(path="structured", succeeded=False, reason_code="run-log-unavailable"),
    ))
    first = plan_ci_evidence_recovery(identity(), **kwargs)
    second = plan_ci_evidence_recovery(identity(), **kwargs)
    assert first.plan_id == second.plan_id
    assert first.canonical_serialization == second.canonical_serialization
