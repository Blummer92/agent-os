"""Additive #398/#407 typed-subject approval successor; pure and non-authorizing."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from instructional_workflow_contracts.common import ValidationStatus
from instructional_workflow_contracts.live_operation_subject import (
    CONTRACT_ID,
    SUBJECT_ID_PREFIX,
    validate_live_operation_subject,
)

# Compatibility name; #1975 serializes CONTRACT_ID as contract_version.
INSTRUCTIONAL_LIVE_SUBJECT_SCHEMA_VERSION = CONTRACT_ID
INSTRUCTIONAL_LIVE_SUBJECT_KIND = "instructional-materials-live-operation"


@dataclass(frozen=True, slots=True)
class TypedSubjectReference:
    subject_kind: str
    subject_schema_version: str
    subject_id: str

    def __post_init__(self) -> None:
        if self.subject_kind != INSTRUCTIONAL_LIVE_SUBJECT_KIND:
            raise ValueError("unsupported typed approval subject kind")
        if self.subject_schema_version != CONTRACT_ID:
            raise ValueError("unsupported typed approval schema version")
        object.__setattr__(self, "subject_id", _canonical_subject_id(self.subject_id))


def _canonical_subject_id(value: object) -> str:
    if type(value) is str and value.startswith(SUBJECT_ID_PREFIX):
        digest = value[len(SUBJECT_ID_PREFIX):]
        if len(digest) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in digest):
            return SUBJECT_ID_PREFIX + digest.lower()
    raise ValueError("typed approval subject_id is malformed")


def validate_typed_subject_reference(subject: object) -> TypedSubjectReference:
    if not isinstance(subject, Mapping):
        raise TypeError("typed approval subject must be the complete subject object")
    if type(subject) is not dict:
        raise ValueError("typed approval subject must be a plain dict")
    try:
        result = validate_live_operation_subject(subject)
    except Exception:
        raise ValueError("typed approval subject validation failed") from None
    if result.status != ValidationStatus.VALID or result.record is None:
        # Codes are bounded by count and length; do not propagate input details.
        reasons = ",".join(code[:64] for code in result.reason_codes[:4])
        raise ValueError("typed approval subject is invalid: " + reasons)
    record = result.record
    # The closed #1975 input has no caller-supplied ID or kind. The canonical
    # validator rejects either extra field and binds identity in its record.
    subject_id = _canonical_subject_id(record.record_id)
    payload_id = next((value for key, value in record.payload.items if key == "subject_id"), None)
    if _canonical_subject_id(payload_id) != subject_id:
        raise ValueError("typed approval subject_id does not match the validated record")
    return TypedSubjectReference(
        INSTRUCTIONAL_LIVE_SUBJECT_KIND, record.contract_version, subject_id
    )
