"""Machine-consumable issue-start CKR6 preflight for ChatGPT Agent OS missions (#2247).

This is an additive execution-interface seam over the existing CKR6/CKR11
retrieval path. It creates no lesson selector, Notion client, authority model,
or repository-write authority.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from agent_memory_context_manager.coding_knowledge_selection import CodingKnowledgeRequest
from agent_memory_context_manager.lesson_activation_bridge import (
    MAX_RETRIEVAL_ROWS,
    LessonActivationSkip,
    known_lesson_numbers,
    normalize_lesson_row,
)
from agent_memory_context_manager.lesson_preflight import MAX_LESSON_RECORDS, LessonRetrievalStatus
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


def _requested_lesson_skips(
    raw: Mapping[str, Any], wanted: frozenset[str],
    skips: list[dict[str, str]], seen_ids: set[str],
) -> None:
    """Observe only bounded, explicitly requested normalization skips.

    No raw Notion row is retained. The canonical executor still makes all
    retrieval and admission decisions. This path is diagnostic only.
    """
    rows = raw.get("results")
    if not isinstance(rows, list) or not wanted or len(skips) >= MAX_LESSON_RECORDS:
        return
    mapped_rows = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        mapped_rows += 1
        if mapped_rows > MAX_RETRIEVAL_ROWS:
            break
        normalized = normalize_lesson_row(row)
        if not isinstance(normalized, LessonActivationSkip):
            continue
        lesson_id = normalized.lesson_id
        if lesson_id not in wanted or lesson_id in seen_ids:
            continue
        revision = row.get("last_edited_time")
        # A diagnostic revision is never an identity/authority token.
        if (not isinstance(revision, str) or not 1 <= len(revision) <= 40
                or any(char not in "0123456789-:.+TZ" for char in revision)):
            revision = "unknown"
        seen_ids.add(lesson_id)
        skips.append({
            "lesson_id": lesson_id,
            "source_revision": revision,
            "currentness": "not-activatable",
            "provenance": "normalization-skip:" + normalized.reason,
        })
        if len(skips) >= MAX_LESSON_RECORDS:
            break


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
    wanted = frozenset(f"LL-{n}" for n in known_lesson_numbers(known_knowledge_refs))
    skipped: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    bounded_read = execute_read
    if execute_read is not None and wanted:
        def bounded_read(query: Mapping[str, Any]) -> Mapping[str, Any]:
            raw = execute_read(query)
            if isinstance(raw, Mapping):
                _requested_lesson_skips(raw, wanted, skipped, seen_ids)
            return raw

    result = orchestrate_lesson_retrieval(request, execute_read=bounded_read)
    # Rejected eligible candidates take precedence. Never duplicate a selected
    # ID in the rejection list or expand the existing five-record output cap.
    rejected = [dict(item) for item in result.rejected_candidate_provenance][:MAX_LESSON_RECORDS]
    excluded_ids = set(result.selected_lesson_ids)
    excluded_ids.update(item["lesson_id"] for item in rejected)
    rejected.extend(item for item in skipped if item["lesson_id"] not in excluded_ids)
    rejected = rejected[:MAX_LESSON_RECORDS]
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
        "rejected_candidate_provenance": rejected,
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
