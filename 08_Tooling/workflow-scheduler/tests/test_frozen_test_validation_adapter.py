"""Tests for the WSC5B3B frozen-test validation adapter.

All runners are small deterministic fakes; no real subprocess is ever
spawned by this adapter or these tests. No arbitrary sleeps are used.
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(SCHEDULER_SRC) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_SRC))

from workflow_scheduler.execution import frozen_test_validation_adapter as adapter_module  # noqa: E402
from workflow_scheduler.execution.frozen_test_validation_adapter import (  # noqa: E402
    MAX_ARGUMENT_BYTES,
    MAX_ARGV_ITEMS,
    MAX_CHANGED_PATHS,
    MAX_COMMAND_BYTES,
    MAX_REQUIRED_TEST_COMMANDS,
    CommandRunObservation,
    CommandRunRequest,
    FrozenTestCommand,
    FrozenTestValidationAdapter,
    FrozenTestValidationError,
    run_frozen_test_validation,
)
from workflow_scheduler.execution.single_issue_pilot import (  # noqa: E402
    PilotValidationObservation,
    PilotValidationRequest,
    ValidationAdapter,
)

MODULE_PATH = (
    SCHEDULER_SRC / "workflow_scheduler" / "execution" / "frozen_test_validation_adapter.py"
)

ALLOWED_FILES = ("src/**",)
FORBIDDEN_PATHS = (".github/workflows/**",)


def _request(**changes: object) -> PilotValidationRequest:
    values: dict[str, object] = {
        "invocation_id": "invocation-597",
        "workspace_identity": "workspace-597",
        "plan_id": "plan-597",
        "required_tests": ("test-a", "test-b"),
    }
    values.update(changes)
    return PilotValidationRequest(**values)  # type: ignore[arg-type]


def _commands(*test_ids: str) -> tuple[FrozenTestCommand, ...]:
    return tuple(
        FrozenTestCommand(test_id=test_id, argv=("run", test_id)) for test_id in test_ids
    )


class FakeRunner:
    """Deterministic in-memory runner returning canned observations."""

    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = responses
        self.calls: list[CommandRunRequest] = []

    def run(self, request: CommandRunRequest) -> CommandRunObservation:
        self.calls.append(request)
        response = self._responses[request.test_id]
        if isinstance(response, BaseException):
            raise response
        return response


def _success(test_id: str, *, changed_paths: tuple[str, ...] = ()) -> CommandRunObservation:
    return CommandRunObservation(
        test_id=test_id, outcome="succeeded", started=True, return_code=0,
        changed_paths=changed_paths,
    )


# --------------------------------------------------------------------------
# Frozen argv accepted and run exactly once
# --------------------------------------------------------------------------


def test_exact_frozen_required_test_argv_accepted_and_run_once() -> None:
    runner = FakeRunner({"test-a": _success("test-a"), "test-b": _success("test-b")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a", "test-b"), runner=runner
    )
    observation = adapter.validate(_request())
    assert isinstance(observation, PilotValidationObservation)
    assert observation.attempted is True
    assert observation.passed is True
    assert observation.completed_tests == ("test-a", "test-b")
    assert len(runner.calls) == 2
    assert runner.calls[0].argv == ("run", "test-a")
    assert runner.calls[1].argv == ("run", "test-b")


def test_adapter_satisfies_the_validation_adapter_protocol() -> None:
    runner = FakeRunner({"test-a": _success("test-a")})
    adapter = FrozenTestValidationAdapter(required_test_commands=_commands("test-a"), runner=runner)
    assert isinstance(adapter, ValidationAdapter)


def test_adapter_runs_at_most_once() -> None:
    runner = FakeRunner({"test-a": _success("test-a")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a"), runner=runner
    )
    adapter.validate(_request(required_tests=("test-a",)))
    with pytest.raises(RuntimeError):
        adapter.validate(_request(required_tests=("test-a",)))


def test_adapter_rejects_wrong_request_type() -> None:
    runner = FakeRunner({"test-a": _success("test-a")})
    adapter = FrozenTestValidationAdapter(required_test_commands=_commands("test-a"), runner=runner)
    with pytest.raises(TypeError):
        adapter.validate("not-a-request")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Argv/config rejection before the runner is ever called
# --------------------------------------------------------------------------


def test_string_command_rejected_before_runner_call() -> None:
    with pytest.raises(FrozenTestValidationError):
        FrozenTestCommand(test_id="test-a", argv="run test-a")  # type: ignore[arg-type]


def test_empty_argv_rejected_before_runner_call() -> None:
    with pytest.raises(FrozenTestValidationError):
        FrozenTestCommand(test_id="test-a", argv=())


def test_nul_byte_in_argv_rejected_before_runner_call() -> None:
    with pytest.raises(FrozenTestValidationError):
        FrozenTestCommand(test_id="test-a", argv=("run", "test\x00a"))


def test_excessive_argument_count_rejected() -> None:
    with pytest.raises(FrozenTestValidationError):
        FrozenTestCommand(test_id="test-a", argv=("arg",) * (MAX_ARGV_ITEMS + 1))


def test_oversized_single_argument_rejected() -> None:
    with pytest.raises(FrozenTestValidationError):
        FrozenTestCommand(test_id="test-a", argv=("x" * (MAX_ARGUMENT_BYTES + 1),))


def test_oversized_aggregate_argv_bytes_rejected() -> None:
    per_arg = MAX_ARGUMENT_BYTES
    count = (MAX_COMMAND_BYTES // per_arg) + 2
    with pytest.raises(FrozenTestValidationError):
        FrozenTestCommand(test_id="test-a", argv=tuple("x" * per_arg for _ in range(count)))


def test_excessive_command_count_rejected_before_runner_call() -> None:
    runner = FakeRunner({})
    commands = _commands(*(f"test-{i}" for i in range(MAX_REQUIRED_TEST_COMMANDS + 1)))
    with pytest.raises(FrozenTestValidationError):
        FrozenTestValidationAdapter(required_test_commands=commands, runner=runner)
    assert runner.calls == []


def test_duplicate_test_id_in_configuration_rejected() -> None:
    commands = (
        FrozenTestCommand(test_id="test-a", argv=("run", "a")),
        FrozenTestCommand(test_id="test-a", argv=("run", "b")),
    )
    with pytest.raises(FrozenTestValidationError):
        run_frozen_test_validation(
            commands, ("test-a",), runner=FakeRunner({}), allowed_files=(), forbidden_paths=()
        )


def test_malformed_command_rejected_via_bad_test_id() -> None:
    with pytest.raises(FrozenTestValidationError):
        FrozenTestCommand(test_id="", argv=("run",))


def test_non_conforming_runner_rejected_at_construction() -> None:
    with pytest.raises(FrozenTestValidationError):
        FrozenTestValidationAdapter(
            required_test_commands=_commands("test-a"), runner=object()  # type: ignore[arg-type]
        )


# --------------------------------------------------------------------------
# Required-test identity/order mismatch fails closed before running commands
# --------------------------------------------------------------------------


def test_required_tests_identity_mismatch_fails_closed_before_runner_call() -> None:
    runner = FakeRunner({"test-a": _success("test-a")})
    adapter = FrozenTestValidationAdapter(required_test_commands=_commands("test-a"), runner=runner)
    observation = adapter.validate(_request(required_tests=("test-a", "test-b")))
    assert observation.attempted is True
    assert observation.passed is False
    assert runner.calls == []


def test_required_tests_reordered_identity_fails_closed() -> None:
    runner = FakeRunner({"test-a": _success("test-a"), "test-b": _success("test-b")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a", "test-b"), runner=runner
    )
    observation = adapter.validate(_request(required_tests=("test-b", "test-a")))
    assert observation.passed is False
    assert runner.calls == []


# --------------------------------------------------------------------------
# Missing / duplicate / timeout / cancellation / unavailable / malformed
# --------------------------------------------------------------------------


def test_missing_required_result_fails_closed() -> None:
    runner = FakeRunner(
        {"test-a": _success("test-a"), "test-b": CommandRunObservation(test_id="test-b", outcome="failed", started=True)}
    )
    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a", "test-b"), runner=runner
    )
    observation = adapter.validate(_request())
    assert observation.passed is False
    assert observation.completed_tests == ()


def test_duplicate_observation_identity_fails_closed() -> None:
    runner = FakeRunner(
        {"test-a": _success("test-a"), "test-b": CommandRunObservation(test_id="test-a", outcome="succeeded", started=True)}
    )
    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a", "test-b"), runner=runner
    )
    observation = adapter.validate(_request())
    assert observation.passed is False


def test_reordered_result_identity_mismatch_fails_closed() -> None:
    runner = FakeRunner(
        {"test-a": CommandRunObservation(test_id="test-b", outcome="succeeded", started=True), "test-b": _success("test-b")}
    )
    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a", "test-b"), runner=runner
    )
    observation = adapter.validate(_request())
    assert observation.passed is False
    assert "test-a" not in observation.completed_tests


def test_timeout_result_fails_closed() -> None:
    runner = FakeRunner(
        {"test-a": CommandRunObservation(test_id="test-a", outcome="timed-out", started=True)}
    )
    adapter = FrozenTestValidationAdapter(required_test_commands=_commands("test-a"), runner=runner)
    observation = adapter.validate(_request(required_tests=("test-a",)))
    assert observation.passed is False
    assert observation.completed_tests == ()


def test_cancellation_before_first_command_fails_closed_without_calling_runner() -> None:
    runner = FakeRunner({"test-a": _success("test-a")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a"),
        runner=runner,
        cancelled=lambda: True,
    )
    observation = adapter.validate(_request(required_tests=("test-a",)))
    assert observation.passed is False
    assert runner.calls == []


def test_unavailable_runner_result_fails_closed() -> None:
    runner = FakeRunner(
        {"test-a": CommandRunObservation(test_id="test-a", outcome="unavailable", started=False)}
    )
    adapter = FrozenTestValidationAdapter(required_test_commands=_commands("test-a"), runner=runner)
    observation = adapter.validate(_request(required_tests=("test-a",)))
    assert observation.passed is False


def test_runner_exception_maps_to_unavailable_and_fails_closed() -> None:
    runner = FakeRunner({"test-a": RuntimeError("binary not found")})
    adapter = FrozenTestValidationAdapter(required_test_commands=_commands("test-a"), runner=runner)
    observation = adapter.validate(_request(required_tests=("test-a",)))
    assert observation.passed is False
    assert observation.attempted is True


def test_malformed_observation_type_fails_closed() -> None:
    runner = FakeRunner({"test-a": "not-an-observation"})
    adapter = FrozenTestValidationAdapter(required_test_commands=_commands("test-a"), runner=runner)
    observation = adapter.validate(_request(required_tests=("test-a",)))
    assert observation.passed is False


def test_oversized_output_is_bounded() -> None:
    runner = FakeRunner(
        {
            "test-a": CommandRunObservation(
                test_id="test-a",
                outcome="succeeded",
                started=True,
                return_code=0,
                stdout_text="x" * (adapter_module.MAX_OUTPUT_BYTES + 100),
            )
        }
    )
    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a"), runner=runner, max_output_bytes=64
    )
    observation = adapter.validate(_request(required_tests=("test-a",)))
    assert observation.passed is True
    assert len(adapter.last_result.command_outcomes[0].stdout_text.encode("utf-8")) <= 64


# --------------------------------------------------------------------------
# Runtime budgets
# --------------------------------------------------------------------------


def test_per_command_timeout_budget_enforced_even_if_runner_claims_success() -> None:
    class SlowRunner:
        def run(self, request: CommandRunRequest) -> CommandRunObservation:
            # Simulate a runner that took longer than the effective timeout
            # by returning an observation whose own outcome claims success;
            # the adapter measures wall time itself and must not trust it.
            import time as _time

            _time.sleep(0.05)
            return CommandRunObservation(test_id=request.test_id, outcome="succeeded", started=True)

    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a"),
        runner=SlowRunner(),
        per_command_timeout_seconds=0.01,
    )
    observation = adapter.validate(_request(required_tests=("test-a",)))
    assert observation.passed is False
    assert adapter.last_result.command_outcomes[0].outcome == "timed-out"


def test_total_runtime_budget_stops_remaining_commands() -> None:
    runner = FakeRunner({"test-a": _success("test-a"), "test-b": _success("test-b")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a", "test-b"),
        runner=runner,
        total_timeout_seconds=1e-9,
    )
    observation = adapter.validate(_request())
    assert observation.passed is False
    assert len(runner.calls) <= 1


# --------------------------------------------------------------------------
# Required-test subset semantics
# --------------------------------------------------------------------------


def test_required_test_subset_semantics_with_extra_completed_tests() -> None:
    runner = FakeRunner({"test-a": _success("test-a"), "test-b": _success("test-b")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a", "test-b"), runner=runner
    )
    observation = adapter.validate(_request())
    assert set(("test-a", "test-b")) <= set(observation.completed_tests)


def test_extra_success_cannot_replace_a_missing_required_command() -> None:
    runner = FakeRunner(
        {"test-a": _success("test-a"), "test-b": CommandRunObservation(test_id="test-b", outcome="failed", started=True)}
    )
    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a", "test-b"), runner=runner
    )
    observation = adapter.validate(_request())
    assert observation.passed is False
    assert "test-b" not in observation.completed_tests


# --------------------------------------------------------------------------
# Changed-path validation
# --------------------------------------------------------------------------


def _adapter_with_paths(changed_paths: tuple[str, ...], **kwargs: object) -> PilotValidationObservation:
    runner = FakeRunner({"test-a": _success("test-a", changed_paths=changed_paths)})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a"),
        runner=runner,
        allowed_files=kwargs.get("allowed_files", ALLOWED_FILES),  # type: ignore[arg-type]
        forbidden_paths=kwargs.get("forbidden_paths", FORBIDDEN_PATHS),  # type: ignore[arg-type]
    )
    return adapter.validate(_request(required_tests=("test-a",)))


def test_valid_changed_path_within_allowlist_passes() -> None:
    observation = _adapter_with_paths(("src/file.py",))
    assert observation.passed is True
    assert observation.changed_paths == ("src/file.py",)


def test_absolute_changed_path_rejected() -> None:
    observation = _adapter_with_paths(("/etc/passwd",))
    assert observation.passed is False


def test_parent_traversal_changed_path_rejected() -> None:
    observation = _adapter_with_paths(("src/../../etc/passwd",))
    assert observation.passed is False


def test_duplicate_changed_path_rejected() -> None:
    observation = _adapter_with_paths(("src/file.py", "src/file.py"))
    assert observation.passed is False


def test_unnormalized_changed_path_rejected() -> None:
    observation = _adapter_with_paths(("src/./file.py",))
    assert observation.passed is False


def test_forbidden_changed_path_rejected() -> None:
    observation = _adapter_with_paths((".github/workflows/ci.yml",), allowed_files=(".github/**",))
    assert observation.passed is False


def test_out_of_allowlist_changed_path_rejected() -> None:
    observation = _adapter_with_paths(("other/file.py",))
    assert observation.passed is False


def test_oversized_changed_path_rejected() -> None:
    long_path = "src/" + ("a" * adapter_module.MAX_PATH_LENGTH) + ".py"
    observation = _adapter_with_paths((long_path,), allowed_files=("src/**",))
    assert observation.passed is False


def test_changed_path_count_bounded() -> None:
    paths = tuple(f"src/file{i}.py" for i in range(MAX_CHANGED_PATHS + 1))
    observation = _adapter_with_paths(paths)
    assert observation.passed is False


def test_changed_paths_inspector_is_used_instead_of_worktree_ownership() -> None:
    def inspector() -> tuple[str, ...]:
        return ("src/inspected.py",)

    runner = FakeRunner({"test-a": _success("test-a")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a"),
        runner=runner,
        allowed_files=ALLOWED_FILES,
        forbidden_paths=FORBIDDEN_PATHS,
        changed_paths_inspector=inspector,
    )
    observation = adapter.validate(_request(required_tests=("test-a",)))
    assert observation.passed is True
    assert "src/inspected.py" in observation.changed_paths


# --------------------------------------------------------------------------
# No retry; runner called at most once per required command
# --------------------------------------------------------------------------


def test_runner_called_at_most_once_per_required_command() -> None:
    runner = FakeRunner({"test-a": _success("test-a"), "test-b": _success("test-b")})
    adapter = FrozenTestValidationAdapter(
        required_test_commands=_commands("test-a", "test-b"), runner=runner
    )
    adapter.validate(_request())
    call_counts: dict[str, int] = {}
    for call in runner.calls:
        call_counts[call.test_id] = call_counts.get(call.test_id, 0) + 1
    assert all(count == 1 for count in call_counts.values())


def test_no_retry_after_a_failed_command() -> None:
    runner = FakeRunner(
        {"test-a": CommandRunObservation(test_id="test-a", outcome="failed", started=True)}
    )
    adapter = FrozenTestValidationAdapter(required_test_commands=_commands("test-a"), runner=runner)
    adapter.validate(_request(required_tests=("test-a",)))
    assert len(runner.calls) == 1


# --------------------------------------------------------------------------
# Architecture boundary
# --------------------------------------------------------------------------


_FORBIDDEN_IMPORT_ROOTS = (
    "subprocess",
    "socket",
    "urllib",
    "http",
    "requests",
    "sqlite3",
    "threading",
    "multiprocessing",
    "asyncio",
    "queue",
    "shutil",
    "signal",
    "selectors",
)

_FORBIDDEN_MODULE_SUBSTRINGS = (
    "in_memory_lease_adapter",
    "quarantine_review",
    "request_dispatch",
    "retry_manager",
    "execution.executor",
    "posix_process_adapter",
    "github",
    "workflow_dispatch",
)


def test_module_imports_no_subprocess_worktree_lease_persistence_or_network_authority() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    for module_name in imported_modules:
        root = module_name.split(".")[0]
        assert root not in _FORBIDDEN_IMPORT_ROOTS, f"forbidden import root: {module_name}"
        lowered = module_name.lower()
        for forbidden in _FORBIDDEN_MODULE_SUBSTRINGS:
            assert forbidden not in lowered, f"forbidden import: {module_name}"


def test_module_defines_no_process_group_or_network_calls() -> None:
    source = inspect.getsource(adapter_module)
    for forbidden_token in (
        "subprocess.",
        "os.killpg",
        "os.getpgid",
        "socket.",
        "sqlite3.",
        "requests.",
        "os.system(",
        "shell=True",
    ):
        assert forbidden_token not in source


def test_module_never_retries_or_installs_packages() -> None:
    source = inspect.getsource(adapter_module)
    for forbidden_token in ("RetryManager", "retry_attempt", "max_retries", "pip install", "apt-get"):
        assert forbidden_token not in source
