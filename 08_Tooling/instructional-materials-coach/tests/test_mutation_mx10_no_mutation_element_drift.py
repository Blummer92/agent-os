"""MX10: known-no-write recovery must prove unchanged persisted element set."""
from instructional_materials_coach import connected_visual_placement as placement
from instructional_materials_coach.connected_visual_placement import VisualPlacementBinding


def test_mx10_same_revision_and_marker_with_changed_elements_keeps_fence(monkeypatch):
    binding = VisualPlacementBinding("diagram", "asset", "file", {}, "plan")
    marker = "{{visual:diagram}}"
    monkeypatch.setattr(placement, "_revision_id", lambda **_: "r1")
    monkeypatch.setattr(placement, "_artifact_element_ids", lambda **_: frozenset({"img-old", "img-foreign"}))
    monkeypatch.setattr(placement, "discover_docs_markers", lambda **_: [{
        "marker": marker, "container_id": "doc", "element_id": "marker-element",
    }])
    assert placement._no_mutation_observed(
        artifact_type="docs", service=object(), artifact_id="doc", binding=binding,
        target_revision="r1", target_marker=marker, target_container="doc",
        target_element="marker-element", before_element_ids=frozenset({"img-old"}),
    ) is False
