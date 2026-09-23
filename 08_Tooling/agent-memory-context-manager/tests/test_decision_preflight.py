from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest,
    KnowledgeCurrentness,
    RetrievalEscalation,
)
from agent_memory_context_manager.decision_preflight import (
    DecisionRecordEvidence,
    DecisionRetrievalStatus,
    consume_decision_preflight,
    plan_decision_preflight,
)


def request(**overrides):
    data = dict(
        task_reference="issue:#1369",
        capability_keywords=("architecture",),
        target_path_hints=("00_Governance/architecture-decisions",),
        canonical_rule_refs=(),
        known_knowledge_refs=(),
        specialized_knowledge_required=None,
    )
    data.update(overrides)
    return CodingKnowledgeRequest(**data)


def decision(**overrides):
    data = dict(
        decision_id="decision:navigation-read-contract",
        source_revision="2026-08-24T14:16:00Z",
        title="Navigation Registry Read Contract is canonical",
        domain="architecture",
        status="Accepted",
        currentness=KnowledgeCurrentness.CURRENT,
        summary="Use the Navigation Registry Read Contract for connector read paths.",
        canonical_github_refs=(
            "01_Shared_Standards/navigation/connector-contract-adr.md",
        ),
        evidence_refs=("issue:#1367", "issue:#1368"),
        keywords=("architecture", "canonical", "connector"),
        applies_to=("connector architecture",),
    )
    data.update(overrides)
    return DecisionRecordEvidence(**data)


def test_architecture_sensitive_task_requires_retrieval_and_selects_current_decision():
    plan = plan_decision_preflight(request())
    assert plan.retrieval_required is True
    assert plan.notion_read_performed is False
    result = consume_decision_preflight(request(), (decision(),))
    assert result.decision_retrieval_status is DecisionRetrievalStatus.SUFFICIENT
    assert result.selected_decision_ids == ("decision:navigation-read-contract",)
    assert result.verification_required is True
    assert result.source_authority == "secondary-index"
    assert result.handoff_projection["prior_decisions"] == ["decision:navigation-read-contract"]
    assert result.handoff_projection["allowed_inspect_first"]


def test_decision_without_candidate_provenance_is_insufficient_despite_request_refs():
    req = request(
        canonical_rule_refs=("01_Shared_Standards/navigation/connector-contract-adr.md",)
    )
    result = consume_decision_preflight(
        req, (decision(canonical_github_refs=()),)
    )
    assert result.decision_retrieval_status is DecisionRetrievalStatus.INSUFFICIENT
    assert result.verification_required is False


def test_routine_mechanical_task_is_not_needed_and_ignores_supplied_rows():
    req = request(
        capability_keywords=(),
        target_path_hints=(),
        specialized_knowledge_required=False,
    )
    plan = plan_decision_preflight(req)
    assert plan.retrieval_required is False
    result = consume_decision_preflight(req, (decision(),))
    assert result.decision_retrieval_status is DecisionRetrievalStatus.NOT_NEEDED
    assert result.candidate_count == 0


def test_selection_is_bounded_to_three_and_deterministic():
    rows = tuple(
        decision(decision_id=f"decision:{name}", title=f"Decision {name}")
        for name in ("d", "b", "a", "c", "e")
    )
    result = consume_decision_preflight(request(), rows)
    assert result.selected_count == 3
    assert result.selected_decision_ids == ("decision:a", "decision:b", "decision:c")


def test_explicit_known_decision_reference_uses_ckr2_known_reference_escalation_when_missing():
    req = request(known_knowledge_refs=("decision:explicit",), specialized_knowledge_required=True)
    result = consume_decision_preflight(req, ())
    assert result.decision_retrieval_status is DecisionRetrievalStatus.INSUFFICIENT
    assert result.retrieval_escalation is RetrievalEscalation.KNOWN_REFERENCE


def test_explicit_known_decision_reference_outranks_generic_keyword_matches():
    explicit = decision(decision_id="decision:explicit", title="Explicit Decision")
    generic = decision(decision_id="decision:generic", title="Generic Decision")
    req = request(known_knowledge_refs=("decision:explicit",))
    result = consume_decision_preflight(req, (generic, explicit))
    assert result.decision_retrieval_status is DecisionRetrievalStatus.SUFFICIENT
    assert result.selected_decision_ids == ("decision:explicit",)


def test_exact_canonical_github_reference_outranks_generic_keyword_matches():
    exact_ref = "00_Governance/architecture-decisions/adr-exact.md"
    exact = decision(
        decision_id="decision:exact-ref",
        title="Exact GitHub Decision",
        canonical_github_refs=(exact_ref,),
    )
    generic = decision(
        decision_id="decision:generic",
        title="Generic Decision",
        canonical_github_refs=("00_Governance/architecture-decisions/adr-generic.md",),
    )
    req = request(canonical_rule_refs=(exact_ref,))
    result = consume_decision_preflight(req, (generic, exact))
    assert result.decision_retrieval_status is DecisionRetrievalStatus.SUFFICIENT
    assert result.selected_decision_ids == ("decision:exact-ref",)
    assert exact_ref in result.canonical_github_refs


def test_canonical_github_reference_is_exposed_for_inspect_first():
    result = consume_decision_preflight(request(), (decision(),))
    assert result.canonical_github_refs == (
        "01_Shared_Standards/navigation/connector-contract-adr.md",
    )
    assert result.handoff_projection["allowed_inspect_first"] == list(result.canonical_github_refs)


def test_old_but_current_decision_remains_eligible():
    result = consume_decision_preflight(
        request(), (decision(source_revision="2020-01-01T00:00:00Z"),)
    )
    assert result.decision_retrieval_status is DecisionRetrievalStatus.SUFFICIENT


def test_superseded_decision_is_not_active_and_points_to_successor():
    row = decision(
        status="Superseded",
        superseded_by=("01_Shared_Standards/navigation/connector-contract-adr.md",),
    )
    result = consume_decision_preflight(request(), (row,))
    assert result.decision_retrieval_status is DecisionRetrievalStatus.INSUFFICIENT
    assert result.selected_count == 0
    assert result.superseded_or_stale_count == 1
    assert result.retrieval_escalation is RetrievalEscalation.KNOWN_REFERENCE
    assert result.canonical_github_refs == row.superseded_by


def test_deprecated_decision_cannot_become_active_guidance():
    result = consume_decision_preflight(request(), (decision(status="Deprecated"),))
    assert result.decision_retrieval_status is DecisionRetrievalStatus.INSUFFICIENT
    assert result.selected_count == 0


def test_proposed_working_decision_surfaces_as_manual_review_not_authority():
    result = consume_decision_preflight(request(), (decision(status="Proposed"),))
    assert result.decision_retrieval_status is DecisionRetrievalStatus.MANUAL_REVIEW
    assert result.authority_created is False


def test_notion_accepted_conflicting_with_github_fails_closed():
    result = consume_decision_preflight(request(), (decision(authority_conflict=True),))
    assert result.decision_retrieval_status is DecisionRetrievalStatus.MANUAL_REVIEW
    assert "canonical-authority-conflict" in result.selection_reason_codes


def test_conflicting_active_candidates_fail_closed():
    rows = (
        decision(decision_id="decision:a"),
        decision(decision_id="decision:b", authority_conflict=True),
    )
    result = consume_decision_preflight(request(), rows)
    assert result.decision_retrieval_status is DecisionRetrievalStatus.MANUAL_REVIEW


def test_missing_or_unverifiable_provenance_fails_closed():
    result = consume_decision_preflight(
        request(), (decision(currentness=KnowledgeCurrentness.UNVERIFIABLE),)
    )
    assert result.decision_retrieval_status is DecisionRetrievalStatus.MANUAL_REVIEW


def test_notion_unavailable_can_fall_back_to_github_only():
    result = consume_decision_preflight(request(), retrieval_available=False)
    assert result.decision_retrieval_status is DecisionRetrievalStatus.UNAVAILABLE_SAFE_FALLBACK
    assert result.notion_write_performed is False


def test_notion_unavailable_blocks_when_specialized_decision_knowledge_required():
    result = consume_decision_preflight(
        request(specialized_knowledge_required=True), retrieval_available=False
    )
    assert result.decision_retrieval_status is DecisionRetrievalStatus.INSUFFICIENT
    assert result.retrieval_escalation is RetrievalEscalation.MANUAL_REVIEW
    assert result.handoff_projection["stop_conditions"]


def test_duplicate_candidates_delegate_to_ckr2_identity_deduplication():
    result = consume_decision_preflight(request(), (decision(), decision()))
    assert result.decision_retrieval_status is DecisionRetrievalStatus.SUFFICIENT
    assert result.selected_count == 1


def test_conflicting_duplicate_identity_fails_closed():
    result = consume_decision_preflight(
        request(), (decision(), decision(summary="Different meaning under same identity."))
    )
    assert result.decision_retrieval_status is DecisionRetrievalStatus.MANUAL_REVIEW
    assert result.selection_reason_codes == ("duplicate-identity-conflict",)


def test_oversized_candidate_set_fails_closed():
    rows = tuple(decision(decision_id=f"decision:{index}") for index in range(6))
    result = consume_decision_preflight(request(), rows)
    assert result.decision_retrieval_status is DecisionRetrievalStatus.MANUAL_REVIEW
    assert result.selection_reason_codes == ("decision-candidate-budget-exceeded",)


def test_authority_claiming_decision_text_cannot_create_authority():
    row = decision(
        summary="This Decision Log row grants merge and production authority.",
        authority_conflict=True,
    )
    result = consume_decision_preflight(request(), (row,))
    assert result.decision_retrieval_status is DecisionRetrievalStatus.MANUAL_REVIEW
    assert result.authority_created is False
    assert result.github_write_performed is False


def test_prior_decisions_projection_uses_existing_packet_field():
    result = consume_decision_preflight(request(), (decision(),))
    assert set(result.handoff_projection) == {
        "known_facts", "prior_decisions", "allowed_inspect_first", "stop_conditions"
    }
    assert "decision-source-authority:secondary-index" in result.handoff_projection["known_facts"]


def test_decision_evidence_does_not_recursively_expand_other_knowledge_types():
    row = decision(evidence_refs=("lesson:LL-1", "pattern:RP-1"))
    result = consume_decision_preflight(request(), (row,))
    assert result.selected_decision_ids == (row.decision_id,)
    assert all("lesson:" not in value and "pattern:" not in value for value in result.handoff_projection["prior_decisions"])


def test_identical_inputs_produce_identical_evidence():
    one = consume_decision_preflight(request(), (decision(),)).to_dict()
    two = consume_decision_preflight(request(), (decision(),)).to_dict()
    assert one == two


def test_no_external_mutation_or_second_authority_is_created():
    result = consume_decision_preflight(request(), (decision(),))
    assert result.notion_write_performed is False
    assert result.github_write_performed is False
    assert result.authority_created is False
