"""Regression checks for Notion lesson-write readback receipt contracts.

These tests use the existing offline fake client; no live Notion writes occur.
"""

from scripts.agent_os_notion_lessons_write.admission import AdmittedRequest
from scripts.agent_os_notion_lessons_write.writer import execute
from tests.agent_os_notion_lessons_write.test_writer import Client, page, update_request


def test_create_canonical_readback_mismatch_has_exact_reason_and_no_verified_claim():
    client = Client()
    client.readback_mismatch = True

    result = execute(AdmittedRequest(100), client)

    assert result["status"] == "uncertain"
    assert result["reason_code"] == "canonical-readback-mismatch"
    assert result["write_attempts"] == 1
    assert result["readback_verified"] is False
    assert client.calls.count("write") == 1
    assert client.calls[-2:] == ["write", "get"]


def test_persisted_update_projects_activation_prerequisites_from_verified_readback():
    existing = page()
    existing["properties"]["Status"]["select"] = {"name": "Applied"}
    existing["properties"]["Surface Before Work?"]["checkbox"] = True
    client = Client(existing)

    result = execute(update_request(), client)

    assert result["status"] == "persisted"
    assert result["reason_code"] == "exact-canonical-readback-confirmed"
    assert result["readback_verified"] is True
    assert result["write_attempts"] == 1
    assert result["activation_prerequisites"] == {
        "required_fields_present": True,
        "missing_owner_activation": [],
        "missing_reviewed_metadata": [],
    }
    assert client.page["properties"]["Status"]["select"] == {"name": "Applied"}
    assert client.page["properties"]["Surface Before Work?"]["checkbox"] is True
    assert client.calls.count("write") == 1