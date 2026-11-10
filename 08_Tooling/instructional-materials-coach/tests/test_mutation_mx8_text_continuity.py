"""MX8: unrelated persisted Docs text edits fail insertion-continuity proof."""
import pytest
from instructional_materials_coach.connected_visual_placement import (
    _check_insertion_continuity, PlacementExecutionError, VisualPlacementBinding,
)
from instructional_materials_coach.artifact_content_qa import ArtifactObservation


def _binding():
    return VisualPlacementBinding("diagram", "asset", "file", {}, "plan")


def test_mx8_extra_text_edit_is_not_hidden_by_single_marker_removal():
    marker = "{{visual:diagram}}"
    before = ArtifactObservation("docs", "doc", "r1", "Intro " + marker + " Ending", image_element_ids=("img-old",))
    after = ArtifactObservation("docs", "doc", "r2", "Tampered Ending", image_element_ids=("img-old", "img-new"))
    with pytest.raises(PlacementExecutionError, match="placement-continuity-broken"):
        _check_insertion_continuity(pre=before, post=after, marker=marker,
                                    inserted_element_id="img-new", binding=_binding())
