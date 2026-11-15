"""#3973: optional multi-source lesson provenance in the normalizer.

Covers the `Supporting Source Links` (rich_text, 0-5 refs, one canonical
GitHub ref per item) extension to `normalize_lesson_row`:

- valid supporting refs join `canonical_github_refs` (primary first,
  then supporting in row order, stably deduped) and the lesson stays ONE
  CKR2 candidate;
- malformed / foreign / duplicate / oversized / over-cap refs are dropped
  and reported in `dropped_supporting_refs`, never voiding the lesson;
- a missing primary Source Link still fails closed: supporting refs never
  substitute for lesson-owned origin (#1520);
- legacy one-link rows and rows where the property is absent behave
  exactly as today.

The #3973 seed pair is used as well-formed canonical refs throughout:
issue #2064 (the original existing-bug backlog selection failure) and
merged PR #2077 (explicitly `Fixes #2064`; the policy-text regression
guard lives in `tests/test_2064_existing_bug_batch_incident.py` and
`tests/test_bug_backlog_first_selection_policy.py`). Those tests are
policy-text regression tests, NOT live proof that an agent follows the
instructions, and PR #2077 is supporting repair evidence here -- never
an applied-lesson receipt.
"""
from agent_memory_context_manager.coding_knowledge_selection import CodingKnowledgeRequest
from agent_memory_context_manager.lesson_activation_bridge import (
    LessonActivationSkip,
    normalize_lesson_row,
    orchestrate_lesson_activation,
)
from agent_memory_context_manager.lesson_preflight import (
    LessonRecordEvidence,
    LessonRetrievalStatus,
)

PRIMARY = "https://github.com/Blummer92/agent-os/issues/2064"
SUPPORTING_PR = "https://github.com/Blummer92/agent-os/pull/2077"
SUPPORTING_GOVERNANCE = "01_Shared_Standards/python/testing-standard.md"


def _title(text):
    return {"type": "title", "title": [{"plain_text": text}]}


def _rich_text(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text}]}


def _rich_text_items(*texts):
    return {"type": "rich_text", "rich_text": [{"plain_text": text} for text in texts]}


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
        "Lesson ID": _rich_text("LL-73"),
        "Lesson Learned": _title("Bounded bug batches must reconcile eligible existing bugs first"),
        "Status": _select("Applied"),
        "Surface Before Work?": _checkbox(True),
        "Area": _select("Automation"),
        "Applies To": _multi_select("Notion", "Curriculum"),
        "Learning Type": _select("Mistake"),
        "Source Link": _url(PRIMARY),
        "Guardrail": _rich_text("Never create fresh issues before exhausting the open bug backlog."),
        "What To Do Next Time": _rich_text("Reconcile eligible existing bugs before discovering new ones."),
    }
    properties.update(overrides.pop("properties", {}))
    row = {
        "object": "page",
        "id": "11111111-1111-1111-1111-111111111111",
        "url": "https://www.notion.so/lesson-page-abc123",
        "last_edited_time": "2026-09-07T23:11:07.594Z",
        "properties": properties,
    }
    row.update(overrides)
    return row


def request(**overrides):
    data = dict(
        task_reference="issue:#3973",
        ecosystem_hints=("python",),
        capability_keywords=("testing",),
        target_path_hints=(),
        canonical_rule_refs=(),
        known_knowledge_refs=(),
        specialized_knowledge_required=None,
    )
    data.update(overrides)
    return CodingKnowledgeRequest(**data)


def test_valid_supporting_refs_join_primary_first_in_row_order():
    result = normalize_lesson_row(
        live_row(properties={"Supporting Source Links": _rich_text_items(SUPPORTING_PR, SUPPORTING_GOVERNANCE)})
    )
    assert isinstance(result, LessonRecordEvidence)
    assert result.canonical_github_refs == (PRIMARY, SUPPORTING_PR, SUPPORTING_GOVERNANCE)
    assert result.dropped_supporting_refs == ()
    assert result.currentness.name == "CURRENT"


def test_duplicate_primary_and_duplicate_supporting_are_dropped_and_reported():
    result = normalize_lesson_row(
        live_row(
            properties={
                "Supporting Source Links": _rich_text_items(PRIMARY, SUPPORTING_PR, SUPPORTING_PR),
            }
        )
    )
    assert isinstance(result, LessonRecordEvidence)
    assert result.canonical_github_refs == (PRIMARY, SUPPORTING_PR)
    assert result.dropped_supporting_refs == (PRIMARY, SUPPORTING_PR)


def test_foreign_malformed_and_oversized_refs_are_dropped_never_void_lesson():
    oversized = "https://github.com/Blummer92/agent-os/issues/2064" + "x" * 500
    assert len(oversized) > 512
    result = normalize_lesson_row(
        live_row(
            properties={
                "Supporting Source Links": _rich_text_items(
                    "https://github.com/Other/repo/pull/1",
                    "not a url",
                    "https://example.com/Blummer92/agent-os/issues/2064",
                    oversized,
                    SUPPORTING_PR,
                )
            }
        )
    )
    assert isinstance(result, LessonRecordEvidence)
    assert result.canonical_github_refs == (PRIMARY, SUPPORTING_PR)
    assert result.dropped_supporting_refs == (
        "https://github.com/Other/repo/pull/1",
        "not a url",
        "https://example.com/Blummer92/agent-os/issues/2064",
        oversized[:512],
    )
    assert result.currentness.name == "CURRENT"


def test_more_than_five_supporting_refs_extra_is_dropped():
    refs = [
        f"https://github.com/Blummer92/agent-os/issues/{3000 + index}" for index in range(6)
    ]
    result = normalize_lesson_row(live_row(properties={"Supporting Source Links": _rich_text_items(*refs)}))
    assert isinstance(result, LessonRecordEvidence)
    assert result.canonical_github_refs == (PRIMARY,) + tuple(refs[:5])
    assert result.dropped_supporting_refs == (refs[5],)


def test_missing_primary_still_fails_closed_supporting_refs_never_substitute():
    result = normalize_lesson_row(
        live_row(
            properties={
                "Source Link": _url(None),
                "Supporting Source Links": _rich_text_items(SUPPORTING_PR),
            }
        )
    )
    assert isinstance(result, LessonRecordEvidence)
    assert result.canonical_github_refs == ()
    assert result.dropped_supporting_refs == (SUPPORTING_PR,)
    assert result.currentness.name == "UNVERIFIABLE"
    # End to end: the lesson cannot reach sufficient without its primary.
    # (Request carries the row's own capability so the row is relevant.)
    orchestrated = orchestrate_lesson_activation(
        request(capability_keywords=("failure-avoidance",)),
        execute_read=lambda query: {"results": [live_row(
            properties={
                "Source Link": _url(None),
                "Supporting Source Links": _rich_text_items(SUPPORTING_PR),
            }
        )]}
    )
    assert orchestrated.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert "unverifiable-relevant-candidate" in orchestrated.selection_reason_codes


def test_legacy_one_link_row_and_absent_property_behave_as_today():
    legacy = normalize_lesson_row(live_row())
    assert isinstance(legacy, LessonRecordEvidence)
    assert legacy.canonical_github_refs == (PRIMARY,)
    assert legacy.dropped_supporting_refs == ()
    assert "Supporting Source Links" not in live_row()["properties"]
    absent = normalize_lesson_row(live_row(properties={}))
    assert isinstance(absent, LessonRecordEvidence)
    assert absent.canonical_github_refs == (PRIMARY,)
    assert absent.dropped_supporting_refs == ()


def test_wrong_type_supporting_property_is_dropped_primary_survives():
    result = normalize_lesson_row(
        live_row(properties={"Supporting Source Links": _url(SUPPORTING_PR)})
    )
    assert isinstance(result, LessonRecordEvidence)
    assert result.canonical_github_refs == (PRIMARY,)
    assert result.dropped_supporting_refs == ("<malformed-supporting-property>",)
    assert result.currentness.name == "CURRENT"


def test_malformed_rich_text_items_are_dropped_not_parsed():
    prop = {"type": "rich_text", "rich_text": [{"plain_text": SUPPORTING_PR}, {"no_text": True}, "bare-string"]}
    result = normalize_lesson_row(live_row(properties={"Supporting Source Links": prop}))
    assert isinstance(result, LessonRecordEvidence)
    assert result.canonical_github_refs == (PRIMARY, SUPPORTING_PR)
    assert result.dropped_supporting_refs == ("<malformed-supporting-item>", "<malformed-supporting-item>")


def test_multi_source_lesson_is_still_one_ckr2_candidate():
    row = live_row(properties={"Supporting Source Links": _rich_text_items(SUPPORTING_PR, SUPPORTING_GOVERNANCE)})
    result = orchestrate_lesson_activation(
        request(capability_keywords=("failure-avoidance",)),
        execute_read=lambda query: {"results": [row]},
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-73",)
    assert result.selected_count == 1
    assert result.candidate_count == 1
    assert PRIMARY in result.canonical_github_refs
    assert SUPPORTING_PR in result.canonical_github_refs


def test_supporting_refs_do_not_change_revision_binding():
    row = live_row(properties={"Supporting Source Links": _rich_text_items(SUPPORTING_PR)})
    result = normalize_lesson_row(row)
    assert isinstance(result, LessonRecordEvidence)
    assert result.source_revision == "2026-09-07T23:11:07.594Z"
    newer = normalize_lesson_row(
        live_row(
            properties={"Supporting Source Links": _rich_text_items(SUPPORTING_PR)},
            last_edited_time="2026-11-14T12:00:00.000Z",
        )
    )
    assert isinstance(newer, LessonRecordEvidence)
    assert newer.source_revision == "2026-11-14T12:00:00.000Z"
    assert newer.canonical_github_refs == result.canonical_github_refs


def test_task_reference_is_never_lesson_owned_provenance():
    # #1520: request-owned refs stay inspect-first evidence only.
    req = request(capability_keywords=("failure-avoidance",), canonical_rule_refs=(SUPPORTING_PR,))
    row = live_row(properties={"Source Link": _url(None)})
    result = orchestrate_lesson_activation(req, execute_read=lambda query: {"results": [row]})
    assert result.lesson_retrieval_status is not LessonRetrievalStatus.SUFFICIENT
    assert SUPPORTING_PR in result.handoff_projection["allowed_inspect_first"]
