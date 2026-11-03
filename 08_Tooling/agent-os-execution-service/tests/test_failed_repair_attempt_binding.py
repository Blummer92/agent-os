"""CKR6 failed-repair admission: exact-attempt binding and producer-shaped outcomes.

November 3 mutation evidence (B1-B6, CK1-CK3). These tests drive the real
activation producer (``activate_agent_os_failed_repair``) into the real
admission consumer (``admit_agent_os_failed_repair``) so the admission verdict is
checked against what the producer actually emits, not a hand-built dict.

Single-fault cases: every case changes exactly one input and asserts the exact
reason code, so removing a guard fails the named case (LL-10/LL-93 discipline).
"""
from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from agent_os_execution_service.mcp_facade import (
    activate_agent_os_failed_repair,
    admit_agent_os_failed_repair,
)

LESSON_REVISION = "2026-10-08T12:00:00.000Z"
CONSUMED_NEXT = "continue-authorized-repair-mutation"
REENTER_NEXT = "reenter-ckr6-for-exact-failed-attempt"


def _rt(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text, "text": {"content": text}}]}


def _lesson_row(number=999):
    return {
        "object": "page",
        "last_edited_time": LESSON_REVISION,
        "url": f"https://www.notion.so/{number}",
        "properties": {
            "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": number}},
            "Lesson Learned": {"type": "title", "title": [{"plain_text": "Verify labels after issue creation"}]},
            "Status": {"type": "select", "select": {"name": "New"}},
            "Surface Before Work?": {"type": "checkbox", "checkbox": True},
            "Area": {"type": "select", "select": {"name": "Governance"}},
            "Learning Type": {"type": "select", "select": {"name": "Mistake"}},
            "Applies To": {"type": "multi_select", "multi_select": [{"name": "Notion"}]},
            "Source Link": {"type": "url", "url": "https://github.com/Blummer92/agent-os/issues/3305"},
            "Guardrail": _rt("Prove label convergence through readback."),
            "What To Do Next Time": _rt("Verify labels after creating a GitHub issue."),
            "What Happened": _rt("Some created issues lacked labels."),
        },
    }


def _reader(rows):
    calls = []

    def execute_read(query):
        calls.append(query)
        return {"results": list(rows), "has_more": False}

    execute_read.calls = calls
    return execute_read


def _activate(attempt_id, *, specialized, rows=None, reader=None):
    return activate_agent_os_failed_repair(
        repository="Blummer92/agent-os",
        issue_number=3418,
        attempt_id=attempt_id,
        failed_hypothesis=f"hypothesis-for-{attempt_id}",
        result_summary="focused tests stayed red",
        task_reference="issue:#3418",
        capability_keywords=("failure-avoidance",),
        known_knowledge_refs=("LL-999",) if specialized else (),
        specialized_knowledge_required=specialized,
        execute_read=reader if reader is not None else (_reader(rows) if rows is not None else None),
    )


def _admit(activation, *, attempt=None):
    return admit_agent_os_failed_repair(
        activation_result=activation,
        failed_repair_attempt_id=activation["attempt_id"] if attempt is None else attempt,
        check_state="red",
        required_check_configuration_state="current",
        review_state="clear",
        branch_freshness="current",
        mergeability="mergeable",
    )


# --------------------------------------------------------------------------
# Positive controls: what the real producer emits must be admitted (B1, B2).
# --------------------------------------------------------------------------
def test_b2_consumed_lessons_for_the_current_attempt_are_admitted():
    activation = _activate("attempt-1", specialized=True, rows=[_lesson_row()])
    assert activation["retry_reentry_outcome"] == "consumed"
    assert activation["mutation_admissible"] is True
    verdict = _admit(activation)
    assert verdict["mutation_admissible"] is True
    assert verdict["next_action"] == CONSUMED_NEXT
    assert verdict["agent_os_continuation"]["blocked"] is False


def test_b1_not_material_activation_from_the_real_producer_is_admitted():
    """The canonical boundary admits a not-material re-entry (standard step 3-4)."""
    activation = _activate("attempt-1", specialized=False)
    # Producer-shaped: this is what the activation seam really returns.
    assert activation["retry_reentry_outcome"] == "not-material"
    assert activation["mutation_admissible"] is True
    verdict = _admit(activation)
    assert verdict["mutation_admissible"] is True, verdict["reason_codes"]
    assert verdict["next_action"] == CONSUMED_NEXT
    assert "retry-specific-lessons-not-consumed" not in verdict["reason_codes"]
    assert verdict["agent_os_continuation"]["blocked"] is False


# --------------------------------------------------------------------------
# Negative controls: inadmissible re-entry stays blocked (B3, B4).
# --------------------------------------------------------------------------
def test_b3_material_lesson_with_unavailable_route_stays_blocked():
    activation = _activate("attempt-1", specialized=True, rows=None)
    assert activation["retry_reentry_outcome"] == "unavailable-or-failed"
    verdict = _admit(activation)
    assert verdict["mutation_admissible"] is False
    assert "retry-specific-lessons-not-consumed" in verdict["reason_codes"]
    assert verdict["next_action"] == REENTER_NEXT


def test_b4_material_lesson_with_no_relevant_candidate_stays_blocked():
    activation = _activate("attempt-1", specialized=True, rows=[])
    assert activation["retry_reentry_outcome"] == "unavailable-or-failed"
    verdict = _admit(activation)
    assert verdict["mutation_admissible"] is False
    assert "retry-specific-lessons-not-consumed" in verdict["reason_codes"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"retry_reentry_outcome": "unavailable-or-failed"},  # forged admissible flag
        {"retry_reentry_outcome": "something-else"},
        {"mutation_admissible": False},  # admitting outcome but boundary refused
    ],
)
def test_inconsistent_or_inadmissible_activation_is_blocked(overrides):
    activation = _activate("attempt-1", specialized=False)
    activation.update(overrides)
    verdict = _admit(activation)
    assert verdict["mutation_admissible"] is False
    assert "retry-specific-lessons-not-consumed" in verdict["reason_codes"]


def test_activation_without_a_recorded_outcome_is_malformed_and_fails_closed():
    activation = _activate("attempt-1", specialized=False)
    activation["retry_reentry_outcome"] = None
    with pytest.raises(ValueError, match="retry_reentry_outcome"):
        _admit(activation)


# --------------------------------------------------------------------------
# A2: exact failed-attempt binding (B5).
# --------------------------------------------------------------------------
def test_b5_activation_for_attempt_1_cannot_admit_a_repair_for_attempt_2():
    attempt_1 = _activate("attempt-1", specialized=True, rows=[_lesson_row()])
    assert attempt_1["mutation_admissible"] is True  # genuinely consumed for attempt 1
    verdict = _admit(attempt_1, attempt="attempt-2")
    assert verdict["mutation_admissible"] is False
    assert "retry-outcome-bound-to-different-attempt" in verdict["reason_codes"]
    assert verdict["next_action"] == REENTER_NEXT
    assert verdict["agent_os_continuation"]["blocked"] is True


def test_b5_stale_not_material_activation_is_equally_bound():
    stale = _activate("attempt-1", specialized=False)
    verdict = _admit(stale, attempt="attempt-2")
    assert verdict["mutation_admissible"] is False
    assert "retry-outcome-bound-to-different-attempt" in verdict["reason_codes"]


@pytest.mark.parametrize("missing", [None, "", "   ", 7])
def test_missing_or_malformed_current_attempt_identity_fails_closed(missing):
    activation = _activate("attempt-1", specialized=False)
    with pytest.raises((TypeError, ValueError)):
        admit_agent_os_failed_repair(
            activation_result=activation,
            failed_repair_attempt_id=missing,
            check_state="red",
            required_check_configuration_state="current",
            review_state="clear",
            branch_freshness="current",
            mergeability="mergeable",
        )


def test_current_attempt_identity_is_a_required_facade_argument():
    activation = _activate("attempt-1", specialized=False)
    with pytest.raises(TypeError):
        admit_agent_os_failed_repair(  # type: ignore[call-arg]
            activation_result=activation,
            check_state="red",
            required_check_configuration_state="current",
            review_state="clear",
            branch_freshness="current",
            mergeability="mergeable",
        )


def test_attempt_binding_is_exact_not_prefix_or_case_insensitive():
    activation = _activate("attempt-1", specialized=False)
    for near_miss in ("attempt-10", "attempt-", "ATTEMPT-1", "attempt-1 "):
        try:
            verdict = _admit(activation, attempt=near_miss)
        except ValueError:
            continue  # a canonical-text validator may reject first; also fail closed
        assert verdict["mutation_admissible"] is False, near_miss
        assert "retry-outcome-bound-to-different-attempt" in verdict["reason_codes"]


# --------------------------------------------------------------------------
# B6: reusing the current attempt's activation never re-retrieves lessons.
# --------------------------------------------------------------------------
def test_b6_admission_is_a_pure_function_of_the_held_activation_no_retrieval():
    reader = _reader([_lesson_row()])
    activation = _activate("attempt-1", specialized=True, reader=reader)
    assert len(reader.calls) == 1  # exactly one retrieval to produce the activation
    first = _admit(activation)
    second = _admit(activation)
    assert first == second
    assert len(reader.calls) == 1, "admission must reuse the held activation, not re-read lessons"


# --------------------------------------------------------------------------
# The registered MCP tool is the production entry point: the binding must hold
# there too, not only in the Python facade (AK7).
# --------------------------------------------------------------------------
def _tool_arguments(activation, attempt):
    return {
        "activation_result": activation,
        "failed_repair_attempt_id": attempt,
        "check_state": "red",
        "required_check_configuration_state": "current",
        "review_state": "clear",
        "branch_freshness": "current",
        "mergeability": "mergeable",
    }


def _call_registered_tool(arguments):
    import asyncio
    import json

    from agent_os_execution_service import mcp_server

    result = asyncio.run(mcp_server.mcp.call_tool("admit_agent_os_failed_repair_tool", arguments))
    contents = result.content if hasattr(result, "content") else result[0]
    return json.loads(contents[0].text)


def test_registered_mcp_tool_blocks_a_stale_attempt_activation():
    stale = _activate("attempt-1", specialized=True, rows=[_lesson_row()])
    payload = _call_registered_tool(_tool_arguments(stale, "attempt-2"))
    assert payload["mutation_admissible"] is False
    assert "retry-outcome-bound-to-different-attempt" in payload["reason_codes"]
    assert payload["agent_os_continuation"]["blocked"] is True


def test_registered_mcp_tool_admits_the_matching_attempt():
    current = _activate("attempt-2", specialized=False)
    payload = _call_registered_tool(_tool_arguments(current, "attempt-2"))
    assert payload["mutation_admissible"] is True
    assert payload["next_action"] == CONSUMED_NEXT


def test_registered_mcp_tool_requires_the_attempt_identity():
    from agent_os_execution_service import mcp_server

    current = _activate("attempt-2", specialized=False)
    arguments = _tool_arguments(current, "attempt-2")
    del arguments["failed_repair_attempt_id"]
    # Schema validation at the registered tool (ToolError wrapping the missing
    # argument), not an unrelated runtime failure.
    with pytest.raises(ToolError, match="failed_repair_attempt_id"):
        _call_registered_tool(arguments)
    import inspect

    parameter = inspect.signature(mcp_server.admit_agent_os_failed_repair_tool).parameters["failed_repair_attempt_id"]
    assert parameter.default is inspect.Parameter.empty
