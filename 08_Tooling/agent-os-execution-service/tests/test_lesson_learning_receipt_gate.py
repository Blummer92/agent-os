"""CKR7 receipt-verification barrier (#3418 H1): the QA acceptance matrix.

A syntactically valid receipt URL is never sufficient evidence. Every case is
write-free: the trusted GitHub read is an exact-id stub, the Notion read is a
stub, and all authority flags stay false. The two LL-87 bodies are the exact
live malformed receipts; nothing strips or repairs them.
"""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge
from agent_os_execution_service import lesson_learning_loop as loop
from agent_os_execution_service.ckr6_github_reader import GitHubIssueCommentReadUnavailable

import receipt_fixtures as rf
from test_lesson_learning_loop import reader, refinement, row, _learning_envelope

REVISION = rf.REVISION


def _route(monkeypatch, rows, records=None, fetch=None):
    read = reader(rows)
    monkeypatch.setattr(bridge, "resolve_lesson_read_route",
                        lambda: type("Route", (), {"execute_read": staticmethod(read)})())
    if fetch is None:
        fetch = rf.fetch_from(rf.verified_chain() if records is None else records)
    monkeypatch.setattr(bridge, "_receipt_comment_fetch", lambda: fetch)
    return read, fetch


def _run(detail=None):
    envelope = _learning_envelope("lesson-refinement", "refinement", detail or refinement())
    return bridge.execute_envelope(envelope, retrieval_required=True)


def _no_proposal(result, status, code):
    assert result["status"] == status
    assert result["reason_codes"] == [code]
    assert result["revision_proposal"] is None
    # The barrier stopped before the lesson read and reported that truthfully.
    assert result["notion_read_performed"] is False
    assert result["side_effects_performed"] is False


# 1. Fully verified chain -> CKR7 evaluates.
def test_verified_receipt_allows_ckr7(monkeypatch):
    read, fetch = _route(monkeypatch, [row()])
    result = _run()
    assert result["status"] == "enrich-existing"
    assert result["revision_proposal"]["lesson_id"] == "LL-999"
    assert result["notion_read_performed"] is True
    # Exact ids only: receipt, its CKR6 result, and the result's request.
    assert fetch.calls == [rf.RECEIPT_ID, rf.RESULT_ID, rf.REQUEST_ID]
    assert read.calls, "the lesson read must follow the verified barrier"


# 2/3. Real malformed LL-87 receipts -> bounded reject, never repaired.
@pytest.mark.parametrize("body", [rf.LL87_RECEIPT_6080491160_BODY, rf.LL87_RECEIPT_6080710239_BODY])
def test_real_malformed_ll87_receipts_are_rejected(monkeypatch, body):
    records = rf.verified_chain()
    records[rf.RECEIPT_ID] = rf.receipt_record(body=body)
    _route(monkeypatch, [row()], records)
    result = _run()
    _no_proposal(result, "rejected", "receipt-parse-invalid")


# 4. Valid-looking URL for a missing/deleted comment -> fail closed.
def test_missing_receipt_comment_fails_closed(monkeypatch):
    records = rf.verified_chain()
    del records[rf.RECEIPT_ID]
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-comment-not-found")


# 5a. No trusted read path at all -> manual review, no CKR7.
def test_unbound_read_path_stops_before_any_read(monkeypatch):
    read, _ = _route(monkeypatch, [row()], fetch=None)
    monkeypatch.setattr(bridge, "_receipt_comment_fetch", lambda: None)
    result = _run()
    _no_proposal(result, "manual-review", "receipt-read-unavailable")
    assert read.calls == []


# 5b/18. Caller-supplied receipt material is not an input channel at all.
@pytest.mark.parametrize("smuggled", [
    {"receipt_comment_body": rf.receipt_body()},
    {"receipt_author": "Blummer92"},
    {"ckr6_result": {"status": "sufficient"}},
])
def test_envelope_cannot_smuggle_receipt_material(smuggled):
    detail = refinement(**smuggled)
    with pytest.raises(ValueError):
        loop.parse_refinement(detail)


# 6. Wrong comment id / repository / location / revision / lesson -> zero proposal.
def test_record_id_must_match_the_cited_comment(monkeypatch):
    records = rf.verified_chain()
    record = deepcopy(records[rf.RECEIPT_ID])
    record["id"] = rf.RECEIPT_ID + 50
    records[rf.RECEIPT_ID] = record
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-location-mismatch")


def test_foreign_repository_location_is_rejected(monkeypatch):
    records = rf.verified_chain()
    record = deepcopy(records[rf.RECEIPT_ID])
    record["issue_url"] = "https://api.github.com/repos/Blummer92/other/issues/3418"
    records[rf.RECEIPT_ID] = record
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-location-mismatch")


def test_cross_issue_anchor_is_rejected(monkeypatch):
    records = rf.verified_chain()
    record = deepcopy(records[rf.RECEIPT_ID])
    record["html_url"] = record["html_url"].replace("/issues/3418#", "/issues/9999#")
    records[rf.RECEIPT_ID] = record
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-location-mismatch")


def test_receipt_for_other_revision_is_rejected(monkeypatch):
    records = rf.verified_chain()
    records[rf.RECEIPT_ID] = rf.receipt_record(revision="2026-01-01T00:00:00.000Z")
    # The result DID select that other revision; the refinement asked for this one.
    records[rf.RESULT_ID] = rf.result_record(lessons=((rf.LESSON, "2026-01-01T00:00:00.000Z"),))
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-lesson-mismatch")


def test_receipt_for_other_lesson_is_rejected(monkeypatch):
    records = rf.verified_chain()
    records[rf.RECEIPT_ID] = rf.receipt_record(lesson="LL-5")
    records[rf.RESULT_ID] = rf.result_record(lessons=(("LL-5", REVISION),))
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-lesson-mismatch")


# 6 (cont). Receipt author and edit provenance.
def test_receipt_not_owner_authored_is_rejected(monkeypatch):
    records = rf.verified_chain()
    records[rf.RECEIPT_ID] = rf.receipt_record(login="github-actions[bot]")
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-author-untrusted")


def test_receipt_edited_after_creation_is_rejected(monkeypatch):
    records = rf.verified_chain()
    records[rf.RECEIPT_ID] = rf.receipt_record(updated="2026-11-13T14:00:00Z")
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-comment-edited")


# 7. Receipt fine but result missing or malformed -> zero proposal.
def test_missing_result_comment_fails_closed(monkeypatch):
    records = rf.verified_chain()
    del records[rf.RESULT_ID]
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-comment-not-found")


def test_malformed_result_body_is_untrusted(monkeypatch):
    records = rf.verified_chain()
    record = deepcopy(records[rf.RESULT_ID])
    record["body"] = "looks like a result but is not"
    records[rf.RESULT_ID] = record
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-result-untrusted")


# 8. Spoofed/edited/mis-ordered result records -> zero proposal.
def test_result_spoofed_by_arbitrary_actor(monkeypatch):
    records = rf.verified_chain()
    record = deepcopy(records[rf.RESULT_ID])
    record["user"] = {"login": "Blummer92", "id": 32861845}
    del record["performed_via_github_app"]
    records[rf.RESULT_ID] = record
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-result-untrusted")


def test_result_with_wrong_request_id_is_untrusted(monkeypatch):
    records = rf.verified_chain()
    wrong_request = rf.REQUEST_ID + 7
    records[wrong_request] = rf.request_record(wrong_request)
    records[rf.RESULT_ID] = rf.result_record(request_id=wrong_request)
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-result-untrusted")


def test_result_on_wrong_issue_is_untrusted(monkeypatch):
    records = rf.verified_chain()
    record = deepcopy(records[rf.RESULT_ID])
    record["issue_url"] = record["issue_url"].replace("/3418", "/9999")
    record["html_url"] = record["html_url"].replace("/3418#", "/9999#")
    records[rf.RESULT_ID] = record
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-result-untrusted")


def test_result_predating_request_is_untrusted(monkeypatch):
    records = rf.verified_chain()
    record = deepcopy(records[rf.RESULT_ID])
    record["created_at"] = record["updated_at"] = "2026-11-13T11:00:00Z"
    records[rf.RESULT_ID] = record
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-result-untrusted")


def test_result_edited_after_creation_is_untrusted(monkeypatch):
    records = rf.verified_chain()
    records[rf.RESULT_ID] = rf.result_record(updated="2026-11-13T13:00:00Z")
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-result-untrusted")


# 8 (cont). Defense-in-depth bindings on the request record and result shape.
def test_result_record_id_must_match_the_cited_result(monkeypatch):
    records = rf.verified_chain()
    record = deepcopy(records[rf.RESULT_ID])
    # Tamper id AND html location consistently, so only the explicit
    # server-id equality check can catch the substitution.
    record["id"] = rf.RESULT_ID + 50
    record["html_url"] = record["html_url"].replace(
        f"issuecomment-{rf.RESULT_ID}", f"issuecomment-{rf.RESULT_ID + 50}")
    records[rf.RESULT_ID] = record
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-result-untrusted")


def test_request_record_id_must_match_the_named_request(monkeypatch):
    records = rf.verified_chain()
    record = deepcopy(records[rf.REQUEST_ID])
    record["id"] = rf.REQUEST_ID + 50
    records[rf.REQUEST_ID] = record
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-result-untrusted")


def test_request_on_another_issue_is_untrusted(monkeypatch):
    records = rf.verified_chain()
    records[rf.REQUEST_ID] = rf.request_record(number=9999)
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-result-untrusted")


def test_result_operation_outside_lesson_selection_is_untrusted(monkeypatch):
    records = rf.verified_chain()
    records[rf.RESULT_ID] = rf.result_record(operation="lesson-candidate")
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-result-untrusted")


# 9. Non-sufficient or revision-less results -> zero proposal.
@pytest.mark.parametrize(("status", "code"), [
    ("insufficient", "receipt-result-not-sufficient"),
    ("not-needed", "receipt-result-not-sufficient"),
    ("manual-review", "receipt-result-not-sufficient"),
])
def test_non_sufficient_result_cannot_support_receipt(monkeypatch, status, code):
    records = rf.verified_chain()
    records[rf.RESULT_ID] = rf.result_record(status=status)
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", code)


def test_result_without_revision_provenance_is_rejected(monkeypatch):
    records = rf.verified_chain()
    record = deepcopy(records[rf.RESULT_ID])
    record["body"] = rf.result_body(selected_lessons=None)
    records[rf.RESULT_ID] = record
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-result-lacks-revision-provenance")


# 10. Noncanonical receipt bodies -> zero proposal.
def _receipt_with_raw_body(monkeypatch, body):
    records = rf.verified_chain()
    records[rf.RECEIPT_ID] = rf.receipt_record(body=body)
    _route(monkeypatch, [row()], records)
    return _run()


def test_noncanonical_json_receipt_is_rejected(monkeypatch):
    body = loop.RECEIPT_MARKER + "\n" + json.dumps(rf.receipt_payload(), indent=2)
    _no_proposal(_receipt_with_raw_body(monkeypatch, body), "rejected", "receipt-parse-invalid")


def test_markdown_wrapped_receipt_is_rejected(monkeypatch):
    _no_proposal(
        _receipt_with_raw_body(monkeypatch, "```\n" + rf.receipt_body() + "\n```"),
        "rejected", "receipt-parse-invalid")


def test_arbitrary_footer_receipt_is_rejected(monkeypatch):
    _no_proposal(
        _receipt_with_raw_body(monkeypatch, rf.receipt_body() + "\n\n---\n_Generated by something else_"),
        "rejected", "receipt-parse-invalid")


def test_duplicate_key_receipt_is_rejected(monkeypatch):
    line = '{"ckr6_result_comment_id":6100000001,"ckr6_result_comment_id":6100000001,"decision":"x",' \
           '"disposition":"applied","lesson_id":"LL-999","outcome_ref":null,"reason_code":"guided-decision",' \
           '"source_revision":"2026-10-08T12:00:00.000Z","task_ref":"https://github.com/Blummer92/agent-os/issues/3418"}'
    _no_proposal(_receipt_with_raw_body(monkeypatch, loop.RECEIPT_MARKER + "\n" + line),
                 "rejected", "receipt-parse-invalid")


def test_oversized_decision_receipt_is_rejected(monkeypatch):
    payload = rf.receipt_payload()
    payload["decision"] = "x" * 300
    line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    _no_proposal(_receipt_with_raw_body(monkeypatch, loop.RECEIPT_MARKER + "\n" + line),
                 "rejected", "receipt-parse-invalid")


def test_unknown_field_receipt_is_rejected(monkeypatch):
    body = rf.receipt_body()
    payload = rf.receipt_payload()
    payload["trusted"] = True
    import json as _json
    line = _json.dumps(payload, sort_keys=True, separators=(",", ":"))
    _no_proposal(_receipt_with_raw_body(monkeypatch, loop.RECEIPT_MARKER + "\n" + line),
                 "rejected", "receipt-parse-invalid")


# 11. Disposition contract: skipped non-signal reasons are not refinement evidence;
# skipped with a refinement-signal reason is.
def test_skipped_not_relevant_receipt_is_not_refinement_evidence(monkeypatch):
    records = rf.verified_chain()
    records[rf.RECEIPT_ID] = rf.receipt_record(disposition="skipped", reason_code="not-relevant-to-task")
    _route(monkeypatch, [row()], records)
    _no_proposal(_run(), "rejected", "receipt-disposition-not-refinement-evidence")


def test_skipped_guidance_outdated_receipt_is_refinement_signal(monkeypatch):
    records = rf.verified_chain()
    records[rf.RECEIPT_ID] = rf.receipt_record(disposition="skipped", reason_code="guidance-outdated")
    _route(monkeypatch, [row()], records)
    result = _run()
    assert result["status"] == "enrich-existing"
    assert result["revision_proposal"] is not None


# 12. Verified receipts + stale current Notion revision -> stale stop, zero draft.
def test_stale_current_revision_still_stops_after_verified_receipts(monkeypatch):
    _route(monkeypatch, [row(revision="2026-10-09T00:00:00.000Z")])
    result = _run()
    assert (result["status"], result["reason_codes"]) == ("rejected", ["stale-lesson-revision"])
    assert result["revision_proposal"] is None
    assert result["notion_read_performed"] is True  # the barrier passed; the read happened


# 13. One valid + one invalid receipt -> NO proposal (no laundering).
def test_invalid_second_receipt_is_not_excused_by_valid_first(monkeypatch):
    records = rf.verified_chain()
    bad_id = rf.RECEIPT_ID + 1
    records[bad_id] = rf.receipt_record(bad_id, body=rf.LL87_RECEIPT_6080491160_BODY)
    _route(monkeypatch, [row()], records)
    detail = refinement(receipt_refs=[rf.receipt_html_ref(), rf.receipt_html_ref(comment_id=bad_id)])
    _no_proposal(_run(detail), "rejected", "receipt-parse-invalid")


# 14a. Duplicate identical references collapse to one verified proof.
def test_duplicate_receipt_references_dedupe(monkeypatch):
    _, fetch = _route(monkeypatch, [row()])
    detail = refinement(receipt_refs=[rf.receipt_html_ref(), rf.receipt_html_ref(), rf.receipt_api_ref()])
    result = _run(detail)
    assert result["status"] == "enrich-existing"
    assert fetch.calls == [rf.RECEIPT_ID, rf.RESULT_ID, rf.REQUEST_ID]


# 14b. Two distinct comments with the same receipt_key are conflicting proof.
def test_conflicting_receipt_key_fails_closed(monkeypatch):
    records = rf.verified_chain()
    dupe_id = rf.RECEIPT_ID + 1
    records[dupe_id] = rf.receipt_record(dupe_id, decision="A different decision for the same use.")
    _route(monkeypatch, [row()], records)
    detail = refinement(receipt_refs=[rf.receipt_html_ref(), rf.receipt_html_ref(comment_id=dupe_id)])
    _no_proposal(_run(detail), "rejected", "receipt-key-conflict")


# 15. Reader/token failures -> manual review, and no credential reaches the output.
def test_read_failures_route_to_manual_review_without_secrets(monkeypatch):
    token = "ghp_secret-token-that-must-never-appear"
    failures = [
        GitHubIssueCommentReadUnavailable("HOST_READ_PATH_UNAVAILABLE", "no GitHub App installation token is available"),
        GitHubIssueCommentReadUnavailable("github-api-failure", "GitHub API returned HTTP 403"),
        GitHubIssueCommentReadUnavailable("github-api-failure", "GitHub API returned HTTP 500"),
        GitHubIssueCommentReadUnavailable("github-api-failure", "GitHub API read failed: TimeoutError"),
        GitHubIssueCommentReadUnavailable("github-api-unexpected-response", "GitHub API response is not valid JSON"),
        GitHubIssueCommentReadUnavailable("github-api-unexpected-response", "GitHub API response exceeds the bounded size"),
    ]
    for failure in failures:
        def fetch(comment_id, _f=failure):
            raise _f
        monkeypatch.setattr(bridge, "resolve_lesson_read_route",
                            lambda: type("Route", (), {"execute_read": staticmethod(reader([row()]))})())
        monkeypatch.setattr(bridge, "_receipt_comment_fetch", lambda _f=fetch: _f)
        monkeypatch.setenv("GITHUB_TOKEN", token)
        result = _run()
        expected = "receipt-read-unavailable" if failure.reason_code == "HOST_READ_PATH_UNAVAILABLE" else "receipt-read-failed"
        _no_proposal(result, "manual-review", expected)
        assert token not in json.dumps(result)


# 18 (bridge level). A smuggled detail field yields the bounded envelope rejection.
def test_bridge_rejects_smuggled_receipt_fields(monkeypatch):
    _route(monkeypatch, [row()])
    detail = refinement(receipt_comment_body=rf.receipt_body())
    result = _run(detail)
    assert result["status"] == "rejected"
    assert result["reason_codes"] == ["envelope-rejected:envelope-field-unsupported"]
    assert result["revision_proposal"] is None


# 19. Owner-authored receipt + Actions-bot result is the positive shape.
def test_owner_receipt_with_bot_result_is_valid(monkeypatch):
    _route(monkeypatch, [row()])
    result = _run()
    assert result["status"] == "enrich-existing"
    records = rf.verified_chain()
    assert records[rf.RECEIPT_ID]["user"]["login"] == "Blummer92"
    assert records[rf.RESULT_ID]["user"]["login"] == "github-actions[bot]"


# 20. Both documented canonical receipt URL forms verify, issue and PR anchors.
@pytest.mark.parametrize("ref", [
    rf.receipt_html_ref(),
    rf.receipt_html_ref(kind="pull"),
    rf.receipt_api_ref(),
])
def test_all_canonical_reference_forms_verify(monkeypatch, ref):
    kind = "pull" if "/pull/" in ref else "issues"
    _route(monkeypatch, [row()], rf.verified_chain(kind=kind))
    result = _run(refinement(receipt_refs=[ref]))
    assert result["status"] == "enrich-existing"


def test_pr_anchor_form_rejects_issue_location(monkeypatch):
    # A /pull/ anchor whose record lives on /issues/ is cross-target evidence.
    records = rf.verified_chain()
    _route(monkeypatch, [row()], records)
    detail = refinement(receipt_refs=[rf.receipt_html_ref(kind="pull")])
    _no_proposal(_run(detail), "rejected", "receipt-location-mismatch")


# Authority and privacy invariants across the whole barrier.
def test_authority_flags_stay_false_and_proposal_carries_no_record_material(monkeypatch):
    _route(monkeypatch, [row()])
    result = _run()
    for flag in ("execution_authorized", "github_writes_authorized", "merge_authorized",
                 "closure_authorized", "side_effects_performed"):
        assert result[flag] is False
    proposal = result["revision_proposal"]
    assert proposal["authority_created"] is False
    assert proposal["notion_write_performed"] is False
    assert proposal["publication_authorized"] is False
    assert "body" not in json.dumps(proposal)
