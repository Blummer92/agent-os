"""Trusted GitHub-conversation source for merge authorization (#2869).

The source is intentionally read-only. GitHub transport is injected; only exact
repository-owner-authored machine records from a complete PR conversation are
accepted. Applicability remains owned by merge_authorization.py.

Provenance boundary (S2, #3463/#3734): an owner login is not, by itself,
proof of an owner-performed decision. GitHub's raw issue-comment API exposes
``performed_via_github_app`` for comments performed through a GitHub App even
when the displayed author is the repository owner (verified live on PR #3734:
comments 6400749120 and 6400951989 display author Blummer92 with
``performed_via_github_app.slug == "chatgpt-codex-connector"``). This source
therefore rejects any trusted-marker comment that carries app-performance
evidence, and it rejects agent-attribution footers instead of stripping them:
a footer is in-band evidence of agent generation, and stripping it would
erase that evidence. Absence of app-performance evidence is still not
positive proof of a direct owner decision -- a comment posted with the
owner's own PAT/OAuth token by an agent is indistinguishable in the GitHub
API from a comment the owner typed -- so a current record from this source
is necessary but not sufficient for merge execution. Execution additionally
requires a separately granted owner decision through a channel that
attests human origin (the runtime approval card); this module grants none.
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


def github_comment_snapshot(comment: object) -> "MergeAuthorizationCommentSnapshot":
    """Build one source snapshot from a GitHub issue-comment object.

    This is the single extraction point shared by both production comment
    readers (merge admission and merge dispatch), so app-performance
    evidence cannot drift between readers. ``performed_via_github_app``
    is read through PyGithub's ``IssueComment.performed_via_github_app``
    (PyGithub 2.10); a comment object without that attribute is treated
    as carrying no app-performance evidence, which is the conservative
    reading for test fakes only -- production PyGithub objects always
    carry the field. An app object without a usable slug still counts
    as app-performance evidence.
    """
    app = getattr(comment, "performed_via_github_app", None)
    slug: str | None = None
    if app is not None:
        raw_slug = getattr(app, "slug", None)
        slug = raw_slug if isinstance(raw_slug, str) and raw_slug else "app-performed"
    created_at = getattr(comment, "created_at")
    if hasattr(created_at, "strftime"):
        created_text = created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        created_text = str(created_at)
    return MergeAuthorizationCommentSnapshot(
        comment_id=comment.id,  # type: ignore[attr-defined]
        author_login=comment.user.login,  # type: ignore[attr-defined]
        created_at=created_text,
        body=getattr(comment, "body", None) or "",
        performed_via_github_app_slug=slug,
    )


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
    # GitHub App slug that performed this comment, or None when the
    # comment carries no app-performance evidence. Any non-None value
    # disqualifies a trusted-marker comment (see reacquire below).
    performed_via_github_app_slug: str | None = None


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
            if item.performed_via_github_app_slug is not None:
                # S2: performed through a GitHub App even though the
                # displayed author is the owner. This is agent
                # performance evidence, not a direct owner decision.
                return MergeAuthorizationSourceResult(
                    MergeAuthorizationSourceStatus.NEEDS_DECISION,
                    ("source.app-performed-record",), (), tuple(source_ids),
                )
            # No footer canonicalization: a trusted record is exactly
            # marker + one payload line. An agent-attribution footer
            # (e.g. Claude Code) makes the payload multi-line and
            # therefore malformed here, by design -- stripping it
            # would erase the only in-band agent-generation evidence.
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

    # The latest revision alone is not proof of current authorization.
    # Require a complete, identity-linked history before accepting a decision.
    by_id: dict[str, list[MergeAuthorizationRecord]] = {}
    for record in records:
        by_id.setdefault(record.authorization_id, []).append(record)
    allowed_next = {
        MergeAuthorizationState.PENDING: {
            MergeAuthorizationState.AUTHORIZED, MergeAuthorizationState.REJECTED,
            MergeAuthorizationState.EXPIRED, MergeAuthorizationState.INVALIDATED,
            MergeAuthorizationState.SUPERSEDED,
        },
        MergeAuthorizationState.AUTHORIZED: {
            MergeAuthorizationState.EXPIRED, MergeAuthorizationState.INVALIDATED,
            MergeAuthorizationState.CONSUMED, MergeAuthorizationState.SUPERSEDED,
        },
    }
    current: list[MergeAuthorizationRecord] = []
    for revisions in by_id.values():
        revisions.sort(key=lambda item: item.revision_number)
        for index, record in enumerate(revisions):
            if index and record.revision_number == revisions[index - 1].revision_number:
                return MergeAuthorizationSourceResult(
                    MergeAuthorizationSourceStatus.NEEDS_DECISION,
                    ("authorization.conflicting-revision",), (), tuple(source_ids),
                )
            if record.revision_number != index + 1:
                return MergeAuthorizationSourceResult(
                    MergeAuthorizationSourceStatus.NEEDS_DECISION,
                    ("authorization.chain-invalid",), (), tuple(source_ids),
                )
            if index == 0:
                if record.state is not MergeAuthorizationState.PENDING or record.previous_revision is not None:
                    return MergeAuthorizationSourceResult(
                        MergeAuthorizationSourceStatus.NEEDS_DECISION,
                        ("authorization.chain-invalid",), (), tuple(source_ids),
                    )
            else:
                prior = revisions[index - 1]
                if (
                    record.previous_revision != prior.authorization_revision
                    or record.state not in allowed_next.get(prior.state, set())
                    or record.binding != prior.binding
                    or record.expires_at != prior.expires_at
                    or record.decision_at < prior.decision_at
                ):
                    return MergeAuthorizationSourceResult(
                        MergeAuthorizationSourceStatus.NEEDS_DECISION,
                        ("authorization.chain-invalid",), (), tuple(source_ids),
                    )
        if revisions[-1].state is MergeAuthorizationState.AUTHORIZED:
            current.append(revisions[-1])
    current = tuple(current)
    if not current:
        return MergeAuthorizationSourceResult(
            MergeAuthorizationSourceStatus.STALE,
            ("authorization.consumed-or-not-current",), (), tuple(source_ids),
        )
    return MergeAuthorizationSourceResult(
        MergeAuthorizationSourceStatus.CURRENT,
        ("current",), current, tuple(source_ids),
    )
