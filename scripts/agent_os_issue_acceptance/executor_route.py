"""Pure deterministic executor-route selection for normalized Agent OS evidence.

The selector consumes caller-supplied projections only. It performs no GitHub,
network, filesystem, subprocess, environment, credential, or Scheduler I/O;
executes no work; mutates no lifecycle state; and creates no authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from .issue_operational_state import AuthorizationState, OperationalOutcome
from .operating_mode import OperatingModeOutcome, RequestedMode

EXECUTOR_ROUTE_DECISION_SCHEMA_NAME = "agent-os-executor-route-decision"
EXECUTOR_ROUTE_DECISION_SCHEMA_VERSION = "1.0"
MAX_ITEMS = 32
MAX_TEXT_BYTES = 1024
MAX_HANDOFF_LINES = 20
MAX_HANDOFF_BYTES = 8 * 1024
MAX_COMPACT_FIELD_BYTES = 512

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}:[0-9a-f]{64}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class ExecutorRoute(str, Enum):
    CHATGPT_CONNECTOR = "chatgpt_connector"
    GOVERNED_RUNNER = "governed_runner"
    EXTERNAL_FALLBACK = "external_fallback"
    HUMAN_DECISION = "human_decision"


class CapabilityState(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    INSUFFICIENT = "insufficient"
    UNKNOWN = "unknown"


class ExplicitExecutionSurface(str, Enum):
    AUTO = "auto"
    CHATGPT_CONNECTOR = "chatgpt_connector"
    GOVERNED_RUNNER = "governed_runner"
    EXTERNAL_FALLBACK = "external_fallback"


class RuntimeRequirement(str, Enum):
    CHECKOUT = "checkout"
    DEPENDENCIES = "dependencies"
    TESTS = "tests"
    BUILD_OR_LINT = "build-or-lint"
    GENERATED_ARTIFACTS = "generated-artifacts"
    RUNTIME_INSPECTION = "runtime-inspection"
    LOCAL_GIT = "local-git"
    CHECKPOINT_RESUME = "checkpoint-resume"


REASON_CODES = frozenset(
    {
        "state.blocked",
        "state.needs-decision",
        "state.stale",
        "state.conflicting",
        "state.terminal",
        "state.invalid",
        "mode.blocked",
        "mode.needs-decision",
        "mode.invalid",
        "authorization.not-authorized",
        "authorization.stale",
        "authorization.needs-decision",
        "authorization.not-applicable",
        "evidence.excluded-surface",
        "evidence.target-missing",
        "evidence.base-missing",
        "evidence.revision-missing",
        "evidence.revision-conflict",
        "evidence.stop-condition-missing",
        "capability.connector-available",
        "capability.connector-unavailable",
        "capability.connector-insufficient",
        "capability.connector-unknown",
        "capability.runner-available",
        "capability.runner-unavailable",
        "capability.runner-insufficient",
        "capability.runner-unknown",
        "capability.external-available",
        "capability.external-unavailable",
        "capability.external-insufficient",
        "capability.external-unknown",
        "runtime.required",
        "user.external-requested",
        "user.runner-requested",
        "user.connector-requested",
        "resume.route-preserved",
        "resume.route-invalid",
        "fallback.connector-and-runner-unavailable",
        "route.chatgpt-connector",
        "route.governed-runner",
        "route.external-fallback",
        "route.human-decision",
    }
)

_STATE_REASON = {
    OperationalOutcome.BLOCKED: "state.blocked",
    OperationalOutcome.NEEDS_DECISION: "state.needs-decision",
    OperationalOutcome.STALE: "state.stale",
    OperationalOutcome.CONFLICTING: "state.conflicting",
    OperationalOutcome.TERMINAL: "state.terminal",
    OperationalOutcome.INVALID: "state.invalid",
}
_MODE_REASON = {
    OperatingModeOutcome.BLOCKED: "mode.blocked",
    OperatingModeOutcome.NEEDS_DECISION: "mode.needs-decision",
    OperatingModeOutcome.INVALID: "mode.invalid",
}
_AUTHORIZATION_REASON = {
    AuthorizationState.NOT_AUTHORIZED: "authorization.not-authorized",
    AuthorizationState.STALE: "authorization.stale",
    AuthorizationState.NEEDS_DECISION: "authorization.needs-decision",
    AuthorizationState.NOT_APPLICABLE: "authorization.not-applicable",
}
_CAPABILITY_REASON = {
    "connector": {
        CapabilityState.AVAILABLE: "capability.connector-available",
        CapabilityState.UNAVAILABLE: "capability.connector-unavailable",
        CapabilityState.INSUFFICIENT: "capability.connector-insufficient",
        CapabilityState.UNKNOWN: "capability.connector-unknown",
    },
    "runner": {
        CapabilityState.AVAILABLE: "capability.runner-available",
        CapabilityState.UNAVAILABLE: "capability.runner-unavailable",
        CapabilityState.INSUFFICIENT: "capability.runner-insufficient",
        CapabilityState.UNKNOWN: "capability.runner-unknown",
    },
    "external": {
        CapabilityState.AVAILABLE: "capability.external-available",
        CapabilityState.UNAVAILABLE: "capability.external-unavailable",
        CapabilityState.INSUFFICIENT: "capability.external-insufficient",
        CapabilityState.UNKNOWN: "capability.external-unknown",
    },
}
_ROUTE_REASON = {
    ExecutorRoute.CHATGPT_CONNECTOR: "route.chatgpt-connector",
    ExecutorRoute.GOVERNED_RUNNER: "route.governed-runner",
    ExecutorRoute.EXTERNAL_FALLBACK: "route.external-fallback",
    ExecutorRoute.HUMAN_DECISION: "route.human-decision",
}


def _exact_text(value: object, name: str, maximum: int = MAX_TEXT_BYTES) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a built-in string")
    if len(value.encode("utf-8")) > maximum or _CONTROL_RE.search(value):
        raise ValueError(f"{name} is outside bounds")
    return value


def _required_text(value: object, name: str) -> str:
    text = _exact_text(value, name)
    if not text.strip():
        raise ValueError(f"{name} must not be blank")
    return text


def _enum(value: object, enum_type: type[Enum], name: str) -> Enum:
    if not isinstance(value, enum_type):
        raise TypeError(f"{name} must be {enum_type.__name__}")
    return value


def _canonical_enum_tuple(
    values: object, enum_type: type[Enum], name: str
) -> tuple[Enum, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    if len(values) > MAX_ITEMS:
        raise ValueError(f"{name} exceeds its bound")
    checked = tuple(_enum(value, enum_type, name) for value in values)
    if len(set(checked)) != len(checked):
        raise ValueError(f"{name} contains duplicates")
    return tuple(sorted(checked, key=lambda item: str(item.value)))


def _canonical_text_tuple(values: object, name: str) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    if len(values) > MAX_ITEMS:
        raise ValueError(f"{name} exceeds its bound")
    checked = tuple(_required_text(value, name) for value in values)
    if len(set(checked)) != len(checked):
        raise ValueError(f"{name} contains duplicates")
    return tuple(sorted(checked))


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _decision_id(payload: object) -> str:
    material = b"agent-os-executor-route-decision:v1\0" + _canonical_json(payload).encode(
        "utf-8"
    )
    return f"executor-route-decision:{hashlib.sha256(material).hexdigest()}"


def _compact_items(values: tuple[str, ...], fallback: str) -> str:
    if not values:
        return fallback
    suffix = f"; +{len(values) - 3} more" if len(values) > 3 else ""
    text = "; ".join(values[:3])
    budget = MAX_COMPACT_FIELD_BYTES - len(suffix.encode("utf-8"))
    encoded = text.encode("utf-8")
    if len(encoded) > budget:
        text = encoded[: max(0, budget - 3)].decode("utf-8", "ignore") + "..."
    return text + suffix


@dataclass(frozen=True, slots=True)
class ExecutorRouteEvidence:
    """Normalized evidence used only for executor capability routing."""

    source_operational_state_id: str
    operational_outcome: OperationalOutcome
    source_operating_mode_decision_id: str
    operating_mode_outcome: OperatingModeOutcome
    requested_mode: RequestedMode
    implementation_authorization: AuthorizationState
    target: str
    base_ref: str
    source_revision: str
    observed_revision: str
    stop_condition: str
    goal: str
    scope: tuple[str, ...]
    validation: tuple[str, ...]
    connector_state: CapabilityState
    runner_state: CapabilityState
    external_fallback_state: CapabilityState
    runtime_requirements: tuple[RuntimeRequirement, ...] = ()
    excluded_surfaces: tuple[str, ...] = ()
    explicit_surface: ExplicitExecutionSurface = ExplicitExecutionSurface.AUTO
    resume_route: ExecutorRoute | None = None
    resume_route_valid: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("source_operational_state_id", self.source_operational_state_id),
            ("source_operating_mode_decision_id", self.source_operating_mode_decision_id),
        ):
            if not _SHA256_ID_RE.fullmatch(_required_text(value, name)):
                raise ValueError(f"{name} is malformed")
        _enum(self.operational_outcome, OperationalOutcome, "operational_outcome")
        _enum(self.operating_mode_outcome, OperatingModeOutcome, "operating_mode_outcome")
        _enum(self.requested_mode, RequestedMode, "requested_mode")
        _enum(
            self.implementation_authorization,
            AuthorizationState,
            "implementation_authorization",
        )
        _exact_text(self.target, "target")
        _exact_text(self.base_ref, "base_ref")
        source_revision = _exact_text(self.source_revision, "source_revision")
        observed_revision = _exact_text(self.observed_revision, "observed_revision")
        if source_revision and not _SHA40_RE.fullmatch(source_revision):
            raise ValueError("source_revision must be a lowercase 40-character SHA")
        if observed_revision and not _SHA40_RE.fullmatch(observed_revision):
            raise ValueError("observed_revision must be a lowercase 40-character SHA")
        _exact_text(self.stop_condition, "stop_condition")
        _required_text(self.goal, "goal")
        object.__setattr__(self, "scope", _canonical_text_tuple(self.scope, "scope"))
        object.__setattr__(
            self, "validation", _canonical_text_tuple(self.validation, "validation")
        )
        _enum(self.connector_state, CapabilityState, "connector_state")
        _enum(self.runner_state, CapabilityState, "runner_state")
        _enum(
            self.external_fallback_state,
            CapabilityState,
            "external_fallback_state",
        )
        object.__setattr__(
            self,
            "runtime_requirements",
            _canonical_enum_tuple(
                self.runtime_requirements, RuntimeRequirement, "runtime_requirements"
            ),
        )
        object.__setattr__(
            self,
            "excluded_surfaces",
            _canonical_text_tuple(self.excluded_surfaces, "excluded_surfaces"),
        )
        _enum(self.explicit_surface, ExplicitExecutionSurface, "explicit_surface")
        if self.resume_route is not None:
            _enum(self.resume_route, ExecutorRoute, "resume_route")
        if type(self.resume_route_valid) is not bool:
            raise TypeError("resume_route_valid must be a built-in bool")
        if self.resume_route is None and self.resume_route_valid:
            raise ValueError("resume_route_valid requires resume_route")


@dataclass(frozen=True, slots=True)
class ExecutorRouteDecision:
    schema_name: Literal["agent-os-executor-route-decision"]
    schema_version: Literal["1.0"]
    route: ExecutorRoute
    reason_codes: tuple[str, ...]
    source_operational_state_id: str
    source_operating_mode_decision_id: str
    handoff: str | None
    decision_id: str = ""
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_name != EXECUTOR_ROUTE_DECISION_SCHEMA_NAME
            or self.schema_version != EXECUTOR_ROUTE_DECISION_SCHEMA_VERSION
        ):
            raise ValueError("unsupported executor-route decision schema")
        _enum(self.route, ExecutorRoute, "route")
        reasons = _canonical_text_tuple(self.reason_codes, "reason_codes")
        if any(reason not in REASON_CODES for reason in reasons):
            raise ValueError("reason_codes contains an unsupported value")
        if _ROUTE_REASON[self.route] not in reasons:
            raise ValueError("reason_codes must include the selected route")
        object.__setattr__(self, "reason_codes", reasons)
        for name, value in (
            ("source_operational_state_id", self.source_operational_state_id),
            ("source_operating_mode_decision_id", self.source_operating_mode_decision_id),
        ):
            if not _SHA256_ID_RE.fullmatch(_required_text(value, name)):
                raise ValueError(f"{name} is malformed")
        if self.route is ExecutorRoute.CHATGPT_CONNECTOR:
            if self.handoff is not None:
                raise ValueError("chatgpt_connector must not emit a handoff")
        else:
            if type(self.handoff) is not str:
                raise TypeError("handoff must be a built-in string")
            if not self.handoff.strip() or len(self.handoff.encode("utf-8")) > MAX_HANDOFF_BYTES:
                raise ValueError("handoff is outside bounds")
            if "\r" in self.handoff or any(
                _CONTROL_RE.search(line) for line in self.handoff.split("\n")
            ):
                raise ValueError("handoff contains unsupported control characters")
            if len(self.handoff.splitlines()) > MAX_HANDOFF_LINES:
                raise ValueError("handoff exceeds the line limit")
        payload = {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "route": self.route.value,
            "reason_codes": list(self.reason_codes),
            "source_operational_state_id": self.source_operational_state_id,
            "source_operating_mode_decision_id": self.source_operating_mode_decision_id,
            "handoff": self.handoff,
            "side_effects_performed": False,
        }
        expected_id = _decision_id(payload)
        if self.decision_id and self.decision_id != expected_id:
            raise ValueError("decision_id does not match canonical decision payload")
        if not self.decision_id:
            object.__setattr__(self, "decision_id", expected_id)


def _route_available(route: ExecutorRoute, evidence: ExecutorRouteEvidence) -> bool:
    if route is ExecutorRoute.CHATGPT_CONNECTOR:
        return (
            evidence.connector_state is CapabilityState.AVAILABLE
            and not evidence.runtime_requirements
        )
    if route is ExecutorRoute.GOVERNED_RUNNER:
        return evidence.runner_state is CapabilityState.AVAILABLE
    if route is ExecutorRoute.EXTERNAL_FALLBACK:
        return evidence.external_fallback_state is CapabilityState.AVAILABLE and (
            evidence.explicit_surface is ExplicitExecutionSurface.EXTERNAL_FALLBACK
            or (
                evidence.connector_state
                in {CapabilityState.UNAVAILABLE, CapabilityState.INSUFFICIENT}
                and evidence.runner_state
                in {CapabilityState.UNAVAILABLE, CapabilityState.INSUFFICIENT}
            )
        )
    return False


def _handoff_owner(route: ExecutorRoute) -> str:
    return {
        ExecutorRoute.GOVERNED_RUNNER: "@Runner",
        ExecutorRoute.EXTERNAL_FALLBACK: "@External",
        ExecutorRoute.HUMAN_DECISION: "@Human",
    }[route]


def format_executor_handoff(
    route: ExecutorRoute,
    evidence: ExecutorRouteEvidence,
    reason_codes: tuple[str, ...],
) -> str:
    """Render one compact handoff for every non-connector route."""

    if route is ExecutorRoute.CHATGPT_CONNECTOR:
        raise ValueError("chatgpt_connector does not require a handoff")
    reason_priority = (
        "state.",
        "mode.",
        "authorization.",
        "evidence.",
        "user.",
        "runtime.",
        "resume.",
        "fallback.",
        "capability.",
    )
    primary_reason = _ROUTE_REASON[route]
    for prefix in reason_priority:
        matched = next((reason for reason in reason_codes if reason.startswith(prefix)), None)
        if matched is not None:
            primary_reason = matched
            break
    lines = (
        _handoff_owner(route),
        f"Target: {evidence.target or '<missing>'}",
        f"Mode: {evidence.requested_mode.value}",
        f"Goal: {evidence.goal}",
        f"Route: {route.value}",
        f"Scope: {_compact_items(evidence.scope, 'governing issue scope')}",
        f"Validate: {_compact_items(evidence.validation, 'governing issue checks')}",
        f"Stop: {evidence.stop_condition or '<missing>'}",
        "Report: files, tests, docs, blockers, handoff, risks, branch, PR, exact-head",
        f"Reason: {primary_reason}",
    )
    return "\n".join(lines)


def _build_decision(
    route: ExecutorRoute,
    evidence: ExecutorRouteEvidence,
    reasons: set[str],
) -> ExecutorRouteDecision:
    reasons.add(_ROUTE_REASON[route])
    canonical_reasons = tuple(sorted(reasons))
    handoff = None if route is ExecutorRoute.CHATGPT_CONNECTOR else format_executor_handoff(
        route, evidence, canonical_reasons
    )
    return ExecutorRouteDecision(
        schema_name=EXECUTOR_ROUTE_DECISION_SCHEMA_NAME,
        schema_version=EXECUTOR_ROUTE_DECISION_SCHEMA_VERSION,
        route=route,
        reason_codes=canonical_reasons,
        source_operational_state_id=evidence.source_operational_state_id,
        source_operating_mode_decision_id=evidence.source_operating_mode_decision_id,
        handoff=handoff,
    )


def _human_decision_reasons(evidence: ExecutorRouteEvidence) -> set[str]:
    reasons: set[str] = set()
    if evidence.operational_outcome is not OperationalOutcome.READY:
        reasons.add(_STATE_REASON[evidence.operational_outcome])
    if evidence.operating_mode_outcome in _MODE_REASON:
        reasons.add(_MODE_REASON[evidence.operating_mode_outcome])
    if evidence.implementation_authorization is not AuthorizationState.AUTHORIZED:
        reasons.add(_AUTHORIZATION_REASON[evidence.implementation_authorization])
    if evidence.excluded_surfaces:
        reasons.add("evidence.excluded-surface")
    if not evidence.target.strip():
        reasons.add("evidence.target-missing")
    if not evidence.base_ref.strip():
        reasons.add("evidence.base-missing")
    if not evidence.source_revision.strip() or not evidence.observed_revision.strip():
        reasons.add("evidence.revision-missing")
    elif evidence.source_revision != evidence.observed_revision:
        reasons.add("evidence.revision-conflict")
    if not evidence.stop_condition.strip():
        reasons.add("evidence.stop-condition-missing")
    return reasons


def evaluate_executor_route(evidence: ExecutorRouteEvidence) -> ExecutorRouteDecision:
    """Select the lowest-compute safe route without granting authority."""

    if type(evidence) is not ExecutorRouteEvidence:
        raise TypeError("evidence must be an exact ExecutorRouteEvidence")

    reasons = _human_decision_reasons(evidence)
    if reasons:
        return _build_decision(ExecutorRoute.HUMAN_DECISION, evidence, reasons)

    for name, state in (
        ("connector", evidence.connector_state),
        ("runner", evidence.runner_state),
        ("external", evidence.external_fallback_state),
    ):
        reasons.add(_CAPABILITY_REASON[name][state])

    if evidence.explicit_surface is ExplicitExecutionSurface.EXTERNAL_FALLBACK:
        reasons.add("user.external-requested")
        route = (
            ExecutorRoute.EXTERNAL_FALLBACK
            if evidence.external_fallback_state is CapabilityState.AVAILABLE
            else ExecutorRoute.HUMAN_DECISION
        )
        return _build_decision(route, evidence, reasons)

    if evidence.explicit_surface is ExplicitExecutionSurface.GOVERNED_RUNNER:
        reasons.add("user.runner-requested")
        route = (
            ExecutorRoute.GOVERNED_RUNNER
            if evidence.runner_state is CapabilityState.AVAILABLE
            else ExecutorRoute.HUMAN_DECISION
        )
        return _build_decision(route, evidence, reasons)

    if evidence.explicit_surface is ExplicitExecutionSurface.CHATGPT_CONNECTOR:
        reasons.add("user.connector-requested")
        if (
            evidence.connector_state is CapabilityState.AVAILABLE
            and not evidence.runtime_requirements
        ):
            return _build_decision(ExecutorRoute.CHATGPT_CONNECTOR, evidence, reasons)

    if evidence.resume_route is not None:
        if evidence.resume_route_valid and _route_available(evidence.resume_route, evidence):
            reasons.add("resume.route-preserved")
            return _build_decision(evidence.resume_route, evidence, reasons)
        reasons.add("resume.route-invalid")

    if evidence.runtime_requirements:
        reasons.add("runtime.required")
        if evidence.runner_state is CapabilityState.AVAILABLE:
            return _build_decision(ExecutorRoute.GOVERNED_RUNNER, evidence, reasons)
        if evidence.runner_state is CapabilityState.UNKNOWN:
            return _build_decision(ExecutorRoute.HUMAN_DECISION, evidence, reasons)
        if evidence.external_fallback_state is CapabilityState.AVAILABLE:
            return _build_decision(ExecutorRoute.EXTERNAL_FALLBACK, evidence, reasons)
        return _build_decision(ExecutorRoute.HUMAN_DECISION, evidence, reasons)

    if evidence.connector_state is CapabilityState.AVAILABLE:
        return _build_decision(ExecutorRoute.CHATGPT_CONNECTOR, evidence, reasons)
    if evidence.connector_state is CapabilityState.UNKNOWN:
        return _build_decision(ExecutorRoute.HUMAN_DECISION, evidence, reasons)
    if evidence.runner_state is CapabilityState.AVAILABLE:
        return _build_decision(ExecutorRoute.GOVERNED_RUNNER, evidence, reasons)
    if evidence.runner_state is CapabilityState.UNKNOWN:
        return _build_decision(ExecutorRoute.HUMAN_DECISION, evidence, reasons)

    reasons.add("fallback.connector-and-runner-unavailable")
    if evidence.external_fallback_state is CapabilityState.AVAILABLE:
        return _build_decision(ExecutorRoute.EXTERNAL_FALLBACK, evidence, reasons)
    return _build_decision(ExecutorRoute.HUMAN_DECISION, evidence, reasons)
