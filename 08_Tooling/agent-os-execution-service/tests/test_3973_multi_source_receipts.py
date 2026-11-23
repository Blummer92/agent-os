"""#3973: CKR7 receipts -- one lesson, two independent PRs, verifiable use.

A single lesson selected in two independent PRs yields two verifiable,
revision-bound application receipts (lesson ID + exact source revision +
trusted CKR6 result comment + task ref). Missing, forged, or skipped
receipts never count as applied. No automatic Notion Usage Count write
exists anywhere on this path: usage is derived only from verified GitHub
receipts, and the code contains no Usage Count write path at all.

The lesson under test is LL-73 at the #3973 seed revision. PR #2077
(merged, `Fixes #2064`) is supporting repair evidence for LL-73's claim,
NOT an applied-lesson receipt: no receipt exists for it, and this file
asserts exactly that distinction -- a fix existing is not proof of use.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge
from agent_os_execution_service import lesson_learning_loop as loop
from agent_os_execution_service.lesson_learning_metrics import derive_lesson_metrics

REVISION = "2026-09-07T23:11:07.594Z"
LESSON = "LL-73"
PR_A = "https://github.com/Blummer92/agent-os/pull/3971"
PR_B = "https://github.com/Blummer92/agent-os/pull/2077"
ISSUE_ORIGIN = "https://github.com/Blummer92/agent-os/issues/2064"


def receipt(**changes):
    value = {
        "ckr6_result_comment_id": 501,
        "lesson_id": LESSON,
        "source_revision": REVISION,
        "task_ref": PR_A,
        "disposition": "applied",
        "reason_code": "guided-decision",
        "decision": "Reconciled eligible existing bugs before discovering new ones.",
        "outcome_ref": None,
    }
    value.update(changes)
    return value


def sufficient_result(issue_number, lessons=((LESSON, REVISION),)):
    return {
        "operation": "issue-start",
        "repository": "Blummer92/agent-os",
        "issue_number": issue_number,
        "status": "sufficient",
        "reason_codes": ["knowledge-sufficient"],
        "selected_lesson_ids": [lesson for lesson, _ in lessons],
        "selected_lessons": [
            {"lesson_id": lesson, "source_revision": rev, "selection_reason_codes": ["x"]}
            for lesson, rev in lessons
        ],
        "canonical_github_refs": [ISSUE_ORIGIN],
        "substantial_hypothesis_admissible": True,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
        "mutation_admissible": False,
    }


def _comment(comment_id, body):
    return {"id": comment_id, "body": body}


def test_one_lesson_two_independent_prs_yields_two_verifiable_receipts():
    result_a = bridge.serialize_ckr6_result_comment(sufficient_result(3971), request_comment_id=500)
    result_b = bridge.serialize_ckr6_result_comment(sufficient_result(2077), request_comment_id=600)
    comments = {
        3971: [
            _comment(501, result_a),
            _comment(502, loop.serialize_receipt_comment(receipt())),
        ],
        2077: [
            _comment(601, result_b),
            _comment(
                602,
                loop.serialize_receipt_comment(
                    receipt(
                        ckr6_result_comment_id=601,
                        task_ref=PR_B,
                        reason_code="prevented-known-failure",
                    )
                ),
            ),
        ],
    }
    metrics = derive_lesson_metrics(comments)
    assert metrics["receipts"]["valid"] == 2
    assert metrics["receipts"]["applied"] == {
        "guided-decision": 1,
        "prevented-known-failure": 1,
    }
    assert metrics["receipts"]["invalid"] == {}
    assert metrics["selected_without_receipt"] == []
    assert metrics["lessons_selected"] == 1


def test_missing_receipt_never_counts_as_applied():
    result_a = bridge.serialize_ckr6_result_comment(sufficient_result(3971), request_comment_id=500)
    metrics = derive_lesson_metrics({3971: [_comment(501, result_a)]})
    assert metrics["receipts"]["valid"] == 0
    assert metrics["receipts"]["applied"] == {}
    assert metrics["selected_without_receipt"] == [f"{LESSON}@{REVISION}"]


def test_forged_receipts_never_count_as_applied():
    result_a = bridge.serialize_ckr6_result_comment(sufficient_result(3971), request_comment_id=500)
    forged_wrong_lesson = receipt(lesson_id="LL-64")
    forged_wrong_revision = receipt(source_revision="2026-01-01T00:00:00.000Z")
    forged_unknown_result = receipt(ckr6_result_comment_id=999, task_ref=PR_B)
    comments = {
        3971: [
            _comment(501, result_a),
            _comment(502, loop.serialize_receipt_comment(forged_wrong_lesson)),
            _comment(503, loop.serialize_receipt_comment(forged_wrong_revision)),
            _comment(504, loop.serialize_receipt_comment(forged_unknown_result)),
            _comment(505, "<!-- agent-os-lesson-receipt:v1 -->\n{broken"),
        ]
    }
    metrics = derive_lesson_metrics(comments)
    assert metrics["receipts"]["valid"] == 0
    assert metrics["receipts"]["applied"] == {}
    assert metrics["receipts"]["invalid"] == {
        "receipt-lesson-not-returned-by-ckr6": 2,
        "receipt-result-not-found": 1,
    }
    assert metrics["malformed_markers"] == {"receipt": 1}
    assert metrics["selected_without_receipt"] == [f"{LESSON}@{REVISION}"]


def test_skipped_receipt_never_counts_as_applied():
    result_a = bridge.serialize_ckr6_result_comment(sufficient_result(3971), request_comment_id=500)
    comments = {
        3971: [
            _comment(501, result_a),
            _comment(
                502,
                loop.serialize_receipt_comment(
                    receipt(disposition="skipped", reason_code="not-relevant-to-task")
                ),
            ),
        ]
    }
    metrics = derive_lesson_metrics(comments)
    assert metrics["receipts"]["valid"] == 1
    assert metrics["receipts"]["applied"] == {}
    assert metrics["receipts"]["skipped"] == {"not-relevant-to-task": 1}
    assert metrics["selected_without_receipt"] == []


def test_a_fix_existing_is_not_proof_of_use():
    # PR #2077 merged with `Fixes #2064`, but no lesson-use receipt binds
    # LL-73 at any revision to that PR. The metrics derivation must report
    # the lesson as selected-without-receipt, never as applied.
    result_b = bridge.serialize_ckr6_result_comment(sufficient_result(2077), request_comment_id=600)
    metrics = derive_lesson_metrics({2077: [_comment(601, result_b)]})
    assert metrics["receipts"]["applied"] == {}
    assert metrics["selected_without_receipt"] == [f"{LESSON}@{REVISION}"]


def test_no_automatic_notion_usage_count_write_path_exists():
    # Usage is derived only from verified GitHub receipts. No source file
    # on this path may name a Notion Usage Count write, and the derived
    # metrics carry no usage-count field.
    repo = Path(__file__).resolve().parents[1]
    for relative in (
        "src/agent_os_execution_service/lesson_learning_loop.py",
        "src/agent_os_execution_service/lesson_learning_metrics.py",
        "src/agent_os_execution_service/ckr6_github_bridge.py",
    ):
        assert "Usage Count" not in (repo / relative).read_text(encoding="utf-8"), relative
    metrics = derive_lesson_metrics({})
    assert "usage_count" not in metrics
    assert "Usage Count" not in str(metrics)
