"""Pure-local deterministic models for PR review remediation evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any

AUTHORITY_FIELDS = (
    "execution_authorized",
    "external_write_authorized",
    "merge_authorized",
    "side_effects_performed",
)


class EvidenceValidationError(ValueError):
    """Supplied evidence is malformed, conflicting, or outside the contract."""


def canonical_json(value: Any) -> str:
    """Serialize only built-in JSON data deterministically."""

    if type(value) not in {dict, list, str, int, float, bool, type(None)}:
        raise EvidenceValidationError("canonical_json accepts built-in JSON values only")
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise EvidenceValidationError("value is not canonical JSON data") from exc


def deterministic_id(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NormalizedPRSnapshot:
    repository: str
    pr_number: int
    base_branch: str
    head_branch: str
    head_sha: str
    state: str
    merged: bool
    draft: bool
    changed_files: tuple[str, ...]
    base_sha: str | None = None
    captured_at: str | None = None
    source_revision: str | None = None
    execution_authorized: bool = False
    external_write_authorized: bool = False
    merge_authorized: bool = False
    side_effects_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def evidence_id(self) -> str:
        return deterministic_id(self.to_dict())


@dataclass(frozen=True)
class NormalizedReviewThread:
    thread_id: str
    top_level_comment_id: int
    reviewer: str
    body_fingerprint: str
    resolved: bool
    outdated: bool
    superseded: bool
    path: str | None = None
    line: int | None = None
    original_line: int | None = None
    side: str | None = None
    start_line: int | None = None
    start_side: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    reply_ids: tuple[str, ...] = ()
    supersession_evidence: tuple[str, ...] = ()
    execution_authorized: bool = False
    external_write_authorized: bool = False
    merge_authorized: bool = False
    side_effects_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def evidence_id(self) -> str:
        return deterministic_id(self.to_dict())

    @property
    def classification(self) -> str:
        if self.superseded:
            return "superseded"
        if self.outdated:
            return "outdated"
        if self.resolved:
            return "resolved"
        if self.path is None or self.line is None:
            return "unavailable"
        return "current-unresolved"
