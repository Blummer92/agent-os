"""Offline-first, idempotent Drive asset writer contract.

No Google client is imported here. Live execution requires a separately authorized
adapter implementing DriveClient.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Protocol

MAX_REFERENCE = 512


class Representation(str, Enum):
    ORIGINAL = "ORIGINAL"
    NORMALIZED = "NORMALIZED"


class WriteState(str, Enum):
    DRY_RUN = "DRY_RUN"
    PRECHECK_FAILED = "PRECHECK_FAILED"
    CREATED = "CREATED"
    RECONCILED_EXISTING = "RECONCILED_EXISTING"
    VERIFIED = "VERIFIED"
    AMBIGUOUS_WRITE_RESULT = "AMBIGUOUS_WRITE_RESULT"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class DriveAssetWriteRequest:
    intake_reference: str
    representation: Representation
    local_reference: str
    content_sha256: str
    mime_type: str
    parent_folder_id: str
    routing_state: str
    teacher_confirmed: bool
    destination_current: bool
    dry_run: bool = True


@dataclass(frozen=True, slots=True)
class DriveFileEvidence:
    file_id: str
    parent_folder_id: str
    mime_type: str
    content_sha256: str
    operation_key: str


@dataclass(frozen=True, slots=True)
class DriveAssetWriteResult:
    operation_key: str | None
    state: WriteState
    dry_run: bool
    file_id: str | None
    parent_folder_id: str | None
    mime_type: str | None
    content_sha256: str | None
    reason_codes: tuple[str, ...]
    readback_verified: bool = False
    external_write_performed: bool = False
    approval_authorized: bool = False
    classroom_readiness_authorized: bool = False
    publication_authorized: bool = False
    production_authorized: bool = False


class DriveClient(Protocol):
    def find_by_operation_key(self, operation_key: str) -> tuple[DriveFileEvidence, ...]: ...
    def reserve_file_id(self) -> str: ...
    def create_file(self, *, file_id: str, request: DriveAssetWriteRequest, operation_key: str) -> None: ...
    def fetch_file(self, file_id: str) -> DriveFileEvidence | None: ...


def operation_key_for(request: DriveAssetWriteRequest) -> str:
    material = "\n".join((request.intake_reference, request.representation.value, request.content_sha256.lower(), request.parent_folder_id))
    return sha256(material.encode("utf-8")).hexdigest()


def write_asset(request: DriveAssetWriteRequest, client: DriveClient | None = None) -> DriveAssetWriteResult:
    """Validate, dry-run, reconcile, or write one teacher-confirmed asset.

    Dry-run performs zero client calls. Non-dry execution requires an injected
    client; this module itself has no live Google dependency.
    """
    reason = _validate(request)
    if reason is not None:
        return _result(request, None, WriteState.PRECHECK_FAILED, (reason,), request_valid=False)

    key = operation_key_for(request)
    if request.dry_run:
        return _result(request, key, WriteState.DRY_RUN, ("drive-write-dry-run-valid",), request_valid=True)
    if client is None:
        return _result(request, key, WriteState.PRECHECK_FAILED, ("drive-client-required",), request_valid=True)

    existing = client.find_by_operation_key(key)
    if len(existing) > 1:
        return _result(request, key, WriteState.PRECHECK_FAILED, ("drive-conflicting-existing-identity",), request_valid=True)
    if existing:
        candidate = existing[0]
        if not _matches(candidate, request, key):
            return _result(request, key, WriteState.PRECHECK_FAILED, ("drive-existing-evidence-mismatch",), request_valid=True)
        evidence = client.fetch_file(candidate.file_id)
        if evidence is None or not _matches(evidence, request, key):
            return _result(request, key, WriteState.PRECHECK_FAILED, ("drive-existing-readback-mismatch",), file_id=candidate.file_id, request_valid=True)
        return _verified(request, key, evidence, WriteState.RECONCILED_EXISTING, external_write=False)

    file_id = client.reserve_file_id()
    try:
        client.create_file(file_id=file_id, request=request, operation_key=key)
    except Exception:
        # A create may have succeeded despite a transport failure. Reconcile first.
        reconciled = client.find_by_operation_key(key)
        if len(reconciled) == 1 and _matches(reconciled[0], request, key):
            evidence = client.fetch_file(reconciled[0].file_id)
            if evidence is not None and _matches(evidence, request, key):
                return _verified(request, key, evidence, WriteState.RECONCILED_EXISTING, external_write=True)
        return _result(request, key, WriteState.AMBIGUOUS_WRITE_RESULT, ("drive-create-outcome-ambiguous",), external_write=True, request_valid=True)

    evidence = client.fetch_file(file_id)
    if evidence is None or not _matches(evidence, request, key):
        return _result(request, key, WriteState.FAILED, ("drive-readback-mismatch",), file_id=file_id, external_write=True, request_valid=True)
    return _verified(request, key, evidence, WriteState.VERIFIED, external_write=True)


def _validate(request: object) -> str | None:
    if type(request) is not DriveAssetWriteRequest:
        return "drive-invalid-request"
    if request.routing_state != "CONFIRMED" or request.teacher_confirmed is not True:
        return "drive-routing-not-confirmed"
    if request.destination_current is not True:
        return "drive-destination-stale"
    if not all(_text(v) for v in (request.intake_reference, request.local_reference, request.mime_type, request.parent_folder_id)):
        return "drive-required-reference-missing"
    if type(request.content_sha256) is not str or len(request.content_sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in request.content_sha256):
        return "drive-invalid-content-sha256"
    if type(request.representation) is not Representation or type(request.dry_run) is not bool:
        return "drive-invalid-request"
    return None


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= MAX_REFERENCE


def _matches(evidence: DriveFileEvidence, request: DriveAssetWriteRequest, key: str) -> bool:
    return (type(evidence) is DriveFileEvidence and evidence.parent_folder_id == request.parent_folder_id and evidence.mime_type == request.mime_type and evidence.content_sha256.lower() == request.content_sha256.lower() and evidence.operation_key == key and _text(evidence.file_id))


def _result(request, key, state, reasons, *, file_id=None, external_write=False, request_valid=False):
    if request_valid:
        return DriveAssetWriteResult(key, state, request.dry_run, file_id, request.parent_folder_id, request.mime_type, request.content_sha256.lower(), reasons, False, external_write)
    return DriveAssetWriteResult(key, state, True, file_id, None, None, None, reasons, False, external_write)


def _verified(request, key, evidence, state, *, external_write):
    return DriveAssetWriteResult(key, state, request.dry_run, evidence.file_id, evidence.parent_folder_id, evidence.mime_type, evidence.content_sha256.lower(), ("drive-write-verified",), True, external_write)
