"""Offline, authority-free writer relevance qualification using canonical CKR2.

A proposed catalog lesson is not evidence of live Notion eligibility. This
pre-publication check projects ONLY reviewed writer fields through the existing
CKR11 normalizer, then measures expected positives and hard negatives with
the existing CKR2 selector. Do not use its output for write or gate authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .catalog import entry_for, lesson_for


@dataclass(frozen=True)
class RelevanceReview:
    qualified: bool
    reason_codes: tuple[str, ...]
    positive_hits: int
    positive_total: int
    hard_negative_false_positives: int
    hard_negative_total: int
    publication_authorized: bool = False
    activation_authorized: bool = False


def _simulated_readback(values: Mapping[str, object]) -> dict[str, object]:
    """Project reviewed writer properties into Notion read shapes, offline only."""
    from .catalog import WRITABLE_TYPES
    props: dict[str, object] = {
        "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": 999999999}},
        # Synthetic eligibility inputs are NEVER evidence of actual owner activation.
        "Status": {"type": "select", "select": {"name": "New"}},
        "Surface Before Work?": {"type": "checkbox", "checkbox": True},
        # Notion returns an empty multi_select property even when no option is set.
        "Applies To": {"type": "multi_select", "multi_select": []},
    }
    for name, value in values.items():
        kind = WRITABLE_TYPES[name]
        if kind in ("title", "rich_text"):
            if name == "Supporting Source Links":
                items = [{"type": "text", "plain_text": ref} for ref in value]
            else:
                items = [{"type": "text", "plain_text": value}]
            props[name] = {"type": kind, kind: items}
        elif kind == "select":
            props[name] = {"type": "select", "select": {"name": value}}
        elif kind == "multi_select":
            props[name] = {"type": kind, kind: [{"name": item} for item in value]}
        elif kind == "url":
            props[name] = {"type": "url", "url": value}
    return {"object": "page", "last_edited_time": "2026-11-23T00:00:00.000Z", "properties": props}


def qualify_reviewed_create(
    request_id: str,
    *,
    positive_requests: tuple[Any, ...],
    hard_negative_requests: tuple[Any, ...],
) -> RelevanceReview:
    """Evaluate an exact reviewed create entry; never inspect or write Notion.

    Every reviewed test case must be a genuine typed CodingKnowledgeRequest.
    A positive must select this lesson. A negative must select no lesson.
    Refuse missing metadata, missing tests, or oversized tests. This check is
    advisory review evidence: the synthetic Status/Surface inputs are not
    assertions about the real Notion page or its activation.
    """
    from agent_memory_context_manager.coding_knowledge_selection import (
        CodingKnowledgeRequest, SufficiencyStatus, select_coding_knowledge,
    )
    from agent_memory_context_manager.lesson_activation_bridge import (
        LessonActivationSkip, _as_selection_candidate, normalize_lesson_row,
    )

    entry = entry_for(request_id)
    values = lesson_for(request_id)
    if entry["target_lesson_id"] is not None:
        return RelevanceReview(False, ("create-entry-required",), 0, 0, 0, 0)
    if (
        not positive_requests or not hard_negative_requests
        or len(positive_requests) > 8 or len(hard_negative_requests) > 8
        or type(positive_requests) is not tuple or type(hard_negative_requests) is not tuple
        or any(type(req) is not CodingKnowledgeRequest for req in positive_requests + hard_negative_requests)
    ):
        return RelevanceReview(False, ("bounded-review-scenarios-required",), 0, 0, 0, 0)
    if not {"Area", "Learning Type", "Source Link"} <= set(values):
        return RelevanceReview(False, ("writer-relevance-metadata-incomplete",), 0, 0, 0, 0)

    normalized = normalize_lesson_row(_simulated_readback(values))
    if isinstance(normalized, LessonActivationSkip):
        return RelevanceReview(False, ("writer-ckr11-normalization-ineligible",), 0, 0, 0, 0)
    candidate = _as_selection_candidate(normalized)
    # A canonical source may not be borrowed from the task's rule references.
    if not candidate.canonical_github_refs:
        return RelevanceReview(False, ("lesson-owned-provenance-required",), 0, 0, 0, 0)

    def selected(req: CodingKnowledgeRequest) -> bool:
        result = select_coding_knowledge(req, (candidate,))
        return (
            result.sufficiency_status is SufficiencyStatus.SUFFICIENT
            and result.knowledge_refs == (candidate.knowledge_id,)
        )

    positive_hits = sum(selected(req) for req in positive_requests)
    false_positives = sum(selected(req) for req in hard_negative_requests)
    reasons = []
    if positive_hits != len(positive_requests):
        reasons.append("expected-task-not-selected")
    if false_positives:
        reasons.append("unrelated-task-false-positive")
    return RelevanceReview(
        not reasons, tuple(reasons), positive_hits, len(positive_requests),
        false_positives, len(hard_negative_requests),
    )
