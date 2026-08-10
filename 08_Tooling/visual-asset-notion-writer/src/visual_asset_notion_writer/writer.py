"""Offline-first Notion Visual Asset Library writer contract.

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
_PROHIBITED_TERMS = (
    "approval", "approved use", "readiness", "rights", "privacy", "audit",
    "sharing", "permission", "publication", "production authorized",
    "source authority", "safe use", "clearance",
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


def operation_key_for(request: NotionAssetWriteRequest) -> str:
    material = "\n".join((request.data_source_id, request.asset_id, request.drive_file_id, request.drive_operation_key))
    return sha256(material.encode("utf-8")).hexdigest()


def write_asset(request: NotionAssetWriteRequest, client: NotionClient | None = None, *, sleep: Callable[[float], None] = time.sleep) -> NotionAssetWriteResult:
    reason = _validate_request(request)
    if reason:
        return _result(request, None, WriteState.PRECHECK_FAILED, (reason,))
    key = operation_key_for(request)
    intended = _intended(request)
    fields = tuple(field for field, _ in _logical_values(request))
    if request.dry_run:
        return _result(request, key, WriteState.DRY_RUN, ("notion-write-dry-run-valid",), fields=fields)
    if client is None:
        return _result(request, key, WriteState.PRECHECK_FAILED, ("notion-client-required",), fields=fields)

    try:
        schema = _retry(lambda: client.fetch_schema(request.data_source_id), request, sleep)
    except _RetryExhausted:
        return _result(request, key, WriteState.FAILED, ("notion-schema-retry-exhausted",), fields=fields)
    except Exception:
        return _result(request, key, WriteState.FAILED, ("notion-schema-read-failed",), fields=fields)
    reason = _validate_schema(request, schema)
    if reason:
        return _result(request, key, WriteState.PRECHECK_FAILED, (reason,), fields=fields)

    try:
        candidates = _find_candidates(client, request, sleep)
    except _RetryExhausted:
        return _result(request, key, WriteState.FAILED, ("notion-reconcile-retry-exhausted",), fields=fields)
    except Exception:
        return _result(request, key, WriteState.FAILED, ("notion-reconcile-read-failed",), fields=fields)
    if len(candidates) > 1:
        return _result(request, key, WriteState.PRECHECK_FAILED, ("notion-conflicting-existing-identity",), fields=fields)
    if candidates:
        page = candidates[0]
        if not _anchors_match(page, request):
            return _result(request, key, WriteState.PRECHECK_FAILED, ("notion-existing-identity-mismatch",), page_id=page.page_id, fields=fields)
        if _properties_match(page, intended):
            return _verified(request, key, page.page_id, fields, WriteState.RECONCILED_EXISTING, False)
        try:
            _retry(lambda: client.update_page(page_id=page.page_id, properties=intended), request, sleep)
            readback = _retry(lambda: client.fetch_page(page.page_id), request, sleep)
        except _RetryExhausted:
            return _result(request, key, WriteState.FAILED, ("notion-update-retry-exhausted",), page_id=page.page_id, fields=fields, external=True)
        except Exception:
            return _result(request, key, WriteState.FAILED, ("notion-update-failed",), page_id=page.page_id, fields=fields, external=True)
        if readback is None or not _anchors_match(readback, request) or not _properties_match(readback, intended):
            return _result(request, key, WriteState.FAILED, ("notion-update-readback-mismatch",), page_id=page.page_id, fields=fields, external=True)
        return _verified(request, key, page.page_id, fields, WriteState.UPDATED, True)

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
                return _verified(request, key, reconciled[0].page_id, fields, WriteState.RECONCILED_EXISTING, True)
        return _result(request, key, WriteState.AMBIGUOUS_WRITE_RESULT, ("notion-create-outcome-ambiguous",), fields=fields, external=True)
    except Exception:
        return _result(request, key, WriteState.FAILED, ("notion-create-failed",), fields=fields)
    if not _text(page_id):
        return _result(request, key, WriteState.FAILED, ("notion-create-page-id-invalid",), fields=fields, external=True)
    try:
        readback = _retry(lambda: client.fetch_page(page_id), request, sleep)
    except _RetryExhausted:
        return _result(request, key, WriteState.FAILED, ("notion-create-readback-retry-exhausted",), page_id=page_id, fields=fields, external=True)
    except Exception:
        return _result(request, key, WriteState.FAILED, ("notion-create-readback-failed",), page_id=page_id, fields=fields, external=True)
    if readback is None or not _anchors_match(readback, request) or not _properties_match(readback, intended):
        return _result(request, key, WriteState.FAILED, ("notion-create-readback-mismatch",), page_id=page_id, fields=fields, external=True)
    return _verified(request, key, page_id, fields, WriteState.CREATED, True)


def _validate_request(request: object) -> str | None:
    if type(request) is not NotionAssetWriteRequest:
        return "notion-invalid-request"
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
    if type(request.bindings) is not tuple or type(request.working_metadata) is not tuple:
        return "notion-invalid-request"
    reason = _validate_bindings(request.bindings)
    if reason:
        return reason
    by_field = {b.logical_field: b for b in request.bindings}
    if "asset_id" not in by_field or "drive_file_id" not in by_field:
        return "notion-identity-binding-missing"
    return _validate_metadata(request.working_metadata, by_field)


def _validate_bindings(bindings: tuple[PropertyBinding, ...]) -> str | None:
    if not bindings:
        return "notion-property-bindings-missing"
    logical_seen: set[str] = set()
    property_seen: set[str] = set()
    for binding in bindings:
        if type(binding) is not PropertyBinding:
            return "notion-invalid-property-binding"
        if binding.logical_field not in ALLOWED_WORKING_FIELDS:
            return "notion-field-not-allowlisted"
        if binding.logical_field in logical_seen or binding.property_name in property_seen:
            return "notion-duplicate-property-binding"
        if not _text(binding.property_name) or binding.property_type not in SUPPORTED_PROPERTY_TYPES:
            return "notion-invalid-property-binding"
        if any(term in binding.property_name.casefold() for term in _PROHIBITED_TERMS):
            return "notion-governed-property-blocked"
        if binding.property_type not in _ALLOWED_TYPES[binding.logical_field]:
            return "notion-property-type-not-allowed"
        logical_seen.add(binding.logical_field)
        property_seen.add(binding.property_name)
    return None


def _validate_metadata(metadata: tuple[WorkingMetadata, ...], bindings: dict[str, PropertyBinding]) -> str | None:
    seen: set[str] = set()
    for item in metadata:
        if type(item) is not WorkingMetadata:
            return "notion-invalid-working-metadata"
        if item.logical_field in {"asset_id", "drive_file_id"}:
            return "notion-identity-field-is-writer-owned"
        if item.logical_field not in ALLOWED_WORKING_FIELDS or item.logical_field not in bindings:
            return "notion-working-field-unbound"
        if item.logical_field in seen:
            return "notion-duplicate-working-field"
        if not _value_matches_type(item.value, bindings[item.logical_field].property_type):
            return "notion-working-value-type-mismatch"
        seen.add(item.logical_field)
    return None


def _validate_schema(request: NotionAssetWriteRequest, schema: object) -> str | None:
    if type(schema) is not tuple or any(type(spec) is not NotionPropertySpec for spec in schema):
        return "notion-schema-response-invalid"
    live: dict[str, str] = {}
    for spec in schema:
        if not _text(spec.name) or spec.property_type not in SUPPORTED_PROPERTY_TYPES or spec.name in live:
            return "notion-schema-response-invalid"
        live[spec.name] = spec.property_type
    for binding in request.bindings:
        if binding.property_name not in live:
            return "notion-schema-property-missing"
        if live[binding.property_name] != binding.property_type:
            return "notion-schema-property-type-drift"
    return None


def _logical_values(request: NotionAssetWriteRequest) -> tuple[tuple[str, MetadataValue], ...]:
    return (("asset_id", request.asset_id), ("drive_file_id", request.drive_file_id), *((m.logical_field, m.value) for m in request.working_metadata))


def _intended(request: NotionAssetWriteRequest) -> tuple[tuple[str, MetadataValue], ...]:
    bindings = {b.logical_field: b.property_name for b in request.bindings}
    return tuple((bindings[field], value) for field, value in _logical_values(request))


def _find_candidates(client: NotionClient, request: NotionAssetWriteRequest, sleep: Callable[[float], None]) -> tuple[NotionPageEvidence, ...]:
    bindings = {b.logical_field: b.property_name for b in request.bindings}
    asset_rows = _retry(lambda: client.find_exact(data_source_id=request.data_source_id, property_name=bindings["asset_id"], value=request.asset_id), request, sleep)
    drive_rows = _retry(lambda: client.find_exact(data_source_id=request.data_source_id, property_name=bindings["drive_file_id"], value=request.drive_file_id), request, sleep)
    combined: dict[str, NotionPageEvidence] = {}
    for page in (*asset_rows, *drive_rows):
        if type(page) is not NotionPageEvidence or not _text(page.page_id):
            raise ValueError("invalid page evidence")
        if page.page_id in combined and combined[page.page_id] != page:
            raise ValueError("conflicting page evidence")
        combined[page.page_id] = page
    return tuple(combined.values())


def _anchors_match(page: NotionPageEvidence, request: NotionAssetWriteRequest) -> bool:
    props = _page_properties(page)
    bindings = {b.logical_field: b.property_name for b in request.bindings}
    return props.get(bindings["asset_id"]) == request.asset_id and props.get(bindings["drive_file_id"]) == request.drive_file_id


def _properties_match(page: NotionPageEvidence, intended: tuple[tuple[str, MetadataValue], ...]) -> bool:
    props = _page_properties(page)
    return all(props.get(name) == value for name, value in intended)


def _page_properties(page: NotionPageEvidence) -> dict[str, MetadataValue]:
    if type(page.properties) is not tuple:
        raise ValueError("invalid page properties")
    props: dict[str, MetadataValue] = {}
    for item in page.properties:
        if type(item) is not tuple or len(item) != 2 or type(item[0]) is not str or item[0] in props:
            raise ValueError("invalid page properties")
        props[item[0]] = item[1]
    return props


class _RetryExhausted(Exception):
    pass


def _retry(call: Callable[[], T], request: NotionAssetWriteRequest, sleep: Callable[[float], None]) -> T:
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
    return type(value) is str and bool(value.strip()) and len(value) <= MAX_VALUE


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= MAX_REFERENCE


def _result(request: object, key: str | None, state: WriteState, reasons: tuple[str, ...], *, page_id: str | None = None, fields: tuple[str, ...] = (), external: bool = False) -> NotionAssetWriteResult:
    dry = request.dry_run if type(request) is NotionAssetWriteRequest and type(request.dry_run) is bool else True
    return NotionAssetWriteResult(key, state, dry, page_id, fields, reasons, False, external)


def _verified(request: NotionAssetWriteRequest, key: str, page_id: str, fields: tuple[str, ...], state: WriteState, external: bool) -> NotionAssetWriteResult:
    return NotionAssetWriteResult(key, state, request.dry_run, page_id, fields, ("notion-write-verified",), True, external)
