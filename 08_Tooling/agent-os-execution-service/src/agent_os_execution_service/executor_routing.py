"""Pure deterministic executor routing for already-approved Agent OS work.

The module selects an execution surface and builds immutable handoff evidence.
It performs no filesystem, process, network, GitHub, provider, credential,
workflow, runner, persistence, clock-read, or external-system operation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

EXECUTOR_ROUTING_SCHEMA_VERSION = "1.0"
MAX_IDENTIFIER_LENGTH = 256
MAX_OPERATION_LENGTH = 256
MAX_CAPABILITIES = 12
MAX_REASONS = 18
MAX_INVALIDATION_CONDITIONS = 32
MAX_PATHS = 256
MAX_PATH_LENGTH = 512
MAX_EVIDENCE_ITEMS = 64

__all__ = [
    "EXECUTOR_ROUTING_SCHEMA_VERSION",
    "ExecutorRoute",
    "ExecutorRouteReason",
    "ExecutorCapability",
    "ExecutorRouteDecision",
    "ExecutorHandoff",
    "select_executor_route",
    "build_executor_handoff",
    "serialize_executor_route_decision",
    "executor_route_decision_id",
    "executor_handoff_id",
]

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$", re.ASCII)
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
    re.ASCII,
)


class ExecutorRoute(str, Enum):
    """Closed vocabulary of execution surfaces selected by the router."""

    CHATGPT_CONNECTOR_NATIVE = "chatgpt-connector-native"
    CHATGPT_GOVERNED_RUNNER = "chatgpt-governed-runner"
    EXTERNAL_CODING_AGENT_FALLBACK = "external-coding-agent-fallback"
    HUMAN_DECISION_REQUIRED = "human-decision-required"


class ExecutorCapability(str, Enum):
    """Finite routing-only vocabulary for runtime capability requirements."""

    CHECKOUT = "checkout"
    ISOLATED_WORKTREE = "isolated-worktree"
    DEPENDENCY_INSTALLATION = "dependency-installation"
    PROCESS_EXECUTION = "process-execution"
    COMPILE_OR_LINT = "compile-or-lint"
    TEST_EXECUTION = "test-execution"
    RUNTIME_INSPECTION = "runtime-inspection"
    GENERATED_ARTIFACT_INSPECTION = "generated-artifact-inspection"
    MULTI_FILE_IMPLEMENTATION = "multi-file-implementation"
    GIT_RECONCILIATION = "git-reconciliation"
    EXACT_HEAD_VALIDATION = "exact-head-validation"
    CHECKPOINTED_RESUME = "checkpointed-resume"


class ExecutorRouteReason(str, Enum):
    """Finite reason codes explaining deterministic route selection."""

    CONNECTOR_SUFFICIENT = "connector-sufficient"
    RUNTIME_CAPABILITY_REQUIRED = "runtime-capability-required"
    GOVERNED_RUNNER_CAPABLE = "governed-runner-capable"
    GOVERNED_RUNNER_UNAVAILABLE = "governed-runner-unavailable"
    GOVERNED_RUNNER_MISSING_REQUIRED_CAPABILITY = (
        "governed-runner-missing-required-capability"
    )
    EXTERNAL_FALLBACK_EXPLICITLY_PERMITTED = (
        "external-fallback-explicitly-permitted"
    )
    EXTERNAL_FALLBACK_UNAVAILABLE = "external-fallback-unavailable"
    EXTERNAL_FALLBACK_NOT_PERMITTED = "external-fallback-not-permitted"
    AUTHORITY_AMBIGUOUS = "authority-ambiguous"
    OWNERSHIP_AMBIGUOUS = "ownership-ambiguous"
    SOURCE_OF_TRUTH_AMBIGUOUS = "source-of-truth-ambiguous"
    TARGET_AMBIGUOUS = "target-ambiguous"
    SCOPE_AMBIGUOUS = "scope-ambiguous"
    EXCLUDED_SURFACE_INVOLVED = "excluded-surface-involved"
    EVIDENCE_STALE = "evidence-stale"
    EVIDENCE_CONTRADICTORY = "evidence-contradictory"
    IRREVERSIBLE_OR_UNCERTAIN_MUTATION = "irreversible-or-uncertain-mutation"
    NO_CAPABLE_APPROVED_ROUTE = "no-capable-approved-route"


_ROUTE_ORDER = (
    ExecutorRoute.CHATGPT_CONNECTOR_NATIVE,
    ExecutorRoute.CHATGPT_GOVERNED_RUNNER,
    ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK,
    ExecutorRoute.HUMAN_DECISION_REQUIRED,
)
_HUMAN_FLAG_REASONS = (
    ("authority_ambiguous", ExecutorRouteReason.AUTHORITY_AMBIGUOUS),
    ("ownership_ambiguous", ExecutorRouteReason.OWNERSHIP_AMBIGUOUS),
    ("source_of_truth_ambiguous", ExecutorRouteReason.SOURCE_OF_TRUTH_AMBIGUOUS),
    ("target_ambiguous", ExecutorRouteReason.TARGET_AMBIGUOUS),
    ("scope_ambiguous", ExecutorRouteReason.SCOPE_AMBIGUOUS),
    ("excluded_surface_involved", ExecutorRouteReason.EXCLUDED_SURFACE_INVOLVED),
    ("evidence_stale", ExecutorRouteReason.EVIDENCE_STALE),
    ("evidence_contradictory", ExecutorRouteReason.EVIDENCE_CONTRADICTORY),
    (
        "irreversible_or_uncertain_mutation",
        ExecutorRouteReason.IRREVERSIBLE_OR_UNCERTAIN_MUTATION,
    ),
)
_VALIDATION_CAPABILITIES = frozenset(
    {
        ExecutorCapability.COMPILE_OR_LINT,
        ExecutorCapability.TEST_EXECUTION,
        ExecutorCapability.EXACT_HEAD_VALIDATION,
    }
)
_AUTHORITY_FIELDS = (
    "execution_authorized",
    "github_writes_authorized",
    "external_writes_authorized",
    "merge_authorized",
)


def _exact_bool(name: str, value: object) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be an exact boolean")
    return value


def _exact_string(
    name: str,
    value: object,
    maximum: int = MAX_IDENTIFIER_LENGTH,
) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if not value or len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{name} is empty or exceeds its byte bound")
    return value


def _identifier(
    name: str,
    value: object | None,
    *,
    required: bool = False,
) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{name} is required")
        return None
    text = _exact_string(name, value)
    if not _IDENTIFIER_RE.fullmatch(text):
        raise ValueError(f"{name} must use bounded ASCII identifier syntax")
    return text


def _repository(value: object) -> str:
    text = _exact_string("repository", value)
    if not _REPOSITORY_RE.fullmatch(text):
        raise ValueError("repository must use owner/name syntax")
    return text


def _timestamp(name: str, value: object) -> datetime:
    text = _exact_string(name, value, 20)
    if not _TIMESTAMP_RE.fullmatch(text):
        raise ValueError(f"{name} must be canonical UTC seconds ending in Z")
    parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != text:
        raise ValueError(f"{name} is not canonical")
    return parsed


def _enum_tuple(
    name: str,
    value: object,
    enum_type: type[Enum],
    maximum: int,
) -> tuple:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds its item bound")
    if not all(type(item) is enum_type for item in value):
        raise TypeError(f"{name} must contain exact {enum_type.__name__} values")
    ordered = tuple(sorted(value, key=lambda item: item.value))
    if value != ordered or len(set(value)) != len(value):
        raise ValueError(f"{name} must be sorted and unique")
    return value


def _string_tuple(
    name: str,
    value: object,
    maximum: int = MAX_EVIDENCE_ITEMS,
) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds its item bound")
    checked = tuple(_identifier(name, item, required=True) for item in value)
    if checked != tuple(sorted(checked)) or len(set(checked)) != len(checked):
        raise ValueError(f"{name} must be sorted and unique")
    return checked


def _path_tuple(name: str, value: object) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    if len(value) > MAX_PATHS:
        raise ValueError(f"{name} exceeds its item bound")
    checked: list[str] = []
    for item in value:
        text = _exact_string(name, item, MAX_PATH_LENGTH)
        if text.startswith("/") or "\\" in text or any(
            part in {"", ".", ".."} for part in text.split("/")
        ):
            raise ValueError(f"{name} contains an unsafe repository path")
        checked.append(text)
    result = tuple(checked)
    if result != tuple(sorted(result)) or len(set(result)) != len(result):
        raise ValueError(f"{name} must be sorted and unique")
    return result


def _paths_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(
        left + "/"
    )


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _digest(domain: str, payload: object) -> str:
    material = f"{domain}:v1\0".encode("ascii") + _canonical_json(payload).encode(
        "utf-8"
    )
    return f"{domain}:{hashlib.sha256(material).hexdigest()}"


def _list_field(payload: dict[str, object], name: str) -> list[object]:
    value = payload[name]
    if type(value) is not list:
        raise TypeError(f"{name} must be an exact array")
    return value


def _expected_route(
    *,
    required_capabilities: tuple[ExecutorCapability, ...],
    governed_runner_capabilities: tuple[ExecutorCapability, ...],
    governed_runner_available: bool,
    external_fallback_available: bool,
    external_fallback_explicitly_permitted: bool,
    human_flags: dict[str, bool],
) -> tuple[
    ExecutorRoute,
    tuple[ExecutorRouteReason, ...],
    tuple[ExecutorRoute, ...],
]:
    human_reasons = tuple(
        reason for name, reason in _HUMAN_FLAG_REASONS if human_flags[name]
    )
    if human_reasons:
        return (
            ExecutorRoute.HUMAN_DECISION_REQUIRED,
            tuple(sorted(human_reasons, key=lambda item: item.value)),
            _ROUTE_ORDER[:-1],
        )
    if not required_capabilities:
        return (
            ExecutorRoute.CHATGPT_CONNECTOR_NATIVE,
            (ExecutorRouteReason.CONNECTOR_SUFFICIENT,),
            (),
        )

    required = frozenset(required_capabilities)
    available = frozenset(governed_runner_capabilities)
    if governed_runner_available and required.issubset(available):
        return (
            ExecutorRoute.CHATGPT_GOVERNED_RUNNER,
            tuple(
                sorted(
                    (
                        ExecutorRouteReason.RUNTIME_CAPABILITY_REQUIRED,
                        ExecutorRouteReason.GOVERNED_RUNNER_CAPABLE,
                    ),
                    key=lambda item: item.value,
                )
            ),
            _ROUTE_ORDER[:1],
        )

    runner_reason = (
        ExecutorRouteReason.GOVERNED_RUNNER_UNAVAILABLE
        if not governed_runner_available
        else ExecutorRouteReason.GOVERNED_RUNNER_MISSING_REQUIRED_CAPABILITY
    )
    if external_fallback_available and external_fallback_explicitly_permitted:
        return (
            ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK,
            tuple(
                sorted(
                    (
                        ExecutorRouteReason.RUNTIME_CAPABILITY_REQUIRED,
                        runner_reason,
                        ExecutorRouteReason.EXTERNAL_FALLBACK_EXPLICITLY_PERMITTED,
                    ),
                    key=lambda item: item.value,
                )
            ),
            _ROUTE_ORDER[:2],
        )

    reasons = {
        ExecutorRouteReason.RUNTIME_CAPABILITY_REQUIRED,
        runner_reason,
        ExecutorRouteReason.NO_CAPABLE_APPROVED_ROUTE,
    }
    if not external_fallback_available:
        reasons.add(ExecutorRouteReason.EXTERNAL_FALLBACK_UNAVAILABLE)
    if not external_fallback_explicitly_permitted:
        reasons.add(ExecutorRouteReason.EXTERNAL_FALLBACK_NOT_PERMITTED)
    return (
        ExecutorRoute.HUMAN_DECISION_REQUIRED,
        tuple(sorted(reasons, key=lambda item: item.value)),
        _ROUTE_ORDER[:-1],
    )


def _authority_is_present(value: object) -> bool:
    return any(getattr(value, name) for name in _AUTHORITY_FIELDS)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutorRouteDecision:
    """Immutable, content-addressed decision selecting one execution surface."""

    schema_version: str
    repository: str
    issue_or_handoff_identity: str
    requested_operation: str
    required_capabilities: tuple[ExecutorCapability, ...]
    governed_runner_capabilities: tuple[ExecutorCapability, ...]
    governed_runner_available: bool
    external_fallback_available: bool
    external_fallback_explicitly_permitted: bool
    selected_route: ExecutorRoute
    route_reasons: tuple[ExecutorRouteReason, ...]
    rejected_lower_cost_routes: tuple[ExecutorRoute, ...]
    authority_ambiguous: bool = False
    ownership_ambiguous: bool = False
    source_of_truth_ambiguous: bool = False
    target_ambiguous: bool = False
    scope_ambiguous: bool = False
    excluded_surface_involved: bool = False
    evidence_stale: bool = False
    evidence_contradictory: bool = False
    irreversible_or_uncertain_mutation: bool = False
    execution_service_request_fingerprint_or_none: str | None = None
    authorization_id_or_none: str | None = None
    validation_command_plan_id_or_none: str | None = None
    operating_mode_decision_id_or_none: str | None = None
    executable_lane_selection_id_or_none: str | None = None
    repository_state_evidence_id_or_none: str | None = None
    worktree_preparation_evidence_id_or_none: str | None = None
    exact_head_package_id_or_none: str | None = None
    environment_profile_id_or_none: str | None = None
    environment_health_evidence_id_or_none: str | None = None
    checkpoint_id_or_none: str | None = None
    resume_plan_id_or_none: str | None = None
    workflow_runtime_identity_or_none: str | None = None
    execution_authorized: bool = False
    github_writes_authorized: bool = False
    external_writes_authorized: bool = False
    merge_authorized: bool = False
    created_at: str = ""
    expires_at: str = ""
    invalidation_conditions: tuple[str, ...] = ()
    decision_id: str = ""
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTOR_ROUTING_SCHEMA_VERSION:
            raise ValueError("schema_version is unsupported")
        _repository(self.repository)
        _identifier(
            "issue_or_handoff_identity",
            self.issue_or_handoff_identity,
            required=True,
        )
        _exact_string(
            "requested_operation",
            self.requested_operation,
            MAX_OPERATION_LENGTH,
        )
        _enum_tuple(
            "required_capabilities",
            self.required_capabilities,
            ExecutorCapability,
            MAX_CAPABILITIES,
        )
        _enum_tuple(
            "governed_runner_capabilities",
            self.governed_runner_capabilities,
            ExecutorCapability,
            MAX_CAPABILITIES,
        )
        for name in (
            "governed_runner_available",
            "external_fallback_available",
            "external_fallback_explicitly_permitted",
            "authority_ambiguous",
            "ownership_ambiguous",
            "source_of_truth_ambiguous",
            "target_ambiguous",
            "scope_ambiguous",
            "excluded_surface_involved",
            "evidence_stale",
            "evidence_contradictory",
            "irreversible_or_uncertain_mutation",
            *_AUTHORITY_FIELDS,
        ):
            _exact_bool(name, getattr(self, name))
        if type(self.selected_route) is not ExecutorRoute:
            raise TypeError("selected_route must be an exact ExecutorRoute")
        _enum_tuple(
            "route_reasons",
            self.route_reasons,
            ExecutorRouteReason,
            MAX_REASONS,
        )
        _enum_tuple(
            "rejected_lower_cost_routes",
            self.rejected_lower_cost_routes,
            ExecutorRoute,
            len(_ROUTE_ORDER),
        )

        human_flags = {
            name: getattr(self, name) for name, _ in _HUMAN_FLAG_REASONS
        }
        expected_route, expected_reasons, expected_rejected = _expected_route(
            required_capabilities=self.required_capabilities,
            governed_runner_capabilities=self.governed_runner_capabilities,
            governed_runner_available=self.governed_runner_available,
            external_fallback_available=self.external_fallback_available,
            external_fallback_explicitly_permitted=(
                self.external_fallback_explicitly_permitted
            ),
            human_flags=human_flags,
        )
        if self.selected_route is not expected_route:
            raise ValueError(
                "selected_route does not match deterministic routing inputs"
            )
        if self.route_reasons != expected_reasons:
            raise ValueError(
                "route_reasons do not match deterministic routing inputs"
            )
        if self.rejected_lower_cost_routes != expected_rejected:
            raise ValueError(
                "rejected_lower_cost_routes do not match selected route"
            )

        identity_names = (
            "execution_service_request_fingerprint_or_none",
            "authorization_id_or_none",
            "validation_command_plan_id_or_none",
            "operating_mode_decision_id_or_none",
            "executable_lane_selection_id_or_none",
            "repository_state_evidence_id_or_none",
            "worktree_preparation_evidence_id_or_none",
            "exact_head_package_id_or_none",
            "environment_profile_id_or_none",
            "environment_health_evidence_id_or_none",
            "checkpoint_id_or_none",
            "resume_plan_id_or_none",
            "workflow_runtime_identity_or_none",
        )
        for name in identity_names:
            _identifier(name, getattr(self, name))
        for name in (
            "execution_service_request_fingerprint_or_none",
            "operating_mode_decision_id_or_none",
            "executable_lane_selection_id_or_none",
        ):
            if getattr(self, name) is None:
                raise ValueError(f"{name} is required for every route decision")
        if _authority_is_present(self) and self.authorization_id_or_none is None:
            raise ValueError(
                "authorization_id_or_none is required when authority is supplied"
            )

        required = frozenset(self.required_capabilities)
        if self.selected_route is not ExecutorRoute.HUMAN_DECISION_REQUIRED:
            if (
                required & _VALIDATION_CAPABILITIES
                and self.validation_command_plan_id_or_none is None
            ):
                raise ValueError(
                    "validation_command_plan_id_or_none is required for validation capabilities"
                )
            if ExecutorCapability.CHECKPOINTED_RESUME in required and (
                self.checkpoint_id_or_none is None
                or self.resume_plan_id_or_none is None
            ):
                raise ValueError(
                    "checkpoint and resume identities are required for checkpointed resume"
                )
        if self.selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER:
            for name in (
                "environment_profile_id_or_none",
                "environment_health_evidence_id_or_none",
                "workflow_runtime_identity_or_none",
            ):
                if getattr(self, name) is None:
                    raise ValueError(
                        f"{name} is required for governed-runner routing"
                    )
        if (
            self.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED
            and _authority_is_present(self)
        ):
            raise ValueError(
                "human-decision routes must reduce authority fields to false"
            )

        created = _timestamp("created_at", self.created_at)
        expires = _timestamp("expires_at", self.expires_at)
        if expires <= created:
            raise ValueError("expires_at must be after created_at")
        _string_tuple(
            "invalidation_conditions",
            self.invalidation_conditions,
            MAX_INVALIDATION_CONDITIONS,
        )
        computed = executor_route_decision_id(self)
        if self.decision_id:
            _identifier("decision_id", self.decision_id, required=True)
            if self.decision_id != computed:
                raise ValueError("decision_id does not match decision content")
        object.__setattr__(self, "decision_id", computed)

    def to_dict(self) -> dict[str, object]:
        """Return the complete canonical JSON-compatible decision object."""

        return _decision_payload(self, include_id=True)

    @classmethod
    def from_dict(cls, payload: object) -> "ExecutorRouteDecision":
        """Validate and deserialize one strict decision object."""

        if type(payload) is not dict:
            raise TypeError("route decision must be an exact object")
        expected = {item.name for item in fields(cls)}
        if set(payload) != expected:
            raise ValueError("route decision contains unknown or missing fields")
        if payload["side_effects_performed"] is not False:
            raise ValueError("side_effects_performed must be false")
        values = dict(payload)
        values.pop("side_effects_performed")
        values["required_capabilities"] = tuple(
            ExecutorCapability(item)
            for item in _list_field(values, "required_capabilities")
        )
        values["governed_runner_capabilities"] = tuple(
            ExecutorCapability(item)
            for item in _list_field(values, "governed_runner_capabilities")
        )
        values["selected_route"] = ExecutorRoute(values["selected_route"])
        values["route_reasons"] = tuple(
            ExecutorRouteReason(item)
            for item in _list_field(values, "route_reasons")
        )
        values["rejected_lower_cost_routes"] = tuple(
            ExecutorRoute(item)
            for item in _list_field(values, "rejected_lower_cost_routes")
        )
        values["invalidation_conditions"] = tuple(
            _list_field(values, "invalidation_conditions")
        )
        return cls(**values)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutorHandoff:
    """Immutable handoff for governed-runner or explicit fallback execution."""

    schema_version: str
    route_decision_id: str
    destination_route: ExecutorRoute
    repository: str
    issue_or_handoff_identity: str
    requested_operation: str
    source_ref_or_none: str | None
    source_sha_or_none: str | None
    required_capabilities: tuple[ExecutorCapability, ...]
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    execution_service_request_fingerprint_or_none: str | None
    authorization_id_or_none: str | None
    validation_command_plan_id_or_none: str | None
    checkpoint_id_or_none: str | None
    resume_plan_id_or_none: str | None
    environment_profile_id_or_none: str | None
    required_return_evidence: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    execution_authorized: bool = False
    github_writes_authorized: bool = False
    external_writes_authorized: bool = False
    merge_authorized: bool = False
    handoff_id: str = ""
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTOR_ROUTING_SCHEMA_VERSION:
            raise ValueError("schema_version is unsupported")
        _identifier("route_decision_id", self.route_decision_id, required=True)
        if type(self.destination_route) is not ExecutorRoute:
            raise TypeError("destination_route must be an exact ExecutorRoute")
        if self.destination_route not in {
            ExecutorRoute.CHATGPT_GOVERNED_RUNNER,
            ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK,
        }:
            raise ValueError(
                "destination_route does not support an executor handoff"
            )
        _repository(self.repository)
        _identifier(
            "issue_or_handoff_identity",
            self.issue_or_handoff_identity,
            required=True,
        )
        _exact_string(
            "requested_operation",
            self.requested_operation,
            MAX_OPERATION_LENGTH,
        )
        if self.source_ref_or_none is not None:
            _identifier("source_ref_or_none", self.source_ref_or_none)
        if self.source_sha_or_none is not None:
            sha = _exact_string("source_sha_or_none", self.source_sha_or_none, 40)
            if not _SHA40_RE.fullmatch(sha):
                raise ValueError(
                    "source_sha_or_none must be a lowercase SHA-1 digest"
                )
        _enum_tuple(
            "required_capabilities",
            self.required_capabilities,
            ExecutorCapability,
            MAX_CAPABILITIES,
        )
        allowed = _path_tuple("allowed_paths", self.allowed_paths)
        forbidden = _path_tuple("forbidden_paths", self.forbidden_paths)
        if any(
            _paths_overlap(left, right)
            for left in allowed
            for right in forbidden
        ):
            raise ValueError("allowed_paths and forbidden_paths must not overlap")
        for name in (
            "execution_service_request_fingerprint_or_none",
            "authorization_id_or_none",
            "validation_command_plan_id_or_none",
            "checkpoint_id_or_none",
            "resume_plan_id_or_none",
            "environment_profile_id_or_none",
        ):
            _identifier(name, getattr(self, name))
        _string_tuple("required_return_evidence", self.required_return_evidence)
        _string_tuple("stop_conditions", self.stop_conditions)
        for name in _AUTHORITY_FIELDS:
            _exact_bool(name, getattr(self, name))
        if _authority_is_present(self) and self.authorization_id_or_none is None:
            raise ValueError(
                "authorization_id_or_none is required when authority is supplied"
            )
        required = frozenset(self.required_capabilities)
        if (
            required & _VALIDATION_CAPABILITIES
            and self.validation_command_plan_id_or_none is None
        ):
            raise ValueError(
                "validation_command_plan_id_or_none is required for validation capabilities"
            )
        if ExecutorCapability.CHECKPOINTED_RESUME in required and (
            self.checkpoint_id_or_none is None
            or self.resume_plan_id_or_none is None
        ):
            raise ValueError(
                "checkpoint and resume identities are required for checkpointed resume"
            )
        computed = executor_handoff_id(self)
        if self.handoff_id:
            _identifier("handoff_id", self.handoff_id, required=True)
            if self.handoff_id != computed:
                raise ValueError("handoff_id does not match handoff content")
        object.__setattr__(self, "handoff_id", computed)

    def to_dict(self) -> dict[str, object]:
        """Return the complete canonical JSON-compatible handoff object."""

        return _handoff_payload(self, include_id=True)

    @classmethod
    def from_dict(cls, payload: object) -> "ExecutorHandoff":
        """Validate and deserialize one strict executor handoff object."""

        if type(payload) is not dict:
            raise TypeError("executor handoff must be an exact object")
        expected = {item.name for item in fields(cls)}
        if set(payload) != expected:
            raise ValueError("executor handoff contains unknown or missing fields")
        if payload["side_effects_performed"] is not False:
            raise ValueError("side_effects_performed must be false")
        values = dict(payload)
        values.pop("side_effects_performed")
        values["destination_route"] = ExecutorRoute(values["destination_route"])
        values["required_capabilities"] = tuple(
            ExecutorCapability(item)
            for item in _list_field(values, "required_capabilities")
        )
        for name in (
            "allowed_paths",
            "forbidden_paths",
            "required_return_evidence",
            "stop_conditions",
        ):
            values[name] = tuple(_list_field(values, name))
        return cls(**values)


def _decision_payload(
    value: ExecutorRouteDecision,
    *,
    include_id: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": value.schema_version,
        "repository": value.repository,
        "issue_or_handoff_identity": value.issue_or_handoff_identity,
        "requested_operation": value.requested_operation,
        "required_capabilities": [item.value for item in value.required_capabilities],
        "governed_runner_capabilities": [
            item.value for item in value.governed_runner_capabilities
        ],
        "governed_runner_available": value.governed_runner_available,
        "external_fallback_available": value.external_fallback_available,
        "external_fallback_explicitly_permitted": (
            value.external_fallback_explicitly_permitted
        ),
        "selected_route": value.selected_route.value,
        "route_reasons": [item.value for item in value.route_reasons],
        "rejected_lower_cost_routes": [
            item.value for item in value.rejected_lower_cost_routes
        ],
        "authority_ambiguous": value.authority_ambiguous,
        "ownership_ambiguous": value.ownership_ambiguous,
        "source_of_truth_ambiguous": value.source_of_truth_ambiguous,
        "target_ambiguous": value.target_ambiguous,
        "scope_ambiguous": value.scope_ambiguous,
        "excluded_surface_involved": value.excluded_surface_involved,
        "evidence_stale": value.evidence_stale,
        "evidence_contradictory": value.evidence_contradictory,
        "irreversible_or_uncertain_mutation": (
            value.irreversible_or_uncertain_mutation
        ),
        "execution_service_request_fingerprint_or_none": (
            value.execution_service_request_fingerprint_or_none
        ),
        "authorization_id_or_none": value.authorization_id_or_none,
        "validation_command_plan_id_or_none": (
            value.validation_command_plan_id_or_none
        ),
        "operating_mode_decision_id_or_none": (
            value.operating_mode_decision_id_or_none
        ),
        "executable_lane_selection_id_or_none": (
            value.executable_lane_selection_id_or_none
        ),
        "repository_state_evidence_id_or_none": (
            value.repository_state_evidence_id_or_none
        ),
        "worktree_preparation_evidence_id_or_none": (
            value.worktree_preparation_evidence_id_or_none
        ),
        "exact_head_package_id_or_none": value.exact_head_package_id_or_none,
        "environment_profile_id_or_none": value.environment_profile_id_or_none,
        "environment_health_evidence_id_or_none": (
            value.environment_health_evidence_id_or_none
        ),
        "checkpoint_id_or_none": value.checkpoint_id_or_none,
        "resume_plan_id_or_none": value.resume_plan_id_or_none,
        "workflow_runtime_identity_or_none": (
            value.workflow_runtime_identity_or_none
        ),
        "execution_authorized": value.execution_authorized,
        "github_writes_authorized": value.github_writes_authorized,
        "external_writes_authorized": value.external_writes_authorized,
        "merge_authorized": value.merge_authorized,
        "created_at": value.created_at,
        "expires_at": value.expires_at,
        "invalidation_conditions": list(value.invalidation_conditions),
        "side_effects_performed": False,
    }
    if include_id:
        payload["decision_id"] = value.decision_id
    return payload


def _handoff_payload(
    value: ExecutorHandoff,
    *,
    include_id: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": value.schema_version,
        "route_decision_id": value.route_decision_id,
        "destination_route": value.destination_route.value,
        "repository": value.repository,
        "issue_or_handoff_identity": value.issue_or_handoff_identity,
        "requested_operation": value.requested_operation,
        "source_ref_or_none": value.source_ref_or_none,
        "source_sha_or_none": value.source_sha_or_none,
        "required_capabilities": [item.value for item in value.required_capabilities],
        "allowed_paths": list(value.allowed_paths),
        "forbidden_paths": list(value.forbidden_paths),
        "execution_service_request_fingerprint_or_none": (
            value.execution_service_request_fingerprint_or_none
        ),
        "authorization_id_or_none": value.authorization_id_or_none,
        "validation_command_plan_id_or_none": (
            value.validation_command_plan_id_or_none
        ),
        "checkpoint_id_or_none": value.checkpoint_id_or_none,
        "resume_plan_id_or_none": value.resume_plan_id_or_none,
        "environment_profile_id_or_none": value.environment_profile_id_or_none,
        "required_return_evidence": list(value.required_return_evidence),
        "stop_conditions": list(value.stop_conditions),
        "execution_authorized": value.execution_authorized,
        "github_writes_authorized": value.github_writes_authorized,
        "external_writes_authorized": value.external_writes_authorized,
        "merge_authorized": value.merge_authorized,
        "side_effects_performed": False,
    }
    if include_id:
        payload["handoff_id"] = value.handoff_id
    return payload


def executor_route_decision_id(value: ExecutorRouteDecision) -> str:
    """Return the deterministic content identity for a route decision."""

    if type(value) is not ExecutorRouteDecision:
        raise TypeError("value must be an exact ExecutorRouteDecision")
    return _digest(
        "executor-route-decision",
        _decision_payload(value, include_id=False),
    )


def executor_handoff_id(value: ExecutorHandoff) -> str:
    """Return the deterministic content identity for an executor handoff."""

    if type(value) is not ExecutorHandoff:
        raise TypeError("value must be an exact ExecutorHandoff")
    return _digest(
        "executor-handoff",
        _handoff_payload(value, include_id=False),
    )


def serialize_executor_route_decision(value: ExecutorRouteDecision) -> str:
    """Serialize one exact route decision as canonical JSON."""

    if type(value) is not ExecutorRouteDecision:
        raise TypeError("value must be an exact ExecutorRouteDecision")
    return _canonical_json(value.to_dict())


def select_executor_route(
    *,
    repository: str,
    issue_or_handoff_identity: str,
    requested_operation: str,
    required_capabilities: tuple[ExecutorCapability, ...],
    governed_runner_capabilities: tuple[ExecutorCapability, ...],
    governed_runner_available: bool,
    external_fallback_available: bool,
    external_fallback_explicitly_permitted: bool,
    created_at: str,
    expires_at: str,
    invalidation_conditions: tuple[str, ...],
    authority_ambiguous: bool = False,
    ownership_ambiguous: bool = False,
    source_of_truth_ambiguous: bool = False,
    target_ambiguous: bool = False,
    scope_ambiguous: bool = False,
    excluded_surface_involved: bool = False,
    evidence_stale: bool = False,
    evidence_contradictory: bool = False,
    irreversible_or_uncertain_mutation: bool = False,
    execution_service_request_fingerprint_or_none: str | None = None,
    authorization_id_or_none: str | None = None,
    validation_command_plan_id_or_none: str | None = None,
    operating_mode_decision_id_or_none: str | None = None,
    executable_lane_selection_id_or_none: str | None = None,
    repository_state_evidence_id_or_none: str | None = None,
    worktree_preparation_evidence_id_or_none: str | None = None,
    exact_head_package_id_or_none: str | None = None,
    environment_profile_id_or_none: str | None = None,
    environment_health_evidence_id_or_none: str | None = None,
    checkpoint_id_or_none: str | None = None,
    resume_plan_id_or_none: str | None = None,
    workflow_runtime_identity_or_none: str | None = None,
    execution_authorized: bool = False,
    github_writes_authorized: bool = False,
    external_writes_authorized: bool = False,
    merge_authorized: bool = False,
) -> ExecutorRouteDecision:
    """Select one deterministic route without executing or authorizing work."""

    _enum_tuple(
        "required_capabilities",
        required_capabilities,
        ExecutorCapability,
        MAX_CAPABILITIES,
    )
    _enum_tuple(
        "governed_runner_capabilities",
        governed_runner_capabilities,
        ExecutorCapability,
        MAX_CAPABILITIES,
    )
    boolean_values = {
        "governed_runner_available": governed_runner_available,
        "external_fallback_available": external_fallback_available,
        "external_fallback_explicitly_permitted": (
            external_fallback_explicitly_permitted
        ),
        "authority_ambiguous": authority_ambiguous,
        "ownership_ambiguous": ownership_ambiguous,
        "source_of_truth_ambiguous": source_of_truth_ambiguous,
        "target_ambiguous": target_ambiguous,
        "scope_ambiguous": scope_ambiguous,
        "excluded_surface_involved": excluded_surface_involved,
        "evidence_stale": evidence_stale,
        "evidence_contradictory": evidence_contradictory,
        "irreversible_or_uncertain_mutation": irreversible_or_uncertain_mutation,
        "execution_authorized": execution_authorized,
        "github_writes_authorized": github_writes_authorized,
        "external_writes_authorized": external_writes_authorized,
        "merge_authorized": merge_authorized,
    }
    for name, value in boolean_values.items():
        _exact_bool(name, value)
    human_flags = {
        name: boolean_values[name] for name, _ in _HUMAN_FLAG_REASONS
    }
    route, reasons, rejected = _expected_route(
        required_capabilities=required_capabilities,
        governed_runner_capabilities=governed_runner_capabilities,
        governed_runner_available=governed_runner_available,
        external_fallback_available=external_fallback_available,
        external_fallback_explicitly_permitted=(
            external_fallback_explicitly_permitted
        ),
        human_flags=human_flags,
    )
    if route is ExecutorRoute.HUMAN_DECISION_REQUIRED:
        execution_authorized = False
        github_writes_authorized = False
        external_writes_authorized = False
        merge_authorized = False
    return ExecutorRouteDecision(
        schema_version=EXECUTOR_ROUTING_SCHEMA_VERSION,
        repository=repository,
        issue_or_handoff_identity=issue_or_handoff_identity,
        requested_operation=requested_operation,
        required_capabilities=required_capabilities,
        governed_runner_capabilities=governed_runner_capabilities,
        governed_runner_available=governed_runner_available,
        external_fallback_available=external_fallback_available,
        external_fallback_explicitly_permitted=(
            external_fallback_explicitly_permitted
        ),
        selected_route=route,
        route_reasons=reasons,
        rejected_lower_cost_routes=rejected,
        authority_ambiguous=authority_ambiguous,
        ownership_ambiguous=ownership_ambiguous,
        source_of_truth_ambiguous=source_of_truth_ambiguous,
        target_ambiguous=target_ambiguous,
        scope_ambiguous=scope_ambiguous,
        excluded_surface_involved=excluded_surface_involved,
        evidence_stale=evidence_stale,
        evidence_contradictory=evidence_contradictory,
        irreversible_or_uncertain_mutation=irreversible_or_uncertain_mutation,
        execution_service_request_fingerprint_or_none=(
            execution_service_request_fingerprint_or_none
        ),
        authorization_id_or_none=authorization_id_or_none,
        validation_command_plan_id_or_none=validation_command_plan_id_or_none,
        operating_mode_decision_id_or_none=operating_mode_decision_id_or_none,
        executable_lane_selection_id_or_none=(
            executable_lane_selection_id_or_none
        ),
        repository_state_evidence_id_or_none=(
            repository_state_evidence_id_or_none
        ),
        worktree_preparation_evidence_id_or_none=(
            worktree_preparation_evidence_id_or_none
        ),
        exact_head_package_id_or_none=exact_head_package_id_or_none,
        environment_profile_id_or_none=environment_profile_id_or_none,
        environment_health_evidence_id_or_none=(
            environment_health_evidence_id_or_none
        ),
        checkpoint_id_or_none=checkpoint_id_or_none,
        resume_plan_id_or_none=resume_plan_id_or_none,
        workflow_runtime_identity_or_none=workflow_runtime_identity_or_none,
        execution_authorized=execution_authorized,
        github_writes_authorized=github_writes_authorized,
        external_writes_authorized=external_writes_authorized,
        merge_authorized=merge_authorized,
        created_at=created_at,
        expires_at=expires_at,
        invalidation_conditions=invalidation_conditions,
    )


def build_executor_handoff(
    decision: ExecutorRouteDecision,
    *,
    source_ref_or_none: str | None,
    source_sha_or_none: str | None,
    allowed_paths: tuple[str, ...],
    forbidden_paths: tuple[str, ...],
    required_return_evidence: tuple[str, ...],
    stop_conditions: tuple[str, ...],
    checkpoint_id_or_none: str | None = None,
    resume_plan_id_or_none: str | None = None,
    environment_profile_id_or_none: str | None = None,
) -> ExecutorHandoff:
    """Build a bound handoff for a governed-runner or fallback decision."""

    if type(decision) is not ExecutorRouteDecision:
        raise TypeError("decision must be an exact ExecutorRouteDecision")
    if decision.selected_route not in {
        ExecutorRoute.CHATGPT_GOVERNED_RUNNER,
        ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK,
    }:
        raise ValueError("selected route does not support an executor handoff")
    for name, supplied, expected in (
        (
            "checkpoint_id_or_none",
            checkpoint_id_or_none,
            decision.checkpoint_id_or_none,
        ),
        (
            "resume_plan_id_or_none",
            resume_plan_id_or_none,
            decision.resume_plan_id_or_none,
        ),
        (
            "environment_profile_id_or_none",
            environment_profile_id_or_none,
            decision.environment_profile_id_or_none,
        ),
    ):
        if supplied is not None and supplied != expected:
            raise ValueError(f"{name} does not match route decision")
    return ExecutorHandoff(
        schema_version=EXECUTOR_ROUTING_SCHEMA_VERSION,
        route_decision_id=decision.decision_id,
        destination_route=decision.selected_route,
        repository=decision.repository,
        issue_or_handoff_identity=decision.issue_or_handoff_identity,
        requested_operation=decision.requested_operation,
        source_ref_or_none=source_ref_or_none,
        source_sha_or_none=source_sha_or_none,
        required_capabilities=decision.required_capabilities,
        allowed_paths=allowed_paths,
        forbidden_paths=forbidden_paths,
        execution_service_request_fingerprint_or_none=(
            decision.execution_service_request_fingerprint_or_none
        ),
        authorization_id_or_none=decision.authorization_id_or_none,
        validation_command_plan_id_or_none=(
            decision.validation_command_plan_id_or_none
        ),
        checkpoint_id_or_none=decision.checkpoint_id_or_none,
        resume_plan_id_or_none=decision.resume_plan_id_or_none,
        environment_profile_id_or_none=decision.environment_profile_id_or_none,
        required_return_evidence=required_return_evidence,
        stop_conditions=stop_conditions,
        execution_authorized=decision.execution_authorized,
        github_writes_authorized=decision.github_writes_authorized,
        external_writes_authorized=decision.external_writes_authorized,
        merge_authorized=decision.merge_authorized,
    )
