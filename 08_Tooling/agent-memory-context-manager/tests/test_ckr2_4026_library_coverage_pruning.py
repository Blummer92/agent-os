"""Exact-order contracts for library coverage search optimizations."""
from types import SimpleNamespace

from agent_memory_context_manager import coding_knowledge_selection as selector


def _rank(names, required):
    request = selector.CodingKnowledgeRequest(
        task_reference="dependency qualification",
        library_hints=required,
        specialized_knowledge_required=True,
    )
    candidates = tuple(SimpleNamespace(name=name, library_name=None) for name in names)
    return selector.required_library_coverage_order(request, candidates)


def test_repeated_coverage_signature_retains_earliest_tie_and_full_tail():
    assert _rank(("A", "A", "A", "A", "-", "B"), ("A", "B")) == [0, 1, 5, 2, 3, 4]


def test_impossible_full_coverage_keeps_the_largest_lexicographic_choice():
    names = ("-",) * 24 + ("A", "B", "C", "D")
    assert _rank(names, ("A", "B", "C", "D")) == [24, 25, 26, *range(24), 27]


def test_repeated_signatures_bound_search_width_without_wall_clock(monkeypatch):
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


def test_overlapping_tie_keeps_the_earliest_choice():
    rows = [SimpleNamespace(name="A", library_name=alias) for alias in "BCDE"]
    req = selector.CodingKnowledgeRequest(task_reference="coverage", library_hints=tuple("ABCDE"))
    assert selector.required_library_coverage_order(req, rows) == [0, 1, 2, 3]


def test_attainable_upper_bound_stops_after_first_improvement(monkeypatch):
    original = selector.combinations
    inspected = []

    def observe(indices, count):
        for subset in original(indices, count):
            inspected.append(subset)
            yield subset

    monkeypatch.setattr(selector, "combinations", observe)
    pairs = (("A", "B"), ("C", "D"), ("A", "C"), ("E", "F"), ("G", "H"))
    candidates = [SimpleNamespace(name=a, library_name=b) for a, b in pairs]
    req = selector.CodingKnowledgeRequest(task_reference="coverage", library_hints=tuple("ABCDEFGH"))
    assert selector.required_library_coverage_order(req, candidates) == [0, 1, 3, 2, 4]
    assert inspected == [(0, 1, 2), (0, 1, 3)]


def test_one_available_library_does_not_reorder():
    assert _rank(("-", "-", "-", "A"), ("A", "B")) == [0, 1, 2, 3]
