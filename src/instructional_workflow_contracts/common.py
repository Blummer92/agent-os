"""Pure shared mechanics for bounded instructional workflow contracts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

MAX_INPUT_BYTES = 64 * 1024
MAX_RESULT_BYTES = 16 * 1024
MAX_STRING_LENGTH = 512
MAX_DEPENDENCY_KEYS = 128
MAX_BLOCKERS = 32
MAX_REASONS = 32
MAX_REFERENCES = 64
MAX_NESTING_DEPTH = 8
MAX_DETAIL_LENGTH = 500

FINGERPRINT_ALGORITHM = "sha256"
SUPPORTED_STATUSES = (
    "valid",
    "invalid",
    "blocked",
    "stale",
    "manual-review-required",
)

FORBIDDEN_IMPORT_PREFIXES = (
    "requests",
    "httpx",
    "urllib.request",
    "subprocess",
    "importlib",
    "notion",
    "google",
    "workflow_scheduler",
    "navigation_registry",
    "sentence_transformers",
    "transformers",
    "torch",
    "paddle",
    "jsonschema",
    "pydantic",
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_REASON_RE = re.compile(
    r"^(?:source|identity|ownership|readiness|authority|handoff|dependency|routing|manual-review)-[a-z0-9][a-z0-9._-]{0,110}$"
)
_DEPENDENCY_KEY_RE = re.compile(
    r"^[a-z0-9][a-z0-9_-]*(?:\.[a-z0-9][a-z0-9_-]*)+$"
)
_ALGORITHM_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE_TEXT_RE = re.compile(
    r"(?:<script\b|javascript:|\$\{\{|\{\{\s*secrets\.|__import__\s*\(|(?:eval|exec)\s*\(|os\.system\s*\()",
    re.IGNORECASE,
)
_SECRET_KEY_RE = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|client[_-]?secret|private[_-]?key|credential|oauth)(?:$|[_-])",
    re.IGNORECASE,
)


class ValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    BLOCKED = "blocked"
    STALE = "stale"
    MANUAL_REVIEW_REQUIRED = "manual-review-required"


class ContractValidationError(ValueError):
    """Bounded validation failure with a finite reason code."""

    def __init__(self, reason_code: str, detail: str) -> None:
        validate_reason_code(reason_code)
        self.reason_code = reason_code
        self.detail = sanitize_detail(detail)
        super().__init__(self.detail)


@dataclass(frozen=True, slots=True)
class AuthorityEvidence:
    execution_authorized: Literal[False] = field(default=False, init=False)
    external_write_authorized: Literal[False] = field(default=False, init=False)
    production_authorized: Literal[False] = field(default=False, init=False)
    publication_authorized: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class ContractReference:
    system: str
    stable_id: str
    exact_location: str
    verification_evidence: str

    def __post_init__(self) -> None:
        validate_stable_id(self.system, "reference system")
        validate_stable_id(self.stable_id, "reference stable_id")
        validate_text(self.exact_location, "reference exact_location")
        validate_text(self.verification_evidence, "reference verification_evidence")


@dataclass(frozen=True, slots=True)
class FrozenObject:
    items: tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class FrozenArray:
    items: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class ValidatedRecord:
    contract_version: str
    record_id: str
    record_revision: int
    fingerprint_algorithm: str
    fingerprint: str
    payload: FrozenObject
    authority: AuthorityEvidence = field(default_factory=AuthorityEvidence)

    def __post_init__(self) -> None:
        validate_version(self.contract_version)
        validate_stable_id(self.record_id, "record_id")
        validate_revision(self.record_revision)
        validate_algorithm(self.fingerprint_algorithm)
        validate_sha256(self.fingerprint, "record fingerprint")
        if type(self.payload) is not FrozenObject:
            raise TypeError("payload must be FrozenObject")
        if canonical_size(self.payload) > MAX_RESULT_BYTES:
            raise ValueError("validated record exceeds result-size bound")

    def to_dict(self) -> dict[str, Any]:
        value = thaw_json(self.payload)
        if type(value) is not dict:
            raise TypeError("record payload must thaw to dict")
        return value


@dataclass(frozen=True, slots=True)
class ValidationResult:
    status: ValidationStatus
    record: ValidatedRecord | None
    reason_codes: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    details: tuple[str, ...] = ()
    authority: AuthorityEvidence = field(default_factory=AuthorityEvidence)

    def __post_init__(self) -> None:
        if type(self.status) is not ValidationStatus:
            raise TypeError("status must be ValidationStatus")
        reasons = canonical_reason_codes(self.reason_codes, MAX_REASONS)
        blockers = canonical_reason_codes(self.blockers, MAX_BLOCKERS)
        details = tuple(sanitize_detail(item) for item in self.details[:MAX_REASONS])
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "details", details)
        if self.status is ValidationStatus.INVALID and self.record is not None:
            raise ValueError("invalid results cannot include a validated record")
        if self.status is ValidationStatus.VALID and (reasons or blockers):
            raise ValueError("valid results cannot include reasons or blockers")
        if self.status is ValidationStatus.BLOCKED and not blockers:
            raise ValueError("blocked results require blockers")
        result_payload = {
            "status": self.status.value,
            "reason_codes": list(reasons),
            "blockers": list(blockers),
            "details": list(details),
            "record_fingerprint": None if self.record is None else self.record.fingerprint,
            "execution_authorized": False,
            "external_write_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
        }
        if canonical_size(result_payload) > MAX_RESULT_BYTES:
            raise ValueError("validation result exceeds result-size bound")


def validate_text(value: object, name: str, *, max_length: int = MAX_STRING_LENGTH) -> str:
    if type(value) is not str:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in string")
    if not value or len(value) > max_length:
        raise ContractValidationError("handoff-invalid", f"{name} length is outside bounds")
    if _CONTROL_RE.search(value):
        raise ContractValidationError("handoff-invalid", f"{name} contains control characters")
    if _UNSAFE_TEXT_RE.search(value):
        raise ContractValidationError("handoff-invalid", f"{name} contains an unsafe executable pattern")
    return value


def validate_stable_id(value: object, name: str = "stable_id") -> str:
    text = validate_text(value, name, max_length=128)
    if not _ID_RE.fullmatch(text):
        raise ContractValidationError("identity-invalid", f"{name} is malformed")
    return text


def validate_version(value: object) -> str:
    text = validate_text(value, "contract_version", max_length=64)
    if not _VERSION_RE.fullmatch(text):
        raise ContractValidationError("handoff-version-unsupported", "contract_version is malformed")
    return text


def validate_revision(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ContractValidationError("identity-invalid", "record_revision must be a positive built-in integer")
    return value


def validate_reason_code(value: object) -> str:
    text = validate_text(value, "reason code", max_length=128)
    if not _REASON_RE.fullmatch(text):
        raise ValueError("reason code is outside the canonical namespaces")
    return text


def validate_dependency_key(value: object) -> str:
    text = validate_text(value, "dependency key", max_length=128)
    if not _DEPENDENCY_KEY_RE.fullmatch(text):
        raise ContractValidationError("dependency-invalid", "dependency key is malformed")
    return text


def validate_algorithm(value: object) -> str:
    text = validate_text(value, "fingerprint algorithm", max_length=32)
    if not _ALGORITHM_RE.fullmatch(text):
        raise ContractValidationError("handoff-invalid", "fingerprint algorithm is malformed")
    return text


def validate_sha256(value: object, name: str) -> str:
    text = validate_text(value, name, max_length=64)
    if not _SHA256_RE.fullmatch(text):
        raise ContractValidationError("handoff-invalid", f"{name} must be a lowercase SHA-256 hex digest")
    return text


def validate_timestamp(value: object, name: str) -> str:
    text = validate_text(value, name, max_length=20)
    if not _TIMESTAMP_RE.fullmatch(text):
        raise ContractValidationError("handoff-invalid", f"{name} must use YYYY-MM-DDTHH:MM:SSZ")
    return text


def is_secret_like_key(key: object) -> bool:
    return type(key) is str and bool(_SECRET_KEY_RE.search(key))


def validate_and_normalize_json(value: object, *, max_bytes: int = MAX_INPUT_BYTES) -> Any:
    normalized = _normalize_json(value, path="$", depth=0)
    if len(_canonical_json_bytes_unchecked(normalized)) > max_bytes:
        raise ContractValidationError("handoff-oversized", "input exceeds the total serialized-size bound")
    return normalized


def _normalize_json(value: object, *, path: str, depth: int) -> Any:
    if depth > MAX_NESTING_DEPTH:
        raise ContractValidationError("handoff-oversized", "input exceeds the nesting-depth bound")
    if value is None or type(value) is bool or type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ContractValidationError("handoff-invalid", f"{path} contains a non-finite float")
        return value
    if type(value) is str:
        return validate_text(value, path)
    if type(value) is list:
        return [
            _normalize_json(item, path=f"{path}[{index}]", depth=depth + 1)
            for index, item in enumerate(value)
        ]
    if type(value) is dict:
        keys = list(value.keys())
        if any(type(key) is not str for key in keys):
            raise ContractValidationError("handoff-wrong-type", f"{path} keys must be built-in strings")
        normalized: dict[str, Any] = {}
        for key in sorted(keys):
            validate_text(key, f"{path} key", max_length=128)
            if is_secret_like_key(key):
                raise ContractValidationError("authority-secret-field", f"{path} contains a secret-like key")
            normalized[key] = _normalize_json(value[key], path=f"{path}.{key}", depth=depth + 1)
        return normalized
    raise ContractValidationError(
        "handoff-wrong-type",
        f"{path} must use exact built-in JSON-compatible types",
    )


def canonical_json_bytes(value: object) -> bytes:
    built_in = (
        thaw_json(value)
        if type(value) in {FrozenObject, FrozenArray}
        else _normalize_json(value, path="$", depth=0)
    )
    return _canonical_json_bytes_unchecked(built_in)


def _canonical_json_bytes_unchecked(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_size(value: object) -> int:
    return len(canonical_json_bytes(value))


def sha256_hex(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def freeze_json(value: object) -> Any:
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if type(value) is list:
        return FrozenArray(tuple(freeze_json(item) for item in value))
    if type(value) is dict:
        return FrozenObject(tuple((key, freeze_json(value[key])) for key in sorted(value)))
    raise TypeError("freeze_json requires normalized built-in JSON values")


def thaw_json(value: object) -> Any:
    if type(value) is FrozenObject:
        return {key: thaw_json(item) for key, item in value.items}
    if type(value) is FrozenArray:
        return [thaw_json(item) for item in value.items]
    if value is None or type(value) in {bool, int, float, str}:
        return value
    raise TypeError("unsupported frozen JSON value")


def canonical_strings(
    values: object,
    *,
    name: str,
    maximum: int,
    validator: Any = validate_text,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if type(values) is not list and type(values) is not tuple:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in sequence")
    if len(values) > maximum:
        raise ContractValidationError("handoff-oversized", f"{name} exceeds its collection bound")
    checked: list[str] = []
    for value in values:
        checked.append(validator(value))
    if not allow_empty and not checked:
        raise ContractValidationError("handoff-invalid", f"{name} cannot be empty")
    if len(set(checked)) != len(checked):
        raise ContractValidationError("handoff-duplicate", f"{name} contains duplicates")
    return tuple(sorted(checked))


def canonical_reason_codes(values: object, maximum: int = MAX_REASONS) -> tuple[str, ...]:
    return canonical_strings(
        values,
        name="reason codes",
        maximum=maximum,
        validator=validate_reason_code,
    )


def sanitize_detail(value: object) -> str:
    if type(value) is not str:
        return "validation detail unavailable"
    cleaned = _CONTROL_RE.sub(" ", value)
    cleaned = _UNSAFE_TEXT_RE.sub("[redacted]", cleaned)
    return cleaned[:MAX_DETAIL_LENGTH]


def resolve_status(
    reason_codes: object,
    blockers: object = (),
    *,
    stale: bool = False,
    manual_review: bool = False,
) -> ValidationStatus:
    reasons = canonical_reason_codes(reason_codes, MAX_REASONS)
    blocker_codes = canonical_reason_codes(blockers, MAX_BLOCKERS)
    if any(_is_invalid_reason(code) for code in (*reasons, *blocker_codes)):
        return ValidationStatus.INVALID
    if blocker_codes or any("blocked" in code or "conflict" in code for code in reasons):
        return ValidationStatus.BLOCKED
    if stale or any("stale" in code for code in reasons):
        return ValidationStatus.STALE
    if manual_review or any(code.startswith("manual-review-") for code in reasons):
        return ValidationStatus.MANUAL_REVIEW_REQUIRED
    return ValidationStatus.VALID


def _is_invalid_reason(code: str) -> bool:
    return any(
        token in code
        for token in (
            "invalid",
            "malformed",
            "unsupported",
            "unknown-field",
            "wrong-type",
            "duplicate",
            "secret-field",
            "oversized",
        )
    )
