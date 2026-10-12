"""Composition contract tests: #2761 decided obligation semantics.

When reusable exact-head candidate evidence says admissible but the newer
required current-main-health dependency is pending or failing, the admission
result is ``blocked`` (fail-closed). These tests compose the real
``classify_validation_gate_currentness`` with the decided mapping — the
currentness inputs are produced by the genuine classifier, never hand-built.
No shape assertions; every case executes the decision path.
"""
from dataclasses import replace

import pytest

from scripts.agent_os_remote_validation.validation_gate_currentness import (
    CanonicalCheckRun,
    GateCurrentness,
    MainHealthAdmission,
    ValidationGateCurrentnessResult,
    WrapperRunSnapshot,
    WrapperRunState,
    classify_validation_gate_currentness,
    compose_admission_with_main_health_currentness,
)

REPOSITORY = "Blummer92/agent-os"
# The main-health gate run is identified by the classifier's generic run identity;
# for main health the "pull request" slot carries the gate run's own number.
GATE_RUN_ID = 38300000001
MAIN_SHA = "f" * 40
SUPERSEDED_MAIN_SHA = "e" * 40


def health_wrapper(run_state=WrapperRunState.PENDING, job_count=0,
                   run_head_sha=MAIN_SHA, run_conclusion=None):
    return WrapperRunSnapshot(
        run_id=GATE_RUN_ID,
        run_state=run_state,
        run_conclusion=run_conclusion,
        job_count=job_count,
        run_head_sha=run_head_sha,
    )


def health_check_run(name, status, conclusion=None):
    return CanonicalCheckRun(
        name=name, status=status, conclusion=conclusion, head_sha=MAIN_SHA
    )


def classify_health(wrapper_snapshot, check_runs, reacquired_sha=MAIN_SHA):
    return classify_validation_gate_currentness(
        repository=REPOSITORY,
        pull_request=GATE_RUN_ID,
        reacquired_head_sha=reacquired_sha,
        wrapper_run=wrapper_snapshot,
        canonical_check_runs=check_runs,
    )


def compose(candidate_admissible, currentness, failed):
    return compose_admission_with_main_health_currentness(
        candidate_admissible=candidate_admissible,
        main_health_currentness=currentness,
        main_health_failed=failed,
    )


def test_2761_pending_main_health_blocks_admissible_candidate():
    # Newer main-health gate still pending: wrapper reports pending + zero jobs
    # with no canonical evidence yet. The real classifier refuses to present
    # this as current; the composition must block, never admit.
    currentness = classify_health(health_wrapper(), ())
    assert currentness.status is GateCurrentness.CROSS_CHECK_REQUIRED

    verdict = compose(True, currentness, failed=False)
    assert verdict is MainHealthAdmission.BLOCKED


def test_2761_failing_main_health_blocks_admissible_candidate():
    # Newer main-health gate converged on failure: wrapper completed/failure
    # and canonical check runs completed/failure. Currentness is CURRENT (the
    # failure state itself is reliably observed), but failing health still
    # blocks an otherwise admissible candidate.
    currentness = classify_health(
        health_wrapper(WrapperRunState.COMPLETED, job_count=8, run_conclusion="failure"),
        (health_check_run("Run aggregate validation", "completed", "failure"),),
    )
    assert currentness.status is GateCurrentness.CURRENT

    verdict = compose(True, currentness, failed=True)
    assert verdict is MainHealthAdmission.BLOCKED


def test_2761_green_main_health_preserves_admissible_candidate():
    # Control: current green main health leaves the candidate verdict standing.
    # The composition neither admits (that is the candidate evaluator's job)
    # nor blocks.
    currentness = classify_health(
        health_wrapper(WrapperRunState.COMPLETED, job_count=8, run_conclusion="success"),
        (health_check_run("Run aggregate validation", "completed", "success"),),
    )
    assert currentness.status is GateCurrentness.CURRENT

    verdict = compose(True, currentness, failed=False)
    assert verdict is MainHealthAdmission.CANDIDATE_VERDICT_STANDS


def test_2761_stale_main_health_evidence_is_never_treated_as_green():
    # The health gate run targets a superseded main SHA: the evidence is stale
    # relative to exact-current main. Staleness must block, never read as green.
    currentness = classify_health(
        health_wrapper(WrapperRunState.COMPLETED, job_count=8,
                       run_head_sha=SUPERSEDED_MAIN_SHA, run_conclusion="success"),
        (),
        reacquired_sha=MAIN_SHA,
    )
    assert currentness.status is GateCurrentness.STALE_RETRY

    verdict = compose(True, currentness, failed=False)
    assert verdict is MainHealthAdmission.BLOCKED


def test_2761_diverged_health_evidence_blocks_admissible_candidate():
    # Wrapper claims success while canonical check runs show failure: the
    # snapshots diverge, so the health evidence is unusable → blocked.
    currentness = classify_health(
        health_wrapper(WrapperRunState.COMPLETED, job_count=8, run_conclusion="success"),
        (health_check_run("Run aggregate validation", "completed", "failure"),),
    )
    assert currentness.status is GateCurrentness.STALE_RETRY

    verdict = compose(True, currentness, failed=True)
    assert verdict is MainHealthAdmission.BLOCKED


def test_2761_composition_never_upgrades_an_inadmissible_candidate():
    # The composition is a pure downgrade gate: green current health does not
    # rescue a candidate the evidence already refused.
    currentness = classify_health(
        health_wrapper(WrapperRunState.COMPLETED, job_count=8, run_conclusion="success"),
        (health_check_run("Run aggregate validation", "completed", "success"),),
    )
    assert currentness.status is GateCurrentness.CURRENT

    verdict = compose(False, currentness, failed=False)
    assert verdict is MainHealthAdmission.CANDIDATE_VERDICT_STANDS


def test_2761_tampered_currentness_result_is_refused():
    currentness = classify_health(
        health_wrapper(WrapperRunState.COMPLETED, job_count=8, run_conclusion="success"),
        (health_check_run("Run aggregate validation", "completed", "success"),),
    )
    tampered = replace(currentness, result_id="validation-gate-currentness:" + "0" * 64)
    with pytest.raises(ValueError, match="integrity verification"):
        compose(True, tampered, failed=False)


def test_2761_inputs_are_strictly_typed():
    currentness = classify_health(
        health_wrapper(WrapperRunState.COMPLETED, job_count=8, run_conclusion="success"),
        (health_check_run("Run aggregate validation", "completed", "success"),),
    )
    with pytest.raises(TypeError):
        compose_admission_with_main_health_currentness(
            candidate_admissible=1,
            main_health_currentness=currentness,
            main_health_failed=False,
        )
    with pytest.raises(TypeError):
        compose_admission_with_main_health_currentness(
            candidate_admissible=True,
            main_health_currentness="current",
            main_health_failed=False,
        )
    with pytest.raises(TypeError):
        compose_admission_with_main_health_currentness(
            candidate_admissible=True,
            main_health_currentness=currentness,
            main_health_failed=0,
        )
