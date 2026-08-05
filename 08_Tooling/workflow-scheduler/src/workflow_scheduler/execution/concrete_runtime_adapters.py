"""Bind concrete WSC5 adapters to one canonical pilot packet.

This module composes only the existing lease, worktree, POSIX process,
frozen-test validation, and runtime-entrypoint implementations. It owns no
scheduler, retry, persistence, network, workflow, publication, or GitHub
authority.

In validation-only mode the configuration carries no executor argv and no
``PosixProcessExecutor`` is constructed at all. The bound validation commands
still run exactly once each through the same frozen-test validation adapter.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import posixpath
from dataclasses import dataclass, field
from typing import Callable, Literal

from scripts.agent_os_execution_capabilities.models import RepositoryIdentity
from workflow_scheduler.execution.frozen_test_validation_adapter import (
    BoundedCommandRunner,
    ChangedPathsInspector,
    CommandRunObservation,
    CommandRunRequest,
    FrozenTestCommand,
    FrozenTestValidationAdapter,
    FrozenTestValidationResult,
)
from workflow_scheduler.execution.git_worktree_adapter import GitRunner, GitWorktreeAdapter
from workflow_scheduler.execution.in_memory_lease_adapter import InMemoryLeaseAdapter
from workflow_scheduler.execution.posix_process_adapter import (
    MAX_OUTPUT_BYTES,
    PosixProcessExecutionResult,
    PosixProcessExecutor,
    PosixProcessExecutorConfig,
    run_bounded_posix_process,
)
from workflow_scheduler.execution.single_issue_pilot import (
    RUNTIME_EXECUTION_MODES,
    STANDARD_EXECUTION_MODE,
    VALIDATION_ONLY_EXECUTION_MODE,
    CancellationProbe,
    RuntimeExecutionMode,
    SingleIssuePilotInput,
    WorkspaceRequest,
    pilot_workspace_identity,
)
from workflow_scheduler.execution.single_issue_runtime import (
    SingleIssueRuntimeOutcome,
    run_single_issue_runtime_entrypoint,
)

SCHEMA_NAME = "agent-os-wsc5b4-concrete-adapters"
SCHEMA_VERSION = "1.0"
ENVIRONMENT_POLICY = "isolated-path-home-c-locale"
MAX_TEXT_BYTES = 4096
MAX_ITEMS = 256
MAX_TIMEOUT_SECONDS = 300.0
ProcessCancellationCheck = Callable[[], bool]


class ConcreteRuntimeConfigurationError(ValueError):
    """Raised before any adapter or process is invoked."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _fingerprint(value: object) -> str:
    digest = hashlib.sha256(
        b"agent-os-wsc5b4-concrete-adapters:v1\0" + _canonical_bytes(value)
    ).hexdigest()
    return f"concrete-adapters:{digest}"


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ConcreteRuntimeConfigurationError(
            f"{name} must be non-empty NUL-free text"
        )
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ConcreteRuntimeConfigurationError(
            f"{name} exceeds the bounded byte length"
        )
    return value


def _sha(value: object, name: str) -> str:
    text = _text(value, name)
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise ConcreteRuntimeConfigurationError(
            f"{name} must be a full lowercase SHA"
        )
    return text


def _directory(value: object, name: str) -> str:
    text = _text(os.fspath(value), name)
    normalized = os.path.abspath(os.path.normpath(text))
    if text != normalized or not os.path.isabs(text) or not os.path.isdir(text):
        raise ConcreteRuntimeConfigurationError(
            f"{name} must be an existing normalized absolute directory"
        )
    return text


def _positive(value: object, name: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConcreteRuntimeConfigurationError(f"{name} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0 < numeric <= maximum:
        raise ConcreteRuntimeConfigurationError(
            f"{name} exceeds the bounded policy"
        )
    return numeric


def _output_bound(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConcreteRuntimeConfigurationError(f"{name} must be an integer")
    if not 0 < value <= MAX_OUTPUT_BYTES:
        raise ConcreteRuntimeConfigurationError(
            f"{name} exceeds the bounded policy"
        )
    return value


def _argv(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        raise ConcreteRuntimeConfigurationError(
            f"{name} must be argv data, never a shell string"
        )
    items = tuple(value)
    if not items or len(items) > 64:
        raise ConcreteRuntimeConfigurationError(
            f"{name} has an invalid item count"
        )
    total = 0
    for item in items:
        if not isinstance(item, str) or not item or "\x00" in item:
            raise ConcreteRuntimeConfigurationError(
                f"{name} contains malformed argv"
            )
        if "${" in item or "$(" in item or "`" in item:
            raise ConcreteRuntimeConfigurationError(
                f"{name} contains shell interpolation syntax"
            )
        encoded = item.encode("utf-8")
        if len(encoded) > 4096:
            raise ConcreteRuntimeConfigurationError(
                f"{name} contains oversized argv"
            )
        total += len(encoded)
    if total > 262_144:
        raise ConcreteRuntimeConfigurationError(
            f"{name} exceeds the aggregate bound"
        )
    return items


def _paths(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        raise ConcreteRuntimeConfigurationError(f"{name} must be a tuple or list")
    items = tuple(value)
    if len(items) > MAX_ITEMS:
        raise ConcreteRuntimeConfigurationError(f"{name} exceeds the bounded count")
    for item in items:
        _text(item, name)
        base = (
            item[:-3]
            if item.endswith("/**")
            else item[:-1]
            if item.endswith("*")
            else item
        )
        if (
            "\\" in item
            or item.startswith("/")
            or any(part == ".." for part in item.split("/"))
            or not base
            or posixpath.normpath(base) != base
        ):
            raise ConcreteRuntimeConfigurationError(
                f"{name} contains a non-canonical path"
            )
    return items


def _workspace_path(pilot_input: SingleIssuePilotInput, parent: str) -> str:
    request = WorkspaceRequest(
        workspace_request_id=pilot_input.workspace_request_id,
        repository=pilot_input.repository,
        branch=pilot_input.branch,
        expected_revision=pilot_input.source_head_sha,
    )
    identity = pilot_workspace_identity(request)
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return os.path.join(parent, f"agent-os-worktree-{suffix}")


def _environment(configuration: "ConcreteRuntimeConfiguration") -> dict[str, str]:
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


@dataclass(frozen=True, slots=True, kw_only=True)
class ConcreteRuntimeConfiguration:
    """Immutable executable configuration for exactly one approved packet."""

    schema_name: str
    schema_version: str
    configuration_fingerprint: str
    execution_mode: RuntimeExecutionMode
    repository: str
    issue_number: int
    invocation_id: str
    workspace_request_id: str
    base_branch: str
    base_sha: str
    source_head_sha: str
    tested_sha: str
    branch: str
    projection_id: str
    approval_id: str
    validation_plan_id: str
    validation_bundle_id: str
    advisory_result_id: str
    advisory_render_id: str
    repository_identity: RepositoryIdentity
    repository_root: str
    workspace_parent: str
    # Executor process authority is structurally absent in validation-only
    # mode: there is no argv, so no unbound process can be dispatched.
    executor_argv: tuple[str, ...] | None
    executor_cwd: str
    environment_policy: Literal["isolated-path-home-c-locale"]
    executor_timeout_seconds: float
    executor_grace_period_seconds: float
    executor_max_output_bytes: int
    required_test_commands: tuple[FrozenTestCommand, ...]
    validation_per_command_timeout_seconds: float
    validation_total_timeout_seconds: float
    validation_max_output_bytes: int
    allowed_files: tuple[str, ...]
    forbidden_paths: tuple[str, ...]

    @classmethod
    def bind(
        cls,
        pilot_input: SingleIssuePilotInput,
        *,
        repository_identity: RepositoryIdentity,
        repository_root: str | os.PathLike[str],
        workspace_parent: str | os.PathLike[str],
        required_test_commands: tuple[FrozenTestCommand, ...],
        executor_argv: tuple[str, ...] | None = None,
        execution_mode: str = STANDARD_EXECUTION_MODE,
        executor_timeout_seconds: float = 30.0,
        executor_grace_period_seconds: float = 5.0,
        executor_max_output_bytes: int = MAX_OUTPUT_BYTES,
        validation_per_command_timeout_seconds: float = 30.0,
        validation_total_timeout_seconds: float = 300.0,
        validation_max_output_bytes: int = MAX_OUTPUT_BYTES,
        environment_policy: str = ENVIRONMENT_POLICY,
    ) -> "ConcreteRuntimeConfiguration":
        if (
            not isinstance(pilot_input, SingleIssuePilotInput)
            or len(pilot_input.issue_numbers) != 1
        ):
            raise ConcreteRuntimeConfigurationError(
                "exactly one canonical pilot issue is required"
            )
        if not isinstance(repository_identity, RepositoryIdentity):
            raise ConcreteRuntimeConfigurationError(
                "repository_identity must be RepositoryIdentity"
            )
        if execution_mode not in RUNTIME_EXECUTION_MODES:
            raise ConcreteRuntimeConfigurationError("unsupported execution mode")
        if execution_mode != pilot_input.execution_mode:
            raise ConcreteRuntimeConfigurationError("execution mode drifted")
        if execution_mode == VALIDATION_ONLY_EXECUTION_MODE:
            if executor_argv is not None:
                raise ConcreteRuntimeConfigurationError(
                    "validation-only mode has no executor process authority"
                )
            argv: tuple[str, ...] | None = None
        else:
            argv = _argv(executor_argv, "executor_argv")
        evidence_identity = getattr(
            pilot_input.repository_state_evidence, "repository_identity", None
        )
        if evidence_identity != repository_identity:
            raise ConcreteRuntimeConfigurationError("repository identity drifted")
        commands = tuple(required_test_commands)
        if not commands or any(
            not isinstance(item, FrozenTestCommand) for item in commands
        ):
            raise ConcreteRuntimeConfigurationError(
                "required_test_commands is malformed"
            )
        test_ids = tuple(item.test_id for item in commands)
        if (
            len(set(test_ids)) != len(test_ids)
            or test_ids != tuple(pilot_input.required_tests)
        ):
            raise ConcreteRuntimeConfigurationError(
                "required test identities are duplicate, missing, reordered, or unbound"
            )
        if tuple(getattr(pilot_input.validation_plan, "commands", ())) != test_ids:
            raise ConcreteRuntimeConfigurationError(
                "validation plan command identities drifted"
            )
        root = _directory(repository_root, "repository_root")
        parent = _directory(workspace_parent, "workspace_parent")
        values = {
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "execution_mode": execution_mode,
            "repository": _text(pilot_input.repository, "repository"),
            "issue_number": pilot_input.issue_numbers[0],
            "invocation_id": _text(pilot_input.invocation_id, "invocation_id"),
            "workspace_request_id": _text(
                pilot_input.workspace_request_id, "workspace_request_id"
            ),
            "base_branch": _text(pilot_input.base_branch, "base_branch"),
            "base_sha": _sha(pilot_input.base_sha, "base_sha"),
            "source_head_sha": _sha(
                pilot_input.source_head_sha, "source_head_sha"
            ),
            "tested_sha": _sha(pilot_input.tested_sha, "tested_sha"),
            "branch": _text(pilot_input.branch, "branch"),
            "projection_id": _text(
                pilot_input.expected_projection_id, "projection_id"
            ),
            "approval_id": _text(
                pilot_input.expected_approval_id, "approval_id"
            ),
            "validation_plan_id": _text(
                pilot_input.expected_plan_id, "validation_plan_id"
            ),
            "validation_bundle_id": _text(
                pilot_input.expected_bundle_id, "validation_bundle_id"
            ),
            "advisory_result_id": _text(
                pilot_input.expected_advisory_result_id, "advisory_result_id"
            ),
            "advisory_render_id": _text(
                pilot_input.expected_advisory_render_id, "advisory_render_id"
            ),
            "repository_identity": repository_identity,
            "repository_root": root,
            "workspace_parent": parent,
            "executor_argv": argv,
            "executor_cwd": _workspace_path(pilot_input, parent),
            "environment_policy": environment_policy,
            "executor_timeout_seconds": _positive(
                executor_timeout_seconds,
                "executor_timeout_seconds",
                MAX_TIMEOUT_SECONDS,
            ),
            "executor_grace_period_seconds": _positive(
                executor_grace_period_seconds,
                "executor_grace_period_seconds",
                MAX_TIMEOUT_SECONDS,
            ),
            "executor_max_output_bytes": _output_bound(
                executor_max_output_bytes, "executor_max_output_bytes"
            ),
            "required_test_commands": commands,
            "validation_per_command_timeout_seconds": _positive(
                validation_per_command_timeout_seconds,
                "validation_per_command_timeout_seconds",
                30.0,
            ),
            "validation_total_timeout_seconds": _positive(
                validation_total_timeout_seconds,
                "validation_total_timeout_seconds",
                300.0,
            ),
            "validation_max_output_bytes": _output_bound(
                validation_max_output_bytes, "validation_max_output_bytes"
            ),
            "allowed_files": _paths(pilot_input.allowed_files, "allowed_files"),
            "forbidden_paths": _paths(
                pilot_input.forbidden_paths, "forbidden_paths"
            ),
        }
        if environment_policy != ENVIRONMENT_POLICY:
            raise ConcreteRuntimeConfigurationError(
                "unsupported environment authority"
            )
        return cls(
            configuration_fingerprint=_fingerprint(_payload(values)),
            **values,
        )

    def __post_init__(self) -> None:
        if self.schema_name != SCHEMA_NAME or self.schema_version != SCHEMA_VERSION:
            raise ConcreteRuntimeConfigurationError(
                "unsupported concrete configuration schema"
            )
        if self.configuration_fingerprint != _fingerprint(_payload(self)):
            raise ConcreteRuntimeConfigurationError(
                "configuration fingerprint mismatch (tampered or stale)"
            )

    def verify(self, pilot_input: SingleIssuePilotInput) -> None:
        if not isinstance(pilot_input, SingleIssuePilotInput):
            raise ConcreteRuntimeConfigurationError(
                "pilot_input must be SingleIssuePilotInput"
            )
        if self.execution_mode not in RUNTIME_EXECUTION_MODES:
            raise ConcreteRuntimeConfigurationError("unsupported execution mode")
        expected = {
            "execution_mode": pilot_input.execution_mode,
            "repository": pilot_input.repository,
            "issue_number": (
                pilot_input.issue_numbers[0]
                if len(pilot_input.issue_numbers) == 1
                else None
            ),
            "invocation_id": pilot_input.invocation_id,
            "workspace_request_id": pilot_input.workspace_request_id,
            "base_branch": pilot_input.base_branch,
            "base_sha": pilot_input.base_sha,
            "source_head_sha": pilot_input.source_head_sha,
            "tested_sha": pilot_input.tested_sha,
            "branch": pilot_input.branch,
            "projection_id": pilot_input.expected_projection_id,
            "approval_id": pilot_input.expected_approval_id,
            "validation_plan_id": pilot_input.expected_plan_id,
            "validation_bundle_id": pilot_input.expected_bundle_id,
            "advisory_result_id": pilot_input.expected_advisory_result_id,
            "advisory_render_id": pilot_input.expected_advisory_render_id,
            "allowed_files": tuple(pilot_input.allowed_files),
            "forbidden_paths": tuple(pilot_input.forbidden_paths),
        }
        for name, value in expected.items():
            if getattr(self, name) != value:
                raise ConcreteRuntimeConfigurationError(f"{name} drifted")
        test_ids = tuple(item.test_id for item in self.required_test_commands)
        if test_ids != tuple(pilot_input.required_tests):
            raise ConcreteRuntimeConfigurationError(
                "required test identity or order drifted"
            )
        if tuple(getattr(pilot_input.validation_plan, "commands", ())) != test_ids:
            raise ConcreteRuntimeConfigurationError(
                "validation plan command identity drifted"
            )
        evidence_identity = getattr(
            pilot_input.repository_state_evidence, "repository_identity", None
        )
        if evidence_identity != self.repository_identity:
            raise ConcreteRuntimeConfigurationError("repository identity drifted")
        if self.executor_cwd != _workspace_path(
            pilot_input, self.workspace_parent
        ):
            raise ConcreteRuntimeConfigurationError("executor cwd drifted")
        if self.configuration_fingerprint != _fingerprint(_payload(self)):
            raise ConcreteRuntimeConfigurationError(
                "configuration fingerprint drifted"
            )


def _payload(configuration: object) -> dict[str, object]:
    get = (
        configuration.get
        if isinstance(configuration, dict)
        else lambda name: getattr(configuration, name)
    )
    identity: RepositoryIdentity = get("repository_identity")
    commands: tuple[FrozenTestCommand, ...] = tuple(
        get("required_test_commands")
    )
    scalar_names = (
        "schema_name",
        "schema_version",
        "execution_mode",
        "repository",
        "issue_number",
        "invocation_id",
        "workspace_request_id",
        "base_branch",
        "base_sha",
        "source_head_sha",
        "tested_sha",
        "branch",
        "projection_id",
        "approval_id",
        "validation_plan_id",
        "validation_bundle_id",
        "advisory_result_id",
        "advisory_render_id",
        "repository_root",
        "workspace_parent",
        "executor_cwd",
        "environment_policy",
        "executor_timeout_seconds",
        "executor_grace_period_seconds",
        "executor_max_output_bytes",
        "validation_per_command_timeout_seconds",
        "validation_total_timeout_seconds",
        "validation_max_output_bytes",
    )
    payload = {name: get(name) for name in scalar_names}
    payload.update(
        {
            "repository_identity": {
                "host": identity.host,
                "owner": identity.owner,
                "repository": identity.repository,
                "repository_id": identity.repository_id,
                "is_fork": identity.is_fork,
                "default_branch": identity.default_branch,
            },
            "executor_argv": (
                None
                if get("executor_argv") is None
                else list(get("executor_argv"))
            ),
            "required_test_commands": [
                {"test_id": item.test_id, "argv": list(item.argv)}
                for item in commands
            ],
            "allowed_files": list(get("allowed_files")),
            "forbidden_paths": list(get("forbidden_paths")),
        }
    )
    return payload


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
            item.test_id: item.argv
            for item in configuration.required_test_commands
        }
        self._attempted: set[str] = set()
        self.last_result: PosixProcessExecutionResult | None = None

    def run(self, request: CommandRunRequest) -> CommandRunObservation:
        if not isinstance(request, CommandRunRequest):
            raise TypeError("request must be CommandRunRequest")
        if self._commands.get(request.test_id) != tuple(request.argv):
            raise ConcreteRuntimeConfigurationError(
                "validation command is unbound"
            )
        if request.test_id in self._attempted:
            raise RuntimeError("a bound validation command may run at most once")
        self._attempted.add(request.test_id)
        result = run_bounded_posix_process(
            request.argv,
            timeout_seconds=min(
                request.timeout_seconds,
                self._configuration.validation_per_command_timeout_seconds,
            ),
            grace_period_seconds=(
                self._configuration.executor_grace_period_seconds
            ),
            max_output_bytes=(
                self._configuration.validation_max_output_bytes
            ),
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
                timeout_seconds=(
                    self._configuration.validation_per_command_timeout_seconds
                ),
                grace_period_seconds=(
                    self._configuration.executor_grace_period_seconds
                ),
                max_output_bytes=(
                    self._configuration.validation_max_output_bytes
                ),
                cwd=self._configuration.executor_cwd,
                env=_environment(self._configuration),
            )
            if (
                result.return_code != 0
                or not result.termination_confirmed
                or result.timeout_observed
                or result.cancellation_requested
            ):
                raise ConcreteRuntimeConfigurationError(
                    "changed paths inspection failed"
                )
            paths.extend(
                item for item in result.stdout_text.split("\x00") if item
            )
        return tuple(dict.fromkeys(paths))


@dataclass(frozen=True, slots=True, kw_only=True)
class ConcreteRuntimeAdapters:
    lease: InMemoryLeaseAdapter
    workspace: GitWorktreeAdapter
    # ``None`` in validation-only mode: no process executor is constructed,
    # rather than a no-op executor standing in for one.
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
    """Verify one binding and construct the merged adapters for this mode."""

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
        per_command_timeout_seconds=(
            configuration.validation_per_command_timeout_seconds
        ),
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
