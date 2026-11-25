"""Test the exact catalog entries without giving the selector a title or ID."""
import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest, SufficiencyStatus, select_coding_knowledge,
)
from agent_memory_context_manager.lesson_activation_bridge import (
    _as_selection_candidate, describe_selection_basis, normalize_lesson_row,
)
from scripts.agent_os_notion_lessons_write.catalog import lesson_for
from scripts.agent_os_notion_lessons_write.relevance_qualification import (
    _simulated_readback, qualify_reviewed_create,
)

REPORTING = "ckr2-selection-reason-caller-basis"
REVERSAL = "ckr2-reversed-instruction-negative-control"


def request(task, *hints):
    return CodingKnowledgeRequest(
        task_reference=task, ecosystem_hints=("agent-os",),
        capability_keywords=hints, specialized_knowledge_required=True,
    )


REPORT_TASK = request("A relevant match is misreported in the caller handoff.",
                      "selection basis", "caller reporting", "testing")
REVERSE_TASK = request("Exercise topic overlap with the action taken in the wrong order.",
                       "lexical lesson relevance", "reversed instruction", "quality-assurance")
CALENDAR = request("Add regression tests for leap-day rendering.", "testing", "quality-assurance")


@pytest.mark.parametrize("entry,positive,sibling", [
    (REPORTING, REPORT_TASK, REVERSE_TASK), (REVERSAL, REVERSE_TASK, REPORT_TASK),
])
def test_reviewed_catalog_entry_qualifies_only_for_its_own_mechanism(entry, positive, sibling):
    result = qualify_reviewed_create(entry, positive_requests=(positive,),
                                     hard_negative_requests=(sibling, CALENDAR))
    assert result.qualified, result
    assert result.positive_hits == 1 and result.hard_negative_false_positives == 0
    assert not result.publication_authorized and not result.activation_authorized


@pytest.mark.parametrize("entry,positive", [(REPORTING, REPORT_TASK), (REVERSAL, REVERSE_TASK)])
def test_contextual_reason_reaches_reporting_without_giving_authority(entry, positive):
    lesson = normalize_lesson_row(_simulated_readback(lesson_for(entry)))
    result = select_coding_knowledge(positive, (_as_selection_candidate(lesson),))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.selected[0].reason_codes == ("verified-lesson-relevance-test-match",)
    assert describe_selection_basis(positive, [lesson], identity_route=False).basis == "generic-unique"
    assert not result.authority_created


@pytest.mark.parametrize("entry,positive,prefix", [
    (REPORTING, REPORT_TASK, "Never register a "),
    (REVERSAL, REVERSE_TASK, "Donʼt pair "),
    (REVERSAL, REVERSE_TASK, "Skip pairing "),
])
def test_negated_lesson_guidance_cannot_match_or_fall_back_to_generic(entry, positive, prefix):
    fields = dict(lesson_for(entry))
    original = fields["What To Do Next Time"]
    if entry == REPORTING:
        fields["What To Do Next Time"] = prefix + "selection reason in selector-to-caller tests."
    else:
        fields["What To Do Next Time"] = prefix + "hard negatives that reverse the advice."
    assert fields["What To Do Next Time"] != original
    lesson = normalize_lesson_row(_simulated_readback(fields))
    outcome = select_coding_knowledge(positive, (_as_selection_candidate(lesson),))
    assert outcome.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert outcome.selected == ()


@pytest.mark.parametrize("entry,positive", [(REPORTING, REPORT_TASK), (REVERSAL, REVERSE_TASK)])
def test_request_prose_alone_does_not_qualify(entry, positive):
    untyped = request(positive.task_reference)
    outcome = qualify_reviewed_create(entry, positive_requests=(untyped,),
                                      hard_negative_requests=(CALENDAR,))
    assert not outcome.qualified
    assert outcome.positive_hits == 0
    assert not outcome.publication_authorized
