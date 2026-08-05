"""Pure-local, deterministic executable lane selection (AOS-QUEUE2, #864).

Classifies every supplied issue -- given its canonical `IssueOperationalState`
(#862) and `AgentOperatingModeDecision` (#863) -- into exactly one next-action
queue, selects up to three productive lanes, and records bounded, finite-reason
replacement decisions. Performs no GitHub, network, filesystem, subprocess,
Scheduler, provider, credential, production, or external-system calls, and no
issue, label, branch, commit, PR, comment, merge, closure, or repository
mutation. Queue placement is descriptive only -- it never widens, infers, or
collapses an authority field already carried by the supplied inputs.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from scripts.agent_os_issue_acceptance.issue_operational_state import (
    ClaimState,
    DependencyState,
    IssueOperationalState,
    LifecycleStage,
    OperationalOutcome,
)
from scripts.agent_os_issue_acceptance.operating_mode import (
    AgentOperatingModeDecision,
    OperatingModeOutcome,
)

EXECUTABLE_LANE_SELECTION_SCHEMA_NAME = "agent-os-executable-lane-selection"
EXECUTABLE_LANE_SELECTION_SCHEMA_VERSION = "1.0"

MIN_LANE_COUNT = 1
MAX_LANE_COUNT = 3
MAX_CANDIDATES = 64
MAX_REASON_CODES = 128
MAX_SERIALIZED_BYTES = 128 * 1024

_SHA256_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}:[0-9a-f]{64}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class Queue(str, Enum):
    READY_FOR_IMPLEMENTATION = "ready-for-implementation"
    READY_FOR_REVIEW = "ready-for-review"
    WAITING_FOR_AUTHORIZATION = "waiting-for-authorization"
    WAITING_FOR_DEPENDENCY = "waiting-for-dependency"
    MERGED_NEEDS_CLOSURE = "merged-needs-closure"
    NEEDS_RECONCILIATION = "needs-reconciliation"
    PLANNING_ONLY = "planning-only"
    TERMINAL = "terminal"
    INVALID = "invalid"


REASON_CODES = frozenset(
    {
        "queue.ready-for-implementation",
        "queue.ready-for-review",
        "queue.waiting-for-authorization",
        "queue.waiting-for-dependency",
        "queue.merged-needs-closure",
        "queue.needs-reconciliation",
        "queue.planning-only",
        "queue.terminal",
        "queue.invalid",
        "duplicate-claim.multiple-primary",
        "replacement.blocked-preferred-substituted",
        "replacement.blocked-exact-required-not-substituted",
    }
)

_QUEUE_REASON_CODE = {
    Queue.READY_FOR_IMPLEMENTATION: "queue.ready-for-implementation",
    Queue.READY_FOR_REVIEW: "queue.ready-for-review",
    Queue.WAITING_FOR_AUTHORIZATION: "queue.waiting-for-authorization",
    Queue.WAITING_FOR_DEPENDENCY: "queue.waiting-for-dependency",
    Queue.MERGED_NEEDS_CLOSURE: "queue.merged-needs-closure",
    Queue.NEEDS_RECONCILIATION: "queue.needs-reconciliation",
    Queue.PLANNING_ONLY: "queue.planning-only",
    Queue.TERMINAL: "queue.terminal",
    Queue.INVALID: "queue.invalid",
}

# Lower tier sorts first. Tiers 1-4 are "productive" (may consume a lane);
# tiers 5-7 remain visible but never consume one.
_QUEUE_TIER = {
    Queue.READY_FOR_IMPLEMENTATION: 1,
    Queue.READY_FOR_REVIEW: 2,
    Queue.NEEDS_RECONCILIATION: 3,
    Queue.MERGED_NEEDS_CLOSURE: 3,
    Queue.PLANNING_ONLY: 4,
    Queue.WAITING_FOR_AUTHORIZATION: 5,
    Queue.WAITING_FOR_DEPENDENCY: 5,
    Queue.TERMINAL: 6,
    Queue.INVALID: 7,
}
_PRODUCTIVE_TIERS = frozenset({1, 2, 3, 4})

_LIFECYCLE_RANK = {
    LifecycleStage.PLANNING: 0,
    LifecycleStage.IMPLEMENTATION: 1,
    LifecycleStage.DRAFT_PR: 2,
    LifecycleStage.REVIEW: 3,
    LifecycleStage.MERGED: 4,
    LifecycleStage.CLOSED: 5,
}


def _exact_text(value: object, name: str, maximum: int = 512) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a built-in string")
    if not value or len(value.encode("utf-8")) > maximum or _CONTROL_RE.search(value):
        raise ValueError(f"{name} is outside bounds")
    return value


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise TypeError(f"{name} must be a positive built-in integer")
    return value


def _nonneg_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise TypeError(f"{name} must be a non-negative built-in integer")
    return value


def _exact_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a built-in bool")
    return value


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _selection_id(payload: object) -> str:
    material = b"agent-os-executable-lane-selection:v1\0" + _canonical_json(payload).encode(
        "utf-8"
    )
    return f"executable-lane-selection:{hashlib.sha256(material).hexdigest()}"


def _strict_keys(payload: dict[str, object], expected: frozenset[str], name: str) -> None:
    unknown = set(payload) - expected
    missing = expected - set(payload)
    if unknown:
        raise ValueError(f"{name} contains unknown fields: {sorted(unknown)}")
    if missing:
        raise ValueError(f"{name} is missing fields: {sorted(missing)}")


def _reason_code(value: object, name: str) -> str:
    text = _exact_text(value, name, 128)
    if text not in REASON_CODES:
        raise ValueError(f"{name} contains an unsupported reason code")
    return text


@dataclass(frozen=True, slots=True)
class CandidateIssueEvidence:
    """One supplied issue's canonical evidence pair plus caller context.

    `dependency_depth` and `substitutable` are caller-supplied structured
    context, not derived from issue prose or live GitHub state. `substitutable`
    marks a caller's explicit request as preferred-but-substitutable (`True`,
    the default) versus exact-required (`False`); only meaningful when the
    issue also appears in `explicit_request_order`.
    """

    issue_number: int
    operational_state: IssueOperationalState
    mode_decision: AgentOperatingModeDecision
    dependency_depth: int
    substitutable: bool = True

    def __post_init__(self) -> None:
        _positive_int(self.issue_number, "issue_number")
        if type(self.operational_state) is not IssueOperationalState:
            raise TypeError("operational_state must be an exact IssueOperationalState")
        if type(self.mode_decision) is not AgentOperatingModeDecision:
            raise TypeError("mode_decision must be an exact AgentOperatingModeDecision")
        if self.operational_state.issue_number != self.issue_number:
            raise ValueError("operational_state does not match issue_number")
        if self.mode_decision.source_operational_state_id != self.operational_state.state_id:
            raise ValueError("mode_decision does not match operational_state identity")
        _nonneg_int(self.dependency_depth, "dependency_depth")
        _exact_bool(self.substitutable, "substitutable")


@dataclass(frozen=True, slots=True)
class QueueClassification:
    issue_number: int
    queue: Queue
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _positive_int(self.issue_number, "issue_number")
        if not isinstance(self.queue, Queue):
            raise TypeError("queue must be Queue")
        object.__setattr__(
            self, "reason_codes", tuple(_reason_code(v, "reason_codes") for v in self.reason_codes)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "queue": self.queue.value,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, payload: object) -> QueueClassification:
        if type(payload) is not dict:
            raise TypeError("queue classification must be an exact object")
        _strict_keys(payload, frozenset({"issue_number", "queue", "reason_codes"}), "queue classification")
        try:
            queue = Queue(payload["queue"])
        except (TypeError, ValueError) as exc:
            raise ValueError("queue classification queue is unsupported") from exc
        if type(payload["reason_codes"]) is not list:
            raise TypeError("queue classification reason_codes must be an exact JSON array")
        return cls(
            issue_number=payload["issue_number"],
            queue=queue,
            reason_codes=tuple(payload["reason_codes"]),
        )


@dataclass(frozen=True, slots=True)
class RankEvidence:
    issue_number: int
    rank: int
    tier: int
    explicit_request_position: int | None
    dependency_depth: int

    def __post_init__(self) -> None:
        _positive_int(self.issue_number, "issue_number")
        _positive_int(self.rank, "rank")
        _positive_int(self.tier, "tier")
        if self.explicit_request_position is not None:
            _nonneg_int(self.explicit_request_position, "explicit_request_position")
        _nonneg_int(self.dependency_depth, "dependency_depth")

    def to_dict(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "rank": self.rank,
            "tier": self.tier,
            "explicit_request_position": self.explicit_request_position,
            "dependency_depth": self.dependency_depth,
        }

    @classmethod
    def from_dict(cls, payload: object) -> RankEvidence:
        if type(payload) is not dict:
            raise TypeError("rank evidence must be an exact object")
        _strict_keys(
            payload,
            frozenset(
                {"issue_number", "rank", "tier", "explicit_request_position", "dependency_depth"}
            ),
            "rank evidence",
        )
        return cls(
            issue_number=payload["issue_number"],
            rank=payload["rank"],
            tier=payload["tier"],
            explicit_request_position=payload["explicit_request_position"],
            dependency_depth=payload["dependency_depth"],
        )


@dataclass(frozen=True, slots=True)
class ReplacementRecord:
    displaced_issue_number: int
    replacement_issue_number: int
    reason_code: str

    def __post_init__(self) -> None:
        _positive_int(self.displaced_issue_number, "displaced_issue_number")
        _positive_int(self.replacement_issue_number, "replacement_issue_number")
        object.__setattr__(self, "reason_code", _reason_code(self.reason_code, "reason_code"))

    def to_dict(self) -> dict[str, object]:
        return {
            "displaced_issue_number": self.displaced_issue_number,
            "replacement_issue_number": self.replacement_issue_number,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, payload: object) -> ReplacementRecord:
        if type(payload) is not dict:
            raise TypeError("replacement record must be an exact object")
        _strict_keys(
            payload,
            frozenset({"displaced_issue_number", "replacement_issue_number", "reason_code"}),
            "replacement record",
        )
        return cls(
            displaced_issue_number=payload["displaced_issue_number"],
            replacement_issue_number=payload["replacement_issue_number"],
            reason_code=payload["reason_code"],
        )


@dataclass(frozen=True, slots=True)
class DuplicateClaimFinding:
    issue_number: int
    claim_count: int
    reason_code: str

    def __post_init__(self) -> None:
        _positive_int(self.issue_number, "issue_number")
        if type(self.claim_count) is not int or self.claim_count < 2:
            raise TypeError("claim_count must be a built-in integer of at least 2")
        object.__setattr__(self, "reason_code", _reason_code(self.reason_code, "reason_code"))

    def to_dict(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "claim_count": self.claim_count,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, payload: object) -> DuplicateClaimFinding:
        if type(payload) is not dict:
            raise TypeError("duplicate claim finding must be an exact object")
        _strict_keys(
            payload, frozenset({"issue_number", "claim_count", "reason_code"}), "duplicate claim finding"
        )
        return cls(
            issue_number=payload["issue_number"],
            claim_count=payload["claim_count"],
            reason_code=payload["reason_code"],
        )


@dataclass(frozen=True, slots=True)
class ExecutableLaneSelection:
    """Immutable `agent-os-executable-lane-selection/1.0` result.

    Pure descriptive output: queue placement, selected lanes, and replacement
    records never create readiness or authority. `execution_authorized` and
    `side_effects_performed` are always `False`.
    """

    schema_name: Literal["agent-os-executable-lane-selection"]
    schema_version: Literal["1.0"]
    campaign_id: str
    requested_lane_count: int
    substitution_allowed: bool
    supplied_issue_numbers: tuple[int, ...]
    source_operational_state_ids: tuple[str, ...]
    source_operating_mode_decision_ids: tuple[str, ...]
    queue_classifications: tuple[QueueClassification, ...]
    selected_lanes: tuple[int, ...]
    deferred_candidates: tuple[int, ...]
    replacement_records: tuple[ReplacementRecord, ...]
    rank_evidence: tuple[RankEvidence, ...]
    duplicate_claim_findings: tuple[DuplicateClaimFinding, ...]
    reason_codes: tuple[str, ...]
    selection_id: str = ""
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_name != EXECUTABLE_LANE_SELECTION_SCHEMA_NAME
            or self.schema_version != EXECUTABLE_LANE_SELECTION_SCHEMA_VERSION
        ):
            raise ValueError("unsupported executable lane selection schema")
        _exact_text(self.campaign_id, "campaign_id", 256)
        if (
            type(self.requested_lane_count) is not int
            or not (MIN_LANE_COUNT <= self.requested_lane_count <= MAX_LANE_COUNT)
        ):
            raise ValueError("requested_lane_count must be a built-in integer from 1 through 3")
        _exact_bool(self.substitution_allowed, "substitution_allowed")

        if type(self.supplied_issue_numbers) is not tuple:
            raise TypeError("supplied_issue_numbers must be an exact tuple")
        if any(type(v) is not int or v < 1 for v in self.supplied_issue_numbers):
            raise TypeError("supplied_issue_numbers must contain positive integers")
        if tuple(sorted(set(self.supplied_issue_numbers))) != self.supplied_issue_numbers:
            raise ValueError("supplied_issue_numbers must be sorted and unique")

        for name in ("source_operational_state_ids", "source_operating_mode_decision_ids"):
            values = getattr(self, name)
            if type(values) is not tuple:
                raise TypeError(f"{name} must be an exact tuple")
            checked = tuple(_exact_text(v, name, 128) for v in values)
            for v in checked:
                if not _SHA256_ID_RE.fullmatch(v):
                    raise ValueError(f"{name} contains a malformed identity")
            deduped_sorted = tuple(sorted(set(checked)))
            if deduped_sorted != checked:
                raise ValueError(f"{name} must be sorted and unique")
            object.__setattr__(self, name, checked)

        if type(self.queue_classifications) is not tuple or any(
            type(v) is not QueueClassification for v in self.queue_classifications
        ):
            raise TypeError("queue_classifications must be an exact tuple of QueueClassification")
        classified_numbers = tuple(qc.issue_number for qc in self.queue_classifications)
        if tuple(sorted(classified_numbers)) != self.supplied_issue_numbers:
            raise ValueError("queue_classifications must classify every supplied issue exactly once")

        for name in ("selected_lanes", "deferred_candidates"):
            values = getattr(self, name)
            if type(values) is not tuple or any(type(v) is not int or v < 1 for v in values):
                raise TypeError(f"{name} must be an exact tuple of positive integers")
        if len(self.selected_lanes) > self.requested_lane_count:
            raise ValueError("selected_lanes exceeds requested_lane_count")
        if len(set(self.selected_lanes)) != len(self.selected_lanes):
            raise ValueError("selected_lanes contains duplicates")
        if set(self.selected_lanes) & set(self.deferred_candidates):
            raise ValueError("selected_lanes and deferred_candidates must be disjoint")
        if set(self.selected_lanes) | set(self.deferred_candidates) != set(self.supplied_issue_numbers):
            raise ValueError("selected_lanes and deferred_candidates must partition supplied issues")

        if type(self.replacement_records) is not tuple or any(
            type(v) is not ReplacementRecord for v in self.replacement_records
        ):
            raise TypeError("replacement_records must be an exact tuple of ReplacementRecord")

        if type(self.rank_evidence) is not tuple or any(
            type(v) is not RankEvidence for v in self.rank_evidence
        ):
            raise TypeError("rank_evidence must be an exact tuple of RankEvidence")
        ranked_numbers = tuple(sorted(r.issue_number for r in self.rank_evidence))
        if ranked_numbers != self.supplied_issue_numbers:
            raise ValueError("rank_evidence must rank every supplied issue exactly once")

        if type(self.duplicate_claim_findings) is not tuple or any(
            type(v) is not DuplicateClaimFinding for v in self.duplicate_claim_findings
        ):
            raise TypeError("duplicate_claim_findings must be an exact tuple of DuplicateClaimFinding")

        reasons = tuple(sorted(set(_reason_code(v, "reason_codes") for v in self.reason_codes)))
        if len(reasons) > MAX_REASON_CODES:
            raise ValueError("reason_codes exceeds its bound")
        object.__setattr__(self, "reason_codes", reasons)

        if self.execution_authorized is not False:
            raise ValueError("executable lane selection cannot authorize execution")
        if self.side_effects_performed is not False:
            raise ValueError("executable lane selection cannot record side effects")

        expected = _selection_id(self._payload())
        if self.selection_id and self.selection_id != expected:
            raise ValueError("selection_id does not match executable lane selection content")
        object.__setattr__(self, "selection_id", expected)
        if len(_canonical_json(self.to_dict()).encode("utf-8")) > MAX_SERIALIZED_BYTES:
            raise ValueError("executable lane selection exceeds serialized bound")

    def _payload(self) -> dict[str, object]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "requested_lane_count": self.requested_lane_count,
            "substitution_allowed": self.substitution_allowed,
            "supplied_issue_numbers": list(self.supplied_issue_numbers),
            "source_operational_state_ids": list(self.source_operational_state_ids),
            "source_operating_mode_decision_ids": list(self.source_operating_mode_decision_ids),
            "queue_classifications": [qc.to_dict() for qc in self.queue_classifications],
            "selected_lanes": list(self.selected_lanes),
            "deferred_candidates": list(self.deferred_candidates),
            "replacement_records": [r.to_dict() for r in self.replacement_records],
            "rank_evidence": [r.to_dict() for r in self.rank_evidence],
            "duplicate_claim_findings": [d.to_dict() for d in self.duplicate_claim_findings],
            "reason_codes": list(self.reason_codes),
            "execution_authorized": False,
            "side_effects_performed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "selection_id": self.selection_id}


def _classify(candidate: CandidateIssueEvidence) -> tuple[Queue, str]:
    state = candidate.operational_state
    mode = candidate.mode_decision

    if state.outcome is OperationalOutcome.INVALID or mode.outcome is OperatingModeOutcome.INVALID:
        queue = Queue.INVALID
    elif state.claim_state is ClaimState.CONFLICTING:
        queue = Queue.NEEDS_RECONCILIATION
    elif (
        state.claim_state is ClaimState.SINGLE
        and "reconciliation.merged-pr-open-issue" in state.reason_codes
    ):
        queue = Queue.MERGED_NEEDS_CLOSURE
    elif state.reconciliation_required:
        queue = Queue.NEEDS_RECONCILIATION
    elif state.outcome is OperationalOutcome.TERMINAL:
        queue = Queue.TERMINAL
    elif state.outcome is OperationalOutcome.BLOCKED and state.dependency_state is DependencyState.BLOCKED:
        queue = Queue.WAITING_FOR_DEPENDENCY
    elif state.outcome in (
        OperationalOutcome.BLOCKED,
        OperationalOutcome.NEEDS_DECISION,
        OperationalOutcome.STALE,
        OperationalOutcome.CONFLICTING,
    ):
        queue = Queue.WAITING_FOR_AUTHORIZATION
    elif state.claim_state is ClaimState.SINGLE:
        if _LIFECYCLE_RANK[mode.maximum_permitted_stage] >= _LIFECYCLE_RANK[LifecycleStage.REVIEW]:
            queue = Queue.READY_FOR_REVIEW
        else:
            queue = Queue.WAITING_FOR_AUTHORIZATION
    elif mode.outcome in (OperatingModeOutcome.BLOCKED, OperatingModeOutcome.NEEDS_DECISION):
        queue = Queue.WAITING_FOR_AUTHORIZATION
    elif _LIFECYCLE_RANK[mode.maximum_permitted_stage] >= _LIFECYCLE_RANK[LifecycleStage.IMPLEMENTATION]:
        queue = Queue.READY_FOR_IMPLEMENTATION
    else:
        queue = Queue.PLANNING_ONLY

    return queue, _QUEUE_REASON_CODE[queue]


def _rank_key(
    candidate: CandidateIssueEvidence,
    queue: Queue,
    explicit_position: dict[int, int],
    sentinel: int,
) -> tuple[int, int, int, int]:
    tier = _QUEUE_TIER[queue]
    position = explicit_position.get(candidate.issue_number, sentinel)
    return (tier, position, candidate.dependency_depth, candidate.issue_number)


def select_executable_lanes(
    *,
    campaign_id: str,
    requested_lane_count: int,
    substitution_allowed: bool,
    explicit_request_order: tuple[int, ...],
    candidates: tuple[CandidateIssueEvidence, ...],
) -> ExecutableLaneSelection:
    """Classify, rank, and select up to `requested_lane_count` productive lanes.

    Pure local computation only; performs no execution or mutation. Fails
    closed on malformed, duplicated, or tampered input rather than guessing.
    """

    _exact_text(campaign_id, "campaign_id", 256)
    if type(requested_lane_count) is not int or not (
        MIN_LANE_COUNT <= requested_lane_count <= MAX_LANE_COUNT
    ):
        raise ValueError("requested_lane_count must be a built-in integer from 1 through 3")
    _exact_bool(substitution_allowed, "substitution_allowed")

    if type(candidates) is not tuple or any(
        type(c) is not CandidateIssueEvidence for c in candidates
    ):
        raise TypeError("candidates must be an exact tuple of CandidateIssueEvidence")
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError("candidates exceeds its bound")
    issue_numbers = tuple(c.issue_number for c in candidates)
    if len(set(issue_numbers)) != len(issue_numbers):
        raise ValueError("candidates contains duplicate issue numbers")

    if type(explicit_request_order) is not tuple or any(
        type(v) is not int for v in explicit_request_order
    ):
        raise TypeError("explicit_request_order must be an exact tuple of integers")
    if len(set(explicit_request_order)) != len(explicit_request_order):
        raise ValueError("explicit_request_order contains duplicates")
    if len(explicit_request_order) > MAX_CANDIDATES:
        raise ValueError("explicit_request_order exceeds its bound")
    known = set(issue_numbers)
    if any(v not in known for v in explicit_request_order):
        raise ValueError("explicit_request_order references an unsupplied issue")

    explicit_position = {
        issue_number: position for position, issue_number in enumerate(explicit_request_order)
    }
    sentinel = len(explicit_request_order)

    by_number = {c.issue_number: c for c in candidates}
    queue_by_number: dict[int, tuple[Queue, str]] = {
        c.issue_number: _classify(c) for c in candidates
    }

    sorted_candidates = sorted(
        candidates,
        key=lambda c: _rank_key(c, queue_by_number[c.issue_number][0], explicit_position, sentinel),
    )

    rank_evidence = tuple(
        RankEvidence(
            issue_number=c.issue_number,
            rank=index + 1,
            tier=_QUEUE_TIER[queue_by_number[c.issue_number][0]],
            explicit_request_position=explicit_position.get(c.issue_number),
            dependency_depth=c.dependency_depth,
        )
        for index, c in enumerate(sorted_candidates)
    )

    top_level_reasons: set[str] = {reason for _, reason in queue_by_number.values()}

    duplicate_claim_findings = tuple(
        sorted(
            (
                DuplicateClaimFinding(
                    issue_number=c.issue_number,
                    claim_count=len(c.operational_state.primary_pr_numbers),
                    reason_code="duplicate-claim.multiple-primary",
                )
                for c in candidates
                if c.operational_state.claim_state is ClaimState.CONFLICTING
            ),
            key=lambda finding: finding.issue_number,
        )
    )
    if duplicate_claim_findings:
        top_level_reasons.add("duplicate-claim.multiple-primary")

    # Multiple active primary claims are excluded from lane selection even
    # though needs-reconciliation is otherwise a productive tier.
    duplicate_claim_numbers = {
        c.issue_number
        for c in candidates
        if c.operational_state.claim_state is ClaimState.CONFLICTING
    }

    def _selectable(issue_number: int) -> bool:
        if issue_number in duplicate_claim_numbers:
            return False
        return _QUEUE_TIER[queue_by_number[issue_number][0]] in _PRODUCTIVE_TIERS

    selected: list[int] = []
    used: set[int] = set()
    replacements: list[ReplacementRecord] = []

    def _next_eligible_independent() -> int | None:
        for c in sorted_candidates:
            if c.issue_number in used:
                continue
            if queue_by_number[c.issue_number][0] is Queue.READY_FOR_IMPLEMENTATION:
                return c.issue_number
        return None

    for issue_number in explicit_request_order:
        if len(selected) >= requested_lane_count:
            break
        if issue_number in used:
            continue
        if _selectable(issue_number):
            selected.append(issue_number)
            used.add(issue_number)
            continue

        candidate = by_number[issue_number]
        if substitution_allowed and candidate.substitutable:
            replacement = _next_eligible_independent()
            used.add(issue_number)
            if replacement is not None:
                selected.append(replacement)
                used.add(replacement)
                replacements.append(
                    ReplacementRecord(
                        displaced_issue_number=issue_number,
                        replacement_issue_number=replacement,
                        reason_code="replacement.blocked-preferred-substituted",
                    )
                )
                top_level_reasons.add("replacement.blocked-preferred-substituted")
        else:
            used.add(issue_number)
            top_level_reasons.add("replacement.blocked-exact-required-not-substituted")

    for candidate in sorted_candidates:
        if len(selected) >= requested_lane_count:
            break
        if candidate.issue_number in used:
            continue
        if _selectable(candidate.issue_number):
            selected.append(candidate.issue_number)
            used.add(candidate.issue_number)

    selected_set = set(selected)
    deferred_candidates = tuple(
        c.issue_number for c in sorted_candidates if c.issue_number not in selected_set
    )

    queue_classifications = tuple(
        QueueClassification(
            issue_number=c.issue_number,
            queue=queue_by_number[c.issue_number][0],
            reason_codes=(queue_by_number[c.issue_number][1],),
        )
        for c in sorted(candidates, key=lambda c: c.issue_number)
    )

    return ExecutableLaneSelection(
        schema_name=EXECUTABLE_LANE_SELECTION_SCHEMA_NAME,
        schema_version=EXECUTABLE_LANE_SELECTION_SCHEMA_VERSION,
        campaign_id=campaign_id,
        requested_lane_count=requested_lane_count,
        substitution_allowed=substitution_allowed,
        supplied_issue_numbers=tuple(sorted(issue_numbers)),
        source_operational_state_ids=tuple(
            sorted({c.operational_state.state_id for c in candidates})
        ),
        source_operating_mode_decision_ids=tuple(
            sorted({c.mode_decision.decision_id for c in candidates})
        ),
        queue_classifications=queue_classifications,
        selected_lanes=tuple(selected),
        deferred_candidates=deferred_candidates,
        replacement_records=tuple(replacements),
        rank_evidence=rank_evidence,
        duplicate_claim_findings=duplicate_claim_findings,
        reason_codes=tuple(top_level_reasons),
    )


def serialize_executable_lane_selection(selection: ExecutableLaneSelection) -> str:
    if type(selection) is not ExecutableLaneSelection:
        raise TypeError("selection must be an exact ExecutableLaneSelection")
    return _canonical_json(selection.to_dict())


def deserialize_executable_lane_selection(serialized: object) -> ExecutableLaneSelection:
    if type(serialized) is not str:
        raise TypeError("serialized selection must be a built-in string")
    if len(serialized.encode("utf-8")) > MAX_SERIALIZED_BYTES:
        raise ValueError("serialized selection exceeds its bound")
    try:
        payload = json.loads(serialized)
    except json.JSONDecodeError as exc:
        raise ValueError("serialized selection is not valid JSON") from exc
    except RecursionError as exc:
        raise ValueError("serialized selection is nested too deeply") from exc
    if type(payload) is not dict:
        raise TypeError("serialized selection must contain an exact JSON object")

    expected = frozenset(
        {
            "schema_name",
            "schema_version",
            "campaign_id",
            "requested_lane_count",
            "substitution_allowed",
            "supplied_issue_numbers",
            "source_operational_state_ids",
            "source_operating_mode_decision_ids",
            "queue_classifications",
            "selected_lanes",
            "deferred_candidates",
            "replacement_records",
            "rank_evidence",
            "duplicate_claim_findings",
            "reason_codes",
            "execution_authorized",
            "side_effects_performed",
            "selection_id",
        }
    )
    _strict_keys(payload, expected, "executable lane selection")
    if payload.get("schema_name") != EXECUTABLE_LANE_SELECTION_SCHEMA_NAME:
        raise ValueError("unsupported executable lane selection schema name")
    if payload.get("schema_version") != EXECUTABLE_LANE_SELECTION_SCHEMA_VERSION:
        raise ValueError("unsupported executable lane selection schema version")
    if payload["execution_authorized"] is not False:
        raise ValueError("serialized selection cannot authorize execution")
    if payload["side_effects_performed"] is not False:
        raise ValueError("serialized selection cannot claim side effects")

    list_fields = (
        "supplied_issue_numbers",
        "source_operational_state_ids",
        "source_operating_mode_decision_ids",
        "queue_classifications",
        "selected_lanes",
        "deferred_candidates",
        "replacement_records",
        "rank_evidence",
        "duplicate_claim_findings",
        "reason_codes",
    )
    for key in list_fields:
        if type(payload[key]) is not list:
            raise TypeError(f"{key} must be an exact JSON array")

    return ExecutableLaneSelection(
        schema_name=payload["schema_name"],
        schema_version=payload["schema_version"],
        campaign_id=payload["campaign_id"],
        requested_lane_count=payload["requested_lane_count"],
        substitution_allowed=payload["substitution_allowed"],
        supplied_issue_numbers=tuple(payload["supplied_issue_numbers"]),
        source_operational_state_ids=tuple(payload["source_operational_state_ids"]),
        source_operating_mode_decision_ids=tuple(payload["source_operating_mode_decision_ids"]),
        queue_classifications=tuple(
            QueueClassification.from_dict(v) for v in payload["queue_classifications"]
        ),
        selected_lanes=tuple(payload["selected_lanes"]),
        deferred_candidates=tuple(payload["deferred_candidates"]),
        replacement_records=tuple(
            ReplacementRecord.from_dict(v) for v in payload["replacement_records"]
        ),
        rank_evidence=tuple(RankEvidence.from_dict(v) for v in payload["rank_evidence"]),
        duplicate_claim_findings=tuple(
            DuplicateClaimFinding.from_dict(v) for v in payload["duplicate_claim_findings"]
        ),
        reason_codes=tuple(payload["reason_codes"]),
        selection_id=payload["selection_id"],
    )
