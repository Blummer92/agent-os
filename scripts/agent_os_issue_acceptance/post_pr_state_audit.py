"""Pure deterministic post-PR state audit and next-work recommendation.

The audit consumes caller-supplied, already-normalized evidence only. It
performs no GitHub, network, filesystem, subprocess, environment, or
credential I/O; executes no work; mutates no lifecycle state; and creates no
authority. Repository/PR health is reported separately from subsystem
maturity, and evidence that is incomplete, conflicting, or ambiguous beyond
one permitted alternate fails closed to a human-decision recommendation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from .executor_route import ExecutorRoute

POST_PR_STATE_AUDIT_SCHEMA_NAME = "agent-os-post-pr-state-audit"
POST_PR_STATE_AUDIT_SCHEMA_VERSION = "1.0"
MAX_ITEMS = 32
MAX_TEXT_BYTES = 1024
MAX_REPORT_LINES = 18
MIN_REPORT_LINES = 12

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class TerminalPrState(str, Enum):
    MERGED = "merged"
    REVIEW_COMPLETE = "review-complete"
    BLOCKED = "blocked"
    CLOSED_UNMERGED = "closed-unmerged"


class RepositoryHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class SubsystemMaturity(str, Enum):
    EARLY = "early"
    PROGRESSING = "progressing"
    NEAR_COMPLETE = "near-complete"
    COMPLETE = "complete"


class CandidateRankTier(int, Enum):
    DEPENDENCY_UNBLOCKED = 1
    QUEUE_SELECTION = 2
    SAME_SUBSYSTEM_SEQUENCE = 3
    VALIDATION_PREREQUISITE = 4


class RecommendationOutcome(str, Enum):
    NEXT_ISSUE = "next-issue"
    HUMAN_DECISION = "human-decision"


REASON_CODES = frozenset(
    {
        "state.merged",
        "state.review-complete",
        "state.blocked",
        "state.closed-unmerged",
        "health.healthy",
        "health.degraded",
        "health.unknown",
        "blocker.present",
        "blocker.none",
        "blocker.not-actionable",
        "replacement.verified",
        "replacement.missing",
        "candidate.selected",
        "candidate.alternate",
        "candidate.none-eligible",
        "candidate.tie-exceeds-alternate",
        "evidence.incomplete",
        "evidence.conflicting",
        "outcome.next-issue",
        "outcome.human-decision",
    }
)

_STATE_REASON = {
    TerminalPrState.MERGED: "state.merged",
    TerminalPrState.REVIEW_COMPLETE: "state.review-complete",
    TerminalPrState.BLOCKED: "state.blocked",
    TerminalPrState.CLOSED_UNMERGED: "state.closed-unmerged",
}
_HEALTH_REASON = {
    RepositoryHealth.HEALTHY: "health.healthy",
    RepositoryHealth.DEGRADED: "health.degraded",
    RepositoryHealth.UNKNOWN: "health.unknown",
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


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise TypeError(f"{name} must be a positive built-in integer")
    return value


def _optional_positive_int(value: object, name: str) -> int | None:
    return None if value is None else _positive_int(value, name)


def _repository(value: object) -> str:
    text = _exact_text(value, "repository", 255)
    if not _REPOSITORY_RE.fullmatch(text):
        raise ValueError("repository is malformed")
    return text


def _sha40(value: object, name: str) -> str:
    text = _exact_text(value, name, 40)
    if not _SHA40_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase 40-character SHA")
    return text


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


def _audit_id(payload: object) -> str:
    material = b"agent-os-post-pr-state-audit:v1\0" + _canonical_json(payload).encode(
        "utf-8"
    )
    return f"post-pr-state-audit:{hashlib.sha256(material).hexdigest()}"


def _compact_items(values: tuple[str, ...]) -> str:
    if not values:
        return "none"
    suffix = f"; +{len(values) - 3} more" if len(values) > 3 else ""
    return "; ".join(values[:3]) + suffix


@dataclass(frozen=True, slots=True)
class NextIssueCandidateEvidence:
    """One already-normalized ranking candidate for the next issue to work."""

    issue_number: int
    subsystem: str
    rank_tier: CandidateRankTier
    is_closed: bool = False
    is_blocked: bool = False
    is_stale: bool = False
    is_claimed: bool = False
    is_authorized: bool = True
    is_superseded: bool = False
    has_required_evidence: bool = True
    executor_route: ExecutorRoute | None = None

    def __post_init__(self) -> None:
        _positive_int(self.issue_number, "issue_number")
        _required_text(self.subsystem, "subsystem")
        _enum(self.rank_tier, CandidateRankTier, "rank_tier")
        for name in (
            "is_closed",
            "is_blocked",
            "is_stale",
            "is_claimed",
            "is_authorized",
            "is_superseded",
            "has_required_evidence",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a built-in bool")
        if self.executor_route is not None:
            _enum(self.executor_route, ExecutorRoute, "executor_route")

    def eligible(self) -> bool:
        return (
            not self.is_closed
            and not self.is_blocked
            and not self.is_stale
            and not self.is_claimed
            and self.is_authorized
            and not self.is_superseded
            and self.has_required_evidence
        )

    def _payload(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "subsystem": self.subsystem,
            "rank_tier": int(self.rank_tier.value),
            "is_closed": self.is_closed,
            "is_blocked": self.is_blocked,
            "is_stale": self.is_stale,
            "is_claimed": self.is_claimed,
            "is_authorized": self.is_authorized,
            "is_superseded": self.is_superseded,
            "has_required_evidence": self.has_required_evidence,
            "executor_route": self.executor_route.value if self.executor_route else None,
        }


@dataclass(frozen=True, slots=True)
class PostPrStateAuditEvidence:
    """Normalized evidence used only for post-PR state auditing and ranking."""

    repository: str
    pull_request_number: int
    terminal_state: TerminalPrState
    head_sha: str
    checks_verified: bool
    unresolved_threads: bool
    landed_capability: str
    subsystem: str
    subsystem_maturity: SubsystemMaturity
    controlling_blocker_issue: int | None = None
    controlling_blocker_actionable: bool = False
    replacement_issue: int | None = None
    replacement_verified: bool = False
    candidates: tuple[NextIssueCandidateEvidence, ...] = ()
    files_changed: tuple[str, ...] = ()
    tests_run: tuple[str, ...] = ()
    docs_updated: tuple[str, ...] = ()
    unresolved_blockers: tuple[str, ...] = ()
    handoff_recommendation: str = ""
    remaining_risks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _repository(self.repository)
        _positive_int(self.pull_request_number, "pull_request_number")
        _enum(self.terminal_state, TerminalPrState, "terminal_state")
        _sha40(self.head_sha, "head_sha")
        if type(self.checks_verified) is not bool:
            raise TypeError("checks_verified must be a built-in bool")
        if type(self.unresolved_threads) is not bool:
            raise TypeError("unresolved_threads must be a built-in bool")
        _exact_text(self.landed_capability, "landed_capability")
        _required_text(self.subsystem, "subsystem")
        _enum(self.subsystem_maturity, SubsystemMaturity, "subsystem_maturity")
        object.__setattr__(
            self,
            "controlling_blocker_issue",
            _optional_positive_int(
                self.controlling_blocker_issue, "controlling_blocker_issue"
            ),
        )
        if type(self.controlling_blocker_actionable) is not bool:
            raise TypeError("controlling_blocker_actionable must be a built-in bool")
        object.__setattr__(
            self,
            "replacement_issue",
            _optional_positive_int(self.replacement_issue, "replacement_issue"),
        )
        if type(self.replacement_verified) is not bool:
            raise TypeError("replacement_verified must be a built-in bool")
        if type(self.candidates) is not tuple:
            raise TypeError("candidates must be an exact tuple")
        if len(self.candidates) > MAX_ITEMS:
            raise ValueError("candidates exceeds its bound")
        if any(type(item) is not NextIssueCandidateEvidence for item in self.candidates):
            raise TypeError("candidates must contain exact NextIssueCandidateEvidence values")
        candidates = tuple(sorted(self.candidates, key=lambda item: item.issue_number))
        if len({item.issue_number for item in candidates}) != len(candidates):
            raise ValueError("candidates contains duplicate issue numbers")
        object.__setattr__(self, "candidates", candidates)
        for name in ("files_changed", "tests_run", "docs_updated", "unresolved_blockers", "remaining_risks"):
            object.__setattr__(self, name, _canonical_text_tuple(getattr(self, name), name))
        _exact_text(self.handoff_recommendation, "handoff_recommendation")


@dataclass(frozen=True, slots=True)
class PostPrStateAuditResult:
    schema_name: Literal["agent-os-post-pr-state-audit"]
    schema_version: Literal["1.0"]
    repository: str
    pull_request_number: int
    terminal_state: TerminalPrState
    repository_health: RepositoryHealth
    subsystem: str
    subsystem_maturity: SubsystemMaturity
    landed_capability: str
    outcome: RecommendationOutcome
    recommended_issue: int | None
    alternate_issue: int | None
    recommended_executor_route: ExecutorRoute | None
    rationale: str
    next_action: str
    files_changed: tuple[str, ...]
    tests_run: tuple[str, ...]
    docs_updated: tuple[str, ...]
    unresolved_blockers: tuple[str, ...]
    handoff_recommendation: str
    remaining_risks: tuple[str, ...]
    reason_codes: tuple[str, ...]
    audit_id: str = ""
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_name != POST_PR_STATE_AUDIT_SCHEMA_NAME
            or self.schema_version != POST_PR_STATE_AUDIT_SCHEMA_VERSION
        ):
            raise ValueError("unsupported post-PR state audit schema")
        _repository(self.repository)
        _positive_int(self.pull_request_number, "pull_request_number")
        _enum(self.terminal_state, TerminalPrState, "terminal_state")
        _enum(self.repository_health, RepositoryHealth, "repository_health")
        _required_text(self.subsystem, "subsystem")
        _enum(self.subsystem_maturity, SubsystemMaturity, "subsystem_maturity")
        _exact_text(self.landed_capability, "landed_capability")
        _enum(self.outcome, RecommendationOutcome, "outcome")
        object.__setattr__(
            self,
            "recommended_issue",
            _optional_positive_int(self.recommended_issue, "recommended_issue"),
        )
        object.__setattr__(
            self,
            "alternate_issue",
            _optional_positive_int(self.alternate_issue, "alternate_issue"),
        )
        if self.alternate_issue is not None and self.recommended_issue is None:
            raise ValueError("alternate_issue requires recommended_issue")
        if self.alternate_issue is not None and self.alternate_issue == self.recommended_issue:
            raise ValueError("alternate_issue must differ from recommended_issue")
        if self.outcome is RecommendationOutcome.HUMAN_DECISION and self.recommended_issue is not None:
            raise ValueError("human_decision outcome must not carry a recommended_issue")
        if self.outcome is RecommendationOutcome.NEXT_ISSUE and self.recommended_issue is None:
            raise ValueError("next_issue outcome requires a recommended_issue")
        if (
            self.terminal_state is TerminalPrState.REVIEW_COMPLETE
            and self.outcome is not RecommendationOutcome.HUMAN_DECISION
        ):
            raise ValueError("review-complete requires a human_decision outcome")
        if (
            self.terminal_state in (TerminalPrState.BLOCKED, TerminalPrState.CLOSED_UNMERGED)
            and self.alternate_issue is not None
        ):
            raise ValueError("only merged results can carry an alternate_issue")
        if self.recommended_executor_route is not None:
            _enum(self.recommended_executor_route, ExecutorRoute, "recommended_executor_route")
        _required_text(self.rationale, "rationale")
        _required_text(self.next_action, "next_action")
        for name in ("files_changed", "tests_run", "docs_updated", "unresolved_blockers", "remaining_risks"):
            object.__setattr__(self, name, _canonical_text_tuple(getattr(self, name), name))
        _exact_text(self.handoff_recommendation, "handoff_recommendation")
        reasons = _canonical_text_tuple(self.reason_codes, "reason_codes")
        if any(reason not in REASON_CODES for reason in reasons):
            raise ValueError("reason_codes contains an unsupported value")
        if _STATE_REASON[self.terminal_state] not in reasons:
            raise ValueError("reason_codes must include the terminal state")
        object.__setattr__(self, "reason_codes", reasons)
        if self.side_effects_performed is not False:
            raise ValueError("post-PR state audit cannot record side effects")
        expected_id = _audit_id(self._payload())
        if self.audit_id and self.audit_id != expected_id:
            raise ValueError("audit_id does not match canonical audit payload")
        if not self.audit_id:
            object.__setattr__(self, "audit_id", expected_id)

    def _payload(self) -> dict[str, object]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "repository": self.repository,
            "pull_request_number": self.pull_request_number,
            "terminal_state": self.terminal_state.value,
            "repository_health": self.repository_health.value,
            "subsystem": self.subsystem,
            "subsystem_maturity": self.subsystem_maturity.value,
            "landed_capability": self.landed_capability,
            "outcome": self.outcome.value,
            "recommended_issue": self.recommended_issue,
            "alternate_issue": self.alternate_issue,
            "recommended_executor_route": (
                self.recommended_executor_route.value
                if self.recommended_executor_route
                else None
            ),
            "rationale": self.rationale,
            "next_action": self.next_action,
            "files_changed": list(self.files_changed),
            "tests_run": list(self.tests_run),
            "docs_updated": list(self.docs_updated),
            "unresolved_blockers": list(self.unresolved_blockers),
            "handoff_recommendation": self.handoff_recommendation,
            "remaining_risks": list(self.remaining_risks),
            "reason_codes": list(self.reason_codes),
            "side_effects_performed": False,
        }


def _evidence_integrity_issue(evidence: PostPrStateAuditEvidence) -> str | None:
    if evidence.terminal_state is TerminalPrState.MERGED and not evidence.landed_capability.strip():
        return "evidence.incomplete"
    if (
        evidence.terminal_state is TerminalPrState.CLOSED_UNMERGED
        and evidence.landed_capability.strip()
    ):
        return "evidence.conflicting"
    if evidence.controlling_blocker_actionable and evidence.controlling_blocker_issue is None:
        return "evidence.conflicting"
    if evidence.replacement_verified and evidence.replacement_issue is None:
        return "evidence.conflicting"
    return None


def _repository_health(evidence: PostPrStateAuditEvidence) -> RepositoryHealth:
    if evidence.terminal_state is TerminalPrState.MERGED:
        if evidence.checks_verified and not evidence.unresolved_threads:
            return RepositoryHealth.HEALTHY
        return RepositoryHealth.DEGRADED
    if evidence.terminal_state is TerminalPrState.REVIEW_COMPLETE:
        return RepositoryHealth.HEALTHY if evidence.checks_verified else RepositoryHealth.DEGRADED
    if evidence.terminal_state is TerminalPrState.BLOCKED:
        return RepositoryHealth.DEGRADED
    return RepositoryHealth.UNKNOWN


def _rationale(
    evidence: PostPrStateAuditEvidence,
    outcome: RecommendationOutcome,
    recommended_issue: int | None,
    alternate_issue: int | None,
    health: RepositoryHealth,
) -> str:
    pr = evidence.pull_request_number
    if evidence.terminal_state is TerminalPrState.MERGED:
        if outcome is RecommendationOutcome.NEXT_ISSUE:
            suffix = f" and #{alternate_issue} as a tied alternate" if alternate_issue else ""
            return (
                f"PR #{pr} merged '{evidence.landed_capability}' with {health.value} "
                f"repository health, unblocking #{recommended_issue}{suffix}."
            )
        return (
            f"PR #{pr} merged '{evidence.landed_capability}' but no eligible next issue "
            "was found with sufficient confidence, so human review is required."
        )
    if evidence.terminal_state is TerminalPrState.REVIEW_COMPLETE:
        return (
            f"PR #{pr} reached review-complete at head {evidence.head_sha[:12]}; "
            "a human lifecycle decision is required next."
        )
    if evidence.terminal_state is TerminalPrState.BLOCKED:
        if outcome is RecommendationOutcome.NEXT_ISSUE:
            return (
                f"PR #{pr} stopped blocked; the controlling blocker #{recommended_issue} "
                "is itself actionable."
            )
        return (
            f"PR #{pr} stopped blocked with no actionable blocker issue, so human review "
            "is required."
        )
    if outcome is RecommendationOutcome.NEXT_ISSUE:
        return (
            f"PR #{pr} closed without merging; verified replacement #{recommended_issue} "
            "supersedes it."
        )
    return (
        f"PR #{pr} closed without merging and no capability landed; no supported "
        "replacement was supplied, so human review is required."
    )


def _next_action(outcome: RecommendationOutcome, recommended_issue: int | None) -> str:
    if outcome is RecommendationOutcome.NEXT_ISSUE and recommended_issue is not None:
        return f"Open #{recommended_issue}."
    return "Escalate to human_decision."


def _build_result(
    evidence: PostPrStateAuditEvidence,
    outcome: RecommendationOutcome,
    recommended_issue: int | None,
    alternate_issue: int | None,
    reasons: set[str],
    health: RepositoryHealth,
) -> PostPrStateAuditResult:
    executor_route = None
    if outcome is RecommendationOutcome.NEXT_ISSUE and recommended_issue is not None:
        match = next(
            (item for item in evidence.candidates if item.issue_number == recommended_issue),
            None,
        )
        if match is not None:
            executor_route = match.executor_route
    reasons.add(_STATE_REASON[evidence.terminal_state])
    reasons.add(_HEALTH_REASON[health])
    reasons.add(
        "outcome.next-issue" if outcome is RecommendationOutcome.NEXT_ISSUE else "outcome.human-decision"
    )
    return PostPrStateAuditResult(
        schema_name=POST_PR_STATE_AUDIT_SCHEMA_NAME,
        schema_version=POST_PR_STATE_AUDIT_SCHEMA_VERSION,
        repository=evidence.repository,
        pull_request_number=evidence.pull_request_number,
        terminal_state=evidence.terminal_state,
        repository_health=health,
        subsystem=evidence.subsystem,
        subsystem_maturity=evidence.subsystem_maturity,
        landed_capability=evidence.landed_capability,
        outcome=outcome,
        recommended_issue=recommended_issue,
        alternate_issue=alternate_issue,
        recommended_executor_route=executor_route,
        rationale=_rationale(evidence, outcome, recommended_issue, alternate_issue, health),
        next_action=_next_action(outcome, recommended_issue),
        files_changed=evidence.files_changed,
        tests_run=evidence.tests_run,
        docs_updated=evidence.docs_updated,
        unresolved_blockers=evidence.unresolved_blockers,
        handoff_recommendation=evidence.handoff_recommendation,
        remaining_risks=evidence.remaining_risks,
        reason_codes=tuple(sorted(reasons)),
    )


def evaluate_post_pr_state_audit(
    evidence: PostPrStateAuditEvidence,
) -> PostPrStateAuditResult:
    """Audit one terminal PR state and rank the best next issue, or fail closed."""

    if type(evidence) is not PostPrStateAuditEvidence:
        raise TypeError("evidence must be an exact PostPrStateAuditEvidence")

    integrity_issue = _evidence_integrity_issue(evidence)
    health = _repository_health(evidence)
    if integrity_issue:
        reasons = {integrity_issue}
        return _build_result(evidence, RecommendationOutcome.HUMAN_DECISION, None, None, reasons, health)

    if evidence.terminal_state is TerminalPrState.REVIEW_COMPLETE:
        return _build_result(evidence, RecommendationOutcome.HUMAN_DECISION, None, None, set(), health)

    if evidence.terminal_state is TerminalPrState.BLOCKED:
        if evidence.controlling_blocker_issue is not None and evidence.controlling_blocker_actionable:
            return _build_result(
                evidence,
                RecommendationOutcome.NEXT_ISSUE,
                evidence.controlling_blocker_issue,
                None,
                {"blocker.present"},
                health,
            )
        reason = "blocker.not-actionable" if evidence.controlling_blocker_issue else "blocker.none"
        return _build_result(evidence, RecommendationOutcome.HUMAN_DECISION, None, None, {reason}, health)

    if evidence.terminal_state is TerminalPrState.CLOSED_UNMERGED:
        if evidence.replacement_issue is not None and evidence.replacement_verified:
            return _build_result(
                evidence,
                RecommendationOutcome.NEXT_ISSUE,
                evidence.replacement_issue,
                None,
                {"replacement.verified"},
                health,
            )
        return _build_result(
            evidence, RecommendationOutcome.HUMAN_DECISION, None, None, {"replacement.missing"}, health
        )

    eligible = [item for item in evidence.candidates if item.eligible()]
    if not eligible:
        return _build_result(
            evidence, RecommendationOutcome.HUMAN_DECISION, None, None, {"candidate.none-eligible"}, health
        )
    best_tier = min(item.rank_tier for item in eligible)
    tied = sorted(
        (item for item in eligible if item.rank_tier == best_tier),
        key=lambda item: item.issue_number,
    )
    if len(tied) == 1:
        return _build_result(
            evidence,
            RecommendationOutcome.NEXT_ISSUE,
            tied[0].issue_number,
            None,
            {"candidate.selected"},
            health,
        )
    if len(tied) == 2:
        return _build_result(
            evidence,
            RecommendationOutcome.NEXT_ISSUE,
            tied[0].issue_number,
            tied[1].issue_number,
            {"candidate.selected", "candidate.alternate"},
            health,
        )
    return _build_result(
        evidence,
        RecommendationOutcome.HUMAN_DECISION,
        None,
        None,
        {"candidate.tie-exceeds-alternate"},
        health,
    )


def format_post_pr_state_audit(result: PostPrStateAuditResult) -> str:
    """Render one compact 12-18 line terminal-handoff report."""

    if type(result) is not PostPrStateAuditResult:
        raise TypeError("result must be an exact PostPrStateAuditResult")
    lines = (
        f"PR #{result.pull_request_number}: {result.terminal_state.value}",
        f"Landed: {result.landed_capability or 'none'}",
        f"Health: {result.repository_health.value}",
        f"Subsystem: {result.subsystem} ({result.subsystem_maturity.value})",
        f"Blocker: {'#' + str(result.recommended_issue) if result.outcome is RecommendationOutcome.NEXT_ISSUE and result.terminal_state is TerminalPrState.BLOCKED else 'none'}",
        f"Next: {'#' + str(result.recommended_issue) if result.recommended_issue else 'human_decision'}",
        f"Alternate: {'#' + str(result.alternate_issue) if result.alternate_issue else 'none'}",
        f"Route: {result.recommended_executor_route.value if result.recommended_executor_route else 'none'}",
        f"Action: {result.next_action}",
        f"Rationale: {result.rationale}",
        f"Files: {_compact_items(result.files_changed)}",
        f"Tests: {_compact_items(result.tests_run)}",
        f"Docs: {_compact_items(result.docs_updated)}",
        f"Unresolved: {_compact_items(result.unresolved_blockers)}",
        f"Handoff: {result.handoff_recommendation or 'none'}",
        f"Risks: {_compact_items(result.remaining_risks)}",
    )
    assert MIN_REPORT_LINES <= len(lines) <= MAX_REPORT_LINES
    return "\n".join(lines)
