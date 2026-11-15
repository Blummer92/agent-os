"""Bounded CKR6 relevance regression: positive and adversarial cases."""
from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest, CodingKnowledgeCandidate, KnowledgeCurrentness,
    SufficiencyStatus, select_coding_knowledge,
)
from agent_memory_context_manager.lesson_activation_bridge import build_filtered_query
from agent_memory_context_manager.lesson_retrieval_orchestrator import orchestrate_lesson_retrieval


def _request(**kw):
    data = dict(task_reference="PR #3972 exact head", ecosystem_hints=("GitHub Actions",),
                language_hints=("Python", "YAML"),
                capability_keywords=("AI Navigation", "CKR6 mutation boundary",
                                     "trusted owner request", "fail-closed lesson preflight"),
                specialized_knowledge_required=True)
    data.update(kw)
    return CodingKnowledgeRequest(**data)


def _candidate(**kw):
    data = dict(knowledge_id="LL-TEST", source_system="notion-lessons-learned",
                source_revision="2026-11-14T00:00:00Z",
                currentness=KnowledgeCurrentness.CURRENT,
                name="CKR6 mutation gate must use verified lesson preflight",
                ecosystem="python", capability_kind="testing",
                use_when=("Check CKR6 mutation boundary admission on the exact head.",),
                canonical_github_refs=("https://github.com/Blummer92/agent-os/issues/2425",))
    data.update(kw)
    return CodingKnowledgeCandidate(**data)


def test_provider_query_uses_only_existing_controlled_area():
    query = build_filtered_query(_request())
    assert {"property": "Area", "select": {"equals": "Testing"}} in query["filter"]["and"][-1]["or"]


def test_exact_ckr6_context_selects_verified_relevant_lesson():
    result = select_coding_knowledge(_request(), (_candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.selected[0].reason_codes == ("verified-ckr6-mutation-context-match",)


def test_unrelated_or_one_anchor_is_not_sufficient():
    for name in ("Generic CI tests", "CKR6 lesson lifecycle", "Mutation testing unrelated to CKR6"):
        result = select_coding_knowledge(_request(), (_candidate(name=name, use_when=("Review ordinary tests.",)),))
        assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT


def test_unverifiable_provenance_remains_blocked():
    result = select_coding_knowledge(_request(), (_candidate(canonical_github_refs=(), currentness=KnowledgeCurrentness.UNVERIFIABLE),))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW


def test_conflicting_authority_remains_blocked():
    result = select_coding_knowledge(_request(), (_candidate(authority_conflict=True),))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW


def test_empty_retrieval_reports_bounded_counts_without_content():
    result = orchestrate_lesson_retrieval(_request(), execute_read=lambda query: {"results": []})
    assert result.retrieval_diagnostics["observed_rows"] == 0
    assert result.retrieval_diagnostics["normalized_rows"] == 0
    assert result.retrieval_diagnostics["read_count"] <= 4
    assert result.lesson_retrieval_status.value == "insufficient"
