"""Additive #398/#407 typed-subject approval successor; pure and non-authorizing."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from instructional_workflow_contracts.common import ValidationStatus
from instructional_workflow_contracts.live_operation_subject import (
    CONTRACT_ID as INSTRUCTIONAL_LIVE_SUBJECT_SCHEMA_VERSION,
    validate_live_operation_subject,
)

TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION = "1.2"
TYPED_SUBJECT_PROJECTION_SCHEMA_VERSION = "1.1"
INSTRUCTIONAL_LIVE_SUBJECT_KIND = "instructional-materials-live-operation"


@dataclass(frozen=True, slots=True)
class TypedSubjectReference:
    subject_kind: str
    subject_schema_version: str
    subject_id: str

    def __post_init__(self) -> None:
        if self.subject_kind != INSTRUCTIONAL_LIVE_SUBJECT_KIND:
            raise ValueError("unsupported typed approval subject kind")
        if self.subject_schema_version != INSTRUCTIONAL_LIVE_SUBJECT_SCHEMA_VERSION:
            raise ValueError("unsupported typed approval schema version")
        prefix = "instructional-live-operation-subject:"
        if not isinstance(self.subject_id, str) or not self.subject_id.startswith(prefix):
            raise ValueError("typed approval subject_id is malformed")
        digest = self.subject_id[len(prefix):]
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("typed approval subject_id is malformed")


def validate_typed_subject_reference(subject: object) -> TypedSubjectReference:
    if not isinstance(subject, Mapping):
        raise TypeError("typed approval subject must be the complete subject object")
    result = validate_live_operation_subject(dict(subject))
    if result.status is not ValidationStatus.VALID or result.record is None:
        raise ValueError("typed approval subject is invalid: " + ",".join((*result.reason_codes, *result.details)))
    return TypedSubjectReference(INSTRUCTIONAL_LIVE_SUBJECT_KIND, result.record.contract_version, result.record.record_id)
