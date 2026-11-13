"""Pre-catalog publication review (#3418): duplicates, updates, holds and bounds.

Pure-function cases for `review_lesson_candidate` plus the production wiring through
`capture_lesson_candidate` and the CKR6 `lesson-candidate` ingress. No Notion, no network.
"""

from __future__ import annotations

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge
from agent_os_execution_service import lesson_learning_loop as loop
from agent_os_execution_service import lesson_publication_review as review_module
from agent_os_execution_service.lesson_publication_review import (
    CandidateLesson,
    ExistingLessonSummary,
    PublicationVerdict as V,
    review_lesson_candidate,
)

REV = "2026-10-10T12:00:00.000Z"
REF_A = "https://github.com/Blummer92/agent-os/issues/3305"
REF_B = "https://github.com/Blummer92/agent-os/pull/3960"

CLOSING_NEXT = "When live acceptance remains, use a non-closing Part of reference and verify the PR description before merge."
CLOSING_GUARD = "If a PR description contains a GitHub closing keyword referencing an issue, merging may close that issue."
CLOSING_CAUSE = "A closing keyword in the PR body closed an issue whose live acceptance had not run."


def existing(lesson_id="LL-87", **changes):
    value = dict(
        lesson_id=lesson_id, source_revision=REV, title="Closing keywords close issues at merge",
        what_to_do_next_time=CLOSING_NEXT, guardrail=CLOSING_GUARD, root_cause=CLOSING_CAUSE,
        canonical_github_refs=(REF_A,),
    )
    value.update(changes)
    return ExistingLessonSummary(**value)


def candidate(**changes):
    value = dict(
        title="A different title for the same idea", root_cause=CLOSING_CAUSE,
        what_to_do_next_time=CLOSING_NEXT, guardrail=CLOSING_GUARD, canonical_github_refs=(REF_A,),
    )
    value.update(changes)
    return CandidateLesson(**value)


def run(cand, *items, complete=True):
    return review_lesson_candidate(cand, tuple(items), existing_set_complete=complete)


# --------------------------------------------------- exact guidance: duplicate / update


def test_same_guidance_with_a_different_title_is_a_duplicate_not_a_new_lesson():
    result = run(candidate(), existing())
    assert result.verdict is V.DUPLICATE
    assert (result.matched_lesson_id, result.expected_revision) == ("LL-87", REV)
    assert result.reason_codes == ("same-guidance-no-new-evidence",)


def test_same_guidance_with_new_evidence_updates_the_existing_lesson_at_its_exact_revision():
    result = run(candidate(canonical_github_refs=(REF_A, REF_B)), existing())
    assert result.verdict is V.UPDATE_EXISTING
    assert (result.matched_lesson_id, result.expected_revision) == ("LL-87", REV)


def test_exact_guidance_with_an_unrelated_root_cause_is_held_for_review():
    other_cause = "Aggregate validation silently skipped the execution service package."
    assert run(candidate(root_cause=other_cause), existing()).reason_codes == ("same-guidance-different-cause",)


def test_comparison_ignores_case_and_unicode_compatibility_forms_but_not_wording():
    shouty = candidate(what_to_do_next_time=CLOSING_NEXT.upper().replace("PART OF", "Part of"))
    assert run(shouty, existing()).verdict in (V.DUPLICATE, V.UPDATE_EXISTING)


# --------------------------------------------------- paraphrase, ambiguity, contradiction


PARAPHRASE_NEXT = "Use a non-closing Part of reference when live acceptance remains, and verify the PR description before merging."
PARAPHRASE_GUARD = "A GitHub closing keyword followed by an issue number in a PR description will close that issue when merged."


def test_a_retitled_paraphrase_is_never_published_as_new():
    result = run(candidate(what_to_do_next_time=PARAPHRASE_NEXT, guardrail=PARAPHRASE_GUARD), existing())
    assert result.verdict is V.HUMAN_REVIEW
    assert result.reason_codes[0] in {"possible-duplicate-paraphrase", "ambiguous-similarity"}
    assert result.matched_lesson_id == "LL-87" and result.advisory_scores
    assert result.publication_authorized is False


def test_same_component_with_a_distinct_cause_and_remedy_finds_no_lexical_match():
    distinct = candidate(
        root_cause="Two mutants in the parser survived a 76-test file that exercised both functions.",
        what_to_do_next_time="Write one single-fault case per guard asserting its exact reason code, then remove the guard.",
        guardrail="A green mapped test is not evidence it detects the protected regression at this SHA.",
        canonical_github_refs=(REF_B,),
    )
    result = run(distinct, existing())
    assert result.verdict is V.NO_LEXICAL_MATCH
    assert result.matched_lesson_id is None
    assert "novelty-not-semantically-verified" in result.reason_codes
    assert result.publication_authorized is False


# Real texts (live LL-82 read-only on 2026-11-13 vs the #3690 continuation entry on main):
# the same lesson in different vocabulary. Lexical comparison cannot see it, so the guard
# must say "no lexical match, novelty unverified", never "validated new".
LL82_NEXT = (
    "When validating mission continuation, test the host boundary end-to-end. Treat subordinate writes as "
    "progress, not parent completion. Require the execution host to consume continuation state and "
    "automatically resume bounded authorized work until a governed terminal state, a real blocker, or an "
    "authorization boundary is reached."
)
LL82_GUARD = (
    "Do not declare continuation repaired solely because repository code emits agent_os_continuation or "
    "because a subordinate mutation succeeded. Require a native-host canary proving the parent mission "
    "continues without an unnecessary user prompt."
)
CONTINUATION_NEXT = (
    "Trace producer -> canonical payload -> registered MCP tool -> approved publication allowlist -> live host "
    "consumer -> next admitted dispatch -> exact receipt. Reuse existing driver, hooks and governed ingress; "
    "repair only the first proven disconnected boundary."
)
CONTINUATION_GUARD = (
    "Registration, a green test, emitted agent_os_continuation or a successful same-turn read does not prove "
    "automatic host dispatch. Do not widen the five-tool allowlist without a separate owner decision."
)


def test_documented_limit_a_semantic_overlap_in_different_vocabulary_is_not_called_new():
    ll82 = existing(
        "LL-82", title="Native execution hosts must enforce continuation",
        what_to_do_next_time=LL82_NEXT, guardrail=LL82_GUARD, root_cause="Continuation state emitted but not consumed by the host.",
    )
    cont = candidate(
        title="Connect continuation decisions to an actual host consumer before claiming automatic execution",
        root_cause="Continuation boundaries were repaired in merged PRs while native host next-dispatch stayed unverified.",
        what_to_do_next_time=CONTINUATION_NEXT, guardrail=CONTINUATION_GUARD,
    )
    result = run(cont, ll82)
    assert result.verdict is V.NO_LEXICAL_MATCH  # the limit: lexical overlap does not see the duplicate
    assert result.reason_codes == ("no-existing-lesson-above-similarity-floor", "novelty-not-semantically-verified")
    assert "validated" not in result.verdict.value
    assert result.publication_authorized is False


def test_two_plausible_existing_matches_are_never_resolved_automatically():
    result = run(candidate(), existing("LL-87"), existing("LL-90"))
    assert result.verdict is V.HUMAN_REVIEW and result.reason_codes == ("ambiguous-multiple-matches",)
    assert [lesson_id for lesson_id, _ in result.advisory_scores] == ["LL-87", "LL-90"]


def test_opposite_guidance_with_almost_identical_wording_is_a_polarity_conflict():
    base_next = "Always merge the pull request after the green aggregate run and read the checks back."
    base_guard = "Merge only with exact head validation recorded for this pull request."
    held = existing("LL-12", what_to_do_next_time=base_next, guardrail=base_guard, root_cause=None)
    flipped = candidate(what_to_do_next_time=base_next.replace("Always merge", "Never merge"), guardrail=base_guard)
    result = run(flipped, held)
    assert result.verdict is V.HUMAN_REVIEW and result.reason_codes == ("polarity-conflict",)


def test_long_unicode_guidance_keeps_its_negation_and_is_never_truncated():
    filler = " ".join(["résumé naïve façade coöperate Ελληνικά"] * 22)
    positive = f"Always {filler} then verify the readback before claiming success."
    negative = positive.replace("Always", "Never")
    assert 700 < len(positive) <= review_module.MAX_FIELD_CHARS
    held = existing("LL-33", what_to_do_next_time=positive, guardrail=CLOSING_GUARD, root_cause=None)
    result = run(candidate(what_to_do_next_time=negative), held)
    assert result.verdict is V.HUMAN_REVIEW and result.reason_codes == ("polarity-conflict",)
    oversized = candidate(what_to_do_next_time="never verify the readback " + "x" * review_module.MAX_FIELD_CHARS)
    assert run(oversized, held).reason_codes == ("candidate-text-over-bound",)


def test_a_match_with_an_archived_lesson_is_held():
    result = run(candidate(), existing(archived=True))
    assert result.verdict is V.HUMAN_REVIEW and result.reason_codes == ("matches-archived-lesson",)


# --------------------------------------------------- insufficient or generic candidates


def test_a_candidate_without_a_verifiable_source_is_insufficient():
    result = run(candidate(canonical_github_refs=("see the discussion",)), existing())
    assert result.verdict is V.INSUFFICIENT_EVIDENCE
    assert "candidate-canonical-reference-missing" in result.reason_codes


def test_a_candidate_without_a_root_cause_is_insufficient():
    assert "candidate-root-cause-missing" in run(candidate(root_cause="  "), existing()).reason_codes


def test_generic_guidance_is_insufficient_even_with_a_source():
    generic = candidate(what_to_do_next_time="Be careful next time.", guardrail="Double check everything.")
    assert run(generic, existing()).reason_codes == ("candidate-guidance-too-generic",)


def test_guidance_that_only_restates_the_guardrail_is_insufficient():
    twin = candidate(what_to_do_next_time=CLOSING_GUARD, guardrail=CLOSING_GUARD)
    assert run(twin, existing()).reason_codes == ("candidate-guidance-restates-guardrail",)


# --------------------------------------------------- unverified or incomplete existing evidence


@pytest.mark.parametrize(
    ("items", "complete", "reason"),
    [
        ((existing(),), False, "existing-set-incomplete"),
        ((existing(lesson_id="87"),), True, "existing-identity-unverified"),
        ((existing(lesson_id="LL-0"),), True, "existing-identity-unverified"),
        ((existing(source_revision="yesterday"),), True, "existing-identity-unverified"),
        ((existing("LL-87"), existing("LL-87")), True, "duplicate-existing-lesson-id"),
        ((existing(guardrail=" "),), True, "existing-lesson-malformed"),
        ((existing(guardrail="x" * 1025),), True, "existing-text-over-bound"),
        (tuple(existing(f"LL-{n}") for n in range(1, 27)), True, "existing-lesson-budget-exceeded"),
    ],
)
def test_unverified_or_incomplete_existing_evidence_stops_automatic_publication(items, complete, reason):
    result = run(candidate(), *items, complete=complete)
    assert result.verdict is V.HUMAN_REVIEW and result.reason_codes == (reason,)


def test_an_empty_but_complete_existing_set_finds_no_lexical_match():
    assert run(candidate(), complete=True).verdict is V.NO_LEXICAL_MATCH


# --------------------------------------------------- contract


def test_no_result_ever_carries_authority_and_wrong_types_are_rejected():
    for result in (run(candidate(), existing()), run(candidate(), complete=False), run(candidate(canonical_github_refs=()))):
        assert (result.authority_created, result.notion_write_performed, result.publication_authorized) == (False,) * 3
    with pytest.raises(TypeError):
        review_lesson_candidate({"title": "x"}, (), existing_set_complete=True)
    with pytest.raises(TypeError):
        review_lesson_candidate(candidate(), [existing()], existing_set_complete=True)
    with pytest.raises(TypeError):
        review_lesson_candidate(candidate(), (), existing_set_complete="yes")


@pytest.mark.parametrize("value", ["LL-1", "LL-987654321", "LL-0", "LL-01", "LL-1234567890", "ll-1", "LL-1 ", "87"])
def test_lesson_id_grammar_matches_the_learning_loop(value):
    assert (review_module.LESSON_ID.fullmatch(value) is not None) == (loop.LESSON_ID.fullmatch(value) is not None)


@pytest.mark.parametrize("value", [REV, "2026-10-10T12:00:00Z", "2026-10-10 12:00:00", "2026-10-10T12:00:00.12Z", "x"])
def test_revision_grammar_matches_the_learning_loop(value):
    assert (review_module.REVISION.fullmatch(value) is not None) == (loop.REVISION.fullmatch(value) is not None)


# --------------------------------------------------- production wiring through capture and ingress


def capture_payload(**changes):
    value = {
        "source_reference": "PR #3392 repair", "signal": "repeated-repair",
        "failure_signature": "pr-body-closing-keyword-closes-issue", "ecosystem": "agent-os",
        "capability_kind": "failure-avoidance",
        "lesson_summary": "A closing keyword in a PR body closes the linked issue at merge",
        "what_happened": "A merged PR closed an issue whose live acceptance had not run.",
        "severity": "High", "owner_agent": "github-service-agent",
        "canonical_github_refs": [REF_A], "evidence_refs": [REF_B],
        "what_to_do_next_time": CLOSING_NEXT, "guardrail": CLOSING_GUARD,
        "reusable_rule_proven": True, "root_cause_or_diagnosis": CLOSING_CAUSE,
    }
    value.update(changes)
    return value


def summary(lesson_id="LL-87", **changes):
    value = {
        "lesson_id": lesson_id, "source_revision": REV, "title": "Closing keywords close issues at merge",
        "what_to_do_next_time": CLOSING_NEXT, "guardrail": CLOSING_GUARD, "root_cause": CLOSING_CAUSE,
        "canonical_github_refs": [REF_A],
    }
    value.update(changes)
    return value


def proposal_review(payload):
    return loop.capture_lesson_candidate(payload)["lesson_proposal"]["publication_review"]


def test_capture_without_existing_lessons_reports_that_no_comparison_happened():
    review = proposal_review(capture_payload())
    assert review["verdict"] == "human-review" and review["reason_codes"] == ["existing-set-incomplete"]
    assert review["publication_authorized"] is False


def test_capture_with_a_complete_existing_set_reports_the_duplicate_and_changes_nothing_else():
    baseline = loop.capture_lesson_candidate(capture_payload())["lesson_proposal"]
    result = loop.capture_lesson_candidate(
        capture_payload(existing_lessons=[summary()], existing_set_complete=True))["lesson_proposal"]
    assert result["publication_review"]["verdict"] == "duplicate"
    assert result["publication_review"]["matched_lesson_id"] == "LL-87"
    assert {k: v for k, v in result.items() if k != "publication_review"} == {
        k: v for k, v in baseline.items() if k != "publication_review"}
    assert result["publication_authorized"] is False and result["notion_write_performed"] is False


def test_capture_holds_a_candidate_with_no_diagnosis_even_when_nothing_matches():
    review = proposal_review(capture_payload(root_cause_or_diagnosis=None, existing_lessons=[], existing_set_complete=True))
    assert review["verdict"] == "insufficient-evidence"
    assert "candidate-root-cause-missing" in review["reason_codes"]


def test_the_lesson_candidate_ingress_carries_the_review_into_the_serialized_result(monkeypatch):
    monkeypatch.setattr(bridge, "resolve_lesson_read_route",
                        lambda: (_ for _ in ()).throw(AssertionError("capture must not read")))
    envelope = bridge.parse_envelope({
        "operation": "lesson-candidate", "repository": "Blummer92/agent-os", "issue_number": 3418,
        "task_reference": "issue:#3418",
        "candidate": capture_payload(existing_lessons=[summary()], existing_set_complete=True),
    })
    result = bridge.execute_envelope(envelope, retrieval_required=False)
    assert result["notion_read_performed"] is False
    comment = bridge.serialize_ckr6_result_comment(result, request_comment_id=11)
    parsed = bridge.parse_ckr6_result_comment(comment)
    assert parsed["lesson_proposal"]["publication_review"]["verdict"] == "duplicate"
    assert len(comment.encode("utf-8")) < bridge.MAX_RESULT_COMMENT_BYTES


@pytest.mark.parametrize(
    "bad",
    [
        {"existing_lessons": "LL-87"},
        {"existing_lessons": [summary()] * 26},
        {"existing_lessons": ["LL-87"]},
        {"existing_lessons": [{**summary(), "status": "Applied"}]},
        {"existing_lessons": [summary(archived="no")]},
        {"existing_lessons": [summary(guardrail="")]},
        {"existing_lessons": [summary()], "existing_set_complete": "yes"},
    ],
)
def test_malformed_existing_lesson_input_is_rejected_not_ignored(bad):
    with pytest.raises(ValueError):
        loop.capture_lesson_candidate(capture_payload(**bad))
