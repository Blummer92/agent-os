"""Bounded governed recovery for action_required workflow runs with zero jobs (#2731).

A workflow run that concludes ``action_required`` without executing any job is
non-executed validation evidence: no validation ran, so the state is not a
candidate code-test failure and must not stall the batch. This module
distinguishes real executed failure from genuinely pending checks from
stale/non-executed evidence, and projects one bounded governed recovery that
re-invokes the existing exact-head validation authority on the same head SHA
without changing the candidate tree.

#3277 extends the same surface-neutral classifier so the live failed-repair
admission path (``admit_agent_os_failed_repair_tool``) can consume it: a
completed ``failure`` run with zero jobs is a pre-job / workflow-definition
failure, and a zero-job run with no conclusion needs a currentness cross-check.
Neither is a candidate code-test failure. ``project_zero_job_admission`` maps the
classification onto the bounded exact-head re-dispatch recovery without adding a
retry engine, state store, or any GitHub access.

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
_PRE_JOB_FAILURE_CONCLUSION = "failure"
_RECOVERY_OPERATION = "reinvoke-governed-exact-head-validation"


class ZeroJobRunDisposition(str, Enum):
    REAL_FAILURE = "real-failure"
    PENDING = "pending"
    STALE_NON_EXECUTED = "stale-non-executed"
    PRE_JOB_FAILURE = "pre-job-failure"
    CURRENTNESS_CROSS_CHECK_REQUIRED = "currentness-cross-check-required"
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
    if run.conclusion == _PRE_JOB_FAILURE_CONCLUSION:
        return "pre-job-failure"
    if run.conclusion is None:
        return "currentness-required"
    return "indeterminate"


def classify_workflow_run_evidence(
    runs: tuple[WorkflowRunConclusionEvidence, ...],
) -> ZeroJobRunDisposition:
    """Distinguish real failure, pending checks, and non-executed zero-job runs.

    Precedence is fail-closed: any executed failure dominates, then a pre-job /
    workflow-definition failure (re-dispatch cannot clear it), then genuinely
    pending/in-flight checks, then a zero-job run whose currentness is unproven,
    then stale/non-executed evidence. Runs that cannot be classified keep the
    caller on its existing behavior.
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
    if "pre-job-failure" in kinds:
        return ZeroJobRunDisposition.PRE_JOB_FAILURE
    if kinds & {"in-flight", "action-required-executed"}:
        return ZeroJobRunDisposition.PENDING
    if "currentness-required" in kinds:
        return ZeroJobRunDisposition.CURRENTNESS_CROSS_CHECK_REQUIRED
    if "stale-non-executed" in kinds:
        return ZeroJobRunDisposition.STALE_NON_EXECUTED
    return ZeroJobRunDisposition.INDETERMINATE


@dataclass(frozen=True, slots=True)
class ZeroJobAdmissionEvidence:
    """Caller-supplied run evidence bound to one PR head for live admission."""

    workflow_runs: tuple[WorkflowRunConclusionEvidence, ...]
    pull_request_number: int
    expected_head_sha: str
    current_head_sha: str
    recovery_attempts_used: int = 0
    expected_main_sha: str | None = None

    def __post_init__(self) -> None:
        if type(self.workflow_runs) is not tuple or any(
            type(run) is not WorkflowRunConclusionEvidence for run in self.workflow_runs
        ):
            raise TypeError(
                "workflow_runs must be an exact tuple of WorkflowRunConclusionEvidence values"
            )
        if type(self.pull_request_number) is not int or self.pull_request_number < 1:
            raise ValueError("pull_request_number must be a positive integer")
        for name in ("expected_head_sha", "current_head_sha"):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError(f"{name} is required")
        if self.expected_main_sha is not None and (
            type(self.expected_main_sha) is not str or not self.expected_main_sha
        ):
            raise ValueError("expected_main_sha must be a non-empty string or None")
        if (
            type(self.recovery_attempts_used) is not int
            or self.recovery_attempts_used < 0
        ):
            raise ValueError("recovery_attempts_used must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ZeroJobAdmissionProjection:
    """Pure projection of zero-job evidence for the live failed-repair path.

    ``gates_code_repair`` is true when the evidence is not an executed code-test
    failure, so the caller must not enter speculative CKR6 code repair.
    ``bounded_continuation`` is true only for the bounded exact-head re-dispatch,
    which is not a repository mutation.
    """

    disposition: ZeroJobRunDisposition
    gates_code_repair: bool
    bounded_continuation: bool
    reason_codes: tuple[str, ...]
    next_action: str | None
    recovery: ZeroJobRecoveryProjection | None = None


_NON_EXECUTED_DISPOSITIONS = frozenset(
    {
        ZeroJobRunDisposition.STALE_NON_EXECUTED,
        ZeroJobRunDisposition.PRE_JOB_FAILURE,
        ZeroJobRunDisposition.CURRENTNESS_CROSS_CHECK_REQUIRED,
        ZeroJobRunDisposition.PENDING,
    }
)


def project_zero_job_admission(
    evidence: ZeroJobAdmissionEvidence,
) -> ZeroJobAdmissionProjection:
    """Map zero-job run classification onto the bounded live admission action.

    Executed failures and unclassifiable runs add no gating. Every non-executed
    shape fails closed when the PR head moved. Only stale non-executed evidence
    projects the bounded exact-head re-dispatch, at most
    ``MAX_ZERO_JOB_RECOVERY_ATTEMPTS`` times. No tree-identical commit, retry
    engine, or state store is involved: the attempt count is caller-supplied.
    """
    if type(evidence) is not ZeroJobAdmissionEvidence:
        raise TypeError("evidence must be an exact ZeroJobAdmissionEvidence")
    disposition = classify_workflow_run_evidence(evidence.workflow_runs)
    if disposition not in _NON_EXECUTED_DISPOSITIONS:
        return ZeroJobAdmissionProjection(disposition, False, False, (), None)
    if evidence.expected_head_sha != evidence.current_head_sha:
        return ZeroJobAdmissionProjection(
            disposition,
            True,
            False,
            ("zero-job-evidence.head-moved",),
            "reacquire-current-head-and-exact-head-validation-evidence",
        )
    if disposition is ZeroJobRunDisposition.PRE_JOB_FAILURE:
        return ZeroJobAdmissionProjection(
            disposition,
            True,
            False,
            ("zero-job-run.pre-job-workflow-definition-failure",),
            "diagnose-pre-job-workflow-definition-failure",
        )
    if disposition is ZeroJobRunDisposition.CURRENTNESS_CROSS_CHECK_REQUIRED:
        return ZeroJobAdmissionProjection(
            disposition,
            True,
            False,
            ("zero-job-run.currentness-cross-check-required",),
            "cross-check-run-currentness-against-exact-head",
        )
    if disposition is ZeroJobRunDisposition.PENDING:
        return ZeroJobAdmissionProjection(
            disposition,
            True,
            False,
            ("zero-job-evidence.validation-run-pending",),
            "reacquire-pending-validation-evidence",
        )
    if evidence.recovery_attempts_used >= MAX_ZERO_JOB_RECOVERY_ATTEMPTS:
        return ZeroJobAdmissionProjection(
            disposition,
            True,
            False,
            (
                "zero-job-run.stale-non-executed",
                "zero-job-recovery.attempts-exhausted",
            ),
            "route-zero-job-recovery-exhaustion-to-canonical-owner",
        )
    recovery = ZeroJobRecoveryProjection(
        pull_request_number=evidence.pull_request_number,
        expected_head_sha=evidence.expected_head_sha,
        expected_main_sha=evidence.expected_main_sha,
        recovery_operation=_RECOVERY_OPERATION,
        attempt=evidence.recovery_attempts_used + 1,
        max_attempts=MAX_ZERO_JOB_RECOVERY_ATTEMPTS,
    )
    return ZeroJobAdmissionProjection(
        disposition,
        True,
        True,
        recovery.reason_codes,
        _RECOVERY_OPERATION,
        recovery,
    )
