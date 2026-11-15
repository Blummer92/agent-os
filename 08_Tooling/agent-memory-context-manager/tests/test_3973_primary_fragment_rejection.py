"""#3973 follow-up (CKR6 full-database readback, 2026-11-14): a `#` fragment
in the primary Source Link must not be admitted as canonical provenance.

Live LL-71's primary was
`https://github.com/Blummer92/agent-os/pull/1858#pullrequestreview-5125849715`
-- a PR-review anchor, not a canonical issue/PR resource -- and the
pre-fix `_github_source_link` admitted it as CURRENT, so CKR6 selected
LL-71 on the strength of an anchor. A fragment names a sub-resource of a
page, not the resource itself, so it is rejected here (UNVERIFIABLE, zero
refs). Plain resource URLs are unaffected: blob-URL primaries (relied on
by `test_lesson_activation_bridge.py`) and governance-path primaries
still normalize as CURRENT.
"""
from agent_memory_context_manager.lesson_activation_bridge import normalize_lesson_row
from agent_memory_context_manager.lesson_preflight import (
    KnowledgeCurrentness,
    LessonRecordEvidence,
)

PRIMARY = "https://github.com/Blummer92/agent-os/issues/2064"
ANCHOR_PRIMARY = "https://github.com/Blummer92/agent-os/pull/1858#pullrequestreview-5125849715"
COMMENT_ANCHOR_PRIMARY = "https://github.com/Blummer92/agent-os/issues/2064#issuecomment-123456789"
BLOB_PRIMARY = "https://github.com/Blummer92/agent-os/blob/main/01_Shared_Standards/python/testing-standard.md"
GOVERNANCE_PRIMARY = "01_Shared_Standards/python/testing-standard.md"


def _title(text):
    return {"type": "title", "title": [{"plain_text": text}]}


def _rich_text(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text}]}


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
        "Lesson ID": _rich_text("LL-71"),
        "Lesson Learned": _title("Accidental GitHub writes should be disclosed, not hidden with further mutations"),
        "Status": _select("Applied"),
        "Surface Before Work?": _checkbox(True),
        "Area": _select("Governance"),
        "Applies To": _multi_select(),
        "Learning Type": _select("Mistake"),
        "Source Link": _url(PRIMARY),
        "Guardrail": _rich_text("Disclose an accidental write; do not hide it with further mutations."),
        "What To Do Next Time": _rich_text("Disclose the accidental write and stop mutating."),
    }
    properties.update(overrides)
    return {
        "object": "page",
        "id": "test-ll-71",
        "url": "https://app.notion.com/test-ll-71",
        "last_edited_time": "2026-09-07T01:09:22.147Z",
        "properties": properties,
    }


def test_review_anchor_primary_is_unverifiable():
    result = normalize_lesson_row(live_row(**{"Source Link": _url(ANCHOR_PRIMARY)}))
    assert isinstance(result, LessonRecordEvidence)
    assert result.currentness is KnowledgeCurrentness.UNVERIFIABLE
    assert result.canonical_github_refs == ()


def test_comment_anchor_primary_is_unverifiable():
    result = normalize_lesson_row(live_row(**{"Source Link": _url(COMMENT_ANCHOR_PRIMARY)}))
    assert isinstance(result, LessonRecordEvidence)
    assert result.currentness is KnowledgeCurrentness.UNVERIFIABLE
    assert result.canonical_github_refs == ()


def test_plain_pr_primary_still_current():
    result = normalize_lesson_row(
        live_row(**{"Source Link": _url("https://github.com/Blummer92/agent-os/pull/1858")})
    )
    assert isinstance(result, LessonRecordEvidence)
    assert result.currentness is KnowledgeCurrentness.CURRENT
    assert result.canonical_github_refs == ("https://github.com/Blummer92/agent-os/pull/1858",)


def test_blob_primary_still_current():
    result = normalize_lesson_row(live_row(**{"Source Link": _url(BLOB_PRIMARY)}))
    assert isinstance(result, LessonRecordEvidence)
    assert result.currentness is KnowledgeCurrentness.CURRENT
    assert result.canonical_github_refs == (BLOB_PRIMARY,)


def test_governance_path_primary_still_current():
    result = normalize_lesson_row(live_row(**{"Source Link": _url(GOVERNANCE_PRIMARY)}))
    assert isinstance(result, LessonRecordEvidence)
    assert result.currentness is KnowledgeCurrentness.CURRENT
    assert result.canonical_github_refs == (GOVERNANCE_PRIMARY,)
