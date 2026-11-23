"""#3973 Phase 4: Notion-facing "Applied in PRs" projection (#3973).

One lesson, many verified applications — displayed, never inferred.

The projection consumes ONLY independently verified GitHub lesson-use
receipts through the existing verifier (``verify_receipt_against_result``,
receipt key = (ckr6_result_comment_id, lesson_id, source_revision,
task_ref)). It is pure and offline: no network, no Notion calls, no writes.

Acceptance matrix coverage (see TEST_ACCEPTANCE_MATRIX.csv):
- A01 legacy one-link lesson unchanged (reuse of the #3974 bridge).
- A02 two distinct supporting PRs in fixtures (reuse of #3974, asserted not duplicated).
- A04 bounds / dedup / order for supporting refs (reuse of #3974).
- A05 missing primary still UNVERIFIABLE (reuse of #3974).
- A08 two independent valid receipts -> two distinct applied PR links.
- A09 merged PR with no receipt -> not applied, explicit empty state.
- A10 forged / wrong-PR / wrong-lesson / wrong-revision / stale-head /
  unknown-result / malformed receipts -> never displayed.
- A11 duplicate receipt id -> no double count.
- A12 protected fields untouched: the projection carries no Status, Surface,
  or counter fields at all, and no counter write path exists on this path.
- A15 blocked-live status: the projection is offline by construction; the
  live Notion property / write remain separately authorized (not here).

PR #2077 appears below only as a FIXTURE task ref in receipt tests and as
the known merged-without-receipt negative case. It is supporting repair
evidence for LL-73, NOT an applied-lesson receipt: no real receipt exists
for it, and the A09 test asserts exactly that distinction.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge
from agent_os_execution_service import lesson_learning_loop as loop
from agent_os_execution_service.lesson_learning_metrics import (
    MAX_APPLIED_PRS_DISPLAYED,
    derive_lesson_metrics,
    project_applied_prs,
)

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


def _two_pr_comments():
    """Two independent PRs, each with its own trusted result + receipt."""
    result_a = bridge.serialize_ckr6_result_comment(sufficient_result(3971), request_comment_id=500)
    result_b = bridge.serialize_ckr6_result_comment(sufficient_result(2077), request_comment_id=600)
    return {
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


# ---------------------------------------------------------------- A01 / A02 / A04 / A05 (reuse of #3974)

def _lesson_row(source_link, supporting=()):
    from agent_memory_context_manager.lesson_activation_bridge import normalize_lesson_row

    properties = {
        "Lesson ID": {"type": "rich_text", "rich_text": [{"plain_text": "LL-73"}]},
        "Lesson Learned": {"type": "title", "title": [{"plain_text": "Bounded bug batches"}]},
        "Source Link": {"type": "url", "url": source_link},
        "Status": {"type": "select", "select": {"name": "Applied"}},
        "Surface Before Work?": {"type": "checkbox", "checkbox": True},
        "Area": {"type": "select", "select": {"name": "Automation"}},
        "Applies To": {"type": "multi_select", "multi_select": [{"name": "Notion"}]},
        "Learning Type": {"type": "select", "select": {"name": "Mistake"}},
        "Guardrail": {"type": "rich_text", "rich_text": [{"plain_text": "Reconcile first."}]},
        "What To Do Next Time": {"type": "rich_text", "rich_text": [{"plain_text": "Reconcile first."}]},
    }
    if supporting:
        properties["Supporting Source Links"] = {
            "type": "rich_text",
            "rich_text": [{"type": "text", "plain_text": ref} for ref in supporting],
        }
    return normalize_lesson_row(
        {"object": "page", "id": "x", "last_edited_time": REVISION, "properties": properties}
    )


def test_a01_legacy_one_link_lesson_unchanged():
    lesson = _lesson_row(ISSUE_ORIGIN)
    assert lesson.canonical_github_refs == (ISSUE_ORIGIN,)
    assert lesson.dropped_supporting_refs == ()
    assert lesson.currentness.value == "current"


def test_a02_two_distinct_supporting_prs_in_fixtures_reuse_3974():
    lesson = _lesson_row(ISSUE_ORIGIN, supporting=(PR_B, PR_A))
    assert lesson.canonical_github_refs == (ISSUE_ORIGIN, PR_B, PR_A)
    assert lesson.dropped_supporting_refs == ()


def test_a04_supporting_refs_bounded_ordered_deduped_reuse_3974():
    extra = [f"https://github.com/Blummer92/agent-os/pull/{4000 + n}" for n in range(4)]
    lesson = _lesson_row(
        ISSUE_ORIGIN,
        supporting=(PR_B, PR_B, PR_A, *extra, "https://github.com/other/repo/pull/1"),
    )
    # Primary first, then supporting in row order; duplicates and the foreign
    # ref are dropped; the 6th distinct supporting ref is over the cap of 5.
    assert lesson.canonical_github_refs == (ISSUE_ORIGIN, PR_B, PR_A, *extra[:3])
    assert len(lesson.dropped_supporting_refs) >= 2


def test_a05_missing_primary_still_unverifiable_reuse_3974():
    lesson = _lesson_row("", supporting=(PR_B,))
    assert lesson.canonical_github_refs == ()
    assert lesson.currentness.value == "unverifiable"


# ---------------------------------------------------------------- A08

def test_a08_two_independent_valid_receipts_two_distinct_applied_links():
    projection = project_applied_prs(LESSON, REVISION, _two_pr_comments())
    assert projection["has_verified_applications"] is True
    assert projection["verified_total"] == 2
    assert projection["displayed"] == 2
    assert projection["additional_count"] == 0
    urls = [item["pr_url"] for item in projection["applied_prs"]]
    assert urls == [PR_B, PR_A]  # ordered by PR number ascending
    assert projection["applied_prs"][0]["reason_code"] == "prevented-known-failure"
    assert projection["applied_prs"][1]["reason_code"] == "guided-decision"
    assert projection["display_text"] == "Applied in 2 verified PRs"
    assert projection["drill_through_url"].startswith("https://github.com/search?q=")
    assert LESSON in projection["drill_through_url"]
    assert projection["drill_through_label"] == f"Full GitHub-backed history for {LESSON}"
    assert projection["source_revision"] == REVISION
    # Notion display form: one rich-text item per displayed PR URL.
    assert [item["text"]["content"] for item in projection["notion_rich_text"]] == urls
    # The projection never carries provenance fields.
    assert "source_link" not in projection
    assert "supporting_source_links" not in projection
    assert "Source Link" not in projection


def test_a08_cap_five_displayed_plus_drill_through():
    comments: dict[int, list[dict]] = {}
    for n in range(7):
        pr_number = 4001 + n
        issue_number = pr_number
        result_id = 1000 + n
        receipt_id = 2000 + n
        result = bridge.serialize_ckr6_result_comment(
            sufficient_result(issue_number), request_comment_id=result_id - 1
        )
        comments[issue_number] = [
            _comment(result_id, result),
            _comment(
                receipt_id,
                loop.serialize_receipt_comment(
                    receipt(
                        ckr6_result_comment_id=result_id,
                        task_ref=f"https://github.com/Blummer92/agent-os/pull/{pr_number}",
                    )
                ),
            ),
        ]
    projection = project_applied_prs(LESSON, REVISION, comments)
    assert projection["verified_total"] == 7
    assert projection["displayed"] == MAX_APPLIED_PRS_DISPLAYED == 5
    assert projection["additional_count"] == 2
    assert [item["pr_number"] for item in projection["applied_prs"]] == [4001, 4002, 4003, 4004, 4005]
    assert projection["display_text"] == "Applied in 7 verified PRs (showing 5)"
    # The trailing rich-text item is the drill-through, not a sixth PR link.
    assert len(projection["notion_rich_text"]) == 6
    assert "+2 more verified applications" in projection["notion_rich_text"][-1]["text"]["content"]
    assert projection["drill_through_url"] in projection["notion_rich_text"][-1]["text"]["content"]


def test_a08_applied_receipt_with_issue_task_ref_is_not_a_pr_link():
    result_a = bridge.serialize_ckr6_result_comment(sufficient_result(3971), request_comment_id=500)
    comments = {
        3971: [
            _comment(501, result_a),
            _comment(
                502,
                loop.serialize_receipt_comment(receipt(task_ref=ISSUE_ORIGIN)),
            ),
        ]
    }
    projection = project_applied_prs(LESSON, REVISION, comments)
    assert projection["applied_prs"] == []
    assert projection["verified_applied_non_pr"] == 1
    assert projection["has_verified_applications"] is False
    assert projection["display_text"] == "No verified applications"


# ---------------------------------------------------------------- A09 / A10

def test_a09_prose_mention_alone_is_never_applied():
    # A plain comment can name the lesson AND paste the PR URL in prose --
    # "Applied LL-73 in https://github.com/Blummer92/agent-os/pull/3974" --
    # and still prove nothing: no trusted CKR6 result comment selected the
    # lesson, and no lesson-use receipt binds it to the PR. Mention, merge,
    # and `Fixes` are all equally non-proof; only a verified receipt counts.
    comments = {
        3974: [
            _comment(
                701,
                "Applied LL-73 here -- see https://github.com/Blummer92/agent-os/pull/3974 "
                "for the change. This follows the lesson exactly.",
            ),
            _comment(702, "LGTM, the LL-73 approach looks right."),
        ]
    }
    projection = project_applied_prs(LESSON, REVISION, comments)
    assert projection["applied_prs"] == []
    assert projection["verified_total"] == 0
    assert projection["has_verified_applications"] is False
    assert projection["display_text"] == "No verified applications"
    assert derive_lesson_metrics(comments)["receipts"]["applied"] == {}


def test_a09_merged_pr_without_receipt_is_not_applied():
    # PR #2077 is merged, and a trusted result selected LL-73 on it — but
    # no lesson-use receipt exists. The projection must stay empty and say
    # so explicitly, never "not applied".
    result_b = bridge.serialize_ckr6_result_comment(sufficient_result(2077), request_comment_id=600)
    projection = project_applied_prs(LESSON, REVISION, {2077: [_comment(601, result_b)]})
    assert projection["applied_prs"] == []
    assert projection["verified_total"] == 0
    assert projection["has_verified_applications"] is False
    assert projection["display_text"] == "No verified applications"
    assert projection["notion_rich_text"] == [
        {"type": "text", "text": {"content": "No verified applications"}}
    ]
    assert derive_lesson_metrics({2077: [_comment(601, result_b)]})["selected_without_receipt"] == [
        f"{LESSON}@{REVISION}"
    ]


def test_a10_forged_and_wrong_receipts_never_display():
    result_a = bridge.serialize_ckr6_result_comment(sufficient_result(3971), request_comment_id=500)
    comments = {
        3971: [
            _comment(501, result_a),
            _comment(502, loop.serialize_receipt_comment(receipt(lesson_id="LL-64"))),
            _comment(503, loop.serialize_receipt_comment(receipt(source_revision="2026-01-01T00:00:00.000Z"))),
            _comment(504, loop.serialize_receipt_comment(receipt(ckr6_result_comment_id=999, task_ref=PR_B))),
            _comment(505, "<!-- agent-os-lesson-receipt:v1 -->\n{broken"),
        ]
    }
    projection = project_applied_prs(LESSON, REVISION, comments)
    assert projection["applied_prs"] == []
    assert projection["verified_total"] == 0
    assert projection["has_verified_applications"] is False
    assert projection["rejected_for_this_lesson"] == {
        "receipt-lesson-not-returned-by-ckr6": 1,
        "receipt-result-not-found": 1,
    }
    assert projection["malformed_receipt_markers"] == 1
    # A forged receipt naming another lesson must not leak into this one,
    # and this lesson's projection must not leak into another lesson.
    other = project_applied_prs("LL-64", REVISION, comments)
    assert other["applied_prs"] == []
    assert other["rejected_for_this_lesson"] == {"receipt-lesson-not-returned-by-ckr6": 1}


def test_a10_cross_revision_receipt_never_leaks_into_new_revision_projection():
    # Receipt and its trusted result AGREE with each other but on an OLDER
    # revision: the pair verifies, yet it is evidence for the old revision's
    # projection only. The exact-revision contract keeps it out of the
    # current revision's projection even though nothing about the receipt is
    # forged.
    old_revision = "2026-01-01T00:00:00.000Z"
    result_old = bridge.serialize_ckr6_result_comment(
        sufficient_result(3971, lessons=((LESSON, old_revision),)),
        request_comment_id=500,
    )
    comments = {
        3971: [
            _comment(501, result_old),
            _comment(
                502,
                loop.serialize_receipt_comment(receipt(source_revision=old_revision)),
            ),
        ]
    }
    current = project_applied_prs(LESSON, REVISION, comments)
    assert current["applied_prs"] == []
    assert current["verified_total"] == 0
    assert current["has_verified_applications"] is False
    # The same verified pair still shows on its own revision's projection.
    old = project_applied_prs(LESSON, old_revision, comments)
    assert old["verified_total"] == 1
    assert [item["pr_url"] for item in old["applied_prs"]] == [PR_A]
    # The binding evidence key names what it holds: the CKR6 RESULT comment.
    assert old["applied_prs"][0]["ckr6_result_comment_id"] == 501
    assert "receipt_comment_id" not in old["applied_prs"][0]


def test_a10_stale_head_receipt_never_counts():
    # Receipt bound to an old revision while the trusted result selected the
    # current revision: stale-head, rejected.
    stale = "2026-09-07T23:11:00.000Z"  # truncated CKR6 form, not the exact revision
    result_a = bridge.serialize_ckr6_result_comment(sufficient_result(3971), request_comment_id=500)
    comments = {
        3971: [
            _comment(501, result_a),
            _comment(502, loop.serialize_receipt_comment(receipt(source_revision=stale))),
        ]
    }
    projection = project_applied_prs(LESSON, REVISION, comments)
    assert projection["applied_prs"] == []
    assert projection["rejected_for_this_lesson"] == {"receipt-lesson-not-returned-by-ckr6": 1}


def test_a10_skipped_receipt_never_counts_as_applied():
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
    projection = project_applied_prs(LESSON, REVISION, comments)
    assert projection["applied_prs"] == []
    assert projection["skipped_not_counted"] == 1
    assert projection["has_verified_applications"] is False


# ---------------------------------------------------------------- A11 / A12 / A15

def test_a11_duplicate_receipt_id_never_double_counts():
    comments = _two_pr_comments()
    # Same receipt body posted twice (same receipt key): idempotent.
    comments[3971].append(_comment(503, loop.serialize_receipt_comment(receipt())))
    projection = project_applied_prs(LESSON, REVISION, comments)
    assert projection["verified_total"] == 2
    assert [item["pr_url"] for item in projection["applied_prs"]] == [PR_B, PR_A]
    assert projection["duplicates_ignored"] == 1


def test_a12_projection_carries_no_protected_or_counter_fields():
    projection = project_applied_prs(LESSON, REVISION, _two_pr_comments())
    blob = str(projection)
    for forbidden in ("Status", "Surface Before Work?", "Usage Count", "usage_count",
                      "Recurrence Count", "recurrence_count"):
        assert forbidden not in blob
    assert set(projection) == {
        "schema_version", "projection", "lesson_id", "source_revision",
        "applied_prs", "verified_total", "displayed", "additional_count",
        "drill_through_url", "drill_through_label", "display_text",
        "has_verified_applications", "notion_rich_text",
        "rejected_for_this_lesson", "duplicates_ignored",
        "skipped_not_counted", "verified_applied_non_pr",
        "malformed_receipt_markers",
    }


def test_a12_no_counter_write_path_on_the_projection_path():
    repo = Path(__file__).resolve().parents[1]
    for relative in (
        "src/agent_os_execution_service/lesson_learning_metrics.py",
        "src/agent_os_execution_service/lesson_learning_loop.py",
        "src/agent_os_execution_service/ckr6_github_bridge.py",
    ):
        assert "Usage Count" not in (repo / relative).read_text(encoding="utf-8"), relative


def test_a15_projection_is_pure_and_offline_no_live_state_needed():
    comments = _two_pr_comments()
    first = project_applied_prs(LESSON, REVISION, comments)
    second = project_applied_prs(LESSON, REVISION, comments)
    assert first == second  # deterministic; no hidden state
    assert comments == _two_pr_comments()  # input untouched
    empty = project_applied_prs(LESSON, REVISION, {})
    assert empty["applied_prs"] == [] and empty["display_text"] == "No verified applications"
    # Persisting this projection inside Notion needs a separate property and
    # owner authorization; this offline projection performs no Notion call.
    source = (Path(__file__).resolve().parents[1] / "src/agent_os_execution_service/lesson_learning_metrics.py").read_text(encoding="utf-8")
    for marker in ("notion-cli", "update-page", "update_page"):
        assert marker not in source


def test_projection_rejects_invalid_inputs():
    comments = _two_pr_comments()
    with pytest.raises(ValueError):
        project_applied_prs("not-a-lesson", REVISION, comments)
    with pytest.raises(ValueError):
        project_applied_prs(LESSON, "", comments)
    with pytest.raises(ValueError):
        project_applied_prs(LESSON, REVISION, comments, max_displayed=0)
    with pytest.raises(ValueError):
        project_applied_prs(LESSON, REVISION, comments, max_displayed=6)
    # max_displayed=1 still shows the first PR and counts the rest.
    one = project_applied_prs(LESSON, REVISION, comments, max_displayed=1)
    assert one["displayed"] == 1 and one["additional_count"] == 1
    assert one["applied_prs"][0]["pr_url"] == PR_B
