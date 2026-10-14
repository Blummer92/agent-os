"""Pure pre-create reconciliation classifier for proposed Agent OS work (#3308).

Answers one question for a proposed work item: given evidence that callers
already acquired, is there an existing owner, active work, capability, or
history to reuse, or may the item proceed toward issue-creation admission?

It is a deterministic function over injected evidence. It performs no I/O,
searches nothing, and imports no reader:

- Navigation Index evidence is the ``outcome`` of the existing
  ``notion_navigation_client.precreate.precreate_preflight`` (#3307), whose
  currentness already consumes the Refresh Log reader (#3306). It is
  conditional: callers mark it not applicable for work that does not touch
  Notion-facing structures.
- GitHub lineage is the caller's bounded, complete issue search, with each
  open issue's lifecycle stage taken from the #3441 PR-lineage acquisition
  when one exists.
- Capability evidence is matching rows of ``04_Registry/reusable-capabilities.yml``.

Exactly one disposition from #3308's vocabulary is returned, with reason
codes in a fixed order. GitHub lineage is authoritative and decides first;
navigation evidence is advisory and only gates ``candidate-new-work``.
Missing, stale, ambiguous or incomplete evidence never becomes a no-match:
it becomes ``manual-review``. No result authorizes issue creation, workflow
execution, or any repository or external mutation; ``candidate-new-work``
still requires the existing issue-creation admission (bugs: #2660).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Literal

RECONCILIATION_CONTRACT_VERSION = "1.0"

REUSE_CURRENT_OWNER = "reuse-current-owner"
CONTINUE_CURRENT_WORK = "continue-current-work"
EXTEND_EXISTING_CAPABILITY = "extend-existing-capability"
HISTORICAL_REGRESSION_EVIDENCE = "historical-regression-evidence"
SUPERSEDED_OR_RETIRED = "superseded-or-retired"
CANDIDATE_NEW_WORK = "candidate-new-work"
MANUAL_REVIEW = "manual-review"
DISPOSITIONS = (
    REUSE_CURRENT_OWNER,
    CONTINUE_CURRENT_WORK,
    EXTEND_EXISTING_CAPABILITY,
    HISTORICAL_REGRESSION_EVIDENCE,
    SUPERSEDED_OR_RETIRED,
    CANDIDATE_NEW_WORK,
    MANUAL_REVIEW,
)

MATCH_EXACT = "exact"
MATCH_RELATED = "related"
_MATCHES = frozenset({MATCH_EXACT, MATCH_RELATED})
_STATES = frozenset({"open", "closed"})
_CLOSED_REASONS = frozenset({"completed", "not_planned", "duplicate"})
# #3441 lifecycle stages an open issue may carry; None means not acquired.
_ACTIVE_STAGES = frozenset({"draft-pr", "review"})
_STAGES = frozenset({"planning", "implementation", "draft-pr", "review", "merged", "closed"})
# reusable-capability-registry statuses (reader._ALLOWED_STATUSES).
_LIVE_CAPABILITY = frozenset({"active", "experimental", "internal-only"})
_RETIRED_CAPABILITY = frozenset({"deprecated", "replaced"})
# notion_navigation_client.precreate outcomes (#3307).
_NAVIGATION_OUTCOMES = frozenset(
    {"existing-match", "duplicate-risk-review", "no-cached-match", "stale-or-unverified", "manual-review"}
)


@dataclass(frozen=True, slots=True)
class LineageCandidate:
    """One GitHub issue the caller's search matched to the proposed work."""

    issue_number: int
    state: str  # "open" | "closed"
    match: str  # "exact": same objective; "related": same area, causal match unproven
    state_reason: str | None = None  # closed only: completed | not_planned | duplicate
    lifecycle_stage: str | None = None  # open only: #3441 acquired stage, if any
    successor_issue_number: int | None = None  # closed only: current successor/root-cause owner
    successor_state: str | None = None
    successor_lifecycle_stage: str | None = None

    def __post_init__(self) -> None:
        _positive(self.issue_number, "issue_number")
        _member(self.state, _STATES, "state")
        _member(self.match, _MATCHES, "match")
        if self.state == "open":
            if self.state_reason is not None or self.successor_issue_number is not None:
                raise ValueError("an open issue carries no closed reason or successor")
            _optional_member(self.lifecycle_stage, _STAGES - {"closed"}, "lifecycle_stage")
        else:
            _member(self.state_reason, _CLOSED_REASONS, "state_reason")
            if self.lifecycle_stage is not None:
                raise ValueError("a closed issue's lineage is not consulted for a stage")
        if self.successor_issue_number is None:
            if self.successor_state is not None or self.successor_lifecycle_stage is not None:
                raise ValueError("successor facts require a successor_issue_number")
        else:
            _positive(self.successor_issue_number, "successor_issue_number")
            if self.successor_issue_number == self.issue_number:
                raise ValueError("an issue cannot succeed itself")
            _member(self.successor_state, _STATES, "successor_state")
            if self.successor_state == "closed" and self.successor_lifecycle_stage is not None:
                raise ValueError("a closed successor carries no lifecycle stage")
            _optional_member(
                self.successor_lifecycle_stage, _STAGES - {"closed"}, "successor_lifecycle_stage"
            )


@dataclass(frozen=True, slots=True)
class CapabilityMatch:
    """One reusable-capability registry row the caller matched to the work."""

    capability_id: str
    status: str

    def __post_init__(self) -> None:
        if type(self.capability_id) is not str or not self.capability_id.strip():
            raise ValueError("capability_id must be a non-empty string")
        _member(self.status, _LIVE_CAPABILITY | _RETIRED_CAPABILITY, "status")


@dataclass(frozen=True, slots=True)
class ReconciliationInput:
    """All evidence for one proposed work item, already acquired by the caller."""

    subject: str
    github_search_complete: bool
    lineage: tuple[LineageCandidate, ...] = ()
    capabilities: tuple[CapabilityMatch, ...] = ()
    navigation_applicable: bool = False
    navigation_outcome: str | None = None

    def __post_init__(self) -> None:
        if type(self.subject) is not str or not self.subject.strip():
            raise ValueError("subject must be a non-empty string")
        for name in ("github_search_complete", "navigation_applicable"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a built-in bool")
        if type(self.lineage) is not tuple or any(type(c) is not LineageCandidate for c in self.lineage):
            raise TypeError("lineage must be a tuple of LineageCandidate")
        if len({c.issue_number for c in self.lineage}) != len(self.lineage):
            raise ValueError("lineage lists an issue more than once")
        if type(self.capabilities) is not tuple or any(
            type(c) is not CapabilityMatch for c in self.capabilities
        ):
            raise TypeError("capabilities must be a tuple of CapabilityMatch")
        if self.navigation_applicable:
            _optional_member(self.navigation_outcome, _NAVIGATION_OUTCOMES, "navigation_outcome")
        elif self.navigation_outcome is not None:
            raise ValueError("navigation_outcome requires navigation_applicable")


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    disposition: str
    reason_codes: tuple[str, ...]
    owner_issue_number: int | None
    capability_id: str | None
    evidence_issue_numbers: tuple[int, ...]
    input_digest: str
    contract_version: str = RECONCILIATION_CONTRACT_VERSION
    live_verification_required: Literal[True] = field(default=True, init=False)
    authorizes_issue_creation: Literal[False] = field(default=False, init=False)
    authorizes_mutation: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        payload["evidence_issue_numbers"] = list(self.evidence_issue_numbers)
        return payload


def classify_proposed_work(evidence: ReconciliationInput) -> ReconciliationResult:
    """Return the single reconciliation disposition for one proposed work item."""
    if type(evidence) is not ReconciliationInput:
        raise TypeError("evidence must be an exact ReconciliationInput")
    evidence.__post_init__()
    digest = _digest(evidence)
    reasons: list[str] = []
    evidence_issues = tuple(sorted(c.issue_number for c in evidence.lineage))

    def result(disposition, *, owner=None, capability=None):
        return ReconciliationResult(
            disposition=disposition,
            reason_codes=tuple(reasons),
            owner_issue_number=owner,
            capability_id=capability,
            evidence_issue_numbers=evidence_issues,
            input_digest=digest,
        )

    if evidence.navigation_applicable:
        reasons.append(f"navigation.{evidence.navigation_outcome or 'evidence-missing'}")
    if not evidence.github_search_complete:
        # An incomplete search cannot prove the absence of an owner.
        reasons.append("github.lineage-incomplete")
        return result(MANUAL_REVIEW)

    # Contradictory successor facts are never resolved by guessing: the same
    # successor must be described identically everywhere, and a successor that
    # is itself in the lineage must match that lineage entry.
    by_number = {c.issue_number: c for c in evidence.lineage}
    closed_exact = [c for c in evidence.lineage if c.match == MATCH_EXACT and c.state == "closed"]
    successor_facts: dict[int, set[tuple[str | None, str | None]]] = {}
    for c in evidence.lineage:
        if c.successor_issue_number is not None:
            successor_facts.setdefault(c.successor_issue_number, set()).add(
                (c.successor_state, c.successor_lifecycle_stage)
            )
    for number, facts in successor_facts.items():
        listed = by_number.get(number)
        if len(facts) > 1 or (
            listed is not None and facts != {(listed.state, listed.lifecycle_stage)}
        ):
            reasons.append("github.successor-facts-conflict")
            return result(MANUAL_REVIEW)

    # 1. GitHub is authoritative: a current open owner of the same objective
    #    wins, then the current successor of closed same-objective history.
    open_owners = {c.issue_number: c.lifecycle_stage for c in evidence.lineage
                   if c.match == MATCH_EXACT and c.state == "open"}
    exact_successors = {c.successor_issue_number for c in closed_exact if c.successor_issue_number is not None}
    # Each successor has exactly one fact set here (conflicts returned above).
    if any(next(iter(successor_facts[n]))[0] == "closed" for n in exact_successors):
        # A closed successor chain must be followed by the caller, not guessed.
        reasons.append("github.successor-closed")
        return result(MANUAL_REVIEW)
    open_successors = {n: next(iter(successor_facts[n]))[1] for n in exact_successors}
    candidates = {**open_successors, **open_owners}
    if len(candidates) > 1:
        reasons.append("github.multiple-open-owners")
        return result(MANUAL_REVIEW)
    if candidates:
        (number, stage), = candidates.items()
        reason = "github.current-open-owner" if number in open_owners else "github.current-successor-owner"
        return _owner(number, stage, reasons, result, reason)

    # 2. Related work (causal match unproven) is ambiguous while it, or a
    #    successor of related history, is open.
    related_successor = any(
        c.match == MATCH_RELATED and c.successor_issue_number is not None for c in evidence.lineage
    )
    if related_successor or any(
        c.match == MATCH_RELATED and c.state == "open" for c in evidence.lineage
    ):
        reasons.append("github.related-open-work")
        return result(MANUAL_REVIEW)

    # 3. A registered capability is extended, never re-implemented; this
    #    outranks closed history of the same objective.
    live = sorted(c.capability_id for c in evidence.capabilities if c.status in _LIVE_CAPABILITY)
    retired = sorted(c.capability_id for c in evidence.capabilities if c.status in _RETIRED_CAPABILITY)
    if len(live) > 1:
        reasons.append("capability.multiple-live-matches")
        return result(MANUAL_REVIEW)
    if live:
        if closed_exact:
            reasons.append("github.completed-history")
        reasons.append("capability.registered")
        return result(EXTEND_EXISTING_CAPABILITY, capability=live[0])

    # 4. Closed same-objective history is evidence only, never actionable.
    if closed_exact:
        if all(c.state_reason in {"not_planned", "duplicate"} for c in closed_exact):
            reasons.append("github.closed-not-planned-or-duplicate")
            return result(SUPERSEDED_OR_RETIRED)
        reasons.append("github.completed-history")
        return result(HISTORICAL_REGRESSION_EVIDENCE)
    if retired:
        reasons.append("capability.retired-or-replaced")
        return result(SUPERSEDED_OR_RETIRED, capability=retired[0])
    if any(c.match == MATCH_RELATED for c in evidence.lineage):
        # Related closed history does not block a candidate, but is named.
        reasons.append("github.related-history")

    # 5. Only now may advisory navigation evidence gate new work.
    if evidence.navigation_applicable and evidence.navigation_outcome != "no-cached-match":
        # Missing, stale, matched, or duplicate-risk navigation evidence is
        # never a no-match (#3307: no-cached-match is not "safe to create").
        return result(MANUAL_REVIEW)
    reasons.append("new-work.requires-creation-admission")
    return result(CANDIDATE_NEW_WORK)


def _owner(number, stage, reasons, result, reason):
    reasons.append(reason)
    if stage in _ACTIVE_STAGES:
        reasons.append(f"lifecycle.{stage}")
        return result(CONTINUE_CURRENT_WORK, owner=number)
    if stage is not None:
        reasons.append(f"lifecycle.{stage}")
    return result(REUSE_CURRENT_OWNER, owner=number)


def _digest(evidence: ReconciliationInput) -> str:
    material = json.dumps(asdict(evidence), sort_keys=True, separators=(",", ":"))
    return "reconciliation-input:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _positive(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive built-in integer")


def _member(value, allowed, name):
    if type(value) is not str or value not in allowed:
        raise ValueError(f"{name} must be one of {sorted(allowed)}")


def _optional_member(value, allowed, name):
    if value is not None:
        _member(value, allowed, name)
