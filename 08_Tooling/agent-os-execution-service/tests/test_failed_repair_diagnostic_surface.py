"""Diagnostic-surface exhaustion on the live failed-repair path (#3280).

The orchestrator overlay's bounded alternate-diagnosis rule is executable on the
live chain ``admit_agent_os_failed_repair_tool`` -> ``admit_agent_os_failed_repair``
-> ``evaluate_failed_repair_admission``:

- insufficient diagnostics + an unused already-authorized surface -> continue
  through that one bounded alternative;
- every distinct authorized surface attempted -> exactly one explicit
  ``BLOCKED_DIAGNOSTIC_SURFACE`` blocker naming the evidence that could not be
  obtained and its clearing condition.

The bound is exhaustion of a finite set of distinct surfaces, never a generic
retry counter, and it stays separate from #2281's semantic recovery progress.
"""
from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from agent_os_execution_service import mcp_server
from agent_os_execution_service.failed_repair_admission import (
    DiagnosticSurfaceEvidence,
    evaluate_failed_repair_admission,
)
from agent_os_execution_service.mcp_facade import admit_agent_os_failed_repair
from agent_os_execution_service.mcp_server import admit_agent_os_failed_repair_tool

ACTIONS = "github-actions-run-logs"
ANNOTATIONS = "check-run-annotations"
STATUS = "commit-status-description"


def _activation(**overrides) -> dict[str, object]:
    values: dict[str, object] = {
        "attempt_id": "attempt-3280",
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


def _diag(actionable=False, authorized=(ACTIONS, ANNOTATIONS), attempted=()):
    return DiagnosticSurfaceEvidence(
        diagnostics_actionable=actionable,
        authorized_surfaces=tuple(authorized),
        attempted_surfaces=tuple(attempted),
    )


def test_unused_authorized_alternate_surface_is_admitted() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(diagnostics=_diag(attempted=(ACTIONS,)))
    )
    assert record.next_diagnostic_surface == ANNOTATIONS
    assert record.next_action == "diagnose-via-authorized-alternate-surface"
    assert record.bounded_continuation_admitted is True
    assert record.mutation_admissible is False
    assert record.diagnostic_blocker is None
    assert "diagnostic-evidence-insufficient-alternate-surface-available" in record.reason_codes


def test_first_authorized_surface_is_chosen_in_declared_order() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(diagnostics=_diag(authorized=(ACTIONS, ANNOTATIONS, STATUS)))
    )
    assert record.next_diagnostic_surface == ACTIONS


def test_same_surface_cannot_count_twice() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(
            diagnostics=_diag(
                authorized=(ACTIONS, ANNOTATIONS),
                attempted=(ACTIONS, ACTIONS, ACTIONS),
            )
        )
    )
    # Three reports of one surface is still one surface: the alternative remains.
    assert record.next_diagnostic_surface == ANNOTATIONS
    assert record.diagnostic_blocker is None


def test_duplicate_authorized_entries_are_one_surface() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(
            diagnostics=_diag(
                authorized=(ACTIONS, ACTIONS), attempted=(ACTIONS,)
            )
        )
    )
    assert record.diagnostic_blocker is not None
    assert record.diagnostic_blocker.attempted_surfaces == (ACTIONS,)


def test_exhaustion_returns_one_explicit_blocker_with_clearing_condition() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(diagnostics=_diag(attempted=(ACTIONS, ANNOTATIONS)))
    )
    assert record.mutation_admissible is False
    assert record.bounded_continuation_admitted is False
    assert record.next_action == "blocked-diagnostic-surface"
    assert record.next_diagnostic_surface is None
    assert "diagnostic-surface-exhausted" in record.reason_codes
    blocker = record.diagnostic_blocker
    assert blocker is not None
    assert blocker.kind == "BLOCKED_DIAGNOSTIC_SURFACE"
    assert blocker.attempted_surfaces == (ACTIONS, ANNOTATIONS)
    assert "actionable failure diagnostics" in blocker.missing_evidence
    assert ACTIONS in blocker.missing_evidence and ANNOTATIONS in blocker.missing_evidence
    assert blocker.clearing_condition.strip()
    assert "already-authorized" in blocker.clearing_condition


def test_exhaustion_is_one_blocker_not_a_repeating_continuation() -> None:
    first = evaluate_failed_repair_admission(
        **_kwargs(diagnostics=_diag(attempted=(ACTIONS, ANNOTATIONS)))
    )
    again = evaluate_failed_repair_admission(
        **_kwargs(diagnostics=_diag(attempted=(ACTIONS, ANNOTATIONS, ANNOTATIONS, ACTIONS)))
    )
    assert first.diagnostic_blocker == again.diagnostic_blocker
    assert again.bounded_continuation_admitted is False
    assert again.reason_codes.count("diagnostic-surface-exhausted") == 1


def test_unauthorized_attempted_surface_neither_counts_nor_creates_continuation() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(
            diagnostics=_diag(
                authorized=(ACTIONS,), attempted=(ACTIONS, "unauthorized-side-channel")
            )
        )
    )
    assert record.diagnostic_blocker is not None
    assert record.diagnostic_blocker.attempted_surfaces == (ACTIONS,)
    assert "unauthorized-side-channel" not in record.diagnostic_blocker.missing_evidence


def test_no_authorized_surface_is_an_immediate_explicit_blocker() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(diagnostics=_diag(authorized=(), attempted=()))
    )
    assert record.diagnostic_blocker is not None
    assert record.diagnostic_blocker.attempted_surfaces == ()
    assert "no authorized diagnostic surface is available" in record.diagnostic_blocker.missing_evidence
    assert record.bounded_continuation_admitted is False


def test_attempts_are_bounded_by_the_finite_authorized_set() -> None:
    """Walking every surface one at a time always terminates in the blocker."""
    authorized = (ACTIONS, ANNOTATIONS, STATUS)
    attempted: tuple[str, ...] = ()
    steps = 0
    while True:
        record = evaluate_failed_repair_admission(
            **_kwargs(diagnostics=_diag(authorized=authorized, attempted=attempted))
        )
        if record.diagnostic_blocker is not None:
            break
        assert record.next_diagnostic_surface is not None
        assert record.next_diagnostic_surface not in attempted
        attempted += (record.next_diagnostic_surface,)
        steps += 1
        assert steps <= len(authorized)
    assert steps == len(authorized)


def test_actionable_diagnostics_add_no_gating() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(diagnostics=_diag(actionable=True, attempted=(ACTIONS, ANNOTATIONS)))
    )
    assert record.mutation_admissible is True
    assert record.next_action == "continue-authorized-repair-mutation"
    assert record.diagnostic_blocker is None
    assert record.next_diagnostic_surface is None


def test_omitted_diagnostics_leave_admission_unchanged() -> None:
    record = evaluate_failed_repair_admission(**_kwargs())
    assert record.mutation_admissible is True
    assert record.diagnostic_blocker is None
    assert record.next_diagnostic_surface is None


def test_diagnostic_gating_precedes_ckr6_reentry_but_not_the_zero_job_projection() -> None:
    unconsumed = _activation(retry_reentry_outcome="not-material", mutation_admissible=False)
    record = evaluate_failed_repair_admission(
        **_kwargs(activation_result=unconsumed, diagnostics=_diag(attempted=(ACTIONS,)))
    )
    # Increasing diagnostic resolution comes first in the failed-repair standard.
    assert record.next_action == "diagnose-via-authorized-alternate-surface"
    assert "retry-specific-lessons-not-consumed" in record.reason_codes


def test_semantic_progress_and_diagnostic_exhaustion_stay_separate_concepts() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(diagnostics=_diag(attempted=(ACTIONS, ANNOTATIONS)))
    )
    assert record.recovery_stalled is False
    assert not any(code.startswith("recovery-") for code in record.reason_codes)


def test_record_remains_non_authorizing_with_a_blocker() -> None:
    record = evaluate_failed_repair_admission(
        **_kwargs(diagnostics=_diag(attempted=(ACTIONS, ANNOTATIONS)))
    )
    assert record.github_writes_authorized is False
    assert record.workflow_authorized is False
    assert record.merge_authorized is False
    assert record.issue_closure_authorized is False


@pytest.mark.parametrize(
    "bad",
    [
        dict(diagnostics_actionable="no"),
        dict(diagnostics_actionable=False, authorized_surfaces=[ACTIONS]),
        dict(diagnostics_actionable=False, attempted_surfaces=("",)),
        dict(diagnostics_actionable=False, authorized_surfaces=(1,)),
    ],
)
def test_malformed_diagnostic_evidence_is_rejected(bad) -> None:
    with pytest.raises(TypeError):
        DiagnosticSurfaceEvidence(**bad)


def test_facade_continuation_carries_alternate_surface_unblocked() -> None:
    payload = admit_agent_os_failed_repair(
        **_kwargs(diagnostics=_diag(attempted=(ACTIONS,)))
    )
    continuation = payload["agent_os_continuation"]
    assert continuation["action"] == "diagnose-via-authorized-alternate-surface"
    assert continuation["blocked"] is False
    assert payload["next_diagnostic_surface"] == ANNOTATIONS
    assert continuation["github_writes_authorized"] is False


def test_facade_continuation_is_blocked_with_the_blocker_on_exhaustion() -> None:
    payload = admit_agent_os_failed_repair(
        **_kwargs(diagnostics=_diag(attempted=(ACTIONS, ANNOTATIONS)))
    )
    assert payload["agent_os_continuation"]["blocked"] is True
    assert payload["agent_os_continuation"]["action"] == ""
    assert payload["diagnostic_blocker"]["kind"] == "BLOCKED_DIAGNOSTIC_SURFACE"
    assert payload["diagnostic_blocker"]["clearing_condition"]


def test_registered_mcp_tool_function_reaches_the_exhaustion_invariant() -> None:
    payload = admit_agent_os_failed_repair_tool(
        **_kwargs(diagnostics=_diag(attempted=(ACTIONS, ANNOTATIONS)))
    )
    assert payload["next_action"] == "blocked-diagnostic-surface"
    assert "diagnostics" in inspect.signature(admit_agent_os_failed_repair_tool).parameters


def _call_registered_tool(arguments: dict[str, object]) -> dict[str, object]:
    result = asyncio.run(
        mcp_server.mcp.call_tool("admit_agent_os_failed_repair_tool", arguments)
    )
    contents = result.content if hasattr(result, "content") else result[0]
    return json.loads(contents[0].text)


def _json_arguments(attempted: list[str]) -> dict[str, object]:
    return {
        "activation_result": _activation(),
        "check_state": "red",
        "required_check_configuration_state": "current",
        "review_state": "clear",
        "branch_freshness": "current",
        "mergeability": "mergeable",
        "diagnostics": {
            "diagnostics_actionable": False,
            "authorized_surfaces": [ACTIONS, ANNOTATIONS],
            "attempted_surfaces": attempted,
        },
    }


def test_registered_mcp_server_advertises_the_diagnostics_input() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    tool = next(t for t in tools if t.name == "admit_agent_os_failed_repair_tool")
    assert "diagnostics" in tool.input_schema["properties"]


def test_registered_mcp_server_admits_the_alternate_surface() -> None:
    payload = _call_registered_tool(_json_arguments([ACTIONS]))
    assert payload["next_diagnostic_surface"] == ANNOTATIONS
    assert payload["agent_os_continuation"]["blocked"] is False
    assert payload["diagnostic_blocker"] is None


def test_registered_mcp_server_returns_the_explicit_blocker_on_exhaustion() -> None:
    payload = _call_registered_tool(_json_arguments([ACTIONS, ANNOTATIONS, ACTIONS]))
    assert payload["agent_os_continuation"]["blocked"] is True
    blocker = payload["diagnostic_blocker"]
    assert blocker["kind"] == "BLOCKED_DIAGNOSTIC_SURFACE"
    assert blocker["missing_evidence"]
    assert blocker["clearing_condition"]
    assert payload["reason_codes"].count("diagnostic-surface-exhausted") == 1
