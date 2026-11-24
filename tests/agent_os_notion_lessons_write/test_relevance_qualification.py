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



def structural_entry(*, target_lesson_id=None, include_narrative=True, meta=None):
    """Minimal schema fixture ONLY; never use as evidence for CKR2 relevance.

    Deliberately short values exercise catalog shape/types, not semantic hits.
    Tests of select_coding_knowledge continue to use reviewed_entry().
    """
    fields = ({
        "Lesson Learned": "T",
        "What Happened": "H",
        "What To Do Next Time": "N",
        "Guardrail": "G",
    } if include_narrative else {})
    if meta:
        fields.update(meta)
    return {"target_lesson_id": target_lesson_id, "properties": fields}


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


def retired_continuation_entry():
    """The retired continuation-live-consumer-2026-10-30 create values, as a fixture.

    The duplicate create candidate was retired from the shipped catalog by the
    LL-82 refinement (#3417); these values preserve the same review scenarios
    against the same content shape without re-admitting the candidate.
    """
    return {
        "target_lesson_id": None,
        "properties": {
            "Lesson Learned": "Connect continuation decisions to an actual host consumer before claiming automatic execution",
            "What Happened": "Native host next-dispatch remains unverified. Owner-reported Cloud Shell runs: 30 MCP tests passed.",
            "What To Do Next Time": "Trace producer -> payload -> live host consumer -> next admitted dispatch -> exact receipt.",
            "Guardrail": "Emitted agent_os_continuation does not prove automatic host dispatch. Do not widen the five-tool allowlist without a separate owner decision.",
            "Area": "Governance",
            "Learning Type": "Mistake",
            "Source Link": "https://github.com/Blummer92/agent-os/issues/3690",
        },
    }


def test_actual_reviewed_continuation_entry_exposes_metadata_miss():
    """Narrative relevance is not a CKR2 match when taxonomy cannot surface it."""
    outcome = check(
        retired_continuation_entry(),
        (request("native host continuation", task="trace the live host consumer"),),
        (request("testing", task="unrelated packaging test"),),
    )
    assert not outcome.qualified
    assert outcome.reason_codes == ("expected-task-not-selected",)
    assert outcome.positive_hits == 0
    assert outcome.hard_negative_false_positives == 0
    assert outcome.publication_authorized is False


def test_actual_reviewed_continuation_entry_rejects_generic_false_positive():
    """A broad governance signal matching an unrelated task must fail review."""
    outcome = check(
        retired_continuation_entry(),
        (request("failure-avoidance", task="host consumer continuation failure"),),
        (request("failure-avoidance", task="unrelated wheel packaging failure"),),
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


def test_eight_positive_and_negative_scenarios_are_admitted():
    """The eight-case cap is inclusive on both sides, with exact counters."""
    entry = reviewed_entry()
    entry["properties"]["Lesson Learned"] = "CKR6 mutation boundary admission"
    entry["properties"]["Guardrail"] = "Check CKR6 mutation boundary evidence."
    positives = tuple(request("ckr6 mutation boundary", task=f"CI gate {i}") for i in range(8))
    negatives = tuple(request("testing", task=f"unrelated fixture {i}") for i in range(8))
    result = check(entry, positives, negatives)
    assert result.qualified
    assert result.reason_codes == ()
    assert (result.positive_hits, result.positive_total) == (8, 8)
    assert (result.hard_negative_false_positives, result.hard_negative_total) == (0, 8)


def test_all_metadata_fields_are_required_with_complete_create_narrative():
    """Required review metadata cannot be omitted individually (M32 boundary)."""
    for name in ("Area", "Learning Type", "Source Link"):
        entry = reviewed_entry()
        del entry["properties"][name]
        result = check(entry, (request("testing"),), (request("quality-assurance"),))
        assert not result.qualified
        assert result.reason_codes == ("writer-relevance-metadata-incomplete",)


def test_qualified_selection_has_exactly_one_real_candidate():
    """Match sufficiency and exact identity, never a second candidate (M104)."""
    entry = reviewed_entry()
    entry["properties"]["Lesson Learned"] = "CKR6 mutation boundary exact identity"
    entry["properties"]["Guardrail"] = "Verify CKR6 mutation boundary provenance."
    result = check(
        entry,
        (request("ckr6 mutation boundary"),),
        (request("testing"),),
    )
    assert result.qualified
    assert result.positive_hits == 1
    assert result.publication_authorized is False
    assert result.activation_authorized is False


def test_structural_fixture_validates_create_and_narrow_update_without_ckr2():
    """Catalog shape validity is deliberately separate from lesson relevance."""
    create = structural_entry()
    assert catalog.validate_entry(create) is create
    assert set(create["properties"]) == set(catalog.NARRATIVE_TYPES)

    # A reviewed update may contain one writable field; it need not recreate
    # all four narrative fields.
    update = structural_entry(
        target_lesson_id="LL-91", include_narrative=False, meta={"Guardrail": "G"}
    )
    assert catalog.validate_entry(update) is update
    assert set(update["properties"]) == {"Guardrail"}


def test_structural_fixture_accepts_exact_descriptive_types_without_narrative_padding():
    entry = structural_entry(meta={
        "Area": "Governance",
        "Learning Type": "Mistake",
        "Applies To": ("Notion",),
        "Source Link": "https://github.com/Blummer92/agent-os/issues/3690",
        "Supporting Source Links": (
            "https://github.com/Blummer92/agent-os/issues/3417",
        ),
    })
    assert catalog.validate_entry(entry) is entry
    assert set(entry["properties"]) == set(catalog.WRITABLE_TYPES)
    assert all(name not in entry["properties"] for name in catalog.PROTECTED_FIELDS)


@pytest.mark.parametrize("entry,reason", [
    (
        structural_entry(include_narrative=False, meta={"Area": "Governance"}),
        "reviewed-narrative-fields-required",
    ),
    (
        structural_entry(target_lesson_id="LL-91", include_narrative=False),
        "reviewed-narrative-fields-required",
    ),
    (
        structural_entry(meta={"Applies To": ()}),
        "reviewed-field-value-invalid",
    ),
    (
        structural_entry(meta={"Applies To": tuple(f"item{i}" for i in range(9))}),
        "reviewed-field-value-invalid",
    ),
    (
        structural_entry(meta={"Supporting Source Links": ()}),
        "reviewed-field-value-invalid",
    ),
    (
        structural_entry(meta={"Source Link": "https://example.com/other"}),
        "reviewed-field-value-invalid",
    ),
    (
        structural_entry(meta={"Status": "Applied"}),
        "protected-activation-field-refused",
    ),
])
def test_structural_fixture_fails_closed_on_invalid_contracts(entry, reason):
    with pytest.raises(ValueError, match=f"^{reason}$"):
        catalog.validate_entry(entry)


def test_title_echo_library_hint_cannot_qualify_generic_relevance():
    """Claude F1: the lesson's own title is not independent library context."""
    entry = reviewed_entry()
    title = entry["properties"]["Lesson Learned"]
    title_echo = CodingKnowledgeRequest(
        task_reference="unrelated packaging maintenance",
        ecosystem_hints=("agent-os",),
        library_hints=(title,),
        capability_keywords=(),
        specialized_knowledge_required=True,
    )
    result = check(entry, (title_echo,), (request("testing"),))
    assert not result.qualified
    assert result.reason_codes == ("positive-relevance-basis-unverified",)
    assert result.positive_hits == 1
    assert result.publication_authorized is False
    assert result.activation_authorized is False


def test_title_echo_cannot_rescue_generic_capability_overlap():
    """A generic classification plus a self-referential title stays unverified."""
    entry = reviewed_entry()
    positive = CodingKnowledgeRequest(
        task_reference="unrelated wheel packaging",
        ecosystem_hints=("agent-os",),
        library_hints=(entry["properties"]["Lesson Learned"],),
        capability_keywords=("failure-avoidance",),
        specialized_knowledge_required=True,
    )
    result = check(entry, (positive,), (request("testing"),))
    assert not result.qualified
    assert "positive-relevance-basis-unverified" in result.reason_codes
    assert result.publication_authorized is False
