"""Semantic visual-role fulfillment checks (#3386).

Image-count and placement-only checks prove that *an* image exists for a
visual role, never that the image is the *right kind* of visual. This
module proves the kind: each required visual role may declare the
governed representation class it needs (the existing
``REPRESENTATION_CLASSES`` vocabulary from
``instructional_workflow_contracts.visual_asset_compatibility``:
``illustration`` / ``photography`` / ``diagram`` / ``interface-capture`` /
``unspecified`` -- never an invented taxonomy), and each placed asset
carries the representation class its governed compatibility evidence
assigned it (the v2 ``cohesion_profile.representation_class``).

Vocabulary note for the 2026-10-07 "Fix This Photo" reproduction: the
four embedded images were "schematic line illustrations" (geometric
scenes with person/tree/path/bench/building). In the governed
vocabulary that is ``diagram`` (a schematic illustration), and the
required role was ``photography`` (weak photographic composition
examples).

Semantics, deliberately conservative:

- ``required = "unspecified"`` (the governed plan declared no kind
  constraint) -> ``fulfilled``. The check never invents a constraint the
  requirement author did not declare; legacy plans keep their existing
  behavior.
- ``required`` declared but ``observed`` missing (v1 evidence, direct
  authoring, or evidence stripped in transit) -> ``unverifiable``. This
  is an explicit blocked state, never a pass: terminal QA routes the
  role to manual review with the role named (#3386 expected path 3).
- ``required`` and ``observed`` both known and different -> ``mismatch``.
  Terminal QA fails with an explicit finding naming the required and the
  observed class.
- equal -> ``fulfilled``.

Pure repository-side validation; no services, no credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from instructional_workflow_contracts.visual_asset_compatibility import (
    REPRESENTATION_CLASSES,
)

#: The governed value meaning "no kind constraint was declared".
UNCONSTRAINED_REPRESENTATION_CLASS = "unspecified"

#: The required/observed vocabulary this module accepts -- the governed
#: set, referenced (not redefined) so the vocabulary cannot drift.
GOVERNED_REPRESENTATION_CLASSES = REPRESENTATION_CLASSES


class VisualRoleFulfillmentError(ValueError):
    """Governed visual-role fulfillment evidence is malformed."""


def validate_representation_class(value: object, *, name: str = "representation class") -> str:
    """Return the governed representation class, or fail closed."""
    if not isinstance(value, str) or value not in GOVERNED_REPRESENTATION_CLASSES:
        raise VisualRoleFulfillmentError(
            f"{name} must be one of the governed representation classes: "
            f"{sorted(GOVERNED_REPRESENTATION_CLASSES)}"
        )
    return value


def observed_representation_class_from_compatibility(
    compatibility_evidence: Mapping[str, Any] | None,
) -> str | None:
    """Read the asset's governed kind from its compatibility evidence.

    Returns the v2 ``cohesion_profile.representation_class`` when present
    and governed, else ``None`` (unknown -- the check reports
    ``unverifiable`` rather than guessing). A malformed evidence envelope
    is an upstream contract breach and fails closed.
    """
    if compatibility_evidence is None:
        return None
    if not isinstance(compatibility_evidence, Mapping):
        raise VisualRoleFulfillmentError(
            "compatibility_evidence must be a mapping when supplied"
        )
    profile = compatibility_evidence.get("cohesion_profile")
    if profile is None:
        return None  # v1 evidence carries no kind: unknown, not wrong
    if not isinstance(profile, Mapping):
        raise VisualRoleFulfillmentError(
            "compatibility_evidence cohesion_profile must be a mapping"
        )
    kind = profile.get("representation_class")
    if kind is None:
        return None
    return validate_representation_class(kind, name="asset representation_class")


@dataclass(frozen=True)
class VisualRoleFulfillmentResult:
    """Outcome of one required-vs-observed visual-kind comparison."""

    status: str  # "fulfilled" | "mismatch" | "unverifiable"
    role_id: str
    slot_id: str
    required: str
    observed: str | None

    def message(self) -> str:
        if self.status == "mismatch":
            return (
                f"Visual role {self.role_id} (slot {self.slot_id}) requires "
                f"a {self.required} visual, but the placed asset is a "
                f"{self.observed} visual."
            )
        if self.status == "unverifiable":
            return (
                f"Visual role {self.role_id} (slot {self.slot_id}) requires "
                f"a {self.required} visual, but the placed asset carries no "
                "governed representation-class evidence; the kind cannot be "
                "proven and the role routes to manual review."
            )
        return (
            f"Visual role {self.role_id} (slot {self.slot_id}) is fulfilled: "
            f"required {self.required}, placed asset "
            f"{self.observed if self.observed is not None else 'unconstrained'}."
        )


def check_visual_role_fulfillment(
    *,
    role_id: str,
    slot_id: str,
    required_representation_class: str | None,
    observed_representation_class: str | None,
) -> VisualRoleFulfillmentResult:
    """Compare the required visual kind against the placed asset's kind.

    ``required_representation_class`` is the kind the governed plan
    declared for the role; ``None``/``"unspecified"`` means no constraint
    was declared (``fulfilled``). ``observed_representation_class`` is the
    kind the asset's governed evidence assigns it; ``None`` means the
    evidence is absent (``unverifiable`` when a constraint was declared).
    Values outside the governed vocabulary fail closed.
    """
    if not isinstance(role_id, str) or not role_id.strip():
        raise VisualRoleFulfillmentError("role_id must be non-empty text")
    if not isinstance(slot_id, str) or not slot_id.strip():
        raise VisualRoleFulfillmentError("slot_id must be non-empty text")
    required = (
        UNCONSTRAINED_REPRESENTATION_CLASS
        if required_representation_class is None
        else validate_representation_class(required_representation_class, name="required representation_class")
    )
    observed = (
        None
        if observed_representation_class is None
        else validate_representation_class(observed_representation_class, name="observed representation_class")
    )
    if required == UNCONSTRAINED_REPRESENTATION_CLASS:
        return VisualRoleFulfillmentResult(
            status="fulfilled", role_id=role_id, slot_id=slot_id,
            required=required, observed=observed,
        )
    if observed is None:
        return VisualRoleFulfillmentResult(
            status="unverifiable", role_id=role_id, slot_id=slot_id,
            required=required, observed=None,
        )
    if observed == required:
        return VisualRoleFulfillmentResult(
            status="fulfilled", role_id=role_id, slot_id=slot_id,
            required=required, observed=observed,
        )
    return VisualRoleFulfillmentResult(
        status="mismatch", role_id=role_id, slot_id=slot_id,
        required=required, observed=observed,
    )
