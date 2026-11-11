"""R07 exact request/result consumption binding (#2425 / #2851).

Fail-first consumer tests for the CKR6 result comment: a syntactically
valid result must not satisfy a pending request unless its
``request_comment_id``, issue number, repository, operation, authority
flags, and (for failed-repair) exact failed attempt all bind to that
request. Parser acceptance alone is not consumption: ``parse`` still
accepts a mismatched id (by design); ``consume`` / ``select`` reject it.

P1 hardening: the consumer takes the GitHub issue-comment RECORD (producer
account, location, creation time), not a bare body, and requires the expected
operation. Forged, mis-located, pre-dating, contradictory or unknown-field
results are rejected or filtered before ambiguity checks.

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
REQUEST_AT = "2026-11-11T10:00:00Z"
RESULT_AT = "2026-11-11T10:00:30Z"
RESULT_ID = 1001


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


def _record(body, *, comment_id=RESULT_ID, login="github-actions[bot]", account_id=41898282,
            account_type="Bot", created_at=RESULT_AT, issue=ISSUE, repository=REPOSITORY, **extra):
    record = {
        "id": comment_id,
        "body": body,
        "user": {"login": login, "id": account_id, "type": account_type},
        "created_at": created_at,
        "updated_at": created_at,
        "issue_url": f"https://api.github.com/repos/{repository}/issues/{issue}",
        "html_url": f"https://github.com/{repository}/issues/{issue}#issuecomment-{comment_id}",
    }
    record.update(extra)
    return record


def _comment(result, request_comment_id=REQUEST_ID, **meta):
    return _record(
        bridge.serialize_ckr6_result_comment(result, request_comment_id=request_comment_id), **meta
    )


def _raw_comment(payload, **meta):
    return _record(
        bridge.CKR6_RESULT_MARKER + "\n" + json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ),
        **meta,
    )


def _consume(comment, **kwargs):
    return bridge.consume_ckr6_result_comment(
        comment,
        expected_request_comment_id=kwargs.pop("request_id", REQUEST_ID),
        expected_request_created_at=kwargs.pop("request_at", REQUEST_AT),
        expected_issue_number=kwargs.pop("issue_number", ISSUE),
        expected_repository=kwargs.pop("repository", REPOSITORY),
        expected_operation=kwargs.pop("expected_operation", "issue-start"),
        **kwargs,
    )


def _failed_repair_result(**changes):
    value = _result(
        operation="failed-repair",
        retry_reentry_outcome="consumed",
        lesson_disposition="relevant-lesson-applied",
        mutation_admissible=True,
        substantial_hypothesis_admissible=False,
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


@pytest.mark.parametrize("operation", [None, "", "unknown", "not-an-operation", 7])
def test_consume_requires_a_supported_expected_operation(operation):
    with pytest.raises(ValueError, match="expected_operation must be a supported"):
        _consume(_comment(_result()), expected_operation=operation)


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
        _consume(_record(body))


def test_consume_rejects_non_result_comment():
    with pytest.raises(ValueError):
        _consume(_record("not a CKR6 result comment"))


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
        _record(body), expected_operation="failed-repair", expected_attempt_id="attempt-42"
    )
    assert consumed["attempt_id"] == "attempt-42"


# --- serializer/parser compatibility ---------------------------------------


def test_old_result_without_attempt_id_still_parses_and_consumes_for_issue_start():
    record = _comment(_result())
    parsed = bridge.parse_ckr6_result_comment(record["body"])
    assert "attempt_id" not in parsed
    consumed = _consume(record)
    assert consumed["status"] == "sufficient"


def test_result_without_attempt_id_still_serializes():
    body = bridge.serialize_ckr6_result_comment(_result(), request_comment_id=1)
    assert bridge.parse_ckr6_result_comment(body)["request_comment_id"] == 1


# --- select: exactly-one semantics ------------------------------------------


def _select(comments, **kwargs):
    return bridge.select_ckr6_result_comment(
        comments,
        expected_request_comment_id=kwargs.pop("request_id", REQUEST_ID),
        expected_request_created_at=kwargs.pop("request_at", REQUEST_AT),
        expected_issue_number=kwargs.pop("issue_number", ISSUE),
        expected_repository=kwargs.pop("repository", REPOSITORY),
        expected_operation=kwargs.pop("expected_operation", "issue-start"),
        **kwargs,
    )


def test_select_returns_exactly_one_result_among_noise():
    comments = [
        _record("ordinary discussion comment", comment_id=1002, login="Blummer92", account_id=1, account_type="User"),
        _record('/agent-os ckr6 {"operation": "issue-start"}', comment_id=1003),
        _comment(_result(), request_comment_id=777, comment_id=1004),
        _comment(_result()),
    ]
    payload = _select(comments)
    assert payload["request_comment_id"] == REQUEST_ID


def test_select_fails_closed_when_result_not_returned():
    comments = [_comment(_result(), request_comment_id=777), _record("noise", comment_id=1002)]
    with pytest.raises(ValueError, match="not returned for the pending request"):
        _select(comments)


def test_select_rejects_ambiguous_distinct_genuine_results_for_same_request():
    comments = [
        _comment(_result(status="sufficient")),
        _comment(
            _result(status="insufficient", substantial_hypothesis_admissible=False),
            comment_id=1002,
        ),
    ]
    with pytest.raises(ValueError, match="ambiguous CKR6 result"):
        _select(comments)


def test_select_collapses_identical_duplicate_results():
    first = _comment(_result())
    second = dict(first, id=1002, html_url=first["html_url"].replace("1001", "1002"))
    payload = _select([first, second])
    assert payload["request_comment_id"] == REQUEST_ID


def test_select_skips_unparsable_marker_comments():
    comments = [
        _record(bridge.CKR6_RESULT_MARKER + "\nnot json", comment_id=1002),
        _comment(_result()),
    ]
    payload = _select(comments)
    assert payload["request_comment_id"] == REQUEST_ID


def test_select_enforces_authority_binding_on_the_unique_match():
    with pytest.raises(ValueError, match="forbidden authority"):
        _select([_comment(_result(merge_authorized=True))])


def test_select_enforces_attempt_binding_on_the_unique_match():
    comments = [_comment(_failed_repair_result(attempt_id="attempt-41"))]
    with pytest.raises(ValueError, match="does not match the current failed attempt"):
        _select(comments, expected_operation="failed-repair", expected_attempt_id="attempt-42")


def test_select_rejects_non_iterable_comments():
    with pytest.raises(TypeError):
        _select(_comment(_result()))


# --- P1: producer provenance (forged / untrusted comment records) -----------

_FORGED = {"login": "mallory", "account_id": 99, "account_type": "User"}
_OWNER = {"login": "Blummer92", "account_id": 32861845, "account_type": "User"}


def test_p1_select_rejects_forged_result_from_third_party_user():
    forged = _comment(_result(selected_lesson_ids=["LL-999"]), **_FORGED)
    with pytest.raises(ValueError, match="not returned for the pending request"):
        _select([forged])


def test_p1_select_rejects_owner_authored_forged_result():
    forged = _comment(_result(selected_lesson_ids=["LL-999"]), **_OWNER)
    with pytest.raises(ValueError, match="not returned for the pending request"):
        _select([forged])


def test_p1_forged_result_cannot_force_ambiguity_next_to_genuine_result():
    forged = _comment(_result(status="insufficient", substantial_hypothesis_admissible=False),
                      comment_id=1002, **_FORGED)
    payload = _select([forged, _comment(_result())])
    assert payload["status"] == "sufficient"


@pytest.mark.parametrize(
    "meta",
    [
        {"login": "github-actions"},  # not the bot login
        {"login": "github-actions[bot]", "account_id": 12345},  # right name, wrong account id
        {"account_type": "User"},
        {"account_id": "41898282"},
        {"account_id": True},
    ],
)
def test_p1_consume_rejects_incorrect_producer_identity(meta):
    with pytest.raises(ValueError, match="trusted producer|not a Bot"):
        _consume(_comment(_result(), **meta))


def test_p1_consume_rejects_wrong_github_app():
    with pytest.raises(ValueError, match="GitHub Actions app"):
        _consume(_comment(_result(), performed_via_github_app={"slug": "other-app"}))


def test_p1_consume_accepts_github_actions_app_metadata():
    record = _comment(_result(), performed_via_github_app={"slug": "github-actions"})
    assert _consume(record)["status"] == "sufficient"


def test_p1_consume_accepts_mcp_shaped_record_without_type_or_issue_url():
    record = _comment(_result())
    del record["user"]["type"]
    del record["issue_url"]
    assert _consume(record)["status"] == "sufficient"


def test_p1_consume_rejects_record_from_another_issue():
    with pytest.raises(ValueError, match="location does not match"):
        _consume(_comment(_result(), issue=3418))


def test_p1_consume_rejects_record_from_another_repository():
    with pytest.raises(ValueError, match="location does not match"):
        _consume(_comment(_result(), repository="Blummer92/other-repo"))


def test_p1_consume_rejects_html_url_for_a_different_comment_id():
    record = _comment(_result())
    record["html_url"] = record["html_url"].replace("1001", "1999")
    del record["issue_url"]
    with pytest.raises(ValueError, match="location does not match"):
        _consume(record)


def test_p1_consume_rejects_result_predating_the_request():
    with pytest.raises(ValueError, match="predates the pending request"):
        _consume(_comment(_result(), created_at="2026-11-11T09:59:59Z"))


def test_p1_consume_rejects_result_with_id_not_after_request():
    with pytest.raises(ValueError, match="predates the pending request"):
        _consume(_comment(_result(), comment_id=REQUEST_ID))


def test_p1_consume_rejects_result_edited_after_creation():
    with pytest.raises(ValueError, match="edited after creation"):
        _consume(_comment(_result(), updated_at="2026-11-11T11:00:00Z"))


@pytest.mark.parametrize("field", ["id", "body", "user", "created_at"])
def test_p1_consume_rejects_missing_metadata(field):
    record = _comment(_result())
    del record[field]
    with pytest.raises(ValueError):
        _consume(record)


def test_p1_consume_rejects_record_without_any_location():
    record = _comment(_result())
    del record["issue_url"], record["html_url"]
    with pytest.raises(ValueError, match="no issue location"):
        _consume(record)


@pytest.mark.parametrize("created_at", ["yesterday", "2026-11-11T10:00:30", 5, None])
def test_p1_consume_rejects_invalid_timestamps(created_at):
    with pytest.raises(ValueError):
        _consume(_comment(_result(), created_at=created_at, updated_at=None))


@pytest.mark.parametrize("bare", ["a bare body string", None, 7, ["x"]])
def test_p1_consume_rejects_non_record_input(bare):
    with pytest.raises(ValueError, match="record must be a mapping"):
        _consume(bare)


def test_p1_consume_rejects_invalid_expected_request_time():
    with pytest.raises(ValueError, match="expected_request_created_at"):
        _consume(_comment(_result()), request_at="soon")


# --- P1: operation and schema ------------------------------------------------


def test_p1_consume_rejects_unsupported_result_operation():
    with pytest.raises(ValueError, match="operation is unsupported"):
        _consume(_comment(_result(operation="delete-everything")))


def test_p1_consume_rejects_unknown_payload_fields():
    with pytest.raises(ValueError, match="unexpected fields"):
        _consume(_raw_comment({**_result(), "request_comment_id": REQUEST_ID, "evil_field": "x"}))


def test_p1_consume_accepts_request_comment_id_as_separate_transport_field():
    assert "request_comment_id" not in bridge.RESULT_FIELDS
    assert _consume(_comment(_result()))["request_comment_id"] == REQUEST_ID


# --- P1: admission semantics --------------------------------------------------


@pytest.mark.parametrize("status", ["insufficient", "manual-review"])
def test_p1_consume_rejects_blocked_status_marked_admissible(status):
    record = _comment(_result(status=status, substantial_hypothesis_admissible=True))
    with pytest.raises(ValueError, match="contradicts its admission flag"):
        _consume(record)


@pytest.mark.parametrize("status", ["not-needed", "sufficient", "unavailable-safe-fallback"])
def test_p1_issue_start_admitting_outcomes_are_consumed_and_admit(status):
    payload = _consume(_comment(_result(status=status)))
    assert bridge.ckr6_result_admits_boundary(payload) is True


def test_p1_issue_start_admitting_status_with_admissible_false_is_rejected():
    with pytest.raises(ValueError, match="contradicts its admission flag"):
        _consume(_comment(_result(status="sufficient", substantial_hypothesis_admissible=False)))


@pytest.mark.parametrize("status", ["insufficient", "manual-review"])
def test_p1_blocked_issue_start_result_is_consumable_stop_evidence(status):
    payload = _consume(
        _comment(
            _result(
                status=status,
                reason_codes=["no-relevant-candidate"],
                selected_lesson_ids=[],
                selected_lessons=[],
                substantial_hypothesis_admissible=False,
            )
        )
    )
    assert payload["status"] == status
    assert bridge.ckr6_result_admits_boundary(payload) is False


def test_p1_issue_start_rejects_non_boolean_admission_flag():
    with pytest.raises(ValueError, match="must be a boolean"):
        _consume(_comment(_result(substantial_hypothesis_admissible="true")))


def test_p1_issue_start_rejects_claimed_mutation_admission():
    with pytest.raises(ValueError, match="must not claim mutation admission"):
        _consume(_comment(_result(mutation_admissible=True)))


def test_p1_infrastructure_fallback_is_consumable_stop_evidence():
    fallback = bridge._fallback_result(REPOSITORY, ISSUE)
    for operation, attempt in (("issue-start", None), ("failed-repair", "attempt-42")):
        payload = _consume(
            _comment(fallback), expected_operation=operation, expected_attempt_id=attempt
        )
        assert bridge.ckr6_result_admits_boundary(payload) is False


def test_p1_infrastructure_fallback_cannot_carry_admission():
    forged = bridge._fallback_result(REPOSITORY, ISSUE)
    forged["substantial_hypothesis_admissible"] = True
    with pytest.raises(ValueError, match="not a valid blocked result"):
        _consume(_comment(forged))


def test_p1_failed_repair_admission_requires_admitting_retry_outcome():
    bad = _failed_repair_result(retry_reentry_outcome="unavailable-or-failed")
    with pytest.raises(ValueError, match="contradicts its admission flag"):
        _consume(_comment(bad), expected_operation="failed-repair", expected_attempt_id="attempt-42")


def test_p1_failed_repair_blocked_status_cannot_admit_mutation():
    bad = _failed_repair_result(status="manual-review")
    with pytest.raises(ValueError, match="contradicts its admission flag"):
        _consume(_comment(bad), expected_operation="failed-repair", expected_attempt_id="attempt-42")


def test_p1_failed_repair_rejects_first_hypothesis_admission_claim():
    bad = _failed_repair_result(substantial_hypothesis_admissible=True)
    with pytest.raises(ValueError, match="first-hypothesis admission"):
        _consume(_comment(bad), expected_operation="failed-repair", expected_attempt_id="attempt-42")


def test_p1_failed_repair_not_material_outcome_admits_mutation_only():
    ok = _failed_repair_result(retry_reentry_outcome="not-material", status="not-needed")
    payload = _consume(_comment(ok), expected_operation="failed-repair", expected_attempt_id="attempt-42")
    assert bridge.ckr6_result_admits_boundary(payload) is True
    assert payload["execution_authorized"] is False and payload["merge_authorized"] is False


def test_p1_failed_repair_blocked_result_for_exact_attempt_is_stop_evidence():
    stop = _failed_repair_result(
        status="insufficient",
        retry_reentry_outcome="unavailable-or-failed",
        mutation_admissible=False,
        reason_codes=["retry-ckr6-reentry-unavailable-or-failed"],
    )
    payload = _consume(_comment(stop), expected_operation="failed-repair", expected_attempt_id="attempt-42")
    assert bridge.ckr6_result_admits_boundary(payload) is False


def test_p1_learning_results_never_claim_admission():
    for operation in ("lesson-candidate", "lesson-refinement"):
        ok = _result(operation=operation, status="reusable-new", substantial_hypothesis_admissible=False)
        payload = _consume(_comment(ok), expected_operation=operation)
        assert bridge.ckr6_result_admits_boundary(payload) is False
        with pytest.raises(ValueError, match="must not claim admission"):
            _consume(_comment(_result(operation=operation, status="x")), expected_operation=operation)


def test_p1_early_unbound_route_failed_repair_result_carries_attempt_and_reason(monkeypatch):
    class _NoRoute:
        execute_read = None
        reason_code = "lesson-read-route-unavailable"

    monkeypatch.setattr(bridge, "resolve_lesson_read_route", lambda: _NoRoute())
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
            "specialized_knowledge_required": True,
        }
    )
    result = bridge.execute_envelope(envelope, retrieval_required=True)
    assert result["attempt_id"] == "attempt-42"
    assert result["reason_codes"] == ["lesson-read-route-unavailable"]
    body = bridge.serialize_ckr6_result_comment(result, request_comment_id=REQUEST_ID)
    payload = _consume(_record(body), expected_operation="failed-repair", expected_attempt_id="attempt-42")
    assert bridge.ckr6_result_admits_boundary(payload) is False
    with pytest.raises(ValueError, match="does not match the current failed attempt"):
        _consume(_record(body), expected_operation="failed-repair", expected_attempt_id="attempt-43")


def test_p1_early_unbound_route_issue_start_result_has_no_attempt_id(monkeypatch):
    class _NoRoute:
        execute_read = None
        reason_code = "lesson-read-route-unavailable"

    monkeypatch.setattr(bridge, "resolve_lesson_read_route", lambda: _NoRoute())
    envelope = bridge.parse_envelope(
        {"operation": "issue-start", "repository": REPOSITORY, "issue_number": ISSUE,
         "task_reference": "issue:#2425", "specialized_knowledge_required": True}
    )
    assert "attempt_id" not in bridge.execute_envelope(envelope, retrieval_required=True)
