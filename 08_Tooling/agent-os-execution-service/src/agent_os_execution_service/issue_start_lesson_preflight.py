"""Machine-consumable issue-start CKR6 preflight for ChatGPT Agent OS missions (#2247).

This is an additive execution-interface seam over the existing CKR6/CKR11
retrieval path. It creates no lesson selector, Notion client, authority model,
or repository-write authority.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from agent_memory_context_manager.coding_knowledge_selection import CodingKnowledgeRequest
from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus
from agent_memory_context_manager.lesson_retrieval_orchestrator import orchestrate_lesson_retrieval

ReadExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]

_ADMISSIBLE = frozenset(
    {
        LessonRetrievalStatus.NOT_NEEDED,
        LessonRetrievalStatus.SUFFICIENT,
        LessonRetrievalStatus.UNAVAILABLE_SAFE_FALLBACK,
    }
)


def selected_lesson_provenance(result: Any) -> list[dict[str, object]]:
    """Exact identity + revision + selection reasons for each selected lesson.

    #3418: a later application receipt is valid only against these exact
    (lesson_id, source_revision) pairs, so retrieval alone never proves use.
    """
    selection = getattr(result, "selection", None)
    if selection is None:
        return []
    return [
        {
            "lesson_id": item.candidate.knowledge_id,
            "source_revision": item.candidate.source_revision,
            "selection_reason_codes": list(item.reason_codes),
        }
        for item in selection.selected
    ]


def activate_issue_start_lesson_preflight(
    *,
    repository: str,
    issue_number: int,
    task_reference: str,
    ecosystem_hints: tuple[str, ...] = (),
    language_hints: tuple[str, ...] = (),
    library_hints: tuple[str, ...] = (),
    capability_keywords: tuple[str, ...] = (),
    target_path_hints: tuple[str, ...] = (),
    canonical_rule_refs: tuple[str, ...] = (),
    known_knowledge_refs: tuple[str, ...] = (),
    specialized_knowledge_required: bool | None = None,
    execute_read: ReadExecutor | None = None,
) -> dict[str, object]:
    """Resolve CKR6 before the first substantial Agent OS hypothesis.

    ``substantial_hypothesis_admissible`` is an execution-order gate only. It
    never authorizes repository mutation, merge, issue closure, or any external
    effect. Current GitHub governance and authorization remain authoritative.
    """
    if type(repository) is not str or "/" not in repository or not repository.strip():
        raise ValueError("repository must use bounded owner/name syntax")
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("issue_number must be a positive built-in integer")
    if type(task_reference) is not str or not task_reference.strip():
        raise ValueError("task_reference must be non-empty exact text")

    # #2780: ordinary issue scope metadata is matching context, not proof
    # that advisory Lessons Learned are material. Preserve explicit caller
    # decisions and use only deterministic issue-start positive signals when
    # the tri-state was omitted.
    issue_start_materiality = specialized_knowledge_required
    if issue_start_materiality is None:
        issue_start_materiality = bool(known_knowledge_refs or library_hints)
        # #3418/#2425: the #2780 default is unchanged, but an inferred decision
        # is reported as inferred so omitted materiality never silently reads
        # as a caller-asserted not-needed.
        materiality_source = "inferred-" + ("material" if issue_start_materiality else "not-material")
    else:
        materiality_source = "caller-asserted-" + ("material" if issue_start_materiality else "not-material")

    request = CodingKnowledgeRequest(
        task_reference=task_reference,
        ecosystem_hints=ecosystem_hints,
        language_hints=language_hints,
        library_hints=library_hints,
        capability_keywords=capability_keywords,
        target_path_hints=target_path_hints,
        canonical_rule_refs=canonical_rule_refs,
        known_knowledge_refs=known_knowledge_refs,
        specialized_knowledge_required=issue_start_materiality,
    )
    result = orchestrate_lesson_retrieval(request, execute_read=execute_read)
    admissible = result.lesson_retrieval_status in _ADMISSIBLE
    handoff = dict(result.handoff_projection)
    handoff["known_facts"] = [
        *handoff.get("known_facts", []), "coding-knowledge-materiality:" + materiality_source,
    ]
    return {
        "repository": repository,
        "issue_number": issue_number,
        "lesson_retrieval_status": result.lesson_retrieval_status.value,
        "selected_lesson_ids": list(result.selected_lesson_ids),
        "selected_lessons": selected_lesson_provenance(result),
        "rejected_candidate_provenance": [dict(item) for item in result.rejected_candidate_provenance],
        "materiality_source": materiality_source,
        "selection_reason_codes": list(result.selection_reason_codes),
        "canonical_github_refs": list(result.canonical_github_refs),
        "knowledge_refs": list(result.knowledge_refs),
        "handoff_projection": handoff,
        "substantial_hypothesis_admissible": admissible,
        "preflight_resolved": True,
        "source_authority": "advisory-only",
        "github_writes_authorized": False,
        "execution_authorized": False,
        "side_effects_performed": False,
    }


__all__ = ["activate_issue_start_lesson_preflight", "selected_lesson_provenance"]
