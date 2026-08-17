from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from agent_os_execution_service.execution_authorization_source import (
    EXECUTION_AUTHORIZATION_COMMENT_MARKER,
    ExecutionAuthorizationCommentSnapshot,
    ExecutionAuthorizationSourceReason,
    ExecutionAuthorizationSourceSnapshot,
    ExecutionAuthorizationSourceStatus,
    reacquire_execution_authorization,
    serialize_execution_authorization_comment,
)

SHA = "d" * 40
CANDIDATE = "candidate-packet:" + "a" * 64
REQUEST = "execution-request:" + "b" * 64
PLAN = "command-plan:" + "c" * 64
INVOCATION = "invocation-1226"
BASE = {
    "issue_number": 1226,
    "authorizer_id": "Blummer92",
    "authorized_candidate_packet_id": CANDIDATE,
    "authorized_invocation_id": INVOCATION,
    "authorized_operation": "validation-only",
    "request_fingerprint": REQUEST,
    "command_plan_id": PLAN,
    "repository": "Blummer92/agent-os",
    "expected_sha": SHA,
    "authorized_at": "2026-08-17T17:00:00Z",
    "expires_at": "2026-08-17T19:00:00Z",
    "execution_authorized": True,
}


def _body(**changes: object) -> str:
    return serialize_execution_authorization_comment(**{**BASE, **changes})


def _comment(
    comment_id: int = 1,
    *,
    author: str = "Blummer92",
    text: str | None = None,
    created_at: str = "2026-08-17T17:01:00Z",
) -> ExecutionAuthorizationCommentSnapshot:
    return ExecutionAuthorizationCommentSnapshot(
        comment_id=comment_id,
        author_login=author,
        created_at=created_at,
        body=_body() if text is None else text,
    )


def _snapshot(
    comments: tuple[ExecutionAuthorizationCommentSnapshot, ...] = (),
    *,
    complete: bool = True,
    owner: str = "Blummer92",
    owner_type: str = "User",
) -> ExecutionAuthorizationSourceSnapshot:
    return ExecutionAuthorizationSourceSnapshot(
        repository="Blummer92/agent-os",
        issue_number=1226,
        owner_login=owner,
        owner_type=owner_type,
        comments_complete=complete,
        comments=comments,
    )


class _Transport:
    def __init__(self, snapshot: ExecutionAuthorizationSourceSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def read_authorization_source(
        self, repository: str, issue_number: int
    ) -> ExecutionAuthorizationSourceSnapshot:
        self.calls += 1
        return self.snapshot


def _read(
    snapshot: ExecutionAuthorizationSourceSnapshot,
    **changes: object,
):
    values: dict[str, object] = {
        "transport": _Transport(snapshot),
        "repository": "Blummer92/agent-os",
        "issue_number": 1226,
        "expected_candidate_packet_id": CANDIDATE,
        "expected_invocation_id": INVOCATION,
        "expected_operation": "validation-only",
        "expected_request_fingerprint": REQUEST,
        "expected_command_plan_id": PLAN,
        "expected_sha": SHA,
        "evaluated_at": "2026-08-17T18:00:00Z",
    }
    values.update(changes)
    return reacquire_execution_authorization(**values)


def test_exact_owner_record_is_current_and_deterministic() -> None:
    snapshot = _snapshot((_comment(),))
    first = _read(snapshot)
    second = _read(snapshot)
    assert first == second
    assert first.status is ExecutionAuthorizationSourceStatus.CURRENT
    assert first.reason_codes == (ExecutionAuthorizationSourceReason.CURRENT,)
    assert first.evidence is not None
    assert first.evidence.execution_authorized is True
    assert first.evidence.authorization_id in _body()
    assert _body() == serialize_execution_authorization_comment(**BASE)


def test_missing_authorization_is_blocked() -> None:
    assert _read(_snapshot()).status is ExecutionAuthorizationSourceStatus.BLOCKED


def test_incomplete_source_needs_decision() -> None:
    assert _read(_snapshot(complete=False)).reason_codes == (
        ExecutionAuthorizationSourceReason.SOURCE_INCOMPLETE,
    )


def test_organization_owner_is_unsupported() -> None:
    assert _read(_snapshot(owner_type="Organization")).reason_codes == (
        ExecutionAuthorizationSourceReason.OWNER_UNSUPPORTED,
    )


def test_non_owner_marker_cannot_authorize() -> None:
    result = _read(_snapshot((_comment(author="other"),)))
    assert result.status is ExecutionAuthorizationSourceStatus.BLOCKED
    assert result.reason_codes == (
        ExecutionAuthorizationSourceReason.AUTHORIZATION_MISSING,
    )


def test_ordinary_owner_prose_cannot_authorize() -> None:
    result = _read(_snapshot((_comment(text="Work on 1226"),)))
    assert result.status is ExecutionAuthorizationSourceStatus.BLOCKED


@pytest.mark.parametrize(
    "text",
    (
        EXECUTION_AUTHORIZATION_COMMENT_MARKER + "\n{}",
        EXECUTION_AUTHORIZATION_COMMENT_MARKER + '\n{"x":1}',
        EXECUTION_AUTHORIZATION_COMMENT_MARKER + "\n{}\nextra",
    ),
)
def test_malformed_trusted_record_needs_decision(text: str) -> None:
    assert _read(_snapshot((_comment(text=text),))).reason_codes == (
        ExecutionAuthorizationSourceReason.TRUSTED_RECORD_MALFORMED,
    )


def test_tampered_authorization_id_needs_decision() -> None:
    marker, serialized = _body().splitlines()
    payload = json.loads(serialized)
    payload["authorization_id"] = "execution-authorization:" + "0" * 64
    text = marker + "\n" + json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert _read(_snapshot((_comment(text=text),))).reason_codes == (
        ExecutionAuthorizationSourceReason.TRUSTED_RECORD_MALFORMED,
    )


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        (
            {"expires_at": "2026-08-17T17:30:00Z"},
            ExecutionAuthorizationSourceReason.AUTHORIZATION_EXPIRED,
        ),
        (
            {
                "authorized_at": "2026-08-17T18:30:00Z",
                "expires_at": "2026-08-17T19:30:00Z",
            },
            ExecutionAuthorizationSourceReason.AUTHORIZATION_NOT_YET_ACTIVE,
        ),
    ),
)
def test_authorization_window_drift_is_stale(
    changes: dict[str, object], reason: ExecutionAuthorizationSourceReason
) -> None:
    result = _read(_snapshot((_comment(text=_body(**changes)),)))
    assert result.status is ExecutionAuthorizationSourceStatus.STALE
    assert result.reason_codes == (reason,)


def test_newer_false_record_revokes_older_true_record() -> None:
    old = _comment(1, created_at="2026-08-17T17:01:00Z")
    new = _comment(
        2,
        text=_body(execution_authorized=False),
        created_at="2026-08-17T17:02:00Z",
    )
    result = _read(_snapshot((new, old)))
    assert result.status is ExecutionAuthorizationSourceStatus.BLOCKED
    assert result.reason_codes == (
        ExecutionAuthorizationSourceReason.AUTHORIZATION_REVOKED,
    )


def test_newer_true_record_supersedes_expected_old_identity() -> None:
    old_text = _body()
    old_id = json.loads(old_text.splitlines()[1])["authorization_id"]
    new = _comment(
        2,
        text=_body(expires_at="2026-08-17T20:00:00Z"),
        created_at="2026-08-17T17:02:00Z",
    )
    result = _read(
        _snapshot((_comment(1, text=old_text), new)),
        expected_authorization_id=old_id,
    )
    assert result.status is ExecutionAuthorizationSourceStatus.STALE
    assert result.reason_codes == (
        ExecutionAuthorizationSourceReason.AUTHORIZATION_SUPERSEDED,
    )


@pytest.mark.parametrize(
    ("argument", "value"),
    (
        ("expected_candidate_packet_id", "candidate-packet:" + "f" * 64),
        ("expected_operation", "other"),
        ("expected_request_fingerprint", "execution-request:" + "f" * 64),
        ("expected_command_plan_id", "command-plan:" + "f" * 64),
        ("expected_sha", "e" * 40),
    ),
)
def test_expected_binding_drift_is_stale(argument: str, value: str) -> None:
    result = _read(_snapshot((_comment(),)), **{argument: value})
    assert result.status is ExecutionAuthorizationSourceStatus.STALE
    assert result.reason_codes == (
        ExecutionAuthorizationSourceReason.BINDING_MISMATCH,
    )


def test_repository_and_issue_drift_are_fail_closed() -> None:
    repository = _read(_snapshot((_comment(text=_body(repository="Other/repo")),)))
    issue = _read(_snapshot((_comment(text=_body(issue_number=999)),)))
    assert repository.reason_codes == (
        ExecutionAuthorizationSourceReason.BINDING_MISMATCH,
    )
    assert issue.reason_codes == (
        ExecutionAuthorizationSourceReason.BINDING_MISMATCH,
    )


def test_other_invocation_does_not_authorize_expected_invocation() -> None:
    result = _read(
        _snapshot((_comment(text=_body(authorized_invocation_id="other")),))
    )
    assert result.reason_codes == (
        ExecutionAuthorizationSourceReason.AUTHORIZATION_MISSING,
    )


def test_duplicate_comment_ids_are_ambiguous() -> None:
    result = _read(_snapshot((_comment(1), _comment(1))))
    assert result.reason_codes == (
        ExecutionAuthorizationSourceReason.SOURCE_AMBIGUOUS,
    )


def test_transport_is_called_at_most_once() -> None:
    transport = _Transport(_snapshot((_comment(),)))
    reacquire_execution_authorization(
        transport=transport,
        repository="Blummer92/agent-os",
        issue_number=1226,
        expected_candidate_packet_id=CANDIDATE,
        expected_invocation_id=INVOCATION,
        expected_operation="validation-only",
        expected_request_fingerprint=REQUEST,
        expected_command_plan_id=PLAN,
        expected_sha=SHA,
        evaluated_at="2026-08-17T18:00:00Z",
    )
    assert transport.calls == 1


def test_source_module_has_no_runtime_or_network_capability() -> None:
    module = __import__(
        "agent_os_execution_service.execution_authorization_source",
        fromlist=["placeholder"],
    )
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert not roots & {
        "github",
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "workflow_scheduler",
    }
