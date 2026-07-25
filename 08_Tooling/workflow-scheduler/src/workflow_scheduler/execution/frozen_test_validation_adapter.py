"""WSC5B3B frozen-test validation adapter for the existing ValidationAdapter contract.

Executes only the exact frozen required-test argv sequences supplied by the
approved packet at construction time, through an injected bounded command
runner, and returns bounded canonical evidence. It owns no subprocess,
process group, Git worktree, lease, network, GitHub, workflow, persistence,
retry, or package-install behavior -- that authority belongs to the injected
runner and re-inspection hook, both supplied by the caller.

Test commands are treated as data (argv tuples), never as shell programs:
this module never parses command text, never invokes a shell, and never
discovers additional tests beyond the frozen set bound at construction.

``run_frozen_test_validation`` is the low-level, pure function that runs the
frozen required-test set at most once each and returns a rich, bounded,
immutable evidence record. ``FrozenTestValidationAdapter`` is a thin adapter
around it that satisfies
``workflow_scheduler.execution.single_issue_pilot.ValidationAdapter`` by
mapping that rich evidence down onto the narrower, frozen
``PilotValidationObservation`` contract; it invents no new fields there.
"""

from __future__ import annotations

import posixpath
import time
from dataclasses import dataclass
from typing import Callable, Literal, Protocol, runtime_checkable

from workflow_scheduler.execution.single_issue_pilot import (
    PilotValidationObservation,
    PilotValidationRequest,
)

MAX_REQUIRED_TEST_COMMANDS = 64
MAX_ARGV_ITEMS = 64
MAX_ARGUMENT_BYTES = 4096
MAX_COMMAND_BYTES = 65_536
MAX_AGGREGATE_ARGV_BYTES = 262_144
MAX_TEST_ID_LENGTH = 4096
MAX_OUTPUT_BYTES = 65_536
MAX_COMPLETED_TESTS = 64
MAX_CHANGED_PATHS = 256
MAX_PATH_LENGTH = 4096
MAX_REASON_LENGTH = 512

DEFAULT_PER_COMMAND_TIMEOUT_SECONDS = 30.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 300.0

CommandOutcome = Literal["succeeded", "failed", "timed-out", "cancelled", "unavailable"]

_RECOVERABLE_RUNNER_EXCEPTIONS = (TypeError, ValueError, RuntimeError, OSError)


class FrozenTestValidationError(ValueError):
    """Raised for malformed/oversized frozen test configuration.

    Always raised before any command runner invocation.
    """


CancellationCheck = Callable[[], bool]


@runtime_checkable
class ChangedPathsInspector(Protocol):
    """Report currently observed changed paths without owning a worktree."""

    def __call__(self) -> tuple[str, ...]: ...


# --------------------------------------------------------------------------
# Frozen command configuration (validated before any execution)
# --------------------------------------------------------------------------


def _validate_argv(argv: object, *, name: str) -> tuple[str, ...]:
    if isinstance(argv, (str, bytes)):
        raise FrozenTestValidationError(
            f"{name} must be a sequence of strings, not a single string or bytes"
        )
    if not isinstance(argv, (list, tuple)):
        raise FrozenTestValidationError(f"{name} must be a list or tuple of strings")
    items = tuple(argv)
    if len(items) == 0:
        raise FrozenTestValidationError(f"{name} must not be empty")
    if len(items) > MAX_ARGV_ITEMS:
        raise FrozenTestValidationError(f"{name} exceeds the bounded argument count")
    total_bytes = 0
    for item in items:
        if not isinstance(item, str):
            raise FrozenTestValidationError(f"every element of {name} must be a string")
        if not item:
            raise FrozenTestValidationError(f"elements of {name} must not be empty")
        if "\x00" in item:
            raise FrozenTestValidationError(f"elements of {name} must not contain NUL bytes")
        encoded_length = len(item.encode("utf-8"))
        if encoded_length > MAX_ARGUMENT_BYTES:
            raise FrozenTestValidationError(f"an element of {name} exceeds the bounded byte length")
        total_bytes += encoded_length
    if total_bytes > MAX_COMMAND_BYTES:
        raise FrozenTestValidationError(f"{name} exceeds the bounded aggregate byte length")
    return items


def _validate_test_id(test_id: object) -> str:
    if not isinstance(test_id, str) or not test_id:
        raise FrozenTestValidationError("test_id must be a non-empty string")
    if "\x00" in test_id:
        raise FrozenTestValidationError("test_id must not contain NUL bytes")
    if len(test_id) > MAX_TEST_ID_LENGTH:
        raise FrozenTestValidationError("test_id exceeds the bounded length")
    return test_id


@dataclass(frozen=True, slots=True, kw_only=True)
class FrozenTestCommand:
    """One canonical, frozen required-test identity bound to its argv."""

    test_id: str
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "test_id", _validate_test_id(self.test_id))
        object.__setattr__(self, "argv", _validate_argv(self.argv, name="argv"))


def _validate_frozen_commands(
    commands: object,
) -> tuple[FrozenTestCommand, ...]:
    if isinstance(commands, (str, bytes)) or not hasattr(commands, "__iter__"):
        raise FrozenTestValidationError("required_test_commands must be an iterable")
    items = tuple(commands)
    if len(items) == 0:
        raise FrozenTestValidationError("required_test_commands must not be empty")
    if len(items) > MAX_REQUIRED_TEST_COMMANDS:
        raise FrozenTestValidationError("required_test_commands exceeds the bounded command count")
    for item in items:
        if not isinstance(item, FrozenTestCommand):
            raise FrozenTestValidationError("every required test command must be a FrozenTestCommand")
    test_ids = tuple(item.test_id for item in items)
    if len(set(test_ids)) != len(test_ids):
        raise FrozenTestValidationError("required_test_commands contains a duplicate test_id")
    aggregate_bytes = sum(
        len(part.encode("utf-8")) for item in items for part in item.argv
    )
    if aggregate_bytes > MAX_AGGREGATE_ARGV_BYTES:
        raise FrozenTestValidationError(
            "required_test_commands exceeds the bounded aggregate argv byte length"
        )
    return items


# --------------------------------------------------------------------------
# Injected bounded command runner contract
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandRunRequest:
    """One bounded request to run exactly one frozen required-test command."""

    test_id: str
    argv: tuple[str, ...]
    timeout_seconds: float


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandRunObservation:
    """One bounded, caller-supplied observation of a single command attempt."""

    test_id: str
    outcome: CommandOutcome
    started: bool
    return_code: int | None = None
    stdout_text: str = ""
    stderr_text: str = ""
    changed_paths: tuple[str, ...] = ()
    reason: str = ""


@runtime_checkable
class BoundedCommandRunner(Protocol):
    """Run exactly one bounded command per invocation; never retried."""

    def run(self, request: CommandRunRequest) -> CommandRunObservation: ...


# --------------------------------------------------------------------------
# Bounded changed-path normalization and validation
# --------------------------------------------------------------------------


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if pattern == path:
            return True
        if pattern.endswith("/**") and path.startswith(pattern[:-2]):
            return True
        if pattern.endswith("*") and path.startswith(pattern[:-1]):
            return True
    return False


def _validate_changed_path(
    path: object,
    *,
    seen: set[str],
    allowed_files: tuple[str, ...],
    forbidden_paths: tuple[str, ...],
) -> str:
    if not isinstance(path, str) or not path:
        raise FrozenTestValidationError("changed path must be a non-empty string")
    if len(path) > MAX_PATH_LENGTH:
        raise FrozenTestValidationError("changed path exceeds the bounded length")
    if "\x00" in path:
        raise FrozenTestValidationError("changed path must not contain NUL bytes")
    if posixpath.isabs(path):
        raise FrozenTestValidationError("changed path must not be absolute")
    if any(part == ".." for part in path.split("/")):
        raise FrozenTestValidationError("changed path must not contain parent traversal")
    normalized = posixpath.normpath(path)
    if normalized != path or normalized in (".", ""):
        raise FrozenTestValidationError("changed path must already be in normalized form")
    if normalized in seen:
        raise FrozenTestValidationError("changed path is duplicated")
    if _matches_any(normalized, forbidden_paths):
        raise FrozenTestValidationError("changed path is forbidden")
    if not _matches_any(normalized, allowed_files):
        raise FrozenTestValidationError("changed path is outside the approved allowlist")
    seen.add(normalized)
    return normalized


# --------------------------------------------------------------------------
# Rich, bounded, immutable validation evidence
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class FrozenTestValidationResult:
    """Bounded, immutable evidence for exactly one frozen-test validation attempt."""

    attempted: bool
    passed: bool
    cancellation_requested: bool
    total_timed_out: bool
    completed_tests: tuple[str, ...]
    changed_paths: tuple[str, ...]
    command_outcomes: tuple[CommandRunObservation, ...]
    reason: str = ""


def _truncate(text: str, *, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def _bounded_reason(text: str) -> str:
    return text[:MAX_REASON_LENGTH]


def run_frozen_test_validation(
    required_test_commands: tuple[FrozenTestCommand, ...],
    supplied_required_tests: tuple[str, ...],
    *,
    runner: BoundedCommandRunner,
    allowed_files: tuple[str, ...],
    forbidden_paths: tuple[str, ...],
    per_command_timeout_seconds: float = DEFAULT_PER_COMMAND_TIMEOUT_SECONDS,
    total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
    max_output_bytes: int = MAX_OUTPUT_BYTES,
    changed_paths_inspector: ChangedPathsInspector | None = None,
    cancelled: CancellationCheck | None = None,
) -> FrozenTestValidationResult:
    """Run the frozen required-test set at most once each and return evidence.

    Every required command is attempted in frozen order, each exactly once,
    through the injected ``runner``. Timeout, cancellation, an unavailable
    or malformed runner observation, or an identity mismatch all fail
    closed: the command is simply not counted as completed rather than
    raising. Changed paths are normalized and validated -- against the
    caller-supplied allowlist/forbidden-path patterns -- only after every
    command has run, before a passing result can ever be emitted.
    """
    validated_commands = _validate_frozen_commands(required_test_commands)
    if not isinstance(supplied_required_tests, tuple) or any(
        not isinstance(item, str) for item in supplied_required_tests
    ):
        raise FrozenTestValidationError("supplied_required_tests must be a tuple of strings")
    if not isinstance(per_command_timeout_seconds, (int, float)) or per_command_timeout_seconds <= 0:
        raise FrozenTestValidationError("per_command_timeout_seconds must be a positive number")
    if not isinstance(total_timeout_seconds, (int, float)) or total_timeout_seconds <= 0:
        raise FrozenTestValidationError("total_timeout_seconds must be a positive number")
    if not isinstance(max_output_bytes, int) or max_output_bytes <= 0:
        raise FrozenTestValidationError("max_output_bytes must be a positive integer")

    frozen_test_ids = tuple(command.test_id for command in validated_commands)
    if supplied_required_tests != frozen_test_ids:
        return FrozenTestValidationResult(
            attempted=True,
            passed=False,
            cancellation_requested=False,
            total_timed_out=False,
            completed_tests=(),
            changed_paths=(),
            command_outcomes=(),
            reason=_bounded_reason(
                "supplied required tests do not match the frozen configured command identity/order"
            ),
        )

    outcomes: list[CommandRunObservation] = []
    completed: list[str] = []
    seen_test_ids: set[str] = set()
    cancellation_requested = False
    total_timed_out = False
    elapsed_total = 0.0

    for command in validated_commands:
        if cancelled is not None and cancelled():
            cancellation_requested = True
            outcomes.append(
                CommandRunObservation(
                    test_id=command.test_id,
                    outcome="cancelled",
                    started=False,
                    reason="cancellation requested before this command started",
                )
            )
            continue

        remaining_budget = total_timeout_seconds - elapsed_total
        if remaining_budget <= 0:
            total_timed_out = True
            outcomes.append(
                CommandRunObservation(
                    test_id=command.test_id,
                    outcome="timed-out",
                    started=False,
                    reason="total validation runtime budget was exhausted",
                )
            )
            continue

        effective_timeout = min(per_command_timeout_seconds, remaining_budget)
        request = CommandRunRequest(
            test_id=command.test_id, argv=command.argv, timeout_seconds=effective_timeout
        )
        started_at = time.monotonic()
        try:
            observation = runner.run(request)
        except _RECOVERABLE_RUNNER_EXCEPTIONS as exc:
            elapsed_total += time.monotonic() - started_at
            outcomes.append(
                CommandRunObservation(
                    test_id=command.test_id,
                    outcome="unavailable",
                    started=False,
                    reason=_bounded_reason(f"runner raised {type(exc).__name__}: {exc}"),
                )
            )
            continue
        elapsed = time.monotonic() - started_at
        elapsed_total += elapsed

        if not isinstance(observation, CommandRunObservation):
            outcomes.append(
                CommandRunObservation(
                    test_id=command.test_id,
                    outcome="failed",
                    started=False,
                    reason="runner returned a malformed observation",
                )
            )
            continue
        if observation.test_id != command.test_id:
            outcomes.append(
                CommandRunObservation(
                    test_id=command.test_id,
                    outcome="failed",
                    started=observation.started,
                    reason="runner observation identity did not match the requested command",
                )
            )
            continue
        if observation.test_id in seen_test_ids:
            outcomes.append(
                CommandRunObservation(
                    test_id=command.test_id,
                    outcome="failed",
                    started=observation.started,
                    reason="duplicate observation identity",
                )
            )
            continue

        outcome = observation.outcome
        if elapsed > effective_timeout and outcome not in ("timed-out", "cancelled"):
            outcome = "timed-out"

        stdout_text, stdout_truncated = _truncate(
            observation.stdout_text, max_bytes=max_output_bytes
        )
        stderr_text, stderr_truncated = _truncate(
            observation.stderr_text, max_bytes=max_output_bytes
        )
        reason = observation.reason
        if stdout_truncated or stderr_truncated:
            reason = _bounded_reason(f"{reason} output-truncated".strip())

        bounded_observation = CommandRunObservation(
            test_id=observation.test_id,
            outcome=outcome,
            started=observation.started,
            return_code=observation.return_code,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            changed_paths=tuple(observation.changed_paths),
            reason=reason,
        )
        outcomes.append(bounded_observation)
        seen_test_ids.add(observation.test_id)
        if outcome == "succeeded":
            completed.append(command.test_id)

    if len(completed) > MAX_COMPLETED_TESTS:
        return FrozenTestValidationResult(
            attempted=True,
            passed=False,
            cancellation_requested=cancellation_requested,
            total_timed_out=total_timed_out,
            completed_tests=(),
            changed_paths=(),
            command_outcomes=tuple(outcomes),
            reason=_bounded_reason("completed test count exceeds the bounded observation limit"),
        )

    all_required_completed = set(frozen_test_ids) <= set(completed)

    changed_paths: tuple[str, ...] = ()
    path_error: str | None = None
    if all_required_completed and not cancellation_requested and not total_timed_out:
        seen_paths: set[str] = set()
        ordered_raw_paths: list[str] = []
        for outcome_item in outcomes:
            ordered_raw_paths.extend(outcome_item.changed_paths)
        if changed_paths_inspector is not None:
            ordered_raw_paths.extend(changed_paths_inspector())
        if len(ordered_raw_paths) > MAX_CHANGED_PATHS:
            path_error = "changed paths exceed the bounded count"
        else:
            validated_paths: list[str] = []
            try:
                for raw_path in ordered_raw_paths:
                    validated_paths.append(
                        _validate_changed_path(
                            raw_path,
                            seen=seen_paths,
                            allowed_files=allowed_files,
                            forbidden_paths=forbidden_paths,
                        )
                    )
            except FrozenTestValidationError as exc:
                path_error = str(exc)
            else:
                changed_paths = tuple(validated_paths)

    passed = bool(all_required_completed and path_error is None and not cancellation_requested and not total_timed_out)

    reason = ""
    if not all_required_completed:
        missing = tuple(test_id for test_id in frozen_test_ids if test_id not in completed)
        reason = _bounded_reason("required tests did not complete: " + ",".join(missing))
    elif cancellation_requested:
        reason = _bounded_reason("validation was cancelled before all required tests completed")
    elif total_timed_out:
        reason = _bounded_reason("total validation runtime budget was exhausted")
    elif path_error is not None:
        reason = _bounded_reason(path_error)

    return FrozenTestValidationResult(
        attempted=True,
        passed=passed,
        cancellation_requested=cancellation_requested,
        total_timed_out=total_timed_out,
        completed_tests=tuple(completed) if passed else (),
        changed_paths=changed_paths,
        command_outcomes=tuple(outcomes),
        reason=reason,
    )


# --------------------------------------------------------------------------
# ValidationAdapter-conformant adapter
# --------------------------------------------------------------------------


def _to_pilot_validation_observation(
    result: FrozenTestValidationResult,
) -> PilotValidationObservation:
    return PilotValidationObservation(
        attempted=result.attempted,
        passed=result.passed,
        completed_tests=result.completed_tests,
        changed_paths=result.changed_paths,
        reason=result.reason,
    )


class FrozenTestValidationAdapter:
    """A ``ValidationAdapter`` backed by a frozen, caller-supplied test set."""

    def __init__(
        self,
        *,
        required_test_commands: tuple[FrozenTestCommand, ...],
        runner: BoundedCommandRunner,
        allowed_files: tuple[str, ...] = (),
        forbidden_paths: tuple[str, ...] = (),
        per_command_timeout_seconds: float = DEFAULT_PER_COMMAND_TIMEOUT_SECONDS,
        total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
        changed_paths_inspector: ChangedPathsInspector | None = None,
        cancelled: CancellationCheck | None = None,
    ) -> None:
        self._required_test_commands = _validate_frozen_commands(required_test_commands)
        if not isinstance(runner, BoundedCommandRunner):
            raise FrozenTestValidationError("runner does not satisfy the BoundedCommandRunner protocol")
        self._runner = runner
        self._allowed_files = tuple(allowed_files)
        self._forbidden_paths = tuple(forbidden_paths)
        self._per_command_timeout_seconds = per_command_timeout_seconds
        self._total_timeout_seconds = total_timeout_seconds
        self._max_output_bytes = max_output_bytes
        self._changed_paths_inspector = changed_paths_inspector
        self._cancelled = cancelled
        self._attempted = False
        self.last_result: FrozenTestValidationResult | None = None

    def validate(self, request: PilotValidationRequest) -> PilotValidationObservation:
        if not isinstance(request, PilotValidationRequest):
            raise TypeError("request must be PilotValidationRequest")
        if self._attempted:
            raise RuntimeError("the frozen-test validation adapter may run at most once")
        self._attempted = True
        result = run_frozen_test_validation(
            self._required_test_commands,
            tuple(request.required_tests),
            runner=self._runner,
            allowed_files=self._allowed_files,
            forbidden_paths=self._forbidden_paths,
            per_command_timeout_seconds=self._per_command_timeout_seconds,
            total_timeout_seconds=self._total_timeout_seconds,
            max_output_bytes=self._max_output_bytes,
            changed_paths_inspector=self._changed_paths_inspector,
            cancelled=self._cancelled,
        )
        self.last_result = result
        return _to_pilot_validation_observation(result)
