"""Bounded Decision/ADR consumption for coding preflight.

This module consumes already-read normalized Decision evidence. It performs no
Notion reads or writes and delegates relevance/sufficiency to CKR2's canonical
``select_coding_knowledge`` contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .coding_knowledge_selection import (
    CodingKnowledgeCandidate,
    CodingKnowledgeRequest,
    CodingKnowledgeSelectionResult,
    KnowledgeCurrentness,
    RetrievalEscalation,
    SufficiencyStatus,
    select_coding_knowledge,
)

MAX_DECISION_RECORDS = 5
_ACTIVE_STATUSES = frozenset({"Accepted", "Active"})
_WORKING_STATUSES = frozenset({"Proposed", "Exploratory", "Working"})
_SUPERSEDED_STATUSES = frozenset({"Superseded", "Deprecated"})
_DECISION_SENSITIVE_TERMS = frozenset(
    {
        "architecture",
        "authorization",
        "canonical",
        "contract",
        "decision",
        "governance",
        "ownership",
        "parser",
        "permission",
        "routing",
        "source-of-truth",
        "supersession",
        "validation",
        "workflow",
    }
)


class DecisionRetrievalStatus(str, Enum):
    NOT_NEEDED = "not-needed"
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    MANUAL_REVIEW = "manual-review"
    UNAVAILABLE_SAFE_FALLBACK = "unavailable-safe-fallback"


@dataclass(frozen=True, slots=True)
class DecisionRecordEvidence:
    """Provider-neutral bounded evidence for one Decision Log / ADR row."""

    decision_id: str
    source_revision: str
    title: str
    domain: str
    status: str
    currentness: KnowledgeCurrentness
    summary: str
    canonical_github_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    keywords: tuple[str, ...] = ()
    applies_to: tuple[str, ...] = ()
    superseded_by: tuple[str, ...] = ()
    authority_conflict: bool = False

    def __post_init__(self) -> None:
        for name in ("decision_id", "source_revision", "title", "domain", "status", "summary"):
            _text(getattr(self, name), name)
        for name in (
            "canonical_github_refs",
            "evidence_refs",
            "keywords",
            "applies_to",
            "superseded_by",
        ):
            _items(getattr(self, name), name)
        if type(self.currentness) is not KnowledgeCurrentness:
            raise TypeError("currentness must be a KnowledgeCurrentness value")
        if type(self.authority_conflict) is not bool:
            raise TypeError("authority_conflict must be bool")


@dataclass(frozen=True, slots=True)
class DecisionPreflightPlan:
    retrieval_required: bool
    reason_codes: tuple[str, ...]
    recommended_escalation: RetrievalEscalation
    notion_read_performed: bool = field(default=False, init=False)
    authority_created: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class DecisionPreflightResult:
    decision_retrieval_status: DecisionRetrievalStatus
    candidate_count: int
    selected_count: int
    selected_decision_ids: tuple[str, ...]
    selection_reason_codes: tuple[str, ...]
    canonical_github_refs: tuple[str, ...]
    knowledge_refs: tuple[str, ...]
    superseded_or_stale_count: int
    retrieval_escalation: RetrievalEscalation
    verification_required: bool
    source_authority: str
    handoff_projection: dict[str, list[str]]
    selection: CodingKnowledgeSelectionResult | None = None
    notion_write_performed: bool = field(default=False, init=False)
    github_write_performed: bool = field(default=False, init=False)
    authority_created: bool = field(default=False, init=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_retrieval_status": self.decision_retrieval_status.value,
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "selected_decision_ids": list(self.selected_decision_ids),
            "selection_reason_codes": list(self.selection_reason_codes),
            "canonical_github_refs": list(self.canonical_github_refs),
            "knowledge_refs": list(self.knowledge_refs),
            "superseded_or_stale_count": self.superseded_or_stale_count,
            "retrieval_escalation": self.retrieval_escalation.value,
            "verification_required": self.verification_required,
            "source_authority": self.source_authority,
            "handoff_projection": self.handoff_projection,
            "notion_write_performed": self.notion_write_performed,
            "github_write_performed": self.github_write_performed,
            "authority_created": self.authority_created,
        }


def plan_decision_preflight(request: CodingKnowledgeRequest) -> DecisionPreflightPlan:
    """Decide whether bounded Decision retrieval could materially help."""
    if type(request) is not CodingKnowledgeRequest:
        raise TypeError("request must be a CodingKnowledgeRequest")
    if request.specialized_knowledge_required is False:
        return DecisionPreflightPlan(False, ("decision-retrieval-not-needed",), RetrievalEscalation.NONE)

    signals = {
        _norm(value)
        for value in (
            request.capability_keywords
            + request.target_path_hints
            + request.canonical_rule_refs
            + request.known_knowledge_refs
        )
    }
    if request.specialized_knowledge_required is True or _decision_sensitive(signals):
        return DecisionPreflightPlan(
            True,
            ("decision-retrieval-required",),
            RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY,
        )
    return DecisionPreflightPlan(False, ("decision-retrieval-not-needed",), RetrievalEscalation.NONE)


def consume_decision_preflight(
    request: CodingKnowledgeRequest,
    decisions: tuple[DecisionRecordEvidence, ...] = (),
    *,
    retrieval_available: bool = True,
) -> DecisionPreflightResult:
    """Normalize bounded Decision evidence and delegate selection to CKR2."""
    if type(request) is not CodingKnowledgeRequest:
        raise TypeError("request must be a CodingKnowledgeRequest")
    if type(decisions) is not tuple or any(type(item) is not DecisionRecordEvidence for item in decisions):
        raise TypeError("decisions must be a tuple of DecisionRecordEvidence values")
    if type(retrieval_available) is not bool:
        raise TypeError("retrieval_available must be bool")

    plan = plan_decision_preflight(request)
    if not plan.retrieval_required:
        return _fallback(
            DecisionRetrievalStatus.NOT_NEEDED,
            "decision-retrieval-not-needed",
            RetrievalEscalation.NONE,
        )

    if not retrieval_available:
        if request.specialized_knowledge_required is True:
            return _fallback(
                DecisionRetrievalStatus.INSUFFICIENT,
                "decision-retrieval-unavailable-specialized-knowledge-required",
                RetrievalEscalation.MANUAL_REVIEW,
            )
        return _fallback(
            DecisionRetrievalStatus.UNAVAILABLE_SAFE_FALLBACK,
            "decision-retrieval-unavailable-github-only-fallback",
            RetrievalEscalation.NONE,
        )

    if len(decisions) > MAX_DECISION_RECORDS:
        return _fallback(
            DecisionRetrievalStatus.MANUAL_REVIEW,
            "decision-candidate-budget-exceeded",
            RetrievalEscalation.MANUAL_REVIEW,
            candidate_count=len(decisions),
        )

    active: list[DecisionRecordEvidence] = []
    stale_or_superseded = 0
    unresolved = False
    for decision in decisions:
        if decision.status in _SUPERSEDED_STATUSES:
            stale_or_superseded += 1
            continue
        if decision.status in _WORKING_STATUSES:
            unresolved = True
            continue
        if decision.status not in _ACTIVE_STATUSES:
            unresolved = True
            continue
        if decision.currentness is not KnowledgeCurrentness.CURRENT or decision.authority_conflict:
            stale_or_superseded += 1
        active.append(decision)

    if unresolved and not active:
        return _fallback(
            DecisionRetrievalStatus.MANUAL_REVIEW,
            "decision-status-not-authoritative",
            RetrievalEscalation.MANUAL_REVIEW,
            candidate_count=len(decisions),
            superseded_or_stale_count=stale_or_superseded,
        )

    if not active and stale_or_superseded:
        successors = sorted({ref for item in decisions for ref in item.superseded_by})
        return _fallback(
            DecisionRetrievalStatus.INSUFFICIENT,
            "no-current-active-decision",
            RetrievalEscalation.KNOWN_REFERENCE if successors else RetrievalEscalation.EXACT_NARROW_LOOKUP,
            candidate_count=len(decisions),
            canonical_github_refs=tuple(successors),
            superseded_or_stale_count=stale_or_superseded,
        )

    active_for_selection = _apply_explicit_precedence(request, tuple(active))
    selection = select_coding_knowledge(
        request,
        tuple(_candidate(item) for item in active_for_selection),
    )
    return _from_selection(selection, active_for_selection, stale_or_superseded)


def _apply_explicit_precedence(
    request: CodingKnowledgeRequest,
    active: tuple[DecisionRecordEvidence, ...],
) -> tuple[DecisionRecordEvidence, ...]:
    """Narrow candidates only for exact caller-supplied Decision/GitHub references.

    This is an adapter-specific evidence-precedence seam, not a second relevance
    selector. Once exact references are applied, CKR2 remains the sole selector
    for relevance, currentness, deduplication, sufficiency, and max-3 retention.
    """
    known_ids = {_norm(value) for value in request.known_knowledge_refs}
    if known_ids:
        matches = tuple(item for item in active if _norm(item.decision_id) in known_ids)
        if matches:
            return matches

    canonical_refs = {_norm(value) for value in request.canonical_rule_refs}
    if canonical_refs:
        matches = tuple(
            item
            for item in active
            if canonical_refs
            & {_norm(reference) for reference in item.canonical_github_refs}
        )
        if matches:
            return matches

    return active


def _candidate(decision: DecisionRecordEvidence) -> CodingKnowledgeCandidate:
    return CodingKnowledgeCandidate(
        knowledge_id=decision.decision_id,
        source_system="notion-decision-log",
        source_revision=decision.source_revision,
        currentness=decision.currentness,
        name=decision.title,
        ecosystem="agent-os",
        library_name=None,
        capability_kind=decision.domain,
        keywords=decision.keywords,
        use_when=decision.applies_to + (decision.summary,),
        avoid_when=(),
        qualification_ref=decision.decision_id,
        canonical_github_refs=decision.canonical_github_refs,
        evidence_refs=decision.evidence_refs,
        authority_conflict=decision.authority_conflict,
    )


def _from_selection(
    selection: CodingKnowledgeSelectionResult,
    active: tuple[DecisionRecordEvidence, ...],
    superseded_or_stale_count: int,
) -> DecisionPreflightResult:
    status = {
        SufficiencyStatus.NOT_NEEDED: DecisionRetrievalStatus.NOT_NEEDED,
        SufficiencyStatus.SUFFICIENT: DecisionRetrievalStatus.SUFFICIENT,
        SufficiencyStatus.INSUFFICIENT: DecisionRetrievalStatus.INSUFFICIENT,
        SufficiencyStatus.MANUAL_REVIEW: DecisionRetrievalStatus.MANUAL_REVIEW,
    }[selection.sufficiency_status]
    selected_ids = tuple(item.candidate.knowledge_id for item in selection.selected)
    projection = selection.to_handoff_projection()
    projection["prior_decisions"] = list(selected_ids)
    projection["known_facts"].append("decision-source-authority:secondary-index")
    return DecisionPreflightResult(
        decision_retrieval_status=status,
        candidate_count=selection.candidate_count,
        selected_count=selection.selected_count,
        selected_decision_ids=selected_ids,
        selection_reason_codes=selection.reason_codes,
        canonical_github_refs=selection.canonical_github_refs,
        knowledge_refs=selection.knowledge_refs,
        superseded_or_stale_count=superseded_or_stale_count,
        retrieval_escalation=selection.recommended_escalation,
        verification_required=bool(selection.canonical_github_refs),
        source_authority="secondary-index",
        handoff_projection=projection,
        selection=selection,
    )


def _fallback(
    status: DecisionRetrievalStatus,
    reason: str,
    escalation: RetrievalEscalation,
    *,
    candidate_count: int = 0,
    canonical_github_refs: tuple[str, ...] = (),
    superseded_or_stale_count: int = 0,
) -> DecisionPreflightResult:
    stop_conditions = []
    if status in {DecisionRetrievalStatus.INSUFFICIENT, DecisionRetrievalStatus.MANUAL_REVIEW}:
        stop_conditions = [f"coding-knowledge:{reason}"]
    return DecisionPreflightResult(
        decision_retrieval_status=status,
        candidate_count=candidate_count,
        selected_count=0,
        selected_decision_ids=(),
        selection_reason_codes=(reason,),
        canonical_github_refs=canonical_github_refs,
        knowledge_refs=(),
        superseded_or_stale_count=superseded_or_stale_count,
        retrieval_escalation=escalation,
        verification_required=bool(canonical_github_refs),
        source_authority="secondary-index",
        handoff_projection={
            "known_facts": [
                f"coding-knowledge-sufficiency:{status.value}",
                "decision-source-authority:secondary-index",
            ],
            "prior_decisions": [],
            "allowed_inspect_first": list(canonical_github_refs),
            "stop_conditions": stop_conditions,
        },
    )


def _decision_sensitive(signals: set[str]) -> bool:
    for signal in signals:
        if any(term in signal for term in _DECISION_SENSITIVE_TERMS):
            return True
    return False


def _norm(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", "-").split())


def _text(value: object, name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must be non-empty")
    if len(value) > 512:
        raise ValueError(f"{name} is oversized")


def _items(value: object, name: str) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be a tuple")
    if len(value) > 20:
        raise ValueError(f"{name} is oversized")
    for item in value:
        _text(item, name)
