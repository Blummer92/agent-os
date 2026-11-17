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


def _assert_snapshot_row_bound_calls(calls):
    """An oversized snapshot page is rejected before normalization or selection."""
    assert len(calls) == 1
    assert calls[0]["page_size"] == 100
    assert "start_cursor" not in calls[0]
    assert len(calls[0]["filter"]["and"]) == 2


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
        "results": [_row(n) for n in range(101)], "has_more": True, "next_cursor": CURSOR,
    })
    result, sink = _run(monkeypatch, reader)
    _assert_fail_closed(result)
    assert sink[0]["retrieval_reason_code"] == "lesson-read-incomplete"
    assert sink[0]["incomplete_reason_code"] == "row-bound-exceeded"
    _assert_snapshot_row_bound_calls(reader.calls)  # no cursor continuation; bounded STOP
    assert CURSOR not in json.dumps(result) + json.dumps(sink)


def test_case_c_provider_429_is_distinct_and_fail_closed(monkeypatch):
    result_b, _ = _run(monkeypatch, _counting({
        "results": [_row(n) for n in range(101)], "has_more": True, "next_cursor": CURSOR,
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
            return {"results": [_row(n) for n in range(101)],
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
    if scenario == "row-bound":
        _assert_snapshot_row_bound_calls(calls)
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


def test_unmapped_incomplete_error_uses_static_fallback(monkeypatch):
    from agent_memory_context_manager.lesson_activation_bridge import LessonActivationError
    result, sink = _run(monkeypatch, _counting(LessonActivationError("unrecognized private payload")))
    _assert_fail_closed(result)
    assert sink[0]["retrieval_reason_code"] == "lesson-read-incomplete"
    assert sink[0]["incomplete_reason_code"] == "unknown-incomplete"
    assert "private payload" not in json.dumps(result) + json.dumps(sink)


@pytest.mark.parametrize(("failure", "expected"), [
    (TimeoutError("private timeout details"), "lesson-read-timeout"),
    (ConnectionError("private connection details"), "lesson-read-connection-error"),
])
def test_transport_failures_are_distinct_and_fail_closed(monkeypatch, failure, expected):
    result, sink = _run(monkeypatch, _counting(failure))
    _assert_fail_closed(result)
    assert sink[0]["retrieval_reason_code"] == expected
    assert sink[0]["incomplete_reason_code"] == "none"
    assert "private" not in json.dumps(result) + json.dumps(sink)

def test_sanitized_retrieval_diagnostics_artifact_tracks_exact_failure(tmp_path, monkeypatch):
    reader = _counting({
        "results": [_row(n) for n in range(101)],
        "has_more": True,
        "next_cursor": CURSOR,
    })
    result, sink = _run(monkeypatch, reader)
    _assert_fail_closed(result)
    target = tmp_path / "retrieval-diagnostics.json"
    assert bridge.write_retrieval_diagnostics_artifact(sink[0], target) is True
    data = json.loads(target.read_text())
    assert data["retrieval_reason_code"] == "lesson-read-incomplete"
    assert data["incomplete_reason_code"] == "row-bound-exceeded"
    assert data["read_count"] == 1
    _assert_snapshot_row_bound_calls(reader.calls)
    assert CURSOR not in target.read_text()
    assert SENSITIVE_SAMPLE not in target.read_text()
    assert "retrieval_diagnostics" not in json.dumps(result)
    assert set(result) <= bridge.RESULT_FIELDS


def test_diagnostic_artifact_rejects_untrusted_fields_boolean_counters_and_secret_text(tmp_path):
    valid = {
        "retrieval_reason_code": "notion-http-429",
        "incomplete_reason_code": "none",
        "read_count": 1,
        "observed_rows": 0,
        "normalized_rows": 0,
        "skipped_rows": 0,
        "candidate_count": 0,
    }
    target = tmp_path / "retrieval-diagnostics.json"
    assert bridge.write_retrieval_diagnostics_artifact(valid, target)
    before = target.read_text()
    variants = [
        {**valid, "raw_provider_text": SENSITIVE_SAMPLE},
        {**valid, "retrieval_reason_code": SENSITIVE_SAMPLE},
        {**valid, "incomplete_reason_code": CURSOR},
        {**valid, "read_count": True},
        {**valid, "candidate_count": 10001},
    ]
    for hostile in variants:
        assert bridge.write_retrieval_diagnostics_artifact(hostile, target) is False
        assert target.read_text() == before
    assert bridge.write_retrieval_diagnostics_artifact(None, target) is False
    assert bridge.write_retrieval_diagnostics_artifact(valid, tmp_path) is False
    assert SENSITIVE_SAMPLE not in target.read_text()



def test_main_cli_writes_sanitized_diagnostics_next_to_trusted_result(monkeypatch, tmp_path):
    import sys
    request = {
        "operation": "failed-repair", "repository": "Blummer92/agent-os",
        "issue_number": 3985, "task_reference": "PR #3985 diagnostics test",
        "ecosystem_hints": ["python"], "language_hints": ["Python"],
        "library_hints": [], "capability_keywords": ["failure-avoidance"],
        "target_path_hints": [], "canonical_rule_refs": [], "known_knowledge_refs": [],
        "specialized_knowledge_required": True, "attempt_id": "diag-cli-1",
        "failed_hypothesis": "h", "result_summary": "r", "repair_context": "ci-diagnosis",
    }
    event = {
        "repository": {"full_name": "Blummer92/agent-os"},
        "issue": {"number": 3985, "pull_request": {}},
        "comment": {"body": "/agent-os ckr6 " + json.dumps(request),
                    "user": {"login": "Blummer92"}},
    }
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(event), encoding="utf-8")
    result_file = tmp_path / "result.json"
    route = type("Route", (), {})()
    route.execute_read = _counting(RuntimeError("notion-http-429"))
    monkeypatch.setattr(bridge, "resolve_lesson_read_route", lambda: route)
    monkeypatch.setattr(sys, "argv", [
        "ckr6_github_bridge", "--phase", "execute", "--event", str(event_file),
        "--repository", "Blummer92/agent-os", "--allowed-actor", "Blummer92",
        "--retrieval-required", "true", "--output", str(result_file),
    ])
    assert bridge.main() == 0
    trusted = json.loads(result_file.read_text(encoding="utf-8"))
    diagnostic = json.loads((tmp_path / "retrieval-diagnostics.json").read_text(encoding="utf-8"))
    assert trusted["status"] == "insufficient"
    assert trusted["mutation_admissible"] is False
    assert set(trusted) <= bridge.RESULT_FIELDS
    assert diagnostic["retrieval_reason_code"] == "notion-http-429"
    assert diagnostic["incomplete_reason_code"] == "none"
    assert "retrieval_reason_code" not in trusted


def test_workflow_artifact_manifest_preserves_trusted_result_and_diagnostics():
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github/workflows/agent-os-ckr6.yml").read_text(encoding="utf-8")
    upload = workflow.split("- name: Publish bounded CKR6 evidence", 1)[1].split(
        "- name: Post bounded CKR6 result to issue", 1
    )[0]
    assert upload.count("uses: actions/upload-artifact@v7") == 1
    assert "${{ runner.temp }}/agent-os-ckr6/result.json" in upload
    assert "${{ runner.temp }}/agent-os-ckr6/retrieval-diagnostics.json" in upload
    assert "if-no-files-found: warn" in upload


def _issue_start_envelope():
    return bridge.parse_envelope({
        "operation": "issue-start", "repository": "Blummer92/agent-os",
        "issue_number": 3986, "task_reference": "issue-start diagnostics propagation",
        "ecosystem_hints": ["python"], "language_hints": ["Python"],
        "library_hints": [], "capability_keywords": ["failure-avoidance"],
        "target_path_hints": [], "canonical_rule_refs": [], "known_knowledge_refs": [],
        "specialized_knowledge_required": True,
    })


def _run_issue_start(monkeypatch, reader):
    route = type("Route", (), {})()
    route.execute_read = reader
    monkeypatch.setattr(bridge, "resolve_lesson_read_route", lambda: route)
    sink: list = []
    result = bridge.execute_envelope(
        _issue_start_envelope(), retrieval_required=True, diagnostics_sink=sink
    )
    return result, sink


def _assert_issue_start_governance(result):
    assert result["mutation_admissible"] is False
    assert set(result) <= bridge.RESULT_FIELDS
    assert "retrieval_diagnostics" not in result
    for flag in ("execution_authorized", "github_writes_authorized", "merge_authorized",
                 "closure_authorized", "side_effects_performed"):
        assert result[flag] is False


def test_issue_start_normal_read_reaches_artifact_with_actual_counters(monkeypatch, tmp_path):
    reader = _counting({"results": [_row(1), _row(2), _row(3)], "has_more": False})
    result, sink = _run_issue_start(monkeypatch, reader)
    assert result["status"] == "sufficient"
    assert result["selected_lesson_ids"] == ["LL-1", "LL-2", "LL-3"]
    _assert_issue_start_governance(result)
    target = tmp_path / "retrieval-diagnostics.json"
    assert bridge.write_retrieval_diagnostics_artifact(sink[0], target) is True
    data = json.loads(target.read_text())
    assert data["read_count"] == 1
    assert data["observed_rows"] == 3
    assert data["normalized_rows"] == 3
    assert data["candidate_count"] == 3
    assert data["incomplete_reason_code"] == "none"


def test_issue_start_incomplete_page_reaches_artifact_with_row_bound_and_read_count(monkeypatch, tmp_path):
    reader = _counting({
        "results": [_row(n) for n in range(101)], "has_more": True, "next_cursor": CURSOR,
    })
    result, sink = _run_issue_start(monkeypatch, reader)
    assert result["status"] == "insufficient"
    assert result["selected_lesson_ids"] == []
    _assert_snapshot_row_bound_calls(reader.calls)
    _assert_issue_start_governance(result)
    target = tmp_path / "retrieval-diagnostics.json"
    assert bridge.write_retrieval_diagnostics_artifact(sink[0], target) is True
    data = json.loads(target.read_text())
    assert data["retrieval_reason_code"] == "lesson-read-incomplete"
    assert data["incomplete_reason_code"] == "row-bound-exceeded"
    assert data["read_count"] == 1
    text = target.read_text()
    assert CURSOR not in text and CURSOR not in json.dumps(result)


def test_issue_start_adversarial_reader_text_never_reaches_result_or_artifact(monkeypatch, tmp_path):
    result, sink = _run_issue_start(
        monkeypatch, _counting(RuntimeError(f"upstream {SENSITIVE_SAMPLE} {CURSOR}"))
    )
    assert result["status"] == "insufficient"
    _assert_issue_start_governance(result)
    target = tmp_path / "retrieval-diagnostics.json"
    assert bridge.write_retrieval_diagnostics_artifact(sink[0], target) is True
    blob = target.read_text() + json.dumps(result) + json.dumps(sink)
    assert SENSITIVE_SAMPLE not in blob and CURSOR not in blob


def test_issue_start_malformed_page_and_unsupported_values_stay_finite(monkeypatch, tmp_path):
    hostile_row = _row(7)
    hostile_row["properties"]["Lesson Learned"] = {"type": "unsupported", "payload": SENSITIVE_SAMPLE}
    for response in ({"results": "not-a-list", "has_more": False},
                     {"results": [hostile_row, "junk", 5, None], "has_more": False}):
        result, sink = _run_issue_start(monkeypatch, _counting(response))
        _assert_issue_start_governance(result)
        target = tmp_path / "d.json"
        assert bridge.write_retrieval_diagnostics_artifact(sink[0], target) is True
        data = json.loads(target.read_text())
        assert all(type(v) is int and 0 <= v <= 10000 for k, v in data.items() if k.endswith(("_count", "_rows")))
        assert SENSITIVE_SAMPLE not in target.read_text()


def test_failed_repair_artifact_values_unchanged_alongside_issue_start(monkeypatch):
    reader = _counting({"results": [_row(n) for n in range(101)], "has_more": True, "next_cursor": CURSOR})
    _, sink = _run(monkeypatch, reader)
    assert sink[0]["incomplete_reason_code"] == "row-bound-exceeded"
    assert sink[0]["read_count"] == 1
    _assert_snapshot_row_bound_calls(reader.calls)

def test_read_budget_stop_is_distinguishable_and_still_fails_closed(monkeypatch, tmp_path):
    import agent_memory_context_manager.lesson_retrieval_orchestrator as orch
    monkeypatch.setattr(orch, "MAX_PREFLIGHT_READS", 2)
    calls = []

    def reader(query):
        calls.append(dict(query))
        return {"results": [_row(n) for n in range(25)],
                "has_more": True, "next_cursor": f"{CURSOR}-{len(calls)}"}

    result, sink = _run(monkeypatch, reader)
    assert result["mutation_admissible"] is False
    assert result["selected_lesson_ids"] == []
    assert sink[0]["incomplete_reason_code"] == "read-budget-exceeded"
    assert sink[0]["read_count"] == 2
    assert len(calls) == 2
    assert calls[1]["start_cursor"] == f"{CURSOR}-1"
    assert all(query["page_size"] == 100 for query in calls)
    assert sink[0]["terminal_query_bucket"] == "workspace"
    target = tmp_path / "budget.json"
    assert bridge.write_retrieval_diagnostics_artifact(sink[0], target)
    assert json.loads(target.read_text())["incomplete_reason_code"] == "read-budget-exceeded"
    assert set(result) <= bridge.RESULT_FIELDS


def test_terminal_query_bucket_survives_only_sanitized_diagnostic_artifact(monkeypatch, tmp_path):
    reader = _counting({"results": [_row(n) for n in range(101)],
                        "has_more": True, "next_cursor": CURSOR})
    result, sink = _run(monkeypatch, reader)
    assert result["mutation_admissible"] is False
    assert sink[0]["terminal_query_bucket"] == "workspace"
    target = tmp_path / "bucket.json"
    assert bridge.write_retrieval_diagnostics_artifact(sink[0], target)
    assert json.loads(target.read_text())["terminal_query_bucket"] == sink[0]["terminal_query_bucket"]
    assert CURSOR not in target.read_text()
    assert "terminal_query_bucket" not in json.dumps(result)
    assert set(result) <= bridge.RESULT_FIELDS


def test_terminal_query_bucket_rejects_hostile_values_and_summary_leaks(tmp_path):
    base = {
        "retrieval_reason_code": "lesson-read-incomplete",
        "incomplete_reason_code": "row-bound-exceeded",
        "read_count": 3, "observed_rows": 0, "normalized_rows": 0,
        "skipped_rows": 0, "candidate_count": 0,
        "terminal_query_bucket": "area:Testing/type:Testing lesson",
    }
    path = tmp_path / "bucket.json"
    assert bridge.write_retrieval_diagnostics_artifact(base, path)
    before = path.read_text()
    for attack in (SENSITIVE_SAMPLE, CURSOR, 4, True, None, ["Testing"]):
        hostile = {**base, "terminal_query_bucket": attack}
        assert bridge.write_retrieval_diagnostics_artifact(hostile, path) is False
        assert path.read_text() == before
        projected = bridge.retrieval_diagnostics_projection({
            "retrieval_diagnostics": hostile,
            "selection_reason_codes": ["lesson-read-incomplete"],
        })
        assert projected["terminal_query_bucket"] == "unobserved"
        assert SENSITIVE_SAMPLE not in json.dumps(projected)
    assert "terminal_query_bucket" not in bridge.retrieval_diagnostics_projection({
        "retrieval_diagnostics": {"read_count": 2},
    })



# #4011: New page fields are emitted only in separate sanitized artifacts.
@pytest.mark.parametrize(("count", "has_more", "row_bucket", "more_bucket", "cursor"), [
    (100, True, "over-25", "true", True),
    (101, False, "over-25", "false", False),
])
def test_4011_two_terminal_page_shapes_are_finite_and_fail_closed(
    monkeypatch, tmp_path, count, has_more, row_bucket, more_bucket, cursor
):
    reader = _counting({
        "results": [_row(n) for n in range(count)],
        "has_more": has_more,
        "next_cursor": CURSOR if has_more else None,
    })
    result, sink = _run(monkeypatch, reader)
    _assert_fail_closed(result)
    assert sink[0]["incomplete_reason_code"] == "row-bound-exceeded"
    assert sink[0]["terminal_page_row_count_bucket"] == row_bucket
    assert sink[0]["terminal_page_has_more"] == more_bucket
    assert sink[0]["terminal_page_cursor_present"] is cursor
    assert "terminal_page_row_count_bucket" not in json.dumps(result)
    target = tmp_path / "retrieval-diagnostics.json"
    assert bridge.write_retrieval_diagnostics_artifact(sink[0], target)
    written = json.loads(target.read_text())
    assert written["terminal_page_row_count_bucket"] == row_bucket
    assert written["terminal_page_has_more"] == more_bucket
    assert written["terminal_page_cursor_present"] is cursor
    assert CURSOR not in target.read_text()
    assert SENSITIVE_SAMPLE not in target.read_text()
    summary = tmp_path / "summary.md"
    assert bridge.write_retrieval_diagnostics_summary(
        sink[0], {"GITHUB_STEP_SUMMARY": str(summary)}
    )
    assert CURSOR not in summary.read_text()


def test_4011_legacy_success_has_no_terminal_page_metadata(monkeypatch, tmp_path):
    result, sink = _run(monkeypatch, _counting({
        "results": [_row(1)], "has_more": False
    }))
    assert result["status"] == "sufficient"
    assert not any(key.startswith("terminal_page_") for key in sink[0])
    path = tmp_path / "normal.json"
    assert bridge.write_retrieval_diagnostics_artifact(sink[0], path)
    assert not any(key.startswith("terminal_page_") for key in json.loads(path.read_text()))


def test_4011_projection_drops_partial_invalid_or_untrusted_page_signature(tmp_path):
    valid = {
        "retrieval_reason_code": "lesson-read-incomplete",
        "incomplete_reason_code": "row-bound-exceeded",
        "read_count": 3, "observed_rows": 0, "normalized_rows": 0,
        "skipped_rows": 0, "candidate_count": 0,
        "terminal_query_bucket": "workspace",
        "terminal_page_row_count_bucket": "25",
        "terminal_page_has_more": "true",
        "terminal_page_cursor_present": True,
    }
    dest = tmp_path / "sanitized.json"
    assert bridge.write_retrieval_diagnostics_artifact(valid, dest)
    before = dest.read_text()
    for name, bad in [
        ("terminal_page_row_count_bucket", "26:" + SENSITIVE_SAMPLE),
        ("terminal_page_row_count_bucket", True),
        ("terminal_page_has_more", CURSOR),
        ("terminal_page_has_more", 1),
        ("terminal_page_cursor_present", "yes"),
        ("terminal_page_cursor_present", 1),
    ]:
        damaged = {**valid, name: bad}
        assert bridge.write_retrieval_diagnostics_artifact(damaged, dest) is False
        assert dest.read_text() == before
        projected = bridge.retrieval_diagnostics_projection({
            "retrieval_diagnostics": damaged,
            "selection_reason_codes": ["lesson-read-incomplete"],
        })
        assert projected is not None
        assert not any(k.startswith("terminal_page_") for k in projected)
    for absent in valid.keys() & bridge._TERMINAL_PAGE_KEYS:
        partial = {k: v for k, v in valid.items() if k != absent}
        assert bridge.write_retrieval_diagnostics_artifact(partial, dest) is False
        assert dest.read_text() == before
    assert bridge.write_retrieval_diagnostics_artifact(
        {**valid, "raw_cursor": CURSOR}, dest
    ) is False
    assert dest.read_text() == before
    assert CURSOR not in dest.read_text()


def test_4011_invalid_incomplete_code_blocks_page_fields(tmp_path):
    valid = {
        "retrieval_reason_code": "none", "incomplete_reason_code": "none",
        "read_count": 1, "observed_rows": 0, "normalized_rows": 0,
        "skipped_rows": 0, "candidate_count": 0,
        "terminal_query_bucket": "workspace",
        "terminal_page_row_count_bucket": "25",
        "terminal_page_has_more": "true",
        "terminal_page_cursor_present": True,
    }
    target = tmp_path / "invalid.json"
    assert bridge.write_retrieval_diagnostics_artifact(valid, target) is False
    projected = bridge.retrieval_diagnostics_projection({
        "retrieval_diagnostics": valid, "selection_reason_codes": [],
    })
    assert projected is not None
    assert "terminal_page_row_count_bucket" not in projected


def test_4011_no_response_does_not_invent_page_signature(monkeypatch):
    result, sink = _run(monkeypatch, _counting(ConnectionError("PRIVATE NO RESPONSE")))
    _assert_fail_closed(result)
    assert not any(k.startswith("terminal_page_") for k in sink[0])
    assert "PRIVATE" not in json.dumps(result) + json.dumps(sink)


def test_4011_direct_summary_writer_refuses_hostile_or_partial_page_signature(tmp_path):
    valid = {
        "retrieval_reason_code": "lesson-read-incomplete",
        "incomplete_reason_code": "row-bound-exceeded",
        "read_count": 3, "observed_rows": 0, "normalized_rows": 0,
        "skipped_rows": 0, "candidate_count": 0,
        "terminal_query_bucket": "workspace",
        "terminal_page_row_count_bucket": "25",
        "terminal_page_has_more": "true",
        "terminal_page_cursor_present": True,
    }
    target = tmp_path / "summary.md"
    env = {"GITHUB_STEP_SUMMARY": str(target)}
    assert bridge.write_retrieval_diagnostics_summary(valid, env) is True
    safe_text = target.read_text()
    for invalid in (
        {**valid, "terminal_page_row_count_bucket": SENSITIVE_SAMPLE},
        {**valid, "terminal_page_has_more": CURSOR},
        {**valid, "terminal_page_cursor_present": "yes"},
        {**valid, "incomplete_reason_code": "none"},
        {k: v for k, v in valid.items() if k != "terminal_page_has_more"},
    ):
        assert bridge.write_retrieval_diagnostics_summary(invalid, env) is False
        assert target.read_text() == safe_text
    assert CURSOR not in safe_text and SENSITIVE_SAMPLE not in safe_text


def test_4011_direct_summary_refuses_untrusted_reason_counters_and_extra_fields(tmp_path):
    """The Actions summary is an export boundary even when called directly."""
    valid = {
        "retrieval_reason_code": "lesson-read-incomplete",
        "incomplete_reason_code": "row-bound-exceeded",
        "read_count": 3, "observed_rows": 0, "normalized_rows": 0,
        "skipped_rows": 0, "candidate_count": 0,
        "terminal_query_bucket": "workspace",
        "terminal_page_row_count_bucket": "25",
        "terminal_page_has_more": "true",
        "terminal_page_cursor_present": True,
    }
    target = tmp_path / "summary.md"
    env = {"GITHUB_STEP_SUMMARY": str(target)}
    assert bridge.write_retrieval_diagnostics_summary(valid, env)
    expected = target.read_text()
    hostile_inputs = (
        {**valid, "retrieval_reason_code": SENSITIVE_SAMPLE},
        {**valid, "incomplete_reason_code": CURSOR},
        {**valid, "terminal_query_bucket": SENSITIVE_SAMPLE},
        {**valid, "read_count": "3 with SECRET"},
        {**valid, "candidate_count": 10001},
        {**valid, "observed_rows": True},
        {**valid, "raw_provider_row": SENSITIVE_SAMPLE},
        {**valid, "incomplete_reason_code": "none"},
    )
    for payload in hostile_inputs:
        assert bridge.write_retrieval_diagnostics_summary(payload, env) is False
        assert target.read_text() == expected
    assert CURSOR not in expected
    assert SENSITIVE_SAMPLE not in expected
