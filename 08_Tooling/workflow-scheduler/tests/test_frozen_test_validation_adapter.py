from __future__ import annotations

import math

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


def test_identity_mismatch_has_exact_failure_reason() -> None:
    adapter = make_adapter({"test-a": success("other")})
    assert adapter.validate(request("test-a")).passed is False
    assert outcome(adapter).reason == (
        "runner observation identity did not match the requested command"
    )


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
        (
            "per_command_timeout_seconds",
            module.DEFAULT_PER_COMMAND_TIMEOUT_SECONDS + 1,
        ),
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
    ticks = iter((10.0, 10.2))
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    adapter = make_adapter(
        {"test-a": success("test-a")},
        per_command_timeout_seconds=0.1,
    )
    assert adapter.validate(request("test-a")).passed is False
    assert outcome(adapter).outcome == "timed-out"


def test_total_runtime_budget_prevents_later_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter((0.0, 0.75))
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    runner = FakeRunner({"test-a": success("test-a"), "test-b": success("test-b")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=commands("test-a", "test-b"),
        runner=runner,
        per_command_timeout_seconds=1,
        total_timeout_seconds=0.5,
    )
    assert adapter.validate(request()).passed is False
    assert len(runner.calls) == 1


def test_output_limit_is_combined_across_stdout_and_stderr() -> None:
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
    retained = len(recorded.stdout_text.encode()) + len(recorded.stderr_text.encode())
    assert retained <= 10
    assert "output-truncated" in recorded.reason
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


def test_cancellation_probe_exception_is_fail_closed() -> None:
    def cancelled() -> bool:
        raise RuntimeError("probe unavailable")

    adapter = make_adapter(
        {"test-a": success("test-a")},
        cancelled=cancelled,
    )
    observed = adapter.validate(request("test-a"))
    assert observed.passed is False
    assert "cancellation check failed" in observed.reason


def test_non_boolean_cancellation_probe_is_fail_closed() -> None:
    adapter = make_adapter(
        {"test-a": success("test-a")},
        cancelled=lambda: 1,  # type: ignore[arg-type]
    )
    assert adapter.validate(request("test-a")).passed is False
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
    assert "inspector failed" in observed.reason


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
        {
            "test-a": success(
                "test-a",
                changed_paths=("src/file.py", "src/file.py"),
            )
        },
        allowed_files=ALLOWED_FILES,
    )
    assert duplicate.validate(request("test-a")).passed is False

    forbidden = make_adapter(
        {
            "test-a": success(
                "test-a",
                changed_paths=(".github/workflows/ci.yml",),
            )
        },
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
    adapter = make_adapter(
        {"test-a": success("test-a", changed_paths=("src/file.py",))},
        allowed_files=ALLOWED_FILES,
        changed_paths_inspector=lambda: ("src/file.py",),
    )
    assert adapter.validate(request("test-a")).passed is False


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
