"""Pure construction and verification for the canonical WSC5 runtime configuration.

This module owns only immutable configuration data, validation, and deterministic
fingerprinting. It performs no subprocess execution, Git operations, worktree
creation, lease acquisition, Scheduler dispatch, workflow dispatch, network I/O,
credential access, persistence, or external-system writes.

The executable adapter layer imports this module and re-exports the configuration
classes for backward compatibility. Non-executing callers such as the #754
candidate-packet coordinator can import this module directly without making the
concrete execution adapters reachable.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import posixpath
from dataclasses import dataclass
from typing import Literal

from scripts.agent_os_execution_capabilities.models import RepositoryIdentity
from workflow_scheduler.execution.frozen_test_validation_adapter import FrozenTestCommand
from workflow_scheduler.execution.single_issue_pilot import (
    RUNTIME_EXECUTION_MODES,
    STANDARD_EXECUTION_MODE,
    VALIDATION_ONLY_EXECUTION_MODE,
    RuntimeExecutionMode,
    SingleIssuePilotInput,
    WorkspaceRequest,
    pilot_workspace_identity,
)

SCHEMA_NAME = "agent-os-wsc5b4-concrete-adapters"
SCHEMA_VERSION = "1.0"
ENVIRONMENT_POLICY = "isolated-path-home-c-locale"
MAX_TEXT_BYTES = 4096
MAX_ITEMS = 256
MAX_TIMEOUT_SECONDS = 300.0
MAX_OUTPUT_BYTES = 65_536


class ConcreteRuntimeConfigurationError(ValueError):
    """Raised before any executable adapter or process is invoked."""


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
        raise ConcreteRuntimeConfigurationError(f"{name} has an invalid item count")
    total = 0
    for item in items:
        if not isinstance(item, str) or not item or "\x00" in item:
            raise ConcreteRuntimeConfigurationError(f"{name} contains malformed argv")
        if "${" in item or "$(" in item or "`" in item:
            raise ConcreteRuntimeConfigurationError(
                f"{name} contains shell interpolation syntax"
            )
        encoded = item.encode("utf-8")
        if len(encoded) > 4096:
            raise ConcreteRuntimeConfigurationError(f"{name} contains oversized argv")
        total += len(encoded)
    if total > 262_144:
        raise ConcreteRuntimeConfigurationError(f"{name} exceeds the aggregate bound")
    return items


def _paths(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        raise ConcreteRuntimeConfigurationError(f"{name} must be a tuple or list")
    items = tuple(value)
    if len(items) > MAX_ITEMS:
        raise ConcreteRuntimeConfigurationError(f"{name} exceeds the bounded count")
    for item in items:
        _text(item, name)
        base = item[:-3] if item.endswith("/**") else item[:-1] if item.endswith("*") else item
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


@dataclass(frozen=True, slots=True, kw_only=True)
class ConcreteRuntimeConfiguration:
    """Immutable configuration for exactly one approved runtime packet.

    The object is data and verification evidence only. Constructing or verifying
    it performs no execution and grants no execution, merge, workflow, or external
    write authority.
    """

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
        if not commands or any(not isinstance(item, FrozenTestCommand) for item in commands):
            raise ConcreteRuntimeConfigurationError("required_test_commands is malformed")
        test_ids = tuple(item.test_id for item in commands)
        if len(set(test_ids)) != len(test_ids) or test_ids != tuple(pilot_input.required_tests):
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
            "workspace_request_id": _text(pilot_input.workspace_request_id, "workspace_request_id"),
            "base_branch": _text(pilot_input.base_branch, "base_branch"),
            "base_sha": _sha(pilot_input.base_sha, "base_sha"),
            "source_head_sha": _sha(pilot_input.source_head_sha, "source_head_sha"),
            "tested_sha": _sha(pilot_input.tested_sha, "tested_sha"),
            "branch": _text(pilot_input.branch, "branch"),
            "projection_id": _text(pilot_input.expected_projection_id, "projection_id"),
            "approval_id": _text(pilot_input.expected_approval_id, "approval_id"),
            "validation_plan_id": _text(pilot_input.expected_plan_id, "validation_plan_id"),
            "validation_bundle_id": _text(pilot_input.expected_bundle_id, "validation_bundle_id"),
            "advisory_result_id": _text(pilot_input.expected_advisory_result_id, "advisory_result_id"),
            "advisory_render_id": _text(pilot_input.expected_advisory_render_id, "advisory_render_id"),
            "repository_identity": repository_identity,
            "repository_root": root,
            "workspace_parent": parent,
            "executor_argv": argv,
            "executor_cwd": _workspace_path(pilot_input, parent),
            "environment_policy": environment_policy,
            "executor_timeout_seconds": _positive(
                executor_timeout_seconds, "executor_timeout_seconds", MAX_TIMEOUT_SECONDS
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
            "forbidden_paths": _paths(pilot_input.forbidden_paths, "forbidden_paths"),
        }
        if environment_policy != ENVIRONMENT_POLICY:
            raise ConcreteRuntimeConfigurationError("unsupported environment authority")
        return cls(configuration_fingerprint=_fingerprint(_payload(values)), **values)

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
            "issue_number": pilot_input.issue_numbers[0] if len(pilot_input.issue_numbers) == 1 else None,
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
        if self.executor_cwd != _workspace_path(pilot_input, self.workspace_parent):
            raise ConcreteRuntimeConfigurationError("executor cwd drifted")
        if self.configuration_fingerprint != _fingerprint(_payload(self)):
            raise ConcreteRuntimeConfigurationError("configuration fingerprint drifted")


def _payload(configuration: object) -> dict[str, object]:
    get = configuration.get if isinstance(configuration, dict) else lambda name: getattr(configuration, name)
    identity: RepositoryIdentity = get("repository_identity")
    commands: tuple[FrozenTestCommand, ...] = tuple(get("required_test_commands"))
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
                "upstream_owner": identity.upstream_owner,
                "upstream_repository": identity.upstream_repository,
                "upstream_repository_id": identity.upstream_repository_id,
                "default_branch": identity.default_branch,
            },
            "executor_argv": None if get("executor_argv") is None else list(get("executor_argv")),
            "required_test_commands": [
                {"test_id": item.test_id, "argv": list(item.argv)} for item in commands
            ],
            "allowed_files": list(get("allowed_files")),
            "forbidden_paths": list(get("forbidden_paths")),
        }
    )
    return payload


def runtime_configuration_payload(
    configuration: ConcreteRuntimeConfiguration,
) -> dict[str, object]:
    """Return the canonical fingerprint payload for deterministic evidence/tests."""
    if type(configuration) is not ConcreteRuntimeConfiguration:
        raise TypeError("configuration must be exact ConcreteRuntimeConfiguration")
    return _payload(configuration)
