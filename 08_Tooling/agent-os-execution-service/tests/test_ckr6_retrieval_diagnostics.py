"""Observational CKR6 retrieval diagnostics (read-failure visibility).

Uses the real bridge -> facade -> CKR11 orchestrator call path with injected
fake read executors. No Notion, no network, no GitHub writes. The trusted
result-comment schema and admission semantics are asserted unchanged.
"""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge

REVISION = "2026-10-08T12:00:00.000Z"
SENSITIVE_SAMPLE = "synthetic sensitive-content sentinel; never a real credential"
CURSOR = "SENSITIVE_SAMPLE-CURSOR-DO-NOT-LEAK"


def _rt(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text}]}


def _row(number):
    return {
        "object": "page", "last_edited_time": REVISION,
        "url": f"https://www.notion.so/{number}",
        "properties": {
            "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": number}},
            "Lesson Learned": {"type": "title", "title": [{"plain_text": "Verify labels"}]},
            "Status": {"type": "select", "select": {"name": "New"}},
            "Surface Before Work?": {"type": "checkbox", "checkbox": True},
            "Area": {"type": "select", "select": {"name": "Governance"}},
            "Learning Type": {"type": "select", "select": {"name": "Mistake"}},
            "Applies To": {"type": "multi_select", "multi_select": [{"name": "Notion"}]},
            "Source Link": {"type": "url", "url": "https://github.com/Blummer92/agent-os/issues/3305"},
            "Guardrail": _rt("Verify the exact result and do not bypass checks."),
            "What To Do Next Time": _rt("Use canonical evidence before repair."),
        },
    }


def _envelope():
    return bridge.parse_envelope({
        "operation": "failed-repair", "repository": "Blummer92/agent-os",
        "issue_number": 3985, "task_reference": "PR #3985 diagnostics test",
        "ecosystem_hints": ["python"], "language_hints": ["Python"],
        "library_hints": [], "capability_keywords": ["failure-avoidance"],
        "target_path_hints": [], "canonical_rule_refs": [], "known_knowledge_refs": [],
        "specialized_knowledge_required": True, "attempt_id": "attempt-diag-1",
        "failed_hypothesis": "h", "result_summary": "r", "repair_context": "ci-diagnosis",
    })


def _run(monkeypatch, reader):
    route = type("Route", (), {})()
    route.execute_read = reader
    monkeypatch.setattr(bridge, "resolve_lesson_read_route", lambda: route)
    sink: list = []
    result = bridge.execute_envelope(
        _envelope(), retrieval_required=True, diagnostics_sink=sink
    )
    return result, sink


def _counting(response_or_exc):
    calls = []

    def execute_read(query):
        calls.append(deepcopy(query))
        if isinstance(response_or_exc, BaseException):
            raise response_or_exc
        return deepcopy(response_or_exc)

    execute_read.calls = calls
    return execute_read


def _assert_fail_closed(result):
    assert result["status"] == "insufficient"
    assert result["selected_lesson_ids"] == []
    assert result["selected_lessons"] == []
    assert result["mutation_admissible"] is False
    assert result["retry_reentry_outcome"] == "unavailable-or-failed"
    for flag in ("execution_authorized", "github_writes_authorized", "merge_authorized",
                 "closure_authorized", "side_effects_performed"):
        assert result[flag] is False


def test_case_a_complete_retrieval_selects_normally_and_reports_none(monkeypatch):
    reader = _counting({"results": [_row(1), _row(2), _row(3)], "has_more": False})
    result, sink = _run(monkeypatch, reader)
    assert result["status"] == "sufficient"
    assert result["mutation_admissible"] is True
    assert result["retry_reentry_outcome"] == "consumed"
    assert result["selected_lesson_ids"] == ["LL-1", "LL-2", "LL-3"]
    assert sink == [{
        "retrieval_reason_code": "none", "incomplete_reason_code": "none",
        "read_count": 1, "observed_rows": 3,
        "normalized_rows": 3, "skipped_rows": 0, "candidate_count": 3,
    }]


def test_case_b_incomplete_pagination_is_distinct_and_fail_closed(monkeypatch):
    reader = _counting({
        "results": [_row(n) for n in range(25)], "has_more": True, "next_cursor": CURSOR,
    })
    result, sink = _run(monkeypatch, reader)
    _assert_fail_closed(result)
    assert sink[0]["retrieval_reason_code"] == "lesson-read-incomplete"
    assert sink[0]["incomplete_reason_code"] == "row-bound-exceeded"
    assert len(reader.calls) == 1  # no unauthorized continuation after the STOP
    assert CURSOR not in json.dumps(result) + json.dumps(sink)


def test_case_c_provider_429_is_distinct_and_fail_closed(monkeypatch):
    result_b, _ = _run(monkeypatch, _counting({
        "results": [_row(n) for n in range(25)], "has_more": True, "next_cursor": CURSOR,
    }))
    reader = _counting(RuntimeError("notion-http-429"))
    result_c, sink = _run(monkeypatch, reader)
    _assert_fail_closed(result_c)
    assert sink[0]["retrieval_reason_code"] == "notion-http-429"
    # The public trusted result is identical for B and C: this is the loss the
    # diagnostic surface now makes observable without changing it.
    assert result_b == result_c
    assert len(reader.calls) == 1


def test_case_d_unknown_exception_and_sensitive_text_never_surface(monkeypatch, tmp_path):
    reader = _counting(RuntimeError(f"upstream said {SENSITIVE_SAMPLE} " + "x" * 5000))
    result, sink = _run(monkeypatch, reader)
    _assert_fail_closed(result)
    assert sink[0]["retrieval_reason_code"] == "lesson-read-runtime-error"
    summary = tmp_path / "summary.md"
    assert bridge.write_retrieval_diagnostics_summary(
        sink[0], {"GITHUB_STEP_SUMMARY": str(summary)}
    ) is True
    text = summary.read_text(encoding="utf-8")
    assert SENSITIVE_SAMPLE not in text and SENSITIVE_SAMPLE not in json.dumps(result) + json.dumps(sink)
    assert "xxxx" not in text
    assert len(text) < 1024


def test_case_d_projection_rejects_hostile_values():
    hostile = {
        "retrieval_diagnostics": {
            "read_count": True, "observed_rows": 10**9, "normalized_rows": -1,
            "skipped_rows": "7", "candidate_count": 4,
            "raw_page": {"secret": SENSITIVE_SAMPLE}, "next_cursor": CURSOR,
        },
        "selection_reason_codes": [
            SENSITIVE_SAMPLE, "notion-" + "a" * 200, "Notion-http-429", {"x": 1}, "notion-http-503",
        ],
    }
    assert bridge.retrieval_diagnostics_projection(hostile) == {
        "retrieval_reason_code": "notion-http-503",
        "incomplete_reason_code": "none",
        "read_count": 0, "observed_rows": 0, "normalized_rows": 0,
        "skipped_rows": 0, "candidate_count": 4,
    }
    assert bridge.retrieval_diagnostics_projection({}) is None
    assert bridge.retrieval_diagnostics_projection("not a mapping") is None  # type: ignore[arg-type]


def test_summary_failures_are_swallowed(tmp_path):
    projected = {"retrieval_reason_code": "none", "read_count": 1, "observed_rows": 0,
                 "normalized_rows": 0, "skipped_rows": 0, "candidate_count": 0}
    assert bridge.write_retrieval_diagnostics_summary(projected, {}) is False
    assert bridge.write_retrieval_diagnostics_summary(
        projected, {"GITHUB_STEP_SUMMARY": str(tmp_path)}  # a directory: OSError
    ) is False
    assert bridge.write_retrieval_diagnostics_summary(None, {"GITHUB_STEP_SUMMARY": "x"}) is False


def test_trusted_result_schema_and_default_behavior_unchanged(monkeypatch):
    reader = _counting(RuntimeError("notion-http-429"))
    route = type("Route", (), {})()
    route.execute_read = reader
    monkeypatch.setattr(bridge, "resolve_lesson_read_route", lambda: route)
    result = bridge.execute_envelope(_envelope(), retrieval_required=True)  # no sink
    assert set(result) <= bridge.RESULT_FIELDS
    assert "retrieval_diagnostics" not in result and "retrieval_reason_code" not in result
    body = bridge.serialize_ckr6_result_comment(result, request_comment_id=1)
    assert "notion-http-429" not in body
    assert bridge.parse_ckr6_result_comment(body)["mutation_admissible"] is False


@pytest.mark.parametrize(("scenario", "expected_code", "expected_reads"), [
    ("row-bound", "row-bound-exceeded", 1),
    ("page-bound", "page-bound-exceeded", 5),
    ("missing-cursor", "missing-cursor", 1),
    ("repeated-cursor", "repeated-cursor", 2),
    ("malformed-page", "malformed-page", 1),
    ("malformed-pagination", "malformed-pagination", 1),
])
def test_incomplete_subreasons_are_finite_and_fail_closed(
    monkeypatch, scenario, expected_code, expected_reads
):
    calls = []

    def read(query):
        calls.append(dict(query))
        if scenario == "row-bound":
            return {"results": [_row(n) for n in range(25)],
                    "has_more": True, "next_cursor": "cursor-next"}
        if scenario == "page-bound":
            return {"results": [], "has_more": True,
                    "next_cursor": f"cursor-{len(calls)}"}
        if scenario == "missing-cursor":
            return {"results": [], "has_more": True, "next_cursor": None}
        if scenario == "repeated-cursor":
            return {"results": [], "has_more": True, "next_cursor": "same-cursor"}
        if scenario == "malformed-page":
            return {"results": "not-a-list", "has_more": False}
        if scenario == "malformed-pagination":
            return {"results": [], "has_more": "not-a-bool"}
        raise AssertionError("unknown test scenario")

    result, sink = _run(monkeypatch, read)
    _assert_fail_closed(result)
    assert len(calls) == expected_reads
    assert sink[0]["retrieval_reason_code"] == "lesson-read-incomplete"
    assert sink[0]["incomplete_reason_code"] == expected_code
    assert "incomplete_reason_code" not in json.dumps(result)
    assert "cursor-next" not in json.dumps(sink)
    assert "same-cursor" not in json.dumps(sink)


def test_incomplete_reason_projection_ignores_untrusted_detail():
    raw = {
        "retrieval_diagnostics": {
            "incomplete_reason_code": "SENSITIVE_SAMPLE-DO-NOT-LEAK",
            "read_count": 1,
        },
        "selection_reason_codes": ["lesson-read-incomplete"],
    }
    projected = bridge.retrieval_diagnostics_projection(raw)
    assert projected is not None
    assert projected["retrieval_reason_code"] == "lesson-read-incomplete"
    assert projected["incomplete_reason_code"] == "none"
    assert "SENSITIVE_SAMPLE-DO-NOT-LEAK" not in json.dumps(projected)
