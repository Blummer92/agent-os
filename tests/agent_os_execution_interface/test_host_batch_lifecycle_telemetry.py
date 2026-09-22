from scripts.agent_os_execution_interface.host_batch_lifecycle_telemetry import (
    HostBatchLifecycleEvidence,
    classify_ceiling_divergence,
)


def evidence(**overrides):
    values = dict(
        parent_mission_identity="issue:2742",
        batch_identity="host-batch:observed",
        tool_budget_exhausted=True,
        last_successful_operation="github-read",
        continuation_classification_attempted="unknown",
        continuation_result_observed="unknown",
        next_internal_batch_attempted="unknown",
        terminal_reason="tool-call-ceiling",
    )
    values.update(overrides)
    return HostBatchLifecycleEvidence(**values)


def test_current_2742_observation_remains_unknown_without_host_telemetry():
    assert classify_ceiling_divergence(evidence()) == "host-lifecycle-transition-unknown"


def test_unscheduled_continuation_is_distinguishable():
    assert classify_ceiling_divergence(
        evidence(continuation_classification_attempted="no")
    ) == "continuation-classification-not-scheduled"


def test_unobserved_classifier_result_is_distinguishable():
    assert classify_ceiling_divergence(
        evidence(
            continuation_classification_attempted="yes",
            continuation_result_observed="no",
        )
    ) == "continuation-classification-result-not-observed"


def test_unconsumed_result_is_distinguishable():
    assert classify_ceiling_divergence(
        evidence(
            continuation_classification_attempted="yes",
            continuation_result_observed="yes",
            next_internal_batch_attempted="no",
        )
    ) == "continuation-result-not-consumed-for-next-batch"


def test_projection_never_grants_authority():
    result = evidence()
    assert result.execution_authorized is False
    assert result.github_writes_authorized is False
    assert result.side_effects_performed is False
