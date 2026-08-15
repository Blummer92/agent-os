"""Bind executable WSC5 adapters to one canonical pure runtime configuration.

Configuration construction and fingerprinting live in ``runtime_configuration``.
This module owns only executable adapter composition and runtime entrypoints.
The configuration classes are re-exported here for backward compatibility.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from workflow_scheduler.execution.frozen_test_validation_adapter import (
    BoundedCommandRunner,
    ChangedPathsInspector,
    CommandRunObservation,
    CommandRunRequest,
    FrozenTestValidationAdapter,
    FrozenTestValidationResult,
)
from workflow_scheduler.execution.git_worktree_adapter import GitRunner, GitWorktreeAdapter
from workflow_scheduler.execution.in_memory_lease_adapter import InMemoryLeaseAdapter
from workflow_scheduler.execution.posix_process_adapter import (
    PosixProcessExecutionResult,
    PosixProcessExecutor,
    PosixProcessExecutorConfig,
    run_bounded_posix_process,
)
from workflow_scheduler.execution.runtime_configuration import (
    ENVIRONMENT_POLICY,
    ConcreteRuntimeConfiguration,
    ConcreteRuntimeConfigurationError,
)
from workflow_scheduler.execution.single_issue_pilot import (
    VALIDATION_ONLY_EXECUTION_MODE,
    CancellationProbe,
    SingleIssuePilotInput,
)
from workflow_scheduler.execution.single_issue_runtime import (
    SingleIssueRuntimeOutcome,
    run_single_issue_runtime_entrypoint,
)
from workflow_scheduler.execution.single_issue_pilot import WorkspaceHandle
from workflow_scheduler.execution.workspace_state_evidence import (
    WorkspaceStateObservation,
)

ProcessCancellationCheck = Callable[[], bool]


def _environment(configuration: ConcreteRuntimeConfiguration) -> dict[str, str]:
    if configuration.environment_policy != ENVIRONMENT_POLICY:
        raise ConcreteRuntimeConfigurationError("unsupported environment authority")
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": configuration.repository_root,
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }


class BoundPosixCommandRunner(BoundedCommandRunner):
    """Run only one exact test-id/argv binding, at most once."""

    def __init__(
        self,
        configuration: ConcreteRuntimeConfiguration,
        *,
        cancelled: ProcessCancellationCheck | None = None,
    ) -> None:
        self._configuration = configuration
        self._cancelled = cancelled
        self._commands = {
            item.test_id: item.argv for item in configuration.required_test_commands
        }
        self._attempted: set[str] = set()
        self.last_result: PosixProcessExecutionResult | None = None

    def run(self, request: CommandRunRequest) -> CommandRunObservation:
        if not isinstance(request, CommandRunRequest):
            raise TypeError("request must be CommandRunRequest")
        if self._commands.get(request.test_id) != tuple(request.argv):
            raise ConcreteRuntimeConfigurationError("validation command is unbound")
        if request.test_id in self._attempted:
            raise RuntimeError("a bound validation command may run at most once")
        self._attempted.add(request.test_id)
        result = run_bounded_posix_process(
            request.argv,
            timeout_seconds=min(
                request.timeout_seconds,
                self._configuration.validation_per_command_timeout_seconds,
            ),
            grace_period_seconds=self._configuration.executor_grace_period_seconds,
            max_output_bytes=self._configuration.validation_max_output_bytes,
            cwd=self._configuration.executor_cwd,
            env=_environment(self._configuration),
            cancelled=self._cancelled,
        )
        self.last_result = result
        outcome = (
            "cancelled"
            if result.cancellation_requested
            else "timed-out"
            if result.timeout_observed
            else "succeeded"
            if result.return_code == 0 and result.termination_confirmed
            else "failed"
        )
        return CommandRunObservation(
            test_id=request.test_id,
            outcome=outcome,
            started=result.started,
            return_code=result.return_code,
            stdout_text=result.stdout_text,
            stderr_text=result.stderr_text,
            reason=result.reason,
        )


class GitChangedPathsInspector(ChangedPathsInspector):
    """Inspect tracked and untracked paths with bounded non-shell Git calls."""

    def __init__(self, configuration: ConcreteRuntimeConfiguration) -> None:
        self._configuration = configuration
        self._attempted = False

    def __call__(self) -> tuple[str, ...]:
        if self._attempted:
            raise RuntimeError("changed paths inspection may run at most once")
        self._attempted = True
        paths: list[str] = []
        commands = (
            ("git", "diff", "--name-only", "--no-renames", "-z", "HEAD"),
            ("git", "ls-files", "--others", "--exclude-standard", "-z"),
        )
        for command in commands:
            result = run_bounded_posix_process(
                command,
                timeout_seconds=self._configuration.validation_per_command_timeout_seconds,
                grace_period_seconds=self._configuration.executor_grace_period_seconds,
                max_output_bytes=self._configuration.validation_max_output_bytes,
                cwd=self._configuration.executor_cwd,
                env=_environment(self._configuration),
            )
            if (
                result.return_code != 0
                or not result.termination_confirmed
                or result.timeout_observed
                or result.cancellation_requested
            ):
                raise ConcreteRuntimeConfigurationError("changed paths inspection failed")
            paths.extend(item for item in result.stdout_text.split("\x00") if item)
        return tuple(dict.fromkeys(paths))


@dataclass(frozen=True, slots=True, kw_only=True)
class ConcreteRuntimeAdapters:
    lease: InMemoryLeaseAdapter
    workspace: GitWorktreeAdapter
    executor: PosixProcessExecutor | None
    validator: FrozenTestValidationAdapter
    validation_runner: BoundPosixCommandRunner = field(repr=False)


def build_concrete_runtime_adapters(
    pilot_input: SingleIssuePilotInput,
    configuration: ConcreteRuntimeConfiguration,
    *,
    git_runner: GitRunner | None = None,
    process_cancelled: ProcessCancellationCheck | None = None,
    changed_paths_inspector: ChangedPathsInspector | None = None,
) -> ConcreteRuntimeAdapters:
    """Verify one binding and construct the executable adapters for this mode."""

    configuration.verify(pilot_input)
    lease = InMemoryLeaseAdapter()
    workspace = GitWorktreeAdapter(
        repository_root=configuration.repository_root,
        workspace_parent=configuration.workspace_parent,
        repository_identity=configuration.repository_identity,
        runner=git_runner,
    )
    executor: PosixProcessExecutor | None = None
    if configuration.execution_mode != VALIDATION_ONLY_EXECUTION_MODE:
        executor = PosixProcessExecutor(
            PosixProcessExecutorConfig(
                argv=configuration.executor_argv,
                timeout_seconds=configuration.executor_timeout_seconds,
                grace_period_seconds=configuration.executor_grace_period_seconds,
                max_output_bytes=configuration.executor_max_output_bytes,
                cwd=configuration.executor_cwd,
                env=_environment(configuration),
            ),
            cancelled=process_cancelled,
        )
    validation_runner = BoundPosixCommandRunner(
        configuration, cancelled=process_cancelled
    )
    validator = FrozenTestValidationAdapter(
        required_test_commands=configuration.required_test_commands,
        runner=validation_runner,
        allowed_files=configuration.allowed_files,
        forbidden_paths=configuration.forbidden_paths,
        per_command_timeout_seconds=configuration.validation_per_command_timeout_seconds,
        total_timeout_seconds=configuration.validation_total_timeout_seconds,
        max_output_bytes=configuration.validation_max_output_bytes,
        changed_paths_inspector=(
            changed_paths_inspector or GitChangedPathsInspector(configuration)
        ),
        cancelled=process_cancelled,
    )
    return ConcreteRuntimeAdapters(
        lease=lease,
        workspace=workspace,
        executor=executor,
        validator=validator,
        validation_runner=validation_runner,
    )


def capture_workspace_state_observation(
    adapters: ConcreteRuntimeAdapters,
    handle: WorkspaceHandle,
    *,
    observation_kind: str,
) -> WorkspaceStateObservation:
    """Capture one complete workspace-state observation via the bound workspace adapter.

    A thin pass-through to ``GitWorktreeAdapter.inspect_complete_state``; it
    adds no new runner, orchestration, or runtime wiring. Runtime selection
    of when this is called is out of this issue's scope.
    """
    return adapters.workspace.inspect_complete_state(
        handle, observation_kind=observation_kind
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ConcreteRuntimeExecutionOutcome:
    """Canonical runtime outcome with exact retained validation evidence."""

    runtime_outcome: SingleIssueRuntimeOutcome
    validation_result: FrozenTestValidationResult | None


def run_concrete_runtime_entrypoint_with_validation_evidence(
    pilot_input: SingleIssuePilotInput,
    configuration: ConcreteRuntimeConfiguration,
    *,
    cancelled: CancellationProbe,
    git_runner: GitRunner | None = None,
    process_cancelled: ProcessCancellationCheck | None = None,
    changed_paths_inspector: ChangedPathsInspector | None = None,
) -> ConcreteRuntimeExecutionOutcome:
    """Run once and return the exact validation evidence retained by the adapter."""

    adapters = build_concrete_runtime_adapters(
        pilot_input,
        configuration,
        git_runner=git_runner,
        process_cancelled=process_cancelled,
        changed_paths_inspector=changed_paths_inspector,
    )
    runtime_outcome = run_single_issue_runtime_entrypoint(
        pilot_input,
        lease=adapters.lease,
        workspace=adapters.workspace,
        executor=adapters.executor,
        validator=adapters.validator,
        cancelled=cancelled,
    )
    return ConcreteRuntimeExecutionOutcome(
        runtime_outcome=runtime_outcome,
        validation_result=adapters.validator.last_result,
    )


def run_concrete_runtime_entrypoint(
    pilot_input: SingleIssuePilotInput,
    configuration: ConcreteRuntimeConfiguration,
    *,
    cancelled: CancellationProbe,
    git_runner: GitRunner | None = None,
    process_cancelled: ProcessCancellationCheck | None = None,
    changed_paths_inspector: ChangedPathsInspector | None = None,
) -> SingleIssueRuntimeOutcome:
    """Preserve the existing runtime-only compatibility contract."""

    return run_concrete_runtime_entrypoint_with_validation_evidence(
        pilot_input,
        configuration,
        cancelled=cancelled,
        git_runner=git_runner,
        process_cancelled=process_cancelled,
        changed_paths_inspector=changed_paths_inspector,
    ).runtime_outcome
