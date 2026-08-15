"""Deterministic coding-knowledge selection and sufficiency projection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import Any

MAX_CANDIDATES = 5
MAX_SELECTED = 3
MAX_SIGNAL_ITEMS = 20
MAX_TEXT_CHARS = 512


class KnowledgeCurrentness(str, Enum):
    """Currentness state supplied by the caller."""

    CURRENT = "current"
    STALE = "stale"
    UNVERIFIABLE = "unverifiable"


class SufficiencyStatus(str, Enum):
    """Finite coding-knowledge sufficiency disposition."""

    NOT_NEEDED = "not-needed"
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    MANUAL_REVIEW = "manual-review"


class RetrievalEscalation(str, Enum):
    """Finite caller-owned next retrieval step."""

    NONE = "none"
    KNOWN_REFERENCE = "known-reference"
    FILTERED_DATA_SOURCE_QUERY = "filtered-data-source-query"
    EXACT_NARROW_LOOKUP = "exact-narrow-lookup"
    WORKSPACE_SEARCH = "workspace-search"
    MANUAL_REVIEW = "manual-review"


@dataclass(frozen=True, slots=True)
class CodingKnowledgeRequest:
    """Bounded explicit task signals supplied by the caller."""

    task_reference: str
    ecosystem_hints: tuple[str, ...] = ()
    language_hints: tuple[str, ...] = ()
    library_hints: tuple[str, ...] = ()
    capability_keywords: tuple[str, ...] = ()
    target_path_hints: tuple[str, ...] = ()
    canonical_rule_refs: tuple[str, ...] = ()
    known_knowledge_refs: tuple[str, ...] = ()
    attempted_retrieval: tuple[RetrievalEscalation, ...] = ()
    specialized_knowledge_required: bool | None = None

    def __post_init__(self) -> None:
        _validate_text(self.task_reference, "task_reference")
        for name in (
            "ecosystem_hints",
            "language_hints",
            "library_hints",
            "capability_keywords",
            "target_path_hints",
            "canonical_rule_refs",
            "known_knowledge_refs",
        ):
            _validate_text_tuple(getattr(self, name), name)
        if type(self.attempted_retrieval) is not tuple:
            raise TypeError("attempted_retrieval must be a tuple")
        if len(self.attempted_retrieval) > len(RetrievalEscalation):
            raise ValueError("attempted_retrieval is oversized")
        if any(type(item) is not RetrievalEscalation for item in self.attempted_retrieval):
            raise TypeError("attempted_retrieval must contain RetrievalEscalation values")
        if self.specialized_knowledge_required is not None and type(
            self.specialized_knowledge_required
        ) is not bool:
            raise TypeError("specialized_knowledge_required must be bool or None")


@dataclass(frozen=True, slots=True)
class CodingKnowledgeCandidate:
    """Bounded normalized non-authoritative coding working knowledge."""

    knowledge_id: str
    source_system: str
    source_revision: str
    currentness: KnowledgeCurrentness
    name: str
    ecosystem: str
    library_name: str | None
    capability_kind: str
    keywords: tuple[str, ...] = ()
    use_when: tuple[str, ...] = ()
    avoid_when: tuple[str, ...] = ()
    version_scope: str | None = None
    qualification_ref: str | None = None
    canonical_github_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    authority_conflict: bool = False

    def __post_init__(self) -> None:
        for name in (
            "knowledge_id",
            "source_system",
            "source_revision",
            "name",
            "ecosystem",
            "capability_kind",
        ):
            _validate_text(getattr(self, name), name)
        for name in ("library_name", "version_scope", "qualification_ref"):
            value = getattr(self, name)
            if value is not None:
                _validate_text(value, name)
        for name in (
            "keywords",
            "use_when",
            "avoid_when",
            "canonical_github_refs",
            "evidence_refs",
        ):
            _validate_text_tuple(getattr(self, name), name)
        if type(self.currentness) is not KnowledgeCurrentness:
            raise TypeError("currentness must be a KnowledgeCurrentness value")
        if type(self.authority_conflict) is not bool:
            raise TypeError("authority_conflict must be a bool")


@dataclass(frozen=True, slots=True)
class SelectedKnowledge:
    """A retained candidate plus deterministic selection reasons."""

    candidate: CodingKnowledgeCandidate
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        candidate = self.candidate
        return {
            "knowledge_id": candidate.knowledge_id,
            "source_system": candidate.source_system,
            "source_revision": candidate.source_revision,
            "currentness": candidate.currentness.value,
            "name": candidate.name,
            "ecosystem": candidate.ecosystem,
            "library_name": candidate.library_name,
            "capability_kind": candidate.capability_kind,
            "keywords": list(candidate.keywords),
            "use_when": list(candidate.use_when),
            "avoid_when": list(candidate.avoid_when),
            "version_scope": candidate.version_scope,
            "qualification_ref": candidate.qualification_ref,
            "canonical_github_refs": list(candidate.canonical_github_refs),
            "evidence_refs": list(candidate.evidence_refs),
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class CodingKnowledgeSelectionResult:
    """Deterministic non-authorizing CKR2 result."""

    sufficiency_status: SufficiencyStatus
    recommended_escalation: RetrievalEscalation
    selected: tuple[SelectedKnowledge, ...]
    canonical_github_refs: tuple[str, ...]
    knowledge_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]
    candidate_count: int
    selected_count: int
    authority_created: bool = False
    side_effects_performed: bool = False
    notion_write_performed: bool = False
    github_write_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "sufficiency_status": self.sufficiency_status.value,
            "recommended_escalation": self.recommended_escalation.value,
            "selected": [item.to_dict() for item in self.selected],
            "canonical_github_refs": list(self.canonical_github_refs),
            "knowledge_refs": list(self.knowledge_refs),
            "reason_codes": list(self.reason_codes),
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "authority_created": self.authority_created,
            "side_effects_performed": self.side_effects_performed,
            "notion_write_performed": self.notion_write_performed,
            "github_write_performed": self.github_write_performed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def to_handoff_projection(self) -> dict[str, list[str]]:
        known_facts = [f"coding-knowledge-sufficiency:{self.sufficiency_status.value}"]
        known_facts.extend(f"coding-knowledge:{ref}" for ref in self.knowledge_refs)
        prior_decisions = sorted(
            {
                item.candidate.qualification_ref
                for item in self.selected
                if item.candidate.qualification_ref is not None
            }
        )
        stop_conditions: list[str] = []
        if self.sufficiency_status in (
            SufficiencyStatus.INSUFFICIENT,
            SufficiencyStatus.MANUAL_REVIEW,
        ):
            stop_conditions = [f"coding-knowledge:{code}" for code in self.reason_codes]
        return {
            "known_facts": known_facts,
            "prior_decisions": prior_decisions,
            "allowed_inspect_first": list(self.canonical_github_refs),
            "stop_conditions": stop_conditions,
        }


def select_coding_knowledge(
    request: CodingKnowledgeRequest,
    candidates: tuple[CodingKnowledgeCandidate, ...],
) -> CodingKnowledgeSelectionResult:
    """Select the smallest current relevant knowledge set from supplied evidence."""
    if type(request) is not CodingKnowledgeRequest:
        raise TypeError("request must be a CodingKnowledgeRequest")
    if type(candidates) is not tuple:
        raise TypeError("candidates must be a tuple")
    if any(type(candidate) is not CodingKnowledgeCandidate for candidate in candidates):
        raise TypeError("candidates must contain CodingKnowledgeCandidate values")

    candidate_count = len(candidates)
    if candidate_count > MAX_CANDIDATES:
        return _result(
            SufficiencyStatus.MANUAL_REVIEW,
            RetrievalEscalation.MANUAL_REVIEW,
            (),
            request.canonical_rule_refs,
            ("candidate-budget-exceeded",),
            candidate_count,
        )

    deduped, duplicate_conflict = _deduplicate(candidates)
    if duplicate_conflict:
        return _result(
            SufficiencyStatus.MANUAL_REVIEW,
            RetrievalEscalation.MANUAL_REVIEW,
            (),
            request.canonical_rule_refs,
            ("duplicate-identity-conflict",),
            candidate_count,
        )

    if _knowledge_not_needed(request):
        return _result(
            SufficiencyStatus.NOT_NEEDED,
            RetrievalEscalation.NONE,
            (),
            request.canonical_rule_refs,
            ("knowledge-not-needed",),
            candidate_count,
        )

    ranked = []
    for candidate in deduped:
        bucket, reasons = _match_candidate(request, candidate)
        if bucket:
            ranked.append((bucket, candidate.knowledge_id.casefold(), candidate, reasons))

    if not ranked:
        return _result(
            SufficiencyStatus.INSUFFICIENT,
            _next_escalation(request),
            (),
            request.canonical_rule_refs,
            ("no-relevant-candidate",),
            candidate_count,
        )

    best_bucket = max(item[0] for item in ranked)
    best = [item for item in ranked if item[0] == best_bucket]
    best.sort(key=lambda item: item[1])

    if any(item[2].authority_conflict for item in best):
        return _result(
            SufficiencyStatus.MANUAL_REVIEW,
            RetrievalEscalation.MANUAL_REVIEW,
            (),
            request.canonical_rule_refs,
            ("canonical-authority-conflict",),
            candidate_count,
        )
    if any(item[2].currentness is KnowledgeCurrentness.STALE for item in best):
        return _result(
            SufficiencyStatus.MANUAL_REVIEW,
            RetrievalEscalation.MANUAL_REVIEW,
            (),
            request.canonical_rule_refs,
            ("stale-relevant-candidate",),
            candidate_count,
        )
    if any(item[2].currentness is KnowledgeCurrentness.UNVERIFIABLE for item in best):
        return _result(
            SufficiencyStatus.MANUAL_REVIEW,
            RetrievalEscalation.MANUAL_REVIEW,
            (),
            request.canonical_rule_refs,
            ("unverifiable-relevant-candidate",),
            candidate_count,
        )

    selected = tuple(
        SelectedKnowledge(candidate=item[2], reason_codes=item[3])
        for item in best[:MAX_SELECTED]
    )

    uncovered = _uncovered_library_hints(request, selected)
    if uncovered:
        refs = _canonical_refs(request, selected)
        return _result(
            SufficiencyStatus.INSUFFICIENT,
            _next_escalation(request),
            selected,
            refs,
            ("required-library-uncovered",),
            candidate_count,
        )

    refs = _canonical_refs(request, selected)
    if not refs:
        return _result(
            SufficiencyStatus.INSUFFICIENT,
            _next_escalation(request),
            selected,
            (),
            ("canonical-reference-missing",),
            candidate_count,
        )

    return _result(
        SufficiencyStatus.SUFFICIENT,
        RetrievalEscalation.NONE,
        selected,
        refs,
        ("knowledge-sufficient",),
        candidate_count,
    )


def _knowledge_not_needed(request: CodingKnowledgeRequest) -> bool:
    if request.specialized_knowledge_required is False:
        return True
    if request.specialized_knowledge_required is True:
        return False
    return not (
        request.library_hints
        or request.capability_keywords
        or request.target_path_hints
        or request.known_knowledge_refs
    )


def _deduplicate(
    candidates: tuple[CodingKnowledgeCandidate, ...],
) -> tuple[tuple[CodingKnowledgeCandidate, ...], bool]:
    by_id: dict[str, CodingKnowledgeCandidate] = {}
    for candidate in candidates:
        existing = by_id.get(candidate.knowledge_id)
        if existing is not None and existing != candidate:
            return (), True
        by_id[candidate.knowledge_id] = candidate
    return tuple(by_id[key] for key in sorted(by_id, key=str.casefold)), False


def _match_candidate(
    request: CodingKnowledgeRequest,
    candidate: CodingKnowledgeCandidate,
) -> tuple[int, tuple[str, ...]]:
    library_hints = {_norm(value) for value in request.library_hints}
    candidate_library = _norm(candidate.library_name) if candidate.library_name else ""
    candidate_name = _norm(candidate.name)
    exact_library = bool(
        library_hints and (candidate_library in library_hints or candidate_name in library_hints)
    )

    ecosystems = {_norm(value) for value in request.ecosystem_hints + request.language_hints}
    ecosystem_match = _norm(candidate.ecosystem) in ecosystems if ecosystems else False

    capability_hints = {_norm(value) for value in request.capability_keywords}
    capability_terms = {_norm(candidate.capability_kind)} | {
        _norm(value) for value in candidate.keywords
    }
    capability_overlap = capability_hints & capability_terms

    path_match = False
    if candidate_library:
        path_match = any(candidate_library in _norm(path) for path in request.target_path_hints)

    if exact_library:
        reasons = ["exact-library-match"]
        if path_match:
            reasons.append("target-path-match")
        return 3, tuple(reasons)
    if ecosystem_match and capability_overlap:
        return 2, ("ecosystem-capability-match",)
    if path_match:
        return 1, ("target-path-match",)
    if capability_overlap:
        return 1, ("keyword-overlap",)
    return 0, ()


def _uncovered_library_hints(
    request: CodingKnowledgeRequest,
    selected: tuple[SelectedKnowledge, ...],
) -> tuple[str, ...]:
    required = {_norm(value) for value in request.library_hints}
    if not required:
        return ()
    covered = set()
    for item in selected:
        candidate = item.candidate
        if candidate.library_name:
            covered.add(_norm(candidate.library_name))
        covered.add(_norm(candidate.name))
    return tuple(sorted(required - covered))


def _canonical_refs(
    request: CodingKnowledgeRequest,
    selected: tuple[SelectedKnowledge, ...],
) -> tuple[str, ...]:
    refs = set(request.canonical_rule_refs)
    for item in selected:
        refs.update(item.candidate.canonical_github_refs)
    return tuple(sorted(refs))


def _next_escalation(request: CodingKnowledgeRequest) -> RetrievalEscalation:
    attempted = set(request.attempted_retrieval)
    if request.known_knowledge_refs and RetrievalEscalation.KNOWN_REFERENCE not in attempted:
        return RetrievalEscalation.KNOWN_REFERENCE
    for step in (
        RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY,
        RetrievalEscalation.EXACT_NARROW_LOOKUP,
        RetrievalEscalation.WORKSPACE_SEARCH,
    ):
        if step not in attempted:
            return step
    return RetrievalEscalation.MANUAL_REVIEW


def _result(
    status: SufficiencyStatus,
    escalation: RetrievalEscalation,
    selected: tuple[SelectedKnowledge, ...],
    canonical_refs: tuple[str, ...],
    reason_codes: tuple[str, ...],
    candidate_count: int,
) -> CodingKnowledgeSelectionResult:
    canonical_refs = tuple(sorted(set(canonical_refs)))
    knowledge_refs = tuple(item.candidate.knowledge_id for item in selected)
    return CodingKnowledgeSelectionResult(
        sufficiency_status=status,
        recommended_escalation=escalation,
        selected=selected,
        canonical_github_refs=canonical_refs,
        knowledge_refs=knowledge_refs,
        reason_codes=reason_codes,
        candidate_count=candidate_count,
        selected_count=len(selected),
    )


def _validate_text(value: object, field: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} must be non-empty")
    if len(value) > MAX_TEXT_CHARS:
        raise ValueError(f"{field} is oversized")
    if any(ord(char) < 32 and char not in "\t" for char in value):
        raise ValueError(f"{field} contains control characters")


def _validate_text_tuple(values: object, field: str) -> None:
    if type(values) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    if len(values) > MAX_SIGNAL_ITEMS:
        raise ValueError(f"{field} is oversized")
    for value in values:
        _validate_text(value, field)


def _norm(value: str) -> str:
    return value.strip().casefold()
