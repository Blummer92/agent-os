from __future__ import annotations

import json

from agent_os_execution_service import issue_start_lesson_preflight as preflight
from agent_os_execution_service.issue_start_lesson_preflight import activate_issue_start_lesson_preflight


def _title(text):
    return {"type": "title", "title": [{"plain_text": text}]}


def _rich(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text}]}


def _select(name):
    return {"type": "select", "select": {"name": name}}


def _lesson():
    return {
        "object": "page",
        "url": "https://www.notion.so/lesson-63",
        "last_edited_time": "2026-09-09T20:09:14Z",
        "properties": {
            "Lesson ID": _rich("LL-63"),
            "Lesson Learned": _title("Lessons Learned preflight is mandatory before each new repair hypothesis, not optional context"),
            "Status": _select("Applied"),
            "Surface Before Work?": {"type": "checkbox", "checkbox": True},
            "Area": _select("Automation"),
            "Applies To": {"type": "multi_select", "multi_select": [{"name": "automation"}]},
            "Learning Type": _select("Mistake"),
            "Source Link": {"type": "url", "url": "https://github.com/Blummer92/agent-os/issues/2065"},
            "Guardrail": _rich("No new repair hypothesis until relevant Lessons Learned have been checked."),
            "What To Do Next Time": _rich("Before the initial implementation or repair hypothesis, retrieve and consume the smallest relevant Lessons Learned set."),
        },
    }


def test_issue_start_preflight_consumes_relevant_lesson_before_hypothesis():
    calls = []
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os",
        issue_number=2247,
        task_reference="issue:#2247",
        capability_keywords=("automation", "repair", "lessons"),
        canonical_rule_refs=("https://github.com/Blummer92/agent-os/issues/2247",),
        specialized_knowledge_required=True,
        execute_read=lambda query: calls.append(query) or {"results": [_lesson()], "has_more": False},
    )
    assert calls
    assert result["lesson_retrieval_status"] == "sufficient"
    assert result["selected_lesson_ids"] == ["LL-63"]
    assert result["substantial_hypothesis_admissible"] is True
    assert result["handoff_projection"]["known_facts"]
    assert result["source_authority"] == "advisory-only"
    assert result["github_writes_authorized"] is False
    assert result["side_effects_performed"] is False


def test_not_needed_issue_start_performs_zero_notion_reads():
    calls = []
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os",
        issue_number=2247,
        task_reference="issue:#2247",
        specialized_knowledge_required=False,
        execute_read=lambda query: calls.append(query) or {"results": [_lesson()], "has_more": False},
    )
    assert calls == []
    assert result["lesson_retrieval_status"] == "not-needed"
    assert result["selected_lesson_ids"] == []
    assert result["substantial_hypothesis_admissible"] is True


def test_required_issue_start_lessons_fail_closed_when_reader_unavailable():
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os",
        issue_number=2247,
        task_reference="issue:#2247",
        specialized_knowledge_required=True,
        execute_read=None,
    )
    assert result["lesson_retrieval_status"] == "insufficient"
    assert result["substantial_hypothesis_admissible"] is False
    assert result["handoff_projection"]["stop_conditions"]



def test_2780_ordinary_paths_do_not_make_issue_start_lessons_material():
    calls = []
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os",
        issue_number=2780,
        task_reference="issue:#2780",
        target_path_hints=("src/example.py",),
        execute_read=lambda query: calls.append(query) or {"results": [_lesson()], "has_more": False},
    )
    assert calls == []
    assert result["lesson_retrieval_status"] == "not-needed"


def test_2780_generic_capability_metadata_does_not_make_lessons_material():
    calls = []
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os",
        issue_number=2780,
        task_reference="issue:#2780",
        capability_keywords=("validation",),
        execute_read=lambda query: calls.append(query) or {"results": [_lesson()], "has_more": False},
    )
    assert calls == []
    assert result["lesson_retrieval_status"] == "not-needed"


def test_2780_known_lesson_reference_remains_material_without_explicit_override():
    calls = []
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os",
        issue_number=2780,
        task_reference="issue:#2780",
        known_knowledge_refs=("LL-63",),
        execute_read=lambda query: calls.append(query) or {"results": [_lesson()], "has_more": False},
    )
    assert calls
    assert result["lesson_retrieval_status"] != "not-needed"


def test_2780_library_requirement_remains_material_without_explicit_override():
    calls = []
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os",
        issue_number=2780,
        task_reference="issue:#2780",
        library_hints=("specialized-library",),
        execute_read=lambda query: calls.append(query) or {"results": [_lesson()], "has_more": False},
    )
    assert calls
    assert result["lesson_retrieval_status"] != "not-needed"


def test_2780_explicit_specialized_decision_remains_authoritative():
    calls = []
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os",
        issue_number=2780,
        task_reference="issue:#2780 architecture-sensitive",
        capability_keywords=("architecture",),
        specialized_knowledge_required=True,
        execute_read=lambda query: calls.append(query) or {"results": [_lesson()], "has_more": False},
    )
    assert calls
    assert result["lesson_retrieval_status"] != "not-needed"


_DIAGNOSTIC_KEYS = {
    "read_count", "observed_rows", "normalized_rows", "skipped_rows",
    "missing_identity_rows", "missing_revision_rows",
    "missing_source_guidance_rows", "ambiguous_metadata_rows", "candidate_count",
}


def _material_call(reader):
    return activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os",
        issue_number=3986,
        task_reference="issue:#3986",
        capability_keywords=("automation", "repair", "lessons"),
        specialized_knowledge_required=True,
        execute_read=reader,
    )


def test_issue_start_preserves_retrieval_diagnostics_for_normal_read():
    result = _material_call(lambda query: {"results": [_lesson()], "has_more": False})
    diagnostics = result["retrieval_diagnostics"]
    assert isinstance(diagnostics, dict)
    assert _DIAGNOSTIC_KEYS <= set(diagnostics)
    assert diagnostics["read_count"] == 1
    assert diagnostics["observed_rows"] == 1
    assert diagnostics["candidate_count"] == 1
    # Existing selection behavior is unchanged.
    assert result["lesson_retrieval_status"] == "sufficient"
    assert result["selected_lesson_ids"] == ["LL-63"]
    assert "incomplete_reason_code" not in diagnostics


def test_issue_start_diagnostics_are_a_copy_not_the_orchestrator_mapping(monkeypatch):
    # Compare mappings from ONE orchestration call; two separate calls each
    # construct a new mapping and cannot detect a shared-reference alias.
    produced = []
    original_orchestrate = preflight.orchestrate_lesson_retrieval

    def capture_orchestrator_result(*args, **kwargs):
        result = original_orchestrate(*args, **kwargs)
        produced.append(result.retrieval_diagnostics)
        return result

    monkeypatch.setattr(preflight, "orchestrate_lesson_retrieval", capture_orchestrator_result)
    result = _material_call(lambda query: {"results": [_lesson()], "has_more": False})
    assert len(produced) == 1
    returned = result["retrieval_diagnostics"]
    assert returned == produced[0]
    assert returned is not produced[0]
    returned["read_count"] = 99
    assert produced[0]["read_count"] == 1


def test_issue_start_bounded_page_with_more_preserves_row_bound_and_read_count():
    # Snapshot A is independently bounded at 100 rows/page, 5 pages and
    # 500 total. Even a relevant first page cannot admit a partial corpus.
    calls = []

    def reader(query):
        calls.append(dict(query))
        return {
            "results": [_lesson() for _ in range(100)],
            "has_more": True,
            "next_cursor": "SENSITIVE-CURSOR-DO-NOT-LEAK-" + str(len(calls)),
        }

    result = _material_call(reader)
    assert len(calls) == 5
    assert calls[0]["page_size"] == 100
    assert result["lesson_retrieval_status"] == "insufficient"
    assert result["substantial_hypothesis_admissible"] is False
    assert result["selected_lesson_ids"] == []
    assert result["retrieval_diagnostics"]["incomplete_reason_code"] == "row-bound-exceeded"
    assert result["retrieval_diagnostics"]["read_count"] == 5
    assert "SENSITIVE-CURSOR-DO-NOT-LEAK" not in repr(result)


def test_issue_start_governance_flags_unchanged_with_diagnostics():
    result = _material_call(lambda query: {"results": [_lesson()], "has_more": False})
    assert result["source_authority"] == "advisory-only"
    for flag in ("github_writes_authorized", "execution_authorized", "side_effects_performed"):
        assert result[flag] is False
    assert set(result) - {"retrieval_diagnostics"} == {
        "repository", "issue_number", "lesson_retrieval_status", "selected_lesson_ids",
        "selected_lessons", "rejected_candidate_provenance", "materiality_source",
        "selection_reason_codes", "canonical_github_refs", "knowledge_refs",
        "handoff_projection", "substantial_hypothesis_admissible", "preflight_resolved",
        "source_authority", "github_writes_authorized", "execution_authorized",
        "side_effects_performed",
    }


def test_not_needed_and_unbound_reader_diagnostics_stay_finite_and_zero_reads():
    skipped = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os", issue_number=1, task_reference="issue:#1",
        specialized_knowledge_required=False, execute_read=lambda q: 1 / 0,
    )
    assert skipped["lesson_retrieval_status"] == "not-needed"
    # CKR11 exits before creating counters for not-needed work.
    # Assert the exact empty diagnostic contract rather than defaulting a
    # missing read_count to zero or fabricating a measured provider read.
    assert skipped["retrieval_diagnostics"] == {}
    unbound = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os", issue_number=1, task_reference="issue:#1",
        specialized_knowledge_required=True, execute_read=None,
    )
    assert unbound["lesson_retrieval_status"] == "insufficient"
    # An unavailable reader also exits before the counted-read loop.
    assert unbound["retrieval_diagnostics"] == {}


def _archived_lesson(lesson_id):
    row = _lesson()
    row["properties"]["Lesson ID"] = _rich(lesson_id)
    row["properties"]["Status"] = _select("Archived note")
    return row


def _is_known_query(query):
    return "Lesson ID" in json.dumps(query.get("filter", {}))


def _issue_start(**overrides):
    args = dict(
        repository="Blummer92/agent-os",
        issue_number=4016,
        task_reference="issue:#4016",
        capability_keywords=("testing",),
        known_knowledge_refs=("LL-42",),
    )
    args.update(overrides)
    return activate_issue_start_lesson_preflight(**args)


def test_requested_skip_dropped_when_retrieval_fails_closed():
    # #4016 R-4: a skip observed on a page the canonical reader later rejects
    # as incomplete must not survive into rejected-candidate provenance.
    def read(query):
        if _is_known_query(query):
            return {"results": [_archived_lesson("LL-42")], "has_more": False}
        if "start_cursor" not in query:
            return {"results": [_lesson()], "has_more": True, "next_cursor": "c1"}
        return {"results": [_lesson()]}  # missing has_more -> rejected

    result = _issue_start(execute_read=read)
    assert result["lesson_retrieval_status"] == "insufficient"
    assert result["retrieval_diagnostics"]["incomplete_reason_code"] == "malformed-pagination"
    assert result["selected_lesson_ids"] == []
    assert "LL-42" not in [
        item["lesson_id"] for item in result["rejected_candidate_provenance"]
    ]


def test_requested_skip_reported_when_retrieval_completes():
    # Same archived requested lesson, but the retrieval completes: the skip
    # is genuine rejected-candidate evidence and is reported.
    def read(query):
        if _is_known_query(query):
            return {"results": [_archived_lesson("LL-42")], "has_more": False}
        if "start_cursor" not in query:
            return {"results": [_lesson()], "has_more": True, "next_cursor": "c1"}
        return {"results": [_lesson()], "has_more": False}

    result = _issue_start(execute_read=read)
    assert result["lesson_retrieval_status"] == "insufficient"
    assert "incomplete_reason_code" not in result["retrieval_diagnostics"]
    rejected = result["rejected_candidate_provenance"]
    assert "LL-42" in [item["lesson_id"] for item in rejected]


def test_requested_skip_found_beyond_row_25_on_snapshot_page():
    # #4016 R-4: the diagnostic inspection cap is the snapshot page bound, so
    # a requested lesson at index 30 of a 100-row page is still diagnosed.
    # The filler rows carry no Lesson ID, so they are not candidates and do
    # not fill the five-record rejected list; only the requested skip is
    # reported. (When five canonical eligible rejections already fill the
    # cap, a requested skip still cannot surface: that precedence is pinned
    # by test_eligible_rejections_precede_requested_skips_regardless_of_row_order
    # and is out of scope for this repair.)
    page = []
    for _ in range(30):
        row = _lesson()
        del row["properties"]["Lesson ID"]
        page.append(row)
    page.append(_archived_lesson("LL-42"))

    def read(query):
        if _is_known_query(query):
            return {"results": [], "has_more": False}
        return {"results": page, "has_more": False}

    result = _issue_start(execute_read=read)
    rejected = result["rejected_candidate_provenance"]
    assert "LL-42" in [item["lesson_id"] for item in rejected]
