"""Focused differential mutation controls for failed-repair admission records.

These are pure evaluator tests; they do not authorize, initiate, or simulate
any external GitHub/Notion mutation. The facade already separately tests
required request IDs. Here we defend the pure evaluator's optional-vs-explicit
ID contract and preserve the canonical admission receipt fields.
"""
from __future__ import annotations

import pytest

from agent_os_execution_service.failed_repair_admission import (
    evaluate_failed_repair_admission,
)


def _evaluate(*, requested_id="attempt-41", outcome="consumed", lesson_ids=("LL-61", "LL-80")):
    return evaluate_failed_repair_admission(
        activation_result={
            "attempt_id": "attempt-41",
            "retry_reentry_outcome": outcome,
            "selected_lesson_ids": list(lesson_ids),
            "mutation_admissible": True,
        },
        failed_repair_attempt_id=requested_id,
        check_state="red",
        required_check_configuration_state="current",
        review_state="clear",
        branch_freshness="current",
        mergeability="mergeable",
    )


@pytest.mark.parametrize("invalid", ["", "   ", 17, True, ["attempt-41"]])
def test_explicit_attempt_id_requires_builtin_nonblank_text(invalid):
    """Differentiates x_evaluate_failed_repair_admission__mutmut_11."""
    with pytest.raises(ValueError, match="failed_repair_attempt_id"):
        _evaluate(requested_id=invalid)


def test_none_attempt_id_is_optional_only_in_the_pure_evaluator():
    """The pure evaluator permits None; the MCP facade separately requires an ID."""
    record = _evaluate(requested_id=None)
    assert record.attempt_id == "attempt-41"
    assert record.mutation_admissible is True
    assert record.next_action == "continue-authorized-repair-mutation"


def test_consumed_receipt_preserves_original_attempt_outcome_and_lesson_ids():
    """Differentiates receipt-loss mutants #28, #33, #338, and #340."""
    record = _evaluate()
    assert record.mutation_admissible is True
    assert record.attempt_id == "attempt-41"
    assert record.retry_reentry_outcome == "consumed"
    assert record.selected_lesson_ids == ("LL-61", "LL-80")
    assert record.reason_codes == ("retry-lessons-and-diagnostics-converged",)


def test_mismatched_attempt_remains_blocked_and_preserves_activation_id():
    record = _evaluate(requested_id="attempt-42")
    assert record.mutation_admissible is False
    assert record.attempt_id == "attempt-41"
    assert "retry-outcome-bound-to-different-attempt" in record.reason_codes
    assert record.next_action == "reenter-ckr6-for-exact-failed-attempt"


def test_not_material_receipt_preserves_canonical_outcome_and_empty_lessons():
    record = _evaluate(outcome="not-material", lesson_ids=())
    assert record.mutation_admissible is True
    assert record.retry_reentry_outcome == "not-material"
    assert record.selected_lesson_ids == ()
