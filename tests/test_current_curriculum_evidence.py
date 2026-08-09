from __future__ import annotations

import copy

import pytest

from instructional_workflow_contracts.common import ContractValidationError, ValidationStatus
from instructional_workflow_contracts.current_curriculum_evidence import (
    assemble_current_curriculum_evidence,
)
from instructional_workflow_contracts.current_curriculum_state import (
    INPUT_CONTRACT_ID,
    resolve_current_curriculum_state,
)


def ref(stable_id: str) -> dict[str, object]:
    return {
        "system": "notion",
        "stable_id": stable_id,
        "exact_location": f"collection://example/{stable_id}",
        "verification_evidence": "normalized-read-back",
    }


def owner(
    evidence_id: str,
    decision_key: str,
    *,
    classification: str = "owner-governed",
    value: str = "ready",
    currentness: str = "current",
    material: bool = True,
    relation_resolved: bool = True,
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "owner": f"owner-{decision_key}",
        "decision_key": decision_key,
        "value": value,
        "classification": classification,
        "source_revision": 1,
        "observed_at": "2026-08-08T12:00:00Z",
        "currentness": currentness,
        "material": material,
        "relation_resolved": relation_resolved,
        "reference": ref(evidence_id),
    }


def pf010(*, related: bool = True) -> dict[str, object]:
    return {
        "asset_id": "pf-010",
        "exists": True,
        "approved_for_requested_use": False,
        "approved_student_reuse": False,
        "source_revision": 1,
        "canonical_unit_relation": related,
    }


def unit() -> dict[str, object]:
    return {"stable_id": "photography-foundations", "status": "active"}


def request(action: str, artifact_type: str, *, assets: bool = False, relative: str = "none") -> dict[str, object]:
    return {
        "action": action,
        "artifact_type": artifact_type,
        "relative_time": relative,
        "requires_reusable_assets": assets,
    }


def assemble(**kwargs):
    return assemble_current_curriculum_evidence(canonical_unit=unit(), **kwargs)


def test_images_request_is_asset_only_and_relation_first() -> None:
    packet = assemble(
        request=request("what-images-exist", "images"),
        owner_evidence=[owner("modeling-1", "modeling-handoff-ready")],
        asset_evidence=[pf010(), {**pf010(related=False), "asset_id": "keyword-only"}],
    )
    assert packet["contract_version"] == INPUT_CONTRACT_ID
    assert packet["owner_evidence"] == []
    assert [item["asset_id"] for item in packet["asset_evidence"]] == ["pf-010"]
    assert "canonical_unit_relation" not in packet["asset_evidence"][0]


def test_asset_without_relation_marker_is_rejected() -> None:
    unbound = pf010()
    unbound.pop("canonical_unit_relation")
    packet = assemble(
        request=request("what-images-exist", "images"),
        asset_evidence=[unbound],
    )
    assert packet["asset_evidence"] == []


def test_modeling_request_excludes_packet_and_material_evidence() -> None:
    packet = assemble(
        request=request("improve-modeling", "none"),
        owner_evidence=[
            owner("modeling-1", "modeling-handoff-ready"),
            owner("packet-1", "packet-generation-gate"),
            owner("materials-1", "instructional-materials-readiness"),
        ],
    )
    assert [item["decision_key"] for item in packet["owner_evidence"]] == [
        "modeling-handoff-ready"
    ]
    assert packet["required_decision_keys"] == ["modeling-handoff-ready"]


def test_blocker_request_keeps_only_material_owner_evidence() -> None:
    packet = assemble(
        request=request("what-is-blocking", "none"),
        owner_evidence=[
            owner("owner-1", "unit-generation-approval"),
            owner("advisory-1", "routing-note", classification="agent-suggested", material=False),
        ],
    )
    assert [item["evidence_id"] for item in packet["owner_evidence"]] == ["owner-1"]
    assert packet["required_decision_keys"] == []


def test_slides_request_selects_bounded_required_categories() -> None:
    packet = assemble(
        request=request("make", "slides", assets=True),
        owner_evidence=[
            owner("unit-1", "unit-generation-approval"),
            owner("modeling-1", "modeling-handoff-ready"),
            owner("packet-1", "packet-generation-gate"),
            owner("materials-1", "instructional-materials-readiness"),
            owner("source-1", "source-control-gate"),
            owner("production-1", "production-authorized", value="false"),
            owner("unrelated-1", "unrelated-owner-state"),
        ],
        asset_evidence=[pf010()],
    )
    keys = {item["decision_key"] for item in packet["owner_evidence"]}
    assert "unrelated-owner-state" not in keys
    assert keys == set(packet["required_decision_keys"])
    assert packet["asset_evidence"][0]["asset_id"] == "pf-010"


def test_next_teaching_action_uses_bounded_lesson_categories() -> None:
    packet = assemble(
        request=request("next-teaching", "none"),
        owner_evidence=[
            owner("unit-1", "unit-generation-approval"),
            owner("modeling-1", "modeling-handoff-ready"),
            owner("packet-1", "packet-generation-gate"),
            owner("materials-1", "instructional-materials-readiness"),
            owner("unrelated-1", "unrelated-owner-state"),
        ],
    )
    keys = {item["decision_key"] for item in packet["owner_evidence"]}
    assert "unrelated-owner-state" not in keys
    assert keys == set(packet["required_decision_keys"])


def test_pf010_teacher_facing_boundary_stays_non_student_reusable() -> None:
    packet = assemble(
        request=request("make", "slides", assets=True),
        owner_evidence=[owner("unit-1", "unit-generation-approval")],
        asset_evidence=[pf010()],
    )
    result = resolve_current_curriculum_state(packet)
    assert result.record is not None
    state = result.record.to_dict()
    assert state["assets"]["matching_asset_exists"] is True
    assert state["assets"]["approved_reusable_student_facing_exists"] is False
    assert state["authority"]["production_authorized"] is False


def test_owner_classification_and_conflicts_are_preserved_for_973() -> None:
    packet = assemble(
        request=request("bounded-context", "none"),
        owner_evidence=[
            owner("owner-1", "unit-generation-approval", value="ready"),
            owner(
                "display-1",
                "unit-generation-approval",
                classification="display-derived",
                value="blocked",
            ),
        ],
    )
    classifications = {item["classification"] for item in packet["owner_evidence"]}
    assert classifications == {"owner-governed", "display-derived"}
    result = resolve_current_curriculum_state(packet)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED


def test_stale_and_unresolved_evidence_are_not_reconciled() -> None:
    packet = assemble(
        request=request("bounded-context", "none"),
        owner_evidence=[
            owner("stale-1", "unit-generation-approval", currentness="stale"),
            owner("relation-1", "packet-generation-gate", relation_resolved=False),
        ],
    )
    stale = next(item for item in packet["owner_evidence"] if item["evidence_id"] == "stale-1")
    assert stale["currentness"] == "stale"
    result = resolve_current_curriculum_state(packet)
    assert result.record is not None
    assert result.status in {ValidationStatus.BLOCKED, ValidationStatus.MANUAL_REVIEW_REQUIRED}
    assert "source-stale-material" in result.record.to_dict()["reason_codes"]


def test_tomorrow_without_current_day_is_left_for_973_to_fail_closed() -> None:
    packet = assemble(request=request("make", "lesson", relative="tomorrow"))
    assert "current_context" not in packet
    result = resolve_current_curriculum_state(packet)
    assert result.status is ValidationStatus.BLOCKED
    assert "routing-current-day-missing" in result.record.to_dict()["blockers"]


def test_equivalent_input_order_is_deterministic_and_inputs_are_immutable() -> None:
    owners = [
        owner("packet-1", "packet-generation-gate"),
        owner("unit-1", "unit-generation-approval"),
    ]
    assets = [pf010()]
    owners_before = copy.deepcopy(owners)
    assets_before = copy.deepcopy(assets)
    first = assemble(request=request("make", "slides", assets=True), owner_evidence=owners, asset_evidence=assets)
    second = assemble(
        request=request("make", "slides", assets=True),
        owner_evidence=list(reversed(owners)),
        asset_evidence=list(reversed(assets)),
    )
    assert first == second
    assert owners == owners_before
    assert assets == assets_before


def test_provider_specific_relation_marker_is_not_exposed_to_973() -> None:
    packet = assemble(
        request=request("what-images-exist", "images"),
        asset_evidence=[pf010()],
    )
    serialized = repr(packet)
    assert "canonical_unit_relation" not in serialized
    assert "LIKE '%" not in serialized
    assert "3907ac78313181298c73cd9f6b8e8a7d" not in serialized


def test_missing_required_owner_evidence_remains_missing_for_973() -> None:
    packet = assemble(request=request("make", "slides", assets=True), asset_evidence=[pf010()])
    result = resolve_current_curriculum_state(packet)
    assert result.status is ValidationStatus.BLOCKED
    assert "dependency-owner-evidence-missing" in result.record.to_dict()["blockers"]


def test_bounds_and_malformed_inputs_fail_closed() -> None:
    too_many = [owner(f"owner-{index}", "unit-generation-approval") for index in range(25)]
    with pytest.raises(ContractValidationError):
        assemble(request=request("bounded-context", "none"), owner_evidence=too_many)
    with pytest.raises(ContractValidationError):
        assemble_current_curriculum_evidence(request=None, canonical_unit=unit())
