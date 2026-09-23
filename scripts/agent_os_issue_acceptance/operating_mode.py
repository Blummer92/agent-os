"""Pure-local, deterministic agent-operating-mode decision evaluator.

Computes the maximum lifecycle stage permitted for one issue by intersecting a
requested mode's capability ceiling with the canonical `IssueOperationalState`
from `issue_operational_state.py` and caller-supplied environment-capability
evidence. Performs no GitHub, network, filesystem, subprocess, environment,
credential, or Scheduler I/O; executes no work; mutates no lifecycle state;
and creates no authority. A requested mode is a capability ceiling only -- it
never broadens an authority field already carried by the supplied
`IssueOperationalState`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from .issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    IssueOperationalState,
    LifecycleStage,
    OperationalOutcome,
)

OPERATING_MODE_DECISION_SCHEMA_NAME = "agent-os-operating-mode-decision"
OPERATING_MODE_DECISION_SCHEMA_VERSION = "1.0"
MAX_TOKEN_BYTES = 64
MAX_REASON_CODES = 32
MAX_SERIALIZED_BYTES = 16 * 1024

_SHA256_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}:[0-9a-f]{64}$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

COMPATIBILITY_PHRASES = frozenset({"complete", "finish", "do everything"})


class RequestedMode(str, Enum):
    PLANNING = "planning"
    BUILD = "build"
    DRAFT_PR = "draft-pr"
    REVIEW = "review"
    RELEASE = "release"


class OperatingModeOutcome(str, Enum):
    PLANNED = "planned"
    BUILT = "built"
    DRAFT_PR_OPENED = "draft-pr-opened"
    REVIEW_COMPLETE = "review-complete"
    RELEASED = "released"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs-decision"
    INVALID = "invalid"


class EnvironmentCapabilityState(str, Enum):
    VERIFIED = "verified"
    NOT_VERIFIED = "not-verified"
    STALE = "stale"
    UNSUPPORTED = "unsupported"


REASON_CODES = frozenset(
    {
        "mode.missing",
        "mode.unrecognized",
        "state.blocked",
        "state.needs-decision",
        "state.stale",
        "state.conflicting",
        "state.terminal",
        "state.invalid",
        "authorization.implementation-not-authorized",
        "authorization.implementation-stale",
        "authorization.implementation-needs-decision",
        "authorization.ready-for-review-not-authorized",
        "authorization.ready-for-review-stale",
        "authorization.ready-for-review-needs-decision",
        "authorization.merge-not-authorized",
        "authorization.merge-stale",
        "authorization.merge-needs-decision",
        "authorization.closure-not-authorized",
        "authorization.closure-stale",
        "authorization.closure-needs-decision",
        "environment.local-execution-not-verified",
        "environment.local-execution-stale",
        "environment.local-execution-unsupported",
        "environment.push-not-verified",
        "environment.push-stale",
        "environment.push-unsupported",
        "lifecycle.mode-ceiling-reached",
        "compatibility.legacy-phrase-ignored",
    }
)

_STAGE_ORDER: tuple[LifecycleStage, ...] = (
    LifecycleStage.PLANNING,
    LifecycleStage.IMPLEMENTATION,
    LifecycleStage.DRAFT_PR,
    LifecycleStage.REVIEW,
    LifecycleStage.MERGED,
    LifecycleStage.CLOSED,
)
_STAGE_INDEX = {stage: index for index, stage in enumerate(_STAGE_ORDER)}

_MODE_CEILING_STAGE = {
    RequestedMode.PLANNING: LifecycleStage.PLANNING,
    RequestedMode.BUILD: LifecycleStage.IMPLEMENTATION,
    RequestedMode.DRAFT_PR: LifecycleStage.DRAFT_PR,
    RequestedMode.REVIEW: LifecycleStage.REVIEW,
    RequestedMode.RELEASE: LifecycleStage.CLOSED,
}

_STAGE_TO_MODE = {
    LifecycleStage.PLANNING: RequestedMode.PLANNING,
    LifecycleStage.IMPLEMENTATION: RequestedMode.BUILD,
    LifecycleStage.DRAFT_PR: RequestedMode.DRAFT_PR,
    LifecycleStage.REVIEW: RequestedMode.REVIEW,
    LifecycleStage.MERGED: RequestedMode.RELEASE,
    LifecycleStage.CLOSED: RequestedMode.RELEASE,
}

_STAGE_OUTCOME = {
    LifecycleStage.PLANNING: OperatingModeOutcome.PLANNED,
    LifecycleStage.IMPLEMENTATION: OperatingModeOutcome.BUILT,
    LifecycleStage.DRAFT_PR: OperatingModeOutcome.DRAFT_PR_OPENED,
    LifecycleStage.REVIEW: OperatingModeOutcome.REVIEW_COMPLETE,
    LifecycleStage.MERGED: OperatingModeOutcome.RELEASED,
    LifecycleStage.CLOSED: OperatingModeOutcome.RELEASED,
}

_TRANSITION_ACTION = {
    LifecycleStage.IMPLEMENTATION: "build",
    LifecycleStage.DRAFT_PR: "push-and-open-draft-pr",
    LifecycleStage.REVIEW: "flip-ready-for-review",
    LifecycleStage.MERGED: "merge",
    LifecycleStage.CLOSED: "close-issue",
}

_STATE_OUTCOME_REASON = {
    OperationalOutcome.BLOCKED: "state.blocked",
    OperationalOutcome.NEEDS_DECISION: "state.needs-decision",
    OperationalOutcome.STALE: "state.stale",
    OperationalOutcome.CONFLICTING: "state.conflicting",
    OperationalOutcome.TERMINAL: "state.terminal",
}

_AUTH_STAGE_TOKEN = {
    LifecycleStage.IMPLEMENTATION: "implementation",
    LifecycleStage.REVIEW: "ready-for-review",
    LifecycleStage.MERGED: "merge",
    LifecycleStage.CLOSED: "closure",
}
_AUTH_REASON_PREFIX = {
    LifecycleStage.IMPLEMENTATION: "authorization.implementation",
    LifecycleStage.REVIEW: "authorization.ready-for-review",
    LifecycleStage.MERGED: "authorization.merge",
    LifecycleStage.CLOSED: "authorization.closure",
}
_AUTH_STATE_SUFFIX = {
    AuthorizationState.NOT_AUTHORIZED: "not-authorized",
    AuthorizationState.STALE: "stale",
    AuthorizationState.NEEDS_DECISION: "needs-decision",
    AuthorizationState.NOT_APPLICABLE: "not-authorized",
}
_ENV_REASON_PREFIX = {
    "local-execution": "environment.local-execution",
    "push": "environment.push",
}
_ENV_STATE_SUFFIX = {
    EnvironmentCapabilityState.NOT_VERIFIED: "not-verified",
    EnvironmentCapabilityState.STALE: "stale",
    EnvironmentCapabilityState.UNSUPPORTED: "unsupported",
}

_KNOWN_ACTIONS = frozenset({*_TRANSITION_ACTION.values(), "none", "resolve-issue-state"})
_KNOWN_HUMAN_AUTHORIZATIONS = frozenset(_AUTH_STAGE_TOKEN.values())
_KNOWN_ENVIRONMENT_CAPABILITIES = frozenset({"push", "local-execution"})


def _exact_text(value: object, name: str, maximum: int) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a built-in string")
    if len(value.encode("utf-8")) > maximum or _CONTROL_RE.search(value):
        raise ValueError(f"{name} is outside bounds")
    return value


def _sha40(value: object, name: str) -> str:
    text = _exact_text(value, name, 40)
    if not _SHA40_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase 40-character SHA")
    return text


def _sha256_id(value: object, name: str, maximum: int = 128) -> str:
    text = _exact_text(value, name, maximum)
    if not _SHA256_ID_RE.fullmatch(text):
        raise ValueError(f"{name} is malformed")
    return text


def _enum(value: object, enum_type: type[Enum], name: str) -> Enum:
    if not isinstance(value, enum_type):
        raise TypeError(f"{name} must be {enum_type.__name__}")
    return value


def _canonical_strings(
    values: object,
    *,
    name: str,
    maximum: int,
    allowed: frozenset[str] | None = None,
) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    if len(values) > maximum:
        raise ValueError(f"{name} exceeds its bound")
    checked = tuple(_exact_text(value, name, 512) for value in values)
    if len(set(checked)) != len(checked):
        raise ValueError(f"{name} contains duplicates")
    if allowed is not None and any(item not in allowed for item in checked):
        raise ValueError(f"{name} contains an unsupported value")
    return tuple(sorted(checked))


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _decision_id(payload: object) -> str:
    material = b"agent-os-operating-mode-decision:v1\0" + _canonical_json(payload).encode(
        "utf-8"
    )
    return f"operating-mode-decision:{hashlib.sha256(material).hexdigest()}"


def _strict_keys(payload: dict[str, object], expected: frozenset[str], name: str) -> None:
    unknown = set(payload) - expected
    missing = expected - set(payload)
    if unknown:
        raise ValueError(f"{name} contains unknown fields: {sorted(unknown)}")
    if missing:
        raise ValueError(f"{name} is missing fields: {sorted(missing)}")


@dataclass(frozen=True, slots=True)
class EnvironmentCapabilityEvidence:
    """Caller-verified environment capability, independent of `IssueOperationalState`."""

    local_execution_state: EnvironmentCapabilityState
    push_state: EnvironmentCapabilityState
    evidence_id: str | None = None
    bound_source_revision: str | None = None
    observed_source_revision: str | None = None

    def __post_init__(self) -> None:
        _enum(self.local_execution_state, EnvironmentCapabilityState, "local_execution_state")
        _enum(self.push_state, EnvironmentCapabilityState, "push_state")
        if self.evidence_id is not None:
            _sha256_id(self.evidence_id, "environment evidence_id")
        needs_evidence = self.local_execution_state in {
            EnvironmentCapabilityState.VERIFIED,
            EnvironmentCapabilityState.STALE,
        } or self.push_state in {
            EnvironmentCapabilityState.VERIFIED,
            EnvironmentCapabilityState.STALE,
        }
        if needs_evidence and self.evidence_id is None:
            raise ValueError(
                "verified or stale environment capability requires evidence_id"
            )
        if self.bound_source_revision is not None:
            _sha40(self.bound_source_revision, "bound_source_revision")
        if self.observed_source_revision is not None:
            _sha40(self.observed_source_revision, "observed_source_revision")
        if (self.bound_source_revision is None) != (self.observed_source_revision is None):
            raise ValueError(
                "environment SHA binding requires both bound and observed revision"
            )

    def effective(self) -> EnvironmentCapabilityEvidence:
        if (
            self.bound_source_revision is not None
            and self.bound_source_revision != self.observed_source_revision
        ):
            def _downgrade(state: EnvironmentCapabilityState) -> EnvironmentCapabilityState:
                return (
                    EnvironmentCapabilityState.STALE
                    if state is EnvironmentCapabilityState.VERIFIED
                    else state
                )

            return EnvironmentCapabilityEvidence(
                local_execution_state=_downgrade(self.local_execution_state),
                push_state=_downgrade(self.push_state),
                evidence_id=self.evidence_id,
                bound_source_revision=self.bound_source_revision,
                observed_source_revision=self.observed_source_revision,
            )
        return self

    def to_dict(self) -> dict[str, object]:
        return {
            "local_execution_state": self.local_execution_state.value,
            "push_state": self.push_state.value,
            "evidence_id": self.evidence_id,
            "bound_source_revision": self.bound_source_revision,
            "observed_source_revision": self.observed_source_revision,
        }

    @classmethod
    def from_dict(cls, payload: object) -> EnvironmentCapabilityEvidence:
        if type(payload) is not dict:
            raise TypeError("environment capability evidence must be an exact object")
        _strict_keys(
            payload,
            frozenset(
                {
                    "local_execution_state",
                    "push_state",
                    "evidence_id",
                    "bound_source_revision",
                    "observed_source_revision",
                }
            ),
            "environment capability evidence",
        )
        try:
            local_execution_state = EnvironmentCapabilityState(payload["local_execution_state"])
            push_state = EnvironmentCapabilityState(payload["push_state"])
        except (TypeError, ValueError) as exc:
            raise ValueError("environment capability state is unsupported") from exc
        return cls(
            local_execution_state=local_execution_state,
            push_state=push_state,
            evidence_id=payload["evidence_id"],
            bound_source_revision=payload["bound_source_revision"],
            observed_source_revision=payload["observed_source_revision"],
        )


@dataclass(frozen=True, slots=True)
class AgentOperatingModeDecision:
    """Immutable `agent-os-operating-mode-decision/1.0` result.

    Every authority dimension is preserved exactly as projected by the supplied
    `IssueOperationalState`; this evaluator never widens, infers, or collapses one.
    """

    schema_name: Literal["agent-os-operating-mode-decision"]
    schema_version: Literal["1.0"]
    requested_mode_input: str
    requested_mode: RequestedMode
    effective_mode: RequestedMode
    outcome: OperatingModeOutcome
    maximum_permitted_stage: LifecycleStage
    highest_completed_stage: LifecycleStage
    next_permitted_action: str
    prohibited_actions: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    reason_codes: tuple[str, ...]
    required_human_authorizations: tuple[str, ...]
    required_environment_capabilities: tuple[str, ...]
    source_operational_state_id: str
    supplied_authorization_evidence_ids: tuple[str, ...]
    supplied_environment_capability_evidence_id: str | None
    implementation_authorization: AuthorityProjection
    ready_for_review_authorization: AuthorityProjection
    execution_authorization: AuthorityProjection
    merge_authorization: AuthorityProjection
    closure_authorization: AuthorityProjection
    external_write_authorization: AuthorityProjection
    decision_id: str = ""
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_name != OPERATING_MODE_DECISION_SCHEMA_NAME
            or self.schema_version != OPERATING_MODE_DECISION_SCHEMA_VERSION
        ):
            raise ValueError("unsupported agent operating mode decision schema")
        _exact_text(self.requested_mode_input, "requested_mode_input", MAX_TOKEN_BYTES)
        _enum(self.requested_mode, RequestedMode, "requested_mode")
        _enum(self.effective_mode, RequestedMode, "effective_mode")
        _enum(self.outcome, OperatingModeOutcome, "outcome")
        _enum(self.maximum_permitted_stage, LifecycleStage, "maximum_permitted_stage")
        _enum(self.highest_completed_stage, LifecycleStage, "highest_completed_stage")
        _exact_text(self.next_permitted_action, "next_permitted_action", 64)
        if self.next_permitted_action not in _KNOWN_ACTIONS:
            raise ValueError("next_permitted_action is unsupported")
        object.__setattr__(
            self,
            "prohibited_actions",
            _canonical_strings(
                self.prohibited_actions,
                name="prohibited_actions",
                maximum=len(_TRANSITION_ACTION),
                allowed=frozenset(_TRANSITION_ACTION.values()),
            ),
        )
        blockers = _canonical_strings(
            self.blocker_codes,
            name="blocker_codes",
            maximum=MAX_REASON_CODES,
            allowed=REASON_CODES,
        )
        reasons = _canonical_strings(
            self.reason_codes,
            name="reason_codes",
            maximum=MAX_REASON_CODES,
            allowed=REASON_CODES,
        )
        if not set(blockers) <= set(reasons):
            raise ValueError("blocker_codes must be a subset of reason_codes")
        object.__setattr__(self, "blocker_codes", blockers)
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(
            self,
            "required_human_authorizations",
            _canonical_strings(
                self.required_human_authorizations,
                name="required_human_authorizations",
                maximum=len(_KNOWN_HUMAN_AUTHORIZATIONS),
                allowed=_KNOWN_HUMAN_AUTHORIZATIONS,
            ),
        )
        object.__setattr__(
            self,
            "required_environment_capabilities",
            _canonical_strings(
                self.required_environment_capabilities,
                name="required_environment_capabilities",
                maximum=len(_KNOWN_ENVIRONMENT_CAPABILITIES),
                allowed=_KNOWN_ENVIRONMENT_CAPABILITIES,
            ),
        )
        _sha256_id(self.source_operational_state_id, "source_operational_state_id")
        object.__setattr__(
            self,
            "supplied_authorization_evidence_ids",
            _canonical_strings(
                self.supplied_authorization_evidence_ids,
                name="supplied_authorization_evidence_ids",
                maximum=6,
            ),
        )
        for value in self.supplied_authorization_evidence_ids:
            _sha256_id(value, "supplied_authorization_evidence_ids entry")
        if self.supplied_environment_capability_evidence_id is not None:
            _sha256_id(
                self.supplied_environment_capability_evidence_id,
                "supplied_environment_capability_evidence_id",
            )
        for name in (
            "implementation_authorization",
            "ready_for_review_authorization",
            "execution_authorization",
            "merge_authorization",
            "closure_authorization",
            "external_write_authorization",
        ):
            if type(getattr(self, name)) is not AuthorityProjection:
                raise TypeError(f"{name} must be an exact AuthorityProjection")
        if self.side_effects_performed is not False:
            raise ValueError("operating mode decision cannot record side effects")
        expected = _decision_id(self._payload())
        if self.decision_id and self.decision_id != expected:
            raise ValueError("decision_id does not match operating mode decision content")
        object.__setattr__(self, "decision_id", expected)
        if len(_canonical_json(self.to_dict()).encode("utf-8")) > MAX_SERIALIZED_BYTES:
            raise ValueError("operating mode decision exceeds serialized bound")

    def _payload(self) -> dict[str, object]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "requested_mode_input": self.requested_mode_input,
            "requested_mode": self.requested_mode.value,
            "effective_mode": self.effective_mode.value,
            "outcome": self.outcome.value,
            "maximum_permitted_stage": self.maximum_permitted_stage.value,
            "highest_completed_stage": self.highest_completed_stage.value,
            "next_permitted_action": self.next_permitted_action,
            "prohibited_actions": list(self.prohibited_actions),
            "blocker_codes": list(self.blocker_codes),
            "reason_codes": list(self.reason_codes),
            "required_human_authorizations": list(self.required_human_authorizations),
            "required_environment_capabilities": list(
                self.required_environment_capabilities
            ),
            "source_operational_state_id": self.source_operational_state_id,
            "supplied_authorization_evidence_ids": list(
                self.supplied_authorization_evidence_ids
            ),
            "supplied_environment_capability_evidence_id": (
                self.supplied_environment_capability_evidence_id
            ),
            "implementation_authorization": self.implementation_authorization.to_dict(),
            "ready_for_review_authorization": self.ready_for_review_authorization.to_dict(),
            "execution_authorization": self.execution_authorization.to_dict(),
            "merge_authorization": self.merge_authorization.to_dict(),
            "closure_authorization": self.closure_authorization.to_dict(),
            "external_write_authorization": self.external_write_authorization.to_dict(),
            "side_effects_performed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "decision_id": self.decision_id}


def _normalize_mode_token(value: object) -> str:
    if value is None:
        return ""
    if type(value) is not str:
        raise TypeError("requested_mode must be a built-in string or None")
    if len(value.encode("utf-8")) > MAX_TOKEN_BYTES or _CONTROL_RE.search(value):
        raise ValueError("requested_mode is outside bounds")
    return value.strip().lower()


def _resolve_requested_mode(token: str) -> tuple[RequestedMode, bool]:
    if token == "":
        return RequestedMode.PLANNING, True
    try:
        return RequestedMode(token), False
    except ValueError:
        return RequestedMode.PLANNING, True


def _add_auth_block(
    stage: LifecycleStage,
    projection: AuthorityProjection,
    reasons: set[str],
    blockers: set[str],
    required_auth: set[str],
) -> None:
    prefix = _AUTH_REASON_PREFIX[stage]
    suffix = _AUTH_STATE_SUFFIX[projection.state]
    code = f"{prefix}-{suffix}"
    reasons.add(code)
    blockers.add(code)
    required_auth.add(_AUTH_STAGE_TOKEN[stage])


def _add_env_block(
    kind: str,
    state: EnvironmentCapabilityState,
    reasons: set[str],
    blockers: set[str],
    required_env: set[str],
) -> None:
    prefix = _ENV_REASON_PREFIX[kind]
    suffix = _ENV_STATE_SUFFIX[state]
    code = f"{prefix}-{suffix}"
    reasons.add(code)
    blockers.add(code)
    required_env.add(kind)


def _advance_stages(
    ceiling: LifecycleStage,
    authorities: dict[str, AuthorityProjection],
    environment: EnvironmentCapabilityEvidence,
) -> tuple[LifecycleStage, set[str], set[str], tuple[str, ...], tuple[str, ...]]:
    reasons: set[str] = set()
    blockers: set[str] = set()
    required_auth: set[str] = set()
    required_env: set[str] = set()
    stage = LifecycleStage.PLANNING

    def _done() -> tuple[LifecycleStage, set[str], set[str], tuple[str, ...], tuple[str, ...]]:
        return stage, reasons, blockers, tuple(sorted(required_auth)), tuple(sorted(required_env))

    if _STAGE_INDEX[ceiling] < _STAGE_INDEX[LifecycleStage.IMPLEMENTATION]:
        return _done()

    implementation = authorities["implementation_authorization"]
    if implementation.state is not AuthorizationState.AUTHORIZED:
        _add_auth_block(
            LifecycleStage.IMPLEMENTATION, implementation, reasons, blockers, required_auth
        )
        return _done()
    if environment.local_execution_state is not EnvironmentCapabilityState.VERIFIED:
        _add_env_block(
            "local-execution", environment.local_execution_state, reasons, blockers, required_env
        )
        return _done()
    stage = LifecycleStage.IMPLEMENTATION
    if _STAGE_INDEX[ceiling] < _STAGE_INDEX[LifecycleStage.DRAFT_PR]:
        return _done()

    if environment.push_state is not EnvironmentCapabilityState.VERIFIED:
        _add_env_block("push", environment.push_state, reasons, blockers, required_env)
        return _done()
    stage = LifecycleStage.DRAFT_PR
    if _STAGE_INDEX[ceiling] < _STAGE_INDEX[LifecycleStage.REVIEW]:
        return _done()

    ready = authorities["ready_for_review_authorization"]
    if ready.state is not AuthorizationState.AUTHORIZED:
        _add_auth_block(LifecycleStage.REVIEW, ready, reasons, blockers, required_auth)
        return _done()
    stage = LifecycleStage.REVIEW
    if _STAGE_INDEX[ceiling] < _STAGE_INDEX[LifecycleStage.MERGED]:
        return _done()

    merge = authorities["merge_authorization"]
    if merge.state is not AuthorizationState.AUTHORIZED:
        _add_auth_block(LifecycleStage.MERGED, merge, reasons, blockers, required_auth)
        return _done()
    stage = LifecycleStage.MERGED
    if _STAGE_INDEX[ceiling] < _STAGE_INDEX[LifecycleStage.CLOSED]:
        return _done()

    closure = authorities["closure_authorization"]
    if closure.state is not AuthorizationState.AUTHORIZED:
        _add_auth_block(LifecycleStage.CLOSED, closure, reasons, blockers, required_auth)
        return _done()
    stage = LifecycleStage.CLOSED
    return _done()


def _next_permitted_action(
    stage_reached: LifecycleStage, highest_completed_stage: LifecycleStage
) -> str:
    """Return the single transition still permitted, anchored on real progress.

    The candidate is the transition out of `highest_completed_stage`, capped by
    `stage_reached` (the maximum permitted stage). Anchoring on the ceiling
    itself would name the first transition *beyond* it -- exactly the action
    `_prohibited_actions` forbids -- so a permitted action is returned only when
    it lands at or below the ceiling, and `"none"` otherwise.
    """
    next_index = _STAGE_INDEX[highest_completed_stage] + 1
    if next_index > _STAGE_INDEX[stage_reached]:
        return "none"
    return _TRANSITION_ACTION[_STAGE_ORDER[next_index]]


def _prohibited_actions(stage_reached: LifecycleStage) -> tuple[str, ...]:
    index = _STAGE_INDEX[stage_reached]
    return tuple(sorted(_TRANSITION_ACTION[stage] for stage in _STAGE_ORDER[index + 1 :]))


def evaluate_operating_mode_decision(
    operational_state: IssueOperationalState,
    requested_mode: object,
    environment: EnvironmentCapabilityEvidence,
) -> AgentOperatingModeDecision:
    """Intersect requested mode capability, `IssueOperationalState`, and
    environment capability into one immutable, fail-closed decision.

    Reuses the supplied `IssueOperationalState` authority projections directly;
    it never re-derives issue state or builds a second authorization framework.
    """

    if type(operational_state) is not IssueOperationalState:
        raise TypeError("operational_state must be an exact IssueOperationalState")
    if type(environment) is not EnvironmentCapabilityEvidence:
        raise TypeError("environment must be an exact EnvironmentCapabilityEvidence")

    reasons: set[str] = set()
    blockers: set[str] = set()

    requested_mode_input = _normalize_mode_token(requested_mode)
    resolved_mode, mode_defaulted = _resolve_requested_mode(requested_mode_input)
    if mode_defaulted:
        if requested_mode_input == "":
            reasons.add("mode.missing")
            blockers.add("mode.missing")
        else:
            reasons.add("mode.unrecognized")
            blockers.add("mode.unrecognized")
            if requested_mode_input in COMPATIBILITY_PHRASES:
                reasons.add("compatibility.legacy-phrase-ignored")
                blockers.add("compatibility.legacy-phrase-ignored")

    env = environment.effective()
    authorities = {
        "implementation_authorization": operational_state.implementation_authorization.effective(),
        "ready_for_review_authorization": operational_state.ready_for_review_authorization.effective(),
        "execution_authorization": operational_state.execution_authorization.effective(),
        "merge_authorization": operational_state.merge_authorization.effective(),
        "closure_authorization": operational_state.closure_authorization.effective(),
        "external_write_authorization": operational_state.external_write_authorization.effective(),
    }

    mode_ceiling = _MODE_CEILING_STAGE[resolved_mode]

    required_human_authorizations: tuple[str, ...] = ()
    required_environment_capabilities: tuple[str, ...] = ()

    if operational_state.outcome is OperationalOutcome.INVALID:
        stage_reached = LifecycleStage.PLANNING
        reasons.add("state.invalid")
        blockers.add("state.invalid")
        outcome = OperatingModeOutcome.INVALID
    elif operational_state.outcome is not OperationalOutcome.READY:
        stage_reached = LifecycleStage.PLANNING
        state_reason = _STATE_OUTCOME_REASON[operational_state.outcome]
        reasons.add(state_reason)
        blockers.add(state_reason)
        if operational_state.outcome is OperationalOutcome.NEEDS_DECISION:
            outcome = OperatingModeOutcome.NEEDS_DECISION
        else:
            outcome = OperatingModeOutcome.BLOCKED
    else:
        (
            stage_reached,
            stage_reasons,
            stage_blockers,
            required_human_authorizations,
            required_environment_capabilities,
        ) = _advance_stages(mode_ceiling, authorities, env)
        reasons |= stage_reasons
        blockers |= stage_blockers
        if (
            stage_reached is mode_ceiling
            and stage_reached is not LifecycleStage.CLOSED
            and not stage_blockers
        ):
            reasons.add("lifecycle.mode-ceiling-reached")
        if resolved_mode is not RequestedMode.PLANNING and stage_reached is LifecycleStage.PLANNING:
            outcome = OperatingModeOutcome.BLOCKED
        else:
            outcome = _STAGE_OUTCOME[stage_reached]

    if outcome in (
        OperatingModeOutcome.BLOCKED,
        OperatingModeOutcome.NEEDS_DECISION,
        OperatingModeOutcome.INVALID,
    ):
        next_action = "resolve-issue-state"
        prohibited = _prohibited_actions(LifecycleStage.PLANNING)
    else:
        next_action = _next_permitted_action(
            stage_reached, operational_state.lifecycle_stage
        )
        prohibited = _prohibited_actions(stage_reached)

    supplied_authorization_evidence_ids = tuple(
        sorted({a.evidence_id for a in authorities.values() if a.evidence_id})
    )

    return AgentOperatingModeDecision(
        schema_name=OPERATING_MODE_DECISION_SCHEMA_NAME,
        schema_version=OPERATING_MODE_DECISION_SCHEMA_VERSION,
        requested_mode_input=requested_mode_input,
        requested_mode=resolved_mode,
        effective_mode=_STAGE_TO_MODE[stage_reached],
        outcome=outcome,
        maximum_permitted_stage=stage_reached,
        highest_completed_stage=operational_state.lifecycle_stage,
        next_permitted_action=next_action,
        prohibited_actions=prohibited,
        blocker_codes=tuple(blockers),
        reason_codes=tuple(reasons),
        required_human_authorizations=required_human_authorizations,
        required_environment_capabilities=required_environment_capabilities,
        source_operational_state_id=operational_state.state_id,
        supplied_authorization_evidence_ids=supplied_authorization_evidence_ids,
        supplied_environment_capability_evidence_id=env.evidence_id,
        implementation_authorization=authorities["implementation_authorization"],
        ready_for_review_authorization=authorities["ready_for_review_authorization"],
        execution_authorization=authorities["execution_authorization"],
        merge_authorization=authorities["merge_authorization"],
        closure_authorization=authorities["closure_authorization"],
        external_write_authorization=authorities["external_write_authorization"],
    )


def serialize_agent_operating_mode_decision(decision: AgentOperatingModeDecision) -> str:
    if type(decision) is not AgentOperatingModeDecision:
        raise TypeError("decision must be an exact AgentOperatingModeDecision")
    return _canonical_json(decision.to_dict())


def deserialize_agent_operating_mode_decision(serialized: object) -> AgentOperatingModeDecision:
    if type(serialized) is not str:
        raise TypeError("serialized decision must be a built-in string")
    if len(serialized.encode("utf-8")) > MAX_SERIALIZED_BYTES:
        raise ValueError("serialized decision exceeds its bound")
    try:
        payload = json.loads(serialized)
    except json.JSONDecodeError as exc:
        raise ValueError("serialized decision is not valid JSON") from exc
    except RecursionError as exc:
        raise ValueError("serialized decision is nested too deeply") from exc
    if type(payload) is not dict:
        raise TypeError("serialized decision must contain an exact JSON object")

    expected = frozenset(
        {
            "schema_name",
            "schema_version",
            "requested_mode_input",
            "requested_mode",
            "effective_mode",
            "outcome",
            "maximum_permitted_stage",
            "highest_completed_stage",
            "next_permitted_action",
            "prohibited_actions",
            "blocker_codes",
            "reason_codes",
            "required_human_authorizations",
            "required_environment_capabilities",
            "source_operational_state_id",
            "supplied_authorization_evidence_ids",
            "supplied_environment_capability_evidence_id",
            "implementation_authorization",
            "ready_for_review_authorization",
            "execution_authorization",
            "merge_authorization",
            "closure_authorization",
            "external_write_authorization",
            "side_effects_performed",
            "decision_id",
        }
    )
    _strict_keys(payload, expected, "agent operating mode decision")
    if payload.get("schema_name") != OPERATING_MODE_DECISION_SCHEMA_NAME:
        raise ValueError("unsupported agent operating mode decision schema name")
    if payload.get("schema_version") != OPERATING_MODE_DECISION_SCHEMA_VERSION:
        raise ValueError("unsupported agent operating mode decision schema version")
    if payload["side_effects_performed"] is not False:
        raise ValueError("serialized decision cannot claim side effects")

    list_fields = (
        "prohibited_actions",
        "blocker_codes",
        "reason_codes",
        "required_human_authorizations",
        "required_environment_capabilities",
        "supplied_authorization_evidence_ids",
    )
    for key in list_fields:
        if type(payload[key]) is not list:
            raise TypeError(f"{key} must be an exact JSON array")

    def enum_value(key: str, enum_type: type[Enum]) -> Enum:
        try:
            return enum_type(payload[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} is unsupported") from exc

    return AgentOperatingModeDecision(
        schema_name=payload["schema_name"],
        schema_version=payload["schema_version"],
        requested_mode_input=payload["requested_mode_input"],
        requested_mode=enum_value("requested_mode", RequestedMode),
        effective_mode=enum_value("effective_mode", RequestedMode),
        outcome=enum_value("outcome", OperatingModeOutcome),
        maximum_permitted_stage=enum_value("maximum_permitted_stage", LifecycleStage),
        highest_completed_stage=enum_value("highest_completed_stage", LifecycleStage),
        next_permitted_action=payload["next_permitted_action"],
        prohibited_actions=tuple(payload["prohibited_actions"]),
        blocker_codes=tuple(payload["blocker_codes"]),
        reason_codes=tuple(payload["reason_codes"]),
        required_human_authorizations=tuple(payload["required_human_authorizations"]),
        required_environment_capabilities=tuple(
            payload["required_environment_capabilities"]
        ),
        source_operational_state_id=payload["source_operational_state_id"],
        supplied_authorization_evidence_ids=tuple(
            payload["supplied_authorization_evidence_ids"]
        ),
        supplied_environment_capability_evidence_id=(
            payload["supplied_environment_capability_evidence_id"]
        ),
        implementation_authorization=AuthorityProjection.from_dict(
            payload["implementation_authorization"]
        ),
        ready_for_review_authorization=AuthorityProjection.from_dict(
            payload["ready_for_review_authorization"]
        ),
        execution_authorization=AuthorityProjection.from_dict(
            payload["execution_authorization"]
        ),
        merge_authorization=AuthorityProjection.from_dict(payload["merge_authorization"]),
        closure_authorization=AuthorityProjection.from_dict(
            payload["closure_authorization"]
        ),
        external_write_authorization=AuthorityProjection.from_dict(
            payload["external_write_authorization"]
        ),
        decision_id=payload["decision_id"],
    )
