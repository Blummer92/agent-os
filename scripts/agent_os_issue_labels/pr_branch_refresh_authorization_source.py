"""GitHub-conversation source for immutable PR refresh authorization evidence (#1403).

This module follows the canonical #1226 authorization-source pattern.  It parses
only exact repository-owner-authored machine records from a complete injected
GitHub conversation snapshot.  It performs no GitHub I/O, mutation, credential
handling, refresh execution, or authorization consumption.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol, runtime_checkable

from .pr_branch_refresh_authorization import RefreshAuthorization, RefreshAuthorizationState

AUTHORIZATION_MARKER = "agent-os-pr-refresh-authorization/v1"
RECEIPT_MARKER = "agent-os-pr-refresh-authorization-receipt/v1"
SOURCE_SCHEMA_VERSION = "1.0"
MAX_COMMENTS = 512
MAX_COMMENT_BYTES = 32 * 1024
MAX_TOTAL_COMMENT_BYTES = 256 * 1024
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_IDENTITY_SEPARATOR = "\0"


class RefreshAuthorizationSourceStatus(str, Enum):
    CURRENT = "current"
    BLOCKED = "blocked"
    STALE = "stale"
    NEEDS_DECISION = "needs-decision"


@dataclass(frozen=True, slots=True)
class RefreshAuthorizationCommentSnapshot:
    comment_id: int
    author_login: str
    created_at: str
    body: str

    def __post_init__(self) -> None:
        if type(self.comment_id) is not int or self.comment_id < 1:
            raise ValueError("comment_id must be positive")
        if not isinstance(self.author_login, str) or not self.author_login.strip():
            raise ValueError("author_login is required")
        if not isinstance(self.created_at, str) or not self.created_at.strip():
            raise ValueError("created_at is required")
        if not isinstance(self.body, str) or len(self.body.encode("utf-8")) > MAX_COMMENT_BYTES:
            raise ValueError("comment body is outside bounds")


@dataclass(frozen=True, slots=True)
class RefreshAuthorizationSourceSnapshot:
    repository: str
    pr_number: int
    owner_login: str
    owner_type: str
    comments_complete: bool
    comments: tuple[RefreshAuthorizationCommentSnapshot, ...]

    def __post_init__(self) -> None:
        if not _REPOSITORY.fullmatch(self.repository):
            raise ValueError("repository must use owner/name")
        if type(self.pr_number) is not int or self.pr_number < 1:
            raise ValueError("pr_number must be positive")
        if not self.owner_login.strip():
            raise ValueError("owner_login is required")
        if type(self.comments_complete) is not bool:
            raise TypeError("comments_complete must be bool")
        if type(self.comments) is not tuple or len(self.comments) > MAX_COMMENTS:
            raise ValueError("comments must be a bounded tuple")
        if sum(len(item.body.encode("utf-8")) for item in self.comments) > MAX_TOTAL_COMMENT_BYTES:
            raise ValueError("comment snapshot exceeds total bound")


@runtime_checkable
class RefreshAuthorizationSourceTransport(Protocol):
    def read_refresh_authorization_source(
        self, repository: str, pr_number: int
    ) -> RefreshAuthorizationSourceSnapshot: ...


@dataclass(frozen=True, slots=True)
class RefreshAuthorizationReceipt:
    schema_version: str
    repository: str
    pr_number: int
    authorization_id: str
    admitted_head_sha: str
    admitted_main_sha: str
    mutation_attempted: bool
    mutation_succeeded: bool
    terminal_status: str
    reason_codes: tuple[str, ...]
    receipt_id: str = ""
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != SOURCE_SCHEMA_VERSION:
            raise ValueError("unsupported receipt schema")
        if not _REPOSITORY.fullmatch(self.repository):
            raise ValueError("repository must use owner/name")
        if type(self.pr_number) is not int or self.pr_number < 1:
            raise ValueError("pr_number must be positive")
        if not self.authorization_id.startswith("refresh-authorization:"):
            raise ValueError("authorization_id is malformed")
        if not _SHA40.fullmatch(self.admitted_head_sha) or not _SHA40.fullmatch(self.admitted_main_sha):
            raise ValueError("receipt SHAs must be lowercase 40-hex")
        if type(self.mutation_attempted) is not bool or type(self.mutation_succeeded) is not bool:
            raise TypeError("mutation flags must be bool")
        if self.mutation_succeeded and not self.mutation_attempted:
            raise ValueError("successful mutation requires attempted mutation")
        if not self.terminal_status.strip():
            raise ValueError("terminal_status is required")
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("reason_codes must be sorted and unique")
        expected = _identity("refresh-authorization-receipt", self._identity_payload())
        if self.receipt_id and self.receipt_id != expected:
            raise ValueError("receipt_id does not match content")
        object.__setattr__(self, "receipt_id", expected)

    @property
    def consumes_authorization(self) -> bool:
        return self.mutation_attempted

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "repository": self.repository,
            "pr_number": self.pr_number,
            "authorization_id": self.authorization_id,
            "admitted_head_sha": self.admitted_head_sha,
            "admitted_main_sha": self.admitted_main_sha,
            "mutation_attempted": self.mutation_attempted,
            "mutation_succeeded": self.mutation_succeeded,
            "terminal_status": self.terminal_status,
            "reason_codes": list(self.reason_codes),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_payload(), "receipt_id": self.receipt_id}


@dataclass(frozen=True, slots=True)
class RefreshAuthorizationSourceResult:
    status: RefreshAuthorizationSourceStatus
    reason_codes: tuple[str, ...]
    records: tuple[RefreshAuthorization, ...]
    receipts: tuple[RefreshAuthorizationReceipt, ...]
    source_comment_ids: tuple[int, ...]
    side_effects_performed: Literal[False] = field(default=False, init=False)


def _canonical(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _identity_digest_material(prefix: str, payload: object) -> str:
    return prefix + ":v1" + _IDENTITY_SEPARATOR + _canonical(payload)


def _identity(prefix: str, payload: object) -> str:
    digest = hashlib.sha256(_identity_digest_material(prefix, payload).encode()).hexdigest()
    return f"{prefix}:{digest}"


def serialize_refresh_authorization_comment(authorization: RefreshAuthorization) -> str:
    if type(authorization) is not RefreshAuthorization:
        raise TypeError("authorization must be exact RefreshAuthorization")
    return AUTHORIZATION_MARKER + "\n" + _canonical(authorization.to_dict())


def serialize_refresh_authorization_receipt(receipt: RefreshAuthorizationReceipt) -> str:
    if type(receipt) is not RefreshAuthorizationReceipt:
        raise TypeError("receipt must be exact RefreshAuthorizationReceipt")
    return RECEIPT_MARKER + "\n" + _canonical(receipt.to_dict())


def _two_line_payload(body: str, marker: str) -> dict[str, object] | None:
    prefix = marker + "\n"
    if not body.startswith(prefix):
        return None
    if body.count("\n") != 1:
        raise ValueError("trusted marker must contain exactly two lines")
    serialized = body[len(prefix):]
    payload = json.loads(serialized)
    if type(payload) is not dict or _canonical(payload) != serialized:
        raise ValueError("trusted payload must be canonical compact JSON")
    return payload


def _authorization(payload: dict[str, object]) -> RefreshAuthorization:
    expected = {
        "schema_version", "repository", "pr_number", "base_branch",
        "expected_head_sha", "expected_main_sha", "allowed_changed_paths",
        "forbidden_paths", "required_validation_command_ids",
        "branch_refresh_authorized", "label_write_authorized",
        "owner_decision_reference", "state", "authorization_id",
        "side_effects_performed",
    }
    if set(payload) != expected or payload["side_effects_performed"] is not False:
        raise ValueError("authorization payload fields are invalid")
    return RefreshAuthorization(
        schema_version=payload["schema_version"], repository=payload["repository"],
        pr_number=payload["pr_number"], base_branch=payload["base_branch"],
        expected_head_sha=payload["expected_head_sha"], expected_main_sha=payload["expected_main_sha"],
        allowed_changed_paths=tuple(payload["allowed_changed_paths"]), forbidden_paths=tuple(payload["forbidden_paths"]),
        required_validation_command_ids=tuple(payload["required_validation_command_ids"]),
        branch_refresh_authorized=payload["branch_refresh_authorized"], label_write_authorized=payload["label_write_authorized"],
        owner_decision_reference=payload["owner_decision_reference"], state=RefreshAuthorizationState(payload["state"]),
        authorization_id=payload["authorization_id"],
    )


def _receipt(payload: dict[str, object]) -> RefreshAuthorizationReceipt:
    expected = {
        "schema_version", "repository", "pr_number", "authorization_id",
        "admitted_head_sha", "admitted_main_sha", "mutation_attempted",
        "mutation_succeeded", "terminal_status", "reason_codes", "receipt_id",
    }
    if set(payload) != expected:
        raise ValueError("receipt payload fields are invalid")
    return RefreshAuthorizationReceipt(
        schema_version=payload["schema_version"], repository=payload["repository"],
        pr_number=payload["pr_number"], authorization_id=payload["authorization_id"],
        admitted_head_sha=payload["admitted_head_sha"], admitted_main_sha=payload["admitted_main_sha"],
        mutation_attempted=payload["mutation_attempted"], mutation_succeeded=payload["mutation_succeeded"],
        terminal_status=payload["terminal_status"], reason_codes=tuple(payload["reason_codes"]),
        receipt_id=payload["receipt_id"],
    )


def reacquire_refresh_authorization_source(
    *, transport: RefreshAuthorizationSourceTransport, repository: str,
    pr_number: int, expected_authorization_id: str | None = None,
) -> RefreshAuthorizationSourceResult:
    """Read one complete trusted PR conversation and return bounded immutable history.

    This source owns provenance, parsing, deduplication, and consumption history.
    It deliberately does not decide which unconsumed authorized record matches the
    current head/main/scope; #1403's current-evidence resolver owns that decision.
    """
    if not isinstance(transport, RefreshAuthorizationSourceTransport):
        raise TypeError("transport does not satisfy RefreshAuthorizationSourceTransport")
    try:
        snapshot = transport.read_refresh_authorization_source(repository, pr_number)
    except Exception:
        return RefreshAuthorizationSourceResult(RefreshAuthorizationSourceStatus.NEEDS_DECISION, ("source.unavailable",), (), (), ())
    if type(snapshot) is not RefreshAuthorizationSourceSnapshot:
        return RefreshAuthorizationSourceResult(RefreshAuthorizationSourceStatus.NEEDS_DECISION, ("source.unavailable",), (), (), ())
    if snapshot.repository.casefold() != repository.casefold() or snapshot.pr_number != pr_number:
        return RefreshAuthorizationSourceResult(RefreshAuthorizationSourceStatus.NEEDS_DECISION, ("source.identity-mismatch",), (), (), ())
    if snapshot.owner_type != "User" or not snapshot.comments_complete:
        reason = "source.owner-unsupported" if snapshot.owner_type != "User" else "source.incomplete"
        return RefreshAuthorizationSourceResult(RefreshAuthorizationSourceStatus.NEEDS_DECISION, (reason,), (), (), ())
    ids = [item.comment_id for item in snapshot.comments]
    if len(ids) != len(set(ids)):
        return RefreshAuthorizationSourceResult(RefreshAuthorizationSourceStatus.NEEDS_DECISION, ("source.ambiguous",), (), (), ())

    records: list[RefreshAuthorization] = []
    receipts: list[RefreshAuthorizationReceipt] = []
    source_ids: list[int] = []
    try:
        for comment in sorted(snapshot.comments, key=lambda item: (item.created_at, item.comment_id)):
            if comment.author_login.casefold() != snapshot.owner_login.casefold():
                continue
            payload = _two_line_payload(comment.body, AUTHORIZATION_MARKER)
            if payload is not None:
                record = _authorization(payload)
                if record.repository.casefold() != repository.casefold() or record.pr_number != pr_number:
                    raise ValueError("trusted authorization binding mismatch")
                records.append(record); source_ids.append(comment.comment_id); continue
            payload = _two_line_payload(comment.body, RECEIPT_MARKER)
            if payload is not None:
                receipt = _receipt(payload)
                if receipt.repository.casefold() != repository.casefold() or receipt.pr_number != pr_number:
                    raise ValueError("trusted receipt binding mismatch")
                receipts.append(receipt); source_ids.append(comment.comment_id)
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return RefreshAuthorizationSourceResult(RefreshAuthorizationSourceStatus.NEEDS_DECISION, ("source.trusted-record-malformed",), (), (), ())

    by_id: dict[str, RefreshAuthorization] = {}
    for record in records:
        prior = by_id.get(record.authorization_id)
        if prior is not None and prior.to_dict() != record.to_dict():
            return RefreshAuthorizationSourceResult(RefreshAuthorizationSourceStatus.NEEDS_DECISION, ("authorization.conflicting-identity",), (), tuple(receipts), tuple(source_ids))
        by_id[record.authorization_id] = record
    unique_records = tuple(by_id.values())
    if expected_authorization_id is not None:
        unique_records = tuple(item for item in unique_records if item.authorization_id == expected_authorization_id)
    if not unique_records:
        return RefreshAuthorizationSourceResult(RefreshAuthorizationSourceStatus.BLOCKED, ("authorization.absent",), (), tuple(receipts), tuple(source_ids))

    consumed = {item.authorization_id for item in receipts if item.consumes_authorization}
    available = tuple(
        item for item in unique_records
        if item.state is RefreshAuthorizationState.AUTHORIZED and item.authorization_id not in consumed
    )
    if not available:
        return RefreshAuthorizationSourceResult(
            RefreshAuthorizationSourceStatus.STALE,
            ("authorization.consumed-or-not-current",),
            (), tuple(receipts), tuple(source_ids),
        )
    return RefreshAuthorizationSourceResult(
        RefreshAuthorizationSourceStatus.CURRENT,
        ("current",),
        available, tuple(receipts), tuple(source_ids),
    )
