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
MAX_JSON_ITEMS = 4096

FINGERPRINT_ALGORITHM = "sha256"
# Consumed by the AST import regression, not a Python runtime sandbox.
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
    r"^(?:source|identity|ownership|readiness|authority|handoff|dependency|routing|manual-review|material|artifact|asset|template|destination|quality|capacity|lp)-[a-z0-9][a-z0-9._-]{0,110}$"
)
_DEPENDENCY_KEY_RE = re.compile(
    r"^[a-z0-9][a-z0-9_-]*(?:\.[a-z0-9][a-z0-9_-]*)+$"
)
_ALGORITHM_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE_TEXT_RE = re.compile(
    r"(?:<script\b|javascript:|\$\{\{|\{\{\s*secrets\.|__import__\s*\(|(?:eval|exec)\s*\(|os\.system\s*\()",
    re.IGNORECASE,
)
_SECRET_LABEL = (
    r"(?:api[_-]?keys?|access[_-]?tokens?|refresh[_-]?tokens?|passwords?|passwds?|"
    r"secrets?|client[_-]?secrets?|private[_-]?keys?|credentials?|oauth)"
)
_SECRET_KEY_RE = re.compile(
    rf"(?:^|[_-]){_SECRET_LABEL}(?:$|[_-])|^(?:tokens?|bearer|sessions?)$",
    re.IGNORECASE,
)
# A diagnostic may contain a serialized string, not a parseable document.
# After a credential label, discard the bounded suffix rather than guessing
# where a value ends inside nested or multiply escaped quotes.
_SECRET_DETAIL_RE = re.compile(
    rf"(?:(?<![\w-])(?:[\w-]*?[_-])?(?:{_SECRET_LABEL}|tokens?|sessions?|bearer|authorization)"
    r"(?:\\*[\"'])?\s*[:=]|\bBearer\s+).*$",
    re.IGNORECASE,
)

_INVALID_REASON_CODES = frozenset(
    {
        "authority-invalid",
        "authority-secret-field",
        "capacity-exceeded",
        "dependency-invalid",
        "dependency-wrong-type",
        "handoff-duplicate",
        "handoff-invalid",
        "handoff-oversized",
        "handoff-unknown-field",
        "handoff-version-unsupported",
        "handoff-wrong-type",
        "identity-duplicate",
        "identity-invalid",
        "ownership-owner-conflict",
        "routing-invalid",
        "source-invalid",
    }
)
_BLOCKED_REASON_CODES = frozenset({"routing-blocked-dependency", "source-conflicting"})
_STALE_REASON_CODES = frozenset({"source-stale"})
_MANUAL_REVIEW_REASON_CODES = frozenset(
    {"manual-review-inspection", "source-provisional", "source-unavailable"}
)
_KNOWN_REASON_CODES = (
    _INVALID_REASON_CODES
    | _BLOCKED_REASON_CODES
    | _STALE_REASON_CODES
    | _MANUAL_REVIEW_REASON_CODES
)


class ValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    BLOCKED = "blocked"
    STALE = "stale"
    MANUAL_REVIEW_REQUIRED = "manual-review-required"


SUPPORTED_STATUSES = tuple(status.value for status in ValidationStatus)


class ContractValidationError(ValueError):
    """Bounded validation failure with a finite reason code."""

    def __init__(self, reason_code: str, detail: str) -> None:
        if _is_reason_code(reason_code):
            self.reason_code = reason_code
            self.detail = sanitize_detail(detail)
        else:
            self.reason_code = "handoff-invalid"
            self.detail = "invalid validation reason code"
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

    def __post_init__(self) -> None:
        _validate_frozen_items(self.items)
        keys: set[str] = set()
        for entry in self.items:
            if type(entry) is not tuple or len(entry) != 2 or type(entry[0]) is not str:
                raise TypeError("frozen JSON object requires string-key pairs")
            key, value = entry
            if key in keys:
                raise ContractValidationError("handoff-duplicate", "frozen JSON object contains duplicate keys")
            keys.add(key)
            _require_frozen_value(value)


@dataclass(frozen=True, slots=True)
class FrozenArray:
    items: tuple[Any, ...]

    def __post_init__(self) -> None:
        _validate_frozen_items(self.items)
        for value in self.items:
            _require_frozen_value(value)


def _validate_frozen_items(items: object) -> None:
    if type(items) is not tuple:
        raise TypeError("frozen JSON items must be an exact tuple")
    if len(items) > MAX_JSON_ITEMS:
        raise ContractValidationError("handoff-oversized", "frozen JSON exceeds the item-count bound")


def _require_frozen_value(value: object) -> None:
    if value is not None and type(value) not in (bool, int, float, str, FrozenObject, FrozenArray):
        raise TypeError("frozen JSON cannot contain mutable or unsupported values")


@dataclass(frozen=True, slots=True)
class ValidatedRecord:
    contract_version: str
    record_id: str
    record_revision: int
    fingerprint_algorithm: str
    fingerprint: str
    payload: FrozenObject
    authority: AuthorityEvidence = field(default_factory=AuthorityEvidence, init=False)

    def __post_init__(self) -> None:
        validate_version(self.contract_version)
        validate_stable_id(self.record_id, "record_id")
        validate_revision(self.record_revision)
        if type(self.fingerprint_algorithm) is not str or self.fingerprint_algorithm != FINGERPRINT_ALGORITHM:
            raise ContractValidationError("handoff-invalid", "unsupported record fingerprint algorithm")
        validate_sha256(self.fingerprint, "record fingerprint")
        if type(self.payload) is not FrozenObject:
            raise TypeError("payload must be FrozenObject")
        if type(self.authority) is not AuthorityEvidence:
            raise TypeError("authority must be internal AuthorityEvidence")
        encoded = canonical_json_bytes(self.payload)
        if len(encoded) > MAX_RESULT_BYTES:
            raise ValueError("validated record exceeds result-size bound")
        if self.fingerprint != _sha256_bytes(encoded):
            raise ContractValidationError("handoff-invalid", "record fingerprint does not match its payload")

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
    authority: AuthorityEvidence = field(default_factory=AuthorityEvidence, init=False)

    def __post_init__(self) -> None:
        if type(self.status) is not ValidationStatus:
            raise TypeError("status must be ValidationStatus")
        if self.record is not None and type(self.record) is not ValidatedRecord:
            raise TypeError("record must be ValidatedRecord or None")
        if type(self.reason_codes) is not tuple:
            raise TypeError("reason_codes must be an exact tuple")
        if type(self.blockers) is not tuple:
            raise TypeError("blockers must be an exact tuple")
        if type(self.details) is not tuple:
            raise TypeError("details must be an exact tuple")
        if len(self.details) > MAX_REASONS:
            raise ValueError("details exceed the collection bound")
        reasons = canonical_reason_codes(self.reason_codes, MAX_REASONS)
        blockers = canonical_reason_codes(self.blockers, MAX_BLOCKERS)
        details = tuple(sanitize_detail(item) for item in self.details)
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "details", details)

        if self.status is ValidationStatus.VALID:
            if self.record is None:
                raise ValueError("valid results require a validated record")
            if reasons or blockers:
                raise ValueError("valid results cannot include reasons or blockers")
        elif self.status is ValidationStatus.INVALID:
            if self.record is not None:
                raise ValueError("invalid results cannot include a validated record")
            if not reasons:
                raise ValueError("invalid results require a reason code")
        else:
            if self.record is None:
                raise ValueError("validated non-valid results require a record")
            if self.status is ValidationStatus.BLOCKED and not blockers:
                raise ValueError("blocked results require blockers")

        if self.status is ValidationStatus.STALE and not reasons:
            raise ValueError("stale results require a reason code")
        # Common reason codes have a finite shared precedence. Domain-specific
        # codes are owned by their validators, not by the handoff resolver.
        # Some existing contracts encode manual review in payload/flags or
        # details rather than reason codes; preserve that non-valid outcome.
        reason_set, blocker_set = set(reasons), set(blockers)
        codes = reason_set | blocker_set
        # A domain-specific code must not suppress a known invalid reason.
        if codes and (codes <= _KNOWN_REASON_CODES or codes & _INVALID_REASON_CODES):
            if self.status != _status_from_codes(reason_set, blocker_set):
                raise ContractValidationError("handoff-invalid", "result status does not match its reasons and blockers")

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
    """Check bounded contract text; these patterns are not a security firewall."""
    if type(value) is not str:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in string")
    if not value or len(value) > max_length:
        raise ContractValidationError("handoff-invalid", f"{name} length is outside bounds")
    if _CONTROL_RE.search(value):
        raise ContractValidationError("handoff-invalid", f"{name} contains control characters")
    if _UNSAFE_TEXT_RE.search(value):
        raise ContractValidationError("handoff-invalid", f"{name} contains an unsafe executable pattern")
    return value


def validate_mapping(value: object, name: str) -> dict[str, Any]:
    """Type-check and return the borrowed dict; copy or normalize before editing."""
    if type(value) is not dict:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in mapping")
    return value


def validate_bounded_list(value: object, name: str, maximum: int) -> list[Any]:
    """Check and return the borrowed list; copy or normalize before editing."""
    if type(value) is not list:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in list")
    if len(value) > maximum:
        raise ContractValidationError("handoff-oversized", f"{name} exceeds its collection bound")
    return value


def validate_exact_fields(value: object, expected: frozenset[str], name: str) -> None:
    if type(value) is not dict:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in mapping")
    if len(value) > len(expected):
        raise ContractValidationError("handoff-unknown-field", f"{name} contains unknown fields")
    keys = value.keys()
    if keys != expected:
        if keys - expected:
            raise ContractValidationError("handoff-unknown-field", f"{name} contains unknown fields")
        raise ContractValidationError("handoff-invalid", f"{name} is missing required fields")


def validate_stable_id(value: object, name: str = "stable_id") -> str:
    """Validate a logical identifier, not a filesystem path or a URL segment."""
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


def _is_reason_code(value: object) -> bool:
    return type(value) is str and len(value) <= 128 and _REASON_RE.fullmatch(value) is not None


def validate_reason_code(value: object) -> str:
    """Check shared syntax; each reason registry owns status semantics."""
    if not _is_reason_code(value):
        raise ContractValidationError("handoff-invalid", "reason code is outside the canonical namespaces")
    return value


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


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def validate_timestamp(value: object, name: str) -> str:
    """Validate UTC second precision; leap-second notation is unsupported."""
    text = validate_text(value, name, max_length=20)
    match = _TIMESTAMP_RE.fullmatch(text)
    if match is None:
        raise ContractValidationError("handoff-invalid", f"{name} must use YYYY-MM-DDTHH:MM:SSZ")
    year, month, day, hour, minute, second = (int(part) for part in match.groups())
    days = (31, 29 if _is_leap_year(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    if year < 1 or not 1 <= month <= 12 or not 1 <= day <= days[month - 1]:
        raise ContractValidationError("handoff-invalid", f"{name} is not a real UTC timestamp")
    if hour > 23 or minute > 59 or second > 59:
        raise ContractValidationError("handoff-invalid", f"{name} is not a real UTC timestamp")
    return text


def is_secret_like_key(key: object) -> bool:
    return type(key) is str and bool(_SECRET_KEY_RE.search(key))


@dataclass(slots=True)
class _NormalizationBudget:
    remaining_bytes: int
    remaining_items: int = MAX_JSON_ITEMS

    def consume_bytes(self, size: int) -> None:
        self.remaining_bytes -= size
        if self.remaining_bytes < 0:
            raise ContractValidationError("handoff-oversized", "input exceeds the total serialized-size bound")

    def consume_item(self) -> None:
        self.remaining_items -= 1
        if self.remaining_items < 0:
            raise ContractValidationError("handoff-oversized", "input exceeds the item-count bound")


def validate_and_normalize_json(value: object, *, max_bytes: int = MAX_INPUT_BYTES) -> Any:
    if type(max_bytes) is not int or max_bytes < 1:
        raise TypeError("max_bytes must be a positive built-in integer")
    budget = _NormalizationBudget(min(max_bytes, MAX_INPUT_BYTES))
    return _normalize_json(value, path="$", depth=0, budget=budget)


def _encoded_scalar_size(value: object) -> int:
    return len(
        json.dumps(
            value,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    )


def _normalize_json(
    value: object,
    *,
    path: str,
    depth: int,
    budget: _NormalizationBudget,
) -> Any:
    if depth > MAX_NESTING_DEPTH:
        raise ContractValidationError("handoff-oversized", "input exceeds the nesting-depth bound")
    budget.consume_item()
    if value is None or type(value) is bool or type(value) is int:
        budget.consume_bytes(_encoded_scalar_size(value))
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ContractValidationError("handoff-invalid", f"{path} contains a non-finite float")
        budget.consume_bytes(_encoded_scalar_size(value))
        return value
    if type(value) is str:
        text = validate_text(value, path)
        budget.consume_bytes(_encoded_scalar_size(text))
        return text
    if type(value) is list:
        if len(value) > MAX_JSON_ITEMS:
            raise ContractValidationError("handoff-oversized", "input exceeds the item-count bound")
        budget.consume_bytes(2)
        normalized_list: list[Any] = []
        for index, item in enumerate(value):
            if index:
                budget.consume_bytes(1)
            normalized_list.append(
                _normalize_json(item, path=f"{path}[{index}]", depth=depth + 1, budget=budget)
            )
        return normalized_list
    if type(value) is dict:
        if len(value) > MAX_JSON_ITEMS:
            raise ContractValidationError("handoff-oversized", "input exceeds the item-count bound")
        keys = list(value.keys())
        if any(type(key) is not str for key in keys):
            raise ContractValidationError("handoff-wrong-type", f"{path} keys must be built-in strings")
        budget.consume_bytes(2)
        normalized_dict: dict[str, Any] = {}
        for index, key in enumerate(sorted(keys)):
            if index:
                budget.consume_bytes(1)
            validate_text(key, f"{path} key", max_length=128)
            # Preserve the Coach receipt's canonical negative telemetry, not
            # credential data. No other value, key spelling, or path qualifies.
            negative_credential_telemetry = (
                path == "$.side_effects" and key == "credentials_initialized"
                and value[key] is False
            )
            if is_secret_like_key(key) and not negative_credential_telemetry:
                raise ContractValidationError("authority-secret-field", f"{path} contains a secret-like key")
            budget.consume_bytes(_encoded_scalar_size(key) + 1)
            normalized_dict[key] = _normalize_json(
                value[key], path=f"{path}.{key}", depth=depth + 1, budget=budget
            )
        return normalized_dict
    raise ContractValidationError(
        "handoff-wrong-type",
        f"{path} must use exact built-in JSON-compatible types",
    )


def canonical_json_bytes(value: object) -> bytes:
    """Canonical serialization of validated contract data, not arbitrary JSON."""
    if type(value) in (FrozenObject, FrozenArray):
        value = thaw_json(value)
    return _canonical_json_bytes_unchecked(validate_and_normalize_json(value))


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


def _sha256_bytes(encoded: bytes) -> str:
    return hashlib.sha256(encoded).hexdigest()


def sha256_hex(value: object) -> str:
    """Hash canonical contract JSON; invalid/oversized input is rejected."""
    return _sha256_bytes(canonical_json_bytes(value))


def freeze_json(value: object) -> Any:
    """Freeze already normalized input; use validate_and_normalize_json first."""
    return _freeze_json(value, 0, _NormalizationBudget(MAX_INPUT_BYTES))


def _freeze_json(value: object, depth: int, budget: _NormalizationBudget) -> Any:
    if depth > MAX_NESTING_DEPTH:
        raise ContractValidationError("handoff-oversized", "input exceeds the nesting-depth bound")
    budget.consume_item()
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if type(value) is list:
        values = validate_bounded_list(value, "frozen JSON array", MAX_JSON_ITEMS)
        return FrozenArray(tuple(_freeze_json(item, depth + 1, budget) for item in values))
    if type(value) is dict:
        if len(value) > MAX_JSON_ITEMS:
            raise ContractValidationError("handoff-oversized", "frozen JSON exceeds the item-count bound")
        return FrozenObject(tuple((key, _freeze_json(value[key], depth + 1, budget)) for key in sorted(value)))
    raise TypeError("freeze_json requires normalized built-in JSON values")


def thaw_json(value: object) -> Any:
    return _thaw_json(value, 0, _NormalizationBudget(MAX_INPUT_BYTES))


def _thaw_json(value: object, depth: int, budget: _NormalizationBudget) -> Any:
    if depth > MAX_NESTING_DEPTH:
        raise ContractValidationError("handoff-oversized", "frozen JSON exceeds the nesting-depth bound")
    budget.consume_item()
    if type(value) is FrozenObject:
        return {key: _thaw_json(item, depth + 1, budget) for key, item in value.items}
    if type(value) is FrozenArray:
        return [_thaw_json(item, depth + 1, budget) for item in value.items]
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
    # Redact before truncating so a credential crossing the output boundary
    # cannot leave a partial secret in the result. Work over a bounded prefix.
    cleaned = _CONTROL_RE.sub(" ", value[:MAX_DETAIL_LENGTH * 2])
    cleaned = _SECRET_DETAIL_RE.sub("[redacted]", cleaned)
    cleaned = _UNSAFE_TEXT_RE.sub("[redacted]", cleaned)
    return cleaned[:MAX_DETAIL_LENGTH]


def invalid_result(reason: str, detail: str) -> ValidationResult:
    return ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=(reason,),
        details=(sanitize_detail(detail),),
    )


def resolve_status(
    reason_codes: object,
    blockers: object = (),
    *,
    stale: bool = False,
    manual_review: bool = False,
) -> ValidationStatus:
    reasons = canonical_reason_codes(reason_codes, MAX_REASONS)
    blocker_codes = canonical_reason_codes(blockers, MAX_BLOCKERS)
    reasons_set, blockers_set = set(reasons), set(blocker_codes)
    if (reasons_set | blockers_set) - _KNOWN_REASON_CODES:
        raise ContractValidationError("handoff-invalid", "reason code has no governed status mapping")
    return _status_from_codes(reasons_set, blockers_set, stale=stale, manual_review=manual_review)


def _status_from_codes(
    reasons: set[str], blockers: set[str], *, stale: bool = False, manual_review: bool = False,
) -> ValidationStatus:
    if (reasons | blockers) & _INVALID_REASON_CODES:
        return ValidationStatus.INVALID
    if blockers or reasons & _BLOCKED_REASON_CODES:
        return ValidationStatus.BLOCKED
    if stale or reasons & _STALE_REASON_CODES:
        return ValidationStatus.STALE
    if manual_review or reasons & _MANUAL_REVIEW_REASON_CODES:
        return ValidationStatus.MANUAL_REVIEW_REQUIRED
    return ValidationStatus.VALID
