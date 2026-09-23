from copy import deepcopy

from navigation_registry.connectors.base import ConnectorError, ConnectorErrorCode, RegistryResource
from navigation_registry.connectors.notion_contract_adapter import NotionContractAdapter
from navigation_registry.connectors.scheduler_notion_evidence import SchedulerNotionEvidenceAdapter


def _data_source_payload() -> dict:
    return {
        "id": "data-source-123",
        "name": "Tasks",
        "url": "https://notion.example/data-source-123",
        "archived": False,
        "in_trash": False,
        "parent": {"database_id": "database-123"},
        "properties": {"Status": {"type": "status"}},
        "created_time": "2026-08-01T00:00:00Z",
        "last_edited_time": "2026-08-07T00:00:00Z",
    }


def test_live_data_source_preserves_distinct_identity_and_parent() -> None:
    payload = _data_source_payload()
    original = deepcopy(payload)
    result = NotionContractAdapter().from_live_data_source_payload(payload)
    assert isinstance(result, RegistryResource)
    assert result.entity_type == "DataSource"
    assert result.canonical_id == "data-source-123"
    assert result.parent == "database-123"
    assert result.metadata["data_source_id"] == "data-source-123"
    assert result.metadata["database_id"] == "database-123"
    assert result.write_allowed is False
    assert payload == original


def test_page_parent_preserves_data_source_identity() -> None:
    result = NotionContractAdapter().from_live_page_payload({
        "id": "page-123",
        "parent": {"data_source_id": "data-source-123", "database_id": "database-legacy"},
        "properties": {"Name": {"type": "title", "title": [{"plain_text": "Task"}]}},
    })
    assert isinstance(result, RegistryResource)
    assert result.parent == "data-source-123"


def test_data_source_missing_id_fails_closed() -> None:
    payload = _data_source_payload()
    payload.pop("id")
    result = NotionContractAdapter().from_live_data_source_payload(payload)
    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.METADATA_INCOMPLETE


def test_data_source_missing_database_parent_fails_closed() -> None:
    payload = _data_source_payload()
    payload["parent"] = {"workspace": True}
    result = NotionContractAdapter().from_live_data_source_payload(payload)
    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.METADATA_INCOMPLETE


def test_data_source_database_identity_conflict_fails_closed() -> None:
    payload = _data_source_payload()
    payload["parent"] = {"database_id": "data-source-123"}
    result = NotionContractAdapter().from_live_data_source_payload(payload)
    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.SOURCE_OF_TRUTH_CONFLICT


def test_scheduler_get_data_source_uses_existing_contract_adapter() -> None:
    output = _data_source_payload()
    result = SchedulerNotionEvidenceAdapter().from_scheduler_result(
        "get_data_source",
        {"status": "success", "message": "ok", "output": output},
    )
    assert isinstance(result, RegistryResource)
    assert result.entity_type == "DataSource"
    assert result.canonical_id == "data-source-123"
    assert result.parent == "database-123"
    assert result.metadata["scheduler_action"] == "get_data_source"
    assert result.metadata["raw_scheduler_output"] == output


def test_query_data_source_remains_outside_single_resource_bridge() -> None:
    result = SchedulerNotionEvidenceAdapter().from_scheduler_result(
        "query_data_source",
        {"status": "success", "output": {"results": [{"id": "page-1"}]}},
    )
    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.METADATA_INCOMPLETE


def test_get_data_source_retry_and_failure_keep_existing_semantics() -> None:
    adapter = SchedulerNotionEvidenceAdapter()
    retry = adapter.from_scheduler_result(
        "get_data_source", {"status": "retryable", "message": "503", "retry_after": 4.0}
    )
    failure = adapter.from_scheduler_result(
        "get_data_source", {"status": "failure", "message": "404"}
    )
    assert isinstance(retry, ConnectorError) and retry.retryable is True
    assert retry.code == ConnectorErrorCode.SYSTEM_UNAVAILABLE
    assert isinstance(failure, ConnectorError) and failure.retryable is False
    assert failure.code == ConnectorErrorCode.VERIFICATION_FAILED


def test_adapters_remain_pure_read_only_contracts() -> None:
    contract = NotionContractAdapter()
    scheduler = SchedulerNotionEvidenceAdapter()
    for adapter in (contract, scheduler):
        assert adapter.write_capabilities == "none"
        assert adapter.live_system_access is False
        for name in ("create_page", "update_page", "delete_page", "archive_page", "execute"):
            assert not hasattr(adapter, name)
