"""One finite create/update with reconciliation and immediate exact readback.

The injected client owns credential/network capability. No raw response, private
value, credential or provider diagnostic is emitted as public result evidence.
"""
from __future__ import annotations

from collections.abc import Mapping
from .admission import AdmittedRequest, WriteBlocked, notion_id
from .catalog import REQUEST_ID, WRITABLE_TYPES, lesson_for


def properties(request_id: str = REQUEST_ID) -> dict:
    return {name: {WRITABLE_TYPES[name]: [{"type": "text", "text": {"content": value}}]}
            for name, value in lesson_for(request_id).items()}


def _values(page: Mapping) -> dict:
    raw = page.get("properties")
    if not isinstance(raw, Mapping):
        raise WriteBlocked("malformed-page-properties")
    values = {}
    for name, kind in WRITABLE_TYPES.items():
        prop = raw.get(name)
        if not isinstance(prop, Mapping) or prop.get("type") != kind:
            raise WriteBlocked("page-property-type-mismatch")
        items = prop.get(kind)
        if type(items) is not list or len(items) > 100:
            raise WriteBlocked("malformed-page-properties")
        texts = []
        for item in items:
            if not isinstance(item, Mapping) or item.get("type") != "text":
                raise WriteBlocked("non-text-lesson-content")
            value = item.get("plain_text", item.get("text", {}).get("content"))
            if type(value) is not str or len(value) > 2000:
                raise WriteBlocked("malformed-page-properties")
            texts.append(value)
        values[name] = "".join(texts)
    return values


def _page(page: Mapping, source_id: str, expected_id: str | None = None) -> str:
    if not isinstance(page, Mapping):
        raise WriteBlocked("malformed-page")
    page_id = notion_id(page.get("id"))
    if expected_id is not None and page_id != notion_id(expected_id):
        raise WriteBlocked("page-identity-mismatch")
    if any(page.get(key) is True for key in ("archived", "is_archived", "in_trash")):
        raise WriteBlocked("inactive-page")
    parent = page.get("parent", {})
    if parent.get("type") != "data_source_id" or notion_id(parent.get("data_source_id")) != source_id:
        raise WriteBlocked("page-destination-mismatch")
    if type(page.get("last_edited_time")) is not str or not page["last_edited_time"]:
        raise WriteBlocked("page-revision-required")
    return page_id


def _find(client, source_id: str, lesson: Mapping) -> Mapping | None:
    result = client.find_exact(lesson["Lesson Learned"])
    if not isinstance(result, Mapping) or result.get("has_more") is not False:
        raise WriteBlocked("incomplete-reconciliation")
    rows = result.get("results")
    if type(rows) is not list or len(rows) > 1:
        raise WriteBlocked("ambiguous-lesson")
    if not rows:
        return None
    _page(rows[0], source_id)
    if _values(rows[0])["Lesson Learned"] != lesson["Lesson Learned"]:
        raise WriteBlocked("query-identity-mismatch")
    return rows[0]


def execute(request: AdmittedRequest, client) -> dict:
    """Consume owner admission under the existing policy, never infer authority."""
    result = {
        "request_id": request.request_id, "comment_id": request.comment_id,
        "status": "blocked", "reason_code": "precheck-incomplete",
        "write_attempts": 0, "readback_verified": False,
        "page_id": None, "revision": None,
    }
    try:
        lesson = lesson_for(request.request_id)
        source_id = notion_id(client.verify_binding())
        schema = client.schema()
        if not isinstance(schema, Mapping) or notion_id(schema.get("id")) != source_id:
            raise WriteBlocked("schema-destination-mismatch")
        if any(schema.get(key) is True for key in ("archived", "is_archived", "in_trash")):
            raise WriteBlocked("inactive-data-source")
        raw = schema.get("properties", {})
        expected = {**WRITABLE_TYPES, "Lesson ID": "unique_id", "Status": "select"}
        if not isinstance(raw, Mapping) or any(
            not isinstance(raw.get(name), Mapping) or raw[name].get("type") != kind
            for name, kind in expected.items()
        ):
            raise WriteBlocked("live-schema-drift")
        existing = _find(client, source_id, lesson)
        page_id = None
        if existing is not None:
            page_id = _page(existing, source_id)
            existing = client.get_page(page_id)
            _page(existing, source_id, page_id)
            values = _values(existing)
            if values["Lesson Learned"] != lesson["Lesson Learned"]:
                raise WriteBlocked("lesson-identity-changed")
            result.update(page_id=page_id, revision=existing["last_edited_time"])
            if values == dict(lesson):
                result.update(status="unchanged", reason_code="identical-canonical-content", readback_verified=True)
                return result
            if (request.expected_page_id, request.expected_revision) != (page_id, existing["last_edited_time"]):
                result.update(status="conflict", reason_code="explicit-exact-update-required")
                return result
            # Reacquire at the mutation boundary. Never overwrite a newer page.
            current = client.get_page(page_id)
            _page(current, source_id, page_id)
            if current != existing:
                result.update(status="conflict", reason_code="page-changed-before-write")
                return result
        elif request.expected_page_id is not None:
            raise WriteBlocked("update-target-missing")
        elif _find(client, source_id, lesson) is not None:
            result.update(status="conflict", reason_code="lesson-appeared-before-create")
            return result
        intended = properties(request.request_id)
        # No automatic retry, including timeout/429/provider errors. Once a
        # write is attempted, uncertainty must never be reported as zero writes.
        result.update(write_attempts=1, status="uncertain", reason_code="write-or-readback-unconfirmed")
        receipt_mismatch = False
        try:
            receipt = client.update(page_id, intended) if page_id else client.create(intended)
            if not isinstance(receipt, Mapping):
                raise WriteBlocked("malformed-write-receipt")
            target = notion_id(receipt.get("id"))
            if page_id is not None and target != page_id:
                receipt_mismatch = True
            else:
                page_id = target
        except Exception:
            # Existing exact target can still be canonically read. A create
            # without an exact returned identity stays uncertain; never retry.
            if page_id is None:
                return result
        result["page_id"] = page_id
        readback = client.get_page(page_id)
        _page(readback, source_id, page_id)
        if receipt_mismatch:
            result.update(reason_code="write-receipt-target-mismatch")
            return result
        if _values(readback) != dict(lesson):
            result.update(reason_code="canonical-readback-mismatch")
            return result
        if existing is not None:
            before = {key: value for key, value in existing["properties"].items() if key not in WRITABLE_TYPES}
            after = {key: value for key, value in readback["properties"].items() if key not in WRITABLE_TYPES}
            if before != after:
                result.update(reason_code="non-routine-property-changed")
                return result
        result.update(status="persisted", reason_code="exact-canonical-readback-confirmed",
                      readback_verified=True, revision=readback["last_edited_time"])
    except WriteBlocked as exc:
        result["reason_code"] = str(exc)
    except Exception:
        result["reason_code"] = "provider-capability-or-read-unavailable"
    return result
