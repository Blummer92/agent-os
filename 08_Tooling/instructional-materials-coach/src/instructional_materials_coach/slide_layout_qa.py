"""Deterministic structural QA for student-facing slide render plans.

This module intentionally evaluates only mechanically provable layout facts.
Rendered judgments that need a human eye remain the responsibility of the
rendered-review gate (#1835).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

Role = Literal["title", "directions", "model", "task", "teacher-cue", "supporting-preview", "accent"]

_REQUIRED_ROLES = frozenset({"title", "directions", "model", "task", "teacher-cue"})
_TEXT_ROLES = frozenset({"title", "directions", "task", "teacher-cue"})


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def overlaps(self, other: "Box") -> bool:
        return self.x < other.right and self.right > other.x and self.y < other.bottom and self.bottom > other.y


@dataclass(frozen=True)
class SlideElement:
    element_id: str
    role: Role
    box: Box
    z_index: int = 0
    text: str = ""
    foreground: str | None = None
    background: str | None = None
    opaque: bool = False
    placeholder: bool = False
    intentional_layering: bool = False


@dataclass(frozen=True)
class SlidePlan:
    width: float
    height: float
    elements: tuple[SlideElement, ...]
    focal_model: bool = False


@dataclass(frozen=True)
class LayoutFinding:
    code: str
    severity: Literal["fail", "manual-review"]
    element_ids: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class LayoutQAResult:
    findings: tuple[LayoutFinding, ...]

    @property
    def passed(self) -> bool:
        return not any(finding.severity == "fail" for finding in self.findings)

    @property
    def manual_review_required(self) -> bool:
        return any(finding.severity == "manual-review" for finding in self.findings)


def _hex_rgb(value: str | None) -> tuple[float, float, float] | None:
    if not value:
        return None
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def _luminance(color: str | None) -> float | None:
    rgb = _hex_rgb(color)
    if rgb is None:
        return None

    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str | None, background: str | None) -> float | None:
    first = _luminance(foreground)
    second = _luminance(background)
    if first is None or second is None:
        return None
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def evaluate_slide_layout(plan: SlidePlan) -> LayoutQAResult:
    """Return deterministic failures plus bounded rendered-review hooks."""
    findings: list[LayoutFinding] = []
    slide_area = max(0.0, plan.width) * max(0.0, plan.height)

    for element in plan.elements:
        if element.role in _TEXT_ROLES and element.text.strip():
            ratio = contrast_ratio(element.foreground, element.background)
            if ratio is None:
                findings.append(LayoutFinding(
                    "contrast-unprovable", "manual-review", (element.element_id,),
                    "Required text contrast cannot be proven from the structural render plan.",
                ))
            elif ratio < 4.5:
                findings.append(LayoutFinding(
                    "unsafe-required-text-contrast", "fail", (element.element_id,),
                    f"Required text contrast ratio {ratio:.2f}:1 is below the structural 4.5:1 floor.",
                ))

        if element.placeholder and element.opaque and not element.text.strip():
            covered = tuple(
                other.element_id
                for other in plan.elements
                if other.element_id != element.element_id
                and other.role in _REQUIRED_ROLES
                and element.z_index > other.z_index
                and element.box.overlaps(other.box)
            )
            if covered:
                findings.append(LayoutFinding(
                    "opaque-placeholder-occlusion", "fail", (element.element_id, *covered),
                    "An empty opaque placeholder is layered above required instructional content.",
                ))

    required = [element for element in plan.elements if element.role in _REQUIRED_ROLES]
    for index, first in enumerate(required):
        for second in required[index + 1:]:
            if first.intentional_layering or second.intentional_layering:
                continue
            if first.box.overlaps(second.box):
                findings.append(LayoutFinding(
                    "required-region-collision", "fail", (first.element_id, second.element_id),
                    "Required instructional regions overlap without an intentional-layering contract.",
                ))

    if slide_area > 0:
        for element in plan.elements:
            if element.role != "supporting-preview":
                continue
            share = element.box.area / slide_area
            if share > 0.35:
                findings.append(LayoutFinding(
                    "supporting-preview-overscale", "fail", (element.element_id,),
                    f"Supporting preview occupies {share:.0%} of the slide; supporting visuals are capped at 35%.",
                ))

        if plan.focal_model:
            models = [element for element in plan.elements if element.role == "model"]
            if models and max(element.box.area / slide_area for element in models) < 0.30:
                findings.append(LayoutFinding(
                    "focal-model-underdominant", "fail", tuple(element.element_id for element in models),
                    "A focal-model slide does not reserve a dominant instructional region for its model visual.",
                ))

    return LayoutQAResult(tuple(findings))


def finding_codes(result: LayoutQAResult) -> set[str]:
    return {finding.code for finding in result.findings}
