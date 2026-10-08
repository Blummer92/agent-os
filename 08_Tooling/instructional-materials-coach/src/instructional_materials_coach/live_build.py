"""Application-owned governed live-build boundary with injected clients only."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Literal

from .artifact_content_qa import (
    QA_STATE_NOT_RUN,
    QA_STATE_VERIFIED,
    TerminalQAExpectations,
    TerminalQAReport,
    run_terminal_qa,
)
from .build_resume import (
    ResumeRecordInvalidError,
    load_resume_record,
    mark_role_state,
    new_resume_record,
    write_resume_record,
)
from .connected_visual_placement import (
    VisualPlacementBinding,
    execute_artifact_visual_placements,
    require_all_required_visuals_placed,
)
from .drive_client import (
    GOOGLE_DOCS_MIME,
    GOOGLE_SLIDES_MIME,
    duplicate_template,
    find_idempotent_copies,
    verify_final_copy,
    verify_target_folder,
    verify_template,
)
from .workspace_clients import (
    apply_docs_requests,
    apply_slides_requests,
    get_docs_revision_id,
    get_slides_revision_id,
)
from .worksheet_pagination import plan_heading_keep_with_next_requests

ArtifactState = Literal["planned", "recovered", "created", "updated", "failed", "ambiguous"]
ArtifactDeliveryKind = Literal["pending", "final"]
ArtifactCompletenessStatus = Literal["complete", "blocked-production"]


@dataclass(frozen=True)
class LiveBuildInput:
    slides_template_id: str
    doc_template_id: str
    target_folder_id: str
    slides_name: str
    doc_name: str
    idempotency_key: str
    slides_requests: tuple[dict[str, Any], ...]
    docs_requests: tuple[dict[str, Any], ...]
    # #3252: fingerprint of the consequential inputs bound to created copies
    # (Drive appProperty ``agent_os_input_fingerprint``). On recovery, a
    # mismatch against the copy's bound fingerprint raises
    # ``IdempotencyKeyInputMismatchError`` instead of silently reusing the
    # stale copy. Empty disables the check (pre-#3252 callers).
    input_fingerprint: str = ""
    # #3257: governed visual-placement bindings planned from the visual-reuse
    # plan. Empty (the default) preserves the text-only behavior for builds
    # with no selected visuals. A non-empty tuple requires a placement
    # transport at build time; without one the build fails closed with
    # placement-runtime-unavailable, never "final".
    visual_placements: tuple[VisualPlacementBinding, ...] = ()
    # #3258: governed terminal-QA expectations derived from the planned
    # requests and visual bindings. ``None`` (the default) means no
    # expectations were supplied: terminal QA then reports
    # evidence-incomplete and the build can never be final. An empty
    # expectations record still runs the unresolved-token scan and
    # artifact-identity binding.
    qa_expectations: TerminalQAExpectations | None = None


class IdempotencyKeyInputMismatchError(RuntimeError):
    """A recovered copy's bound input fingerprint differs from this run's.

    The idempotency key was reused with different consequential inputs.
    Never silently apply the current requests to the stale copy.
    """


@dataclass(frozen=True)
class ReconciliationCandidate:
    file_id: str
    web_view_link: str = ""
    drive_id: str = ""
    mime_type: str = ""
    parents: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactReceipt:
    role: str
    state: ArtifactState = "planned"
    file_id: str = ""
    web_view_link: str = ""
    drive_id: str = ""
    mime_type: str = ""
    parents: tuple[str, ...] = ()
    delivery_kind: ArtifactDeliveryKind = "pending"
    canonical_editable: bool = False
    persistence_verified: bool = False
    error: str = ""
    reconciliation_candidates: tuple[ReconciliationCandidate, ...] = ()
    # #3258: terminal artifact-content QA state for this artifact. ``final``
    # requires ``verified``: metadata-only verification is ``persisted``,
    # never ``final``.
    terminal_qa_state: str = QA_STATE_NOT_RUN

    @property
    def is_final(self) -> bool:
        return (
            self.state == "updated"
            and self.delivery_kind == "final"
            and self.canonical_editable
            and self.persistence_verified
            and self.terminal_qa_state == QA_STATE_VERIFIED
            and bool(self.file_id)
            and bool(self.mime_type)
            and bool(self.parents)
        )

    @property
    def is_persisted(self) -> bool:
        """Metadata-verified but not terminal-QA-verified.

        The artifact exists with the right identity (mime, parents,
        idempotency attribution) but its persisted content has not passed
        terminal QA. ``persisted`` is a nonterminal state: it must never be
        reported as ``final``.
        """
        return (
            self.state == "updated"
            and self.delivery_kind == "final"
            and self.canonical_editable
            and self.persistence_verified
            and self.terminal_qa_state != QA_STATE_VERIFIED
            and bool(self.file_id)
            and bool(self.mime_type)
            and bool(self.parents)
        )



@dataclass(frozen=True)
class ArtifactCompletenessResult:
    role: str
    requested_mime_type: str
    status: ArtifactCompletenessStatus
    complete: bool
    reason_code: str
    file_id: str = ""
    side_effects_performed: bool = False


def evaluate_artifact_completeness(
    receipt: ArtifactReceipt,
    *,
    requested_mime_type: str,
    target_folder_id: str,
) -> ArtifactCompletenessResult:
    """Evaluate requested-format completion without performing any external write."""
    if not requested_mime_type or not target_folder_id:
        raise ValueError("requested_mime_type and target_folder_id are required")
    persisted = (
        receipt.state == "updated"
        and receipt.persistence_verified
        and bool(receipt.file_id)
        and receipt.mime_type == requested_mime_type
        and target_folder_id in receipt.parents
    )
    if persisted:
        return ArtifactCompletenessResult(
            receipt.role, requested_mime_type, "complete", True, "requested-format-verified", receipt.file_id
        )
    if receipt.mime_type and receipt.mime_type != requested_mime_type:
        reason = "requested-format-mismatch"
    elif receipt.persistence_verified and target_folder_id not in receipt.parents:
        reason = "requested-destination-mismatch"
    else:
        reason = "requested-format-missing"
    return ArtifactCompletenessResult(
        receipt.role, requested_mime_type, "blocked-production", False, reason, receipt.file_id
    )


@dataclass(frozen=True)
class LiveBuildReceipt:
    slides: ArtifactReceipt
    worksheet: ArtifactReceipt
    manual_reconciliation_required: bool = False
    # #3258: machine-readable terminal QA report for the pair. ``succeeded``
    # requires both artifacts terminal-QA ``verified``: anything unresolved,
    # stale, failed, inaccessible, or unverified refuses terminal success.
    terminal_qa: TerminalQAReport | None = None

    @property
    def succeeded(self) -> bool:
        return self.slides.is_final and self.worksheet.is_final


def _parents(meta: dict[str, Any]) -> tuple[str, ...]:
    parents = meta.get("parents", [])
    if not isinstance(parents, list):
        return ()
    return tuple(str(parent) for parent in parents)


def _candidate(meta: dict[str, Any]) -> ReconciliationCandidate:
    return ReconciliationCandidate(
        file_id=str(meta.get("id", "")),
        web_view_link=str(meta.get("webViewLink", "")),
        drive_id=str(meta.get("driveId", "")),
        mime_type=str(meta.get("mimeType", "")),
        parents=_parents(meta),
    )


def _receipt(
    role: str,
    state: ArtifactState,
    meta: dict[str, Any] | None = None,
    error: str = "",
    reconciliation_candidates: tuple[ReconciliationCandidate, ...] = (),
    *,
    final: bool = False,
) -> ArtifactReceipt:
    meta = meta or {}
    return ArtifactReceipt(
        role=role,
        state=state,
        file_id=str(meta.get("id", "")),
        web_view_link=str(meta.get("webViewLink", "")),
        drive_id=str(meta.get("driveId", "")),
        mime_type=str(meta.get("mimeType", "")),
        parents=_parents(meta),
        delivery_kind="final" if final else "pending",
        canonical_editable=final,
        persistence_verified=final,
        error=error,
        reconciliation_candidates=reconciliation_candidates,
    )


def _ambiguous_receipt(role: str, matches: list[dict[str, Any]], error: str) -> ArtifactReceipt:
    return _receipt(
        role,
        "ambiguous",
        error=error,
        reconciliation_candidates=tuple(_candidate(match) for match in matches),
    )


def _check_input_fingerprint(
    meta: dict[str, Any], *, input_fingerprint: str, role: str
) -> None:
    """Anti-collision: reject a recovered copy bound to different inputs.

    Copies created before #3252 carry no ``agent_os_input_fingerprint``
    property; those are unverifiable and allowed through (the key alone
    governed them). A present-but-different fingerprint is a hard error.
    """
    if not input_fingerprint:
        return
    bound = (meta.get("appProperties") or {}).get("agent_os_input_fingerprint")
    if bound is None or bound == "":
        return
    if bound != input_fingerprint:
        raise IdempotencyKeyInputMismatchError(
            "idempotency-key-input-mismatch: recovered "
            f"{role} copy was created with different inputs; refusing to "
            "apply the current requests to the stale copy"
        )


def _resolve_copy(
    drive_service: Any,
    *,
    template_id: str,
    target_folder_id: str,
    name: str,
    key: str,
    role: str,
    input_fingerprint: str = "",
) -> ArtifactReceipt:
    matches = find_idempotent_copies(drive_service, target_folder_id, key, role)
    if len(matches) > 1:
        return _ambiguous_receipt(role, matches, "multiple idempotency matches require manual reconciliation")
    if len(matches) == 1:
        _check_input_fingerprint(matches[0], input_fingerprint=input_fingerprint, role=role)
        return _receipt(role, "recovered", matches[0])
    try:
        created = duplicate_template(
            drive_service,
            template_id,
            target_folder_id,
            name,
            idempotency_key=key,
            role=role,
            input_fingerprint=input_fingerprint or None,
        )
        return _receipt(role, "created", created)
    except Exception as exc:
        recovered = find_idempotent_copies(drive_service, target_folder_id, key, role)
        if len(recovered) == 1:
            _check_input_fingerprint(recovered[0], input_fingerprint=input_fingerprint, role=role)
            return _receipt(role, "recovered", recovered[0])
        detail = "copy outcome unknown; manual reconciliation required"
        if len(recovered) > 1:
            detail = "copy outcome ambiguous with multiple idempotency matches"
        return _ambiguous_receipt(role, recovered, f"{detail}: {type(exc).__name__}")


def _extract_docs_text(document: Any) -> str | None:
    """Best-effort plain-text extraction from a Docs resource for the
    already-applied safety net. Returns None when unreadable."""
    try:
        parts: list[str] = []
        body = document.get("body", {}) if isinstance(document, dict) else {}
        for element in body.get("content", []):
            paragraph = element.get("paragraph") if isinstance(element, dict) else None
            if not isinstance(paragraph, dict):
                continue
            for child in paragraph.get("elements", []):
                text_run = child.get("textRun") if isinstance(child, dict) else None
                if isinstance(text_run, dict):
                    parts.append(str(text_run.get("content", "")))
        return "".join(parts)
    except Exception:
        return None


def _extract_slides_text(presentation: Any) -> str | None:
    """Best-effort plain-text extraction from a Slides resource."""
    try:
        parts: list[str] = []
        slides = presentation.get("slides", []) if isinstance(presentation, dict) else []
        for slide in slides:
            for element in slide.get("pageElements", []):
                shape = element.get("shape", {}) if isinstance(element, dict) else {}
                text = shape.get("text", {}) if isinstance(shape, dict) else {}
                for text_element in text.get("textElements", []):
                    text_run = text_element.get("textRun") if isinstance(text_element, dict) else None
                    if isinstance(text_run, dict):
                        parts.append(str(text_run.get("content", "")))
        return "".join(parts)
    except Exception:
        return None


def _docs_text_fetcher(docs_service: Any, document_id: str) -> Callable[[], str | None]:
    def _fetch() -> str | None:
        try:
            document = docs_service.documents().get(documentId=document_id).execute()
        except Exception:
            return None
        return _extract_docs_text(document)

    return _fetch


def _slides_text_fetcher(slides_service: Any, presentation_id: str) -> Callable[[], str | None]:
    def _fetch() -> str | None:
        try:
            presentation = slides_service.presentations().get(presentationId=presentation_id).execute()
        except Exception:
            return None
        return _extract_slides_text(presentation)

    return _fetch


def _apply_requests_tracked(
    *,
    role: str,
    service: Any,
    file_id: str,
    requests: list[dict[str, Any]],
    applied_indices: set[int],
    get_revision_id: Callable[[Any, str], str],
    apply_requests: Callable[..., None],
    content_fetcher: Callable[[], str | None] | None,
    on_applied: Callable[[int], None],
) -> None:
    """Apply the not-yet-applied requests for one artifact.

    First attempt (nothing applied): single batch, hot path unchanged.
    Resume (partial progress): one request at a time so each application is
    crash-safe; the content-presence safety net proves already-applied
    requests instead of failing on them.
    """
    unapplied = [(index, request) for index, request in enumerate(requests) if index not in applied_indices]
    if not unapplied:
        return
    if not applied_indices:
        revision = get_revision_id(service, file_id)
        apply_requests(
            service,
            file_id,
            [request for _, request in unapplied],
            required_revision_id=revision,
            content_fetcher=content_fetcher,
        )
        for index, _ in unapplied:
            on_applied(index)
        return
    for index, request in unapplied:
        revision = get_revision_id(service, file_id)
        apply_requests(
            service,
            file_id,
            [request],
            required_revision_id=revision,
            content_fetcher=content_fetcher,
        )
        on_applied(index)


def _apply_heading_keep_with_next(docs_service: Any, document_id: str) -> None:
    """#3416: guarantee worksheet headings stay with their following content.

    Reads the document once and, only when some heading lacks effective
    ``keepWithNext``, applies one revision-bound ``updateParagraphStyle``
    batch. An empty plan writes nothing, so no revision bump. Runs before
    #3257 placement because placement receipts bind the artifact revision.
    """
    document = docs_service.documents().get(documentId=document_id).execute()
    if not isinstance(document, dict):
        raise RuntimeError("Docs readback for heading keep-with-next did not return a document")
    requests = list(plan_heading_keep_with_next_requests(document))
    if not requests:
        return
    revision = document.get("revisionId")
    if not isinstance(revision, str) or not revision:
        raise RuntimeError("Docs revisionId is required before heading keep-with-next mutation")
    apply_docs_requests(docs_service, document_id, requests, required_revision_id=revision)


def _place_artifact_visuals(
    *,
    build: LiveBuildInput,
    artifact_type: str,
    artifact_id: str,
    drive_service: Any,
    artifact_service: Any,
    placement_transport: Any,
    placement_receipts_dir: str | None,
) -> None:
    """#3257: place selected visuals into one live artifact after text requests.

    Runs between text-request application and final-copy verification so the
    verified copy reflects the placed visuals. Raises
    ``PlacementRuntimeUnavailable`` when bindings exist but no transport was
    supplied, and ``PlacementExecutionError`` when any attempted binding
    cannot be verified-placed. Both fail the artifact closed via the
    caller's per-artifact handler.
    """
    if not build.visual_placements:
        return
    execute_artifact_visual_placements(
        bindings=build.visual_placements,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        drive_service=drive_service,
        artifact_service=artifact_service,
        transport=placement_transport,
        receipts_dir=placement_receipts_dir,
        idempotency_key=build.idempotency_key,
    )


def build_live_materials(
    build: LiveBuildInput,
    *,
    drive_service: Any,
    slides_service: Any,
    docs_service: Any,
    resume_dir: str | None = None,
    placement_transport: Any = None,
    placement_receipts_dir: str | None = None,
    qa_evidence_dir: str | None = None,
) -> LiveBuildReceipt:
    """Build one governed Slides/Docs pair without acquiring credentials or authority.

    ``resume_dir`` enables #3252 retry continuation: per-role resume state
    is loaded by idempotency key, already-verified work is skipped, and only
    unapplied requests are applied. Without it, behavior is unchanged.

    ``placement_transport`` + ``build.visual_placements`` enable #3257
    connected visual placement: after text requests are applied to each
    artifact, selected visuals are placed through the transport, verified
    against the persisted artifact, and recorded as durable receipts. A
    missing transport with non-empty placements fails closed with
    ``placement-runtime-unavailable``; a placement failure fails the
    artifact closed with its explicit reason -- never a visual gap and
    never generation permission.

    ``qa_evidence_dir`` enables #3258 terminal artifact-content QA evidence
    persistence: verified QA reports are recovered on retry while artifact
    revision and expectations still match, and re-verified otherwise. Even
    without it, terminal QA runs in-memory and gates ``succeeded``.
    """
    verify_template(drive_service, build.slides_template_id, GOOGLE_SLIDES_MIME)
    verify_template(drive_service, build.doc_template_id, GOOGLE_DOCS_MIME)
    verify_target_folder(drive_service, build.target_folder_id)

    resume: dict[str, Any] | None = None
    resume_was_loaded = False
    if resume_dir:
        try:
            loaded = load_resume_record(resume_dir, build.idempotency_key)
        except ResumeRecordInvalidError as exc:
            error = str(exc)
            return LiveBuildReceipt(
                ArtifactReceipt("slides", state="ambiguous", error=error),
                ArtifactReceipt("worksheet", state="ambiguous", error=error),
                True,
            )
        resume_was_loaded = loaded is not None
        resume = loaded if loaded is not None else new_resume_record(
            build.idempotency_key, build.input_fingerprint
        )

    def _persist() -> None:
        if resume is not None and resume_dir:
            write_resume_record(resume_dir, resume)

    def _resume_role(role: str) -> dict[str, Any]:
        if resume is None:
            return {"state": "planned", "file_id": "", "applied_request_indices": [], "error": ""}
        return resume[role]

    slides = _resolve_copy(
        drive_service,
        template_id=build.slides_template_id,
        target_folder_id=build.target_folder_id,
        name=build.slides_name,
        key=build.idempotency_key,
        role="slides",
        input_fingerprint=build.input_fingerprint,
    )
    if slides.state == "ambiguous":
        return LiveBuildReceipt(slides, ArtifactReceipt("worksheet"), True)

    worksheet = _resolve_copy(
        drive_service,
        template_id=build.doc_template_id,
        target_folder_id=build.target_folder_id,
        name=build.doc_name,
        key=build.idempotency_key,
        role="worksheet",
        input_fingerprint=build.input_fingerprint,
    )
    if worksheet.state == "ambiguous":
        return LiveBuildReceipt(slides, worksheet, True)

    # Record recovery in the resume record (crash-safe before mutation).
    # Only copies created by this run are marked; recovered copies keep
    # their prior resume state ("recovered" is a resolution outcome, not a
    # progress state).
    if resume is not None:
        for role_label, receipt in (("slides", slides), ("worksheet", worksheet)):
            if receipt.state == "created" and resume[role_label]["state"] == "planned":
                mark_role_state(resume, role_label, state="created", file_id=receipt.file_id)
        _persist()

    try:
        slides_state = _resume_role("slides")
        if (
            slides.state == "recovered"
            and slides_state.get("state") == "updated"
            and slides_state.get("file_id") == slides.file_id
            and slides.file_id
        ):
            # Prior run completed this copy: verify current state, skip mutation.
            final = verify_final_copy(
                drive_service,
                slides.file_id,
                expected_mime=GOOGLE_SLIDES_MIME,
                target_folder_id=build.target_folder_id,
                idempotency_key=build.idempotency_key,
                role="slides",
            )
            slides = _receipt("slides", "updated", final, final=True)
            if resume is not None:
                mark_role_state(resume, "slides", state="updated", file_id=slides.file_id)
                _persist()
        else:
            applied = set(slides_state.get("applied_request_indices", ()))
            # Retry path (safety net on): partial resume progress, or a
            # recovered copy with no resume record (record lost, copy survived).
            is_retry = bool(applied) or (
                not resume_was_loaded and slides.state == "recovered"
            )
            _apply_requests_tracked(
                role="slides",
                service=slides_service,
                file_id=slides.file_id,
                requests=list(build.slides_requests),
                applied_indices=applied,
                get_revision_id=get_slides_revision_id,
                apply_requests=apply_slides_requests,
                content_fetcher=(
                    _slides_text_fetcher(slides_service, slides.file_id) if is_retry else None
                ),
                on_applied=lambda index: (
                    slides_state.setdefault("applied_request_indices", []).append(index),
                    _persist(),
                ),
            )
            _place_artifact_visuals(
                build=build,
                artifact_type="slides",
                artifact_id=slides.file_id,
                drive_service=drive_service,
                artifact_service=slides_service,
                placement_transport=placement_transport,
                placement_receipts_dir=placement_receipts_dir,
            )
            final = verify_final_copy(
                drive_service,
                slides.file_id,
                expected_mime=GOOGLE_SLIDES_MIME,
                target_folder_id=build.target_folder_id,
                idempotency_key=build.idempotency_key,
                role="slides",
            )
            slides = _receipt("slides", "updated", final, final=True)
            if resume is not None:
                mark_role_state(resume, "slides", state="updated", file_id=slides.file_id)
                _persist()
    except Exception as exc:
        if resume is not None:
            mark_role_state(resume, "slides", state="failed", file_id=slides.file_id, error=str(exc))
            _persist()
        return LiveBuildReceipt(replace(slides, state="failed", error=str(exc)), worksheet)

    try:
        worksheet_state = _resume_role("worksheet")
        if (
            worksheet.state == "recovered"
            and worksheet_state.get("state") == "updated"
            and worksheet_state.get("file_id") == worksheet.file_id
            and worksheet.file_id
        ):
            final = verify_final_copy(
                drive_service,
                worksheet.file_id,
                expected_mime=GOOGLE_DOCS_MIME,
                target_folder_id=build.target_folder_id,
                idempotency_key=build.idempotency_key,
                role="worksheet",
            )
            worksheet = _receipt("worksheet", "updated", final, final=True)
            if resume is not None:
                mark_role_state(resume, "worksheet", state="updated", file_id=worksheet.file_id)
                _persist()
        else:
            applied = set(worksheet_state.get("applied_request_indices", ()))
            # Retry path (safety net on): partial resume progress, or a
            # recovered copy with no resume record (record lost, copy survived).
            is_retry = bool(applied) or (
                not resume_was_loaded and worksheet.state == "recovered"
            )
            _apply_requests_tracked(
                role="worksheet",
                service=docs_service,
                file_id=worksheet.file_id,
                requests=list(build.docs_requests),
                applied_indices=applied,
                get_revision_id=get_docs_revision_id,
                apply_requests=apply_docs_requests,
                content_fetcher=(
                    _docs_text_fetcher(docs_service, worksheet.file_id) if is_retry else None
                ),
                on_applied=lambda index: (
                    worksheet_state.setdefault("applied_request_indices", []).append(index),
                    _persist(),
                ),
            )
            _apply_heading_keep_with_next(docs_service, worksheet.file_id)
            _place_artifact_visuals(
                build=build,
                artifact_type="docs",
                artifact_id=worksheet.file_id,
                drive_service=drive_service,
                artifact_service=docs_service,
                placement_transport=placement_transport,
                placement_receipts_dir=placement_receipts_dir,
            )
            final = verify_final_copy(
                drive_service,
                worksheet.file_id,
                expected_mime=GOOGLE_DOCS_MIME,
                target_folder_id=build.target_folder_id,
                idempotency_key=build.idempotency_key,
                role="worksheet",
            )
            worksheet = _receipt("worksheet", "updated", final, final=True)
            if resume is not None:
                mark_role_state(resume, "worksheet", state="updated", file_id=worksheet.file_id)
                _persist()
    except Exception as exc:
        if resume is not None:
            mark_role_state(
                resume, "worksheet", state="failed", file_id=worksheet.file_id, error=str(exc)
            )
            _persist()
        worksheet = replace(worksheet, state="failed", error=str(exc))
    # #3257 backstop: a visuals-required build can complete only when every
    # required slot is verified-placed. The per-artifact placement step above
    # already fails closed on any attempted binding; this covers paths where
    # placement ran in an earlier attempt (resume recovery).
    if build.visual_placements and slides.state == "updated" and worksheet.state == "updated":
        require_all_required_visuals_placed(
            bindings=build.visual_placements,
            receipts_dir=placement_receipts_dir,
            idempotency_key=build.idempotency_key,
            artifact_files={"slides": slides.file_id, "worksheet": worksheet.file_id},
        )
    # #3258 terminal artifact-content QA: the single admission gate. A build
    # is terminal-success only when the PERSISTED artifacts prove the
    # governed required content and visuals, attributable to this build and
    # artifact state. QA runs on every terminal attempt, including the
    # resume fast path (read-only: no external mutation), so a mutated
    # artifact can never ride a stale success to "final".
    qa_report = None
    if slides.state == "updated" and worksheet.state == "updated":
        qa_report = run_terminal_qa(
            expectations=build.qa_expectations,
            slides_service=slides_service,
            docs_service=docs_service,
            slides_file_id=slides.file_id,
            worksheet_file_id=worksheet.file_id,
            receipts_dir=placement_receipts_dir,
            qa_evidence_dir=qa_evidence_dir,
        )
        slides = replace(slides, terminal_qa_state=qa_report.slides.state)
        worksheet = replace(worksheet, terminal_qa_state=qa_report.worksheet.state)
    return LiveBuildReceipt(
        slides, worksheet, worksheet.state == "ambiguous", terminal_qa=qa_report
    )
