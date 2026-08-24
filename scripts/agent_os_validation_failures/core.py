"""Pure-local provider-neutral projection of already-normalized validation failures."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Sequence

VALIDATION_FAILURE_SCHEMA_VERSION = "1.0"
MAX_TEXT_BYTES = 4096
MAX_EXCERPT_BYTES = 16384
MAX_FACTS = 64
MAX_ITEMS = 128
MAX_REASON_CODES = 64
MAX_SERIALIZED_BYTES = 262144

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SECRETS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"(?i)authorization\s*[:=]\s*\S+"),
    re.compile(r"(?i)(?:api[_-]?key|token|secret|password|passwd)\s*[:=]\s*\S+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)https?://\S*[?&](?:sig|signature|token|x-goog-signature)=\S+"),
)


class ValidationFailureError(ValueError):
    pass


class ValidationFailureSource(str, Enum):
    CLOUD_BUILD = "cloud-build"
    EXECUTION_COMPOSITION = "execution-composition"
    WORKFLOW_SCHEDULER = "workflow-scheduler"
    GITHUB_ACTIONS_NORMALIZED = "github-actions-normalized"
    LOCAL_NORMALIZED = "local-normalized"
    OTHER_NORMALIZED = "other-normalized"


class ValidationFailureStatus(str, Enum):
    ACTIONABLE_FAILURE = "actionable-failure"
    INFRASTRUCTURE_FAILURE = "infrastructure-failure"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    INCOMPLETE = "incomplete"
    MALFORMED_INPUT = "malformed-input"
    MANUAL_REVIEW = "manual-review"


class ValidationMode(str, Enum):
    FOCUSED = "focused"
    AGGREGATE = "aggregate"
    UNAVAILABLE = "unavailable"


class EvidenceValueState(str, Enum):
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"
    REDACTED = "redacted"
    TRUNCATED = "truncated"


_OUTCOME = {
    "failure": ValidationFailureStatus.ACTIONABLE_FAILURE,
    "focused-fail": ValidationFailureStatus.ACTIONABLE_FAILURE,
    "aggregate-fail": ValidationFailureStatus.ACTIONABLE_FAILURE,
    "infrastructure-failure": ValidationFailureStatus.INFRASTRUCTURE_FAILURE,
    "internal-error": ValidationFailureStatus.INFRASTRUCTURE_FAILURE,
    "cancelled": ValidationFailureStatus.CANCELLED,
    "timeout": ValidationFailureStatus.TIMEOUT,
    "timed-out": ValidationFailureStatus.TIMEOUT,
    "expired": ValidationFailureStatus.INCOMPLETE,
    "pending": ValidationFailureStatus.INCOMPLETE,
    "unavailable": ValidationFailureStatus.INCOMPLETE,
    "incomplete": ValidationFailureStatus.INCOMPLETE,
    "focused-pass-aggregate-pending": ValidationFailureStatus.INCOMPLETE,
    "malformed": ValidationFailureStatus.MALFORMED_INPUT,
    "malformed-input": ValidationFailureStatus.MALFORMED_INPUT,
    "manual-review": ValidationFailureStatus.MANUAL_REVIEW,
    "success": ValidationFailureStatus.MANUAL_REVIEW,
    "aggregate-pass": ValidationFailureStatus.MANUAL_REVIEW,
}
_PRECEDENCE = {
    ValidationFailureStatus.MALFORMED_INPUT: 70,
    ValidationFailureStatus.MANUAL_REVIEW: 60,
    ValidationFailureStatus.INFRASTRUCTURE_FAILURE: 50,
    ValidationFailureStatus.CANCELLED: 40,
    ValidationFailureStatus.TIMEOUT: 30,
    ValidationFailureStatus.INCOMPLETE: 20,
    ValidationFailureStatus.ACTIONABLE_FAILURE: 10,
}
_PROVENANCE = {
    "fresh-and-applicable", "verified", "stale", "identity-mismatch", "expired",
    "incomplete", "manual-review", "unverified", "unavailable",
}


def _text(value: object, name: str, maximum: int = MAX_TEXT_BYTES) -> str:
    if type(value) is not str or not value or _CONTROL.search(value) or len(value.encode()) > maximum:
        raise ValidationFailureError(f"{name} must be bounded safe text")
    return value


def _optional(value: object, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _items(value: object, name: str, maximum: int = MAX_ITEMS) -> tuple[str, ...]:
    if type(value) not in {list, tuple} or len(value) > maximum:
        raise ValidationFailureError(f"{name} must be a bounded list or tuple")
    result = tuple(_text(item, name) for item in value)
    if len(set(result)) != len(result):
        raise ValidationFailureError(f"{name} contains duplicates")
    return tuple(sorted(result))


def _untrusted(value: object, maximum: int) -> tuple[str | None, EvidenceValueState, bool, bool]:
    if value is None:
        return None, EvidenceValueState.UNAVAILABLE, False, False
    if type(value) is not str:
        raise ValidationFailureError("untrusted evidence text must be a string or None")
    text = value.encode("utf-8", errors="replace").decode("utf-8")
    text = _CONTROL.sub("�", text)
    redacted = False
    for pattern in _SECRETS:
        changed = pattern.sub("[REDACTED]", text)
        redacted = redacted or changed != text
        text = changed
    encoded = text.encode()
    truncated = len(encoded) > maximum
    if truncated:
        text = encoded[:maximum].decode("utf-8", errors="ignore")
    state = EvidenceValueState.REDACTED if redacted else EvidenceValueState.TRUNCATED if truncated else EvidenceValueState.OBSERVED
    return text, state, redacted, truncated


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservedFailureFact:
    repository: str
    tested_sha: str
    source: ValidationFailureSource
    mode: ValidationMode
    source_record_id: str
    outcome: str
    run_identity: str | None = None
    provider_identity: str | None = None
    operation: str | None = None
    command_identity: str | None = None
    return_code: int | None = None
    failing_step: str | None = None
    test_name: str | None = None
    error_excerpt: str | None = field(default=None, repr=False)
    timestamp: str | None = None
    duration_seconds: float | None = None
    aggregate_pending: bool = False
    source_complete: bool = True
    output_truncated: bool = False
    redacted: bool = False
    executed_commands: tuple[str, ...] = ()
    skipped_commands: tuple[str, ...] = ()
    not_reached_commands: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    provenance_id: str | None = None
    provenance_state: str | None = None
    return_code_state: EvidenceValueState = field(init=False)
    failing_step_state: EvidenceValueState = field(init=False)
    test_name_state: EvidenceValueState = field(init=False)
    excerpt_state: EvidenceValueState = field(init=False)
    timestamp_state: EvidenceValueState = field(init=False)
    duration_state: EvidenceValueState = field(init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    repair_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        repo = _text(self.repository, "repository").lower()
        if not _REPOSITORY.fullmatch(repo):
            raise ValidationFailureError("repository must be owner/name")
        object.__setattr__(self, "repository", repo)
        if type(self.tested_sha) is not str or not _SHA40.fullmatch(self.tested_sha):
            raise ValidationFailureError("tested_sha must be a lowercase 40-character SHA")
        if type(self.source) is not ValidationFailureSource or type(self.mode) is not ValidationMode:
            raise ValidationFailureError("source/mode enum is invalid")
        object.__setattr__(self, "source_record_id", _text(self.source_record_id, "source_record_id"))
        if self.outcome not in _OUTCOME:
            raise ValidationFailureError("outcome is unsupported")
        for name in ("run_identity", "provider_identity", "operation", "command_identity", "provenance_id"):
            object.__setattr__(self, name, _optional(getattr(self, name), name))
        if self.return_code is not None and type(self.return_code) is not int:
            raise ValidationFailureError("return_code must be an int or None")
        if self.duration_seconds is not None:
            if type(self.duration_seconds) not in {int, float} or isinstance(self.duration_seconds, bool):
                raise ValidationFailureError("duration_seconds must be numeric or None")
            duration = float(self.duration_seconds)
            if not math.isfinite(duration) or duration < 0:
                raise ValidationFailureError("duration_seconds must be finite and non-negative")
            object.__setattr__(self, "duration_seconds", duration)
        for name in ("aggregate_pending", "source_complete", "output_truncated", "redacted"):
            if type(getattr(self, name)) is not bool:
                raise ValidationFailureError(f"{name} must be bool")
        redacted = self.redacted
        truncated = self.output_truncated
        for name, maximum, state_name in (
            ("failing_step", MAX_TEXT_BYTES, "failing_step_state"),
            ("test_name", MAX_TEXT_BYTES, "test_name_state"),
            ("error_excerpt", MAX_EXCERPT_BYTES, "excerpt_state"),
            ("timestamp", MAX_TEXT_BYTES, "timestamp_state"),
        ):
            value, state, was_redacted, was_truncated = _untrusted(getattr(self, name), maximum)
            object.__setattr__(self, name, value)
            object.__setattr__(self, state_name, state)
            redacted |= was_redacted
            truncated |= was_truncated
        object.__setattr__(self, "redacted", redacted)
        object.__setattr__(self, "output_truncated", truncated)
        object.__setattr__(self, "return_code_state", EvidenceValueState.UNAVAILABLE if self.return_code is None else EvidenceValueState.OBSERVED)
        object.__setattr__(self, "duration_state", EvidenceValueState.UNAVAILABLE if self.duration_seconds is None else EvidenceValueState.OBSERVED)
        if redacted and self.error_excerpt is not None:
            object.__setattr__(self, "excerpt_state", EvidenceValueState.REDACTED)
        elif truncated and self.error_excerpt is not None:
            object.__setattr__(self, "excerpt_state", EvidenceValueState.TRUNCATED)
        for name in ("executed_commands", "skipped_commands", "not_reached_commands"):
            object.__setattr__(self, name, _items(getattr(self, name), name))
        object.__setattr__(self, "reason_codes", _items(self.reason_codes, "reason_codes", MAX_REASON_CODES))
        if self.provenance_state is not None and self.provenance_state not in _PROVENANCE:
            raise ValidationFailureError("provenance_state is unsupported")


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationFailureRecord:
    schema_version: str
    repository: str
    tested_sha: str
    source: ValidationFailureSource
    mode: ValidationMode
    status: ValidationFailureStatus
    facts: tuple[ObservedFailureFact, ...]
    aggregate_pending: bool
    reason_codes: tuple[str, ...]
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    repair_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def _fact_payload(f: ObservedFailureFact) -> dict[str, object]:
    return {
        "repository": f.repository, "tested_sha": f.tested_sha, "source": f.source.value, "mode": f.mode.value,
        "source_record_id": f.source_record_id, "outcome": f.outcome, "run_identity": f.run_identity,
        "provider_identity": f.provider_identity, "operation": f.operation, "command_identity": f.command_identity,
        "return_code": f.return_code, "return_code_state": f.return_code_state.value,
        "failing_step": f.failing_step, "failing_step_state": f.failing_step_state.value,
        "test_name": f.test_name, "test_name_state": f.test_name_state.value,
        "error_excerpt": f.error_excerpt, "excerpt_state": f.excerpt_state.value,
        "timestamp": f.timestamp, "timestamp_state": f.timestamp_state.value,
        "duration_seconds": f.duration_seconds, "duration_state": f.duration_state.value,
        "aggregate_pending": f.aggregate_pending, "source_complete": f.source_complete,
        "output_truncated": f.output_truncated, "redacted": f.redacted,
        "executed_commands": list(f.executed_commands), "skipped_commands": list(f.skipped_commands),
        "not_reached_commands": list(f.not_reached_commands), "reason_codes": list(f.reason_codes),
        "provenance_id": f.provenance_id, "provenance_state": f.provenance_state,
        "execution_authorized": False, "merge_authorized": False, "repair_authorized": False,
        "side_effects_performed": False,
    }


def _sort_key(f: ObservedFailureFact) -> str:
    return json.dumps(_fact_payload(f), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _status(facts: tuple[ObservedFailureFact, ...], reasons: set[str]) -> ValidationFailureStatus:
    statuses: list[ValidationFailureStatus] = []
    for f in facts:
        status = _OUTCOME[f.outcome]
        statuses.append(status)
        if not f.source_complete:
            statuses.append(ValidationFailureStatus.INCOMPLETE); reasons.add("evidence-incomplete")
        if f.provenance_state in {"stale", "identity-mismatch", "expired", "incomplete", "manual-review", "unverified", "unavailable"}:
            statuses.append(ValidationFailureStatus.MANUAL_REVIEW); reasons.add(f"provenance-{f.provenance_state}")
        if f.return_code == 0 and status in {ValidationFailureStatus.ACTIONABLE_FAILURE, ValidationFailureStatus.INFRASTRUCTURE_FAILURE, ValidationFailureStatus.TIMEOUT, ValidationFailureStatus.CANCELLED}:
            statuses.append(ValidationFailureStatus.MANUAL_REVIEW); reasons.add("contradictory-return-code")
        if f.return_code not in {None, 0} and f.outcome in {"success", "aggregate-pass"}:
            statuses.append(ValidationFailureStatus.MANUAL_REVIEW); reasons.add("contradictory-return-code")
        if f.mode is ValidationMode.FOCUSED and status is ValidationFailureStatus.ACTIONABLE_FAILURE and not f.aggregate_pending:
            statuses.append(ValidationFailureStatus.MANUAL_REVIEW); reasons.add("focused-aggregate-pending-missing")
        if f.mode is ValidationMode.AGGREGATE and f.aggregate_pending:
            statuses.append(ValidationFailureStatus.MANUAL_REVIEW); reasons.add("aggregate-cannot-be-pending")
    terminals = {s for s in statuses if s not in {ValidationFailureStatus.INCOMPLETE, ValidationFailureStatus.MANUAL_REVIEW}}
    if len(terminals) > 1:
        statuses.append(ValidationFailureStatus.MANUAL_REVIEW); reasons.add("contradictory-terminal-status")
    failures = [f for f in facts if _OUTCOME[f.outcome] is ValidationFailureStatus.ACTIONABLE_FAILURE]
    identities = {(f.run_identity or f.source_record_id, f.command_identity or f.failing_step or f.test_name or f.source_record_id) for f in failures}
    if len(identities) > 1:
        statuses.append(ValidationFailureStatus.MANUAL_REVIEW); reasons.add("multiple-independent-failures")
    return max(statuses, key=lambda s: _PRECEDENCE[s])


def build_validation_failure_record(*, repository: str, tested_sha: str, source: ValidationFailureSource, mode: ValidationMode, facts: Sequence[ObservedFailureFact]) -> ValidationFailureRecord:
    repository = _text(repository, "repository").lower()
    if not _REPOSITORY.fullmatch(repository) or type(tested_sha) is not str or not _SHA40.fullmatch(tested_sha):
        raise ValidationFailureError("repository or tested_sha is invalid")
    if type(source) is not ValidationFailureSource or type(mode) is not ValidationMode:
        raise ValidationFailureError("source/mode enum is invalid")
    if type(facts) not in {list, tuple} or not facts or len(facts) > MAX_FACTS or any(type(f) is not ObservedFailureFact for f in facts):
        raise ValidationFailureError("facts must be a non-empty bounded sequence of exact ObservedFailureFact")
    normalized = tuple(sorted(facts, key=_sort_key))
    reasons: set[str] = set()
    if any(f.repository != repository for f in normalized): reasons.add("repository-mismatch")
    if any(f.tested_sha != tested_sha for f in normalized): reasons.add("tested-sha-mismatch")
    if any(f.source is not source for f in normalized): reasons.add("source-mismatch")
    if any(f.mode is not mode and f.mode is not ValidationMode.UNAVAILABLE for f in normalized): reasons.add("mode-mismatch")
    if len({f.provider_identity for f in normalized if f.provider_identity}) > 1: reasons.add("provider-identity-mismatch")
    if len({f.run_identity for f in normalized if f.run_identity}) > 1: reasons.add("run-identity-mismatch")
    status = _status(normalized, reasons)
    if reasons & {"repository-mismatch", "tested-sha-mismatch", "source-mismatch", "mode-mismatch", "provider-identity-mismatch", "run-identity-mismatch"}:
        status = ValidationFailureStatus.MANUAL_REVIEW
    for f in normalized: reasons.update(f.reason_codes)
    marker = {
        ValidationFailureStatus.ACTIONABLE_FAILURE: "actionable-failure-observed",
        ValidationFailureStatus.INFRASTRUCTURE_FAILURE: "infrastructure-failure-observed",
        ValidationFailureStatus.CANCELLED: "cancellation-observed",
        ValidationFailureStatus.TIMEOUT: "timeout-observed",
        ValidationFailureStatus.INCOMPLETE: "evidence-incomplete",
        ValidationFailureStatus.MALFORMED_INPUT: "malformed-input-observed",
        ValidationFailureStatus.MANUAL_REVIEW: "manual-review-required",
    }[status]
    reasons.add(marker)
    if len(reasons) > MAX_REASON_CODES: raise ValidationFailureError("too many reason codes")
    result = ValidationFailureRecord(
        schema_version=VALIDATION_FAILURE_SCHEMA_VERSION, repository=repository, tested_sha=tested_sha,
        source=source, mode=mode, status=status, facts=normalized,
        aggregate_pending=any(f.aggregate_pending for f in normalized), reason_codes=tuple(sorted(reasons)),
    )
    if len(serialize_validation_failure_record(result).encode()) > MAX_SERIALIZED_BYTES:
        raise ValidationFailureError("serialized record exceeds the bounded size")
    return result


def serialize_validation_failure_record(record: ValidationFailureRecord) -> str:
    if type(record) is not ValidationFailureRecord: raise TypeError("record must be exact ValidationFailureRecord")
    payload = {
        "schema_version": record.schema_version, "repository": record.repository, "tested_sha": record.tested_sha,
        "source": record.source.value, "mode": record.mode.value, "status": record.status.value,
        "facts": [_fact_payload(f) for f in record.facts], "aggregate_pending": record.aggregate_pending,
        "reason_codes": list(record.reason_codes), "execution_authorized": False, "merge_authorized": False,
        "repair_authorized": False, "side_effects_performed": False,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def validation_failure_record_id(record: ValidationFailureRecord) -> str:
    digest = hashlib.sha256(b"agent-os-validation-failure:v1\0" + serialize_validation_failure_record(record).encode()).hexdigest()
    return f"validation-failure:{digest}"
