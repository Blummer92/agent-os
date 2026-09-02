"""Pure-local, fail-closed planning for resilient GitHub Actions evidence recovery."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .models import EvidenceValidationError, canonical_json, deterministic_id

MIN_DIAGNOSTIC_EXCERPT_LINES = 50
DEFAULT_DIAGNOSTIC_EXCERPT_LINES = 50
MAX_DIAGNOSTIC_EXCERPT_LINES = 150
DIAGNOSTIC_EXCERPT_EXPANSION_LINES = 50
MAX_ACTIONABLE_FAILURE_CHARS = 12_000

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)bearer\s+[a-z0-9\-_.]+"),
    re.compile(r"(?i)authorization\s*[:=]\s*\S+"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd)\s*[:=]\s*\S+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)https?://\S*[?&](?:sig|signature|token|x-goog-signature)=\S+"),
    re.compile(r"(?i)\S*(?:\.ssh|\.aws|\.gnupg|\.pem|\.env|id_rsa|credentials)\S*"),
)
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

RECOVERY_FAILURE_REASONS = frozenset({
    "cli-unavailable", "cli-unauthenticated", "insufficient-permission",
    "credential-conflict", "wrong-host", "rate-limited", "run-in-progress",
    "run-attempt-mismatch", "wrong-head", "run-log-unavailable",
    "job-log-unavailable", "log-association-failed", "transient-network",
    "environment-expired", "disk-exhausted", "evidence-unavailable",
})
TRANSIENT_REASONS = frozenset({"rate-limited", "transient-network"})
RECOVERY_PATHS = ("structured", "direct-actions-log", "gh-run-log", "job-log", "approved-alternate", "user-handoff")


def _text(value: Any, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise EvidenceValidationError(f"{field} must be a non-empty string")
    return value.strip()


def sanitize_actionable_failure(value: Any) -> str:
    """Return deterministic public-safe failure text bounded by lines and chars."""
    text = _text(value, "actionable_failure").replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARACTERS.sub("�", text)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    lines = text.split("\n")[:MAX_DIAGNOSTIC_EXCERPT_LINES]
    text = "\n".join(lines)
    if len(text) > MAX_ACTIONABLE_FAILURE_CHARS:
        text = text[:MAX_ACTIONABLE_FAILURE_CHARS] + "…[truncated]"
    return text


def _sha40(value: Any, field: str) -> str:
    text = _text(value, field).lower()
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text):
        raise EvidenceValidationError(f"{field} must be a 40-character hexadecimal SHA")
    return text


def diagnostic_excerpt_lines(value: int = DEFAULT_DIAGNOSTIC_EXCERPT_LINES) -> int:
    """Validate one routine diagnostic excerpt target."""
    if type(value) is not int or value < MIN_DIAGNOSTIC_EXCERPT_LINES or value > MAX_DIAGNOSTIC_EXCERPT_LINES:
        raise EvidenceValidationError("diagnostic excerpt lines must be an integer from 50 through 150")
    return value


def expand_diagnostic_excerpt_lines(current_lines: int, *, increment: int = DIAGNOSTIC_EXCERPT_EXPANSION_LINES) -> int:
    """Expand a routine excerpt deterministically without exceeding 150 lines."""
    current = diagnostic_excerpt_lines(current_lines)
    if type(increment) is not int or increment < 1:
        raise EvidenceValidationError("diagnostic excerpt expansion increment must be a positive integer")
    return min(MAX_DIAGNOSTIC_EXCERPT_LINES, current + increment)


@dataclass(frozen=True, slots=True)
class CIEvidenceIdentity:
    repository: str
    pr_number: int
    head_sha: str
    run_id: int
    run_attempt: int
    job_id: int | None = None

    def __post_init__(self) -> None:
        repository = _text(self.repository, "repository")
        if repository.count("/") != 1 or any(not part for part in repository.split("/")):
            raise EvidenceValidationError("repository must be exact owner/name")
        if type(self.pr_number) is not int or self.pr_number < 1:
            raise EvidenceValidationError("pr_number must be positive")
        if type(self.run_id) is not int or self.run_id < 1:
            raise EvidenceValidationError("run_id must be positive")
        if type(self.run_attempt) is not int or self.run_attempt < 1:
            raise EvidenceValidationError("run_attempt must be positive")
        if self.job_id is not None and (type(self.job_id) is not int or self.job_id < 1):
            raise EvidenceValidationError("job_id must be positive when present")
        object.__setattr__(self, "repository", repository)
        object.__setattr__(self, "head_sha", _sha40(self.head_sha, "head_sha"))


@dataclass(frozen=True, slots=True)
class RecoveryObservation:
    identity: CIEvidenceIdentity
    path: str
    succeeded: bool
    reason_code: str | None = None
    actionable_failure: str | None = None
    run_complete: bool = True

    def __post_init__(self) -> None:
        if type(self.identity) is not CIEvidenceIdentity:
            raise EvidenceValidationError("observation identity must be a CIEvidenceIdentity")
        if self.path not in RECOVERY_PATHS[:-1]:
            raise EvidenceValidationError("unsupported recovery path")
        if type(self.succeeded) is not bool or type(self.run_complete) is not bool:
            raise EvidenceValidationError("recovery booleans must be exact bool")
        if self.reason_code is not None and self.reason_code not in RECOVERY_FAILURE_REASONS:
            raise EvidenceValidationError("unsupported recovery reason code")
        if self.succeeded and self.reason_code not in {None, "log-association-failed"}:
            raise EvidenceValidationError("successful recovery cannot carry a blocking reason")
        if self.actionable_failure is not None:
            object.__setattr__(self, "actionable_failure", sanitize_actionable_failure(self.actionable_failure))


@dataclass(frozen=True, slots=True)
class CIEvidenceRecoveryPlan:
    identity: CIEvidenceIdentity
    current_head_sha: str
    current_run_attempt: int
    attempted_paths: tuple[str, ...]
    next_path: str | None
    reason_codes: tuple[str, ...]
    actionable_failure: str | None
    evidence_usable_for_attribution: bool
    retry_count: int
    retry_limit: int
    user_handoff_required: bool
    diagnostic_excerpt_target_lines: int = DEFAULT_DIAGNOSTIC_EXCERPT_LINES
    repair_authorized: bool = False
    external_write_authorized: bool = False
    side_effects_performed: bool = False

    def __post_init__(self) -> None:
        diagnostic_excerpt_lines(self.diagnostic_excerpt_target_lines)
        if self.actionable_failure is not None:
            object.__setattr__(self, "actionable_failure", sanitize_actionable_failure(self.actionable_failure))
        if any(value is not False for value in (self.repair_authorized, self.external_write_authorized, self.side_effects_performed)):
            raise EvidenceValidationError("CI evidence recovery authority fields must be exactly false")

    @property
    def plan_id(self) -> str:
        return deterministic_id(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def canonical_serialization(self) -> str:
        return canonical_json(self.to_dict())


def plan_ci_evidence_recovery(
    identity: CIEvidenceIdentity,
    *,
    current_head_sha: str,
    current_run_attempt: int,
    observations: tuple[RecoveryObservation, ...] = (),
    retry_count: int = 0,
    retry_limit: int = 2,
    diagnostic_excerpt_target_lines: int = DEFAULT_DIAGNOSTIC_EXCERPT_LINES,
) -> CIEvidenceRecoveryPlan:
    if type(identity) is not CIEvidenceIdentity:
        raise EvidenceValidationError("identity must be a CIEvidenceIdentity")
    current_head = _sha40(current_head_sha, "current_head_sha")
    excerpt_lines = diagnostic_excerpt_lines(diagnostic_excerpt_target_lines)
    if type(current_run_attempt) is not int or current_run_attempt < 1:
        raise EvidenceValidationError("current_run_attempt must be positive")
    if type(retry_count) is not int or type(retry_limit) is not int or retry_count < 0 or retry_limit < 0:
        raise EvidenceValidationError("retry counts must be non-negative integers")
    if retry_count > retry_limit:
        raise EvidenceValidationError("retry_count cannot exceed retry_limit")
    if type(observations) is not tuple:
        raise EvidenceValidationError("observations must be a tuple")
    if any(type(item) is not RecoveryObservation for item in observations):
        raise EvidenceValidationError("observations must contain only RecoveryObservation values")

    attempted = tuple(item.path for item in observations)
    if len(set(attempted)) != len(attempted):
        raise EvidenceValidationError("recovery paths cannot be attempted twice in one plan")

    reasons: list[str] = []
    actionable: str | None = None
    usable = False
    next_path: str | None = None
    handoff = False

    if identity.head_sha != current_head:
        reasons.append("wrong-head")
    elif identity.run_attempt != current_run_attempt:
        reasons.append("run-attempt-mismatch")
    else:
        for item in observations:
            if item.identity != identity:
                reasons.append("wrong-head" if item.identity.head_sha != identity.head_sha else "run-attempt-mismatch")
                break
            if item.reason_code:
                reasons.append(item.reason_code)
            if item.reason_code in {"wrong-head", "run-attempt-mismatch"}:
                break
            if not item.run_complete:
                reasons.append("run-in-progress")
                break
            if item.succeeded and item.actionable_failure:
                actionable = item.actionable_failure
                usable = True
                break

        fail_closed = any(reason in {"wrong-head", "run-attempt-mismatch"} for reason in reasons)
        if fail_closed:
            actionable = None
            usable = False
        elif not usable and "run-in-progress" not in reasons:
            last_reason = reasons[-1] if reasons else None
            if last_reason in TRANSIENT_REASONS and retry_count < retry_limit:
                next_path = attempted[-1] if attempted else RECOVERY_PATHS[0]
            else:
                remaining = [path for path in RECOVERY_PATHS[:-1] if path not in attempted]
                next_path = remaining[0] if remaining else None
                if next_path is None:
                    handoff = True
                    reasons.append("evidence-unavailable")

    return CIEvidenceRecoveryPlan(
        identity=identity,
        current_head_sha=current_head,
        current_run_attempt=current_run_attempt,
        attempted_paths=attempted,
        next_path=next_path,
        reason_codes=tuple(dict.fromkeys(reasons)),
        actionable_failure=actionable,
        evidence_usable_for_attribution=usable,
        retry_count=retry_count,
        retry_limit=retry_limit,
        user_handoff_required=handoff,
        diagnostic_excerpt_target_lines=excerpt_lines,
    )
