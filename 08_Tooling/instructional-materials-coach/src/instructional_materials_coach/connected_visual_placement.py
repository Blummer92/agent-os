"""Connected visual placement orchestration (#3257).

This module wires the existing governed contracts into one connected path:

    governed selected asset (visual_reuse plan, #3248/#3251/#3252/#3253/#3254)
      -> VisualPlacementBinding (role/slot + Asset ID + Drive file + content identity)
      -> marker discovery in the live artifact (new; no producer existed)
      -> visual_placement.resolve_exact_target (#2087 contract, reused)
      -> visual_placement.build_placement_request (#2087 contract, reused)
      -> exact content/revision verification against fresh Drive metadata (#3256)
      -> placement_transport.insert_placement (connected boundary; #2087 Apps
         Script seam via the Execution API, or an injected fake in tests)
      -> post-insertion verification against the persisted artifact
      -> visual_placement.verify_placement_receipt (#2087 contract, reused)
      -> durable receipt in placement_receipts (the #3258 handoff surface)

Ownership respected: gap classification (#3248), role identity (#3251),
eligibility (#3253/#3254), content identity (#3256), and teacher-choice
persistence/continuation (#3252) are consumed, never re-implemented. The
placement layer receives explicit eligibility evidence on each binding and
never infers eligibility itself; it receives the durable teacher selection
through the governed plan and never reconstructs it from conversation
memory.

Fail-closed throughout: a placement failure keeps its own explicit reason
(marker-not-found, asset-missing, asset-access-failure,
content-identity-mismatch, placement-transport-failed, ...) and never
becomes visual absence, never authorizes new visual creation, and never
triggers a Drive re-search for a "similar" asset. The selected reference
is authoritative unless current validation proves it stale or invalid.

Pure repository-side orchestration with injected clients only; no
credentials are acquired here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from instructional_workflow_contracts.asset_content_identity import (
    content_identity_from_fingerprint,
    is_valid_content_identity,
)

from .drive_client import describe_drive_file_outcome
from .placement_receipts import (
    append_placement_record,
    build_placement_record,
    find_verified_record,
    load_placement_records,
)
from .placement_transport import (
    PlacementRuntimeUnavailable,
    PlacementTransport,
    PlacementTransportError,
)
from .visual_placement import (
    VisualPlacementError,
    build_placement_request,
    parse_marker_binding,
    resolve_exact_target,
    verify_placement_receipt,
    verify_request_content_identity,
)
from .workspace_clients import get_docs_revision_id, get_slides_revision_id


class PlacementExecutionError(RuntimeError):
    """A visual placement run failed closed with explicit per-binding reasons."""

    def __init__(self, message: str, *, outcomes: tuple["BindingOutcome", ...] = ()) -> None:
        super().__init__(message)
        self.outcomes = outcomes


@dataclass(frozen=True)
class VisualPlacementBinding:
    """One governed visual selected for placement.

    ``slot_id`` keys the #3251 (role_id, slot_id) multiplicity contract; the
    current planner emits one implicit slot per role (``"0"``). The binding
    carries the explicit eligibility evidence the plan attached -- placement
    never infers eligibility itself.
    """

    role_id: str
    asset_id: str
    drive_file_id: str
    content_identity: Mapping[str, Any]
    source_plan_id: str
    required: bool = True
    slot_id: str = "0"
    eligibility_evidence: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class BindingOutcome:
    binding: VisualPlacementBinding
    artifact_type: str
    artifact_id: str
    status: str  # placed | recovered | skipped-no-marker | failed
    reason: str = ""
    record: Mapping[str, Any] | None = None


def plan_visual_placement_bindings(visual_plan: Any) -> tuple[VisualPlacementBinding, ...]:
    """Build placement bindings from the governed visual-reuse plan.

    Consumes the cohesive plan's required/optional role assignments. Every
    binding must carry a role, an asset, a Drive file, a valid canonical
    content identity, and explicit eligibility evidence; anything less is
    an upstream contract breach and fails closed here rather than being
    repaired by guessing.
    """
    result = getattr(visual_plan, "cohesive_visual_plan_result", None)
    payload = result.record.to_dict() if result is not None and getattr(result, "record", None) is not None else {}
    if not isinstance(payload, dict):
        raise PlacementExecutionError(
            "placement-binding-incomplete: governed plan carries no cohesive visual plan payload"
        )
    source_plan_id = payload.get("cohesive_visual_plan_id")
    if not isinstance(source_plan_id, str) or not source_plan_id:
        raise PlacementExecutionError("placement-binding-incomplete: cohesive plan has no plan identity")
    bindings: list[VisualPlacementBinding] = []
    for required, key in ((True, "required_role_assignments"), (False, "optional_role_assignments")):
        assignments = payload.get(key, ())
        if not isinstance(assignments, (list, tuple)):
            continue
        for assignment in assignments:
            if not isinstance(assignment, Mapping):
                continue
            role_id = assignment.get("role_id")
            selected = assignment.get("selected_candidate")
            asset_reference = selected.get("asset_reference") if isinstance(selected, Mapping) else None
            library_reference = selected.get("library_reference") if isinstance(selected, Mapping) else None
            asset_id = asset_reference.get("asset_id") if isinstance(asset_reference, Mapping) else None
            drive_file_id = library_reference.get("drive_file_id") if isinstance(library_reference, Mapping) else None
            fingerprint = asset_reference.get("content_fingerprint") if isinstance(asset_reference, Mapping) else None
            if not (isinstance(role_id, str) and role_id and isinstance(asset_id, str) and asset_id
                    and isinstance(drive_file_id, str) and drive_file_id):
                raise PlacementExecutionError(
                    "placement-binding-incomplete: assignment is missing role_id, asset_id, or drive_file_id; "
                    "refusing to guess the selected reference"
                )
            try:
                identity = content_identity_from_fingerprint(fingerprint) if fingerprint else None
            except (ValueError, TypeError):
                identity = None
            if not is_valid_content_identity(identity):
                raise PlacementExecutionError(
                    f"placement-binding-missing-content-identity: role={role_id} asset={asset_id}; "
                    "placement must never proceed on bytes that were not reviewed (#3256)"
                )
            evidence = assignment.get("compatibility_evidence")
            if not isinstance(evidence, Mapping) or not evidence:
                raise PlacementExecutionError(
                    f"placement-eligibility-evidence-missing: role={role_id} asset={asset_id}; "
                    "placement consumes explicit eligibility evidence and never infers it (#3253/#3254)"
                )
            raw_slot = assignment.get("slot_id", 0)
            bindings.append(
                VisualPlacementBinding(
                    role_id=role_id,
                    asset_id=asset_id,
                    drive_file_id=drive_file_id,
                    content_identity=dict(identity),
                    source_plan_id=source_plan_id,
                    required=required,
                    slot_id=str(raw_slot),
                    eligibility_evidence=dict(evidence),
                )
            )
    seen: dict[tuple[str, str], VisualPlacementBinding] = {}
    for binding in bindings:
        key = (binding.role_id, binding.slot_id)
        if key in seen:
            raise PlacementExecutionError(
                f"placement-binding-ambiguous: duplicate binding for role={binding.role_id} slot={binding.slot_id}; "
                "failing closed instead of placing twice"
            )
        seen[key] = binding
    return tuple(sorted(bindings, key=lambda b: (b.role_id, b.slot_id)))


def _paragraph_texts(paragraph: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for element in paragraph.get("elements", ()):
        if not isinstance(element, Mapping):
            continue
        text_run = element.get("textRun")
        if isinstance(text_run, Mapping):
            content = text_run.get("content")
            if isinstance(content, str):
                parts.append(content)
    return "".join(parts)


def discover_docs_markers(*, docs_service: Any, document_id: str) -> list[dict[str, Any]]:
    """Discover controlled visual markers in a live Google Doc.

    Markers are ``{{visual:<role_id>}}`` (implicit slot) or
    ``{{visual:<role_id>:<slot_id>}}`` (explicit slot, #3251). A marker is
    a paragraph whose full stripped text is exactly the controlled marker.
    Returns pre-discovered matches for ``resolve_exact_target``; discovery
    never mutates. Each match carries the artifact's own marker spelling so
    slot bindings survive into placement targets and receipts.
    """
    response = docs_service.documents().get(documentId=document_id, fields="body/content").execute()
    body = response.get("body", {}) if isinstance(response, dict) else {}
    content = body.get("content", ()) if isinstance(body, dict) else ()
    matches: list[dict[str, Any]] = []
    for index, element in enumerate(content):
        if not isinstance(element, Mapping):
            continue
        paragraph = element.get("paragraph")
        if not isinstance(paragraph, Mapping):
            continue
        text = _paragraph_texts(paragraph).strip()
        if not text:
            continue
        try:
            parse_marker_binding(text)
        except VisualPlacementError:
            continue
        matches.append(
            {
                "marker": text,
                "container_id": "body",
                "element_id": f"body-child-{index}",
                "index": index,
            }
        )
    return matches


def _shape_text(shape: Mapping[str, Any]) -> str:
    text = shape.get("text", {})
    if not isinstance(text, Mapping):
        return ""
    parts: list[str] = []
    for text_element in text.get("textElements", ()):
        if not isinstance(text_element, Mapping):
            continue
        text_run = text_element.get("textRun")
        if isinstance(text_run, Mapping):
            content = text_run.get("content")
            if isinstance(content, str):
                parts.append(content)
    return "".join(parts)


def discover_slides_markers(*, slides_service: Any, presentation_id: str) -> list[dict[str, Any]]:
    """Discover controlled visual markers in a live Slides deck.

    Markers are ``{{visual:<role_id>}}`` (implicit slot) or
    ``{{visual:<role_id>:<slot_id>}}`` (explicit slot, #3251). A marker is
    a shape whose full stripped text is exactly the controlled marker.
    Returns pre-discovered matches for ``resolve_exact_target``;
    discovery never mutates.
    """
    response = slides_service.presentations().get(
        presentationId=presentation_id,
        fields="slides(objectId,pageElements(objectId,shape(text(textElements(textRun(content))))))",
    ).execute()
    slides = response.get("slides", ()) if isinstance(response, dict) else ()
    matches: list[dict[str, Any]] = []
    for slide in slides:
        if not isinstance(slide, Mapping):
            continue
        slide_id = slide.get("objectId")
        for page_element in slide.get("pageElements", ()):
            if not isinstance(page_element, Mapping):
                continue
            shape = page_element.get("shape")
            if not isinstance(shape, Mapping):
                continue
            text = _shape_text(shape).strip()
            if not text:
                continue
            try:
                parse_marker_binding(text)
            except VisualPlacementError:
                continue
            element_id = page_element.get("objectId")
            if not isinstance(element_id, str) or not element_id or not isinstance(slide_id, str) or not slide_id:
                continue
            matches.append(
                {
                    "marker": text,
                    "container_id": slide_id,
                    "element_id": element_id,
                }
            )
    return matches


def _revision_id(*, artifact_type: str, service: Any, artifact_id: str) -> str:
    if artifact_type == "slides":
        return get_slides_revision_id(service, artifact_id)
    return get_docs_revision_id(service, artifact_id)


def _verify_insertion_against_artifact(
    *,
    artifact_type: str,
    service: Any,
    artifact_id: str,
    binding: VisualPlacementBinding,
    inserted_element_id: str,
) -> None:
    """Verify the insertion against the persisted artifact.

    The placement marker must be gone from the live artifact; for Slides the
    inserted element must additionally be present. This is the positive
    proof that replaces the old fail-closed refusal: placement is reported
    only when the persisted artifact shows it.
    """
    if artifact_type == "slides":
        matches = discover_slides_markers(slides_service=service, presentation_id=artifact_id)
        remaining = [
            m
            for m in matches
            if parse_marker_binding(m["marker"]) == (binding.role_id, binding.slot_id)
        ]
        if remaining:
            raise PlacementExecutionError(
                f"post-insertion-verification-failed: marker for role={binding.role_id} slot={binding.slot_id} "
                f"is still present in {artifact_id} after the transport reported placement"
            )
        response = service.presentations().get(
            presentationId=artifact_id, fields="slides(objectId,pageElements(objectId))"
        ).execute()
        element_ids: set[str] = set()
        for slide in response.get("slides", ()):
            if not isinstance(slide, Mapping):
                continue
            for page_element in slide.get("pageElements", ()):
                if isinstance(page_element, Mapping) and isinstance(page_element.get("objectId"), str):
                    element_ids.add(page_element["objectId"])
        if inserted_element_id not in element_ids:
            raise PlacementExecutionError(
                f"post-insertion-verification-failed: inserted element {inserted_element_id} for "
                f"role={binding.role_id} is absent from the persisted presentation {artifact_id}"
            )
    else:
        matches = discover_docs_markers(docs_service=service, document_id=artifact_id)
        remaining = [
            m
            for m in matches
            if parse_marker_binding(m["marker"]) == (binding.role_id, binding.slot_id)
        ]
        if remaining:
            raise PlacementExecutionError(
                f"post-insertion-verification-failed: marker for role={binding.role_id} slot={binding.slot_id} "
                f"is still present in {artifact_id} after the transport reported placement"
            )


def _place_one_binding(
    *,
    binding: VisualPlacementBinding,
    artifact_type: str,
    artifact_id: str,
    match: Mapping[str, Any],
    drive_service: Any,
    artifact_service: Any,
    transport: PlacementTransport,
    receipts_dir: str | None,
    idempotency_key: str,
) -> tuple[BindingOutcome, dict[str, Any] | None]:
    """Run the full governed placement chain for one binding in one artifact."""
    target = resolve_exact_target(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        artifact_revision_id=_revision_id(
            artifact_type=artifact_type, service=artifact_service, artifact_id=artifact_id
        ),
        role_id=binding.role_id,
        slot_id=binding.slot_id,
        matches=[match],
    )
    request = build_placement_request(
        selected_asset={
            "asset_id": binding.asset_id,
            "drive_file_id": binding.drive_file_id,
            "content_identity": dict(binding.content_identity),
        },
        role_id=binding.role_id,
        slot_id=binding.slot_id,
        source_plan_id=binding.source_plan_id,
        target=target,
    )
    # Exact-content verification immediately before insertion (#3256).
    # Every non-match outcome fails visibly with its own reason -- never
    # absence, never a generation handoff (#3248).
    described = describe_drive_file_outcome(drive_service, binding.drive_file_id)
    outcome = described.get("outcome")
    metadata = described.get("metadata")
    if outcome == "not-found":
        raise PlacementExecutionError(
            f"asset-missing: Drive file {binding.drive_file_id} for asset {binding.asset_id} "
            f"(role={binding.role_id}) is missing or trashed; blocked as missing, not a visual gap"
        )
    if outcome == "no-access":
        raise PlacementExecutionError(
            f"asset-access-failure: Drive file {binding.drive_file_id} for asset {binding.asset_id} "
            f"(role={binding.role_id}) is not accessible; blocked as access failure, not absence"
        )
    if outcome != "ok" or not isinstance(metadata, Mapping):
        raise PlacementExecutionError(
            f"asset-unverifiable: Drive lookup for file {binding.drive_file_id} "
            f"(role={binding.role_id}) failed; failing closed without guessing"
        )
    identity_outcome = verify_request_content_identity(request=request, drive_metadata=metadata)
    if identity_outcome != "content-identity-match":
        raise PlacementExecutionError(
            f"{identity_outcome}: live Drive bytes for file {binding.drive_file_id} do not match the "
            f"approved content identity for asset {binding.asset_id} (role={binding.role_id}); "
            "stale bytes are never placed silently and never reinterpret the selection"
        )
    try:
        raw = transport.insert_placement(request=request)
    except PlacementRuntimeUnavailable:
        raise
    except PlacementTransportError:
        raise
    except Exception as exc:
        raise PlacementTransportError(
            f"placement-transport-failed: transport {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(raw, Mapping):
        raise PlacementTransportError("placement-transport-failed: transport returned no result mapping")
    _verify_insertion_against_artifact(
        artifact_type=artifact_type,
        service=artifact_service,
        artifact_id=artifact_id,
        binding=binding,
        inserted_element_id=str(raw.get("inserted_element_id") or ""),
    )
    # Assemble the receipt candidate from request-known identity plus the
    # transport's completion claim; the verifier accepts only an exact
    # reconstruction.
    receipt_candidate = {
        "asset_id": request.asset_id,
        "drive_file_id": request.drive_file_id,
        "role_id": request.role_id,
        "slot_id": request.slot_id,
        "artifact_type": request.target.artifact_type,
        "artifact_id": request.target.artifact_id,
        "artifact_revision_id": request.target.artifact_revision_id,
        "marker": request.target.marker,
        "container_id": request.target.container_id,
        "content_identity": dict(request.content_identity),
        "state": raw.get("state"),
        "inserted_element_id": raw.get("inserted_element_id"),
    }
    try:
        verified = verify_placement_receipt(request, receipt_candidate)
    except VisualPlacementError as exc:
        raise PlacementExecutionError(f"placement-receipt-rejected: {exc}") from exc
    if not receipts_dir:
        raise PlacementExecutionError(
            "placement-receipt-store-unavailable: a verified placement without a durable "
            "receipt is a false success; refusing to report placement"
        )
    post_revision = _revision_id(artifact_type=artifact_type, service=artifact_service, artifact_id=artifact_id)
    record = append_placement_record(
        receipts_dir,
        idempotency_key,
        build_placement_record(
            receipt={
                "asset_id": verified.asset_id,
                "drive_file_id": verified.drive_file_id,
                "role_id": verified.role_id,
                "artifact_type": verified.artifact_type,
                "artifact_id": verified.artifact_id,
                "artifact_revision_id": verified.artifact_revision_id,
                "marker": verified.marker,
                "container_id": verified.container_id,
                "inserted_element_id": verified.inserted_element_id,
                "state": verified.state,
            },
            content_identity=dict(binding.content_identity),
            slot_id=binding.slot_id,
            source_plan_id=binding.source_plan_id,
            required=binding.required,
            eligibility_evidence=binding.eligibility_evidence,
            transport_name=getattr(transport, "name", type(transport).__name__),
            post_insertion_revision=post_revision,
        ),
    )
    outcome_record = BindingOutcome(
        binding=binding,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        status="placed",
        record=record,
    )
    return outcome_record, record


def execute_artifact_visual_placements(
    *,
    bindings: tuple[VisualPlacementBinding, ...] | list[VisualPlacementBinding],
    artifact_type: str,
    artifact_id: str,
    drive_service: Any,
    artifact_service: Any,
    transport: PlacementTransport | None,
    receipts_dir: str | None,
    idempotency_key: str,
) -> tuple[BindingOutcome, ...]:
    """Place every binding whose marker is discovered in one live artifact.

    Bindings with no marker in this artifact are skipped (the marker, not
    the planner, decides which artifact receives a visual); bindings with
    more than one marker fail closed. Already-verified bindings are
    recovered from the durable receipt store instead of being inserted
    again (#3252 retry idempotency). Any attempted binding that cannot be
    verified-placed fails the whole run closed via
    ``PlacementExecutionError`` -- placement failure is never absence and
    never authorizes generation.
    """
    kind = str(artifact_type).strip().lower()
    if kind not in ("docs", "slides"):
        raise PlacementExecutionError(f"unsupported placement artifact type: {artifact_type!r}")
    bindings = tuple(bindings or ())
    if not bindings:
        return ()
    if transport is None:
        raise PlacementRuntimeUnavailable(
            "placement-runtime-unavailable: a placement transport is required to place "
            f"{len(bindings)} selected visual(s) into {kind}:{artifact_id}; no transport "
            "is configured. This is an explicit blocked state, never final."
        )
    if kind == "slides":
        discovered = discover_slides_markers(slides_service=artifact_service, presentation_id=artifact_id)
    else:
        discovered = discover_docs_markers(docs_service=artifact_service, document_id=artifact_id)
    # #3251: bindings key on (role_id, slot_id). One role may own several
    # markers (one per slot); two markers for the SAME binding still fail
    # closed as ambiguous.
    by_binding: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for match in discovered:
        by_binding.setdefault(parse_marker_binding(match["marker"]), []).append(match)
    stored = load_placement_records(receipts_dir, idempotency_key) if receipts_dir else ()
    outcomes: list[BindingOutcome] = []
    for binding in bindings:
        # Recovery first (#3252): a verified receipt for this exact binding
        # means the visual is already placed -- recover it instead of
        # inserting again. This check precedes marker discovery because a
        # successful placement removes the marker from the artifact.
        recovered = find_verified_record(
            stored,
            role_id=binding.role_id,
            slot_id=binding.slot_id,
            artifact_type=kind,
            artifact_id=artifact_id,
            content_identity=binding.content_identity,
        )
        if recovered is not None:
            outcomes.append(BindingOutcome(binding, kind, artifact_id, "recovered", record=recovered))
            continue
        matches = by_binding.get((binding.role_id, binding.slot_id), [])
        if not matches:
            outcomes.append(
                BindingOutcome(binding, kind, artifact_id, "skipped-no-marker",
                               reason="no placement marker for this role/slot in this artifact")
            )
            continue
        if len(matches) > 1:
            outcomes.append(
                BindingOutcome(binding, kind, artifact_id, "failed",
                               reason=f"marker-ambiguous: {len(matches)} markers for role={binding.role_id} "
                                      f"slot={binding.slot_id} in this artifact; failing closed instead of guessing the target")
            )
            continue
        try:
            binding_outcome, _ = _place_one_binding(
                binding=binding,
                artifact_type=kind,
                artifact_id=artifact_id,
                match=matches[0],
                drive_service=drive_service,
                artifact_service=artifact_service,
                transport=transport,
                receipts_dir=receipts_dir,
                idempotency_key=idempotency_key,
            )
            outcomes.append(binding_outcome)
        except PlacementRuntimeUnavailable:
            raise
        except (PlacementExecutionError, PlacementTransportError, VisualPlacementError) as exc:
            outcomes.append(BindingOutcome(binding, kind, artifact_id, "failed", reason=str(exc)))
        except Exception as exc:
            outcomes.append(
                BindingOutcome(binding, kind, artifact_id, "failed",
                               reason=f"placement-transport-failed: unexpected {type(exc).__name__}: {exc}")
            )
    failed = [o for o in outcomes if o.status == "failed"]
    if failed:
        detail = "; ".join(f"role={o.binding.role_id} slot={o.binding.slot_id}: {o.reason}" for o in failed)
        raise PlacementExecutionError(
            f"visual placement failed closed for {len(failed)} binding(s) in {kind}:{artifact_id}: {detail}. "
            "Placement failure is not visual absence and does not authorize new visual creation.",
            outcomes=tuple(outcomes),
        )
    return tuple(outcomes)


def require_all_required_visuals_placed(
    *,
    bindings: tuple[VisualPlacementBinding, ...] | list[VisualPlacementBinding],
    receipts_dir: str | None,
    idempotency_key: str,
    artifact_files: Mapping[str, str],
) -> None:
    """Fail closed unless every required binding has a verified receipt.

    A visuals-required build can complete only when every required slot is
    verified-placed; it cannot complete otherwise. This is the backstop for
    paths where placement ran in an earlier attempt (resume recovery).
    """
    required = [b for b in (bindings or ()) if b.required]
    if not required:
        return
    if not receipts_dir:
        raise PlacementExecutionError(
            "placement-receipt-store-unavailable: required visual placements cannot be "
            "proven without the durable receipt store"
        )
    records = load_placement_records(receipts_dir, idempotency_key)
    artifact_ids = {str(v) for v in artifact_files.values() if v}
    missing: list[str] = []
    for binding in sorted(required, key=lambda b: (b.role_id, b.slot_id)):
        satisfied = any(
            record.get("state") == "verified"
            and record.get("role_id") == binding.role_id
            and str(record.get("slot_id")) == str(binding.slot_id)
            and record.get("artifact_id") in artifact_ids
            and record.get("content_identity") == dict(binding.content_identity)
            for record in records
        )
        if not satisfied:
            missing.append(f"role={binding.role_id} slot={binding.slot_id} asset={binding.asset_id}")
    if missing:
        raise PlacementExecutionError(
            "required visual placements are not verified-placed: " + "; ".join(missing) + ". "
            "The build cannot complete until every required slot carries a verified placement receipt."
        )
