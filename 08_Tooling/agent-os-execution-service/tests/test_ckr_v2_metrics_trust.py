"""CKR runtime v2 WP-F: learning metrics never count untrusted results or receipts.

Regression for the 2026-11-25 adversarial review (F9, E12 I5): derive_lesson_metrics counted a
marker-shaped result and an 'applied' receipt posted by any account. States stay distinct:
selected != delivered != reportedly applied != independently validated.
"""
from __future__ import annotations

from agent_os_execution_service import ckr6_github_bridge as bridge
from agent_os_execution_service import lesson_learning_loop as loop
from agent_os_execution_service.lesson_learning_metrics import derive_lesson_metrics

STAMP = "2026-11-25T12:00:00Z"
BOT = {"login": "github-actions[bot]", "id": 41898282, "type": "Bot"}
OWNER = {"login": "Blummer92", "id": 1, "type": "User"}
OUTSIDER = {"login": "random-outsider", "id": 7, "type": "User"}


def result_body():
    return bridge.serialize_ckr6_result_comment({
        "operation": "issue-start", "repository": "Blummer92/agent-os", "issue_number": 4026, "status": "sufficient",
        "reason_codes": ["knowledge-sufficient"], "selected_lesson_ids": ["LL-77"],
        "selected_lessons": [{"lesson_id": "LL-77", "source_revision": "2026-11-25T12:00:00.000Z",
                              "selection_reason_codes": ["ecosystem-capability-match"]}],
        "substantial_hypothesis_admissible": True, "mutation_admissible": False, "execution_authorized": False,
        "github_writes_authorized": False, "merge_authorized": False, "closure_authorized": False,
        "side_effects_performed": False}, request_comment_id=1)


def receipt_body(disposition="applied", reason="prevented-known-failure"):
    return loop.serialize_receipt_comment({
        "ckr6_result_comment_id": 501, "lesson_id": "LL-77", "source_revision": "2026-11-25T12:00:00.000Z",
        "task_ref": "https://github.com/Blummer92/agent-os/issues/4026", "disposition": disposition,
        "reason_code": reason, "decision": "Followed it.", "outcome_ref": None})


def rec(cid, body, user, updated=STAMP):
    return {"id": cid, "body": body, "user": user, "created_at": STAMP, "updated_at": updated}


def test_trusted_result_and_owner_receipt_count():
    m = derive_lesson_metrics({4026: [rec(501, result_body(), BOT), rec(502, receipt_body(), OWNER)]})
    assert m["receipts"]["valid"] == 1 and m["receipts"]["applied"] == {"prevented-known-failure": 1}


def test_outsider_result_and_receipt_never_count():
    m = derive_lesson_metrics({4026: [rec(501, result_body(), OUTSIDER), rec(502, receipt_body(), OUTSIDER)]})
    assert m["receipts"]["valid"] == 0 and m["receipts"]["applied"] == {}
    assert m["lessons_selected"] == 0
    assert m["malformed_markers"] == {"untrusted-ckr6-result": 1, "untrusted-receipt": 1}


def test_bot_receipt_and_owner_result_are_not_interchangeable():
    m = derive_lesson_metrics({4026: [rec(501, result_body(), OWNER), rec(502, receipt_body(), BOT)]})
    assert m["receipts"]["valid"] == 0


def test_edited_or_undated_records_never_count():
    edited = derive_lesson_metrics({4026: [rec(501, result_body(), BOT, updated="2026-11-25T12:05:00Z"),
                                           rec(502, receipt_body(), OWNER)]})
    assert edited["receipts"]["valid"] == 0
    undated = derive_lesson_metrics({4026: [{"id": 501, "body": result_body(), "user": BOT},
                                            rec(502, receipt_body(), OWNER)]})
    assert undated["receipts"]["valid"] == 0


def test_selection_without_receipt_is_reported_not_counted_as_applied():
    m = derive_lesson_metrics({4026: [rec(501, result_body(), BOT)]})
    assert m["selected_without_receipt"] == ["LL-77@2026-11-25T12:00:00.000Z"]
    assert m["receipts"]["applied"] == {}


def test_bot_login_with_wrong_account_id_never_counts():
    impostor = {"login": "github-actions[bot]", "id": 99999, "type": "Bot"}
    m = derive_lesson_metrics({4026: [rec(501, result_body(), impostor), rec(502, receipt_body(), OWNER)]})
    assert m["receipts"]["valid"] == 0 and m["malformed_markers"] == {"untrusted-ckr6-result": 1}
