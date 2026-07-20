"""Pure-local WSC4 approved-execution projection consumption.

The consumer validates already-built portable projection evidence against explicit
caller expectations. It does not authorize execution, create Scheduler objects,
read clocks, inspect repositories, access credentials, or perform external I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from scripts.agent_os_issue_acceptance import (
    ApprovedExecutionProjection,
    serialize_approved_execution_projection,
)

_CONSUMPTION_STATUSES = frozenset(
    {"accepted", "rejected", "stale", "blocked", "needs-decision"}
)
_REASON_CODES = frozenset(
    {
        "projection.incomplete",
        "projection.lookup-failed",
        "identity.quarantined",
        "validation.stale",
    }
)


@dataclass(frozen=True, slots=True)
class ProjectionConsumptionResult:
    """Immutable, non-authoritative result of checking one supplied projection."""

    status: str
    projection: ApprovedExecutionProjection | None
    reason_codes: tuple[str, ...] = ()
    details: tuple[str, ...] = ()
    complete: bool = field(init=False)
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.status not in _CONSUMPTION_STATUSES:
            raise ValueError("unsupported projection consumption status")
        reasons = tuple(sorted(set(self.reason_codes)))
        if not set(reasons) <= _REASON_CODES:
            raise ValueError("projection consumption reason code is unsupported")
        details = tuple(str(item) for item in self.details)
        accepted = self.status == "accepted"
        if accepted:
            if not isinstance(self.projection, ApprovedExecutionProjection):
                raise ValueError("accepted consumption requires one projection")
            if reasons:
                raise ValueError("accepted consumption cannot carry reason codes")
        else:
            if self.projection is not None:
                raise ValueError("non-accepted consumption cannot carry a projection")
            if not reasons:
                raise ValueError("non-accepted consumption requires reason codes")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "details", details)
        object.__setattr__(self, "complete", accepted)


def consume_approved_execution_projection(
    projection: object,
    *,
    expected_repository: str | None,
    expected_base_branch: str | None,
    expected_evaluated_repository_sha: str | None,
    expected_tested_repository_sha: str | None,
    expected_projection_id: str | None = None,
    expected_proposal_id: str | None = None,
    expected_approval_id: str | None = None,
) -> ProjectionConsumptionResult:
    """Check one supplied projection without expanding its authority.

    Repository and SHA expectations are explicit inputs. The function does not
    discover current state or re-evaluate approval policy. A successful result
    means only that the supplied projection is internally valid and matches the
    supplied bindings.
    """

    if not isinstance(projection, ApprovedExecutionProjection):
        return _result(
            "rejected",
            "projection.incomplete",
            "projection:invalid-type",
        )

    try:
        serialize_approved_execution_projection(projection)
    except (TypeError, ValueError) as exc:
        return _result(
            "rejected",
            "projection.incomplete",
            f"projection:{exc}",
        )

    required_expectations = {
        "repository": expected_repository,
        "base-branch": expected_base_branch,
        "evaluated-repository-sha": expected_evaluated_repository_sha,
        "tested-repository-sha": expected_tested_repository_sha,
    }
    missing = tuple(
        name
        for name, value in required_expectations.items()
        if not isinstance(value, str) or not value.strip()
    )
    if missing:
        return _result(
            "blocked",
            "projection.lookup-failed",
            *(f"expectation:{name}:missing" for name in missing),
        )

    if (
        projection.repository != expected_repository
        or projection.base_branch != expected_base_branch
    ):
        return _result(
            "rejected",
            "identity.quarantined",
            "repository-or-base-branch:mismatch",
        )

    if (
        projection.evaluated_repository_sha != expected_evaluated_repository_sha
        or projection.tested_repository_sha != expected_tested_repository_sha
    ):
        return _result(
            "stale",
            "validation.stale",
            "repository-sha:mismatch",
        )

    identity_expectations = {
        "projection-id": (expected_projection_id, projection.projection_id),
        "proposal-id": (expected_proposal_id, projection.proposal_id),
        "approval-id": (expected_approval_id, projection.approval_id),
    }
    mismatches = tuple(
        name
        for name, (expected, actual) in identity_expectations.items()
        if expected is not None and expected != actual
    )
    if mismatches:
        return _result(
            "needs-decision",
            "projection.lookup-failed",
            *(f"{name}:mismatch" for name in mismatches),
        )

    return ProjectionConsumptionResult("accepted", projection)


def _result(
    status: str,
    reason_code: str,
    *details: str,
) -> ProjectionConsumptionResult:
    return ProjectionConsumptionResult(
        status=status,
        projection=None,
        reason_codes=(reason_code,),
        details=tuple(details),
    )
