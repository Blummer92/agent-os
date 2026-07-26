"""Bounded frozen-test validation for the existing ValidationAdapter contract.

Commands are immutable argv data supplied at construction time and are executed
only through an injected runner. This module owns no external execution,
worktree, network, persistence, retry, publication, or GitHub authority.
"""

from __future__ import annotations

import math
import ntpath
import posixpath
import time
from dataclasses import dataclass, field
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
_SUPPORTED_OUTCOMES = frozenset({"succeeded", "failed", "timed-out", "cancelled", "unavailable"})
_RECOVERABLE_RUNNER_EXCEPTIONS = (TypeError, ValueError, RuntimeError, OSError)


class FrozenTestValidationError(ValueError):
    """Raised for malformed or oversized frozen validation configuration."""


CancellationCheck = Callable[[], bool]


@runtime_checkable
class ChangedPathsInspector(Protocol):
    """Report currently observed changed paths without owning a worktree."""

    def __call__(self) -> tuple[str, ...]: ...


def _validate_argv(argv: object, *, name: str) -> tuple[str, ...]:
    if isinstance(argv, (str, bytes)):
        raise FrozenTestValidationError(
            f"{name} must be a sequence of strings, not a single string or bytes"
        )
    if not isinstance(argv, (list, tuple)):
        raise FrozenTestValidationError(f"{name} must be a list or tuple of strings")
    items = tuple(argv)
    if not items:
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
    """One canonical required-test identity bound to its exact argv."""

    test_id: str
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "test_id", _validate_test_id(self.test_id))
        object.__setattr__(self, "argv", _validate_argv(self.argv, name="argv"))


def _validate_frozen_commands(commands: object) -> tuple[FrozenTestCommand, ...]:
    if isinstance(commands, (str, bytes)) or not hasattr(commands, "__iter__"):
        raise FrozenTestValidationError("required_test_commands must be an iterable")
    items = tuple(commands)
    if not items:
        raise FrozenTestValidationError("required_test_commands must not be empty")
    if len(items) > MAX_REQUIRED_TEST_COMMANDS:
        raise FrozenTestValidationError("required_test_commands exceeds the bounded command count")
    if any(not isinstance(item, FrozenTestCommand) for item in items):
        raise FrozenTestValidationError("every required test command must be a FrozenTestCommand")
    test_ids = tuple(item.test_id for item in items)
    if len(set(test_ids)) != len(test_ids):
        raise FrozenTestValidationError("required_test_commands contains a duplicate test_id")
    aggregate_bytes = sum(len(part.encode("utf-8")) for item in items for part in item.argv)
    if aggregate_bytes > MAX_AGGREGATE_ARGV_BYTES:
        raise FrozenTestValidationError(
            "required_test_commands exceeds the bounded aggregate argv byte length"
        )
    return items


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandRunRequest:
    """One bounded request to run one exact frozen command."""

    test_id: str
    argv: tuple[str, ...]
    timeout_seconds: float


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandRunObservation:
    """One caller-supplied observation of a command attempt."""

    test_id: str
    outcome: CommandOutcome
    started: bool
    return_code: int | None = None
    stdout_text: str = field(default="", repr=False)
    stderr_text: str = field(default="", repr=False)
    changed_paths: tuple[str, ...] = ()
    reason: str = field(default="", repr=False)


@runtime_checkable
class BoundedCommandRunner(Protocol):
    """Run exactly one bounded command per invocation; never retried."""

    def run(self, request: CommandRunRequest) -> CommandRunObservation: ...


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if pattern == path:
            return True
        if pattern.endswith("/**") and path.startswith(pattern[:-2]):
            return True
        if pattern.endswith("*") and path.startswith(pattern[:-1]):
            return True
    return False


def _validate_patterns(patterns: object, *, name: str) -> tuple[str, ...]:
    if isinstance(patterns, (str, bytes)) or not isinstance(patterns, (list, tuple)):
        raise FrozenTestValidationError(f"{name} must be a list or tuple of strings")
    items = tuple(patterns)
    if len(items) > MAX_CHANGED_PATHS:
        raise FrozenTestValidationError(f"{name} exceeds the bounded pattern count")
    for item in items:
        if not isinstance(item, str) or not item:
            raise FrozenTestValidationError(f"every element of {name} must be a non-empty string")
        if "\x00" in item or len(item) > MAX_PATH_LENGTH:
            raise FrozenTestValidationError(f"an element of {name} is malformed or oversized")
    return items


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
    if "\\" in path:
        raise FrozenTestValidationError("changed path must use canonical forward slashes")
    drive, _ = ntpath.splitdrive(path)
    if drive or ntpath.isabs(path) or posixpath.isabs(path):
        raise FrozenTestValidationError("changed path must not be absolute or drive-qualified")
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


@dataclass(frozen=True, slots=True, kw_only=True)
class FrozenTestValidationResult:
    """Bounded immutable evidence for one frozen-test validation attempt."""

    attempted: bool
    passed: bool
    cancellation_requested: bool
    total_timed_out: bool
    completed_tests: tuple[str, ...]
    changed_paths: tuple[str, ...]
    command_outcomes: tuple[CommandRunObservation, ...] = field(repr=False)
    reason: str = field(default="", repr=False)


def _normalize_utf8(text: str) -> tuple[str, bytes]:
    encoded = text.encode("utf-8", errors="replace")
    return encoded.decode("utf-8", errors="strict"), encoded


def _truncate(text: str, *, max_bytes: int) -> tuple[str, int, bool]:
    normalized, encoded = _normalize_utf8(text)
    if len(encoded) <= max_bytes:
        return normalized, len(encoded), normalized != text
    bounded = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return bounded, len(bounded.encode("utf-8")), True


def _truncate_output_pair(stdout: str, stderr: str, *, max_bytes: int) -> tuple[str, str, bool]:
    """Retain at most max_bytes total across normalized stdout then stderr."""

    bounded_stdout, used, stdout_changed = _truncate(stdout, max_bytes=max_bytes)
    remaining = max(0, max_bytes - used)
    bounded_stderr, _, stderr_changed = _truncate(stderr, max_bytes=remaining)
    if remaining == 0 and stderr:
        stderr_changed = True
    return bounded_stdout, bounded_stderr, stdout_changed or stderr_changed


def _bounded_reason(text: str) -> str:
    normalized, _ = _normalize_utf8(text)
    return normalized[:MAX_REASON_LENGTH]


def _validate_positive_bound(value: object, *, name: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FrozenTestValidationError(f"{name} must be a positive finite number")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0 or numeric > maximum:
        raise FrozenTestValidationError(f"{name} must be positive, finite, and no greater than {maximum}")
    return numeric


def _validate_output_bound(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FrozenTestValidationError("max_output_bytes must be a positive integer")
    if value <= 0 or value > MAX_OUTPUT_BYTES:
        raise FrozenTestValidationError(
            f"max_output_bytes must be positive and no greater than {MAX_OUTPUT_BYTES}"
        )
    return value


def _collect_changed_paths(value: object, *, maximum: int) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not hasattr(value, "__iter__"):
        raise FrozenTestValidationError("changed_paths must be a bounded iterable of strings")
    collected: list[str] = []
    try:
        for item in value:  # type: ignore[union-attr]
            if len(collected) >= maximum:
                raise FrozenTestValidationError("changed paths exceed the bounded count")
            if not isinstance(item, str):
                raise FrozenTestValidationError("every changed path must be a string")
            collected.append(item)
    except _RECOVERABLE_RUNNER_EXCEPTIONS as exc:
        if isinstance(exc, FrozenTestValidationError):
            raise
        raise FrozenTestValidationError(
            _bounded_reason(f"changed path evidence failed: {type(exc).__name__}: {exc}")
        ) from exc
    return tuple(collected)


def _failed_observation(test_id: str, reason: str, *, started: bool = False) -> CommandRunObservation:
    return CommandRunObservation(
        test_id=test_id,
        outcome="failed",
        started=started,
        reason=_bounded_reason(reason),
    )


def _normalize_observation(
    observation: object,
    *,
    command: FrozenTestCommand,
    elapsed: float,
    effective_timeout: float,
    max_output_bytes: int,
) -> CommandRunObservation:
    if not isinstance(observation, CommandRunObservation):
        return _failed_observation(command.test_id, "runner returned a malformed observation")

    started = observation.started if type(observation.started) is bool else False
    try:
        observed_test_id = _validate_test_id(observation.test_id)
    except FrozenTestValidationError:
        return _failed_observation(command.test_id, "runner observation test_id was malformed", started=started)
    if observed_test_id != command.test_id:
        return _failed_observation(
            command.test_id,
            "runner observation identity did not match the requested command",
            started=started,
        )
    if not isinstance(observation.outcome, str) or observation.outcome not in _SUPPORTED_OUTCOMES:
        return _failed_observation(command.test_id, "runner observation outcome was unsupported", started=started)
    if type(observation.started) is not bool:
        return _failed_observation(command.test_id, "runner observation started flag was malformed")
    if observation.return_code is not None and type(observation.return_code) is not int:
        return _failed_observation(command.test_id, "runner observation return code was malformed", started=started)
    if not isinstance(observation.stdout_text, str):
        return _failed_observation(command.test_id, "runner observation stdout was malformed", started=started)
    if not isinstance(observation.stderr_text, str):
        return _failed_observation(command.test_id, "runner observation stderr was malformed", started=started)
    if not isinstance(observation.reason, str):
        return _failed_observation(command.test_id, "runner observation reason was malformed", started=started)
    try:
        changed_paths = _collect_changed_paths(observation.changed_paths, maximum=MAX_CHANGED_PATHS)
    except FrozenTestValidationError as exc:
        return _failed_observation(command.test_id, str(exc), started=started)

    outcome: CommandOutcome = observation.outcome
    reason = observation.reason
    if outcome == "succeeded" and (observation.started is not True or observation.return_code != 0):
        outcome = "failed"
        reason = "successful runner observation requires started=True and return_code=0"
    elif observation.started is False and observation.return_code is not None:
        outcome = "failed"
        reason = "runner observation reported a return code without starting"
    if elapsed > effective_timeout and outcome not in ("timed-out", "cancelled"):
        outcome = "timed-out"
        reason = "command exceeded its effective timeout"

    stdout_text, stderr_text, output_changed = _truncate_output_pair(
        observation.stdout_text,
        observation.stderr_text,
        max_bytes=max_output_bytes,
    )
    if output_changed:
        reason = f"{reason} output-normalized-or-truncated".strip()

    return CommandRunObservation(
        test_id=command.test_id,
        outcome=outcome,
        started=observation.started,
        return_code=observation.return_code,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        changed_paths=changed_paths,
        reason=_bounded_reason(reason),
    )


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
    """Run the exact frozen required-test set at most once and return bounded evidence."""

    commands = _validate_frozen_commands(required_test_commands)
    if not isinstance(supplied_required_tests, tuple) or any(
        not isinstance(item, str) for item in supplied_required_tests
    ):
        raise FrozenTestValidationError("supplied_required_tests must be a tuple of strings")
    per_command_timeout = _validate_positive_bound(
        per_command_timeout_seconds,
        name="per_command_timeout_seconds",
        maximum=DEFAULT_PER_COMMAND_TIMEOUT_SECONDS,
    )
    total_timeout = _validate_positive_bound(
        total_timeout_seconds,
        name="total_timeout_seconds",
        maximum=DEFAULT_TOTAL_TIMEOUT_SECONDS,
    )
    output_limit = _validate_output_bound(max_output_bytes)
    allowed = _validate_patterns(allowed_files, name="allowed_files")
    forbidden = _validate_patterns(forbidden_paths, name="forbidden_paths")

    deadline = time.monotonic() + total_timeout

    def remaining() -> float:
        return deadline - time.monotonic()

    frozen_test_ids = tuple(command.test_id for command in commands)
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
    cancellation_requested = False
    total_timed_out = False
    hook_error: str | None = None

    for command in commands:
        if remaining() <= 0:
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

        if cancellation_requested:
            outcomes.append(
                CommandRunObservation(
                    test_id=command.test_id,
                    outcome="cancelled",
                    started=False,
                    reason="cancellation requested before this command started",
                )
            )
            continue

        if cancelled is not None:
            try:
                cancellation_value = cancelled()
            except _RECOVERABLE_RUNNER_EXCEPTIONS as exc:
                hook_error = _bounded_reason(
                    f"cancellation check failed: {type(exc).__name__}: {exc}"
                )
                outcomes.append(
                    CommandRunObservation(
                        test_id=command.test_id,
                        outcome="unavailable",
                        started=False,
                        reason=hook_error,
                    )
                )
                break
            if remaining() <= 0:
                total_timed_out = True
                outcomes.append(
                    CommandRunObservation(
                        test_id=command.test_id,
                        outcome="timed-out",
                        started=False,
                        reason="total validation runtime budget was exhausted during cancellation check",
                    )
                )
                continue
            if type(cancellation_value) is not bool:
                hook_error = "cancellation check returned a non-boolean value"
                outcomes.append(
                    CommandRunObservation(
                        test_id=command.test_id,
                        outcome="unavailable",
                        started=False,
                        reason=hook_error,
                    )
                )
                break
            if cancellation_value:
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

        remaining_budget = remaining()
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

        effective_timeout = min(per_command_timeout, remaining_budget)
        request = CommandRunRequest(
            test_id=command.test_id,
            argv=command.argv,
            timeout_seconds=effective_timeout,
        )
        started_at = time.monotonic()
        try:
            raw_observation = runner.run(request)
        except _RECOVERABLE_RUNNER_EXCEPTIONS as exc:
            elapsed = time.monotonic() - started_at
            if elapsed > effective_timeout or remaining() <= 0:
                total_timed_out = remaining() <= 0
                normalized = CommandRunObservation(
                    test_id=command.test_id,
                    outcome="timed-out",
                    started=False,
                    reason="command exceeded its effective timeout",
                )
            else:
                normalized = CommandRunObservation(
                    test_id=command.test_id,
                    outcome="unavailable",
                    started=False,
                    reason=_bounded_reason(f"runner raised {type(exc).__name__}: {exc}"),
                )
        else:
            elapsed = time.monotonic() - started_at
            normalized = _normalize_observation(
                raw_observation,
                command=command,
                elapsed=elapsed,
                effective_timeout=effective_timeout,
                max_output_bytes=output_limit,
            )
            if remaining() <= 0:
                total_timed_out = True
                normalized = CommandRunObservation(
                    test_id=command.test_id,
                    outcome="timed-out",
                    started=normalized.started,
                    return_code=normalized.return_code,
                    stdout_text=normalized.stdout_text,
                    stderr_text=normalized.stderr_text,
                    changed_paths=normalized.changed_paths,
                    reason="total validation runtime budget was exhausted",
                )

        outcomes.append(normalized)
        if normalized.outcome == "succeeded":
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
            reason="completed test count exceeds the bounded observation limit",
        )

    all_required_completed = tuple(completed) == frozen_test_ids
    changed_paths: tuple[str, ...] = ()
    path_error: str | None = None

    if all_required_completed and not cancellation_requested and not total_timed_out and hook_error is None:
        raw_paths: list[str] = []
        try:
            for outcome_item in outcomes:
                for raw_path in outcome_item.changed_paths:
                    if remaining() <= 0:
                        raise TimeoutError("total validation runtime budget was exhausted during path collection")
                    if len(raw_paths) >= MAX_CHANGED_PATHS:
                        raise FrozenTestValidationError("changed paths exceed the bounded count")
                    raw_paths.append(raw_path)
            if changed_paths_inspector is not None:
                if remaining() <= 0:
                    raise TimeoutError("total validation runtime budget was exhausted before path inspection")
                inspected = changed_paths_inspector()
                if remaining() <= 0:
                    raise TimeoutError("total validation runtime budget was exhausted during path inspection")
                raw_paths.extend(
                    _collect_changed_paths(inspected, maximum=MAX_CHANGED_PATHS - len(raw_paths))
                )
        except TimeoutError as exc:
            total_timed_out = True
            path_error = str(exc)
        except _RECOVERABLE_RUNNER_EXCEPTIONS as exc:
            path_error = _bounded_reason(
                str(exc)
                if isinstance(exc, FrozenTestValidationError)
                else f"changed paths inspector failed: {type(exc).__name__}: {exc}"
            )
        else:
            seen_paths: set[str] = set()
            validated_paths: list[str] = []
            try:
                for raw_path in raw_paths:
                    if remaining() <= 0:
                        raise TimeoutError(
                            "total validation runtime budget was exhausted during path validation"
                        )
                    validated_paths.append(
                        _validate_changed_path(
                            raw_path,
                            seen=seen_paths,
                            allowed_files=allowed,
                            forbidden_paths=forbidden,
                        )
                    )
            except TimeoutError as exc:
                total_timed_out = True
                path_error = str(exc)
            except FrozenTestValidationError as exc:
                path_error = _bounded_reason(str(exc))
            else:
                changed_paths = tuple(validated_paths)

    if remaining() <= 0:
        total_timed_out = True

    passed = bool(
        all_required_completed
        and hook_error is None
        and path_error is None
        and not cancellation_requested
        and not total_timed_out
    )

    if hook_error is not None:
        reason = hook_error
    elif total_timed_out:
        reason = _bounded_reason(path_error or "total validation runtime budget was exhausted")
    elif not all_required_completed:
        missing = tuple(test_id for test_id in frozen_test_ids if test_id not in completed)
        reason = _bounded_reason("required tests did not complete: " + ",".join(missing))
    elif cancellation_requested:
        reason = "validation was cancelled before all required tests completed"
    elif path_error is not None:
        reason = _bounded_reason(path_error)
    else:
        reason = ""

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


def _public_validation_reason(result: FrozenTestValidationResult) -> str:
    """Return one stable non-sensitive classification for the public observation."""

    diagnostic = result.reason
    command_reasons = tuple(item.reason for item in result.command_outcomes)

    if result.passed:
        return ""
    if diagnostic.startswith("cancellation check failed:"):
        return "cancellation check failed"
    if diagnostic == "cancellation check returned a non-boolean value":
        return "cancellation check returned invalid evidence"
    if diagnostic.startswith("changed paths inspector failed:"):
        return "changed paths inspector failed"
    if diagnostic.startswith("changed path evidence failed:") or any(
        reason.startswith("changed path evidence failed:") for reason in command_reasons
    ):
        return "changed path evidence failed"
    if result.total_timed_out:
        return "validation timed out"
    if result.cancellation_requested:
        return "validation cancelled"
    if diagnostic.startswith("supplied required tests do not match"):
        return "frozen required tests do not match"
    if diagnostic.startswith("completed test count exceeds"):
        return "validation evidence exceeded limits"
    if diagnostic.startswith("required tests did not complete"):
        if any(item.outcome == "unavailable" for item in result.command_outcomes):
            return "validation dependency unavailable"
        return "required tests did not complete"
    if diagnostic.startswith("changed path") or diagnostic.startswith("changed paths"):
        return "changed path validation failed"
    return "validation failed"


def _to_pilot_validation_observation(
    result: FrozenTestValidationResult,
) -> PilotValidationObservation:
    return PilotValidationObservation(
        attempted=result.attempted,
        passed=result.passed,
        completed_tests=result.completed_tests,
        changed_paths=result.changed_paths,
        reason=_public_validation_reason(result),
    )


class FrozenTestValidationAdapter:
    """A one-shot ValidationAdapter backed by a frozen caller-supplied test set."""

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
        self._allowed_files = _validate_patterns(allowed_files, name="allowed_files")
        self._forbidden_paths = _validate_patterns(forbidden_paths, name="forbidden_paths")
        self._per_command_timeout_seconds = _validate_positive_bound(
            per_command_timeout_seconds,
            name="per_command_timeout_seconds",
            maximum=DEFAULT_PER_COMMAND_TIMEOUT_SECONDS,
        )
        self._total_timeout_seconds = _validate_positive_bound(
            total_timeout_seconds,
            name="total_timeout_seconds",
            maximum=DEFAULT_TOTAL_TIMEOUT_SECONDS,
        )
        self._max_output_bytes = _validate_output_bound(max_output_bytes)
        self._changed_paths_inspector = changed_paths_inspector
        self._cancelled = cancelled
        self._attempted = False
        self._last_result: FrozenTestValidationResult | None = None

    @property
    def last_result(self) -> FrozenTestValidationResult | None:
        """Return read-only local evidence from the completed attempt, if any."""

        return self._last_result

    def validate(self, request: PilotValidationRequest) -> PilotValidationObservation:
        if not isinstance(request, PilotValidationRequest):
            raise TypeError("request must be PilotValidationRequest")
        if self._attempted:
            raise RuntimeError("the frozen-test validation adapter may run at most once")
        self._attempted = True
        self._last_result = None
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
        self._last_result = result
        return _to_pilot_validation_observation(result)
