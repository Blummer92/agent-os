"""MX9: inserting one image must not hide an extra inserted or removed element."""
import pytest
from instructional_materials_coach.connected_visual_placement import (
    _check_insertion_continuity, PlacementExecutionError, VisualPlacementBinding,
)
from instructional_materials_coach.artifact_content_qa import ArtifactObservation


def _binding():
    return VisualPlacementBinding("diagram", "asset", "file", {}, "plan")


@pytest.mark.parametrize("after_ids", [
    ("img-old", "img-new", "img-unrelated"),
    ("img-new",),
])
def test_mx9_unrelated_element_changes_refuse_continuity(after_ids):
    marker = "{{visual:diagram}}"
    before = ArtifactObservation("docs", "doc", "r1", "Start " + marker + " End", image_element_ids=("img-old",))
    after = ArtifactObservation("docs", "doc", "r2", "Start  End", image_element_ids=after_ids)
    with pytest.raises(PlacementExecutionError, match="placement-continuity-broken"):
        _check_insertion_continuity(pre=before, post=after, marker=marker,
                                    inserted_element_id="img-new", binding=_binding())
