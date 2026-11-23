"""Source-anchored, offline writer-to-CKR2 review controls (#3417/#4026)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

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
    assert outcome.reason_codes == ("positive-relevance-basis-unverified", "unrelated-task-false-positive")
    assert outcome.hard_negative_false_positives == 1


def test_qualified_pair_preserves_no_publication_or_activation_authority():
    outcome = check(
        reviewed_entry(),
        (request("failure-avoidance", task="actual host failure"),),
        (request("testing", task="unrelated packaging issue"),),
    )
    assert not outcome.qualified
    assert outcome.reason_codes == ("positive-relevance-basis-unverified",)
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
    assert outcome.reason_codes == ("positive-relevance-basis-unverified", "unrelated-task-false-positive")
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
    assert not outcome.qualified
    assert outcome.reason_codes == ("positive-relevance-basis-unverified",)
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


def test_context_specific_ckr2_signal_qualifies_without_generic_padding():
    entry = reviewed_entry()
    entry["properties"]["Lesson Learned"] = "CKR6 mutation boundary requires exact-head gate admission"
    entry["properties"]["Guardrail"] = "Verify CKR6 mutation guidance before a gated PR lands."
    outcome = check(
        entry,
        (request("ckr6 mutation boundary", task="CKR6 mutation boundary CI gate"),),
        (request("testing", task="unrelated frontend snapshots"),),
    )
    assert outcome.qualified
    assert outcome.reason_codes == ()
    assert (outcome.positive_hits, outcome.positive_total) == (1, 1)
    assert outcome.hard_negative_false_positives == 0
    assert outcome.publication_authorized is False
    assert outcome.activation_authorized is False


@pytest.mark.parametrize("positives,negatives", [
    (1, (request("testing"),)),
    ((request("failure-avoidance"),), 1),
    ({"case": request("failure-avoidance")}, (request("testing"),)),
    ((request("failure-avoidance"),), {"case": request("testing")}),
    ([request("failure-avoidance")], (request("testing"),)),
    ((request("failure-avoidance"),), [request("testing")]),
])
def test_invalid_scenario_containers_fail_with_bounded_reason(positives, negatives):
    outcome = check(reviewed_entry(), positives, negatives)
    assert not outcome.qualified
    assert outcome.reason_codes == ("bounded-review-scenarios-required",)
    assert (outcome.positive_hits, outcome.positive_total,
            outcome.hard_negative_false_positives, outcome.hard_negative_total) == (0, 0, 0, 0)


@pytest.mark.parametrize("field,value", [
    ("Area", ""),
    ("Learning Type", "  "),
    ("Source Link", None),
    ("Source Link", "https://example.com/unsupported"),
    ("Applies To", (["not hashable"],)),
    ("Supporting Source Links", (["not hashable"],)),
    ("Supporting Source Links", None),
    ("Applies To", "Notion"),
    ("Status", "New"),
    ("Unapproved Property", "value"),
])
def test_invalid_reviewed_catalog_fields_fail_closed_without_coercion(field, value):
    entry = reviewed_entry()
    entry["properties"][field] = value
    with pytest.raises(ValueError, match="reviewed-field-value-invalid|protected-activation-field-refused|reviewed-narrative-fields-required"):
        check(entry, (request("failure-avoidance"),), (request("testing"),))


def test_exact_authority_false_even_when_strong_selection_passes():
    entry = reviewed_entry()
    entry["properties"]["Lesson Learned"] = "CKR6 mutation boundary safety"
    entry["properties"]["What To Do Next Time"] = "Verify CKR6 mutation boundary CI evidence."
    outcome = check(entry, (request("ckr6 mutation boundary"),), (request("testing"),))
    assert outcome.qualified
    assert outcome.publication_authorized is False
    assert outcome.activation_authorized is False


def test_specific_positive_cannot_hide_same_generic_keyword_hard_negative():
    entry = reviewed_entry(learning_type="QA feedback")
    entry["properties"]["Lesson Learned"] = "CKR6 mutation boundary source check"
    entry["properties"]["What To Do Next Time"] = "Trace the CKR6 mutation gate evidence."
    result = check(
        entry,
        (request("ckr6 mutation boundary", task="CKR6 mutation CI repair"),),
        (request("quality-assurance", task="unrelated packaging QA work"),),
    )
    assert not result.qualified
    assert result.reason_codes == ("unrelated-task-false-positive",)
    assert result.positive_hits == 1
    assert result.hard_negative_false_positives == 1
    assert result.publication_authorized is False
    assert result.activation_authorized is False
