"""Declared visual-example coverage for worksheets (#3212).

A lesson content spec may declare per-section visual examples (worked
examples, before/after frames, clear-vs-confusing comparisons) the unit
requires on the student worksheet. These declarations are the unit's image
needs surfaced as build-time obligations:

- ``require_visual_example_plan_coverage`` fails closed unless the governed
  #944 visual plan covers every declared example. A motion-spot worksheet
  whose unit requires visual examples can never be generated text-only.
- ``check_visual_example_coverage`` reuses the ``visual_completeness``
  contract to evaluate declared examples against verified placements, so
  classroom admission can refuse a text-only worksheet on the same terms.

This module selects no assets, retrieves no files, and grants no
authority. It only derives obligations from authored lesson declarations
and evaluates them against caller-supplied governed evidence.
"""
from __future__ import annotations

from .content_spec import LessonContent
from .visual_completeness import (
    VisualCompletenessResult,
    validate_visual_completeness,
)


class VisualExampleCoverageError(ValueError):
    """A declared visual example has no governed visual-plan coverage."""


def required_visual_example_bindings(
    content: LessonContent,
) -> tuple[tuple[str, str], ...]:
    """Sorted unique ``(role_id, slot_id)`` pairs the lesson declares.

    One pair is one completeness obligation (#3251): a role with N slots is
    N distinct obligations.
    """
    return tuple(
        sorted({(example.role_id, example.slot_id) for example in content.visual_examples})
    )


def require_visual_example_plan_coverage(
    content: LessonContent,
    visual_bindings: tuple[tuple[str, str, str], ...],
) -> None:
    """Fail closed unless the governed visual plan covers every declared example.

    ``visual_bindings`` are the ``(role_id, slot_id, asset_id)`` triples
    from the governed #944 plan. Declared visual examples with no plan
    binding raise instead of shipping a text-only worksheet; a lesson that
    declares no visual examples is unaffected.
    """
    required = required_visual_example_bindings(content)
    if not required:
        return
    if not visual_bindings:
        raise VisualExampleCoverageError(
            "worksheet declares required visual examples but no governed visual "
            "plan was supplied: "
            + ", ".join(f"{role_id}:{slot_id}" for role_id, slot_id in required)
        )
    planned = {(role_id, slot_id) for role_id, slot_id, _ in visual_bindings}
    missing = [binding for binding in required if binding not in planned]
    if missing:
        raise VisualExampleCoverageError(
            "governed visual plan does not cover declared visual examples: "
            + ", ".join(f"{role_id}:{slot_id}" for role_id, slot_id in missing)
        )


def check_visual_example_coverage(
    content: LessonContent,
    *,
    verified_bindings: tuple[tuple[str, str], ...] = (),
    unresolved_bindings: tuple[tuple[str, str], ...] = (),
) -> VisualCompletenessResult:
    """Evaluate declared visual examples against verified placements.

    Reuses the ``visual_completeness`` contract: every declared
    ``(role_id, slot_id)`` pair must be verified-placed. ``"fail"`` means at
    least one declared example has no verified placement; ``"manual-review"``
    means all are accounted for but some are unresolved; ``"pass"`` means
    every declared example is verified.
    """
    return validate_visual_completeness(
        required_roles=required_visual_example_bindings(content),
        verified_roles=tuple(verified_bindings),
        unresolved_roles=tuple(unresolved_bindings),
    )
