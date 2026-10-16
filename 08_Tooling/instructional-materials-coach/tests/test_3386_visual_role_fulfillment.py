"""#3386 — semantic visual-role fulfillment regression tests.

The 2026-10-07 "Fix This Photo" reproduction: a Photography worksheet
requesting weak photographic composition examples was delivered with four
embedded images that were schematic line illustrations, not photographs.
An image-count or placement-only check passes on that artifact; the
semantic role-fulfillment check must not.

Required-behavior matrix (from the issue):

- photographic-example role + schematic/diagram image -> not complete
- photographic-example role + verified photographic asset -> eligible
- diagram/illustration role + schematic image -> may pass when valid
- four image objects present but all role-mismatched -> cannot pass by
  count alone
- direct DOCX route preserves required visual-role evidence into
  terminal QA

Vocabulary note: the governed representation-class vocabulary is
``REPRESENTATION_CLASSES`` from
``instructional_workflow_contracts.visual_asset_compatibility``. The
issue's "schematic" maps to the governed ``diagram`` class (a schematic
line illustration).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_PLACEMENT_UNVERIFIED,
    QA_STATE_VERIFIED,
    QA_STATE_VISUAL_MISMATCH,
    QA_STATE_VISUAL_ROLE_MISMATCH,
    ArtifactObservation,
    TerminalQAExpectations,
    VisualExpectation,
    evaluate_artifact_qa,
)
from instructional_materials_coach.connected_visual_placement import (
    PlacementExecutionError,
    VisualPlacementBinding,
    plan_visual_placement_bindings,
)
from instructional_materials_coach.placement_receipts import (
    build_placement_record,
    load_placement_records,
)
from instructional_materials_coach.visual_role_fulfillment import (
    UNCONSTRAINED_REPRESENTATION_CLASS,
    VisualRoleFulfillmentError,
    check_visual_role_fulfillment,
    observed_representation_class_from_compatibility,
    validate_representation_class,
)

KEY = "k" * 64
IDENTITY = {"sha256": "abc123"}

ROLE = "weak-photographic-composition-example"
DIAGRAM_ROLE = "weak-composition-diagram"

FOUR_SLOTS = ("angle", "distance", "framing", "composition")


# ---------------------------------------------------------------------------
# Unit: the pure fulfillment check
# ---------------------------------------------------------------------------

def test_photographic_required_diagram_observed_is_mismatch():
    result = check_visual_role_fulfillment(
        role_id=ROLE, slot_id="0",
        required_representation_class="photography",
        observed_representation_class="diagram",
    )
    assert result.status == "mismatch"
    message = result.message()
    assert "photography" in message and "diagram" in message
    assert ROLE in message


def test_photographic_required_photography_observed_fulfills():
    result = check_visual_role_fulfillment(
        role_id=ROLE, slot_id="0",
        required_representation_class="photography",
        observed_representation_class="photography",
    )
    assert result.status == "fulfilled"


def test_diagram_role_with_diagram_observed_may_pass():
    result = check_visual_role_fulfillment(
        role_id=DIAGRAM_ROLE, slot_id="0",
        required_representation_class="diagram",
        observed_representation_class="diagram",
    )
    assert result.status == "fulfilled"


def test_unconstrained_required_never_invents_a_constraint():
    # A plan that declared no kind constraint keeps its existing behavior:
    # any governed observed kind passes.
    for observed in ("diagram", "photography", "illustration", None):
        result = check_visual_role_fulfillment(
            role_id=ROLE, slot_id="0",
            required_representation_class=None,
            observed_representation_class=observed,
        )
        assert result.status == "fulfilled", observed
    assert UNCONSTRAINED_REPRESENTATION_CLASS == "unspecified"


def test_declared_kind_without_observed_evidence_is_unverifiable():
    # v1 evidence carries no representation class: the kind cannot be
    # proven. This is an explicit blocked state, never a pass.
    result = check_visual_role_fulfillment(
        role_id=ROLE, slot_id="0",
        required_representation_class="photography",
        observed_representation_class=None,
    )
    assert result.status == "unverifiable"
    assert "manual review" in result.message()


def test_invalid_kind_values_fail_closed():
    with pytest.raises(VisualRoleFulfillmentError):
        validate_representation_class("photo")
    with pytest.raises(VisualRoleFulfillmentError):
        check_visual_role_fulfillment(
            role_id=ROLE, slot_id="0",
            required_representation_class="photograph",  # not governed
            observed_representation_class="diagram",
        )
    with pytest.raises(VisualRoleFulfillmentError):
        check_visual_role_fulfillment(
            role_id=ROLE, slot_id="0",
            required_representation_class="photography",
            observed_representation_class="schematic",  # not governed
        )


def test_observed_kind_reads_from_governed_compatibility_evidence():
    evidence = {"cohesion_profile": {"representation_class": "diagram"}}
    assert observed_representation_class_from_compatibility(evidence) == "diagram"
    assert observed_representation_class_from_compatibility(None) is None
    assert observed_representation_class_from_compatibility({}) is None  # v1 shape
    with pytest.raises(VisualRoleFulfillmentError):
        observed_representation_class_from_compatibility(
            {"cohesion_profile": {"representation_class": "photo"}}
        )


# ---------------------------------------------------------------------------
# Binding fixtures: bindings -> terminal-QA expectations -> QA verdict
# ---------------------------------------------------------------------------

def _binding(role_id: str, slot_id: str, asset_id: str, *,
             expected: str = "photography",
             observed: str | None = "diagram") -> VisualPlacementBinding:
    return VisualPlacementBinding(
        role_id=role_id, asset_id=asset_id, drive_file_id="drive-1",
        content_identity=dict(IDENTITY), source_plan_id="plan-1",
        required=True, slot_id=slot_id,
        expected_representation_class=expected,
        observed_representation_class=observed,
    )


def _record(role_id: str, slot_id: str, asset_id: str, observed: str | None,
            *, revision: str = "r1", inserted: str | None = None) -> dict[str, Any]:
    return build_placement_record(
        receipt={
            "asset_id": asset_id, "drive_file_id": "drive-1", "role_id": role_id,
            "artifact_type": "docs", "artifact_id": "doc-1",
            "artifact_revision_id": "r0", "marker": None, "container_id": None,
            "inserted_element_id": inserted or f"img-{slot_id}", "state": "verified",
        },
        content_identity=dict(IDENTITY),
        slot_id=slot_id, source_plan_id="plan-1", required=True,
        eligibility_evidence=None, transport_name="test",
        post_insertion_revision=revision,
        observed_representation_class=observed,
    )


def _observation(*, revision: str = "r1", images: tuple[str, ...] = ("img-0",),
                 text: str = "Fix This Photo worksheet") -> ArtifactObservation:
    return ArtifactObservation(
        artifact_type="docs", artifact_id="doc-1", revision_id=revision,
        full_text=text, token_hits=(), image_element_ids=images,
    )


def _evaluate(bindings: tuple[VisualPlacementBinding, ...],
              records: tuple[dict[str, Any], ...],
              observation: ArtifactObservation):
    expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key=KEY, visual_placements=bindings,
    )
    return evaluate_artifact_qa(
        artifact_type="docs", artifact_id="doc-1", expectations=expectations,
        observation=observation, placement_records=records, idempotency_key=KEY,
    )


def _codes(report) -> list[str]:
    return [finding.code for finding in report.findings]


def test_photographic_required_diagram_placed_fails_with_explicit_finding():
    """Issue required test 1: photographic-example role + diagram image ->
    not complete, with an explicit finding naming required and observed."""
    binding = _binding(ROLE, "0", "asset-1", expected="photography", observed="diagram")
    record = _record(ROLE, "0", "asset-1", "diagram")
    report = _evaluate((binding,), (record,), _observation())
    assert report.state == QA_STATE_VISUAL_ROLE_MISMATCH
    assert "qa-visual-role-kind-mismatch" in _codes(report)
    finding = next(f for f in report.findings if f.code == "qa-visual-role-kind-mismatch")
    assert finding.severity == "fail"
    assert finding.detail["required_representation_class"] == "photography"
    assert finding.detail["observed_representation_class"] == "diagram"
    assert "photography" in finding.message and "diagram" in finding.message


def test_photographic_required_photography_placed_is_eligible_to_complete():
    """Issue required test 2: photographic-example role + verified
    photographic asset -> eligible to complete."""
    binding = _binding(ROLE, "0", "asset-1", expected="photography", observed="photography")
    record = _record(ROLE, "0", "asset-1", "photography")
    report = _evaluate((binding,), (record,), _observation())
    assert report.state == QA_STATE_VERIFIED, [ (f.code, f.message) for f in report.findings ]


def test_diagram_role_with_diagram_placed_passes_when_otherwise_valid():
    """Issue required test 3: diagram/illustration role + schematic image ->
    may pass when otherwise valid."""
    binding = _binding(DIAGRAM_ROLE, "0", "asset-1", expected="diagram", observed="diagram")
    record = _record(DIAGRAM_ROLE, "0", "asset-1", "diagram")
    report = _evaluate((binding,), (record,), _observation())
    assert report.state == QA_STATE_VERIFIED


def test_four_role_mismatched_images_cannot_pass_by_count():
    """Issue required test 4 + the 2026-10-07 Fix This Photo regression
    fixture: four image objects are present, inserted, and verified-placed
    (count/placement checks pass), but every one is a diagram occupying a
    photographic-example role. The artifact cannot pass by count alone."""
    bindings = tuple(
        _binding(ROLE, slot, f"asset-{slot}", expected="photography", observed="diagram")
        for slot in FOUR_SLOTS
    )
    records = tuple(
        _record(ROLE, slot, f"asset-{slot}", "diagram")
        for slot in FOUR_SLOTS
    )
    images = tuple(f"img-{slot}" for slot in FOUR_SLOTS)
    report = _evaluate(bindings, records, _observation(images=images))
    assert report.state == QA_STATE_VISUAL_ROLE_MISMATCH
    mismatches = [f for f in report.findings if f.code == "qa-visual-role-kind-mismatch"]
    assert len(mismatches) == 4
    assert {f.detail["slot_id"] for f in mismatches} == set(FOUR_SLOTS)


def test_unverifiable_kind_routes_to_manual_review_not_a_pass():
    """Declared photographic requirement but the placed asset carries no
    governed kind evidence (v1 evidence): terminal QA refuses a pass and
    routes the role to manual review with the role named."""
    binding = _binding(ROLE, "0", "asset-1", expected="photography", observed=None)
    record = _record(ROLE, "0", "asset-1", None)
    report = _evaluate((binding,), (record,), _observation())
    assert report.state != QA_STATE_VERIFIED
    assert "qa-visual-role-kind-unverifiable" in _codes(report)
    finding = next(f for f in report.findings if f.code == "qa-visual-role-kind-unverifiable")
    assert ROLE in finding.message


def test_unconstrained_role_keeps_existing_behavior():
    """Legacy bindings without a declared kind constraint pass as before."""
    binding = _binding(ROLE, "0", "asset-1",
                       expected=UNCONSTRAINED_REPRESENTATION_CLASS, observed="diagram")
    record = _record(ROLE, "0", "asset-1", "diagram")
    report = _evaluate((binding,), (record,), _observation())
    assert report.state == QA_STATE_VERIFIED


def test_direct_docx_route_preserves_required_kind_into_terminal_qa():
    """Issue required test 5: a direct-route binding carrying the required
    visual kind flows through build_from_requests into the expectations
    hash and into terminal QA evaluation."""
    binding = _binding(ROLE, "0", "asset-1", expected="photography", observed="diagram")
    plain = _binding(ROLE, "0", "asset-1",
                     expected=UNCONSTRAINED_REPRESENTATION_CLASS, observed="diagram")
    with_kind = TerminalQAExpectations.build_from_requests(
        idempotency_key=KEY, visual_placements=(binding,))
    without_kind = TerminalQAExpectations.build_from_requests(
        idempotency_key=KEY, visual_placements=(plain,))
    assert with_kind.visuals[0].expected_representation_class == "photography"
    # The required kind is part of the governed QA identity: changing it
    # changes the expectations hash.
    assert with_kind.expectations_hash() != without_kind.expectations_hash()
    record = _record(ROLE, "0", "asset-1", "diagram")
    report = evaluate_artifact_qa(
        artifact_type="docs", artifact_id="doc-1", expectations=with_kind,
        observation=_observation(), placement_records=(record,), idempotency_key=KEY,
    )
    assert report.state == QA_STATE_VISUAL_ROLE_MISMATCH


def test_invalid_expected_kind_on_binding_fails_closed():
    with pytest.raises(ValueError, match="invalid expected representation class"):
        TerminalQAExpectations.build_from_requests(
            idempotency_key=KEY,
            visual_placements=(_binding(ROLE, "0", "asset-1", expected="photo"),),
        )


# ---------------------------------------------------------------------------
# Plan -> binding -> receipt wiring
# ---------------------------------------------------------------------------

def _repo_fixture(name: str) -> dict[str, Any]:
    root = Path(__file__).parents[3]
    fixture = root / "tests" / "fixtures" / "instructional_workflow_contracts" / name
    return json.loads(fixture.read_text(encoding="utf-8"))


def test_real_governed_plan_binding_carries_observed_kind_and_no_invented_constraint():
    """The real reuse planner's assignments flow into bindings: the
    observed kind comes from the governed compatibility evidence, and no
    kind constraint is invented for plans that did not declare one."""
    from instructional_materials_coach.visual_reuse import plan_governed_visual_reuse
    plan = plan_governed_visual_reuse(
        _repo_fixture("valid_material_requirement_v2.json"),
        visual_candidates=[_repo_fixture("valid_visual_asset_compatibility_v2.json")],
        source_revision="visual-library-snapshot-v2",
        teacher_decisions=(),
    )
    assert plan.outcome == "visuals-ready"
    bindings = plan_visual_placement_bindings(plan)
    assert bindings
    for binding in bindings:
        assert binding.observed_representation_class == "illustration"
        assert binding.expected_representation_class == UNCONSTRAINED_REPRESENTATION_CLASS


def test_plan_binding_with_declared_required_kind_carries_it(tmp_path):
    """A plan assignment that explicitly declares required_representation_class
    (the governed field, validated against the governed vocabulary) carries
    it onto the binding; an invalid declaration fails closed."""
    from instructional_materials_coach.visual_reuse import plan_governed_visual_reuse
    plan = plan_governed_visual_reuse(
        _repo_fixture("valid_material_requirement_v2.json"),
        visual_candidates=[_repo_fixture("valid_visual_asset_compatibility_v2.json")],
        source_revision="visual-library-snapshot-v2",
        teacher_decisions=(),
    )
    payload = plan.cohesive_visual_plan_result.record.to_dict()
    payload["required_role_assignments"][0]["required_representation_class"] = "photography"

    class _FakeRecord:
        def __init__(self, payload): self._payload = payload
        def to_dict(self): return self._payload
    class _FakeResult:
        def __init__(self, payload): self._payload = payload
        @property
        def record(self): return _FakeRecord(self._payload)

    from instructional_materials_coach.visual_reuse import GovernedVisualReusePlan
    declared = GovernedVisualReusePlan(
        outcome=plan.outcome, final_production_blocked=False,
        selected_asset_ids=plan.selected_asset_ids,
        material_requirement_result=plan.material_requirement_result,
        visual_needs_result=plan.visual_needs_result,
        cohesive_visual_plan_result=_FakeResult(payload),
    )
    bindings = plan_visual_placement_bindings(declared)
    assert bindings[0].expected_representation_class == "photography"

    payload["required_role_assignments"][0]["required_representation_class"] = "photo"
    broken = GovernedVisualReusePlan(
        outcome=plan.outcome, final_production_blocked=False,
        selected_asset_ids=plan.selected_asset_ids,
        material_requirement_result=plan.material_requirement_result,
        visual_needs_result=plan.visual_needs_result,
        cohesive_visual_plan_result=_FakeResult(payload),
    )
    with pytest.raises(PlacementExecutionError, match="placement-visual-kind-evidence-invalid"):
        plan_visual_placement_bindings(broken)


def test_observed_kind_survives_receipt_store_round_trip(tmp_path):
    """The observed kind on the durable placement receipt is the evidence
    terminal QA evaluates -- never re-derived downstream."""
    record = _record(ROLE, "0", "asset-1", "diagram")
    from instructional_materials_coach.placement_receipts import append_placement_record
    stored = append_placement_record(tmp_path, KEY, record)
    assert stored["observed_representation_class"] == "diagram"
    loaded = load_placement_records(tmp_path, KEY)
    assert loaded[0]["observed_representation_class"] == "diagram"


def test_binding_defaults_keep_legacy_callers_working():
    """Existing callers that construct VisualPlacementBinding without the
    new fields keep the previous semantics: no invented constraint."""
    binding = VisualPlacementBinding(
        role_id=ROLE, asset_id="asset-1", drive_file_id="drive-1",
        content_identity=dict(IDENTITY), source_plan_id="plan-1",
    )
    assert binding.expected_representation_class == UNCONSTRAINED_REPRESENTATION_CLASS
    assert binding.observed_representation_class is None
    expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key=KEY, visual_placements=(binding,))
    assert expectations.visuals[0].expected_representation_class == "unspecified"
    assert isinstance(expectations.visuals[0], VisualExpectation)
    assert QA_STATE_VISUAL_MISMATCH  # import sanity for the module surface
