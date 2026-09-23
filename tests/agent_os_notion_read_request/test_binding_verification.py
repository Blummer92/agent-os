"""Focused regression coverage for the #2283 live binding bootstrap."""

from __future__ import annotations

import pytest

from scripts.agent_os_notion_read_request.binding_verification import (
    CANONICAL_REGISTRY_DATABASE_ID,
    CANONICAL_REGISTRY_TITLE,
    PHOTOGRAPHY_FOUNDATIONS_PAGE_ID,
    VERIFICATION_REQUEST_ID,
    VISUAL_ASSET_LIBRARY_DATABASE_ID,
    VISUAL_ASSET_LIBRARY_TITLE,
    admit_binding_verification_request,
    verify_live_bindings,
)
from scripts.agent_os_notion_read_request.models import NotionReadRequestError
from tests.agent_os_notion_read_request.notion_read_support import ACTOR, REPOSITORY, transport


class VerificationAdapter:
    def __init__(self, *, visual_sources=None):
        self.calls = []
        self.visual_sources = visual_sources or [
            {"id": "visual-data-source-current", "name": VISUAL_ASSET_LIBRARY_TITLE}
        ]

    def execute(self, task):
        self.calls.append(dict(task.payload))
        action = task.payload["action"]
        if action == "get_database":
            database_id = task.payload["database_id"]
            if database_id == CANONICAL_REGISTRY_DATABASE_ID:
                output = {
                    "id": CANONICAL_REGISTRY_DATABASE_ID,
                    "title": CANONICAL_REGISTRY_TITLE,
                    "archived": False,
                    "in_trash": False,
                    "data_sources": [
                        {"id": "canonical-data-source-current", "name": CANONICAL_REGISTRY_TITLE}
                    ],
                }
            elif database_id == VISUAL_ASSET_LIBRARY_DATABASE_ID:
                output = {
                    "id": VISUAL_ASSET_LIBRARY_DATABASE_ID,
                    "title": VISUAL_ASSET_LIBRARY_TITLE,
                    "archived": False,
                    "in_trash": False,
                    "data_sources": self.visual_sources,
                }
            else:  # pragma: no cover - fixed vocabulary must make this unreachable
                raise AssertionError(database_id)
            return {"status": "success", "output": output}
        if action == "get_page":
            return {
                "status": "success",
                "output": {
                    "id": PHOTOGRAPHY_FOUNDATIONS_PAGE_ID,
                    "archived": False,
                    "in_trash": False,
                },
            }
        raise AssertionError(action)


def test_verification_request_is_exact_and_authority_stays_false() -> None:
    decision = admit_binding_verification_request(
        transport(request_id=VERIFICATION_REQUEST_ID),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert decision["status"] == "admitted"
    assert decision["secret_dispatch_authorized"] is True
    assert decision["allowed_read_actions"] == ["get_database", "get_page"]
    assert decision["write_allowed"] is False
    assert decision["production_authorized"] is False
    assert decision["notion_write_reachable"] is False
    assert decision["gce_required"] is False


def test_verification_request_rejects_wrong_actor_or_issue() -> None:
    wrong_actor = admit_binding_verification_request(
        transport(request_id=VERIFICATION_REQUEST_ID, actor="someone-else"),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    wrong_issue = admit_binding_verification_request(
        transport(request_id=VERIFICATION_REQUEST_ID, issue_number=999),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert wrong_actor["secret_dispatch_authorized"] is False
    assert wrong_actor["reason_codes"] == ["actor-not-allowed"]
    assert wrong_issue["secret_dispatch_authorized"] is False
    assert wrong_issue["reason_codes"] == ["issue-target-mismatch"]


def test_live_verification_uses_exactly_two_databases_and_one_page() -> None:
    adapter = VerificationAdapter()
    evidence = verify_live_bindings(adapter, generated_at="run:1")

    assert [call["action"] for call in adapter.calls] == [
        "get_database",
        "get_database",
        "get_page",
    ]
    assert evidence["canonical_registry"]["data_source_id"] == "canonical-data-source-current"
    assert evidence["visual_asset_library"]["data_source_id"] == "visual-data-source-current"
    assert evidence["photography_foundations"]["provider_page_id"] == PHOTOGRAPHY_FOUNDATIONS_PAGE_ID
    assert evidence["notion_writes_performed"] is False
    assert evidence["drive_writes_performed"] is False
    assert evidence["gce_invoked"] is False


def test_ambiguous_data_source_identity_fails_closed() -> None:
    adapter = VerificationAdapter(
        visual_sources=[
            {"id": "one", "name": "Other"},
            {"id": "two", "name": "Also Other"},
        ]
    )
    with pytest.raises(NotionReadRequestError, match="data source identity is ambiguous"):
        verify_live_bindings(adapter, generated_at="run:1")
