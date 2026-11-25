"""PR #4090 selector regression: Notion-read executor-outcome mechanism match.

A correctly authored lesson about rejecting explicit failed Notion executor
outcomes must be selectable by an explicit mechanism request, without the
generic "notion"/"quality-assurance" keywords doing the work and without the
new branch leaking onto unrelated tasks.
"""
import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest,
    SufficiencyStatus,
    select_coding_knowledge,
)
from agent_memory_context_manager.lesson_activation_bridge import (
    LessonActivationSkip,
    _as_selection_candidate,
    normalize_lesson_row,
)

REASON = "verified-notion-executor-outcome-match"

TITLE = "Reject failed executor outcomes before completing a Notion read"
GUIDANCE = (
    "Before marking governed read dispatch completed, validate executor output "
    "is a mapping and reject an explicit non-success status or non-null error. "
    "Test failed-status, error-despite-success, wrong-type and success controls "
    "on each route."
)
GUARDRAIL = (
    "Never infer execution success from a returned helper value or transport "
    "success alone. Project explicit failures into bounded sanitized receipts, "
    "keep curriculum state separate from execution completion, and do not treat "
    "passing CI as proof of live runtime acceptance."
)
REVISION = "2026-11-25T12:00:00.000Z"


def row(*, title=TITLE, guidance=GUIDANCE):
    def rich(value, kind="rich_text"):
        return {"type": kind, kind: [{"plain_text": value}]}

    def selected(value):
        return {"type": "select", "select": {"name": value}}

    return {
        "object": "page", "id": "fixture-4090", "last_edited_time": REVISION,
        "properties": {
            "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": 4090}},
            "Lesson Learned": rich(title, "title"),
            "Status": selected("New"),
            "Surface Before Work?": {"type": "checkbox", "checkbox": True},
            "Area": selected("Governance"),
            "Learning Type": selected("QA feedback"),
            "Applies To": {
                "type": "multi_select",
                "multi_select": [{"name": "Notion"}],
            },
            "Source Link": {"type": "url", "url": "https://github.com/Blummer92/agent-os/issues/2816"},
            "What To Do Next Time": rich(guidance),
            "Guardrail": rich(GUARDRAIL),
        },
    }


def candidate(**overrides):
    normalized = normalize_lesson_row(row(**overrides))
    assert not isinstance(normalized, LessonActivationSkip)
    return _as_selection_candidate(normalized)


def request(*hints: str, task: str = "reviewed task", paths=()):
    return CodingKnowledgeRequest(
        task_reference=task,
        ecosystem_hints=("agent-os",),
        language_hints=("Python",),
        capability_keywords=tuple(hints),
        target_path_hints=tuple(paths),
        specialized_knowledge_required=True,
    )


def reasons_for(req, cand):
    result = select_coding_knowledge(req, (cand,))
    selected = [item.reason_codes for item in result.selected]
    return result, selected


def test_explicit_mechanism_request_selects_via_contextual_reason():
    result, selected = reasons_for(
        request(
            "notion read", "executor outcome",
            task="The governed Notion read runner must reject an explicit failed "
                 "status returned by the executor before marking dispatch completed",
            paths=("scripts/agent_os_notion_read_request/runner.py",),
        ),
        candidate(),
    )
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert selected == [(REASON,)]


def test_extra_caller_hints_do_not_dilute_the_mechanism_match():
    _, selected = reasons_for(
        request("notion read", "executor outcome", "failure-receipts"),
        candidate(),
    )
    assert selected == [(REASON,)]


@pytest.mark.parametrize("hints", [
    ("notion read",),
    ("executor outcome",),
    ("notion", "executor"),
])
def test_partial_caller_signals_never_activate_the_branch(hints):
    _, selected = reasons_for(request(*hints), candidate())
    assert all(REASON not in reason_codes for reason_codes in selected)


def test_negated_title_never_activates_the_branch():
    _, selected = reasons_for(
        request("notion read", "executor outcome"),
        candidate(title="Do not reject failed executor outcomes before completing a Notion read"),
    )
    assert all(REASON not in reason_codes for reason_codes in selected)


def test_negated_guidance_never_activates_the_branch():
    _, selected = reasons_for(
        request("notion read", "executor outcome"),
        candidate(
            guidance="Do not validate executor output for an explicit failure "
                     "before marking governed read dispatch completed.",
        ),
    )
    assert all(REASON not in reason_codes for reason_codes in selected)


def test_guidance_without_completion_signal_never_activates_the_branch():
    _, selected = reasons_for(
        request("notion read", "executor outcome"),
        candidate(guidance="Reject failed executor output and surface an explicit error receipt."),
    )
    assert all(REASON not in reason_codes for reason_codes in selected)


def test_guardrail_text_alone_never_supplies_positive_evidence():
    # The Guardrail entry mentions failure and completion, but positive
    # evidence must come from the title and the primary guidance entry.
    _, selected = reasons_for(
        request("notion read", "executor outcome"),
        candidate(guidance="Record the executor outcome and continue the read."),
    )
    assert all(REASON not in reason_codes for reason_codes in selected)


HARD_NEGATIVES = (
    ("Publish a reviewed Lessons Learned entry through the governed writer and verify canonical Notion readback",
     ("notion", "lessons-write")),
    ("Discover available Notion databases and enumerate their schema properties",
     ("notion", "database-discovery")),
    ("Troubleshoot why the CKR6 mutation boundary gate did not revalidate after a trusted result postback",
     ("ckr6 mutation boundary",)),
    ("Fix CI packaging of transport artifacts for the validation workflow",
     ("ci", "packaging")),
    ("A Notion read executor returned success with a valid bounded payload; project the read evidence",
     ("notion",)),
)


@pytest.mark.parametrize("task,hints", HARD_NEGATIVES)
def test_unrelated_tasks_never_receive_the_contextual_reason(task, hints):
    _, selected = reasons_for(request(*hints, task=task), candidate())
    assert all(REASON not in reason_codes for reason_codes in selected)
