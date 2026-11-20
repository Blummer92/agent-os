"""#4026: relevance-blind lexical ID tie-break decides which tied lessons are kept.

Inside one relevance bucket both the five-ID candidate bound
(`_bound_relevant_lessons`) and the three-item CKR2 cut order lessons by
`lesson_id.casefold()` ("ll-10" < "ll-2" < "ll-65"). All records here are
SYNTHETIC fixtures; they prove selector mechanics, not live Notion content,
live eligibility, or production accuracy. No independently labelled gold set
exists, so nothing here is a precision/recall claim.
"""
import itertools
import pytest

from agent_memory_context_manager import lesson_retrieval_orchestrator as ckr11
from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeCandidate,
    CodingKnowledgeRequest,
    KnowledgeCurrentness,
    SufficiencyStatus,
    select_coding_knowledge,
)
from agent_memory_context_manager.lesson_activation_bridge import (
    orchestrate_lesson_activation,
)
from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus
from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    orchestrate_lesson_retrieval,
)

REF = "https://github.com/Blummer92/agent-os/issues/1904"
RELEVANT_TASK = "avoid duplicate aggregate validation for an unchanged exact head"
FILLER_TITLE = "Recheck currentness before routing"
FILLER_GUIDANCE = "Reacquire evidence after head advances."


def request(task=RELEVANT_TASK, **kw):
    d = dict(task_reference=task, ecosystem_hints=("python",),
             capability_keywords=("testing",), target_path_hints=(),
             canonical_rule_refs=(), known_knowledge_refs=(),
             specialized_knowledge_required=True)
    d.update(kw)
    return CodingKnowledgeRequest(**d)


def _t(text, kind="rich_text"):
    return {"type": kind, kind: [{"plain_text": text}]}


def row(n, title=FILLER_TITLE, guidance=FILLER_GUIDANCE, source=REF, area="Testing",
        ltype="Testing lesson"):
    return {
        "object": "page", "id": f"page-{n}", "url": f"https://www.notion.so/ll-{n}",
        "last_edited_time": "2026-11-15T00:41:00.000Z",
        "properties": {
            "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": n}},
            "Lesson Learned": _t(title, "title"),
            "Status": {"type": "select", "select": {"name": "Applied"}},
            "Surface Before Work?": {"type": "checkbox", "checkbox": True},
            "Area": {"type": "select", "select": {"name": area}},
            "Learning Type": {"type": "select", "select": {"name": ltype}},
            "Applies To": {"type": "multi_select", "multi_select": []},
            "Source Link": {"type": "url", "url": source},
            "Guardrail": _t("Never reuse stale evidence."),
            "What To Do Next Time": _t(guidance),
        },
    }


def corpus(relevant_id=65, **relevant_kw):
    """24 generic testing lessons (LL-1..LL-24; the bridge path caps one read at 25 rows) + one contextually relevant lesson."""
    rows = [row(n) for n in range(1, 25)]
    rows.append(row(relevant_id, title="Do not repeat aggregate validation on an unchanged head",
                    guidance="Skip a duplicate aggregate validation when the exact head is unchanged.",
                    **relevant_kw))
    return rows


def reader(rows):
    return lambda q: {"results": list(rows), "has_more": False, "next_cursor": None}


def cand(i, name=FILLER_TITLE, use=(FILLER_GUIDANCE,), **kw):
    d = dict(knowledge_id=i, source_system="notion-lessons-learned", source_revision="r1",
             currentness=KnowledgeCurrentness.CURRENT, name=name, ecosystem="python",
             library_name=None, capability_kind="testing", keywords=(), use_when=tuple(use),
             canonical_github_refs=(REF,))
    d.update(kw)
    return CodingKnowledgeCandidate(**d)


# ---- red: the relevant lesson is outside the first five lexical IDs ----------

def test_bridge_bound_keeps_relevant_lesson_outside_first_five_lexical_ids():
    result = orchestrate_lesson_activation(request(), execute_read=reader(corpus()))
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert "LL-65" in result.selected_lesson_ids


def test_ckr11_still_prioritizes_context_before_generic_tie_abstention(monkeypatch):
    evaluated = []
    actual_consume = ckr11.consume_lesson_preflight

    def record_prepolicy_result(*args, **kwargs):
        result = actual_consume(*args, **kwargs)
        evaluated.append(result)
        return result

    monkeypatch.setattr(ckr11, "consume_lesson_preflight", record_prepolicy_result)
    result = orchestrate_lesson_retrieval(request(), execute_read=reader(corpus()))
    assert len(evaluated) == 1
    assert evaluated[0].lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert "LL-65" in evaluated[0].selected_lesson_ids
    assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert result.selected_lesson_ids == ()
    assert result.selection_reason_codes == ("generic-relevance-unverified",)
    assert result.retrieval_diagnostics["best_bucket_tied_identities"] == 25


def test_ckr2_three_item_cut_does_not_drop_relevant_lesson_by_id_string():
    # Five tied candidates; the relevant one has the lexically LAST id ("ll-9").
    cands = (cand("LL-10"), cand("LL-11"), cand("LL-12"), cand("LL-13"),
             cand("LL-9", name="Do not repeat aggregate validation on an unchanged head",
                  use=("Skip a duplicate aggregate validation when the exact head is unchanged.",)))
    result = select_coding_knowledge(request(), cands)
    ids = tuple(s.candidate.knowledge_id for s in result.selected)
    assert "LL-9" in ids and len(ids) <= 3


def test_rare_distinctive_token_outweighs_many_universal_tokens():
    universal = "Reacquire evidence after head advances and recheck currentness before routing."
    cands = (
        cand("LL-1", use=(universal,)),                      # repeats common words only
        cand("LL-2", use=(universal,)),
        cand("LL-3", use=(universal,)),
        cand("LL-4", use=(universal,)),
        cand("LL-9", use=("Wheelhouse packaging omitted a registry.",)),  # one rare word
    )
    req = request(task="evidence head routing currentness recheck wheelhouse")
    ids = tuple(s.candidate.knowledge_id for s in select_coding_knowledge(req, cands).selected)
    assert "LL-9" in ids


# ---- invariants (must hold before AND after the repair) -----------------------

def test_without_context_overlap_legacy_lexical_order_is_unchanged():
    req = request(task="zzzz qqqq unrelated words")
    result = orchestrate_lesson_activation(req, execute_read=reader(corpus()))
    assert result.selected_lesson_ids == ("LL-1", "LL-10", "LL-11")


def test_context_overlap_cannot_outrank_a_better_relevance_bucket():
    better = cand("LL-10")                                   # python + testing -> bucket 2
    worse = cand("LL-2", ecosystem="notion",                 # capability only -> bucket 1
                 name="Do not repeat aggregate validation on an unchanged head",
                 use=("Skip a duplicate aggregate validation when the exact head is unchanged.",))
    result = select_coding_knowledge(request(), (better, worse))
    assert tuple(s.candidate.knowledge_id for s in result.selected) == ("LL-10",)


def test_task_reference_alone_cannot_create_relevance():
    rows = [row(n, area="Governance", ltype="Scope/permission lesson",
                title="Do not repeat aggregate validation on an unchanged head")
            for n in range(1, 4)]
    result = orchestrate_lesson_activation(request(), execute_read=reader(rows))
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.selected_lesson_ids == ()
    assert "no-relevant-candidate" in result.selection_reason_codes


def test_contextually_best_unverifiable_lesson_still_fails_closed():
    rows = corpus(source=None)  # relevant LL-65 has no primary GitHub source -> UNVERIFIABLE
    result = orchestrate_lesson_activation(request(), execute_read=reader(rows))
    assert result.lesson_retrieval_status is not LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ()


def test_budgets_and_provenance_are_unchanged():
    result = orchestrate_lesson_activation(request(), execute_read=reader(corpus()))
    assert result.candidate_count <= 5 and len(result.selected_lesson_ids) <= 3
    assert result.canonical_github_refs and not result.notion_write_performed
    assert not result.github_write_performed and not result.authority_created


def test_selection_is_independent_of_input_order():
    rows = corpus()
    outcomes = {orchestrate_lesson_activation(request(), execute_read=reader(list(p))).selected_lesson_ids
                for p in (rows, rows[::-1], rows[17:] + rows[:17])}
    assert len(outcomes) == 1


# ---- added after mutation review (Md, Mf survived the first test set) ----------

def test_bound_never_lets_lower_bucket_context_overlap_displace_a_better_bucket():
    # Five weaker-bucket lessons (ecosystem mismatch -> bucket 1) overlap the task
    # strongly; one better-bucket lesson (python + testing -> bucket 2) overlaps weakly.
    strong = "Do not repeat aggregate validation on an unchanged exact head"
    rows = [row(n, area="Documentation", title=strong, guidance=strong) for n in range(1, 6)]
    rows.append(row(9, title="Aggregate notes", guidance="Keep notes short."))
    result = orchestrate_lesson_activation(request(), execute_read=reader(rows))
    assert result.selected_lesson_ids == ("LL-9",)


def test_short_filler_tokens_never_outweigh_a_distinctive_word():
    cands = (
        cand("LL-1", use=("Go to a bar of it.",)),           # only 1-3 letter words match
        cand("LL-2"), cand("LL-3"), cand("LL-4"),
        cand("LL-9", use=("Wheelhouse packaging omitted a registry.",)),
    )
    req = request(task="go to a bar of it wheelhouse")
    ids = tuple(s.candidate.knowledge_id for s in select_coding_knowledge(req, cands).selected)
    assert ids[0] == "LL-9"


def test_bucket_defining_keyword_is_not_counted_again_as_context():
    # "testing" already formed the relevance bucket; a lesson that merely contains the
    # word in its title must not be promoted over legacy order for an unrelated task.
    cands = (
        cand("LL-1"), cand("LL-2"), cand("LL-3"), cand("LL-4"),
        cand("LL-9", name="Use Hypothesis selectively for property-based testing"),
    )
    req = request(task="rename a dashboard column header")
    ids = tuple(s.candidate.knowledge_id for s in select_coding_knowledge(req, cands).selected)
    assert ids == ("LL-1", "LL-2", "LL-3")


def test_free_text_capability_phrases_still_count_as_context():
    cands = (
        cand("LL-1"), cand("LL-2"), cand("LL-3"), cand("LL-4"),
        cand("LL-9", use=("Wheelhouse packaging omitted a registry.",)),
    )
    req = request(task="zzzz", capability_keywords=("testing", "offline wheelhouse"))
    ids = tuple(s.candidate.knowledge_id for s in select_coding_knowledge(req, cands).selected)
    assert ids[0] == "LL-9"
