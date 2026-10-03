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
            "library_reference": {
                "page_id": "notion-page-pf-010",
                "drive_file_id": "drive-file-pf-010",
            },
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
    assert sources(plan) == [CANONICAL_UNIT, VISUAL_ASSETS, VISUAL_ASSETS]
    assert plan.steps[1].relation_first is True
    assert plan.steps[1].reuse_scope == "unit-specific"
    # #3253: the coursewide step reuses the same source/executor with no
    # unit-relation requirement and no fabricated relation.
    assert plan.steps[2].relation_first is False
    assert plan.steps[2].reuse_scope == "coursewide"


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
        VISUAL_ASSETS,
    ]
    assert plan.steps[-2].relation_first is True
    assert plan.steps[-1].reuse_scope == "coursewide"


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
    asset_calls = [payload for step, payload in calls if step.logical_source == VISUAL_ASSETS]
    assert asset_calls[0]["relation_filter"] == {
        "property": "Canonical Unit",
        "contains_page_id": "3907ac78313181298c73cd9f6b8e8a7d",
    }
    # #3253: the coursewide step selects on the reusable checkbox, never a
    # fabricated unit relation.
    assert "relation_filter" not in asset_calls[1]
    assert asset_calls[1]["property_filter"] == {
        "property": "Reusable Across Units?",
        "checkbox": {"equals": True},
    }
    # The same asset returned by both steps is deduplicated; the
    # relation-first (unit-specific) record wins.
    assert packet["asset_evidence"] == [{
        "asset_id": "pf-010",
        "approved_for_requested_use": False,
        "approved_student_reuse": False,
        "exists": True,
        "source_revision": 1,
        "reuse_scope": "unit-specific",
        "reuse_status": "unknown",
        "library_reference": {
            "page_id": "notion-page-pf-010",
            "drive_file_id": "drive-file-pf-010",
        },
    }]
    assert "relation_filter" not in repr(packet)
    assert "deliberately-not-photography-named" not in repr(packet)
    assert packet["asset_evidence"][0]["library_reference"] == {
        "page_id": "notion-page-pf-010",
        "drive_file_id": "drive-file-pf-010",
    }
    state = resolve_current_curriculum_state(packet)
    assert state.record is not None
    record = state.record.to_dict()
    assert record["assets"]["matching_asset_exists"] is True
    assert record["assets"]["approved_reusable_student_facing_exists"] is False
    assert "asset-reusable-unavailable" in record["blockers"]
    assert record["disposition"] == "blocked"
    assert record["authority"]["production_authorized"] is False



def test_raw_notion_visual_asset_page_becomes_bounded_unapproved_evidence() -> None:
    def reader(step, payload):
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE}
        assert step.logical_source == VISUAL_ASSETS
        if step.relation_first:
            assert payload["relation_filter"]["property"] == "Canonical Unit"
        else:
            # #3253: coursewide step never carries a relation filter.
            assert "relation_filter" not in payload
            assert payload["property_filter"]["property"] == "Reusable Across Units?"
        return {
            "results": [{
                "id": "3907ac78-3131-8111-9999-aaaaaaaaaaaa",
                "last_edited_time": "2026-09-25T12:00:00Z",
                "properties": {
                    "Asset Title": {
                        "type": "title",
                        "title": [{"plain_text": "Camera Diagram"}],
                    },
                    "Canonical Unit": {
                        "type": "relation",
                        "relation": [{"id": UNIT_PAGE}],
                    },
                },
            }]
        }

    packet = orchestrate_curriculum_evidence(
        request=CurriculumReadRequest("images", "images"),
        canonical_unit=unit(),
        resolve_identity=identity,
        execute_read=reader,
    )

    assert packet["asset_evidence"] == []
    # #3254: no governed Asset ID on the page -> explicit incomplete-evidence,
    # never a page-UUID substitution, never absence, never approval.
    assert packet["incomplete_asset_evidence"] == [{
        "page_id": "3907ac78-3131-8111-9999-aaaaaaaaaaaa",
        "projection_status": "incomplete-evidence",
        "evidence_gaps": [
            "identity: no governed Asset ID on the Notion record",
            "drive binding: no Drive File ID on the Notion record",
        ],
    }]
    state = resolve_current_curriculum_state(packet)
    assert state.record is not None
    assert state.record.to_dict()["assets"]["matching_asset_exists"] is False
    # Incomplete identity is not absence: the resolver must not claim it.
    assert "asset-approval-ambiguous" not in state.record.to_dict()["assets"].get("reason_codes", [])


def test_raw_notion_visual_asset_with_governed_asset_id_becomes_evidence() -> None:
    """#3254: a page carrying the governed Asset ID projects to asset evidence."""
    def reader(step, payload):
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE}
        assert step.logical_source == VISUAL_ASSETS
        return {
            "results": [{
                "id": "3907ac78-3131-8111-9999-bbbbbbbbbbbb",
                "last_edited_time": "2026-09-25T12:00:00Z",
                "properties": {
                    "Asset Title": {
                        "type": "title",
                        "title": [{"plain_text": "Camera Diagram"}],
                    },
                    "Asset ID": {
                        "type": "rich_text",
                        "rich_text": [{"plain_text": "VA-20260925-0001"}],
                    },
                    "Drive File ID": {
                        "type": "rich_text",
                        "rich_text": [{"plain_text": "drive-file-1"}],
                    },
                    "Reuse status": {
                        "type": "status",
                        "status": {"name": "approved"},
                    },
                    "Canonical Unit": {
                        "type": "relation",
                        "relation": [{"id": UNIT_PAGE}],
                    },
                },
            }]
        }

    packet = orchestrate_curriculum_evidence(
        request=CurriculumReadRequest("images", "images"),
        canonical_unit=unit(),
        resolve_identity=identity,
        execute_read=reader,
    )

    assert packet["asset_evidence"] == [{
        "asset_id": "VA-20260925-0001",
        "exists": True,
        "approved_for_requested_use": True,
        "approved_student_reuse": None,
        "source_revision": 1,
        "reuse_scope": "unit-specific",
        "reuse_status": "unknown",
        "library_reference": {
            "page_id": "3907ac78-3131-8111-9999-bbbbbbbbbbbb",
            "drive_file_id": "drive-file-1",
        },
    }]
    assert "incomplete_asset_evidence" not in packet
    state = resolve_current_curriculum_state(packet)
    assert state.record is not None
    assert state.record.to_dict()["assets"]["matching_asset_exists"] is True



def test_raw_notion_visual_asset_zero_match_stays_explicitly_empty() -> None:
    def reader(step, payload):
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE}
        return {"results": []}

    packet = orchestrate_curriculum_evidence(
        request=CurriculumReadRequest("images", "images"),
        canonical_unit=unit(),
        resolve_identity=identity,
        execute_read=reader,
    )

    assert packet["asset_evidence"] == []
    state = resolve_current_curriculum_state(packet)
    assert state.record is not None
    assert state.record.to_dict()["assets"]["matching_asset_exists"] is False



def test_raw_notion_asset_missing_properties_fails_closed_instead_of_looking_empty() -> None:
    def reader(step, payload):
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE}
        return {"results": [{"id": "raw-asset-without-properties"}]}

    with pytest.raises(CurriculumReadError, match="missing required asset_id"):
        orchestrate_curriculum_evidence(
            request=CurriculumReadRequest("images", "images"),
            canonical_unit=unit(),
            resolve_identity=identity,
            execute_read=reader,
        )


def test_raw_notion_owner_page_fails_closed_until_source_schema_is_verified() -> None:
    def reader(step, payload):
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE}
        return {
            "results": [{
                "id": "3907ac78-3131-8222-9999-bbbbbbbbbbbb",
                "properties": {
                    "Decision": {
                        "type": "rich_text",
                        "rich_text": [{"plain_text": "ready"}],
                    }
                },
            }]
        }

    with pytest.raises(
        CurriculumReadError,
        match="requires a verified provider-neutral schema mapping",
    ):
        orchestrate_curriculum_evidence(
            request=CurriculumReadRequest("improve-modeling"),
            canonical_unit=unit(),
            resolve_identity=identity,
            execute_read=reader,
        )



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


@pytest.mark.parametrize("review_flag", ["true", 1])
def test_malformed_review_flag_fails_before_provider_read(review_flag: object) -> None:
    calls = []

    def malformed(source: str):
        value = identity(source)
        value["human_review_required"] = review_flag
        return value

    with pytest.raises(CurriculumReadError, match="malformed review flag"):
        orchestrate_curriculum_evidence(
            request=CurriculumReadRequest("images", "images"),
            canonical_unit=unit(),
            resolve_identity=malformed,
            execute_read=fake_reader(calls),
        )
    assert calls == []


@pytest.mark.parametrize("data_source_id", [1, ""])
def test_malformed_data_source_id_fails_before_source_read(data_source_id: object) -> None:
    calls = []

    def malformed(source: str):
        value = identity(source)
        if source == VISUAL_ASSETS:
            value["data_source_id"] = data_source_id
        return value

    with pytest.raises(CurriculumReadError, match="data-source identity"):
        orchestrate_curriculum_evidence(
            request=CurriculumReadRequest("images", "images"),
            canonical_unit=unit(),
            resolve_identity=malformed,
            execute_read=fake_reader(calls),
        )
    assert [step.logical_source for step, _ in calls] == [CANONICAL_UNIT]


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


@pytest.mark.parametrize("status", ["missing", "not-found", "permission-denied", "stale", "unresolved"])
def test_provider_failure_states_fail_closed(status: str) -> None:
    def reader(step, payload):
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE}
        return {"status": status}

    with pytest.raises(CurriculumReadError, match=f"provider {status}"):
        orchestrate_curriculum_evidence(
            request=CurriculumReadRequest("what-is-blocking"),
            canonical_unit=unit(),
            resolve_identity=identity,
            execute_read=reader,
        )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("exists", "false"),
        ("approved_for_requested_use", "false"),
        ("approved_student_reuse", 0),
    ],
)
def test_asset_boolean_fields_require_actual_booleans(field: str, bad_value: object) -> None:
    def reader(step, payload):
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE}
        asset = source_records(VISUAL_ASSETS)[0]
        asset[field] = bad_value
        return {"results": [asset]}

    with pytest.raises(CurriculumReadError, match="malformed asset boolean"):
        orchestrate_curriculum_evidence(
            request=CurriculumReadRequest("images", "images"),
            canonical_unit=unit(),
            resolve_identity=identity,
            execute_read=reader,
        )


def test_aggregate_owner_evidence_bound_fails_closed() -> None:
    def reader(step, payload):
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE}
        records = [owner(f"{step.logical_source}-{index}", f"decision-{step.logical_source}-{index}") for index in range(5)]
        return {"results": records}

    with pytest.raises(CurriculumReadError, match="owner evidence exceeds handoff bound"):
        orchestrate_curriculum_evidence(
            request=CurriculumReadRequest("what-is-blocking"),
            canonical_unit=unit(),
            resolve_identity=identity,
            execute_read=reader,
        )


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
