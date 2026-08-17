from __future__ import annotations

from agent_os_execution_service.validation_lifecycle_evidence import (
    VALIDATION_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
    ValidationLifecycleResult,
    ValidationLifecycleTerminalStatus,
)
from agent_os_execution_service.validation_supersession import (
    ValidationHeadDisposition,
    ValidationRunEvidence,
    ValidationRunPhase,
    ValidationSupersessionEvidence,
    project_validation_head_disposition,
)
from scripts.agent_os_issue_acceptance.validation_failure_classifier import (
    EvidenceState,
    RequirementResult,
    ValidationFailureEvidence,
    classify_validation_failure,
)

SHA_A = "a" * 40
SHA_B = "b" * 40
OBSERVED = "2026-08-15T22:00:00Z"


def _lifecycle(status: ValidationLifecycleTerminalStatus) -> ValidationLifecycleResult:
    return ValidationLifecycleResult(
        schema_version=VALIDATION_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
        bundle_id="bundle:fixture",
        request_id="request:fixture",
        status=status,
        reason_codes=("fixture",),
        execution_authorized=False,
        side_effects_performed=False,
        evaluated_at=OBSERVED,
    )


def _run(
    *,
    run_id: str = "run-a",
    head_sha: str = SHA_A,
    phase: ValidationRunPhase = ValidationRunPhase.TERMINAL,
    status: ValidationLifecycleTerminalStatus = ValidationLifecycleTerminalStatus.CANCELLED,
    lane: str = "aggregate",
    group: str = "pr-1188",
) -> ValidationRunEvidence:
    return ValidationRunEvidence(
        run_id=run_id,
        validation_lane=lane,
        concurrency_group=group,
        head_sha=head_sha,
        phase=phase,
        lifecycle_result=None if phase is not ValidationRunPhase.TERMINAL else _lifecycle(status),
    )


def _evidence(**overrides) -> ValidationSupersessionEvidence:
    values = dict(
        current_head_sha=SHA_B,
        observed_at=OBSERVED,
        evidence_current=True,
        prior_run=_run(),
        replacement_runs=(
            _run(run_id="run-b", head_sha=SHA_B, phase=ValidationRunPhase.IN_PROGRESS),
        ),
        concurrency_replacement_proven=True,
        user_or_external_cancellation_proven=False,
        failure_classification=None,
    )
    values.update(overrides)
    return ValidationSupersessionEvidence(**values)


def test_cancelled_stale_head_with_proven_replacement_is_superseded() -> None:
    decision = project_validation_head_disposition(_evidence())
    assert decision.disposition is ValidationHeadDisposition.SUPERSEDED_BY_NEW_HEAD
    assert decision.replacement_run_ids == ("run-b",)
    assert "replacement.concurrency-proven" in decision.reason_codes
    assert decision.satisfies_current_head is False
    assert decision.retry_authorized is False


def test_cancelled_stale_head_without_replacement_proof_is_not_superseded() -> None:
    decision = project_validation_head_disposition(
        _evidence(concurrency_replacement_proven=False)
    )
    assert decision.disposition is ValidationHeadDisposition.NEEDS_DECISION
    assert "cancellation.cause-unproven" in decision.reason_codes


def test_replacement_must_match_current_head_lane_and_concurrency_group() -> None:
    wrong_lane = _run(
        run_id="run-b",
        head_sha=SHA_B,
        phase=ValidationRunPhase.QUEUED,
        lane="focused",
    )
    decision = project_validation_head_disposition(
        _evidence(replacement_runs=(wrong_lane,))
    )
    assert decision.disposition is ValidationHeadDisposition.NEEDS_DECISION


def test_explicit_user_or_external_cancellation_remains_distinct() -> None:
    decision = project_validation_head_disposition(
        _evidence(
            replacement_runs=(),
            concurrency_replacement_proven=False,
            user_or_external_cancellation_proven=True,
        )
    )
    assert decision.disposition is ValidationHeadDisposition.CANCELLED_BY_USER_OR_EXTERNAL_ACTION


def test_real_validation_failure_on_old_head_remains_failure_after_new_head_exists() -> None:
    failed = _run(status=ValidationLifecycleTerminalStatus.VALIDATION_FAILED)
    decision = project_validation_head_disposition(_evidence(prior_run=failed))
    assert decision.disposition is ValidationHeadDisposition.FAILED
    assert "validation.failure-preserved" in decision.reason_codes
    assert "validation.failure-on-prior-head" in decision.reason_codes


def test_prior_pass_cannot_satisfy_a_new_head() -> None:
    passed = _run(status=ValidationLifecycleTerminalStatus.SUCCEEDED)
    decision = project_validation_head_disposition(_evidence(prior_run=passed))
    assert decision.disposition is ValidationHeadDisposition.STALE_HEAD
    assert decision.satisfies_current_head is False


def test_only_current_exact_head_pass_satisfies_validation() -> None:
    current_pass = _run(head_sha=SHA_B, status=ValidationLifecycleTerminalStatus.SUCCEEDED)
    decision = project_validation_head_disposition(
        _evidence(current_head_sha=SHA_B, prior_run=current_pass, replacement_runs=())
    )
    assert decision.disposition is ValidationHeadDisposition.PASSED
    assert decision.satisfies_current_head is True


def test_current_head_in_progress_is_pending_without_duplicate_run() -> None:
    current = _run(head_sha=SHA_B, phase=ValidationRunPhase.IN_PROGRESS)
    decision = project_validation_head_disposition(
        _evidence(
            prior_run=current,
            replacement_runs=(),
            concurrency_replacement_proven=False,
        )
    )
    assert decision.disposition is ValidationHeadDisposition.PENDING
    assert "do not start a duplicate run" in decision.recommended_action


def test_old_nonterminal_run_is_stale_not_failed() -> None:
    old = _run(phase=ValidationRunPhase.IN_PROGRESS)
    decision = project_validation_head_disposition(_evidence(prior_run=old))
    assert decision.disposition is ValidationHeadDisposition.STALE_HEAD


def test_stale_supersession_evidence_never_proves_replacement() -> None:
    decision = project_validation_head_disposition(_evidence(evidence_current=False))
    assert decision.disposition is ValidationHeadDisposition.NEEDS_DECISION
    assert "supersession.evidence-stale" in decision.reason_codes


def test_existing_988_infrastructure_classification_is_reused() -> None:
    prior = _run(status=ValidationLifecycleTerminalStatus.VALIDATION_FAILED)
    classification = classify_validation_failure(
        ValidationFailureEvidence(
            pr_head_sha=SHA_A,
            comparison_main_sha=SHA_B,
            command="aggregate",
            failed_requirement="runner",
            error_excerpt="configuration unavailable",
            exit_code=1,
            source_identifiers=("run-a",),
            evidence_state=EvidenceState.CURRENT,
            comparable_pr_and_main=False,
            same_requirement_executed=False,
            pr_requirement_result=RequirementResult.FAIL,
            main_requirement_result=RequirementResult.UNAVAILABLE,
            materially_equivalent_failure=False,
            pr_scope_attribution_supported=False,
            infrastructure_configuration_failure_proven=True,
            infrastructure_authorization_boundary="workflow settings separately governed",
        )
    )
    decision = project_validation_head_disposition(
        _evidence(prior_run=prior, failure_classification=classification)
    )
    assert decision.disposition is ValidationHeadDisposition.INFRASTRUCTURE_FAILURE


def test_timeout_quarantine_and_blocked_remain_distinct() -> None:
    expected = {
        ValidationLifecycleTerminalStatus.TIMED_OUT: ValidationHeadDisposition.TIMED_OUT,
        ValidationLifecycleTerminalStatus.QUARANTINED: ValidationHeadDisposition.QUARANTINED,
        ValidationLifecycleTerminalStatus.BLOCKED: ValidationHeadDisposition.BLOCKED,
    }
    for status, disposition in expected.items():
        decision = project_validation_head_disposition(
            _evidence(prior_run=_run(status=status))
        )
        assert decision.disposition is disposition
        assert decision.retry_authorized is False


def test_cleanup_failure_is_not_hidden_as_superseded() -> None:
    cleanup = _run(status=ValidationLifecycleTerminalStatus.CLEANUP_FAILED)
    decision = project_validation_head_disposition(_evidence(prior_run=cleanup))
    assert decision.disposition is ValidationHeadDisposition.NEEDS_DECISION
    assert "validation.lifecycle:cleanup-failed" in decision.reason_codes
