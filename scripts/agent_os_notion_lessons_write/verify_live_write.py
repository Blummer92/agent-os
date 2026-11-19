"""Independent read-only verification of one already-authorized Notion write.

This is a pure read-only post-write observer invoked by the existing
owner-authorized execution runner. It performs a separate exact-page GET
through the canonical Notion reader. Matching state is not proof of write
causality; unchanged results cannot claim a new write.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .admission import notion_id
from .catalog import LESSON_ID, lesson_for
from .writer import _lesson_id, _page, _values

def _outcome(status: str, reason_code: str, *, read_performed: bool = False) -> dict[str, object]:
    return {
        "status": status,
        "reason_code": reason_code,
        "independent_readback_verified": status == "verified-current-state",
        "persisted_state_verified": status == "verified-current-state",
        # State equality cannot prove that this particular write caused it.
        "write_causality_established": False,
        "read_performed": read_performed,
        "verification_write_performed": False,
        "publication_authorized": False,
        "activation_authorized": False,
    }


def verify_persisted_write(
    writer_result: object,
    client_factory: Callable[[str], Any],
    *,
    expected_request_id: str | None = None,
) -> dict[str, object]:
    """Verify current state after an authorized, reported write attempt.

    No client is created for invalid or unchanged receipts. Only finite codes
    are returned, never raw Notion properties, credentials or provider errors.
    A matching page does NOT prove this execution caused the data to change.
    """
    if not isinstance(writer_result, Mapping):
        return _outcome("unverified", "invalid-writer-result")
    status = writer_result.get("status")
    if status == "unchanged":
        if type(writer_result.get("write_attempts")) is int and writer_result["write_attempts"] == 0 and writer_result.get("readback_verified") is True:
            return _outcome("no-new-write", "writer-confirmed-unchanged")
        return _outcome("unverified", "invalid-unchanged-receipt")
    if status != "persisted":
        return _outcome("unverified", "writer-did-not-confirm-persistence")
    if (type(writer_result.get("write_attempts")) is not int
            or writer_result["write_attempts"] != 1
            or writer_result.get("readback_verified") is not True):
        return _outcome("unverified", "writer-receipt-incomplete")

    request_id = writer_result.get("request_id")
    page_id = writer_result.get("page_id")
    lesson_id = writer_result.get("lesson_id")
    revision = writer_result.get("revision")
    if expected_request_id is not None and request_id != expected_request_id:
        return _outcome("unverified", "writer-request-binding-mismatch")
    if (type(request_id) is not str or type(page_id) is not str
            or type(lesson_id) is not str or LESSON_ID.fullmatch(lesson_id) is None
            or type(revision) is not str or not revision):
        return _outcome("unverified", "writer-receipt-identity-invalid")
    try:
        expected = lesson_for(request_id)
        exact_page_id = notion_id(page_id)
    except Exception:
        return _outcome("unverified", "writer-receipt-identity-invalid")

    # Exactly one page GET after the source binding check. Neither verification
    # nor the factory ever calls create/update, and the live adapter is read-only
    # at this invocation site. A provider failure is not proof of absence.
    try:
        client = client_factory(request_id)
        source_id = notion_id(client.verify_binding())
        current = client.get_page(exact_page_id)
    except Exception:
        return _outcome("unverified", "independent-read-unavailable")
    try:
        _page(current, source_id, exact_page_id)
    except Exception:
        return _outcome("unverified", "independent-page-identity-invalid", read_performed=True)
    if current.get("last_edited_time") != revision:
        return _outcome("unverified", "independent-revision-mismatch", read_performed=True)
    if _lesson_id(current) != lesson_id:
        return _outcome("unverified", "independent-lesson-id-mismatch", read_performed=True)
    try:
        if _values(current, expected) != expected:
            return _outcome("unverified", "independent-content-mismatch", read_performed=True)
    except Exception:
        return _outcome("unverified", "independent-content-invalid", read_performed=True)
    return _outcome("verified-current-state", "independent-exact-canonical-state-confirmed", read_performed=True)

