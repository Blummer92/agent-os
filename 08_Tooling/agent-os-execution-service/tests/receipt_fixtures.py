"""Verified-comment fixtures for the CKR7 receipt barrier (#3418 H1).

Every record is GitHub-record-shaped (server-assigned id, author, location,
timestamps) and every body is produced by the production serializers, so a
test exercises the real trust chain instead of a re-implemented one. The two
malformed LL-87 bodies are the exact live #3418 comment bodies (read-only
public API capture, 2026-11-13); they are evidence, not repaired text.
"""
from __future__ import annotations

from agent_os_execution_service import ckr6_github_bridge as bridge
from agent_os_execution_service import lesson_learning_loop as loop

REPO = "Blummer92/agent-os"
ISSUE = 3418
REVISION = "2026-10-08T12:00:00.000Z"
LESSON = "LL-999"
TASK = f"https://github.com/{REPO}/issues/{ISSUE}"

REQUEST_ID = 6100000000
RESULT_ID = 6100000001
RECEIPT_ID = 6100000002

REQUEST_CREATED = "2026-11-13T12:00:00Z"
RESULT_CREATED = "2026-11-13T12:01:00Z"
RECEIPT_CREATED = "2026-11-13T12:02:00Z"


def receipt_html_ref(number=ISSUE, comment_id=RECEIPT_ID, kind="issues"):
    return f"https://github.com/{REPO}/{kind}/{number}#issuecomment-{comment_id}"


def receipt_api_ref(comment_id=RECEIPT_ID):
    return f"https://api.github.com/repos/{REPO}/issues/comments/{comment_id}"


def receipt_payload(result_id=RESULT_ID, lesson=LESSON, revision=REVISION, **changes):
    value = {
        "ckr6_result_comment_id": result_id,
        "lesson_id": lesson,
        "source_revision": revision,
        "task_ref": TASK,
        "disposition": "applied",
        "reason_code": "guided-decision",
        "decision": "Routed the repair through the verified lesson before acting.",
        "outcome_ref": f"https://github.com/{REPO}/pull/3962",
    }
    value.update(changes)
    return value


def result_payload(lessons=((LESSON, REVISION),), operation="issue-start",
                   status="sufficient", issue_number=ISSUE, **changes):
    admissible = status in ("not-needed", "sufficient", "unavailable-safe-fallback")
    value = {
        "operation": operation,
        "repository": REPO,
        "issue_number": issue_number,
        "status": status,
        "reason_codes": ["knowledge-sufficient"],
        "selected_lesson_ids": [lesson for lesson, _ in lessons],
        "selected_lessons": [
            {"lesson_id": lesson, "source_revision": rev, "selection_reason_codes": ["x"]}
            for lesson, rev in lessons
        ],
        "canonical_github_refs": [],
        "substantial_hypothesis_admissible": admissible if operation == "issue-start" else False,
        "mutation_admissible": False,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
    }
    if operation == "failed-repair":
        value["attempt_id"] = "attempt-1"
    value.update(changes)
    return value


def receipt_body(**changes):
    return loop.serialize_receipt_comment(receipt_payload(**changes))


def result_body(request_id=REQUEST_ID, **changes):
    return bridge.serialize_ckr6_result_comment(
        result_payload(**changes), request_comment_id=request_id
    )


def _record(comment_id, body, *, login, created, number=ISSUE, kind="issues",
            account_id=None, account_type=None, app_slug=None, updated=None):
    record = {
        "id": comment_id,
        "body": body,
        "user": {"login": login},
        "issue_url": f"https://api.github.com/repos/{REPO}/issues/{number}",
        "html_url": f"https://github.com/{REPO}/{kind}/{number}#issuecomment-{comment_id}",
        "created_at": created,
        "updated_at": created if updated is None else updated,
    }
    if account_id is not None:
        record["user"]["id"] = account_id
    if account_type is not None:
        record["user"]["type"] = account_type
    if app_slug is not None:
        record["performed_via_github_app"] = {"slug": app_slug}
    return record


def request_record(comment_id=REQUEST_ID, *, number=ISSUE, kind="issues", created=REQUEST_CREATED):
    return _record(comment_id, "/agent-os ckr6 {...}", login="Blummer92",
                   created=created, number=number, kind=kind)


def result_record(comment_id=RESULT_ID, *, request_id=REQUEST_ID, number=ISSUE,
                  kind="issues", created=RESULT_CREATED, updated=None, **changes):
    return _record(
        comment_id, result_body(request_id=request_id, issue_number=number, **changes),
        login=bridge.CKR6_PRODUCER_LOGIN, created=created, number=number, kind=kind,
        account_id=bridge.CKR6_PRODUCER_ACCOUNT_ID,
        account_type=bridge.CKR6_PRODUCER_ACCOUNT_TYPE,
        app_slug=bridge.CKR6_PRODUCER_APP_SLUG, updated=updated,
    )


def receipt_record(comment_id=RECEIPT_ID, *, body=None, number=ISSUE, kind="issues",
                   created=RECEIPT_CREATED, updated=None, login="Blummer92", **changes):
    return _record(
        comment_id, receipt_body(**changes) if body is None else body,
        login=login, created=created, number=number, kind=kind, updated=updated,
    )


def verified_chain(**kwargs):
    """The default fully-verified fixture: request < result < receipt records."""
    return {
        REQUEST_ID: request_record(),
        RESULT_ID: result_record(**{k: v for k, v in kwargs.items() if k in ("number", "kind")}),
        RECEIPT_ID: receipt_record(**{k: v for k, v in kwargs.items() if k in ("number", "kind")}),
    }


def fetch_from(records):
    """Trusted-read stub: exact-id lookup with a call log; unknown id is a 404."""
    from agent_os_execution_service.ckr6_github_reader import GitHubIssueCommentReadUnavailable

    calls = []

    def fetch(comment_id):
        calls.append(comment_id)
        try:
            return records[comment_id]
        except KeyError:
            raise GitHubIssueCommentReadUnavailable(
                "github-api-failure", "GitHub API returned HTTP 404"
            ) from None

    fetch.calls = calls
    return fetch


# Exact live malformed LL-87 receipt bodies (public #3418, fetched read-only
# 2026-11-13; identical verdicts to the archived mission evidence). The
# trailing backtick after the JSON line is the production parse defect input.
LL87_RECEIPT_6080491160_BODY = (
    '<!-- agent-os-lesson-receipt:v1 -->\n'
    '{"ckr6_result_comment_id":6080461535,"decision":"Linked PRs #3456-#3458 with'
    " \'Part of #N\', kept close/fix/resolve wording away from issue numbers, and"
    ' verified by readback regex that no closing reference existed; issues stayed'
    ' open after merge.","disposition":"applied","lesson_id":"LL-87",'
    '"outcome_ref":"`https://github.com/Blummer92/agent-os/pull/3458",'
    '"reason_code":"confirmed-existing-approach",'
    '"source_revision":"2026-10-05T13:06:00.000Z",'
    '"task_ref":"https://github.com/Blummer92/agent-os/issues/3418"}`'
    '\n\n---\n_Generated by [Claude Code](https://claude.ai/code)_'
)

LL87_RECEIPT_6080710239_BODY = (
    '<!-- agent-os-lesson-receipt:v1 -->\n'
    '{"ckr6_result_comment_id":6080461535,"decision":"The three lesson-loop PRs'
    ' were linked as Part-of only, with no issue-linking verbs near issue'
    ' numbers, verified by readback before merge; the issues stayed open after'
    ' merge as intended.","disposition":"applied","lesson_id":"LL-87",'
    '"outcome_ref":"`https://github.com/Blummer92/agent-os/pull/3458",'
    '"reason_code":"confirmed-existing-approach",'
    '"source_revision":"2026-10-05T13:06:00.000Z",'
    '"task_ref":"https://github.com/Blummer92/agent-os/issues/3418"}`'
    '\n\n---\n_Generated by [Claude Code](https://claude.ai/code)_'
)
