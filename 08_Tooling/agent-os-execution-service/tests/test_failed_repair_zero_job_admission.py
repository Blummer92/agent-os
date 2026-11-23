"""Zero-job validation recovery on the live failed-repair path (#3277).

``failed_repair_admission`` is the FIRST live consumer of the surface-neutral
zero-job classifier. It is reached through the registered MCP tool chain
``admit_agent_os_failed_repair_tool`` -> ``admit_agent_os_failed_repair`` ->
``evaluate_failed_repair_admission``; BM2 (``batch_merge_execution``) is not
involved and receives no new behavior.

Non-executed validation evidence is never a red code-test failure and never
enters speculative CKR6 code repair; it projects the existing bounded exact-head
re-dispatch. Whether a session can actually dispatch it is #2410's concern and
is deliberately not asserted here.
"""
from __future__ import annotations

import asyncio
import inspect

from agent_os_execution_service import mcp_server
from agent_os_execution_service.failed_repair_admission import (
    evaluate_failed_repair_admission,
)
from agent_os_execution_service.mcp_facade import admit_agent_os_failed_repair
from agent_os_execution_service.mcp_server import admit_agent_os_failed_repair_tool
from scripts.agent_os_issue_acceptance.zero_job_validation_recovery import (
    WorkflowRunConclusionEvidence as Run,
    ZeroJobAdmissionEvidence,
)

HEAD = "b" * 40
MOVED = "c" * 40


def _activation(**overrides) -> dict[str, object]:
    values: dict[str, object] = {
        "attempt_id": "attempt-3277",
        "retry_reentry_outcome": "consumed",
        "selected_lesson_ids": ["LL-1"],
        "mutation_admissible": True,
    }
    values.update(overrides)
    return values


def _kwargs(**overrides):
    values = dict(
        activation_result=_activation(),
        check_state="red",
        required_check_configuration_state="current",
        review_state="clear",
        branch_freshness="current",
        mergeability="mergeable",
        failed_repair_attempt_id="attempt-3277",
    )
    values.update(overrides)
    return values


def _zero_job(*runs: Run, **overrides) -> ZeroJobAdmissionEvidence:
    values = dict(
        workflow_runs=tuple(runs),
        pull_request_number=3277,
        expected_head_sha=HEAD,
        current_head_sha=HEAD,
    )
    values.update(overrides)
    return ZeroJobAdmissionEvidence(**values)


def test_stale_non_executed_evidence_projects_redispatch_not_code_repair() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(zero_job=_zero_job(Run(1, "action_required", 0)))
    )
    assert record.mutation_admissible is False
    assert record.next_action == "reinvoke-governed-exact-head-validation"
    assert record.next_action != "reenter-ckr6-for-exact-failed-attempt"
    assert record.bounded_continuation_admitted is True
    assert record.zero_job_recovery is not None
    assert record.zero_job_recovery.expected_head_sha == HEAD
    assert "zero-job-run.stale-non-executed" in record.reason_codes
    assert "retry-lessons-and-diagnostics-converged" not in record.reason_codes


def test_zero_job_evidence_skips_ckr6_reentry_even_when_lessons_unconsumed() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(
            activation_result=_activation(
                retry_reentry_outcome="unavailable-or-failed", mutation_admissible=False
            ),
            zero_job=_zero_job(Run(1, "action_required", 0)),
        )
    )
    assert record.next_action == "reinvoke-governed-exact-head-validation"
    assert record.mutation_admissible is False


def test_pre_job_failure_is_not_a_red_code_test_failure() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(zero_job=_zero_job(Run(1, "failure", 0)))
    )
    assert record.mutation_admissible is False
    assert record.next_action == "diagnose-pre-job-workflow-definition-failure"
    assert record.bounded_continuation_admitted is False
    assert record.zero_job_recovery is None


def test_null_conclusion_zero_jobs_requires_currentness_cross_check() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(zero_job=_zero_job(Run(1, None, 0)))
    )
    assert record.mutation_admissible is False
    assert record.next_action == "cross-check-run-currentness-against-exact-head"
    assert record.zero_job_recovery is None


def test_executed_failure_stays_ordinary_code_repair() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(zero_job=_zero_job(Run(1, "action_required", 0), Run(2, "failure", 5)))
    )
    assert record.mutation_admissible is True
    assert record.next_action == "continue-authorized-repair-mutation"
    assert record.zero_job_recovery is None
    assert record.bounded_continuation_admitted is False


def test_recovery_is_capped_at_two_attempts() -> None:
    first = evaluate_failed_repair_admission(
        **_kwargs(zero_job=_zero_job(Run(1, "action_required", 0), recovery_attempts_used=1))
    )
    assert first.zero_job_recovery is not None and first.zero_job_recovery.attempt == 2
    third = evaluate_failed_repair_admission(
        **_kwargs(zero_job=_zero_job(Run(1, "action_required", 0), recovery_attempts_used=2))
    )
    assert third.zero_job_recovery is None
    assert third.bounded_continuation_admitted is False
    assert third.mutation_admissible is False
    assert "zero-job-recovery.attempts-exhausted" in third.reason_codes


def test_head_move_fails_closed() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(
            zero_job=_zero_job(Run(1, "action_required", 0), current_head_sha=MOVED)
        )
    )
    assert record.mutation_admissible is False
    assert record.zero_job_recovery is None
    assert record.bounded_continuation_admitted is False
    assert record.reason_codes[0] == "zero-job-evidence.head-moved"


def test_omitted_zero_job_evidence_leaves_admission_unchanged() -> None:
    record = evaluate_failed_repair_admission(**_kwargs())
    assert record.mutation_admissible is True
    assert record.zero_job_recovery is None
    assert record.bounded_continuation_admitted is False


def test_record_remains_non_authorizing_with_zero_job_projection() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(zero_job=_zero_job(Run(1, "action_required", 0)))
    )
    assert record.github_writes_authorized is False
    assert record.workflow_authorized is False
    assert record.merge_authorized is False
    assert record.issue_closure_authorized is False
    assert record.zero_job_recovery.tree_change_permitted is False  # type: ignore[union-attr]
    assert record.zero_job_recovery.side_effects_performed is False  # type: ignore[union-attr]


def test_facade_continuation_carries_the_bounded_redispatch_unblocked() -> None:
    payload = admit_agent_os_failed_repair(
        **_kwargs(zero_job=_zero_job(Run(1, "action_required", 0)))
    )
    continuation = payload["agent_os_continuation"]
    assert continuation["action"] == "reinvoke-governed-exact-head-validation"
    assert continuation["blocked"] is False
    assert continuation["execution_authorized"] is False
    assert continuation["github_writes_authorized"] is False
    assert payload["mutation_admissible"] is False


def test_facade_continuation_stays_blocked_for_head_move() -> None:
    payload = admit_agent_os_failed_repair(
        **_kwargs(
            zero_job=_zero_job(Run(1, "action_required", 0), current_head_sha=MOVED)
        )
    )
    assert payload["agent_os_continuation"]["blocked"] is True
    assert payload["agent_os_continuation"]["action"] == ""


def test_registered_mcp_tool_function_reaches_zero_job_classifier() -> None:
    payload = admit_agent_os_failed_repair_tool(
        **_kwargs(zero_job=_zero_job(Run(1, "action_required", 0)))
    )
    assert payload["next_action"] == "reinvoke-governed-exact-head-validation"
    assert payload["zero_job_recovery"]["attempt"] == 1
    assert payload["zero_job_recovery"]["max_attempts"] == 2
    assert "zero_job" in inspect.signature(admit_agent_os_failed_repair_tool).parameters


def _call_registered_tool(arguments: dict[str, object]) -> dict[str, object]:
    import json

    result = asyncio.run(
        mcp_server.mcp.call_tool("admit_agent_os_failed_repair_tool", arguments)
    )
    assert not getattr(result, "isError", False), "MCP returned an error result"
    contents = result.content if hasattr(result, "content") else result[0]
    assert contents, "Expected a non-empty MCP response"
    payload = json.loads(contents[0].text)
    assert isinstance(payload, dict), "Expected a JSON object from MCP admission"
    return payload


def _json_arguments(runs: list[dict[str, object]], **zero_job_overrides):
    zero_job: dict[str, object] = {
        "workflow_runs": runs,
        "pull_request_number": 3277,
        "expected_head_sha": HEAD,
        "current_head_sha": HEAD,
        "recovery_attempts_used": 0,
    }
    zero_job.update(zero_job_overrides)
    return {
        "activation_result": _activation(),
        "failed_repair_attempt_id": "attempt-3277",
        "check_state": "red",
        "required_check_configuration_state": "current",
        "review_state": "clear",
        "branch_freshness": "current",
        "mergeability": "mergeable",
        "zero_job": zero_job,
    }


def test_registered_mcp_server_advertises_and_executes_zero_job_input() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    tool = next(t for t in tools if t.name == "admit_agent_os_failed_repair_tool")
    assert "zero_job" in tool.input_schema["properties"]

    payload = _call_registered_tool(
        _json_arguments([{"run_id": 1, "conclusion": "action_required", "job_count": 0}])
    )
    assert payload["mutation_admissible"] is False
    assert payload["next_action"] == "reinvoke-governed-exact-head-validation"
    assert payload["agent_os_continuation"]["blocked"] is False
    assert payload["zero_job_recovery"]["recovery_operation"] == (
        "reinvoke-governed-exact-head-validation"
    )


def test_registered_mcp_server_fails_closed_on_head_move() -> None:
    payload = _call_registered_tool(
        _json_arguments(
            [{"run_id": 1, "conclusion": "action_required", "job_count": 0}],
            current_head_sha=MOVED,
        )
    )
    assert payload["agent_os_continuation"]["blocked"] is True
    assert payload["zero_job_recovery"] is None
    assert "zero-job-evidence.head-moved" in payload["reason_codes"]


def test_failed_repair_admission_is_a_non_test_consumer_of_the_classifier() -> None:
    import pathlib

    source = pathlib.Path(inspect.getsourcefile(evaluate_failed_repair_admission)).read_text(
        encoding="utf-8"
    )
    assert "zero_job_validation_recovery import" in source
    assert "project_zero_job_admission" in source
    assert "batch_merge_execution" not in source


# --------------------------------------------------------------------------
# #3772 cross-owner regression matrix (#3277 + #3280 + #2281 + CKR6).
# These are admission projections only; no workflow or GitHub write is issued.
# --------------------------------------------------------------------------

from dataclasses import asdict
from enum import Enum

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from agent_os_execution_service.failed_repair_admission import DiagnosticSurfaceEvidence
from workflow_scheduler.execution.continuation import (
    CONTINUATION_SCHEMA_VERSION,
    ContinuationDecision,
    ContinuationDisposition,
)
from workflow_scheduler.execution.recovery_progress import (
    RecoverySemanticEvidence,
    classify_recovery_progress,
)

ACTIONS = "github-actions-run-logs"
ANNOTATIONS = "check-run-annotations"


def _recovery_evidence(*, effective_blocker="lease.ambiguous"):
    continuation = ContinuationDecision(
        schema_version=CONTINUATION_SCHEMA_VERSION,
        disposition=ContinuationDisposition.NEEDS_DECISION,
        repository="Blummer92/agent-os",
        issue_number=2281,
        branch="agent/2281-failed-repair-continuation",
        observed_base_sha=HEAD,
        observed_head_sha=HEAD,
        current_base_sha=HEAD,
        current_head_sha=HEAD,
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
    return RecoverySemanticEvidence(
        continuation=continuation,
        recovery_action="reacquire-current-evidence",
        effective_blocker=effective_blocker,
        route_decision_id="route:same",
        environment_evidence_id="environment:same",
    )


def _diagnostics(*, exhausted=False):
    return DiagnosticSurfaceEvidence(
        diagnostics_actionable=False,
        authorized_surfaces=(ACTIONS, ANNOTATIONS),
        attempted_surfaces=(ACTIONS, ANNOTATIONS) if exhausted else (ACTIONS,),
    )


def _wire_value(value):
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return _wire_value(asdict(value))
    if isinstance(value, dict):
        return {key: _wire_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire_value(item) for item in value]
    return value


def test_zero_job_head_move_precedes_exhausted_budget():
    record = evaluate_failed_repair_admission(
        **_kwargs(
            zero_job=_zero_job(
                Run(1, "action_required", 0),
                current_head_sha=MOVED,
                recovery_attempts_used=2,
            )
        )
    )
    assert record.reason_codes[0] == "zero-job-evidence.head-moved"
    assert "zero-job-recovery.attempts-exhausted" not in record.reason_codes
    assert record.next_action == "reacquire-current-head-and-exact-head-validation-evidence"
    assert record.zero_job_recovery is None
    assert record.bounded_continuation_admitted is False
    assert record.mutation_admissible is False


def test_bounded_zero_job_redispatch_preserves_stalled_recovery_signal():
    prior = _recovery_evidence()
    first = classify_recovery_progress(prior, prior=prior)
    payload = admit_agent_os_failed_repair(
        **_kwargs(
            zero_job=_zero_job(Run(1, "action_required", 0)),
            current=prior,
            prior=prior,
            prior_transition_fingerprint=first.transition_fingerprint,
        )
    )
    assert payload["mutation_admissible"] is False
    assert payload["bounded_continuation_admitted"] is True
    assert payload["next_action"] == "reinvoke-governed-exact-head-validation"
    assert "recovery-stalled-repeated-equivalent-transition" in payload["reason_codes"]
    assert payload["agent_os_continuation"]["stalled"] is True
    assert payload["agent_os_continuation"]["execution_authorized"] is False


def test_zero_job_redispatch_preserves_exhausted_surface_blocker():
    record = evaluate_failed_repair_admission(
        **_kwargs(
            zero_job=_zero_job(Run(1, "action_required", 0)),
            diagnostics=_diagnostics(exhausted=True),
        )
    )
    assert record.next_action == "reinvoke-governed-exact-head-validation"
    assert record.bounded_continuation_admitted is True
    assert record.mutation_admissible is False
    assert record.diagnostic_blocker is not None
    assert record.diagnostic_blocker.kind == "BLOCKED_DIAGNOSTIC_SURFACE"
    assert "diagnostic-surface-exhausted" in record.reason_codes
    assert record.github_writes_authorized is False
    assert record.merge_authorized is False


def test_zero_job_exhaustion_cannot_be_reopened_by_alternate_diagnostics():
    record = evaluate_failed_repair_admission(
        **_kwargs(
            zero_job=_zero_job(
                Run(1, "action_required", 0), recovery_attempts_used=2
            ),
            diagnostics=_diagnostics(),
        )
    )
    assert "zero-job-recovery.attempts-exhausted" in record.reason_codes
    assert record.next_diagnostic_surface == ANNOTATIONS
    assert record.next_action == "route-zero-job-recovery-exhaustion-to-canonical-owner"
    assert record.bounded_continuation_admitted is False
    assert record.mutation_admissible is False


def test_zero_job_moved_head_cannot_be_reopened_by_alternate_diagnostics():
    record = evaluate_failed_repair_admission(
        **_kwargs(
            zero_job=_zero_job(
                Run(1, "action_required", 0), current_head_sha=MOVED
            ),
            diagnostics=_diagnostics(),
        )
    )
    assert record.reason_codes[0] == "zero-job-evidence.head-moved"
    assert record.next_diagnostic_surface == ANNOTATIONS
    assert record.bounded_continuation_admitted is False
    assert record.mutation_admissible is False


def test_executed_failure_still_obeys_recovery_stall_gate():
    prior = _recovery_evidence()
    first = classify_recovery_progress(prior, prior=prior)
    payload = admit_agent_os_failed_repair(
        **_kwargs(
            zero_job=_zero_job(Run(1, "failure", 5)),
            current=prior,
            prior=prior,
            prior_transition_fingerprint=first.transition_fingerprint,
        )
    )
    assert payload["mutation_admissible"] is False
    assert payload["bounded_continuation_admitted"] is False
    assert payload["agent_os_continuation"]["blocked"] is True
    assert payload["agent_os_continuation"]["stalled"] is True


def test_zero_job_bounded_redispatch_cannot_admit_stale_attempt():
    record = evaluate_failed_repair_admission(
        **_kwargs(
            failed_repair_attempt_id="wrong-attempt",
            zero_job=_zero_job(Run(1, "action_required", 0)),
        )
    )
    assert "retry-outcome-bound-to-different-attempt" in record.reason_codes
    assert record.mutation_admissible is False
    assert record.bounded_continuation_admitted is True
    assert record.next_action == "reinvoke-governed-exact-head-validation"


def test_registered_mcp_wire_composes_zero_job_recovery_diagnostics_and_ckr6():
    prior = _recovery_evidence()
    first = classify_recovery_progress(prior, prior=prior)
    arguments = _json_arguments(
        [{"run_id": 1, "conclusion": "action_required", "job_count": 0}]
    )
    arguments.update(
        diagnostics={
            "diagnostics_actionable": False,
            "authorized_surfaces": [ACTIONS, ANNOTATIONS],
            "attempted_surfaces": [ACTIONS, ANNOTATIONS],
        },
        current=_wire_value(prior),
        prior=_wire_value(prior),
        prior_transition_fingerprint=first.transition_fingerprint,
    )
    payload = _call_registered_tool(arguments)
    assert payload["mutation_admissible"] is False
    assert payload["next_action"] == "reinvoke-governed-exact-head-validation"
    assert payload["diagnostic_blocker"]["kind"] == "BLOCKED_DIAGNOSTIC_SURFACE"
    assert "recovery-stalled-repeated-equivalent-transition" in payload["reason_codes"]
    assert payload["agent_os_continuation"]["stalled"] is True
    assert payload["agent_os_continuation"]["github_writes_authorized"] is False


def test_registered_mcp_wire_stale_attempt_stays_non_admissible_with_zero_job():
    arguments = _json_arguments(
        [{"run_id": 1, "conclusion": "action_required", "job_count": 0}]
    )
    arguments["failed_repair_attempt_id"] = "stale-attempt"
    payload = _call_registered_tool(arguments)
    assert payload["mutation_admissible"] is False
    assert "retry-outcome-bound-to-different-attempt" in payload["reason_codes"]
    assert payload["agent_os_continuation"]["execution_authorized"] is False


@pytest.mark.parametrize(
    "invalid_run",
    [
        {"run_id": 1, "conclusion": "action_required", "job_count": -1},
        {"run_id": 1, "conclusion": "action_required", "job_count": "invalid"},
        {"run_id": 0, "conclusion": "action_required", "job_count": 0},
    ],
)
def test_registered_mcp_wire_rejects_invalid_nested_zero_job_evidence(invalid_run):
    arguments = _json_arguments([invalid_run])
    try:
        result = asyncio.run(
            mcp_server.mcp.call_tool("admit_agent_os_failed_repair_tool", arguments)
        )
    except ToolError:
        return
    assert getattr(result, "isError", False), (
        "Malformed nested zero-job evidence cannot be interpreted as an admitting "
        "or redispatch-authorizing MCP success response"
    )
