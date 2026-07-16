"""Local lesson-candidate records for the Notion Lessons Learned learning loop.

This module never talks to Notion -- it only produces a structured local
YAML artifact that a human applies to the real database. See
01_Shared_Standards/notion/notion-learning-databases.md for the schema
this mirrors, and this package's README for the field-mapping table.
"""
from __future__ import annotations

import dataclasses
import datetime
import uuid
from pathlib import Path
from typing import Any

import yaml

SEVERITIES = ("Low", "Medium", "High", "Critical")
LEARNING_TYPES = (
    "Mistake",
    "QA feedback",
    "Testing lesson",
    "Deployment lesson",
    "Scope/permission lesson",
    "Trigger lesson",
)
AREAS = ("Curriculum", "Automation", "Dashboard", "Governance", "Documentation", "Testing")
SOURCE_TYPES = ("Task", "ADR", "Incident", "Reflection", "Manual")


@dataclasses.dataclass
class LessonRecord:
    lesson_learned: str
    what_happened: str
    what_to_do_next_time: str = ""
    guardrail: str = ""
    owner_agent: str = "Instructional Materials Coach"
    severity: str = "Low"
    learning_type: str = "Mistake"
    area: str = "Curriculum"
    applies_to: list[str] = dataclasses.field(default_factory=lambda: ["Instructional Materials"])
    source_type: str = "Manual"
    source_link: str = ""
    follow_up_needed: bool = False
    surface_before_work: bool = False

    def __post_init__(self) -> None:
        _require_one_of("severity", self.severity, SEVERITIES)
        _require_one_of("learning_type", self.learning_type, LEARNING_TYPES)
        _require_one_of("area", self.area, AREAS)
        _require_one_of("source_type", self.source_type, SOURCE_TYPES)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _require_one_of(field_name: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ValueError(f"{field_name} must be one of {allowed}, got {value!r}")


def lesson_from_exception(exc: Exception, context: dict[str, Any]) -> LessonRecord:
    """Build a Mistake lesson record from a caught build failure.

    context carries whatever the caller already knows about the attempted
    build (e.g. slides_template, doc_template, target_folder, content_title)
    so What Happened is specific, not just a bare stack trace.
    """
    title = context.get("content_title", "Instructional materials build")
    what_happened = f"Build failed for '{title}': {type(exc).__name__}: {exc}. Context: {context}"
    return LessonRecord(
        lesson_learned=f"Build failure: {title}",
        what_happened=what_happened,
        what_to_do_next_time=(
            "Investigate the error above before retrying; confirm template IDs and "
            "target folder are correct and accessible."
        ),
        severity="Medium",
        learning_type="Mistake",
        source_type="Incident",
        follow_up_needed=True,
        surface_before_work=True,
    )


def record_lesson(record: LessonRecord, output_dir: str | Path) -> Path:
    """Write record as a timestamped YAML file under output_dir. Never touches Notion."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    slug = "".join(c if c.isalnum() else "-" for c in record.lesson_learned.lower())[:40].strip("-")
    path = output_dir / f"{timestamp}-{uuid.uuid4().hex[:8]}-{slug or 'lesson'}.yaml"
    path.write_text(yaml.safe_dump(record.to_dict(), sort_keys=False))
    return path
