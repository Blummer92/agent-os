"""Pure deterministic post-PR executable-lane planning adapter (#914)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from scripts.agent_os_issue_acceptance.executor_route import ExecutorRoute
from scripts.agent_os_issue_acceptance.post_pr_state_audit import (
    PostPrStateAuditResult,
    RecommendationOutcome,
    TerminalPrState,
)

from .executable_lane_selection import ExecutableLaneSelection, Queue

POST_PR_LANE_PLAN_SCHEMA_NAME = "agent-os-post-pr-lane-plan"
POST_PR_LANE_PLAN_SCHEMA_VERSION = "1.0"
MAX_REASON_CODES = 32
MAX_CONFLICT_FINDINGS = 16
MAX_SERIALIZED_BYTES = 64 * 1024
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class LanePlanOutcome(str, Enum):
    LANE_PLAN = "lane-plan"
    HUMAN_DECISION = "human-decision"


REASON_CODES = frozenset(
    {
        "plan.selector-precedence-preserved",
        "plan.audit-recommendation-selected",
        "plan.audit-alternate-selected",
        "plan.no-audit-recommendation",
        "conflict.audit-human-decision",
        "conflict.recommendation-absent",
        "conflict.recommendation-waiting-authorization",
        "conflict.recommendation-waiting-dependency",
        "conflict.recommendation-terminal",
        "conflict.recommendation-invalid",
        "conflict.recommendation-lower-precedence",
        "conflict.recommendation-exact-required",
        "conflict.alternate-unsupported",
        "conflict.source-identity",
        "conflict.duplicate-evidence",
    }
)


@dataclass(frozen=True, slots=True)
class ConflictFinding:
    reason_code: str
    issue_number: int | None = None

    def __post_init__(self) -> None:
        if self.reason_code not in REASON_CODES or not self.reason_code.startswith("conflict."):
            raise ValueError("unsupported conflict reason code")
        if self.issue_number is not None and (type(self.issue_number) is not int or self.issue_number < 1):
            raise TypeError("issue_number must be a positive built-in integer or None")

    def to_dict(self) -> dict[str, object]:
        return {"reason_code": self.reason_code, "issue_number": self.issue_number}


@dataclass(frozen=True, slots=True)
class PostPrLanePlan:
    schema_name: Literal["agent-os-post-pr-lane-plan"]
    schema_version: Literal["1.0"]
    source_executable_lane_selection_id: str
    source_post_pr_audit_id: str
    terminal_pr_state: TerminalPrState
    outcome: LanePlanOutcome
    selected_lane_issue_numbers: tuple[int, ...]
    primary_next_issue: int | None
    alternate_issue: int | None
    recommended_executor_route: ExecutorRoute | None
    smallest_next_action: str
    reason_codes: tuple[str, ...]
    conflict_findings: tuple[ConflictFinding, ...]
    plan_id: str = ""
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)
    scheduler_invoked: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != POST_PR_LANE_PLAN_SCHEMA_NAME or self.schema_version != POST_PR_LANE_PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported post-PR lane-plan schema")
        if not isinstance(self.terminal_pr_state, TerminalPrState):
            raise TypeError("terminal_pr_state must be TerminalPrState")
        if not isinstance(self.outcome, LanePlanOutcome):
            raise TypeError("outcome must be LanePlanOutcome")
        if type(self.selected_lane_issue_numbers) is not tuple:
            raise TypeError("selected_lane_issue_numbers must be an exact tuple")
        if not 1 <= len(self.selected_lane_issue_numbers) <= 3:
            raise ValueError("selected_lane_issue_numbers must contain 1 through 3 lanes")
        if any(type(v) is not int or v < 1 for v in self.selected_lane_issue_numbers):
            raise TypeError("selected lanes must be positive built-in integers")
        if len(set(self.selected_lane_issue_numbers)) != len(self.selected_lane_issue_numbers):
            raise ValueError("selected lanes contain duplicates")
        for name in ("primary_next_issue", "alternate_issue"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 1):
                raise TypeError(f"{name} must be a positive built-in integer or None")
        if self.recommended_executor_route is not None and not isinstance(self.recommended_executor_route, ExecutorRoute):
            raise TypeError("recommended_executor_route must be ExecutorRoute or None")
        if type(self.smallest_next_action) is not str or not self.smallest_next_action or _CONTROL_RE.search(self.smallest_next_action):
            raise ValueError("smallest_next_action is outside bounds")
        reasons = tuple(sorted(set(self.reason_codes)))
        if len(reasons) > MAX_REASON_CODES or any(reason not in REASON_CODES for reason in reasons):
            raise ValueError("reason_codes contains unsupported or oversized evidence")
        object.__setattr__(self, "reason_codes", reasons)
        if type(self.conflict_findings) is not tuple or any(type(v) is not ConflictFinding for v in self.conflict_findings):
            raise TypeError("conflict_findings must be an exact tuple of ConflictFinding")
        conflicts = tuple(
            sorted(
                set(self.conflict_findings),
                key=lambda item: (item.reason_code, item.issue_number or 0),
            )
        )
        if len(conflicts) > MAX_CONFLICT_FINDINGS:
            raise ValueError("conflict_findings exceeds bound")
        object.__setattr__(self, "conflict_findings", conflicts)
        if self.execution_authorized or self.side_effects_performed or self.scheduler_invoked:
            raise ValueError("lane plan cannot authorize or perform execution, side effects, or scheduling")
        expected = _plan_id(self._payload())
        if self.plan_id and self.plan_id != expected:
            raise ValueError("plan_id does not match lane-plan content")
        object.__setattr__(self, "plan_id", expected)
        if len(_canonical_json(self.to_dict()).encode("utf-8")) > MAX_SERIALIZED_BYTES:
            raise ValueError("lane plan exceeds serialized bound")

    def _payload(self) -> dict[str, object]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "source_executable_lane_selection_id": self.source_executable_lane_selection_id,
            "source_post_pr_audit_id": self.source_post_pr_audit_id,
            "terminal_pr_state": self.terminal_pr_state.value,
            "outcome": self.outcome.value,
            "selected_lane_issue_numbers": list(self.selected_lane_issue_numbers),
            "primary_next_issue": self.primary_next_issue,
            "alternate_issue": self.alternate_issue,
            "recommended_executor_route": self.recommended_executor_route.value if self.recommended_executor_route else None,
            "smallest_next_action": self.smallest_next_action,
            "reason_codes": list(self.reason_codes),
            "conflict_findings": [finding.to_dict() for finding in self.conflict_findings],
            "execution_authorized": False,
            "side_effects_performed": False,
            "scheduler_invoked": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "plan_id": self.plan_id}

    @classmethod
    def from_dict(cls, payload: object) -> "PostPrLanePlan":
        if type(payload) is not dict:
            raise TypeError("lane plan must be an exact object")
        expected = {
            "schema_name", "schema_version", "source_executable_lane_selection_id", "source_post_pr_audit_id",
            "terminal_pr_state", "outcome", "selected_lane_issue_numbers", "primary_next_issue", "alternate_issue",
            "recommended_executor_route", "smallest_next_action", "reason_codes", "conflict_findings", "plan_id",
            "execution_authorized", "side_effects_performed", "scheduler_invoked",
        }
        if set(payload) != expected:
            raise ValueError("lane plan contains unknown or missing fields")
        if payload["execution_authorized"] is not False or payload["side_effects_performed"] is not False or payload["scheduler_invoked"] is not False:
            raise ValueError("lane plan authority/side-effect fields must be false")
        if type(payload["selected_lane_issue_numbers"]) is not list or type(payload["reason_codes"]) is not list or type(payload["conflict_findings"]) is not list:
            raise TypeError("lane-plan collections must be exact JSON arrays")
        supplied_plan_id = payload["plan_id"]
        if type(supplied_plan_id) is not str:
            raise TypeError("plan_id must be a built-in string")
        route = None if payload["recommended_executor_route"] is None else ExecutorRoute(payload["recommended_executor_route"])
        plan = cls(
            schema_name=payload["schema_name"], schema_version=payload["schema_version"],
            source_executable_lane_selection_id=payload["source_executable_lane_selection_id"],
            source_post_pr_audit_id=payload["source_post_pr_audit_id"], terminal_pr_state=TerminalPrState(payload["terminal_pr_state"]),
            outcome=LanePlanOutcome(payload["outcome"]), selected_lane_issue_numbers=tuple(payload["selected_lane_issue_numbers"]),
            primary_next_issue=payload["primary_next_issue"], alternate_issue=payload["alternate_issue"],
            recommended_executor_route=route, smallest_next_action=payload["smallest_next_action"],
            reason_codes=tuple(payload["reason_codes"]),
            conflict_findings=tuple(ConflictFinding(**item) for item in payload["conflict_findings"]), plan_id=supplied_plan_id,
        )
        if supplied_plan_id != plan.plan_id:
            raise ValueError("plan_id does not match lane-plan content")
        return plan


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _plan_id(payload: object) -> str:
    material = b"agent-os-post-pr-lane-plan:v1\0" + _canonical_json(payload).encode("utf-8")
    return f"post-pr-lane-plan:{hashlib.sha256(material).hexdigest()}"


def _queue_for(selection: ExecutableLaneSelection, issue_number: int) -> Queue | None:
    match = next((item for item in selection.queue_classifications if item.issue_number == issue_number), None)
    return None if match is None else match.queue


def _conflict_for_recommendation(selection: ExecutableLaneSelection, issue_number: int) -> str | None:
    queue = _queue_for(selection, issue_number)
    if queue is None:
        return "conflict.recommendation-absent"
    if queue is Queue.WAITING_FOR_AUTHORIZATION:
        return "conflict.recommendation-waiting-authorization"
    if queue is Queue.WAITING_FOR_DEPENDENCY:
        return "conflict.recommendation-waiting-dependency"
    if queue is Queue.TERMINAL:
        return "conflict.recommendation-terminal"
    if queue is Queue.INVALID:
        return "conflict.recommendation-invalid"
    if issue_number not in selection.selected_lanes:
        exact_required = any(
            record.displaced_issue_number == issue_number and record.reason_code == "replacement.blocked-exact-required-not-substituted"
            for record in selection.replacement_records
        )
        return "conflict.recommendation-exact-required" if exact_required else "conflict.recommendation-lower-precedence"
    return None


def plan_post_pr_lane(selection: ExecutableLaneSelection, audit: PostPrStateAuditResult) -> PostPrLanePlan:
    """Reconcile canonical selector precedence with advisory post-PR evidence."""
    if type(selection) is not ExecutableLaneSelection or type(audit) is not PostPrStateAuditResult:
        raise TypeError("exact canonical source types are required")
    # Re-run source invariants so object.__setattr__ tampering fails closed.
    try:
        selection.__post_init__()
        audit.__post_init__()
    except (TypeError, ValueError) as exc:
        raise ValueError("source identity or content validation failed") from exc

    lanes = selection.selected_lanes
    if not lanes:
        raise ValueError("selector supplied no executable lane")
    reasons = {"plan.selector-precedence-preserved"}
    conflicts: list[ConflictFinding] = []
    outcome = LanePlanOutcome.LANE_PLAN
    primary = lanes[0]
    alternate = None
    route = None

    if audit.outcome is RecommendationOutcome.HUMAN_DECISION:
        outcome = LanePlanOutcome.HUMAN_DECISION
        conflicts.append(ConflictFinding("conflict.audit-human-decision"))
    elif audit.recommended_issue is None:
        reasons.add("plan.no-audit-recommendation")
    else:
        conflict = _conflict_for_recommendation(selection, audit.recommended_issue)
        if conflict:
            outcome = LanePlanOutcome.HUMAN_DECISION
            conflicts.append(ConflictFinding(conflict, audit.recommended_issue))
        else:
            reasons.add("plan.audit-recommendation-selected")
            if audit.recommended_issue == primary:
                route = audit.recommended_executor_route

    if audit.alternate_issue is not None:
        if audit.alternate_issue not in lanes:
            outcome = LanePlanOutcome.HUMAN_DECISION
            conflicts.append(ConflictFinding("conflict.alternate-unsupported", audit.alternate_issue))
        else:
            reasons.add("plan.audit-alternate-selected")
            alternate = audit.alternate_issue

    for finding in conflicts:
        reasons.add(finding.reason_code)
    conflicts_tuple = tuple(sorted(conflicts, key=lambda item: (item.reason_code, item.issue_number or 0)))
    if outcome is LanePlanOutcome.HUMAN_DECISION:
        primary = None
        alternate = None
        route = ExecutorRoute.HUMAN_DECISION
        action = "Escalate conflicting post-PR lane evidence to human decision."
    else:
        action = f"Open #{primary}."

    return PostPrLanePlan(
        schema_name=POST_PR_LANE_PLAN_SCHEMA_NAME,
        schema_version=POST_PR_LANE_PLAN_SCHEMA_VERSION,
        source_executable_lane_selection_id=selection.selection_id,
        source_post_pr_audit_id=audit.audit_id,
        terminal_pr_state=audit.terminal_state,
        outcome=outcome,
        selected_lane_issue_numbers=lanes,
        primary_next_issue=primary,
        alternate_issue=alternate,
        recommended_executor_route=route,
        smallest_next_action=action,
        reason_codes=tuple(reasons),
        conflict_findings=conflicts_tuple,
    )


def serialize_post_pr_lane_plan(plan: PostPrLanePlan) -> str:
    if type(plan) is not PostPrLanePlan:
        raise TypeError("plan must be an exact PostPrLanePlan")
    return _canonical_json(plan.to_dict())


def deserialize_post_pr_lane_plan(payload: str) -> PostPrLanePlan:
    if type(payload) is not str:
        raise TypeError("payload must be a built-in string")
    if len(payload.encode("utf-8")) > MAX_SERIALIZED_BYTES:
        raise ValueError("serialized lane plan exceeds bound")
    value = json.loads(payload)
    return PostPrLanePlan.from_dict(value)
