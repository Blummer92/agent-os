"""Offline student-material PDF draft/preview rendering with provenance verification."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
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
    compact_worksheet_header: bool = True
    student_identification_labels: tuple[str, ...] = ("Name", "Hour", "Date")
    unit_day: str = ""


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
    temp_target: Path | None = None
    try:
        _validate_source(source, expected_revision_id)
        unresolved_visual_roles = _unresolved_required_visual_roles(source)
        if unresolved_visual_roles:
            raise StudentMaterialPdfError(
                "required visual placement is unresolved: " + ", ".join(unresolved_visual_roles)
            )
        if source.required_visual_role_ids:
            raise StudentMaterialPdfError(
                "required visual render evidence is unavailable for this text-only PDF renderer"
            )
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            temp_target = Path(handle.name)
        styles = getSampleStyleSheet()
        story = _build_story(source, styles)
        story.extend([
            Spacer(1, 10),
            Paragraph("PDF draft/preview - derived artifact. The native Google Drive file remains the canonical editable final.", styles["Italic"]),
        ])
        SimpleDocTemplate(
            str(temp_target),
            pagesize=LETTER,
            title=source.title,
            author="Agent OS Instructional Materials Coach",
        ).build(story)
        _verify_pdf(temp_target)
        temp_target.replace(target)
        temp_target = None
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
        if temp_target is not None:
            temp_target.unlink(missing_ok=True)
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
    _preview_artifact_type(source.artifact_role)
    if not source.paragraphs or any(not isinstance(item, str) or not item.strip() for item in source.paragraphs):
        raise StudentMaterialPdfError("paragraphs must contain non-empty text")
    _validate_role_ids(source.required_visual_role_ids)
    if not isinstance(source.compact_worksheet_header, bool):
        raise StudentMaterialPdfError("compact_worksheet_header must be boolean")
    _validate_student_identification_labels(source.student_identification_labels)
    if not isinstance(source.unit_day, str):
        raise StudentMaterialPdfError("unit_day must be text")
    if source.unit_day and (source.unit_day != source.unit_day.strip() or len(source.unit_day) > 32):
        raise StudentMaterialPdfError("unit_day must be trimmed text no longer than 32 characters")
    if not isinstance(source.verified_visual_placements, tuple) or any(
        not isinstance(item, PlacementReceipt) for item in source.verified_visual_placements
    ):
        raise StudentMaterialPdfError("verified_visual_placements must contain PlacementReceipt values")



def _build_story(source: StudentMaterialPdfSource, styles) -> list[object]:
    """Build the bounded preview story, using the compact worksheet header by default."""
    artifact_type = _preview_artifact_type(source.artifact_role)
    body_paragraphs = source.paragraphs
    if artifact_type == "docs" and source.compact_worksheet_header:
        story = _compact_worksheet_header_flowables(source, styles)
        body_paragraphs = _without_legacy_identification_paragraph(body_paragraphs)
    else:
        story = [Paragraph(_esc(source.title), styles["Title"]), Spacer(1, 10)]

    for paragraph in body_paragraphs:
        story.extend([Paragraph(_esc(paragraph), styles["BodyText"]), Spacer(1, 7)])
    return story


def _compact_worksheet_header_flowables(source: StudentMaterialPdfSource, styles) -> list[object]:
    """Render title + identification as one compact first-page band."""
    title_style = ParagraphStyle(
        "CompactWorksheetTitle",
        parent=styles["Heading2"],
        fontSize=14,
        leading=16,
        spaceAfter=0,
    )
    meta_style = ParagraphStyle(
        "CompactWorksheetMeta",
        parent=styles["BodyText"],
        fontSize=9,
        leading=11,
        spaceAfter=0,
    )
    flowables: list[object] = [Paragraph(_esc(source.title), title_style)]
    fields: list[str] = []
    for index, label in enumerate(source.student_identification_labels):
        blank = "____________________" if index == 0 else "________"
        fields.append(f"{_esc(label)}: {blank}")
    if source.unit_day:
        fields.append(f"Unit/Day: {_esc(source.unit_day)}")
    if fields:
        flowables.append(Paragraph(" &nbsp;&nbsp; ".join(fields), meta_style))
    flowables.append(Spacer(1, 6))
    return flowables


def _without_legacy_identification_paragraph(paragraphs: tuple[str, ...]) -> tuple[str, ...]:
    """Suppress only the old first-line Name blank when the compact band replaces it."""
    if paragraphs and _looks_like_legacy_identification_line(paragraphs[0]):
        return paragraphs[1:]
    return paragraphs


def _looks_like_legacy_identification_line(value: str) -> bool:
    normalized = " ".join(value.strip().split())
    return (
        len(normalized) <= 160
        and normalized.casefold().startswith("name:")
        and "_" in normalized
    )


def _validate_student_identification_labels(labels: object) -> None:
    if not isinstance(labels, tuple):
        raise StudentMaterialPdfError("student_identification_labels must be a tuple")
    if len(labels) > 4:
        raise StudentMaterialPdfError("student_identification_labels exceeds the bounded header limit")
    seen: set[str] = set()
    for label in labels:
        if not isinstance(label, str) or not label.strip():
            raise StudentMaterialPdfError("student identification labels must be non-empty text")
        if label != label.strip() or len(label) > 32:
            raise StudentMaterialPdfError("student identification labels must be trimmed text no longer than 32 characters")
        if label in seen:
            raise StudentMaterialPdfError("student identification labels must be unique")
        seen.add(label)


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
        if placement.artifact_revision_id != source.native_revision_id:
            raise StudentMaterialPdfError("visual placement receipt does not bind the exact preview source revision")
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
    trailer_index = data.rfind(b"trailer")
    startxref_index = data.rfind(b"startxref")
    eof_index = data.rfind(b"%%EOF")
    if trailer_index < 0 or startxref_index < trailer_index or eof_index < startxref_index:
        raise StudentMaterialPdfError("PDF render verification failed")
    offset_text = data[startxref_index + len(b"startxref"):eof_index].strip().splitlines()
    if not offset_text or not offset_text[0].isdigit():
        raise StudentMaterialPdfError("PDF render verification failed")
    xref_offset = int(offset_text[0])
    if xref_offset <= 0 or xref_offset >= len(data) or not data[xref_offset:].startswith(b"xref"):
        raise StudentMaterialPdfError("PDF render verification failed")


def _esc(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
