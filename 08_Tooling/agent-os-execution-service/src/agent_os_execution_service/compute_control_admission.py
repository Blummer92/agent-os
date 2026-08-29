"""Fail-closed execution admission over the canonical #1419 projection.

This module does not decide whether compute is justified. That decision remains
owned entirely by ``scripts.agent_os_issue_acceptance.compute_control_projection``.
It only verifies that one already-produced canonical projection matches the
exact repository/head being dispatched and refuses runtime execution for every
non-spend disposition.

No authorization is created here. A successful return means only that #1419 did
not prohibit spending compute for this exact identity; all downstream execution
authorization, capability routing, Scheduler lease, validation, and lifecycle
gates remain independently required.
"""

from __future__ import annotations

from scripts.agent_os_issue_acceptance.compute_control_projection import (
    ComputeControlProjection,
    ComputeDisposition,
)

_SPEND_COMPUTE_DISPOSITIONS = frozenset(
    {
        ComputeDisposition.RUN_NOW,
        ComputeDisposition.FOCUSED_VALIDATION_FIRST,
        ComputeDisposition.FINAL_CLOUD_VALIDATION_REQUIRED,
    }
)


class ComputeControlAdmissionError(RuntimeError):
    """Raised before runtime when canonical compute-control does not admit spend."""


def require_compute_control_admission(
    projection: ComputeControlProjection,
    *,
    repository: str,
    current_head_sha: str,
    validation_class: str | None = None,
) -> ComputeControlProjection:
    """Verify one exact #1419 projection before expensive execution.

    The projection is revalidated using its canonical invariant, then bound to
    the repository/head the caller is about to execute. When a validation class
    is supplied, it must also match #1419's already-projected recommendation.

    This function never upgrades a disposition and never treats missing or stale
    evidence as permission. It returns the same projection object only for the
    three #1419 dispositions that explicitly describe a legitimate next compute
    step. Every other disposition fails closed before runtime side effects.
    """
    if type(projection) is not ComputeControlProjection:
        raise TypeError("projection must be exact ComputeControlProjection")
    if type(repository) is not str or not repository or "/" not in repository:
        raise ValueError("repository must use owner/name form")
    if type(current_head_sha) is not str or len(current_head_sha) != 40:
        raise ValueError("current_head_sha must be an exact 40-character SHA")
    if validation_class is not None and (
        type(validation_class) is not str or not validation_class
    ):
        raise ValueError("validation_class must be non-empty built-in text or None")

    try:
        projection.__post_init__()
    except (TypeError, ValueError) as exc:
        raise ComputeControlAdmissionError(
            "compute-control projection failed canonical validation"
        ) from exc

    if projection.repository.casefold() != repository.casefold():
        raise ComputeControlAdmissionError(
            "compute-control projection repository does not match dispatch identity"
        )
    if projection.current_head_sha is None:
        raise ComputeControlAdmissionError(
            "compute-control projection has no exact current-head identity"
        )
    if projection.current_head_sha != current_head_sha:
        raise ComputeControlAdmissionError(
            "compute-control projection is stale for the dispatch head"
        )
    if projection.compute_disposition not in _SPEND_COMPUTE_DISPOSITIONS:
        raise ComputeControlAdmissionError(
            "compute-control projection blocks runtime spend: "
            f"{projection.compute_disposition.value}"
        )
    if (
        validation_class is not None
        and projection.recommended_validation_or_execution_class != validation_class
    ):
        raise ComputeControlAdmissionError(
            "compute-control recommended class does not match dispatch class"
        )

    return projection
