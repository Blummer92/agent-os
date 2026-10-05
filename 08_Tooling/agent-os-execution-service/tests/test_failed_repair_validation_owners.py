"""Stale-head and validation-failure owners on the live failed-repair path (#3280).

Before this change ``project_validation_head_disposition`` and
``classify_validation_failure`` had no production caller reachable from a
registered runtime surface: the first had none at all, the second was reached
only through the offline ``agent-os-release-run.py`` CLI that no workflow or MCP
tool invokes. Both are now composed by ``evaluate_failed_repair_admission``,
reached through the registered MCP tool chain

    admit_agent_os_failed_repair_tool -> admit_agent_os_failed_repair
        -> evaluate_failed_repair_admission
        -> project_validation_head_disposition / classify_validation_failure

These tests drive that chain, including the registered MCP server's
``call_tool`` with JSON arguments, rather than calling the owners directly.
"""
from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import pathlib

import pytest

from agent_os_execution_service import mcp_server
from agent_os_execution_service import failed_repair_admission as admission_module
from agent_os_execution_service.failed_repair_admission import (
    evaluate_failed_repair_admission,
)
from agent_os_execution_service.mcp_facade import admit_agent_os_failed_repair
from agent_os_execution_service.mcp_server import admit_agent_os_failed_repair_tool
from agent_os_execution_service.validation_lifecycle_evidence import (
    VALIDATION_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
    ValidationLifecycleResult,
    ValidationLifecycleTerminalStatus,
)
from agent_os_execution_service.validation_supersession import (
    ValidationRunEvidence,
    ValidationRunPhase,
    ValidationSupersessionEvidence,
)
from scripts.agent_os_issue_acceptance.validation_failure_classifier import (
    EvidenceState,
    RequirementResult,
    ValidationFailureEvidence,
)

OLD = "a" * 40
CURRENT = "b" * 40
MAIN = "c" * 40
OBSERVED = "2026-10-04T22:00:00Z"
LADDER = (
    "repair within authorized current scope -> rerun focused validation -> "
    "rerun exact-head aggregate validation -> continue"
)


def _activation() -> dict[str, object]:
    return {
        "attempt_id": "attempt-3280",
        "retry_reentry_outcome": "consumed",
        "selected_lesson_ids": ["LL-1"],
        "mutation_admissible": True,
    }


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
    head: str,
    status: ValidationLifecycleTerminalStatus | None,
    phase: ValidationRunPhase = ValidationRunPhase.TERMINAL,
    run_id: str = "run-1",
) -> ValidationRunEvidence:
    return ValidationRunEvidence(
        run_id=run_id,
        validation_lane="aggregate",
        concurrency_group="pr-3280",
        head_sha=head,
        phase=phase,
        lifecycle_result=_lifecycle(status) if phase is ValidationRunPhase.TERMINAL else None,
    )


def _head(prior: ValidationRunEvidence, **overrides) -> ValidationSupersessionEvidence:
    values = dict(
        current_head_sha=CURRENT,
        observed_at=OBSERVED,
        evidence_current=True,
        prior_run=prior,
    )
    values.update(overrides)
    return ValidationSupersessionEvidence(**values)


FAILED = ValidationLifecycleTerminalStatus.VALIDATION_FAILED
SUCCEEDED = ValidationLifecycleTerminalStatus.SUCCEEDED


def _failure(**overrides) -> ValidationFailureEvidence:
    values = dict(
        pr_head_sha=CURRENT,
        comparison_main_sha=MAIN,
        command="python3 -m pytest",
        failed_requirement="tests/test_x.py::test_y",
        error_excerpt="AssertionError",
        exit_code=1,
        source_identifiers=("run-1",),
        evidence_state=EvidenceState.CURRENT,
        comparable_pr_and_main=True,
        same_requirement_executed=True,
        pr_requirement_result=RequirementResult.FAIL,
        main_requirement_result=RequirementResult.PASS,
        pr_scope_attribution_supported=True,
    )
    values.update(overrides)
    return ValidationFailureEvidence(**values)


# --------------------------------------------------------------------------
# Stale-head owner
# --------------------------------------------------------------------------


def test_prior_head_pass_cannot_satisfy_current_head() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(validation_head=_head(_run(head=OLD, status=SUCCEEDED)))
    )
    assert record.mutation_admissible is False
    assert record.next_action == "reacquire-current-head-validation-evidence"
    assert record.validation_head_disposition == "stale-head"
    assert "validation-head-stale-evidence-cannot-satisfy-current-head" in record.reason_codes
    assert "retry-lessons-and-diagnostics-converged" not in record.reason_codes


def test_nonterminal_run_on_old_head_is_stale() -> None:
    prior = _run(head=OLD, status=None, phase=ValidationRunPhase.IN_PROGRESS)
    record = evaluate_failed_repair_admission(**_kwargs(validation_head=_head(prior)))
    assert record.validation_head_disposition == "stale-head"
    assert record.next_action == "reacquire-current-head-validation-evidence"
    assert record.mutation_admissible is False


def test_failure_preserved_on_prior_head_is_not_current_red() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(validation_head=_head(_run(head=OLD, status=FAILED)))
    )
    assert record.validation_head_disposition == "failed"
    assert record.mutation_admissible is False
    assert record.next_action == "reacquire-current-head-validation-evidence"


def test_cancelled_old_head_with_proven_replacement_is_superseded_and_gated() -> None:
    cancelled = _run(head=OLD, status=ValidationLifecycleTerminalStatus.CANCELLED)
    replacement = _run(
        head=CURRENT,
        status=None,
        phase=ValidationRunPhase.IN_PROGRESS,
        run_id="run-2",
    )
    record = evaluate_failed_repair_admission(
        **_kwargs(
            validation_head=_head(
                cancelled,
                replacement_runs=(replacement,),
                concurrency_replacement_proven=True,
            )
        )
    )
    assert record.validation_head_disposition == "superseded-by-new-head"
    assert record.next_action == "reacquire-current-head-validation-evidence"
    assert record.mutation_admissible is False


def test_current_head_failure_stays_ordinary_repair() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(validation_head=_head(_run(head=CURRENT, status=FAILED)))
    )
    assert record.validation_head_disposition == "failed"
    assert record.mutation_admissible is True
    assert record.next_action == "continue-authorized-repair-mutation"


def test_other_dispositions_fail_closed_to_the_owner() -> None:
    pending = _run(head=CURRENT, status=None, phase=ValidationRunPhase.IN_PROGRESS)
    record = evaluate_failed_repair_admission(**_kwargs(validation_head=_head(pending)))
    assert record.validation_head_disposition == "pending"
    assert record.mutation_admissible is False
    assert record.next_action == "route-validation-head-disposition-to-canonical-owner"

    stale_evidence = evaluate_failed_repair_admission(
        **_kwargs(
            validation_head=_head(
                _run(head=CURRENT, status=FAILED), evidence_current=False
            )
        )
    )
    assert stale_evidence.validation_head_disposition == "needs-decision"
    assert stale_evidence.mutation_admissible is False


def test_omitted_validation_evidence_leaves_admission_unchanged() -> None:
    record = evaluate_failed_repair_admission(**_kwargs())
    assert record.mutation_admissible is True
    assert record.validation_head_disposition is None
    assert record.validation_failure_classification is None
    assert record.validation_repair_ladder is None


# --------------------------------------------------------------------------
# Validation-failure owner
# --------------------------------------------------------------------------


def test_pr_regression_keeps_focused_then_exact_head_aggregate_ladder() -> None:
    record = evaluate_failed_repair_admission(**_kwargs(validation_failure=_failure()))
    assert record.validation_failure_classification == "pr_regression"
    assert record.validation_repair_ladder == LADDER
    assert record.mutation_admissible is True
    assert record.next_action == "continue-authorized-repair-mutation"


def test_inherited_main_failure_does_not_contaminate_the_pr() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(
            validation_failure=_failure(
                main_requirement_result=RequirementResult.FAIL,
                materially_equivalent_failure=True,
                pr_scope_attribution_supported=False,
            )
        )
    )
    assert record.validation_failure_classification == "inherited_main_failure"
    assert record.mutation_admissible is False
    assert record.next_action == "report-inherited-main-failure-blocker"
    assert record.validation_repair_ladder is None


def test_infrastructure_configuration_failure_stops_at_authorization_boundary() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(
            validation_failure=_failure(
                infrastructure_configuration_failure_proven=True,
                comparable_pr_and_main=False,
            )
        )
    )
    assert record.validation_failure_classification == "ci_infrastructure_configuration_failure"
    assert record.mutation_admissible is False
    assert record.next_action == "stop-at-ci-infrastructure-authorization-boundary"


def test_insufficient_evidence_requests_only_the_missing_evidence() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(validation_failure=_failure(comparable_pr_and_main=False))
    )
    assert record.validation_failure_classification == "insufficient_evidence_needs_decision"
    assert record.mutation_admissible is False
    assert record.next_action == "reacquire-missing-validation-failure-evidence"


def test_stale_failure_evidence_is_insufficient_not_pr_regression() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(validation_failure=_failure(evidence_state=EvidenceState.STALE))
    )
    assert record.validation_failure_classification == "insufficient_evidence_needs_decision"
    assert record.mutation_admissible is False


def test_failure_evidence_bound_to_another_head_requires_reacquisition() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(
            validation_head=_head(_run(head=CURRENT, status=FAILED)),
            validation_failure=_failure(pr_head_sha=OLD),
        )
    )
    assert record.mutation_admissible is False
    assert record.next_action == "reacquire-current-head-validation-evidence"
    assert "validation-failure-evidence-bound-to-non-current-head" in record.reason_codes


def test_record_stays_non_authorizing_with_both_owners_composed() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(
            validation_head=_head(_run(head=CURRENT, status=FAILED)),
            validation_failure=_failure(),
        )
    )
    assert record.github_writes_authorized is False
    assert record.workflow_authorized is False
    assert record.merge_authorized is False
    assert record.issue_closure_authorized is False


# --------------------------------------------------------------------------
# Regressions: existing owners keep their behavior and precedence
# --------------------------------------------------------------------------


def test_review_blocked_state_still_blocks_with_validation_evidence_present() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(
            review_state="blocking-thread",
            validation_head=_head(_run(head=CURRENT, status=FAILED)),
            validation_failure=_failure(),
        )
    )
    assert record.mutation_admissible is False
    assert record.next_action == "resolve-or-reacquire-review-state"


def test_stale_head_takes_precedence_over_diagnostic_surface_blocker() -> None:
    from agent_os_execution_service.failed_repair_admission import DiagnosticSurfaceEvidence

    record = evaluate_failed_repair_admission(
        **_kwargs(
            validation_head=_head(_run(head=OLD, status=SUCCEEDED)),
            diagnostics=DiagnosticSurfaceEvidence(
                diagnostics_actionable=False,
                authorized_surfaces=("a",),
                attempted_surfaces=("a",),
            ),
        )
    )
    assert record.next_action == "reacquire-current-head-validation-evidence"
    assert record.diagnostic_blocker is not None  # still reported, not dropped


def test_diagnostic_surface_exhaustion_still_blocks_3280() -> None:
    from agent_os_execution_service.failed_repair_admission import DiagnosticSurfaceEvidence

    record = evaluate_failed_repair_admission(
        **_kwargs(
            diagnostics=DiagnosticSurfaceEvidence(
                diagnostics_actionable=False,
                authorized_surfaces=("a", "b"),
                attempted_surfaces=("a", "b"),
            )
        )
    )
    assert record.next_action == "blocked-diagnostic-surface"
    assert record.diagnostic_blocker is not None
    assert record.diagnostic_blocker.clearing_condition


def test_zero_job_recovery_still_wins_over_validation_owners_3277() -> None:
    from scripts.agent_os_issue_acceptance.zero_job_validation_recovery import (
        WorkflowRunConclusionEvidence as Run,
        ZeroJobAdmissionEvidence,
    )

    record = evaluate_failed_repair_admission(
        **_kwargs(
            zero_job=ZeroJobAdmissionEvidence(
                workflow_runs=(Run(1, "action_required", 0),),
                pull_request_number=3280,
                expected_head_sha=CURRENT,
                current_head_sha=CURRENT,
            ),
            validation_head=_head(_run(head=OLD, status=SUCCEEDED)),
        )
    )
    assert record.next_action == "reinvoke-governed-exact-head-validation"
    assert record.bounded_continuation_admitted is True


def test_recovery_progress_still_gates_2281() -> None:
    from workflow_scheduler.execution.recovery_progress import RecoverySemanticEvidence

    fields = {f.name for f in dataclasses.fields(RecoverySemanticEvidence)}
    assert fields  # the #2281 evidence type remains importable on this path
    assert "classify_recovery_progress" in inspect.getsource(admission_module)


# --------------------------------------------------------------------------
# Production reachability through the registered MCP surface
# --------------------------------------------------------------------------


def test_facade_continuation_blocks_stale_evidence() -> None:
    payload = admit_agent_os_failed_repair(
        **_kwargs(validation_head=_head(_run(head=OLD, status=SUCCEEDED)))
    )
    assert payload["agent_os_continuation"]["blocked"] is True
    assert payload["agent_os_continuation"]["action"] == ""
    assert payload["next_action"] == "reacquire-current-head-validation-evidence"
    assert payload["mutation_admissible"] is False


def test_registered_tool_function_reaches_both_owners() -> None:
    parameters = inspect.signature(admit_agent_os_failed_repair_tool).parameters
    assert "validation_head" in parameters and "validation_failure" in parameters
    payload = admit_agent_os_failed_repair_tool(
        **_kwargs(
            validation_head=_head(_run(head=CURRENT, status=FAILED)),
            validation_failure=_failure(),
        )
    )
    assert payload["validation_head_disposition"] == "failed"
    assert payload["validation_failure_classification"] == "pr_regression"
    assert payload["validation_repair_ladder"] == LADDER


def _call_registered_tool(arguments: dict[str, object]) -> dict[str, object]:
    result = asyncio.run(
        mcp_server.mcp.call_tool("admit_agent_os_failed_repair_tool", arguments)
    )
    contents = result.content if hasattr(result, "content") else result[0]
    return json.loads(contents[0].text)


def _json_head(head: str, status: str, **overrides) -> dict[str, object]:
    value: dict[str, object] = {
        "current_head_sha": CURRENT,
        "observed_at": OBSERVED,
        "evidence_current": True,
        "prior_run": {
            "run_id": "run-1",
            "validation_lane": "aggregate",
            "concurrency_group": "pr-3280",
            "head_sha": head,
            "phase": "terminal",
            "lifecycle_result": {
                "schema_version": VALIDATION_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
                "bundle_id": "bundle:fixture",
                "request_id": "request:fixture",
                "status": status,
                "reason_codes": ["fixture"],
                "execution_authorized": False,
                "side_effects_performed": False,
                "evaluated_at": OBSERVED,
            },
        },
    }
    value.update(overrides)
    return value


def _json_arguments(**extra) -> dict[str, object]:
    arguments: dict[str, object] = {
        "activation_result": _activation(),
        "check_state": "red",
        "required_check_configuration_state": "current",
        "review_state": "clear",
        "branch_freshness": "current",
        "mergeability": "mergeable",
    }
    arguments.update(extra)
    return arguments


def test_registered_server_advertises_both_inputs() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    tool = next(t for t in tools if t.name == "admit_agent_os_failed_repair_tool")
    assert "validation_head" in tool.input_schema["properties"]
    assert "validation_failure" in tool.input_schema["properties"]


def test_registered_server_stale_head_requires_current_head_reacquisition() -> None:
    payload = _call_registered_tool(
        _json_arguments(validation_head=_json_head(OLD, SUCCEEDED.value))
    )
    assert payload["validation_head_disposition"] == "stale-head"
    assert payload["mutation_admissible"] is False
    assert payload["next_action"] == "reacquire-current-head-validation-evidence"
    assert payload["agent_os_continuation"]["blocked"] is True


def test_registered_server_current_head_failure_continues() -> None:
    payload = _call_registered_tool(
        _json_arguments(validation_head=_json_head(CURRENT, FAILED.value))
    )
    assert payload["validation_head_disposition"] == "failed"
    assert payload["mutation_admissible"] is True


def test_registered_server_pr_regression_returns_the_ladder() -> None:
    payload = _call_registered_tool(
        _json_arguments(
            validation_failure={
                "pr_head_sha": CURRENT,
                "comparison_main_sha": MAIN,
                "command": "python3 -m pytest",
                "failed_requirement": "tests/test_x.py::test_y",
                "error_excerpt": "AssertionError",
                "exit_code": 1,
                "source_identifiers": ["run-1"],
                "evidence_state": "current",
                "comparable_pr_and_main": True,
                "same_requirement_executed": True,
                "pr_requirement_result": "fail",
                "main_requirement_result": "pass",
                "pr_scope_attribution_supported": True,
            }
        )
    )
    assert payload["validation_failure_classification"] == "pr_regression"
    assert payload["validation_repair_ladder"] == LADDER
    assert payload["mutation_admissible"] is True


def test_registered_server_inherited_main_failure_blocks() -> None:
    payload = _call_registered_tool(
        _json_arguments(
            validation_failure={
                "pr_head_sha": CURRENT,
                "comparison_main_sha": MAIN,
                "command": "python3 -m pytest",
                "failed_requirement": "tests/test_x.py::test_y",
                "error_excerpt": None,
                "exit_code": None,
                "evidence_state": "current",
                "comparable_pr_and_main": True,
                "same_requirement_executed": True,
                "pr_requirement_result": "fail",
                "main_requirement_result": "fail",
                "materially_equivalent_failure": True,
            }
        )
    )
    assert payload["validation_failure_classification"] == "inherited_main_failure"
    assert payload["next_action"] == "report-inherited-main-failure-blocker"
    assert payload["mutation_admissible"] is False


def test_failed_repair_admission_is_a_non_test_consumer_of_both_owners() -> None:
    source = pathlib.Path(
        inspect.getsourcefile(evaluate_failed_repair_admission)
    ).read_text(encoding="utf-8")
    assert "project_validation_head_disposition" in source
    assert "classify_validation_failure" in source
    assert "batch_merge_execution" not in source
