"""LL-95 discovery regression: catalog text and a synthetic candidate pool."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest, KnowledgeCurrentness, SufficiencyStatus, select_coding_knowledge,
)
from agent_memory_context_manager.lesson_activation_bridge import _as_selection_candidate, normalize_lesson_row
from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus
from agent_memory_context_manager.lesson_retrieval_orchestrator import orchestrate_lesson_retrieval

TITLE = "Preserve explicitly requested library coverage within lesson-ranking ties"
GUIDANCE = (
    "Within the same relevance bucket, preserve the widest coverage of explicitly "
    "requested libraries before truncating. Keep the existing deterministic order "
    "when coverage is equal."
)
GUARDRAIL = (
    "Never promote a lower relevance bucket or bypass provenance to gain coverage. "
    "Keep the existing candidate and selection limits. If reordering changes which "
    "lesson IDs make the cutoff, replay the original shortlist in its original order. "
    "Keep any prior refusal unless missing required-library coverage was the only reason."
)
REVISION = "2026-11-24T20:31:00.000Z"
TASKS = (
    ("Find why a tied shortlist drops the only result for a requested library.",
     ("lesson-selection", "library coverage")),
    ("Fix leap-day rounding in the school calendar.", ("date arithmetic", "calendar week rollover")),
    ("Fix a library coverage report that drops test files.", ("coverage reporting", "library coverage")),
    ("Fix lesson selection for expired records.", ("lesson-selection", "revision checking")),
)


def row(number=95, *, title=TITLE, guidance=GUIDANCE, surface=True):
    def rich(value, kind="rich_text"):
        return {"type": kind, kind: [{"plain_text": value}]}

    def selected(value):
        return {"type": "select", "select": {"name": value}}

    return {
        "object": "page", "id": f"fixture-{number}", "last_edited_time": REVISION,
        "properties": {
            "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": number}},
            "Lesson Learned": rich(title, "title"),
            "Status": selected("New"),
            "Surface Before Work?": {"type": "checkbox", "checkbox": surface},
            "Area": selected("Governance"),
            "Learning Type": selected("Testing lesson"),
            "Applies To": {"type": "multi_select", "multi_select": []},
            "Source Link": {"type": "url", "url": "https://github.com/Blummer92/agent-os/issues/4026"},
            "What To Do Next Time": rich(guidance),
            "Guardrail": rich(GUARDRAIL),
        },
    }


def request(case=0, *, testing=False):
    task, hints = TASKS[case]
    return CodingKnowledgeRequest(
        task_reference=task, ecosystem_hints=("agent-os",), language_hints=("Python",),
        capability_keywords=(("testing",) if testing else ()) + hints,
        specialized_knowledge_required=True,
    )


def replay(req, population):
    return orchestrate_lesson_retrieval(
        req, execute_read=lambda _: {"results": population, "has_more": False, "next_cursor": None},
    )


@pytest.mark.parametrize("testing", [False, True])
@pytest.mark.parametrize("case", range(len(TASKS)))
def test_matched_requests_through_ckr11(case, testing):
    population = [
        row(i, title="Generic testing recommendation", guidance="Test failure behavior.")
        for i in range(1, 88)
    ] + [row()]
    result = replay(request(case, testing=testing), population)
    if case == 0:
        assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
        assert result.selected_lesson_ids == ("LL-95",)
        assert result.selection.selected[0].candidate.source_revision == REVISION
        assert result.retrieval_diagnostics["selection_basis"] == "generic-unique"
    else:
        assert "LL-95" not in result.selected_lesson_ids
        if testing:
            assert result.selection_reason_codes == ("generic-relevance-unverified",)


@pytest.mark.parametrize("case", [1, 2, 3])
def test_generic_testing_cannot_surface_mechanism_lesson_even_when_alone(case):
    assert replay(request(case, testing=True), [row()]).selected_lesson_ids == ()


@pytest.mark.parametrize(("title", "guidance"), [
    ("Preserve explicitly requested library coverage in a calendar report", GUIDANCE),
    ("Do not preserve explicitly requested library coverage within lesson-ranking ties", GUIDANCE),
    (TITLE, "Within the same relevance bucket, never preserve coverage before truncating."),
    (TITLE, "Within the same relevance bucket, preserve coverage of requested libraries "
            "before truncating only if that reduces library coverage."),
    (TITLE, "Quote the title and run all library coverage tests."),
    (TITLE, GUIDANCE + " Actually, never preserve coverage."),
])
def test_title_and_affirmative_guidance_are_required_even_with_testing(title, guidance):
    assert replay(request(testing=True), [row(title=title, guidance=guidance)]).selected_lesson_ids == ()


def test_identity_and_exact_spelling_are_not_required():
    result = replay(request(), [row(
        70, title="Maintain coverage for requested libraries within lesson ranking ties",
        guidance="Within a relevance bucket, maintain coverage across requested libraries "
                 "before cutting the shortlist.",
    )])
    assert result.selected_lesson_ids == ("LL-70",)
    assert result.authority_created is False


def test_natural_prose_alone_does_not_qualify_a_lesson():
    req = replace(request(), capability_keywords=())
    assert replay(req, [row()]).selected_lesson_ids == ()


def test_existing_generic_selection_for_unrelated_lesson_is_preserved():
    result = replay(request(1, testing=True), [
        row(11, title="Test calendar boundaries", guidance="Check the calendar week."),
    ])
    assert result.selected_lesson_ids == ("LL-11",)


def test_generic_ambiguity_is_not_overridden_for_independent_signals():
    others = []
    for i in range(1, 5):
        item = row(i, title="Other mechanism", guidance="Test shortlist behavior.")
        item["properties"]["Applies To"]["multi_select"] = [{"name": "lesson-selection"}]
        others.append(item)
    result = replay(request(testing=True), [*others, row()])
    assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert result.selection_reason_codes == ("generic-relevance-unverified",)


def test_currentness_source_conflict_and_activation_holds():
    ordinary = row()
    missing_source = deepcopy(ordinary)
    missing_source["properties"]["Source Link"]["url"] = None
    result = replay(request(), [missing_source])
    assert result.selected_lesson_ids == ()
    assert result.selection_reason_codes == ("unverifiable-relevant-candidate",)
    assert replay(request(), [row(surface=False)]).selected_lesson_ids == ()

    duplicate = deepcopy(ordinary)
    duplicate["last_edited_time"] = "2026-11-23T20:31:00.000Z"
    conflict = replay(request(), [ordinary, duplicate])
    assert conflict.selected_lesson_ids == ()
    assert conflict.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW

    candidate = _as_selection_candidate(normalize_lesson_row(ordinary))
    for changed in (
        replace(candidate, currentness=KnowledgeCurrentness.STALE),
        replace(candidate, authority_conflict=True),
    ):
        result = select_coding_knowledge(request(), (changed,))
        assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
        assert not result.selected


def test_known_id_does_not_admit_an_unrelated_lesson():
    req = replace(request(1, testing=True), known_knowledge_refs=("LL-95",))
    assert replay(req, [row()]).selected_lesson_ids == ()


def test_lookalike_from_another_source_does_not_get_mechanism_match():
    candidate = _as_selection_candidate(normalize_lesson_row(row()))
    result = select_coding_knowledge(
        request(testing=True), (replace(candidate, source_system="local-notes"),),
    )
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert not result.selected


# Only public request and receipt metadata is frozen. This is not a snapshot
# of private Notion data. The mixed population below is a test fixture and
# the earlier request is replayed against the newly eligible catalog entry.
_HISTORICAL = [
    json.loads(line) for line in (
        Path(__file__).parent / "fixtures" / "ckr2_4026_historical_requests.jsonl"
    ).read_text(encoding="utf-8").splitlines()
]
_HINT_FIELDS = (
    "ecosystem_hints", "language_hints", "library_hints", "capability_keywords",
    "target_path_hints", "canonical_rule_refs", "known_knowledge_refs",
)


def _recorded_request(record):
    raw = record["request"]
    return CodingKnowledgeRequest(
        task_reference=raw["task_reference"],
        specialized_knowledge_required=raw["specialized_knowledge_required"],
        **{name: tuple(raw.get(name, ())) for name in _HINT_FIELDS},
    )


def _mixed_corpus():
    special = {10, 51, 61, 80}
    rows = [
        row(i, title="Generic testing recommendation", guidance="Test failure behavior.")
        for i in range(1, 88) if i not in special
    ]
    # Public source refs and revision identities are pinned. Instructional text
    # for older lessons is synthetic; it is not a copy of the Notion rows.
    for number, ref, revision, title, guide in (
        (10, "pull/1366", "2026-11-15T00:41:00.000Z",
         "CKR7 enrichment fixture", "Preserve distinct evidence."),
        (51, "issues/1362", "2026-11-15T02:52:00.000Z",
         "CKR6 mutation boundary fixture", "Re-enter lesson review."),
        (61, "issues/1865", "2026-11-15T00:45:00.000Z",
         "PR reconciliation fixture", "Git refresh reconciliation."),
        (80, "issues/1865", "2026-11-19T22:41:00.000Z",
         "Pull request reconciliation fixture", "Git refresh merge-tree."),
    ):
        item = row(number, title=title, guidance=guide)
        item["last_edited_time"] = revision
        item["properties"]["Source Link"]["url"] = f"https://github.com/Blummer92/agent-os/{ref}"
        rows.append(item)
    return [*rows, row()]


def _replay_public_request(req, population):
    reads = []

    def read(query):
        reads.append(query)
        # Emulate exact-ID and active-snapshot queries without manufacturing a
        # provider success or sending any network requests.
        id_clauses = query["filter"].get("or")
        if id_clauses:
            wanted = {clause["unique_id"]["equals"] for clause in id_clauses}
            results = [
                value for value in population
                if value["properties"]["Lesson ID"]["unique_id"]["number"] in wanted
            ]
        else:
            results = [
                value for value in population
                if value["properties"]["Surface Before Work?"]["checkbox"]
            ]
        return {"results": results, "has_more": False, "next_cursor": None}

    return orchestrate_lesson_retrieval(req, execute_read=read), reads


@pytest.mark.parametrize("record", _HISTORICAL, ids=lambda record: record["id"])
def test_public_request_regression(record):
    req = _recorded_request(record)
    group = record["group"]
    population = _mixed_corpus()
    if group in {"provenance-hold", "provenance-restored"}:
        for number in (67, 78, 83, 91):
            if number == 83 and group == "provenance-restored":
                continue
            # Explicitly synthetic source rows; only the repaired/missing
            # provenance conditions and request/results come from the receipts.
            item = row(number, title="Governed lesson-read routing fixture",
                       guidance="Require verified reader binding before routing.")
            item["properties"]["Learning Type"]["select"]["name"] = "Scope/permission lesson"
            if number != 91 and group == "provenance-hold":
                item["properties"]["Source Link"]["url"] = None
                item["properties"]["Supporting Source Links"] = {
                    "type": "rich_text", "rich_text": [{
                        "plain_text": "https://github.com/Blummer92/agent-os/issues/3973",
                    }],
                }
            population = [
                x for x in population
                if x["properties"]["Lesson ID"]["unique_id"]["number"] != number
            ]
            population.append(item)
    if group == "incomplete-read-hold":
        # Simulate incomplete provider evidence, not the obsolete page bound.
        result = orchestrate_lesson_retrieval(
            req, execute_read=lambda _: {"results": population[:1], "has_more": True},
        )
        reads = []
    else:
        result, reads = _replay_public_request(req, population)
    if group == "tie":
        assert not req.known_knowledge_refs and not req.library_hints
        assert result.selected_lesson_ids == ("LL-95",)
        assert result.selection.selected[0].candidate.source_revision == REVISION
        without_lesson, _ = _replay_public_request(req, _mixed_corpus()[:-1])
        assert without_lesson.selected_lesson_ids == ()
    elif group == "refresh-alias":
        assert not req.known_knowledge_refs and not req.library_hints
        assert set(result.selected_lesson_ids) == {"LL-61", "LL-80"}
        assert result.retrieval_diagnostics["selection_basis"] == "generic-unique"
        assert all(
            item.reason_codes == ("pr-refresh-reconciliation-text-match",)
            for item in result.selection.selected
        )
    else:
        observed = record["observed"]
        assert result.lesson_retrieval_status.value == observed["status"]
        assert set(result.selected_lesson_ids) == set(observed["selected_lesson_ids"])
        assert result.selection_reason_codes == tuple(observed["reason_codes"])
        if req.known_knowledge_refs:
            assert bool(reads[0]["filter"]["or"])
        if group in {"refresh", "mutation-boundary"}:
            assert {
                item.candidate.knowledge_id: (item.candidate.source_revision, item.reason_codes)
                for item in result.selection.selected
            } == {
                item["lesson_id"]: (item["source_revision"], tuple(item["selection_reason_codes"]))
                for item in observed["selected_lessons"]
            }
    assert not result.authority_created


@pytest.mark.parametrize("missing", range(3))
def test_each_historical_intent_hint_is_required(missing):
    req = _recorded_request(_HISTORICAL[0])
    hints = tuple(term for i, term in enumerate(req.capability_keywords) if i != missing)
    # Same exact historical prose and paths, but one structured signal absent.
    req = replace(req, capability_keywords=("testing", *hints))
    assert replay(req, [row()]).selected_lesson_ids == ()


def test_historical_hint_aliases_are_normalized_but_not_substrings():
    req = _recorded_request(_HISTORICAL[0])
    normalized = replace(req, capability_keywords=tuple(
        " " + term.upper() + " " for term in req.capability_keywords
    ))
    assert replay(normalized, [row()]).selected_lesson_ids == ("LL-95",)
    negated = replace(req, capability_keywords=tuple(
        "not " + term for term in req.capability_keywords
    ))
    assert replay(negated, [row()]).selected_lesson_ids == ()


@pytest.mark.parametrize("hints", [
    ("lesson-selection", "explicit multi-library coverage"),
    ("deterministic lesson ranking", "library coverage", "bounded candidate selection"),
    ("deterministic lesson ranking", "explicit multi-library coverage",
     "bounded candidate selection extra"),
])
def test_partial_alias_families_do_not_combine(hints):
    req = replace(request(), capability_keywords=("testing", *hints))
    assert replay(req, [row()]).selected_lesson_ids == ()


def test_four_specific_matches_still_require_manual_review():
    result = replay(request(), [row(i) for i in [89, 95, 97, 99]])
    assert result.selected_lesson_ids == ()
    assert result.selection_reason_codes == ("generic-relevance-unverified",)
    assert result.retrieval_diagnostics["best_bucket_tied_identities"] == 4


def test_historical_activation_and_provenance_exclusions_still_hold():
    req = _recorded_request(_HISTORICAL[0])
    inactive = row(surface=False)
    inactive["properties"]["Status"]["select"] = None
    result, _ = _replay_public_request(req, [inactive])
    assert result.selected_lesson_ids == ()
    addressed = replace(req, known_knowledge_refs=("LL-95",))
    result, reads = _replay_public_request(addressed, [inactive])
    assert result.selected_lesson_ids == ()
    assert len(reads) == 2
    invalid = row()
    invalid["properties"]["Source Link"]["url"] = None
    result, _ = _replay_public_request(req, [invalid])
    assert result.selection_reason_codes == ("unverifiable-relevant-candidate",)


@pytest.mark.parametrize("contradiction", [
    "Never preserve coverage across requested libraries before truncating.",
    "Do not maintain explicitly requested library coverage in a ranking tie.",
    "Avoid preserving the widest coverage of requested libraries.",
])
def test_explicitly_contradictory_guardrail_is_not_a_positive(contradiction):
    fixture = row()
    fixture["properties"]["Guardrail"]["rich_text"][0]["plain_text"] = contradiction
    result = replay(request(testing=True), [fixture])
    assert result.selected_lesson_ids == ()


@pytest.mark.parametrize("missing", range(4))
def test_historical_git_refresh_alias_requires_all_hints(missing):
    req = _recorded_request(_HISTORICAL[-1])
    hints = tuple(value for i, value in enumerate(req.capability_keywords) if i != missing)
    result, _ = _replay_public_request(replace(req, capability_keywords=hints), _mixed_corpus())
    assert result.selected_lesson_ids == ()


def test_historical_git_refresh_alias_requires_explicit_git_context():
    req = _recorded_request(_HISTORICAL[-1])
    result, _ = _replay_public_request(replace(req, ecosystem_hints=("python",)), _mixed_corpus())
    assert result.selected_lesson_ids == ()


def test_git_refresh_alias_does_not_qualify_unrelated_or_negated_guidance():
    req = _recorded_request(_HISTORICAL[-1])
    result, _ = _replay_public_request(req, [
        row(),
        row(62, title="PR reconciliation", guidance="Refresh the dashboard during reconciliation."),
        row(63, title="Avoid PR reconciliation for releases", guidance="Git refresh reconciliation."),
        row(64, title="Git branch refresh checklist", guidance="Run merge-tree and reconcile Git."),
    ])
    assert result.selected_lesson_ids == ()


def test_historical_git_refresh_alias_does_not_erase_generic_tie_stop():
    req = _recorded_request(_HISTORICAL[-1])
    result, _ = _replay_public_request(req, [
        row(i, title="PR reconciliation", guidance="Git refresh reconciliation.")
        for i in (61, 80, 86, 87)
    ])
    assert result.selected_lesson_ids == ()
    assert result.selection_reason_codes == ("generic-relevance-unverified",)


@pytest.mark.parametrize("guidance", [
    "Never refresh Git using merge-tree during reconciliation.",
    "Do not refresh Git for pull request reconciliation.",
    "Avoid Git refresh reconciliation.",
])
def test_historical_git_refresh_route_rejects_explicitly_negative_instructions(guidance):
    req = _recorded_request(_HISTORICAL[-1])
    result, _ = _replay_public_request(
        req, [row(61, title="PR reconciliation", guidance=guidance)],
    )
    assert result.selected_lesson_ids == ()


def test_historical_git_refresh_cannot_qualify_from_guardrail_alone():
    req = _recorded_request(_HISTORICAL[-1])
    item = row(61, title="PR reconciliation", guidance="Verify the operator receipt.")
    item["properties"]["Guardrail"]["rich_text"][0]["plain_text"] = (
        "Never refresh Git via merge-tree without proving reconciliation scope."
    )
    result, _ = _replay_public_request(req, [item])
    assert result.selected_lesson_ids == ()


@pytest.mark.parametrize("testing", [False, True])
def test_library_coverage_explicit_avoid_when_contradiction_vetoes_primary(testing):
    candidate = _as_selection_candidate(normalize_lesson_row(row()))
    candidate = replace(
        candidate,
        avoid_when=("Never preserve explicitly requested library coverage.",),
    )
    result = select_coding_knowledge(request(testing=testing), (candidate,))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.selected == ()
    assert result.authority_created is False


@pytest.mark.parametrize("shape", [{"ecosystem": "calendar"}, {"use_when": ()}],
                         ids=["unrelated-ecosystem", "no-primary"])
def test_library_tie_exact_title_cannot_replace_the_other_bound_signals(shape):
    lesson = _as_selection_candidate(normalize_lesson_row(row()))
    result = select_coding_knowledge(request(), (replace(lesson, **shape),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.selected == ()


def test_library_tie_match_requires_explicit_request_ecosystem():
    lesson = _as_selection_candidate(normalize_lesson_row(row()))
    result = select_coding_knowledge(
        replace(request(), ecosystem_hints=("calendar",)), (lesson,)
    )
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.selected == ()
