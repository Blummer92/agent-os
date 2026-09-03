"""Application-owned governed live-build boundary with injected clients only."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

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

ArtifactState = Literal["planned", "recovered", "created", "updated", "failed", "ambiguous"]


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
    error: str = ""
    reconciliation_candidates: tuple[ReconciliationCandidate, ...] = ()


@dataclass(frozen=True)
class LiveBuildReceipt:
    slides: ArtifactReceipt
    worksheet: ArtifactReceipt
    manual_reconciliation_required: bool = False

    @property
    def succeeded(self) -> bool:
        return self.slides.state == "updated" and self.worksheet.state == "updated"


def _candidate(meta: dict[str, Any]) -> ReconciliationCandidate:
    parents = meta.get("parents", [])
    if not isinstance(parents, list):
        parents = []
    return ReconciliationCandidate(
        file_id=str(meta.get("id", "")),
        web_view_link=str(meta.get("webViewLink", "")),
        drive_id=str(meta.get("driveId", "")),
        mime_type=str(meta.get("mimeType", "")),
        parents=tuple(str(parent) for parent in parents),
    )


def _receipt(
    role: str,
    state: ArtifactState,
    meta: dict[str, Any] | None = None,
    error: str = "",
    reconciliation_candidates: tuple[ReconciliationCandidate, ...] = (),
) -> ArtifactReceipt:
    meta = meta or {}
    return ArtifactReceipt(
        role=role,
        state=state,
        file_id=str(meta.get("id", "")),
        web_view_link=str(meta.get("webViewLink", "")),
        drive_id=str(meta.get("driveId", "")),
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


def _resolve_copy(drive_service: Any, *, template_id: str, target_folder_id: str, name: str, key: str, role: str) -> ArtifactReceipt:
    matches = find_idempotent_copies(drive_service, target_folder_id, key, role)
    if len(matches) > 1:
        return _ambiguous_receipt(role, matches, "multiple idempotency matches require manual reconciliation")
    if len(matches) == 1:
        return _receipt(role, "recovered", matches[0])
    try:
        created = duplicate_template(
            drive_service,
            template_id,
            target_folder_id,
            name,
            idempotency_key=key,
            role=role,
        )
        return _receipt(role, "created", created)
    except Exception as exc:
        recovered = find_idempotent_copies(drive_service, target_folder_id, key, role)
        if len(recovered) == 1:
            return _receipt(role, "recovered", recovered[0])
        detail = "copy outcome unknown; manual reconciliation required"
        if len(recovered) > 1:
            detail = "copy outcome ambiguous with multiple idempotency matches"
        return _ambiguous_receipt(role, recovered, f"{detail}: {type(exc).__name__}")


def build_live_materials(
    build: LiveBuildInput,
    *,
    drive_service: Any,
    slides_service: Any,
    docs_service: Any,
) -> LiveBuildReceipt:
    """Build one governed Slides/Docs pair without acquiring credentials or authority."""
    verify_template(drive_service, build.slides_template_id, GOOGLE_SLIDES_MIME)
    verify_template(drive_service, build.doc_template_id, GOOGLE_DOCS_MIME)
    verify_target_folder(drive_service, build.target_folder_id)

    slides = _resolve_copy(
        drive_service,
        template_id=build.slides_template_id,
        target_folder_id=build.target_folder_id,
        name=build.slides_name,
        key=build.idempotency_key,
        role="slides",
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
    )
    if worksheet.state == "ambiguous":
        return LiveBuildReceipt(slides, worksheet, True)

    try:
        revision = get_slides_revision_id(slides_service, slides.file_id)
        apply_slides_requests(slides_service, slides.file_id, list(build.slides_requests), required_revision_id=revision)
        final = verify_final_copy(
            drive_service,
            slides.file_id,
            expected_mime=GOOGLE_SLIDES_MIME,
            target_folder_id=build.target_folder_id,
            idempotency_key=build.idempotency_key,
            role="slides",
        )
        slides = _receipt("slides", "updated", final)
    except Exception as exc:
        return LiveBuildReceipt(replace(slides, state="failed", error=str(exc)), worksheet)

    try:
        revision = get_docs_revision_id(docs_service, worksheet.file_id)
        apply_docs_requests(docs_service, worksheet.file_id, list(build.docs_requests), required_revision_id=revision)
        final = verify_final_copy(
            drive_service,
            worksheet.file_id,
            expected_mime=GOOGLE_DOCS_MIME,
            target_folder_id=build.target_folder_id,
            idempotency_key=build.idempotency_key,
            role="worksheet",
        )
        worksheet = _receipt("worksheet", "updated", final)
    except Exception as exc:
        worksheet = replace(worksheet, state="failed", error=str(exc))
    return LiveBuildReceipt(slides, worksheet, worksheet.state == "ambiguous")
