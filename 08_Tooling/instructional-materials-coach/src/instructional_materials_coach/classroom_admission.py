"""Classroom-ready admission predicate for canonical IMC build receipts (#3259 D8).

D8 (approved in principle): classroom-ready requires a canonical
``imc-build-receipt-v1`` build record; direct ChatGPT/DOCX output is
non-authoritative and can bypass the governed Notion -> Agent OS -> Drive
production path, so it must never be admitted as classroom-ready by the
repository.

This module is a pure decision function in the established seam pattern
(#2761 ``MainHealthAdmission``). It consumes one build receipt mapping as
produced by ``build_receipt.build_receipt_record`` and reports whether the
evidence admits classroom-ready. It never performs network or filesystem I/O,
never trusts caller authority claims (the receipt's ``authority`` block is
ignored entirely — admission rests only on verifiable evidence fields), never
grants execution/production/classroom authority, and never mutates its input.
A ``NOT_ADMITTED`` verdict is terminal for the admission question; it directs
the caller back to the canonical production path, never to a bypass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Any, Literal, Mapping

from .build_receipt import BUILD_RECEIPT_CONTRACT

CLASSROOM_ADMISSION_SCHEMA_NAME = "agent-os-classroom-admission"
CLASSROOM_ADMISSION_SCHEMA_VERSION = "1.0"

TERMINAL_QA_VERIFIED = "verified"


class ClassroomAdmission(str, Enum):
    """Whether the build receipt evidence admits classroom-ready."""

    #: All three evidence conditions hold: contract version matches
    #: ``imc-build-receipt-v1``, the build succeeded, and terminal QA state is
    #: ``verified``. The evidence admits classroom-ready; no authority is
    #: granted by this verdict — downstream governors still own authorization.
    ADMITTED = "admitted"
    #: One or more evidence conditions failed, or the receipt was malformed.
    #: Fail-closed: the caller must not treat the artifact as classroom-ready.
    NOT_ADMITTED = "not-admitted"


class ClassroomAdmissionReason(str, Enum):
    """Finite reason codes explaining one deterministic classification."""

    #: All evidence conditions hold.
    EVIDENCE_COMPLETE = "classroom.evidence-complete"
    #: ``contract_version`` is missing or is not ``imc-build-receipt-v1``.
    CONTRACT_VERSION_MISMATCH = "classroom.contract-version-mismatch"
    #: ``succeeded`` is missing or is not exactly ``True``.
    BUILD_NOT_SUCCEEDED = "classroom.build-not-succeeded"
    #: ``terminal_qa_state`` is missing or is not ``verified``.
    TERMINAL_QA_NOT_VERIFIED = "classroom.terminal-qa-not-verified"
    #: The receipt is not a mapping, or a required evidence field has an
    #: unexpected type. Fail-closed on malformed input.
    RECEIPT_MALFORMED = "classroom.receipt-malformed"


@dataclass(frozen=True, slots=True, kw_only=True)
class ClassroomAdmissionResult:
    schema_name: str = CLASSROOM_ADMISSION_SCHEMA_NAME
    schema_version: str = CLASSROOM_ADMISSION_SCHEMA_VERSION
    status: ClassroomAdmission = ClassroomAdmission.NOT_ADMITTED
    result_id: str = ""
    reason_codes: tuple[ClassroomAdmissionReason, ...] = ()
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    production_authorized: Literal[False] = field(default=False, init=False)
    classroom_ready_granted: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != CLASSROOM_ADMISSION_SCHEMA_NAME:
            raise ValueError("unsupported classroom admission schema name")
        if self.schema_version != CLASSROOM_ADMISSION_SCHEMA_VERSION:
            raise ValueError("unsupported classroom admission schema version")
        if type(self.status) is not ClassroomAdmission:
            raise TypeError("status must be an exact ClassroomAdmission")
        if type(self.result_id) is not str or not self.result_id.startswith(
            "classroom-admission:"
        ):
            raise ValueError("result_id must carry the classroom-admission prefix")
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty exact tuple")
        if any(type(item) is not ClassroomAdmissionReason for item in self.reason_codes):
            raise TypeError("reason_codes contain an invalid value")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes must be unique")
        if tuple(sorted(item.value for item in self.reason_codes)) != tuple(
            item.value for item in self.reason_codes
        ):
            raise ValueError("reason_codes must be sorted")


def _result(
    status: ClassroomAdmission,
    reason_codes: tuple[ClassroomAdmissionReason, ...],
) -> ClassroomAdmissionResult:
    digest = sha256(
        (
            "agent-os-classroom-admission:v1\0"
            f"{status.value}\0" + ",".join(sorted(reason.value for reason in reason_codes))
        ).encode("utf-8")
    ).hexdigest()
    return ClassroomAdmissionResult(
        status=status,
        result_id=f"classroom-admission:{digest}",
        reason_codes=tuple(sorted(reason_codes, key=lambda reason: reason.value)),
    )


def classify_classroom_admission(
    receipt: Mapping[str, Any],
) -> ClassroomAdmissionResult:
    """Decide classroom-ready admission from one canonical build receipt.

    The receipt must be a mapping as produced by
    ``build_receipt.build_receipt_record``. Admission requires ALL of:
    ``contract_version == "imc-build-receipt-v1"``,
    ``succeeded is True``,
    ``terminal_qa_state == "verified"``.

    The receipt's ``authority`` block is deliberately ignored: caller claims
    (including any ``classroom_ready`` flag a caller might assert) never
    influence admission. Only the three verifiable evidence fields decide.

    Fail-closed: malformed receipts, missing fields, wrong types, or any
    single failed condition yields ``NOT_ADMITTED`` with the specific reason
    codes. The input mapping is never mutated.
    """
    if not isinstance(receipt, Mapping):
        return _result(
            ClassroomAdmission.NOT_ADMITTED,
            (ClassroomAdmissionReason.RECEIPT_MALFORMED,),
        )

    failures: list[ClassroomAdmissionReason] = []

    contract_version = receipt.get("contract_version")
    if type(contract_version) is not str or contract_version != BUILD_RECEIPT_CONTRACT:
        failures.append(ClassroomAdmissionReason.CONTRACT_VERSION_MISMATCH)

    succeeded = receipt.get("succeeded")
    if type(succeeded) is not bool or succeeded is not True:
        failures.append(ClassroomAdmissionReason.BUILD_NOT_SUCCEEDED)

    terminal_qa_state = receipt.get("terminal_qa_state")
    if type(terminal_qa_state) is not str or terminal_qa_state != TERMINAL_QA_VERIFIED:
        failures.append(ClassroomAdmissionReason.TERMINAL_QA_NOT_VERIFIED)

    if failures:
        return _result(ClassroomAdmission.NOT_ADMITTED, tuple(failures))
    return _result(
        ClassroomAdmission.ADMITTED,
        (ClassroomAdmissionReason.EVIDENCE_COMPLETE,),
    )


def serialize_classroom_admission(
    result: ClassroomAdmissionResult,
) -> dict[str, object]:
    """Serialize one admission result with integrity binding."""
    if type(result) is not ClassroomAdmissionResult:
        raise TypeError("result must be an exact ClassroomAdmissionResult")
    payload = {
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "status": result.status.value,
        "reason_codes": [reason.value for reason in result.reason_codes],
        "authoritative": False,
        "execution_authorized": False,
        "production_authorized": False,
        "classroom_ready_granted": False,
        "side_effects_performed": False,
    }
    expected = _result(result.status, result.reason_codes).result_id
    if result.result_id != expected:
        raise ValueError("classroom admission result ID mismatch")
    serialized = dict(payload)
    serialized["result_id"] = result.result_id
    return serialized


def classroom_admission_result_id(result: ClassroomAdmissionResult) -> str:
    return str(serialize_classroom_admission(result)["result_id"])


__all__ = [
    "CLASSROOM_ADMISSION_SCHEMA_NAME",
    "CLASSROOM_ADMISSION_SCHEMA_VERSION",
    "TERMINAL_QA_VERIFIED",
    "ClassroomAdmission",
    "ClassroomAdmissionReason",
    "ClassroomAdmissionResult",
    "classify_classroom_admission",
    "classroom_admission_result_id",
    "serialize_classroom_admission",
]
