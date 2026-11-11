"""R07 exact request/result consumption binding (#2425 / #2851).

Fail-first consumer tests for the CKR6 result comment: a syntactically
valid result must not satisfy a pending request unless its
``request_comment_id``, issue number, repository, operation, authority
flags, and (for failed-repair) exact failed attempt all bind to that
request. Parser acceptance alone is not consumption: ``parse`` still
accepts a mismatched id (by design); ``consume`` / ``select`` reject it.

The host is the actual downstream consumer and must call these functions
with the exact pending request identity; no host invocation is proven by
these tests alone (see CKR6_HOST_CONSUMPTION_PROOF.md).
"""
from __future__ import annotations

import json

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge

REPOSITORY = "Blummer92/agent-os"
ISSUE = 2425
REQUEST_ID = 1000


def _result(**changes):
    value = {
        "operation": "issue-start",
        "repository": REPOSITORY,
        "issue_number": ISSUE,
        "status": "sufficient",
        "reason_codes": ["lesson-retrieval-required"],
        "selected_lesson_ids": ["LL-87"],
        "selected_lessons": [
            {
                "lesson_id": "LL-87",
                "source_revision": "2026-08-24 13:45:32Z",
                "selection_reason_codes": ["relevant"],
            }
        ],
        "materiality_source": "caller-asserted-material",
        "canonical_github_refs": ["Blummer92/agent-os#2425"],
        "rejected_candidate_provenance": [],
        "handoff_projection": {
            "known_facts": ["coding-knowledge-sufficiency:sufficient"],
            "prior_decisions": [],
            "allowed_inspect_first": [],
            "stop_conditions": [],
        },
        "substantial_hypothesis_admissible": True,
        "mutation_admissible": False,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
        "notion_read_performed": True,
        "retrieval_required": True,
        "recommended_escalation": "filtered-data-source-query",
    }
    value.update(changes)
    return value


def _comment(result, request_comment_id=REQUEST_ID):
    return bridge.serialize_ckr6_result_comment(result, request_comment_id=request_comment_id)


def _raw_comment(payload):
    return bridge.CKR6_RESULT_MARKER + "\n" + json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _consume(body, **kwargs):
    return bridge.consume_ckr6_result_comment(
        body,
        expected_request_comment_id=kwargs.pop("request_id", REQUEST_ID),
        expected_issue_number=kwargs.pop("issue_number", ISSUE),
        expected_repository=kwargs.pop("repository", REPOSITORY),
        **kwargs,
    )


def _failed_repair_result(**changes):
    value = _result(
        operation="failed-repair",
        retry_reentry_outcome="consumed",
        lesson_disposition="relevant-lesson-applied",
        mutation_admissible=True,
        blocking_attempt_id=None,
        attempt_id="attempt-42",
    )
    value.update(changes)
    return value


# --- valid matching consumption -------------------------------------------


def test_consume_accepts_exact_matching_issue_start_result():
    payload = _consume(_comment(_result()), expected_operation="issue-start")
    assert payload["request_comment_id"] == REQUEST_ID
    assert payload["issue_number"] == ISSUE
    assert payload["selected_lesson_ids"] == ["LL-87"]
    assert payload["substantial_hypothesis_admissible"] is True


def test_consume_accepts_matching_result_without_expected_operation():
    payload = _consume(_comment(_result()))
    assert payload["operation"] == "issue-start"


def test_consume_accepts_matching_failed_repair_result_for_exact_attempt():
    payload = _consume(
        _comment(_failed_repair_result()),
        expected_operation="failed-repair",
        expected_attempt_id="attempt-42",
    )
    assert payload["attempt_id"] == "attempt-42"
    assert payload["retry_reentry_outcome"] == "consumed"


# --- R07: request identity -------------------------------------------------


def test_consume_rejects_mismatched_request_comment_id():
    body = _comment(_result(), request_comment_id=999)
    with pytest.raises(ValueError, match="does not match the pending request"):
        _consume(body)


def test_consume_rejects_missing_request_comment_id():
    payload = _result()
    body = _raw_comment(payload)  # no request_comment_id key at all
    with pytest.raises(ValueError, match="missing request_comment_id"):
        _consume(body)


def test_consume_rejects_non_integer_request_comment_id():
    payload = _result()
    payload["request_comment_id"] = "1000"
    body = _raw_comment(payload)
    with pytest.raises(ValueError, match="missing request_comment_id"):
        _consume(body)


def test_consume_rejects_cross_issue_result():
    body = _comment(_result(issue_number=3418))
    with pytest.raises(ValueError, match="issue_number does not match"):
        _consume(body)


def test_consume_rejects_cross_repository_result():
    body = _comment(_result(repository="Blummer92/other-repo"))
    with pytest.raises(ValueError, match="repository does not match"):
        _consume(body)


def test_consume_rejects_operation_mismatch():
    body = _comment(_failed_repair_result())
    with pytest.raises(ValueError, match="operation does not match"):
        _consume(body, expected_operation="issue-start")


# --- forged authority ------------------------------------------------------


@pytest.mark.parametrize(
    "flag",
    [
        "execution_authorized",
        "github_writes_authorized",
        "merge_authorized",
        "closure_authorized",
        "side_effects_performed",
    ],
)
def test_consume_rejects_forged_authority_flag(flag):
    body = _comment(_result(**{flag: True}))
    with pytest.raises(ValueError, match="forbidden authority"):
        _consume(body)


def test_consume_rejects_missing_authority_flag():
    payload = _result()
    del payload["merge_authorized"]
    body = _comment(payload)
    with pytest.raises(ValueError, match="forbidden authority"):
        _consume(body)


# --- parser passthrough -----------------------------------------------------


def test_consume_rejects_non_canonical_payload():
    body = bridge.CKR6_RESULT_MARKER + "\n" + '{"a": 1}'
    with pytest.raises(ValueError):
        _consume(body)


def test_consume_rejects_non_result_comment():
    with pytest.raises(ValueError):
        _consume("not a CKR6 result comment")


# --- failed-repair attempt binding -----------------------------------------


def test_consume_rejects_wrong_attempt_result():
    body = _comment(_failed_repair_result(attempt_id="attempt-41"))
    with pytest.raises(ValueError, match="does not match the current failed attempt"):
        _consume(body, expected_operation="failed-repair", expected_attempt_id="attempt-42")


def test_consume_rejects_failed_repair_result_without_attempt_id():
    payload = _failed_repair_result()
    del payload["attempt_id"]
    body = _comment(payload)
    with pytest.raises(ValueError, match="missing attempt_id"):
        _consume(body, expected_operation="failed-repair", expected_attempt_id="attempt-42")


def test_consume_requires_expected_attempt_id_for_failed_repair():
    body = _comment(_failed_repair_result())
    with pytest.raises(ValueError, match="requires expected_attempt_id"):
        _consume(body, expected_operation="failed-repair")


def test_execute_envelope_projects_attempt_id_through_serialize_and_parse(monkeypatch):
    canonical = {
        "lesson_retrieval_status": "sufficient",
        "retry_reentry_outcome": "consumed",
        "lesson_disposition": "relevant-lesson-applied",
        "reason_codes": ["canonical-retry-reason"],
        "selected_lesson_ids": [],
        "selected_lessons": [],
        "canonical_github_refs": ["Blummer92/agent-os#2425"],
        "mutation_admissible": True,
        "blocking_attempt_id": None,
    }
    monkeypatch.setattr(
        bridge, "activate_agent_os_failed_repair", lambda **kwargs: canonical
    )
    envelope = bridge.parse_envelope(
        {
            "operation": "failed-repair",
            "repository": REPOSITORY,
            "issue_number": ISSUE,
            "task_reference": "issue:#2425",
            "attempt_id": "attempt-42",
            "failed_hypothesis": "first repair failed",
            "result_summary": "CI still red",
            "repair_context": "failed-pr-repair",
            "specialized_knowledge_required": False,
        }
    )
    result = bridge.execute_envelope(envelope, retrieval_required=False)
    assert result["attempt_id"] == "attempt-42"
    body = bridge.serialize_ckr6_result_comment(result, request_comment_id=REQUEST_ID)
    parsed = bridge.parse_ckr6_result_comment(body)
    assert parsed["attempt_id"] == "attempt-42"
    consumed = _consume(
        body, expected_operation="failed-repair", expected_attempt_id="attempt-42"
    )
    assert consumed["attempt_id"] == "attempt-42"


# --- serializer/parser compatibility ---------------------------------------


def test_old_result_without_attempt_id_still_parses_and_consumes_for_issue_start():
    body = _comment(_result())
    parsed = bridge.parse_ckr6_result_comment(body)
    assert "attempt_id" not in parsed
    consumed = _consume(body)
    assert consumed["status"] == "sufficient"


def test_result_without_attempt_id_still_serializes():
    body = bridge.serialize_ckr6_result_comment(_result(), request_comment_id=1)
    assert bridge.parse_ckr6_result_comment(body)["request_comment_id"] == 1


# --- select: exactly-one semantics ------------------------------------------


def _select(bodies, **kwargs):
    return bridge.select_ckr6_result_comment(
        bodies,
        expected_request_comment_id=kwargs.pop("request_id", REQUEST_ID),
        expected_issue_number=kwargs.pop("issue_number", ISSUE),
        expected_repository=kwargs.pop("repository", REPOSITORY),
        **kwargs,
    )


def test_select_returns_exactly_one_result_among_noise():
    bodies = [
        "ordinary discussion comment",
        "/agent-os ckr6 {\"operation\": \"issue-start\"}",
        _comment(_result(), request_comment_id=777),
        _comment(_result()),
    ]
    payload = _select(bodies)
    assert payload["request_comment_id"] == REQUEST_ID


def test_select_fails_closed_when_result_not_returned():
    bodies = [_comment(_result(), request_comment_id=777), "noise"]
    with pytest.raises(ValueError, match="not returned for the pending request"):
        _select(bodies)


def test_select_rejects_ambiguous_distinct_results_for_same_request():
    bodies = [
        _comment(_result(status="sufficient")),
        _comment(_result(status="insufficient")),
    ]
    with pytest.raises(ValueError, match="ambiguous CKR6 result"):
        _select(bodies)


def test_select_collapses_identical_duplicate_results():
    body = _comment(_result())
    payload = _select([body, body])
    assert payload["request_comment_id"] == REQUEST_ID


def test_select_skips_unparsable_marker_comments():
    bodies = [
        bridge.CKR6_RESULT_MARKER + "\nnot json",
        _comment(_result()),
    ]
    payload = _select(bodies)
    assert payload["request_comment_id"] == REQUEST_ID


def test_select_enforces_authority_binding_on_the_unique_match():
    bodies = [_comment(_result(merge_authorized=True))]
    with pytest.raises(ValueError, match="forbidden authority"):
        _select(bodies)


def test_select_enforces_attempt_binding_on_the_unique_match():
    bodies = [_comment(_failed_repair_result(attempt_id="attempt-41"))]
    with pytest.raises(
        ValueError, match="does not match the current failed attempt"
    ):
        _select(
            bodies,
            expected_operation="failed-repair",
            expected_attempt_id="attempt-42",
        )


def test_select_rejects_non_iterable_bodies():
    with pytest.raises(TypeError):
        _select(_comment(_result()))
