"""Deterministic structural QA for student-facing artifact specifications."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

PASS = "pass"
MANUAL_REVIEW = "manual-review"
FAIL = "fail"


@dataclass(frozen=True)
class ArtifactStructureFinding:
    code: str
    severity: str
    message: str
    slide_index: int | None = None


@dataclass(frozen=True)
class ArtifactStructureResult:
    status: str
    findings: tuple[ArtifactStructureFinding, ...]

    @property
    def passed(self) -> bool:
        return self.status == PASS


def _slide_index(slide: Mapping[str, Any]) -> int | None:
    value = slide.get("index")
    return value if isinstance(value, int) else None


def _rects_overlap(a: Sequence[float], b: Sequence[float]) -> bool:
    if len(a) != 4 or len(b) != 4:
        return True
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _required_sections(slides: Sequence[Mapping[str, Any]], requirements: Mapping[str, Any]) -> Iterable[ArtifactStructureFinding]:
    kinds = {str(slide.get("kind", "")).strip() for slide in slides}
    rules = {
        "warm_up": ("warm-up", "artifact-required-warm-up-missing"),
        "exit_ticket": ("exit-ticket", "artifact-required-exit-ticket-missing"),
        "finalization": ("finalization", "artifact-required-finalization-missing"),
    }
    for key, (kind, code) in rules.items():
        if requirements.get(key) is True and kind not in kinds:
            yield ArtifactStructureFinding(code, FAIL, f"Required student-facing section is missing: {kind}.")


def _slide_findings(slide: Mapping[str, Any]) -> Iterable[ArtifactStructureFinding]:
    kind = slide.get("kind")
    index = _slide_index(slide)
    instructional = kind in {"model", "tutorial", "guided-practice", "independent-task"}
    if instructional:
        move_ids = slide.get("teaching_move_ids", [])
        if not isinstance(move_ids, list) or len(move_ids) != 1:
            yield ArtifactStructureFinding("artifact-multiple-teaching-moves", FAIL, "Step-specific slides must carry exactly one teaching move.", index)
        paragraphs = slide.get("paragraph_blocks", 0)
        bullets = slide.get("bullet_count", 0)
        if not isinstance(paragraphs, int) or paragraphs > 0:
            yield ArtifactStructureFinding("artifact-paragraph-block-on-student-slide", FAIL, "Student-facing model/tutorial slides cannot contain paragraph blocks.", index)
        if not isinstance(bullets, int) or bullets > 3:
            yield ArtifactStructureFinding("artifact-student-slide-too-dense", FAIL, "Student-facing model/tutorial slides should use three or fewer bullets.", index)
    if kind in {"model", "tutorial"}:
        if slide.get("visual_role") != "dominant":
            yield ArtifactStructureFinding("artifact-model-visual-not-dominant", FAIL, "Model/tutorial slides must declare the instructional visual as dominant.", index)
        if slide.get("rendered_visual_scale_verified") is not True:
            yield ArtifactStructureFinding("artifact-rendered-visual-scale-needs-review", MANUAL_REVIEW, "Rendered visual scale/readability is not mechanically proven; phone/projector review is required.", index)

    regions = slide.get("regions")
    if not isinstance(regions, Mapping):
        yield ArtifactStructureFinding("artifact-section-hierarchy-unverifiable", MANUAL_REVIEW, "Section hierarchy cannot be verified because normalized region bounds are missing.", index)
        return
    required = {"title", "body"}
    if instructional:
        required.add("action")
    if kind in {"check", "critique", "exit-ticket"}:
        required.add("check")
    missing = sorted(name for name in required if name not in regions)
    if missing:
        yield ArtifactStructureFinding("artifact-section-hierarchy-missing-region", FAIL, f"Required structural regions are missing: {', '.join(missing)}.", index)
        return
    items = [(name, bounds) for name, bounds in regions.items() if isinstance(bounds, Sequence) and not isinstance(bounds, (str, bytes))]
    for pos, (left_name, left_bounds) in enumerate(items):
        for right_name, right_bounds in items[pos + 1 :]:
            if _rects_overlap(left_bounds, right_bounds):
                yield ArtifactStructureFinding("artifact-section-regions-overlap", FAIL, f"Structural regions overlap: {left_name} and {right_name}.", index)


def _worksheet_alignment(slides: Sequence[Mapping[str, Any]], requirements: Mapping[str, Any]) -> Iterable[ArtifactStructureFinding]:
    required_ref = requirements.get("plan_worksheet_ref")
    if not required_ref:
        return
    plan_slides = [slide for slide in slides if slide.get("kind") == "plan"]
    if not plan_slides:
        yield ArtifactStructureFinding("artifact-plan-slide-missing", FAIL, "A planning worksheet is required but no Plan slide exists.")
    elif not any(slide.get("worksheet_ref") == required_ref for slide in plan_slides):
        yield ArtifactStructureFinding("artifact-plan-worksheet-mismatch", FAIL, "Plan stage does not preserve the required planning worksheet reference.")


def _instructional_purpose(spec: Mapping[str, Any], requirements: Mapping[str, Any]) -> Iterable[ArtifactStructureFinding]:
    required = requirements.get("required_concept_tags", [])
    represented = set(spec.get("instructional_concept_tags", []))
    if required and not set(required).issubset(represented):
        yield ArtifactStructureFinding("artifact-approved-purpose-not-preserved", FAIL, "Artifact specification does not preserve all required concept-level instructional purposes.")
    if spec.get("learning_target_mode") == "click-sequence":
        yield ArtifactStructureFinding("artifact-learning-target-collapsed-to-clicks", FAIL, "Learning target collapses the broader approved objective into software-click directions.")


def validate_artifact_structure(spec: Mapping[str, Any]) -> ArtifactStructureResult:
    """Validate structure only; rendered visual uncertainty routes to manual review."""
    slides_value = spec.get("slides", [])
    requirements_value = spec.get("requirements", {})
    if not isinstance(slides_value, list) or not all(isinstance(slide, Mapping) for slide in slides_value):
        return ArtifactStructureResult(FAIL, (ArtifactStructureFinding("artifact-slides-invalid", FAIL, "Artifact spec must provide slides as structured mappings."),))
    if not isinstance(requirements_value, Mapping):
        return ArtifactStructureResult(FAIL, (ArtifactStructureFinding("artifact-requirements-invalid", FAIL, "Artifact requirements must be a structured mapping."),))

    slides: list[Mapping[str, Any]] = slides_value
    requirements: Mapping[str, Any] = requirements_value
    findings: list[ArtifactStructureFinding] = []
    findings.extend(_required_sections(slides, requirements))
    findings.extend(_worksheet_alignment(slides, requirements))
    findings.extend(_instructional_purpose(spec, requirements))
    for slide in slides:
        findings.extend(_slide_findings(slide))

    if any(f.severity == FAIL for f in findings):
        status = FAIL
    elif any(f.severity == MANUAL_REVIEW for f in findings):
        status = MANUAL_REVIEW
    else:
        status = PASS
    return ArtifactStructureResult(status, tuple(findings))
