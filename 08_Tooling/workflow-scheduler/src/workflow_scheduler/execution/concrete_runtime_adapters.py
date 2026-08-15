"""Bind executable WSC5 adapters to one canonical pure runtime configuration.

Configuration construction and fingerprinting live in ``runtime_configuration``.
This module owns only executable adapter composition and runtime entrypoints.
The configuration classes are re-exported here for backward compatibility.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Callable

from workflow_scheduler.execution import cgroup_v2_containment
from workflow_scheduler.execution.frozen_test_validation_adapter import (
    BoundedCommandRunner,
    ChangedPathsInspector,
    CommandRunObservation,
    CommandRunRequest,
    FrozenTestValidationAdapter,
    FrozenTestValidationResult,
)
from workflow_scheduler.execution.git_worktree_adapter import GitRunner, GitWorktreeAdapter
from workflow_scheduler.execution.host_local_lease_adapter import (
    HostLocalLeaseAdapter,
    HostLocalLeasePolicy,
)
from workflow_scheduler.execution.in_memory_lease_adapter import InMemoryLeaseAdapter
from workflow_scheduler.execution.posix_process_adapter import (
    ContainmentConfig,
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
    WorkspaceLifecycleEvidence,
    WorkspaceStateObservation,
)

ProcessCancellationCheck = Callable[[], bool]


class ConcreteRuntimeContainmentError(ConcreteRuntimeConfigurationError):
    """Raised when configured #759 containment cannot be preflighted.

    Raised before any lease, worktree, or process exists for this
    invocation -- there is no fallback to the uncontained path once
    ``delegated_parent_cgroup`` has been configured.
    """


def _invocation_scope(configuration: ConcreteRuntimeConfiguration, *, suffix: str) -> str:
    """A bounded, filesystem-safe per-purpose invocation id derived from the base one.

    Multiple #759 invocation cgroups can exist under the same
    ``delegated_parent_cgroup`` for one configuration (the executor and each
    validation command each get their own), so each needs a distinct,
    collision-free directory name.
    """
    digest = hashlib.sha256(
        f"{configuration.invocation_id}:{suffix}".encode("utf-8")
    ).hexdigest()
    return f"wsc-{digest[:32]}"


def _preflight_containment(configuration: ConcreteRuntimeConfiguration) -> None:
    if configuration.delegated_parent_cgroup is None:
        return
    preflight = cgroup_v2_containment.preflight_check(configuration.delegated_parent_cgroup)
    if not preflight.supported:
        raise ConcreteRuntimeContainmentError(
            f"#759 containment preflight failed: {preflight.reason}"
        )


def _containment_config(
    configuration: ConcreteRuntimeConfiguration, *, suffix: str
) -> ContainmentConfig | None:
    if configuration.delegated_parent_cgroup is None:
        return None
    return ContainmentConfig(
        delegated_parent_cgroup=configuration.delegated_parent_cgroup,
        invocation_id=_invocation_scope(configuration, suffix=suffix),
    )


def _lease_adapter(
    configuration: ConcreteRuntimeConfiguration,
) -> InMemoryLeaseAdapter | HostLocalLeaseAdapter:
    if configuration.lease_directory is None:
        return InMemoryLeaseAdapter()
    return HostLocalLeaseAdapter(
        policy=HostLocalLeasePolicy(lease_directory=configuration.lease_directory)
    )


class WorkspaceStateCapturingAdapter:
    """Thin #760 capture wrapper: every call delegates to the bound adapter unchanged.

    Captures the #760 initial observation immediately after a successful
    ``create`` and the #760 final observation immediately before delegating
    to the real ``cleanup`` -- the only two points in the unmodified
    single-issue-pilot lifecycle where the workspace is known to exist and
    is about to change ownership. Adds no Git runner, worktree manager, or
    orchestration beyond that pass-through.
    """

    def __init__(self, adapter: GitWorktreeAdapter) -> None:
        self._adapter = adapter
        self.initial_observation: WorkspaceStateObservation | None = None
        self.final_observation: WorkspaceStateObservation | None = None

    def create(self, request):
        handle = self._adapter.create(request)
        if handle.created:
            self.initial_observation = self._adapter.inspect_complete_state(
                handle, observation_kind="initial"
            )
        return handle

    def inspect(self, handle):
        return self._adapter.inspect(handle)

    def cleanup(self, handle):
        if handle.created and self.final_observation is None:
            self.final_observation = self._adapter.inspect_complete_state(
                handle, observation_kind="final"
            )
        return self._adapter.cleanup(handle)


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
            containment=_containment_config(
                self._configuration, suffix=f"validate:{request.test_id}"
            ),
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
    lease: InMemoryLeaseAdapter | HostLocalLeaseAdapter
    workspace: WorkspaceStateCapturingAdapter
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
    """Verify one binding and construct the executable adapters for this mode.

    #759 containment (when ``configuration.delegated_parent_cgroup`` is set)
    is preflighted here, before the #758 lease or the worktree exist for
    this invocation -- a failed preflight fails closed before either is
    created.
    """

    configuration.verify(pilot_input)
    _preflight_containment(configuration)
    lease = _lease_adapter(configuration)
    workspace = WorkspaceStateCapturingAdapter(
        GitWorktreeAdapter(
            repository_root=configuration.repository_root,
            workspace_parent=configuration.workspace_parent,
            repository_identity=configuration.repository_identity,
            runner=git_runner,
        )
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
                containment=_containment_config(configuration, suffix="executor"),
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
    workspace_lifecycle_evidence: WorkspaceLifecycleEvidence | None = None


def run_concrete_runtime_entrypoint_with_validation_evidence(
    pilot_input: SingleIssuePilotInput,
    configuration: ConcreteRuntimeConfiguration,
    *,
    cancelled: CancellationProbe,
    git_runner: GitRunner | None = None,
    process_cancelled: ProcessCancellationCheck | None = None,
    changed_paths_inspector: ChangedPathsInspector | None = None,
) -> ConcreteRuntimeExecutionOutcome:
    """Run once and return the exact validation/#760 evidence retained by the adapters."""

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
    workspace_lifecycle_evidence: WorkspaceLifecycleEvidence | None = None
    if (
        adapters.workspace.initial_observation is not None
        and adapters.workspace.final_observation is not None
    ):
        workspace_lifecycle_evidence = WorkspaceLifecycleEvidence(
            initial=adapters.workspace.initial_observation,
            final=adapters.workspace.final_observation,
            validation_only=pilot_input.execution_mode == VALIDATION_ONLY_EXECUTION_MODE,
        )
    return ConcreteRuntimeExecutionOutcome(
        runtime_outcome=runtime_outcome,
        validation_result=adapters.validator.last_result,
        workspace_lifecycle_evidence=workspace_lifecycle_evidence,
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
