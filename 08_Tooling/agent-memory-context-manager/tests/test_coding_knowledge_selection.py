from dataclasses import replace
import json
from itertools import permutations

import pytest

from agent_memory_context_manager import (
    MAX_CANDIDATES,
    MAX_SELECTED,
    CodingKnowledgeCandidate,
    CodingKnowledgeRequest,
    KnowledgeCurrentness,
    RetrievalEscalation,
    SufficiencyStatus,
    select_coding_knowledge,
)


def candidate(
    knowledge_id="hypothesis",
    *,
    currentness=KnowledgeCurrentness.CURRENT,
    library_name="hypothesis",
    ecosystem="python",
    capability_kind="property-based-testing",
    keywords=("property-based-testing", "shrinking"),
    canonical_github_refs=("01_Shared_Standards/python/testing-standard.md",),
    authority_conflict=False,
    qualification_ref="#1138",
):
    return CodingKnowledgeCandidate(
        knowledge_id=knowledge_id,
        source_system="notion",
        source_revision="rev-1",
        currentness=currentness,
        name=library_name or knowledge_id,
        ecosystem=ecosystem,
        library_name=library_name,
        capability_kind=capability_kind,
        keywords=keywords,
        use_when=("Use for generated invariant coverage.",),
        avoid_when=("Avoid when example tests are clearer.",),
        version_scope="6.x",
        qualification_ref=qualification_ref,
        canonical_github_refs=canonical_github_refs,
        evidence_refs=("tests/reference.py",),
        authority_conflict=authority_conflict,
    )


def request(**overrides):
    data = dict(
        task_reference="#1144-test",
        ecosystem_hints=("python",),
        language_hints=("python",),
        library_hints=("hypothesis",),
        capability_keywords=("property-based-testing",),
        target_path_hints=(),
        canonical_rule_refs=(),
        known_knowledge_refs=(),
        attempted_retrieval=(),
        specialized_knowledge_required=True,
    )
    data.update(overrides)
    return CodingKnowledgeRequest(**data)


def test_explicit_python_hypothesis_selects_current_candidate():
    result = select_coding_knowledge(request(), (candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.knowledge_refs == ("hypothesis",)


def test_unrelated_libraries_are_not_preloaded():
    pydantic = candidate(
        "pydantic",
        library_name="pydantic",
        capability_kind="validation",
        keywords=("validation",),
    )
    result = select_coding_knowledge(request(), (pydantic, candidate()))
    assert result.knowledge_refs == ("hypothesis",)


def test_path_derived_hint_can_select_without_repository_access():
    req = request(
        library_hints=(),
        capability_keywords=(),
        target_path_hints=("tests/hypothesis/test_props.py",),
    )
    result = select_coding_knowledge(req, (candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.selected[0].reason_codes == ("target-path-match",)


def test_typescript_canonical_ref_is_preserved_without_working_knowledge():
    ref = "01_Shared_Standards/typescript-react.md"
    req = request(
        ecosystem_hints=("typescript",),
        language_hints=("typescript",),
        library_hints=(),
        capability_keywords=(),
        canonical_rule_refs=(ref,),
        specialized_knowledge_required=False,
    )
    result = select_coding_knowledge(req, ())
    assert result.sufficiency_status is SufficiencyStatus.NOT_NEEDED
    assert result.canonical_github_refs == (ref,)


def test_exact_library_match_outranks_generic_ecosystem_capability():
    generic = candidate(
        "generic",
        library_name="other",
        capability_kind="property-based-testing",
        keywords=("property-based-testing",),
    )
    result = select_coding_knowledge(request(), (generic, candidate()))
    assert result.knowledge_refs == ("hypothesis",)


def test_tie_order_is_deterministic_by_identity():
    first = candidate("a", library_name="hypothesis")
    second = candidate("b", library_name="hypothesis")
    result = select_coding_knowledge(request(), (second, first))
    assert result.knowledge_refs == ("a", "b")


def test_casefold_collisions_have_deterministic_order_and_selection_at_limit():
    # Identity is case-sensitive; neither ASCII nor Unicode fold collisions
    # may make the retained three candidates depend on provider arrival order.
    values = tuple(candidate(identity) for identity in ("A", "a", "SS", "ss", "ß"))
    expected = select_coding_knowledge(request(), values)
    assert expected.knowledge_refs == ("A", "a", "SS")
    for ordering in permutations(values):
        assert select_coding_knowledge(request(), ordering).to_json() == expected.to_json()


def test_casefold_collision_preserves_distinct_case_sensitive_identities():
    values = (candidate("a"), candidate("A"))
    result = select_coding_knowledge(request(), values)
    assert result.candidate_count == 2
    assert result.selected_count == 2
    assert result.knowledge_refs == ("A", "a")


def test_identical_duplicate_identity_deduplicates():
    item = candidate()
    result = select_coding_knowledge(request(), (item, item))
    assert result.selected_count == 1
    assert result.candidate_count == 2


def test_conflicting_duplicate_identity_requires_manual_review():
    one = candidate(canonical_github_refs=("a.md",))
    two = candidate(canonical_github_refs=("b.md",))
    result = select_coding_knowledge(request(), (one, two))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert "duplicate-identity-conflict" in result.reason_codes


def test_stale_relevant_candidate_cannot_be_sufficient():
    result = select_coding_knowledge(
        request(), (candidate(currentness=KnowledgeCurrentness.STALE),)
    )
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW


def test_unverifiable_currentness_routes_conservatively():
    result = select_coding_knowledge(
        request(), (candidate(currentness=KnowledgeCurrentness.UNVERIFIABLE),)
    )
    assert result.recommended_escalation is RetrievalEscalation.MANUAL_REVIEW


def test_canonical_authority_conflict_requires_manual_review():
    result = select_coding_knowledge(request(), (candidate(authority_conflict=True),))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.reason_codes == ("canonical-authority-conflict",)


def test_missing_required_knowledge_is_insufficient():
    result = select_coding_knowledge(request(), ())
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.recommended_escalation is RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY


def test_known_reference_precedes_filtered_query():
    req = request(known_knowledge_refs=("knowledge:hypothesis",))
    result = select_coding_knowledge(req, ())
    assert result.recommended_escalation is RetrievalEscalation.KNOWN_REFERENCE


def test_filtered_query_precedes_exact_lookup():
    result = select_coding_knowledge(request(), ())
    assert result.recommended_escalation is RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY


def test_exact_lookup_follows_attempted_filtered_query():
    req = request(
        attempted_retrieval=(RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY,)
    )
    result = select_coding_knowledge(req, ())
    assert result.recommended_escalation is RetrievalEscalation.EXACT_NARROW_LOOKUP


def test_workspace_search_is_last_bounded_search_escalation():
    req = request(
        attempted_retrieval=(
            RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY,
            RetrievalEscalation.EXACT_NARROW_LOOKUP,
        )
    )
    result = select_coding_knowledge(req, ())
    assert result.recommended_escalation is RetrievalEscalation.WORKSPACE_SEARCH


def test_manual_review_after_all_bounded_searches_attempted():
    req = request(
        attempted_retrieval=(
            RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY,
            RetrievalEscalation.EXACT_NARROW_LOOKUP,
            RetrievalEscalation.WORKSPACE_SEARCH,
        )
    )
    result = select_coding_knowledge(req, ())
    assert result.recommended_escalation is RetrievalEscalation.MANUAL_REVIEW


def test_no_specialized_knowledge_returns_not_needed_without_candidates():
    req = request(
        library_hints=(),
        capability_keywords=(),
        target_path_hints=(),
        specialized_knowledge_required=False,
    )
    result = select_coding_knowledge(req, ())
    assert result.sufficiency_status is SufficiencyStatus.NOT_NEEDED
    assert result.candidate_count == 0


def test_implicit_no_specialized_signals_returns_not_needed():
    req = request(
        library_hints=(),
        capability_keywords=(),
        target_path_hints=(),
        known_knowledge_refs=(),
        specialized_knowledge_required=None,
    )
    result = select_coding_knowledge(req, ())
    assert result.sufficiency_status is SufficiencyStatus.NOT_NEEDED


def test_raw_mapping_cannot_enter_candidate_contract():
    with pytest.raises(TypeError):
        select_coding_knowledge(request(), ({"raw_page_body": "..."},))


def test_candidate_constructor_rejects_unknown_executable_payload_field():
    with pytest.raises(TypeError):
        CodingKnowledgeCandidate(
            knowledge_id="x",
            source_system="notion",
            source_revision="r",
            currentness=KnowledgeCurrentness.CURRENT,
            name="x",
            ecosystem="python",
            library_name="x",
            capability_kind="test",
            raw_test_body="def test_x(): pass",  # type: ignore[call-arg]
        )


def test_oversized_candidate_collection_fails_closed():
    values = tuple(
        candidate(str(index), library_name="hypothesis")
        for index in range(MAX_CANDIDATES + 1)
    )
    result = select_coding_knowledge(request(), values)
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.selected_count == 0


def test_selected_count_never_exceeds_three():
    values = tuple(
        candidate(str(index), library_name="hypothesis")
        for index in range(MAX_CANDIDATES)
    )
    result = select_coding_knowledge(request(), values)
    assert result.selected_count == 3


def test_missing_canonical_reference_is_insufficient():
    result = select_coding_knowledge(request(), (candidate(canonical_github_refs=()),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.reason_codes == ("canonical-reference-missing",)


def test_missing_candidate_reference_is_insufficient_even_with_unrelated_request_ref():
    req = request(canonical_rule_refs=("01_Shared_Standards/unrelated-standard.md",))
    result = select_coding_knowledge(req, (candidate(canonical_github_refs=()),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.reason_codes == ("canonical-reference-missing",)


def test_missing_candidate_reference_is_insufficient_with_related_request_ref():
    req = request(
        canonical_rule_refs=("01_Shared_Standards/python/testing-standard.md",)
    )
    result = select_coding_knowledge(req, (candidate(canonical_github_refs=()),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.reason_codes == ("canonical-reference-missing",)


def test_candidate_reference_is_sufficient_without_request_refs():
    req = request(canonical_rule_refs=())
    result = select_coding_knowledge(req, (candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT


def test_candidate_reference_is_sufficient_alongside_request_refs():
    req = request(canonical_rule_refs=("01_Shared_Standards/unrelated-standard.md",))
    result = select_coding_knowledge(req, (candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert "01_Shared_Standards/unrelated-standard.md" in result.canonical_github_refs
    assert "01_Shared_Standards/python/testing-standard.md" in result.canonical_github_refs


def test_one_candidates_refs_do_not_satisfy_anothers_missing_provenance():
    req = request(library_hints=("hypothesis", "pydantic"))
    with_refs = candidate()
    without_refs = candidate(
        "pydantic",
        library_name="pydantic",
        capability_kind="validation",
        keywords=("validation",),
        canonical_github_refs=(),
    )
    result = select_coding_knowledge(req, (with_refs, without_refs))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.reason_codes == ("canonical-reference-missing",)


def test_missing_one_of_multiple_required_libraries_is_insufficient():
    req = request(library_hints=("hypothesis", "pydantic"))
    result = select_coding_knowledge(req, (candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.reason_codes == ("required-library-uncovered",)


def test_serialization_is_byte_deterministic():
    values = (candidate("b"), candidate("a"))
    one = select_coding_knowledge(request(), values).to_json()
    two = select_coding_knowledge(request(), tuple(reversed(values))).to_json()
    assert one == two
    assert json.loads(one)["sufficiency_status"] == "sufficient"


def test_handoff_projection_uses_existing_packet_concepts():
    result = select_coding_knowledge(request(), (candidate(),))
    projection = result.to_handoff_projection()
    assert set(projection) == {
        "known_facts",
        "prior_decisions",
        "allowed_inspect_first",
        "stop_conditions",
    }
    assert projection["prior_decisions"] == ["#1138"]


def test_insufficient_projection_adds_stop_conditions():
    result = select_coding_knowledge(request(), ())
    projection = result.to_handoff_projection()
    assert projection["stop_conditions"] == ["coding-knowledge:no-relevant-candidate"]


def test_result_cannot_create_authority_or_side_effects():
    result = select_coding_knowledge(request(), (candidate(),))
    assert result.authority_created is False
    assert result.side_effects_performed is False
    assert result.notion_write_performed is False
    assert result.github_write_performed is False


def test_request_requires_bounded_exact_tuple_inputs():
    with pytest.raises(TypeError):
        request(library_hints=["hypothesis"])


def test_candidate_currentness_requires_finite_enum():
    with pytest.raises(TypeError):
        candidate(currentness="current")


# --- CKR6 PR-A (R1 selector dedup / candidate-budget repair, #2425) ---
# A03/A04/A05/A11 from PR_A_TEST_MATRIX.csv. These tests are written
# fail-first: A03 fails on the pre-repair budget check (raw count), A04/A05/A11
# pin behavior that must not change across the repair.


def test_pr_a03_six_raw_three_distinct_does_not_trigger_budget_failure():
    # Duplicates must not consume the candidate budget. Six raw candidates
    # collapse to three distinct identities, which fits the five-candidate
    # budget, so selection proceeds instead of failing closed on the budget.
    values = (
        candidate("a", library_name="hypothesis"),
        candidate("a", library_name="hypothesis"),
        candidate("b", library_name="hypothesis"),
        candidate("b", library_name="hypothesis"),
        candidate("c", library_name="hypothesis"),
        candidate("c", library_name="hypothesis"),
    )
    result = select_coding_knowledge(request(), values)
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert "candidate-budget-exceeded" not in result.reason_codes
    assert result.candidate_count == 6
    assert result.selected_count == 3
    assert result.knowledge_refs == ("a", "b", "c")


def test_pr_a04_six_genuinely_distinct_still_exceed_budget():
    # The budget still binds genuinely distinct candidates: six distinct
    # identities exceed the five-candidate budget and fail closed.
    values = tuple(
        candidate(str(index), library_name="hypothesis")
        for index in range(MAX_CANDIDATES + 1)
    )
    result = select_coding_knowledge(request(), values)
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.reason_codes == ("candidate-budget-exceeded",)
    assert result.selected_count == 0
    assert result.candidate_count == MAX_CANDIDATES + 1


def test_pr_a05_same_id_conflicting_revisions_require_manual_review():
    # The same identity at two different source revisions is a conflict,
    # not a duplicate to collapse: it must fail closed.

    one = candidate()
    two = replace(one, source_revision="rev-2")
    assert one != two
    result = select_coding_knowledge(request(), (one, two))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.reason_codes == ("duplicate-identity-conflict",)


def test_pr_a11_candidate_count_retains_raw_count_after_dedup():
    # candidate_count keeps its documented raw contract: it counts the
    # supplied candidates, not the deduplicated set.
    values = (
        candidate("a", library_name="hypothesis"),
        candidate("a", library_name="hypothesis"),
        candidate("b", library_name="hypothesis"),
    )
    result = select_coding_knowledge(request(), values)
    assert result.candidate_count == 3
    assert result.selected_count == 2
    assert result.knowledge_refs == ("a", "b")


# #4026: frozen source-adjudicated LL-61/LL-80 mechanism controls.
# Snapshots prove deterministic matching behavior, not live Notion truth.
def _pr_refresh_candidate(identity, title, guidance, *,
                          currentness=KnowledgeCurrentness.CURRENT,
                          refs=("https://github.com/Blummer92/agent-os/issues/1865",),
                          conflict=False):
    return CodingKnowledgeCandidate(
        knowledge_id=identity,
        source_system="notion-lessons-learned",
        source_revision="2026-11-15T00:45:00.000Z",
        currentness=currentness,
        name=title,
        ecosystem="python",
        library_name=None,
        capability_kind="deployment",
        use_when=(guidance,),
        canonical_github_refs=refs,
        authority_conflict=conflict,
    )


_PR_REFRESH_HINTS = (
    "branch refresh",
    "merge-tree fallback",
    "Git lineage scope validation",
    "expected-head transport",
)
_LL61_REFRESH = _pr_refresh_candidate(
    "LL-61",
    "Stale or diverged PRs should get deterministic reconciliation before being declared unrefreshable",
    "For stale PR refresh, reacquire exact head and current main, then use the governed deterministic reconciliation path. A genuine git conflict must fail closed before any push.",
)
_LL80_REFRESH = _pr_refresh_candidate(
    "LL-80",
    "PR refresh must test deterministic reconciliation before treating mergeable=false as a conflict",
    "For refresh/reconciliation, let the deterministic reconciliation or git merge-tree path determine whether the branch can be refreshed. A genuine conflict must fail closed before push.",
)


def _pr_refresh_request(**changes):
    fields = {
        "task_reference": "PR #3991 exact-head guarded branch reconciliation",
        "ecosystem_hints": ("agent-os",),
        "language_hints": ("python",),
        "capability_keywords": _PR_REFRESH_HINTS,
        "specialized_knowledge_required": True,
    }
    fields.update(changes)
    return CodingKnowledgeRequest(**fields)


def test_pr_refresh_exact_signals_match_archived_mechanism_without_generic_testing():
    result = select_coding_knowledge(
        _pr_refresh_request(), (_LL80_REFRESH, _LL61_REFRESH)
    )
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert set(result.knowledge_refs) == {"LL-61", "LL-80"}
    assert all(item.reason_codes == ("pr-refresh-reconciliation-text-match",)
               for item in result.selected)


@pytest.mark.parametrize("hints", [
    (), ("branch refresh",), ("merge-tree fallback",),
    ("testing",), ("not branch refresh", "merge-tree fallback"),
])
def test_pr_refresh_partial_or_generic_hints_do_not_activate_text_match(hints):
    result = select_coding_knowledge(
        _pr_refresh_request(capability_keywords=hints),
        (_LL61_REFRESH, _LL80_REFRESH),
    )
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.selected == ()


@pytest.mark.parametrize("title,guidance", [
    ("PR refresh documentation", "Reconcile changelog, not git."),
    ("Git PR refresh", "Refresh git tags only, not branch reconciliation."),
    ("Deploy branch via Git", "Reconcile refresh operation."),
    ("PR refresh must not use deterministic reconciliation", "Use git refresh reconciliation."),
])
def test_pr_refresh_unrelated_or_negated_guidance_cannot_match(title, guidance):
    unrelated = _pr_refresh_candidate("LL-TEST", title, guidance)
    result = select_coding_knowledge(_pr_refresh_request(), (unrelated,))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.selected == ()


def test_pr_refresh_missing_source_cannot_be_sufficient():
    bad = _pr_refresh_candidate(
        "LL-61", _LL61_REFRESH.name, _LL61_REFRESH.use_when[0], refs=()
    )
    result = select_coding_knowledge(_pr_refresh_request(), (bad,))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.reason_codes == ("canonical-reference-missing",)


def test_pr_refresh_stale_and_conflicting_lessons_still_fail_closed():
    for changes in (
        {"currentness": KnowledgeCurrentness.STALE},
        {"currentness": KnowledgeCurrentness.UNVERIFIABLE},
        {"conflict": True},
    ):
        bad = _pr_refresh_candidate(
            "LL-61", _LL61_REFRESH.name, _LL61_REFRESH.use_when[0], **changes
        )
        result = select_coding_knowledge(_pr_refresh_request(), (bad,))
        assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
        assert result.selected == ()
        assert result.reason_codes


def test_pr_refresh_matching_does_not_override_candidate_budget():
    result = select_coding_knowledge(
        _pr_refresh_request(),
        tuple(_pr_refresh_candidate(
            f"LL-TEST-{i}", _LL61_REFRESH.name, _LL61_REFRESH.use_when[0]
        ) for i in range(MAX_CANDIDATES + 1)),
    )
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.reason_codes == ("candidate-budget-exceeded",)


# Additional adversarial contract coverage from the #4091 Gemini review.
# These tests pin observed CKR2 semantics; they neither authorize writes nor
# claim human-adjudicated relevance or CKR6 admission.
@pytest.mark.parametrize("count", (4, MAX_CANDIDATES))
def test_gemini_budget_exact_boundary_and_selection_cap(count):
    values = tuple(candidate(f"item-{i}", library_name="hypothesis")
                   for i in range(count))
    result = select_coding_knowledge(request(), values)
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.candidate_count == count
    assert result.selected_count == MAX_SELECTED
    assert result.knowledge_refs == ("item-0", "item-1", "item-2")


@pytest.mark.parametrize("field,value", (
    ("currentness", KnowledgeCurrentness.STALE),
    ("authority_conflict", True),
    ("library_name", "different-library"),
    ("use_when", ("A conflicting normalized guidance field.",)),
))
def test_gemini_equal_revision_with_different_fields_fails_duplicate_identity(field, value):
    original = candidate()
    conflicting = replace(original, **{field: value})
    result = select_coding_knowledge(request(), (original, conflicting))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.reason_codes == ("duplicate-identity-conflict",)
    assert result.selected_count == 0


def test_gemini_winning_bucket_checks_all_five_for_currentness():
    values = tuple(candidate(f"item-{i}", library_name="hypothesis",
                             currentness=(KnowledgeCurrentness.STALE if i == 4
                                          else KnowledgeCurrentness.CURRENT))
                   for i in range(MAX_CANDIDATES))
    result = select_coding_knowledge(request(), values)
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.reason_codes == ("stale-relevant-candidate",)
    assert result.selected_count == 0


def test_gemini_lower_bucket_stale_does_not_override_current_exact_match():
    generic = candidate("generic", library_name="other",
                        currentness=KnowledgeCurrentness.STALE)
    exact = candidate("exact", library_name="hypothesis")
    result = select_coding_knowledge(request(), (generic, exact))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.knowledge_refs == ("exact",)
    assert result.selected[0].reason_codes == ("exact-library-match",)


@pytest.mark.parametrize("changed,expected_reason", (
    ({"authority_conflict": True, "canonical_github_refs": ()},
     "canonical-authority-conflict"),
    ({"currentness": KnowledgeCurrentness.STALE, "canonical_github_refs": ()},
     "stale-relevant-candidate"),
    ({"currentness": KnowledgeCurrentness.UNVERIFIABLE,
      "canonical_github_refs": ()}, "unverifiable-relevant-candidate"),
))
def test_gemini_manual_review_precedes_missing_selected_provenance(changed, expected_reason):
    result = select_coding_knowledge(request(), (replace(candidate(), **changed),))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.reason_codes == (expected_reason,)
    assert result.selected == ()


def test_gemini_distinct_candidate_budget_precedes_currentness():
    values = tuple(candidate(f"item-{i}", library_name="hypothesis",
                             currentness=(KnowledgeCurrentness.STALE if i == 0
                                          else KnowledgeCurrentness.CURRENT))
                   for i in range(MAX_CANDIDATES + 1))
    result = select_coding_knowledge(request(), values)
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.reason_codes == ("candidate-budget-exceeded",)
    assert result.selected_count == 0


def test_gemini_winning_bucket_missing_selected_provenance_remains_insufficient():
    values = tuple(candidate(f"item-{i}", library_name="hypothesis",
                             canonical_github_refs=(() if i == 0 else ("docs/ok.md",)))
                   for i in range(MAX_CANDIDATES))
    result = select_coding_knowledge(request(), values)
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.reason_codes == ("canonical-reference-missing",)


def test_gemini_exact_library_path_combines_reasons_and_dominates_generic_match():
    generic = candidate("generic", library_name="other")
    req = request(target_path_hints=("pkg/hypothesis/helpers.py",))
    result = select_coding_knowledge(req, (generic, candidate()))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.knowledge_refs == ("hypothesis",)
    assert result.selected[0].reason_codes == ("exact-library-match", "target-path-match")


def test_gemini_contextual_tie_break_prefers_unique_mechanism_context():
    first = replace(candidate("z", library_name="other"),
                    use_when=("Handle rebase conflict recovery safely.",))
    second = replace(candidate("a", library_name="other"),
                     use_when=("Update release notes only.",))
    req = request(library_hints=(), task_reference="Investigate rebase conflict recovery")
    outcome = select_coding_knowledge(req, (second, first))
    assert outcome.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert outcome.knowledge_refs == ("z", "a")
    assert tuple(item.reason_codes for item in outcome.selected) == (
        ("ecosystem-capability-match",), ("ecosystem-capability-match",),
    )


def test_gemini_known_reference_precedes_out_of_order_attempt_history():
    req = request(known_knowledge_refs=("knowledge:hypothesis",),
                  attempted_retrieval=(RetrievalEscalation.WORKSPACE_SEARCH,
                                       RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY))
    result = select_coding_knowledge(req, ())
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.recommended_escalation is RetrievalEscalation.KNOWN_REFERENCE


@pytest.mark.parametrize("name", (
    "ecosystem_hints", "language_hints", "library_hints",
    "capability_keywords", "target_path_hints", "canonical_rule_refs",
    "known_knowledge_refs",
))
def test_gemini_request_signal_fields_reject_non_tuple_values(name):
    with pytest.raises(TypeError):
        request(**{name: ["python"]})


@pytest.mark.parametrize("supplied", ([], (item for item in (candidate(),))))
def test_gemini_candidate_pool_requires_exact_tuple(supplied):
    with pytest.raises(TypeError):
        select_coding_knowledge(request(), supplied)


def test_gemini_validation_limits_and_control_character_fail_closed():
    from agent_memory_context_manager.coding_knowledge_selection import (
        MAX_GUIDANCE_TEXT_CHARS, MAX_SIGNAL_ITEMS, MAX_TEXT_CHARS,
    )
    with pytest.raises(ValueError):
        request(library_hints=tuple(f"lib-{i}" for i in range(MAX_SIGNAL_ITEMS + 1)))
    with pytest.raises(ValueError):
        request(task_reference="x" * (MAX_TEXT_CHARS + 1))
    for field in ("use_when", "avoid_when"):
        with pytest.raises(ValueError):
            replace(candidate(), **{field: ("x" * (MAX_GUIDANCE_TEXT_CHARS + 1),)})
    for invalid in ("\n", "\x00", "  "):
        with pytest.raises(ValueError):
            request(task_reference=invalid)


def test_gemini_projection_reports_selected_and_inspect_first_evidence():
    result = select_coding_knowledge(request(), (candidate(),))
    projection = result.to_handoff_projection()
    assert projection["known_facts"] == [
        "coding-knowledge-sufficiency:sufficient",
        "coding-knowledge:hypothesis",
    ]
    assert projection["allowed_inspect_first"] == [
        "01_Shared_Standards/python/testing-standard.md",
    ]
    insufficient = select_coding_knowledge(request(), ())
    assert insufficient.recommended_escalation is RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY
    assert insufficient.to_handoff_projection()["known_facts"] == [
        "coding-knowledge-sufficiency:insufficient",
    ]


def test_gemini_pr_refresh_pair_has_stable_order_and_count():
    left = select_coding_knowledge(_pr_refresh_request(), (_LL61_REFRESH, _LL80_REFRESH))
    right = select_coding_knowledge(_pr_refresh_request(), (_LL80_REFRESH, _LL61_REFRESH))
    assert left.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert left.selected_count == 2
    assert left.to_json() == right.to_json()
    assert set(left.knowledge_refs) == {"LL-61", "LL-80"}


def test_gemini_casefold_collision_status_and_count():
    values = tuple(candidate(identity) for identity in ("A", "a", "SS", "ss", "ß"))
    result = select_coding_knowledge(request(), values)
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.selected_count == MAX_SELECTED
    assert result.knowledge_refs == ("A", "a", "SS")


def test_multiple_required_libraries_survive_three_candidate_cut():
    req = request(library_hints=("hypothesis", "pydantic"))
    values = (
        candidate("a", library_name="hypothesis"),
        candidate("b", library_name="hypothesis"),
        candidate("c", library_name="hypothesis"),
        candidate("z", library_name="pydantic"),
    )
    expected = select_coding_knowledge(req, values)
    assert expected.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert expected.knowledge_refs == ("a", "b", "z")
    for ordering in permutations(values):
        assert select_coding_knowledge(req, ordering).to_json() == expected.to_json()


def test_library_coverage_optimizes_all_three_slots():
    req = request(library_hints=("alpha", "beta", "gamma"))
    values = tuple(
        candidate(ident, library_name=library)
        for ident, library in (
            ("a", "alpha"), ("b", "alpha"), ("c", "alpha"),
            ("d", "beta"), ("e", "gamma"),
        )
    )
    result = select_coding_knowledge(req, values)
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.knowledge_refs == ("a", "d", "e")


def test_library_coverage_does_not_hide_stale_or_missing_provenance():
    req = request(library_hints=("alpha", "beta"))
    values = (
        candidate("a", library_name="alpha"),
        candidate("b", library_name="alpha"),
        candidate("c", library_name="alpha"),
        candidate("z", library_name="beta", currentness=KnowledgeCurrentness.STALE),
    )
    result = select_coding_knowledge(req, values)
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.reason_codes == ("stale-relevant-candidate",)
    current = replace(values[-1], currentness=KnowledgeCurrentness.CURRENT,
                      canonical_github_refs=())
    result = select_coding_knowledge(req, (*values[:-1], current))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.reason_codes == ("canonical-reference-missing",)


def test_library_coverage_never_crosses_relevance_buckets():
    req = request(library_hints=("alpha", "beta"), capability_keywords=("validation",))
    high = tuple(candidate(ident, library_name="alpha") for ident in ("a", "b", "c"))
    low = candidate("z", library_name="other", capability_kind="validation",
                    keywords=("validation",))
    result = select_coding_knowledge(req, (*high, low))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.knowledge_refs == ("a", "b", "c")
    assert result.reason_codes == ("required-library-uncovered",)
