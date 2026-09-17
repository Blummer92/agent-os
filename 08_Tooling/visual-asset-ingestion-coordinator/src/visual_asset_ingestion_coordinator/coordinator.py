"""Pure orchestration for repair-safe visual asset ingestion.

This module deliberately knows only bounded evidence projections and injected
component callables. It contains no Drive, Notion, image, or provider client.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol


class CoordinatorState(str, Enum):
    DRY_RUN = "DRY_RUN"
    PRECHECK_BLOCKED = "PRECHECK_BLOCKED"
    EXISTING_ASSET_REUSED = "EXISTING_ASSET_REUSED"
    DRIVE_VERIFIED_METADATA_PENDING = "DRIVE_VERIFIED_METADATA_PENDING"
    VISUAL_ASSET_LIBRARY_VERIFIED = "VISUAL_ASSET_LIBRARY_VERIFIED"
    ICON_SYSTEM_PENDING = "ICON_SYSTEM_PENDING"
    FULLY_SYNCHRONIZED = "FULLY_SYNCHRONIZED"
    AMBIGUOUS_EXTERNAL_OUTCOME = "AMBIGUOUS_EXTERNAL_OUTCOME"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class GenerationProvenance:
    generation_handoff_id: str
    returned_binding_id: str
    intake_id: str
    association_state: str


@dataclass(frozen=True, slots=True)
class RoutingEvidence:
    intake_reference: str
    duplicate_disposition: str
    existing_identity: str | None
    routing_state: str
    teacher_confirmed: bool
    drive_destination_ref: str | None
    notion_destination_ref: str | None
    destination_current: bool
    reusable_icon_confirmed: bool = False


@dataclass(frozen=True, slots=True)
class WriterResult:
    state: str
    verified: bool
    external_identity: str | None = None
    ambiguous: bool = False
    repair_required: bool = False
    external_write_performed: bool = False


@dataclass(frozen=True, slots=True)
class CoordinatorRequest:
    routing: RoutingEvidence
    provenance: GenerationProvenance | None = None
    dry_run: bool = True


@dataclass(frozen=True, slots=True)
class CoordinatorResult:
    state: CoordinatorState
    reason_codes: tuple[str, ...]
    provenance: GenerationProvenance | None
    drive_result: WriterResult | None = None
    library_result: WriterResult | None = None
    icon_result: WriterResult | None = None
    execution_authorized: bool = False
    external_write_authorized: bool = False
    approval_authorized: bool = False
    classroom_readiness_authorized: bool = False
    publication_authorized: bool = False
    production_authorized: bool = False


class DriveStep(Protocol):
    def __call__(self, routing: RoutingEvidence) -> WriterResult: ...


class LibraryStep(Protocol):
    def __call__(self, routing: RoutingEvidence, drive: WriterResult) -> WriterResult: ...


class IconStep(Protocol):
    def __call__(self, routing: RoutingEvidence, drive: WriterResult) -> WriterResult: ...


def coordinate_ingestion(
    request: CoordinatorRequest,
    *,
    drive_step: DriveStep | None = None,
    library_step: LibraryStep | None = None,
    icon_step: IconStep | None = None,
) -> CoordinatorResult:
    """Coordinate already-governed components without implementing their logic."""
    reason = _precheck(request)
    if reason is not None:
        return _result(CoordinatorState.PRECHECK_BLOCKED, (reason,), request)

    routing = request.routing
    if routing.duplicate_disposition in {"EXACT_EXISTING", "NORMALIZED_EXISTING"}:
        if not routing.existing_identity:
            return _result(CoordinatorState.MANUAL_REVIEW_REQUIRED, ("coordinator-existing-identity-missing",), request)
        return _result(CoordinatorState.EXISTING_ASSET_REUSED, ("coordinator-existing-asset-reused",), request)

    if request.dry_run:
        return _result(CoordinatorState.DRY_RUN, ("coordinator-dry-run-valid",), request)

    # External execution is never self-authorized here. Injected steps represent
    # separately admitted component execution supplied by the caller.
    if drive_step is None or library_step is None:
        return _result(CoordinatorState.PRECHECK_BLOCKED, ("coordinator-writer-step-missing",), request)

    drive = drive_step(routing)
    if drive.ambiguous:
        return _result(CoordinatorState.AMBIGUOUS_EXTERNAL_OUTCOME, ("coordinator-drive-outcome-ambiguous",), request, drive=drive)
    if drive.repair_required or not drive.verified:
        return _result(CoordinatorState.REPAIR_REQUIRED, ("coordinator-drive-repair-required",), request, drive=drive)

    library = library_step(routing, drive)
    if library.ambiguous:
        return _result(CoordinatorState.AMBIGUOUS_EXTERNAL_OUTCOME, ("coordinator-library-outcome-ambiguous",), request, drive=drive, library=library)
    if library.repair_required or not library.verified:
        return _result(CoordinatorState.DRIVE_VERIFIED_METADATA_PENDING, ("coordinator-library-repair-required",), request, drive=drive, library=library)

    if routing.reusable_icon_confirmed:
        if icon_step is None:
            return _result(CoordinatorState.ICON_SYSTEM_PENDING, ("coordinator-icon-step-missing",), request, drive=drive, library=library)
        icon = icon_step(routing, drive)
        if icon.ambiguous:
            return _result(CoordinatorState.AMBIGUOUS_EXTERNAL_OUTCOME, ("coordinator-icon-outcome-ambiguous",), request, drive=drive, library=library, icon=icon)
        if icon.repair_required or not icon.verified:
            return _result(CoordinatorState.ICON_SYSTEM_PENDING, ("coordinator-icon-repair-required",), request, drive=drive, library=library, icon=icon)
        return _result(CoordinatorState.FULLY_SYNCHRONIZED, ("coordinator-fully-synchronized",), request, drive=drive, library=library, icon=icon)

    return _result(CoordinatorState.FULLY_SYNCHRONIZED, ("coordinator-fully-synchronized",), request, drive=drive, library=library)


def _precheck(request: object) -> str | None:
    if type(request) is not CoordinatorRequest or type(request.routing) is not RoutingEvidence:
        return "coordinator-invalid-request"
    routing = request.routing
    if request.provenance is not None:
        if type(request.provenance) is not GenerationProvenance:
            return "coordinator-invalid-provenance"
        p = request.provenance
        if not all(_text(v) for v in (p.generation_handoff_id, p.returned_binding_id, p.intake_id, p.association_state)):
            return "coordinator-invalid-provenance"
        if p.intake_id != routing.intake_reference:
            return "coordinator-provenance-intake-mismatch"
        if p.association_state not in {"exact", "teacher-confirmed", "corrected"}:
            return "coordinator-provenance-review-required"
    if not _text(routing.intake_reference) or not _text(routing.duplicate_disposition):
        return "coordinator-routing-invalid"
    if routing.routing_state != "CONFIRMED" or routing.teacher_confirmed is not True:
        return "coordinator-routing-not-confirmed"
    if routing.duplicate_disposition in {"MANUAL_REVIEW_REQUIRED", "INVALID", "POSSIBLE_NEAR_DUPLICATE"}:
        return "coordinator-duplicate-review-required"
    if routing.destination_current is not True:
        return "coordinator-destination-stale"
    if routing.duplicate_disposition == "NO_DUPLICATE_FOUND":
        if not _text(routing.drive_destination_ref) or not _text(routing.notion_destination_ref):
            return "coordinator-destination-missing"
    return None


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= 512


def _result(state, reasons, request, *, drive=None, library=None, icon=None):
    return CoordinatorResult(state, tuple(reasons), request.provenance, drive, library, icon)
