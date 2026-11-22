import json
from itertools import permutations

import pytest

from agent_memory_context_manager import (
    MAX_CANDIDATES,
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
    from dataclasses import replace

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
