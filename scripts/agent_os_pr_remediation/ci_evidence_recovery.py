"""Pure-local, fail-closed planning for resilient GitHub Actions evidence recovery."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .models import EvidenceValidationError, canonical_json, deterministic_id

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


def _sha40(value: Any, field: str) -> str:
    text = _text(value, field).lower()
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text):
        raise EvidenceValidationError(f"{field} must be a 40-character hexadecimal SHA")
    return text


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
    path: str
    succeeded: bool
    reason_code: str | None = None
    actionable_failure: str | None = None
    run_complete: bool = True

    def __post_init__(self) -> None:
        if self.path not in RECOVERY_PATHS[:-1]:
            raise EvidenceValidationError("unsupported recovery path")
        if type(self.succeeded) is not bool or type(self.run_complete) is not bool:
            raise EvidenceValidationError("recovery booleans must be exact bool")
        if self.reason_code is not None and self.reason_code not in RECOVERY_FAILURE_REASONS:
            raise EvidenceValidationError("unsupported recovery reason code")
        if self.succeeded and self.reason_code not in {None, "log-association-failed"}:
            raise EvidenceValidationError("successful recovery cannot carry a blocking reason")
        if self.actionable_failure is not None:
            object.__setattr__(self, "actionable_failure", _text(self.actionable_failure, "actionable_failure"))


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
    repair_authorized: bool = False
    external_write_authorized: bool = False
    side_effects_performed: bool = False

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
) -> CIEvidenceRecoveryPlan:
    current_head = _sha40(current_head_sha, "current_head_sha")
    if type(current_run_attempt) is not int or current_run_attempt < 1:
        raise EvidenceValidationError("current_run_attempt must be positive")
    if type(retry_count) is not int or type(retry_limit) is not int or retry_count < 0 or retry_limit < 0:
        raise EvidenceValidationError("retry counts must be non-negative integers")
    if retry_count > retry_limit:
        raise EvidenceValidationError("retry_count cannot exceed retry_limit")
    if type(observations) is not tuple:
        raise EvidenceValidationError("observations must be a tuple")

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
            if item.reason_code:
                reasons.append(item.reason_code)
            if not item.run_complete:
                reasons.append("run-in-progress")
                break
            if item.succeeded and item.actionable_failure:
                actionable = item.actionable_failure
                usable = True
                break

        if not usable and "run-in-progress" not in reasons:
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
    )
