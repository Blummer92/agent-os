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
from typing import Any, Callable, Mapping

from .coding_knowledge_selection import (
    CodingKnowledgeRequest,
    RetrievalEscalation,
    select_coding_knowledge,
)
from .lesson_activation_bridge import (
    MAX_RETRIEVAL_ROWS,
    _bound_relevant_lessons,
    _extract_bounded_rows,
    build_filtered_query,
    build_known_reference_query,
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
        return build_filtered_query(request)

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
        query["page_size"] = MAX_RETRIEVAL_ROWS
        return query

    raise ValueError("manual-review and none do not execute provider queries")


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

    for _ in range(MAX_ESCALATION_STEPS):
        step = select_coding_knowledge(
            current_request,
            (),
        ).recommended_escalation
        if step in {RetrievalEscalation.NONE, RetrievalEscalation.MANUAL_REVIEW}:
            if result is not None:
                return result
            return consume_lesson_preflight(current_request, ())

        query = build_escalation_query(current_request, step)
        try:
            raw = execute_read(query)
        except (ConnectionError, TimeoutError, RuntimeError):
            return consume_lesson_preflight(
                current_request,
                (),
                retrieval_available=False,
            )

        current_request = record_retrieval_attempt(current_request, step)
        rows = _extract_bounded_rows(raw)
        for row in rows:
            normalized = normalize_lesson_row(row)
            if isinstance(normalized, LessonRecordEvidence):
                accumulated.append(normalized)

        bounded = _bound_relevant_lessons(current_request, accumulated)
        result = consume_lesson_preflight(current_request, bounded)
        if result.lesson_retrieval_status is not LessonRetrievalStatus.INSUFFICIENT:
            return result
        if result.retrieval_escalation is RetrievalEscalation.MANUAL_REVIEW:
            return result

    if result is None:
        raise RuntimeError("lesson retrieval bound was reached without a result")
    return result


__all__ = [
    "MAX_ESCALATION_STEPS",
    "build_escalation_query",
    "orchestrate_lesson_retrieval",
    "record_retrieval_attempt",
]
