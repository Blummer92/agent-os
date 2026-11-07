"""Execution-boundary proofs for the #2283 bounded Notion read.

These lock the credential gate, the read-only dispatch surface, relation-first
Visual Asset Library retrieval, and the absence of any GCE dependency.
"""

from __future__ import annotations

import pytest

from navigation_registry.connectors.curriculum_execution_surface_router import (
    READ_ONLY_ACTIONS,
)
from navigation_registry.connectors.curriculum_evidence_orchestrator import (
    CurriculumReadError,
)
from scripts.agent_os_notion_read_request import (
    DISPATCH_BLOCKED,
    DISPATCH_NOT_ACTIVATED,
    NotionReadRequestError,
    admit_notion_read_request,
    execute_admitted_notion_read,
    run_notion_read_request,
)
from .notion_read_support import (
    ACTOR,
    APPROVED_ASSET,
    GENERATED_AT,
    REPOSITORY,
    UNAPPROVED_ASSET,
    UNIT_PAGE_ID,
    ExplodingExecutor,
    RecordingExecutor,
    transport,
)

WRITE_METHODS = (
    "create_page", "update_page", "patch_page", "delete_page", "archive_page",
    "create_database", "update_database", "create_comment", "share_page",
    "update_data_source", "append_block_children",
)


def admit(payload, catalog):
    return admit_notion_read_request(payload, catalog=catalog, expected_repository=REPOSITORY, expected_actor=ACTOR)


def run(catalog, executor=None, **kwargs):
    return run_notion_read_request(
        kwargs.pop("payload", transport()), expected_repository=REPOSITORY,
        expected_actor=ACTOR, generated_at=GENERATED_AT, catalog=catalog,
        scheduler_task_executor_factory=executor.factory if executor else None, **kwargs,
    )


@pytest.mark.parametrize("payload", [
    transport(actor="someone-else"), transport(repository="someone/else"),
    transport(run_attempt=2), transport(request_id="search"),
    transport(request_id="da5cba48-50fd-4377-9790-8df8f6f2c7dd"),
    transport(reason="accepted-envelope"), transport(issue_number=9999),
])
def test_rejected_request_never_builds_the_credential_bearing_executor(verified_catalog, payload) -> None:
    evidence = run(verified_catalog, ExplodingExecutor(), payload=payload)
    assert evidence["dispatch_status"] == DISPATCH_BLOCKED
    assert evidence["result"] is None
    assert evidence["admission"]["secret_dispatch_authorized"] is False


def test_rejected_admission_cannot_be_forced_into_execution(verified_catalog) -> None:
    decision = admit(transport(actor="someone-else"), verified_catalog)
    executor = ExplodingExecutor()
    with pytest.raises(NotionReadRequestError, match="requires an admitted"):
        execute_admitted_notion_read(decision, catalog=verified_catalog, scheduler_task_executor_factory=executor.factory)


def test_shipped_verified_catalog_stays_inactive_without_executor(shipped_catalog) -> None:
    evidence = run(shipped_catalog)
    assert evidence["dispatch_status"] == DISPATCH_NOT_ACTIVATED
    assert evidence["dispatch_reason"] == "live-read-executor-not-configured"
    assert evidence["admission"]["secret_dispatch_authorized"] is True
    assert evidence["result"] is None


def test_admitted_request_without_a_configured_executor_is_not_activated(verified_catalog) -> None:
    evidence = run(verified_catalog)
    assert evidence["dispatch_status"] == DISPATCH_NOT_ACTIVATED
    assert evidence["dispatch_reason"] == "live-read-executor-not-configured"
    assert evidence["result"] is None


def test_only_allowed_read_actions_are_dispatched(verified_catalog) -> None:
    executor = RecordingExecutor()
    # #2816: the coursewide step fails closed on the schema mismatch before
    # its own dispatch; the actions below are the canonical-unit reads and
    # the relation-first asset query only.
    with pytest.raises(CurriculumReadError, match="filter-property-unavailable"):
        run(verified_catalog, executor)
    assert executor.actions == ["get_page", "get_page", "query_data_source"]
    assert set(executor.actions) <= set(READ_ONLY_ACTIONS)


def test_no_dispatched_payload_carries_a_write_method(verified_catalog) -> None:
    executor = RecordingExecutor()
    with pytest.raises(CurriculumReadError, match="filter-property-unavailable"):
        run(verified_catalog, executor)
    for call in executor.calls:
        serialized = repr(call).lower()
        for method in WRITE_METHODS: assert method not in serialized
        for verb in ("post", "patch", "put", "delete", "archive"): assert call["action"] != verb


def test_workspace_wide_search_is_never_dispatched(verified_catalog) -> None:
    executor = RecordingExecutor()
    with pytest.raises(CurriculumReadError, match="filter-property-unavailable"):
        run(verified_catalog, executor)
    for call in executor.calls:
        assert call["action"] != "search"; assert "query" not in call
        if call["action"] == "query_data_source":
            assert call["data_source_id"] == "ds-visual-asset-library"
            assert call["max_pages"] == 1; assert call["max_results"] <= 24


def test_coursewide_filter_fails_closed_before_any_gce_dependency_can_arise(verified_catalog) -> None:
    # Renamed (EXP-S5): the old name claimed a GCE property this body never
    # proves. What this body actually proves is that the read dies at the
    # #2816/#3253/#3254 filter-vocabulary step (filter-property-unavailable)
    # after only the bounded read-only dispatches, so no later step -- GCE
    # or otherwise -- is ever reached on this path. The actual GCE refusal
    # is proven by 08_Tooling/workflow-scheduler/tests/
    # test_2283_notion_read_ingress.py::
    # test_accepted_notion_read_envelope_is_never_routed_to_gce.
    # NOTE: the rename changes this test's node ID; no other file in the
    # repository referenced the old node ID (grep-verified).
    with pytest.raises(CurriculumReadError, match="filter-property-unavailable"):
        run(verified_catalog, RecordingExecutor())


def test_no_notion_or_drive_or_classroom_write_is_performed(verified_catalog) -> None:
    executor = RecordingExecutor()
    # #2816: the read fails closed before the coursewide dispatch; no write
    # is performed on this path by construction.
    with pytest.raises(CurriculumReadError, match="filter-property-unavailable"):
        run(verified_catalog, executor)
    for call in executor.calls:
        serialized = repr(call).lower()
        for method in WRITE_METHODS: assert method not in serialized
        for verb in ("post", "patch", "put", "delete", "archive"): assert call["action"] != verb


def test_visual_assets_are_retrieved_through_the_canonical_unit_relation(verified_catalog) -> None:
    executor = RecordingExecutor()
    # #2816: the relation-first unit query still dispatches; the coursewide
    # checkbox filter fails closed before reaching the provider.
    with pytest.raises(CurriculumReadError, match="filter-property-unavailable"):
        run(verified_catalog, executor)
    query = [call for call in executor.calls if call["action"] == "query_data_source"]
    assert len(query) == 1
    relation_filter = query[0]["filter"]
    assert relation_filter["property"] == "Canonical Unit"
    assert relation_filter["relation"]["contains"] == UNIT_PAGE_ID.replace("-", "")
    serialized = repr(relation_filter).lower()
    for forbidden in ("title", "name", "filename", "contains_text", "rich_text", "search"): assert forbidden not in serialized
    # #3253: no fabricated unit relation, no keyword/title/name matching —
    # and #2816: the unanswerable Icon System checkbox filter is never
    # dispatched against the Visual Asset Library.
    assert "reusable across units" not in repr(executor.calls).lower()


def test_coursewide_filter_fails_closed_before_any_similarity_substitution_is_reached(verified_catalog) -> None:
    executor = RecordingExecutor(assets=[
        {"asset_id":"asset-photography-foundations-lookalike","exists":True,"approved_for_requested_use":True,"approved_student_reuse":True,"source_revision":9,"canonical_unit_relation":False},
        {"asset_id":APPROVED_ASSET,"exists":True,"approved_for_requested_use":True,"approved_student_reuse":True,"source_revision":3,"canonical_unit_relation":True},
    ])
    # Renamed (EXP-S5 neighbor audit): the old name claimed a substitution
    # property this body never reaches -- the read dies at the
    # filter-vocabulary step before any asset normalization, so whether
    # similarity could substitute for the relation is never tested here.
    # NOTE: the rename changes this test's node ID; no other file in the
    # repository referenced the old node ID (grep-verified).
    with pytest.raises(CurriculumReadError, match="filter-property-unavailable"):
        run(verified_catalog, executor)


def test_coursewide_filter_fails_closed_before_any_projection_is_produced(verified_catalog) -> None:
    executor = RecordingExecutor(assets=[{
        "asset_id": APPROVED_ASSET,
        "exists": True,
        "approved_for_requested_use": True,
        "approved_student_reuse": True,
        "source_revision": 3,
        "canonical_unit_relation": True,
        "library_reference": {
            "page_id": "private-notion-page-id",
            "drive_file_id": "private-drive-file-id",
        },
    }])
    # Renamed (EXP-S5 neighbor audit): the old name read as a general
    # projection guarantee, but this body never exercises projection code
    # -- the read fails closed before any result is produced or projected.
    # The new name states only what this body proves.
    # NOTE: the rename changes this test's node ID; no other file in the
    # repository referenced the old node ID (grep-verified).
    with pytest.raises(CurriculumReadError, match="filter-property-unavailable"):
        run(verified_catalog, executor)


def test_asset_authority_is_undecided_when_coursewide_filter_fails_closed(verified_catalog) -> None:
    # Renamed (EXP-S5): the old name claimed an asset-authority property
    # this body never reaches. What this body actually proves is that the
    # read dies at the filter-vocabulary step before any asset evidence is
    # normalized, so no eligibility or authority decision happens here at
    # all. The existence != eligibility != production-authority contract
    # is proven at the state-resolution layer, not here:
    # tests/test_current_curriculum_state.py::
    #   test_asset_exists_but_is_not_reusable_and_required_blocks,
    #   test_approved_reusable_asset_reports_eligibility_without_authority,
    #   test_ambiguous_asset_eligibility_needs_reconciliation.
    # A run()-level asset oracle is blocked until the #2816/#3253/#3254
    # filter vocabulary gap is resolved.
    # NOTE: the rename changes this test's node ID; no other file in the
    # repository referenced the old node ID (grep-verified).
    with pytest.raises(CurriculumReadError, match="filter-property-unavailable"):
        run(verified_catalog, RecordingExecutor())


def test_coursewide_filter_fails_closed_before_any_eligibility_evaluation(verified_catalog) -> None:
    executor = RecordingExecutor(assets=[{"asset_id":UNAPPROVED_ASSET,"exists":True,"approved_for_requested_use":True,"approved_student_reuse":False,"source_revision":2,"canonical_unit_relation":True}])
    # Renamed (EXP-S5 neighbor audit): the old name claimed an eligibility
    # property this body never reaches -- the read dies at the
    # filter-vocabulary step before any eligibility evaluation, so whether
    # an unapproved asset could become eligible is never tested here. The
    # eligibility contract is proven at the state-resolution layer:
    # tests/test_current_curriculum_state.py::
    # test_asset_exists_but_is_not_reusable_and_required_blocks.
    # NOTE: the rename changes this test's node ID; no other file in the
    # repository referenced the old node ID (grep-verified).
    with pytest.raises(CurriculumReadError, match="filter-property-unavailable"):
        run(verified_catalog, executor)


def test_canonical_unit_request_loads_no_unrelated_evidence(verified_catalog) -> None:
    executor = RecordingExecutor()
    evidence = run(verified_catalog, executor, payload=transport(request_id="photography-foundations-canonical-unit"))
    assert executor.actions == ["get_page", "get_page"]
    assert evidence["result"]["request_class"] == "canonical-unit"
    assert [source["logical_source"] for source in evidence["result"]["sources"]] == ["canonical-unit"]


@pytest.mark.parametrize("provider_status", ["permission-denied", "missing", "not-found", "stale"])
def test_inaccessible_provider_state_fails_closed(verified_catalog, provider_status: str) -> None:
    class FailingExecutor(RecordingExecutor):
        def execute(self, payload):
            self.calls.append(dict(payload))
            if payload["action"] == "get_page": return {"status":"success","output":{"id":UNIT_PAGE_ID}}
            return {"status":"failure","message":provider_status}
    with pytest.raises(Exception) as excinfo: run(verified_catalog, FailingExecutor())
    assert "unresolved" in str(excinfo.value) or "provider" in str(excinfo.value)


def test_canonical_unit_identity_mismatch_fails_closed(verified_catalog) -> None:
    executor = RecordingExecutor(page_id="22222222-2222-2222-2222-222222222222")
    with pytest.raises(Exception, match="canonical unit identity mismatch"): run(verified_catalog, executor)
