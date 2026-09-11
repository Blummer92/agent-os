"""Execution-boundary proofs for the #2283 bounded Notion read.

These lock the credential gate, the read-only dispatch surface, relation-first
Visual Asset Library retrieval, and the absence of any GCE dependency.
"""

from __future__ import annotations

import pytest

from navigation_registry.connectors.curriculum_execution_surface_router import (
    FALLBACK_ROUTE,
    READ_ONLY_ACTIONS,
)
from scripts.agent_os_notion_read_request import (
    DISPATCH_BLOCKED,
    DISPATCH_COMPLETED,
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
    "create_page",
    "update_page",
    "patch_page",
    "delete_page",
    "archive_page",
    "create_database",
    "update_database",
    "create_comment",
    "share_page",
    "update_data_source",
    "append_block_children",
)


def admit(payload, catalog):
    return admit_notion_read_request(
        payload,
        catalog=catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )


def run(catalog, executor=None, **kwargs):
    return run_notion_read_request(
        kwargs.pop("payload", transport()),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
        generated_at=GENERATED_AT,
        catalog=catalog,
        scheduler_task_executor_factory=executor.factory if executor else None,
        **kwargs,
    )


# --------------------------------------------------------------------------
# No secret-bearing step before admission
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        transport(actor="someone-else"),
        transport(repository="someone/else"),
        transport(run_attempt=2),
        transport(request_id="search"),
        transport(request_id="da5cba48-50fd-4377-9790-8df8f6f2c7dd"),
        transport(reason="accepted-envelope"),
        transport(issue_number=9999),
    ],
)
def test_rejected_request_never_builds_the_credential_bearing_executor(
    verified_catalog, payload
) -> None:
    evidence = run(verified_catalog, ExplodingExecutor(), payload=payload)

    assert evidence["dispatch_status"] == DISPATCH_BLOCKED
    assert evidence["result"] is None
    assert evidence["admission"]["secret_dispatch_authorized"] is False


def test_rejected_admission_cannot_be_forced_into_execution(verified_catalog) -> None:
    decision = admit(transport(actor="someone-else"), verified_catalog)
    executor = ExplodingExecutor()

    with pytest.raises(NotionReadRequestError, match="requires an admitted"):
        execute_admitted_notion_read(
            decision,
            catalog=verified_catalog,
            scheduler_task_executor_factory=executor.factory,
        )


def test_shipped_catalog_blocks_before_any_dispatch(shipped_catalog) -> None:
    evidence = run(shipped_catalog, ExplodingExecutor())

    assert evidence["dispatch_status"] == DISPATCH_BLOCKED
    assert evidence["admission"]["secret_dispatch_authorized"] is False


def test_admitted_request_without_a_configured_executor_is_not_activated(
    verified_catalog,
) -> None:
    evidence = run(verified_catalog)

    assert evidence["dispatch_status"] == DISPATCH_NOT_ACTIVATED
    assert evidence["dispatch_reason"] == "live-read-executor-not-configured"
    assert evidence["result"] is None


# --------------------------------------------------------------------------
# Only approved read operations are reachable
# --------------------------------------------------------------------------


def test_only_allowed_read_actions_are_dispatched(verified_catalog) -> None:
    executor = RecordingExecutor()

    evidence = run(verified_catalog, executor)

    assert evidence["dispatch_status"] == DISPATCH_COMPLETED
    # Resolve-then-verify: the first get_page resolves the unit's live #973
    # status, then #980's own plan re-reads and re-verifies the same identity.
    assert executor.actions == ["get_page", "get_page", "query_data_source"]
    assert set(executor.actions) <= set(READ_ONLY_ACTIONS)


def test_no_dispatched_payload_carries_a_write_method(verified_catalog) -> None:
    executor = RecordingExecutor()

    run(verified_catalog, executor)

    for call in executor.calls:
        serialized = repr(call).lower()
        for method in WRITE_METHODS:
            assert method not in serialized
        for verb in ("post", "patch", "put", "delete", "archive"):
            assert call["action"] != verb


def test_workspace_wide_search_is_never_dispatched(verified_catalog) -> None:
    executor = RecordingExecutor()

    run(verified_catalog, executor)

    for call in executor.calls:
        assert call["action"] != "search"
        assert "query" not in call
        # Every data-source read is pinned to one approved binding and bounded.
        if call["action"] == "query_data_source":
            assert call["data_source_id"] == "ds-visual-asset-library"
            assert call["max_pages"] == 1
            assert call["max_results"] <= 24


def test_read_route_never_requires_gce(verified_catalog) -> None:
    executor = RecordingExecutor()

    evidence = run(verified_catalog, executor)

    assert evidence["gce_invoked"] is False
    assert evidence["result"]["read_route"] == FALLBACK_ROUTE
    assert evidence["result"]["read_route"] == "agent-os-notion-reader"


def test_no_notion_or_drive_or_classroom_write_is_performed(verified_catalog) -> None:
    evidence = run(verified_catalog, RecordingExecutor())

    assert evidence["notion_writes_performed"] is False
    assert evidence["drive_writes_performed"] is False
    assert evidence["classroom_artifact_writes_performed"] is False
    authority = evidence["result"]["authority"]
    assert authority["notion_write_authorized"] is False
    assert authority["drive_write_authorized"] is False
    assert authority["classroom_artifact_write_authorized"] is False
    assert authority["write_allowed"] is False


# --------------------------------------------------------------------------
# Relation-first Visual Asset Library retrieval (#971)
# --------------------------------------------------------------------------


def test_visual_assets_are_retrieved_through_the_canonical_unit_relation(
    verified_catalog,
) -> None:
    executor = RecordingExecutor()

    run(verified_catalog, executor)

    query = [call for call in executor.calls if call["action"] == "query_data_source"]
    assert len(query) == 1
    relation_filter = query[0]["filter"]
    assert relation_filter["property"] == "Canonical Unit"
    assert relation_filter["relation"]["contains"] == UNIT_PAGE_ID.replace("-", "")
    # No title/filename/keyword criterion may appear in the dispatched filter.
    serialized = repr(relation_filter).lower()
    for forbidden in ("title", "name", "filename", "contains_text", "rich_text", "search"):
        assert forbidden not in serialized


def test_title_or_filename_similarity_cannot_substitute_for_the_relation(
    verified_catalog,
) -> None:
    """An asset without the governed relation is dropped, however well it matches."""
    executor = RecordingExecutor(
        assets=[
            {
                "asset_id": "asset-photography-foundations-lookalike",
                "exists": True,
                "approved_for_requested_use": True,
                "approved_student_reuse": True,
                "source_revision": 9,
                # Title/filename similarity only; no Canonical Unit relation.
                "canonical_unit_relation": False,
            },
            {
                "asset_id": APPROVED_ASSET,
                "exists": True,
                "approved_for_requested_use": True,
                "approved_student_reuse": True,
                "source_revision": 3,
                "canonical_unit_relation": True,
            },
        ]
    )

    evidence = run(verified_catalog, executor)
    assets = evidence["result"]["assets"]

    assert assets["asset_ids"] == [APPROVED_ASSET]
    assert "asset-photography-foundations-lookalike" not in assets["eligible_asset_ids"]
    assert assets["title_or_filename_matching_used"] is False
    assert assets["relation_source"] == "canonical-unit-relation"


def test_asset_existence_is_not_approved_use_or_production_authority(
    verified_catalog,
) -> None:
    evidence = run(verified_catalog, RecordingExecutor())
    assets = evidence["result"]["assets"]

    # Both assets exist and are related; only one is approved for reuse.
    assert assets["matching_asset_exists"] is True
    assert sorted(assets["asset_ids"]) == sorted([APPROVED_ASSET, UNAPPROVED_ASSET])
    assert assets["eligible_asset_ids"] == [APPROVED_ASSET]
    assert assets["production_authorized"] is False
    assert assets["existence_implies_approved_use"] is False
    assert assets["existence_implies_production_authority"] is False


def test_unapproved_assets_never_become_eligible(verified_catalog) -> None:
    executor = RecordingExecutor(
        assets=[
            {
                "asset_id": UNAPPROVED_ASSET,
                "exists": True,
                "approved_for_requested_use": True,
                "approved_student_reuse": False,
                "source_revision": 2,
                "canonical_unit_relation": True,
            }
        ]
    )

    evidence = run(verified_catalog, executor)
    assets = evidence["result"]["assets"]

    assert assets["matching_asset_exists"] is True
    assert assets["eligible_asset_ids"] == []
    assert assets["approved_reusable_student_facing_exists"] is False


# --------------------------------------------------------------------------
# Request-sensitive planning and inaccessible provider state
# --------------------------------------------------------------------------


def test_canonical_unit_request_loads_no_unrelated_evidence(verified_catalog) -> None:
    executor = RecordingExecutor()

    evidence = run(
        verified_catalog,
        executor,
        payload=transport(request_id="photography-foundations-canonical-unit"),
    )

    assert executor.actions == ["get_page", "get_page"]
    assert evidence["result"]["request_class"] == "canonical-unit"
    assert [source["logical_source"] for source in evidence["result"]["sources"]] == [
        "canonical-unit"
    ]


@pytest.mark.parametrize(
    "provider_status", ["permission-denied", "missing", "not-found", "stale"]
)
def test_inaccessible_provider_state_fails_closed(
    verified_catalog, provider_status: str
) -> None:
    class FailingExecutor(RecordingExecutor):
        def execute(self, payload):
            self.calls.append(dict(payload))
            if payload["action"] == "get_page":
                return {"status": "success", "output": {"id": UNIT_PAGE_ID}}
            return {"status": "failure", "message": provider_status}

    with pytest.raises(Exception) as excinfo:
        run(verified_catalog, FailingExecutor())

    # Never a partially assembled result: the read fails closed instead.
    assert "unresolved" in str(excinfo.value) or "provider" in str(excinfo.value)


def test_canonical_unit_identity_mismatch_fails_closed(verified_catalog) -> None:
    executor = RecordingExecutor(page_id="22222222-2222-2222-2222-222222222222")

    with pytest.raises(Exception, match="canonical unit identity mismatch"):
        run(verified_catalog, executor)
