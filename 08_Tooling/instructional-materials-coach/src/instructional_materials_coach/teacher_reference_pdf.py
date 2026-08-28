from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Mapping

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


class TeacherReferencePdfError(ValueError):
    """Fail-closed error for invalid teacher-reference PDF render inputs."""


def render_teacher_reference_pdf(
    reference: object,
    output_path: str | Path,
    *,
    asset_content: Mapping[str, bytes] | None = None,
) -> Path:
    """Render a bounded teacher reference using only caller-supplied asset bytes.

    ``asset_content`` is keyed by an exact governed ``asset_id``, ``stable_ref``,
    or ``external_file_id`` already present in the projection. The renderer does
    no retrieval and makes no asset-selection or approval decision.
    """
    if type(reference) is not dict:
        raise TeacherReferencePdfError("reference must be a built-in mapping")
    authority = reference.get("authority")
    if type(authority) is not dict or any(authority.values()):
        raise TeacherReferencePdfError("reference authority must remain false")

    reference_type = reference.get("reference_type")
    title = _text(reference.get("unit_title"), "unit_title")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    assets = dict(asset_content or {})
    if not all(isinstance(key, str) and isinstance(value, bytes) for key, value in assets.items()):
        raise TeacherReferencePdfError("asset_content must map string identities to bytes")

    doc = SimpleDocTemplate(
        str(target),
        pagesize=LETTER,
        rightMargin=0.48 * inch,
        leftMargin=0.48 * inch,
        topMargin=0.48 * inch,
        bottomMargin=0.48 * inch,
        title=title,
        author="Agent OS Instructional Materials Coach",
    )
    styles = _styles()
    story: list[Any] = [Paragraph(_esc(title), styles["title"]), Spacer(1, 8)]
    if reference_type == "unit-vocabulary-map":
        story.extend(_vocabulary_story(reference, assets, styles))
    elif reference_type == "worked-examples-visual-prompts":
        story.extend(_worked_examples_story(reference, assets, styles))
    else:
        raise TeacherReferencePdfError("unsupported reference_type")

    story.extend(
        [
            Spacer(1, 10),
            Paragraph(
                "Teacher reference only. This projection grants no readiness, approval, source, publication, production, or external-write authority.",
                styles["footer"],
            ),
        ]
    )
    doc.build(story)
    return target


def _vocabulary_story(reference: Mapping[str, Any], assets: Mapping[str, bytes], styles):
    rows = _rows(reference.get("rows"), "rows")
    data: list[list[Any]] = [[
        Paragraph("Day / lesson", styles["table_head"]),
        Paragraph("Word / term", styles["table_head"]),
        Paragraph("Student-friendly definition", styles["table_head"]),
        Paragraph("Expectation", styles["table_head"]),
        Paragraph("Icon status", styles["table_head"]),
        Paragraph("Icon preview", styles["table_head"]),
    ]]
    for index, row in enumerate(rows, start=1):
        data.append([
            Paragraph(_esc(row.get("day_lesson") or "-"), styles["table_body"]),
            Paragraph(_esc(_text(row.get("term"), f"rows[{index}].term")), styles["table_body"]),
            Paragraph(_esc(_text(row.get("student_friendly_definition"), f"rows[{index}].student_friendly_definition")), styles["table_body"]),
            Paragraph(_esc(row.get("expectation") or "unspecified"), styles["table_small"]),
            Paragraph(_esc(row.get("icon_status") or "unknown"), styles["table_small"]),
            _preview_flowable(row.get("icon_preview"), assets, styles, max_size=0.42 * inch),
        ])

    table = Table(
        data,
        colWidths=[0.68 * inch, 0.82 * inch, 2.38 * inch, 0.74 * inch, 0.82 * inch, 0.72 * inch],
        repeatRows=1,
        hAlign="CENTER",
    )
    table.setStyle(_table_style(header=True))
    excluded = reference.get("excluded_scaffolds") or []
    return [
        Paragraph("Unit Vocabulary Map", styles["heading"]),
        Paragraph(
            "Icon key: approved-existing = governed reusable icon supplied for this teacher-reference use; useful-but-missing = explicit gap; no-icon-needed = no icon required.",
            styles["note"],
        ),
        Spacer(1, 7),
        table,
        Spacer(1, 7),
        Paragraph(
            "Instructional scaffolds kept out of vocabulary: " + (", ".join(_esc(value) for value in excluded) if excluded else "None"),
            styles["note"],
        ),
    ]


def _worked_examples_story(reference: Mapping[str, Any], assets: Mapping[str, bytes], styles):
    rows = _rows(reference.get("rows"), "rows")
    story: list[Any] = [Paragraph("Worked Examples + Visual Prompt Reference", styles["heading"])]
    for index, row in enumerate(rows, start=1):
        header = f"{row.get('day_lesson') or 'Unplaced'} - {_text(row.get('skill_learning_purpose'), f'rows[{index}].skill_learning_purpose')}"
        detail = [
            [Paragraph("Example role", styles["label"]), Paragraph(_esc(row.get("example_role") or "unspecified"), styles["body"])],
            [Paragraph("Teacher modeling purpose", styles["label"]), Paragraph(_esc(_text(row.get("teacher_modeling_purpose"), f"rows[{index}].teacher_modeling_purpose")), styles["body"])],
            [Paragraph("Artifact location", styles["label"]), Paragraph(_esc(row.get("artifact_location") or "Not resolved"), styles["body"])],
            [Paragraph("Tutorial step", styles["label"]), Paragraph(_esc(row.get("tutorial_step") or "Not applicable"), styles["body"])],
            [Paragraph("Visual status", styles["label"]), Paragraph(_esc(row.get("visual_status") or "unknown"), styles["body"])],
            [Paragraph("Visual preview", styles["label"]), _preview_flowable(row.get("visual_preview"), assets, styles, max_size=1.45 * inch)],
            [Paragraph("Existing visual prompt", styles["label"]), Paragraph(_esc(row.get("visual_prompt") or "None / not generative"), styles["body"])],
            [Paragraph("Expected visual role", styles["label"]), Paragraph(_esc(row.get("expected_visual_description") or "Not resolved"), styles["body"])],
            [Paragraph("Source / reuse / safe-use", styles["label"]), Paragraph(_esc(row.get("source_reuse_safe_use_constraints") or "No additional supplied constraint"), styles["body"])],
        ]
        table = Table(detail, colWidths=[1.35 * inch, 5.05 * inch], hAlign="LEFT")
        table.setStyle(_table_style(header=False))
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F5F8"))]))
        story.extend([KeepTogether([Paragraph(_esc(header), styles["subheading"]), table]), Spacer(1, 11)])
    return story


def _preview_flowable(preview: object, assets: Mapping[str, bytes], styles, *, max_size: float):
    if not isinstance(preview, Mapping):
        return Paragraph("Explicit gap", styles["table_small_center"])
    content = _asset_bytes(preview, assets)
    if content is None:
        identity = preview.get("asset_id") or preview.get("stable_ref") or preview.get("external_file_id") or "approved identity"
        return Paragraph("Approved identity:<br/>" + _esc(identity), styles["table_small_center"])
    try:
        reader = ImageReader(BytesIO(content))
        width, height = reader.getSize()
        if width <= 0 or height <= 0:
            raise ValueError("invalid image dimensions")
        scale = min(max_size / width, max_size / height)
        return Image(BytesIO(content), width=width * scale, height=height * scale)
    except Exception as exc:
        raise TeacherReferencePdfError("asset_content contains unreadable image bytes") from exc


def _asset_bytes(preview: Mapping[str, Any], assets: Mapping[str, bytes]) -> bytes | None:
    matches = []
    for field in ("asset_id", "stable_ref", "external_file_id"):
        value = preview.get(field)
        if isinstance(value, str) and value in assets:
            matches.append(assets[value])
    if not matches:
        return None
    first = matches[0]
    if any(item != first for item in matches[1:]):
        raise TeacherReferencePdfError("asset_content identities for one governed preview disagree")
    return first


def _table_style(*, header: bool) -> TableStyle:
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B7C0CC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    if header:
        commands.extend([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9EEF5")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#172033")),
        ])
    return TableStyle(commands)


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("TRTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=colors.HexColor("#172033"), spaceAfter=4),
        "heading": ParagraphStyle("TRHeading", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=colors.HexColor("#1F3B5B"), spaceAfter=6),
        "subheading": ParagraphStyle("TRSubheading", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.HexColor("#223C58"), spaceAfter=5),
        "body": ParagraphStyle("TRBody", parent=base["BodyText"], fontName="Helvetica", fontSize=8.6, leading=11),
        "label": ParagraphStyle("TRLabel", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=8.2, leading=10.5),
        "note": ParagraphStyle("TRNote", parent=base["BodyText"], fontName="Helvetica", fontSize=8.3, leading=11, textColor=colors.HexColor("#445064")),
        "footer": ParagraphStyle("TRFooter", parent=base["BodyText"], fontName="Helvetica-Oblique", fontSize=7.6, leading=10, textColor=colors.HexColor("#596273")),
        "table_head": ParagraphStyle("TRTableHead", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.4, leading=9, alignment=TA_CENTER),
        "table_body": ParagraphStyle("TRTableBody", parent=base["BodyText"], fontName="Helvetica", fontSize=7.2, leading=9),
        "table_small": ParagraphStyle("TRTableSmall", parent=base["BodyText"], fontName="Helvetica", fontSize=6.9, leading=8.5),
        "table_small_center": ParagraphStyle("TRTableSmallCenter", parent=base["BodyText"], fontName="Helvetica", fontSize=6.6, leading=8, alignment=TA_CENTER),
    }


def _rows(value: object, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise TeacherReferencePdfError(f"{field} must be a list")
    if any(type(row) is not dict for row in value):
        raise TeacherReferencePdfError(f"{field} rows must be built-in mappings")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TeacherReferencePdfError(f"{field} must be non-empty text")
    return value.strip()


def _esc(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
