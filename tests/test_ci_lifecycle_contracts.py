"""#1557 cross-boundary lifecycle, stale-state, idempotency, and concurrency regressions.

These tests intentionally compose existing canonical seams instead of introducing
new lifecycle, retry, lease, or supersession machinery.  They protect defect
classes identified by #1551/#1557 using deterministic offline evidence only.
"""

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
from scripts.agent_os_execution_interface.post_selection_continuation import (
    ContinuationClassification,
    ContinuationLineage,
    ContinuationObligation,
    PostSelectionAttemptEvidence,
    PriorAttemptEffect,
    classify_post_selection_continuation,
)
from agent_os_execution_service.execution_surface_availability import (
    ExecutionSurfaceAvailabilityOutcome,
)
from workflow_scheduler.project_execution import ProjectExecutionMVP, ProjectJob


SHA_A = "a" * 40
SHA_B = "b" * 40
OBSERVED = "2026-08-31T20:00:00Z"
LINEAGE = ContinuationLineage(
    repository="Blummer92/agent-os",
    issue_number=1557,
    branch="agent/1557-ci-tst3c-lifecycle",
    checkpoint_id="checkpoint:1557",
    lease_id="lease:1557",
)


def _lifecycle(status: ValidationLifecycleTerminalStatus) -> ValidationLifecycleResult:
    return ValidationLifecycleResult(
        schema_version=VALIDATION_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
        bundle_id="bundle:1557",
        request_id="request:1557",
        status=status,
        reason_codes=("ci-tst3c-fixture",),
        execution_authorized=False,
        side_effects_performed=False,
        evaluated_at=OBSERVED,
    )


def _run(
    run_id: str,
    head_sha: str,
    *,
    phase: ValidationRunPhase = ValidationRunPhase.TERMINAL,
    status: ValidationLifecycleTerminalStatus = ValidationLifecycleTerminalStatus.CANCELLED,
) -> ValidationRunEvidence:
    return ValidationRunEvidence(
        run_id=run_id,
        validation_lane="aggregate",
        concurrency_group="pr-1557",
        head_sha=head_sha,
        phase=phase,
        lifecycle_result=None if phase is not ValidationRunPhase.TERMINAL else _lifecycle(status),
    )


def _continuation(**overrides) -> PostSelectionAttemptEvidence:
    values = {
        "operation_id": "ci-tst3c-operation",
        "lineage": LINEAGE,
        "surface_outcome": ExecutionSurfaceAvailabilityOutcome.SELECTED_SURFACE_UNAVAILABLE,
        "approved_alternative_capability": "github-exact-read",
        "target_identity_reacquired": True,
    }
    values.update(overrides)
    return PostSelectionAttemptEvidence(**values)


def test_stale_pass_cannot_satisfy_current_head_and_same_evidence_is_idempotent() -> None:
    """#1551 stale-evidence class: an old green run never becomes current by repetition."""
    evidence = ValidationSupersessionEvidence(
        current_head_sha=SHA_B,
        observed_at=OBSERVED,
        evidence_current=True,
        prior_run=_run(
            "run-a",
            SHA_A,
            status=ValidationLifecycleTerminalStatus.SUCCEEDED,
        ),
        replacement_runs=(),
        concurrency_replacement_proven=False,
        user_or_external_cancellation_proven=False,
        failure_classification=None,
    )

    first = project_validation_head_disposition(evidence)
    second = project_validation_head_disposition(evidence)

    assert first == second
    assert first.disposition is ValidationHeadDisposition.STALE_HEAD
    assert first.satisfies_current_head is False
    assert first.retry_authorized is False


def test_supersession_requires_positive_current_replacement_evidence() -> None:
    """#1188/#1551: age or cancellation alone cannot manufacture supersession."""
    prior = _run("run-a", SHA_A)
    replacement = _run("run-b", SHA_B, phase=ValidationRunPhase.IN_PROGRESS)

    unproven = project_validation_head_disposition(
        ValidationSupersessionEvidence(
            current_head_sha=SHA_B,
            observed_at=OBSERVED,
            evidence_current=True,
            prior_run=prior,
            replacement_runs=(replacement,),
            concurrency_replacement_proven=False,
            user_or_external_cancellation_proven=False,
            failure_classification=None,
        )
    )
    proven = project_validation_head_disposition(
        ValidationSupersessionEvidence(
            current_head_sha=SHA_B,
            observed_at=OBSERVED,
            evidence_current=True,
            prior_run=prior,
            replacement_runs=(replacement,),
            concurrency_replacement_proven=True,
            user_or_external_cancellation_proven=False,
            failure_classification=None,
        )
    )

    assert unproven.disposition is ValidationHeadDisposition.NEEDS_DECISION
    assert proven.disposition is ValidationHeadDisposition.SUPERSEDED_BY_NEW_HEAD
    assert proven.satisfies_current_head is False
    assert proven.retry_authorized is False


def test_active_lease_and_continuation_contract_jointly_prevent_competing_execution() -> None:
    """#758/#1237/#1551: active ownership blocks both a second claim and reroute execution."""
    scheduler = ProjectExecutionMVP(
        [ProjectJob(id="issue-1557", issue_number=1557, title="CI-TST3C")]
    )
    first = scheduler.claim_job("issue-1557", "worker-a")
    second = scheduler.claim_job("issue-1557", "worker-b")
    continuation = classify_post_selection_continuation(
        _continuation(active_foreign_lease=True)
    )

    assert first is not None
    assert second is None
    assert scheduler.lease_state("issue-1557").worker_id == "worker-a"
    assert scheduler.lease_state("issue-1557").active is True
    assert continuation.classification is ContinuationClassification.AUTHORITY_OR_SCOPE_BOUNDARY
    assert continuation.continue_automatically is False
    assert continuation.lease_acquired is False
    assert continuation.scheduler_invoked is False
    assert continuation.competing_lineage_created is False


def test_ambiguous_mutation_routes_to_reconciliation_not_blind_retry() -> None:
    """#1237/#1551: uncertain side effects require readback and forbid a second mutation."""
    first = classify_post_selection_continuation(
        _continuation(prior_effect=PriorAttemptEffect.AMBIGUOUS)
    )
    second = classify_post_selection_continuation(
        _continuation(prior_effect=PriorAttemptEffect.AMBIGUOUS)
    )

    assert first == second
    assert first.classification is ContinuationClassification.PARTIAL_EFFECT_RECONCILIATION_REQUIRED
    assert ContinuationObligation.READ_BACK_CANONICAL_STATE in first.obligations
    assert first.continue_automatically is False
    assert first.mutation_permitted is False
    assert first.execution_authorized is False
    assert first.side_effects_performed is False


def test_same_state_rerun_converges_without_duplicate_mutation_or_new_authority() -> None:
    """#1237/#1551: already-applied state is convergence, not permission to mutate again."""
    first = classify_post_selection_continuation(
        _continuation(prior_effect=PriorAttemptEffect.DESIRED_STATE_ALREADY_PRESENT)
    )
    second = classify_post_selection_continuation(
        _continuation(prior_effect=PriorAttemptEffect.DESIRED_STATE_ALREADY_PRESENT)
    )

    assert first == second
    assert first.classification is ContinuationClassification.CAPABILITY_ALTERNATIVE_AVAILABLE
    assert first.continue_automatically is True
    assert first.mutation_permitted is False
    assert ContinuationObligation.SUPPRESS_DUPLICATE_MUTATION in first.obligations
    assert first.execution_authorized is False
    assert first.github_writes_authorized is False
    assert first.merge_authorized is False
    assert first.issue_closure_authorized is False
    assert first.external_writes_authorized is False
