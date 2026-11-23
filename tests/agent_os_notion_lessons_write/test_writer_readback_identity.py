"""Regression tests for the final Notion write-readback identity boundary.

Covers execute() mutmut variants 214 and 217 which omit the expected page ID
from the final post-write _page() validation call.
"""

from scripts.agent_os_notion_lessons_write.admission import AdmittedRequest
from scripts.agent_os_notion_lessons_write.writer import execute
from tests.agent_os_notion_lessons_write.test_writer import (
    Client,
    PAGE_ID,
    SOURCE_ID,
    page,
    update_request,
)


class _WrongIdOnPostWriteReadback(Client):
    """Return canonical content from a page whose ID is not the written ID."""

    def get_page(self, page_id):
        record = super().get_page(page_id)
        if "write" in self.calls:
            # The canonical content, parent and revision remain intact.
            # Only the ID of the page returned by the final readback changes.
            record["id"] = SOURCE_ID
        return record


def test_create_readback_wrong_page_id_never_claims_persistence():
    client = _WrongIdOnPostWriteReadback()

    result = execute(AdmittedRequest(100), client)

    assert result["status"] == "uncertain"
    assert result["reason_code"] == "page-identity-mismatch"
    assert result["readback_verified"] is False
    assert result["write_attempts"] == 1
    assert result["page_id"] == PAGE_ID
    assert client.calls.count("write") == 1
    assert client.calls[-1] == "get"


def test_update_readback_wrong_page_id_never_claims_persistence():
    client = _WrongIdOnPostWriteReadback(page())

    result = execute(update_request(), client)

    assert result["status"] == "uncertain"
    assert result["reason_code"] == "page-identity-mismatch"
    assert result["readback_verified"] is False
    assert result["write_attempts"] == 1
    assert result["page_id"] == PAGE_ID
    assert client.calls.count("write") == 1
    assert client.calls.count("get") == 3