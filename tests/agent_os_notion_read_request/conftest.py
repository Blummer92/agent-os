"""Fixtures for the #2283 GitHub-controlled Notion read tests."""

from __future__ import annotations

import json

import pytest

from .notion_read_support import verified_payload
from scripts.agent_os_notion_read_request import load_catalog, parse_catalog
from scripts.agent_os_notion_read_request.catalog import CATALOG_PATH


@pytest.fixture
def shipped_catalog():
    """The repository-owned catalog exactly as it ships."""
    return load_catalog()


@pytest.fixture
def catalog_payload() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def verified_catalog(catalog_payload):
    """A test-only catalog whose bindings are marked verified and bound."""
    return parse_catalog(verified_payload(catalog_payload))
