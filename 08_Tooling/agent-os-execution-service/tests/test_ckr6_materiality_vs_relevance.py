"""Materiality and relevance are distinct CKR6 decisions (#3690 audit).

Reproduces the live #4102/#4103/#4104/#4105 producer outcome offline: the
exact request shape, with ``specialized_knowledge_required=true`` and no
relevant eligible lesson, is ``insufficient`` and blocks. The same task with
materiality omitted is classified by the existing #2780 issue-start contract
(``inferred-not-material``) and is ``not-needed``. "No matching lesson" never
becomes "not material", and the gate consumes exactly the producer decision.
"""
from __future__ import annotations

import json

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge
from agent_os_execution_service.ckr6_mutation_gate import evaluate_mutation_boundary
from agent_os_execution_service.issue_start_lesson_preflight import (
    activate_issue_start_lesson_preflight,
)

REVISION = "2026-11-15T00:41:00.000Z"
HEAD = "3fb851014c37806af3edabbf07ecedfa9ae1136c"
PR = 4105
OWNER_ID = 32861845
REQUEST_ID = 7120252842
REQUEST_AT = "2026-11-24T02:32:57Z"

LIVE_4105_REQUEST = {
    "repository": "Blummer92/agent-os",
    "issue_number": PR,
    "task_reference": (
        f"PR #{PR} exact head {HEAD}: governed Notion writer source-preserving "
        "evidence review and revision-bound lesson updates"
    ),
    "ecosystem_hints": ("agent-os",),
    "language_hints": ("python",),
    "capability_keywords": (
        "notion-lessons-writer", "lesson-source-provenance",
        "lesson-refinement", "regression-tests",
    ),
    "target_path_hints": ("scripts/agent_os_notion_lessons_write/writer.py",),
    "canonical_rule_refs": ("https://github.com/Blummer92/agent-os/issues/3417",),
}


def _rt(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text}]}


def _unrelated_row(number):
    # Eligible, current, canonically sourced, and unrelated to the writer task.
    return {
        "object": "page",
        "url": f"https://www.notion.so/lesson-{number}",
        "last_edited_time": REVISION,
        "properties": {
            "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": number}},
            "Lesson Learned": {"type": "title", "title": [{"plain_text": "Recheck currentness before routing"}]},
            "Status": {"type": "select", "select": {"name": "Applied"}},
            "Surface Before Work?": {"type": "checkbox", "checkbox": True},
            "Area": {"type": "select", "select": {"name": "Testing"}},
            "Applies To": {"type": "multi_select", "multi_select": [{"name": "Python"}]},
            "Learning Type": {"type": "select", "select": {"name": "Testing lesson"}},
            "Source Link": {"type": "url", "url": "https://github.com/Blummer92/agent-os/issues/520"},
            "Guardrail": _rt("Never reuse stale evidence."),
            "What To Do Next Time": _rt("Reacquire evidence after head advances."),
        },
    }


def _reader(rows):
    def read(_query):
        return {"results": list(rows), "has_more": False, "next_cursor": None}
    return read


def _produce(materiality, rows=()):
    return activate_issue_start_lesson_preflight(
        **LIVE_4105_REQUEST,
        specialized_knowledge_required=materiality,
        execute_read=_reader(rows),
    )


# --- hard negatives: material work with no applicable lesson still blocks ---

@pytest.mark.parametrize("rows", [(), tuple(_unrelated_row(n) for n in range(10, 15))])
def test_caller_asserted_material_without_relevant_lesson_blocks(rows):
    result = _produce(True, rows)
    assert result["materiality_source"] == "caller-asserted-material"
    assert result["lesson_retrieval_status"] == "insufficient"
    assert result["selection_reason_codes"] == ["no-relevant-candidate"]
    assert result["selected_lesson_ids"] == []
    assert result["substantial_hypothesis_admissible"] is False


def test_generic_shared_keywords_do_not_make_an_unrelated_lesson_relevant():
    # Python/testing vocabulary overlaps the request but is not relevance.
    result = _produce(True, tuple(_unrelated_row(n) for n in range(10, 15)))
    assert result["selected_lesson_ids"] == []


# --- positive: the existing materiality contract classifies the same task ---

def test_omitted_materiality_uses_existing_issue_start_inference():
    result = _produce(None, tuple(_unrelated_row(n) for n in range(10, 15)))
    assert result["materiality_source"] == "inferred-not-material"
    assert result["lesson_retrieval_status"] == "not-needed"
    assert result["substantial_hypothesis_admissible"] is True


def test_library_hint_makes_inferred_materiality_material_again():
    result = activate_issue_start_lesson_preflight(
        **LIVE_4105_REQUEST, library_hints=("Notion API",), execute_read=_reader(()),
    )
    assert result["materiality_source"] == "inferred-material"
    assert result["substantial_hypothesis_admissible"] is False


# --- the gate consumes the producer decision once, without re-deciding ---

def _bridge_result(materiality):
    raw = _produce(materiality)
    return {
        "operation": "issue-start",
        "repository": "Blummer92/agent-os",
        "issue_number": PR,
        "status": raw["lesson_retrieval_status"],
        "reason_codes": raw["selection_reason_codes"],
        "selected_lesson_ids": raw["selected_lesson_ids"],
        "selected_lessons": raw["selected_lessons"],
        "materiality_source": raw["materiality_source"],
        "canonical_github_refs": raw["canonical_github_refs"],
        "rejected_candidate_provenance": raw["rejected_candidate_provenance"],
        "handoff_projection": raw["handoff_projection"],
        "substantial_hypothesis_admissible": raw["substantial_hypothesis_admissible"],
        "mutation_admissible": False,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
    }


def _thread(materiality):
    envelope = {
        "operation": "issue-start",
        "repository": "Blummer92/agent-os",
        "issue_number": PR,
        "task_reference": LIVE_4105_REQUEST["task_reference"],
    }
    if materiality is not None:
        envelope["specialized_knowledge_required"] = materiality
    request = {
        "id": REQUEST_ID,
        "body": bridge.COMMAND_PREFIX + json.dumps(envelope, separators=(",", ":")),
        "user": {"login": "Blummer92", "id": OWNER_ID, "type": "User"},
        "created_at": REQUEST_AT,
        "updated_at": REQUEST_AT,
        "issue_url": f"https://api.github.com/repos/Blummer92/agent-os/issues/{PR}",
        "html_url": f"https://github.com/Blummer92/agent-os/pull/{PR}#issuecomment-{REQUEST_ID}",
    }
    result_id = REQUEST_ID + 15
    result = {
        "id": result_id,
        "body": bridge.serialize_ckr6_result_comment(_bridge_result(materiality), request_comment_id=REQUEST_ID),
        "user": {"login": "github-actions[bot]", "id": 41898282, "type": "Bot"},
        "created_at": "2026-11-24T02:33:51Z",
        "updated_at": "2026-11-24T02:33:51Z",
        "issue_url": f"https://api.github.com/repos/Blummer92/agent-os/issues/{PR}",
        "html_url": f"https://github.com/Blummer92/agent-os/pull/{PR}#issuecomment-{result_id}",
    }
    return [request, result]


def _gate(comments, head=HEAD, pr=PR):
    return evaluate_mutation_boundary(
        repository="Blummer92/agent-os", issue_number=pr, issue_comments=(),
        pr_number=pr, pr_comments=comments,
        head_proposed_at="2026-11-24T02:15:29Z", head_sha=head,
    )


def test_gate_blocks_exactly_the_live_4105_insufficient_result():
    decision = _gate(_thread(True))
    assert (decision.admitted, decision.reason_code, decision.status) == (
        False, "ckr6-boundary-blocked", "insufficient")
    assert decision.detail == "status=insufficient reason_codes=[no-relevant-candidate]"


def test_gate_admits_the_producer_not_needed_result_for_the_exact_head():
    decision = _gate(_thread(None))
    assert (decision.admitted, decision.reason_code, decision.status) == (
        True, "admitted", "not-needed")


def test_admission_does_not_transfer_to_a_new_head():
    decision = _gate(_thread(None), head="0" * 40)
    assert (decision.admitted, decision.reason_code) == (False, "ckr6-request-head-unbound")
