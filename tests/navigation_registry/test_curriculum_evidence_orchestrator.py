from __future__ import annotations

import copy

import pytest

from navigation_registry.connectors.curriculum_evidence_orchestrator import (
    CANONICAL_UNIT,
    MATERIALS,
    MODELING,
    PACKET,
    PRODUCTION,
    SOURCE_CONTROL,
    UNIT_ALIGNMENT,
    VISUAL_ASSETS,
    CurriculumReadError,
    CurriculumReadRequest,
    build_curriculum_read_plan,
    orchestrate_curriculum_evidence,
)
from instructional_workflow_contracts.current_curriculum_state import (
    resolve_current_curriculum_state,
)

UNIT_PAGE = "3907ac78-3131-8129-8c73-cd9f6b8e8a7d"


def identity(source: str) -> dict[str, object]:
    return {
        "logical_source": source,
        "data_source_id": f"ds-{source}",
        "human_review_required": False,
    }


def unit() -> dict[str, object]:
    return {
        "stable_id": "photography-foundations",
        "status": "active",
        "provider_page_id": UNIT_PAGE,
    }


def owner(evidence_id: str, decision_key: str, value: str = "ready") -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "owner": f"owner-{decision_key}",
        "decision_key": decision_key,
        "value": value,
        "classification": "owner-governed",
        "source_revision": 1,
        "observed_at": "2026-08-08T12:00:00Z",
        "currentness": "current",
        "material": True,
        "relation_resolved": True,
        "reference": {
            "system": "notion",
            "stable_id": evidence_id,
            "exact_location": f"collection://example/{evidence_id}",
            "verification_evidence": "normalized-read-back",
        },
    }


def source_records(source: str) -> list[dict[str, object]]:
    mapping = {
        UNIT_ALIGNMENT: [owner("unit-1", "unit-generation-approval")],
        MODELING: [owner("modeling-1", "modeling-handoff-ready")],
        PACKET: [owner("packet-1", "packet-generation-gate")],
        MATERIALS: [owner("materials-1", "instructional-materials-readiness")],
        SOURCE_CONTROL: [owner("source-1", "source-control-gate")],
        PRODUCTION: [owner("production-1", "production-authorized", "false")],
        VISUAL_ASSETS: [{
            "asset_id": "pf-010",
            "exists": True,
            "approved_for_requested_use": False,
            "approved_student_reuse": False,
            "source_revision": 1,
            "canonical_unit_relation": True,
            "title": "deliberately-not-photography-named",
        }],
    }
    return mapping.get(source, [])


def fake_reader(calls: list[tuple[object, dict[str, object]]]):
    def execute(step, payload):
        calls.append((step, dict(payload)))
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE, "last_edited_time": "2026-08-08T12:00:00Z"}
        return {"results": source_records(step.logical_source)}

    return execute


def sources(plan) -> list[str]:
    return [step.logical_source for step in plan.steps]


def test_image_plan_is_minimal_and_relation_first() -> None:
    plan = build_curriculum_read_plan(CurriculumReadRequest("images", "images"))
    assert sources(plan) == [CANONICAL_UNIT, VISUAL_ASSETS]
    assert plan.steps[-1].relation_first is True


def test_modeling_plan_excludes_packet_and_materials() -> None:
    plan = build_curriculum_read_plan(CurriculumReadRequest("improve-modeling"))
    assert sources(plan) == [CANONICAL_UNIT, MODELING]
    assert PACKET not in sources(plan)
    assert MATERIALS not in sources(plan)


def test_blocker_plan_is_bounded_to_owner_surfaces() -> None:
    plan = build_curriculum_read_plan(CurriculumReadRequest("what-is-blocking"))
    assert sources(plan) == [
        CANONICAL_UNIT,
        UNIT_ALIGNMENT,
        MODELING,
        PACKET,
        SOURCE_CONTROL,
        MATERIALS,
        PRODUCTION,
    ]


def test_slides_plan_selects_required_categories_and_assets() -> None:
    plan = build_curriculum_read_plan(CurriculumReadRequest("make", "slides", requires_reusable_assets=True))
    assert sources(plan) == [
        CANONICAL_UNIT,
        UNIT_ALIGNMENT,
        MODELING,
        PACKET,
        MATERIALS,
        SOURCE_CONTROL,
        PRODUCTION,
        VISUAL_ASSETS,
    ]


def test_worksheet_lesson_and_teach_next_plans_remain_bounded() -> None:
    worksheet = build_curriculum_read_plan(CurriculumReadRequest("make", "worksheet"))
    lesson = build_curriculum_read_plan(CurriculumReadRequest("make", "lesson", relative_time="tomorrow"))
    teach_next = build_curriculum_read_plan(CurriculumReadRequest("next-teaching"))
    assert VISUAL_ASSETS not in sources(worksheet)
    assert sources(lesson) == sources(teach_next)
    assert PRODUCTION not in sources(lesson)


def test_pf010_is_reached_by_relation_and_provider_filter_is_hidden_downstream() -> None:
    calls = []
    packet = orchestrate_curriculum_evidence(
        request=CurriculumReadRequest("make", "slides", requires_reusable_assets=True),
        canonical_unit=unit(),
        resolve_identity=identity,
        execute_read=fake_reader(calls),
    )
    asset_call = next(payload for step, payload in calls if step.logical_source == VISUAL_ASSETS)
    assert asset_call["relation_filter"] == {
        "property": "Canonical Unit",
        "contains_page_id": "3907ac78313181298c73cd9f6b8e8a7d",
    }
    assert packet["asset_evidence"] == [{
        "asset_id": "pf-010",
        "approved_for_requested_use": False,
        "approved_student_reuse": False,
        "exists": True,
        "source_revision": 1,
    }]
    assert "relation_filter" not in repr(packet)
    assert "deliberately-not-photography-named" not in repr(packet)
    state = resolve_current_curriculum_state(packet)
    assert state.record is not None
    assert state.record.to_dict()["assets"]["matching_asset_exists"] is True
    assert state.record.to_dict()["assets"]["approved_reusable_student_facing_exists"] is False
    assert state.record.to_dict()["authority"]["production_authorized"] is False


def test_identity_drift_fails_closed_before_provider_read() -> None:
    calls = []

    def drifted(source: str):
        value = identity(source)
        value["logical_source"] = "wrong-source"
        return value

    with pytest.raises(CurriculumReadError, match="identity drift"):
        orchestrate_curriculum_evidence(
            request=CurriculumReadRequest("images", "images"),
            canonical_unit=unit(),
            resolve_identity=drifted,
            execute_read=fake_reader(calls),
        )
    assert calls == []


def test_live_unit_identity_mismatch_fails_closed() -> None:
    def reader(step, payload):
        if step.logical_source == CANONICAL_UNIT:
            return {"id": "00000000-0000-0000-0000-000000000000"}
        return {"results": []}

    with pytest.raises(CurriculumReadError, match="identity mismatch"):
        orchestrate_curriculum_evidence(
            request=CurriculumReadRequest("images", "images"),
            canonical_unit=unit(),
            resolve_identity=identity,
            execute_read=reader,
        )


def test_missing_permission_and_stale_provider_states_are_bounded() -> None:
    for status in ("missing", "not-found", "permission-denied", "stale", "unresolved"):
        def reader(step, payload, status=status):
            if step.logical_source == CANONICAL_UNIT:
                return {"id": UNIT_PAGE}
            return {"status": status}

        packet = orchestrate_curriculum_evidence(
            request=CurriculumReadRequest("images", "images"),
            canonical_unit=unit(),
            resolve_identity=identity,
            execute_read=reader,
        )
        assert packet["asset_evidence"] == []


def test_tomorrow_does_not_invent_current_context() -> None:
    calls = []
    packet = orchestrate_curriculum_evidence(
        request=CurriculumReadRequest("make", "lesson", relative_time="tomorrow"),
        canonical_unit=unit(),
        resolve_identity=identity,
        execute_read=fake_reader(calls),
    )
    assert "current_context" not in packet
    state = resolve_current_curriculum_state(packet)
    assert state.record is not None
    assert "routing-current-day-missing" in state.record.to_dict()["blockers"]


def test_inputs_are_not_mutated_and_normal_tests_need_no_credentials() -> None:
    original = unit()
    before = copy.deepcopy(original)
    calls = []
    orchestrate_curriculum_evidence(
        request=CurriculumReadRequest("images", "images"),
        canonical_unit=original,
        resolve_identity=identity,
        execute_read=fake_reader(calls),
    )
    assert original == before
    assert calls


def test_malformed_or_overbound_results_fail_closed() -> None:
    def malformed(step, payload):
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE}
        return "not-a-result"

    with pytest.raises(CurriculumReadError, match="malformed"):
        orchestrate_curriculum_evidence(
            request=CurriculumReadRequest("images", "images"),
            canonical_unit=unit(),
            resolve_identity=identity,
            execute_read=malformed,
        )

    def overbound(step, payload):
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE}
        return {"results": [{"asset_id": f"asset-{index}"} for index in range(25)]}

    with pytest.raises(CurriculumReadError, match="exceeds bound"):
        orchestrate_curriculum_evidence(
            request=CurriculumReadRequest("images", "images"),
            canonical_unit=unit(),
            resolve_identity=identity,
            execute_read=overbound,
        )
