"""Project declared pre-PR developer-loop requirements into #918 capabilities.

This adapter is a pure, non-authorizing join between the existing #1197
``RequiredEnvironmentSpec`` / ``DependencyReadinessEvidence`` contracts and the
existing #918 executor-routing capability vocabulary.  It does not select a new
route, parse issue prose, install dependencies, invoke a runner, or create
execution authority.

Callers feed the returned ``required_capabilities`` and evidence flags directly
into ``select_executor_route``.  A pre-PR developer loop therefore cannot appear
connector-native merely because GitHub read/write operations are available: the
normalized checkout/runtime/test requirements remain explicit routing inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from agent_os_execution_service.executor_routing import ExecutorCapability
from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
    RequiredEnvironmentSpec,
)


_PRE_PR_RUNTIME_CAPABILITIES = frozenset(
    {
        ExecutorCapability.CHECKOUT,
        ExecutorCapability.EXACT_HEAD_VALIDATION,
        ExecutorCapability.ISOLATED_WORKTREE,
        ExecutorCapability.PROCESS_EXECUTION,
        ExecutorCapability.RUNTIME_INSPECTION,
        ExecutorCapability.TEST_EXECUTION,
    }
)

_CONTRADICTORY_PREPARATION_STATUSES = frozenset(
    {
        DependencyPreparationStatus.SOURCE_UPDATE_REQUIRED,
        DependencyPreparationStatus.BLOCKED,
        DependencyPreparationStatus.FAILED,
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PrePrRuntimeCapabilityProjection:
    """Non-authorizing routing inputs for one normalized pre-PR developer loop."""

    required_environment_id: str
    dependency_readiness_evidence_id: str
    environment_health_evidence_id: str
    required_capabilities: tuple[ExecutorCapability, ...]
    dependency_preparation_status: DependencyPreparationStatus
    evidence_stale: bool
    evidence_contradictory: bool
    execution_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        for name in (
            "required_environment_id",
            "dependency_readiness_evidence_id",
            "environment_health_evidence_id",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError(f"{name} must be non-empty exact text")
        if type(self.required_capabilities) is not tuple:
            raise TypeError("required_capabilities must be an exact tuple")
        if any(
            type(item) is not ExecutorCapability for item in self.required_capabilities
        ):
            raise TypeError("required_capabilities must use exact ExecutorCapability values")
        canonical = tuple(sorted(set(self.required_capabilities), key=lambda item: item.value))
        if self.required_capabilities != canonical:
            raise ValueError("required_capabilities must be sorted and unique")
        if type(self.dependency_preparation_status) is not DependencyPreparationStatus:
            raise TypeError(
                "dependency_preparation_status must be exact DependencyPreparationStatus"
            )
        for name in ("evidence_stale", "evidence_contradictory"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")


def project_pre_pr_runtime_capabilities(
    *,
    required_environment: RequiredEnvironmentSpec,
    dependency_readiness: DependencyReadinessEvidence,
    evaluated_at: str,
    base_required_capabilities: tuple[ExecutorCapability, ...] = (),
) -> PrePrRuntimeCapabilityProjection:
    """Join #1197 runtime evidence into the existing #918 capability vocabulary.

    The function consumes only already-normalized contracts.  It never derives
    shell commands from issue prose.  ``base_required_capabilities`` preserves
    capabilities the caller already derived for the requested operation; this
    adapter only adds the minimum capabilities every executable pre-PR
    developer loop requires plus dependency installation when #1197 says an
    already-authorized preparation step is required.
    """

    if type(required_environment) is not RequiredEnvironmentSpec:
        raise TypeError("required_environment must be exact RequiredEnvironmentSpec")
    if type(dependency_readiness) is not DependencyReadinessEvidence:
        raise TypeError("dependency_readiness must be exact DependencyReadinessEvidence")
    if type(evaluated_at) is not str or not evaluated_at:
        raise TypeError("evaluated_at must be non-empty exact text")
    if type(base_required_capabilities) is not tuple:
        raise TypeError("base_required_capabilities must be an exact tuple")
    if any(type(item) is not ExecutorCapability for item in base_required_capabilities):
        raise TypeError(
            "base_required_capabilities must use exact ExecutorCapability values"
        )
    if tuple(sorted(set(base_required_capabilities), key=lambda item: item.value)) != (
        base_required_capabilities
    ):
        raise ValueError("base_required_capabilities must be sorted and unique")
    if not required_environment.required_validation_command_ids:
        raise ValueError(
            "pre-PR runtime compatibility requires normalized validation command identities"
        )

    required = set(base_required_capabilities) | set(_PRE_PR_RUNTIME_CAPABILITIES)
    if (
        dependency_readiness.preparation_status
        is DependencyPreparationStatus.PREPARATION_REQUIRED
    ):
        required.add(ExecutorCapability.DEPENDENCY_INSTALLATION)

    evidence_contradictory = any(
        (
            dependency_readiness.required_environment_id
            != required_environment.required_environment_id,
            dependency_readiness.package_root != required_environment.package_root,
            dependency_readiness.ecosystem is not required_environment.ecosystem,
            dependency_readiness.install_mode is not required_environment.install_mode,
            dependency_readiness.preparation_status
            in _CONTRADICTORY_PREPARATION_STATUSES,
        )
    )

    return PrePrRuntimeCapabilityProjection(
        required_environment_id=required_environment.required_environment_id,
        dependency_readiness_evidence_id=(
            dependency_readiness.dependency_readiness_evidence_id
        ),
        environment_health_evidence_id=(
            dependency_readiness.environment_health_evidence_id
        ),
        required_capabilities=tuple(sorted(required, key=lambda item: item.value)),
        dependency_preparation_status=dependency_readiness.preparation_status,
        evidence_stale=not dependency_readiness.is_current(evaluated_at),
        evidence_contradictory=evidence_contradictory,
    )
