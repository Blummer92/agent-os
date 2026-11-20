"""#4024: non-LL-51 relevance controls, not a claim of live Notion eligibility.

All lesson records below are synthetic, reviewer-labeled test fixtures. Historical
issues #1904 and #1362 support the scenario identities but do NOT prove current
Notion content, revision, activation, or an actual LL-65 selection.

Live issue #520 request 6966624791 returned insufficient/no-relevant-candidate
in result 6966640825. This deterministic test therefore proves the selector's
behavior given eligible records, not that the live provider returned them.
"""

from dataclasses import replace

import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeCandidate,
    CodingKnowledgeRequest,
    KnowledgeCurrentness,
    SufficiencyStatus,
    select_coding_knowledge,
)
from agent_memory_context_manager.lesson_activation_bridge import (
    LessonActivationError,
    orchestrate_lesson_activation,
)
from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus


ISSUE_1904 = "https://github.com/Blummer92/agent-os/issues/1904"
ISSUE_1362 = "https://github.com/Blummer92/agent-os/issues/1362"
NON51_REVISION = "synthetic-ll65-revision-1"


def ci_request(**changes):
    values = dict(
        task_reference="issue #520: avoid duplicate aggregate CI on the same PR head",
        ecosystem_hints=("python",),
        capability_keywords=("scheduling",),
        target_path_hints=(),
        specialized_knowledge_required=True,
    )
    values.update(changes)
    return CodingKnowledgeRequest(**values)


def packaging_request(**changes):
    values = dict(
        task_reference="issue #4022: offline packaging wheelhouse omitted navigation-registry",
        ecosystem_hints=("python",),
        capability_keywords=(
            "offline Python wheelhouse",
            "navigation registry package",
            "isolated pip installation",
        ),
        target_path_hints=(),
        specialized_knowledge_required=True,
    )
    values.update(changes)
    return CodingKnowledgeRequest(**values)


def ci_lesson(**changes):
    values = dict(
        knowledge_id="LL-65",
        source_system="notion-lessons-learned",
        source_revision=NON51_REVISION,
        currentness=KnowledgeCurrentness.CURRENT,
        name="Prevent duplicate exact-head aggregate validation on Ready transitions",
        ecosystem="python",
        library_name=None,
        capability_kind="scheduling",
        keywords=("duplicate aggregate validation",),
        use_when=("Only run the required aggregate once for an unchanged PR head.",),
        canonical_github_refs=(ISSUE_1904,),
    )
    values.update(changes)
    return CodingKnowledgeCandidate(**values)


def unrelated_ckr6_lesson():
    return CodingKnowledgeCandidate(
        knowledge_id="LL-51",
        source_system="notion-lessons-learned",
        source_revision="synthetic-ll51-revision-1",
        currentness=KnowledgeCurrentness.CURRENT,
        name="CKR6 mutation boundary must re-enter failed-repair lesson preflight",
        ecosystem="notion",
        library_name=None,
        capability_kind="testing",
        keywords=("ckr6 mutation boundary",),
        use_when=("Re-enter CKR6 after a failed repair before another mutation.",),
        canonical_github_refs=(ISSUE_1362,),
    )


def selected_ids(result):
    return tuple(item.candidate.knowledge_id for item in result.selected)


def _text_property(text, kind="rich_text"):
    return {"type": kind, kind: [{"plain_text": text}]}


def _select(name):
    return {"type": "select", "select": {"name": name}}


def synthetic_notion_row(lesson_id="LL-65", **changes):
    """Notion-shaped eligibility fixture, never a claimed copy of a real page."""
    is_ci = lesson_id == "LL-65"
    properties = {
        "Lesson ID": _text_property(lesson_id),
        "Lesson Learned": _text_property(
            "Prevent duplicate exact-head aggregate validation"
            if is_ci else "CKR6 mutation boundary requires failed-repair preflight",
            kind="title",
        ),
        "Status": _select("Applied"),
        "Surface Before Work?": {"type": "checkbox", "checkbox": True},
        "Area": _select("Automation" if is_ci else "Testing"),
        "Learning Type": _select("Trigger lesson" if is_ci else "Testing lesson"),
        "Applies To": {
            "type": "multi_select",
            "multi_select": [{"name": "Notion"}],
        },
        "Source Link": {"type": "url", "url": ISSUE_1904 if is_ci else ISSUE_1362},
        "Guardrail": _text_property("Keep a bounded exact-head regression check."),
        "What To Do Next Time": _text_property(
            "Deduplicate identical-head aggregate events."
            if is_ci else "Re-enter CKR6 at the failed-repair boundary."
        ),
    }
    properties.update(changes.pop("properties", {}))
    row = {
        "object": "page",
        "id": "synthetic-page-" + lesson_id.lower(),
        "url": "https://www.notion.so/synthetic-" + lesson_id.lower(),
        "last_edited_time": "2026-11-15T00:41:00.000Z",
        "properties": properties,
    }
    row.update(changes)
    return row


def test_relevant_ci_task_selects_non51_from_mixed_synthetic_candidates():
    result = select_coding_knowledge(
        ci_request(), (unrelated_ckr6_lesson(), ci_lesson())
    )
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert selected_ids(result) == ("LL-65",)
    assert "ecosystem-capability-match" in result.selected[0].reason_codes
    assert result.selected[0].candidate.source_revision == NON51_REVISION
    assert ISSUE_1904 in result.canonical_github_refs
    assert not result.authority_created and not result.notion_write_performed


@pytest.mark.parametrize("reverse", [False, True], ids=["forward", "reversed"])
def test_packaging_task_does_not_select_ll51_or_an_unrelated_ci_lesson(reverse):
    corpus = (ci_lesson(), unrelated_ckr6_lesson())
    if reverse:
        corpus = tuple(reversed(corpus))
    result = select_coding_knowledge(packaging_request(), corpus)
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.reason_codes == ("no-relevant-candidate",)
    assert result.selected_count == 0 and selected_ids(result) == ()


def test_irrelevant_metadata_does_not_change_non51_selection():
    corpus = (ci_lesson(), unrelated_ckr6_lesson())
    baseline = select_coding_knowledge(ci_request(), corpus)
    added_noise = ci_request(
        capability_keywords=("scheduling", "unrelated-display-hint"),
        target_path_hints=("docs/example-noise.md",),
    )
    changed = select_coding_knowledge(added_noise, tuple(reversed(corpus)))
    assert baseline.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert changed.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert selected_ids(changed) == selected_ids(baseline) == ("LL-65",)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"currentness": KnowledgeCurrentness.STALE}, "stale-relevant-candidate"),
        ({"currentness": KnowledgeCurrentness.UNVERIFIABLE}, "unverifiable-relevant-candidate"),
        ({"authority_conflict": True}, "canonical-authority-conflict"),
    ],
    ids=["stale", "unverifiable", "authority-conflict"],
)
def test_relevant_non51_unsafe_candidate_is_blocked(change, reason):
    result = select_coding_knowledge(ci_request(), (ci_lesson(**change),))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert reason in result.reason_codes
    assert result.selected_count == 0


def test_request_cannot_supply_missing_candidate_provenance():
    result = select_coding_knowledge(
        ci_request(canonical_rule_refs=(ISSUE_1904,)),
        (ci_lesson(canonical_github_refs=()),),
    )
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert "canonical-reference-missing" in result.reason_codes
    assert ISSUE_1904 in result.canonical_github_refs
    assert not result.authority_created


def test_conflicting_revisions_of_same_non51_lesson_fail_closed():
    original = ci_lesson()
    conflict = replace(original, source_revision="synthetic-different-revision")
    result = select_coding_knowledge(ci_request(), (original, conflict))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.reason_codes == ("duplicate-identity-conflict",)
    assert result.selected_count == 0


def test_explicit_not_material_performs_no_selection():
    result = select_coding_knowledge(
        ci_request(specialized_knowledge_required=False),
        (ci_lesson(),),
    )
    assert result.sufficiency_status is SufficiencyStatus.NOT_NEEDED
    assert result.selected_count == 0
    assert result.reason_codes == ("knowledge-not-needed",)


def test_ckr11_to_ckr2_to_ckr6_can_select_non51_without_known_id_or_writes():
    calls = []

    def reader(query):
        calls.append(query)
        return {
            "results": [synthetic_notion_row("LL-51"), synthetic_notion_row("LL-65")],
            "has_more": False,
            "next_cursor": None,
        }

    result = orchestrate_lesson_activation(ci_request(), execute_read=reader)
    assert len(calls) == 1
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-65",)
    assert result.source_authority
    assert ISSUE_1904 in result.canonical_github_refs
    assert not result.notion_write_performed
    assert not result.github_write_performed
    assert not result.authority_created


def test_ckr6_unrelated_packaging_read_does_not_promote_ll51():
    result = orchestrate_lesson_activation(
        packaging_request(),
        execute_read=lambda query: {
            "results": [synthetic_notion_row("LL-51"), synthetic_notion_row("LL-65")],
            "has_more": False,
            "next_cursor": None,
        },
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.selected_lesson_ids == ()
    assert "no-relevant-candidate" in result.selection_reason_codes


def test_ckr6_missing_primary_source_must_not_select_non51():
    result = orchestrate_lesson_activation(
        ci_request(),
        execute_read=lambda query: {
            "results": [synthetic_notion_row("LL-65", properties={
                "Source Link": {"type": "url", "url": None},
            })],
            "has_more": False,
            "next_cursor": None,
        },
    )
    assert result.lesson_retrieval_status is not LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ()
    assert not result.notion_write_performed


def test_ckr6_unsurfaced_non51_cannot_be_selected():
    result = orchestrate_lesson_activation(
        ci_request(),
        execute_read=lambda query: {
            "results": [synthetic_notion_row("LL-65", properties={
                "Surface Before Work?": {"type": "checkbox", "checkbox": False},
            })],
            "has_more": False,
            "next_cursor": None,
        },
    )
    assert result.lesson_retrieval_status is not LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ()


@pytest.mark.parametrize(
    "pagination",
    [
        {"has_more": False, "next_cursor": "contradiction"},
        {"has_more": True, "next_cursor": None},
        {"has_more": "false", "next_cursor": None},
    ],
    ids=["terminal-with-cursor", "unfinished-without-cursor", "malformed-has-more"],
)
def test_contradictory_ckr11_page_never_admits_non51(pagination):
    with pytest.raises(LessonActivationError):
        orchestrate_lesson_activation(
            ci_request(),
            execute_read=lambda query: {
                "results": [synthetic_notion_row("LL-65")],
                **pagination,
            },
        )


def test_not_needed_ckr6_preflight_reads_zero_rows():
    calls = []
    result = orchestrate_lesson_activation(
        ci_request(specialized_knowledge_required=False),
        execute_read=lambda query: calls.append(query),
    )
    assert calls == []
    assert result.lesson_retrieval_status is LessonRetrievalStatus.NOT_NEEDED
    assert result.selected_lesson_ids == ()
