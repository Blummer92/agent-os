"""Validation-gate currentness classification before merge admission (#3269).

The #3269 defect, observed on PR #3267 at head
``7f7e801223a616fe8b62b7dddad48ed03daca893``:

```text
connector wrappers report Validation Gate run 37134507655 as pending, zero jobs
-> GitHub UI is simultaneously green
-> direct REST read shows the same run in_progress
-> commit check-runs already expose "Run aggregate validation: completed / failure"
-> a later job read exposes the aggregate failure and its logs
```

The high-level connector wrappers (``fetch_commit_workflow_runs`` /
``fetch_workflow_run_jobs``) can lag behind or return an incomplete snapshot
relative to GitHub's canonical run/check endpoints. A merge controller that
relies only on the wrapper can describe validation state incorrectly and may
stop on stale ``pending`` / empty-job evidence.

This module is a pure decision function in the established seam pattern
(#1237 ``post_selection_continuation.py``). It converges one wrapper snapshot
against canonical check-run evidence for the reacquired PR head SHA and
reports whether the observed gate state may be presented as current. It never
performs network I/O, never grants merge authority, and never bypasses branch
protection, required checks, or mandatory approvals. It deliberately creates no
poller, daemon, cache, second GitHub client, or synchronization worker: the
caller reacquires both snapshots at the decision boundary and reclassifies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Literal, Mapping, Sequence

VALIDATION_GATE_CURRENTNESS_SCHEMA_NAME = "agent-os-validation-gate-currentness"
VALIDATION_GATE_CURRENTNESS_SCHEMA_VERSION = "1.0"

MAX_CURRENTNESS_REASON_CODES = 32

_HEX40_LENGTH = 40
_FAILURE_CONCLUSIONS = frozenset({"failure", "timed_out", "action_required", "cancelled"})
_PENDING_RUN_STATES = frozenset({"pending", "queued"})


class WrapperRunState(str, Enum):
    """The workflow-run state vocabulary the connector wrapper may report."""

    PENDING = "pending"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class GateCurrentness(str, Enum):
    """Whether the observed validation-gate state may be presented as current."""

    #: The wrapper snapshot and canonical check-run evidence converge on the
    #: same run and head SHA with no contradiction. The observed state may be
    #: presented as current for the merge admission decision.
    CURRENT = "current"
    #: The wrapper reports the known-unreliable ``pending`` + zero-jobs shape
    #: and no canonical check-run evidence confirms or refutes it. The wrapper
    #: state must not be presented as current; the caller must obtain canonical
    #: check-run evidence for the head SHA first.
    CROSS_CHECK_REQUIRED = "cross-check-required"
    #: The snapshots conflict, or the wrapper run targets a different head SHA
    #: than the reacquired PR head. An explicit retry state: reacquire both
    #: snapshots and reclassify. Never a terminal conclusion.
    STALE_RETRY = "stale-retry"


class GateCurrentnessReason(str, Enum):
    """Finite reason codes explaining one deterministic classification."""

    #: Wrapper and canonical evidence agree on terminality and failure state.
    CONVERGED = "currentness.converged"
    #: Wrapper is substantive (jobs exist or run in progress) and canonical
    #: check-run evidence is absent, so nothing contradicts the wrapper.
    WRAPPER_SUBSTANTIVE_UNCONTESTED = "currentness.wrapper-substantive-uncontested"
    #: Wrapper is terminal and uncontested by any canonical check-run evidence.
    WRAPPER_TERMINAL_UNCONTESTED = "currentness.wrapper-terminal-uncontested"
    #: Wrapper reports pending + zero jobs and no canonical check-run evidence
    #: exists yet. The wrapper state must be cross-checked, never presented.
    WRAPPER_PENDING_ZERO_JOBS_UNCONFIRMED = "currentness.wrapper-pending-zero-jobs-unconfirmed"
    #: Canonical check-runs show terminal conclusions the wrapper does not
    #: reflect (the #3267 shape). The wrapper snapshot is stale.
    CANONICAL_TERMINAL_BEATS_WRAPPER = "currentness.canonical-terminal-beats-wrapper"
    #: Canonical check-runs show in-flight activity the pending wrapper missed.
    CANONICAL_AHEAD_OF_WRAPPER = "currentness.canonical-ahead-of-wrapper"
    #: Wrapper and canonical check-runs disagree on failure for the same head.
    CONCLUSION_DIVERGED = "currentness.conclusion-diverged"
    #: Wrapper claims completion while canonical check-runs are still running.
    CANONICAL_BEHIND_WRAPPER = "currentness.canonical-behind-wrapper"
    #: The wrapper run targets a different head SHA than the reacquired PR head.
    RUN_HEAD_SHA_STALE = "currentness.run-head-sha-stale"


@dataclass(frozen=True, slots=True, kw_only=True)
class WrapperRunSnapshot:
    """One connector-wrapper observation of the validation-gate workflow run."""

    run_id: int
    run_state: WrapperRunState
    run_conclusion: str | None
    job_count: int
    run_head_sha: str

    def __post_init__(self) -> None:
        if type(self.run_id) is not int or isinstance(self.run_id, bool) or self.run_id <= 0:
            raise ValueError("run_id must be a positive built-in integer")
        if type(self.run_state) is not WrapperRunState:
            raise TypeError("run_state must be an exact WrapperRunState")
        if self.run_conclusion is not None:
            if type(self.run_conclusion) is not str or not self.run_conclusion.strip():
                raise ValueError("run_conclusion must be non-blank text or None")
            if self.run_state is not WrapperRunState.COMPLETED:
                raise ValueError("a non-completed wrapper run must not carry a conclusion")
        if type(self.job_count) is not int or isinstance(self.job_count, bool) or self.job_count < 0:
            raise ValueError("job_count must be a non-negative built-in integer")
        _require_hex40(self.run_head_sha, "run_head_sha")


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalCheckRun:
    """One check-run mapping from the canonical check-runs endpoint."""

    name: str
    status: str
    conclusion: str | None
    head_sha: str

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("check-run name must be non-blank text")
        if self.status not in ("queued", "in_progress", "completed"):
            raise ValueError("check-run status must be queued, in_progress, or completed")
        if self.conclusion is not None:
            if type(self.conclusion) is not str or not self.conclusion.strip():
                raise ValueError("check-run conclusion must be non-blank text or None")
            if self.status != "completed":
                raise ValueError("a non-completed check run must not carry a conclusion")
        _require_hex40(self.head_sha, "head_sha")


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationGateCurrentnessResult:
    schema_name: str = VALIDATION_GATE_CURRENTNESS_SCHEMA_NAME
    schema_version: str = VALIDATION_GATE_CURRENTNESS_SCHEMA_VERSION
    status: GateCurrentness = GateCurrentness.STALE_RETRY
    result_id: str = ""
    repository: str = ""
    pull_request: int = 0
    head_sha: str = ""
    run_id: int = 0
    reason_codes: tuple[GateCurrentnessReason, ...] = ()
    authoritative: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != VALIDATION_GATE_CURRENTNESS_SCHEMA_NAME:
            raise ValueError("unsupported validation-gate currentness schema name")
        if self.schema_version != VALIDATION_GATE_CURRENTNESS_SCHEMA_VERSION:
            raise ValueError("unsupported validation-gate currentness schema version")
        if type(self.status) is not GateCurrentness:
            raise TypeError("status must be an exact GateCurrentness")
        if type(self.result_id) is not str or not self.result_id.startswith(
            "validation-gate-currentness:"
        ):
            raise ValueError("result_id must carry the validation-gate-currentness prefix")
        if type(self.repository) is not str or not self.repository.strip():
            raise ValueError("repository must be non-blank text")
        if type(self.pull_request) is not int or isinstance(self.pull_request, bool) or self.pull_request <= 0:
            raise ValueError("pull_request must be a positive built-in integer")
        _require_hex40(self.head_sha, "head_sha")
        if type(self.run_id) is not int or isinstance(self.run_id, bool) or self.run_id <= 0:
            raise ValueError("run_id must be a positive built-in integer")
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty exact tuple")
        if any(type(item) is not GateCurrentnessReason for item in self.reason_codes):
            raise TypeError("reason_codes contain an invalid value")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes must be unique")
        if tuple(sorted(item.value for item in self.reason_codes)) != tuple(
            item.value for item in self.reason_codes
        ):
            raise ValueError("reason_codes must be sorted")
        if len(self.reason_codes) > MAX_CURRENTNESS_REASON_CODES:
            raise ValueError("reason_codes exceeds the bounded vocabulary size")


def _require_hex40(value: object, name: str) -> None:
    if type(value) is not str or len(value) != _HEX40_LENGTH:
        raise ValueError(f"{name} must be an exact 40-character SHA")
    try:
        int(value, 16)
    except ValueError:
        raise ValueError(f"{name} must be lowercase hexadecimal") from None
    if any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be lowercase hexadecimal")


def _coerce_wrapper_run(value: object) -> WrapperRunSnapshot:
    if type(value) is not WrapperRunSnapshot:
        raise TypeError("wrapper_run must be an exact WrapperRunSnapshot")
    return value


def _coerce_check_runs(value: object) -> tuple[CanonicalCheckRun, ...]:
    if type(value) is not tuple:
        raise TypeError("canonical_check_runs must be an exact tuple")
    for item in value:
        if type(item) is not CanonicalCheckRun:
            raise TypeError("canonical_check_runs must contain exact CanonicalCheckRun items")
    return value


def classify_validation_gate_currentness(
    *,
    repository: object,
    pull_request: object,
    reacquired_head_sha: object,
    wrapper_run: object,
    canonical_check_runs: object,
) -> ValidationGateCurrentnessResult:
    """Converge a wrapper workflow-run snapshot against canonical check runs.

    ``reacquired_head_sha`` must be freshly read from canonical PR state at the
    merge admission decision boundary; it is never inherited from an earlier
    plan or cached read. ``canonical_check_runs`` are the check-run mappings
    from the canonical check-runs endpoint for that head SHA.
    """
    if type(repository) is not str or not repository.strip():
        raise ValueError("repository must be non-blank text")
    if type(pull_request) is not int or isinstance(pull_request, bool) or pull_request <= 0:
        raise ValueError("pull_request must be a positive built-in integer")
    _require_hex40(reacquired_head_sha, "reacquired_head_sha")
    head_sha = reacquired_head_sha
    run = _coerce_wrapper_run(wrapper_run)
    check_runs = _coerce_check_runs(canonical_check_runs)
    for check_run in check_runs:
        if check_run.head_sha != head_sha:
            raise ValueError("canonical check runs must all target the reacquired head SHA")

    if run.run_head_sha != head_sha:
        return _result(
            repository,
            pull_request,
            head_sha,
            run.run_id,
            GateCurrentness.STALE_RETRY,
            (GateCurrentnessReason.RUN_HEAD_SHA_STALE,),
        )

    pending_empty = run.run_state.value in _PENDING_RUN_STATES and run.job_count == 0
    canonical_terminal = [check_run for check_run in check_runs if check_run.status == "completed"]

    if pending_empty:
        # The #3267 shape: a pending wrapper with zero jobs is the known
        # unreliable snapshot. It is never presented as the current state.
        if canonical_terminal:
            return _result(
                repository,
                pull_request,
                head_sha,
                run.run_id,
                GateCurrentness.STALE_RETRY,
                (GateCurrentnessReason.CANONICAL_TERMINAL_BEATS_WRAPPER,),
            )
        if check_runs:
            return _result(
                repository,
                pull_request,
                head_sha,
                run.run_id,
                GateCurrentness.STALE_RETRY,
                (GateCurrentnessReason.CANONICAL_AHEAD_OF_WRAPPER,),
            )
        return _result(
            repository,
            pull_request,
            head_sha,
            run.run_id,
            GateCurrentness.CROSS_CHECK_REQUIRED,
            (GateCurrentnessReason.WRAPPER_PENDING_ZERO_JOBS_UNCONFIRMED,),
        )

    if run.run_state is WrapperRunState.COMPLETED:
        if not check_runs:
            return _result(
                repository,
                pull_request,
                head_sha,
                run.run_id,
                GateCurrentness.CURRENT,
                (GateCurrentnessReason.WRAPPER_TERMINAL_UNCONTESTED,),
            )
        if len(canonical_terminal) != len(check_runs):
            return _result(
                repository,
                pull_request,
                head_sha,
                run.run_id,
                GateCurrentness.STALE_RETRY,
                (GateCurrentnessReason.CANONICAL_BEHIND_WRAPPER,),
            )
        wrapper_failed = run.run_conclusion in _FAILURE_CONCLUSIONS
        canonical_failed = any(
            check_run.conclusion in _FAILURE_CONCLUSIONS for check_run in canonical_terminal
        )
        if wrapper_failed != canonical_failed:
            return _result(
                repository,
                pull_request,
                head_sha,
                run.run_id,
                GateCurrentness.STALE_RETRY,
                (GateCurrentnessReason.CONCLUSION_DIVERGED,),
            )
        return _result(
            repository,
            pull_request,
            head_sha,
            run.run_id,
            GateCurrentness.CURRENT,
            (GateCurrentnessReason.CONVERGED,),
        )

    # Wrapper is in progress (or queued with jobs): substantive evidence exists.
    if not check_runs:
        return _result(
            repository,
            pull_request,
            head_sha,
            run.run_id,
            GateCurrentness.CURRENT,
            (GateCurrentnessReason.WRAPPER_SUBSTANTIVE_UNCONTESTED,),
        )
    if canonical_terminal:
        return _result(
            repository,
            pull_request,
            head_sha,
            run.run_id,
            GateCurrentness.STALE_RETRY,
            (GateCurrentnessReason.CANONICAL_TERMINAL_BEATS_WRAPPER,),
        )
    return _result(
        repository,
        pull_request,
        head_sha,
        run.run_id,
        GateCurrentness.CURRENT,
        (GateCurrentnessReason.CONVERGED,),
    )


def _result(
    repository: str,
    pull_request: int,
    head_sha: str,
    run_id: int,
    status: GateCurrentness,
    reason_codes: tuple[GateCurrentnessReason, ...],
) -> ValidationGateCurrentnessResult:
    digest = sha256(
        (
            "agent-os-validation-gate-currentness:v1\0"
            f"{repository}\0{pull_request}\0{head_sha}\0{run_id}\0"
            f"{status.value}\0" + ",".join(sorted(reason.value for reason in reason_codes))
        ).encode("utf-8")
    ).hexdigest()
    return ValidationGateCurrentnessResult(
        status=status,
        result_id=f"validation-gate-currentness:{digest}",
        repository=repository,
        pull_request=pull_request,
        head_sha=head_sha,
        run_id=run_id,
        reason_codes=tuple(sorted(reason_codes, key=lambda reason: reason.value)),
    )


def serialize_validation_gate_currentness(result: ValidationGateCurrentnessResult) -> dict[str, object]:
    """Serialize one classification result with integrity binding."""
    if type(result) is not ValidationGateCurrentnessResult:
        raise TypeError("result must be an exact ValidationGateCurrentnessResult")
    payload = {
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "status": result.status.value,
        "repository": result.repository,
        "pull_request": result.pull_request,
        "head_sha": result.head_sha,
        "run_id": result.run_id,
        "reason_codes": [reason.value for reason in result.reason_codes],
        "authoritative": False,
        "merge_authorized": False,
        "side_effects_performed": False,
    }
    expected = _result(
        result.repository,
        result.pull_request,
        result.head_sha,
        result.run_id,
        result.status,
        result.reason_codes,
    ).result_id
    if result.result_id != expected:
        raise ValueError("validation-gate currentness result ID mismatch")
    serialized = dict(payload)
    serialized["result_id"] = result.result_id
    return serialized


def validation_gate_currentness_result_id(result: ValidationGateCurrentnessResult) -> str:
    return str(serialize_validation_gate_currentness(result)["result_id"])


__all__ = [
    "CanonicalCheckRun",
    "GateCurrentness",
    "GateCurrentnessReason",
    "VALIDATION_GATE_CURRENTNESS_SCHEMA_NAME",
    "VALIDATION_GATE_CURRENTNESS_SCHEMA_VERSION",
    "ValidationGateCurrentnessResult",
    "WrapperRunSnapshot",
    "WrapperRunState",
    "classify_validation_gate_currentness",
    "serialize_validation_gate_currentness",
    "validation_gate_currentness_result_id",
]
