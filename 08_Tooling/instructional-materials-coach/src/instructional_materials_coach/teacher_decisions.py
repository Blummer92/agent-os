"""Local persistence for teacher visual-decision records (#3252).

Decisions are JSON files under ``reports/teacher-decisions/`` — the same
class of surface as ``lesson_record.py``'s ``reports/lessons/``: local,
human-readable, append-only, no daemon, no store, no scheduler. The overlay
already authorizes local record files; the files are never rewritten to
fake history (invalidation is evaluated at read time; supersession writes
a new file).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

DEFAULT_TEACHER_DECISIONS_DIR = "reports/teacher-decisions"

_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_component(value: object) -> str:
    text = str(value) if value is not None else ""
    cleaned = _SAFE_COMPONENT_RE.sub("-", text).strip("-")
    return cleaned[:120] or "unknown"


def decision_filename(decision: Mapping[str, Any]) -> str:
    """``<decided_at>-<decision_id>-<requirement_id>-<role>.json``.

    ``decided_at`` is ISO-8601; colons are sanitized for filename safety.
    """
    return "-".join(
        (
            _sanitize_component(decision.get("decided_at")),
            _sanitize_component(decision.get("decision_id")),
            _sanitize_component(decision.get("requirement_id")),
            _sanitize_component(decision.get("role")),
        )
    ) + ".json"


def write_teacher_decision(
    decision: Mapping[str, Any], decisions_dir: str | Path = DEFAULT_TEACHER_DECISIONS_DIR
) -> Path:
    """Validate and persist one decision record as JSON. Returns the path."""
    from instructional_workflow_contracts.teacher_visual_decision import (
        TeacherVisualDecisionRecord,
    )

    record = TeacherVisualDecisionRecord.from_dict(decision)
    payload = record.to_dict()
    directory = Path(decisions_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / decision_filename(payload)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def load_teacher_decisions(
    decisions_dir: str | Path = DEFAULT_TEACHER_DECISIONS_DIR,
    *,
    requirement_id: str | None = None,
) -> list[dict[str, Any]]:
    """Load decision records, optionally filtered by requirement.

    Unparseable files are skipped (a corrupt record must never crash the
    build path); malformed records that parse but fail validation are
    skipped as well. Absent directory → empty list, never an exception.
    """
    from instructional_workflow_contracts.teacher_visual_decision import (
        TeacherVisualDecisionRecord,
    )

    directory = Path(decisions_dir)
    if not directory.is_dir():
        return []
    decisions: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        try:
            record = TeacherVisualDecisionRecord.from_dict(raw)
        except ValueError:
            continue
        payload = record.to_dict()
        if requirement_id is not None and payload.get("requirement_id") != requirement_id:
            continue
        decisions.append(payload)
    return decisions


def active_decision_for(
    decisions: list[Mapping[str, Any]],
    *,
    requirement_id: str,
    role: str,
    slot: int = 0,
) -> dict[str, Any] | None:
    """Latest active decision for a (requirement, role, slot) triple.

    Returns None when absent — never an exception, never a fabricated
    default.
    """
    matches = [
        d
        for d in decisions
        if d.get("requirement_id") == requirement_id
        and d.get("role") == role
        and d.get("slot") == slot
        and d.get("status") == "active"
    ]
    if not matches:
        return None
    matches.sort(key=lambda d: str(d.get("decided_at", "")))
    return dict(matches[-1])
