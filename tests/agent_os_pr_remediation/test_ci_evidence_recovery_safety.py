from scripts.agent_os_pr_remediation.ci_evidence_recovery import (
    MAX_ACTIONABLE_FAILURE_CHARS,
    MAX_DIAGNOSTIC_EXCERPT_LINES,
    CIEvidenceIdentity,
    CIEvidenceRecoveryPlan,
    RecoveryObservation,
    plan_ci_evidence_recovery,
)

SHA = "a" * 40


def identity():
    return CIEvidenceIdentity(
        repository="Blummer92/agent-os",
        pr_number=1600,
        head_sha=SHA,
        run_id=33466185451,
        run_attempt=1,
        job_id=99726423920,
    )


def test_actionable_failure_redacts_secret_like_values_and_control_characters():
    observed = RecoveryObservation(
        identity=identity(),
        path="job-log",
        succeeded=True,
        actionable_failure=(
            "Authorization: super-secret\n"
            "token=abc123\n"
            "Bearer ghp_abcdefghijklmnopqrstuvwxyz\n"
            "bad\x00control"
        ),
    )
    assert "super-secret" not in observed.actionable_failure
    assert "abc123" not in observed.actionable_failure
    assert "ghp_" not in observed.actionable_failure
    assert "\x00" not in observed.actionable_failure
    assert "[REDACTED]" in observed.actionable_failure


def test_actionable_failure_is_bounded_to_maximum_lines():
    observed = RecoveryObservation(
        identity=identity(),
        path="job-log",
        succeeded=True,
        actionable_failure="\n".join(f"line {index}" for index in range(200)),
    )
    assert len(observed.actionable_failure.splitlines()) == MAX_DIAGNOSTIC_EXCERPT_LINES
    assert "line 149" in observed.actionable_failure
    assert "line 150" not in observed.actionable_failure


def test_actionable_failure_is_bounded_by_character_limit():
    observed = RecoveryObservation(
        identity=identity(),
        path="job-log",
        succeeded=True,
        actionable_failure="x" * (MAX_ACTIONABLE_FAILURE_CHARS + 500),
    )
    assert len(observed.actionable_failure) <= MAX_ACTIONABLE_FAILURE_CHARS + len("…[truncated]")
    assert observed.actionable_failure.endswith("…[truncated]")


def test_plan_only_carries_sanitized_observation_text():
    observed = RecoveryObservation(
        identity=identity(),
        path="job-log",
        succeeded=True,
        actionable_failure="password=hunter2\nAssertionError: expected 1 got 2",
    )
    plan = plan_ci_evidence_recovery(
        identity(),
        current_head_sha=SHA,
        current_run_attempt=1,
        observations=(observed,),
    )
    assert plan.evidence_usable_for_attribution is True
    assert "hunter2" not in plan.actionable_failure
    assert "AssertionError" in plan.actionable_failure


def test_direct_plan_construction_cannot_bypass_sanitization():
    plan = CIEvidenceRecoveryPlan(
        identity=identity(),
        current_head_sha=SHA,
        current_run_attempt=1,
        attempted_paths=("job-log",),
        next_path=None,
        reason_codes=(),
        actionable_failure="api_key=topsecret\nfailed assertion",
        evidence_usable_for_attribution=True,
        retry_count=0,
        retry_limit=2,
        user_handoff_required=False,
    )
    assert "topsecret" not in plan.actionable_failure
    assert "failed assertion" in plan.actionable_failure
    assert plan.repair_authorized is False
    assert plan.external_write_authorized is False
    assert plan.side_effects_performed is False
