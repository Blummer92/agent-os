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
                retry_reentry_outcome="not-material", mutation_admissible=False
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
    contents = result.content if hasattr(result, "content") else result[0]
    return json.loads(contents[0].text)


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
