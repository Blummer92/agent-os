"""ADR-001 merge-proposal evidence type (``merge-proposal/v1``) (#2340/#3463).

A ``MergeProposal`` is the typed, content-bound evidence that lets the
canonical merge-authorization evaluator be honestly invoked for merge
dispatch. It is deliberately NOT a task-planning proposal: it carries no
issueplan, planning graph, or cohort state, because a merge decision binds
a repository, a pull request, an exact head/base/body, a file scope, a merge
method, and an approval triple — not a planning handoff.

This module performs no retrieval, publication, merge, issue mutation, or
external I/O, and it confers no authority by itself:

- It is pure evidence. A proposal is only meaningful when it is assembled
  from already-trusted, independently reacquired records (see
  ``merge_authorization.build_merge_proposal``) and then checked by
  ``evaluate_merge_authorization_applicability`` against live PR evidence
  and an AUTHORIZED authorization record. A matching proposal alone never
  produces ``merge_authorized=true``.
- It posts nothing. How an owner decision becomes a trusted approval /
  authorization comment on a PR conversation (the authenticated producer
  posting path) is a separate owner decision (Phase 4 decision (e)) and is
  NOT implemented here. Nothing in this module hand-crafts, posts, or
  endorses a GitHub comment.
- It dispatches nothing. No merge API is called from this module or from
  any consumer of it; dispatch remains a separately authorized step that
  must re-verify a positive applicable receipt immediately before mutation
  with ``expected_head_sha`` and record a consumption observation after.

The proposal identity is content-derived: ``proposal_id`` is
``merge-proposal:<sha256>`` over every other field, so any tampering with
a bound field invalidates the identity instead of silently changing the
proposal.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, Literal

MERGE_PROPOSAL_SCHEMA_VERSION = "merge-proposal/v1"

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_PROPOSAL_ID_RE = re.compile(r"^merge-proposal:[0-9a-f]{64}$")
_APPROVAL_ID_RE = re.compile(r"^approval:[0-9a-f]{64}$")
_APPROVAL_REVISION_RE = re.compile(r"^approval-revision:[0-9a-f]{64}$")
_APPLICABILITY_ID_RE = re.compile(r"^approval-applicability:[0-9a-f]{64}$")
_PROJECTION_ID_RE = re.compile(r"^approved-execution-projection:[0-9a-f]{64}$")
_EVIDENCE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}:[0-9a-f]{64}$")
_REPOSITORY_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_MAX_ITEMS = 256
_MAX_TEXT_BYTES = 4096

_CHECK_STATES = frozenset(
    {
        "success",
        "failure",
        "pending",
        "cancelled",
        "skipped",
        "not-triggered",
        "unknown",
    }
)
_MERGE_METHODS = frozenset({"merge", "squash", "rebase"})


@dataclass(frozen=True, slots=True)
class MergeProposal:
    """Typed merge evidence bound to one PR, head, scope, and approval triple.

    ``required_checks`` entries are plain ``(context, app_identity,
    tested_sha, state)`` tuples. They are kept as plain data (rather than
    ``MergeCheckEvidence`` objects) so this module has no import dependency
    on the merge-authorization module that consumes it; the consumer
    converts them to canonical check evidence before comparing.
    """

    schema_version: str
    proposal_id: str
    repository: str
    pull_request_number: int
    exact_head_sha: str
    target_base_branch: str
    base_sha_or_evidence_id: str
    permitted_merge_method: str
    changed_scope_fingerprint: str
    allowed_files: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_tests: tuple[str, ...]
    required_checks: tuple[tuple[str, str, str, str], ...]
    blocking_review_present: bool
    unresolved_conversation_count: int
    exact_head_reviewed: bool
    pr_metadata_sha256: str
    closure_admission_ids: tuple[str, ...]
    draft_ready_state: Literal["draft", "ready"]
    approval_id: str
    approval_revision: str
    approval_applicability_identity: str
    approval_expires_at: str | None
    approved_execution_projection_id: str

    def __post_init__(self) -> None:
        if self.schema_version != MERGE_PROPOSAL_SCHEMA_VERSION:
            raise ValueError("unsupported merge-proposal schema version")
        _repository(self.repository)
        _positive_int(self.pull_request_number, "pull_request_number")
        _sha40(self.exact_head_sha, "exact_head_sha")
        _text(self.target_base_branch, "target_base_branch")
        _base_identity(self.base_sha_or_evidence_id)
        if self.permitted_merge_method not in _MERGE_METHODS:
            raise ValueError("unsupported permitted_merge_method")
        _sha256(self.changed_scope_fingerprint, "changed_scope_fingerprint")
        object.__setattr__(
            self, "allowed_files", _strings(self.allowed_files, "allowed_files")
        )
        object.__setattr__(
            self,
            "forbidden_paths",
            _strings(self.forbidden_paths, "forbidden_paths"),
        )
        object.__setattr__(
            self, "required_tests", _strings(self.required_tests, "required_tests")
        )
        object.__setattr__(
            self, "required_checks", _checks(self.required_checks)
        )
        if not isinstance(self.blocking_review_present, bool) or not isinstance(
            self.exact_head_reviewed, bool
        ):
            raise TypeError("review evidence flags must be bool")
        if (
            not isinstance(self.unresolved_conversation_count, int)
            or isinstance(self.unresolved_conversation_count, bool)
            or self.unresolved_conversation_count < 0
            or self.unresolved_conversation_count > _MAX_ITEMS
        ):
            raise ValueError("unresolved_conversation_count is out of bounds")
        _sha256(self.pr_metadata_sha256, "pr_metadata_sha256")
        object.__setattr__(
            self,
            "closure_admission_ids",
            _evidence_ids(self.closure_admission_ids),
        )
        if self.draft_ready_state not in {"draft", "ready"}:
            raise ValueError("draft_ready_state is unsupported")
        _matches(self.approval_id, _APPROVAL_ID_RE, "approval_id")
        _matches(self.approval_revision, _APPROVAL_REVISION_RE, "approval_revision")
        _matches(
            self.approval_applicability_identity,
            _APPLICABILITY_ID_RE,
            "approval_applicability_identity",
        )
        _optional_timestamp(self.approval_expires_at, "approval_expires_at")
        _matches(
            self.approved_execution_projection_id,
            _PROJECTION_ID_RE,
            "approved_execution_projection_id",
        )
        expected = _proposal_id(self)
        if self.proposal_id and self.proposal_id != expected:
            raise ValueError("proposal_id does not match merge-proposal content")
        object.__setattr__(self, "proposal_id", expected)


def _proposal_id(proposal: MergeProposal) -> str:
    payload = {
        item.name: getattr(proposal, item.name)
        for item in fields(proposal)
        if item.init and item.name != "proposal_id"
    }
    digest = hashlib.sha256(
        b"agent-os-merge-proposal:v1\0" + _canonical_bytes(payload)
    ).hexdigest()
    return f"merge-proposal:{digest}"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _checks(
    value: Any,
) -> tuple[tuple[str, str, str, str], ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError("required checks must be an iterable of check tuples")
    items: list[tuple[str, str, str, str]] = []
    for item in value:
        if not isinstance(item, (tuple, list)) or len(item) != 4:
            raise ValueError("required check must be a 4-tuple")
        context, app_identity, tested_sha, state = item
        _text(context, "check context")
        _text(app_identity, "check app_identity")
        _sha40(tested_sha, "check tested_sha")
        if state not in _CHECK_STATES:
            raise ValueError("unsupported merge-check state")
        items.append((context, app_identity, tested_sha, state))
    if not items or len(items) > _MAX_ITEMS:
        raise ValueError("required checks must be non-empty and bounded")
    identities = tuple((item[0], item[1]) for item in items)
    if len(set(identities)) != len(identities):
        raise ValueError("required check identities must be unique")
    return tuple(sorted(items))


def _strings(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of strings")
    items = tuple(value)
    if len(items) > _MAX_ITEMS:
        raise ValueError(f"{name} exceeds bounded item count")
    for item in items:
        _text(item, name)
    if len(set(items)) != len(items):
        raise ValueError(f"{name} contains duplicate values")
    return tuple(sorted(items))


def _evidence_ids(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError("closure_admission_ids must be an iterable of text")
    items = tuple(
        _matches(item, _EVIDENCE_ID_RE, "closure_admission_ids") for item in value
    )
    if len(items) > _MAX_ITEMS:
        raise ValueError("closure_admission_ids exceeds bounded item count")
    if len(set(items)) != len(items):
        raise ValueError("closure_admission_ids contains duplicate admissions")
    return tuple(sorted(items))


def _repository(value: str) -> str:
    text = _text(value, "repository")
    if text.count("/") != 1:
        raise ValueError("repository must use owner/name form")
    owner, name = text.split("/", 1)
    if not _REPOSITORY_SEGMENT_RE.fullmatch(owner) or not _REPOSITORY_SEGMENT_RE.fullmatch(
        name
    ):
        raise ValueError("repository must use canonical owner/name segments")
    if owner in {".", ".."} or name in {".", ".."}:
        raise ValueError("repository must use canonical owner/name segments")
    return text


def _base_identity(value: Any) -> str:
    text = _text(value, "base_sha_or_evidence_id")
    if _SHA40_RE.fullmatch(text) or _EVIDENCE_ID_RE.fullmatch(text):
        return text
    raise ValueError("base identity must be a full SHA or canonical evidence identity")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{name} must be non-empty NUL-free text")
    if not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be canonical non-whitespace text")
    if len(value.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ValueError(f"{name} exceeds bounded byte length")
    return value


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _sha40(value: Any, name: str) -> str:
    text = _text(value, name)
    if not _SHA40_RE.fullmatch(text):
        raise ValueError(f"{name} must be a full lowercase SHA")
    return text


def _sha256(value: Any, name: str) -> str:
    text = _text(value, name)
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{name} must be lowercase SHA-256 text")
    return text


def _matches(value: Any, pattern: re.Pattern[str], name: str) -> str:
    text = _text(value, name)
    if not pattern.fullmatch(text):
        raise ValueError(f"{name} is malformed")
    return text


def _timestamp(value: Any, name: str) -> datetime:
    text = _text(value, name)
    if not _TIMESTAMP_RE.fullmatch(text):
        raise ValueError(f"{name} must use canonical UTC timestamp format")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{name} is not a valid timestamp") from exc


def _optional_timestamp(value: Any, name: str) -> datetime | None:
    return None if value is None else _timestamp(value, name)
