"""Immutable, pure-local Cloud Build reporting evidence models.

No network, filesystem, clock, subprocess, credential, or environment access.
Every value here is supplied by the caller; nothing is fabricated or inferred.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

CLOUD_BUILD_EVIDENCE_SCHEMA_NAME = "agent-os-cloud-build-evidence"
CLOUD_BUILD_EVIDENCE_SCHEMA_VERSION = "1.0"

MAX_FIELD_LENGTH = 512
MAX_REASON_CODES = 32
MAX_PR_CANDIDATES = 64

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^[a-z0-9_.-]+/[a-z0-9_.-]+$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class CloudBuildEvidenceError(ValueError):
    """Raised when supplied evidence cannot be represented safely."""


class OverallResult(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal-error"
    EXPIRED = "expired"
    UNAVAILABLE = "unavailable"
    PENDING = "pending"
    MALFORMED = "malformed"


TERMINAL_RESULTS = frozenset(
    {
        OverallResult.SUCCESS,
        OverallResult.FAILURE,
        OverallResult.TIMEOUT,
        OverallResult.CANCELLED,
        OverallResult.INTERNAL_ERROR,
        OverallResult.EXPIRED,
    }
)
NON_TERMINAL_RESULTS = frozenset({OverallResult.PENDING})


class PullRequestState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    SKIPPED = "skipped"
    MANUAL_REVIEW = "manual-review"
    INVALID = "invalid"


def _check_bounded_str(name: str, value: object, *, allow_none: bool = False) -> str | None:
    if value is None:
        if allow_none:
            return None
        raise CloudBuildEvidenceError(f"{name} must not be None")
    if not isinstance(value, str) or not value:
        raise CloudBuildEvidenceError(f"{name} must be a non-empty string")
    if len(value) > MAX_FIELD_LENGTH:
        raise CloudBuildEvidenceError(f"{name} exceeds maximum length")
    if _CONTROL_CHAR_RE.search(value):
        raise CloudBuildEvidenceError(f"{name} contains control characters")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildResultEvidence:
    build_id: str
    tested_sha: str
    repository: str
    trigger_id: str | None = None
    invocation_id: str | None = None
    overall_result: OverallResult
    failed_step: str | None = None
    exit_code: int | None = None
    observed_at: str | None = None
    terminal: bool
    source_complete: bool
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "build_id", _check_bounded_str("build_id", self.build_id))

        if not isinstance(self.tested_sha, str) or not _SHA40_RE.fullmatch(self.tested_sha):
            raise CloudBuildEvidenceError("tested_sha must be a full 40-character lowercase SHA")

        repository = _check_bounded_str("repository", self.repository).lower()
        if not _REPOSITORY_RE.fullmatch(repository):
            raise CloudBuildEvidenceError("repository must be owner/name")
        object.__setattr__(self, "repository", repository)

        object.__setattr__(
            self, "trigger_id", _check_bounded_str("trigger_id", self.trigger_id, allow_none=True)
        )
        object.__setattr__(
            self,
            "invocation_id",
            _check_bounded_str("invocation_id", self.invocation_id, allow_none=True),
        )
        object.__setattr__(
            self,
            "observed_at",
            _check_bounded_str("observed_at", self.observed_at, allow_none=True),
        )

        if not isinstance(self.overall_result, OverallResult):
            raise CloudBuildEvidenceError("overall_result must be an OverallResult")
        if not isinstance(self.terminal, bool):
            raise CloudBuildEvidenceError("terminal must be a bool")
        if not isinstance(self.source_complete, bool):
            raise CloudBuildEvidenceError("source_complete must be a bool")

        if self.overall_result in TERMINAL_RESULTS and not self.terminal:
            raise CloudBuildEvidenceError("terminal result requires terminal=True")
        if self.overall_result in NON_TERMINAL_RESULTS and self.terminal:
            raise CloudBuildEvidenceError("pending result requires terminal=False")

        if self.failed_step is not None:
            object.__setattr__(
                self, "failed_step", _check_bounded_str("failed_step", self.failed_step)
            )
        if self.failed_step == "none" and self.overall_result != OverallResult.SUCCESS:
            raise CloudBuildEvidenceError("failed_step=none is valid only for proven success")
        if self.failed_step == "none" and not self.terminal:
            raise CloudBuildEvidenceError("failed_step=none requires a terminal result")

        if self.exit_code is not None:
            if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int):
                raise CloudBuildEvidenceError("exit_code must be an int or None")
        if self.exit_code == 0 and self.overall_result != OverallResult.SUCCESS:
            raise CloudBuildEvidenceError("exit_code=0 is valid only for proven success")
        if self.exit_code == 0 and not self.terminal:
            raise CloudBuildEvidenceError("exit_code=0 requires a terminal result")

        if self.overall_result == OverallResult.SUCCESS and self.terminal:
            if self.failed_step not in (None, "none"):
                raise CloudBuildEvidenceError("proven success cannot carry a failed step")
            if self.exit_code not in (None, 0):
                raise CloudBuildEvidenceError("proven success cannot carry a nonzero exit code")


@dataclass(frozen=True, slots=True, kw_only=True)
class PullRequestResolutionCandidate:
    repository: str
    pull_request_number: int
    head_sha: str
    state: PullRequestState
    evidence_source: str

    def __post_init__(self) -> None:
        repository = _check_bounded_str("repository", self.repository).lower()
        if not _REPOSITORY_RE.fullmatch(repository):
            raise CloudBuildEvidenceError("repository must be owner/name")
        object.__setattr__(self, "repository", repository)

        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number <= 0
        ):
            raise CloudBuildEvidenceError("pull_request_number must be a positive int")

        if not isinstance(self.head_sha, str) or not _SHA40_RE.fullmatch(self.head_sha):
            raise CloudBuildEvidenceError("head_sha must be a full 40-character lowercase SHA")

        if not isinstance(self.state, PullRequestState):
            raise CloudBuildEvidenceError("state must be a PullRequestState")

        object.__setattr__(
            self, "evidence_source", _check_bounded_str("evidence_source", self.evidence_source)
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PullRequestResolutionResult:
    status: ResolutionStatus
    pull_request_number: int | None
    reason_codes: tuple[str, ...]
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResolutionStatus):
            raise CloudBuildEvidenceError("status must be a ResolutionStatus")
        if self.status == ResolutionStatus.RESOLVED:
            if self.pull_request_number is None:
                raise CloudBuildEvidenceError("resolved status requires a pull_request_number")
        elif self.pull_request_number is not None:
            raise CloudBuildEvidenceError(
                "pull_request_number must be None unless status is resolved"
            )
        if self.pull_request_number is not None and (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number <= 0
        ):
            raise CloudBuildEvidenceError("pull_request_number must be a positive int")

        codes = tuple(self.reason_codes)
        if len(codes) > MAX_REASON_CODES:
            raise CloudBuildEvidenceError("too many reason codes")
        for code in codes:
            _check_bounded_str("reason_code", code)
        object.__setattr__(self, "reason_codes", tuple(sorted(dict.fromkeys(codes))))
        if not self.reason_codes:
            raise CloudBuildEvidenceError("reason_codes must not be empty")
