"""Integration tests for WSC5B4 concrete runtime adapter binding."""

from __future__ import annotations

import ast
import shutil
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
TESTS_DIR = Path(__file__).resolve().parent
for path in (REPOSITORY_ROOT, SCHEDULER_SRC, TESTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import test_single_issue_pilot as tsp  # noqa: E402

from workflow_scheduler.execution import concrete_runtime_adapters as module  # noqa: E402
from workflow_scheduler.execution.concrete_runtime_adapters import (  # noqa: E402
    BoundPosixCommandRunner,
    ConcreteRuntimeAdapters,
    ConcreteRuntimeConfiguration,
    ConcreteRuntimeConfigurationError,
    build_concrete_runtime_adapters,
    run_concrete_runtime_entrypoint,
)
from workflow_scheduler.execution.frozen_test_validation_adapter import (  # noqa: E402
    CommandRunRequest,
    FrozenTestCommand,
)
from workflow_scheduler.execution.git_worktree_adapter import (  # noqa: E402
    GitObservation,
    GitWorktreeAdapter,
)
from workflow_scheduler.execution.in_memory_lease_adapter import (  # noqa: E402
    InMemoryLeaseAdapter,
)
from workflow_scheduler.execution.posix_process_adapter import (  # noqa: E402
    PosixProcessExecutor,
)

MODULE_PATH = (
    SCHEDULER_SRC
    / "workflow_scheduler"
    / "execution"
    / "concrete_runtime_adapters.py"
)


def _commands(argv: tuple[str, ...]) -> tuple[FrozenTestCommand, ...]:
    return tuple(
        FrozenTestCommand(test_id=test_id, argv=argv)
        for test_id in tsp.REQUIRED_TESTS
    )


def _configuration(
    tmp_path: Path,
    *,
    executor_argv: tuple[str, ...] = (sys.executable, "-c", "pass"),
    validation_argv: tuple[str, ...] = (sys.executable, "-c", "pass"),
    executor_timeout_seconds: float = 1.0,
) -> ConcreteRuntimeConfiguration:
    root = tmp_path / "repository"
    parent = tmp_path / "worktrees"
    root.mkdir()
    parent.mkdir()
    return ConcreteRuntimeConfiguration.bind(
        tsp._pilot_input(),
        repository_identity=tsp._identity(),
        repository_root=str(root),
        workspace_parent=str(parent),
        executor_argv=executor_argv,
        required_test_commands=_commands(validation_argv),
        executor_timeout_seconds=executor_timeout_seconds,
        executor_grace_period_seconds=0.05,
        validation_per_command_timeout_seconds=1.0,
        validation_total_timeout_seconds=5.0,
    )


class ScenarioGitRunner:
    """Deterministic GitRunner exercising the real worktree adapter."""

    def __init__(
        self,
        configuration: ConcreteRuntimeConfiguration,
        *,
        fail_remove: bool = False,
    ) -> None:
        self.configuration = configuration
        self.fail_remove = fail_remove
        self.added = False
        self.locked = False
        self.lock_reason = ""
        self.calls: list[tuple[str, ...]] = []

    @staticmethod
    def _ok(stdout: str = "") -> GitObservation:
        return GitObservation(
            started=True,
            return_code=0,
            timed_out=False,
            termination_confirmed=True,
            stdout=stdout,
        )

    @staticmethod
    def _fail(reason: str) -> GitObservation:
        return GitObservation(
            started=True,
            return_code=1,
            timed_out=False,
            termination_confirmed=True,
            reason=reason,
        )

    def _porcelain(self) -> str:
        records = [
            f"worktree {self.configuration.repository_root}\x00",
            f"HEAD {self.configuration.source_head_sha}\x00",
            "branch refs/heads/main\x00\x00",
        ]
        if self.added:
            records.extend(
                [
                    f"worktree {self.configuration.executor_cwd}\x00",
                    f"HEAD {self.configuration.source_head_sha}\x00",
                    f"branch refs/heads/{self.configuration.branch}\x00",
                ]
            )
            if self.locked:
                records.append(f"locked {self.lock_reason}\x00")
            records.append("\x00")
        return "".join(records)

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: str,
        env: dict[str, str],
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> GitObservation:
        del cwd, env, timeout_seconds, max_output_bytes
        command = tuple(argv)
        self.calls.append(command)
        if command[1:3] == ("check-ref-format", "--branch"):
            return self._ok()
        if "rev-parse" in command:
            return self._ok(self.configuration.source_head_sha + "\n")
        if command[-4:] == ("worktree", "list", "--porcelain", "-z"):
            return self._ok(self._porcelain())
        if "worktree" in command and "add" in command:
            self.lock_reason = command[command.index("--reason") + 1]
            Path(self.configuration.executor_cwd).mkdir()
            self.added = True
            self.locked = True
            return self._ok()
        if command[-4:] == (
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ):
            return self._ok()
        if "worktree" in command and "unlock" in command:
            self.locked = False
            return self._ok()
        if "worktree" in command and "remove" in command:
            if self.fail_remove:
                return self._fail("remove failed")
            shutil.rmtree(self.configuration.executor_cwd)
            self.added = False
            return self._ok()
        if "worktree" in command and "lock" in command:
            self.locked = True
            return self._ok()
        return self._fail(f"unsupported test command: {command}")


def _run(
    tmp_path: Path,
    *,
    executor_argv: tuple[str, ...] = (sys.executable, "-c", "pass"),
    validation_argv: tuple[str, ...] = (sys.executable, "-c", "pass"),
    executor_timeout_seconds: float = 1.0,
    fail_remove: bool = False,
    cancelled=tsp.never_cancelled,
):
    configuration = _configuration(
        tmp_path,
        executor_argv=executor_argv,
        validation_argv=validation_argv,
        executor_timeout_seconds=executor_timeout_seconds,
    )
    git_runner = ScenarioGitRunner(configuration, fail_remove=fail_remove)
    outcome = run_concrete_runtime_entrypoint(
        tsp._pilot_input(),
        configuration,
        cancelled=cancelled,
        git_runner=git_runner,
        changed_paths_inspector=lambda: (),
    )
    return outcome, configuration, git_runner


# Immutable configuration and fail-closed binding


def test_binding_is_deterministic_immutable_and_tamper_evident(
    tmp_path: Path,
) -> None:
    first = _configuration(tmp_path)
    second = ConcreteRuntimeConfiguration.bind(
        tsp._pilot_input(),
        repository_identity=tsp._identity(),
        repository_root=first.repository_root,
        workspace_parent=first.workspace_parent,
        executor_argv=first.executor_argv,
        required_test_commands=first.required_test_commands,
        executor_timeout_seconds=first.executor_timeout_seconds,
        executor_grace_period_seconds=first.executor_grace_period_seconds,
        validation_per_command_timeout_seconds=(
            first.validation_per_command_timeout_seconds
        ),
        validation_total_timeout_seconds=(
            first.validation_total_timeout_seconds
        ),
    )
    assert first.configuration_fingerprint == second.configuration_fingerprint
    with pytest.raises(FrozenInstanceError):
        first.branch = "drift"  # type: ignore[misc]
    with pytest.raises(ConcreteRuntimeConfigurationError):
        replace(first, configuration_fingerprint="concrete-adapters:" + "0" * 64)


@pytest.mark.parametrize(
    "executor_argv",
    [
        "python -c pass",
        ("python", "-c", "print(${TOKEN})"),
        ("python", "-c", "$(malicious)"),
        ("python", "-c", "`malicious`"),
    ],
)
def test_shell_strings_and_interpolation_are_rejected(
    tmp_path: Path, executor_argv
) -> None:
    root, parent = tmp_path / "root", tmp_path / "parent"
    root.mkdir()
    parent.mkdir()
    with pytest.raises(ConcreteRuntimeConfigurationError):
        ConcreteRuntimeConfiguration.bind(
            tsp._pilot_input(),
            repository_identity=tsp._identity(),
            repository_root=str(root),
            workspace_parent=str(parent),
            executor_argv=executor_argv,
            required_test_commands=_commands((sys.executable, "-c", "pass")),
        )


def test_duplicate_missing_and_unbound_test_identities_are_rejected(
    tmp_path: Path,
) -> None:
    root, parent = tmp_path / "root", tmp_path / "parent"
    root.mkdir()
    parent.mkdir()
    invalid = (
        (),
        (
            FrozenTestCommand(test_id=tsp.REQUIRED_TESTS[0], argv=("python",)),
            FrozenTestCommand(test_id=tsp.REQUIRED_TESTS[0], argv=("python",)),
        ),
        (FrozenTestCommand(test_id="different", argv=("python",)),),
    )
    for commands in invalid:
        with pytest.raises(ConcreteRuntimeConfigurationError):
            ConcreteRuntimeConfiguration.bind(
                tsp._pilot_input(),
                repository_identity=tsp._identity(),
                repository_root=str(root),
                workspace_parent=str(parent),
                executor_argv=(sys.executable, "-c", "pass"),
                required_test_commands=commands,
            )


def test_packet_identity_and_path_drift_fail_closed(tmp_path: Path) -> None:
    configuration = _configuration(tmp_path)
    with pytest.raises(ConcreteRuntimeConfigurationError):
        configuration.verify(
            tsp._pilot_input(invocation_id="drifted-invocation")
        )
    with pytest.raises(ConcreteRuntimeConfigurationError):
        configuration.verify(tsp._pilot_input(allowed_files=("different.py",)))


# Concrete runner mapping and no retry


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ((sys.executable, "-c", "pass"), "succeeded"),
        ((sys.executable, "-c", "import sys;sys.exit(1)"), "failed"),
    ],
)
def test_runner_maps_posix_evidence_and_never_retries(
    tmp_path: Path,
    argv: tuple[str, ...],
    expected: str,
) -> None:
    configuration = _configuration(tmp_path, validation_argv=argv)
    Path(configuration.executor_cwd).mkdir()
    runner = BoundPosixCommandRunner(configuration)
    command = configuration.required_test_commands[0]
    request = CommandRunRequest(
        test_id=command.test_id,
        argv=command.argv,
        timeout_seconds=1.0,
    )
    assert runner.run(request).outcome == expected
    assert runner.last_result is not None
    with pytest.raises(RuntimeError):
        runner.run(request)


def test_unbound_runner_argv_fails_before_execution(tmp_path: Path) -> None:
    configuration = _configuration(tmp_path)
    runner = BoundPosixCommandRunner(configuration)
    with pytest.raises(ConcreteRuntimeConfigurationError):
        runner.run(
            CommandRunRequest(
                test_id=tsp.REQUIRED_TESTS[0],
                argv=(sys.executable, "-c", "different"),
                timeout_seconds=1.0,
            )
        )
    assert runner.last_result is None


# All-concrete runtime compatibility matrix


def test_builder_constructs_only_existing_adapter_types(tmp_path: Path) -> None:
    configuration = _configuration(tmp_path)
    adapters = build_concrete_runtime_adapters(
        tsp._pilot_input(),
        configuration,
        git_runner=ScenarioGitRunner(configuration),
        changed_paths_inspector=lambda: (),
    )
    assert isinstance(adapters, ConcreteRuntimeAdapters)
    assert isinstance(adapters.lease, InMemoryLeaseAdapter)
    assert isinstance(adapters.workspace, GitWorktreeAdapter)
    assert isinstance(adapters.executor, PosixProcessExecutor)
    assert isinstance(adapters.validator, module.FrozenTestValidationAdapter)


def test_all_concrete_completed_path(tmp_path: Path) -> None:
    outcome, _, git_runner = _run(tmp_path)
    assert outcome.result.status == "completed"
    assert outcome.observation.orchestrator_invocation_count == 1
    assert outcome.result.executor_dispatch_attempts == 1
    assert outcome.result.validation_attempts == 1
    assert outcome.result.workspace_cleanup_attempts == 1
    assert outcome.result.lease_release_attempts == 1
    assert git_runner.added is False


def test_all_concrete_failed_validation_path(tmp_path: Path) -> None:
    outcome, _, git_runner = _run(
        tmp_path,
        validation_argv=(sys.executable, "-c", "import sys;sys.exit(1)"),
    )
    assert outcome.result.status == "failed"
    assert "validation.failed" in outcome.result.reason_codes
    assert outcome.result.validation_attempts == 1
    assert outcome.result.workspace_cleanup_attempts == 1
    assert outcome.result.lease_release_attempts == 1
    assert git_runner.added is False


def test_all_concrete_timed_out_execution_path(tmp_path: Path) -> None:
    outcome, _, git_runner = _run(
        tmp_path,
        executor_argv=(
            sys.executable,
            "-c",
            "import time;time.sleep(2)",
        ),
        executor_timeout_seconds=0.05,
    )
    assert outcome.result.status == "timed-out"
    assert "executor.timeout" in outcome.result.reason_codes
    assert outcome.result.executor_dispatch_attempts == 1
    assert outcome.result.validation_attempts == 0
    assert git_runner.added is False


def test_all_concrete_cancelled_path(tmp_path: Path) -> None:
    checkpoints = []

    def cancelled(checkpoint):
        checkpoints.append(checkpoint)
        return checkpoint == "pre-lease"

    outcome, _, git_runner = _run(tmp_path, cancelled=cancelled)
    assert outcome.result.status == "cancelled"
    assert checkpoints == ["pre-lease"]
    assert outcome.result.executor_dispatch_attempts == 0
    assert git_runner.calls == []


def test_all_concrete_quarantined_cleanup_path(tmp_path: Path) -> None:
    outcome, _, git_runner = _run(tmp_path, fail_remove=True)
    assert outcome.result.status == "quarantined"
    assert outcome.quarantine_evidence is not None
    assert outcome.result.workspace_cleanup_attempts == 1
    assert outcome.result.lease_release_attempts == 1
    assert git_runner.added is True


class RaisingRunner:
    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.calls = 0

    def run(self, request):
        del request
        self.calls += 1
        raise self.error


def test_ordinary_runner_exception_is_bounded_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "SECRET-src/private-token.py"
    raising = RaisingRunner(KeyError(secret))
    monkeypatch.setattr(
        module,
        "BoundPosixCommandRunner",
        lambda configuration, cancelled=None: raising,
    )
    outcome, _, git_runner = _run(tmp_path)
    assert outcome.result.status == "failed"
    assert "validation.failed" in outcome.result.reason_codes
    assert secret not in repr(outcome.result)
    assert raising.calls == 1
    assert git_runner.added is False


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_process_control_exceptions_propagate_through_integration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
) -> None:
    raising = RaisingRunner(error_type("process control"))
    monkeypatch.setattr(
        module,
        "BoundPosixCommandRunner",
        lambda configuration, cancelled=None: raising,
    )
    with pytest.raises(error_type):
        _run(tmp_path)
    assert raising.calls == 1


# Architecture boundaries


def test_module_reuses_existing_process_and_runtime_lifecycles() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "subprocess" not in imports
    assert "threading" not in imports
    assert "requests" not in imports
    assert "github" not in imports
    assert "run_bounded_posix_process" in source
    assert source.count("run_single_issue_runtime_entrypoint(") == 1
