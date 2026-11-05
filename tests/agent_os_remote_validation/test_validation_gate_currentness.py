"""Tests for validation-gate currentness classification (#3269)."""
import pytest

from scripts.agent_os_remote_validation.validation_gate_currentness import (
    CanonicalCheckRun,
    GateCurrentness,
    GateCurrentnessReason,
    ValidationGateCurrentnessResult,
    WrapperRunSnapshot,
    WrapperRunState,
    classify_validation_gate_currentness,
    serialize_validation_gate_currentness,
    validation_gate_currentness_result_id,
)

# Exact live shape from the #3269 reproduction on PR #3267.
HEAD = "7f7e801223a616fe8b62b7dddad48ed03daca893"
RUN_ID = 37134507655
OTHER_HEAD = "a" * 40


def wrapper(run_state=WrapperRunState.PENDING, job_count=0, run_head_sha=HEAD, run_conclusion=None):
    return WrapperRunSnapshot(
        run_id=RUN_ID,
        run_state=run_state,
        run_conclusion=run_conclusion,
        job_count=job_count,
        run_head_sha=run_head_sha,
    )


def check_run(name, status, conclusion=None, head_sha=HEAD):
    return CanonicalCheckRun(name=name, status=status, conclusion=conclusion, head_sha=head_sha)


def classify(wrapper_snapshot, check_runs, head_sha=HEAD):
    return classify_validation_gate_currentness(
        repository="Blummer92/agent-os",
        pull_request=3267,
        reacquired_head_sha=head_sha,
        wrapper_run=wrapper_snapshot,
        canonical_check_runs=check_runs,
    )


def test_3267_repro_pending_zero_jobs_vs_terminal_check_runs_is_stale_retry():
    result = classify(
        wrapper(),
        (
            check_run("Run validation plan", "in_progress"),
            check_run("Run aggregate validation", "completed", "failure"),
        ),
    )
    assert result.status is GateCurrentness.STALE_RETRY
    assert result.reason_codes == (GateCurrentnessReason.CANONICAL_TERMINAL_BEATS_WRAPPER,)
    assert result.head_sha == HEAD
    assert result.run_id == RUN_ID


def test_pending_zero_jobs_without_canonical_evidence_requires_cross_check():
    result = classify(wrapper(), ())
    assert result.status is GateCurrentness.CROSS_CHECK_REQUIRED
    assert result.reason_codes == (GateCurrentnessReason.WRAPPER_PENDING_ZERO_JOBS_UNCONFIRMED,)


def test_pending_zero_jobs_vs_inflight_check_runs_is_stale_retry():
    result = classify(wrapper(), (check_run("Run validation plan", "in_progress"),))
    assert result.status is GateCurrentness.STALE_RETRY
    assert result.reason_codes == (GateCurrentnessReason.CANONICAL_AHEAD_OF_WRAPPER,)


def test_queued_zero_jobs_is_treated_as_pending():
    result = classify(wrapper(run_state=WrapperRunState.QUEUED), ())
    assert result.status is GateCurrentness.CROSS_CHECK_REQUIRED


def test_converged_completed_gate_is_current():
    result = classify(
        wrapper(WrapperRunState.COMPLETED, job_count=8, run_conclusion="success"),
        (
            check_run("Run validation plan", "completed", "success"),
            check_run("Run aggregate validation", "completed", "success"),
        ),
    )
    assert result.status is GateCurrentness.CURRENT
    assert result.reason_codes == (GateCurrentnessReason.CONVERGED,)


def test_converged_failed_gate_is_current_not_stale():
    # Both sides agree the gate failed: current evidence of failure, not a
    # currentness conflict. The failure itself still blocks merge elsewhere.
    result = classify(
        wrapper(WrapperRunState.COMPLETED, job_count=8, run_conclusion="failure"),
        (check_run("Run aggregate validation", "completed", "failure"),),
    )
    assert result.status is GateCurrentness.CURRENT
    assert result.reason_codes == (GateCurrentnessReason.CONVERGED,)


def test_converged_in_progress_gate_is_current():
    result = classify(
        wrapper(WrapperRunState.IN_PROGRESS, job_count=5),
        (check_run("Run validation plan", "in_progress"),),
    )
    assert result.status is GateCurrentness.CURRENT
    assert result.reason_codes == (GateCurrentnessReason.CONVERGED,)


def test_wrapper_completed_but_check_run_failed_is_stale_retry():
    result = classify(
        wrapper(WrapperRunState.COMPLETED, job_count=8, run_conclusion="success"),
        (check_run("Run aggregate validation", "completed", "failure"),),
    )
    assert result.status is GateCurrentness.STALE_RETRY
    assert result.reason_codes == (GateCurrentnessReason.CONCLUSION_DIVERGED,)


def test_wrapper_completed_while_check_runs_still_running_is_stale_retry():
    result = classify(
        wrapper(WrapperRunState.COMPLETED, job_count=8, run_conclusion="success"),
        (check_run("Run aggregate validation", "in_progress"),),
    )
    assert result.status is GateCurrentness.STALE_RETRY
    assert result.reason_codes == (GateCurrentnessReason.CANONICAL_BEHIND_WRAPPER,)


def test_wrapper_run_for_older_head_is_stale_retry():
    result = classify(wrapper(run_head_sha=OTHER_HEAD), ())
    assert result.status is GateCurrentness.STALE_RETRY
    assert result.reason_codes == (GateCurrentnessReason.RUN_HEAD_SHA_STALE,)


def test_wrapper_in_progress_with_jobs_and_no_check_runs_is_current():
    result = classify(wrapper(WrapperRunState.IN_PROGRESS, job_count=5), ())
    assert result.status is GateCurrentness.CURRENT
    assert result.reason_codes == (GateCurrentnessReason.WRAPPER_SUBSTANTIVE_UNCONTESTED,)


def test_wrapper_completed_with_jobs_and_no_check_runs_is_current():
    result = classify(
        wrapper(WrapperRunState.COMPLETED, job_count=8, run_conclusion="success"), ()
    )
    assert result.status is GateCurrentness.CURRENT
    assert result.reason_codes == (GateCurrentnessReason.WRAPPER_TERMINAL_UNCONTESTED,)


def test_wrapper_in_progress_vs_terminal_check_runs_is_stale_retry():
    result = classify(
        wrapper(WrapperRunState.IN_PROGRESS, job_count=5),
        (check_run("Run aggregate validation", "completed", "failure"),),
    )
    assert result.status is GateCurrentness.STALE_RETRY
    assert result.reason_codes == (GateCurrentnessReason.CANONICAL_TERMINAL_BEATS_WRAPPER,)


def test_classification_grants_no_authority():
    result = classify(wrapper(), ())
    assert result.authoritative is False
    assert result.merge_authorized is False
    assert result.side_effects_performed is False
    serialized = serialize_validation_gate_currentness(result)
    assert serialized["authoritative"] is False
    assert serialized["merge_authorized"] is False
    assert serialized["side_effects_performed"] is False


def test_result_id_is_stable_and_bound_to_inputs():
    first = classify(wrapper(), ())
    second = classify(wrapper(), ())
    assert validation_gate_currentness_result_id(first) == validation_gate_currentness_result_id(second)
    assert first.result_id.startswith("validation-gate-currentness:")
    diverged = classify(wrapper(WrapperRunState.IN_PROGRESS, job_count=5), ())
    assert diverged.result_id != first.result_id


def test_tampered_result_fails_serialization():
    result = classify(wrapper(), ())
    tampered = ValidationGateCurrentnessResult(
        status=GateCurrentness.CURRENT,
        result_id=result.result_id,
        repository=result.repository,
        pull_request=result.pull_request,
        head_sha=result.head_sha,
        run_id=result.run_id,
        reason_codes=result.reason_codes,
    )
    with pytest.raises(ValueError, match="result ID mismatch"):
        serialize_validation_gate_currentness(tampered)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reacquired_head_sha": "not-a-sha"},
        {"reacquired_head_sha": "A" * 40},
        {"pull_request": 0},
        {"pull_request": True},
        {"repository": ""},
        {"repository": None},
    ],
)
def test_malformed_top_level_inputs_fail_closed(kwargs):
    with pytest.raises((TypeError, ValueError)):
        classify_validation_gate_currentness(
            repository=kwargs.get("repository", "Blummer92/agent-os"),
            pull_request=kwargs.get("pull_request", 3267),
            reacquired_head_sha=kwargs.get("reacquired_head_sha", HEAD),
            wrapper_run=wrapper(),
            canonical_check_runs=(),
        )


def test_malformed_wrapper_snapshot_fails_closed():
    with pytest.raises(ValueError):
        WrapperRunSnapshot(
            run_id=RUN_ID, run_state=WrapperRunState.PENDING, run_conclusion=None,
            job_count=True, run_head_sha=HEAD,
        )
    with pytest.raises(ValueError):
        # A pending run must not carry a conclusion.
        WrapperRunSnapshot(
            run_id=RUN_ID, run_state=WrapperRunState.PENDING, run_conclusion="success",
            job_count=0, run_head_sha=HEAD,
        )
    with pytest.raises(TypeError):
        classify_validation_gate_currentness(
            repository="Blummer92/agent-os",
            pull_request=3267,
            reacquired_head_sha=HEAD,
            wrapper_run={"run_id": RUN_ID},
            canonical_check_runs=(),
        )


def test_check_run_for_other_head_fails_closed():
    with pytest.raises(ValueError, match="reacquired head SHA"):
        classify(wrapper(), (check_run("Run validation plan", "in_progress", head_sha=OTHER_HEAD),))


def test_non_tuple_check_runs_fail_closed():
    with pytest.raises(TypeError):
        classify_validation_gate_currentness(
            repository="Blummer92/agent-os",
            pull_request=3267,
            reacquired_head_sha=HEAD,
            wrapper_run=wrapper(),
            canonical_check_runs=[check_run("Run validation plan", "in_progress")],
        )


# ---------------------------------------------------------------------------
# 2026-10-29 finish campaign (Workstream B3): terminal-conclusion matrix.
#
# _FAILURE_CONCLUSIONS already contains failure, timed_out, action_required
# and cancelled, but the pre-existing tests exercised only "failure".
# Converged terminal failures are CURRENT evidence of failure (never
# success, never merge authority); any wrapper/check divergence is
# STALE_RETRY, including a pending zero-job wrapper facing a terminal
# failure check run. A different head never inherits earlier validation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("conclusion", ["failure", "timed_out", "cancelled", "action_required"])
def test_converged_terminal_conclusion_is_current_failure_not_success(conclusion):
    result = classify(
        wrapper(WrapperRunState.COMPLETED, job_count=8, run_conclusion=conclusion),
        (check_run("Run aggregate validation", "completed", conclusion),),
    )
    assert result.status is GateCurrentness.CURRENT
    assert result.reason_codes == (GateCurrentnessReason.CONVERGED,)
    assert result.merge_authorized is False
    assert result.authoritative is False


@pytest.mark.parametrize("conclusion", ["timed_out", "cancelled", "action_required"])
def test_wrapper_success_vs_terminal_failure_check_is_diverged(conclusion):
    result = classify(
        wrapper(WrapperRunState.COMPLETED, job_count=8, run_conclusion="success"),
        (check_run("Run aggregate validation", "completed", conclusion),),
    )
    assert result.status is GateCurrentness.STALE_RETRY
    assert result.reason_codes == (GateCurrentnessReason.CONCLUSION_DIVERGED,)
    assert result.merge_authorized is False


@pytest.mark.parametrize("conclusion", ["timed_out", "cancelled", "action_required"])
def test_wrapper_failure_vs_terminal_success_check_is_diverged(conclusion):
    result = classify(
        wrapper(WrapperRunState.COMPLETED, job_count=8, run_conclusion=conclusion),
        (check_run("Run aggregate validation", "completed", "success"),),
    )
    assert result.status is GateCurrentness.STALE_RETRY
    assert result.reason_codes == (GateCurrentnessReason.CONCLUSION_DIVERGED,)


@pytest.mark.parametrize("conclusion", ["timed_out", "cancelled", "action_required"])
def test_pending_zero_job_wrapper_never_hides_terminal_failure_check(conclusion):
    result = classify(
        wrapper(),
        (check_run("Run aggregate validation", "completed", conclusion),),
    )
    assert result.status is GateCurrentness.STALE_RETRY
    assert result.reason_codes == (
        GateCurrentnessReason.CANONICAL_TERMINAL_BEATS_WRAPPER,
    )
    assert result.merge_authorized is False


def test_terminal_failure_evidence_for_another_head_is_not_inherited():
    # The classifier raises on a check run for a different head rather
    # than classifying it against the reacquired head (see pre-existing
    # test_check_run_for_other_head_fails_closed); this case pins the
    # complementary direction: a wrapper for a stale head is STALE_RETRY
    # even when its own conclusion agrees with the canonical failure.
    result = classify(
        wrapper(
            WrapperRunState.COMPLETED,
            job_count=8,
            run_conclusion="failure",
            run_head_sha=OTHER_HEAD,
        ),
        (check_run("Run aggregate validation", "completed", "failure"),),
    )
    assert result.status is GateCurrentness.STALE_RETRY
    assert result.reason_codes == (GateCurrentnessReason.RUN_HEAD_SHA_STALE,)
    assert result.merge_authorized is False


# ---------------------------------------------------------------------------
# 2026-11-05 CI mutation repair (bounded retest of V3): boundary regressions.
#
# Three surviving mutants, each killed by one direct test below. No
# production-code change: the unmutated code already behaves correctly on
# every probed input; these tests pin the contract the mutants weaken.
# ---------------------------------------------------------------------------


def test_short_lowercase_hex_head_sha_is_rejected():
    # _require_hex40 must enforce the exact-40 length for str inputs: "ab"
    # and "a" * 39 are valid lowercase hex but truncated. Kills
    # _require_hex40__mutmut_1 (or -> and drops the length check for strs).
    # Existing malformed cases ("not-a-sha", "A" * 40) do not kill it: the
    # first fails int(x, 16), the second fails the lowercase check.
    for bad_sha in ("ab", "a" * 39):
        with pytest.raises(ValueError, match="exact 40-character SHA"):
            classify_validation_gate_currentness(
                repository="Blummer92/agent-os",
                pull_request=3267,
                reacquired_head_sha=bad_sha,
                wrapper_run=wrapper(),
                canonical_check_runs=(),
            )


def test_valid_pr_number_one_is_accepted():
    # classify must accept pull_request=1, the smallest valid PR number.
    # Kills classify__mutmut_13 (<= 0 -> <= 1 falsely rejects PR #1).
    result = classify_validation_gate_currentness(
        repository="Blummer92/agent-os",
        pull_request=1,
        reacquired_head_sha=HEAD,
        wrapper_run=wrapper(),
        canonical_check_runs=(),
    )
    assert result.status is GateCurrentness.CROSS_CHECK_REQUIRED
    assert result.pull_request == 1


@pytest.mark.parametrize("bad_pr", ["3", None])
def test_non_integer_pr_number_raises_value_error(bad_pr):
    # A non-int pull_request must raise ValueError, not leak a TypeError
    # from the <= comparison. Kills classify__mutmut_9 (or -> and).
    with pytest.raises(ValueError):
        classify_validation_gate_currentness(
            repository="Blummer92/agent-os",
            pull_request=bad_pr,
            reacquired_head_sha=HEAD,
            wrapper_run=wrapper(),
            canonical_check_runs=(),
        )
