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
