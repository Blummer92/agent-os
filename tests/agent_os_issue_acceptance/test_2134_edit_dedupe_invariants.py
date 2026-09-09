"""Adversarial dedupe invariants for the #2134 acceptance-edit self-loop repair.

The original defect was a self-loop: the acceptance report wrote exact-head evidence
into the PR body, the resulting ``edited`` event re-triggered the report on the same
unchanged head, and that run wrote evidence again.  Merged PR #2198 removed the
redundant ``ready_for_review`` trigger, and the relevance classifier closes the
remaining ``edited`` path.

Suppressing one hand-written fixture is not the contract.  The loop only stays closed
if normalization is idempotent and stable under repetition, so these tests exercise
repeated runs, retries, stale bodies, partially-written evidence, and mixed edits.
"""

from __future__ import annotations

import pytest

from scripts.agent_os_issue_acceptance.edit_relevance import (
    classify_acceptance_event,
    normalize_acceptance_pr_body,
)

EVIDENCE = "Exact-head `Agent OS Issue Acceptance Report`: **pass** on `abc1234`."
LATER_EVIDENCE = "Exact-head `Agent OS Issue Acceptance Report`: **pass** on `def5678`."
BODY = "## Summary\n\nCloses #2134.\n\n- a bullet\n"


def _edit(old_body: str, new_body: str) -> dict:
    return {
        "action": "edited",
        "changes": {"body": {"from": old_body}},
        "pull_request": {"body": new_body},
    }


def test_normalization_is_idempotent():
    """A non-idempotent normalizer would let the second write look meaningful."""
    once = normalize_acceptance_pr_body(f"{BODY}\n{EVIDENCE}\n")
    assert normalize_acceptance_pr_body(once) == once


def test_repeated_evidence_rewrite_stays_suppressed_across_sequential_runs():
    """Multiple sequential report runs on the same head must never re-trigger."""
    body = BODY
    for evidence in (EVIDENCE, LATER_EVIDENCE, EVIDENCE):
        updated = f"{body}\n{evidence}\n"
        reportable, reason = classify_acceptance_event(_edit(body, updated))
        assert reportable is False, reason
        assert reason == "acceptance-evidence-only-body-edit"
        body = updated


def test_identical_retry_of_the_same_edit_is_deterministic():
    """A redelivered webhook must classify identically, not flip to reportable."""
    event = _edit(BODY, f"{BODY}\n{EVIDENCE}\n")
    first = classify_acceptance_event(event)
    second = classify_acceptance_event(event)
    assert first == second == (False, "acceptance-evidence-only-body-edit")


def test_evidence_removal_is_also_suppressed():
    """Rollback of an evidence line changes no consumed acceptance input."""
    reportable, reason = classify_acceptance_event(
        _edit(f"{BODY}\n{EVIDENCE}\n", BODY)
    )
    assert reportable is False
    assert reason == "acceptance-evidence-only-body-edit"


def test_evidence_line_position_does_not_change_the_decision():
    """Stale bodies place evidence differently; suppression must not depend on order."""
    reportable, _ = classify_acceptance_event(
        _edit(f"{EVIDENCE}\n\n{BODY}", f"{BODY}\n{EVIDENCE}\n")
    )
    assert reportable is False


@pytest.mark.parametrize(
    "meaningful",
    [
        f"{BODY}\n{EVIDENCE}\nCloses #9999 as well.\n",
        f"{BODY.replace('a bullet', 'a different bullet')}\n{EVIDENCE}\n",
    ],
    ids=["added-line", "changed-line"],
)
def test_meaningful_change_alongside_evidence_still_reports(meaningful):
    """Suppression must never swallow a real acceptance-input change."""
    reportable, reason = classify_acceptance_event(_edit(BODY, meaningful))
    assert reportable is True
    assert reason == "body-input-changed"


def test_partially_written_evidence_line_is_treated_as_a_real_change():
    """A truncated write is not canonical evidence and must fail open to reporting."""
    truncated = "Exact-head `Agent OS Issue Acceptance Report`: **pass**"
    reportable, _ = classify_acceptance_event(_edit(BODY, f"{BODY}\n{truncated}\n"))
    assert reportable is True


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "edited", "changes": {"body": {}}, "pull_request": {"body": BODY}},
        {"action": "edited", "changes": {"body": {"from": None}}, "pull_request": {"body": None}},
        {"action": "edited", "changes": {"body": {"from": BODY}}, "pull_request": {}},
    ],
    ids=["no-from", "null-bodies", "no-pull-request"],
)
def test_missing_or_null_edit_evidence_never_crashes(payload):
    """Ambiguity must resolve to a decision, not an exception that breaks the gate."""
    reportable, reason = classify_acceptance_event(payload)
    assert isinstance(reportable, bool) and reason


@pytest.mark.parametrize(
    "action", ["opened", "reopened", "synchronize", "ready_for_review"]
)
def test_non_edited_actions_are_never_suppressed(action):
    """The classifier only dedupes `edited`; it must not gate real head changes."""
    reportable, reason = classify_acceptance_event({"action": action})
    assert reportable is True
    assert reason == "non-edited-event"


def test_title_and_base_edits_are_never_suppressed_by_evidence_normalization():
    """Evidence-only body text must not mask a concurrent title or base change."""
    for field in ("title", "base"):
        payload = {
            "action": "edited",
            "changes": {field: {"from": "old"}, "body": {"from": BODY}},
            "pull_request": {"body": f"{BODY}\n{EVIDENCE}\n"},
        }
        reportable, _ = classify_acceptance_event(payload)
        assert reportable is True, field
