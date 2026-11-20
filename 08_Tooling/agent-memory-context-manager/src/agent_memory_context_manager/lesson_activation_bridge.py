"""Bounded live Lessons Learned activation bridge for CKR6 (#1516 / CKR11).

This module is the runtime seam between already-resolved
``CodingKnowledgeRequest`` signals and the existing CKR6
``consume_lesson_preflight`` contract. It performs no Notion network access
itself: the caller injects a bounded read executor that must reuse the
existing read-only Notion query path (``NotionReadOnlyAdapter.query_data_source``
via the Workflow Scheduler, or an equivalent already-approved read surface).

Ordering matches CKR6/CKR2 exactly: ``not-needed`` performs zero reads; a
known lesson reference is attempted before a bounded filtered query. Ordinary
filtered retrieval derives exact provider filters from the request's existing
finite signals, may inspect a bounded relevance page larger than CKR2's five
candidate budget, and deterministically narrows to at most
``MAX_LESSON_RECORDS`` before selection. Live Notion row shapes are mapped
through a finite, deterministic vocabulary; anything missing or ambiguous is
excluded as explicitly non-ready rather than guessed. The shared CKR2
candidate-owned provenance invariant (#1520) is reused unchanged -- this
module adds no duplicate provenance guard or relevance vocabulary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .coding_knowledge_selection import (
    MAX_GUIDANCE_TEXT_CHARS,
    MAX_SELECTED,
    CodingKnowledgeCandidate,
    CodingKnowledgeRequest,
    KnowledgeCurrentness,
    RetrievalEscalation,
    _match_candidate,
    _norm,
)
from .lesson_preflight import (
    MAX_LESSON_RECORDS,
    LessonPreflightResult,
    LessonRecordEvidence,
    consume_lesson_preflight,
    plan_lesson_preflight,
)

MAX_ROW_TEXT_CHARS = 512
MAX_ROW_LIST_ITEMS = 20
MAX_RETRIEVAL_ROWS = MAX_LESSON_RECORDS * 5
# #3973 full-database repair: a Notion query page is not the database.
# The live Lessons Learned database holds more rows than one page_size=25
# response can carry, and the provider may return smaller pages. Follow
# `next_cursor` until `has_more` is false, bounded by the row cap above
# and by this page cap so a lying executor can never loop forever. Hitting
# the page cap with pages still outstanding fails closed (a
# LessonActivationError) instead of silently truncating the database tail.
MAX_RETRIEVAL_PAGES = 5

_LESSON_ID_PROPERTY = "Lesson ID"
_TITLE_PROPERTY = "Lesson Learned"
_STATUS_PROPERTY = "Status"
_SURFACE_PROPERTY = "Surface Before Work?"
_AREA_PROPERTY = "Area"
_APPLIES_TO_PROPERTY = "Applies To"
_LEARNING_TYPE_PROPERTY = "Learning Type"
_SOURCE_LINK_PROPERTY = "Source Link"
# #3973 (optional, proposed): bounded curated corroborating refs. One
# canonical GitHub ref per rich-text item; no free-form parsing. The
# property is absent on legacy rows, which behave exactly as today.
_SUPPORTING_PROPERTY = "Supporting Source Links"
MAX_SUPPORTING_REFS = 5
# A supporting ref must be a canonical Blummer92/agent-os issue/PR URL or
# one of the five repo-relative governance prefixes -- the same allowlist
# shape as the primary Source Link, tightened to this repository for
# supporting evidence. Anything else is dropped and reported, never admitted.
_SUPPORTING_REF = re.compile(
    r"https://github\.com/Blummer92/agent-os/(?:issues|pull)/[1-9][0-9]{0,6}"
)
_GITHUB_REPOSITORY = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+")
_GITHUB_NUMBER = re.compile(r"[1-9][0-9]*")
_GITHUB_COMMIT = re.compile(r"[0-9a-fA-F]{7,40}")
_GOVERNANCE_PREFIXES = (
    "00_Governance/",
    "01_Shared_Standards/",
    "02_Agent_Overlays/",
    "04_Registry/",
    "08_Tooling/",
)
_GUARDRAIL_PROPERTY = "Guardrail"
_NEXT_TIME_PROPERTY = "What To Do Next Time"

REQUIRED_LESSON_PROPERTIES = (
    _LESSON_ID_PROPERTY,
    _TITLE_PROPERTY,
    _STATUS_PROPERTY,
    _SURFACE_PROPERTY,
    _AREA_PROPERTY,
    _APPLIES_TO_PROPERTY,
    _LEARNING_TYPE_PROPERTY,
    _SOURCE_LINK_PROPERTY,
    _GUARDRAIL_PROPERTY,
    _NEXT_TIME_PROPERTY,
)

# Live finite Status vocabulary (#1516 point 4 / notion-learning-databases.md).
_STATUS_VOCABULARY = frozenset({"New", "Applied", "Needs follow-up", "Archived note"})
_APPLIES_TO_VOCABULARY = (
    "Apps Script",
    "Google Workspace",
    "Drive",
    "Notion",
    "Curriculum",
    "Dashboard",
    "Deployment",
    "Instructional Materials",
)

# Finite deterministic Area -> ecosystem mapping. Anything outside this map
# fails closed as ambiguous activation vocabulary rather than being guessed.
_AREA_ECOSYSTEM: dict[str, str] = {
    "Curriculum": "agent-os",
    "Automation": "python",
    "Dashboard": "python",
    "Governance": "agent-os",
    "Documentation": "agent-os",
    "Testing": "python",
}

# Finite deterministic Learning Type -> capability_kind mapping.
_LEARNING_TYPE_CAPABILITY: dict[str, str] = {
    "Mistake": "failure-avoidance",
    "QA feedback": "quality-assurance",
    "Testing lesson": "testing",
    "Deployment lesson": "deployment",
    "Scope/permission lesson": "authorization-routing",
    "Trigger lesson": "scheduling",
}


class LessonActivationError(ValueError):
    """Bounded orchestration-boundary error. Never used to fabricate evidence."""


@dataclass(frozen=True, slots=True)
class LessonActivationSkip:
    """One explicitly non-ready live row and the fail-closed reason."""

    lesson_id: str | None
    reason: str


ReadExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]


_LESSON_ID_REFERENCE = re.compile(r"(?:[A-Za-z][A-Za-z0-9_]*-)?([0-9]{1,9})")


def known_lesson_numbers(known_ids: Sequence[str]) -> tuple[int, ...]:
    """Lesson ID numbers named by explicit references, in first-seen order.

    The live ``Lesson ID`` is a Notion ``unique_id`` (auto-increment) property,
    rendered by row normalization as ``<prefix>-<number>``. Only that shape (or a
    bare number) names a lesson; other references such as ``#2638`` do not.
    """
    numbers: dict[int, None] = {}
    for value in known_ids:
        match = _LESSON_ID_REFERENCE.fullmatch(value.strip()) if isinstance(value, str) else None
        if match is not None:
            numbers[int(match.group(1))] = None
    return tuple(numbers)[:MAX_LESSON_RECORDS]


def build_known_reference_query(known_ids: Sequence[str]) -> dict[str, Any]:
    """Smallest bounded query for an explicit known lesson identity lookup.

    Provider response projection is deliberately omitted here. The canonical
    source binding gives us a data-source identity, not provider property IDs;
    projecting by stable display names can make an otherwise valid live query
    fail before CKR6 can normalize the bounded rows. Row normalization below
    still consumes only ``REQUIRED_LESSON_PROPERTIES``.

    Filter types must match the live property types (#3032): a type-mismatched
    Notion filter is rejected with HTTP 400.
    """
    numbers = known_lesson_numbers(known_ids)
    if not numbers:
        raise LessonActivationError("known_ids must contain at least one lesson identifier")
    return {
        "page_size": MAX_LESSON_RECORDS,
        "filter": {
            "or": [
                {"property": _LESSON_ID_PROPERTY, "unique_id": {"equals": number}}
                for number in numbers
            ]
        },
    }


def _normalized(values: Sequence[str]) -> frozenset[str]:
    return frozenset(value.strip().casefold() for value in values if value.strip())


def _relevance_filter_clauses(request: CodingKnowledgeRequest) -> list[dict[str, Any]]:
    """Translate explicit request signals through the existing finite vocabularies."""
    ecosystem_hints = _normalized(request.ecosystem_hints + request.language_hints)
    capability_hints = _normalized(request.capability_keywords)

    clauses: list[dict[str, Any]] = []
    # Only a finite exact CI/CKR6 hint maps to the existing Testing area.
    # No arbitrary request prose is sent as a provider option identity.
    if {"ckr6 mutation boundary", "fail-closed lesson preflight"} & capability_hints:
        clauses.append({"property": _AREA_PROPERTY, "select": {"equals": "Testing"}})
    for area, ecosystem in sorted(_AREA_ECOSYSTEM.items()):
        if ecosystem.casefold() in ecosystem_hints:
            clauses.append({"property": _AREA_PROPERTY, "select": {"equals": area}})
    for learning_type, capability in sorted(_LEARNING_TYPE_CAPABILITY.items()):
        if capability.casefold() in capability_hints:
            clauses.append(
                {"property": _LEARNING_TYPE_PROPERTY, "select": {"equals": learning_type}}
            )

    # Applies To is a controlled multi-select.  Only values from the canonical
    # finite vocabulary may be sent to Notion.  Request paths and arbitrary
    # capability/library text remain useful to CKR2's in-memory matcher after
    # rows are returned, but they are not provider option identities and must
    # never be projected into a schema-sensitive multi_select filter.
    applies_to_hints = _normalized(
        request.capability_keywords + request.library_hints + request.ecosystem_hints
    )
    for term in _APPLIES_TO_VOCABULARY:
        if term.casefold() in applies_to_hints:
            clauses.append(
                {"property": _APPLIES_TO_PROPERTY, "multi_select": {"contains": term}}
            )
    # Repeated canonical clauses must not consume the bounded query budget.
    return list({str(clause): clause for clause in clauses}.values())


def build_filtered_query(request: CodingKnowledgeRequest) -> dict[str, Any]:
    """Build a bounded task-specific read query without inventing vocabulary.

    Do not emit a provider ``filter_properties`` projection from property
    display names. The live source binding does not carry provider property
    IDs, while bounded row normalization already drops every unknown field.
    """
    if type(request) is not CodingKnowledgeRequest:
        raise TypeError("request must be a CodingKnowledgeRequest")

    base_filter: list[dict[str, Any]] = [
        {"property": _SURFACE_PROPERTY, "checkbox": {"equals": True}},
        {
            "property": _STATUS_PROPERTY,
            "select": {"does_not_equal": "Archived note"},
        },
    ]
    relevance_clauses = _relevance_filter_clauses(request)
    if relevance_clauses:
        base_filter.append({"or": relevance_clauses})

    return {
        "page_size": MAX_RETRIEVAL_ROWS if relevance_clauses else MAX_LESSON_RECORDS,
        "filter": {"and": base_filter},
    }


def normalize_lesson_row(row: Mapping[str, Any]) -> LessonRecordEvidence | LessonActivationSkip:
    """Deterministically map one bounded live row, or fail closed as non-ready.

    Consumes only the finite set of controlled properties this module knows
    about. No raw page body, unknown property, or unbounded collection is
    read into the result; anything missing or ambiguous yields an explicit
    ``LessonActivationSkip`` rather than an invented value.
    """
    if not isinstance(row, Mapping):
        return LessonActivationSkip(None, "malformed-row")
    if row.get("object") not in (None, "page"):
        return LessonActivationSkip(None, "malformed-row")

    properties = row.get("properties")
    if not isinstance(properties, Mapping):
        return LessonActivationSkip(None, "missing-properties")

    lesson_id = _rich_text_or_unique_id(properties.get(_LESSON_ID_PROPERTY))
    if lesson_id is None:
        return LessonActivationSkip(None, "missing-stable-identity")

    source_revision = row.get("last_edited_time")
    if not isinstance(source_revision, str) or not source_revision.strip():
        return LessonActivationSkip(lesson_id, "missing-verified-revision")

    title = _title_text(properties.get(_TITLE_PROPERTY))
    if title is None:
        return LessonActivationSkip(lesson_id, "missing-title")

    status = _select_name(properties.get(_STATUS_PROPERTY))
    if status is None or status not in _STATUS_VOCABULARY:
        return LessonActivationSkip(lesson_id, "ambiguous-status-vocabulary")

    surface_before_work = _checkbox(properties.get(_SURFACE_PROPERTY))
    if surface_before_work is None:
        return LessonActivationSkip(lesson_id, "ambiguous-surface-flag")

    area = _select_name(properties.get(_AREA_PROPERTY))
    ecosystem = _AREA_ECOSYSTEM.get(area) if area is not None else None
    if ecosystem is None:
        return LessonActivationSkip(lesson_id, "ambiguous-area-vocabulary")

    learning_type = _select_name(properties.get(_LEARNING_TYPE_PROPERTY))
    capability_kind = (
        _LEARNING_TYPE_CAPABILITY.get(learning_type) if learning_type is not None else None
    )
    if capability_kind is None:
        return LessonActivationSkip(lesson_id, "ambiguous-learning-type-vocabulary")

    guardrail, guardrail_state = _guidance_text(properties.get(_GUARDRAIL_PROPERTY))
    what_to_do_next_time, next_time_state = _guidance_text(properties.get(_NEXT_TIME_PROPERTY))
    if guardrail_state == "oversized" or next_time_state == "oversized":
        # Present but over the shared guidance bound: fail closed with a
        # distinct reason, never mislabeled as missing guidance.
        return LessonActivationSkip(lesson_id, "oversized-activation-guidance")
    if guardrail is None or what_to_do_next_time is None:
        return LessonActivationSkip(lesson_id, "missing-activation-guidance")

    applies_to = _multi_select_names(properties.get(_APPLIES_TO_PROPERTY))
    if applies_to is None:
        return LessonActivationSkip(lesson_id, "ambiguous-applies-to-vocabulary")

    canonical_ref = _github_source_link(properties.get(_SOURCE_LINK_PROPERTY))
    currentness = KnowledgeCurrentness.CURRENT if canonical_ref else KnowledgeCurrentness.UNVERIFIABLE
    supporting_valid, supporting_dropped = _supporting_source_links(
        properties.get(_SUPPORTING_PROPERTY), canonical_ref
    )
    if canonical_ref:
        # Primary first, then supporting refs in row order, stably deduped.
        # One lesson stays one CKR2 candidate; the budget does not change.
        canonical_github_refs = (canonical_ref,) + supporting_valid
        dropped_supporting_refs = supporting_dropped
    else:
        # The primary Source Link is still required (#3973 / #1520): valid
        # supporting refs never substitute for a missing primary. They are
        # reported as dropped rather than silently admitted or lost.
        canonical_github_refs = ()
        dropped_supporting_refs = (supporting_dropped + supporting_valid)[:MAX_ROW_LIST_ITEMS]

    evidence_refs: tuple[str, ...] = ()
    page_url = row.get("url")
    if isinstance(page_url, str) and page_url.strip():
        evidence_refs = (page_url.strip()[:MAX_ROW_TEXT_CHARS],)

    try:
        lesson = LessonRecordEvidence(
            lesson_id=lesson_id,
            source_revision=source_revision,
            title=title,
            ecosystem=ecosystem,
            capability_kind=capability_kind,
            status=status,
            surface_before_work=surface_before_work,
            currentness=currentness,
            what_to_do_next_time=what_to_do_next_time,
            guardrail=guardrail,
            canonical_github_refs=canonical_github_refs,
            evidence_refs=evidence_refs,
            keywords=applies_to,
            dropped_supporting_refs=dropped_supporting_refs,
            archived=status == "Archived note",
        )
        # Validate CKR2 text invariants inside the per-row isolation boundary.
        _as_selection_candidate(lesson)
        return lesson
    except (TypeError, ValueError):
        return LessonActivationSkip(lesson_id, "oversized-or-malformed-field")


def _as_selection_candidate(lesson: LessonRecordEvidence) -> CodingKnowledgeCandidate:
    return CodingKnowledgeCandidate(
        knowledge_id=lesson.lesson_id,
        source_system="notion-lessons-learned",
        source_revision=lesson.source_revision,
        currentness=lesson.currentness,
        name=lesson.title,
        ecosystem=lesson.ecosystem,
        library_name=lesson.library_name,
        capability_kind=lesson.capability_kind,
        keywords=lesson.keywords,
        use_when=(lesson.what_to_do_next_time, lesson.guardrail),
        avoid_when=(),
        canonical_github_refs=lesson.canonical_github_refs,
        evidence_refs=lesson.evidence_refs,
        authority_conflict=lesson.authority_conflict,
    )


def _bound_relevant_lessons(
    request: CodingKnowledgeRequest, lessons: Sequence[LessonRecordEvidence]
) -> tuple[LessonRecordEvidence, ...]:
    """Keep CKR2's candidate budget while reusing CKR2's canonical matcher.

    R1 (#2425): the budget counts DISTINCT lesson IDs. A conflicting
    identity counts once, and ALL its records enter the bound set, so a
    conflict at the bound edge is reported by the selector instead of being
    silently dropped with the second revision.
    """
    ranked: list[tuple[int, str, LessonRecordEvidence]] = []
    unranked: list[LessonRecordEvidence] = []
    for lesson in lessons:
        bucket, _ = _match_candidate(request, _as_selection_candidate(lesson))
        if bucket:
            ranked.append((bucket, lesson.lesson_id.casefold(), lesson))
        else:
            unranked.append(lesson)

    if ranked:
        ranked.sort(key=lambda item: (-item[0], item[1]))
        # Rank identities, not individual revisions. A second revision of
        # a selected ID may be unranked, but must still reach CKR2's
        # fail-closed duplicate-identity conflict check.
        selected_ids = {
            lesson.lesson_id
            for lesson in _take_distinct_ids([item[2] for item in ranked])
        }
        return tuple(lesson for lesson in lessons if lesson.lesson_id in selected_ids)
    unranked.sort(key=lambda item: item.lesson_id.casefold())
    return _take_distinct_ids(unranked)


# PR-1 (observational): closed vocabulary describing HOW the CKR2 matcher chose
# lessons. A value states mechanism only -- never relevance, truth or
# verification -- and never feeds selection, status or admission.
# ``not-evaluated`` means selection was skipped, unavailable or could not
# complete (not-needed, no read executor, read error, incomplete pagination);
# ``no-relevant-signal`` is reserved for a COMPLETED evaluation that found no
# qualifying match.
SELECTION_BASIS_VALUES = frozenset({
    "no-relevant-signal",
    "identity-scoped",
    "title-echo",
    "exact-library",
    "rule-ckr6-mutation-boundary",
    "generic-unique",
    "generic-tie-lexical-cut",
    "not-evaluated",
})
_GENERIC_REASONS = frozenset({
    "keyword-overlap", "ecosystem-capability-match", "target-path-match",
})


@dataclass(frozen=True)
class SelectionBasis:
    basis: str
    best_bucket: int
    tied_identities: int


# Recorded when no evaluation completed. Never produced by
# ``describe_selection_basis`` itself, which always describes a completed one.
NOT_EVALUATED = SelectionBasis(basis="not-evaluated", best_bucket=0, tied_identities=0)


def describe_selection_basis(
    request: CodingKnowledgeRequest,
    lessons: Sequence[LessonRecordEvidence],
    *,
    identity_route: bool,
) -> SelectionBasis:
    """Describe how the canonical CKR2 matcher chose among ``lessons``.

    Pure and observational: reuses ``_match_candidate`` unchanged, reads
    only the request's hint fields (never ``task_reference``), does not
    mutate or reorder its inputs, and is never consulted by selection.
    ``tied_identities`` counts DISTINCT lesson IDs in the best bucket over
    the whole pool given (before the five-ID bound), so a duplicate revision
    counts once.
    """
    best = 0
    tied: set[str] = set()
    reasons: set[str] = set()
    via_library_name = False
    hints = {_norm(value) for value in request.library_hints}
    for lesson in lessons:
        bucket, matched = _match_candidate(request, _as_selection_candidate(lesson))
        if not bucket:
            continue
        if bucket > best:
            best, tied, reasons, via_library_name = bucket, set(), set(), False
        if bucket == best:
            tied.add(lesson.lesson_id)
            reasons.update(matched)
            if lesson.library_name and _norm(lesson.library_name) in hints:
                via_library_name = True

    # Evaluated in the documented order; the first matching row wins.
    if not best:
        basis = "no-relevant-signal"
    elif identity_route:
        basis = "identity-scoped"
    elif best == 3:
        basis = "exact-library" if via_library_name else "title-echo"
    elif "verified-ckr6-mutation-context-match" in reasons:
        basis = "rule-ckr6-mutation-boundary"
    elif reasons & _GENERIC_REASONS:
        basis = "generic-unique" if len(tied) <= MAX_SELECTED else "generic-tie-lexical-cut"
    else:  # pragma: no cover - the matcher has no other reason vocabulary
        basis = "no-relevant-signal"
    return SelectionBasis(basis=basis, best_bucket=best, tied_identities=len(tied))


def _take_distinct_ids(
    ordered: Sequence[LessonRecordEvidence],
) -> tuple[LessonRecordEvidence, ...]:
    """First MAX_LESSON_RECORDS distinct lesson IDs, with every record of
    each bounded identity included."""
    seen: set[str] = set()
    kept: list[LessonRecordEvidence] = []
    for lesson in ordered:
        if lesson.lesson_id in seen:
            kept.append(lesson)
            continue
        if len(seen) >= MAX_LESSON_RECORDS:
            continue
        seen.add(lesson.lesson_id)
        kept.append(lesson)
    return tuple(kept)


def orchestrate_lesson_activation(
    request: CodingKnowledgeRequest,
    *,
    execute_read: ReadExecutor | None,
) -> LessonPreflightResult:
    """Plan, bound, execute, and normalize one live Lessons Learned retrieval.

    ``execute_read`` must already be bound to the canonical Lessons Learned
    data source through the existing read-only Notion adapter; this function
    never constructs a client, credential, or second retrieval mechanism.
    """
    if type(request) is not CodingKnowledgeRequest:
        raise TypeError("request must be a CodingKnowledgeRequest")

    plan = plan_lesson_preflight(request)
    if not plan.retrieval_required:
        return consume_lesson_preflight(request, ())

    if execute_read is None:
        return consume_lesson_preflight(request, (), retrieval_available=False)

    if plan.recommended_escalation is RetrievalEscalation.KNOWN_REFERENCE and known_lesson_numbers(
        request.known_knowledge_refs
    ):
        query = build_known_reference_query(request.known_knowledge_refs)
    else:
        query = build_filtered_query(request)

    # Exhaust every provider page up to the bounded row/page caps. A single
    # first page is NOT the database: rows past the first page are real
    # lessons, and silently dropping them would make CKR6 retrieval
    # incomplete exactly when the database grows past one page. Follow-up
    # pages carry only `start_cursor`; the real read adapter forwards the
    # query body to the Notion data-source query endpoint, which accepts it.
    rows: list[Mapping[str, Any]] = []
    seen_cursors: set[str | None] = set()
    cursor: str | None = None
    for _page_index in range(MAX_RETRIEVAL_PAGES):
        if cursor in seen_cursors:
            raise LessonActivationError("repeated pagination cursor")
        seen_cursors.add(cursor)
        page_query = query if cursor is None else {**query, "start_cursor": cursor}
        raw = execute_read(page_query)
        page_rows = _extract_bounded_rows(raw)
        # Validate pagination BEFORE admitting any rows. At the row boundary
        # a complete 25-row page is acceptable only with has_more=False.
        has_more, next_cursor = _page_cursor(raw)
        if len(rows) + len(page_rows) > MAX_RETRIEVAL_ROWS:
            raise LessonActivationError("paginated retrieval exceeded row bound")
        rows.extend(page_rows)
        if not has_more:
            break
        if len(rows) >= MAX_RETRIEVAL_ROWS:
            raise LessonActivationError("paginated retrieval exceeded row bound")
        if next_cursor is None:
            raise LessonActivationError("paginated retrieval missing next cursor")
        cursor = next_cursor
    else:
        raise LessonActivationError("paginated retrieval exceeded page bound")

    lessons: list[LessonRecordEvidence] = []
    for row in rows:
        normalized = normalize_lesson_row(row)
        if isinstance(normalized, LessonRecordEvidence):
            lessons.append(normalized)

    bounded = _bound_relevant_lessons(request, lessons)
    return consume_lesson_preflight(request, bounded)


def _extract_bounded_rows(raw: Any) -> list[Mapping[str, Any]]:
    if not isinstance(raw, Mapping):
        raise LessonActivationError("read executor must return a mapping")
    results = raw.get("results")
    if not isinstance(results, list):
        raise LessonActivationError("read executor result is missing 'results'")
    # A page is admitted only whole: any non-mapping item makes the page
    # malformed, never silently filtered.
    if not all(isinstance(item, Mapping) for item in results):
        raise LessonActivationError("read executor result contains non-mapping items")
    if len(results) > MAX_RETRIEVAL_ROWS:
        raise LessonActivationError("paginated retrieval exceeded row bound")
    return list(results)


def _page_cursor(raw: Any) -> tuple[bool, str | None]:
    """Validate one page's pagination state, or fail closed.

    A missing ``has_more`` is malformed, not a complete single page:
    assuming completeness could silently truncate the database.
    ``has_more: true`` without a non-empty string ``next_cursor`` is
    malformed: following it would loop, and ignoring it would silently
    truncate the database.
    """
    if not isinstance(raw, Mapping):
        raise LessonActivationError("read executor must return a mapping")
    if "has_more" not in raw:
        raise LessonActivationError("read executor result is missing 'has_more'")
    has_more = raw["has_more"]
    if type(has_more) is not bool:
        raise LessonActivationError("read executor returned a non-boolean has_more")
    next_cursor = raw.get("next_cursor")
    if next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor.strip()):
        raise LessonActivationError("read executor returned a malformed next_cursor")
    # A terminal page must not simultaneously advertise a continuation.
    # Do not admit an incomplete or internally contradictory corpus to CKR2.
    if not has_more and next_cursor is not None:
        raise LessonActivationError("read executor returned a malformed next_cursor")
    return has_more, next_cursor.strip() if isinstance(next_cursor, str) else None


def _guidance_text(prop: Any) -> tuple[str | None, str]:
    """Advisory narrative text under the shared guidance bound.

    Returns (text, "ok") when the property is present and within
    MAX_GUIDANCE_TEXT_CHARS; (None, "missing") when absent, malformed, or
    empty; (None, "oversized") when present but over the shared bound, so a
    long Guardrail is never reported as "missing-activation-guidance".
    Nothing is truncated; over-bound guidance fails closed.
    """
    if not isinstance(prop, Mapping) or prop.get("type") != "rich_text":
        return None, "missing"
    items = prop.get("rich_text")
    if not isinstance(items, list) or len(items) > MAX_ROW_LIST_ITEMS:
        return None, "missing"
    parts: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            return None, "missing"
        text = item.get("plain_text")
        if not isinstance(text, str):
            return None, "missing"
        parts.append(text)
    joined = "".join(parts).strip()
    if not joined:
        return None, "missing"
    if len(joined) > MAX_GUIDANCE_TEXT_CHARS:
        return None, "oversized"
    return joined, "ok"


def _plain_text(rich_text: Any) -> str | None:
    if not isinstance(rich_text, list) or len(rich_text) > MAX_ROW_LIST_ITEMS:
        return None
    parts: list[str] = []
    for item in rich_text:
        if not isinstance(item, Mapping):
            return None
        text = item.get("plain_text")
        if not isinstance(text, str):
            return None
        parts.append(text)
    joined = "".join(parts).strip()
    if not joined or len(joined) > MAX_ROW_TEXT_CHARS:
        return None
    return joined


def _title_text(prop: Any) -> str | None:
    if not isinstance(prop, Mapping) or prop.get("type") != "title":
        return None
    return _plain_text(prop.get("title"))


def _rich_text(prop: Any) -> str | None:
    if not isinstance(prop, Mapping) or prop.get("type") != "rich_text":
        return None
    return _plain_text(prop.get("rich_text"))


def _rich_text_or_unique_id(prop: Any) -> str | None:
    if not isinstance(prop, Mapping):
        return None
    prop_type = prop.get("type")
    if prop_type == "rich_text":
        return _plain_text(prop.get("rich_text"))
    if prop_type == "title":
        return _plain_text(prop.get("title"))
    if prop_type == "unique_id":
        value = prop.get("unique_id")
        if not isinstance(value, Mapping):
            return None
        number = value.get("number")
        if not isinstance(number, int) or isinstance(number, bool):
            return None
        prefix = value.get("prefix")
        prefix_text = prefix if isinstance(prefix, str) and prefix else "lesson"
        return f"{prefix_text}-{number}"
    return None


def _select_name(prop: Any) -> str | None:
    if not isinstance(prop, Mapping) or prop.get("type") not in ("select", "status"):
        return None
    value = prop.get(prop["type"])
    if not isinstance(value, Mapping):
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_ROW_TEXT_CHARS:
        return None
    return name


def _multi_select_names(prop: Any) -> tuple[str, ...] | None:
    if not isinstance(prop, Mapping) or prop.get("type") != "multi_select":
        return None
    values = prop.get("multi_select")
    if not isinstance(values, list) or len(values) > MAX_ROW_LIST_ITEMS:
        return None
    names: list[str] = []
    for item in values:
        if not isinstance(item, Mapping):
            return None
        name = item.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > MAX_ROW_TEXT_CHARS:
            return None
        names.append(name)
    return tuple(names)


def _checkbox(prop: Any) -> bool | None:
    if not isinstance(prop, Mapping) or prop.get("type") != "checkbox":
        return None
    value = prop.get("checkbox")
    if type(value) is not bool:
        return None
    return value


def _is_supporting_ref(value: str) -> bool:
    """One canonical supporting ref: this repo's issue/PR, or a governance path."""
    if len(value) > MAX_ROW_TEXT_CHARS:
        return False
    if _SUPPORTING_REF.fullmatch(value) is not None:
        return True
    return value.startswith(_GOVERNANCE_PREFIXES)


def _supporting_source_links(prop: Any, primary: str | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Parse approved bounded supporting refs: (admitted, dropped).

    One URL per rich-text item, no free-form parsing. A missing property
    behaves exactly as today (legacy one-link rows). Malformed, foreign,
    duplicate, oversized, or over-cap refs are dropped and reported -- never
    admitted, and never voiding the lesson or its primary ref. Dropped
    entries are truncated to the row text bound so the evidence record
    itself stays within its finite validation.
    """
    if prop is None:
        return (), ()
    if not isinstance(prop, Mapping) or prop.get("type") != "rich_text":
        return (), ("<malformed-supporting-property>",)
    items = prop.get("rich_text")
    if not isinstance(items, list) or len(items) > MAX_ROW_LIST_ITEMS:
        return (), ("<oversized-supporting-list>",)
    seen: set[str] = {primary} if primary else set()
    valid: list[str] = []
    dropped: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            dropped.append("<malformed-supporting-item>")
            continue
        text = item.get("plain_text")
        if not isinstance(text, str):
            dropped.append("<malformed-supporting-item>")
            continue
        ref = text.strip()
        if not ref:
            continue
        # A link annotation (what Notion makes clickable) must agree with
        # the displayed text: a live row whose display text names one
        # canonical ref while its link target points elsewhere is a spoof
        # shape, so drop the item rather than admitting the display while
        # the UI links somewhere else. Real API responses carry the link
        # target as top-level `href` (and requests as nested `text.link`);
        # the pre-repair writer emitted a top-level `link` key, so all
        # three shapes are checked. Any present container that is malformed
        # or disagrees with the displayed ref drops the item.
        link_targets: list[str] = []
        malformed_link = False
        # Real API response field: `href` is always a string or null.
        href = item.get("href")
        if href is not None:
            if isinstance(href, str) and href.strip():
                link_targets.append(href.strip())
            else:
                malformed_link = True
        # Legacy mock/pre-repair-writer shape: top-level `link` object.
        legacy = item.get("link")
        if legacy is not None:
            if isinstance(legacy, Mapping) and isinstance(legacy.get("url"), str) and legacy["url"].strip():
                link_targets.append(legacy["url"].strip())
            else:
                malformed_link = True
        text_obj = item.get("text")
        if isinstance(text_obj, Mapping):
            nested = text_obj.get("link")
            if nested is not None:
                if isinstance(nested, Mapping) and isinstance(nested.get("url"), str) and nested["url"].strip():
                    link_targets.append(nested["url"].strip())
                else:
                    malformed_link = True
        if malformed_link or any(target != ref for target in link_targets):
            dropped.append(ref[:MAX_ROW_TEXT_CHARS])
            continue
        if len(valid) >= MAX_SUPPORTING_REFS:
            dropped.append(ref[:MAX_ROW_TEXT_CHARS])
            continue
        if ref in seen or not _is_supporting_ref(ref):
            dropped.append(ref[:MAX_ROW_TEXT_CHARS])
            continue
        seen.add(ref)
        valid.append(ref)
    return tuple(valid), tuple(dropped[:MAX_ROW_LIST_ITEMS])


def _github_source_link(prop: Any) -> str | None:
    if not isinstance(prop, Mapping) or prop.get("type") != "url":
        return None
    value = prop.get("url")
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if len(value) > MAX_ROW_TEXT_CHARS:
        return None
    # CKR6 full-database readback (2026-11-14): a `#` fragment names a
    # sub-resource of a page, not a canonical resource -- one live lesson's
    # primary was a pull-request review anchor (`.../pull/1858` plus a
    # `#pullrequestreview-...` fragment) and was admitted as CURRENT.
    # A review/comment anchor is not a canonical issue/PR resource, so it
    # is rejected here (UNVERIFIABLE) rather than admitted as the lesson's
    # provenance. Plain resource URLs are unaffected: blob-URL primaries
    # (relied on by an existing test) and governance-path primaries still
    # normalize as CURRENT.
    if (
        "#" in value or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return None

    if value.startswith(_GOVERNANCE_PREFIXES):
        # Keep the existing governed locations but require a path to a
        # resource, not just the directory prefix.
        return value if _has_source_segments(value.split("/")) else None

    github = "https://github.com/"
    if not value.startswith(github) or "?" in value or any(char.isspace() for char in value):
        return None
    segments = value.removeprefix(github).split("/")
    if len(segments) < 4 or not _has_source_segments(segments):
        return None
    owner, repo, kind, *resource = segments
    if _GITHUB_REPOSITORY.fullmatch(f"{owner}/{repo}") is None:
        return None

    # Validate shape only. This does not resolve a remote link or assert that
    # the linked material substantiates the lesson.
    if kind in {"issues", "pull"} and len(resource) == 1 and _GITHUB_NUMBER.fullmatch(resource[0]):
        return value
    if kind == "blob" and len(resource) >= 2:
        return value  # a ref and a file path
    if kind == "commit" and len(resource) == 1 and _GITHUB_COMMIT.fullmatch(resource[0]):
        return value
    if kind == "actions" and len(resource) in {2, 4}:
        if resource[0] == "runs" and _GITHUB_NUMBER.fullmatch(resource[1]):
            if len(resource) == 2 or (
                resource[2] == "job" and _GITHUB_NUMBER.fullmatch(resource[3])
            ):
                return value
    return None


def _has_source_segments(segments: Sequence[str]) -> bool:
    return all(segment.strip() and segment not in {".", ".."} for segment in segments)
