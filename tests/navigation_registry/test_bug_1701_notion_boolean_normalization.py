"""Regression coverage for #1701."""

import pytest

from navigation_registry.connectors.notion_contract_adapter import NotionContractAdapter


@pytest.mark.parametrize("field", ["archived", "page_body_read"])
@pytest.mark.parametrize("value", ["false", "true", "0", "1"])
def test_page_string_booleans_do_not_become_canonical_truth_values(field, value):
    result = NotionContractAdapter().from_live_page_payload(
        {"id": "page-1", "title": "Page", field: value}
    )
    # Malformed live evidence must not be silently converted with Python truthiness.
    assert result.metadata[field] is not True


def test_real_page_booleans_are_preserved():
    result = NotionContractAdapter().from_live_page_payload(
        {"id": "page-1", "title": "Page", "archived": False, "page_body_read": True}
    )
    assert result.metadata["archived"] is False
    assert result.metadata["page_body_read"] is True


@pytest.mark.parametrize("value", ["false", "true", "0", "1"])
def test_database_string_archived_does_not_become_true(value):
    result = NotionContractAdapter().from_live_database_payload(
        {"id": "db-1", "title": "Database", "archived": value}
    )
    assert result.metadata["archived"] is not True
