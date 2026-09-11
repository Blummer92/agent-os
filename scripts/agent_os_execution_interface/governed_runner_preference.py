"""Provider preference for one existing #918 governed-runner route (#2299).

This module does not create an executor route, capability registry, transport,
authority model, validation plan, or Scheduler. It only chooses which already-
observed governed runtime should supply the single ``CHATGPT_GOVERNED_RUNNER``
input to #918. Codespaces is preferred for ordinary developer-loop work; GCE is
retained when Codespaces cannot satisfy the required capabilities or when the
caller has already classified the operation as requiring an autonomous VM host.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from agent_os_execution_service.executor_routing import ExecutorCapability


class GovernedRunnerKind(str, Enum):
    CODESPACES = "codespaces"
    GCE = "gce"


class GovernedRunnerPreferenceReason(str, Enum):
    CODESPACES_CAPABLE = "codespaces-capable"
    CODESPACES_UNAVAILABLE = "codespaces-unavailable"
    CODESPACES_STALE = "codespaces-stale"
    CODESPACES_MISSING_CAPABILITY = "codespaces-missing-capability"
    AUTONOMOUS_HOST_REQUIRED = "autonomous-host-required"
    GCE_CAPABLE = "gce-capable"
    GCE_UNAVAILABLE = "gce-unavailable"
    GCE_STALE = "gce-stale"
    GCE_MISSING_CAPABILITY = "gce-missing-capability"
    NO_CAPABLE_GOVERNED_RUNNER = "no-capable-governed-runner"


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernedRunnerCandidate:
    kind: GovernedRunnerKind
    available: bool
    current: bool
    capabilities: tuple[ExecutorCapability, ...]
    execution_surface_id: str
    environment_profile_id: str
    environment_health_evidence_id: str
    workflow_runtime_identity: str

    def __post_init__(self) -> None:
        if type(self.kind) is not GovernedRunnerKind:
            raise TypeError("kind must be an exact GovernedRunnerKind")
        if type(self.available) is not bool or type(self.current) is not bool:
            raise TypeError("available and current must be exact booleans")
        if type(self.capabilities) is not tuple or any(
            type(item) is not ExecutorCapability for item in self.capabilities
        ):
            raise TypeError("capabilities must contain exact ExecutorCapability values")
        ordered = tuple(sorted(self.capabilities, key=lambda item: item.value))
        if self.capabilities != ordered or len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("capabilities must be sorted and unique")
        for name in (
            "execution_surface_id",
            "environment_profile_id",
            "environment_health_evidence_id",
            "workflow_runtime_identity",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value or len(value) > 256 or any(ch.isspace() for ch in value):
                raise ValueError(f"{name} must be bounded non-whitespace text")


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernedRunnerPreference:
    selected: GovernedRunnerCandidate | None
    reason_codes: tuple[GovernedRunnerPreferenceReason, ...]
    rejected_kinds: tuple[GovernedRunnerKind, ...]
    execution_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def _candidate_reason(
    candidate: GovernedRunnerCandidate,
    required: frozenset[ExecutorCapability],
) -> GovernedRunnerPreferenceReason | None:
    if not candidate.available:
        return (
            GovernedRunnerPreferenceReason.CODESPACES_UNAVAILABLE
            if candidate.kind is GovernedRunnerKind.CODESPACES
            else GovernedRunnerPreferenceReason.GCE_UNAVAILABLE
        )
    if not candidate.current:
        return (
            GovernedRunnerPreferenceReason.CODESPACES_STALE
            if candidate.kind is GovernedRunnerKind.CODESPACES
            else GovernedRunnerPreferenceReason.GCE_STALE
        )
    if not required.issubset(frozenset(candidate.capabilities)):
        return (
            GovernedRunnerPreferenceReason.CODESPACES_MISSING_CAPABILITY
            if candidate.kind is GovernedRunnerKind.CODESPACES
            else GovernedRunnerPreferenceReason.GCE_MISSING_CAPABILITY
        )
    return None


def choose_governed_runner(
    *,
    required_capabilities: tuple[ExecutorCapability, ...],
    codespaces: GovernedRunnerCandidate,
    gce: GovernedRunnerCandidate,
    autonomous_host_required: bool = False,
) -> GovernedRunnerPreference:
    """Choose the runtime that should supply #918's one governed-runner input.

    ``autonomous_host_required`` is an upstream operation classification, not a
    new capability or authority flag. #2300 owns the detailed VM/containment
    boundary; #2299 only guarantees that such work never selects Codespaces.
    """
    if type(required_capabilities) is not tuple or any(
        type(item) is not ExecutorCapability for item in required_capabilities
    ):
        raise TypeError("required_capabilities must contain exact ExecutorCapability values")
    ordered = tuple(sorted(required_capabilities, key=lambda item: item.value))
    if required_capabilities != ordered or len(set(required_capabilities)) != len(required_capabilities):
        raise ValueError("required_capabilities must be sorted and unique")
    if type(codespaces) is not GovernedRunnerCandidate or codespaces.kind is not GovernedRunnerKind.CODESPACES:
        raise TypeError("codespaces must be the Codespaces candidate")
    if type(gce) is not GovernedRunnerCandidate or gce.kind is not GovernedRunnerKind.GCE:
        raise TypeError("gce must be the GCE candidate")
    if type(autonomous_host_required) is not bool:
        raise TypeError("autonomous_host_required must be an exact boolean")

    required = frozenset(required_capabilities)
    reasons: list[GovernedRunnerPreferenceReason] = []
    rejected: list[GovernedRunnerKind] = []

    if autonomous_host_required:
        reasons.append(GovernedRunnerPreferenceReason.AUTONOMOUS_HOST_REQUIRED)
        rejected.append(GovernedRunnerKind.CODESPACES)
    else:
        codespaces_rejection = _candidate_reason(codespaces, required)
        if codespaces_rejection is None:
            return GovernedRunnerPreference(
                selected=codespaces,
                reason_codes=(GovernedRunnerPreferenceReason.CODESPACES_CAPABLE,),
                rejected_kinds=(),
            )
        reasons.append(codespaces_rejection)
        rejected.append(GovernedRunnerKind.CODESPACES)

    gce_rejection = _candidate_reason(gce, required)
    if gce_rejection is None:
        reasons.append(GovernedRunnerPreferenceReason.GCE_CAPABLE)
        return GovernedRunnerPreference(
            selected=gce,
            reason_codes=tuple(reasons),
            rejected_kinds=tuple(rejected),
        )

    reasons.extend((gce_rejection, GovernedRunnerPreferenceReason.NO_CAPABLE_GOVERNED_RUNNER))
    rejected.append(GovernedRunnerKind.GCE)
    return GovernedRunnerPreference(
        selected=None,
        reason_codes=tuple(reasons),
        rejected_kinds=tuple(rejected),
    )


def executor_route_inputs(preference: GovernedRunnerPreference) -> dict[str, object]:
    """Project the selected runtime into the existing #918 input vocabulary."""
    if type(preference) is not GovernedRunnerPreference:
        raise TypeError("preference must be an exact GovernedRunnerPreference")
    selected = preference.selected
    if selected is None:
        return {
            "governed_runner_available": False,
            "governed_runner_capabilities": (),
            "environment_profile_id_or_none": None,
            "environment_health_evidence_id_or_none": None,
            "workflow_runtime_identity_or_none": None,
        }
    return {
        "governed_runner_available": True,
        "governed_runner_capabilities": selected.capabilities,
        "environment_profile_id_or_none": selected.environment_profile_id,
        "environment_health_evidence_id_or_none": selected.environment_health_evidence_id,
        "workflow_runtime_identity_or_none": selected.workflow_runtime_identity,
    }
