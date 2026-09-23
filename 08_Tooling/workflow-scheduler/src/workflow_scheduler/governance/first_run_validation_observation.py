"""Bind existing fixed GCE dev-validation evidence to #1985 observations.

This module does not execute validation and accepts no command, argv, runner, or
timestamp input from the first-run caller. It only validates the evidence emitted
by the existing fixed dev-validation runner and projects it into the canonical
#1985 ``ObservedDevValidationCommand`` type.
"""
from __future__ import annotations

from datetime import datetime

from scripts.agent_os_remote_validation import PrePrValidationPlan

from .dev_validation import VALIDATION_REGISTRY
from .dev_validation_profiles import canonical_profile_id, profile_argv
from .pre_pr_dev_validation_evidence import ObservedDevValidationCommand

FIXED_GCE_RUNNER_ID = "agent-os-gce-dev-validation-v1"

# The first-run lane may only execute a validation plan the *existing* fixed GCE
# dev-validation runner already knows how to run. ``VALIDATION_REGISTRY`` is that
# runner's own legacy execution registry, so this widens nothing: a plan that is
# not exactly one of those fixed profiles fails closed instead of becoming a new
# command surface.
FIRST_RUN_SUPPORTED_VALIDATION_IDS = tuple(sorted(VALIDATION_REGISTRY))


class FirstRunValidationObservationError(ValueError):
    """Fixed-runner evidence is incomplete, malformed, or identity-drifted."""


def resolve_fixed_first_run_validation_id(validation_plan: object) -> str:
    """Return the one existing fixed validation id whose argv is exactly the plan.

    The canonical #1985 pre-validation plan may execute only when it maps to an
    exact existing fixed validation profile. No plan is translated, rewritten, or
    approximated, and no new validation identity is created.
    """
    if type(validation_plan) is not PrePrValidationPlan:
        raise FirstRunValidationObservationError("validation-plan-malformed")
    commands = tuple(validation_plan.commands)
    if len(commands) != 1:
        raise FirstRunValidationObservationError("validation-plan-not-single-command")
    matches = tuple(
        validation_id
        for validation_id in FIRST_RUN_SUPPORTED_VALIDATION_IDS
        if " ".join(profile_argv(validation_id)) == commands[0]
    )
    if len(matches) != 1:
        raise FirstRunValidationObservationError("validation-profile-unsupported")
    return matches[0]


def _instant(value: object, name: str) -> datetime:
    if type(value) is not str or not value or not value.endswith("Z"):
        raise FirstRunValidationObservationError(f"{name}-invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise FirstRunValidationObservationError(f"{name}-invalid") from exc
    return parsed


def observed_command_from_fixed_gce_evidence(
    evidence: object,
    *,
    expected_repository: str,
    expected_issue_number: int,
    expected_sha: str,
    expected_profile_id: str,
    expected_request_id: str,
) -> ObservedDevValidationCommand:
    """Project one exact fixed-runner result into the existing #1985 adapter input."""
    if type(evidence) is not dict:
        raise FirstRunValidationObservationError("runner-evidence-malformed")
    expected_profile = canonical_profile_id(expected_profile_id)
    actual_profile = canonical_profile_id(evidence.get("profile_id", evidence.get("validation_id")))
    bindings = {
        "repository": expected_repository,
        "issue_number": expected_issue_number,
        "tested_sha": expected_sha,
        "request_id": expected_request_id,
    }
    if any(evidence.get(name) != value for name, value in bindings.items()):
        raise FirstRunValidationObservationError("runner-evidence-identity-mismatch")
    if actual_profile != expected_profile:
        raise FirstRunValidationObservationError("runner-evidence-profile-mismatch")
    if evidence.get("runner_id") != FIXED_GCE_RUNNER_ID:
        raise FirstRunValidationObservationError("runner-id-invalid")
    started = _instant(evidence.get("started_at"), "started-at")
    completed = _instant(evidence.get("completed_at"), "completed-at")
    if completed < started:
        raise FirstRunValidationObservationError("runner-time-order-invalid")
    status_map = {
        "success": "passed",
        "failure": "failed",
        "timeout": "timed-out",
        "needs-decision": "infrastructure-error",
    }
    status = status_map.get(evidence.get("status"))
    if status is None:
        raise FirstRunValidationObservationError("runner-status-invalid")
    exit_code = evidence.get("exit_code")
    if exit_code is not None and type(exit_code) is not int:
        raise FirstRunValidationObservationError("runner-exit-code-invalid")
    diagnostic = evidence.get("stderr_tail", "") or evidence.get("stdout_tail", "")
    if type(diagnostic) is not str:
        raise FirstRunValidationObservationError("runner-diagnostic-invalid")
    truncated = evidence.get("stderr_truncated", False) or evidence.get("stdout_truncated", False)
    if type(truncated) is not bool:
        raise FirstRunValidationObservationError("runner-diagnostic-invalid")
    return ObservedDevValidationCommand(
        profile_id=expected_profile,
        runner_id=FIXED_GCE_RUNNER_ID,
        started_at=evidence["started_at"],
        completed_at=evidence["completed_at"],
        status=status,
        exit_code=exit_code,
        diagnostic_summary=diagnostic,
        diagnostic_truncated=truncated,
    )


__all__ = [
    "FIRST_RUN_SUPPORTED_VALIDATION_IDS",
    "FIXED_GCE_RUNNER_ID",
    "FirstRunValidationObservationError",
    "observed_command_from_fixed_gce_evidence",
    "resolve_fixed_first_run_validation_id",
]
