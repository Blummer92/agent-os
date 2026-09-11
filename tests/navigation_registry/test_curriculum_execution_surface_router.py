from __future__ import annotations

from pathlib import Path

import pytest

from instructional_workflow_contracts.current_curriculum_state import (
    resolve_current_curriculum_state,
)
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
    NATIVE_ROUTE,
    READ_ONLY_ACTIONS,
    CurriculumSurfaceError,
    build_scheduler_fallback_read_executor,
    retrieve_curriculum_evidence,
    select_curriculum_read_executor,
)

UNIT_PAGE = "3907ac78-3131-8129-8c73-cd9f6b8e8a7d"
UNIT_PAGE_COMPACT = "3907ac78313181298c73cd9f6b8e8a7d"


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


def teacher_facing_asset() -> dict[str, object]:
    """A real Visual Asset Library row that exists but is not student-reusable.

    The title is deliberately unit-named so a title/filename match cannot stand
    in for canonical-relation and approved-use evidence.
    """
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
    mapping = {
        UNIT_ALIGNMENT: [owner("unit-1", "unit-generation-approval")],
        MODELING: [owner("modeling-1", "modeling-handoff-ready")],
        PACKET: [owner("packet-1", "packet-generation-gate")],
        MATERIALS: [owner("materials-1", "instructional-materials-readiness")],
        SOURCE_CONTROL: [owner("source-1", "source-control-gate")],
        PRODUCTION: [owner("production-1", "production-authorized", "false")],
        VISUAL_ASSETS: [teacher_facing_asset()],
    }
    return mapping.get(source, [])


def native_reader(calls: list[tuple[str, dict[str, object]]]):
    """Host-supplied native ChatGPT Notion executor for the #980 read seam."""

    def execute(step, payload):
        calls.append((step.logical_source, dict(payload)))
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE, "last_edited_time": "2026-08-08T12:00:00Z"}
        return {"results": source_records(step.logical_source)}

    return execute


def scheduler(calls: list[dict[str, object]], *, result=None):
    """Stub of the canonical #936 Scheduler five-state read contract."""

    def execute(task_payload):
        calls.append(dict(task_payload))
        if result is not None:
            return result
        if task_payload["action"] == "get_page":
            return {
                "status": "success",
                "message": "ok",
                "output": {"id": UNIT_PAGE, "last_edited_time": "2026-08-08T12:00:00Z"},
            }
        source = str(task_payload["data_source_id"]).removeprefix("ds-")
        return {
            "status": "success",
            "message": "ok",
            "output": {"results": source_records(source), "has_more": False},
        }

    return execute


def fallback_factory(calls: list[dict[str, object]], *, result=None):
    return lambda: build_scheduler_fallback_read_executor(
        execute_scheduler_task=scheduler(calls, result=result)
    )


def via_native(request: CurriculumReadRequest, calls=None, **kwargs) -> dict[str, object]:
    return retrieve_curriculum_evidence(
        request=request,
        canonical_unit=unit(),
        resolve_identity=identity,
        native_notion_connector_available=True,
        native_execute_read=native_reader(calls if calls is not None else []),
        **kwargs,
    )


def via_fallback(request: CurriculumReadRequest, calls=None, **kwargs) -> dict[str, object]:
    return retrieve_curriculum_evidence(
        request=request,
        canonical_unit=unit(),
        resolve_identity=identity,
        native_notion_connector_available=False,
        fallback_factory=fallback_factory(calls if calls is not None else []),
        **kwargs,
    )


IMAGES = CurriculumReadRequest("images", "images")
SLIDES = CurriculumReadRequest("make", "slides", requires_reusable_assets=True)


# --- route selection -------------------------------------------------------


def test_native_available_uses_native_route_and_never_builds_fallback() -> None:
    built = []
    result = via_native(IMAGES, fallback_factory=lambda: built.append("built") or None)
    assert result["read_route"] == NATIVE_ROUTE
    assert built == [], "fallback composition must stay lazy"


def test_native_unavailable_routes_through_the_existing_agent_os_fallback() -> None:
    tasks: list[dict[str, object]] = []
    result = via_fallback(IMAGES, calls=tasks)
    assert result["read_route"] == FALLBACK_ROUTE
    assert tasks, "the injected #936 Scheduler path must perform the reads"


def test_native_route_without_a_host_executor_fails_closed() -> None:
    with pytest.raises(CurriculumSurfaceError, match="host-supplied read executor"):
        select_curriculum_read_executor(native_notion_connector_available=True)


def test_fallback_route_without_the_existing_composition_fails_closed() -> None:
    with pytest.raises(CurriculumSurfaceError, match="existing Agent OS reader composition"):
        select_curriculum_read_executor(native_notion_connector_available=False)


def test_unavailable_fallback_composition_fails_closed() -> None:
    with pytest.raises(CurriculumSurfaceError, match="composition is unavailable"):
        select_curriculum_read_executor(
            native_notion_connector_available=False, fallback_factory=lambda: None
        )


@pytest.mark.parametrize("flag", [1, 0, "true", None])
def test_non_bool_connector_capability_is_rejected(flag: object) -> None:
    with pytest.raises(CurriculumSurfaceError, match="must be a built-in bool"):
        select_curriculum_read_executor(native_notion_connector_available=flag)


# --- fallback reuses the canonical #936 path -------------------------------


def test_fallback_builds_only_canonical_936_read_payloads() -> None:
    tasks: list[dict[str, object]] = []
    via_fallback(SLIDES, calls=tasks)

    actions = {task["action"] for task in tasks}
    assert actions <= READ_ONLY_ACTIONS
    assert actions == {"get_page", "query_data_source"}

    page_tasks = [task for task in tasks if task["action"] == "get_page"]
    assert [task["page_id"] for task in page_tasks] == [UNIT_PAGE]

    for task in tasks:
        if task["action"] != "query_data_source":
            continue
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

    with pytest.raises(CurriculumReadError):
        retrieve_curriculum_evidence(
            request=IMAGES,
            canonical_unit=unit(),
            resolve_identity=unbound,
            native_notion_connector_available=False,
            fallback_factory=fallback_factory(tasks),
        )
    assert [task["action"] for task in tasks] == ["get_page"]


def test_out_of_bound_result_request_fails_closed_before_dispatch() -> None:
    tasks: list[dict[str, object]] = []
    executor = build_scheduler_fallback_read_executor(
        execute_scheduler_task=scheduler(tasks)
    )
    step = CurriculumReadStep(VISUAL_ASSETS, "query_data_source", relation_first=True)
    with pytest.raises(CurriculumSurfaceError, match="bounded read limit"):
        executor(step, {"identity": identity(VISUAL_ASSETS), "max_results": 500})
    assert tasks == []


# --- native/fallback semantic equivalence ----------------------------------


@pytest.mark.parametrize(
    "request_",
    [
        IMAGES,
        SLIDES,
        CurriculumReadRequest("improve-modeling"),
        CurriculumReadRequest("what-is-blocking"),
        CurriculumReadRequest("make", "worksheet"),
        CurriculumReadRequest("next-teaching"),
    ],
)
def test_native_and_fallback_normalize_identically(request_: CurriculumReadRequest) -> None:
    native = via_native(request_)
    fallback = via_fallback(request_)

    assert native["curriculum_evidence"] == fallback["curriculum_evidence"]

    native_state = resolve_current_curriculum_state(native["curriculum_evidence"])
    fallback_state = resolve_current_curriculum_state(fallback["curriculum_evidence"])
    assert native_state.record is not None
    assert fallback_state.record is not None
    assert native_state.record.to_dict() == fallback_state.record.to_dict()

    assert native["read_route"] != fallback["read_route"]


@pytest.mark.parametrize("route", [via_native, via_fallback])
def test_owner_class_currentness_and_provenance_survive_both_routes(route) -> None:
    packet = route(CurriculumReadRequest("what-is-blocking"))["curriculum_evidence"]
    owners = packet["owner_evidence"]
    assert owners

    for record in owners:
        assert record["classification"] == "owner-governed"
        assert record["currentness"] == "current"
        assert record["source_revision"] == 1
        assert record["owner"]
        assert record["decision_key"]
        assert record["reference"]["system"] == "notion"
        assert record["reference"]["verification_evidence"] == "normalized-read-back"

    assert {record["decision_key"] for record in owners} >= {
        "unit-generation-approval",
        "modeling-handoff-ready",
        "packet-generation-gate",
        "source-control-gate",
        "instructional-materials-readiness",
        "production-authorized",
    }


@pytest.mark.parametrize("route", [via_native, via_fallback])
def test_canonical_unit_identity_survives_both_routes(route) -> None:
    packet = route(IMAGES)["curriculum_evidence"]
    assert packet["canonical_unit"]["stable_id"] == "photography-foundations"
    assert "provider_page_id" not in packet["canonical_unit"]


# --- request sensitivity ---------------------------------------------------


def test_image_request_stays_request_sensitive_on_the_native_route() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    via_native(IMAGES, calls=calls)
    assert [source for source, _ in calls] == [CANONICAL_UNIT, VISUAL_ASSETS]


def test_image_request_stays_request_sensitive_on_the_fallback_route() -> None:
    tasks: list[dict[str, object]] = []
    via_fallback(IMAGES, calls=tasks)

    queried = [task["data_source_id"] for task in tasks if task["action"] == "query_data_source"]
    assert queried == [f"ds-{VISUAL_ASSETS}"]
    for unrelated in (MODELING, PACKET, MATERIALS, SOURCE_CONTROL, PRODUCTION, UNIT_ALIGNMENT):
        assert f"ds-{unrelated}" not in queried


def test_modeling_request_does_not_reach_packet_or_material_surfaces() -> None:
    tasks: list[dict[str, object]] = []
    via_fallback(CurriculumReadRequest("improve-modeling"), calls=tasks)
    queried = [task["data_source_id"] for task in tasks if task["action"] == "query_data_source"]
    assert queried == [f"ds-{MODELING}"]


# --- visual asset governance (#971) ---------------------------------------


def test_visual_asset_lookup_is_relation_first_in_the_provider_payload() -> None:
    tasks: list[dict[str, object]] = []
    via_fallback(IMAGES, calls=tasks)

    asset_task = next(
        task
        for task in tasks
        if task.get("data_source_id") == f"ds-{VISUAL_ASSETS}"
    )
    assert asset_task["filter"] == {
        "property": "Canonical Unit",
        "relation": {"contains": UNIT_PAGE_COMPACT},
    }


def test_provider_filter_syntax_stays_behind_the_read_boundary() -> None:
    for route in (via_native, via_fallback):
        packet = route(IMAGES)["curriculum_evidence"]
        rendered = repr(packet)
        assert "relation_filter" not in rendered
        assert "contains_page_id" not in rendered
        assert UNIT_PAGE_COMPACT not in rendered


@pytest.mark.parametrize("route", [via_native, via_fallback])
def test_asset_title_cannot_substitute_for_governed_approval_evidence(route) -> None:
    packet = route(IMAGES)["curriculum_evidence"]
    assert "Photography Foundations hero image" not in repr(packet)
    assert packet["asset_evidence"] == [
        {
            "asset_id": "pf-010",
            "approved_for_requested_use": False,
            "approved_student_reuse": False,
            "exists": True,
            "source_revision": 1,
        }
    ]


@pytest.mark.parametrize("route", [via_native, via_fallback])
def test_teacher_facing_asset_existence_is_not_approval_or_production_authority(route) -> None:
    packet = route(IMAGES)["curriculum_evidence"]
    state = resolve_current_curriculum_state(packet)
    assert state.record is not None
    record = state.record.to_dict()

    assert record["assets"]["matching_asset_exists"] is True
    assert record["assets"]["approved_reusable_student_facing_exists"] is False
    assert "asset-reusable-unavailable" in record["blockers"]
    assert record["disposition"] == "blocked"
    assert record["authority"]["production_authorized"] is False


def test_route_label_carries_no_authority() -> None:
    result = via_fallback(IMAGES)
    assert set(result) == {
        "read_route",
        "native_notion_connector_available",
        "curriculum_evidence",
    }


# --- explicit failure states ----------------------------------------------


@pytest.mark.parametrize(
    "scheduler_result",
    [
        {"status": "failure", "message": "source is not shared with the integration"},
        {"status": "retryable", "message": "rate limited", "retry_after": 5.0},
        {"status": "", "message": "malformed"},
    ],
)
def test_scheduler_non_success_remains_explicit_and_fails_closed(scheduler_result) -> None:
    tasks: list[dict[str, object]] = []
    with pytest.raises(CurriculumReadError, match="provider unresolved"):
        retrieve_curriculum_evidence(
            request=IMAGES,
            canonical_unit=unit(),
            resolve_identity=identity,
            native_notion_connector_available=False,
            fallback_factory=fallback_factory(tasks, result=scheduler_result),
        )


def test_malformed_scheduler_envelopes_fail_closed() -> None:
    for bad in ("not-a-mapping", {"status": "success"}, {"status": "success", "output": {}}):
        executor = build_scheduler_fallback_read_executor(
            execute_scheduler_task=lambda _payload, value=bad: value
        )
        step = CurriculumReadStep(VISUAL_ASSETS, "query_data_source", relation_first=True)
        with pytest.raises(CurriculumSurfaceError):
            executor(step, {"identity": identity(VISUAL_ASSETS), "max_results": 5})


def test_relative_time_request_does_not_invent_current_day_context() -> None:
    packet = via_fallback(
        CurriculumReadRequest("make", "lesson", relative_time="tomorrow")
    )["curriculum_evidence"]
    assert "current_context" not in packet
    state = resolve_current_curriculum_state(packet)
    assert state.record is not None
    assert "routing-current-day-missing" in state.record.to_dict()["blockers"]


# --- boundary guards -------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    ["update_page", "create_page", "delete_page", "query_database", "patch_data_source", ""],
)
def test_no_write_or_unapproved_action_can_reach_the_scheduler(action: str) -> None:
    tasks: list[dict[str, object]] = []
    executor = build_scheduler_fallback_read_executor(
        execute_scheduler_task=scheduler(tasks)
    )
    step = CurriculumReadStep(VISUAL_ASSETS, action)
    with pytest.raises(CurriculumSurfaceError, match="non-read action"):
        executor(step, {"identity": identity(VISUAL_ASSETS), "max_results": 5})
    assert tasks == []


def router_source() -> str:
    return Path(curriculum_execution_surface_router.__file__).read_text(encoding="utf-8")


def test_no_coding_knowledge_or_lessons_learned_route_remains_in_2282() -> None:
    source = router_source().lower()
    for superseded in (
        "lesson_reader",
        "lessons_learned",
        "lessons learned",
        "ckr6",
        "ckr11",
        "coding_knowledge",
        "coding knowledge",
        "failed_repair",
        "repair_retry",
        "lesson_retrieval",
    ):
        assert superseded not in source, f"superseded coding-knowledge scope leaked: {superseded}"


def test_router_creates_no_second_notion_client_or_curriculum_system() -> None:
    source = router_source()
    for forbidden in (
        "import workflow_scheduler",
        "from workflow_scheduler",
        "NotionReadOnlyAdapter(",
        "notion_client",
        "api.notion.com",
        "NOTION_API_BASE",
        "urllib",
        "requests.",
        "httpx",
    ):
        assert forbidden not in source, f"router reached outside the injected seam: {forbidden}"

    # The assembled evidence and current-state model stay the existing ones.
    assert "orchestrate_curriculum_evidence" in source
    assert "assemble_current_curriculum_evidence" not in source
    assert "resolve_current_curriculum_state" not in source


def test_no_drive_or_classroom_artifact_write_surface_exists() -> None:
    source = router_source().lower()
    for forbidden in (
        "drive",
        "googleapis",
        "slides",
        "upload",
        "publish",
        "create_file",
        "share",
    ):
        assert forbidden not in source, f"classroom/Drive write surface leaked: {forbidden}"
