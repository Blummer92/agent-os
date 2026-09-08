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
class StudentMaterialPdfSource:
    artifact_role: str
    native_file_id: str
    native_revision_id: str
    target_folder_id: str
    title: str
    paragraphs: tuple[str, ...]


@dataclass(frozen=True)
class StudentMaterialPdfReceipt:
    state: PdfPreviewState
    path: str = ""
    source_file_id: str = ""
    source_revision_id: str = ""
    source_target_folder_id: str = ""
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
    try:
        _validate_source(source, expected_revision_id)
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


def _verify_pdf(path: Path) -> None:
    if not path.is_file():
        raise StudentMaterialPdfError("PDF render did not produce a file")
    data = path.read_bytes()
    if len(data) < 64 or not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
        raise StudentMaterialPdfError("PDF render verification failed")


def _esc(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
