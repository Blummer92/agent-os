"""#3212 repair regressions: declared worksheet figures are required Docs targets.

Each declared visual example is a required Docs image obligation with a
distinct (role_id, slot_id). A Slides receipt or an optional-only binding
must not satisfy it; duplicate same-slot declarations across independent
sections fail closed; the same approved asset reused in distinct slots is
fine; and a lesson with no declarations keeps the legacy behavior.
"""
from __future__ import annotations

import pytest

from instructional_materials_coach.artifact_content_qa import (
    ArtifactObservation,
    TerminalQAExpectations,
    evaluate_artifact_qa,
)
from instructional_materials_coach.build_request import compose_governed_build_request
from instructional_materials_coach.connected_visual_placement import (
    VisualPlacementBinding,
)
from instructional_materials_coach.content_spec import content_from_dict
from instructional_materials_coach.worksheet_visual_examples import (
    VisualExampleCoverageError,
    required_visual_example_bindings,
    require_visual_example_plan_coverage,
)

KEY = "k" * 64


def _binding(
    role_id: str,
    slot_id: str = "0",
    *,
    required: bool = True,
    asset_id: str = "asset-1",
) -> VisualPlacementBinding:
    return VisualPlacementBinding(
        role_id=role_id,
        asset_id=asset_id,
        drive_file_id=f"file-{asset_id}",
        content_identity={"kind": "bytes", "sha256": "ab" * 32},
        source_plan_id="plan-1",
        required=required,
        slot_id=slot_id,
        eligibility_evidence={"rule": "fixture"},
    )


def _record(
    binding: VisualPlacementBinding,
    *,
    artifact_type: str,
    artifact_id: str,
    element_id: str,
    post_revision: str,
) -> dict:
    return {
        "idempotency_key": KEY,
        "role_id": binding.role_id,
        "slot_id": binding.slot_id,
        "asset_id": binding.asset_id,
        "content_identity": dict(binding.content_identity),
        "artifact_type": artifact_type,
        "artifact_id": artifact_id,
        "state": "verified",
        "post_insertion_revision_id": post_revision,
        "inserted_element_id": element_id,
    }


def _observation(
    artifact_type: str, artifact_id: str, *, revision: str, image_ids: tuple[str, ...] = ()
) -> ArtifactObservation:
    return ArtifactObservation(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        revision_id=revision,
        full_text="",
        image_element_ids=image_ids,
    )


def _compose(bindings, targets):
    return compose_governed_build_request(
        slides_template_id="slides",
        doc_template_id="docs",
        target_folder_id="folder",
        content_title="Unit",
        idempotency_key=KEY,
        slides_requests=(),
        docs_requests=(),
        visual_placements=tuple(bindings),
        resume_dir="resume",
        placement_transport=None,
        placement_receipts_dir="placements",
        qa_evidence_dir="qa",
        worksheet_visual_targets=tuple(targets),
        # #3259 D2 (current main): the governed composer fails closed when
        # the authored token set is missing. These fixtures compose empty
        # plans with no authored content, so the set is explicitly empty.
        expected_content_tokens=(),
    )


def _evaluate_docs(report_input, records, observation):
    return evaluate_artifact_qa(
        artifact_type="docs",
        artifact_id=observation.artifact_id,
        expectations=report_input.build_input.qa_expectations,
        observation=observation,
        placement_records=tuple(records),
        idempotency_key=KEY,
    )


def _codes(report) -> list[str]:
    return [finding.code for finding in report.findings]


def _content(examples):
    return content_from_dict(
        {
            "title": "Lesson",
            "objectives": ["Compare"],
            "slides": [],
            "worksheet_questions": ["Choose"],
            "visual_examples": examples,
        }
    )


# --- Counterexamples: must fail closed -------------------------------------


def test_slides_only_receipt_for_docs_target_fails():
    """A verified Slides receipt must not satisfy a required Docs figure."""
    binding = _binding("figure")
    composed = _compose((binding,), (("figure", "0"),))
    records = [
        _record(
            binding, artifact_type="slides", artifact_id="slides-1",
            element_id="image-1", post_revision="rev-1",
        )
    ]
    report = _evaluate_docs(
        composed, records, _observation("docs", "doc-1", revision="rev-1")
    )
    assert report.state != "verified"
    assert "qa-visual-wrong-artifact" in _codes(report)


def test_optional_only_binding_fails_composition():
    """An optional-only binding cannot discharge a declared required figure."""
    binding = _binding("figure", required=False)
    with pytest.raises(ValueError, match="optional"):
        _compose((binding,), (("figure", "0"),))


def test_optional_plan_assignment_fails_plan_coverage():
    """Pre-write: optional plan coverage of a declared figure fails closed."""
    content = _content([{"section": "page1", "role_id": "figure"}])
    with pytest.raises(VisualExampleCoverageError, match="optional"):
        require_visual_example_plan_coverage(
            content, (("figure", "0", "asset-1", False),)
        )


def test_missing_docs_marker_fails():
    """A declared figure with no Docs placement at all fails closed."""
    binding = _binding("figure")
    composed = _compose((binding,), (("figure", "0"),))
    report = _evaluate_docs(
        composed, (), _observation("docs", "doc-1", revision="rev-1")
    )
    assert report.state != "verified"
    assert "qa-placement-unverified" in _codes(report)


def test_duplicate_role_slot_across_sections_fails():
    """Two sections declaring the same (role, slot) is a conflict, not sharing."""
    content = _content(
        [
            {"section": "page1", "role_id": "figure", "slot_id": "0"},
            {"section": "page2", "role_id": "figure", "slot_id": "0"},
        ]
    )
    with pytest.raises(VisualExampleCoverageError, match="page1"):
        required_visual_example_bindings(content)
    with pytest.raises(VisualExampleCoverageError, match="page1"):
        require_visual_example_plan_coverage(
            content, (("figure", "0", "asset-1", True),)
        )


def test_two_distinct_figures_require_two_placements():
    """Two declared figures: placing only one fails the other closed."""
    bindings = (_binding("figure", "0"), _binding("figure", "1"))
    composed = _compose(bindings, (("figure", "0"), ("figure", "1")))
    records = [
        _record(
            bindings[0], artifact_type="docs", artifact_id="doc-1",
            element_id="image-1", post_revision="rev-1",
        )
    ]
    report = _evaluate_docs(
        composed, records, _observation("docs", "doc-1", revision="rev-1", image_ids=("image-1",))
    )
    assert report.state != "verified"
    assert "qa-placement-unverified" in _codes(report)


def test_receipt_for_wrong_docs_artifact_fails():
    """A Docs receipt bound to a different Docs artifact ID does not satisfy."""
    binding = _binding("figure")
    composed = _compose((binding,), (("figure", "0"),))
    records = [
        _record(
            binding, artifact_type="docs", artifact_id="doc-OTHER",
            element_id="image-1", post_revision="rev-1",
        )
    ]
    report = _evaluate_docs(
        composed, records, _observation("docs", "doc-1", revision="rev-1", image_ids=("image-1",))
    )
    assert report.state != "verified"
    assert "qa-receipt-artifact-conflict" in _codes(report)


# --- Positives: must verify -------------------------------------------------


def test_single_required_docs_figure_verifies():
    """One declared figure with one genuine verified Docs placement verifies."""
    binding = _binding("figure")
    composed = _compose((binding,), (("figure", "0"),))
    expectations = composed.build_input.qa_expectations
    scoped = [v for v in expectations.visuals if (v.role_id, v.slot_id) == ("figure", "0")]
    assert len(scoped) == 1 and scoped[0].artifact_type == "docs" and scoped[0].required
    records = [
        _record(
            binding, artifact_type="docs", artifact_id="doc-1",
            element_id="image-1", post_revision="rev-1",
        )
    ]
    report = _evaluate_docs(
        composed, records, _observation("docs", "doc-1", revision="rev-1", image_ids=("image-1",))
    )
    assert report.state == "verified", _codes(report)


def test_shared_asset_in_distinct_slots_passes_plan_coverage():
    """Approved reuse of one asset across distinct slots is legitimate."""
    content = _content(
        [
            {"section": "page1", "role_id": "figure", "slot_id": "0"},
            {"section": "page2", "role_id": "figure", "slot_id": "1"},
        ]
    )
    # Same asset covers both distinct slots in the governed plan.
    require_visual_example_plan_coverage(
        content,
        (("figure", "0", "asset-1", True), ("figure", "1", "asset-1", True)),
    )
    assert required_visual_example_bindings(content) == (("figure", "0"), ("figure", "1"))


def test_no_declarations_preserves_backward_compatibility():
    """No declared figures: legacy artifact-agnostic behavior is unchanged."""
    binding = _binding("figure")
    composed = _compose((binding,), ())
    expectations = composed.build_input.qa_expectations
    assert all(v.artifact_type == "" for v in expectations.visuals)
    # Legacy marker routing: a slides-side verified receipt does not fail
    # the docs-side evaluation of an artifact-agnostic required visual.
    records = [
        _record(
            binding, artifact_type="slides", artifact_id="slides-1",
            element_id="image-1", post_revision="rev-1",
        )
    ]
    report = _evaluate_docs(
        composed, records, _observation("docs", "doc-1", revision="rev-1")
    )
    assert report.state == "verified", _codes(report)


def test_expectations_hash_binds_docs_scope():
    """The docs scope of a declared figure is part of the expectations hash."""
    binding = _binding("figure")
    scoped = TerminalQAExpectations.build_from_requests(
        idempotency_key=KEY, visual_placements=(binding,),
        required_docs_visuals=(("figure", "0"),),
    )
    legacy = TerminalQAExpectations.build_from_requests(
        idempotency_key=KEY, visual_placements=(binding,),
    )
    assert scoped.expectations_hash() != legacy.expectations_hash()


@pytest.mark.xfail(
    reason="blocked on R1 (#3258): sequential genuine placements leave the "
    "earlier receipt stale until the batch-reconciliation proof lands",
    strict=False,
)
def test_two_required_docs_figures_verify_after_r1():
    """Two declared figures, two genuine sequential placements: both verify.

    Genuine revisions (each receipt keeps its own post-insertion revision;
    no synthesized uniform final). Blocked until R1's receipt-reconciliation
    repair; today the earlier receipt is rejected as qa-artifact-stale.
    """
    bindings = (_binding("figure", "0"), _binding("figure", "1"))
    composed = _compose(bindings, (("figure", "0"), ("figure", "1")))
    records = [
        _record(
            bindings[0], artifact_type="docs", artifact_id="doc-1",
            element_id="image-1", post_revision="rev-1",
        ),
        _record(
            bindings[1], artifact_type="docs", artifact_id="doc-1",
            element_id="image-2", post_revision="rev-1+insert",
        ),
    ]
    report = _evaluate_docs(
        composed,
        records,
        _observation(
            "docs", "doc-1", revision="rev-1+insert", image_ids=("image-1", "image-2")
        ),
    )
    assert report.state == "verified", _codes(report)
