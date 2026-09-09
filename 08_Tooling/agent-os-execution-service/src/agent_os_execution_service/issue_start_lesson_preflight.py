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

    request = CodingKnowledgeRequest(
        task_reference=task_reference,
        ecosystem_hints=ecosystem_hints,
        language_hints=language_hints,
        library_hints=library_hints,
        capability_keywords=capability_keywords,
        target_path_hints=target_path_hints,
        canonical_rule_refs=canonical_rule_refs,
        known_knowledge_refs=known_knowledge_refs,
        specialized_knowledge_required=specialized_knowledge_required,
    )
    result = orchestrate_lesson_retrieval(request, execute_read=execute_read)
    admissible = result.lesson_retrieval_status in _ADMISSIBLE
    return {
        "repository": repository,
        "issue_number": issue_number,
        "lesson_retrieval_status": result.lesson_retrieval_status.value,
        "selected_lesson_ids": list(result.selected_lesson_ids),
        "selection_reason_codes": list(result.selection_reason_codes),
        "canonical_github_refs": list(result.canonical_github_refs),
        "knowledge_refs": list(result.knowledge_refs),
        "handoff_projection": result.handoff_projection,
        "substantial_hypothesis_admissible": admissible,
        "preflight_resolved": True,
        "source_authority": "advisory-only",
        "github_writes_authorized": False,
        "execution_authorized": False,
        "side_effects_performed": False,
    }


__all__ = ["activate_issue_start_lesson_preflight"]
