"""Source-anchored, offline writer-to-CKR2 review controls (#3417/#4026)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_memory_context_manager import coding_knowledge_selection as selector
from agent_memory_context_manager.coding_knowledge_selection import CodingKnowledgeRequest
from scripts.agent_os_notion_lessons_write import catalog
from scripts.agent_os_notion_lessons_write.relevance_qualification import qualify_reviewed_create


def request(*keywords: str, task: str = "reviewed task", ecosystem: str = "agent-os"):
    return CodingKnowledgeRequest(
        task_reference=task, ecosystem_hints=(ecosystem,),
        capability_keywords=tuple(keywords), specialized_knowledge_required=True,
    )


def reviewed_entry(*, area="Governance", learning_type="Mistake", applies_to=(),
                   target_lesson_id=None, overrides=None):
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
    if overrides:
        fields.update(overrides)
    return {"target_lesson_id": target_lesson_id, "properties": fields}


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


def assert_unprivileged(outcome):
    assert outcome.publication_authorized is False
    assert outcome.activation_authorized is False

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


def test_generic_positive_without_false_positives_still_cannot_qualify():
    outcome = check(
        reviewed_entry(),
        (request("failure-avoidance", task="actual host failure"),),
        (request("testing", task="unrelated packaging issue"),),
    )
    assert not outcome.qualified
    assert outcome.reason_codes == ("positive-relevance-basis-unverified",)
    assert outcome.positive_hits == 1
    assert outcome.hard_negative_false_positives == 0
    assert_unprivileged(outcome)


def test_known_reference_is_not_a_relevance_bypass():
    req = CodingKnowledgeRequest(
        task_reference="unrelated navigation task", ecosystem_hints=("python",),
        capability_keywords=("testing",), known_knowledge_refs=("LL-999999999",),
        specialized_knowledge_required=True,
    )
    outcome = check(reviewed_entry(), (req,), (request("testing"),))
    assert not outcome.qualified
    assert outcome.reason_codes == ("expected-task-not-selected",)


def test_update_entries_are_not_qualified_as_creates():
    outcome = check(
        reviewed_entry(target_lesson_id="LL-91"),
        (request("failure-avoidance"),), (request("testing"),),
    )
    assert not outcome.qualified
    assert outcome.reason_codes == ("create-entry-required",)


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


def test_context_specific_ckr2_signal_qualifies_without_generic_padding():
    entry = reviewed_entry(overrides={
        "Lesson Learned": "CKR6 mutation boundary requires exact-head gate admission",
        "Guardrail": "Verify CKR6 mutation guidance before a gated PR lands.",
    })
    outcome = check(
        entry,
        (request("ckr6 mutation boundary", task="CKR6 mutation boundary CI gate"),),
        (request("testing", task="unrelated frontend snapshots"),),
    )
    assert outcome.qualified
    assert outcome.reason_codes == ()
    assert (outcome.positive_hits, outcome.positive_total) == (1, 1)
    assert outcome.hard_negative_false_positives == 0
    assert_unprivileged(outcome)


@pytest.mark.parametrize("positives,negatives", [
    pytest.param((), (request("testing"),), id="missing-positives"),
    pytest.param((request("failure-avoidance"),), (), id="missing-negatives"),
    pytest.param((request("failure-avoidance"),) * 9, (request("testing"),), id="oversized-positives"),
    pytest.param((request("failure-avoidance"),), (request("testing"),) * 9, id="oversized-negatives"),
    pytest.param((request("failure-avoidance"),), ("not a typed request",), id="untyped-negative"),
    (1, (request("testing"),)),
    ((request("failure-avoidance"),), 1),
    ({"case": request("failure-avoidance")}, (request("testing"),)),
    ((request("failure-avoidance"),), {"case": request("testing")}),
    ([request("failure-avoidance")], (request("testing"),)),
    ((request("failure-avoidance"),), [request("testing")]),
])
def test_invalid_scenarios_fail_with_bounded_reason(positives, negatives):
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


def test_specific_positive_cannot_hide_same_generic_keyword_hard_negative():
    entry = reviewed_entry(learning_type="QA feedback", overrides={
        "Lesson Learned": "CKR6 mutation boundary source check",
        "What To Do Next Time": "Trace the CKR6 mutation gate evidence.",
    })
    result = check(
        entry,
        (request("ckr6 mutation boundary", task="CKR6 mutation CI repair"),),
        (request("quality-assurance", task="unrelated packaging QA work"),),
    )
    assert not result.qualified
    assert result.reason_codes == ("unrelated-task-false-positive",)
    assert result.positive_hits == 1
    assert result.hard_negative_false_positives == 1
    assert_unprivileged(result)


def test_eight_positive_and_negative_scenarios_are_admitted():
    """The eight-case cap is inclusive on both sides, with exact counters."""
    entry = reviewed_entry(overrides={
        "Lesson Learned": "CKR6 mutation boundary admission",
        "Guardrail": "Check CKR6 mutation boundary evidence.",
    })
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


@pytest.mark.parametrize("fault,reason", [
    ("wrong-identity", "expected-task-not-selected"),
    ("extra-selection", "positive-relevance-basis-unverified"),
])
def test_review_refuses_inconsistent_selector_evidence(fault, reason):
    select = selector.select_coding_knowledge

    def inconsistent(req, candidates):
        result = select(req, candidates)
        if result.sufficiency_status is not selector.SufficiencyStatus.SUFFICIENT:
            return result
        return SimpleNamespace(
            sufficiency_status=result.sufficiency_status,
            knowledge_refs=("LL-91",) if fault == "wrong-identity" else result.knowledge_refs,
            selected=result.selected * 2 if fault == "extra-selection" else result.selected,
        )

    with patch.object(selector, "select_coding_knowledge", side_effect=inconsistent):
        outcome = check(notion_executor_entry(), (request("notion read", "executor outcome"),), (request("testing"),))
    assert not outcome.qualified
    assert outcome.reason_codes == (reason,)
    assert_unprivileged(outcome)


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


@pytest.mark.parametrize("keywords", [(), ("failure-avoidance",)], ids=["title-only", "title-and-generic"])
def test_title_echo_is_not_independent_relevance_evidence(keywords):
    entry = reviewed_entry()
    title_echo = CodingKnowledgeRequest(
        task_reference="unrelated packaging maintenance",
        ecosystem_hints=("agent-os",),
        library_hints=(entry["properties"]["Lesson Learned"],),
        capability_keywords=keywords,
        specialized_knowledge_required=True,
    )
    outcome = check(entry, (title_echo,), (request("testing"),))
    assert not outcome.qualified
    assert outcome.reason_codes == ("positive-relevance-basis-unverified",)
    assert outcome.positive_hits == 1
    assert_unprivileged(outcome)


def notion_executor_entry(*, generic_applies_to=False):
    """Corrected PR #4090 handoff field values (#3417 comment 7166415482)."""
    return {
        "target_lesson_id": None,
        "properties": {
            "Lesson Learned": "Reject failed executor outcomes before completing a Notion read",
            "What Happened": "PR #4090 found governed Notion read routes could report dispatch completed after an explicit failed executor result.",
            "What To Do Next Time": "Before marking governed read dispatch completed, validate executor output is a mapping and reject an explicit non-success status or non-null error. Test failed-status, error-despite-success, wrong-type and success controls on each route.",
            "Guardrail": "Never infer execution success from a returned helper value or transport success alone. Project explicit failures into bounded sanitized receipts, keep curriculum state separate from execution completion, and do not treat passing CI as proof of live runtime acceptance.",
            "Area": "Governance",
            "Learning Type": "QA feedback",
            **({"Applies To": ("Notion",)} if generic_applies_to else {}),
            "Source Link": "https://github.com/Blummer92/agent-os/issues/2816",
        },
    }


def test_notion_executor_outcome_contextual_match_qualifies_without_authority():
    """The CKR2 mechanism reason counts as contextual; it grants no authority."""
    positive = request(
        "notion read", "executor outcome",
        task="The governed Notion read runner must reject an explicit failed "
             "status returned by the executor before marking dispatch completed",
    )
    negatives = (
        request("testing", task="unrelated packaging issue"),
        request("notion", "readback", task="Verify the revision of a written Notion page"),
        request("notion", "lessons-write", task="Publish and re-read a reviewed Notion entry"),
        request("notion", "database-discovery", task="Discover Notion database schema options"),
        request("ckr6 mutation boundary", task="Report stale CKR6 gate evidence"),
    )
    outcome = check(notion_executor_entry(), (positive,), negatives)
    assert outcome.qualified
    assert outcome.reason_codes == ()
    assert outcome.positive_hits == 1
    assert outcome.hard_negative_false_positives == 0
    assert_unprivileged(outcome)


def test_generic_notion_keyword_alone_stays_unverified_for_executor_lesson():
    """A bare generic classification is not a defensible contextual basis."""
    positive = request("notion", task="Discover available Notion databases")
    negative = request("testing", task="unrelated packaging issue")
    outcome = check(notion_executor_entry(generic_applies_to=True), (positive,), (negative,))
    assert not outcome.qualified
    assert outcome.reason_codes == ("positive-relevance-basis-unverified",)
    assert outcome.positive_hits == 1
    assert_unprivileged(outcome)


def test_generic_notion_tag_blocks_writer_qualification_on_unrelated_task():
    positive = request(
        "notion read", "executor outcome",
        task="Reject explicit errors returned during governed Notion read execution",
    )
    negative = request("notion", "readback", task="Verify a written page's revision")
    result = check(notion_executor_entry(generic_applies_to=True), (positive,), (negative,))
    assert not result.qualified
    assert result.reason_codes == ("unrelated-task-false-positive",)
    assert result.hard_negative_false_positives == 1
    assert_unprivileged(result)


def test_writer_refuses_guidance_that_completes_dispatch_despite_errors():
    entry = notion_executor_entry()
    entry["properties"]["What To Do Next Time"] = (
        "Mark dispatch completed even if the executor returns an error."
    )
    positive = request("notion read", "executor outcome",
                       task="Reject explicit errors returned during governed Notion read execution")
    outcome = check(entry, (positive,), (request("testing"),))
    assert not outcome.qualified
    assert outcome.reason_codes == ("expected-task-not-selected",)
    assert_unprivileged(outcome)
