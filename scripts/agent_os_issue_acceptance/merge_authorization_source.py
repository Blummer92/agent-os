"""Trusted GitHub-conversation source for merge authorization (#2869).

The source is intentionally read-only. GitHub transport is injected; only exact
repository-owner-authored machine records from a complete PR conversation are
accepted. Applicability remains owned by merge_authorization.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol, runtime_checkable

from .merge_authorization import (
    MergeAuthorizationRecord,
    MergeAuthorizationState,
    reconstruct_merge_authorization_record,
    serialize_merge_authorization_record,
)

AUTHORIZATION_MARKER = "agent-os-merge-authorization/v1"
MAX_COMMENTS = 512
MAX_COMMENT_BYTES = 32 * 1024
MAX_TOTAL_COMMENT_BYTES = 256 * 1024


class MergeAuthorizationSourceStatus(str, Enum):
    CURRENT = "current"
    BLOCKED = "blocked"
    STALE = "stale"
    NEEDS_DECISION = "needs-decision"


@dataclass(frozen=True, slots=True)
class MergeAuthorizationCommentSnapshot:
    comment_id: int
    author_login: str
    created_at: str
    body: str


@dataclass(frozen=True, slots=True)
class MergeAuthorizationSourceSnapshot:
    repository: str
    pr_number: int
    owner_login: str
    owner_type: str
    comments_complete: bool
    comments: tuple[MergeAuthorizationCommentSnapshot, ...]


@runtime_checkable
class MergeAuthorizationSourceTransport(Protocol):
    def read_merge_authorization_source(
        self, repository: str, pr_number: int
    ) -> MergeAuthorizationSourceSnapshot: ...


@dataclass(frozen=True, slots=True)
class MergeAuthorizationSourceResult:
    status: MergeAuthorizationSourceStatus
    reason_codes: tuple[str, ...]
    records: tuple[MergeAuthorizationRecord, ...]
    source_comment_ids: tuple[int, ...]
    side_effects_performed: Literal[False] = field(default=False, init=False)


def serialize_merge_authorization_comment(record: MergeAuthorizationRecord) -> str:
    payload = serialize_merge_authorization_record(record).decode("utf-8").rstrip("\n")
    return AUTHORIZATION_MARKER + "\n" + payload


def reacquire_merge_authorization_source(
    *,
    transport: MergeAuthorizationSourceTransport,
    repository: str,
    pr_number: int,
    expected_authorization_id: str | None = None,
) -> MergeAuthorizationSourceResult:
    if not isinstance(transport, MergeAuthorizationSourceTransport):
        raise TypeError("transport does not satisfy MergeAuthorizationSourceTransport")
    try:
        snapshot = transport.read_merge_authorization_source(repository, pr_number)
    except Exception:
        return MergeAuthorizationSourceResult(
            MergeAuthorizationSourceStatus.NEEDS_DECISION,
            ("source.unavailable",), (), (),
        )
    if (
        type(snapshot) is not MergeAuthorizationSourceSnapshot
        or snapshot.repository.casefold() != repository.casefold()
        or snapshot.pr_number != pr_number
    ):
        return MergeAuthorizationSourceResult(
            MergeAuthorizationSourceStatus.NEEDS_DECISION,
            ("source.identity-mismatch",), (), (),
        )
    if snapshot.owner_type != "User" or not snapshot.comments_complete:
        reason = "source.owner-unsupported" if snapshot.owner_type != "User" else "source.incomplete"
        return MergeAuthorizationSourceResult(
            MergeAuthorizationSourceStatus.NEEDS_DECISION, (reason,), (), (),
        )
    if len(snapshot.comments) > MAX_COMMENTS or sum(
        len(item.body.encode("utf-8")) for item in snapshot.comments
    ) > MAX_TOTAL_COMMENT_BYTES:
        return MergeAuthorizationSourceResult(
            MergeAuthorizationSourceStatus.NEEDS_DECISION,
            ("source.outside-bounds",), (), (),
        )
    ids = [item.comment_id for item in snapshot.comments]
    if len(ids) != len(set(ids)):
        return MergeAuthorizationSourceResult(
            MergeAuthorizationSourceStatus.NEEDS_DECISION,
            ("source.ambiguous",), (), (),
        )

    records: list[MergeAuthorizationRecord] = []
    source_ids: list[int] = []
    try:
        for item in sorted(snapshot.comments, key=lambda value: (value.created_at, value.comment_id)):
            if (
                item.author_login.casefold() != snapshot.owner_login.casefold()
                or not item.body.startswith(AUTHORIZATION_MARKER + "\n")
            ):
                continue
            if len(item.body.encode("utf-8")) > MAX_COMMENT_BYTES:
                raise ValueError("trusted comment exceeds bounds")
            payload = item.body[len(AUTHORIZATION_MARKER) + 1 :]
            if "\n" in payload:
                raise ValueError("trusted authorization must contain exactly two lines")
            record = reconstruct_merge_authorization_record(payload)
            if (
                record.binding.repository.casefold() != repository.casefold()
                or record.binding.pull_request_number != pr_number
            ):
                raise ValueError("trusted authorization binding mismatch")
            records.append(record)
            source_ids.append(item.comment_id)
    except (TypeError, ValueError):
        return MergeAuthorizationSourceResult(
            MergeAuthorizationSourceStatus.NEEDS_DECISION,
            ("source.trusted-record-malformed",), (), (),
        )

    if expected_authorization_id is not None:
        records = [item for item in records if item.authorization_id == expected_authorization_id]
    if not records:
        return MergeAuthorizationSourceResult(
            MergeAuthorizationSourceStatus.BLOCKED,
            ("authorization.absent",), (), tuple(source_ids),
        )

    by_id: dict[str, MergeAuthorizationRecord] = {}
    for record in records:
        prior = by_id.get(record.authorization_id)
        if prior is None or record.revision_number > prior.revision_number:
            by_id[record.authorization_id] = record
        elif record.revision_number == prior.revision_number and record != prior:
            return MergeAuthorizationSourceResult(
                MergeAuthorizationSourceStatus.NEEDS_DECISION,
                ("authorization.conflicting-revision",), (), tuple(source_ids),
            )

    current = tuple(
        record for record in by_id.values()
        if record.state is MergeAuthorizationState.AUTHORIZED
    )
    if not current:
        return MergeAuthorizationSourceResult(
            MergeAuthorizationSourceStatus.STALE,
            ("authorization.consumed-or-not-current",), (), tuple(source_ids),
        )
    return MergeAuthorizationSourceResult(
        MergeAuthorizationSourceStatus.CURRENT,
        ("current",), current, tuple(source_ids),
    )
