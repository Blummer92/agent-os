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

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

from instructional_workflow_contracts.asset_content_identity import (
    content_identity_from_fingerprint,
    is_valid_content_identity,
)

from .drive_client import describe_drive_file_outcome
from .placement_receipts import (
    append_placement_record,
    build_placement_record,
    find_verified_record,
    load_batch_proofs,
    load_placement_records,
    load_placement_records_strict,
    load_placement_attempt,
    begin_placement_attempt,
    clear_placement_attempt,
    assert_no_unresolved_placement_attempts,
    placement_attempt_path,
    reconcile_placement_batch,
    validate_batch_proof_structure,
    PlacementStoreIntegrityError,
)
from .placement_transport import (
    PlacementRuntimeUnavailable,
    PlacementTransport,
    PlacementTransportError,
    PlacementNoMutation,
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


if TYPE_CHECKING:
    # Annotation-only: artifact_content_qa imports this module
    # (_revision_chain_is_current), so the runtime import of its observation
    # surface stays function-local (see _observe_artifact_state) to avoid a
    # circular import.
    from .artifact_content_qa import ArtifactObservation


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
    expected_container_id: str | None = None,
) -> None:
    """Verify the insertion against the persisted artifact.

    The placement marker must be gone from the live artifact; for Slides the
    inserted element must additionally be present. This is the positive
    proof that replaces the old fail-closed refusal: placement is reported
    only when the persisted artifact shows it.
    """
    if not inserted_element_id:
        raise PlacementExecutionError(
            "post-insertion-verification-failed: inserted element identity is missing"
        )
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
            presentationId=artifact_id, fields="slides(objectId,pageElements(objectId,image))"
        ).execute()
        element_ids: set[str] = set()
        for slide in response.get("slides", ()):
            if not isinstance(slide, Mapping):
                continue
            if expected_container_id and slide.get("objectId") != expected_container_id:
                continue
            for page_element in slide.get("pageElements", ()):
                if (isinstance(page_element, Mapping)
                        and isinstance(page_element.get("objectId"), str)
                        and isinstance(page_element.get("image"), Mapping)):
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
        # A removed marker alone does not prove that an image exists in the
        # current Doc. Confirm the receipt's embeddedObjectId is actually
        # referenced by the persisted body and the inlineObjects map.
        response = service.documents().get(
            documentId=artifact_id, fields="inlineObjects,body(content)"
        ).execute()
        if not isinstance(response, Mapping):
            raise PlacementExecutionError(
                "post-insertion-verification-failed: persisted Docs readback was invalid"
            )
        objects = response.get("inlineObjects")
        if not isinstance(objects, Mapping) or inserted_element_id not in objects:
            raise PlacementExecutionError(
                f"post-insertion-verification-failed: inline object {inserted_element_id} "
                f"is absent from the persisted document {artifact_id}"
            )
        body = response.get("body")
        content = body.get("content", ()) if isinstance(body, Mapping) else ()
        referenced = False
        for element in content:
            paragraph = element.get("paragraph") if isinstance(element, Mapping) else None
            if not isinstance(paragraph, Mapping):
                continue
            for part in paragraph.get("elements", ()):
                obj = part.get("inlineObjectElement") if isinstance(part, Mapping) else None
                if isinstance(obj, Mapping) and obj.get("embeddedObjectId") == inserted_element_id:
                    referenced = True
                    break
            if referenced:
                break
        if not referenced:
            raise PlacementExecutionError(
                f"post-insertion-verification-failed: inline object {inserted_element_id} "
                f"is not referenced in the persisted document body {artifact_id}"
            )



def _revision_chain_is_current(
    record: Mapping[str, Any], all_records: tuple[dict[str, Any], ...], current_revision: str,
) -> bool:
    """Accept later *recorded placements*, never an unexplained revision drift.

    One image can be placed at r1->r2 and another at r2->r3. The first
    placement remains recoverable at r3 only if that full chain is recorded.
    """
    revision = record.get('post_insertion_revision_id')
    if not isinstance(revision, str) or not revision:
        return False
    seen: set[str] = set()
    while revision != current_revision:
        if revision in seen:
            return False
        seen.add(revision)
        candidates = [r for r in all_records if r.get('state') == 'verified'
                      and r.get('artifact_type') == record.get('artifact_type')
                      and r.get('artifact_id') == record.get('artifact_id')
                      and r.get('artifact_revision_id') == revision]
        if len(candidates) != 1:
            return False
        revision = candidates[0].get('post_insertion_revision_id')
        if not isinstance(revision,str) or not revision:
            return False
    return True


def _attempt_matches_binding(attempt: Mapping[str, Any], binding: VisualPlacementBinding) -> bool:
    return (
        attempt.get('asset_id') == binding.asset_id
        and attempt.get('drive_file_id') == binding.drive_file_id
        and attempt.get('source_plan_id') == binding.source_plan_id
        and attempt.get('content_identity') == dict(binding.content_identity)
    )


def _artifact_element_ids(*, artifact_type: str, service: Any, artifact_id: str) -> frozenset[str]:
    if artifact_type == 'docs':
        response = service.documents().get(documentId=artifact_id,fields='inlineObjects').execute()
        if not isinstance(response,Mapping):
            raise PlacementExecutionError('placement-readback-unavailable: invalid Docs readback')
        # Google Docs omits inlineObjects when the document has zero images.
        obj = response.get('inlineObjects',{})
        if not isinstance(obj,Mapping):
            raise PlacementExecutionError('placement-readback-unavailable: malformed Docs inlineObjects')
        return frozenset(str(v) for v in obj)
    response = service.presentations().get(
        presentationId=artifact_id,fields='slides(objectId,pageElements(objectId))'
    ).execute()
    slides = response.get('slides') if isinstance(response,Mapping) else None
    if not isinstance(slides,(list,tuple)):
        raise PlacementExecutionError('placement-readback-unavailable: Slides page elements not observable')
    ids = set()
    for slide in slides:
        if not isinstance(slide,Mapping):
            raise PlacementExecutionError('placement-readback-unavailable: malformed slide')
        els = slide.get('pageElements',())
        if not isinstance(els,(list,tuple)):
            raise PlacementExecutionError('placement-readback-unavailable: malformed slide elements')
        for el in els:
            if isinstance(el,Mapping) and isinstance(el.get('objectId'),str):
                ids.add(el['objectId'])
    return frozenset(ids)


def _no_mutation_observed(
    *, artifact_type: str, service: Any, artifact_id: str,
    binding: VisualPlacementBinding, target_revision: str,
    target_marker: str, target_container: str, target_element: str,
    before_element_ids: frozenset[str],
) -> bool:
    """Fresh revision + original marker prove a transport failure had no effect.

    If readback fails or revision changes, retain the durable fence. This
    check only unlocks the existing known-no-write test case; it never
    infers ownership of an orphaned image.
    """
    try:
        if _revision_id(artifact_type=artifact_type,service=service,artifact_id=artifact_id) != target_revision:
            return False
        if _artifact_element_ids(artifact_type=artifact_type,service=service,artifact_id=artifact_id) != before_element_ids:
            return False
        matches = (discover_slides_markers(slides_service=service,presentation_id=artifact_id)
                   if artifact_type == 'slides' else
                   discover_docs_markers(docs_service=service,document_id=artifact_id))
        found = [m for m in matches if m.get('marker') == target_marker
                 and m.get('container_id') == target_container
                 and m.get('element_id') == target_element
                 and parse_marker_binding(m['marker']) == (binding.role_id,binding.slot_id)]
        return len(found) == 1
    except Exception:
        return False


def _observe_artifact_state(
    *,
    artifact_type: str,
    service: Any,
    artifact_id: str,
) -> "ArtifactObservation":
    """Read back the persisted artifact for insertion-continuity evidence.

    Uses the exact same observation surface terminal QA consumes, so the
    continuity evidence and the QA readback cannot disagree about what the
    artifact contained. The import is function-local: artifact_content_qa
    imports this module (for _revision_chain_is_current), so a top-level
    import here would be circular.
    """
    from .artifact_content_qa import (
        ArtifactInaccessibleError,
        VerificationRuntimeUnavailableError,
        observe_artifact,
    )
    try:
        return observe_artifact(service, artifact_type, artifact_id)
    except (VerificationRuntimeUnavailableError, ArtifactInaccessibleError) as exc:
        raise PlacementExecutionError(
            f"placement-continuity-unverifiable: cannot read back {artifact_type} "
            f"{artifact_id} to verify insertion continuity: {exc}"
        ) from exc
    except Exception as exc:
        raise PlacementExecutionError(
            f"placement-continuity-unverifiable: unexpected {type(exc).__name__} "
            f"reading back {artifact_type} {artifact_id}: {exc}"
        ) from exc


def _check_insertion_continuity(
    *,
    pre: "ArtifactObservation",
    post: "ArtifactObservation",
    marker: str,
    inserted_element_id: str,
    binding: VisualPlacementBinding,
) -> dict[str, Any]:
    """Verify that one insertion mutated the artifact in exactly the expected way.

    The only permitted changes between the pre- and post-insertion
    snapshots are: the single placement marker's removal and the appearance
    of exactly the reported inserted element. Any other element addition or
    removal, any other text change, or a reused element id fails closed --
    an external or intervening mutation (or a same-ID byte replacement the
    transport cannot prove) must never be absorbed into a verified batch.
    Returns the continuity evidence bound into the batch proof.
    """
    from .artifact_content_qa import normalize_text
    role_id = binding.role_id
    slot_id = str(binding.slot_id)
    element_id = str(inserted_element_id or "")
    if not element_id:
        raise PlacementExecutionError(
            f"placement-element-id-missing: transport reported no inserted element "
            f"id for role={role_id} slot={slot_id}; the insertion cannot be proven"
        )
    pre_ids = set(pre.image_element_ids)
    post_ids = set(post.image_element_ids)
    if element_id in pre_ids:
        raise PlacementExecutionError(
            f"placement-element-id-reused: inserted element {element_id} for "
            f"role={role_id} slot={slot_id} was already present before this "
            "insertion; the transport cannot prove these bytes are the new "
            "insertion (same-ID byte replacement is rejected)"
        )
    added = post_ids - pre_ids
    removed = pre_ids - post_ids
    if added != {element_id} or removed:
        raise PlacementExecutionError(
            f"placement-continuity-broken: insertion for role={role_id} "
            f"slot={slot_id} changed the artifact's element set beyond the "
            f"single reported insertion (added={sorted(added)} "
            f"removed={sorted(removed)}); external or intervening mutation "
            "suspected"
        )
    if not marker or marker not in pre.full_text:
        raise PlacementExecutionError(
            f"placement-continuity-unverifiable: marker {marker!r} for "
            f"role={role_id} slot={slot_id} was not observed before insertion"
        )
    # The only permitted text delta is the single marker's removal. Docs
    # observations carry raw text (byte-exact check); Slides observations
    # carry whitespace-normalized per-slide text, so both sides are
    # normalized before comparison there.
    if pre.artifact_type == "slides":
        text_changed = normalize_text(
            pre.full_text.replace(marker, "", 1)
        ) != normalize_text(post.full_text)
    else:
        text_changed = post.full_text != pre.full_text.replace(marker, "", 1)
    if text_changed:
        raise PlacementExecutionError(
            f"placement-continuity-broken: artifact text for role={role_id} "
            f"slot={slot_id} changed beyond the single marker removal during "
            "insertion; external or intervening mutation suspected"
        )
    return {
        "role_id": role_id,
        "slot_id": slot_id,
        "inserted_element_id": element_id,
        "pre_revision_id": pre.revision_id,
        "post_revision_id": post.revision_id,
        "pre_text_digest": hashlib.sha256(pre.full_text.encode("utf-8")).hexdigest(),
        "post_text_digest": hashlib.sha256(post.full_text.encode("utf-8")).hexdigest(),
        "pre_element_ids": sorted(pre_ids),
        "post_element_ids": sorted(post_ids),
    }


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
) -> tuple[BindingOutcome, dict[str, Any] | None, dict[str, Any] | None]:
    """Run the full governed placement chain for one binding in one artifact.

    Returns (outcome, stored record, insertion-continuity evidence). The
    artifact is observed immediately before and after the transport call;
    the continuity evidence proves the insertion mutated the artifact in
    exactly the expected way (single marker removal, single new element),
    and is bound into the run's reconciled batch proof (#3258).
    """
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
    if not receipts_dir:
        raise PlacementExecutionError(
            'placement-receipt-store-unavailable: cannot begin an unjournaled external insertion'
        )
    # Snapshot persisted object identity before attempting any mutation.
    # Without an observable baseline, a known-no-effect retry cannot be
    # established and placement must block before the transport call.
    pre_ids = _artifact_element_ids(
        artifact_type=artifact_type,service=artifact_service,artifact_id=artifact_id
    )
    if _revision_id(artifact_type=artifact_type,service=artifact_service,
                    artifact_id=artifact_id) != request.target.artifact_revision_id:
        raise PlacementExecutionError('placement-revision-stale: artifact changed before insertion')
    intent = {
        'artifact_type': artifact_type, 'artifact_id': artifact_id,
        'role_id': binding.role_id, 'slot_id': binding.slot_id,
        'asset_id': binding.asset_id, 'drive_file_id': binding.drive_file_id,
        'source_plan_id': binding.source_plan_id,
        'content_identity': dict(binding.content_identity),
        'artifact_revision_id': request.target.artifact_revision_id,
        'marker': request.target.marker, 'container_id': request.target.container_id,
    }
    begin_placement_attempt(receipts_dir, idempotency_key, intent)
    # Observe the artifact immediately before the transport acts: this is
    # the pre-insertion anchor for continuity evidence (#3258).
    pre_observation = _observe_artifact_state(
        artifact_type=artifact_type, service=artifact_service, artifact_id=artifact_id
    )
    try:
        raw = transport.insert_placement(request=request)
    except Exception as exc:
        # A timeout may happen AFTER the remote insertion succeeded. Only
        # release the fence if fresh persisted readback proves no mutation.
        # Retry classification (#3257 x #3258 producer hardening): the
        # transport's PlacementTransportError raises are NEVER
        # PlacementNoMutation, so none of them may release the fence. A
        # revision-less request never reached the runtime, but a rejected
        # result claim (synthetic element id, missing post-placement
        # revision evidence) may follow a real remote insertion -- the
        # fence is kept in both cases and no retry may reinsert blindly.
        if isinstance(exc, PlacementNoMutation) and _no_mutation_observed(
            artifact_type=artifact_type, service=artifact_service, artifact_id=artifact_id,
            binding=binding, target_revision=request.target.artifact_revision_id,
            target_marker=request.target.marker, target_container=request.target.container_id,
            target_element=request.target.element_id, before_element_ids=pre_ids,
        ):
            clear_placement_attempt(receipts_dir, idempotency_key, intent)
        if isinstance(exc, (PlacementRuntimeUnavailable, PlacementTransportError)):
            raise
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
        expected_container_id=request.target.container_id,
    )
    # Observe again immediately after: the only permitted delta is the
    # single marker removal plus the single reported inserted element.
    # External/intervening mutations and same-ID byte replacement fail
    # closed here; the fence stays held so a failed continuity check can
    # never be retried into a duplicate insertion.
    post_observation = _observe_artifact_state(
        artifact_type=artifact_type, service=artifact_service, artifact_id=artifact_id
    )
    continuity = _check_insertion_continuity(
        pre=pre_observation,
        post=post_observation,
        marker=request.target.marker,
        inserted_element_id=raw.get("inserted_element_id"),
        binding=binding,
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
    post_revision = post_observation.revision_id
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
    clear_placement_attempt(receipts_dir, idempotency_key, intent)
    outcome_record = BindingOutcome(
        binding=binding,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        status="placed",
        record=record,
    )
    return outcome_record, record, continuity


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
    never authorizes generation. On success the run's ordered complete
    receipt set is reconciled against the current artifact snapshot and an
    atomic batch proof is persisted (#3258); original per-insertion
    receipts are preserved untouched.
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
    # #3258: the run's initial artifact state anchors the batch
    # reconciliation chain (every insertion's pre/post revisions must link
    # back to this observation).
    initial_observation = _observe_artifact_state(
        artifact_type=kind, service=artifact_service, artifact_id=artifact_id
    )
    # #3251: bindings key on (role_id, slot_id). One role may own several
    # markers (one per slot); two markers for the SAME binding still fail
    # closed as ambiguous.
    by_binding: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for match in discovered:
        by_binding.setdefault(parse_marker_binding(match["marker"]), []).append(match)
    if not receipts_dir:
        raise PlacementExecutionError('placement-receipt-store-unavailable: cannot verify recovery')
    try:
        stored = load_placement_records_strict(receipts_dir, idempotency_key)
    except PlacementStoreIntegrityError as exc:
        raise PlacementExecutionError(str(exc)) from exc
    # Current bindings may retain a matching crash-after-receipt fence,
    # which is verified and cleared by the existing recovery path below.
    # All OTHER attempt files (including abandoned roles, artifacts, and
    # malformed unknown files) must block before any fresh remote mutation.
    permitted = frozenset(
        placement_attempt_path(
            receipts_dir, idempotency_key, artifact_type=kind,
            artifact_id=artifact_id, role_id=binding.role_id, slot_id=binding.slot_id,
        )
        for binding in bindings
    )
    try:
        assert_no_unresolved_placement_attempts(
            receipts_dir, idempotency_key, permitted_for_recovery=permitted,
        )
    except PlacementStoreIntegrityError as exc:
        raise PlacementExecutionError(str(exc)) from exc
    # Preflight every currently selected pending attempt BEFORE inserting
    # another image. An unreceipted in-plan attempt also fails closed.
    for binding in bindings:
        try:
            pending = load_placement_attempt(
                receipts_dir,idempotency_key,artifact_type=kind,artifact_id=artifact_id,
                role_id=binding.role_id,slot_id=binding.slot_id,
            )
        except PlacementStoreIntegrityError as exc:
            raise PlacementExecutionError(str(exc)) from exc
        if pending is not None:
            verified = find_verified_record(
                stored,role_id=binding.role_id,slot_id=binding.slot_id,
                artifact_type=kind,artifact_id=artifact_id,content_identity=binding.content_identity,
            )
            if verified is None:
                reason = ('placement-reconciliation-required: unreceipted mutation'
                          if _attempt_matches_binding(pending,binding) else
                          'placement-recovery-conflict: pending attempt does not match selected asset')
                raise PlacementExecutionError(reason, outcomes=(BindingOutcome(
                    binding,kind,artifact_id,'failed',reason=reason),))
    outcomes: list[BindingOutcome] = []
    placed: list[tuple[VisualPlacementBinding, BindingOutcome, dict[str, Any]]] = []
    recovered: list[VisualPlacementBinding] = []
    for binding in bindings:
        # Recovery first (#3252): a verified receipt for this exact binding
        # means the visual is already placed -- recover it instead of
        # inserting again. This check precedes marker discovery because a
        # successful placement removes the marker from the artifact.
        recovered_record = find_verified_record(
            stored,
            role_id=binding.role_id,
            slot_id=binding.slot_id,
            artifact_type=kind,
            artifact_id=artifact_id,
            content_identity=binding.content_identity,
        )
        if recovered_record is None and any(
            r.get('role_id') == binding.role_id and str(r.get('slot_id')) == str(binding.slot_id)
            and r.get('artifact_type') == kind and r.get('artifact_id') == artifact_id
            for r in stored
        ):
            outcomes.append(BindingOutcome(binding,kind,artifact_id,'failed',
                reason='placement-recovery-conflict: prior receipt differs from governed identity'))
            continue
        try:
            attempt = load_placement_attempt(
                receipts_dir,idempotency_key,artifact_type=kind,artifact_id=artifact_id,
                role_id=binding.role_id,slot_id=binding.slot_id,
            )
        except PlacementStoreIntegrityError as exc:
            outcomes.append(BindingOutcome(binding,kind,artifact_id,'failed',reason=str(exc)))
            continue
        if attempt is not None and not _attempt_matches_binding(attempt,binding):
            outcomes.append(BindingOutcome(binding,kind,artifact_id,'failed',
                reason='placement-recovery-conflict: in-flight attempt differs from selected asset'))
            continue
        if attempt is not None and recovered_record is None:
            outcomes.append(BindingOutcome(binding,kind,artifact_id,'failed',
                reason='placement-reconciliation-required: unknown insertion outcome; '
                       'do not reinsert or attribute an unreceipted image by marker absence'))
            continue
        if recovered_record is not None:
            # A matching role/content hash does not prove that a receipt
            # still describes the selected asset or a present image.
            # Reject evidence substitution instead of trusting the cache.
            if (
                recovered_record.get("asset_id") != binding.asset_id
                or recovered_record.get("drive_file_id") != binding.drive_file_id
                or recovered_record.get("source_plan_id") != binding.source_plan_id
                or recovered_record.get("required") != binding.required
                or not isinstance(recovered_record.get("inserted_element_id"), str)
                or not recovered_record.get("inserted_element_id")
                or (kind == "docs" and recovered_record.get("container_id") != "body")
            ):
                outcomes.append(BindingOutcome(
                    binding, kind, artifact_id, "failed",
                    reason="placement-recovery-conflict: verified receipt differs from the "
                           "governed selected asset or is missing target/element evidence",
                ))
                continue
            try:
                _verify_insertion_against_artifact(
                    artifact_type=kind,
                    service=artifact_service,
                    artifact_id=artifact_id,
                    binding=binding,
                    inserted_element_id=recovered_record["inserted_element_id"],
                    expected_container_id=str(recovered_record.get("container_id") or ""),
                )
            except Exception as exc:
                # Never reinsert on an uncertain outcome: the marker was
                # removed by the original placement, so target is ambiguous.
                outcomes.append(BindingOutcome(
                    binding, kind, artifact_id, "failed",
                    reason=f"placement-recovery-stale: current artifact does not "
                           f"verify the stored placement ({type(exc).__name__}: {exc})",
                ))
                continue
            live_revision = _revision_id(artifact_type=kind,service=artifact_service,artifact_id=artifact_id)
            if not _revision_chain_is_current(recovered_record,stored,live_revision):
                outcomes.append(BindingOutcome(binding,kind,artifact_id,'failed',
                    reason='placement-recovery-stale: unaccounted artifact revision drift'))
                continue
            if attempt is not None:
                # Crash after durable receipt but before deleting the fence:
                # current readback and the recorded revision chain are now
                # proven, so removing this exact matching fence is safe.
                try:
                    clear_placement_attempt(receipts_dir,idempotency_key,attempt)
                except PlacementStoreIntegrityError as exc:
                    outcomes.append(BindingOutcome(binding,kind,artifact_id,'failed',reason=str(exc)))
                    continue
            outcomes.append(BindingOutcome(binding, kind, artifact_id, "recovered", record=recovered_record))
            recovered.append(binding)
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
            binding_outcome, _, continuity = _place_one_binding(
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
            placed.append((binding, binding_outcome, continuity))
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
    # #3258: reconcile the completed batch against the current artifact
    # snapshot and persist the atomic batch proof. Original per-insertion
    # receipts are preserved untouched; the proof binds the ordered complete
    # receipt set to the observed final revision with verified mutation
    # continuity. Any unexplained drift fails closed here -- no proof.
    _reconcile_completed_batch(
        receipts_dir=receipts_dir,
        idempotency_key=idempotency_key,
        artifact_type=kind,
        artifact_id=artifact_id,
        bindings=bindings,
        placed=tuple(placed),
        recovered=tuple(recovered),
        initial_observation=initial_observation,
        artifact_service=artifact_service,
        pre_run_records=stored,
    )
    return tuple(outcomes)


def _reconcile_completed_batch(
    *,
    receipts_dir: str | None,
    idempotency_key: str,
    artifact_type: str,
    artifact_id: str,
    bindings: tuple[VisualPlacementBinding, ...],
    placed: tuple[tuple[VisualPlacementBinding, BindingOutcome, dict[str, Any]], ...],
    recovered: tuple[VisualPlacementBinding, ...],
    initial_observation: "ArtifactObservation",
    artifact_service: Any,
    pre_run_records: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any] | None:
    """Reconcile this run's complete receipt set and persist the batch proof.

    Every binding resolved in this run (placed or recovered) becomes a proof
    member. Recovered members must already have been reconciled by a prior
    batch proof (or predate batch proofs with the artifact unmoved since
    their insertion); their inserted elements must still be observable.
    Unexplained revision drift at any point fails closed without a proof.

    The proof is stored under the ``batch_artifact_type`` field (not
    ``artifact_type``): the proof-side artifact concept is deliberately
    named apart from the receipt envelope's ``artifact_type``.
    """
    if not placed and not recovered:
        return None
    if not receipts_dir:
        raise PlacementExecutionError(
            "placement-receipt-store-unavailable: cannot reconcile a placement "
            "batch without the durable receipt store"
        )
    final_observation = _observe_artifact_state(
        artifact_type=artifact_type, service=artifact_service, artifact_id=artifact_id
    )
    try:
        stored = load_placement_records_strict(receipts_dir, idempotency_key)
    except PlacementStoreIntegrityError as exc:
        raise PlacementExecutionError(str(exc)) from exc
    prior_proofs = [
        proof for proof in load_batch_proofs(receipts_dir, idempotency_key)
        if proof.get("batch_artifact_type") == artifact_type
        and str(proof.get("artifact_id")) == artifact_id
    ]
    latest = prior_proofs[-1] if prior_proofs else None
    initial_rev = initial_observation.revision_id
    # All revisions ever explained by prior proofs for this artifact.
    explained: set[str] = set()
    proven_members: set[tuple[str, str]] = set()
    if latest is not None:
        if initial_rev != str(latest.get("final_revision_id")):
            raise PlacementExecutionError(
                "placement-batch-unreconciled: artifact revision moved since the "
                f"latest reconciled batch proof (proof final={latest.get('final_revision_id')} "
                f"current={initial_rev}); refusing to reconcile across unexplained drift"
            )
        for proof in prior_proofs:
            # #3258 P1-1: validate prior-proof structure before iterating.
            # A malformed prior proof is corrupted evidence, not history:
            # reconciling against it could mask drift, so fail closed.
            structure_issues = validate_batch_proof_structure(proof)
            if structure_issues:
                raise PlacementExecutionError(
                    "placement-batch-unreconciled: a prior reconciled batch "
                    f"proof for {artifact_type} {artifact_id} is structurally "
                    f"malformed ({'; '.join(structure_issues)}); refusing to "
                    "reconcile against corrupted evidence"
                )
            explained.add(str(proof.get("initial_revision_id")))
            explained.add(str(proof.get("final_revision_id")))
            for entry in proof.get("insertion_continuity") or ():
                if isinstance(entry, Mapping):
                    explained.add(str(entry.get("pre_revision_id")))
                    explained.add(str(entry.get("post_revision_id")))
            for member in proof.get("ordered_members") or ():
                if isinstance(member, Mapping):
                    proven_members.add((str(member.get("role_id")), str(member.get("slot_id"))))
    # The insertion chain of this run must link initial -> ... -> final.
    continuity_entries = [continuity for _, _, continuity in placed]
    if continuity_entries:
        if str(continuity_entries[0].get("pre_revision_id")) != initial_rev:
            raise PlacementExecutionError(
                "placement-batch-unreconciled: the first insertion's pre-revision "
                "does not match this run's initial artifact observation; "
                "intervening mutation suspected"
            )
        for previous, current in zip(continuity_entries, continuity_entries[1:]):
            if str(current.get("pre_revision_id")) != str(previous.get("post_revision_id")):
                raise PlacementExecutionError(
                    "placement-batch-unreconciled: the insertion chain is broken "
                    "between two insertions of this run; an edit slipped in "
                    "between placements and no batch proof is written"
                )
            # Defense in depth: the observable artifact state must also link
            # across the chain, so even a revision-preserving content
            # mutation between insertions fails closed.
            if str(current.get("pre_text_digest")) != str(previous.get("post_text_digest")):
                raise PlacementExecutionError(
                    "placement-batch-unreconciled: artifact text diverged "
                    "between two insertions of this run; an edit slipped in "
                    "between placements and no batch proof is written"
                )
            if list(current.get("pre_element_ids") or []) != list(previous.get("post_element_ids") or []):
                raise PlacementExecutionError(
                    "placement-batch-unreconciled: artifact element set diverged "
                    "between two insertions of this run; an edit slipped in "
                    "between placements and no batch proof is written"
                )
        if final_observation.revision_id != str(continuity_entries[-1].get("post_revision_id")):
            raise PlacementExecutionError(
                "placement-batch-unreconciled: the artifact mutated between the "
                "last insertion and reconciliation; no batch proof is written"
            )
    elif final_observation.revision_id != initial_rev:
        raise PlacementExecutionError(
            "placement-batch-unreconciled: the artifact mutated during a "
            "recovery-only run; no batch proof is written"
        )
    placed_records = {
        (binding.role_id, str(binding.slot_id)): outcome
        for binding, outcome, _ in placed
    }
    resolved_keys = set(placed_records) | {
        (binding.role_id, str(binding.slot_id)) for binding in recovered
    }
    final_element_ids = set(final_observation.image_element_ids)
    members: list[dict[str, Any]] = []
    for binding in bindings:
        key = (binding.role_id, str(binding.slot_id))
        if key not in resolved_keys:
            # skipped-no-marker: not part of this artifact's receipt set.
            continue
        if key in placed_records:
            record = placed_records[key].record or {}
            members.append(
                {
                    "role_id": binding.role_id,
                    "slot_id": str(binding.slot_id),
                    "batch_artifact_type": artifact_type,
                    "artifact_id": artifact_id,
                    "asset_id": binding.asset_id,
                    "drive_file_id": binding.drive_file_id,
                    "content_identity": dict(binding.content_identity),
                    "inserted_element_id": str(record.get("inserted_element_id") or ""),
                    "post_insertion_revision_id": str(record.get("post_insertion_revision_id") or ""),
                    "member_source": "placed",
                }
            )
            continue
        record = find_verified_record(
            stored,
            role_id=binding.role_id,
            slot_id=binding.slot_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            content_identity=binding.content_identity,
        )
        if record is None:
            raise PlacementExecutionError(
                f"placement-batch-unreconciled: no verified receipt for recovered "
                f"binding role={binding.role_id} slot={binding.slot_id}; refusing "
                "to reconcile without receipt evidence"
            )
        member_revision = str(record.get("post_insertion_revision_id") or "")
        if latest is not None:
            if key not in proven_members:
                raise PlacementExecutionError(
                    f"placement-batch-unreconciled: recovered receipt for "
                    f"role={binding.role_id} slot={binding.slot_id} was never "
                    "reconciled by a batch proof; refusing to absorb "
                    "unreconciled evidence"
                )
            if member_revision not in explained:
                raise PlacementExecutionError(
                    f"placement-batch-unreconciled: recovered receipt for "
                    f"role={binding.role_id} slot={binding.slot_id} carries a "
                    "post-insertion revision no batch proof explains; "
                    "unexplained drift, manual review required"
                )
        element_id = str(record.get("inserted_element_id") or "")
        if element_id not in final_element_ids:
            raise PlacementExecutionError(
                f"placement-batch-unreconciled: previously placed element "
                f"{element_id} for role={binding.role_id} slot={binding.slot_id} "
                "is no longer observable in the artifact; refusing to reconcile"
            )
        members.append(
            {
                "role_id": binding.role_id,
                "slot_id": str(binding.slot_id),
                "batch_artifact_type": artifact_type,
                "artifact_id": artifact_id,
                "asset_id": str(record.get("asset_id") or ""),
                "drive_file_id": str(record.get("drive_file_id") or ""),
                "content_identity": dict(record.get("content_identity") or {}),
                "inserted_element_id": element_id,
                "post_insertion_revision_id": member_revision,
                "member_source": "recovered",
            }
        )
    if latest is None:
        # No prior proof: the only honest anchor is that the artifact has
        # not moved since the latest insertion recorded BEFORE this run.
        # (Records placed by this run are excluded: this run's own
        # continuity chain already explains them.)
        pre_run_revisions = [
            str(record.get("post_insertion_revision_id") or "")
            for record in pre_run_records
            if record.get("state") == "verified"
            and record.get("artifact_type") == artifact_type
            and str(record.get("artifact_id")) == artifact_id
        ]
        if pre_run_revisions and initial_rev != pre_run_revisions[-1]:
            raise PlacementExecutionError(
                "placement-batch-unreconciled: the artifact moved since the "
                "latest recorded insertion and no batch proof explains the "
                "drift; manual review required"
            )
    for member in members:
        if member["inserted_element_id"] not in final_element_ids:
            raise PlacementExecutionError(
                f"placement-batch-unreconciled: member element "
                f"{member['inserted_element_id']} for role={member['role_id']} "
                "is not observable in the reconciled artifact snapshot"
            )
    return reconcile_placement_batch(
        receipts_dir=receipts_dir,
        idempotency_key=idempotency_key,
        batch_artifact_type=artifact_type,
        artifact_id=artifact_id,
        ordered_members=members,
        insertion_continuity=continuity_entries,
        initial_revision_id=initial_rev,
        final_revision_id=final_observation.revision_id,
    )


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
    # Unresolved writes are a build-wide block, even when every remaining
    # visual is optional (or a changed plan has no required roles).
    if receipts_dir:
        try:
            assert_no_unresolved_placement_attempts(receipts_dir, idempotency_key)
        except PlacementStoreIntegrityError as exc:
            raise PlacementExecutionError(str(exc)) from exc
    if not required:
        return
    if not receipts_dir:
        raise PlacementExecutionError(
            "placement-receipt-store-unavailable: required visual placements cannot be "
            "proven without the durable receipt store"
        )
    try:
        records = load_placement_records_strict(receipts_dir, idempotency_key)
    except PlacementStoreIntegrityError as exc:
        raise PlacementExecutionError(str(exc)) from exc
    artifact_ids = {str(v) for v in artifact_files.values() if v}
    # Scan the full build journal, including abandoned role bindings that a
    # changed plan no longer lists. No orphan may be silently ignored.
    try:
        assert_no_unresolved_placement_attempts(receipts_dir,idempotency_key)
    except PlacementStoreIntegrityError as exc:
        raise PlacementExecutionError(str(exc)) from exc
    # A pending mutation (including an optional role) prevents release, even
    # if a historical verified receipt exists. The outcome is unresolved.
    for binding in bindings or ():
        for role, file_id in artifact_files.items():
            kind = 'docs' if role in ('worksheet','docs') else 'slides'
            if file_id and load_placement_attempt(
                receipts_dir,idempotency_key,artifact_type=kind,artifact_id=str(file_id),
                role_id=binding.role_id,slot_id=binding.slot_id,
            ) is not None:
                raise PlacementExecutionError(
                    'placement-reconciliation-required: unresolved insertion attempt for '
                    f'role={binding.role_id} slot={binding.slot_id} in {kind}:{file_id}'
                )
    missing: list[str] = []
    for binding in sorted(required, key=lambda b: (b.role_id, b.slot_id)):
        satisfied = any(
            record.get("state") == "verified"
            and record.get("role_id") == binding.role_id
            and str(record.get("slot_id")) == str(binding.slot_id)
            and record.get("artifact_id") in artifact_ids
            and record.get("asset_id") == binding.asset_id
            and record.get("drive_file_id") == binding.drive_file_id
            and record.get("source_plan_id") == binding.source_plan_id
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
