"""Pure adapter from bounded dev-validation observations to pre-PR evidence.

The adapter accepts no argv or shell text from callers.  A plan is eligible only
when its exact command tuple matches one existing main-owned dev-validation
profile.  Observed timestamps/status/exit/diagnostics are supplied by the
bounded runner boundary and are never synthesized here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scripts.agent_os_remote_validation import (
    PrePrValidationPlan,
    SuppliedCommandResult,
    pre_pr_validation_plan_id,
)

from .dev_validation_profiles import PROFILE_CATALOG, profile_argv

ObservedStatus = Literal[
    "passed", "failed", "timed-out", "cancelled", "unavailable", "infrastructure-error"
]


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservedDevValidationCommand:
    profile_id: str
    runner_id: str
    started_at: str
    completed_at: str
    status: ObservedStatus
    exit_code: int | None
    diagnostic_summary: str = ""
    diagnostic_truncated: bool = False


def supplied_command_results_from_dev_validation(
    plan: PrePrValidationPlan,
    observed: tuple[ObservedDevValidationCommand, ...],
) -> tuple[SuppliedCommandResult, ...]:
    """Convert exact fixed-profile observations into canonical supplied results."""
    if type(plan) is not PrePrValidationPlan:
        raise TypeError("plan must be exact PrePrValidationPlan")
    if type(observed) is not tuple:
        raise TypeError("observed must be an exact tuple")
    if len(plan.commands) != 1 or len(observed) != 1:
        raise ValueError("dev-validation adapter requires one exact fixed command observation")

    item = observed[0]
    if type(item) is not ObservedDevValidationCommand:
        raise TypeError("observed item must be exact ObservedDevValidationCommand")
    if item.profile_id not in PROFILE_CATALOG:
        raise ValueError("unknown dev-validation profile")
    canonical_command = " ".join(profile_argv(item.profile_id))
    if plan.commands != (canonical_command,):
        raise ValueError("pre-PR plan command is not represented by the fixed profile catalog")
    if type(item.runner_id) is not str or not item.runner_id:
        raise ValueError("runner_id must be observed non-empty text")
    if type(item.started_at) is not str or not item.started_at:
        raise ValueError("started_at must be observed non-empty text")
    if type(item.completed_at) is not str or not item.completed_at:
        raise ValueError("completed_at must be observed non-empty text")
    if item.status not in {
        "passed", "failed", "timed-out", "cancelled", "unavailable", "infrastructure-error"
    }:
        raise ValueError("unsupported observed status")
    if type(item.diagnostic_summary) is not str:
        raise TypeError("diagnostic_summary must be exact text")
    if type(item.diagnostic_truncated) is not bool:
        raise TypeError("diagnostic_truncated must be exact bool")

    subject = plan.subject
    return (
        SuppliedCommandResult(
            plan_id=pre_pr_validation_plan_id(plan),
            invocation_id=subject.invocation_id,
            runner_id=item.runner_id,
            command_ordinal=0,
            command=canonical_command,
            source_head_sha=subject.expected_source_sha,
            tested_sha=subject.tested_sha,
            started_at=item.started_at,
            completed_at=item.completed_at,
            status=item.status,
            exit_code=item.exit_code,
            diagnostic_summary=item.diagnostic_summary,
            diagnostic_truncated=item.diagnostic_truncated,
        ),
    )


__all__ = ["ObservedDevValidationCommand", "supplied_command_results_from_dev_validation"]
