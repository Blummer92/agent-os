"""Read-only GitHub-backed reacquisition of current execution authorization.

GitHub transport is injected. Only exact repository-owner-authored machine
records can produce the existing ExecutionAuthorizationEvidence model. This
module performs no GitHub/network/runtime/write operation itself.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Protocol, runtime_checkable

from .authorization import ExecutionAuthorizationEvidence

EXECUTION_AUTHORIZATION_SOURCE_SCHEMA_VERSION = "1.0"
EXECUTION_AUTHORIZATION_COMMENT_MARKER = "agent-os-execution-authorization/v1"
MAX_COMMENTS = 512
MAX_COMMENT_BYTES = 32 * 1024
MAX_TOTAL_COMMENT_BYTES = 256 * 1024
MAX_TEXT_BYTES = 512

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_AUTHORIZATION_ID_RE = re.compile(
    r"^execution-authorization:[0-9a-f]{64}$", re.ASCII
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,511}$", re.ASCII)
_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", re.ASCII
)
_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "issue_number",
        "authorizer_id",
        "authorized_candidate_packet_id",
        "authorized_invocation_id",
        "authorized_operation",
        "request_fingerprint",
        "command_plan_id",
        "repository",
        "expected_sha",
        "authorized_at",
        "expires_at",
        "execution_authorized",
        "authorization_id",
    }
)


class ExecutionAuthorizationSourceStatus(str, Enum):
    CURRENT = "current"
    BLOCKED = "blocked"
    STALE = "stale"
    NEEDS_DECISION = "needs-decision"


class ExecutionAuthorizationSourceReason(str, Enum):
    CURRENT = "current"
    AUTHORIZATION_MISSING = "authorization-missing"
    AUTHORIZATION_REVOKED = "authorization-revoked"
    AUTHORIZATION_EXPIRED = "authorization-expired"
    AUTHORIZATION_NOT_YET_ACTIVE = "authorization-not-yet-active"
    AUTHORIZATION_SUPERSEDED = "authorization-superseded"
    BINDING_MISMATCH = "binding-mismatch"
    SOURCE_INCOMPLETE = "source-incomplete"
    SOURCE_AMBIGUOUS = "source-ambiguous"
    OWNER_UNSUPPORTED = "owner-unsupported"
    TRUSTED_RECORD_MALFORMED = "trusted-record-malformed"
    SOURCE_UNAVAILABLE = "source-unavailable"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty canonical text")
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES or any(
        ord(ch) < 32 or ord(ch) == 127 for ch in value
    ):
        raise ValueError(f"{name} is outside bounds")
    return value


def _identifier(value: object, name: str) -> str:
    text = _text(value, name)
    if not _IDENTIFIER_RE.fullmatch(text):
        raise ValueError(f"{name} is malformed")
    return text


def _repository(value: object) -> str:
    text = _text(value, "repository")
    if not _REPOSITORY_RE.fullmatch(text):
        raise ValueError("repository is malformed")
    return text


def _timestamp(value: object, name: str) -> datetime:
    text = _text(value, name)
    if not _TIMESTAMP_RE.fullmatch(text):
        raise ValueError(f"{name} must use canonical UTC seconds")
    parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != text:
        raise ValueError(f"{name} is not canonical")
    return parsed


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise TypeError(f"{name} must be a positive exact integer")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionAuthorizationCommentSnapshot:
    comment_id: int
    author_login: str
    created_at: str
    body: str

    def __post_init__(self) -> None:
        _positive_int(self.comment_id, "comment_id")
        _identifier(self.author_login, "author_login")
        _timestamp(self.created_at, "created_at")
        if type(self.body) is not str or len(self.body.encode("utf-8")) > MAX_COMMENT_BYTES:
            raise ValueError("comment body is outside bounds")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionAuthorizationSourceSnapshot:
    repository: str
    issue_number: int
    owner_login: str
    owner_type: str
    comments_complete: bool
    comments: tuple[ExecutionAuthorizationCommentSnapshot, ...]

    def __post_init__(self) -> None:
        _repository(self.repository)
        _positive_int(self.issue_number, "issue_number")
        _identifier(self.owner_login, "owner_login")
        _text(self.owner_type, "owner_type")
        if type(self.comments_complete) is not bool:
            raise TypeError("comments_complete must be an exact boolean")
        if type(self.comments) is not tuple or len(self.comments) > MAX_COMMENTS:
            raise ValueError("comments must be a bounded exact tuple")
        if any(type(item) is not ExecutionAuthorizationCommentSnapshot for item in self.comments):
            raise TypeError("comments must contain exact comment snapshots")
        total = sum(len(item.body.encode("utf-8")) for item in self.comments)
        if total > MAX_TOTAL_COMMENT_BYTES:
            raise ValueError("comment snapshot exceeds total byte bound")


@runtime_checkable
class ExecutionAuthorizationSourceTransport(Protocol):
    def read_authorization_source(
        self, repository: str, issue_number: int
    ) -> ExecutionAuthorizationSourceSnapshot: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class _ParsedAuthorizationRecord:
    issue_number: int
    authorizer_id: str
    authorized_candidate_packet_id: str
    authorized_invocation_id: str
    authorized_operation: str
    evidence: ExecutionAuthorizationEvidence
    source_comment_id: int
    source_created_at: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionAuthorizationReadResult:
    status: ExecutionAuthorizationSourceStatus
    reason_codes: tuple[ExecutionAuthorizationSourceReason, ...]
    evidence: ExecutionAuthorizationEvidence | None
    authorizer_id: str | None
    authorized_candidate_packet_id: str | None
    authorized_invocation_id: str | None
    authorized_operation: str | None
    source_comment_id: int | None
    current_authorization_id: str | None
    expected_authorization_id: str | None
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.status) is not ExecutionAuthorizationSourceStatus:
            raise TypeError("status must be exact ExecutionAuthorizationSourceStatus")
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty exact tuple")
        if any(
            type(item) is not ExecutionAuthorizationSourceReason
            for item in self.reason_codes
        ):
            raise TypeError("reason_codes contain unsupported values")
        expected = tuple(sorted(set(self.reason_codes), key=lambda item: item.value))
        if self.reason_codes != expected:
            raise ValueError("reason_codes must be sorted and unique")
        if self.evidence is not None and type(self.evidence) is not ExecutionAuthorizationEvidence:
            raise TypeError("evidence must be exact ExecutionAuthorizationEvidence or None")
        if self.status is ExecutionAuthorizationSourceStatus.CURRENT and (
            self.reason_codes != (ExecutionAuthorizationSourceReason.CURRENT,)
            or self.evidence is None
            or not self.evidence.execution_authorized
        ):
            raise ValueError("current result requires current authorized evidence")


def _validated_semantic_values(**values: object) -> dict[str, object]:
    expected = set(_RECORD_KEYS) - {"authorization_id", "schema_version"}
    if set(values) != expected:
        raise ValueError(
            "authorization semantic fields are incomplete or contain unknown fields"
        )
    issue_number = _positive_int(values["issue_number"], "issue_number")
    authorizer_id = _identifier(values["authorizer_id"], "authorizer_id")
    candidate = _identifier(
        values["authorized_candidate_packet_id"], "authorized_candidate_packet_id"
    )
    invocation = _identifier(
        values["authorized_invocation_id"], "authorized_invocation_id"
    )
    operation = _identifier(values["authorized_operation"], "authorized_operation")
    request = _identifier(values["request_fingerprint"], "request_fingerprint")
    plan = _identifier(values["command_plan_id"], "command_plan_id")
    repository = _repository(values["repository"])
    sha = _text(values["expected_sha"], "expected_sha")
    if not _SHA40_RE.fullmatch(sha):
        raise ValueError("expected_sha is malformed")
    authorized_at = _text(values["authorized_at"], "authorized_at")
    expires_at = _text(values["expires_at"], "expires_at")
    if _timestamp(authorized_at, "authorized_at") >= _timestamp(expires_at, "expires_at"):
        raise ValueError("authorization window is empty")
    execution_authorized = values["execution_authorized"]
    if type(execution_authorized) is not bool:
        raise TypeError("execution_authorized must be an exact boolean")
    return {
        "schema_version": EXECUTION_AUTHORIZATION_SOURCE_SCHEMA_VERSION,
        "issue_number": issue_number,
        "authorizer_id": authorizer_id,
        "authorized_candidate_packet_id": candidate,
        "authorized_invocation_id": invocation,
        "authorized_operation": operation,
        "request_fingerprint": request,
        "command_plan_id": plan,
        "repository": repository,
        "expected_sha": sha,
        "authorized_at": authorized_at,
        "expires_at": expires_at,
        "execution_authorized": execution_authorized,
    }


def execution_authorization_id(**values: object) -> str:
    payload = _validated_semantic_values(**values)
    digest = hashlib.sha256(
        b"agent-os-execution-authorization:v1\0"
        + _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return f"execution-authorization:{digest}"


def serialize_execution_authorization_comment(**values: object) -> str:
    payload = _validated_semantic_values(**values)
    semantic = {key: value for key, value in payload.items() if key != "schema_version"}
    full = {**payload, "authorization_id": execution_authorization_id(**semantic)}
    return EXECUTION_AUTHORIZATION_COMMENT_MARKER + "\n" + _canonical_json(full)


def _parse_trusted_comment(
    comment: ExecutionAuthorizationCommentSnapshot,
) -> _ParsedAuthorizationRecord | None:
    prefix = EXECUTION_AUTHORIZATION_COMMENT_MARKER + "\n"
    if not comment.body.startswith(prefix):
        return None
    if comment.body.count("\n") != 1:
        raise ValueError("trusted authorization marker must contain exactly two lines")
    serialized = comment.body[len(prefix) :]
    payload = json.loads(serialized)
    if type(payload) is not dict or set(payload) != _RECORD_KEYS:
        raise ValueError("trusted authorization payload fields are invalid")
    if _canonical_json(payload) != serialized:
        raise ValueError("trusted authorization payload is not canonical compact JSON")
    if payload["schema_version"] != EXECUTION_AUTHORIZATION_SOURCE_SCHEMA_VERSION:
        raise ValueError("unsupported authorization source schema")
    semantic = {
        key: payload[key]
        for key in payload
        if key not in {"authorization_id", "schema_version"}
    }
    validated = _validated_semantic_values(**semantic)
    identity_values = {
        key: value for key, value in validated.items() if key != "schema_version"
    }
    expected_id = execution_authorization_id(**identity_values)
    supplied_id = payload["authorization_id"]
    if (
        type(supplied_id) is not str
        or not _AUTHORIZATION_ID_RE.fullmatch(supplied_id)
        or supplied_id != expected_id
    ):
        raise ValueError("authorization_id does not match authorization content")
    evidence = ExecutionAuthorizationEvidence(
        authorization_id=expected_id,
        request_fingerprint=validated["request_fingerprint"],
        command_plan_id=validated["command_plan_id"],
        repository=validated["repository"],
        expected_sha=validated["expected_sha"],
        authorized_at=validated["authorized_at"],
        expires_at=validated["expires_at"],
        execution_authorized=validated["execution_authorized"],
    )
    return _ParsedAuthorizationRecord(
        issue_number=validated["issue_number"],
        authorizer_id=validated["authorizer_id"],
        authorized_candidate_packet_id=validated["authorized_candidate_packet_id"],
        authorized_invocation_id=validated["authorized_invocation_id"],
        authorized_operation=validated["authorized_operation"],
        evidence=evidence,
        source_comment_id=comment.comment_id,
        source_created_at=comment.created_at,
    )


def _result(
    status: ExecutionAuthorizationSourceStatus,
    reasons: tuple[ExecutionAuthorizationSourceReason, ...],
    *,
    record: _ParsedAuthorizationRecord | None = None,
    expected_authorization_id: str | None = None,
) -> ExecutionAuthorizationReadResult:
    return ExecutionAuthorizationReadResult(
        status=status,
        reason_codes=tuple(sorted(set(reasons), key=lambda item: item.value)),
        evidence=None if record is None else record.evidence,
        authorizer_id=None if record is None else record.authorizer_id,
        authorized_candidate_packet_id=(
            None if record is None else record.authorized_candidate_packet_id
        ),
        authorized_invocation_id=(
            None if record is None else record.authorized_invocation_id
        ),
        authorized_operation=None if record is None else record.authorized_operation,
        source_comment_id=None if record is None else record.source_comment_id,
        current_authorization_id=(
            None if record is None else record.evidence.authorization_id
        ),
        expected_authorization_id=expected_authorization_id,
    )


def reacquire_execution_authorization(
    *,
    transport: ExecutionAuthorizationSourceTransport,
    repository: str,
    issue_number: int,
    expected_candidate_packet_id: str,
    expected_invocation_id: str,
    expected_operation: str,
    expected_request_fingerprint: str,
    expected_command_plan_id: str,
    expected_sha: str,
    evaluated_at: str,
    expected_authorization_id: str | None = None,
) -> ExecutionAuthorizationReadResult:
    repository = _repository(repository)
    issue_number = _positive_int(issue_number, "issue_number")
    for value, name in (
        (expected_candidate_packet_id, "expected_candidate_packet_id"),
        (expected_invocation_id, "expected_invocation_id"),
        (expected_operation, "expected_operation"),
        (expected_request_fingerprint, "expected_request_fingerprint"),
        (expected_command_plan_id, "expected_command_plan_id"),
    ):
        _identifier(value, name)
    expected_sha = _text(expected_sha, "expected_sha")
    if not _SHA40_RE.fullmatch(expected_sha):
        raise ValueError("expected_sha is malformed")
    evaluated = _timestamp(evaluated_at, "evaluated_at")
    if expected_authorization_id is not None and (
        type(expected_authorization_id) is not str
        or not _AUTHORIZATION_ID_RE.fullmatch(expected_authorization_id)
    ):
        raise ValueError("expected_authorization_id is malformed")
    if not isinstance(transport, ExecutionAuthorizationSourceTransport):
        raise TypeError("transport must satisfy ExecutionAuthorizationSourceTransport")
    try:
        snapshot = transport.read_authorization_source(repository, issue_number)
    except (TypeError, ValueError, RuntimeError, OSError):
        return _result(
            ExecutionAuthorizationSourceStatus.NEEDS_DECISION,
            (ExecutionAuthorizationSourceReason.SOURCE_UNAVAILABLE,),
            expected_authorization_id=expected_authorization_id,
        )
    if type(snapshot) is not ExecutionAuthorizationSourceSnapshot:
        return _result(
            ExecutionAuthorizationSourceStatus.NEEDS_DECISION,
            (ExecutionAuthorizationSourceReason.SOURCE_UNAVAILABLE,),
            expected_authorization_id=expected_authorization_id,
        )
    if (
        snapshot.repository.casefold() != repository.casefold()
        or snapshot.issue_number != issue_number
    ):
        return _result(
            ExecutionAuthorizationSourceStatus.NEEDS_DECISION,
            (ExecutionAuthorizationSourceReason.SOURCE_AMBIGUOUS,),
            expected_authorization_id=expected_authorization_id,
        )
    if snapshot.owner_type != "User":
        return _result(
            ExecutionAuthorizationSourceStatus.NEEDS_DECISION,
            (ExecutionAuthorizationSourceReason.OWNER_UNSUPPORTED,),
            expected_authorization_id=expected_authorization_id,
        )
    if not snapshot.comments_complete:
        return _result(
            ExecutionAuthorizationSourceStatus.NEEDS_DECISION,
            (ExecutionAuthorizationSourceReason.SOURCE_INCOMPLETE,),
            expected_authorization_id=expected_authorization_id,
        )
    comment_ids = [item.comment_id for item in snapshot.comments]
    if len(comment_ids) != len(set(comment_ids)):
        return _result(
            ExecutionAuthorizationSourceStatus.NEEDS_DECISION,
            (ExecutionAuthorizationSourceReason.SOURCE_AMBIGUOUS,),
            expected_authorization_id=expected_authorization_id,
        )

    records: list[_ParsedAuthorizationRecord] = []
    for comment in sorted(snapshot.comments, key=lambda item: (item.created_at, item.comment_id)):
        if comment.author_login.casefold() != snapshot.owner_login.casefold():
            continue
        try:
            record = _parse_trusted_comment(comment)
        except (TypeError, ValueError, json.JSONDecodeError, RecursionError):
            return _result(
                ExecutionAuthorizationSourceStatus.NEEDS_DECISION,
                (ExecutionAuthorizationSourceReason.TRUSTED_RECORD_MALFORMED,),
                expected_authorization_id=expected_authorization_id,
            )
        if record is None:
            continue
        if record.authorizer_id.casefold() != snapshot.owner_login.casefold():
            return _result(
                ExecutionAuthorizationSourceStatus.NEEDS_DECISION,
                (ExecutionAuthorizationSourceReason.TRUSTED_RECORD_MALFORMED,),
                expected_authorization_id=expected_authorization_id,
            )
        if record.authorized_invocation_id == expected_invocation_id:
            records.append(record)

    if not records:
        return _result(
            ExecutionAuthorizationSourceStatus.BLOCKED,
            (ExecutionAuthorizationSourceReason.AUTHORIZATION_MISSING,),
            expected_authorization_id=expected_authorization_id,
        )
    current = records[-1]
    if not current.evidence.execution_authorized:
        return _result(
            ExecutionAuthorizationSourceStatus.BLOCKED,
            (ExecutionAuthorizationSourceReason.AUTHORIZATION_REVOKED,),
            record=current,
            expected_authorization_id=expected_authorization_id,
        )
    start = _timestamp(current.evidence.authorized_at, "authorized_at")
    expires = _timestamp(current.evidence.expires_at, "expires_at")
    if evaluated < start:
        return _result(
            ExecutionAuthorizationSourceStatus.STALE,
            (ExecutionAuthorizationSourceReason.AUTHORIZATION_NOT_YET_ACTIVE,),
            record=current,
            expected_authorization_id=expected_authorization_id,
        )
    if evaluated >= expires:
        return _result(
            ExecutionAuthorizationSourceStatus.STALE,
            (ExecutionAuthorizationSourceReason.AUTHORIZATION_EXPIRED,),
            record=current,
            expected_authorization_id=expected_authorization_id,
        )
    if not all(
        (
            current.evidence.repository.casefold() == repository.casefold(),
            current.issue_number == issue_number,
            current.authorized_candidate_packet_id == expected_candidate_packet_id,
            current.authorized_invocation_id == expected_invocation_id,
            current.authorized_operation == expected_operation,
            current.evidence.request_fingerprint == expected_request_fingerprint,
            current.evidence.command_plan_id == expected_command_plan_id,
            current.evidence.expected_sha == expected_sha,
            current.authorizer_id.casefold() == snapshot.owner_login.casefold(),
        )
    ):
        return _result(
            ExecutionAuthorizationSourceStatus.STALE,
            (ExecutionAuthorizationSourceReason.BINDING_MISMATCH,),
            record=current,
            expected_authorization_id=expected_authorization_id,
        )
    if (
        expected_authorization_id is not None
        and current.evidence.authorization_id != expected_authorization_id
    ):
        return _result(
            ExecutionAuthorizationSourceStatus.STALE,
            (ExecutionAuthorizationSourceReason.AUTHORIZATION_SUPERSEDED,),
            record=current,
            expected_authorization_id=expected_authorization_id,
        )
    return _result(
        ExecutionAuthorizationSourceStatus.CURRENT,
        (ExecutionAuthorizationSourceReason.CURRENT,),
        record=current,
        expected_authorization_id=expected_authorization_id,
    )
