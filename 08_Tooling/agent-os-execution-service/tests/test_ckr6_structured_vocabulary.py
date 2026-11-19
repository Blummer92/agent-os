"""Targeted offline provider controls, usable by stock pytest in execution-service.

Suggested path: 08_Tooling/agent-os-execution-service/tests/test_ckr6_structured_vocabulary.py
Rows are synthetic; these tests never contact Notion or GitHub.
"""
from agent_os_execution_service.issue_start_lesson_preflight import (
    activate_issue_start_lesson_preflight,
)


_OWNER = {
    "repository": "Blummer92/agent-os",
    "issue_number": 4046,
    "task_reference": (
        "Post-4030 CKR6 live canary PR #4046 exact head "
        "25733da31ccd4dae696aed846d0198fe896cc71e; investigate trusted "
        "lesson retrieval, selection relevance, and mutation admission"
    ),
    "ecosystem_hints": ("agent-os",),
    "language_hints": ("python",),
    "library_hints": (),
    "capability_keywords": ("ckr6", "lesson-retrieval", "mutation-boundary", "failed-repair"),
    "target_path_hints": (
        "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/ckr6_mutation_gate.py",
        "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/ckr6_github_bridge.py",
    ),
    "canonical_rule_refs": ("#2425", "#3418"),
    "known_knowledge_refs": (),
    "specialized_knowledge_required": True,
}
_CANONICAL = "CKR6 mutation boundary"
_REVISION = "2026-11-04T12:00:00.000Z"
_ID = "LL-9001"


def _field(kind, value):
    return {"type": kind, kind: value}


def _text(kind, text):
    return _field(kind, [{"plain_text": text}])


def _row(title="CKR6 mutation boundary guard", lesson_type="Mistake", guidance=None):
    return {
        "object": "page", "id": "row-" + _ID, "last_edited_time": _REVISION,
        "url": "https://www.notion.so/synthetic-lesson",
        "properties": {
            "Lesson ID": _text("rich_text", _ID),
            "Lesson Learned": _text("title", title),
            "Status": _field("select", {"name": "Applied"}),
            "Surface Before Work?": _field("checkbox", True),
            "Area": _field("select", {"name": "Documentation"}),
            "Applies To": _field("multi_select", [{"name": "Notion"}]),
            "Learning Type": _field("select", {"name": lesson_type}),
            "Source Link": _field("url", "https://github.com/Blummer92/agent-os/issues/2425"),
            "Guardrail": _text("rich_text", "Never reuse stale evidence."),
            "What To Do Next Time": _text("rich_text", guidance or "Bind CKR6 mutation admission to the exact head."),
        },
    }


def _run(row, **overrides):
    calls = []
    def read(query):
        calls.append(query)
        return {"results": [row], "has_more": False}
    result = activate_issue_start_lesson_preflight(**(_OWNER | overrides), execute_read=read)
    assert result["retrieval_diagnostics"]["normalized_rows"] == 1
    return result, calls


def test_owner_vocabulary_ab_changes_matching_not_query_or_eligibility():
    row = _row()
    exact, exact_calls = _run(row)
    canonical, canonical_calls = _run(
        row, capability_keywords=(*_OWNER["capability_keywords"], _CANONICAL))
    assert exact_calls == canonical_calls
    assert len(exact_calls) == 1
    assert not exact["selected_lessons"]
    assert exact["lesson_retrieval_status"] == "insufficient"
    assert "no-relevant-candidate" in exact["selection_reason_codes"]
    assert exact["retrieval_diagnostics"]["selection_basis"] == "no-relevant-signal"
    assert canonical["lesson_retrieval_status"] == "sufficient"
    assert canonical["retrieval_diagnostics"]["selection_basis"] == "rule-ckr6-mutation-boundary"
    assert canonical["selected_lessons"] == [{
        "lesson_id": _ID, "source_revision": _REVISION,
        "selection_reason_codes": ["verified-ckr6-mutation-context-match"],
    }]
    assert canonical["source_authority"] == "advisory-only"
    assert not canonical["execution_authorized"]


def test_same_lesson_does_not_match_unrelated_packaging_request():
    result, _ = _run(
        _row(), task_reference="offline wheelhouse installation and navigation registry packaging",
        ecosystem_hints=("python",), language_hints=("python",),
        capability_keywords=("offline wheelhouse", "package installation"),
        library_hints=("agent-os-navigation-registry",),
        target_path_hints=("tests/offline_wheelhouse",),
    )
    assert result["lesson_retrieval_status"] == "insufficient"
    assert not result["selected_lessons"]
    assert result["retrieval_diagnostics"]["selection_basis"] == "no-relevant-signal"


def test_generic_lone_capability_overlap_remains_distinct_from_specialized_ckr6():
    generic, _ = _run(
        _row(title="Review smoke check output", lesson_type="Testing lesson",
             guidance="Record the smoke check output."),
        ecosystem_hints=(), language_hints=(), capability_keywords=("testing",), target_path_hints=(),
    )
    assert generic["lesson_retrieval_status"] == "sufficient"
    assert generic["selected_lessons"][0]["selection_reason_codes"] == ["keyword-overlap"]
    assert generic["retrieval_diagnostics"]["selection_basis"] == "generic-unique"


def test_source_root_without_a_github_resource_is_not_canonical_provenance():
    row = _row()
    row["properties"]["Source Link"] = _field("url", "https://github.com/")
    result, _ = _run(
        row, capability_keywords=(*_OWNER["capability_keywords"], _CANONICAL),
    )
    assert result["lesson_retrieval_status"] == "manual-review"
    assert not result["selected_lessons"]
    assert "unverifiable-relevant-candidate" in result["selection_reason_codes"]
