"""Failed-repair admission gated on recovery-progress semantics (#2281).

Gap reproduction + focused coverage: ``classify_recovery_progress`` must be
reachable through the live MCP tool chain
``admit_agent_os_failed_repair_tool`` -> ``admit_agent_os_failed_repair`` ->
``evaluate_failed_repair_admission`` via optional keyword-only
``current`` / ``prior`` / ``prior_transition_fingerprint`` evidence.

Semantics:
- EQUIVALENT (no semantic progress vs prior) -> mutation inadmissible.
- PROGRESSED -> admissible exactly as before.
- RECOVERY_STALLED (same equivalent transition observed again) ->
  ``agent_os_continuation["stalled"] is True`` through the full tool chain.
- Omitted optional params -> behavior unchanged (#3280 sequencing).

The classification is a pure projection: no Notion read, no CI execution, no
mutation, and no retry happen inside it; capability failures stay outside the
recurrence accounting (only caller-supplied semantic identities move the
disposition).
"""
from __future__ import annotations

from agent_os_execution_service.failed_repair_admission import (
    evaluate_failed_repair_admission,
)
from agent_os_execution_service.mcp_facade import admit_agent_os_failed_repair
from agent_os_execution_service.mcp_server import admit_agent_os_failed_repair_tool
from workflow_scheduler.execution.continuation import (
    CONTINUATION_SCHEMA_VERSION,
    ContinuationDecision as SchedulerContinuationDecision,
    ContinuationDisposition,
)
from workflow_scheduler.execution.recovery_progress import (
    RecoverySemanticEvidence,
    classify_recovery_progress,
)

SHA_A = "a" * 40


def _scheduler_continuation(**overrides) -> SchedulerContinuationDecision:
    values = dict(
        schema_version=CONTINUATION_SCHEMA_VERSION,
        disposition=ContinuationDisposition.NEEDS_DECISION,
        repository="Blummer92/agent-os",
        issue_number=2281,
        branch="agent/2281-failed-repair-continuation",
        observed_base_sha=SHA_A,
        observed_head_sha=SHA_A,
        current_base_sha=SHA_A,
        current_head_sha=SHA_A,
        invocation_id="invocation-2281",
        execution_id="execution-2281",
        candidate_identity="candidate:2281",
        checkpoint_lineage_identity="checkpoint:2281",
        authorization_identity="authorization:2281",
        executor_identity="governed-runner",
        scope_identity="scope:2281",
        resume_plan_id="resume-plan:2281",
        resume_point="focused-tests-passed",
        lease_identity="lease:2281",
        lease_holder_identity=None,
        lease_generation=3,
        reason_codes=("lease.ambiguous",),
        recommended_action="manual recovery",
    )
    values.update(overrides)
    return SchedulerContinuationDecision(**values)


def _evidence(**overrides) -> RecoverySemanticEvidence:
    values = dict(
        continuation=_scheduler_continuation(),
        recovery_action="reacquire-current-evidence",
        effective_blocker="lease.ambiguous",
        route_decision_id="route:same",
        environment_evidence_id="environment:same",
    )
    values.update(overrides)
    return RecoverySemanticEvidence(**values)


def _activation(**overrides):
    value = {
        "attempt_id": "pr-2281-head-a-validation-1",
        "retry_reentry_outcome": "consumed",
        "selected_lesson_ids": ["LL-51"],
        "mutation_admissible": True,
    }
    value.update(overrides)
    return value


def _admission_kwargs(**overrides):
    value = {
        "activation_result": _activation(),
        "check_state": "red",
        "required_check_configuration_state": "current",
        "review_state": "clear",
        "branch_freshness": "current",
        "mergeability": "mergeable",
    }
    value.update(overrides)
    return value


def test_equivalent_recovery_evidence_makes_mutation_inadmissible() -> None:
    prior = _evidence()
    current = _evidence()
    result = evaluate_failed_repair_admission(
        **_admission_kwargs(current=current, prior=prior)
    )
    assert result.mutation_admissible is False
    assert "recovery-equivalent-no-semantic-progress" in result.reason_codes
    assert result.recovery_stalled is False


def test_progressed_recovery_evidence_preserves_admissibility() -> None:
    prior = _evidence()
    current = _evidence(effective_blocker="dependency.source-unavailable")
    result = evaluate_failed_repair_admission(
        **_admission_kwargs(current=current, prior=prior)
    )
    assert result.mutation_admissible is True
    assert result.next_action == "continue-authorized-repair-mutation"
    assert result.recovery_stalled is False


def test_initial_recovery_observation_preserves_admissibility() -> None:
    result = evaluate_failed_repair_admission(
        **_admission_kwargs(current=_evidence())
    )
    assert result.mutation_admissible is True
    assert result.next_action == "continue-authorized-repair-mutation"
    assert result.recovery_stalled is False


def test_stalled_recovery_marks_driver_continuation_stalled_through_facade() -> None:
    prior = _evidence()
    current = _evidence()
    first = classify_recovery_progress(current, prior=prior)
    result = admit_agent_os_failed_repair(
        **_admission_kwargs(
            current=current,
            prior=prior,
            prior_transition_fingerprint=first.transition_fingerprint,
        )
    )
    assert result["mutation_admissible"] is False
    assert "recovery-stalled-repeated-equivalent-transition" in result["reason_codes"]
    continuation = result["agent_os_continuation"]
    assert continuation["stalled"] is True
    assert continuation["blocked"] is True
    assert continuation["action"] == ""


def test_stalled_recovery_marks_driver_continuation_stalled_through_tool() -> None:
    prior = _evidence()
    current = _evidence()
    first = classify_recovery_progress(current, prior=prior)
    result = admit_agent_os_failed_repair_tool(
        **_admission_kwargs(
            current=current,
            prior=prior,
            prior_transition_fingerprint=first.transition_fingerprint,
        )
    )
    continuation = result["agent_os_continuation"]
    assert continuation["stalled"] is True
    assert continuation["blocked"] is True
    assert result["mutation_admissible"] is False


def test_equivalent_recovery_through_tool_blocks_without_stalled_flag() -> None:
    prior = _evidence()
    current = _evidence()
    result = admit_agent_os_failed_repair_tool(
        **_admission_kwargs(current=current, prior=prior)
    )
    assert result["mutation_admissible"] is False
    continuation = result["agent_os_continuation"]
    assert continuation["stalled"] is False
    assert continuation["blocked"] is True


def test_omitted_recovery_params_behave_unchanged() -> None:
    result = admit_agent_os_failed_repair_tool(**_admission_kwargs())
    assert result["mutation_admissible"] is True
    assert result["next_action"] == "continue-authorized-repair-mutation"
    continuation = result["agent_os_continuation"]
    assert continuation["stalled"] is False
    assert continuation["blocked"] is False
    assert continuation["action"] == "continue-authorized-repair-mutation"


def test_recovery_gating_is_non_authorizing_and_side_effect_free() -> None:
    prior = _evidence()
    current = _evidence()
    first = classify_recovery_progress(current, prior=prior)
    progress = classify_recovery_progress(
        current, prior=prior, prior_transition_fingerprint=first.transition_fingerprint
    )
    # The classification itself authorizes nothing: no retry, no lease, no
    # branch refresh, no merge, no external writes, no Notion read, no CI run.
    assert progress.retry_authorized is False
    assert progress.lease_takeover_authorized is False
    assert progress.branch_refresh_authorized is False
    assert progress.merge_authorized is False
    assert progress.external_writes_authorized is False
    result = admit_agent_os_failed_repair(
        **_admission_kwargs(
            current=current,
            prior=prior,
            prior_transition_fingerprint=first.transition_fingerprint,
        )
    )
    for flag in (
        "github_writes_authorized",
        "workflow_authorized",
        "merge_authorized",
        "issue_closure_authorized",
        "protected_setting_authorized",
        "production_authorized",
        "external_system_write_authorized",
    ):
        assert result[flag] is False
    continuation = result["agent_os_continuation"]
    assert continuation["execution_authorized"] is False
    assert continuation["github_writes_authorized"] is False
    assert continuation["side_effects_performed"] is False


def test_capability_failure_identity_change_is_progress_not_recurrence() -> None:
    # A capability failure that changes the effective blocker is semantic
    # movement: the recurrence accounting must not gate it as a repeated
    # repair. Capability failures stay outside recurrence; only equivalent
    # observations gate.
    prior = _evidence(effective_blocker="capability.schoology-live-read-unavailable")
    current = _evidence(effective_blocker="capability.codespace-route-available")
    result = evaluate_failed_repair_admission(
        **_admission_kwargs(current=current, prior=prior)
    )
    assert result.mutation_admissible is True
    assert "recovery-equivalent-no-semantic-progress" not in result.reason_codes
    assert "recovery-stalled-repeated-equivalent-transition" not in result.reason_codes
