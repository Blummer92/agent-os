"""Bind executable WSC5 adapters to one canonical pure runtime configuration.

Configuration construction and fingerprinting live in ``runtime_configuration``.
This module owns only executable adapter composition and runtime entrypoints.
The configuration classes are re-exported here for backward compatibility.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Callable

from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyCacheState,
    DependencyEcosystem,
    DependencyInstallMode,
    DependencyReadinessEvidence,
    RequiredEnvironmentSpec,
)
from workflow_scheduler.execution import cgroup_v2_containment
from workflow_scheduler.execution.dependency_preparation import (
    BoundDependencyPreparationAdapter,
    DependencyCommandObservation,
    DependencyCommandRunner,
    DependencyPreparationAdapter,
    DependencyPreparationObservation,
    DependencyPreparationObservationProvider,
)
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
    WorkspaceHandle,
)
from workflow_scheduler.execution.single_issue_runtime import (
    SingleIssueRuntimeOutcome,
    run_single_issue_runtime_entrypoint,
)
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
    """A bounded, filesystem-safe per-purpose invocation id derived from the base one."""
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
    """Thin #760 capture wrapper: every call delegates to the bound adapter unchanged."""

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

    def inspect_complete_state(self, handle, *, observation_kind):
        return self._adapter.inspect_complete_state(
            handle, observation_kind=observation_kind
        )

    def cleanup(self, handle):
        if handle.created and self.final_observation is None:
            self.final_observation = self._adapter.inspect_complete_state(
                handle, observation_kind="final"
            )
        return self._adapter.cleanup(handle)


def _python_dependency_environment_directory(
    configuration: ConcreteRuntimeConfiguration,
) -> str:
    digest = hashlib.sha256(
        f"{configuration.configuration_fingerprint}:python-dependency-env".encode(
            "utf-8"
        )
    ).hexdigest()[:24]
    return os.path.join(
        configuration.workspace_parent, f"agent-os-dependency-env-{digest}"
    )


def _python_dependency_executable(
    configuration: ConcreteRuntimeConfiguration,
) -> str:
    return os.path.join(
        _python_dependency_environment_directory(configuration), "bin", "python"
    )


def _environment(
    configuration: ConcreteRuntimeConfiguration,
    *,
    include_dependency_environment: bool = True,
) -> dict[str, str]:
    if configuration.environment_policy != ENVIRONMENT_POLICY:
        raise ConcreteRuntimeConfigurationError("unsupported environment authority")
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": configuration.repository_root,
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    spec = configuration.required_environment_spec
    if (
        include_dependency_environment
        and spec is not None
        and spec.ecosystem is DependencyEcosystem.PYTHON_PIP
        and os.path.isfile(_python_dependency_executable(configuration))
    ):
        venv = _python_dependency_environment_directory(configuration)
        environment["VIRTUAL_ENV"] = venv
        environment["PATH"] = os.path.join(venv, "bin") + os.pathsep + environment["PATH"]
    return environment


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
class ConcreteDependencyPreparationInputs:
    """Current-surface facts supplied by #972/source-cache evidence, never credentials."""

    execution_surface_id: str
    environment_health_evidence_id: str
    environment_health_current: bool
    runtime_version: str
    runtime_compatible: bool
    package_manager_version: str
    observed_source_identity: str
    source_reachable: bool
    package_available: bool
    cache_state: DependencyCacheState
    expires_at: str
    offline_source_identity: str | None = None
    offline_source_location: str | None = None
    existing_ready_evidence: DependencyReadinessEvidence | None = None

    def __post_init__(self) -> None:
        for name in (
            "execution_surface_id",
            "environment_health_evidence_id",
            "runtime_version",
            "package_manager_version",
            "observed_source_identity",
            "expires_at",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value or "\x00" in value:
                raise TypeError(f"{name} must be non-empty NUL-free exact text")
        for name in (
            "environment_health_current",
            "runtime_compatible",
            "source_reachable",
            "package_available",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be exact bool")
        if type(self.cache_state) is not DependencyCacheState:
            raise TypeError("cache_state must be exact DependencyCacheState")
        if self.offline_source_identity is not None and (
            type(self.offline_source_identity) is not str
            or not self.offline_source_identity
        ):
            raise TypeError("offline_source_identity must be non-empty exact text or None")
        if self.offline_source_location is not None and (
            type(self.offline_source_location) is not str
            or not self.offline_source_location
            or "\x00" in self.offline_source_location
        ):
            raise TypeError("offline_source_location must be non-empty NUL-free text or None")
        if self.existing_ready_evidence is not None and type(
            self.existing_ready_evidence
        ) is not DependencyReadinessEvidence:
            raise TypeError(
                "existing_ready_evidence must be exact DependencyReadinessEvidence or None"
            )


def _file_sha256(path: str) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65_536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
        return None


def _workspace_file(configuration: ConcreteRuntimeConfiguration, relative_path: str) -> str:
    return os.path.join(configuration.executor_cwd, *relative_path.split("/"))


def _materialized_environment_present(
    configuration: ConcreteRuntimeConfiguration,
    spec: RequiredEnvironmentSpec,
) -> bool:
    if spec.ecosystem is DependencyEcosystem.PYTHON_PIP:
        return os.path.isfile(_python_dependency_executable(configuration))
    package_root = (
        configuration.executor_cwd
        if spec.package_root == "."
        else _workspace_file(configuration, spec.package_root)
    )
    return os.path.isdir(os.path.join(package_root, "node_modules"))


class ConcreteDependencyObservationProvider(DependencyPreparationObservationProvider):
    """Verify task manifest/lock identities against one already-created workspace."""

    def __init__(
        self,
        configuration: ConcreteRuntimeConfiguration,
        spec: RequiredEnvironmentSpec,
        inputs: ConcreteDependencyPreparationInputs,
    ) -> None:
        self._configuration = configuration
        self._spec = spec
        self._inputs = inputs

    def observe(
        self,
        *,
        workspace_identity: str,
        existing_ready_evidence: DependencyReadinessEvidence | None,
    ) -> DependencyPreparationObservation:
        manifest_sha = _file_sha256(
            _workspace_file(
                self._configuration,
                self._spec.dependency_manifest_identity.relative_path,
            )
        )
        lock_matches: bool | None = None
        if self._spec.lock_or_constraints_identity is not None:
            lock_sha = _file_sha256(
                _workspace_file(
                    self._configuration,
                    self._spec.lock_or_constraints_identity.relative_path,
                )
            )
            lock_matches = lock_sha == self._spec.lock_or_constraints_identity.sha256
        reusable = existing_ready_evidence or self._inputs.existing_ready_evidence
        if reusable is not None and not _materialized_environment_present(
            self._configuration, self._spec
        ):
            reusable = None
        return DependencyPreparationObservation(
            execution_surface_id=self._inputs.execution_surface_id,
            workspace_identity=workspace_identity,
            source_sha=self._configuration.source_head_sha,
            environment_health_evidence_id=self._inputs.environment_health_evidence_id,
            environment_health_current=self._inputs.environment_health_current,
            runtime_version=self._inputs.runtime_version,
            runtime_compatible=self._inputs.runtime_compatible,
            package_manager_version=self._inputs.package_manager_version,
            manifest_matches=(
                manifest_sha == self._spec.dependency_manifest_identity.sha256
            ),
            lock_matches=lock_matches,
            source_identity_matches=(
                self._inputs.observed_source_identity
                == self._spec.approved_source_identity
            ),
            source_reachable=self._inputs.source_reachable,
            package_available=self._inputs.package_available,
            cache_state=self._inputs.cache_state,
            offline_source_identity=self._inputs.offline_source_identity,
            offline_source_location=self._inputs.offline_source_location,
            existing_ready_evidence=reusable,
        )


class ConcreteDependencyCommandRunner(DependencyCommandRunner):
    """Run deterministic preparation and hash resolved environment evidence."""

    def __init__(
        self,
        configuration: ConcreteRuntimeConfiguration,
        spec: RequiredEnvironmentSpec,
        *,
        cancelled: ProcessCancellationCheck | None = None,
    ) -> None:
        self._configuration = configuration
        self._spec = spec
        self._cancelled = cancelled
        self._attempts = 0

    def _cwd(self) -> str:
        if self._spec.ecosystem is DependencyEcosystem.PYTHON_PIP:
            return self._configuration.executor_cwd
        if self._spec.package_root == ".":
            return self._configuration.executor_cwd
        return _workspace_file(self._configuration, self._spec.package_root)

    def _run(
        self,
        argv: tuple[str, ...],
        *,
        suffix: str,
        include_dependency_environment: bool = True,
    ) -> PosixProcessExecutionResult:
        return run_bounded_posix_process(
            argv,
            timeout_seconds=self._configuration.validation_total_timeout_seconds,
            grace_period_seconds=self._configuration.executor_grace_period_seconds,
            max_output_bytes=self._configuration.validation_max_output_bytes,
            cwd=self._cwd(),
            env=_environment(
                self._configuration,
                include_dependency_environment=include_dependency_environment,
            ),
            cancelled=self._cancelled,
            containment=_containment_config(
                self._configuration, suffix=f"dependency:{suffix}"
            ),
        )

    @staticmethod
    def _succeeded(result: PosixProcessExecutionResult) -> bool:
        return (
            result.return_code == 0
            and result.termination_confirmed
            and not result.timeout_observed
            and not result.cancellation_requested
        )

    @staticmethod
    def _failure_reason(result: PosixProcessExecutionResult) -> str:
        text = f"{result.stderr_text}\n{result.reason}".casefold()
        if any(
            marker in text
            for marker in (
                "eai_again",
                "temporary failure in name resolution",
                "network is unreachable",
                "connection timed out",
            )
        ):
            return "dependency.source-unavailable"
        if any(
            marker in text
            for marker in (
                "no matching distribution found",
                "could not find a version that satisfies",
                "notarget",
                "e404",
            )
        ):
            return "dependency.package-unavailable"
        return "dependency.preparation-failed"

    def _prepare_clean_python_environment(self) -> PosixProcessExecutionResult:
        return self._run(
            (
                "python",
                "-m",
                "venv",
                "--clear",
                _python_dependency_environment_directory(self._configuration),
            ),
            suffix="python-venv",
            include_dependency_environment=False,
        )

    def _resolved_identity(self) -> str | None:
        if self._spec.install_mode is DependencyInstallMode.ABSENT_AUTHORIZED_LOCK_GENERATION:
            lock_path = os.path.join(self._cwd(), "package-lock.json")
            digest = _file_sha256(lock_path)
            return None if digest is None else f"lock:{digest}"
        if self._spec.ecosystem is DependencyEcosystem.PYTHON_PIP:
            result = self._run(
                (
                    _python_dependency_executable(self._configuration),
                    "-m",
                    "pip",
                    "freeze",
                    "--all",
                ),
                suffix="resolve-python",
            )
            if not self._succeeded(result):
                return None
            lines = sorted(
                line.strip()
                for line in result.stdout_text.splitlines()
                if line.strip()
            )
            digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
            return f"pip-freeze:{digest}"
        result = self._run(("npm", "ls", "--all", "--json"), suffix="resolve-node")
        if not self._succeeded(result):
            return None
        try:
            payload = json.loads(result.stdout_text)
            canonical = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return f"npm-tree:{hashlib.sha256(canonical).hexdigest()}"

    def run(
        self, argv: tuple[str, ...], *, workspace_identity: str
    ) -> DependencyCommandObservation:
        if self._attempts >= 2:
            raise RuntimeError(
                "dependency command runner allows initial preparation plus one changed-input preparation"
            )
        self._attempts += 1
        effective_argv = tuple(argv)
        if self._spec.ecosystem is DependencyEcosystem.PYTHON_PIP:
            environment_result = self._prepare_clean_python_environment()
            if not self._succeeded(environment_result):
                return DependencyCommandObservation(
                    attempted=True,
                    succeeded=False,
                    failure_reason_code="dependency.preparation-failed",
                )
            if effective_argv[:3] != ("python", "-m", "pip"):
                return DependencyCommandObservation(
                    attempted=True,
                    succeeded=False,
                    failure_reason_code="dependency.preparation-failed",
                )
            effective_argv = (
                _python_dependency_executable(self._configuration),
                *effective_argv[1:],
            )
        result = self._run(effective_argv, suffix=f"prepare-{self._attempts}")
        if not self._succeeded(result):
            return DependencyCommandObservation(
                attempted=True,
                succeeded=False,
                failure_reason_code=self._failure_reason(result),
            )
        return DependencyCommandObservation(
            attempted=True,
            succeeded=True,
            resolved_dependency_identity=self._resolved_identity(),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ConcreteRuntimeAdapters:
    lease: InMemoryLeaseAdapter | HostLocalLeaseAdapter
    workspace: WorkspaceStateCapturingAdapter
    executor: PosixProcessExecutor | None
    validator: FrozenTestValidationAdapter
    validation_runner: BoundPosixCommandRunner = field(repr=False)
    dependency_preparer: DependencyPreparationAdapter | None = field(
        default=None, repr=False
    )


def build_concrete_runtime_adapters(
    pilot_input: SingleIssuePilotInput,
    configuration: ConcreteRuntimeConfiguration,
    *,
    git_runner: GitRunner | None = None,
    process_cancelled: ProcessCancellationCheck | None = None,
    changed_paths_inspector: ChangedPathsInspector | None = None,
    dependency_preparation_inputs: ConcreteDependencyPreparationInputs | None = None,
    dependency_command_runner: DependencyCommandRunner | None = None,
) -> ConcreteRuntimeAdapters:
    """Verify one binding and construct the executable adapters for this mode."""

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

    spec = configuration.required_environment_spec
    dependency_preparer: DependencyPreparationAdapter | None = None
    if spec is None:
        if dependency_preparation_inputs is not None or dependency_command_runner is not None:
            raise ConcreteRuntimeConfigurationError(
                "dependency preparation inputs require a bound required environment"
            )
    else:
        if type(dependency_preparation_inputs) is not ConcreteDependencyPreparationInputs:
            raise ConcreteRuntimeConfigurationError(
                "required environment requires current dependency preparation inputs"
            )
        observation_provider = ConcreteDependencyObservationProvider(
            configuration, spec, dependency_preparation_inputs
        )
        command_runner = dependency_command_runner or ConcreteDependencyCommandRunner(
            configuration, spec, cancelled=process_cancelled
        )
        dependency_preparer = BoundDependencyPreparationAdapter(
            spec=spec,
            observations=observation_provider,
            runner=command_runner,
            evaluated_at=pilot_input.evaluated_at,
            expires_at=dependency_preparation_inputs.expires_at,
        )

    return ConcreteRuntimeAdapters(
        lease=lease,
        workspace=workspace,
        executor=executor,
        validator=validator,
        validation_runner=validation_runner,
        dependency_preparer=dependency_preparer,
    )


def capture_workspace_state_observation(
    adapters: ConcreteRuntimeAdapters,
    handle: WorkspaceHandle,
    *,
    observation_kind: str,
) -> WorkspaceStateObservation:
    """Capture one complete workspace-state observation via the bound workspace adapter."""
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
    dependency_preparation_inputs: ConcreteDependencyPreparationInputs | None = None,
    dependency_command_runner: DependencyCommandRunner | None = None,
) -> ConcreteRuntimeExecutionOutcome:
    """Run once and return retained validation, workspace, and readiness evidence."""

    adapters = build_concrete_runtime_adapters(
        pilot_input,
        configuration,
        git_runner=git_runner,
        process_cancelled=process_cancelled,
        changed_paths_inspector=changed_paths_inspector,
        dependency_preparation_inputs=dependency_preparation_inputs,
        dependency_command_runner=dependency_command_runner,
    )
    runtime_outcome = run_single_issue_runtime_entrypoint(
        pilot_input,
        lease=adapters.lease,
        workspace=adapters.workspace,
        executor=adapters.executor,
        validator=adapters.validator,
        cancelled=cancelled,
        dependency_preparer=adapters.dependency_preparer,
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
    dependency_preparation_inputs: ConcreteDependencyPreparationInputs | None = None,
    dependency_command_runner: DependencyCommandRunner | None = None,
) -> SingleIssueRuntimeOutcome:
    """Preserve the existing runtime-only compatibility contract."""

    return run_concrete_runtime_entrypoint_with_validation_evidence(
        pilot_input,
        configuration,
        cancelled=cancelled,
        git_runner=git_runner,
        process_cancelled=process_cancelled,
        changed_paths_inspector=changed_paths_inspector,
        dependency_preparation_inputs=dependency_preparation_inputs,
        dependency_command_runner=dependency_command_runner,
    ).runtime_outcome
