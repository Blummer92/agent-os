"""Bounded governed recovery for action_required workflow runs with zero jobs (#2731).

A workflow run that concludes ``action_required`` without executing any job is
non-executed validation evidence: no validation ran, so the state is not a
candidate code-test failure and must not stall the batch. This module
distinguishes real executed failure from genuinely pending checks from
stale/non-executed evidence, and projects one bounded governed recovery that
re-invokes the existing exact-head validation authority on the same head SHA
without changing the candidate tree.

The module performs no GitHub reads or writes and grants no merge, closure,
branch, or workflow authority. Required validation is never weakened: fresh
exact-head ``passed`` evidence is still required before any merge admission,
and the recovery fails closed when the PR head moves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

MAX_ZERO_JOB_RECOVERY_ATTEMPTS = 2

_STALE_CONCLUSION = "action_required"
_EXECUTED_FAILURE_CONCLUSIONS = frozenset(
    {"failure", "timed_out", "startup_failure", "cancelled"}
)
_EXECUTED_SUCCESS_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})
_RECOVERY_OPERATION = "reinvoke-governed-exact-head-validation"


class ZeroJobRunDisposition(str, Enum):
    REAL_FAILURE = "real-failure"
    PENDING = "pending"
    STALE_NON_EXECUTED = "stale-non-executed"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class WorkflowRunConclusionEvidence:
    """One workflow run's terminal signal as reported by the provider."""

    run_id: int
    conclusion: str | None
    job_count: int

    def __post_init__(self) -> None:
        if type(self.run_id) is not int or self.run_id < 1:
            raise ValueError("run_id must be a positive integer")
        if self.conclusion is not None and (
            type(self.conclusion) is not str or not self.conclusion.strip()
        ):
            raise ValueError("conclusion must be a non-empty string or None")
        if type(self.job_count) is not int or self.job_count < 0:
            raise ValueError("job_count must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ZeroJobRecoveryProjection:
    """Bounded governed recovery emitted to the existing validation owner."""

    pull_request_number: int
    expected_head_sha: str
    expected_main_sha: str | None
    recovery_operation: Literal["reinvoke-governed-exact-head-validation"]
    attempt: int
    max_attempts: int
    reason_codes: tuple[str, ...] = (
        "zero-job-run.stale-non-executed",
        "zero-job-recovery.reinvoke-exact-head-validation",
    )
    tree_change_permitted: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.pull_request_number) is not int or self.pull_request_number < 1:
            raise ValueError("pull_request_number must be a positive integer")
        if type(self.expected_head_sha) is not str or not self.expected_head_sha:
            raise ValueError("expected_head_sha is required")
        if self.expected_main_sha is not None and (
            type(self.expected_main_sha) is not str or not self.expected_main_sha
        ):
            raise ValueError("expected_main_sha must be a non-empty string or None")
        if self.recovery_operation != _RECOVERY_OPERATION:
            raise ValueError("recovery_operation is outside the governed vocabulary")
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("attempt must be a positive integer")
        if self.max_attempts != MAX_ZERO_JOB_RECOVERY_ATTEMPTS:
            raise ValueError("max_attempts must match the governed bound")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str or not code for code in self.reason_codes
        ):
            raise TypeError("reason_codes must be an exact tuple of non-empty strings")
        if self.tree_change_permitted or self.side_effects_performed:
            raise ValueError("recovery projection cannot permit tree changes or side effects")


def _classify_run(run: WorkflowRunConclusionEvidence) -> str:
    if run.job_count > 0:
        if run.conclusion in _EXECUTED_FAILURE_CONCLUSIONS:
            return "failed-executed"
        if run.conclusion in _EXECUTED_SUCCESS_CONCLUSIONS:
            return "passed-executed"
        if run.conclusion == _STALE_CONCLUSION:
            return "action-required-executed"
        if run.conclusion is None:
            return "in-flight"
        return "indeterminate"
    if run.conclusion == _STALE_CONCLUSION:
        return "stale-non-executed"
    if run.conclusion is None:
        return "pending"
    return "indeterminate"


def classify_workflow_run_evidence(
    runs: tuple[WorkflowRunConclusionEvidence, ...],
) -> ZeroJobRunDisposition:
    """Distinguish real failure, pending checks, and stale non-executed runs.

    Precedence is fail-closed: any executed failure dominates, then genuinely
    pending/in-flight checks, then stale/non-executed evidence. Runs that
    cannot be classified keep the caller on its existing behavior.
    """
    if type(runs) is not tuple or any(
        type(run) is not WorkflowRunConclusionEvidence for run in runs
    ):
        raise TypeError(
            "runs must be an exact tuple of WorkflowRunConclusionEvidence values"
        )
    kinds = {_classify_run(run) for run in runs}
    if "failed-executed" in kinds:
        return ZeroJobRunDisposition.REAL_FAILURE
    if kinds & {"in-flight", "pending", "action-required-executed"}:
        return ZeroJobRunDisposition.PENDING
    if "stale-non-executed" in kinds:
        return ZeroJobRunDisposition.STALE_NON_EXECUTED
    return ZeroJobRunDisposition.INDETERMINATE
