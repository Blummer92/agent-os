"""#3389 — student-visible provenance / AI disclosure regression tests.

The Focus Test 2B (2026-10-07) reproduction: `Composition_Comparison.docx`
included photographs whose visible captions identified only the depicted
subject/context -- no photographer attribution, no AI disclosure. The
teacher requirement: "If it's a real photo from the web the
photographer's name should be next to the photograph. If it's an AI photo
it should say it's AI."

Required-behavior matrix (from the issue):

- sourced photograph + known photographer -> photographer name visibly
  adjacent
- AI-generated image -> visibly labeled AI-generated
- unknown origin -> cannot pass as fully final without explicit
  unresolved/manual-review result
- label remains attached to the correct image after DOCX/Slides
  layout/export
- semantic visual-role tests from #3386 continue to pass independently of
  provenance labeling
- terminal QA cannot treat image presence alone as sufficient provenance
  evidence

Scope note: provenance is explicit governed input carried on the plan
assignment (`image_provenance`), enforced strictly by terminal QA
whenever it is carried. Upstream paths that predate provenance tracking
carry no evidence (None) and keep their existing QA behavior -- that
boundary is pinned by `test_legacy_expectation_without_provenance_keeps_behavior`
and documented in the module. Web-photo provenance metadata needs live
image metadata for full validation (Phase 1 partial-dependency
classification); fixtures here are synthetic only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_EVIDENCE_INCOMPLETE,
    QA_STATE_PROVENANCE_UNRESOLVED,
    QA_STATE_VERIFIED,
    ArtifactObservation,
    TerminalQAExpectations,
    evaluate_artifact_qa,
)
from instructional_materials_coach.connected_visual_placement import (
    PlacementExecutionError,
    VisualPlacementBinding,
    plan_visual_placement_bindings,
)
from instructional_materials_coach.image_provenance import (
    AI_GENERATED_LABEL,
    UNKNOWN_CREATOR_LABEL,
    UNKNOWN_ORIGIN_LABEL,
    ImageProvenance,
    ImageProvenanceError,
    bind_caption_to_image,
    image_provenance_from_mapping,
    provenance_qa_outcome,
    student_visible_caption,
)
from instructional_materials_coach.placement_receipts import (
    append_placement_record,
    build_placement_record,
    load_placement_records,
)

KEY = "k" * 64
IDENTITY = {"sha256": "abc123"}


def _prov(origin_kind, creator=None, detail=None) -> ImageProvenance:
    return ImageProvenance(origin_kind=origin_kind, creator_name=creator, source_detail=detail)


# ---------------------------------------------------------------------------
# Caption builder: student-visible disclosure at the point of use
# ---------------------------------------------------------------------------

def test_sourced_photograph_caption_names_photographer():
    caption = student_visible_caption(_prov("human-photograph", creator="Ada Lovelace"))
    assert caption == "Photo: Ada Lovelace"


def test_ai_generated_caption_labels_ai():
    caption = student_visible_caption(_prov("ai-generated"))
    assert caption == "AI-generated image"
    assert caption == AI_GENERATED_LABEL


def test_unknown_origin_caption_discloses_unknown():
    # Fail-closed disclosure: never silently omitted.
    caption = student_visible_caption(_prov("unknown"))
    assert caption == "Image source unknown"
    assert caption == UNKNOWN_ORIGIN_LABEL


def test_human_photograph_without_known_creator_discloses_unknown_creator():
    caption = student_visible_caption(_prov("human-photograph"))
    assert caption == "Photo: source unknown"
    assert caption == UNKNOWN_CREATOR_LABEL


def test_caption_builder_rejects_garbage():
    with pytest.raises(ImageProvenanceError):
        student_visible_caption("Photo: Ada Lovelace")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Evidence validation: explicit, never invented, malformed fails closed
# ---------------------------------------------------------------------------

def test_from_mapping_none_means_no_evidence_carried():
    assert image_provenance_from_mapping(None) is None


def test_from_mapping_accepts_governed_shapes():
    prov = image_provenance_from_mapping(
        {"origin_kind": "human-photograph", "creator_name": "Ada Lovelace",
         "source_detail": "library asset photo-1"}
    )
    assert prov == _prov("human-photograph", creator="Ada Lovelace",
                        detail="library asset photo-1")


def test_from_mapping_unknown_is_explicit_carried_evidence():
    prov = image_provenance_from_mapping({"origin_kind": "unknown"})
    assert prov is not None and prov.origin_kind == "unknown"


def test_from_mapping_malformed_fails_closed():
    with pytest.raises(ImageProvenanceError):
        image_provenance_from_mapping("human-photograph")  # type: ignore[arg-type]
    with pytest.raises(ImageProvenanceError):
        image_provenance_from_mapping({"origin_kind": "stock-photo"})
    with pytest.raises(ImageProvenanceError):
        image_provenance_from_mapping(
            {"origin_kind": "human-photograph", "creator_name": "   "})
    with pytest.raises(ImageProvenanceError):
        image_provenance_from_mapping({})  # missing origin_kind


def test_provenance_qa_outcome_matrix():
    assert provenance_qa_outcome(_prov("ai-generated")) == "verified"
    assert provenance_qa_outcome(_prov("human-photograph", creator="Ada Lovelace")) == "verified"
    assert provenance_qa_outcome(_prov("human-photograph")) == "unresolved"
    assert provenance_qa_outcome(_prov("unknown")) == "unresolved"


def test_caption_binding_stays_attached_to_image():
    """The visible label travels with the image: the bound structure keys
    the exact caption text to the exact image reference, so layout/export
    cannot separate or swap disclosures."""
    first = bind_caption_to_image(
        image_ref="img-rule-of-thirds",
        provenance=_prov("human-photograph", creator="Ada Lovelace"),
    )
    second = bind_caption_to_image(
        image_ref="img-leading-lines",
        provenance=_prov("ai-generated"),
    )
    assert first["image_ref"] == "img-rule-of-thirds"
    assert first["caption_text"] == "Photo: Ada Lovelace"
    assert second["image_ref"] == "img-leading-lines"
    assert second["caption_text"] == "AI-generated image"
    # The binding re-derives nothing: caption and provenance agree.
    assert student_visible_caption(
        image_provenance_from_mapping(first["provenance"])) == first["caption_text"]
    with pytest.raises(ImageProvenanceError):
        bind_caption_to_image(image_ref="  ", provenance=_prov("ai-generated"))


# ---------------------------------------------------------------------------
# Terminal QA integration
# ---------------------------------------------------------------------------

def _binding(role_id: str, slot_id: str, asset_id: str,
             provenance: ImageProvenance | None) -> VisualPlacementBinding:
    return VisualPlacementBinding(
        role_id=role_id, asset_id=asset_id, drive_file_id="drive-1",
        content_identity=dict(IDENTITY), source_plan_id="plan-1",
        required=True, slot_id=slot_id, image_provenance=provenance,
    )


def _record(role_id: str, slot_id: str, asset_id: str,
            provenance: Mapping[str, Any] | None) -> dict[str, Any]:
    return build_placement_record(
        receipt={
            "asset_id": asset_id, "drive_file_id": "drive-1", "role_id": role_id,
            "artifact_type": "docs", "artifact_id": "doc-1",
            "artifact_revision_id": "r0", "marker": None, "container_id": None,
            "inserted_element_id": f"img-{slot_id}", "state": "verified",
        },
        content_identity=dict(IDENTITY),
        slot_id=slot_id, source_plan_id="plan-1", required=True,
        eligibility_evidence=None, transport_name="test",
        post_insertion_revision="r1",
        image_provenance=dict(provenance) if provenance else None,
    )


def _observation(*, images: tuple[str, ...] = ("img-0",)) -> ArtifactObservation:
    return ArtifactObservation(
        artifact_type="docs", artifact_id="doc-1", revision_id="r1",
        full_text="Composition Comparison worksheet", token_hits=(),
        image_element_ids=images,
    )


def _evaluate(bindings, records, observation):
    expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key=KEY, visual_placements=bindings)
    return evaluate_artifact_qa(
        artifact_type="docs", artifact_id="doc-1", expectations=expectations,
        observation=observation, placement_records=records, idempotency_key=KEY,
    )


def _codes(report) -> list[str]:
    return [finding.code for finding in report.findings]


def test_sourced_photo_with_known_photographer_passes_qa():
    prov = _prov("human-photograph", creator="Ada Lovelace")
    report = _evaluate(
        (_binding("rule-of-thirds", "0", "asset-1", prov),),
        (_record("rule-of-thirds", "0", "asset-1", prov.to_dict()),),
        _observation(),
    )
    assert report.state == QA_STATE_VERIFIED, [(f.code, f.message) for f in report.findings]


def test_ai_generated_image_passes_qa_with_disclosure():
    """An AI-generated image is not blocked -- it is disclosed. The
    carried evidence says AI-generated, so terminal QA passes."""
    prov = _prov("ai-generated")
    report = _evaluate(
        (_binding("leading-lines", "0", "asset-1", prov),),
        (_record("leading-lines", "0", "asset-1", prov.to_dict()),),
        _observation(),
    )
    assert report.state == QA_STATE_VERIFIED


def test_unknown_origin_cannot_pass_as_fully_final():
    """Issue required test 3 + 6: image presence alone is not provenance
    evidence. A placed image with carried unknown origin gets an explicit
    unresolved-provenance finding (naming the student-visible disclosure)
    and terminal completion is refused."""
    prov = _prov("unknown")
    report = _evaluate(
        (_binding("framing", "0", "asset-1", prov),),
        (_record("framing", "0", "asset-1", prov.to_dict()),),
        _observation(),
    )
    assert report.state == QA_STATE_PROVENANCE_UNRESOLVED
    assert "qa-provenance-unresolved" in _codes(report)
    finding = next(f for f in report.findings if f.code == "qa-provenance-unresolved")
    assert finding.severity == "fail"
    assert finding.detail["student_visible_caption"] == "Image source unknown"
    assert "manual review" in finding.message
    assert "framing" in finding.message


def test_human_photo_without_known_creator_routes_to_manual_review():
    prov = _prov("human-photograph")  # no creator name
    report = _evaluate(
        (_binding("negative-space", "0", "asset-1", prov),),
        (_record("negative-space", "0", "asset-1", prov.to_dict()),),
        _observation(),
    )
    assert report.state == QA_STATE_PROVENANCE_UNRESOLVED
    finding = next(f for f in report.findings if f.code == "qa-provenance-unresolved")
    assert finding.detail["student_visible_caption"] == "Photo: source unknown"


def test_malformed_carried_provenance_fails_closed_in_qa():
    from instructional_materials_coach.artifact_content_qa import VisualExpectation
    expectations = TerminalQAExpectations(
        idempotency_key=KEY,
        visuals=(VisualExpectation(
            role_id="r", slot_id="0", asset_id="a",
            content_identity=dict(IDENTITY),
            provenance={"origin_kind": "stock-photo"},  # bypasses builder validation
        ),),
    )
    report = evaluate_artifact_qa(
        artifact_type="docs", artifact_id="doc-1", expectations=expectations,
        observation=_observation(images=("img-0",)),
        placement_records=(_record("r", "0", "a", {"origin_kind": "stock-photo"}),),
        idempotency_key=KEY,
    )
    assert report.state == QA_STATE_EVIDENCE_INCOMPLETE
    assert "qa-provenance-evidence-invalid" in _codes(report)


def test_legacy_expectation_without_provenance_keeps_behavior():
    """Documented boundary: expectations that carry no provenance evidence
    (upstream predates provenance tracking) are not given provenance
    findings. The requirement is enforced whenever evidence IS carried."""
    report = _evaluate(
        (_binding("rule-of-thirds", "0", "asset-1", None),),
        (_record("rule-of-thirds", "0", "asset-1", None),),
        _observation(),
    )
    assert report.state == QA_STATE_VERIFIED
    assert not [c for c in _codes(report) if "provenance" in c]


def test_invalid_provenance_on_binding_fails_closed_at_expectations_build():
    class _BadBinding:
        role_id = "r"; slot_id = "0"; asset_id = "a"
        content_identity = dict(IDENTITY); required = True
        image_provenance = {"origin_kind": "stock-photo"}
    with pytest.raises(ValueError, match="invalid image provenance"):
        TerminalQAExpectations.build_from_requests(
            idempotency_key=KEY, visual_placements=(_BadBinding(),))


# ---------------------------------------------------------------------------
# Focus Test 2B shape: Composition Comparison, four photographic examples
# ---------------------------------------------------------------------------

def test_focus_test_2b_composition_comparison_shape():
    """The 2026-10-07 Focus Test 2B shape: four photographic examples
    (rule of thirds / leading lines / framing / negative space). Two carry
    photographer attribution, one is AI-generated (disclosed), one has
    unknown origin. Only the unknown-origin image blocks terminal
    completion -- with the finding naming exactly that role."""
    roles = (
        ("photo-rule-of-thirds", _prov("human-photograph", creator="Ada Lovelace")),
        ("photo-leading-lines", _prov("human-photograph", creator="Grace Hopper")),
        ("photo-framing", _prov("ai-generated")),
        ("photo-negative-space", _prov("unknown")),
    )
    bindings = tuple(_binding(role, str(i), f"asset-{i}", prov)
                     for i, (role, prov) in enumerate(roles))
    records = tuple(_record(role, str(i), f"asset-{i}", prov.to_dict())
                    for i, (role, prov) in enumerate(roles))
    images = tuple(f"img-{i}" for i in range(4))
    report = _evaluate(bindings, records, _observation(images=images))
    assert report.state == QA_STATE_PROVENANCE_UNRESOLVED
    unresolved = [f for f in report.findings if f.code == "qa-provenance-unresolved"]
    assert len(unresolved) == 1
    assert unresolved[0].detail["role_id"] == "photo-negative-space"
    assert unresolved[0].detail["student_visible_caption"] == "Image source unknown"


# ---------------------------------------------------------------------------
# Plan -> binding -> receipt -> expectation wiring
# ---------------------------------------------------------------------------

def _repo_fixture(name: str) -> dict[str, Any]:
    root = Path(__file__).parents[3]
    fixture = root / "tests" / "fixtures" / "instructional_workflow_contracts" / name
    return json.loads(fixture.read_text(encoding="utf-8"))


def _declared_plan(provenance: Any):
    from instructional_materials_coach.visual_reuse import (
        GovernedVisualReusePlan, plan_governed_visual_reuse)
    plan = plan_governed_visual_reuse(
        _repo_fixture("valid_material_requirement_v2.json"),
        visual_candidates=[_repo_fixture("valid_visual_asset_compatibility_v2.json")],
        source_revision="visual-library-snapshot-v2",
        teacher_decisions=(),
    )
    assert plan.outcome == "visuals-ready"
    payload = plan.cohesive_visual_plan_result.record.to_dict()
    payload["required_role_assignments"][0]["image_provenance"] = provenance

    class _FakeRecord:
        def __init__(self, payload): self._payload = payload
        def to_dict(self): return self._payload
    class _FakeResult:
        def __init__(self, payload): self._payload = payload
        @property
        def record(self): return _FakeRecord(self._payload)

    return GovernedVisualReusePlan(
        outcome=plan.outcome, final_production_blocked=False,
        selected_asset_ids=plan.selected_asset_ids,
        material_requirement_result=plan.material_requirement_result,
        visual_needs_result=plan.visual_needs_result,
        cohesive_visual_plan_result=_FakeResult(payload),
    )


def test_plan_binding_carries_declared_provenance():
    plan = _declared_plan({"origin_kind": "human-photograph",
                           "creator_name": "Ada Lovelace"})
    bindings = plan_visual_placement_bindings(plan)
    assert bindings[0].image_provenance == _prov("human-photograph", creator="Ada Lovelace")


def test_plan_binding_without_provenance_carries_none():
    from instructional_materials_coach.visual_reuse import plan_governed_visual_reuse
    plan = plan_governed_visual_reuse(
        _repo_fixture("valid_material_requirement_v2.json"),
        visual_candidates=[_repo_fixture("valid_visual_asset_compatibility_v2.json")],
        source_revision="visual-library-snapshot-v2",
        teacher_decisions=(),
    )
    bindings = plan_visual_placement_bindings(plan)
    assert all(b.image_provenance is None for b in bindings)


def test_plan_binding_with_malformed_provenance_fails_closed():
    plan = _declared_plan({"origin_kind": "stock-photo"})
    with pytest.raises(PlacementExecutionError, match="placement-provenance-evidence-invalid"):
        plan_visual_placement_bindings(plan)


def test_provenance_flows_binding_to_receipt_to_expectation_and_hash(tmp_path):
    """Provenance evidence is carried (never re-derived) from binding ->
    durable receipt -> terminal-QA expectation, and it participates in the
    expectations hash so QA evidence is bound to the disclosed provenance."""
    prov = _prov("ai-generated")
    binding = _binding("photo-framing", "0", "asset-1", prov)
    record = _record("photo-framing", "0", "asset-1", prov.to_dict())
    stored = append_placement_record(tmp_path, KEY, record)
    assert stored["image_provenance"] == prov.to_dict()
    loaded = load_placement_records(tmp_path, KEY)
    assert loaded[0]["image_provenance"] == prov.to_dict()

    with_prov = TerminalQAExpectations.build_from_requests(
        idempotency_key=KEY, visual_placements=(binding,))
    without_prov = TerminalQAExpectations.build_from_requests(
        idempotency_key=KEY,
        visual_placements=(_binding("photo-framing", "0", "asset-1", None),))
    assert with_prov.visuals[0].provenance == prov.to_dict()
    assert without_prov.visuals[0].provenance is None
    assert with_prov.expectations_hash() != without_prov.expectations_hash()
