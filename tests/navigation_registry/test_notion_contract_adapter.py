from navigation_registry.connectors.base import (
    ConnectorError,
    ConnectorErrorCode,
    RegistryResource,
)
from navigation_registry.connectors.notion_contract_adapter import (
    CACHED_NOTION_INDEX_SOURCE,
    LIVE_NOTION_SOURCE,
    NOTION_SEARCH_RESULT_SOURCE,
    NotionContractAdapter,
)


def test_cached_dashboard_record_normalizes_to_registry_resource() -> None:
    adapter = NotionContractAdapter()
    record = {
        "Dashboard Name": "Curriculum Source Control",
        "Owner": "Integration Manager",
        "Human Review Needed?": "No",
        "navigation_warning": "Navigation aid only. Verify live state in Notion.",
    }

    result = adapter.from_navigation_record("dashboard", record)

    assert isinstance(result, RegistryResource)
    assert result.system == "notion"
    assert result.entity_type == "Dashboard"
    assert result.canonical_id == "Curriculum Source Control"
    assert result.display_name == "Curriculum Source Control"
    assert result.owner == "Integration Manager"
    assert result.source_of_truth == CACHED_NOTION_INDEX_SOURCE
    assert result.verification_state == "CachedOnly"
    assert result.cache_status == "SessionCache"
    assert result.write_allowed is False
    assert result.human_review_required is False
    assert result.metadata["live_verification_required"] is True


def test_cached_database_record_preserves_warning_and_human_review() -> None:
    adapter = NotionContractAdapter()
    record = {
        "Database Name": "DM Units",
        "Notion Database ID": "database-123",
        "Human Review Needed?": "Yes",
        "navigation_warning": "Navigation aid only. Verify live state in Notion.",
    }

    result = adapter.from_navigation_record("database", record)

    assert isinstance(result, RegistryResource)
    assert result.entity_type == "Database"
    assert result.canonical_id == "database-123"
    assert result.human_review_required is True
    assert "Navigation aid only" in result.metadata["navigation_warning"]
    assert result.metadata["raw_record"] == record


def test_cached_field_record_sets_property_type_and_parent_database() -> None:
    adapter = NotionContractAdapter()
    record = {
        "Database Name": "DM Units",
        "Property Name": "Generation Gate",
        "Human Review Needed?": "Yes if owner unclear",
    }

    result = adapter.from_navigation_record("field", record)

    assert isinstance(result, RegistryResource)
    assert result.entity_type == "Property"
    assert result.display_name == "Generation Gate"
    assert result.parent == "DM Units"
    assert result.human_review_required is True


def test_cached_duplicate_risk_record_requires_human_review() -> None:
    adapter = NotionContractAdapter()
    record = {
        "Suspect Field, Database, or Dashboard": "Readiness",
        "Similar To": "Materials Production Readiness",
        "Risk Type": "Conflicting status meaning",
        "Human Review Needed?": "No",
    }

    result = adapter.from_navigation_record("duplicate-risk", record)

    assert isinstance(result, RegistryResource)
    assert result.entity_type == "DuplicateRisk"
    assert result.human_review_required is True
    assert result.metadata["live_verification_required"] is True


def test_search_result_normalizes_to_reference_evidence() -> None:
    adapter = NotionContractAdapter()
    result_payload = {
        "title": "Production Cycles",
        "url": "https://app.notion.com/p/3797ac7831318153a36ff496c9448ca3",
        "display_url": "https://app.notion.com/p/3797ac7831318153a36ff496c9448ca3?pvs=1",
        "highlight": "Students practice short mini video production cycles.",
        "timestamp": "2026-07-13T22:08:00.000Z",
    }

    result = adapter.from_search_result(result_payload, query="Production Cycles")

    assert isinstance(result, RegistryResource)
    assert result.system == "notion"
    assert result.entity_type == "Page"
    assert result.canonical_id == "https://app.notion.com/p/3797ac7831318153a36ff496c9448ca3"
    assert result.display_name == "Production Cycles"
    assert result.source_of_truth == NOTION_SEARCH_RESULT_SOURCE
    assert result.verification_state == "SearchResultOnly"
    assert result.cache_status == "SearchResult"
    assert result.human_review_required is True
    assert result.write_allowed is False
    assert result.metadata["query"] == "Production Cycles"
    assert result.metadata["fetch_required"] is True
    assert result.metadata["live_verification_required"] is True
    assert result.metadata["semantic_reference"] is True
    assert result.metadata["raw_result"] == result_payload


def test_search_result_without_title_returns_connector_error() -> None:
    adapter = NotionContractAdapter()

    result = adapter.from_search_result({"url": "https://app.notion.com/p/page"})

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.METADATA_INCOMPLETE


def test_live_page_payload_normalizes_to_registry_resource() -> None:
    adapter = NotionContractAdapter()
    payload = {
        "id": "page-123",
        "url": "https://notion.example/page-123",
        "archived": False,
        "created_time": "2026-07-01T00:00:00Z",
        "last_edited_time": "2026-07-02T00:00:00Z",
        "parent": {"database_id": "database-123"},
        "properties": {
            "Name": {
                "type": "title",
                "title": [{"plain_text": "Approved Page"}],
            }
        },
    }

    result = adapter.from_live_page_payload(payload)

    assert isinstance(result, RegistryResource)
    assert result.system == "notion"
    assert result.entity_type == "Page"
    assert result.canonical_id == "page-123"
    assert result.display_name == "Approved Page"
    assert result.parent == "database-123"
    assert result.source_of_truth == LIVE_NOTION_SOURCE
    assert result.verification_state == "VerifiedReadOnly"
    assert result.cache_status == "LiveRead"
    assert result.write_allowed is False
    assert result.metadata["page_body_read"] is False
    assert result.metadata["raw_payload"] == payload


def test_live_database_payload_normalizes_and_preserves_properties() -> None:
    adapter = NotionContractAdapter()
    payload = {
        "id": "database-123",
        "url": "https://notion.example/database-123",
        "archived": False,
        "title": "Approved Database",
        "created_time": "2026-07-01T00:00:00Z",
        "last_edited_time": "2026-07-02T00:00:00Z",
        "parent": {"workspace": "workspace"},
        "properties": {"Status": {"type": "select"}},
    }

    result = adapter.from_live_database_payload(payload)

    assert isinstance(result, RegistryResource)
    assert result.entity_type == "Database"
    assert result.canonical_id == "database-123"
    assert result.display_name == "Approved Database"
    assert result.parent == "workspace"
    assert result.source_of_truth == LIVE_NOTION_SOURCE
    assert result.cache_status == "LiveRead"
    assert result.write_allowed is False
    assert result.metadata["properties"] == {"Status": {"type": "select"}}
    assert result.metadata["properties_schema_visible"] is True


def test_missing_live_page_id_returns_connector_error() -> None:
    adapter = NotionContractAdapter()

    result = adapter.from_live_page_payload({"title": "Missing ID"})

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.METADATA_INCOMPLETE
    assert result.retryable is False


def test_unsupported_cached_kind_returns_connector_error() -> None:
    adapter = NotionContractAdapter()

    result = adapter.from_navigation_record("unknown-kind", {"Name": "Something"})

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.METADATA_INCOMPLETE
    assert result.evidence["kind"] == "unknown-kind"


def test_adapter_exposes_no_write_like_methods() -> None:
    adapter = NotionContractAdapter()
    write_like_methods = {
        "create_page",
        "update_page",
        "delete_page",
        "archive_page",
        "share_page",
        "refresh_cache",
        "repair_relationship",
        "append_block_children",
        "query_database",
        "fetch_tab_values",
        "search",
    }

    assert all(not hasattr(adapter, method) for method in write_like_methods)
    assert adapter.write_capabilities == "none"
    assert adapter.live_system_access is False


def test_report_health_declares_bridge_role_and_canonical_paths() -> None:
    adapter = NotionContractAdapter()

    health = adapter.report_health()

    assert health["health_state"] == "Healthy"
    assert health["live_system_access"] is False
    assert health["write_capabilities"] == "none"
    assert health["role"] == "contract-normalization-bridge"
    assert health["canonical_cached_lookup"] == "08_Tooling/notion-navigation-client/"
    assert health["canonical_search_discovery"] == "Notion search/fetch tooling outside this adapter"
    assert "workflow-scheduler" in health["canonical_live_read"]
