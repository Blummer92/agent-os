"""Bridge the WSC5 validated-workspace boundary into the #2137 continuation driver.

The single-issue pilot owns isolated execution plus validation. It deliberately
does not own GitHub PR materialization or handoff publication. This module makes
that boundary executable without adding a second lifecycle, repair state machine,
or GitHub write path: it projects canonical pilot evidence into one structured
#2137 continuation decision for the existing GitHub Service Agent delivery owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scripts.agent_os_execution_interface.continuation_driver import ContinuationDecision

VALIDATED_WORKSPACE_TERMINAL = "validated-workspace"
SAFE_IMPLEMENTATION_TERMINAL = "draft-pr-handoff"

ValidatedWorkspaceAction = Literal[
    "materialize-draft-pr",
    "repair-validation-failure",
    "stop",
]


@dataclass(frozen=True, slots=True)
class ValidatedWorkspaceObservation:
    """Smallest cross-runtime observation needed to continue delivery."""

    pilot_status: str
    validation_passed: bool
    changed_paths_contained: bool
    repair_admissible: bool = False
    excluded_surface_required: bool = False

    def __post_init__(self) -> None:
        for name in ("pilot_status",):
            if type(getattr(self, name)) is not str or not getattr(self, name):
                raise TypeError(f"{name} must be a non-empty string")
        for name in (
            "validation_passed",
            "changed_paths_contained",
            "repair_admissible",
            "excluded_surface_required",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a bool")


def decide_validated_workspace_continuation(
    observation: ValidatedWorkspaceObservation,
) -> ContinuationDecision:
    """Return the next bounded delivery transition without granting authority.

    A completed pilot with passing validation is not the Safe Implementation
    Lane terminal state; it is the validated-workspace boundary. The existing
    GitHub Service Agent delivery path owns Draft PR materialization/readback and
    handoff. Failed validation may re-enter repair only when the separate repair
    admission already says it is admissible. Excluded surfaces remain blocked.
    """
    if type(observation) is not ValidatedWorkspaceObservation:
        raise TypeError("observation must be an exact ValidatedWorkspaceObservation")

    if observation.excluded_surface_required:
        return ContinuationDecision(
            action="",
            blocked=True,
            reason_codes=("excluded-surface-authorization-required",),
        )

    if (
        observation.pilot_status == "completed"
        and observation.validation_passed
        and observation.changed_paths_contained
    ):
        return ContinuationDecision(
            action="materialize-draft-pr",
            reason_codes=("validated-workspace-delivery-required",),
        )

    if observation.pilot_status == "failed" and observation.repair_admissible:
        return ContinuationDecision(
            action="repair-validation-failure",
            reason_codes=("repair-admission-satisfied",),
        )

    return ContinuationDecision(
        action="",
        blocked=True,
        reason_codes=("validated-workspace-not-deliverable",),
    )
