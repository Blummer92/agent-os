"""Offline-first Notion visual-asset metadata writer contracts.

No Notion SDK is imported. Live execution requires a separately authorized
adapter implementing NotionClient.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Callable, Protocol, TypeVar
from urllib.parse import urlsplit

MAX_REFERENCE = 512
MAX_VALUE = 4000
MAX_RETRIES = 5
MAX_TOTAL_RETRY_DELAY = 120.0

ALLOWED_WORKING_FIELDS = frozenset({
    "asset_id", "asset_title", "asset_type", "alt_text",
    "instructional_purpose", "unit_reference", "concept_reference",
    "material_type", "keywords", "style_family", "reuse_notes",
    "reuse_status", "accessibility_notes", "source_import_notes",
    "ai_metadata_status", "import_version", "drive_file_id", "drive_url",
    "review_needed",
})

ICON_SYSTEM_WORKING_FIELDS = frozenset({
    "icon_name", "meaning", "icon_category", "source_asset_link",
    "reusable_across_units", "reuse_boundary", "reuse_notes",
    "teacher_use_note", "vocabulary_concept_supported", "do_not_confuse_with",
})

SUPPORTED_PROPERTY_TYPES = frozenset({
    "title", "rich_text", "url", "select", "status", "multi_select", "checkbox"
})

_ALLOWED_TYPES = {
    "asset_id": {"title", "rich_text"}, "asset_title": {"title", "rich_text"},
    "asset_type": {"select", "rich_text"}, "alt_text": {"rich_text"},
    "instructional_purpose": {"rich_text"}, "unit_reference": {"rich_text"},
    "concept_reference": {"rich_text"}, "material_type": {"select", "rich_text"},
    "keywords": {"multi_select", "rich_text"}, "style_family": {"select", "rich_text"},
    "reuse_notes": {"rich_text"}, "reuse_status": {"select", "status", "rich_text"},
    "accessibility_notes": {"rich_text"}, "source_import_notes": {"rich_text"},
    "ai_metadata_status": {"select", "status", "rich_text"},
    "import_version": {"rich_text"}, "drive_file_id": {"rich_text"},
    "drive_url": {"url"}, "review_needed": {"checkbox", "select", "status"},
}

_ICON_ALLOWED_TYPES = {
    "icon_name": {"title", "rich_text"},
    "meaning": {"rich_text"},
    "icon_category": {"select", "rich_text"},
    "source_asset_link": {"url"},
    "reusable_across_units": {"checkbox"},
    "reuse_boundary": {"rich_text"},
    "reuse_notes": {"rich_text"},
    "teacher_use_note": {"rich_text"},
    "vocabulary_concept_supported": {"rich_text"},
    "do_not_confuse_with": {"rich_text"},
}

_PROHIBITED_TERMS = (
    "approval", "approved use", "source approved", "readiness", "rights", "privacy",
    "audit", "sharing", "permission", "publication", "production authorized",
    "production route", "source authority", "safe use", "safe-use", "clearance",
    "current review owner", "modeling handoff", "modeling review",
    "unit alignment review needed",
)

MetadataValue = str | bool | tuple[str, ...]
T = TypeVar("T")


class WriteState(str, Enum):
    DRY_RUN = "DRY_RUN"
    PRECHECK_FAILED = "PRECHECK_FAILED"
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    RECONCILED_EXISTING = "RECONCILED_EXISTING"
    AMBIGUOUS_WRITE_RESULT = "AMBIGUOUS_WRITE_RESULT"
    FAILED = "FAILED"


class SyncState(str, Enum):
    DRY_RUN = "DRY_RUN"
    PRECHECK_FAILED = "PRECHECK_FAILED"
    VERIFIED = "VERIFIED"
    PARTIAL_REPAIR_REQUIRED = "PARTIAL_REPAIR_REQUIRED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class PropertyBinding:
    logical_field: str
    property_name: str
    property_type: str


@dataclass(frozen=True, slots=True)
class WorkingMetadata:
    logical_field: str
    value: MetadataValue


@dataclass(frozen=True, slots=True)
class NotionPropertySpec:
    name: str
    property_type: str


@dataclass(frozen=True, slots=True)
class NotionPageEvidence:
    page_id: str
    properties: tuple[tuple[str, MetadataValue], ...]


@dataclass(frozen=True, slots=True)
class NotionAssetWriteRequest:
    data_source_id: str
    asset_id: str
    routing_reference: str
    routing_state: str
    teacher_confirmed: bool
    drive_operation_key: str
    drive_file_id: str
    drive_parent_id: str
    drive_mime_type: str
    drive_content_sha256: str
    drive_state: str
    drive_readback_verified: bool
    bindings: tuple[PropertyBinding, ...]
    working_metadata: tuple[WorkingMetadata, ...] = ()
    dry_run: bool = True
    maximum_retries: int = 2
    maximum_total_retry_delay: float = 30.0


@dataclass(frozen=True, slots=True)
class IconSystemWriteRequest:
    data_source_id: str
    asset_id: str
    icon_name: str
    source_asset_link: str
    routing_reference: str
    routing_state: str
    teacher_confirmed: bool
    reusable_icon_confirmed: bool
    drive_operation_key: str
    drive_file_id: str
    drive_parent_id: str
    drive_mime_type: str
    drive_content_sha256: str
    drive_state: str
    drive_readback_verified: bool
    bindings: tuple[PropertyBinding, ...]
    working_metadata: tuple[WorkingMetadata, ...] = ()
    dry_run: bool = True
    maximum_retries: int = 2
    maximum_total_retry_delay: float = 30.0


@dataclass(frozen=True, slots=True)
class NotionAssetWriteResult:
    operation_key: str | None
    state: WriteState
    dry_run: bool
    page_id: str | None
    written_fields: tuple[str, ...]
    reason_codes: tuple[str, ...]
    readback_verified: bool = False
    external_write_performed: bool = False
    approval_authorized: bool = False
    classroom_readiness_authorized: bool = False
    rights_authorized: bool = False
    privacy_authorized: bool = False
    publication_authorized: bool = False
    production_authorized: bool = False


@dataclass(frozen=True, slots=True)
class IconSystemWriteResult:
    operation_key: str | None
    state: WriteState
    dry_run: bool
    page_id: str | None
    written_fields: tuple[str, ...]
    reason_codes: tuple[str, ...]
    readback_verified: bool = False
    external_write_performed: bool = False
    approval_authorized: bool = False
    classroom_readiness_authorized: bool = False
    rights_authorized: bool = False
    privacy_authorized: bool = False
    publication_authorized: bool = False
    production_authorized: bool = False


@dataclass(frozen=True, slots=True)
class NotionAssetSyncRequest:
    visual_asset: NotionAssetWriteRequest
    reusable_icon_confirmed: bool = False
    icon_system: IconSystemWriteRequest | None = None


@dataclass(frozen=True, slots=True)
class NotionAssetSyncResult:
    state: SyncState
    dry_run: bool
    visual_asset_result: NotionAssetWriteResult
    icon_system_result: IconSystemWriteResult | None
    reason_codes: tuple[str, ...]
    fully_synchronized: bool = False
    external_write_performed: bool = False
    approval_authorized: bool = False
    classroom_readiness_authorized: bool = False
    rights_authorized: bool = False
    privacy_authorized: bool = False
    publication_authorized: bool = False
    production_authorized: bool = False


class NotionRateLimitError(Exception):
    def __init__(self, retry_after: float) -> None:
        if type(retry_after) not in {int, float}:
            raise TypeError("retry_after must be an exact number")
        delay = float(retry_after)
        if not math.isfinite(delay) or delay < 0 or delay > MAX_TOTAL_RETRY_DELAY:
            raise ValueError("retry_after is outside the supported range")
        super().__init__("notion request was rate limited")
        self.retry_after = delay


class NotionTransientError(Exception):
    """Client-neutral transient failure with no provider text exposure."""


class NotionClient(Protocol):
    def fetch_schema(self, data_source_id: str) -> tuple[NotionPropertySpec, ...]: ...
    def find_exact(self, *, data_source_id: str, property_name: str, value: str) -> tuple[NotionPageEvidence, ...]: ...
    def create_page(self, *, data_source_id: str, properties: tuple[tuple[str, MetadataValue], ...], operation_key: str) -> str: ...
    def update_page(self, *, page_id: str, properties: tuple[tuple[str, MetadataValue], ...]) -> None: ...
    def fetch_page(self, page_id: str) -> NotionPageEvidence | None: ...


def _operation_key_material(parts: tuple[str, ...]) -> bytes:
    material = bytearray()
    for part in parts:
        encoded = part.encode("utf-8")
        material.extend(len(encoded).to_bytes(8, "big"))
        material.extend(encoded)
    return bytes(material)


def operation_key_for(request: NotionAssetWriteRequest) -> str:
    parts = (request.data_source_id, request.asset_id, request.drive_file_id, request.drive_operation_key)
    return sha256(_operation_key_material(parts)).hexdigest()


def icon_operation_key_for(request: IconSystemWriteRequest) -> str:
    parts = (
        request.data_source_id,
        request.asset_id,
        request.drive_file_id,
        request.drive_operation_key,
        request.source_asset_link,
    )
    return sha256(_operation_key_material(parts)).hexdigest()


def write_asset(request: NotionAssetWriteRequest, client: NotionClient | None = None, *, sleep: Callable[[float], None] = time.sleep) -> NotionAssetWriteResult:
    reason = _validate_request(request)
    if reason:
        return _asset_result(request, None, WriteState.PRECHECK_FAILED, (reason,))
    key = operation_key_for(request)
    intended = _intended(request)
    fields = tuple(field for field, _ in _logical_values(request))
    if request.dry_run:
        return _asset_result(request, key, WriteState.DRY_RUN, ("notion-write-dry-run-valid",), fields=fields)
    if client is None:
        return _asset_result(request, key, WriteState.PRECHECK_FAILED, ("notion-client-required",), fields=fields)

    schema_reason, schema_state = _asset_schema_preflight(client, request, sleep)
    if schema_reason:
        return _asset_result(request, key, schema_state, (schema_reason,), fields=fields)

    try:
        candidates = _find_candidates(client, request, sleep)
    except _RetryExhausted:
        return _asset_result(request, key, WriteState.FAILED, ("notion-reconcile-retry-exhausted",), fields=fields)
    except Exception:
        return _asset_result(request, key, WriteState.FAILED, ("notion-reconcile-read-failed",), fields=fields)
    if len(candidates) > 1:
        return _asset_result(request, key, WriteState.PRECHECK_FAILED, ("notion-conflicting-existing-identity",), fields=fields)
    if candidates:
        page = candidates[0]
        if not _anchors_match(page, request):
            return _asset_result(request, key, WriteState.PRECHECK_FAILED, ("notion-existing-identity-mismatch",), page_id=page.page_id, fields=fields)
        if _properties_match(page, intended):
            return _asset_verified(request, key, page.page_id, fields, WriteState.RECONCILED_EXISTING, False)
        try:
            _retry(lambda: client.update_page(page_id=page.page_id, properties=intended), request, sleep)
            readback = _retry(lambda: client.fetch_page(page.page_id), request, sleep)
        except _RetryExhausted:
            return _asset_result(request, key, WriteState.FAILED, ("notion-update-retry-exhausted",), page_id=page.page_id, fields=fields, external=True)
        except Exception:
            return _asset_result(request, key, WriteState.FAILED, ("notion-update-failed",), page_id=page.page_id, fields=fields, external=True)
        if readback is None or not _anchors_match(readback, request) or not _properties_match(readback, intended):
            return _asset_result(request, key, WriteState.FAILED, ("notion-update-readback-mismatch",), page_id=page.page_id, fields=fields, external=True)
        return _asset_verified(request, key, page.page_id, fields, WriteState.UPDATED, True)

    try:
        page_id = client.create_page(data_source_id=request.data_source_id, properties=intended, operation_key=key)
    except (NotionRateLimitError, NotionTransientError):
        try:
            reconciled = _find_candidates(client, request, sleep)
        except Exception:
            reconciled = ()
        if len(reconciled) == 1 and _anchors_match(reconciled[0], request):
            try:
                readback = _retry(lambda: client.fetch_page(reconciled[0].page_id), request, sleep)
            except Exception:
                readback = None
            if readback is not None and _properties_match(readback, intended):
                return _asset_verified(request, key, reconciled[0].page_id, fields, WriteState.RECONCILED_EXISTING, True)
        return _asset_result(request, key, WriteState.AMBIGUOUS_WRITE_RESULT, ("notion-create-outcome-ambiguous",), fields=fields, external=True)
    except Exception:
        return _asset_result(request, key, WriteState.FAILED, ("notion-create-failed",), fields=fields, external=True)
    if not _text(page_id):
        return _asset_result(request, key, WriteState.FAILED, ("notion-create-page-id-invalid",), fields=fields, external=True)
    try:
        readback = _retry(lambda: client.fetch_page(page_id), request, sleep)
    except _RetryExhausted:
        return _asset_result(request, key, WriteState.FAILED, ("notion-create-readback-retry-exhausted",), page_id=page_id, fields=fields, external=True)
    except Exception:
        return _asset_result(request, key, WriteState.FAILED, ("notion-create-readback-failed",), page_id=page_id, fields=fields, external=True)
    if readback is None or not _anchors_match(readback, request) or not _properties_match(readback, intended):
        return _asset_result(request, key, WriteState.FAILED, ("notion-create-readback-mismatch",), page_id=page_id, fields=fields, external=True)
    return _asset_verified(request, key, page_id, fields, WriteState.CREATED, True)


def write_icon(request: IconSystemWriteRequest, client: NotionClient | None = None, *, sleep: Callable[[float], None] = time.sleep) -> IconSystemWriteResult:
    reason = _validate_icon_request(request)
    if reason:
        return _icon_result(request, None, WriteState.PRECHECK_FAILED, (reason,))
    key = icon_operation_key_for(request)
    intended = _icon_intended(request)
    fields = tuple(field for field, _ in _icon_logical_values(request))
    if request.dry_run:
        return _icon_result(request, key, WriteState.DRY_RUN, ("notion-icon-write-dry-run-valid",), fields=fields)
    if client is None:
        return _icon_result(request, key, WriteState.PRECHECK_FAILED, ("notion-client-required",), fields=fields)

    schema_reason, schema_state = _icon_schema_preflight(client, request, sleep)
    if schema_reason:
        return _icon_result(request, key, schema_state, (schema_reason,), fields=fields)

    try:
        candidates = _find_icon_candidates(client, request, sleep)
    except _RetryExhausted:
        return _icon_result(request, key, WriteState.FAILED, ("notion-icon-reconcile-retry-exhausted",), fields=fields)
    except Exception:
        return _icon_result(request, key, WriteState.FAILED, ("notion-icon-reconcile-read-failed",), fields=fields)
    if len(candidates) > 1:
        return _icon_result(request, key, WriteState.PRECHECK_FAILED, ("notion-icon-conflicting-existing-identity",), fields=fields)
    if candidates:
        page = candidates[0]
        if not _icon_anchors_match(page, request):
            return _icon_result(request, key, WriteState.PRECHECK_FAILED, ("notion-icon-existing-identity-mismatch",), page_id=page.page_id, fields=fields)
        if _properties_match(page, intended):
            return _icon_verified(request, key, page.page_id, fields, WriteState.RECONCILED_EXISTING, False)
        try:
            _retry(lambda: client.update_page(page_id=page.page_id, properties=intended), request, sleep)
            readback = _retry(lambda: client.fetch_page(page.page_id), request, sleep)
        except _RetryExhausted:
            return _icon_result(request, key, WriteState.FAILED, ("notion-icon-update-retry-exhausted",), page_id=page.page_id, fields=fields, external=True)
        except Exception:
            return _icon_result(request, key, WriteState.FAILED, ("notion-icon-update-failed",), page_id=page.page_id, fields=fields, external=True)
        if readback is None or not _icon_anchors_match(readback, request) or not _properties_match(readback, intended):
            return _icon_result(request, key, WriteState.FAILED, ("notion-icon-update-readback-mismatch",), page_id=page.page_id, fields=fields, external=True)
        return _icon_verified(request, key, page.page_id, fields, WriteState.UPDATED, True)

    try:
        page_id = client.create_page(data_source_id=request.data_source_id, properties=intended, operation_key=key)
    except (NotionRateLimitError, NotionTransientError):
        try:
            reconciled = _find_icon_candidates(client, request, sleep)
        except Exception:
            reconciled = ()
        if len(reconciled) == 1 and _icon_anchors_match(reconciled[0], request):
            try:
                readback = _retry(lambda: client.fetch_page(reconciled[0].page_id), request, sleep)
            except Exception:
                readback = None
            if readback is not None and _properties_match(readback, intended):
                return _icon_verified(request, key, reconciled[0].page_id, fields, WriteState.RECONCILED_EXISTING, True)
        return _icon_result(request, key, WriteState.AMBIGUOUS_WRITE_RESULT, ("notion-icon-create-outcome-ambiguous",), fields=fields, external=True)
    except Exception:
        return _icon_result(request, key, WriteState.FAILED, ("notion-icon-create-failed",), fields=fields, external=True)
    if not _text(page_id):
        return _icon_result(request, key, WriteState.FAILED, ("notion-icon-create-page-id-invalid",), fields=fields, external=True)
    try:
        readback = _retry(lambda: client.fetch_page(page_id), request, sleep)
    except _RetryExhausted:
        return _icon_result(request, key, WriteState.FAILED, ("notion-icon-create-readback-retry-exhausted",), page_id=page_id, fields=fields, external=True)
    except Exception:
        return _icon_result(request, key, WriteState.FAILED, ("notion-icon-create-readback-failed",), page_id=page_id, fields=fields, external=True)
    if readback is None or not _icon_anchors_match(readback, request) or not _properties_match(readback, intended):
        return _icon_result(request, key, WriteState.FAILED, ("notion-icon-create-readback-mismatch",), page_id=page_id, fields=fields, external=True)
    return _icon_verified(request, key, page_id, fields, WriteState.CREATED, True)


def sync_asset(request: NotionAssetSyncRequest, client: NotionClient | None = None, *, sleep: Callable[[float], None] = time.sleep) -> NotionAssetSyncResult:
    reason = _validate_sync_request(request)
    if reason:
        visual = _asset_result(request.visual_asset if type(request) is NotionAssetSyncRequest else None, None, WriteState.PRECHECK_FAILED, (reason,))
        return _sync_result(request, SyncState.PRECHECK_FAILED, visual, None, (reason,))

    visual_request = request.visual_asset
    icon_request = request.icon_system

    visual_reason = _validate_request(visual_request)
    if visual_reason:
        visual = _asset_result(visual_request, None, WriteState.PRECHECK_FAILED, (visual_reason,))
        return _sync_result(request, SyncState.PRECHECK_FAILED, visual, None, (visual_reason,))
    if request.reusable_icon_confirmed:
        assert icon_request is not None
        icon_reason = _validate_icon_request(icon_request)
        if icon_reason:
            visual = _asset_result(visual_request, None, WriteState.PRECHECK_FAILED, ("notion-sync-icon-precheck-failed",))
            icon = _icon_result(icon_request, None, WriteState.PRECHECK_FAILED, (icon_reason,))
            return _sync_result(request, SyncState.PRECHECK_FAILED, visual, icon, (icon_reason,))

    if visual_request.dry_run:
        visual = write_asset(visual_request, client, sleep=sleep)
        icon = write_icon(icon_request, client, sleep=sleep) if icon_request is not None else None
        return _sync_result(request, SyncState.DRY_RUN, visual, icon, ("notion-sync-dry-run-valid",))

    if client is None:
        visual = _asset_result(visual_request, operation_key_for(visual_request), WriteState.PRECHECK_FAILED, ("notion-client-required",))
        icon = _icon_result(icon_request, icon_operation_key_for(icon_request), WriteState.PRECHECK_FAILED, ("notion-client-required",)) if icon_request is not None else None
        return _sync_result(request, SyncState.PRECHECK_FAILED, visual, icon, ("notion-client-required",))

    visual_schema_reason, visual_schema_state = _asset_schema_preflight(client, visual_request, sleep)
    if visual_schema_reason:
        visual = _asset_result(visual_request, operation_key_for(visual_request), visual_schema_state, (visual_schema_reason,))
        return _sync_result(request, _sync_state_for_preflight(visual_schema_state), visual, None, (visual_schema_reason,))

    if icon_request is not None:
        icon_schema_reason, icon_schema_state = _icon_schema_preflight(client, icon_request, sleep)
        if icon_schema_reason:
            visual = _asset_result(visual_request, operation_key_for(visual_request), WriteState.PRECHECK_FAILED, ("notion-sync-icon-schema-preflight-blocked",))
            icon = _icon_result(icon_request, icon_operation_key_for(icon_request), icon_schema_state, (icon_schema_reason,))
            return _sync_result(request, _sync_state_for_preflight(icon_schema_state), visual, icon, (icon_schema_reason,))

    visual = write_asset(visual_request, client, sleep=sleep)
    if not _write_success(visual.state):
        return _sync_result(request, SyncState.FAILED, visual, None, ("notion-sync-visual-asset-write-failed", *visual.reason_codes))

    if icon_request is None:
        return _sync_result(request, SyncState.VERIFIED, visual, None, ("notion-sync-verified",), fully=True)

    icon = write_icon(icon_request, client, sleep=sleep)
    if _write_success(icon.state):
        return _sync_result(request, SyncState.VERIFIED, visual, icon, ("notion-sync-verified",), fully=True)
    return _sync_result(request, SyncState.PARTIAL_REPAIR_REQUIRED, visual, icon, ("notion-sync-partial-repair-required", *icon.reason_codes))


def _validate_sync_request(request: object) -> str | None:
    if type(request) is not NotionAssetSyncRequest:
        return "notion-invalid-sync-request"
    if type(request.visual_asset) is not NotionAssetWriteRequest or type(request.reusable_icon_confirmed) is not bool:
        return "notion-invalid-sync-request"
    if request.reusable_icon_confirmed and type(request.icon_system) is not IconSystemWriteRequest:
        return "notion-icon-request-required"
    if not request.reusable_icon_confirmed and request.icon_system is not None:
        return "notion-icon-request-not-authorized"
    if request.icon_system is None:
        return None
    icon = request.icon_system
    visual = request.visual_asset
    evidence = (
        "asset_id", "routing_reference", "routing_state", "teacher_confirmed",
        "drive_operation_key", "drive_file_id", "drive_parent_id", "drive_mime_type",
        "drive_content_sha256", "drive_state", "drive_readback_verified", "dry_run",
    )
    if any(getattr(visual, name) != getattr(icon, name) for name in evidence):
        return "notion-cross-destination-evidence-mismatch"
    if icon.reusable_icon_confirmed is not True:
        return "notion-icon-classification-not-confirmed"
    return None


def _validate_request(request: object) -> str | None:
    if type(request) is not NotionAssetWriteRequest:
        return "notion-invalid-request"
    reason = _validate_common_request(request)
    if reason:
        return reason
    if type(request.bindings) is not tuple or type(request.working_metadata) is not tuple:
        return "notion-invalid-request"
    reason = _validate_bindings(request.bindings, ALLOWED_WORKING_FIELDS, _ALLOWED_TYPES)
    if reason:
        return reason
    by_field = {b.logical_field: b for b in request.bindings}
    if "asset_id" not in by_field or "drive_file_id" not in by_field:
        return "notion-identity-binding-missing"
    return _validate_metadata(request.working_metadata, by_field, ALLOWED_WORKING_FIELDS, {"asset_id", "drive_file_id"})


def _validate_icon_request(request: object) -> str | None:
    if type(request) is not IconSystemWriteRequest:
        return "notion-invalid-icon-request"
    reason = _validate_common_request(request)
    if reason:
        return reason
    if request.reusable_icon_confirmed is not True:
        return "notion-icon-classification-not-confirmed"
    if not _text(request.icon_name) or not _text(request.source_asset_link):
        return "notion-icon-identity-missing"
    if not _value_matches_type(request.source_asset_link, "url"):
        return "notion-icon-source-asset-link-invalid"
    if type(request.bindings) is not tuple or type(request.working_metadata) is not tuple:
        return "notion-invalid-icon-request"
    reason = _validate_bindings(request.bindings, ICON_SYSTEM_WORKING_FIELDS, _ICON_ALLOWED_TYPES)
    if reason:
        return reason
    by_field = {b.logical_field: b for b in request.bindings}
    if "icon_name" not in by_field or "source_asset_link" not in by_field:
        return "notion-icon-identity-binding-missing"
    return _validate_metadata(request.working_metadata, by_field, ICON_SYSTEM_WORKING_FIELDS, {"icon_name", "source_asset_link"})


def _validate_common_request(request: object) -> str | None:
    if request.routing_state != "CONFIRMED" or request.teacher_confirmed is not True:
        return "notion-routing-not-confirmed"
    if request.drive_state not in {"VERIFIED", "RECONCILED_EXISTING"} or request.drive_readback_verified is not True:
        return "notion-drive-evidence-not-verified"
    refs = (request.data_source_id, request.asset_id, request.routing_reference, request.drive_operation_key, request.drive_file_id, request.drive_parent_id, request.drive_mime_type)
    if not all(_text(v) for v in refs):
        return "notion-required-reference-missing"
    if type(request.drive_content_sha256) is not str or len(request.drive_content_sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in request.drive_content_sha256):
        return "notion-invalid-content-sha256"
    if type(request.dry_run) is not bool or type(request.maximum_retries) is not int:
        return "notion-invalid-request"
    if request.maximum_retries < 0 or request.maximum_retries > MAX_RETRIES:
        return "notion-invalid-retry-policy"
    if type(request.maximum_total_retry_delay) not in {int, float}:
        return "notion-invalid-retry-policy"
    delay = float(request.maximum_total_retry_delay)
    if not math.isfinite(delay) or delay < 0 or delay > MAX_TOTAL_RETRY_DELAY:
        return "notion-invalid-retry-policy"
    return None


def _validate_bindings(bindings: tuple[PropertyBinding, ...], allowlist: frozenset[str], allowed_types: dict[str, set[str]]) -> str | None:
    if not bindings:
        return "notion-property-bindings-missing"
    logical_seen: set[str] = set()
    property_seen: set[str] = set()
    for binding in bindings:
        if type(binding) is not PropertyBinding:
            return "notion-invalid-property-binding"
        if binding.logical_field not in allowlist:
            return "notion-field-not-allowlisted"
        if binding.logical_field in logical_seen or binding.property_name in property_seen:
            return "notion-duplicate-property-binding"
        if not _text(binding.property_name) or binding.property_type not in SUPPORTED_PROPERTY_TYPES:
            return "notion-invalid-property-binding"
        if any(term in binding.property_name.casefold() for term in _PROHIBITED_TERMS):
            return "notion-governed-property-blocked"
        if binding.property_type not in allowed_types[binding.logical_field]:
            return "notion-property-type-not-allowed"
        logical_seen.add(binding.logical_field)
        property_seen.add(binding.property_name)
    return None


def _validate_metadata(metadata: tuple[WorkingMetadata, ...], bindings: dict[str, PropertyBinding], allowlist: frozenset[str], writer_owned: set[str]) -> str | None:
    seen: set[str] = set()
    for item in metadata:
        if type(item) is not WorkingMetadata:
            return "notion-invalid-working-metadata"
        if item.logical_field in writer_owned:
            return "notion-identity-field-is-writer-owned"
        if item.logical_field not in allowlist or item.logical_field not in bindings:
            return "notion-working-field-unbound"
        if item.logical_field in seen:
            return "notion-duplicate-working-field"
        if not _value_matches_type(item.value, bindings[item.logical_field].property_type):
            return "notion-working-value-type-mismatch"
        seen.add(item.logical_field)
    return None


def _validate_schema(bindings: tuple[PropertyBinding, ...], schema: object) -> str | None:
    if type(schema) is not tuple or any(type(spec) is not NotionPropertySpec for spec in schema):
        return "notion-schema-response-invalid"
    live: dict[str, str] = {}
    for spec in schema:
        if not _text(spec.name) or spec.property_type not in SUPPORTED_PROPERTY_TYPES or spec.name in live:
            return "notion-schema-response-invalid"
        live[spec.name] = spec.property_type
    for binding in bindings:
        if binding.property_name not in live:
            return "notion-schema-property-missing"
        if live[binding.property_name] != binding.property_type:
            return "notion-schema-property-type-drift"
    return None


def _asset_schema_preflight(client: NotionClient, request: NotionAssetWriteRequest, sleep: Callable[[float], None]) -> tuple[str | None, WriteState]:
    return _schema_preflight(client, request.data_source_id, request.bindings, request, sleep)


def _icon_schema_preflight(client: NotionClient, request: IconSystemWriteRequest, sleep: Callable[[float], None]) -> tuple[str | None, WriteState]:
    reason, state = _schema_preflight(client, request.data_source_id, request.bindings, request, sleep)
    if reason is None:
        return None, state
    return reason.replace("notion-schema", "notion-icon-schema", 1), state


def _schema_preflight(client: NotionClient, data_source_id: str, bindings: tuple[PropertyBinding, ...], request: NotionAssetWriteRequest | IconSystemWriteRequest, sleep: Callable[[float], None]) -> tuple[str | None, WriteState]:
    try:
        schema = _retry(lambda: client.fetch_schema(data_source_id), request, sleep)
    except _RetryExhausted:
        return "notion-schema-retry-exhausted", WriteState.FAILED
    except Exception:
        return "notion-schema-read-failed", WriteState.FAILED
    reason = _validate_schema(bindings, schema)
    if reason:
        return reason, WriteState.PRECHECK_FAILED
    return None, WriteState.RECONCILED_EXISTING


def _logical_values(request: NotionAssetWriteRequest) -> tuple[tuple[str, MetadataValue], ...]:
    return (("asset_id", request.asset_id), ("drive_file_id", request.drive_file_id), *((m.logical_field, m.value) for m in request.working_metadata))


def _icon_logical_values(request: IconSystemWriteRequest) -> tuple[tuple[str, MetadataValue], ...]:
    return (("icon_name", request.icon_name), ("source_asset_link", request.source_asset_link), *((m.logical_field, m.value) for m in request.working_metadata))


def _intended(request: NotionAssetWriteRequest) -> tuple[tuple[str, MetadataValue], ...]:
    bindings = {b.logical_field: b.property_name for b in request.bindings}
    return tuple((bindings[field], value) for field, value in _logical_values(request))


def _icon_intended(request: IconSystemWriteRequest) -> tuple[tuple[str, MetadataValue], ...]:
    bindings = {b.logical_field: b.property_name for b in request.bindings}
    return tuple((bindings[field], value) for field, value in _icon_logical_values(request))


def _find_candidates(client: NotionClient, request: NotionAssetWriteRequest, sleep: Callable[[float], None]) -> tuple[NotionPageEvidence, ...]:
    bindings = {b.logical_field: b.property_name for b in request.bindings}
    asset_rows = _retry(lambda: client.find_exact(data_source_id=request.data_source_id, property_name=bindings["asset_id"], value=request.asset_id), request, sleep)
    drive_rows = _retry(lambda: client.find_exact(data_source_id=request.data_source_id, property_name=bindings["drive_file_id"], value=request.drive_file_id), request, sleep)
    return _combine_candidates(asset_rows, drive_rows)


def _find_icon_candidates(client: NotionClient, request: IconSystemWriteRequest, sleep: Callable[[float], None]) -> tuple[NotionPageEvidence, ...]:
    bindings = {b.logical_field: b.property_name for b in request.bindings}
    name_rows = _retry(lambda: client.find_exact(data_source_id=request.data_source_id, property_name=bindings["icon_name"], value=request.icon_name), request, sleep)
    source_rows = _retry(lambda: client.find_exact(data_source_id=request.data_source_id, property_name=bindings["source_asset_link"], value=request.source_asset_link), request, sleep)
    return _combine_candidates(name_rows, source_rows)


def _combine_candidates(*groups: tuple[NotionPageEvidence, ...]) -> tuple[NotionPageEvidence, ...]:
    combined: dict[str, NotionPageEvidence] = {}
    for group in groups:
        if type(group) is not tuple:
            raise ValueError("invalid page evidence")
        for page in group:
            if type(page) is not NotionPageEvidence or not _text(page.page_id):
                raise ValueError("invalid page evidence")
            _page_properties(page)
            if page.page_id in combined and combined[page.page_id] != page:
                raise ValueError("conflicting page evidence")
            combined[page.page_id] = page
    return tuple(combined.values())


def _anchors_match(page: NotionPageEvidence, request: NotionAssetWriteRequest) -> bool:
    try:
        props = _page_properties(page)
    except ValueError:
        return False
    bindings = {b.logical_field: b.property_name for b in request.bindings}
    return props.get(bindings["asset_id"]) == request.asset_id and props.get(bindings["drive_file_id"]) == request.drive_file_id


def _icon_anchors_match(page: NotionPageEvidence, request: IconSystemWriteRequest) -> bool:
    try:
        props = _page_properties(page)
    except ValueError:
        return False
    bindings = {b.logical_field: b.property_name for b in request.bindings}
    return props.get(bindings["icon_name"]) == request.icon_name and props.get(bindings["source_asset_link"]) == request.source_asset_link


def _properties_match(page: NotionPageEvidence, intended: tuple[tuple[str, MetadataValue], ...]) -> bool:
    try:
        props = _page_properties(page)
    except ValueError:
        return False
    return all(props.get(name) == value for name, value in intended)


def _page_properties(page: NotionPageEvidence) -> dict[str, MetadataValue]:
    if type(page) is not NotionPageEvidence or type(page.properties) is not tuple:
        raise ValueError("invalid page properties")
    props: dict[str, MetadataValue] = {}
    for item in page.properties:
        if type(item) is not tuple or len(item) != 2 or type(item[0]) is not str or item[0] in props:
            raise ValueError("invalid page properties")
        props[item[0]] = item[1]
    return props


class _RetryExhausted(Exception):
    pass


def _retry(call: Callable[[], T], request: NotionAssetWriteRequest | IconSystemWriteRequest, sleep: Callable[[float], None]) -> T:
    retries = 0
    total_delay = 0.0
    while True:
        try:
            return call()
        except NotionRateLimitError as error:
            delay = error.retry_after
        except NotionTransientError:
            delay = 0.0
        if retries >= request.maximum_retries or total_delay + delay > float(request.maximum_total_retry_delay):
            raise _RetryExhausted from None
        if delay:
            sleep(delay)
        total_delay += delay
        retries += 1


def _value_matches_type(value: MetadataValue, property_type: str) -> bool:
    if property_type == "checkbox":
        return type(value) is bool
    if property_type == "multi_select":
        return type(value) is tuple and all(_text(v) for v in value) and len(set(value)) == len(value)
    if type(value) is not str or not value.strip() or len(value) > MAX_VALUE:
        return False
    if property_type == "url":
        parsed = urlsplit(value.strip())
        return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.netloc)
    return True


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= MAX_REFERENCE


def _write_success(state: WriteState) -> bool:
    return state in {WriteState.CREATED, WriteState.UPDATED, WriteState.RECONCILED_EXISTING}


def _sync_state_for_preflight(state: WriteState) -> SyncState:
    return SyncState.PRECHECK_FAILED if state is WriteState.PRECHECK_FAILED else SyncState.FAILED


def _asset_result(request: object, key: str | None, state: WriteState, reasons: tuple[str, ...], *, page_id: str | None = None, fields: tuple[str, ...] = (), external: bool = False) -> NotionAssetWriteResult:
    dry = request.dry_run if type(request) is NotionAssetWriteRequest and type(request.dry_run) is bool else True
    return NotionAssetWriteResult(key, state, dry, page_id, fields, reasons, False, external)


def _icon_result(request: object, key: str | None, state: WriteState, reasons: tuple[str, ...], *, page_id: str | None = None, fields: tuple[str, ...] = (), external: bool = False) -> IconSystemWriteResult:
    dry = request.dry_run if type(request) is IconSystemWriteRequest and type(request.dry_run) is bool else True
    return IconSystemWriteResult(key, state, dry, page_id, fields, reasons, False, external)


def _asset_verified(request: NotionAssetWriteRequest, key: str, page_id: str, fields: tuple[str, ...], state: WriteState, external: bool) -> NotionAssetWriteResult:
    return NotionAssetWriteResult(key, state, request.dry_run, page_id, fields, ("notion-write-verified",), True, external)


def _icon_verified(request: IconSystemWriteRequest, key: str, page_id: str, fields: tuple[str, ...], state: WriteState, external: bool) -> IconSystemWriteResult:
    return IconSystemWriteResult(key, state, request.dry_run, page_id, fields, ("notion-icon-write-verified",), True, external)


def _sync_result(request: object, state: SyncState, visual: NotionAssetWriteResult, icon: IconSystemWriteResult | None, reasons: tuple[str, ...], *, fully: bool = False) -> NotionAssetSyncResult:
    dry = request.visual_asset.dry_run if type(request) is NotionAssetSyncRequest and type(request.visual_asset) is NotionAssetWriteRequest and type(request.visual_asset.dry_run) is bool else True
    external = visual.external_write_performed or (icon.external_write_performed if icon else False)
    return NotionAssetSyncResult(state, dry, visual, icon, reasons, fully, external)
