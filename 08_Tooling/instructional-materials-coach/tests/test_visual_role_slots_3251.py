"""Regression tests for #3251 — slot-aware placement, context, and completeness.

Covers the downstream (role_id, slot_id) keying through the real IMC
modules: slot-aware markers, per-slot placement targets/receipts,
generation-context multiplicity, and slot-keyed completeness QA.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from instructional_materials_coach.generation_context import (
    GenerationContextError,
    compose_generation_context,
)
from instructional_materials_coach.visual_completeness import (
    validate_visual_completeness,
)
from instructional_materials_coach.visual_placement import (
    IMPLICIT_SLOT_ID,
    VisualPlacementError,
    build_placement_request,
    marker_for_role,
    marker_for_role_slot,
    parse_marker,
    parse_marker_binding,
    resolve_exact_target,
    retry_is_safe,
    verify_placement_receipt,
)

ROLE = "visual-role-aaaabbbbccccdddd"
OTHER_ROLE = "visual-role-eeeeffff00001111"

CONTENT_IDENTITY = {
    "contract_version": "governed-asset-content-identity-v1",
    "source": "drive-sha256",
    "algorithm": "sha256",
    "value": "a" * 64,
}


def _target(*, role_id=ROLE, slot_id=IMPLICIT_SLOT_ID, marker=None):
    return resolve_exact_target(
        artifact_type="slides",
        artifact_id="presentation-1",
        artifact_revision_id="revision-1",
        role_id=role_id,
        slot_id=slot_id,
        matches=[
            {
                "marker": marker or marker_for_role(role_id),
                "container_id": "slide-1",
                "element_id": "shape-1",
            }
        ],
    )


def _request(*, slot_id=IMPLICIT_SLOT_ID, marker=None):
    target = _target(slot_id=slot_id, marker=marker)
    return build_placement_request(
        selected_asset={
            "asset_id": "asset-1",
            "drive_file_id": "file-1",
            "content_identity": dict(CONTENT_IDENTITY),
        },
        role_id=ROLE,
        slot_id=slot_id,
        source_plan_id="plan-1",
        target=target,
    )


# --- Slot-aware markers --------------------------------------------------------

def test_role_only_marker_binds_implicit_slot() -> None:
    assert parse_marker(marker_for_role(ROLE)) == ROLE
    assert parse_marker_binding(marker_for_role(ROLE)) == (ROLE, "0")


def test_slot_marker_round_trip() -> None:
    marker = marker_for_role_slot(ROLE, "page-1")
    assert marker == "{{visual:" + ROLE + ":page-1}}"
    assert parse_marker_binding(marker) == (ROLE, "page-1")


def test_malformed_slot_marker_rejected() -> None:
    with pytest.raises(VisualPlacementError):
        parse_marker_binding("{{visual:" + ROLE + ":page:1}}")
    with pytest.raises(VisualPlacementError):
        marker_for_role_slot(ROLE, "has space")
    with pytest.raises(VisualPlacementError):
        marker_for_role_slot(ROLE, "")


def test_slot_target_resolves_exactly_one_match_per_binding() -> None:
    target = _target(
        slot_id="page-1",
        marker=marker_for_role_slot(ROLE, "page-1"),
    )
    assert target.slot_id == "page-1"
    assert target.marker == marker_for_role_slot(ROLE, "page-1")
    # A role-only marker does NOT satisfy an explicit-slot binding.
    with pytest.raises(VisualPlacementError, match="does not bind"):
        _target(slot_id="page-1", marker=marker_for_role(ROLE))
    # Two matches for one binding still fail closed.
    with pytest.raises(VisualPlacementError, match="exactly one marker match"):
        resolve_exact_target(
            artifact_type="slides",
            artifact_id="presentation-1",
            artifact_revision_id="revision-1",
            role_id=ROLE,
            slot_id="page-1",
            matches=[
                {"marker": marker_for_role_slot(ROLE, "page-1"), "container_id": "s", "element_id": "e1"},
                {"marker": marker_for_role_slot(ROLE, "page-1"), "container_id": "s", "element_id": "e2"},
            ],
        )


def test_two_slots_of_one_role_resolve_independently() -> None:
    first = _target(slot_id="page-1", marker=marker_for_role_slot(ROLE, "page-1"))
    second = _target(slot_id="page-2", marker=marker_for_role_slot(ROLE, "page-2"))
    assert (first.slot_id, second.slot_id) == ("page-1", "page-2")
    assert first.marker != second.marker


def test_placement_request_rejects_slot_mismatch() -> None:
    target = _target(slot_id="page-1", marker=marker_for_role_slot(ROLE, "page-1"))
    with pytest.raises(VisualPlacementError, match="does not bind"):
        build_placement_request(
            selected_asset={
                "asset_id": "asset-1",
                "drive_file_id": "file-1",
                "content_identity": dict(CONTENT_IDENTITY),
            },
            role_id=ROLE,
            slot_id="page-2",
            source_plan_id="plan-1",
            target=target,
        )


# --- Per-slot receipts ---------------------------------------------------------

def _receipt(request, **overrides):
    base = {
        "state": "placed",
        "asset_id": request.asset_id,
        "drive_file_id": request.drive_file_id,
        "role_id": request.role_id,
        "slot_id": request.slot_id,
        "artifact_type": request.target.artifact_type,
        "artifact_id": request.target.artifact_id,
        "artifact_revision_id": request.target.artifact_revision_id,
        "marker": request.target.marker,
        "container_id": request.target.container_id,
        "content_identity": dict(CONTENT_IDENTITY),
        "inserted_element_id": "image-1",
    }
    base.update(overrides)
    return base


def test_receipt_verifies_per_slot_identity() -> None:
    request = _request(slot_id="page-1", marker=marker_for_role_slot(ROLE, "page-1"))
    verified = verify_placement_receipt(request, _receipt(request))
    assert verified.state == "verified"
    assert verified.slot_id == "page-1"
    with pytest.raises(VisualPlacementError, match="slot_id mismatch"):
        verify_placement_receipt(request, _receipt(request, slot_id="page-2"))


def test_retry_is_safe_compares_slot_bindings() -> None:
    request = _request(slot_id="page-1", marker=marker_for_role_slot(ROLE, "page-1"))
    not_placed = dict(_receipt(request), state="not-placed", inserted_element_id=None)
    assert retry_is_safe(request=request, receipt=not_placed) is True
    assert (
        retry_is_safe(request=request, receipt=dict(not_placed, slot_id="page-2"))
        is False
    )


# --- Slot-keyed completeness ---------------------------------------------------

def test_completeness_keys_on_role_slot_bindings() -> None:
    required = ((ROLE, "page-1"), (ROLE, "page-2"), (OTHER_ROLE, "0"))
    verified = ((ROLE, "page-1"), (OTHER_ROLE, "0"))
    outcome = validate_visual_completeness(
        required_roles=required, verified_roles=verified
    )
    assert outcome.status == "fail"
    assert outcome.missing_roles == (f"{ROLE}:page-2",)


def test_completeness_accepts_plain_role_ids_for_implicit_slot() -> None:
    outcome = validate_visual_completeness(
        required_roles=(ROLE, OTHER_ROLE),
        verified_roles=(ROLE, OTHER_ROLE),
    )
    assert outcome.status == "pass"
    assert outcome.missing_roles == ()


def test_completeness_unresolved_slot_routes_to_manual_review() -> None:
    outcome = validate_visual_completeness(
        required_roles=((ROLE, "page-1"),),
        verified_roles=(),
        unresolved_roles=((ROLE, "page-1"),),
    )
    assert outcome.status == "manual-review"
    assert outcome.unresolved_roles == (f"{ROLE}:page-1",)


# --- Generation context multiplicity -------------------------------------------

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "instructional_workflow_contracts"


def _fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def _ref(stable_id: str):
    return {
        "system": "notion",
        "stable_id": stable_id,
        "exact_location": f"collection://fixture/{stable_id}",
        "verification_evidence": "fixture-read-back",
    }


def _owner(evidence_id: str, decision_key: str, value: str):
    return {
        "evidence_id": evidence_id,
        "owner": "instructional-materials-coach",
        "decision_key": decision_key,
        "value": value,
        "classification": "owner-governed",
        "source_revision": 1,
        "observed_at": "2026-08-28T12:00:00Z",
        "currentness": "current",
        "material": True,
        "relation_resolved": True,
        "reference": _ref(evidence_id),
    }


def _supported_evidence():
    return {
        "contract_version": "curriculum-current-state-evidence-v1",
        "canonical_unit": {"stable_id": "photography-foundations", "status": "active"},
        "request": {
            "action": "make",
            "artifact_type": "worksheet",
            "relative_time": "none",
            "requires_reusable_assets": False,
        },
        "required_decision_keys": ["unit-generation-approval"],
        "owner_evidence": [
            _owner("gate-0", "unit-generation-approval", "ready"),
        ],
        "asset_evidence": [],
    }


def _slotted_visual_plan():
    """Real governed reuse plan for a two-slot role through every producer."""
    from instructional_workflow_contracts.material_requirement import (
        material_requirement_source_fingerprint,
    )
    from instructional_materials_coach.visual_reuse import plan_governed_visual_reuse

    mr = _fixture("valid_material_requirement_v2.json")
    role = dict(mr["visual_direction"]["roles"][0], slots=["page-1", "page-2"])
    mr["visual_direction"]["roles"] = [role]
    mr["visual_direction"]["maximum_visual_count"] = 1
    mr["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(mr)
    plan = plan_governed_visual_reuse(
        mr,
        artifact_manifests=[_fixture("valid_artifact_manifest.json")],
        visual_candidates=[_fixture("valid_visual_asset_compatibility_v2.json")],
        source_revision="visual-library-snapshot-3251",
        changed_dependency_keys=[],
        impact_map={},
    )
    assert plan.outcome == "visuals-ready", plan.outcome
    assert plan.cohesive_visual_plan_result is not None
    return plan


def _lesson_content():
    from instructional_materials_coach.content_spec import content_from_dict

    return content_from_dict(
        {
            "title": "Lesson",
            "objectives": [],
            "slides": [],
            "worksheet_questions": ["What did you change and why?"],
        }
    )


def _requirement():
    return _fixture("valid_material_requirement_v2.json")


def test_shared_asset_appears_once_per_binding_in_context() -> None:
    plan = _slotted_visual_plan()
    # One governed asset shared across the two slots: the reuse plan's
    # per-binding selection carries it twice.
    assert tuple(plan.selected_asset_ids) == ("asset-1", "asset-1")
    content = compose_generation_context(
        _lesson_content(),
        material_requirement=_requirement(),
        current_curriculum_evidence=_supported_evidence(),
        selected_asset_ids=tuple(plan.selected_asset_ids),
        governed_visual_plan=plan.cohesive_visual_plan_result,
    )
    # Multiplicity preserved: the shared asset appears once per binding,
    # not once via asset-ID dedup.
    assert content.context_tokens["context_selected_asset_ids"] == "asset-1 | asset-1"


def test_narrowed_selection_within_plan_bindings_is_accepted() -> None:
    # Teacher decisions (#3252) may legitimately narrow the selection: the
    # supplied multiset must be covered by the plan's bindings, not equal.
    # The token still carries the plan's full binding multiplicity.
    plan = _slotted_visual_plan()
    content = compose_generation_context(
        _lesson_content(),
        material_requirement=_requirement(),
        current_curriculum_evidence=_supported_evidence(),
        selected_asset_ids=("asset-1",),
        governed_visual_plan=plan.cohesive_visual_plan_result,
    )
    assert content.context_tokens["context_selected_asset_ids"] == "asset-1 | asset-1"


def test_unplanned_asset_still_rejected() -> None:
    plan = _slotted_visual_plan()
    with pytest.raises(GenerationContextError, match="does not match"):
        compose_generation_context(
            _lesson_content(),
            material_requirement=_requirement(),
            current_curriculum_evidence=_supported_evidence(),
            selected_asset_ids=("asset-1", "asset-1", "asset-smuggled"),
            governed_visual_plan=plan.cohesive_visual_plan_result,
        )
