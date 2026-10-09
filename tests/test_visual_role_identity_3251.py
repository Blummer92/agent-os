"""Regression tests for #3251 — semantic visual-role identity.

Covers the still-broken mechanisms through the real producers
(validate_material_requirement -> plan_visual_needs ->
filter_approved_visual_candidates -> plan_cohesive_visual_set, plus the
Asset Picker and the #2890 revision-QA consumer):

- F1: role_id stability across irrelevant revisions (the semantic-key
  identity landed via #3252; these tests pin it for #3251).
- F2/S11: the candidate filter evaluates each role individually --
  same-type roles no longer collapse on role_type.
- F3/S8: one governed asset may fill multiple compatible roles/slots when
  independently compatibility-passing per binding.
- F4: one role may declare N explicit slots; bindings key on
  (role_id, slot_id).
- F5: picker selections carry their (role_id, slot_id) binding; identity
  conflicts fail closed.
- F6: an author-supplied concept reference survives onto the planned role.
- Caps: MAX_SLOTS_PER_ROLE=16, MAX_ROLE_SLOT_BINDINGS=64.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from instructional_workflow_contracts import ValidationStatus
from instructional_workflow_contracts.cohesive_visual_plan import (
    plan_cohesive_visual_set,
)
from instructional_workflow_contracts.material_requirement import (
    MAX_ROLE_SLOT_BINDINGS,
    MAX_SLOTS_PER_ROLE,
    material_requirement_source_fingerprint,
    validate_material_requirement,
)
from instructional_workflow_contracts.visual_asset_candidates import (
    V2_CONTRACT_ID,
    filter_approved_visual_candidates,
)
from instructional_workflow_contracts.visual_asset_picker import (
    AssetCandidate,
    AssetPickerError,
    AssetPickerIntent,
    check_reference_role_binding,
    resolve_visual_asset_picker,
)
from instructional_workflow_contracts.visual_needs import plan_visual_needs

FIXTURES = Path(__file__).parent / "fixtures" / "instructional_workflow_contracts"
READ_REVISION = "visual-library-read-3251"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _requirement_with_roles(roles: list[dict], maximum_visual_count: int) -> dict:
    """Raw MR v2 with the given visual roles, re-signed through the producer."""
    mr = _load("valid_material_requirement_v2.json")
    mr["visual_direction"]["roles"] = roles
    mr["visual_direction"]["maximum_visual_count"] = maximum_visual_count
    mr["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(mr)
    return mr


def _validated_requirement(roles: list[dict], maximum_visual_count: int):
    result = validate_material_requirement(_requirement_with_roles(roles, maximum_visual_count))
    assert result.status is ValidationStatus.VALID, result.reason_codes
    assert result.record is not None
    return result.record


def _plan(roles: list[dict], maximum_visual_count: int):
    result = plan_visual_needs(_validated_requirement(roles, maximum_visual_count))
    assert result.status is ValidationStatus.VALID, result.reason_codes
    assert result.record is not None
    return result.record


def _base_role() -> dict:
    return {
        "instructional_purpose": "Show students a completed example.",
        "intended_placement": "example-adjacent",
        "orientation": "landscape",
        "requirement_state": "required",
        "role_type": "worked-example",
    }


def _role_ids(plan_record) -> list[str]:
    payload = plan_record.to_dict()
    return [role["role_id"] for role in payload["required_roles"]]


def _filter(plan_record, raws):
    result = filter_approved_visual_candidates(
        plan_record,
        raws,
        source_revision=READ_REVISION,
        contract_version=V2_CONTRACT_ID,
    )
    assert result.status is ValidationStatus.VALID, result.reason_codes
    assert result.record is not None
    return result


def _compatibility_for(role_types: list[str], orientation: str = "landscape") -> dict:
    raw = _load("valid_visual_asset_compatibility_v2.json")
    raw["compatibility_evidence"]["purpose"]["role_types"] = list(role_types)
    raw["compatibility_evidence"]["approved_use"]["role_types"] = list(role_types)
    raw["compatibility_evidence"]["orientation"]["orientation"] = orientation
    return raw


# --- F1: role identity stable across irrelevant revisions --------------------

def test_role_ids_stable_across_metadata_churn() -> None:
    first = _plan([_base_role()], 1)
    raw = _requirement_with_roles([_base_role()], 1)
    # Record churn excluded from the source fingerprint: bump created_at and
    # re-identify exactly as a producer would.
    raw["identity"]["created_at"] = "2026-10-09T00:00:00Z"
    raw["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(raw)
    second = _plan_from_raw(raw)
    assert _role_ids(first) == _role_ids(second)


def _plan_from_raw(raw: dict):
    validated = validate_material_requirement(raw)
    assert validated.status is ValidationStatus.VALID, validated.reason_codes
    planned = plan_visual_needs(validated.record)
    assert planned.status is ValidationStatus.VALID, planned.reason_codes
    assert planned.record is not None
    return planned.record


def test_role_ids_stable_across_irrelevant_content_edit() -> None:
    first = _plan([_base_role()], 1)
    raw = _requirement_with_roles([_base_role()], 1)
    raw["instructional"]["purpose"] = "A completely reworded lesson purpose."
    raw["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(raw)
    second = _plan_from_raw(raw)
    # The fingerprint changes (content changed) but no role's semantics did.
    assert first.fingerprint != second.fingerprint
    assert _role_ids(first) == _role_ids(second)


def test_single_role_semantic_edit_changes_only_that_role() -> None:
    other = dict(
        _base_role(),
        role_type="comparison",
        instructional_purpose="Compare effective and ineffective choices.",
        intended_placement="section",
        orientation="square",
    )
    first = _plan([_base_role(), other], 2)
    edited = dict(
        _base_role(),
        instructional_purpose="Show students a revised completed example.",
    )
    second = _plan([edited, other], 2)
    # Roles sort comparison-first; compare by role_type, not position.
    first_by_type = {r["role_type"]: r["role_id"] for r in first.to_dict()["required_roles"]}
    second_by_type = {r["role_type"]: r["role_id"] for r in second.to_dict()["required_roles"]}
    assert first_by_type["worked-example"] != second_by_type["worked-example"]
    assert first_by_type["comparison"] == second_by_type["comparison"]


def test_revision_qa_passes_across_irrelevant_revision() -> None:
    pytest.importorskip(
        "instructional_materials_coach",
        reason="IMC package not installed in this environment",
    )
    from instructional_materials_coach.worksheet_revision_qa import (
        validate_revision_preserves_required_visual_roles,
    )

    first = _plan([_base_role()], 1)
    raw = _requirement_with_roles([_base_role()], 1)
    raw["identity"]["created_at"] = "2026-10-09T00:00:00Z"
    raw["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(raw)
    second = _plan_from_raw(raw)
    outcome = validate_revision_preserves_required_visual_roles(
        prior_required_role_ids=tuple(_role_ids(first)),
        revised_required_role_ids=tuple(_role_ids(second)),
    )
    assert outcome.passed


# --- F2/S11: filter evaluates each role individually -------------------------

def test_filter_evaluates_same_type_roles_individually() -> None:
    portrait = dict(
        _base_role(),
        instructional_purpose="Show students a second completed example in portrait.",
        intended_placement="section",
        orientation="portrait",
    )
    plan = _plan([_base_role(), portrait], 2)
    payload = plan.to_dict()
    assert len(payload["required_roles"]) == 2
    landscape_id = payload["required_roles"][0]["role_id"]
    portrait_id = payload["required_roles"][1]["role_id"]
    assert landscape_id != portrait_id

    filtered = _filter(plan, [_compatibility_for(["worked-example"], "landscape")])
    filtered_payload = filtered.record.to_dict()
    assert len(filtered_payload["eligible"]) == 1
    assert filtered_payload["rejected"] == []
    # Only the landscape role admitted the candidate -- the portrait
    # sibling was judged on its own terms, not collapsed away.
    assert filtered_payload["eligible"][0]["matched_role_ids"] == [landscape_id]
    assert portrait_id not in filtered_payload["eligible"][0]["matched_role_ids"]


def test_filter_portrait_candidate_matches_only_portrait_role() -> None:
    portrait = dict(
        _base_role(),
        instructional_purpose="Show students a second completed example in portrait.",
        intended_placement="section",
        orientation="portrait",
    )
    plan = _plan([_base_role(), portrait], 2)
    landscape_id = plan.to_dict()["required_roles"][0]["role_id"]
    portrait_id = plan.to_dict()["required_roles"][1]["role_id"]
    filtered = _filter(plan, [_compatibility_for(["worked-example"], "portrait")])
    filtered_payload = filtered.record.to_dict()
    assert len(filtered_payload["eligible"]) == 1
    assert filtered_payload["eligible"][0]["matched_role_ids"] == [portrait_id]
    assert landscape_id not in filtered_payload["eligible"][0]["matched_role_ids"]


def test_filter_rejection_names_no_role_when_nothing_matches() -> None:
    plan = _plan([_base_role()], 1)
    filtered = _filter(plan, [_compatibility_for(["comparison"], "landscape")])
    filtered_payload = filtered.record.to_dict()
    assert filtered_payload["eligible"] == []
    assert len(filtered_payload["rejected"]) == 1
    assert filtered_payload["rejected"][0]["reason_codes"] == ["visual-candidate-role-mismatch"]


# --- F3/S8: shared asset across compatible roles -----------------------------

def test_shared_asset_fills_two_compatible_roles() -> None:
    comparison = dict(
        _base_role(),
        role_type="comparison",
        instructional_purpose="Compare two completed examples.",
    )
    plan = _plan([_base_role(), comparison], 2)
    filtered = _filter(
        plan,
        [_compatibility_for(["worked-example", "comparison"], "landscape")],
    )
    assert len(filtered.record.to_dict()["eligible"]) == 1
    planned = plan_cohesive_visual_set(plan, filtered)
    assert planned.status is ValidationStatus.VALID, planned.reason_codes
    payload = planned.record.to_dict()
    assert payload["outcome"] == "complete-set"
    assert payload["unfilled_required_roles"] == []
    assert payload["image_gap_briefs"] == []
    assignments = payload["required_role_assignments"]
    assert len(assignments) == 2
    bindings = {(a["role_id"], a["slot_id"]) for a in assignments}
    assert len(bindings) == 2
    asset_ids = {
        a["selected_candidate"]["asset_reference"]["asset_id"] for a in assignments
    }
    assert asset_ids == {"asset-1"}
    # Each binding carries its own compatibility evidence.
    for assignment in assignments:
        assert sorted(
            assignment["compatibility_evidence"]["approved_use"]["role_types"]
        ) == ["comparison", "worked-example"]


# --- F4: multi-slot roles -----------------------------------------------------

def test_multi_slot_role_produces_per_slot_bindings() -> None:
    role = dict(_base_role(), slots=["page-3", "page-1", "page-2"])
    plan = _plan([role], 1)
    planned_role = plan.to_dict()["required_roles"][0]
    # Slots are canonicalized (sorted) by the requirement contract.
    assert planned_role["slots"] == ["page-1", "page-2", "page-3"]
    filtered = _filter(plan, [_compatibility_for(["worked-example"], "landscape")])
    planned = plan_cohesive_visual_set(plan, filtered)
    assert planned.status is ValidationStatus.VALID, planned.reason_codes
    payload = planned.record.to_dict()
    assert payload["outcome"] == "complete-set"
    assignments = payload["required_role_assignments"]
    assert [(a["slot_id"]) for a in assignments] == ["page-1", "page-2", "page-3"]
    assert {a["role_id"] for a in assignments} == {planned_role["role_id"]}
    # One governed asset shared across the three slots: multiplicity is in
    # the bindings, not in distinct assets.
    assert {
        a["selected_candidate"]["asset_reference"]["asset_id"] for a in assignments
    } == {"asset-1"}


def test_nine_slot_packet_expressible_within_slot_caps() -> None:
    # The 9-page recurring-icon packet: 9 slots are expressible within the
    # recorded role/slot maxima (16/role, 64 total). The cohesive plan's
    # governed 16 KiB result bound separately limits how many full-evidence
    # bindings one plan record can carry (see remaining risks); the
    # five-slot end-to-end case below proves the planner path.
    slots = [f"page-{index}" for index in range(1, 10)]
    role = dict(_base_role(), slots=slots)
    record = _validated_requirement([role], 1)
    planned_role = plan_visual_needs(record).record.to_dict()["required_roles"][0]
    assert planned_role["slots"] == sorted(slots)


def test_four_slot_packet_plans_end_to_end() -> None:
    # The cohesive plan's governed 16 KiB result bound limits how many
    # full-evidence bindings fit in one plan record with this evidence
    # size (4 fit; the bound is orthogonal to the role/slot caps).
    slots = [f"page-{index}" for index in range(1, 5)]
    role = dict(_base_role(), slots=slots)
    plan = _plan([role], 1)
    filtered = _filter(plan, [_compatibility_for(["worked-example"], "landscape")])
    planned = plan_cohesive_visual_set(plan, filtered)
    assert planned.status is ValidationStatus.VALID, planned.reason_codes
    payload = planned.record.to_dict()
    assert payload["outcome"] == "complete-set"
    assert len(payload["required_role_assignments"]) == 4
    assert [a["slot_id"] for a in payload["required_role_assignments"]] == slots
    assert len({a["slot_id"] for a in payload["required_role_assignments"]}) == 4


def test_slot_caps_are_enforced() -> None:
    assert MAX_SLOTS_PER_ROLE == 16
    assert MAX_ROLE_SLOT_BINDINGS == 64
    too_many = dict(_base_role(), slots=[f"s{index}" for index in range(17)])
    result = validate_material_requirement(_requirement_with_roles([too_many], 1))
    assert result.status is ValidationStatus.INVALID
    assert "handoff-oversized" in result.reason_codes
    # 8 roles x 9 slots = 72 bindings exceeds the 64-binding bound.
    roles = [dict(_base_role(), slots=[f"r{index}-s{slot}" for slot in range(9)]) for index in range(8)]
    for index, role in enumerate(roles):
        role["instructional_purpose"] = f"Purpose {index}."
    result = validate_material_requirement(_requirement_with_roles(roles, 8))
    assert result.status is ValidationStatus.INVALID
    assert "handoff-oversized" in result.reason_codes


def test_malformed_slot_ids_fail_closed() -> None:
    # Slot ids must survive the controlled marker syntax: ':' and
    # whitespace are forbidden; duplicates are rejected. (Empty strings
    # are rejected even earlier by JSON normalization, repo-wide.)
    for bad in (["page:1"], ["has space"], ["ok", "ok"]):
        role = dict(_base_role(), slots=bad)
        result = validate_material_requirement(_requirement_with_roles([role], 1))
        assert result.status is ValidationStatus.INVALID, bad


# --- F5: picker per-role selection --------------------------------------------

def _candidate(asset_id: str, role_id: str | None = None, slot_id: str | None = None) -> AssetCandidate:
    return AssetCandidate(
        asset_id=asset_id,
        source_reference="library",
        eligible=True,
        review_status="approved",
        role_id=role_id,
        slot_id=slot_id,
    )


def test_picker_selection_carries_role_and_slot_binding() -> None:
    decision = resolve_visual_asset_picker(
        AssetPickerIntent(
            selection_authority="teacher-select",
            visual_roles=("visual-role-aaa", "visual-role-bbb"),
        ),
        [
            _candidate("asset-a", role_id="visual-role-aaa", slot_id="page-1"),
            _candidate("asset-b", role_id="visual-role-bbb"),
        ],
        selected_asset_ids=("asset-a", "asset-b"),
    )
    assert decision.outcome == "recommended"
    by_asset = {ref.asset_id: ref for ref in decision.selected_references}
    assert by_asset["asset-a"].role_id == "visual-role-aaa"
    assert by_asset["asset-a"].slot_id == "page-1"
    assert by_asset["asset-b"].role_id == "visual-role-bbb"


def test_picker_reference_presented_for_wrong_role_fails_closed() -> None:
    decision = resolve_visual_asset_picker(
        AssetPickerIntent(selection_authority="teacher-select"),
        [_candidate("asset-a", role_id="visual-role-aaa", slot_id="page-1")],
        selected_asset_ids=("asset-a",),
    )
    (reference,) = decision.selected_references
    # The right binding passes.
    check_reference_role_binding(reference, role_id="visual-role-aaa", slot_id="page-1")
    # A different role or slot fails closed -- never silently re-attributed.
    with pytest.raises(AssetPickerError):
        check_reference_role_binding(reference, role_id="visual-role-bbb", slot_id="page-1")
    with pytest.raises(AssetPickerError):
        check_reference_role_binding(reference, role_id="visual-role-aaa", slot_id="page-2")


def test_picker_duplicate_binding_selection_fails_closed() -> None:
    with pytest.raises(AssetPickerError, match="duplicate selection"):
        resolve_visual_asset_picker(
            AssetPickerIntent(selection_authority="teacher-select"),
            [
                _candidate("asset-a", role_id="visual-role-aaa"),
                _candidate("asset-b", role_id="visual-role-aaa"),
            ],
            selected_asset_ids=("asset-a", "asset-b"),
        )


def test_picker_winner_carries_candidate_binding() -> None:
    decision = resolve_visual_asset_picker(
        AssetPickerIntent(),
        [_candidate("asset-a", role_id="visual-role-aaa", slot_id="s1")],
    )
    assert decision.outcome == "recommended"
    (reference,) = decision.selected_references
    assert (reference.role_id, reference.slot_id) == ("visual-role-aaa", "s1")


# --- F6: concept reference survives onto the planned role ----------------------

def test_concept_reference_survives_onto_planned_role() -> None:
    role = dict(_base_role(), concept="fractions")
    plan = _plan([role], 1)
    planned_role = plan.to_dict()["required_roles"][0]
    assert planned_role["concept"] == "fractions"
    # Concept never enters the role identity.
    plain = _plan([_base_role()], 1)
    assert planned_role["role_id"] == plain.to_dict()["required_roles"][0]["role_id"]


# --- Slots never enter role identity ------------------------------------------

def test_slots_do_not_change_role_identity() -> None:
    plain = _plan([_base_role()], 1)
    slotted = _plan([dict(_base_role(), slots=["page-1"])], 1)
    assert (
        plain.to_dict()["required_roles"][0]["role_id"]
        == slotted.to_dict()["required_roles"][0]["role_id"]
    )
