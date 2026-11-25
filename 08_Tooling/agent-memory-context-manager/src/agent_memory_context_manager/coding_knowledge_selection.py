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
# joined and whitespace is stripped; it is not a provider per-segment limit.
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

    # The pre-cut ranking is internal to the CKR11/CKR6 path. Reject
    # stale or forged identity priorities and cross-bucket inversions.
    if _ranked_order is not None:
        ranked_buckets = {item.knowledge_id: 0 for item in deduped}
        ranked_buckets.update((item[2].knowledge_id, item[0]) for item in ranked)
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
    best.sort(key=lambda item: item[1])
    if _ranked_order is None:
        # Standalone CKR2 callers retain the original bounded ranking.
        scores = contextual_tie_scores(request, (item[2] for item in best))
        order = sorted(range(len(best)), key=lambda index: (-scores[index], best[index][1]))
        best = [best[index] for index in order]
        coverage_order = required_library_coverage_order(
            request, (item[2] for item in best)
        )
        best = [best[index] for index in coverage_order]
    else:
        # Never recompute document frequency on the five finalists.
        priority = {identity: index for index, identity in enumerate(_ranked_order)}
        best.sort(key=lambda item: priority[item[2].knowledge_id])

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
_LIBRARY_TIE_CONTRADICTION = re.compile(
    r"\b(?:(?:never|do not|must not|should not) (?:preserve|maintain)"
    r"|avoid (?:preserving|maintaining)) "
    r"(?:(?:explicitly )?requested library coverage|(?:the widest )?coverage "
    r"(?:of|for|across) (?:explicitly )?requested libraries)\b"
)


def _library_tie_guidance(candidate: CodingKnowledgeCandidate) -> bool:
    return (
        candidate.source_system == "notion-lessons-learned"
        and _norm(candidate.ecosystem) == "agent-os"
        and bool(candidate.use_when)
        and _LIBRARY_TIE_TITLE.fullmatch(" ".join(candidate.name.casefold().split())) is not None
        and _LIBRARY_TIE_GUIDANCE.fullmatch(
            " ".join(candidate.use_when[0].casefold().split())
        ) is not None
    )


_PR_REFRESH_HINTS = frozenset({"branch refresh", "merge-tree fallback"})
# The owner used this complete mechanism description on #3991 before #4091.
# It must not reduce to generic Git, merge-tree, or conflict-detection hints.
_PR_REFRESH_HISTORICAL_HINTS = frozenset({
    "git branch refresh", "rebase rejection", "merge-tree conflict detection", "bounded recovery",
})
_PR_REFRESH_REASON = "pr-refresh-reconciliation-text-match"


_LESSON_TEST_REASON = "verified-lesson-relevance-test-match"
# Keep task hints and the lesson's own title / primary guidance independent.
_LESSON_TEST_MECHANISMS = (
    (
        frozenset({"selection basis", "caller reporting"}),
        re.compile(r"\b(?:caller|handoff)\b"),
        re.compile(r"\bselection reason\b[^.!?]*\bselector-to-caller\b"),
    ),
    (
        frozenset({"lexical lesson relevance", "reversed instruction"}),
        re.compile(r"\b(?:lexical lesson|relevance match)"),
        re.compile(r"\bhard negatives?\b[^.!?]*\breverse (?:the )?(?:advice|action|order)\b"),
    ),
)
_LESSON_TEST_NEGATION = re.compile(
    r"\b(?:not|never|skip|avoid|cannot|no need|\w+n['’ʼ]t)\s+"
    r"(?:test(?:ing)?|check(?:ing)?|pair(?:ing)?|revers(?:e|ing)|register(?:ing)?|extend(?:ing)?)\b"
)


def _lesson_test_mechanisms(candidate: CodingKnowledgeCandidate) -> tuple[frozenset[str], ...]:
    if candidate.source_system != "notion-lessons-learned" or not candidate.use_when:
        return ()
    title = " ".join(candidate.name.casefold().split())
    guidance = " ".join(candidate.use_when[0].casefold().split())
    return tuple(
        hints if not _LESSON_TEST_NEGATION.search(title + " " + guidance) else frozenset()
        for hints, title_pattern, guidance_pattern in _LESSON_TEST_MECHANISMS
        if title_pattern.search(title) and guidance_pattern.search(guidance)
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
    library_tie_request = "agent-os" in ecosystems and any(
        hints <= capability_hints for hints in _LIBRARY_TIE_HINT_SETS
    )
    if library_tie_request or "testing" in capability_overlap:
        library_tie_lesson = _library_tie_guidance(candidate)
        if library_tie_request and library_tie_lesson and not any(
            _LIBRARY_TIE_CONTRADICTION.search(" ".join(text.casefold().split()))
            for text in candidate.use_when[1:]
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
        guidance = " ".join(candidate.use_when).casefold()
        if not canonical_refresh:
            # Do not extend the old token matcher to a new request shape on
            # the strength of a warning, or a negated instruction.
            guidance = candidate.use_when[0].casefold() if candidate.use_when else ""
            if re.search(r"\b(?:not|never|avoid|skip|cannot)\b", guidance):
                guidance = ""
        if (
            re.search(r"(?<![a-z0-9])(?:prs?|pull requests?)(?![a-z0-9])", title)
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

    lesson_tests = _lesson_test_mechanisms(candidate)
    if lesson_tests:
        # Generic Testing/QA metadata is not enough for this mechanism.
        capability_overlap.difference_update(("testing", "quality-assurance"))
        if ecosystem_match and len(lesson_tests) == 1:
            hints, = lesson_tests
            if hints and hints <= capability_hints:
                return 2, (_LESSON_TEST_REASON,)

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
