from __future__ import annotations

from pathlib import Path

import pytest

from instructional_workflow_contracts.current_curriculum_state import resolve_current_curriculum_state
from navigation_registry.connectors import curriculum_execution_surface_router
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
    CurriculumReadStep,
)
from navigation_registry.connectors.curriculum_execution_surface_router import (
    FALLBACK_ROUTE,
    READ_ONLY_ACTIONS,
    CurriculumSurfaceError,
    build_scheduler_fallback_read_executor,
    retrieve_curriculum_evidence,
)

UNIT_PAGE = "3907ac78-3131-8129-8c73-cd9f6b8e8a7d"
UNIT_PAGE_COMPACT = "3907ac78313181298c73cd9f6b8e8a7d"


def identity(source: str) -> dict[str, object]:
    return {"logical_source": source, "data_source_id": f"ds-{source}", "human_review_required": False}


def unit() -> dict[str, object]:
    return {"stable_id": "photography-foundations", "status": "active", "provider_page_id": UNIT_PAGE}


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


def teacher_facing_asset() -> dict[str, object]:
    return {
        "asset_id": "pf-010",
        "exists": True,
        "approved_for_requested_use": False,
        "approved_student_reuse": False,
        "source_revision": 1,
        "canonical_unit_relation": True,
        "title": "Photography Foundations hero image",
    }


def source_records(source: str) -> list[dict[str, object]]:
    return {
        UNIT_ALIGNMENT: [owner("unit-1", "unit-generation-approval")],
        MODELING: [owner("modeling-1", "modeling-handoff-ready")],
        PACKET: [owner("packet-1", "packet-generation-gate")],
        MATERIALS: [owner("materials-1", "instructional-materials-readiness")],
        SOURCE_CONTROL: [owner("source-1", "source-control-gate")],
        PRODUCTION: [owner("production-1", "production-authorized", "false")],
        VISUAL_ASSETS: [teacher_facing_asset()],
    }.get(source, [])


def scheduler(calls: list[dict[str, object]], *, result=None):
    def execute(task_payload):
        calls.append(dict(task_payload))
        if result is not None:
            return result
        if task_payload["action"] == "get_page":
            return {"status": "success", "message": "ok", "output": {"id": UNIT_PAGE, "last_edited_time": "2026-08-08T12:00:00Z"}}
        source = str(task_payload["data_source_id"]).removeprefix("ds-")
        return {"status": "success", "message": "ok", "output": {"results": source_records(source), "has_more": False}}
    return execute


def via_agent_os(request: CurriculumReadRequest, calls=None, *, result=None, **kwargs) -> dict[str, object]:
    tasks = calls if calls is not None else []
    execute_read = build_scheduler_fallback_read_executor(execute_scheduler_task=scheduler(tasks, result=result))
    return retrieve_curriculum_evidence(
        request=request,
        canonical_unit=unit(),
        resolve_identity=identity,
        execute_read=execute_read,
        **kwargs,
    )


IMAGES = CurriculumReadRequest("images", "images")
SLIDES = CurriculumReadRequest("make", "slides", requires_reusable_assets=True)


def test_single_governed_route_uses_existing_agent_os_reader() -> None:
    tasks: list[dict[str, object]] = []
    result = via_agent_os(IMAGES, calls=tasks)
    assert result["read_route"] == FALLBACK_ROUTE
    assert tasks
    assert set(result) == {"read_route", "curriculum_evidence"}


def test_missing_governed_executor_fails_closed() -> None:
    with pytest.raises(CurriculumSurfaceError, match="Agent OS read executor"):
        retrieve_curriculum_evidence(
            request=IMAGES,
            canonical_unit=unit(),
            resolve_identity=identity,
            execute_read=None,
        )


def test_governed_reader_builds_only_canonical_936_read_payloads() -> None:
    tasks: list[dict[str, object]] = []
    via_agent_os(SLIDES, calls=tasks)
    actions = {task["action"] for task in tasks}
    assert actions == {"get_page", "query_data_source"}
    assert actions <= READ_ONLY_ACTIONS
    assert [task["page_id"] for task in tasks if task["action"] == "get_page"] == [UNIT_PAGE]
    for task in tasks:
        if task["action"] == "query_data_source":
            assert str(task["data_source_id"]).startswith("ds-")
            assert task["max_pages"] == 1
            assert 1 <= task["page_size"] <= 24
            assert task["max_results"] == task["page_size"]


def test_missing_class_source_binding_fails_closed_for_2283() -> None:
    tasks: list[dict[str, object]] = []
    def unbound(source: str) -> dict[str, object]:
        value = identity(source)
        if source == VISUAL_ASSETS:
            value["data_source_id"] = "   "
        return value
    execute_read = build_scheduler_fallback_read_executor(execute_scheduler_task=scheduler(tasks))
    with pytest.raises(CurriculumReadError):
        retrieve_curriculum_evidence(
            request=IMAGES,
            canonical_unit=unit(),
            resolve_identity=unbound,
            execute_read=execute_read,
        )
    assert [task["action"] for task in tasks] == ["get_page"]


def test_out_of_bound_result_request_fails_closed_before_dispatch() -> None:
    tasks: list[dict[str, object]] = []
    executor = build_scheduler_fallback_read_executor(execute_scheduler_task=scheduler(tasks))
    step = CurriculumReadStep(VISUAL_ASSETS, "query_data_source", relation_first=True)
    with pytest.raises(CurriculumSurfaceError, match="bounded read limit"):
        executor(step, {"identity": identity(VISUAL_ASSETS), "max_results": 500})
    assert tasks == []


@pytest.mark.parametrize("request_", [IMAGES, SLIDES, CurriculumReadRequest("improve-modeling"), CurriculumReadRequest("what-is-blocking"), CurriculumReadRequest("make", "worksheet"), CurriculumReadRequest("next-teaching")])
def test_governed_route_preserves_current_state_semantics(request_: CurriculumReadRequest) -> None:
    packet = via_agent_os(request_)["curriculum_evidence"]
    state = resolve_current_curriculum_state(packet)
    assert state.record is not None


def test_owner_class_currentness_and_provenance_survive_governed_route() -> None:
    packet = via_agent_os(CurriculumReadRequest("what-is-blocking"))["curriculum_evidence"]
    owners = packet["owner_evidence"]
    assert owners
    for record in owners:
        assert record["classification"] == "owner-governed"
        assert record["currentness"] == "current"
        assert record["source_revision"] == 1
        assert record["reference"]["system"] == "notion"
        assert record["reference"]["verification_evidence"] == "normalized-read-back"


def test_canonical_unit_identity_survives_governed_route() -> None:
    packet = via_agent_os(IMAGES)["curriculum_evidence"]
    assert packet["canonical_unit"]["stable_id"] == "photography-foundations"
    assert "provider_page_id" not in packet["canonical_unit"]


def test_image_request_stays_request_sensitive() -> None:
    tasks: list[dict[str, object]] = []
    via_agent_os(IMAGES, calls=tasks)
    queried = [task["data_source_id"] for task in tasks if task["action"] == "query_data_source"]
    assert queried == [f"ds-{VISUAL_ASSETS}"]
    for unrelated in (MODELING, PACKET, MATERIALS, SOURCE_CONTROL, PRODUCTION, UNIT_ALIGNMENT):
        assert f"ds-{unrelated}" not in queried


def test_modeling_request_does_not_reach_packet_or_material_surfaces() -> None:
    tasks: list[dict[str, object]] = []
    via_agent_os(CurriculumReadRequest("improve-modeling"), calls=tasks)
    queried = [task["data_source_id"] for task in tasks if task["action"] == "query_data_source"]
    assert queried == [f"ds-{MODELING}"]


def test_visual_asset_lookup_is_relation_first_in_provider_payload() -> None:
    tasks: list[dict[str, object]] = []
    via_agent_os(IMAGES, calls=tasks)
    asset_task = next(task for task in tasks if task.get("data_source_id") == f"ds-{VISUAL_ASSETS}")
    assert asset_task["filter"] == {"property": "Canonical Unit", "relation": {"contains": UNIT_PAGE_COMPACT}}


def test_provider_filter_syntax_stays_behind_read_boundary() -> None:
    packet = via_agent_os(IMAGES)["curriculum_evidence"]
    rendered = repr(packet)
    assert "relation_filter" not in rendered
    assert "contains_page_id" not in rendered
    assert UNIT_PAGE_COMPACT not in rendered


def test_asset_title_cannot_substitute_for_governed_approval_evidence() -> None:
    packet = via_agent_os(IMAGES)["curriculum_evidence"]
    assert "Photography Foundations hero image" not in repr(packet)
    assert packet["asset_evidence"] == [{"asset_id": "pf-010", "approved_for_requested_use": False, "approved_student_reuse": False, "exists": True, "source_revision": 1}]


def test_teacher_facing_asset_existence_is_not_production_authority() -> None:
    packet = via_agent_os(IMAGES)["curriculum_evidence"]
    state = resolve_current_curriculum_state(packet)
    assert state.record is not None
    record = state.record.to_dict()
    assert record["assets"]["matching_asset_exists"] is True
    assert record["assets"]["approved_reusable_student_facing_exists"] is False
    assert "asset-reusable-unavailable" in record["blockers"]
    assert record["disposition"] == "blocked"
    assert record["authority"]["production_authorized"] is False


@pytest.mark.parametrize("scheduler_result", [{"status": "failure", "message": "source is not shared with the integration"}, {"status": "retryable", "message": "rate limited", "retry_after": 5.0}, {"status": "", "message": "malformed"}])
def test_scheduler_non_success_remains_explicit_and_fails_closed(scheduler_result) -> None:
    with pytest.raises(CurriculumReadError, match="provider unresolved"):
        via_agent_os(IMAGES, result=scheduler_result)


def test_malformed_scheduler_envelopes_fail_closed() -> None:
    for bad in ("not-a-mapping", {"status": "success"}, {"status": "success", "output": {}}):
        executor = build_scheduler_fallback_read_executor(execute_scheduler_task=lambda _payload, value=bad: value)
        step = CurriculumReadStep(VISUAL_ASSETS, "query_data_source", relation_first=True)
        with pytest.raises(CurriculumSurfaceError):
            executor(step, {"identity": identity(VISUAL_ASSETS), "max_results": 5})


def test_relative_time_request_does_not_invent_current_day_context() -> None:
    packet = via_agent_os(CurriculumReadRequest("make", "lesson", relative_time="tomorrow"))["curriculum_evidence"]
    assert "current_context" not in packet
    state = resolve_current_curriculum_state(packet)
    assert state.record is not None
    assert "routing-current-day-missing" in state.record.to_dict()["blockers"]


@pytest.mark.parametrize("action", ["update_page", "create_page", "delete_page", "query_database", "patch_data_source", ""])
def test_no_write_or_unapproved_action_can_reach_scheduler(action: str) -> None:
    tasks: list[dict[str, object]] = []
    executor = build_scheduler_fallback_read_executor(execute_scheduler_task=scheduler(tasks))
    step = CurriculumReadStep(VISUAL_ASSETS, action)
    with pytest.raises(CurriculumSurfaceError, match="non-read action"):
        executor(step, {"identity": identity(VISUAL_ASSETS), "max_results": 5})
    assert tasks == []


def router_source() -> str:
    return Path(curriculum_execution_surface_router.__file__).read_text(encoding="utf-8")


def test_native_direct_connector_branch_is_removed() -> None:
    source = router_source()
    for removed in ("NATIVE_ROUTE", "native_notion_connector_available", "native_execute_read", "select_curriculum_read_executor"):
        assert removed not in source


def test_router_creates_no_second_notion_client_or_curriculum_system() -> None:
    source = router_source()
    for forbidden in ("import workflow_scheduler", "from workflow_scheduler", "NotionReadOnlyAdapter(", "notion_client", "api.notion.com", "NOTION_API_BASE", "urllib", "requests.", "httpx"):
        assert forbidden not in source
    assert "orchestrate_curriculum_evidence" in source
    assert "assemble_current_curriculum_evidence" not in source
    assert "resolve_current_curriculum_state" not in source
