"""Normalize immutable caller-supplied PR and review-thread evidence."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Any

from .models import (
    AUTHORITY_FIELDS,
    EvidenceValidationError,
    NormalizedPRSnapshot,
    NormalizedReviewThread,
)

MAX_STRING_LENGTH = 10_000
MAX_BODY_LENGTH = 100_000
MAX_CHANGED_FILES = 5_000
MAX_THREADS = 5_000

_PR_FIELDS = {
    "repository",
    "pr_number",
    "base_branch",
    "base_sha",
    "head_branch",
    "head_sha",
    "state",
    "merged",
    "draft",
    "changed_files",
    "captured_at",
    "source_revision",
    *AUTHORITY_FIELDS,
}
_THREAD_FIELDS = {
    "thread_id",
    "top_level_comment_id",
    "reviewer",
    "body",
    "path",
    "line",
    "original_line",
    "side",
    "start_line",
    "start_side",
    "resolved",
    "outdated",
    "superseded",
    "created_at",
    "updated_at",
    "reply_ids",
    "supersession_evidence",
    *AUTHORITY_FIELDS,
}


def _exact(value: Any, expected: type, field: str) -> None:
    if type(value) is not expected:
        raise EvidenceValidationError(f"{field} must be exactly {expected.__name__}")


def _string(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    _exact(value, str, field)
    if not value or len(value) > MAX_STRING_LENGTH:
        raise EvidenceValidationError(f"{field} must be non-empty and within size limits")
    return value


def _sha(value: Any, field: str, *, optional: bool = False) -> str | None:
    text = _string(value, field, optional=optional)
    if text is None:
        return None
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text.lower()):
        raise EvidenceValidationError(f"{field} must be a 40-character hexadecimal SHA")
    return text.lower()


def _timestamp(value: Any, field: str, *, optional: bool = True) -> str | None:
    text = _string(value, field, optional=optional)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceValidationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceValidationError(f"{field} must include a timezone")
    return text


def _optional_positive_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    _exact(value, int, field)
    if value <= 0:
        raise EvidenceValidationError(f"{field} must be positive")
    return value


def _bool(payload: dict[str, Any], field: str, *, default: bool | None = None) -> bool:
    value = payload.get(field, default)
    if value is None:
        raise EvidenceValidationError(f"{field} is required")
    _exact(value, bool, field)
    return value


def _authority_false(payload: dict[str, Any]) -> dict[str, bool]:
    values: dict[str, bool] = {}
    for field in AUTHORITY_FIELDS:
        value = payload.get(field, False)
        _exact(value, bool, field)
        if value:
            raise EvidenceValidationError(f"{field} must remain false")
        values[field] = False
    return values


def _reject_unknown(payload: Any, allowed: set[str], label: str) -> dict[str, Any]:
    _exact(payload, dict, label)
    if any(type(key) is not str for key in payload):
        raise EvidenceValidationError(f"{label} keys must be strings")
    unknown = set(payload) - allowed
    if unknown:
        raise EvidenceValidationError(f"unknown {label} fields: {', '.join(sorted(unknown))}")
    return payload


def _string_sequence(value: Any, field: str, *, max_items: int) -> tuple[str, ...]:
    _exact(value, list, field)
    if len(value) > max_items:
        raise EvidenceValidationError(f"{field} exceeds size limit")
    result: list[str] = []
    for index, item in enumerate(value):
        text = _string(item, f"{field}[{index}]")
        assert text is not None
        result.append(text)
    if len(set(result)) != len(result):
        raise EvidenceValidationError(f"{field} contains duplicates")
    return tuple(result)


def normalize_pr_snapshot(payload: Any) -> NormalizedPRSnapshot:
    data = _reject_unknown(payload, _PR_FIELDS, "PR snapshot")
    repository = _string(data.get("repository"), "repository")
    if repository is None or repository.count("/") != 1:
        raise EvidenceValidationError("repository must be owner/name")
    _exact(data.get("pr_number"), int, "pr_number")
    pr_number = data["pr_number"]
    if pr_number <= 0:
        raise EvidenceValidationError("pr_number must be positive")
    base_branch = _string(data.get("base_branch"), "base_branch")
    head_branch = _string(data.get("head_branch"), "head_branch")
    state = _string(data.get("state"), "state")
    if state not in {"open", "closed"}:
        raise EvidenceValidationError("state must be open or closed")
    merged = _bool(data, "merged")
    draft = _bool(data, "draft")
    if merged and state != "closed":
        raise EvidenceValidationError("merged PR must be closed")
    changed_files = tuple(
        sorted(_string_sequence(data.get("changed_files"), "changed_files", max_items=MAX_CHANGED_FILES))
    )
    return NormalizedPRSnapshot(
        repository=repository,
        pr_number=pr_number,
        base_branch=base_branch,
        base_sha=_sha(data.get("base_sha"), "base_sha", optional=True),
        head_branch=head_branch,
        head_sha=_sha(data.get("head_sha"), "head_sha"),
        state=state,
        merged=merged,
        draft=draft,
        changed_files=changed_files,
        captured_at=_timestamp(data.get("captured_at"), "captured_at"),
        source_revision=_string(data.get("source_revision"), "source_revision", optional=True),
        **_authority_false(data),
    )


def normalize_review_thread(payload: Any) -> NormalizedReviewThread:
    data = _reject_unknown(payload, _THREAD_FIELDS, "review thread")
    thread_id = _string(data.get("thread_id"), "thread_id")
    reviewer = _string(data.get("reviewer"), "reviewer")
    body = _string(data.get("body"), "body")
    assert body is not None
    if len(body) > MAX_BODY_LENGTH:
        raise EvidenceValidationError("body exceeds size limit")
    _exact(data.get("top_level_comment_id"), int, "top_level_comment_id")
    comment_id = data["top_level_comment_id"]
    if comment_id <= 0:
        raise EvidenceValidationError("top_level_comment_id must be positive")
    superseded = _bool(data, "superseded", default=False)
    supersession_evidence = _string_sequence(
        data.get("supersession_evidence", []),
        "supersession_evidence",
        max_items=100,
    )
    if superseded and not supersession_evidence:
        raise EvidenceValidationError("superseded threads require supersession_evidence")
    side = _string(data.get("side"), "side", optional=True)
    start_side = _string(data.get("start_side"), "start_side", optional=True)
    for field, value in (("side", side), ("start_side", start_side)):
        if value is not None and value not in {"LEFT", "RIGHT"}:
            raise EvidenceValidationError(f"{field} must be LEFT or RIGHT")
    return NormalizedReviewThread(
        thread_id=thread_id,
        top_level_comment_id=comment_id,
        reviewer=reviewer,
        body_fingerprint=sha256(body.encode("utf-8")).hexdigest(),
        resolved=_bool(data, "resolved"),
        outdated=_bool(data, "outdated"),
        superseded=superseded,
        path=_string(data.get("path"), "path", optional=True),
        line=_optional_positive_int(data.get("line"), "line"),
        original_line=_optional_positive_int(data.get("original_line"), "original_line"),
        side=side,
        start_line=_optional_positive_int(data.get("start_line"), "start_line"),
        start_side=start_side,
        created_at=_timestamp(data.get("created_at"), "created_at"),
        updated_at=_timestamp(data.get("updated_at"), "updated_at"),
        reply_ids=_string_sequence(data.get("reply_ids", []), "reply_ids", max_items=500),
        supersession_evidence=supersession_evidence,
        **_authority_false(data),
    )


def normalize_review_threads(payload: Any) -> tuple[NormalizedReviewThread, ...]:
    _exact(payload, list, "review threads")
    if len(payload) > MAX_THREADS:
        raise EvidenceValidationError("review threads exceed size limit")
    threads = tuple(normalize_review_thread(item) for item in payload)
    thread_ids = [thread.thread_id for thread in threads]
    comment_ids = [thread.top_level_comment_id for thread in threads]
    if len(set(thread_ids)) != len(thread_ids):
        raise EvidenceValidationError("duplicate thread_id")
    if len(set(comment_ids)) != len(comment_ids):
        raise EvidenceValidationError("duplicate top_level_comment_id")
    return threads


def classify_review_thread_payload(payload: Any) -> str:
    """Classify supplied thread evidence without weakening strict normalization."""

    try:
        return normalize_review_thread(payload).classification
    except EvidenceValidationError:
        return "malformed"
