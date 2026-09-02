"""Deterministic #1537 risk-to-CKR12 lesson activation projection.

This module does not classify risk and does not retrieve Lessons Learned. It
accepts already-canonical risk identifiers, projects them to a small checked-in
set of stable lesson identities, and applies CKR12 activation accountability
before returning known references for the existing CKR6/CKR11/CKR2 path.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .lesson_activation_accountability import (
    LessonAccountabilityError,
    LessonActivationAccountability,
    load_lesson_accountability_catalog,
)

MAX_PROJECTED_LESSONS = 3
RISK_LESSON_MAP_PATH = (
    Path(__file__).with_name("data") / "risk_lesson_activation.json"
)


@dataclass(frozen=True, slots=True)
class RiskLessonProjection:
    """Bounded advisory lesson references selected from supplied risk IDs only."""

    risk_classes: tuple[str, ...]
    lesson_ids: tuple[str, ...]
    blocked_lesson_ids: tuple[str, ...]
    blocked_reasons: tuple[str, ...]

    @property
    def retrieval_required(self) -> bool:
        return bool(self.lesson_ids)

    @property
    def retrieval_mode(self) -> str:
        return "known-reference" if self.lesson_ids else "not-needed"


def load_risk_lesson_activation_map(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Load compact risk -> lesson identity metadata with strict bounds."""

    raw = json.loads((path or RISK_LESSON_MAP_PATH).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise LessonAccountabilityError("risk lesson activation map root must be an object")

    result: dict[str, tuple[str, ...]] = {}
    for risk, lesson_ids in raw.items():
        if not isinstance(risk, str) or not risk.strip():
            raise LessonAccountabilityError("risk class must be a non-empty string")
        if not isinstance(lesson_ids, list) or not lesson_ids:
            raise LessonAccountabilityError(f"risk mapping {risk!r} must contain lesson identities")
        if len(lesson_ids) > MAX_PROJECTED_LESSONS:
            raise LessonAccountabilityError(
                f"risk mapping {risk!r} exceeds the bounded lesson budget"
            )
        normalized: list[str] = []
        for lesson_id in lesson_ids:
            if not isinstance(lesson_id, str) or not lesson_id.strip():
                raise LessonAccountabilityError("mapped lesson identity must be non-empty text")
            if lesson_id in normalized:
                raise LessonAccountabilityError(
                    f"risk mapping {risk!r} contains duplicate lesson identity: {lesson_id}"
                )
            normalized.append(lesson_id)
        result[risk] = tuple(normalized)
    return result


def project_risks_to_lessons(
    risk_classes: Iterable[str],
    *,
    mapping: Mapping[str, Sequence[str]] | None = None,
    catalog: Sequence[LessonActivationAccountability] | None = None,
) -> RiskLessonProjection:
    """Project already-classified risks to ready CKR12 signal-activatable IDs.

    Unknown/unmapped risk identifiers intentionally produce no activation. A
    mapped identity that is missing from CKR12 is an accountability error. A
    mapped lesson whose CKR12 activation class/readiness no longer permits
    ordinary signal activation is reported as blocked and is never returned as
    a usable known reference.
    """

    if isinstance(risk_classes, (str, bytes)):
        raise TypeError("risk_classes must be an iterable of risk identifiers")

    normalized_risks: list[str] = []
    for risk in risk_classes:
        if not isinstance(risk, str) or not risk.strip():
            raise LessonAccountabilityError("risk class must be a non-empty string")
        normalized_risks.append(risk)
    canonical_risks = tuple(sorted(set(normalized_risks)))

    active_mapping = dict(mapping or load_risk_lesson_activation_map())
    active_catalog = tuple(catalog or load_lesson_accountability_catalog())
    by_id = {entry.lesson_id: entry for entry in active_catalog}

    candidates: list[str] = []
    for risk in canonical_risks:
        for lesson_id in active_mapping.get(risk, ()):
            if lesson_id not in candidates:
                candidates.append(lesson_id)

    selected: list[str] = []
    blocked_ids: list[str] = []
    blocked_reasons: list[str] = []
    for lesson_id in candidates:
        entry = by_id.get(lesson_id)
        if entry is None:
            raise LessonAccountabilityError(
                f"risk mapping references unknown lesson identity: {lesson_id}"
            )
        if entry.activation_class != "signal-activatable":
            blocked_ids.append(lesson_id)
            blocked_reasons.append(f"{lesson_id}:activation-class:{entry.activation_class}")
            continue
        if entry.activation_readiness != "ready":
            blocked_ids.append(lesson_id)
            blocked_reasons.append(f"{lesson_id}:activation-readiness:{entry.activation_readiness}")
            continue
        if len(selected) < MAX_PROJECTED_LESSONS:
            selected.append(lesson_id)

    return RiskLessonProjection(
        risk_classes=canonical_risks,
        lesson_ids=tuple(selected),
        blocked_lesson_ids=tuple(blocked_ids),
        blocked_reasons=tuple(blocked_reasons),
    )
