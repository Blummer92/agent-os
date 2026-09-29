"""Pure governed template-pair resolution for Instructional Materials builds (#2969)."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

TemplateKind = Literal["slides", "docs"]

@dataclass(frozen=True, slots=True)
class TemplateCandidate:
    template_id: str
    kind: TemplateKind
    approval_state: Literal["approved", "prototype", "historical", "unverified"]
    access_state: Literal["verified", "stale", "inaccessible", "unknown"]
    supported_placeholders: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ResolvedTemplatePair:
    slides_template_id: str
    docs_template_id: str

def resolve_approved_template_pair(candidates: tuple[TemplateCandidate, ...], *, required_placeholders: tuple[str, ...]) -> ResolvedTemplatePair:
    """Resolve exactly one approved compatible Slides/Docs pair or fail closed."""
    required=set(required_placeholders)
    if not required or any(not token for token in required):
        raise ValueError("required_placeholders must contain exact non-empty tokens")
    eligible={"slides": [], "docs": []}
    for candidate in candidates:
        if not candidate.template_id:
            raise ValueError("template_id is required")
        if candidate.approval_state!="approved" or candidate.access_state!="verified":
            continue
        if not required.issubset(set(candidate.supported_placeholders)):
            continue
        eligible[candidate.kind].append(candidate.template_id)
    for kind in ("slides","docs"):
        if len(eligible[kind]) != 1:
            raise ValueError(f"{kind} approved compatible template count must be exactly one; found {len(eligible[kind])}")
    return ResolvedTemplatePair(eligible["slides"][0],eligible["docs"][0])
