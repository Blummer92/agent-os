"""Fail-closed modeling-guide acceptance check (#3562).

Enforces the six canonical Teacher Modeling checks
(``01_Shared_Standards/instructional-design/teacher-modeling-standards.md``)
and the rehearsal-view structure on a generated modeling-guide artifact's
text.

This module performs output validation only. It creates no agent, schema,
orchestration framework, persistence layer, or lesson-planning engine. The
six checks and the three views (rehearsal, audit, materials-extract) are
reused unchanged from the canonical standard; this module only inspects
artifact text for their evidence.

Fail-closed throughout: a missing, blank, or non-text artifact is never
accepted. Lesson-plan-shaped content without the required modeling
evidence fails, even when it carries a modeling-guide label. Brief lesson
context is allowed; it never substitutes for the rehearsal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

# The six canonical modeling checks, reused verbatim from
# teacher-modeling-standards.md. Each must be evidenced in the artifact.
SIX_MODELING_CHECKS: tuple[str, ...] = (
    "learning objective",
    "student task alignment",
    "think-aloud method",
    "component breakdown",
    "visual anchors",
    "error analysis",
)

# Governed aliases accepted as evidence for each canonical check name.
_CHECK_ALIASES: Mapping[str, tuple[str, ...]] = {
    "learning objective": ("learning objective",),
    "student task alignment": ("student task alignment", "immediate student task"),
    "think-aloud method": ("think-aloud method", "think-aloud", "think aloud"),
    "component breakdown": ("component breakdown",),
    "visual anchors": ("visual anchors", "visual anchor"),
    "error analysis": ("error analysis",),
}

# Rehearsal moment fields from the canonical play-by-play table.
_MOMENT_LABELS: Mapping[str, str] = {
    "teacher says": r"teacher\s+says",
    "teacher does": r"teacher\s+does",
    "students do or notice": r"students?\s+do(\s+or\s+notice)?",
    "check": r"(?<![\w-])check(?![\w-])",
}

_STEP_MARKERS = (
    r"step\s*\d",
    r"\bfirst\b,",
    r"\bthen\b,",
    r"\bnext\b,",
)
_CONSTRUCTION_VERBS = (
    "construct",
    "build",
    "write",
    "annotate",
    "highlight",
    "circle",
    "underline",
    "display",
    "project",
    "model",
    "demonstrate",
)
_DISPLAY_NOUNS = (
    "whiteboard",
    "board",
    "slide",
    "chart",
    "poster",
    "screen",
    "display",
    "projector",
)
_MISTAKE_WORDS = ("misconception", "mistake", "mistaken", "wrong", "incorrect", "error")
_CORRECTION_WORDS = ("correct", "self-correct", "revision", "revise", "instead", "fix")

_MIN_MOMENTS = 2  # a play-by-play needs more than one labeled moment
_MIN_TEXT_CHARS = 200  # below this there cannot be a usable rehearsal

MODELING_GUIDE_OWNER = "teacher-modeling-coach"
MODELING_GUIDE_DEFAULT_VIEW = "rehearsal"


@dataclass(frozen=True)
class ModelingGuideAcceptance:
    """Result of evaluating one modeling-guide artifact's text."""

    accepted: bool
    checks_passed: tuple[str, ...]
    checks_failed: tuple[str, ...]
    reason_codes: tuple[str, ...]
    evidence: Mapping[str, str] = field(default_factory=dict)


def _snip(match: re.Match[str] | None) -> str:
    if match is None:
        return ""
    text = match.group(0)
    return text[:120]


def _check_artifact_present(text: str) -> tuple[bool, str, str]:
    if not text or not text.strip():
        return False, "artifact-missing", ""
    if len(text.strip()) < _MIN_TEXT_CHARS:
        return False, "artifact-too-short", ""
    return True, "", ""


def _check_moment_structure(text: str) -> tuple[bool, str, str]:
    hits = {}
    for label, pattern in _MOMENT_LABELS.items():
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        hits[label] = matches
    missing = [label for label, matches in hits.items() if not matches]
    if missing:
        return False, "moment-structure-missing", ""
    says_count = len(hits["teacher says"])
    if says_count < _MIN_MOMENTS:
        return False, "moment-structure-single-moment", ""
    return True, "", _snip(hits["teacher says"][0])


def _check_worked_example_construction(text: str) -> tuple[bool, str, str]:
    lowered = text.lower()
    step_hits = sum(len(re.findall(p, lowered)) for p in _STEP_MARKERS)
    verb_hit = next((v for v in _CONSTRUCTION_VERBS if v in lowered), "")
    if step_hits >= 2 and verb_hit:
        m = re.search(r"step\s*\d.{0,80}", lowered)
        return True, "", (m.group(0)[:120] if m else verb_hit)
    return False, "construction-missing", ""


def _check_visual_anchor(text: str) -> tuple[bool, str, str]:
    lowered = text.lower()
    if "visual anchor" not in lowered:
        return False, "visual-anchor-missing", ""
    if not any(noun in lowered for noun in _DISPLAY_NOUNS):
        return False, "visual-anchor-undisplayed", ""
    m = re.search(r"visual anchor.{0,100}", lowered)
    return True, "", (m.group(0)[:120] if m else "visual anchor")


def _check_misconception_correction(text: str) -> tuple[bool, str, str]:
    lowered = text.lower()
    mistake = next((w for w in _MISTAKE_WORDS if w in lowered), "")
    if not mistake:
        return False, "misconception-missing", ""
    correction = next((w for w in _CORRECTION_WORDS if w in lowered), "")
    if not correction:
        return False, "correction-missing", ""
    return True, "", f"{mistake} -> {correction}"


def _check_canonical_check(text: str, check_name: str) -> tuple[bool, str, str]:
    lowered = text.lower()
    for alias in _CHECK_ALIASES[check_name]:
        if alias in lowered:
            return True, "", alias
    return False, f"check-missing:{check_name}", ""


def evaluate_modeling_guide_acceptance(
    artifact_text: str | None,
) -> ModelingGuideAcceptance:
    """Evaluate a generated modeling-guide artifact's text, fail-closed.

    Returns accepted=True only when every required check passes:
    artifact presence, rehearsal moment structure, worked-example
    construction, visual anchor, misconception + correction, and each of
    the six canonical modeling checks.
    """
    text = artifact_text if isinstance(artifact_text, str) else ""

    passed: list[str] = []
    failed: list[str] = []
    reasons: list[str] = []
    evidence: dict[str, str] = {}

    def record_check(name: str, result: tuple[bool, str, str]) -> None:
        ok, reason, snip = result
        if ok:
            passed.append(name)
            if snip:
                evidence[name] = snip
        else:
            failed.append(name)
            reasons.append(reason)

    record_check("artifact-present", _check_artifact_present(text))
    if "artifact-present" in failed:
        return ModelingGuideAcceptance(
            accepted=False,
            checks_passed=tuple(passed),
            checks_failed=tuple(failed),
            reason_codes=tuple(reasons),
            evidence=evidence,
        )

    record_check("rehearsal-moment-structure", _check_moment_structure(text))
    record_check("worked-example-construction", _check_worked_example_construction(text))
    record_check("visual-anchor", _check_visual_anchor(text))
    record_check("misconception-correction", _check_misconception_correction(text))
    for check_name in SIX_MODELING_CHECKS:
        record_check(
            f"canonical-check:{check_name}",
            _check_canonical_check(text, check_name),
        )

    return ModelingGuideAcceptance(
        accepted=not failed,
        checks_passed=tuple(passed),
        checks_failed=tuple(failed),
        reason_codes=tuple(reasons),
        evidence=evidence,
    )


def is_modeling_guide_request(request_text: str | None) -> bool:
    """Whether a teacher request asks for a modeling guide.

    Bound to the #3562 Modeling Guide Request Rule: an explicit modeling
    guide request belongs to the Teacher Modeling Coach, not to the
    Instructional Materials Coach ``teacher-guide`` document path.
    """
    if not isinstance(request_text, str):
        return False
    return bool(re.search(r"modeling\s+guide|teacher\s+modeling", request_text, re.IGNORECASE))


def default_modeling_guide_view(request_text: str | None) -> str:
    """Default presentation view for an explicit modeling-guide request.

    ``rehearsal`` unless the teacher requests another supported view.
    """
    lowered = (request_text or "").lower()
    if "audit" in lowered:
        return "audit"
    if "materials-extract" in lowered or "materials extract" in lowered:
        return "materials-extract"
    return MODELING_GUIDE_DEFAULT_VIEW


def resolve_modeling_guide_owner(request_text: str | None) -> tuple[str, str]:
    """Resolve (owner, view) for a modeling-guide request.

    Returns the canonical Teacher Modeling Coach owner and the default
    view. Non-modeling-guide requests return ("", "") so callers route
    them through their existing path unchanged.
    """
    if not is_modeling_guide_request(request_text):
        return "", ""
    return MODELING_GUIDE_OWNER, default_modeling_guide_view(request_text)
