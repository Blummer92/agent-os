from navigation_registry.connectors.base import (
    ConnectorError,
    ConnectorErrorCode,
    RegistryResource,
)
from navigation_registry.connectors.scheduler_notion_evidence import (
    SchedulerNotionEvidenceAdapter,
)


def test_successful_page_result_uses_b2_live_mapping() -> None:
    adapter = SchedulerNotionEvidenceAdapter()
    output = {
        "id": "page-123",
        "url": "https://notion.example/page-123",
        "archived": False,
        "properties": {
            "Name": {
                "type": "title",
                "title": [{"plain_text": "Scheduler Page"}],
            }
        },
        "created_time": "2026-07-01T00:00:00Z",
        "last_edited_time": "2026-07-02T00:00:00Z",
    }
    scheduler_result = {
        "status": "success",
        "message": "Notion 'get_page' succeeded",
        "output": output,
    }

    result = adapter.from_scheduler_result("get_page", scheduler_result)

    assert isinstance(result, RegistryResource)
    assert result.system == "notion"
    assert result.entity_type == "Page"
    assert result.canonical_id == "page-123"
    assert result.display_name == "Scheduler Page"
    assert result.source_of_truth == "notion-live"
    assert result.verification_state == "VerifiedReadOnly"
    assert result.cache_status == "LiveRead"
    assert result.write_allowed is False
    assert result.metadata["scheduler_action"] == "get_page"
    assert result.metadata["raw_scheduler_output"] == output
    assert result.metadata["scheduler_result"] == scheduler_result
    assert result.metadata["evidence_path_mode"] == "live_notion_verification"


def test_successful_database_result_uses_b2_live_mapping() -> None:
    adapter = SchedulerNotionEvidenceAdapter()
    output = {
        "id": "database-123",
        "url": "https://notion.example/database-123",
        "archived": False,
        "title": "Scheduler Database",
        "properties": {"Status": {"type": "select"}},
        "created_time": "2026-07-01T00:00:00Z",
        "last_edited_time": "2026-07-02T00:00:00Z",
    }

    result = adapter.from_scheduler_result(
        "get_database",
        {
            "status": "success",
            "message": "Notion 'get_database' succeeded",
            "output": output,
        },
    )

    assert isinstance(result, RegistryResource)
    assert result.entity_type == "Database"
    assert result.canonical_id == "database-123"
    assert result.display_name == "Scheduler Database"
    assert result.metadata["properties"] == {"Status": {"type": "select"}}
    assert result.metadata["scheduler_action"] == "get_database"
    assert result.write_allowed is False


def test_scheduler_failure_maps_to_nonretryable_connector_error() -> None:
    result = SchedulerNotionEvidenceAdapter().from_scheduler_result(
        "get_page",
        {"status": "failure", "message": "Notion API returned HTTP 404"},
    )

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.VERIFICATION_FAILED
    assert result.retryable is False
    assert result.evidence["scheduler_action"] == "get_page"
    assert "output" not in result.evidence["scheduler_result"]


def test_scheduler_retryable_maps_to_retryable_connector_error() -> None:
    result = SchedulerNotionEvidenceAdapter().from_scheduler_result(
        "get_database",
        {
            "status": "retryable",
            "message": "Notion API returned HTTP 503",
            "retry_after": 10.0,
        },
    )

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.SYSTEM_UNAVAILABLE
    assert result.retryable is True
    assert result.evidence["scheduler_result"]["retry_after"] == 10.0


def test_success_without_output_fails_closed() -> None:
    result = SchedulerNotionEvidenceAdapter().from_scheduler_result(
        "get_page",
        {"status": "success", "message": "missing output"},
    )

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.METADATA_INCOMPLETE
    assert result.retryable is False


def test_b2_payload_error_preserves_scheduler_context() -> None:
    result = SchedulerNotionEvidenceAdapter().from_scheduler_result(
        "get_page",
        {"status": "success", "message": "ok", "output": {"url": "missing-id"}},
    )

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.METADATA_INCOMPLETE
    assert result.evidence["scheduler_action"] == "get_page"
    assert result.evidence["scheduler_result"]["status"] == "success"


def test_query_database_does_not_invent_multi_resource_contract() -> None:
    result = SchedulerNotionEvidenceAdapter().from_scheduler_result(
        "query_database",
        {"status": "success", "output": {"results": [{"id": "page-1"}]}},
    )

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.METADATA_INCOMPLETE
    assert result.evidence["scheduler_action"] == "query_database"


def test_unknown_or_malformed_status_fails_closed() -> None:
    adapter = SchedulerNotionEvidenceAdapter()

    missing = adapter.from_scheduler_result("get_page", {})
    unknown = adapter.from_scheduler_result("get_page", {"status": "cancelled"})

    assert isinstance(missing, ConnectorError)
    assert isinstance(unknown, ConnectorError)
    assert missing.code == ConnectorErrorCode.METADATA_INCOMPLETE
    assert unknown.code == ConnectorErrorCode.METADATA_INCOMPLETE


def test_adapter_exposes_no_write_like_methods() -> None:
    adapter = SchedulerNotionEvidenceAdapter()
    write_like_methods = {
        "create_page",
        "update_page",
        "delete_page",
        "archive_page",
        "comment",
        "share_page",
        "query_database",
        "execute",
    }

    assert all(not hasattr(adapter, method) for method in write_like_methods)
    assert adapter.write_capabilities == "none"
    assert adapter.live_system_access is False
