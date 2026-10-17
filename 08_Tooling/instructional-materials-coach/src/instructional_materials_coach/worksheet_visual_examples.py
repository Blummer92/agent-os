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
    N distinct obligations. A ``(role_id, slot_id)`` pair declared in more
    than one section is a conflicting obligation, not a shared one: slots
    are distinct placement targets, so the same slot cannot satisfy two
    independent sections. Fail closed and name both sections (#3212).
    """
    seen: dict[tuple[str, str], str] = {}
    for example in content.visual_examples:
        key = (example.role_id, example.slot_id)
        first_section = seen.get(key)
        if first_section is not None:
            raise VisualExampleCoverageError(
                "declared visual examples reuse (role_id, slot_id) "
                f"{example.role_id}:{example.slot_id} across independent "
                f"sections ({first_section!r} and {example.section!r}); "
                "declare a distinct slot for each section or keep one declaration"
            )
        seen[key] = example.section
    return tuple(sorted(seen))


def require_visual_example_plan_coverage(
    content: LessonContent,
    visual_bindings: tuple[tuple[str, str, str, bool], ...],
) -> None:
    """Fail closed unless the governed visual plan covers every declared example.

    ``visual_bindings`` are the ``(role_id, slot_id, asset_id, required)``
    quadruples from the governed #944 plan. Declared visual examples are
    required Docs obligations (#3212): a declared example with no plan
    binding raises, and so does one covered only by an *optional* plan
    assignment -- an optional binding that is never placed cannot discharge
    a required worksheet figure. A lesson that declares no visual examples
    is unaffected.
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
    planned_required = {
        (role_id, slot_id)
        for role_id, slot_id, _asset_id, is_required in visual_bindings
        if is_required
    }
    planned_optional = {
        (role_id, slot_id)
        for role_id, slot_id, _asset_id, is_required in visual_bindings
        if not is_required
    }
    missing = [binding for binding in required if binding not in planned_required]
    if missing:
        optional_only = [binding for binding in missing if binding in planned_optional]
        if optional_only:
            raise VisualExampleCoverageError(
                "declared visual examples are covered only by optional visual-plan "
                "assignments, which cannot satisfy a required worksheet figure: "
                + ", ".join(f"{role_id}:{slot_id}" for role_id, slot_id in optional_only)
                + ". Require the assignment in the governed plan or remove the declaration."
            )
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
