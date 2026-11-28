"""CKR2 applicability evidence: one generic mechanism, no per-lesson matcher edits.

Labels were fixed before implementation (see mission LABELED_CASES.md).
LL-102's live Supporting Cases are the source-owned, reviewed applicability
record: a target path, a positive condition, and an exclusion. The mechanism
evaluates those cases against the request's finite signals only; lesson IDs,
titles, and source URLs never prove relevance, and a fired exclusion or a
contradicted positive case wins over every positive signal.

Older lessons without Supporting Cases keep exactly their previous behavior:
the evaluator abstains and the existing branches decide. The LL-92-shaped
variant below is explicitly synthetic: it proves only that abstention
preserves the legacy path, never that the live LL-92 record is eligible.
"""
from dataclasses import replace

import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeCandidate,
    CodingKnowledgeRequest,
    KnowledgeCurrentness,
    SufficiencyStatus,
    _match_candidate,
    evaluate_applicability,
    select_coding_knowledge,
)
from agent_memory_context_manager.lesson_activation_bridge import (
    LessonActivationSkip,
    _as_selection_candidate,
    normalize_lesson_row,
)
from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus
from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    orchestrate_lesson_retrieval,
)

REASON = "applicability-evidence-text-match"

LL102_TITLE = (
    "Keep pull-request head execution out of workflows that process "
    "trusted post-merge evidence."
)
LL102_GUARDRAIL = (
    "Do not treat read-only token permissions or passing PR tests as proof "
    "of workflow isolation. This rule does not require splitting a workflow "
    "whose triggers all run at the same trust level."
)
LL102_NEXT_TIME = (
    "Put PR-head tests in a PR-only workflow. Keep trusted processing in a "
    "separate workflow pinned to trusted source. Parse both definitions in a "
    "regression test and assert trigger, checkout, and cache isolation."
)
LL102_CASES = (
    ".github/workflows/agent-os-post-merge-learning.yml; "
    "Do not apply to a PR-only workflow that never consumes or produces "
    "trusted-run state.; "
    "Review a workflow that executes PR-head code and also processes "
    "trusted post-merge evidence."
)
LL102_REVISION = "2026-11-28T02:44:00.000Z"
LL102_REQUEST = CodingKnowledgeRequest(
    task_reference=(
        "PR #4102 exact head e72c9623b5d0e3d5516f48f14de9d9c7e1ae4164: "
        "retrieve LL-102 for the CodeQL workflow isolation repair. Keep "
        "PR-head tests in a PR-only workflow and trusted post-merge "
        "reporting in a separate workflow. This is a guidance lookup, "
        "not permission to publish or merge."
    ),
    ecosystem_hints=("agent-os", "github-actions"),
    language_hints=("yaml",),
    capability_keywords=("github-actions", "checkout trust boundary", "post-merge-learning"),
    target_path_hints=(".github/workflows/agent-os-post-merge-learning.yml",),
    known_knowledge_refs=("LL-102",),
    canonical_rule_refs=(
        "https://github.com/Blummer92/agent-os/issues/3418",
        "https://github.com/Blummer92/agent-os/pull/4102",
    ),
    specialized_knowledge_required=True,
)


def _rich(value, kind="rich_text"):
    return {"type": kind, kind: [{"type": "text", "plain_text": value, "text": {"content": value}}]}


def _select(value):
    return {"type": "select", "select": {"name": value}}


def row(number, *, title, guidance, guardrail, cases=None, revision="2026-11-28T02:44:00.000Z",
        learning_type="QA feedback", area="Governance", source="https://github.com/Blummer92/agent-os/issues/3418"):
    properties = {
        "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": number}},
        "Lesson Learned": _rich(title, "title"),
        "Status": _select("New"),
        "Surface Before Work?": {"type": "checkbox", "checkbox": True},
        "Area": _select(area),
        "Learning Type": _select(learning_type),
        "Applies To": {"type": "multi_select", "multi_select": []},
        "Source Link": {"type": "url", "url": source},
        "What To Do Next Time": _rich(guidance),
        "Guardrail": _rich(guardrail),
    }
    if cases is not None:
        properties["Supporting Cases"] = _rich(cases)
    return {
        "object": "page", "id": f"fixture-{number}", "url": f"https://www.notion.so/fixture-{number}",
        "last_edited_time": revision, "properties": properties,
    }


def ll102_row(**overrides):
    kwargs = {
        "title": LL102_TITLE, "guidance": LL102_NEXT_TIME, "guardrail": LL102_GUARDRAIL,
        "cases": LL102_CASES, "revision": LL102_REVISION,
    }
    kwargs.update(overrides)
    return row(102, **kwargs)


def _candidate_from_row(raw):
    normalized = normalize_lesson_row(raw)
    assert not isinstance(normalized, LessonActivationSkip)
    return _as_selection_candidate(normalized)


def ll102_candidate(**overrides):
    candidate = _candidate_from_row(ll102_row())
    return replace(candidate, **overrides) if overrides else candidate


def test_ll102_positive_selects_on_applicability_evidence():
    candidate = ll102_candidate()
    evaluation = evaluate_applicability(LL102_REQUEST, candidate)
    assert evaluation.matched is True
    assert evaluation.exclusions_fired == ()
    assert len(evaluation.satisfied) == 2
    assert _match_candidate(LL102_REQUEST, candidate) == (2, (REASON,))
    decision = select_coding_knowledge(LL102_REQUEST, (candidate,))
    assert decision.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert [s.candidate.knowledge_id for s in decision.selected] == ["LL-102"]
    assert decision.selected[0].reason_codes == (REASON,)


def test_ll102_positive_selects_through_the_orchestrator():
    def read(query):
        return {"results": [ll102_row()], "has_more": False, "next_cursor": None}

    result = orchestrate_lesson_retrieval(LL102_REQUEST, execute_read=read)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-102",)


def test_ll102_same_trust_negative_exclusion_wins():
    request = CodingKnowledgeRequest(
        task_reference="Review the PR-only workflow that runs PR-head tests and never touches trusted state.",
        ecosystem_hints=("agent-os", "github-actions"),
        language_hints=("yaml",),
        capability_keywords=("github-actions", "pr-only workflow", "checkout trust boundary"),
        target_path_hints=(".github/workflows/pr-tests.yml",),
        known_knowledge_refs=("LL-102",),
        canonical_rule_refs=("https://github.com/Blummer92/agent-os/pull/4102",),
        specialized_knowledge_required=True,
    )
    candidate = ll102_candidate()
    evaluation = evaluate_applicability(request, candidate)
    assert evaluation.exclusions_fired != ()
    assert evaluation.matched is False
    assert _match_candidate(request, candidate) == (0, ("applicability-exclusion-fired",))
    assert select_coding_knowledge(request, (candidate,)).selected == ()


def test_ll102_id_only_request_cannot_select():
    request = replace(
        LL102_REQUEST,
        ecosystem_hints=(), language_hints=(), capability_keywords=(),
        target_path_hints=(), canonical_rule_refs=(),
    )
    candidate = ll102_candidate()
    evaluation = evaluate_applicability(request, candidate)
    assert evaluation.matched is False
    assert evaluation.unsatisfied != ()
    assert _match_candidate(request, candidate)[0] == 0


def test_ll102_stale_record_matches_but_is_not_admitted():
    candidate = ll102_candidate(currentness=KnowledgeCurrentness.STALE)
    assert _match_candidate(LL102_REQUEST, candidate) == (2, (REASON,))
    decision = select_coding_knowledge(LL102_REQUEST, (candidate,))
    assert decision.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert decision.selected == ()
    assert decision.reason_codes == ("stale-relevant-candidate",)


def test_ll102_contradictory_guardrail_wins():
    candidate = ll102_candidate(use_when=(
        LL102_NEXT_TIME,
        "Never review a workflow that executes PR-head code and processes trusted post-merge evidence.",
    ))
    evaluation = evaluate_applicability(LL102_REQUEST, candidate)
    assert evaluation.matched is False
    assert _match_candidate(LL102_REQUEST, candidate)[0] == 0


def test_ll102_no_matcher_edit_keyed_to_identity_title_or_url():
    candidate = ll102_candidate()
    renamed = replace(
        candidate,
        knowledge_id="LL-9001",
        name="A differently worded workflow trust lesson",
        canonical_github_refs=("https://github.com/Blummer92/agent-os/issues/9999",),
    )
    assert _match_candidate(LL102_REQUEST, renamed) == (2, (REASON,))


# --- A newly added fixture lesson: no matcher change, generic mechanism only.

NEW_TITLE = "Require bounded retry budgets for flaky webhook deliveries"
NEW_GUIDANCE = (
    "Retry a failed webhook delivery only within a bounded retry budget with jitter."
)
NEW_GUARDRAIL = "Never retry without a budget cap or an idempotency key."
NEW_CASES = (
    "08_Tooling/webhook-delivery/src/retry_budget.py; "
    "Do not apply to scheduled batch exports that retry on a fixed calendar.; "
    "Retry a failed webhook delivery only within a bounded retry budget with jitter."
)


def new_lesson_candidate():
    return _candidate_from_row(row(
        9000, title=NEW_TITLE, guidance=NEW_GUIDANCE, guardrail=NEW_GUARDRAIL,
        cases=NEW_CASES, source="https://github.com/Blummer92/agent-os/issues/4026",
    ))


def new_lesson_request(*, generic_only=False, exclusion=False):
    if generic_only:
        return CodingKnowledgeRequest(
            task_reference="Fix the webhook thing.",
            ecosystem_hints=("agent-os",),
            capability_keywords=("webhook",),
            specialized_knowledge_required=True,
        )
    if exclusion:
        return CodingKnowledgeRequest(
            task_reference="Fix the scheduled batch export retry calendar.",
            ecosystem_hints=("agent-os",),
            capability_keywords=("scheduled batch exports", "fixed calendar retry"),
            target_path_hints=("08_Tooling/batch-export/src/calendar_retry.py",),
            specialized_knowledge_required=True,
        )
    return CodingKnowledgeRequest(
        task_reference="Fix flaky webhook delivery retries exceeding their budget.",
        ecosystem_hints=("agent-os",),
        language_hints=("python",),
        capability_keywords=("webhook delivery", "bounded retry budget"),
        target_path_hints=("08_Tooling/webhook-delivery/src/retry_budget.py",),
        specialized_knowledge_required=True,
    )


def test_new_fixture_lesson_selects_without_matcher_edit():
    candidate = new_lesson_candidate()
    assert evaluate_applicability(new_lesson_request(), candidate).exclusions_fired == ()
    assert _match_candidate(new_lesson_request(), candidate) == (2, (REASON,))
    decision = select_coding_knowledge(new_lesson_request(), (candidate,))
    assert [s.candidate.knowledge_id for s in decision.selected] == ["LL-9000"]


def test_new_fixture_lesson_generic_keyword_alone_cannot_select():
    candidate = new_lesson_candidate()
    assert _match_candidate(new_lesson_request(generic_only=True), candidate)[0] == 0


def test_new_fixture_lesson_exclusion_wins():
    candidate = new_lesson_candidate()
    assert _match_candidate(new_lesson_request(exclusion=True), candidate)[0] == 0


# --- Held-out set (labels fixed before implementation; no tuning on these).

HELD_TITLE = "Verify cache invalidation after schema migration"
HELD_GUIDANCE = "Invalidate cached entries after a schema migration completes."
HELD_GUARDRAIL = "Never serve stale cached entries after a migration."
HELD_CASES = (
    "08_Tooling/cache-service/src/invalidation.py; "
    "Do not apply to read-through caches that refresh on TTL expiry.; "
    "Invalidate cached entries after a schema migration completes."
)


def held_candidate():
    return _candidate_from_row(row(
        9001, title=HELD_TITLE, guidance=HELD_GUIDANCE, guardrail=HELD_GUARDRAIL,
        cases=HELD_CASES, source="https://github.com/Blummer92/agent-os/issues/4026",
    ))


def test_held_out_new_lesson_positive():
    request = CodingKnowledgeRequest(
        task_reference="Cached entries survive a schema migration.",
        ecosystem_hints=("agent-os",),
        language_hints=("python",),
        capability_keywords=("schema migration", "cache invalidation"),
        target_path_hints=("08_Tooling/cache-service/src/invalidation.py",),
        specialized_knowledge_required=True,
    )
    assert _match_candidate(request, held_candidate()) == (2, (REASON,))


def test_held_out_new_lesson_generic_only():
    request = CodingKnowledgeRequest(
        task_reference="Cache is slow.",
        ecosystem_hints=("agent-os",),
        capability_keywords=("cache",),
        specialized_knowledge_required=True,
    )
    assert _match_candidate(request, held_candidate())[0] == 0


def test_held_out_nine_cases_refuse_without_legacy_fallback():
    cases = "; ".join(f"Case number {i} about webhook delivery retry budgets" for i in range(9))
    normalized = normalize_lesson_row(row(
        9002, title=NEW_TITLE, guidance=NEW_GUIDANCE, guardrail=NEW_GUARDRAIL,
        cases=cases, source="https://github.com/Blummer92/agent-os/issues/4026",
    ))
    assert isinstance(normalized, LessonActivationSkip)
    assert normalized.reason == "invalid-supporting-cases"


def test_oversized_direct_candidate_cannot_fall_back():
    unrelated = replace(
        new_lesson_request(),
        capability_keywords=("quality-assurance",),
    )
    oversized = ll102_candidate(
        applicability_cases=tuple(f"Case {i}" for i in range(9)),
        capability_kind="quality-assurance",
    )
    assert _match_candidate(unrelated, oversized) == (0, ("oversized-applicability-record",))


def test_held_out_lesson_without_cases_keeps_legacy_generic_path():
    # Synthetic LL-92-shaped candidate: generic metadata only, no cases.
    # Legacy ecosystem-capability behavior is preserved unchanged.
    candidate = CodingKnowledgeCandidate(
        knowledge_id="LL-92",
        source_system="notion-lessons-learned",
        source_revision="2026-11-20T05:04:32.565Z",
        currentness=KnowledgeCurrentness.CURRENT,
        name="Decide in parallel, record on the issue",
        ecosystem="agent-os",
        library_name=None,
        capability_kind="quality-assurance",
        use_when=("Parallelize read-only evidence gathering.", "Investigate in parallel."),
        canonical_github_refs=("https://github.com/Blummer92/agent-os/issues/3099",),
    )
    request = CodingKnowledgeRequest(
        task_reference="Run parallel investigations.",
        ecosystem_hints=("agent-os",),
        capability_keywords=("quality-assurance",),
        specialized_knowledge_required=True,
    )
    assert evaluate_applicability(request, candidate).matched is False
    assert _match_candidate(request, candidate) == (2, ("ecosystem-capability-match",))


def test_supporting_links_split_is_separately_tested():
    # One comma-joined rich-text item: valid pieces are admitted as
    # supporting refs, fragment pieces are dropped, primary still required.
    joined = (
        "https://github.com/Blummer92/agent-os/issues/3277, "
        "https://github.com/Blummer92/agent-os/issues/3200, "
        "https://github.com/Blummer92/agent-os/pull/4102#issuecomment-7198014711"
    )
    raw = ll102_row(cases=None)
    raw["properties"]["Supporting Source Links"] = _rich(joined)
    normalized = normalize_lesson_row(raw)
    assert not isinstance(normalized, LessonActivationSkip)
    assert normalized.canonical_github_refs == (
        "https://github.com/Blummer92/agent-os/issues/3418",
        "https://github.com/Blummer92/agent-os/issues/3277",
        "https://github.com/Blummer92/agent-os/issues/3200",
    )
    assert normalized.dropped_supporting_refs == (
        "https://github.com/Blummer92/agent-os/pull/4102#issuecomment-7198014711",
    )


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("docs/layout.md", True),
        ("./docs/layout.md", True),
        ("docs/layout.md.backup", False),
        ("archive/docs/layout.md", False),
        ("docs/layout", False),
        ("layout.md", False),
        ("docs/Layout.md", False),
        ("/docs/layout.md", False),
        ("../docs/layout.md", False),
    ],
)
def test_applicability_file_case_requires_the_same_repo_relative_path(hint, expected):
    request = CodingKnowledgeRequest(
        task_reference="Review print layout",
        capability_keywords=("document layout",),
        target_path_hints=(hint,),
    )
    candidate = ll102_candidate(
        name="Synthetic document layout",
        applicability_cases=("docs/layout.md", "Review document layout"),
        use_when=("Review document layout.",),
        avoid_when=(),
    )
    result = evaluate_applicability(request, candidate)
    assert result.matched is expected
    if not expected:
        assert result.unsatisfied == (0,)
        assert _match_candidate(request, candidate)[0] == 0


@pytest.mark.parametrize(
    "cases",
    [
        ("Do not apply to a PDF export",),
        ("docs/layout.md", "Do not apply to a PDF export"),
    ],
)
def test_applicability_requires_positive_task_evidence_even_with_matching_metadata(cases):
    request = CodingKnowledgeRequest(
        task_reference="Review print layout",
        ecosystem_hints=("agent-os",),
        capability_keywords=("quality-assurance",),
        target_path_hints=("docs/layout.md",),
    )
    candidate = ll102_candidate(
        name="Synthetic document layout",
        applicability_cases=cases,
        use_when=("Review document layout.",),
        avoid_when=(),
    )
    result = evaluate_applicability(request, candidate)
    assert not result.matched
    assert result.reason_codes == ("applicability-positive-case-missing",)
    assert _match_candidate(request, candidate) == (0, result.reason_codes)


@pytest.mark.parametrize(
    ("task", "capability_hints", "matched"),
    [
        ("Fix a spelling mistake in the file", ("spelling correction",), False),
        ("Review the file", (), False),
        ("Check document layout for digital PDF export", ("digital PDF export",), True),
    ],
    ids=["spelling-edit", "path-only", "actual-pdf-export"],
)
def test_matching_filename_is_scope_only_not_topic_evidence(task, capability_hints, matched):
    path = "docs/document_layout.md"
    request = CodingKnowledgeRequest(
        task_reference=task,
        capability_keywords=capability_hints,
        target_path_hints=(path,),
        specialized_knowledge_required=True,
    )
    candidate = ll102_candidate(
        name="Synthetic document layout",
        applicability_cases=(path, "Check document layout for digital PDF export"),
        use_when=("Check document layout for digital PDF export.",),
        avoid_when=(),
    )
    result = evaluate_applicability(request, candidate)
    assert result.matched is matched
    assert (0, (path,)) in result.evidence
    decision = select_coding_knowledge(request, (candidate,))
    assert (decision.sufficiency_status is SufficiencyStatus.SUFFICIENT) is matched
    if not matched:
        assert result.unsatisfied == (1,)
        assert decision.selected == ()


def _document_export_candidate(selection_guidance="Check document layout for digital PDF export."):
    return ll102_candidate(
        name="Synthetic digital PDF export",
        applicability_cases=("Check document layout for digital PDF export",),
        use_when=(selection_guidance, "Keep report formatting unchanged."),
        avoid_when=(),
    )


def test_distinct_task_hints_cannot_be_combined_into_one_positive_case():
    candidate = _document_export_candidate()
    unrelated = CodingKnowledgeRequest(
        task_reference="Correct typos and adjust menu layout",
        ecosystem_hints=("agent-os",),
        capability_keywords=("document typos", "menu layout"),
        specialized_knowledge_required=True,
    )
    assert _match_candidate(unrelated, candidate) == (
        0, ("applicability-conditions-unsatisfied",)
    )
    assert not select_coding_knowledge(unrelated, (candidate,)).selected
    actual_export = replace(unrelated, capability_keywords=("digital PDF export",))
    assert _match_candidate(actual_export, candidate) == (2, (REASON,))


@pytest.mark.parametrize("guidance_slot", ["primary", "avoid"])
def test_opposite_guidance_refuses_even_with_matching_applicability(guidance_slot):
    contradiction = "Do not check document layout for digital PDF export."
    candidate = (
        _document_export_candidate(contradiction)
        if guidance_slot == "primary"
        else replace(_document_export_candidate(), avoid_when=(contradiction,))
    )
    request = CodingKnowledgeRequest(
        task_reference="Validate a digital PDF export",
        capability_keywords=("digital PDF export",),
        specialized_knowledge_required=True,
    )
    assert _match_candidate(request, candidate) == (
        0, ("applicability-contradicted-guidance",)
    )
    assert not select_coding_knowledge(request, (candidate,)).selected


@pytest.mark.parametrize("prefix", ["Don't", "Don’t", "Don‘t", "Donʼt", "Do not"])
def test_contracted_exclusion_refuses_instead_of_helping_match(prefix):
    positive = "Preserve webhook delivery retries"
    candidate = ll102_candidate(
        applicability_cases=(f"{prefix} apply to a PR-only workflow.", positive),
    )
    request = replace(LL102_REQUEST, capability_keywords=("pr-only workflow", positive))
    result = evaluate_applicability(request, candidate)
    assert result.exclusions_fired == (0,)
    assert _match_candidate(request, candidate) == (0, ("applicability-exclusion-fired",))


@pytest.mark.parametrize("case", ["./docs/Layout.md", "./docs/Layout.md.", "docs/Layout.md"])
@pytest.mark.parametrize("hint, matches", [
    ("./docs/Layout.md", True), ("docs/Layout.md", True),
    ("docs/layout.md", False), ("other/docs/Layout.md", False),
])
def test_path_case_prefix_and_punctuation_preserve_exact_scope(case, hint, matches):
    positive = "Preserve webhook delivery retries"
    candidate = ll102_candidate(applicability_cases=(case, positive))
    request = replace(LL102_REQUEST, target_path_hints=(hint,), capability_keywords=(positive,))
    result = evaluate_applicability(request, candidate)
    assert result.matched is matches
    assert result.unsatisfied == (() if matches else (0,))


def test_exclusion_requires_coherent_task_evidence():
    positive = "Preserve webhook delivery retries"
    candidate = ll102_candidate(applicability_cases=(
        "Do not apply to Python unit tests in the batch exporter.",
        positive,
    ))
    unrelated = replace(
        LL102_REQUEST, language_hints=("python",), capability_keywords=("integration tests", positive),
    )
    assert evaluate_applicability(unrelated, candidate).matched is True
    language_only = replace(unrelated, language_hints=("Python unit tests",))
    assert evaluate_applicability(language_only, candidate).matched is True
    related = replace(unrelated, capability_keywords=("Python unit tests", positive))
    assert evaluate_applicability(related, candidate).exclusions_fired == (0,)


@pytest.mark.parametrize("topic", ["PDF", "PR", "API", "YML", "CI"])
def test_exclusion_recognizes_short_technical_terms(topic):
    positive = "Preserve webhook delivery retries"
    candidate = ll102_candidate(applicability_cases=(f"Do not apply to {topic} export.", positive))
    request = replace(LL102_REQUEST, capability_keywords=(f"{topic} export", positive))
    assert evaluate_applicability(request, candidate).exclusions_fired == (0,)
    unrelated = replace(request, capability_keywords=("CSV export", positive))
    assert evaluate_applicability(unrelated, candidate).matched is True


@pytest.mark.parametrize("field", [
    None, {"type": "select", "select": {"name": "webhook delivery"}},
    {"type": "rich_text", "rich_text": [{"text": {"content": "missing plain_text"}}]},
    _rich("; ;"), _rich("x" * 513), _rich("x" * 50000), _rich(" " * 50000),
])
def test_present_invalid_supporting_cases_refuse_normalization(field):
    raw = ll102_row()
    raw["properties"]["Supporting Cases"] = field
    normalized = normalize_lesson_row(raw)
    assert isinstance(normalized, LessonActivationSkip)
    assert normalized.reason == "invalid-supporting-cases"


@pytest.mark.parametrize("case, hint", [
    ("PDF export", "PDF export"),
    ("Using this schema", "Using this migration"),
])
def test_positive_cases_require_two_distinctive_long_tokens(case, hint):
    candidate = ll102_candidate(applicability_cases=(case,))
    request = replace(LL102_REQUEST, capability_keywords=(hint,))
    result = evaluate_applicability(request, candidate)
    assert result.reason_codes == ("applicability-conditions-unsatisfied",)
    assert result.evidence == ()


def test_evidence_tie_is_stable_when_hints_are_reordered():
    candidate = ll102_candidate(applicability_cases=("webhook delivery retry budget",))
    hints = ("delivery retry", "budget webhook")
    request = replace(LL102_REQUEST, capability_keywords=hints)
    forward = evaluate_applicability(request, candidate)
    backward = evaluate_applicability(replace(request, capability_keywords=hints[::-1]), candidate)
    assert forward == backward
    assert forward.evidence == ((0, ("delivery", "retry")),)


def test_eight_provider_cases_are_preserved_and_evaluated():
    cases = tuple(f"Verify webhook delivery case {index}." for index in range(8))
    raw = ll102_row(cases="; ".join(cases[:4]) + "\n" + "\n".join(cases[4:]))
    candidate = _candidate_from_row(raw)
    assert candidate.applicability_cases == cases
    request = replace(LL102_REQUEST, capability_keywords=("webhook delivery",))
    result = evaluate_applicability(request, candidate)
    assert result.matched is True
    assert result.satisfied == tuple(range(8))


@pytest.mark.parametrize("path", [
    "/docs/document_layout.md",
    "../docs/document_layout.md",
    "docs/../document_layout.md",
    "docs/./document_layout.md",
    "docs//document_layout.md",
])
def test_malformed_file_case_cannot_match_even_an_identical_hint(path):
    candidate = ll102_candidate(applicability_cases=(path, "Preserve document layout"))
    request = replace(
        LL102_REQUEST, target_path_hints=(path,), capability_keywords=("document layout",),
    )
    result = evaluate_applicability(request, candidate)
    assert result.reason_codes == ("applicability-conditions-unsatisfied",)
    assert result.unsatisfied == (0,)
    assert _match_candidate(request, candidate)[0] == 0


@pytest.mark.parametrize("case", [
    "docs/document_layout.md.backup",
    "docs/document_layout.md..",
    "docs/document_layout.md?v=1",
    "components/document_layout.tsx",
    "docs/document layout.md",
    "docs/document_layout.md?mode=two words",
    "document_layout.md?v=1",
    "document_layout.md",
])
def test_file_shaped_case_is_never_evidenced_by_filename_words(case):
    candidate = ll102_candidate(applicability_cases=(case, "Review document layout"))
    request = replace(
        LL102_REQUEST, target_path_hints=("other/place.py",),
        capability_keywords=("document layout",),
    )
    assert _match_candidate(request, candidate) == (0, ("applicability-conditions-unsatisfied",))
    evaluation = evaluate_applicability(request, candidate)
    assert evaluation.unsatisfied == (0,)
    assert evaluation.evidence == ((1, ("document", "layout")),)


@pytest.mark.parametrize("case, allowed", [
    ("docs/document_layout.md.backup", False),
    ("docs/document_layout.md..", False),
    ("docs/document_layout.md?v=1", False),
    ("components/document_layout.tsx", True),
    ("document_layout.md", True),
    ("./document_layout.md.", True),
])
def test_file_shaped_case_validates_syntax_before_comparison(case, allowed):
    candidate = ll102_candidate(applicability_cases=(case, "Review document layout"))
    hint = "document_layout.md" if case.startswith("./") else case
    if case.endswith(".."):
        hint = case[:-1]  # Would match after removing one terminal period.
    request = replace(
        LL102_REQUEST, target_path_hints=(hint,), capability_keywords=("document layout",),
    )
    evaluation = evaluate_applicability(request, candidate)
    assert evaluation.matched is allowed
    if allowed:
        assert evaluation.evidence[0] == (0, (case,))
    else:
        assert evaluation.unsatisfied == (0,)


@pytest.mark.parametrize("directive", ["Must not apply", "Never use this", "Should not apply"])
def test_negative_directives_veto_without_adding_positive_evidence(directive):
    candidate = ll102_candidate(applicability_cases=(
        f"{directive} to a PR-only workflow.", "Review document layout",
    ))
    request = replace(LL102_REQUEST, capability_keywords=("pr-only workflow", "document layout"))
    assert _match_candidate(request, candidate) == (0, ("applicability-exclusion-fired",))
    assert evaluate_applicability(request, candidate).exclusions_fired == (0,)
    unrelated = replace(request, capability_keywords=("document layout",))
    assert _match_candidate(unrelated, candidate) == (2, (REASON,))


@pytest.mark.parametrize("segments", [[], [" "], [" ", "\t\n", ""]])
def test_empty_valid_rich_text_has_no_structured_cases(segments):
    raw = ll102_row()
    raw["properties"]["Supporting Cases"]["rich_text"] = [
        {"plain_text": segment} for segment in segments
    ]
    candidate = _candidate_from_row(raw)
    assert candidate.applicability_cases == ()
    request = replace(LL102_REQUEST, capability_keywords=(candidate.capability_kind,))
    assert _match_candidate(request, candidate) == (2, ("ecosystem-capability-match",))


@pytest.mark.parametrize("separator", [";", "\n"])
def test_rich_text_formatting_runs_are_not_case_boundaries(separator):
    raw = ll102_row()
    raw["properties"]["Supporting Cases"]["rich_text"] = [
        {"plain_text": segment} for segment in (
            "Do not apply to a PR-only workflow.", separator, "Review docu", "ment layout.",
        )
    ]
    assert _candidate_from_row(raw).applicability_cases == (
        "Do not apply to a PR-only workflow.", "Review document layout.",
    )
    raw["properties"]["Supporting Cases"]["rich_text"].pop(1)
    assert _candidate_from_row(raw).applicability_cases == (
        "Do not apply to a PR-only workflow.Review document layout.",
    )


def test_prose_that_mentions_a_filename_stays_a_text_case():
    candidate = ll102_candidate(applicability_cases=("Review docs/document_layout.md for print.",))
    request = replace(
        LL102_REQUEST, target_path_hints=("other/place.py",),
        capability_keywords=("document layout",),
    )
    evaluation = evaluate_applicability(request, candidate)
    assert evaluation.matched
    assert evaluation.evidence == ((0, ("document", "layout")),)
