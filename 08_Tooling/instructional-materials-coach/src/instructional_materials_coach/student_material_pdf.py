"""Offline student-material PDF draft/preview rendering with provenance verification."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

PdfPreviewState = Literal["preview", "blocked"]


class StudentMaterialPdfError(ValueError):
    """Fail-closed error for invalid or unverifiable student-material previews."""


@dataclass(frozen=True)
class StudentMaterialVisualEvidence:
    """Caller-supplied governed visual requirements and verified placements."""

    required_roles: tuple[str, ...] = ()
    verified_placed_roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class StudentMaterialPdfSource:
    artifact_role: str
    native_file_id: str
    native_revision_id: str
    target_folder_id: str
    title: str
    paragraphs: tuple[str, ...]
    visual_evidence: StudentMaterialVisualEvidence | None = None


@dataclass(frozen=True)
class StudentMaterialPdfReceipt:
    state: PdfPreviewState
    path: str = ""
    source_file_id: str = ""
    source_revision_id: str = ""
    source_target_folder_id: str = ""
    unresolved_visual_roles: tuple[str, ...] = ()
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
    """Render and verify a non-canonical PDF preview from one exact native source revision."""
    unresolved_visual_roles: tuple[str, ...] = ()
    try:
        _validate_source(source, expected_revision_id)
        unresolved_visual_roles = _unresolved_visual_roles(source.visual_evidence)
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
            canonical=False,
            render_verified=True,
        )
    except Exception as exc:
        return StudentMaterialPdfReceipt(
            state="blocked",
            source_file_id=source.native_file_id,
            source_revision_id=source.native_revision_id,
            source_target_folder_id=source.target_folder_id,
            unresolved_visual_roles=unresolved_visual_roles,
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
    if source.visual_evidence is not None and not isinstance(source.visual_evidence, StudentMaterialVisualEvidence):
        raise StudentMaterialPdfError("visual_evidence must use StudentMaterialVisualEvidence")


def _unresolved_visual_roles(evidence: StudentMaterialVisualEvidence | None) -> tuple[str, ...]:
    if evidence is None:
        return ()
    required = _normalized_roles(evidence.required_roles, "required_roles")
    placed = set(_normalized_roles(evidence.verified_placed_roles, "verified_placed_roles"))
    return tuple(role for role in required if role not in placed)


def _normalized_roles(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise StudentMaterialPdfError(f"{field} must be a tuple")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise StudentMaterialPdfError(f"{field} must contain non-empty role identities")
        role = value.strip()
        if role not in seen:
            normalized.append(role)
            seen.add(role)
    return tuple(normalized)


def _verify_pdf(path: Path) -> None:
    if not path.is_file():
        raise StudentMaterialPdfError("PDF render did not produce a file")
    data = path.read_bytes()
    if len(data) < 64 or not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
        raise StudentMaterialPdfError("PDF render verification failed")


def _esc(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
