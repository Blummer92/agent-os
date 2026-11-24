"""Exact-order contracts for library coverage search optimizations."""
from types import SimpleNamespace

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest,
    required_library_coverage_order,
)


def _rank(names, required):
    request = CodingKnowledgeRequest(
        task_reference="dependency qualification",
        library_hints=required,
        specialized_knowledge_required=True,
    )
    candidates = tuple(SimpleNamespace(name=name, library_name=None) for name in names)
    return required_library_coverage_order(request, candidates)


def test_repeated_coverage_signature_retains_earliest_tie_and_full_tail():
    assert _rank(("A", "A", "A", "A", "-", "B"), ("A", "B")) == [0, 1, 5, 2, 3, 4]


def test_impossible_full_coverage_keeps_the_largest_lexicographic_choice():
    names = ("-",) * 24 + ("A", "B", "C", "D")
    assert _rank(names, ("A", "B", "C", "D")) == [24, 25, 26, *range(24), 27]


def test_repeated_signatures_bound_search_width_without_wall_clock(monkeypatch):
    from agent_memory_context_manager import coding_knowledge_selection as selector

    original = selector.combinations
    search_width = []

    def observe(indices, count):
        positions = tuple(indices)
        search_width.append(len(positions))
        return original(positions, count)

    monkeypatch.setattr(selector, "combinations", observe)
    names = ("-",) * 24 + ("A", "B", "C", "D")
    assert _rank(names, ("A", "B", "C", "D")) == [24, 25, 26, *range(24), 27]
    assert search_width == [7]
