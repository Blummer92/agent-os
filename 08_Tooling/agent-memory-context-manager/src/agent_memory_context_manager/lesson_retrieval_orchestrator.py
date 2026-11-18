"""Finite CKR11 Lessons Learned retrieval orchestration (#2141).

This module makes CKR2's existing retrieval ledger executable without creating a
second selector, Notion client, credential path, or authority model.  It reuses
the existing CKR11 query/normalization helpers and the injected read-only
executor.  For Lessons Learned, the final provider-side broadening remains
strictly inside the canonical Lessons Learned data source; it never performs an
unbounded raw Notion workspace scan.
"""

from __future__ import annotations

from dataclasses import replace
from collections import Counter
import json
import re
from typing import Any, Callable, Mapping

from .coding_knowledge_selection import (
    CodingKnowledgeRequest,
    RetrievalEscalation,
    select_coding_knowledge,
)
from .lesson_activation_bridge import (
    MAX_RETRIEVAL_PAGES,
    MAX_RETRIEVAL_ROWS,
    LessonActivationError,
    SelectionBasis,
    _AREA_ECOSYSTEM,
    _AREA_PROPERTY,
    _LEARNING_TYPE_CAPABILITY,
    _LEARNING_TYPE_PROPERTY,
    _page_cursor,
    _bound_relevant_lessons,
    _extract_bounded_rows,
    build_filtered_query,
    build_known_reference_query,
    describe_selection_basis,
    known_lesson_numbers,
    normalize_lesson_row,
)
from .lesson_preflight import (
    MAX_LESSON_RECORDS,
    LessonPreflightResult,
    LessonRecordEvidence,
    LessonRetrievalStatus,
    consume_lesson_preflight,
    plan_lesson_preflight,
)

ReadExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]

_EXECUTABLE_STEPS = (
    RetrievalEscalation.KNOWN_REFERENCE,
    RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY,
    RetrievalEscalation.EXACT_NARROW_LOOKUP,
    RetrievalEscalation.WORKSPACE_SEARCH,
)
MAX_ESCALATION_STEPS = len(_EXECUTABLE_STEPS)
# Only the two relevance-filtered steps partition. The broad workspace-search
# step and exact-title fallback stay fail-closed on overflow, as before.
_PARTITIONED_STEPS = frozenset(
    {RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY, RetrievalEscalation.EXACT_NARROW_LOOKUP}
)
# Shared per-preflight read ceiling (previously derived as 4 steps x 5 pages = 20).
# Partitioned sequences spend from it. Offline replays, not live measurements:
# on a fixture consistent with the measured counts the cross-Area OR hit takes
# 21 reads and the longest miss path 30; an adversarial stress fixture reaches
# 31. Exhaustion fails closed, so 32 bounds refusal and does not guarantee
# complete retrieval. Per-sequence bounds (25 rows, 5 pages) and the 4-step
# per-preflight limit are unchanged; the 5-identity selection budget is a
# separate CKR2 limit.
MAX_PREFLIGHT_READS = 32
# Complete bounded snapshot bounds (CKR11 retrieval completeness replacement).
# The canonical read-only Notion adapter already bounds page_size at 100
# (_MAX_PAGE_SIZE), so one snapshot page asks for 100 rows. A snapshot is
# complete only when the provider reports has_more false within
# SNAPSHOT_MAX_PAGES pages and SNAPSHOT_MAX_ROWS rows; anything oversized,
# incomplete, or malformed fails closed with the existing reason codes and
# admits nothing.
SNAPSHOT_PAGE_SIZE = 100
SNAPSHOT_MAX_PAGES = 5
SNAPSHOT_MAX_ROWS = SNAPSHOT_PAGE_SIZE * SNAPSHOT_MAX_PAGES
_ROW_BOUND_MESSAGE = "paginated retrieval exceeded row bound"
_READ_BUDGET_MESSAGE = "preflight read budget exceeded"
_SANITIZED_PROVIDER_REASON_RE = re.compile(r"^notion-[a-z0-9-]{1,72}$")


# This is intentionally a closed vocabulary. Raw exception text (including
# provider-controlled payloads) is never a diagnostic value.
_INCOMPLETE_REASON_CODES = {
    "paginated retrieval exceeded row bound": "row-bound-exceeded",
    "paginated retrieval exceeded page bound": "page-bound-exceeded",
    "paginated retrieval missing next cursor": "missing-cursor",
    "repeated pagination cursor": "repeated-cursor",
    "read executor must return a mapping": "malformed-page",
    "read executor result is missing 'results'": "malformed-page",
    "read executor result contains non-mapping items": "malformed-page",
    "read executor result is missing 'has_more'": "malformed-pagination",
    "read executor returned a non-boolean has_more": "malformed-pagination",
    "read executor returned a malformed next_cursor": "malformed-pagination",
    _READ_BUDGET_MESSAGE: "read-budget-exceeded",
}


# Adapter-projected provider pagination failures carry the same incomplete
# classification as a direct-executor pagination failure (#4016 R-1): the
# composition projects a missing/malformed ``has_more`` into a finite
# provider code, and the retrieval result records the existing CKR11 reason
# instead of leaving the failure without an incomplete classification.
_NOTION_INCOMPLETE_REASON_CODES = {
    "notion-malformed-pagination": "malformed-pagination",
}


def _sanitized_read_failure_reason(exc: BaseException) -> str:
    """Keep only finite provider reason codes; never expose raw exception text."""

    if isinstance(exc, LessonActivationError):
        # Incomplete provider pagination is STOP evidence, not a candidate set.
        return "lesson-read-incomplete"
    if isinstance(exc, TimeoutError):
        return "lesson-read-timeout"
    if isinstance(exc, ConnectionError):
        return "lesson-read-connection-error"
    message = str(exc)
    if _SANITIZED_PROVIDER_REASON_RE.fullmatch(message):
        return message
    return "lesson-read-runtime-error"


def _unavailable_result(
    request: CodingKnowledgeRequest,
    exc: BaseException,
) -> LessonPreflightResult:
    result = consume_lesson_preflight(request, (), retrieval_available=False)
    reason = _sanitized_read_failure_reason(exc)
    if reason in result.selection_reason_codes:
        return result
    return replace(
        result,
        selection_reason_codes=result.selection_reason_codes + (reason,),
    )


def record_retrieval_attempt(
    request: CodingKnowledgeRequest,
    step: RetrievalEscalation,
) -> CodingKnowledgeRequest:
    """Return an immutable request copy recording one retrieval actually run."""
    if type(request) is not CodingKnowledgeRequest:
        raise TypeError("request must be a CodingKnowledgeRequest")
    if type(step) is not RetrievalEscalation:
        raise TypeError("step must be a RetrievalEscalation")
    if step not in _EXECUTABLE_STEPS:
        raise ValueError("only executable retrieval steps may be recorded")
    if step in request.attempted_retrieval:
        raise ValueError("retrieval step was already attempted")
    return replace(
        request,
        attempted_retrieval=request.attempted_retrieval + (step,),
    )


def build_escalation_query(
    request: CodingKnowledgeRequest,
    step: RetrievalEscalation,
) -> dict[str, Any]:
    """Build one distinct bounded provider query for the CKR2 escalation step."""
    if type(request) is not CodingKnowledgeRequest:
        raise TypeError("request must be a CodingKnowledgeRequest")
    if type(step) is not RetrievalEscalation:
        raise TypeError("step must be a RetrievalEscalation")

    if step is RetrievalEscalation.KNOWN_REFERENCE:
        return build_known_reference_query(request.known_knowledge_refs)

    if step is RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY:
        query = build_filtered_query(request)
        # CKR2 explicitly recognizes the "ckr6 mutation boundary" capability
        # and requires BOTH "ckr6" and "mutation" in lesson-owned guidance.
        # Its existing provider vocabulary maps that exact hint to Area=Testing.
        # Do not widen this first lookup with generic Python -> Automation /
        # Dashboard OR branches: that 25-row union was incomplete in the
        # 2026-11-15 live request (#3989). Query the controlled Testing area
        # first; if no qualifying lesson is found CKR2's existing escalation
        # ledger still handles subsequent lookups. All pagination and row caps
        # remain unchanged, including STOP when Testing itself overflows.
        hints = {item.strip().casefold() for item in request.capability_keywords}
        if "ckr6 mutation boundary" in hints:
            filters = query.get("filter")
            clauses = filters.get("and") if isinstance(filters, dict) else None
            if isinstance(clauses, list) and clauses:
                relevance = clauses[-1]
                testing = {"property": "Area", "select": {"equals": "Testing"}}
                if (
                    isinstance(relevance, dict)
                    and isinstance(relevance.get("or"), list)
                    and testing in relevance["or"]
                ):
                    query["filter"] = {"and": [*clauses[:-1], testing]}
        return query

    if step is RetrievalEscalation.EXACT_NARROW_LOOKUP:
        query = build_filtered_query(request)
        filter_value = query.get("filter")
        if isinstance(filter_value, dict):
            clauses = filter_value.get("and")
            if isinstance(clauses, list) and clauses:
                last = clauses[-1]
                if isinstance(last, dict):
                    alternatives = last.get("or")
                    if isinstance(alternatives, list) and alternatives:
                        # #2140 already orders clauses deterministically.  Use
                        # the first exact controlled-property clause rather than
                        # repeating the broader OR query.
                        narrowed = list(clauses)
                        narrowed[-1] = alternatives[0]
                        # The CKR6-specific first query already searched Testing.
                        # The second finite lookup must cover remaining controlled
                        # relevance clauses, not repeat the same Testing area.
                        # Preserve the existing 5-row and complete-cursor bounds.
                        hints = {
                            item.strip().casefold()
                            for item in request.capability_keywords
                        }
                        testing = {"property": "Area", "select": {"equals": "Testing"}}
                        remaining = [
                            clause for clause in alternatives if clause != testing
                        ]
                        if (
                            "ckr6 mutation boundary" in hints
                            and testing in alternatives
                            and remaining
                        ):
                            narrowed[-1] = (
                                remaining[0]
                                if len(remaining) == 1
                                else {"or": remaining}
                            )
                        query["filter"] = {"and": narrowed}
                        query["page_size"] = MAX_LESSON_RECORDS
                        return query

        # Sparse forced-material requests can legitimately have no mapped
        # relevance clause.  The exact fallback searches the controlled title
        # for the exact task reference rather than reissuing the filtered read.
        broad_request = replace(
            request,
            ecosystem_hints=(),
            language_hints=(),
            library_hints=(),
            capability_keywords=(),
            target_path_hints=(),
            known_knowledge_refs=(),
        )
        query = build_filtered_query(broad_request)
        query["filter"]["and"].append(
            {
                "property": "Lesson Learned",
                "title": {"contains": request.task_reference},
            }
        )
        query["page_size"] = MAX_LESSON_RECORDS
        return query

    if step is RetrievalEscalation.WORKSPACE_SEARCH:
        # CKR2's last bounded search slot is realized conservatively for the
        # Lessons Learned provider by broadening only inside the canonical data
        # source.  A raw workspace-wide Notion search would create the second
        # retrieval mechanism explicitly excluded by #2141.
        broad_request = replace(
            request,
            ecosystem_hints=(),
            language_hints=(),
            library_hints=(),
            capability_keywords=(),
            target_path_hints=(),
            known_knowledge_refs=(),
        )
        query = build_filtered_query(broad_request)
        # The canonical snapshot query reads at the adapter's maximum page
        # size; completeness is enforced by the cursor chain, not the window.
        query["page_size"] = SNAPSHOT_PAGE_SIZE
        return query

    raise ValueError("manual-review and none do not execute provider queries")


def _select_equals(clause: Any, property_name: str) -> bool:
    return (
        isinstance(clause, dict)
        and clause.get("property") == property_name
        and isinstance(clause.get("select"), dict)
        and isinstance(clause["select"].get("equals"), str)
    )


def _query_key(query: Mapping[str, Any]) -> str:
    filter_value = query.get("filter")
    clauses = filter_value.get("and") if isinstance(filter_value, dict) else None
    items = clauses if isinstance(clauses, list) else [filter_value]
    return json.dumps(sorted(json.dumps(c, sort_keys=True) for c in items))


def _partition_queries(query: Mapping[str, Any], *, crossed: bool) -> tuple[list[dict[str, Any]], bool]:
    """Split an overflowing query into exact sub-queries over the controlled vocabularies.

    Level 1 gives each OR alternative its own sequence. Level 2 crosses a single
    Area (or Learning Type) clause with every value of the other controlled
    vocabulary, enumerated from the normalizer's own tables, never from
    observed counts. Anything else returns no partition and the caller fails
    closed. Sub-query results are unioned by the existing full-record dedup.
    """
    filter_value = query.get("filter")
    clauses = filter_value.get("and") if isinstance(filter_value, dict) else None
    if not isinstance(clauses, list) or not clauses:
        return [], crossed
    head, last = clauses[:-1], clauses[-1]

    def with_last(*tail: Any) -> dict[str, Any]:
        return {**query, "filter": {"and": [*head, *tail]}}

    if (
        isinstance(last, dict)
        and isinstance(last.get("or"), list)
        and len(last["or"]) == 1
    ):
        # A single-alternative OR is that alternative.
        last = last["or"][0]
    if isinstance(last, dict) and isinstance(last.get("or"), list):
        alternatives = last["or"]
        if len(alternatives) > 1 and not crossed:
            return [with_last(item) for item in alternatives], False
        return [], crossed
    if crossed:
        return [], crossed
    if _select_equals(last, _AREA_PROPERTY):
        return [
            with_last(
                last,
                {"property": _LEARNING_TYPE_PROPERTY, "select": {"equals": value}},
            )
            for value in sorted(_LEARNING_TYPE_CAPABILITY)
        ], True
    if _select_equals(last, _LEARNING_TYPE_PROPERTY):
        return [
            with_last(
                last,
                {"property": _AREA_PROPERTY, "select": {"equals": value}},
            )
            for value in sorted(_AREA_ECOSYSTEM)
        ], True
    return [], crossed



def _terminal_query_bucket(query: Mapping[str, Any]) -> str:
    """Finite internal query-shape diagnostic; never echo provider or caller text."""
    filt = query.get("filter")
    if not isinstance(filt, dict):
        return "unobserved"
    if isinstance(filt.get("or"), list):
        return "known-reference"
    clauses = filt.get("and")
    if not isinstance(clauses, list) or len(clauses) < 2:
        return "unobserved"
    if len(clauses) == 2:
        return "workspace"
    last = clauses[-1]
    if not isinstance(last, dict):
        return "unobserved"
    if isinstance(last.get("or"), list):
        return "broad-or"
    if last.get("property") == "Lesson Learned" and isinstance(last.get("title"), dict):
        return "title-fallback"

    def selected(clause: object, prop: str, vocabulary: Mapping[str, str]) -> str | None:
        if not isinstance(clause, dict) or clause.get("property") != prop:
            return None
        field = clause.get("select")
        value = field.get("equals") if isinstance(field, dict) else None
        return value if type(value) is str and value in vocabulary else None

    if len(clauses) == 4:
        # Partitions can be refined Area-first or Learning Type-first.
        area = selected(clauses[-2], _AREA_PROPERTY, _AREA_ECOSYSTEM)
        kind = selected(last, _LEARNING_TYPE_PROPERTY, _LEARNING_TYPE_CAPABILITY)
        if area is None or kind is None:
            area = selected(last, _AREA_PROPERTY, _AREA_ECOSYSTEM)
            kind = selected(clauses[-2], _LEARNING_TYPE_PROPERTY, _LEARNING_TYPE_CAPABILITY)
        if area is not None and kind is not None:
            return "area:" + area + "/type:" + kind
    if len(clauses) == 3:
        area = selected(last, _AREA_PROPERTY, _AREA_ECOSYSTEM)
        if area is not None:
            return "area:" + area
        kind = selected(last, _LEARNING_TYPE_PROPERTY, _LEARNING_TYPE_CAPABILITY)
        if kind is not None:
            return "type:" + kind
    return "unobserved"


def _finite_terminal_page_signature(
    raw: object, *, page_size: int
) -> dict[str, object] | None:
    """Classify finite, provider-response-only page metadata (#4011).

    Buckets are relative to the regime's page size: the legacy 25-row
    vocabulary for read_sequence, the 100-row snapshot bound for
    read_snapshot. A normal 100-row snapshot page is '100', not 'over-25',
    so it can no longer be confused with an oversized page.
    """
    if not isinstance(raw, Mapping):
        return None
    results = raw.get("results")
    if isinstance(results, list):
        bucket = (
            f"0-{page_size - 1}" if len(results) < page_size
            else str(page_size) if len(results) == page_size
            else f"over-{page_size}"
        )
    else:
        bucket = "unobserved"
    # Missing metadata is invalid, just like a non-boolean completion flag.
    has_more = raw.get("has_more")
    cursor = raw.get("next_cursor")
    return {
        "terminal_page_row_count_bucket": bucket,
        "terminal_page_has_more": (
            "true" if has_more is True
            else "false" if has_more is False
            else "invalid"
        ),
        "terminal_page_cursor_present": (
            isinstance(cursor, str) and bool(cursor.strip())
        ),
    }


def orchestrate_lesson_retrieval(
    request: CodingKnowledgeRequest,
    *,
    execute_read: ReadExecutor | None,
) -> LessonPreflightResult:
    """Walk CKR2's existing retrieval ledger within a strict finite bound."""
    if type(request) is not CodingKnowledgeRequest:
        raise TypeError("request must be a CodingKnowledgeRequest")

    plan = plan_lesson_preflight(request)
    if not plan.retrieval_required:
        return consume_lesson_preflight(request, ())
    if execute_read is None:
        return consume_lesson_preflight(request, (), retrieval_available=False)

    current_request = request
    accumulated: list[LessonRecordEvidence] = []
    result: LessonPreflightResult | None = None
    observed_rows = 0
    normalized_rows = 0
    skipped = Counter()
    read_count = 0
    incomplete_reason_code: str | None = None
    terminal_query_bucket = "unobserved"
    terminal_page_signature: dict[str, object] | None = None

    def with_diagnostics(
        value: LessonPreflightResult, basis: SelectionBasis | None = None
    ) -> LessonPreflightResult:
        # Only finite counts and static normalization reason names; no raw rows.
        diagnostics = {
            "read_count": read_count,
            "observed_rows": observed_rows,
            "normalized_rows": normalized_rows,
            "skipped_rows": sum(skipped.values()),
            "missing_identity_rows": skipped["missing-stable-identity"],
            "missing_revision_rows": skipped["missing-verified-revision"],
            "missing_source_guidance_rows": skipped["missing-activation-guidance"],
            "ambiguous_metadata_rows": sum(count for reason, count in skipped.items() if reason.startswith("ambiguous-")),
            # Complete skip accounting: every normalization skip reason, named.
            # Without this, reasons outside the four legacy buckets (e.g.
            # "oversized-or-malformed-field") vanish from diagnostics while
            # skipped_rows still counts them.
            "skip_reasons": {reason: skipped[reason] for reason in sorted(skipped)},
            "candidate_count": value.candidate_count,
        }
        if basis is not None:
            # PR-1 (observational): HOW the lessons were chosen. Never read
            # back by selection, status mapping or admission.
            diagnostics["selection_basis"] = basis.basis
            diagnostics["best_bucket_tied_identities"] = basis.tied_identities
        if incomplete_reason_code is not None:
            diagnostics["incomplete_reason_code"] = incomplete_reason_code
            diagnostics["terminal_query_bucket"] = terminal_query_bucket
            if terminal_page_signature is not None:
                diagnostics.update(terminal_page_signature)
        return replace(value, retrieval_diagnostics=diagnostics)

    def read_sequence(query: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        # One bounded sequence: at most MAX_RETRIEVAL_PAGES pages and
        # MAX_RETRIEVAL_ROWS rows, following cursors as before (#3973).
        nonlocal read_count, terminal_query_bucket, terminal_page_signature
        rows: list[Mapping[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str | None] = set()
        for _page_index in range(MAX_RETRIEVAL_PAGES):
            if cursor in seen_cursors:
                raise LessonActivationError("repeated pagination cursor")
            seen_cursors.add(cursor)
            if read_count >= MAX_PREFLIGHT_READS:
                raise LessonActivationError(_READ_BUDGET_MESSAGE)
            page_query = query if cursor is None else {**query, "start_cursor": cursor}
            # Name only a query that is actually sent: a budget stop above leaves
            # the bucket of the last issued query, never the one it refused.
            terminal_query_bucket = _terminal_query_bucket(query)
            # Discard stale metadata when the next provider call fails.
            terminal_page_signature = None
            raw = execute_read(page_query)
            read_count += 1
            terminal_page_signature = _finite_terminal_page_signature(
                raw, page_size=MAX_RETRIEVAL_ROWS
            )
            page_rows = _extract_bounded_rows(raw)
            # Reject an oversized supplied page instead of truncating it.
            if len(raw["results"]) > MAX_RETRIEVAL_ROWS - len(rows):
                raise LessonActivationError(_ROW_BOUND_MESSAGE)
            rows.extend(page_rows)
            has_more, next_cursor = _page_cursor(raw)
            if not has_more:
                return rows
            if len(rows) >= MAX_RETRIEVAL_ROWS:
                raise LessonActivationError(_ROW_BOUND_MESSAGE)
            if next_cursor is None:
                raise LessonActivationError("paginated retrieval missing next cursor")
            cursor = next_cursor
        raise LessonActivationError("paginated retrieval exceeded page bound")

    def read_step(
        query: Mapping[str, Any],
        *,
        crossed: bool,
        partitionable: bool,
        seen: set[str] | None = None,
    ) -> list[Mapping[str, Any]]:
        # A row-bound overflow is never truncated or selected from. When the
        # step is partitionable, the same query is re-read as exact controlled
        # sub-queries that each keep the unchanged 25-row/5-page bound. Any
        # sub-query that still overflows, or the shared read budget running
        # out, fails the whole step closed with no partial population.
        seen = set() if seen is None else seen
        key = _query_key(query)
        if key in seen:
            # The same exact sub-query (for example Area=A and Type=T reached
            # from two alternatives) is read once; its rows are already merged.
            return []
        seen.add(key)
        try:
            return read_sequence(query)
        except LessonActivationError as exc:
            if not partitionable or str(exc) != _ROW_BOUND_MESSAGE:
                raise
            parts, parts_crossed = _partition_queries(query, crossed=crossed)
            if not parts:
                raise
            merged: list[Mapping[str, Any]] = []
            for part in parts:
                merged.extend(
                    read_step(part, crossed=parts_crossed, partitionable=True, seen=seen)
                )
            return merged

    def read_snapshot(query: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        # One complete bounded snapshot of the canonical data source. Only a
        # complete snapshot is returned; a partial one never reaches
        # normalization, the CKR2 bound, or selection. Cursor discipline and
        # the shared read budget are unchanged from read_sequence; page and
        # row bounds are the snapshot's own.
        nonlocal read_count, terminal_query_bucket, terminal_page_signature
        rows: list[Mapping[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str | None] = set()
        for _page_index in range(SNAPSHOT_MAX_PAGES):
            if cursor in seen_cursors:
                raise LessonActivationError("repeated pagination cursor")
            seen_cursors.add(cursor)
            if read_count >= MAX_PREFLIGHT_READS:
                raise LessonActivationError(_READ_BUDGET_MESSAGE)
            page_query = query if cursor is None else {**query, "start_cursor": cursor}
            terminal_query_bucket = _terminal_query_bucket(query)
            # Discard stale metadata when the next provider call fails.
            terminal_page_signature = None
            raw = execute_read(page_query)
            read_count += 1
            terminal_page_signature = _finite_terminal_page_signature(
                raw, page_size=SNAPSHOT_PAGE_SIZE
            )
            if not isinstance(raw, Mapping):
                raise LessonActivationError("read executor must return a mapping")
            results = raw.get("results")
            if not isinstance(results, list):
                raise LessonActivationError("read executor result is missing 'results'")
            # Reject an oversized supplied page instead of truncating it.
            if len(results) > SNAPSHOT_PAGE_SIZE:
                raise LessonActivationError(_ROW_BOUND_MESSAGE)
            # A page is admitted only whole: any non-mapping item makes the
            # page malformed, never silently filtered.
            if not all(isinstance(item, Mapping) for item in results):
                raise LessonActivationError(
                    "read executor result contains non-mapping items"
                )
            rows.extend(results)
            has_more, next_cursor = _page_cursor(raw)
            if not has_more:
                return rows
            if len(rows) >= SNAPSHOT_MAX_ROWS:
                raise LessonActivationError(_ROW_BOUND_MESSAGE)
            if next_cursor is None:
                raise LessonActivationError("paginated retrieval missing next cursor")
            cursor = next_cursor
        raise LessonActivationError("paginated retrieval exceeded page bound")

    def accumulate(rows: list[Mapping[str, Any]]) -> None:
        # R1 (#2425): accumulate keyed by full record equality, unchanged.
        nonlocal observed_rows, normalized_rows
        observed_rows += len(rows)
        for row in rows:
            # Invalid rows must not crash a fully retrieved corpus or leak
            # unchecked candidates into CKR2.
            try:
                normalized = normalize_lesson_row(row)
            except (TypeError, ValueError):
                skipped["oversized-or-malformed-field"] += 1
                continue
            if isinstance(normalized, LessonRecordEvidence):
                normalized_rows += 1
                if normalized not in accumulated:
                    accumulated.append(normalized)
            else:
                skipped[normalized.reason] += 1

    try:
        if known_lesson_numbers(request.known_knowledge_refs):
            # Explicitly referenced lessons keep their exact identity lookup:
            # bounded by the number of referenced IDs, complete by identity.
            known_query = build_known_reference_query(request.known_knowledge_refs)
            accumulate(
                read_step(known_query, crossed=False, partitionable=False)
            )
            current_request = record_retrieval_attempt(
                current_request, RetrievalEscalation.KNOWN_REFERENCE
            )
            result = consume_lesson_preflight(
                current_request, _bound_relevant_lessons(current_request, accumulated)
            )
            if result.lesson_retrieval_status is not LessonRetrievalStatus.INSUFFICIENT:
                return with_diagnostics(
                    result,
                    describe_selection_basis(
                        current_request, accumulated, identity_route=True
                    ),
                )
        # Relevance retrieval is one complete bounded snapshot of the
        # canonical data source, replacing the fragmented filtered/exact/
        # workspace cascade: normalization, dedup, the CKR2 bound and
        # selection all see the same complete corpus.
        snapshot_query = build_escalation_query(
            current_request, RetrievalEscalation.WORKSPACE_SEARCH
        )
        snapshot_rows = read_snapshot(snapshot_query)
        current_request = record_retrieval_attempt(
            current_request, RetrievalEscalation.WORKSPACE_SEARCH
        )
    except (ConnectionError, TimeoutError, RuntimeError, LessonActivationError) as exc:
        # No partial page population may reach CKR2 or admit a repair.
        if isinstance(exc, LessonActivationError):
            incomplete_reason_code = _INCOMPLETE_REASON_CODES.get(
                str(exc), "unknown-incomplete"
            )
        elif str(exc) in _NOTION_INCOMPLETE_REASON_CODES:
            incomplete_reason_code = _NOTION_INCOMPLETE_REASON_CODES[str(exc)]
        return with_diagnostics(_unavailable_result(current_request, exc))

    accumulate(snapshot_rows)
    result = consume_lesson_preflight(
        current_request, _bound_relevant_lessons(current_request, accumulated)
    )
    if (
        result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
        and result.retrieval_escalation is not RetrievalEscalation.MANUAL_REVIEW
    ):
        # A complete snapshot leaves no further retrieval step: the honest
        # next recommendation is manual review, not a cascade re-read.
        result = replace(result, retrieval_escalation=RetrievalEscalation.MANUAL_REVIEW)
    return with_diagnostics(
        result,
        describe_selection_basis(current_request, accumulated, identity_route=False),
    )


__all__ = [
    "MAX_ESCALATION_STEPS",
    "MAX_PREFLIGHT_READS",
    "build_escalation_query",
    "orchestrate_lesson_retrieval",
    "record_retrieval_attempt",
]

