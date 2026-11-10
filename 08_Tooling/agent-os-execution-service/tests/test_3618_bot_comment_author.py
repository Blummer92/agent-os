"""#3618 (D4): GitHub App bot comments must not poison owner authorization.

Every test that matters drives the real ``HostGitHubReadTransport`` over a fake
JSON reader, so the host transport -> snapshot -> reacquisition path runs as it
does in production. Only the HTTP layer is faked.
"""

from __future__ import annotations

import pytest

from agent_os_execution_service import human_approval_custody
from agent_os_execution_service.execution_authorization_source import (
    EXECUTION_AUTHORIZATION_COMMENT_MARKER,
    INSTRUCTIONAL_MATERIALS_LIVE_OPERATION,
    MAX_COMMENT_BYTES,
    ExecutionAuthorizationCommentSnapshot,
    ExecutionAuthorizationSourceReason as Reason,
    ExecutionAuthorizationSourceSnapshot,
    ExecutionAuthorizationSourceStatus as Status,
    execution_authorization_id,
    reacquire_execution_authorization,
    reacquire_live_operation_execution_authorization,
    serialize_execution_authorization_comment,
    serialize_live_operation_execution_authorization_comment,
)
from agent_os_execution_service.host_github_read_transport import (
    COMMENTS_PAGE_SIZE,
    HostGitHubReadError,
    HostGitHubReadTransport,
)
from scripts.agent_os_candidate_packet_live_input import SingleIssueTransportOutcome

REPOSITORY = "Blummer92/agent-os"
ISSUE = 3333
OWNER = "Blummer92"
BOT = "github-actions[bot]"
OPERATION = "pre-pr-developer-loop"
SHA = "d" * 40
CANDIDATE = "candidate-packet:" + "a" * 64
REQUEST = "execution-request:" + "b" * 64
PLAN = "command-plan:" + "c" * 64
INVOCATION = "invocation-3333"
EVALUATED_AT = "2026-10-15T12:00:00Z"
RECORD = {
    "issue_number": ISSUE,
    "authorizer_id": OWNER,
    "authorized_candidate_packet_id": CANDIDATE,
    "authorized_invocation_id": INVOCATION,
    "authorized_operation": OPERATION,
    "request_fingerprint": REQUEST,
    "command_plan_id": PLAN,
    "repository": REPOSITORY,
    "expected_sha": SHA,
    "authorized_at": "2026-10-15T11:00:00Z",
    "expires_at": "2026-10-15T13:00:00Z",
    "execution_authorized": True,
}
CKR6_BOT_BODY = (
    "<!-- agent-os-ckr6-lessons-result -->\n"
    "CKR6 lessons-learned preflight result: `not-needed`. Advisory only."
)


def _record(**changes: object) -> str:
    return serialize_execution_authorization_comment(**{**RECORD, **changes})


def _item(comment_id: int, login: object, body: object, created_at: str) -> dict[str, object]:
    return {"id": comment_id, "user": {"login": login}, "created_at": created_at, "body": body}


def _bot_items(count: int = 6, *, start_id: int = 100) -> list[dict[str, object]]:
    # Mirrors #3333: several CKR6 workflow comments interleaved in the thread.
    return [
        _item(start_id + n, BOT, CKR6_BOT_BODY, f"2026-10-15T10:{n // 60:02d}:{n % 60:02d}Z")
        for n in range(count)
    ]


def _owner_item(comment_id: int = 500, *, body: str | None = None, created_at: str = "2026-10-15T11:01:00Z") -> dict[str, object]:
    return _item(comment_id, OWNER, _record() if body is None else body, created_at)


class _Reader:
    """Fake JSON reader over GitHub REST paths; counts every call."""

    def __init__(self, comments: list[dict[str, object]], *, owner_login: object = OWNER, owner_type: object = "User", error: Exception | None = None) -> None:
        self.comments = comments
        self.owner = {"login": owner_login, "type": owner_type}
        self.error = error
        self.calls: list[str] = []

    def __call__(self, path: str, parameters: dict[str, object] | None) -> object:
        self.calls.append(path)
        if self.error is not None:
            raise self.error
        if path == f"/repos/{REPOSITORY}":
            return {"owner": self.owner}
        if path == f"/repos/{REPOSITORY}/issues/{ISSUE}/comments":
            assert parameters is not None
            page = int(parameters["page"])
            size = int(parameters["per_page"])
            return self.comments[(page - 1) * size : page * size]
        raise AssertionError(f"unexpected read {path}")


def _transport(reader: _Reader, **kwargs: object) -> HostGitHubReadTransport:
    return HostGitHubReadTransport(read_json=reader, **kwargs)


def _reacquire(transport: object, **changes: object):
    values: dict[str, object] = {
        "transport": transport,
        "repository": REPOSITORY,
        "issue_number": ISSUE,
        "expected_candidate_packet_id": CANDIDATE,
        "expected_invocation_id": INVOCATION,
        "expected_operation": OPERATION,
        "expected_request_fingerprint": REQUEST,
        "expected_command_plan_id": PLAN,
        "expected_sha": SHA,
        "evaluated_at": EVALUATED_AT,
    }
    values.update(changes)
    return reacquire_execution_authorization(**values)


def _through_host(comments: list[dict[str, object]], **changes: object):
    return _reacquire(_transport(_Reader(comments)), **changes)


# --- the defect itself -----------------------------------------------------


def test_bot_comments_alone_no_longer_make_the_source_unavailable() -> None:
    result = _through_host(_bot_items())
    assert result.status is Status.BLOCKED
    assert result.reason_codes == (Reason.AUTHORIZATION_MISSING,)


def test_owner_record_among_many_bot_comments_is_current() -> None:
    comments = _bot_items(3) + [_owner_item()] + _bot_items(3, start_id=200)
    result = _through_host(comments)
    assert result.status is Status.CURRENT
    assert result.reason_codes == (Reason.CURRENT,)
    assert result.evidence is not None
    assert result.evidence.authorization_id == execution_authorization_id(**RECORD)


def test_snapshot_keeps_every_bot_comment_rather_than_dropping_them() -> None:
    reader = _Reader(_bot_items() + [_owner_item()])
    snapshot = _transport(reader).read_authorization_source(REPOSITORY, ISSUE)
    assert snapshot.comments_complete is True
    assert [item.author_login for item in snapshot.comments] == [BOT] * 6 + [OWNER]


def test_bot_comments_spanning_pagination_are_read_completely() -> None:
    comments = _bot_items(COMMENTS_PAGE_SIZE + 5) + [_owner_item(created_at="2026-10-15T11:59:00Z")]
    reader = _Reader(comments)
    result = _reacquire(_transport(reader))
    assert result.status is Status.CURRENT
    assert reader.calls.count(f"/repos/{REPOSITORY}/issues/{ISSUE}/comments") == 2


# --- bots and other non-owners can never authorize ---------------------------


@pytest.mark.parametrize("author", [BOT, "dependabot[bot]", "Blummer92[bot]", "blummer92[bot]", "mallory"])
def test_non_owner_marker_bearing_record_is_ignored_not_promoted(author: str) -> None:
    result = _through_host(_bot_items() + [_item(600, author, _record(), "2026-10-15T11:01:00Z")])
    assert result.status is Status.BLOCKED
    assert result.reason_codes == (Reason.AUTHORIZATION_MISSING,)
    assert result.evidence is None


def test_later_bot_record_cannot_override_owner_revocation() -> None:
    comments = [
        _owner_item(500, body=_record(execution_authorized=False)),
        _item(600, BOT, _record(), "2026-10-15T11:30:00Z"),
    ]
    result = _through_host(comments)
    assert result.status is Status.BLOCKED
    assert result.reason_codes == (Reason.AUTHORIZATION_REVOKED,)


def test_malformed_bot_marker_body_does_not_block_owner_record() -> None:
    bad = EXECUTION_AUTHORIZATION_COMMENT_MARKER + "\n{not json"
    result = _through_host([_item(600, BOT, bad, "2026-10-15T11:00:30Z"), _owner_item()])
    assert result.status is Status.CURRENT


# --- malformed identities stay fail closed -----------------------------------


@pytest.mark.parametrize(
    "login",
    ["[bot]", "github-actions[bot][bot]", "github actions[bot]", "-actions[bot]", "github-actions[BOT]", "github-actions[bot", "bot]", "github-actions[app]", "", " Blummer92", None, 7],
)
def test_malformed_comment_author_fails_closed_as_source_unavailable(login: object) -> None:
    result = _through_host([_owner_item(), _item(600, login, CKR6_BOT_BODY, "2026-10-15T11:02:00Z")])
    assert result.status is Status.NEEDS_DECISION
    assert result.reason_codes == (Reason.SOURCE_UNAVAILABLE,)


@pytest.mark.parametrize("login", ["[bot]", "x[bot][bot]", "x [bot]", "x[BOT]"])
def test_snapshot_rejects_malformed_bot_logins(login: str) -> None:
    with pytest.raises(ValueError, match="author_login is malformed"):
        ExecutionAuthorizationCommentSnapshot(comment_id=1, author_login=login, created_at="2026-10-15T11:00:00Z", body="")


@pytest.mark.parametrize("owner_login", ["Blummer92[bot]", "github-actions[bot]", "[bot]"])
def test_owner_login_keeps_strict_identifier_validation(owner_login: str) -> None:
    with pytest.raises(ValueError, match="owner_login is malformed"):
        ExecutionAuthorizationSourceSnapshot(repository=REPOSITORY, issue_number=ISSUE, owner_login=owner_login, owner_type="User", comments_complete=True, comments=())
    result = _reacquire(_transport(_Reader([_owner_item()], owner_login=owner_login)))
    assert result.status is Status.NEEDS_DECISION
    assert result.reason_codes == (Reason.SOURCE_UNAVAILABLE,)


@pytest.mark.parametrize("owner_type", ["Bot", "Organization"])
def test_non_user_owner_is_unsupported(owner_type: str) -> None:
    result = _reacquire(_transport(_Reader(_bot_items() + [_owner_item()], owner_type=owner_type)))
    assert result.status is Status.NEEDS_DECISION
    assert result.reason_codes == (Reason.OWNER_UNSUPPORTED,)


def test_malformed_owner_record_still_needs_decision() -> None:
    bad = EXECUTION_AUTHORIZATION_COMMENT_MARKER + "\n{not json"
    result = _through_host(_bot_items() + [_owner_item(body=bad)])
    assert result.status is Status.NEEDS_DECISION
    assert result.reason_codes == (Reason.TRUSTED_RECORD_MALFORMED,)


# --- source shape stays fail closed with bot comments present ----------------


def test_incomplete_pagination_needs_decision() -> None:
    comments = _bot_items(COMMENTS_PAGE_SIZE) + [_owner_item()]
    result = _reacquire(_transport(_Reader(comments), max_comment_pages=1))
    assert result.status is Status.NEEDS_DECISION
    assert result.reason_codes == (Reason.SOURCE_INCOMPLETE,)


def test_duplicate_comment_ids_need_decision() -> None:
    result = _through_host([_item(500, BOT, CKR6_BOT_BODY, "2026-10-15T10:00:00Z"), _owner_item(500)])
    assert result.status is Status.NEEDS_DECISION
    assert result.reason_codes == (Reason.SOURCE_AMBIGUOUS,)


def test_oversize_bot_comment_still_fails_closed() -> None:
    huge = "x" * (MAX_COMMENT_BYTES + 1)
    result = _through_host([_item(600, BOT, huge, "2026-10-15T10:00:00Z"), _owner_item()])
    assert result.status is Status.NEEDS_DECISION
    assert result.reason_codes == (Reason.SOURCE_UNAVAILABLE,)


@pytest.mark.parametrize(
    "error",
    [HostGitHubReadError(SingleIssueTransportOutcome.PERMISSION_DENIED), HostGitHubReadError(SingleIssueTransportOutcome.NOT_FOUND), OSError("network down")],
)
def test_unavailable_transport_needs_decision(error: Exception) -> None:
    result = _reacquire(_transport(_Reader([], error=error)))
    assert result.status is Status.NEEDS_DECISION
    assert result.reason_codes == (Reason.SOURCE_UNAVAILABLE,)


# --- binding, currentness and expiry are unchanged ---------------------------


@pytest.mark.parametrize(
    ("changes", "status", "reason"),
    [
        ({"expected_operation": "validation-only"}, Status.STALE, Reason.BINDING_MISMATCH),
        ({"expected_sha": "e" * 40}, Status.STALE, Reason.BINDING_MISMATCH),
        ({"expected_command_plan_id": "command-plan:" + "f" * 64}, Status.STALE, Reason.BINDING_MISMATCH),
        ({"expected_invocation_id": "invocation-other"}, Status.BLOCKED, Reason.AUTHORIZATION_MISSING),
        ({"evaluated_at": "2026-10-15T13:00:00Z"}, Status.STALE, Reason.AUTHORIZATION_EXPIRED),
        ({"evaluated_at": "2026-10-15T10:59:59Z"}, Status.STALE, Reason.AUTHORIZATION_NOT_YET_ACTIVE),
        ({"expected_authorization_id": "execution-authorization:" + "0" * 64}, Status.STALE, Reason.AUTHORIZATION_SUPERSEDED),
    ],
)
def test_binding_and_time_checks_still_fail_closed(changes: dict[str, object], status: Status, reason: Reason) -> None:
    result = _through_host(_bot_items() + [_owner_item()], **changes)
    assert result.status is status
    assert result.reason_codes == (reason,)


def test_wrong_issue_snapshot_is_ambiguous() -> None:
    class _WrongIssue:
        def read_authorization_source(self, repository: str, issue_number: int) -> ExecutionAuthorizationSourceSnapshot:
            return ExecutionAuthorizationSourceSnapshot(repository=REPOSITORY, issue_number=ISSUE + 1, owner_login=OWNER, owner_type="User", comments_complete=True, comments=())

    result = _reacquire(_WrongIssue())
    assert result.status is Status.NEEDS_DECISION
    assert result.reason_codes == (Reason.SOURCE_AMBIGUOUS,)


# --- the shared snapshot's other readers benefit, and stay owner-only --------


def test_live_v2_reader_reads_owner_record_among_bot_comments() -> None:
    live = {
        "issue_number": ISSUE,
        "authorizer_id": OWNER,
        "repository": REPOSITORY,
        "authorized_subject_id": "instructional-live-operation-subject:" + "1" * 64,
        "authorized_approval_id": "approval:" + "2" * 64,
        "authorized_approval_revision": "approval-revision:" + "3" * 64,
        "authorized_projection_id": "approved-execution-projection:" + "4" * 64,
        "authorized_run_id": "run-1",
        "authorized_task_id": "task-1",
        "authorized_attempt_number": 0,
        "authorized_operation": INSTRUCTIONAL_MATERIALS_LIVE_OPERATION,
        "authorized_at": "2026-10-15T11:00:00Z",
        "expires_at": "2026-10-15T13:00:00Z",
        "execution_authorized": True,
    }
    body = serialize_live_operation_execution_authorization_comment(**live)
    expected = {
        "repository": REPOSITORY,
        "issue_number": ISSUE,
        "expected_subject_id": live["authorized_subject_id"],
        "expected_approval_id": live["authorized_approval_id"],
        "expected_approval_revision": live["authorized_approval_revision"],
        "expected_projection_id": live["authorized_projection_id"],
        "expected_run_id": "run-1",
        "expected_task_id": "task-1",
        "expected_attempt_number": 0,
        "expected_operation": INSTRUCTIONAL_MATERIALS_LIVE_OPERATION,
        "evaluated_at": EVALUATED_AT,
    }
    owner = reacquire_live_operation_execution_authorization(
        transport=_transport(_Reader(_bot_items() + [_owner_item(body=body)])), **expected
    )
    assert owner.status is Status.CURRENT
    bot_only = reacquire_live_operation_execution_authorization(
        transport=_transport(_Reader(_bot_items() + [_item(600, BOT, body, "2026-10-15T11:01:00Z")])), **expected
    )
    assert bot_only.status is Status.BLOCKED
    assert bot_only.reason_codes == (Reason.AUTHORIZATION_MISSING,)


def test_human_approval_custody_ignores_bot_approval_command() -> None:
    provenance = "pre-publication-evidence:" + "a" * 64
    command = f"/agent-os approve-candidate {provenance}"
    with pytest.raises(human_approval_custody.HumanApprovalCustodyError, match="human-approval-missing"):
        human_approval_custody.reacquire_human_approval_decision(
            transport=_transport(_Reader(_bot_items() + [_item(600, BOT, command, "2026-10-15T11:01:00Z")])),
            repository=REPOSITORY,
            issue_number=ISSUE,
            candidate_provenance_id=provenance,
        )
    result = human_approval_custody.reacquire_human_approval_decision(
        transport=_transport(_Reader(_bot_items() + [_owner_item(body=command)])),
        repository=REPOSITORY,
        issue_number=ISSUE,
        candidate_provenance_id=provenance,
    )
    assert result.authorizer_id == OWNER
    assert result.source_comment_id == 500
