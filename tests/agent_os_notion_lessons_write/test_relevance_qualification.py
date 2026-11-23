"""Source-anchored, offline writer-to-CKR2 review controls (#3417/#4026)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

# Use the real in-repository CKR2/CKR11 matcher rather than a duplicate.
ROOT = Path(__file__).resolve().parents[2]
MEMORY_SRC = ROOT / "08_Tooling" / "agent-memory-context-manager" / "src"
if str(MEMORY_SRC) not in sys.path:
    sys.path.insert(0, str(MEMORY_SRC))

from agent_memory_context_manager.coding_knowledge_selection import CodingKnowledgeRequest
from scripts.agent_os_notion_lessons_write import catalog
from scripts.agent_os_notion_lessons_write.relevance_qualification import qualify_reviewed_create


def request(*keywords: str, task: str = "reviewed task", ecosystem: str = "agent-os"):
    return CodingKnowledgeRequest(
        task_reference=task, ecosystem_hints=(ecosystem,),
        capability_keywords=tuple(keywords), specialized_knowledge_required=True,
    )


def reviewed_entry(*, area="Governance", learning_type="Mistake", applies_to=()):
    fields = {
        "Lesson Learned": "Trace the CKR6 host consumer for approved continuation",
        "What Happened": "A host did not consume an approved continuation payload.",
        "What To Do Next Time": "Trace the approved host continuation consumer.",
        "Guardrail": "Do not imply that code tests prove the native host invoked it.",
        "Area": area,
        "Learning Type": learning_type,
        "Source Link": "https://github.com/Blummer92/agent-os/issues/3690",
    }
    if applies_to:
        fields["Applies To"] = applies_to
    return {"target_lesson_id": None, "properties": fields}


def check(entry, positives, negatives):
    with patch.object(catalog, "LESSONS", {"reviewed-create": entry}):
        return qualify_reviewed_create(
            "reviewed-create", positive_requests=positives,
            hard_negative_requests=negatives,
        )


def test_review_requires_real_writer_metadata_not_narrative_alone():
    entry = reviewed_entry()
    del entry["properties"]["Area"]
    outcome = check(entry, (request("failure-avoidance"),), (request("testing"),))
    assert not outcome.qualified
    assert outcome.reason_codes == ("writer-relevance-metadata-incomplete",)


def test_reviewer_detects_unmatched_positive_task_without_faking_a_lesson_match():
    outcome = check(reviewed_entry(), (request("native host continuation"),), (request("testing"),))
    assert not outcome.qualified
    assert outcome.reason_codes == ("expected-task-not-selected",)
    assert outcome.positive_hits == 0


def test_review_reports_hard_negative_false_positive_on_generic_capability():
    outcome = check(
        reviewed_entry(),
        (request("failure-avoidance", task="actual host failure"),),
        (request("failure-avoidance", task="unrelated packaging issue"),),
    )
    assert not outcome.qualified
    assert outcome.reason_codes == ("unrelated-task-false-positive",)
    assert outcome.hard_negative_false_positives == 1


def test_qualified_pair_preserves_no_publication_or_activation_authority():
    outcome = check(
        reviewed_entry(),
        (request("failure-avoidance", task="actual host failure"),),
        (request("testing", task="unrelated packaging issue"),),
    )
    assert outcome.qualified
    assert outcome.positive_hits == 1
    assert outcome.hard_negative_false_positives == 0
    assert outcome.publication_authorized is False
    assert outcome.activation_authorized is False


def test_known_reference_is_not_a_relevance_bypass():
    req = CodingKnowledgeRequest(
        task_reference="unrelated navigation task", ecosystem_hints=("python",),
        capability_keywords=("testing",), known_knowledge_refs=("LL-999999999",),
        specialized_knowledge_required=True,
    )
    outcome = check(reviewed_entry(), (req,), (request("testing"),))
    assert not outcome.qualified
    assert outcome.reason_codes == ("expected-task-not-selected",)


def test_missing_scenarios_and_update_entries_are_not_qualified():
    entry = reviewed_entry()
    assert not check(entry, (), (request("testing"),)).qualified
    entry["target_lesson_id"] = "LL-91"
    result = check(entry, (request("failure-avoidance"),), (request("testing"),))
    assert result.reason_codes == ("create-entry-required",)


def test_no_raw_lesson_text_in_qualification_receipt():
    outcome = check(reviewed_entry(), (request("native host continuation"),), (request("testing"),))
    assert "host" not in str(outcome).casefold()
    assert "continuation" not in str(outcome).casefold()


def test_actual_reviewed_continuation_entry_exposes_metadata_miss():
    """Narrative relevance is not a CKR2 match when taxonomy cannot surface it."""
    outcome = qualify_reviewed_create(
        catalog.CONTINUATION_CONSUMER_REQUEST_ID,
        positive_requests=(request("native host continuation", task="trace the live host consumer"),),
        hard_negative_requests=(request("testing", task="unrelated packaging test"),),
    )
    assert not outcome.qualified
    assert outcome.reason_codes == ("expected-task-not-selected",)
    assert outcome.positive_hits == 0
    assert outcome.hard_negative_false_positives == 0
    assert outcome.publication_authorized is False


def test_actual_reviewed_continuation_entry_rejects_generic_false_positive():
    """A broad governance signal matching an unrelated task must fail review."""
    outcome = qualify_reviewed_create(
        catalog.CONTINUATION_CONSUMER_REQUEST_ID,
        positive_requests=(request("failure-avoidance", task="host consumer continuation failure"),),
        hard_negative_requests=(request("failure-avoidance", task="unrelated wheel packaging failure"),),
    )
    assert not outcome.qualified
    assert outcome.reason_codes == ("unrelated-task-false-positive",)
    assert outcome.positive_hits == 1
    assert outcome.hard_negative_false_positives == 1
    assert outcome.activation_authorized is False


def test_review_counts_multiple_positive_and_negative_requests():
    outcome = check(
        reviewed_entry(),
        (
            request("failure-avoidance", task="host continuation failure"),
            request("failure-avoidance", task="unconsumed host decision"),
        ),
        (
            request("testing", task="unrelated packaging fixture"),
            request("testing", task="unrelated frontend snapshot"),
        ),
    )
    assert outcome.qualified
    assert (outcome.positive_hits, outcome.positive_total) == (2, 2)
    assert (outcome.hard_negative_false_positives, outcome.hard_negative_total) == (0, 2)


def test_review_refuses_oversized_and_untyped_review_scenarios():
    entry = reviewed_entry()
    too_many = tuple(request("failure-avoidance", task=f"case {i}") for i in range(9))
    result = check(entry, too_many, (request("testing"),))
    assert result.reason_codes == ("bounded-review-scenarios-required",)
    assert not result.qualified
    result = check(entry, (request("failure-avoidance"),), ("not a typed request",))
    assert result.reason_codes == ("bounded-review-scenarios-required",)
    assert not result.qualified
