"""Deterministic coding-knowledge selection and sufficiency projection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import combinations
import json
import re
from typing import Any

MAX_CANDIDATES = 5
MAX_SELECTED = 3
MAX_SIGNAL_ITEMS = 20
MAX_TEXT_CHARS = 512
# Advisory narrative text (candidate use_when / avoid_when guidance) is bounded
# separately from structured identity text. This approved 2048-character limit
# applies to EACH logical guidance field after Notion rich_text segments are
# joined and stripped by the Notion adapter. CKR2 bounds the text it receives.
# Notion's 2000-character per-segment limit is a distinct transport constraint.
# The same logical-field policy is shared across CKR11 -> CKR6 -> CKR2.
# Guidance over this bound still fails closed; nothing is truncated.
MAX_GUIDANCE_TEXT_CHARS = 2048


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
    # Source-owned, reviewed applicability cases parsed from the lesson's
    # "Supporting Cases" record (see lesson_activation_bridge). Empty for
    # older lessons without structured applicability: the evaluator abstains
    # and the existing matcher decides exactly as before. Cases are
    # lesson-owned text, never matcher configuration keyed to an ID.
    applicability_cases: tuple[str, ...] = ()

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
        for name in ("keywords", "canonical_github_refs", "evidence_refs"):
            _validate_text_tuple(getattr(self, name), name)
        for name in ("use_when", "avoid_when"):
            _validate_text_tuple(
                getattr(self, name), name, max_chars=MAX_GUIDANCE_TEXT_CHARS
            )
        _validate_text_tuple(self.applicability_cases, "applicability_cases")
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
            "applicability_cases": list(candidate.applicability_cases),
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


# #4026: contextual tie-break INSIDE one relevance bucket only. It never creates
# relevance (bucket 0 stays excluded), never moves a candidate across buckets,
# never changes budgets, provenance or currentness checks, and adds no reason
# code. With no overlap every score is 0 and the legacy id order is unchanged.
_CONTEXT_TOKEN = re.compile(r"[a-z0-9]+")
_MIN_CONTEXT_TOKEN_CHARS = 4


def _context_tokens(texts: Any) -> frozenset[str]:
    return frozenset(
        token
        for text in texts
        for token in _CONTEXT_TOKEN.findall(text.casefold())
        if len(token) >= _MIN_CONTEXT_TOKEN_CHARS
    )


def contextual_tie_scores(
    request: CodingKnowledgeRequest,
    tied: Any,
) -> list[int]:
    """Exact whole-word overlap between request context and tied candidates.

    Request context is task_reference plus capability_keywords;
    candidate text is its name and use_when. A shared token is weighted by
    how many tied candidates do NOT contain it (n - df), so words common
    to the whole tie group carry no weight. No stemming, synonyms or fuzzy
    matching. Deterministic, integer-valued, aligned with tied by position.
    """
    candidates = list(tied)
    if len(candidates) < 2:
        return [0] * len(candidates)
    # A capability keyword that already matched candidate vocabulary formed the
    # relevance bucket; counting it again as context would reward any lesson
    # that merely mentions the bucket's own term. Free-text phrases still count.
    consumed = {_norm(candidate.capability_kind) for candidate in candidates} | {
        _norm(keyword) for candidate in candidates for keyword in candidate.keywords
    }
    wanted = _context_tokens(
        (
            request.task_reference,
            *(kw for kw in request.capability_keywords if _norm(kw) not in consumed),
        )
    )
    shared = [
        _context_tokens((candidate.name, *candidate.use_when)) & wanted
        for candidate in candidates
    ]
    document_frequency: dict[str, int] = {}
    for tokens in shared:
        for token in tokens:
            document_frequency[token] = document_frequency.get(token, 0) + 1
    total = len(candidates)
    return [sum(total - document_frequency[token] for token in tokens) for tokens in shared]


def required_library_coverage_order(
    request: CodingKnowledgeRequest,
    ordered: Any,
) -> list[int]:
    """Maximize tied-bucket coverage; keep original order on equal coverage."""
    candidates = tuple(ordered)
    indices = range(len(candidates))
    required = frozenset(map(_norm, request.library_hints))
    if len(required) < 2 or len(indices) <= MAX_SELECTED:
        return list(indices)

    coverage = [
        required.intersection((_norm(item.name), _norm(item.library_name or "")))
        for item in candidates
    ]

    def score(subset):
        return len(set().union(*(coverage[i] for i in subset)))

    best = tuple(indices[:MAX_SELECTED])
    best_count = score(best)
    # The row union and the largest per-row contributions both upper-bound
    # coverage. Only an actual subset reaching that bound can stop the search.
    upper = min(score(indices), sum(sorted(map(len, coverage), reverse=True)[:MAX_SELECTED]))
    if upper < 2 or best_count == upper:
        return list(indices)

    # At most MAX_SELECTED equivalent rows can contribute. Retain their
    # earliest positions in the search, but keep the entire output tail.
    counts: dict[frozenset[str], int] = {}
    search = []
    for i, signature in enumerate(coverage):
        if (count := counts.get(signature, 0)) < MAX_SELECTED:
            counts[signature] = count + 1
            search.append(i)
    for subset in combinations(search, MAX_SELECTED):
        if (count := score(subset)) > best_count:
            best, best_count = subset, count
            if count == upper:
                break
    return [*best, *(i for i in indices if i not in best)]


def _rank_tied_candidates(
    request: CodingKnowledgeRequest, candidates: tuple[CodingKnowledgeCandidate, ...],
) -> tuple[list[int], list[int]]:
    """Rank one ID-ordered bucket; retain the pre-coverage order for replay."""
    scores = contextual_tie_scores(request, candidates)
    contextual = sorted(range(len(candidates)), key=lambda i: -scores[i])
    coverage = required_library_coverage_order(request, (candidates[i] for i in contextual))
    return contextual, [contextual[i] for i in coverage]


def select_coding_knowledge(
    request: CodingKnowledgeRequest,
    candidates: tuple[CodingKnowledgeCandidate, ...],
) -> CodingKnowledgeSelectionResult:
    """Standalone CKR2: rank once within the caller's bounded candidate pool."""
    return _select_coding_knowledge(request, candidates, _ranked_order=None)


def _select_coding_knowledge(
    request: CodingKnowledgeRequest,
    candidates: tuple[CodingKnowledgeCandidate, ...],
    *,
    _ranked_order: tuple[str, ...] | None,
) -> CodingKnowledgeSelectionResult:
    """Run CKR2 safeguards; trusted retrieval may supply a frozen rank order."""
    if type(request) is not CodingKnowledgeRequest:
        raise TypeError("request must be a CodingKnowledgeRequest")
    if type(candidates) is not tuple:
        raise TypeError("candidates must be a tuple")
    if any(type(candidate) is not CodingKnowledgeCandidate for candidate in candidates):
        raise TypeError("candidates must contain CodingKnowledgeCandidate values")

    # R1 (#2425): deduplicate BEFORE the budget check. The budget counts
    # DISTINCT candidate identities; identical duplicates must not consume
    # it. candidate_count keeps its raw contract (len of supplied candidates).
    candidate_count = len(candidates)
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
    if len(deduped) > MAX_CANDIDATES:
        return _result(
            SufficiencyStatus.MANUAL_REVIEW,
            RetrievalEscalation.MANUAL_REVIEW,
            (),
            request.canonical_rule_refs,
            ("candidate-budget-exceeded",),
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
            ranked.append((bucket, candidate, reasons))

    if not ranked:
        return _result(
            SufficiencyStatus.INSUFFICIENT,
            _next_escalation(request),
            (),
            request.canonical_rule_refs,
            ("no-relevant-candidate",),
            candidate_count,
        )

    # The pre-cut ranking is internal to the CKR11/CKR6 path. Reject
    # stale or forged identity priorities and cross-bucket inversions.
    if _ranked_order is not None:
        ranked_buckets = {item.knowledge_id: 0 for item in deduped}
        ranked_buckets.update((item[1].knowledge_id, item[0]) for item in ranked)
        invalid_order = (
            type(_ranked_order) is not tuple
            or any(type(identity) is not str for identity in _ranked_order)
            or len(_ranked_order) != len(set(_ranked_order))
            or set(_ranked_order) != {item.knowledge_id for item in deduped}
            or 0 in ranked_buckets.values()
        )
        if not invalid_order:
            invalid_order = any(
                ranked_buckets[earlier] < ranked_buckets[later]
                for earlier, later in zip(_ranked_order, _ranked_order[1:])
            )
        if invalid_order:
            return _result(
                SufficiencyStatus.MANUAL_REVIEW,
                RetrievalEscalation.MANUAL_REVIEW,
                (),
                request.canonical_rule_refs,
                ("upstream-ranking-order-mismatch",),
                candidate_count,
            )

    best_bucket = max(item[0] for item in ranked)
    best = [item for item in ranked if item[0] == best_bucket]
    if _ranked_order is None:
        # Filtering retains the total ID order established by _deduplicate.
        _, order = _rank_tied_candidates(request, tuple(item[1] for item in best))
        best = [best[i] for i in order]
    else:
        # Never recompute document frequency on the five finalists.
        priority = {identity: index for index, identity in enumerate(_ranked_order)}
        best.sort(key=lambda item: priority[item[1].knowledge_id])

    # Check the entire winning bucket before the final cut, in hold priority order.
    hold = None
    if any(item[1].authority_conflict for item in best):
        hold = "canonical-authority-conflict"
    elif any(item[1].currentness is KnowledgeCurrentness.STALE for item in best):
        hold = "stale-relevant-candidate"
    elif any(item[1].currentness is KnowledgeCurrentness.UNVERIFIABLE for item in best):
        hold = "unverifiable-relevant-candidate"
    if hold is not None:
        return _result(
            SufficiencyStatus.MANUAL_REVIEW,
            RetrievalEscalation.MANUAL_REVIEW,
            (),
            request.canonical_rule_refs,
            (hold,),
            candidate_count,
        )

    selected = tuple(
        SelectedKnowledge(candidate=item[1], reason_codes=item[2])
        for item in best[:MAX_SELECTED]
    )

    refs = request.canonical_rule_refs + tuple(
        ref for item in selected for ref in item.candidate.canonical_github_refs
    )
    if _uncovered_library_hints(request, selected):
        return _result(
            SufficiencyStatus.INSUFFICIENT,
            _next_escalation(request),
            selected,
            refs,
            ("required-library-uncovered",),
            candidate_count,
        )

    if _missing_candidate_provenance(selected):
        return _result(
            SufficiencyStatus.INSUFFICIENT,
            _next_escalation(request),
            selected,
            refs,
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
    if request.specialized_knowledge_required is not None:
        return not request.specialized_knowledge_required
    return not (
        request.library_hints
        or request.capability_keywords
        or request.target_path_hints
        or request.known_knowledge_refs
    )


# A finite, affirmative mechanism signature. Neither caller prose nor a
# lesson ID establishes relevance. In particular, do not search the Guardrail
# (the second Notion use_when entry) for positive evidence.
_LIBRARY_TIE_HINT_SETS = (
    frozenset({"lesson-selection", "library coverage"}),
    # Literal production #4097 request before the lesson was registered.
    frozenset({"deterministic lesson ranking", "explicit multi-library coverage",
               "bounded candidate selection"}),
)
_LIBRARY_TIE_REASON = "library-tie-coverage-text-match"
_LIBRARY_TIE_TITLE = re.compile(
    r"(?:preserve|maintain) (?:explicitly )?requested library coverage "
    r"within lesson[- ]ranking ties"
    r"|(?:preserve|maintain) coverage (?:of|for|across) (?:explicitly )?requested libraries "
    r"within lesson[- ]ranking ties"
)
_LIBRARY_TIE_GUIDANCE = re.compile(
    r"within (?:a|the same) relevance bucket, (?:preserve|maintain) "
    r"(?:the widest )?coverage (?:of|across) (?:explicitly )?requested libraries "
    r"before (?:truncating|cutting the shortlist)\.?"
    r"(?: keep the existing deterministic order when coverage is equal\.)?"
)

# A separate guardrail can explicitly contradict the affirmative instruction.
# Limit this veto to the same action/object, not unrelated prohibitions (e.g.
# "never bypass provenance" or "never promote a lower relevance bucket").
_REVIEWED_NEGATION = r"(?:never|do not|must not|should not|don['’ʼ]t)"
_LIBRARY_TIE_CONTRADICTION = re.compile(
    rf"\b(?:{_REVIEWED_NEGATION} (?:preserve|maintain)"
    r"|avoid (?:preserving|maintaining)) "
    r"(?:(?:explicitly )?requested library coverage|(?:the widest )?coverage "
    r"(?:of|for|across) (?:explicitly )?requested libraries)\b"
)


def _reviewed_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _contradicts_primary(
    candidate: CodingKnowledgeCandidate, contradiction: re.Pattern[str],
) -> bool:
    return any(
        contradiction.search(_reviewed_text(text))
        for text in (*candidate.use_when[1:], *candidate.avoid_when)
    )


def _library_tie_guidance(candidate: CodingKnowledgeCandidate) -> bool:
    return (
        candidate.source_system == "notion-lessons-learned"
        and _norm(candidate.ecosystem) == "agent-os"
        and bool(candidate.use_when)
        and _LIBRARY_TIE_TITLE.fullmatch(_reviewed_text(candidate.name)) is not None
        and _LIBRARY_TIE_GUIDANCE.fullmatch(_reviewed_text(candidate.use_when[0])) is not None
    )


_PR_REFRESH_HINTS = frozenset({"branch refresh", "merge-tree fallback"})
# The owner used this complete mechanism description on #3991 before #4091.
# It must not reduce to generic Git, merge-tree, or conflict-detection hints.
_PR_REFRESH_HISTORICAL_HINTS = frozenset({
    "git branch refresh", "rebase rejection", "merge-tree conflict detection", "bounded recovery",
})
_PR_REFRESH_REASON = "pr-refresh-reconciliation-text-match"
_PR_REFRESH_CONTRADICTION = re.compile(
    rf"\b(?:{_REVIEWED_NEGATION} (?:use|run|refresh|reconcile)"
    r"|(?:skip|avoid) (?:using|running|refreshing|reconciling))"
    r"\b[^.!?;]{0,160}\b(?:git|merge-tree)\b[^.!?;]{0,80}"
    r"\b(?:refresh|reconcil(?:e|ing|iation))\b"
)

# #4090: a specifically requested Notion-read executor-outcome guard can match
# source-owned lesson text even when Notion's generic Learning Type/Applies To
# fields carry no such controlled label.
_NOTION_EXECUTOR_HINTS = frozenset({"notion read", "executor outcome"})
_NOTION_EXECUTOR_REASON = "verified-notion-executor-outcome-match"
# Match complete reviewed wording, not a collection of words that also appears
# in reversed or retracted instructions. Case and whitespace are immaterial;
# other paraphrases abstain until separately reviewed.
_NOTION_EXECUTOR_TITLE = "reject failed executor outcomes before completing a notion read"
_NOTION_EXECUTOR_GUIDANCE = frozenset({
    "before marking governed read dispatch completed, validate executor output "
    "is a mapping and reject an explicit non-success status or non-null error. "
    "test failed-status, error-despite-success, wrong-type and success controls "
    "on each route.",
    "reject explicit executor errors before reporting dispatch completion.",
})


# The reviewed instruction stays exact; only a contrary action on the same
# failure or validation step, in the same completion context, vetoes it.
_NOTION_READ_COMPLETION = (
    r"(?:completing (?:a |the )?notion read|reporting dispatch completion"
    r"|marking (?:governed read )?dispatch completed)"
)
_NOTION_EXECUTOR_FAILURE = (
    r"(?:failed executor outcomes?|explicit executor errors?"
    r"|(?:an? )?explicit non-success status|(?:an? )?non-null error)"
)
_NOTION_EXECUTOR_CONTRADICTION = re.compile(
    rf"\b(?:{_REVIEWED_NEGATION} "
    rf"(?:reject {_NOTION_EXECUTOR_FAILURE}|validate executor output)"
    rf"|(?:skip|avoid) (?:rejecting {_NOTION_EXECUTOR_FAILURE}|validating executor output))"
    rf" before {_NOTION_READ_COMPLETION}\b"
    r"|\b(?:do not|never|don['’ʼ]t) complete (?:a |the )?notion read unless "
    rf"{_NOTION_EXECUTOR_FAILURE} (?:was|were|is|are) (?:accepted|ignored)\b"
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
    return tuple(by_id[key] for key in sorted(by_id, key=lambda key: (key.casefold(), key))), False


_REST_COMMENT_IDENTITY = r"github\s+(?:issue[- ]+)?comments?\s+(?:ids?|records?)"
_REST_RESPONSE_BYTES = r"oversized\s+github\s+(?:http|rest)\s+get\s+response\s+bytes"
_REST_TIMESTAMP = r"(?:edited\s+)?timestamp\s+provenance"
_REST_CLAUSE_START = r"(?:^|[.!?;]\s+)(?:[-*+]\s+)?"
_REST_PAGINATION_CONTRADICTION = re.compile(
    rf"{_REST_CLAUSE_START}(?:{_REVIEWED_NEGATION} (?:reject|detect)|keep|retain|accept|allow)"
    rf"\s+duplicate\s+{_REST_COMMENT_IDENTITY}\b"
)
_REST_RECEIPT_CONTRADICTION = re.compile(
    rf"{_REST_CLAUSE_START}(?:(?:{_REVIEWED_NEGATION} reject|accept|allow)\s+{_REST_RESPONSE_BYTES}"
    rf"|(?:{_REVIEWED_NEGATION} (?:verify|validate|check)|ignore|disregard)\s+{_REST_TIMESTAMP})\b"
)


def _github_rest_evidence_match(
    candidate: CodingKnowledgeCandidate,
    capability_hints: set[str],
    ecosystems: set[str],
) -> bool:
    """#4026: bounded source-owned GitHub REST mechanism relevance.

    This is a relevance hypothesis, not a live lesson qualification or
    authorization. Unlike broad Python/Testing tags, two independent explicit
    capability hints and affirmative lesson-owned text are both required.
    """
    pagination = {
        "github issue comment pagination", "duplicate record detection",
    } <= capability_hints
    receipts = {
        "bounded http get response limits", "timestamp provenance",
    } <= capability_hints
    if not (pagination or receipts):
        return False
    if not {"python", "github rest api"} <= ecosystems:
        return False
    if candidate.source_system != "notion-lessons-learned" or candidate.ecosystem != "python":
        return False

    # Only source-owned title and activation guidance are eligible. Neither
    # arbitrary task_reference prose nor known_knowledge_refs are interpreted.
    def has(pattern: str, value: str) -> bool:
        return re.search(r"\b(?:" + pattern + r")\b", value) is not None

    title = candidate.name.casefold()
    if not has(r"github", title) or has(r"not|never|unrelated", title):
        return False

    guidance = tuple(_reviewed_text(text) for text in (*candidate.use_when, *candidate.avoid_when))
    clauses = tuple(
        clause.strip()
        for value in candidate.use_when[:1]
        for line in value.casefold().splitlines()
        # Keep commas and semicolons inside the sentence: a trailing
        # qualification must not become invisible. Strip only a leading bullet.
        for clause in re.split(r"[.!?]+", re.sub(r"^[-*+][ \t]+", "", line.strip()))
    )
    if pagination and has(r"issue[- ]comments?", title) and has(
        r"pag(?:e|es|ed|ing|ination)", title
    ):
        # Bind the validating action to comment identities, not page validity.
        # For example, checking complete pages and keeping duplicates is not
        # evidence of duplicate identity detection.
        action_on_identity = (
            rf"(?:"
            rf"(?:reject|detect)\s+duplicate\s+{_REST_COMMENT_IDENTITY}"
            rf"|(?:verify|validate|check)\s+(?:that\s+)?{_REST_COMMENT_IDENTITY}\s+are\s+unique"
            rf")\s+across\s+(?:(?:all|paginated)\s+)?pages?"
            rf"(?:\s+and\s+verify\s+complete\s+page\s+records)?"
        )
        if (
            any(re.fullmatch(action_on_identity, clause) for clause in clauses)
            and not any(_REST_PAGINATION_CONTRADICTION.search(text) for text in guidance)
        ):
            return True

    if receipts and all(
        has(pattern, title) for pattern in (
            r"get", r"http|rest", r"response|receipt|evidence|reads?",
            r"size|bounded|bound|limit|limits|trust|provenance|cap",
        )
    ):
        # Both actions must apply to the stated REST evidence. A bag of
        # size words and an unrelated timestamp is not a verified mechanism.
        receipt_action = (
            rf"reject\s+{_REST_RESPONSE_BYTES}"
            rf"\s+(?:and|then)\s+(?:verify|validate|check)\s+{_REST_TIMESTAMP}"
        )
        return (
            any(re.fullmatch(receipt_action, clause) for clause in clauses)
            and not any(_REST_RECEIPT_CONTRADICTION.search(text) for text in guidance)
        )
    return False



# A reviewed executed-revision mechanism. Scope this to the existing canary
# signals, never an incident identifier, generic QA tag, or task prose.
_EXECUTED_REVISION_HINTS = frozenset({"exact-head evidence", "lesson preflight"})
_EXECUTED_REVISION_REASON = "executed-revision-evidence-text-match"
_EXECUTED_REVISION_TITLE = re.compile(
    r"verify (?:ckr2 relevance fixes|lesson retrieval evidence) against the exact (?:code )?revision executed"
)
# This narrow rule admits reviewed wording in full, not a prefix plus
# arbitrary prose. Unreviewed guidance abstains even with no negation words.
_EXECUTED_REVISION_GUARD_NOTE = r"(?: (?:skip unrelated checks|unrelated checks are optional)\.)?"
_EXECUTED_REVISION_PRIMARY = re.compile(
    r"(?:when validating an unmerged ckr2 relevance fix, )?record the sha actually executed\. "
    r"compare positive and negative lesson-selection fixtures against both main and the exact pr head\."
    r"(?: independently verify lesson applicability before interpreting a no-match result as a matcher defect\.)?"
)
_EXECUTED_REVISION_GUARD = re.compile(
    r"never treat a main-branch ckr6 result as proof that an unmerged pr's matcher works\. "
    r"preserve fail-closed abstention, provenance checks, retrieval limits, and authorization boundaries\."
    + _EXECUTED_REVISION_GUARD_NOTE
)


def _executed_revision_evidence_match(candidate: CodingKnowledgeCandidate) -> bool:
    return (
        candidate.source_system == "notion-lessons-learned"
        and _norm(candidate.ecosystem) == "agent-os"
        and len(candidate.use_when) == 2
        and not candidate.avoid_when
        and _EXECUTED_REVISION_PRIMARY.fullmatch(_reviewed_text(candidate.use_when[0])) is not None
        and _EXECUTED_REVISION_GUARD.fullmatch(_reviewed_text(candidate.use_when[1])) is not None
    )


# ---------------------------------------------------------------------------
# Generic applicability evidence (CKR2 relevance fix).
#
# One explainable mechanism, no per-lesson configuration: a lesson that
# carries source-owned, reviewed applicability cases (its "Supporting
# Cases" record) matches only when every positive case is evidenced by the
# request's finite signals, no exclusion case is evidenced, and no later
# guidance contradicts a satisfied positive case. Exclusions and
# contradictions win over every positive signal, including the narrow
# reviewed branches below. A lesson without cases abstains here and keeps
# exactly its previous behavior; a lesson with cases whose positives are
# not evidenced also blocks the loose generic fallback, because its own
# applicability record says the task does not exhibit what must be true.
#
# A positive condition needs whole-word overlap within one explicit task
# capability hint; do not assemble a match from unrelated hints, filenames,
# or evidence URLs. Exclusions may still use the broader non-path context.
# Caller prose in task_reference is never read, lesson IDs/titles/URLs
# never prove relevance, and there is no stemming, synonym, or fuzzy
# matching. A target-path case must name the same repository-relative file
# against target_path_hints. A path is a scope constraint, not positive task
# evidence. The file comparison is exact, not substring containment. This is
# a lexical relevance hypothesis, like
# the other text matches in this module: it does not attest to lesson
# applicability in the lesson_applicability.py verified-observation sense,
# currentness, provenance, or write authority, all of which still run
# unchanged in the selector. The lesson_applicability.py contract is
# deliberately NOT activated here: its mechanism vocabulary, registry
# governance, and trusted-observation acquisition remain owner decisions
# pending, and its production registry is empty.
# ---------------------------------------------------------------------------

_APPLICABILITY_REASON = "applicability-evidence-text-match"
_APPLICABILITY_MAX_CASES = 8
_APPLICABILITY_MIN_SHARED_TOKENS = 2
_APPLICABILITY_EXCLUSION = re.compile(
    r"^(?:do not|don't|never apply|not applicable|does not apply|excludes)\b"
)
_APPLICABILITY_APOSTROPHES = str.maketrans({char: "'" for char in "‘’ʼ"})
# Short domain words are useful for a veto but don't expand positive matches.
_APPLICABILITY_SHORT_EXCLUSION_TOKENS = frozenset({"api", "ci", "pdf", "pr", "yml"})
# Structural scaffolding, not topical evidence: negation and application
# verbs that appear in exclusion phrasing and in guidance generally.
_APPLICABILITY_SCAFFOLD = frozenset({
    "do", "does", "not", "never", "apply", "applies", "use", "used", "using",
    "the", "and", "also", "that", "with", "from", "into", "when", "this",
    "for", "are", "its", "per", "via", "upon", "each", "such", "than",
    "then", "after", "before", "should", "must", "will", "would", "can",
})
_APPLICABILITY_NEGATION = re.compile(
    r"\b(?:never|do not|must not|should not|don['\u2019\u02bc]t|avoid|skip|reject|not|no)\b"
)
_APPLICABILITY_PATH = re.compile(
    r"^(?:\./|[a-z0-9_.-]+/)[a-z0-9_./-]+\.(?:yml|yaml|py|md|json|toml|txt|sh|js|ts)$"
)


@dataclass(frozen=True, slots=True)
class ApplicabilityEvaluation:
    """Per-stage trace of one applicability-evidence evaluation.

    ``matched`` is a relevance hypothesis only; it selects nothing and
    grants no authority. Case references are indexes into
    ``candidate.applicability_cases`` so the trace stays bounded without
    truncating lesson text. ``evidence`` maps each satisfied/exclusion
    case index to the shared distinctive tokens that evidenced it.
    """

    matched: bool
    reason_codes: tuple[str, ...]
    satisfied: tuple[int, ...]
    unsatisfied: tuple[int, ...]
    exclusions_fired: tuple[int, ...]
    contradicted: tuple[int, ...]
    evidence: tuple[tuple[int, tuple[str, ...]], ...]
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "reason_codes": list(self.reason_codes),
            "satisfied": list(self.satisfied),
            "unsatisfied": list(self.unsatisfied),
            "exclusions_fired": list(self.exclusions_fired),
            "contradicted": list(self.contradicted),
            "evidence": {str(index): list(tokens) for index, tokens in self.evidence},
            "explanation": self.explanation,
        }


def _applicability_tokens(text: str, *, exclusion: bool = False) -> frozenset[str]:
    return frozenset(
        token
        for token in _CONTEXT_TOKEN.findall(text.casefold())
        if token not in _APPLICABILITY_SCAFFOLD
        and (
            len(token) >= _MIN_CONTEXT_TOKEN_CHARS
            or (exclusion and token in _APPLICABILITY_SHORT_EXCLUSION_TOKENS)
        )
    )


def _strongest_case_evidence(
    case_tokens: frozenset[str], task_signals: tuple[frozenset[str], ...],
) -> tuple[str, ...]:
    # Resolve equally strong signals deterministically without merging them.
    return max(
        (tuple(sorted(case_tokens & signal)) for signal in task_signals),
        key=lambda match: (len(match), match),
        default=(),
    )


def _applicability_case_kind(case: str) -> str:
    reviewed = _reviewed_text(case).translate(_APPLICABILITY_APOSTROPHES)
    if _APPLICABILITY_EXCLUSION.match(reviewed):
        return "exclusion"
    # One terminal prose period is optional; never strip the leading ./.
    if _APPLICABILITY_PATH.fullmatch(case.strip().removesuffix(".").casefold()) is not None:
        return "path"
    return "positive"


def _path_case_satisfied(case: str, request: CodingKnowledgeRequest) -> bool:
    wanted = case.strip().removesuffix(".").removeprefix("./")
    return any(
        hint.strip().removeprefix("./") == wanted
        for hint in request.target_path_hints
    )


def evaluate_applicability(
    request: CodingKnowledgeRequest,
    candidate: CodingKnowledgeCandidate,
) -> ApplicabilityEvaluation:
    """Evaluate source-owned applicability cases against finite task signals.

    Pure and deterministic. Only verified-shaped inputs are accepted;
    malformed caller data raises, as elsewhere in this module.
    """
    if type(request) is not CodingKnowledgeRequest:
        raise TypeError("request must be a CodingKnowledgeRequest")
    if type(candidate) is not CodingKnowledgeCandidate:
        raise TypeError("candidate must be a CodingKnowledgeCandidate")
    cases = candidate.applicability_cases

    def _result(matched, reasons, satisfied, unsatisfied, fired, contradicted, evidence):
        satisfied_text = ",".join(map(str, satisfied)) or "-"
        unsatisfied_text = ",".join(map(str, unsatisfied)) or "-"
        fired_text = ",".join(map(str, fired)) or "-"
        contradicted_text = ",".join(map(str, contradicted)) or "-"
        return ApplicabilityEvaluation(
            matched=matched,
            reason_codes=tuple(reasons),
            satisfied=tuple(satisfied),
            unsatisfied=tuple(unsatisfied),
            exclusions_fired=tuple(fired),
            contradicted=tuple(contradicted),
            evidence=tuple(evidence),
            explanation=(
                f"applicability: satisfied=[{satisfied_text}] "
                f"unsatisfied=[{unsatisfied_text}] exclusions=[{fired_text}] "
                f"contradicted=[{contradicted_text}]"
            ),
        )

    if not cases:
        return _result(False, ("no-structured-applicability",), (), (), (), (), ())
    if len(cases) > _APPLICABILITY_MAX_CASES:
        return _result(False, ("oversized-applicability-record",), (), (), (), (), ())

    task_signals = tuple(_applicability_tokens(hint) for hint in request.capability_keywords)
    # As for positives, only one coherent task hint may evidence an exclusion.
    exclusion_signals = tuple(
        _applicability_tokens(hint, exclusion=True) for hint in request.capability_keywords
    )
    kinds = [_applicability_case_kind(case) for case in cases]
    satisfied: list[int] = []
    unsatisfied: list[int] = []
    fired: list[int] = []
    evidence: list[tuple[int, tuple[str, ...]]] = []
    for index, case in enumerate(cases):
        kind = kinds[index]
        if kind == "exclusion":
            shared = _strongest_case_evidence(
                _applicability_tokens(case, exclusion=True), exclusion_signals
            )
            if len(shared) >= _APPLICABILITY_MIN_SHARED_TOKENS:
                fired.append(index)
                evidence.append((index, shared))
            continue
        if kind == "path":
            if _path_case_satisfied(case, request):
                satisfied.append(index)
                evidence.append((index, (case.strip(),)))
            else:
                unsatisfied.append(index)
            continue
        shared = _strongest_case_evidence(_applicability_tokens(case), task_signals)
        if len(shared) >= _APPLICABILITY_MIN_SHARED_TOKENS:
            satisfied.append(index)
            evidence.append((index, shared))
        else:
            unsatisfied.append(index)

    if fired:
        return _result(
            False, ("applicability-exclusion-fired",), satisfied, unsatisfied,
            fired, (), evidence,
        )
    if "positive" not in kinds:
        return _result(
            False, ("applicability-positive-case-missing",), satisfied,
            unsatisfied, (), (), evidence,
        )
    if unsatisfied:
        return _result(
            False, ("applicability-conditions-unsatisfied",), satisfied,
            unsatisfied, (), (), evidence,
        )

    # Contradictory guidance wins, but only on strong evidence: the primary
    # guidance, a guardrail, or an avoid_when entry that restates a satisfied
    # positive case nearly in full and negates it. Mere shared tokens
    # plus a negation do not contradict: a guardrail like "never retry
    # without a budget cap" constrains the same action the case requires
    # and must not veto it. The bar is therefore a near-verbatim
    # restatement (all but at most one of the case's distinctive tokens,
    # at least three shared), not a two-token overlap.
    contradicted: list[int] = []
    contradiction_sources = (*candidate.use_when, *candidate.avoid_when)
    for index in satisfied:
        if kinds[index] != "positive":
            continue
        case_tokens = _applicability_tokens(cases[index])
        for source in contradiction_sources:
            if not _APPLICABILITY_NEGATION.search(_reviewed_text(source)):
                continue
            shared = _applicability_tokens(source) & case_tokens
            if len(shared) >= max(3, len(case_tokens) - 1):
                contradicted.append(index)
                break
    if contradicted:
        return _result(
            False, ("applicability-contradicted-guidance",), satisfied,
            unsatisfied, (), contradicted, evidence,
        )
    return _result(True, (_APPLICABILITY_REASON,), satisfied, (), (), (), evidence)


def _match_candidate(
    request: CodingKnowledgeRequest,
    candidate: CodingKnowledgeCandidate,
) -> tuple[int, tuple[str, ...]]:
    # Structured applicability is authoritative for its own lesson: a fired
    # exclusion or contradicted guidance returns no match, and unsatisfied
    # positives block every later path, including the generic fallback.
    # Satisfied positives are remembered and applied only after the narrow
    # reviewed branches below have had their chance to decide.
    applicability = evaluate_applicability(request, candidate)
    has_applicability = bool(candidate.applicability_cases)
    if has_applicability and not applicability.matched:
        return 0, applicability.reason_codes
    applicability_matched = has_applicability and applicability.matched

    def _no_match() -> tuple[int, tuple[str, ...]]:
        if applicability_matched:
            return 2, (_APPLICABILITY_REASON,)
        return 0, ()

    library_hints = {_norm(value) for value in request.library_hints}
    candidate_library = _norm(candidate.library_name) if candidate.library_name else ""
    candidate_name = _norm(candidate.name)
    exact_library = candidate_library in library_hints or candidate_name in library_hints

    ecosystems = {_norm(value) for value in request.ecosystem_hints + request.language_hints}
    ecosystem_match = _norm(candidate.ecosystem) in ecosystems

    capability_hints = {_norm(value) for value in request.capability_keywords}
    capability_terms = {_norm(candidate.capability_kind)} | {
        _norm(value) for value in candidate.keywords
    }
    capability_overlap = capability_hints & capability_terms

    path_match = False
    if candidate_library:
        path_match = any(candidate_library in _norm(path) for path in request.target_path_hints)

    exact_revision_request = "agent-os" in ecosystems and _EXECUTED_REVISION_HINTS <= capability_hints
    exact_revision_title = _EXECUTED_REVISION_TITLE.fullmatch(_reviewed_text(candidate.name).removesuffix("."))
    if exact_revision_title and (_norm(candidate.ecosystem) == "agent-os" or exact_revision_request):
        # A claimed rule cannot win on metadata, a caller-supplied hint, or a path alone.
        if (exact_revision_request or (ecosystem_match and capability_overlap)) and _executed_revision_evidence_match(candidate):
            return 2, (_EXECUTED_REVISION_REASON,)
        return _no_match()

    if exact_library:
        reasons = ["exact-library-match"]
        if path_match:
            reasons.append("target-path-match")
        return 3, tuple(reasons)
    library_tie_request = "agent-os" in ecosystems and any(
        hints <= capability_hints for hints in _LIBRARY_TIE_HINT_SETS
    )
    if library_tie_request or "testing" in capability_overlap:
        library_tie_lesson = _library_tie_guidance(candidate)
        if library_tie_request and library_tie_lesson and not _contradicts_primary(
            candidate, _LIBRARY_TIE_CONTRADICTION
        ):
            return 2, (_LIBRARY_TIE_REASON,)
        if library_tie_request or library_tie_lesson:
            # Testing alone neither answers this explicit mechanism request nor
            # makes this mechanism-specific guidance applicable elsewhere.
            capability_overlap.discard("testing")

    # Explicit CKR6 mutation-boundary requests may match a lesson's verified
    # title/guidance even when Notion's controlled vocabulary is generic.
    # Require BOTH distinctive tokens, as whole words, in the lesson-owned
    # text. This is relevance only, never eligibility or authorization.
    ci_request = "ckr6 mutation boundary" in capability_hints
    if ci_request:
        lesson_text = " ".join((candidate.name, *candidate.use_when)).casefold()
        if all(re.search(r"(?<![a-z0-9])" + term + r"(?![a-z0-9])", lesson_text)
               for term in ("ckr6", "mutation")):
            return 2, ("verified-ckr6-mutation-context-match",)

    # #4026: a specifically requested Git PR-refresh reconciliation
    # mechanism can match source-owned guidance even when Notion's generic
    # Learning Type/Applies To fields have no such controlled label.
    #
    # Require two explicit caller signals and multiple independent signals in
    # the lesson itself. Free-form task_reference and generic "testing" never
    # activate this path. This is a relevance *text match* only; it does not
    # attest to lesson applicability, currentness, provenance, or write authority.
    canonical_refresh = _PR_REFRESH_HINTS <= capability_hints
    historical_refresh = "git" in ecosystems and _PR_REFRESH_HISTORICAL_HINTS <= capability_hints
    if canonical_refresh or historical_refresh:
        title = candidate.name.casefold()
        guidance = _reviewed_text(candidate.use_when[0]) if candidate.use_when else ""
        if (
            not _PR_REFRESH_CONTRADICTION.search(guidance)
            and (canonical_refresh or not re.search(r"\b(?:not|never|avoid|skip|cannot)\b", guidance))
            and not _contradicts_primary(candidate, _PR_REFRESH_CONTRADICTION)
            and re.search(r"(?<![a-z0-9])(?:prs?|pull requests?)(?![a-z0-9])", title)
            and re.search(r"(?<![a-z0-9])(?:reconciliation|reconciling)(?![a-z0-9])", title)
            and not re.search(r"(?<![a-z0-9])(?:not|never|unrelated|avoid)(?![a-z0-9])", title)
            and re.search(r"(?<![a-z0-9])refresh(?:es|ed|ing)?(?![a-z0-9])", guidance)
            and re.search(
                r"(?<![a-z0-9])(?:reconciliation|reconcile|reconciled|reconciling|merge-tree)(?![a-z0-9])",
                guidance,
            )
            and re.search(r"(?<![a-z0-9])git(?![a-z0-9])", guidance)
        ):
            return 2, (_PR_REFRESH_REASON,)

    # #4026: the Writer's real, explicit task phrases are not controlled
    # Notion Learning Type / Applies To options. Before the old generic path,
    # allow only a source-owned, two-mechanism title+guidance agreement. A bare
    # "Notion" tag, caller prose, or known-ID hint is never a match on its own.
    # This is a lexical relevance hypothesis; eligibility and independent
    # semantic applicability remain separate CKR6/CKR2 requirements.
    if (
        {"notion writer", "persistence readback", "failure receipts"} <= capability_hints
        and ecosystem_match
        and candidate.source_system == "notion-lessons-learned"
        and "notion" in {_norm(tag) for tag in candidate.keywords}
    ):
        title = candidate.name.casefold()
        # Primary guidance can qualify; all other guidance can only veto.
        guidance = candidate.use_when[0].casefold() if candidate.use_when else ""
        all_guidance = " ".join(candidate.use_when).casefold()
        avoidance = " ".join(candidate.avoid_when).casefold()
        def whole(pattern: str, text: str) -> bool:
            return bool(re.search(r"(?<![a-z0-9])(?:" + pattern + r")(?![a-z0-9])", text))

        # Negative statements in use_when remain a blanket ambiguity stop.
        # An explicit warning about readback in avoid_when also vetoes this
        # specialized lexical match; generic keyword relevance and authority
        # are distinct contracts and are not changed here.
        negation = (
            r"unrelated|irrelevant|nonapplicable|no|not|never|without|"
            r"avoid|skip|reject(?:ed)?|"
            r"prohibit(?:ed|ion)?|forbid(?:den)?|cannot|"
            r"can.t|don.t|doesn.t|didn.t|shouldn.t|mustn.t|"
            r"wouldn.t|couldn.t|won.t|isn.t|aren.t"
        )
        readback_warning = (
            whole("readback|read.back|verif(?:y|ied|ication)", avoidance)
            and whole(negation, avoidance)
        )

        readback = r"(?:an? )?independent read[ -]?back"
        persisted_state = r"(?:the )?(?:persisted|saved) (?:state|revision|changes)"
        # Require an explicit verification purpose or instrument in one
        # guidance element, not a bag of related words across statements.
        persistence_verification = (
            rf"(?:use|perform) {readback} to (?:verify|confirm) {persisted_state}"
            rf"|(?:verify|confirm) {persisted_state} (?:with|using) {readback}"
        )
        # A write and verification in the same clause do not establish
        # their order. Accept an explicit post-write relation, not word order.
        after_write = r"after (?:a |the )?notion write"
        ordered_verification = re.compile(
            rf"(?:{after_write},? (?:{persistence_verification})"
            rf"|(?:{persistence_verification}) {after_write}"
            rf"|(?:write|persist) to notion,? then (?:{persistence_verification}))"
        )
        if (
            whole("notion", title)
            and whole("writ(?:e|er|ing|ten)|persist(?:ed|ence)?", title)
            and any(
                ordered_verification.fullmatch(_reviewed_text(clause))
                for clause in re.split(r"[.!?;]+", guidance)
            )
            and not whole(negation, title + " " + all_guidance)
            and not readback_warning
        ):
            return 2, ("notion-writer-readback-text-match",)

    # #4026: a source-owned REST evidence mechanism can outrank generic
    # metadata only after an explicit conjunctive request and strict content
    # check. Canonical currentness/provenance/identity gates still run later.
    if _github_rest_evidence_match(candidate, capability_hints, ecosystems):
        return 2, ("github-rest-evidence-text-match",)
    # #4090: require BOTH explicit caller signals and independent title plus
    # guidance signals owned by the lesson. Free-form task_reference, generic
    # "notion"/"quality-assurance" keywords, and the Guardrail entry never
    # activate this path. This is a relevance *text match* only; it does not
    # attest to lesson applicability, currentness, provenance, or write authority.
    if (
        _NOTION_EXECUTOR_HINTS <= capability_hints
        and candidate.source_system == "notion-lessons-learned"
        and _reviewed_text(candidate.name) == _NOTION_EXECUTOR_TITLE
        and candidate.use_when
        and _reviewed_text(candidate.use_when[0]) in _NOTION_EXECUTOR_GUIDANCE
        and not _contradicts_primary(candidate, _NOTION_EXECUTOR_CONTRADICTION)
    ):
        return 2, (_NOTION_EXECUTOR_REASON,)

    if exact_revision_request and (not ecosystem_match or _norm(candidate.ecosystem) == "agent-os"):
        return _no_match()

    # Satisfied structured applicability outranks the loose generic
    # fallback: the lesson's own record evidenced the task, so the result
    # must say so instead of reporting a metadata overlap.
    if applicability_matched:
        return 2, (_APPLICABILITY_REASON,)

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


def _missing_candidate_provenance(selected: tuple[SelectedKnowledge, ...]) -> bool:
    """Every retained candidate must carry its own canonical_github_refs.

    Request-owned canonical_rule_refs are task/inspect-first evidence and can
    never satisfy a selected candidate's own provenance requirement, and one
    candidate's refs can never satisfy another candidate's absence.
    """
    return any(not item.candidate.canonical_github_refs for item in selected)


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


def _validate_text(value: object, field: str, *, max_chars: int = MAX_TEXT_CHARS) -> None:
    if type(value) is not str:
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} must be non-empty")
    if len(value) > max_chars:
        raise ValueError(f"{field} is oversized")
    if any(ord(char) < 32 and char not in "\t" for char in value):
        raise ValueError(f"{field} contains control characters")


def _validate_text_tuple(
    values: object, field: str, *, max_chars: int = MAX_TEXT_CHARS
) -> None:
    if type(values) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    if len(values) > MAX_SIGNAL_ITEMS:
        raise ValueError(f"{field} is oversized")
    for value in values:
        _validate_text(value, field, max_chars=max_chars)


def _norm(value: str) -> str:
    return value.strip().casefold()
