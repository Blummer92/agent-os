"""Visual-asset registration composition (#3254, Lane F).

ONE composition site proving the real end-to-end registration chain with
INJECTED clients (no live I/O, no new minting scheme, no new registry):

    coordinator.coordinate_ingestion (#954; injected drive/library/icon steps)
      -> visual-asset-drive-writer write_asset (#958; injected Drive client)
      -> asset_content_identity.identity_evidence_for_drive_file (#3256;
         Drive SHA-256 capture from the verified write)
      -> reusable_visual_identity.issue_reusable_visual_identity (#3256;
         canonical ``visual-asset-<24hex>`` mint)
      -> asset-ID policy (this module; governed "Asset ID" is authoritative
         input, legacy values are external aliases, unknown values fail closed)
      -> visual-asset-notion-writer write_asset (#959; injected Notion client;
         binds the issued asset_id to the governed "Asset ID" property)
      -> notion_asset_evidence_projection.project_ingestion_admission (#3266;
         verified record -> admission evidence, eligible candidate next run)

Physical ordering note: the identity is minted AFTER the verified Drive
write because the library file_id is an input to the mint and is only
stable once the writer has reconciled-or-created the file. A governed
Asset ID conflict is therefore detected after an idempotent Drive write;
the write is content-addressed (operation key), so a corrected
re-registration reconciles to the same file instead of duplicating it.

Asset ID policy (owner-gated decision remains OPEN -- see below):

- The governed "Asset ID" property is authoritative INPUT: the composition
  reads it and never invents a replacement.
- Absent/blank: the #3256 issuer mints the canonical ``visual-asset-<24hex>``
  identity from verified evidence; the Notion write binds it.
- Canonical ``visual-asset-[0-9a-f]{24}``: reconciled -- the re-minted
  identity must equal the governed value, else fail closed
  (``registration-asset-id-conflict``).
- Legacy ``VA-...`` / ``DMIMG-...``: recognized EXTERNAL ALIASES. Never
  minted by repository code, never validated as canonical. They pass through
  with explicit provenance on the registration record and admission evidence.
  The composition still mints and binds the canonical identity.
- Anything else: explicit incomplete-evidence
  (``registration-asset-id-unrecognized``). Never adopted, never invented.

OPEN owner decision (stated, not resolved here): whether downstream
consumers (#3257 placement tuples, eligibility joins) should adopt the
canonical identity over a legacy alias, and whether binding the canonical
ID over an existing legacy "Asset ID" property value is desired. This
module binds the canonical ID (the issuer is the minting authority) and
preserves every legacy value as a provenanced alias; no new scheme is
invented.

Fail-closed taxonomy (additive; #3257 placement and #3258 terminal-QA
contracts are untouched and not redefined):

- ``registration-intake-invalid`` -- governed intake fails validation.
- ``registration-icon-step-required`` -- icon confirmed but no icon step given.
- ``registration-drive-unverified`` -- Drive write not readback-verified.
- ``registration-drive-evidence-unavailable`` -- verified file not re-readable.
- ``registration-identity-evidence-failed`` -- no SHA-256 to mint from.
- ``registration-identity-invalid`` -- issuer rejected the evidence.
- ``registration-asset-id-conflict`` -- governed canonical ID != minted ID.
- ``registration-asset-id-unrecognized`` -- governed ID of unknown format.
- ``registration-notion-unverified`` -- Notion write not readback-verified.
- ``registration-coordinator-blocked`` -- coordinator stopped short of
  FULLY_SYNCHRONIZED (carries the coordinator's state and reason codes).

No failure path invents an identity, approves an asset, or reports absence:
unknown/missing/incomplete evidence stays explicit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from instructional_workflow_contracts.asset_content_identity import (
    identity_evidence_for_drive_file,
)
from instructional_workflow_contracts.reusable_visual_identity import (
    issue_reusable_visual_identity,
)
from navigation_registry.connectors.notion_asset_evidence_projection import (
    ProjectedAsset,
    project_ingestion_admission,
)
from visual_asset_drive_writer.writer import (
    DriveAssetWriteRequest,
    Representation,
    write_asset as drive_write_asset,
)
from visual_asset_ingestion_coordinator.coordinator import (
    CoordinatorRequest,
    CoordinatorState,
    GenerationProvenance,
    RoutingEvidence,
    WriterResult,
    coordinate_ingestion,
)
from visual_asset_notion_writer.writer import (
    NotionAssetWriteRequest,
    PropertyBinding,
    WorkingMetadata,
    write_asset as notion_write_asset,
)

# ---------------------------------------------------------------------------
# Asset ID policy
# ---------------------------------------------------------------------------

CANONICAL_ASSET_ID_RE = re.compile(r"^visual-asset-[0-9a-f]{24}$")
LEGACY_ASSET_ID_RES = (
    re.compile(r"^VA-[A-Za-z0-9_-]+$"),
    re.compile(r"^DMIMG-[A-Za-z0-9_-]+$"),
)

_KNOWN_DUPLICATE_DISPOSITIONS = frozenset(
    {
        "NO_DUPLICATE_FOUND",
        "EXACT_EXISTING",
        "NORMALIZED_EXISTING",
        "MANUAL_REVIEW_REQUIRED",
        "INVALID",
        "POSSIBLE_NEAR_DUPLICATE",
    }
)


@dataclass(frozen=True, slots=True)
class ExternalAlias:
    """A recognized legacy Asset ID carried with explicit provenance."""

    value: str
    provenance: str


@dataclass(frozen=True, slots=True)
class AssetIdentityResolution:
    asset_id: str
    stable_ref: str
    governed_input: str | None
    external_aliases: tuple[ExternalAlias, ...]
    reason_codes: tuple[str, ...]


class _FailClosed(Exception):
    """Internal fail-closed signal: never escapes register_visual_asset."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(detail or reason_code)
        self.reason_code = reason_code
        self.detail = detail


def resolve_asset_identity(
    governed_value: str | None,
    *,
    minted_asset_id: str,
    minted_stable_ref: str,
) -> AssetIdentityResolution:
    """Apply the #3254 asset-ID policy to one governed "Asset ID" value.

    ``governed_value`` is the authoritative property value read from the
    record (None/blank for a new registration). ``minted_*`` come from the
    #3256 issuer. Legacy values become provenanced external aliases; unknown
    values fail closed; canonical values must reconcile exactly.
    """
    governed = governed_value.strip() if isinstance(governed_value, str) else ""
    if not governed:
        return AssetIdentityResolution(
            asset_id=minted_asset_id,
            stable_ref=minted_stable_ref,
            governed_input=None,
            external_aliases=(),
            reason_codes=("registration-asset-id-minted",),
        )
    if CANONICAL_ASSET_ID_RE.fullmatch(governed):
        if governed != minted_asset_id:
            raise _FailClosed(
                "registration-asset-id-conflict",
                "governed Asset ID does not match the evidence-minted identity",
            )
        return AssetIdentityResolution(
            asset_id=governed,
            stable_ref=minted_stable_ref,
            governed_input=governed,
            external_aliases=(),
            reason_codes=("registration-asset-id-reconciled",),
        )
    if any(pattern.fullmatch(governed) for pattern in LEGACY_ASSET_ID_RES):
        alias = ExternalAlias(
            value=governed,
            provenance=(
                "governed 'Asset ID' property carried legacy value "
                f"'{governed}'; recognized as an external alias: never minted "
                "by repository code, never validated as canonical; the "
                "canonical identity was minted by the #3256 issuer from "
                "verified Drive evidence"
            ),
        )
        return AssetIdentityResolution(
            asset_id=minted_asset_id,
            stable_ref=minted_stable_ref,
            governed_input=governed,
            external_aliases=(alias,),
            reason_codes=("registration-asset-id-legacy-alias",),
        )
    raise _FailClosed(
        "registration-asset-id-unrecognized",
        f"governed Asset ID has an unrecognized format: {governed!r}",
    )


# ---------------------------------------------------------------------------
# Intake and result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegistrationIntake:
    """Governed inputs to one registration. No live values are invented here."""

    intake_reference: str
    local_reference: str
    content_sha256: str
    mime_type: str
    parent_folder_id: str
    provenance: Mapping[str, Any] = field(default_factory=dict)
    lineage: Mapping[str, Any] = field(default_factory=dict)
    representation: str = "ORIGINAL"
    teacher_confirmed: bool = True
    governed_asset_id: str | None = None
    drive_exact_reference: str | None = None
    concept: str | None = None
    asset_title: str | None = None
    source_approved: bool = False
    reusable_across_units: bool = False
    reuse_status: str | None = None
    reuse_scope: str | None = None
    notion_data_source_id: str = ""
    duplicate_disposition: str = "NO_DUPLICATE_FOUND"
    reusable_icon_confirmed: bool = False
    generation_provenance: Mapping[str, Any] | None = None
    dry_run: bool = True


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    state: str  # registered | dry-run | existing-asset-reused | failed
    reason_codes: tuple[str, ...]
    asset_id: str | None = None
    stable_ref: str | None = None
    external_aliases: tuple[ExternalAlias, ...] = ()
    drive_file_id: str | None = None
    drive_operation_key: str | None = None
    page_id: str | None = None
    coordinator_state: str | None = None
    admission: ProjectedAsset | None = None
    detail: str = ""


def _validate_intake(intake: RegistrationIntake) -> None:
    if type(intake) is not RegistrationIntake:
        raise _FailClosed("registration-intake-invalid", "intake has the wrong type")
    for name in (
        "intake_reference",
        "local_reference",
        "mime_type",
        "parent_folder_id",
        "notion_data_source_id",
    ):
        value = getattr(intake, name)
        if type(value) is not str or not value.strip() or len(value) > 512:
            raise _FailClosed("registration-intake-invalid", f"intake.{name} is required")
    sha = intake.content_sha256
    if (
        type(sha) is not str
        or len(sha) != 64
        or any(c not in "0123456789abcdefABCDEF" for c in sha)
    ):
        raise _FailClosed("registration-intake-invalid", "intake.content_sha256 must be hex64")
    if intake.representation not in {"ORIGINAL", "NORMALIZED"}:
        raise _FailClosed("registration-intake-invalid", "intake.representation is unknown")
    if intake.teacher_confirmed is not True:
        raise _FailClosed(
            "registration-intake-invalid", "registration requires teacher_confirmed=True"
        )
    if intake.duplicate_disposition not in _KNOWN_DUPLICATE_DISPOSITIONS:
        raise _FailClosed("registration-intake-invalid", "intake.duplicate_disposition is unknown")
    if not isinstance(intake.provenance, Mapping) or not isinstance(intake.lineage, Mapping):
        raise _FailClosed("registration-intake-invalid", "provenance/lineage must be mappings")
    if intake.generation_provenance is not None and not isinstance(
        intake.generation_provenance, Mapping
    ):
        raise _FailClosed("registration-intake-invalid", "generation_provenance must be a mapping")


# ---------------------------------------------------------------------------
# The composition
# ---------------------------------------------------------------------------


def _notion_bindings() -> tuple[PropertyBinding, ...]:
    return (
        PropertyBinding("asset_id", "Asset ID", "rich_text"),
        PropertyBinding("drive_file_id", "Drive File ID", "rich_text"),
        PropertyBinding("asset_title", "Asset Title", "title"),
        PropertyBinding("concept_reference", "Concept", "rich_text"),
        PropertyBinding("source_import_notes", "Import Notes", "rich_text"),
    )


def register_visual_asset(
    *,
    intake: RegistrationIntake,
    drive_client: Any,
    notion_client: Any,
    icon_step: Callable[..., WriterResult] | None = None,
) -> RegistrationResult:
    """Run the real registration composition with injected clients.

    ``drive_client``/``notion_client`` implement the writer protocols
    (in-memory fakes in tests; separately authorized adapters live).
    ``icon_step`` is an optional injected coordinator icon step; when the
    intake confirms a reusable icon but no step is supplied, registration
    fails closed instead of silently skipping the icon system.
    """
    try:
        _validate_intake(intake)
    except _FailClosed as exc:
        return RegistrationResult(state="failed", reason_codes=(exc.reason_code,), detail=exc.detail)
    if drive_client is None or notion_client is None:
        return RegistrationResult(
            state="failed",
            reason_codes=("registration-client-missing",),
            detail="drive and notion clients are required (injected, never constructed here)",
        )
    if intake.reusable_icon_confirmed and icon_step is None:
        return RegistrationResult(
            state="failed",
            reason_codes=("registration-icon-step-required",),
            detail="reusable icon confirmed but no icon step was injected",
        )

    ctx: dict[str, Any] = {}

    def _drive_step(routing: RoutingEvidence) -> WriterResult:
        request = DriveAssetWriteRequest(
            intake_reference=intake.intake_reference,
            representation=Representation[intake.representation],
            local_reference=intake.local_reference,
            content_sha256=intake.content_sha256,
            mime_type=intake.mime_type,
            parent_folder_id=intake.parent_folder_id,
            routing_state="CONFIRMED",
            teacher_confirmed=True,
            destination_current=True,
            dry_run=False,
        )
        written = drive_write_asset(request, client=drive_client)
        if not written.readback_verified or not written.file_id:
            ctx["step_failure"] = (
                "registration-drive-unverified",
                f"drive write not readback-verified: {written.state.value}",
            )
            return WriterResult(state="FAILED", verified=False, repair_required=True)
        # Drive SHA-256 capture: re-read the verified file's metadata through
        # the injected client; only a SHA-256 identity can mint v1 identity.
        evidence_file = drive_client.fetch_file(written.file_id)
        metadata = {
            "id": written.file_id,
            "webViewLink": intake.drive_exact_reference or "",
            "sha256Checksum": getattr(evidence_file, "content_sha256", "") or "",
        }
        try:
            identity_evidence = identity_evidence_for_drive_file(
                metadata=metadata,
                provenance=dict(intake.provenance),
                lineage=dict(intake.lineage),
            )
        except (ValueError, TypeError) as exc:
            ctx["step_failure"] = ("registration-identity-evidence-failed", str(exc))
            return WriterResult(state="FAILED", verified=False, repair_required=True)
        issued = issue_reusable_visual_identity(identity_evidence)
        if issued.get("status") != "valid":
            ctx["step_failure"] = (
                "registration-identity-invalid",
                ";".join(issued.get("reason_codes", ())),
            )
            return WriterResult(state="FAILED", verified=False, repair_required=True)
        identity = issued["identity"]
        try:
            resolution = resolve_asset_identity(
                intake.governed_asset_id,
                minted_asset_id=identity["asset_id"],
                minted_stable_ref=identity["stable_ref"],
            )
        except _FailClosed as exc:
            ctx["step_failure"] = (exc.reason_code, exc.detail)
            return WriterResult(state="FAILED", verified=False, repair_required=True)
        ctx["asset_id"] = resolution.asset_id
        ctx["stable_ref"] = resolution.stable_ref
        ctx["external_aliases"] = resolution.external_aliases
        ctx["asset_reason_codes"] = resolution.reason_codes
        ctx["drive_file_id"] = written.file_id
        ctx["drive_operation_key"] = written.operation_key
        ctx["drive_content_sha256"] = written.content_sha256
        ctx["identity"] = identity
        return WriterResult(
            state="VERIFIED", verified=True, external_identity=resolution.asset_id
        )

    def _library_step(routing: RoutingEvidence, drive: WriterResult) -> WriterResult:
        if "asset_id" not in ctx:
            ctx["step_failure"] = (
                "registration-context-missing",
                "drive step did not produce an asset identity",
            )
            return WriterResult(state="FAILED", verified=False, repair_required=True)
        working: list[WorkingMetadata] = []
        if isinstance(intake.asset_title, str) and intake.asset_title.strip():
            working.append(WorkingMetadata("asset_title", intake.asset_title.strip()))
        if isinstance(intake.concept, str) and intake.concept.strip():
            working.append(WorkingMetadata("concept_reference", intake.concept.strip()))
        identity = ctx["identity"]
        notes = (
            "registration #3254: canonical identity minted by "
            "governed-reusable-visual-identity-v1; "
            f"basis_fingerprint={identity['basis_fingerprint']}; "
            f"stable_ref={identity['stable_ref']}"
        )
        for alias in ctx["external_aliases"]:
            notes += f"; external alias {alias.value!r} ({alias.provenance})"
        working.append(WorkingMetadata("source_import_notes", notes))
        request = NotionAssetWriteRequest(
            data_source_id=intake.notion_data_source_id,
            asset_id=ctx["asset_id"],
            routing_reference=intake.intake_reference,
            routing_state="CONFIRMED",
            teacher_confirmed=True,
            drive_operation_key=ctx["drive_operation_key"],
            drive_file_id=ctx["drive_file_id"],
            drive_parent_id=intake.parent_folder_id,
            drive_mime_type=intake.mime_type,
            drive_content_sha256=ctx["drive_content_sha256"],
            drive_state="VERIFIED",
            drive_readback_verified=True,
            bindings=_notion_bindings(),
            working_metadata=tuple(working),
            dry_run=False,
        )
        written = notion_write_asset(request, client=notion_client, sleep=lambda _: None)
        if not written.readback_verified or not written.page_id:
            ctx["step_failure"] = (
                "registration-notion-unverified",
                f"notion write not readback-verified: {written.state.value}",
            )
            return WriterResult(state="FAILED", verified=False, repair_required=True)
        ctx["page_id"] = written.page_id
        return WriterResult(state="VERIFIED", verified=True, external_identity=ctx["asset_id"])

    try:
        provenance = None
        if intake.generation_provenance is not None:
            gp = intake.generation_provenance
            provenance = GenerationProvenance(
                generation_handoff_id=gp["generation_handoff_id"],
                returned_binding_id=gp["returned_binding_id"],
                intake_id=gp["intake_id"],
                association_state=gp["association_state"],
            )
        coordinator_request = CoordinatorRequest(
            routing=RoutingEvidence(
                intake_reference=intake.intake_reference,
                duplicate_disposition=intake.duplicate_disposition,
                existing_identity=None,
                routing_state="CONFIRMED",
                teacher_confirmed=True,
                drive_destination_ref=intake.parent_folder_id,
                notion_destination_ref=intake.notion_data_source_id,
                destination_current=True,
                reusable_icon_confirmed=intake.reusable_icon_confirmed,
            ),
            provenance=provenance,
            dry_run=intake.dry_run,
        )
    except (TypeError, KeyError) as exc:
        return RegistrationResult(
            state="failed",
            reason_codes=("registration-intake-invalid",),
            detail=f"generation provenance invalid: {exc}",
        )

    coordinated = coordinate_ingestion(
        coordinator_request,
        drive_step=_drive_step,
        library_step=_library_step,
        icon_step=icon_step,
    )
    coordinator_state = coordinated.state.value

    if coordinated.state is CoordinatorState.DRY_RUN:
        return RegistrationResult(
            state="dry-run",
            reason_codes=("registration-dry-run",),
            coordinator_state=coordinator_state,
        )
    if coordinated.state is CoordinatorState.EXISTING_ASSET_REUSED:
        return RegistrationResult(
            state="existing-asset-reused",
            reason_codes=("registration-existing-asset-reused",) + coordinated.reason_codes,
            coordinator_state=coordinator_state,
            detail="existing asset reused by the coordinator; no new admission projected",
        )
    if coordinated.state is not CoordinatorState.FULLY_SYNCHRONIZED:
        reasons: list[str] = ["registration-coordinator-blocked"]
        step_failure = ctx.get("step_failure")
        if step_failure is not None:
            reasons.append(step_failure[0])
        reasons.extend(coordinated.reason_codes)
        return RegistrationResult(
            state="failed",
            reason_codes=tuple(reasons),
            coordinator_state=coordinator_state,
            detail=step_failure[1] if step_failure is not None else "",
        )

    record = {
        "page_id": ctx["page_id"],
        "asset_id": ctx["asset_id"],
        "drive_file_id": ctx["drive_file_id"],
        "reuse_status": intake.reuse_status or "",
        "source_approved": bool(intake.source_approved),
        "reusable_across_units": bool(intake.reusable_across_units),
        "reuse_scope": intake.reuse_scope,
        "concept": intake.concept or "",
    }
    admission = project_ingestion_admission(record)
    return RegistrationResult(
        state="registered",
        reason_codes=ctx.get("asset_reason_codes", ()) + ("registration-complete",),
        asset_id=ctx["asset_id"],
        stable_ref=ctx["stable_ref"],
        external_aliases=ctx["external_aliases"],
        drive_file_id=ctx["drive_file_id"],
        drive_operation_key=ctx["drive_operation_key"],
        page_id=ctx["page_id"],
        coordinator_state=coordinator_state,
        admission=admission,
    )
