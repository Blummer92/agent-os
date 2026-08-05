from __future__ import annotations

import ast
import inspect
import math
from pathlib import Path

import pytest

from workflow_scheduler.execution import frozen_test_validation_adapter as module
from workflow_scheduler.execution.frozen_test_validation_adapter import (
    MAX_ARGUMENT_BYTES,
    MAX_ARGV_ITEMS,
    MAX_CHANGED_PATHS,
    MAX_COMMAND_BYTES,
    MAX_OUTPUT_BYTES,
    MAX_REASON_LENGTH,
    MAX_REQUIRED_TEST_COMMANDS,
    CommandRunObservation,
    CommandRunRequest,
    FrozenTestCommand,
    FrozenTestValidationAdapter,
    FrozenTestValidationError,
    run_frozen_test_validation,
)
from workflow_scheduler.execution.single_issue_pilot import (
    PilotValidationObservation,
    PilotValidationRequest,
    ValidationAdapter,
)

ALLOWED_FILES = ("src/**",)
FORBIDDEN_PATHS = (".github/workflows/**",)
MODULE_PATH = Path(module.__file__)


def request(*tests: str) -> PilotValidationRequest:
    return PilotValidationRequest(
        invocation_id="invocation-597",
        workspace_identity="workspace-597",
        plan_id="plan-597",
        required_tests=tests or ("test-a", "test-b"),
    )


def commands(*test_ids: str) -> tuple[FrozenTestCommand, ...]:
    return tuple(FrozenTestCommand(test_id=item, argv=("run", item)) for item in test_ids)


def success(test_id: str, **changes: object) -> CommandRunObservation:
    values: dict[str, object] = {
        "test_id": test_id,
        "outcome": "succeeded",
        "started": True,
        "return_code": 0,
    }
    values.update(changes)
    return CommandRunObservation(**values)  # type: ignore[arg-type]


class FakeRunner:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[CommandRunRequest] = []

    def run(self, item: CommandRunRequest) -> CommandRunObservation:
        self.calls.append(item)
        response = self.responses[item.test_id]
        if isinstance(response, BaseException):
            raise response
        return response  # type: ignore[return-value]


class Clock:
    def __init__(self, *values: float) -> None:
        self.values = iter(values)
        self.last = values[-1]

    def __call__(self) -> float:
        try:
            self.last = next(self.values)
        except StopIteration:
            pass
        return self.last


class ExplodingPaths:
    def __init__(self, secret: str, error_type: type[Exception] = RuntimeError) -> None:
        self.secret = secret
        self.error_type = error_type

    def __iter__(self):
        yield "src/file.py"
        raise self.error_type(self.secret)


def make_adapter(
    responses: dict[str, object],
    *,
    test_ids: tuple[str, ...] = ("test-a",),
    **kwargs: object,
) -> FrozenTestValidationAdapter:
    return FrozenTestValidationAdapter(
        required_test_commands=commands(*test_ids),
        runner=FakeRunner(responses),
        **kwargs,
    )


def outcome(adapter: FrozenTestValidationAdapter) -> CommandRunObservation:
    assert adapter.last_result is not None
    return adapter.last_result.command_outcomes[0]


def test_exact_frozen_argv_runs_once_and_passes() -> None:
    runner = FakeRunner({"test-a": success("test-a"), "test-b": success("test-b")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=commands("test-a", "test-b"), runner=runner
    )
    observed = adapter.validate(request())
    assert isinstance(observed, PilotValidationObservation)
    assert observed.passed is True
    assert observed.completed_tests == ("test-a", "test-b")
    assert [item.argv for item in runner.calls] == [("run", "test-a"), ("run", "test-b")]
    assert isinstance(adapter, ValidationAdapter)


def test_adapter_is_one_shot_and_last_result_is_read_only() -> None:
    adapter = make_adapter({"test-a": success("test-a")})
    assert adapter.last_result is None
    adapter.validate(request("test-a"))
    with pytest.raises(RuntimeError):
        adapter.validate(request("test-a"))
    with pytest.raises(AttributeError):
        adapter.last_result = None  # type: ignore[misc]


def test_wrong_request_type_leaves_no_result() -> None:
    adapter = make_adapter({"test-a": success("test-a")})
    with pytest.raises(TypeError):
        adapter.validate("bad")  # type: ignore[arg-type]
    assert adapter.last_result is None


@pytest.mark.parametrize(
    "argv",
    [
        "run test",
        (),
        ("run", "bad\x00value"),
        ("x",) * (MAX_ARGV_ITEMS + 1),
        ("x" * (MAX_ARGUMENT_BYTES + 1),),
    ],
)
def test_bad_argv_is_rejected(argv: object) -> None:
    with pytest.raises(FrozenTestValidationError):
        FrozenTestCommand(test_id="test-a", argv=argv)  # type: ignore[arg-type]


def test_aggregate_argv_and_command_counts_are_bounded() -> None:
    count = (MAX_COMMAND_BYTES // MAX_ARGUMENT_BYTES) + 2
    with pytest.raises(FrozenTestValidationError):
        FrozenTestCommand(
            test_id="test-a",
            argv=tuple("x" * MAX_ARGUMENT_BYTES for _ in range(count)),
        )
    with pytest.raises(FrozenTestValidationError):
        FrozenTestValidationAdapter(
            required_test_commands=commands(
                *(f"t-{index}" for index in range(MAX_REQUIRED_TEST_COMMANDS + 1))
            ),
            runner=FakeRunner({}),
        )


def test_duplicate_test_id_is_rejected() -> None:
    duplicate = (
        FrozenTestCommand(test_id="a", argv=("run", "a")),
        FrozenTestCommand(test_id="a", argv=("run", "b")),
    )
    with pytest.raises(FrozenTestValidationError):
        run_frozen_test_validation(
            duplicate,
            ("a",),
            runner=FakeRunner({}),
            allowed_files=(),
            forbidden_paths=(),
        )


def test_identity_and_order_mismatch_fails_before_runner() -> None:
    runner = FakeRunner({"test-a": success("test-a"), "test-b": success("test-b")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=commands("test-a", "test-b"), runner=runner
    )
    observed = adapter.validate(request("test-b", "test-a"))
    assert observed.passed is False
    assert runner.calls == []


def test_identity_mismatch_has_exact_failure_reason() -> None:
    adapter = make_adapter({"test-a": success("other")})
    assert adapter.validate(request("test-a")).passed is False
    assert outcome(adapter).reason == (
        "runner observation identity did not match the requested command"
    )


@pytest.mark.parametrize(
    ("changes", "reason_fragment"),
    [
        ({"started": False}, "requires started=True"),
        ({"return_code": None}, "requires started=True"),
        ({"return_code": 7}, "requires started=True"),
        ({"outcome": "invented"}, "outcome was unsupported"),
        ({"started": 1}, "started flag was malformed"),
        ({"return_code": True}, "return code was malformed"),
        ({"stdout_text": 1}, "stdout was malformed"),
        ({"stderr_text": object()}, "stderr was malformed"),
        ({"reason": 3}, "reason was malformed"),
        ({"changed_paths": "src/file.py"}, "changed_paths must be"),
    ],
)
def test_malformed_or_contradictory_success_never_completes(
    changes: dict[str, object], reason_fragment: str
) -> None:
    adapter = make_adapter({"test-a": success("test-a", **changes)})
    observed = adapter.validate(request("test-a"))
    assert observed.passed is False
    assert observed.completed_tests == ()
    assert outcome(adapter).outcome == "failed"
    assert reason_fragment in outcome(adapter).reason


def test_runner_exception_is_bounded_unavailable_evidence() -> None:
    adapter = make_adapter({"test-a": RuntimeError("x" * 5000)})
    assert adapter.validate(request("test-a")).passed is False
    assert outcome(adapter).outcome == "unavailable"
    assert len(outcome(adapter).reason) <= MAX_REASON_LENGTH


def test_non_observation_fails_closed() -> None:
    adapter = make_adapter({"test-a": "wrong"})
    assert adapter.validate(request("test-a")).passed is False
    assert outcome(adapter).reason == "runner returned a malformed observation"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("per_command_timeout_seconds", float("nan")),
        ("per_command_timeout_seconds", float("inf")),
        ("per_command_timeout_seconds", True),
        ("per_command_timeout_seconds", module.DEFAULT_PER_COMMAND_TIMEOUT_SECONDS + 1),
        ("total_timeout_seconds", float("-inf")),
        ("total_timeout_seconds", module.DEFAULT_TOTAL_TIMEOUT_SECONDS + 1),
        ("max_output_bytes", True),
        ("max_output_bytes", MAX_OUTPUT_BYTES + 1),
    ],
)
def test_runtime_and_output_bounds_reject_invalid_or_expanded_values(
    field: str, value: object
) -> None:
    with pytest.raises(FrozenTestValidationError):
        make_adapter({"test-a": success("test-a")}, **{field: value})


def test_reduced_runtime_and_output_bounds_are_allowed() -> None:
    adapter = make_adapter(
        {"test-a": success("test-a")},
        per_command_timeout_seconds=1,
        total_timeout_seconds=2,
        max_output_bytes=32,
    )
    assert adapter.validate(request("test-a")).passed is True


def test_elapsed_timeout_overrides_claimed_success_without_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module.time, "monotonic", Clock(0.0, 0.0, 0.0, 0.0, 0.2, 0.2))
    adapter = make_adapter(
        {"test-a": success("test-a")},
        per_command_timeout_seconds=0.1,
        total_timeout_seconds=1,
    )
    assert adapter.validate(request("test-a")).passed is False
    assert outcome(adapter).outcome == "timed-out"


def test_total_runtime_budget_prevents_later_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        module.time,
        "monotonic",
        Clock(0.0, 0.0, 0.0, 0.75, 0.75, 0.75, 0.75),
    )
    runner = FakeRunner({"test-a": success("test-a"), "test-b": success("test-b")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=commands("test-a", "test-b"),
        runner=runner,
        per_command_timeout_seconds=1,
        total_timeout_seconds=0.5,
    )
    assert adapter.validate(request()).passed is False
    assert len(runner.calls) == 1


def test_cancellation_probe_consumes_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module.time, "monotonic", Clock(0.0, 0.0, 2.0, 2.0, 2.0))
    adapter = make_adapter(
        {"test-a": success("test-a")},
        cancelled=lambda: False,
        total_timeout_seconds=1,
    )
    observed = adapter.validate(request("test-a"))
    assert observed.passed is False
    assert adapter.last_result is not None
    assert adapter.last_result.total_timed_out is True


def test_changed_path_inspector_consumes_total_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        module.time,
        "monotonic",
        Clock(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 2.0, 2.0),
    )
    adapter = make_adapter(
        {"test-a": success("test-a")},
        allowed_files=ALLOWED_FILES,
        changed_paths_inspector=lambda: ("src/file.py",),
        total_timeout_seconds=1,
    )
    observed = adapter.validate(request("test-a"))
    assert observed.passed is False
    assert adapter.last_result is not None
    assert adapter.last_result.total_timed_out is True


def test_path_validation_crossing_deadline_never_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        module.time,
        "monotonic",
        Clock(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 2.0),
    )
    adapter = make_adapter(
        {"test-a": success("test-a", changed_paths=("src/file.py",))},
        allowed_files=ALLOWED_FILES,
        total_timeout_seconds=1,
    )
    assert adapter.validate(request("test-a")).passed is False
    assert adapter.last_result is not None
    assert adapter.last_result.total_timed_out is True


@pytest.mark.parametrize(
    ("stdout", "stderr"),
    [
        ("before\ud800after", ""),
        ("", "before\udfffafter"),
        ("123456\ud800", "abcdef\udfff"),
    ],
)
def test_unpaired_surrogates_are_normalized_and_bounded(stdout: str, stderr: str) -> None:
    adapter = make_adapter(
        {"test-a": success("test-a", stdout_text=stdout, stderr_text=stderr)},
        max_output_bytes=12,
    )
    assert adapter.validate(request("test-a")).passed is True
    recorded = outcome(adapter)
    retained = len(recorded.stdout_text.encode("utf-8")) + len(recorded.stderr_text.encode("utf-8"))
    assert retained <= 12
    recorded.stdout_text.encode("utf-8")
    recorded.stderr_text.encode("utf-8")


def test_hook_exception_secrets_are_not_in_result_repr() -> None:
    secret = "TOP-SECRET-HOOK-VALUE"

    def cancelled() -> bool:
        raise RuntimeError(secret)

    cancellation_adapter = make_adapter(
        {"test-a": success("test-a")},
        cancelled=cancelled,
    )
    assert cancellation_adapter.validate(request("test-a")).passed is False
    assert secret not in repr(cancellation_adapter.last_result)

    def inspector() -> tuple[str, ...]:
        raise OSError(secret)

    inspector_adapter = make_adapter(
        {"test-a": success("test-a")},
        allowed_files=ALLOWED_FILES,
        changed_paths_inspector=inspector,
    )
    assert inspector_adapter.validate(request("test-a")).passed is False
    assert secret not in repr(inspector_adapter.last_result)


@pytest.mark.parametrize("error_type", [RuntimeError, OSError])
def test_cancellation_exception_is_private_and_public_reason_is_stable(
    error_type: type[Exception],
) -> None:
    secret = f"CANCELLATION-SECRET-{error_type.__name__}"

    def cancelled() -> bool:
        raise error_type(secret)

    adapter = make_adapter({"test-a": success("test-a")}, cancelled=cancelled)
    observed = adapter.validate(request("test-a"))

    assert observed.passed is False
    assert observed.reason == "cancellation check failed"
    assert secret not in observed.reason
    assert secret not in repr(observed)
    assert adapter.last_result is not None
    assert secret in adapter.last_result.reason
    assert secret not in repr(adapter.last_result)


@pytest.mark.parametrize("error_type", [RuntimeError, OSError])
def test_inspector_exception_is_private_and_public_reason_is_stable(
    error_type: type[Exception],
) -> None:
    secret = f"INSPECTOR-SECRET-{error_type.__name__}"

    def inspector() -> tuple[str, ...]:
        raise error_type(secret)

    adapter = make_adapter(
        {"test-a": success("test-a")},
        allowed_files=ALLOWED_FILES,
        changed_paths_inspector=inspector,
    )
    observed = adapter.validate(request("test-a"))

    assert observed.passed is False
    assert observed.reason == "changed paths inspector failed"
    assert secret not in observed.reason
    assert secret not in repr(observed)
    assert adapter.last_result is not None
    assert secret in adapter.last_result.reason
    assert secret not in repr(adapter.last_result)


def test_inspector_iterable_exception_is_private_and_public_reason_is_stable() -> None:
    secret = "INSPECTOR-ITERABLE-SECRET"
    adapter = make_adapter(
        {"test-a": success("test-a")},
        allowed_files=ALLOWED_FILES,
        changed_paths_inspector=lambda: ExplodingPaths(secret),  # type: ignore[arg-type]
    )
    observed = adapter.validate(request("test-a"))

    assert observed.passed is False
    assert observed.reason == "changed path evidence failed"
    assert secret not in observed.reason
    assert secret not in repr(observed)
    assert adapter.last_result is not None
    assert secret in adapter.last_result.reason
    assert secret not in repr(adapter.last_result)


def test_runner_path_iterable_exception_is_private_and_public_reason_is_stable() -> None:
    secret = "RUNNER-PATH-ITERABLE-SECRET"
    adapter = make_adapter(
        {"test-a": success("test-a", changed_paths=ExplodingPaths(secret))},
        allowed_files=ALLOWED_FILES,
    )
    observed = adapter.validate(request("test-a"))

    assert observed.passed is False
    assert observed.reason == "changed path evidence failed"
    assert secret not in observed.reason
    assert secret not in repr(observed)
    assert adapter.last_result is not None
    assert secret in outcome(adapter).reason
    assert secret not in repr(outcome(adapter))
    assert secret not in repr(adapter.last_result)


def test_cancellation_probe_exception_is_fail_closed() -> None:
    def cancelled() -> bool:
        raise RuntimeError("probe unavailable")

    adapter = make_adapter({"test-a": success("test-a")}, cancelled=cancelled)
    observed = adapter.validate(request("test-a"))
    assert observed.passed is False
    assert observed.reason == "cancellation check failed"


def test_non_boolean_cancellation_probe_is_fail_closed() -> None:
    adapter = make_adapter(
        {"test-a": success("test-a")},
        cancelled=lambda: 1,  # type: ignore[arg-type]
    )
    observed = adapter.validate(request("test-a"))
    assert observed.passed is False
    assert observed.reason == "cancellation check returned invalid evidence"
    assert adapter.last_result is not None
    assert "non-boolean" in adapter.last_result.reason


def test_changed_paths_inspector_exception_is_fail_closed() -> None:
    def inspector() -> tuple[str, ...]:
        raise OSError("worktree unavailable")

    adapter = make_adapter(
        {"test-a": success("test-a")},
        allowed_files=ALLOWED_FILES,
        changed_paths_inspector=inspector,
    )
    observed = adapter.validate(request("test-a"))
    assert observed.passed is False
    assert observed.reason == "changed paths inspector failed"


class CustomOperationalError(Exception):
    """An ordinary operational failure outside the previously handled tuple."""


ORDINARY_EXCEPTIONS = [Exception, KeyError, AssertionError, CustomOperationalError]
PROCESS_CONTROL_EXCEPTIONS = [KeyboardInterrupt, SystemExit, GeneratorExit]

SENTINEL_PATH = "src/secret-evidence-path.py"


def assert_public_reason_is_stable(
    observed: PilotValidationObservation,
    *,
    expected_reason: str,
    error_type: type[BaseException],
    secret: str,
) -> None:
    assert observed.attempted is True
    assert observed.passed is False
    assert observed.completed_tests == ()
    assert observed.changed_paths == ()
    assert observed.reason == expected_reason
    for fragment in (secret, SENTINEL_PATH, error_type.__name__):
        assert fragment not in observed.reason
        assert fragment not in repr(observed)


def assert_diagnostic_is_bounded(text: str, *, secret: str) -> None:
    assert secret in text
    assert len(text) <= MAX_REASON_LENGTH


@pytest.mark.parametrize("error_type", ORDINARY_EXCEPTIONS)
def test_ordinary_cancellation_probe_exception_fails_closed(
    error_type: type[Exception],
) -> None:
    secret = f"CANCEL-{error_type.__name__}-{SENTINEL_PATH}"

    def cancelled() -> bool:
        raise error_type(secret)

    runner = FakeRunner({"test-a": success("test-a")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=commands("test-a"),
        runner=runner,
        cancelled=cancelled,
    )
    observed = adapter.validate(request("test-a"))

    assert_public_reason_is_stable(
        observed,
        expected_reason="cancellation check failed",
        error_type=error_type,
        secret=secret,
    )
    assert adapter.last_result is not None
    assert_diagnostic_is_bounded(adapter.last_result.reason, secret=secret)
    assert secret not in repr(adapter.last_result)
    assert runner.calls == []


@pytest.mark.parametrize("error_type", ORDINARY_EXCEPTIONS)
def test_ordinary_runner_exception_fails_closed_without_retry(
    error_type: type[Exception],
) -> None:
    secret = f"RUNNER-{error_type.__name__}-{SENTINEL_PATH}"
    runner = FakeRunner({"test-a": error_type(secret)})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=commands("test-a"), runner=runner
    )
    observed = adapter.validate(request("test-a"))

    assert_public_reason_is_stable(
        observed,
        expected_reason="validation dependency unavailable",
        error_type=error_type,
        secret=secret,
    )
    assert adapter.last_result is not None
    assert outcome(adapter).outcome == "unavailable"
    assert outcome(adapter).started is False
    assert_diagnostic_is_bounded(outcome(adapter).reason, secret=secret)
    assert secret not in repr(outcome(adapter))
    assert secret not in repr(adapter.last_result)
    assert [item.test_id for item in runner.calls] == ["test-a"]


@pytest.mark.parametrize("error_type", ORDINARY_EXCEPTIONS)
def test_ordinary_inspector_exception_fails_closed(error_type: type[Exception]) -> None:
    secret = f"INSPECTOR-{error_type.__name__}-{SENTINEL_PATH}"

    def inspector() -> tuple[str, ...]:
        raise error_type(secret)

    runner = FakeRunner({"test-a": success("test-a")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=commands("test-a"),
        runner=runner,
        allowed_files=ALLOWED_FILES,
        changed_paths_inspector=inspector,
    )
    observed = adapter.validate(request("test-a"))

    assert_public_reason_is_stable(
        observed,
        expected_reason="changed paths inspector failed",
        error_type=error_type,
        secret=secret,
    )
    assert adapter.last_result is not None
    assert_diagnostic_is_bounded(adapter.last_result.reason, secret=secret)
    assert secret not in repr(adapter.last_result)
    assert [item.test_id for item in runner.calls] == ["test-a"]


@pytest.mark.parametrize("error_type", ORDINARY_EXCEPTIONS)
def test_ordinary_inspector_iterable_exception_fails_closed(
    error_type: type[Exception],
) -> None:
    secret = f"INSPECTOR-ITERABLE-{error_type.__name__}-{SENTINEL_PATH}"
    runner = FakeRunner({"test-a": success("test-a")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=commands("test-a"),
        runner=runner,
        allowed_files=ALLOWED_FILES,
        changed_paths_inspector=lambda: ExplodingPaths(secret, error_type),  # type: ignore[arg-type]
    )
    observed = adapter.validate(request("test-a"))

    assert_public_reason_is_stable(
        observed,
        expected_reason="changed path evidence failed",
        error_type=error_type,
        secret=secret,
    )
    assert adapter.last_result is not None
    assert_diagnostic_is_bounded(adapter.last_result.reason, secret=secret)
    assert secret not in repr(adapter.last_result)


@pytest.mark.parametrize("error_type", ORDINARY_EXCEPTIONS)
def test_ordinary_runner_path_iterable_exception_fails_closed(
    error_type: type[Exception],
) -> None:
    secret = f"RUNNER-ITERABLE-{error_type.__name__}-{SENTINEL_PATH}"
    runner = FakeRunner(
        {"test-a": success("test-a", changed_paths=ExplodingPaths(secret, error_type))}
    )
    adapter = FrozenTestValidationAdapter(
        required_test_commands=commands("test-a"),
        runner=runner,
        allowed_files=ALLOWED_FILES,
    )
    observed = adapter.validate(request("test-a"))

    assert_public_reason_is_stable(
        observed,
        expected_reason="changed path evidence failed",
        error_type=error_type,
        secret=secret,
    )
    assert adapter.last_result is not None
    assert_diagnostic_is_bounded(outcome(adapter).reason, secret=secret)
    assert secret not in repr(outcome(adapter))
    assert secret not in repr(adapter.last_result)
    assert [item.test_id for item in runner.calls] == ["test-a"]


@pytest.mark.parametrize("error_type", PROCESS_CONTROL_EXCEPTIONS)
def test_process_control_exception_propagates_from_cancellation_probe(
    error_type: type[BaseException],
) -> None:
    def cancelled() -> bool:
        raise error_type("process control")

    adapter = make_adapter({"test-a": success("test-a")}, cancelled=cancelled)
    with pytest.raises(error_type):
        adapter.validate(request("test-a"))
    assert adapter.last_result is None


@pytest.mark.parametrize("error_type", PROCESS_CONTROL_EXCEPTIONS)
def test_process_control_exception_propagates_from_runner(
    error_type: type[BaseException],
) -> None:
    runner = FakeRunner({"test-a": error_type("process control")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=commands("test-a"), runner=runner
    )
    with pytest.raises(error_type):
        adapter.validate(request("test-a"))
    assert adapter.last_result is None
    assert [item.test_id for item in runner.calls] == ["test-a"]


@pytest.mark.parametrize("error_type", PROCESS_CONTROL_EXCEPTIONS)
def test_process_control_exception_propagates_from_inspector(
    error_type: type[BaseException],
) -> None:
    def inspector() -> tuple[str, ...]:
        raise error_type("process control")

    adapter = make_adapter(
        {"test-a": success("test-a")},
        allowed_files=ALLOWED_FILES,
        changed_paths_inspector=inspector,
    )
    with pytest.raises(error_type):
        adapter.validate(request("test-a"))
    assert adapter.last_result is None


@pytest.mark.parametrize("error_type", PROCESS_CONTROL_EXCEPTIONS)
def test_process_control_exception_propagates_from_inspector_iterable(
    error_type: type[BaseException],
) -> None:
    adapter = make_adapter(
        {"test-a": success("test-a")},
        allowed_files=ALLOWED_FILES,
        changed_paths_inspector=lambda: ExplodingPaths("process control", error_type),  # type: ignore[arg-type]
    )
    with pytest.raises(error_type):
        adapter.validate(request("test-a"))
    assert adapter.last_result is None


@pytest.mark.parametrize("error_type", PROCESS_CONTROL_EXCEPTIONS)
def test_process_control_exception_propagates_from_runner_path_iterable(
    error_type: type[BaseException],
) -> None:
    adapter = make_adapter(
        {
            "test-a": success(
                "test-a",
                changed_paths=ExplodingPaths("process control", error_type),  # type: ignore[arg-type]
            )
        },
        allowed_files=ALLOWED_FILES,
    )
    with pytest.raises(error_type):
        adapter.validate(request("test-a"))
    assert adapter.last_result is None


def test_adapter_never_catches_base_exception() -> None:
    assert module._BOUNDARY_EXCEPTIONS == (Exception,)
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    caught: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        assert node.type is not None, "bare except is never allowed at a boundary"
        caught.append(ast.unparse(node.type))
    assert caught, "the adapter must still handle bounded operational failures"
    for expression in caught:
        assert "BaseException" not in expression
        assert "KeyboardInterrupt" not in expression
        assert "SystemExit" not in expression
        assert "GeneratorExit" not in expression


def test_combined_output_limit_and_command_repr_protection() -> None:
    secret = "TOP-SECRET-SENTINEL"
    adapter = make_adapter(
        {
            "test-a": success(
                "test-a",
                stdout_text="a" * 6,
                stderr_text=secret,
                reason=secret,
            )
        },
        max_output_bytes=10,
    )
    assert adapter.validate(request("test-a")).passed is True
    recorded = outcome(adapter)
    assert len(recorded.stdout_text.encode()) + len(recorded.stderr_text.encode()) <= 10
    assert secret not in repr(recorded)
    assert secret not in repr(adapter.last_result)


def test_reason_and_stderr_are_bounded() -> None:
    adapter = make_adapter(
        {
            "test-a": success(
                "test-a",
                stderr_text="e" * 1000,
                reason="r" * 5000,
            )
        },
        max_output_bytes=32,
    )
    assert adapter.validate(request("test-a")).passed is True
    assert len(outcome(adapter).stderr_text.encode()) <= 32
    assert len(outcome(adapter).reason) <= MAX_REASON_LENGTH


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "src/../../etc/passwd",
        "src/./file.py",
        "C:\\repo\\file.py",
        "C:/repo/file.py",
        "\\\\server\\share\\file.py",
        "src\\mixed/file.py",
    ],
)
def test_noncanonical_or_absolute_paths_are_rejected(path: str) -> None:
    adapter = make_adapter(
        {"test-a": success("test-a", changed_paths=(path,))},
        allowed_files=("*",),
    )
    assert adapter.validate(request("test-a")).passed is False


def test_valid_posix_path_passes_and_duplicate_forbidden_outside_fail() -> None:
    valid = make_adapter(
        {"test-a": success("test-a", changed_paths=("src/file.py",))},
        allowed_files=ALLOWED_FILES,
        forbidden_paths=FORBIDDEN_PATHS,
    )
    assert valid.validate(request("test-a")).changed_paths == ("src/file.py",)

    duplicate = make_adapter(
        {"test-a": success("test-a", changed_paths=("src/file.py", "src/file.py"))},
        allowed_files=ALLOWED_FILES,
    )
    assert duplicate.validate(request("test-a")).passed is False

    forbidden = make_adapter(
        {"test-a": success("test-a", changed_paths=(".github/workflows/ci.yml",))},
        allowed_files=(".github/**",),
        forbidden_paths=FORBIDDEN_PATHS,
    )
    assert forbidden.validate(request("test-a")).passed is False

    outside = make_adapter(
        {"test-a": success("test-a", changed_paths=("other/file.py",))},
        allowed_files=ALLOWED_FILES,
    )
    assert outside.validate(request("test-a")).passed is False


def test_inspector_and_runner_paths_share_duplicate_and_count_checks() -> None:
    duplicate = make_adapter(
        {"test-a": success("test-a", changed_paths=("src/file.py",))},
        allowed_files=ALLOWED_FILES,
        changed_paths_inspector=lambda: ("src/file.py",),
    )
    assert duplicate.validate(request("test-a")).passed is False

    runner_paths = tuple(f"src/{index}.py" for index in range(MAX_CHANGED_PATHS))
    excessive = make_adapter(
        {"test-a": success("test-a", changed_paths=runner_paths)},
        allowed_files=ALLOWED_FILES,
        changed_paths_inspector=lambda: ("src/extra.py",),
    )
    assert excessive.validate(request("test-a")).passed is False


def test_changed_path_generator_is_collected_only_to_hard_limit() -> None:
    def paths():
        for index in range(MAX_CHANGED_PATHS + 5):
            yield f"src/{index}.py"

    adapter = make_adapter(
        {"test-a": success("test-a", changed_paths=paths())},
        allowed_files=ALLOWED_FILES,
    )
    assert adapter.validate(request("test-a")).passed is False
    assert "bounded count" in outcome(adapter).reason


def test_failed_command_is_never_retried_and_extra_success_cannot_replace_missing() -> None:
    runner = FakeRunner(
        {
            "test-a": success("test-a"),
            "test-b": CommandRunObservation(
                test_id="test-b",
                outcome="failed",
                started=True,
                return_code=1,
            ),
        }
    )
    adapter = FrozenTestValidationAdapter(
        required_test_commands=commands("test-a", "test-b"), runner=runner
    )
    observed = adapter.validate(request())
    assert observed.passed is False
    assert observed.completed_tests == ()
    assert [item.test_id for item in runner.calls] == ["test-a", "test-b"]


def test_no_nonfinite_value_slips_through_low_level_function() -> None:
    with pytest.raises(FrozenTestValidationError):
        run_frozen_test_validation(
            commands("test-a"),
            ("test-a",),
            runner=FakeRunner({"test-a": success("test-a")}),
            allowed_files=(),
            forbidden_paths=(),
            total_timeout_seconds=math.nan,
        )


def test_module_imports_no_forbidden_authority() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    forbidden_roots = {
        "subprocess",
        "signal",
        "threading",
        "multiprocessing",
        "asyncio",
        "queue",
        "socket",
        "urllib",
        "http",
        "requests",
        "sqlite3",
        "concurrent",
    }
    forbidden_fragments = (
        "github",
        "workflow_dispatch",
        "retry_manager",
        "in_memory_lease_adapter",
        "legacy_executor",
        "execution.executor",
        "publication",
    )
    for name in imported:
        assert name.split(".")[0] not in forbidden_roots
        lowered = name.lower()
        assert not any(fragment in lowered for fragment in forbidden_fragments)


def test_module_source_contains_no_forbidden_execution_tokens() -> None:
    source = inspect.getsource(module).lower()
    forbidden = (
        "os.system(",
        "shell=true",
        "pip install",
        "apt-get",
        "retrymanager",
        "execute_many",
        "threadpoolexecutor",
        "workflow_dispatch",
        "githubclient",
        "set_status(",
        "add_label(",
        "publish_result(",
    )
    for token in forbidden:
        assert token not in source
