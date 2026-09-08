"""Offline student-material PDF draft/preview rendering with provenance verification."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .visual_placement import PlacementReceipt

PdfPreviewState = Literal["preview", "blocked"]


class StudentMaterialPdfError(ValueError):
    """Fail-closed error for invalid or unverifiable student-material previews."""


@dataclass(frozen=True)
class StudentMaterialPdfSource:
    artifact_role: str
    native_file_id: str
    native_revision_id: str
    target_folder_id: str
    title: str
    paragraphs: tuple[str, ...]
    required_visual_role_ids: tuple[str, ...] = ()
    verified_visual_placements: tuple[PlacementReceipt, ...] = ()


@dataclass(frozen=True)
class StudentMaterialPdfReceipt:
    state: PdfPreviewState
    path: str = ""
    source_file_id: str = ""
    source_revision_id: str = ""
    source_target_folder_id: str = ""
    unresolved_visual_role_ids: tuple[str, ...] = ()
    canonical: bool = False
    render_verified: bool = False
    error: str = ""

    @property
    def available(self) -> bool:
        return self.state == "preview" and self.render_verified and not self.canonical and bool(self.path)


def render_student_material_pdf_preview(
    source: StudentMaterialPdfSource,
    output_path: str | Path,
    *,
    expected_revision_id: str,
) -> StudentMaterialPdfReceipt:
    """Render and verify a non-canonical PDF preview from one exact native source revision.

    Required visual roles are caller-supplied governed identities. Every required
    role must have one exact already-verified placement receipt for the same native
    artifact before this text renderer may claim a usable preview. This seam does
    not select, retrieve, place, or generate visuals.
    """
    unresolved_visual_roles: tuple[str, ...] = ()
    try:
        _validate_source(source, expected_revision_id)
        unresolved_visual_roles = _unresolved_required_visual_roles(source)
        if unresolved_visual_roles:
            raise StudentMaterialPdfError(
                "required visual placement is unresolved: " + ", ".join(unresolved_visual_roles)
            )
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        styles = getSampleStyleSheet()
        story = [Paragraph(_esc(source.title), styles["Title"]), Spacer(1, 10)]
        for paragraph in source.paragraphs:
            story.extend([Paragraph(_esc(paragraph), styles["BodyText"]), Spacer(1, 7)])
        story.extend([
            Spacer(1, 10),
            Paragraph("PDF draft/preview - derived artifact. The native Google Drive file remains the canonical editable final.", styles["Italic"]),
        ])
        SimpleDocTemplate(
            str(target),
            pagesize=LETTER,
            title=source.title,
            author="Agent OS Instructional Materials Coach",
        ).build(story)
        _verify_pdf(target)
        return StudentMaterialPdfReceipt(
            state="preview",
            path=str(target),
            source_file_id=source.native_file_id,
            source_revision_id=source.native_revision_id,
            source_target_folder_id=source.target_folder_id,
            unresolved_visual_role_ids=(),
            canonical=False,
            render_verified=True,
        )
    except Exception as exc:
        return StudentMaterialPdfReceipt(
            state="blocked",
            source_file_id=source.native_file_id,
            source_revision_id=source.native_revision_id,
            source_target_folder_id=source.target_folder_id,
            unresolved_visual_role_ids=unresolved_visual_roles,
            canonical=False,
            render_verified=False,
            error=str(exc),
        )


def _validate_source(source: StudentMaterialPdfSource, expected_revision_id: str) -> None:
    for field, value in (
        ("artifact_role", source.artifact_role),
        ("native_file_id", source.native_file_id),
        ("native_revision_id", source.native_revision_id),
        ("target_folder_id", source.target_folder_id),
        ("title", source.title),
        ("expected_revision_id", expected_revision_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise StudentMaterialPdfError(f"{field} must be non-empty text")
    if source.native_revision_id != expected_revision_id:
        raise StudentMaterialPdfError("native source revision is stale or mismatched")
    if not source.paragraphs or any(not isinstance(item, str) or not item.strip() for item in source.paragraphs):
        raise StudentMaterialPdfError("paragraphs must contain non-empty text")
    _validate_role_ids(source.required_visual_role_ids)
    if not isinstance(source.verified_visual_placements, tuple) or any(
        not isinstance(item, PlacementReceipt) for item in source.verified_visual_placements
    ):
        raise StudentMaterialPdfError("verified_visual_placements must contain PlacementReceipt values")


def _validate_role_ids(role_ids: object) -> None:
    if not isinstance(role_ids, tuple):
        raise StudentMaterialPdfError("required_visual_role_ids must be a tuple")
    if len(role_ids) > 32:
        raise StudentMaterialPdfError("required_visual_role_ids exceeds the bounded preview limit")
    seen: set[str] = set()
    for role_id in role_ids:
        if not isinstance(role_id, str) or not role_id.strip():
            raise StudentMaterialPdfError("required visual role IDs must be non-empty text")
        normalized = role_id.strip()
        if normalized != role_id or len(normalized) > 128 or any(char.isspace() for char in normalized):
            raise StudentMaterialPdfError("required visual role ID is malformed")
        if normalized in seen:
            raise StudentMaterialPdfError("required visual role IDs must be unique")
        seen.add(normalized)


def _unresolved_required_visual_roles(source: StudentMaterialPdfSource) -> tuple[str, ...]:
    if not source.required_visual_role_ids:
        return ()
    expected_artifact_type = _preview_artifact_type(source.artifact_role)
    placements_by_role: dict[str, list[PlacementReceipt]] = {}
    for placement in source.verified_visual_placements:
        if placement.state != "verified":
            raise StudentMaterialPdfError("visual placement receipt must be verified")
        if placement.artifact_type != expected_artifact_type or placement.artifact_id != source.native_file_id:
            raise StudentMaterialPdfError("visual placement receipt does not bind the preview source artifact")
        placements_by_role.setdefault(placement.role_id, []).append(placement)

    unresolved: list[str] = []
    for role_id in source.required_visual_role_ids:
        matches = placements_by_role.get(role_id, [])
        if len(matches) > 1:
            raise StudentMaterialPdfError(f"required visual role has ambiguous placement evidence: {role_id}")
        if len(matches) != 1:
            unresolved.append(role_id)
    return tuple(unresolved)


def _preview_artifact_type(artifact_role: str) -> str:
    normalized = artifact_role.strip().casefold()
    if normalized in {"worksheet", "doc", "docs", "google-doc", "google-docs"}:
        return "docs"
    if normalized in {"slide", "slides", "deck", "google-slide", "google-slides"}:
        return "slides"
    raise StudentMaterialPdfError("artifact_role does not map to a supported visual placement artifact type")


def _verify_pdf(path: Path) -> None:
    if not path.is_file():
        raise StudentMaterialPdfError("PDF render did not produce a file")
    data = path.read_bytes()
    if len(data) < 64 or not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
        raise StudentMaterialPdfError("PDF render verification failed")


def _esc(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
