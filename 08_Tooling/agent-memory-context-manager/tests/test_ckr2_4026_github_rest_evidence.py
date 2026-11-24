"""#4026 synthetic REST evidence mechanism QA; no live lesson applicability claim."""
from dataclasses import replace
import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeCandidate, CodingKnowledgeRequest, KnowledgeCurrentness,
    SufficiencyStatus, select_coding_knowledge,
)
from agent_memory_context_manager.lesson_activation_bridge import (
    SELECTION_BASIS_VALUES, describe_selection_basis,
)
from agent_memory_context_manager.lesson_preflight import LessonRecordEvidence

SOURCE = ("https://github.com/Blummer92/agent-os/issues/4026",)
PAGINATION = ("GitHub issue comment pagination", "duplicate record detection")
RECEIPTS = ("bounded HTTP GET response limits", "timestamp provenance")


def request(hints=PAGINATION, **overrides):
    fields = dict(task_reference="PR #4106 exact head synthetic evidence review",
                  ecosystem_hints=("GitHub REST API", "Python"),
                  language_hints=("Python",), capability_keywords=hints,
                  specialized_knowledge_required=True)
    fields.update(overrides)
    return CodingKnowledgeRequest(**fields)


def candidate(kind="pagination", **overrides):
    title, guidance = (
        ("GitHub issue comment pagination",
         "Reject duplicate GitHub comment IDs across paginated pages and verify complete page records.")
        if kind == "pagination" else
        ("GitHub REST bounded HTTP response evidence",
         "Reject oversized GitHub HTTP response bytes and verify edited timestamp provenance.")
    )
    fields = dict(knowledge_id="LL-SYNTHETIC", source_system="notion-lessons-learned",
                  source_revision="2026-11-24T00:00:00Z",
                  currentness=KnowledgeCurrentness.CURRENT, name=title,
                  ecosystem="python", library_name=None, capability_kind="testing",
                  keywords=(), use_when=(guidance,), avoid_when=(),
                  canonical_github_refs=SOURCE)
    fields.update(overrides)
    return CodingKnowledgeCandidate(**fields)


@pytest.mark.parametrize("kind,hints", [("pagination", PAGINATION), ("receipt", RECEIPTS)])
def test_strict_source_owned_positive(kind, hints):
    result = select_coding_knowledge(request(hints), (candidate(kind),))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.selected[0].reason_codes == ("github-rest-evidence-text-match",)


@pytest.mark.parametrize("hints", [
    (), ("testing",), ("GitHub issue comment pagination",),
    ("duplicate record detection",), ("bounded HTTP GET response limits",),
    ("timestamp provenance",),
])
def test_partial_or_generic_hints_cannot_select(hints):
    result = select_coding_knowledge(request(hints), (candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT


@pytest.mark.parametrize("change", [
    {"name": "Notion curriculum page pagination"},
    {"name": "Failed PR repair CKR6 retry guidance"},
    {"name": "GitHub issue comment records"},
    {"use_when": ("GitHub comments can be paginated.",)},
    {"use_when": ("Never reject duplicate GitHub comment IDs across pages.",)},
    {"source_system": "untrusted-external"},
    {"ecosystem": "typescript"},
])
def test_unrelated_or_negated_source_owned_mechanism_fails(change):
    result = select_coding_knowledge(request(), (candidate(**change),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT


@pytest.mark.parametrize("change", [
    {"currentness": KnowledgeCurrentness.STALE},
    {"currentness": KnowledgeCurrentness.UNVERIFIABLE},
    {"authority_conflict": True},
])
def test_currentness_and_authority_still_block(change):
    result = select_coding_knowledge(request(), (candidate(**change),))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW


def test_missing_source_and_duplicate_identity_fail_closed():
    no_source = select_coding_knowledge(request(), (candidate(canonical_github_refs=()),))
    assert no_source.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    first = candidate()
    conflicting = replace(first, source_revision="2026-11-25T00:00:00Z")
    result = select_coding_knowledge(request(), (first, conflicting))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW


def test_no_source_evidence_is_still_insufficient():
    result = select_coding_knowledge(request(), ())
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT


def test_budget_and_determinism():
    items = tuple(candidate(knowledge_id=f"LL-{i}") for i in range(6))
    result = select_coding_knowledge(request(), items)
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    items = items[:3]
    assert select_coding_knowledge(request(), items).to_json() == select_coding_knowledge(
        request(), tuple(reversed(items))
    ).to_json()


def test_observational_basis_remains_generic_not_authority():
    lesson = LessonRecordEvidence(
        lesson_id="LL-SYNTHETIC", source_revision="2026-11-24T00:00:00Z",
        title="GitHub issue comment pagination", ecosystem="python",
        capability_kind="testing", status="Applied", surface_before_work=True,
        currentness=KnowledgeCurrentness.CURRENT,
        what_to_do_next_time="Reject duplicate GitHub comment IDs across paginated pages and verify complete page records.",
        guardrail="Do not trust incomplete GitHub pages.", canonical_github_refs=SOURCE,
        evidence_refs=(),
    )
    basis = describe_selection_basis(request(), (lesson,), identity_route=False)
    assert (basis.basis, basis.best_bucket, basis.tied_identities) == ("generic-unique", 2, 1)
    assert len(SELECTION_BASIS_VALUES) == 8
