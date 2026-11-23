"""Regression coverage for exact Notion write targets and uncertainty receipts.

Add this file to tests/agent_os_notion_lessons_write/ in the Agent OS repo.
"""

from scripts.agent_os_notion_lessons_write.admission import AdmittedRequest
from scripts.agent_os_notion_lessons_write.writer import execute
from tests.agent_os_notion_lessons_write.test_writer import (
    Client,
    PAGE_ID,
    page,
    update_request,
)


def test_create_timeout_retains_exact_uncertain_reason_and_single_write():
    client = Client()
    client.raise_mutation = True

    result = execute(AdmittedRequest(100), client)

    assert result["status"] == "uncertain"
    assert result["reason_code"] == "write-or-readback-unconfirmed"
    assert result["write_attempts"] == 1
    assert result["readback_verified"] is False
    assert client.calls.count("write") == 1


def test_update_passes_exact_canonical_page_id_to_provider():
    class RecordingClient(Client):
        def __init__(self, existing):
            super().__init__(existing)
            self.update_page_ids = []

        def update(self, page_id, intended):
            self.update_page_ids.append(page_id)
            return super().update(page_id, intended)

    client = RecordingClient(page())

    result = execute(update_request(), client)

    assert result["status"] == "persisted"
    assert result["reason_code"] == "exact-canonical-readback-confirmed"
    assert result["write_attempts"] == 1
    assert client.update_page_ids == [PAGE_ID]