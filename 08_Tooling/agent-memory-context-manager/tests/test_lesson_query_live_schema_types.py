"""#3032: every CKR6 provider filter clause must match the live property type.

Notion rejects a filter whose type does not match the property type with HTTP
400. The live Lessons Learned data source
(collection://2dfd0def-fa42-4c61-992e-c977a1fcaaf4, read 2026-09-28) declares
``Status`` as ``select`` and ``Lesson ID`` as an auto-increment ``unique_id``;
the query previously emitted ``status`` and ``rich_text`` filters for them.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from agent_memory_context_manager import (
    CodingKnowledgeRequest,
    LessonActivationError,
    build_filtered_query,
    build_known_reference_query,
)
from agent_memory_context_manager.lesson_activation_bridge import known_lesson_numbers
from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    build_escalation_query,
    orchestrate_lesson_retrieval,
)
from agent_memory_context_manager.coding_knowledge_selection import RetrievalEscalation

# Filter key per live property type (Notion data source query API).
LIVE_FILTER_TYPE = {
    "Lesson ID": "unique_id",
    "Lesson Learned": "title",
    "Status": "select",
    "Surface Before Work?": "checkbox",
    "Area": "select",
    "Applies To": "multi_select",
    "Learning Type": "select",
}


def _clauses(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        if "property" in node:
            yield node
        for key in ("and", "or"):
            for child in node.get(key, ()):
                yield from _clauses(child)


def _assert_live_typed(query: dict[str, Any]) -> None:
    clauses = list(_clauses(query["filter"]))
    assert clauses
    for clause in clauses:
        expected = LIVE_FILTER_TYPE[clause["property"]]
        filter_keys = set(clause) - {"property"}
        assert filter_keys == {expected}, clause


def request(**overrides: Any) -> CodingKnowledgeRequest:
    values: dict[str, Any] = {
        "task_reference": "#3032 live CKR6 retrieval",
        "ecosystem_hints": ("python", "agent-os"),
        "language_hints": ("python",),
        "capability_keywords": ("testing", "deployment", "Notion"),
        "target_path_hints": ("scripts/agent_os_issue_acceptance",),
        "canonical_rule_refs": ("AGENTS.md",),
    }
    values.update(overrides)
    return CodingKnowledgeRequest(**values)


def test_filtered_query_uses_live_property_filter_types() -> None:
    query = build_filtered_query(request())
    _assert_live_typed(query)
    status = [c for c in _clauses(query["filter"]) if c["property"] == "Status"]
    assert status == [{"property": "Status", "select": {"does_not_equal": "Archived note"}}]


def test_escalation_queries_use_live_property_filter_types() -> None:
    for step in (
        RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY,
        RetrievalEscalation.EXACT_NARROW_LOOKUP,
    ):
        _assert_live_typed(build_escalation_query(request(), step))


def test_known_reference_query_filters_unique_id_numbers() -> None:
    query = build_known_reference_query(("lesson-12", "LL-42", "7", "lesson-12", "#2638"))
    _assert_live_typed(query)
    assert [c["unique_id"]["equals"] for c in query["filter"]["or"]] == [12, 42, 7]


def test_non_lesson_references_name_no_lesson_and_fail_closed() -> None:
    assert known_lesson_numbers(("#2638", "AGENTS.md", "", "run:36459267724")) == ()
    with pytest.raises(LessonActivationError):
        build_known_reference_query(("#2638",))


def test_non_lesson_reference_skips_known_lookup_and_reaches_live_typed_query() -> None:
    calls: list[dict[str, Any]] = []

    def executor(query: dict[str, Any]) -> dict[str, Any]:
        calls.append(query)
        return {"results": []}

    orchestrate_lesson_retrieval(
        request(known_knowledge_refs=("#2638", "#2783")),
        execute_read=executor,
    )

    assert calls
    for query in calls:
        _assert_live_typed(query)
        assert all(c["property"] != "Lesson ID" for c in _clauses(query["filter"]))
