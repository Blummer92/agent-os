"""Pure deterministic Coding Command Center handoff projection (#1097).

This module composes caller-supplied canonical Agent OS evidence only. It performs
no GitHub, network, filesystem, subprocess, Scheduler, provider, or Notion I/O;
executes no work; mutates no lifecycle state; and creates no authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Literal

from scripts.agent_os_candidate_packet.post_pr_lane_plan import PostPrLanePlan

from .executor_route import ExecutorRouteDecision
from .issue_operational_state import (
    ClaimState,
    IssueOperationalState,
    OperationalOutcome,
)
from .validation_failure_classifier import ValidationFailureClassificationResult

CODING_COMMAND_CENTER_HANDOFF_SCHEMA_NAME = "agent-os-coding-command-center-handoff"
CODING_COMMAND_CENTER_HANDOFF_SCHEMA_VERSION = "1.0"
MAX_TEXT_BYTES = 4096
MAX_REASON_CODES = 32
MAX_SERIALIZED_BYTES = 64 * 1024
_UNAVAILABLE = "unavailable"
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class CodingCommandCenterEvidence:
    """Canonical projections supplied by the caller for one issue."""

    operational_state: IssueOperationalState
    source_revision: str
    observed_head_sha: str | None = None
    executor_route_decision: ExecutorRouteDecision | None = None
    validation_classification: ValidationFailureClassificationResult | None = None
    validation_evidence_reference: str | None = None
    post_pr_lane_plan: PostPrLanePlan | None = None
    handoff_target: str | None = None

    def __post_init__(self) -> None:
        if type(self.operational_state) is not IssueOperationalState:
            raise TypeError("operational_state must be exact IssueOperationalState")
        _sha40(self.source_revision, "source_revision")
        if self.source_revision != self.operational_state.source_revision:
            raise ValueError("source_revision conflicts with operational state")
        if self.observed_head_sha is not None:
            _sha40(self.observed_head_sha, "observed_head_sha")
        if self.executor_route_decision is not None and type(self.executor_route_decision) is not ExecutorRouteDecision:
            raise TypeError("executor_route_decision must be exact ExecutorRouteDecision or None")
        if self.validation_classification is not None and type(self.validation_classification) is not ValidationFailureClassificationResult:
            raise TypeError("validation_classification must be exact ValidationFailureClassificationResult or None")
        if self.post_pr_lane_plan is not None and type(self.post_pr_lane_plan) is not PostPrLanePlan:
            raise TypeError("post_pr_lane_plan must be exact PostPrLanePlan or None")
        _optional_text(self.validation_evidence_reference, "validation_evidence_reference")
        _optional_text(self.handoff_target, "handoff_target")


@dataclass(frozen=True, slots=True)
class CodingCommandCenterHandoff:
    schema_name: Literal["agent-os-coding-command-center-handoff"]
    schema_version: Literal["1.0"]
    repository: str
    issue_number: int
    pull_request_number: int | None
    observed_head_sha: str | None
    canonical_state_reference: str
    current_stage: str
    smallest_next_action: str
    executor_route: str | None
    executor_route_decision_id: str | None
    validation_classification: str | None
    validation_evidence_reference: str | None
    primary_blocker: str | None
    handoff_target: str | None
    source_revision: str
    reason_codes: tuple[str, ...]
    handoff_id: str = ""
    authority_created: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)
    notion_write_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != CODING_COMMAND_CENTER_HANDOFF_SCHEMA_NAME or self.schema_version != CODING_COMMAND_CENTER_HANDOFF_SCHEMA_VERSION:
            raise ValueError("unsupported Coding Command Center handoff schema")
        _required_text(self.repository, "repository")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise TypeError("issue_number must be a positive built-in integer")
        if self.pull_request_number is not None and (type(self.pull_request_number) is not int or self.pull_request_number < 1):
            raise TypeError("pull_request_number must be a positive built-in integer or None")
        if self.observed_head_sha is not None:
            _sha40(self.observed_head_sha, "observed_head_sha")
        _required_text(self.canonical_state_reference, "canonical_state_reference")
        _required_text(self.current_stage, "current_stage")
        _required_text(self.smallest_next_action, "smallest_next_action")
        for name in (
            "executor_route",
            "executor_route_decision_id",
            "validation_classification",
            "validation_evidence_reference",
            "primary_blocker",
            "handoff_target",
        ):
            _optional_text(getattr(self, name), name)
        _sha40(self.source_revision, "source_revision")
        reasons = _canonical_reasons(self.reason_codes)
        object.__setattr__(self, "reason_codes", reasons)
        payload = self._payload()
        expected = "coding-command-center-handoff:" + hashlib.sha256(
            b"agent-os-coding-command-center-handoff:v1\0" + _canonical_json(payload).encode("utf-8")
        ).hexdigest()
        if self.handoff_id and self.handoff_id != expected:
            raise ValueError("handoff_id does not match canonical content")
        object.__setattr__(self, "handoff_id", expected)
        if len(_canonical_json(self.to_dict()).encode("utf-8")) > MAX_SERIALIZED_BYTES:
            raise ValueError("Coding Command Center handoff exceeds serialized bound")

    def _payload(self) -> dict[str, object]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "pull_request_number": self.pull_request_number,
            "observed_head_sha": self.observed_head_sha,
            "canonical_state_reference": self.canonical_state_reference,
            "current_stage": self.current_stage,
            "smallest_next_action": self.smallest_next_action,
            "executor_route": self.executor_route,
            "executor_route_decision_id": self.executor_route_decision_id,
            "validation_classification": self.validation_classification,
            "validation_evidence_reference": self.validation_evidence_reference,
            "primary_blocker": self.primary_blocker,
            "handoff_target": self.handoff_target,
            "source_revision": self.source_revision,
            "reason_codes": list(self.reason_codes),
            "authority_created": False,
            "side_effects_performed": False,
            "notion_write_performed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "handoff_id": self.handoff_id}


def build_coding_command_center_handoff(
    evidence: CodingCommandCenterEvidence,
) -> CodingCommandCenterHandoff:
    """Compose existing canonical evidence without reranking or inferring authority."""
    if type(evidence) is not CodingCommandCenterEvidence:
        raise TypeError("evidence must be exact CodingCommandCenterEvidence")
    state = evidence.operational_state
    # Re-run the canonical state invariant so tampered frozen objects fail closed.
    try:
        state.__post_init__()
    except (TypeError, ValueError) as exc:
        raise ValueError("operational state validation failed") from exc

    reasons: set[str] = set()
    primary_pr = state.primary_pr_numbers[0] if len(state.primary_pr_numbers) == 1 else None
    if state.claim_state is ClaimState.CONFLICTING:
        reasons.add("handoff.primary-claim-conflicting")

    route = evidence.executor_route_decision
    if route is not None:
        try:
            route.__post_init__()
        except (TypeError, ValueError) as exc:
            raise ValueError("executor route decision validation failed") from exc
        executor_route = route.route.value
        executor_route_decision_id = route.decision_id
        reasons.update(f"route.{item}" for item in route.reason_codes)
    else:
        executor_route = None
        executor_route_decision_id = None
        reasons.add("handoff.executor-route-unavailable")

    classification = evidence.validation_classification
    if classification is not None:
        validation_classification = classification.classification.value
        smallest_next_action = classification.recommended_next_action
        reasons.add("handoff.validation-classification-present")
    else:
        validation_classification = None
        smallest_next_action = _state_next_action(state)

    plan = evidence.post_pr_lane_plan
    if plan is not None:
        try:
            plan.__post_init__()
        except (TypeError, ValueError) as exc:
            raise ValueError("post-PR lane plan validation failed") from exc
        # #914 owns post-PR lane choice and smallest-next-action semantics.
        smallest_next_action = plan.smallest_next_action
        reasons.add("handoff.post-pr-next-action-preserved")
        if evidence.handoff_target is None and plan.primary_next_issue is not None:
            handoff_target = f"issue:{plan.primary_next_issue}"
        else:
            handoff_target = evidence.handoff_target
    else:
        handoff_target = evidence.handoff_target

    blocker = state.blocker_codes[0] if state.blocker_codes else None
    if state.outcome in {OperationalOutcome.STALE, OperationalOutcome.CONFLICTING, OperationalOutcome.INVALID}:
        smallest_next_action = "reacquire current canonical evidence; do not continue from stale or conflicting state"
        reasons.add("handoff.fail-closed-currentness")
    elif state.outcome is OperationalOutcome.BLOCKED:
        reasons.add("handoff.blocked")
    elif state.outcome is OperationalOutcome.NEEDS_DECISION:
        reasons.add("handoff.needs-decision")

    return CodingCommandCenterHandoff(
        schema_name=CODING_COMMAND_CENTER_HANDOFF_SCHEMA_NAME,
        schema_version=CODING_COMMAND_CENTER_HANDOFF_SCHEMA_VERSION,
        repository=state.repository,
        issue_number=state.issue_number,
        pull_request_number=primary_pr,
        observed_head_sha=evidence.observed_head_sha,
        canonical_state_reference=state.state_id,
        current_stage=state.lifecycle_stage.value,
        smallest_next_action=smallest_next_action,
        executor_route=executor_route,
        executor_route_decision_id=executor_route_decision_id,
        validation_classification=validation_classification,
        validation_evidence_reference=evidence.validation_evidence_reference,
        primary_blocker=blocker,
        handoff_target=handoff_target,
        source_revision=evidence.source_revision,
        reason_codes=tuple(sorted(reasons)),
    )


def serialize_coding_command_center_handoff(
    handoff: CodingCommandCenterHandoff,
) -> dict[str, object]:
    if type(handoff) is not CodingCommandCenterHandoff:
        raise TypeError("handoff must be exact CodingCommandCenterHandoff")
    handoff.__post_init__()
    return handoff.to_dict()


def render_coding_command_center_handoff(
    handoff: CodingCommandCenterHandoff,
) -> str:
    """Render #926-compatible operator ordering without adding new semantics."""
    payload = serialize_coding_command_center_handoff(handoff)
    route = payload["executor_route"] or _UNAVAILABLE
    validation = payload["validation_classification"] or _UNAVAILABLE
    blocker = payload["primary_blocker"] or _UNAVAILABLE
    target = f"{payload['repository']}#{payload['issue_number']}"
    lines = (
        f"Current target: {target}",
        f"Smallest safe next action: {payload['smallest_next_action']}",
        f"Route / escalation reason: {route}",
        f"Validation or blocker evidence: validation={validation}; blocker={blocker}",
        f"Handoff target: {payload['handoff_target'] or _UNAVAILABLE}",
        f"Canonical state: {payload['canonical_state_reference']}",
        f"Source revision: {payload['source_revision']}",
        "authority_created: false",
        "side_effects_performed: false",
        "notion_write_performed: false",
    )
    return "\n".join(lines)


def _state_next_action(state: IssueOperationalState) -> str:
    # Fail-closed currentness outranks every other projection.
    if state.outcome in {OperationalOutcome.STALE, OperationalOutcome.CONFLICTING, OperationalOutcome.INVALID}:
        return "reacquire current canonical evidence; do not continue from stale or conflicting state"
    if state.outcome is OperationalOutcome.TERMINAL:
        return "no implementation action; preserve terminal state"
    # The canonical primary blocker owns ordering; this only reads it, never reranks.
    primary_blocker = state.blocker_codes[0] if state.blocker_codes else None
    if primary_blocker == "validation.failed":
        return "classify the validation failure before repair or retry"
    if primary_blocker == "validation.pending":
        return "await current validation evidence"
    if state.outcome is OperationalOutcome.BLOCKED:
        return "clear the primary canonical blocker before continuing"
    if state.outcome is OperationalOutcome.NEEDS_DECISION:
        return "obtain the required human decision before continuing"
    return "continue with the canonical action for the current lifecycle stage"


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _required_text(value: object, name: str) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > MAX_TEXT_BYTES or _CONTROL_RE.search(value):
        raise ValueError(f"{name} is outside bounds")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, name)


def _sha40(value: object, name: str) -> str:
    text = _required_text(value, name)
    if not _SHA40_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase 40-character SHA")
    return text


def _canonical_reasons(values: object) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError("reason_codes must be an exact tuple")
    if len(values) > MAX_REASON_CODES:
        raise ValueError("reason_codes exceeds bound")
    checked = tuple(_required_text(item, "reason_code") for item in values)
    if len(set(checked)) != len(checked):
        raise ValueError("reason_codes contains duplicates")
    return tuple(sorted(checked))
