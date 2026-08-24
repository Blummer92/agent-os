from scripts.agent_os_issue_acceptance.evidence_compatibility import (
    CompatibilityEvidenceRecord,
    CompatibilityOutcome,
    ExpectedGeneration,
    evaluate_execution_dispatch_compatibility,
    evaluate_ready_for_review_compatibility,
)


def expected(**overrides: str) -> ExpectedGeneration:
    values = {
        "repository": "Blummer92/agent-os",
        "issue_identity": "issue:1201",
        "authorization_id": "authorization:current",
        "scope_id": "scope:current",
        "execution_id": "execution:2",
        "candidate_id": "candidate:2",
        "head_sha": "b" * 40,
        "base_sha": "a" * 40,
        "workspace_id": "workspace:2",
        "executor_surface": "chatgpt-governed-runner",
        "environment_id": "environment:2",
        "dependency_id": "dependency:2",
        "lease_generation": "lease:7",
        "command_plan_id": "command-plan:2",
        "resume_lineage_id": "resume:2",
        "lifecycle_snapshot_id": "lifecycle:2",
    }
    values.update(overrides)
    return ExpectedGeneration(bindings=tuple(values.items()))


def record(evidence_id: str, owner: str, **bindings: str) -> CompatibilityEvidenceRecord:
    return CompatibilityEvidenceRecord(
        evidence_id=evidence_id,
        owner=owner,
        bindings=tuple(bindings.items()),
    )


def test_coherent_generation_is_compatible_and_order_independent() -> None:
    records = (
        record("validation:2", "validation", repository="Blummer92/agent-os", head_sha="b" * 40),
        record("runtime:2", "runtime", execution_id="execution:2", environment_id="environment:2"),
    )
    first = evaluate_execution_dispatch_compatibility(expected=expected(), records=records)
    second = evaluate_execution_dispatch_compatibility(expected=expected(), records=tuple(reversed(records)))
    assert first == second
    assert first.outcome is CompatibilityOutcome.COMPATIBLE
    assert first.reason_codes == ("compatible",)
    assert first.authority_created is False
    assert first.side_effects_performed is False


def test_current_head_with_old_workspace_requires_reacquisition() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=expected(),
        records=(record("runtime:1", "runtime", head_sha="b" * 40, workspace_id="workspace:1"),),
    )
    assert decision.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED
    assert decision.reason_codes == ("binding.workspace_id.mismatch",)
    assert decision.reacquire_owners == ("runtime",)


def test_executor_surface_reroute_rejects_old_surface_evidence() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=expected(),
        records=(record("environment:1", "environment", executor_surface="local-cli", environment_id="environment:1"),),
    )
    assert decision.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED
    assert set(decision.reason_codes) == {
        "binding.environment_id.mismatch",
        "binding.executor_surface.mismatch",
    }


def test_current_resume_plan_with_old_execution_candidate_is_rejected() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=expected(),
        records=(record("resume:current", "resume", resume_lineage_id="resume:2", execution_id="execution:1", candidate_id="candidate:1"),),
    )
    assert decision.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED
    assert set(decision.reason_codes) == {
        "binding.candidate_id.mismatch",
        "binding.execution_id.mismatch",
    }


def test_branch_refresh_rejects_old_head_bound_runtime_evidence() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=expected(),
        records=(record("runtime:old-head", "runtime", head_sha="c" * 40, environment_id="environment:2"),),
    )
    assert decision.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED
    assert decision.reason_codes == ("binding.head_sha.mismatch",)


def test_current_validation_with_old_review_state_blocks_ready_for_review() -> None:
    decision = evaluate_ready_for_review_compatibility(
        expected=expected(),
        records=(
            record("validation:current", "validation", head_sha="b" * 40),
            record("review:old", "review", head_sha="c" * 40),
        ),
    )
    assert decision.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED
    assert decision.reacquire_owners == ("review",)


def test_old_validation_with_current_review_state_blocks_ready_for_review() -> None:
    decision = evaluate_ready_for_review_compatibility(
        expected=expected(),
        records=(
            record("validation:old", "validation", head_sha="c" * 40),
            record("review:current", "review", head_sha="b" * 40),
        ),
    )
    assert decision.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED
    assert decision.reacquire_owners == ("validation",)


def test_same_sha_different_environment_is_not_compatible() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=expected(),
        records=(record("environment:old", "environment", head_sha="b" * 40, environment_id="environment:1"),),
    )
    assert decision.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED
    assert decision.reason_codes == ("binding.environment_id.mismatch",)


def test_lease_bound_evidence_rejects_generation_change() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=expected(),
        records=(record("lease-bound:6", "scheduler", lease_generation="lease:6"),),
    )
    assert decision.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED


def test_lease_independent_evidence_is_not_over_invalidated() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=expected(),
        records=(record("static:1", "static-check", repository="Blummer92/agent-os", head_sha="b" * 40),),
    )
    assert decision.outcome is CompatibilityOutcome.COMPATIBLE


def test_authorization_change_requires_decision_not_reacquisition() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=expected(),
        records=(record("authorization:old", "authorization", authorization_id="authorization:old"),),
    )
    assert decision.outcome is CompatibilityOutcome.NEEDS_DECISION
    assert decision.reacquire_owners == ()


def test_dependency_evidence_from_other_workspace_is_rejected() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=expected(),
        records=(record("dependency:old", "dependency", dependency_id="dependency:2", workspace_id="workspace:1"),),
    )
    assert decision.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED
    assert decision.reason_codes == ("binding.workspace_id.mismatch",)


def test_reconstructed_invocation_plus_stale_environment_and_lease_is_rejected() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=expected(),
        records=(
            record("invocation:current", "invocation", execution_id="execution:2", head_sha="b" * 40),
            record("environment:old", "environment", environment_id="environment:1"),
            record("lease:old", "scheduler", lease_generation="lease:6"),
        ),
    )
    assert decision.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED
    assert set(decision.reacquire_owners) == {"environment", "scheduler"}


def test_missing_current_binding_fails_closed_to_needs_decision() -> None:
    current = ExpectedGeneration(bindings=(("repository", "Blummer92/agent-os"),))
    decision = evaluate_execution_dispatch_compatibility(
        expected=current,
        records=(record("runtime:2", "runtime", repository="Blummer92/agent-os", workspace_id="workspace:2"),),
    )
    assert decision.outcome is CompatibilityOutcome.NEEDS_DECISION
    assert decision.reason_codes == ("binding.workspace_id.current-unavailable",)


def test_scope_mismatch_never_widens_authority() -> None:
    decision = evaluate_ready_for_review_compatibility(
        expected=expected(),
        records=(record("scope:old", "scope", scope_id="scope:old"),),
    )
    assert decision.outcome is CompatibilityOutcome.NEEDS_DECISION


def test_duplicate_evidence_identity_is_rejected() -> None:
    item = record("runtime:2", "runtime", execution_id="execution:2")
    try:
        evaluate_execution_dispatch_compatibility(expected=expected(), records=(item, item))
    except ValueError as exc:
        assert "duplicate evidence_id" in str(exc)
    else:
        raise AssertionError("duplicate evidence identity must fail closed")
