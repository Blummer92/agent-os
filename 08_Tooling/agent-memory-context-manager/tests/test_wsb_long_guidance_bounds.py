"""Workstream B regression tests: long advisory guidance bounds (#3991 campaign).

Provenance: all lesson rows and guidance text in this file are SYNTHETIC,
constructed 2026-11-16 in this worktree to reproduce the documented defect
(Defect B: valid lesson guidance rejected by the uniform 512-char bounds in
lesson_activation_bridge.py, lesson_preflight.py and
coding_knowledge_selection.py). They are not recovered Notion corpus rows and
must not be cited as live-corpus measurements.

Defect chain pinned by these tests:
1. bridge `_plain_text` joins rich_text items and rejects joined text over
   MAX_ROW_TEXT_CHARS (512), so a present-but-long Guardrail or
   What To Do Next Time is skipped as "missing-activation-guidance" --
   a misleading reason for guidance that exists but is oversized.
2. preflight `LessonRecordEvidence._text` rejects guardrail /
   what_to_do_next_time over 512 with ValueError.
3. preflight `_candidate()` maps guidance into
   CodingKnowledgeCandidate.use_when, whose 512 bound raises an UNCAUGHT
   ValueError inside consume_lesson_preflight -- a crash, not a fail-closed
   result.

Expected post-patch policy (bounded, coordinated across all three modules):
a single shared guidance bound MAX_GUIDANCE_TEXT_CHARS applies to advisory
narrative text only; every other field keeps the 512 structured bound;
guidance over the new bound still fails closed, with a DISTINCT reason
("oversized-activation-guidance") separate from genuinely missing guidance.
"""

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeCandidate,
    CodingKnowledgeRequest,
    KnowledgeCurrentness,
    select_coding_knowledge,
)

try:  # post-patch shared bound; pre-patch fall back to the proposed value
    from agent_memory_context_manager.coding_knowledge_selection import (
        MAX_GUIDANCE_TEXT_CHARS,
    )
except ImportError:  # pre-patch base: bound does not exist yet
    MAX_GUIDANCE_TEXT_CHARS = 2048
from agent_memory_context_manager.lesson_activation_bridge import (
    LessonActivationSkip,
    normalize_lesson_row,
    orchestrate_lesson_activation,
)
from agent_memory_context_manager.lesson_preflight import (
    LessonRecordEvidence,
    LessonRetrievalStatus,
    consume_lesson_preflight,
)

# A realistic-length guardrail: 4 clauses of operational instruction, ~600
# chars. Synthetic; modeled on the repo's own catalog guardrail style.
LONG_GUARDRAIL = (
    "Before merging any pull request that references an open issue, read the "
    "full PR description and confirm no closing keyword targets an issue whose "
    "live acceptance work is still outstanding. When acceptance remains open, "
    "use a non-closing 'Part of #N' reference instead of 'Fixes' or 'Closes', "
    "and record the substitution in the merge evidence. If the description was "
    "edited after the last review, re-read it in full rather than relying on "
    "the reviewed copy, because a later edit can introduce a closing keyword "
    "that was not present when approval was given. Recheck immediately before "
    "merge, not at approval time."
)
LONG_NEXT_TIME = (
    "Recheck the exact PR head SHA against the reviewed head before merging, "
    "then verify the merge result against the same head. If the head advanced "
    "between review and merge, treat the earlier review as stale evidence, "
    "re-run the required checks against the new head, and only then merge. "
    "Record both the reviewed head and the merged head in the evidence note "
    "so later audits can reconstruct exactly what was approved. Never rely on "
    "a green check that was computed against an older head, and never merge "
    "while the head check is still pending."
)
assert 512 < len(LONG_GUARDRAIL) <= MAX_GUIDANCE_TEXT_CHARS
assert 512 < len(LONG_NEXT_TIME) <= MAX_GUIDANCE_TEXT_CHARS

OVERSIZED_GUIDANCE = "x" * (MAX_GUIDANCE_TEXT_CHARS + 1)


def request(**overrides):
    data = dict(
        task_reference="issue:#3991",
        ecosystem_hints=("python",),
        capability_keywords=("testing",),
        target_path_hints=(),
        canonical_rule_refs=(),
        known_knowledge_refs=(),
        specialized_knowledge_required=None,
    )
    data.update(overrides)
    return CodingKnowledgeRequest(**data)


def _title(text):
    return {"type": "title", "title": [{"plain_text": text}]}


def _rich_text(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text}]}


def _rich_text_items(*texts):
    return {"type": "rich_text", "rich_text": [{"plain_text": t} for t in texts]}


def _select(name):
    return {"type": "select", "select": {"name": name}}


def _multi_select(*names):
    return {"type": "multi_select", "multi_select": [{"name": name} for name in names]}


def _checkbox(value):
    return {"type": "checkbox", "checkbox": value}


def _url(value):
    return {"type": "url", "url": value}


def live_row(**overrides):
    properties = {
        "Lesson ID": _rich_text("LL-42"),
        "Lesson Learned": _title("Recheck currentness before routing"),
        "Status": _select("Applied"),
        "Surface Before Work?": _checkbox(True),
        "Area": _select("Testing"),
        "Applies To": _multi_select("Notion", "Curriculum"),
        "Learning Type": _select("Testing lesson"),
        "Source Link": _url("https://github.com/Blummer92/agent-os/blob/main/01_Shared_Standards/python/testing-standard.md"),
        "Guardrail": _rich_text("Never reuse stale evidence."),
        "What To Do Next Time": _rich_text("Reacquire evidence after head advances."),
    }
    properties.update(overrides.pop("properties", {}))
    row = {
        "object": "page",
        "id": "11111111-1111-1111-1111-111111111111",
        "url": "https://www.notion.so/lesson-page-abc123",
        "last_edited_time": "2026-08-30T12:00:00.000Z",
        "properties": properties,
    }
    row.update(overrides)
    return row


def evidence(**overrides):
    data = dict(
        lesson_id="LL-42",
        source_revision="2026-08-30T12:00:00.000Z",
        title="Recheck currentness before routing",
        ecosystem="python",
        capability_kind="testing",
        status="Applied",
        surface_before_work=True,
        currentness=KnowledgeCurrentness.CURRENT,
        what_to_do_next_time="Reacquire evidence after head advances.",
        guardrail="Never reuse stale evidence.",
        canonical_github_refs=(
            "https://github.com/Blummer92/agent-os/blob/main/01_Shared_Standards/python/testing-standard.md",
        ),
        evidence_refs=("https://www.notion.so/lesson-page-abc123",),
        keywords=("Notion", "Curriculum"),
    )
    data.update(overrides)
    return LessonRecordEvidence(**data)


# --- Bridge: normalize_lesson_row -------------------------------------------

def test_bridge_admits_long_guardrail_verbatim():
    result = normalize_lesson_row(live_row(properties={"Guardrail": _rich_text(LONG_GUARDRAIL)}))
    assert isinstance(result, LessonRecordEvidence)
    assert result.guardrail == LONG_GUARDRAIL


def test_bridge_admits_long_what_to_do_next_time_verbatim():
    result = normalize_lesson_row(
        live_row(properties={"What To Do Next Time": _rich_text(LONG_NEXT_TIME)})
    )
    assert isinstance(result, LessonRecordEvidence)
    assert result.what_to_do_next_time == LONG_NEXT_TIME


def test_bridge_admits_multi_item_guidance_split_by_provider():
    # Notion splits long rich text into multiple items; each item can be
    # within the item limit while the joined text exceeds 512.
    first, second = LONG_GUARDRAIL[:400], LONG_GUARDRAIL[400:]
    result = normalize_lesson_row(
        live_row(properties={"Guardrail": _rich_text_items(first, second)})
    )
    assert isinstance(result, LessonRecordEvidence)
    assert result.guardrail == LONG_GUARDRAIL


def test_bridge_guidance_over_shared_bound_fails_closed_with_distinct_reason():
    result = normalize_lesson_row(
        live_row(properties={"Guardrail": _rich_text(OVERSIZED_GUIDANCE)})
    )
    assert isinstance(result, LessonActivationSkip)
    assert result.reason == "oversized-activation-guidance"
    assert result.reason != "missing-activation-guidance"


def test_bridge_missing_guidance_keeps_missing_reason():
    result = normalize_lesson_row(live_row(properties={"Guardrail": _rich_text("")}))
    assert isinstance(result, LessonActivationSkip)
    assert result.reason == "missing-activation-guidance"


def test_bridge_guidance_at_shared_bound_is_admitted():
    exact = "g" * MAX_GUIDANCE_TEXT_CHARS
    result = normalize_lesson_row(live_row(properties={"Guardrail": _rich_text(exact)}))
    assert isinstance(result, LessonRecordEvidence)
    assert result.guardrail == exact


def test_bridge_structured_fields_keep_512_bound():
    long_title = "t" * 513
    result = normalize_lesson_row(
        live_row(properties={"Lesson Learned": _title(long_title)})
    )
    assert isinstance(result, LessonActivationSkip)


# --- Preflight: LessonRecordEvidence + consume_lesson_preflight --------------

def test_preflight_evidence_admits_long_guidance():
    item = evidence(guardrail=LONG_GUARDRAIL, what_to_do_next_time=LONG_NEXT_TIME)
    assert item.guardrail == LONG_GUARDRAIL


def test_preflight_evidence_rejects_guidance_over_shared_bound():
    import pytest

    with pytest.raises(ValueError):
        evidence(guardrail=OVERSIZED_GUIDANCE)


def test_consume_lesson_preflight_does_not_crash_on_long_guidance():
    # Pre-patch this raises an uncaught ValueError out of _candidate() --
    # a crash, not a fail-closed LessonPreflightResult.
    item = evidence(guardrail=LONG_GUARDRAIL, what_to_do_next_time=LONG_NEXT_TIME)
    result = consume_lesson_preflight(request(), (item,), retrieval_available=True)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert "LL-42" in result.selected_lesson_ids


def test_consume_lesson_preflight_preserves_guidance_verbatim_no_truncation():
    item = evidence(guardrail=LONG_GUARDRAIL, what_to_do_next_time=LONG_NEXT_TIME)
    result = consume_lesson_preflight(request(), (item,), retrieval_available=True)
    selected = result.selection.selected[0].candidate
    assert LONG_GUARDRAIL in selected.use_when
    assert LONG_NEXT_TIME in selected.use_when


def test_preflight_identity_fields_keep_512_bound():
    import pytest

    with pytest.raises(ValueError):
        evidence(title="t" * 513)


# --- Selection: CodingKnowledgeCandidate ------------------------------------

def _candidate(**overrides):
    data = dict(
        knowledge_id="LL-42",
        source_system="notion-lessons-learned",
        source_revision="2026-08-30T12:00:00.000Z",
        currentness=KnowledgeCurrentness.CURRENT,
        name="Recheck currentness before routing",
        ecosystem="python",
        library_name=None,
        capability_kind="testing",
        keywords=("testing",),
        use_when=("Reacquire evidence after head advances.", "Never reuse stale evidence."),
        avoid_when=(),
        canonical_github_refs=(
            "https://github.com/Blummer92/agent-os/blob/main/01_Shared_Standards/python/testing-standard.md",
        ),
        evidence_refs=("https://www.notion.so/lesson-page-abc123",),
    )
    data.update(overrides)
    return CodingKnowledgeCandidate(**data)


def test_candidate_admits_long_use_when_item():
    item = _candidate(use_when=(LONG_NEXT_TIME, LONG_GUARDRAIL))
    assert item.use_when[0] == LONG_NEXT_TIME


def test_candidate_rejects_use_when_over_shared_bound():
    import pytest

    with pytest.raises(ValueError):
        _candidate(use_when=(OVERSIZED_GUIDANCE,))


def test_candidate_name_keeps_512_bound():
    import pytest

    with pytest.raises(ValueError):
        _candidate(name="n" * 513)


def test_select_coding_knowledge_matches_keywords_inside_long_guidance():
    # Selection matching reads use_when text; long guidance must not break
    # deterministic relevance matching.
    item = _candidate(use_when=(LONG_NEXT_TIME + " testing recheck.",))
    result = select_coding_knowledge(request(), (item,))
    assert result.candidate_count == 1


# --- End-to-end through the bridge orchestrator ------------------------------

def test_orchestration_admits_long_guidance_lesson():
    row = live_row(
        properties={
            "Guardrail": _rich_text(LONG_GUARDRAIL),
            "What To Do Next Time": _rich_text(LONG_NEXT_TIME),
        }
    )

    def executor(query):
        return {"results": [row], "has_more": False, "next_cursor": None}

    result = orchestrate_lesson_activation(request(), execute_read=executor)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert "LL-42" in result.selected_lesson_ids


# --- Mutation-killing additions (targeted at surviving boundary mutants) ----

def test_candidate_use_when_at_exact_shared_bound_is_admitted():
    # Kills the > vs >= boundary mutant on _validate_text.
    exact = "u" * MAX_GUIDANCE_TEXT_CHARS
    item = _candidate(use_when=(exact,))
    assert item.use_when[0] == exact


def test_candidate_use_when_rejects_control_characters():
    import pytest

    with pytest.raises(ValueError):
        _candidate(use_when=("bad\x00guidance",))


def test_bridge_guidance_with_exactly_20_items_is_admitted():
    items = [{"plain_text": "clause %d. " % i} for i in range(20)]
    prop = {"type": "rich_text", "rich_text": items}
    result = normalize_lesson_row(live_row(properties={"Guardrail": prop}))
    assert isinstance(result, LessonRecordEvidence)


def test_bridge_guidance_with_21_items_fails_closed_as_missing():
    items = [{"plain_text": "clause %d. " % i} for i in range(21)]
    prop = {"type": "rich_text", "rich_text": items}
    result = normalize_lesson_row(live_row(properties={"Guardrail": prop}))
    assert isinstance(result, LessonActivationSkip)
    assert result.reason == "missing-activation-guidance"


def test_bridge_absent_guardrail_property_is_missing_not_crash():
    row = live_row()
    del row["properties"]["Guardrail"]
    result = normalize_lesson_row(row)
    assert isinstance(result, LessonActivationSkip)
    assert result.reason == "missing-activation-guidance"


def test_bridge_malformed_guidance_items_fail_closed_as_missing():
    prop = {"type": "rich_text", "rich_text": "not-a-list"}
    result = normalize_lesson_row(live_row(properties={"Guardrail": prop}))
    assert isinstance(result, LessonActivationSkip)
    assert result.reason == "missing-activation-guidance"


def test_candidate_avoid_when_513_admitted_post_patch():
    text = "a" * 513
    item = _candidate(avoid_when=(text,))
    assert item.avoid_when[0] == text


def test_candidate_avoid_when_at_exact_shared_bound_is_admitted():
    exact = "a" * MAX_GUIDANCE_TEXT_CHARS
    item = _candidate(avoid_when=(exact,))
    assert item.avoid_when[0] == exact


def test_candidate_avoid_when_over_shared_bound_fails_closed():
    import pytest

    with pytest.raises(ValueError):
        _candidate(avoid_when=(OVERSIZED_GUIDANCE,))
