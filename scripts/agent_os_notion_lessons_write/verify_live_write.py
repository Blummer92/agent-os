"""Independent read-only verification of one already-authorized Notion write.

This is a post-write observer, not a writer or a new trigger. It accepts only
the writer's same-job bounded result, then performs a separate exact-page GET
through the existing Notion read adapter. It never claims a write for an
"unchanged" result, nor trusts a writer receipt without fresh canonical data.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .admission import notion_id
from .catalog import LESSON_ID, lesson_for
from .writer import _lesson_id, _page, _values

_MAX_RESULT_BYTES = 16 * 1024
_OK = frozenset({"verified-persisted", "no-new-write"})


def _outcome(status: str, reason_code: str, *, read_performed: bool = False) -> dict[str, object]:
    return {
        "status": status,
        "reason_code": reason_code,
        "independent_readback_verified": status == "verified-persisted",
        "write_verified": status == "verified-persisted",
        "read_performed": read_performed,
        "notion_write_performed": False,
        "publication_authorized": False,
        "activation_authorized": False,
    }


def verify_persisted_write(
    writer_result: object,
    client_factory: Callable[[str], Any],
) -> dict[str, object]:
    """Require writer persistence evidence AND a new exact-page provider GET.

    The factory is not called for a missing/invalid receipt or an unchanged
    lesson. Result fields are finite codes only; no provider rows, credentials,
    exception messages, or arbitrary request text may enter the output.
    """
    if not isinstance(writer_result, Mapping):
        return _outcome("unverified", "invalid-writer-result")
    status = writer_result.get("status")
    if status == "unchanged":
        if writer_result.get("write_attempts") == 0 and writer_result.get("readback_verified") is True:
            return _outcome("no-new-write", "writer-confirmed-unchanged")
        return _outcome("unverified", "invalid-unchanged-receipt")
    if status != "persisted":
        return _outcome("unverified", "writer-did-not-confirm-persistence")
    if writer_result.get("write_attempts") != 1 or writer_result.get("readback_verified") is not True:
        return _outcome("unverified", "writer-receipt-incomplete")

    request_id = writer_result.get("request_id")
    page_id = writer_result.get("page_id")
    lesson_id = writer_result.get("lesson_id")
    revision = writer_result.get("revision")
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
    return _outcome("verified-persisted", "independent-exact-canonical-readback-confirmed", read_performed=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writer-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw = args.writer_result.read_bytes()
        if len(raw) > _MAX_RESULT_BYTES:
            raise ValueError("bounded result exceeded")
        writer_result = json.loads(raw)
    except Exception:
        writer_result = None

    def live_client(request_id: str) -> object:
        # Lazy credential access: only an eligible same-run persisted receipt
        # reaches this path. Reuse the production read adapter, not a new token.
        from .live import LiveLessonsClient
        return LiveLessonsClient(request_id)

    verified = verify_persisted_write(writer_result, live_client)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(verified, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if verified["status"] in _OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
