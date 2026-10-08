"""One finite create/update with reconciliation and immediate exact readback.

The injected client owns credential/network capability. No raw response, private
value, credential or provider diagnostic is emitted as public result evidence.

Create entries reconcile by exact title. Update entries (#3417) address their
reviewed target by canonical ``Lesson ID`` and require the owner command to bind
the exact current revision; a stale revision is refused with zero writes.
"""
from __future__ import annotations

from collections.abc import Mapping
from .admission import AdmittedRequest, WriteBlocked, notion_id
from .catalog import LESSON_ID, PROTECTED_FIELDS, REQUEST_ID, WRITABLE_TYPES, entry_for, lesson_for


def properties(request_id: str = REQUEST_ID) -> dict:
    """Notion property payload for exactly the reviewed fields of one entry."""
    payload = {}
    for name, value in lesson_for(request_id).items():
        kind = WRITABLE_TYPES[name]
        if kind in ("title", "rich_text"):
            payload[name] = {kind: [{"type": "text", "text": {"content": value}}]}
        elif kind == "select":
            payload[name] = {"select": {"name": value}}
        elif kind == "multi_select":
            payload[name] = {"multi_select": [{"name": item} for item in value]}
        else:
            payload[name] = {"url": value}
    if set(payload) & PROTECTED_FIELDS:
        raise WriteBlocked("protected-activation-field-refused")
    return payload


def _text(items: object) -> str:
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
    return "".join(texts)


def _values(page: Mapping, names) -> dict:
    """Comparable values for the named reviewed fields only."""
    raw = page.get("properties")
    if not isinstance(raw, Mapping):
        raise WriteBlocked("malformed-page-properties")
    values = {}
    for name in names:
        kind = WRITABLE_TYPES[name]
        prop = raw.get(name)
        if not isinstance(prop, Mapping) or prop.get("type") != kind:
            raise WriteBlocked("page-property-type-mismatch")
        item = prop.get(kind)
        if kind in ("title", "rich_text"):
            values[name] = _text(item)
        elif kind == "select":
            values[name] = item.get("name") if isinstance(item, Mapping) else None
        elif kind == "multi_select":
            if type(item) is not list or len(item) > 100:
                raise WriteBlocked("malformed-page-properties")
            values[name] = tuple(option.get("name") for option in item if isinstance(option, Mapping))
        else:
            values[name] = item
    return values


def _lesson_id(page: Mapping) -> str | None:
    prop = page.get("properties", {}).get("Lesson ID")
    if not isinstance(prop, Mapping) or prop.get("type") != "unique_id":
        return None
    value = prop.get("unique_id") or {}
    number, prefix = value.get("number"), value.get("prefix")
    if type(number) is not int or prefix != "LL":
        return None
    return f"LL-{number}"


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


def _single(result: object, source_id: str) -> Mapping | None:
    if not isinstance(result, Mapping) or result.get("has_more") is not False:
        raise WriteBlocked("incomplete-reconciliation")
    rows = result.get("results")
    if type(rows) is not list or len(rows) > 1:
        raise WriteBlocked("ambiguous-lesson")
    if not rows:
        return None
    _page(rows[0], source_id)
    return rows[0]


def _find_title(client, source_id: str, lesson: Mapping) -> Mapping | None:
    row = _single(client.find_exact(lesson["Lesson Learned"]), source_id)
    if row is not None and _values(row, ("Lesson Learned",))["Lesson Learned"] != lesson["Lesson Learned"]:
        raise WriteBlocked("query-identity-mismatch")
    return row


def _find_lesson_id(client, source_id: str, lesson_id: str) -> Mapping | None:
    match = LESSON_ID.fullmatch(lesson_id)
    if match is None:
        raise WriteBlocked("reviewed-target-lesson-mismatch")
    row = _single(client.find_lesson(int(match.group(1))), source_id)
    if row is not None and _lesson_id(row) != lesson_id:
        raise WriteBlocked("query-identity-mismatch")
    return row


def _check_schema(schema: object, source_id: str, lesson: Mapping) -> None:
    if not isinstance(schema, Mapping) or notion_id(schema.get("id")) != source_id:
        raise WriteBlocked("schema-destination-mismatch")
    if any(schema.get(key) is True for key in ("archived", "is_archived", "in_trash")):
        raise WriteBlocked("inactive-data-source")
    raw = schema.get("properties", {})
    expected = {**{name: WRITABLE_TYPES[name] for name in lesson},
                "Lesson ID": "unique_id", "Status": "select"}
    if not isinstance(raw, Mapping) or any(
        not isinstance(raw.get(name), Mapping) or raw[name].get("type") != kind
        for name, kind in expected.items()
    ):
        raise WriteBlocked("live-schema-drift")
    # A select/multi-select value outside the live options would make Notion
    # create a new option: that is a schema change, never a routine write.
    for name, value in lesson.items():
        kind = WRITABLE_TYPES[name]
        if kind not in ("select", "multi_select"):
            continue
        options = raw[name].get(kind, {}).get("options")
        names = {item.get("name") for item in options or () if isinstance(item, Mapping)}
        wanted = value if kind == "multi_select" else (value,)
        if not names or any(item not in names for item in wanted):
            raise WriteBlocked("descriptive-option-not-in-live-schema")


def execute(request: AdmittedRequest, client) -> dict:
    """Consume owner admission under the existing policy, never infer authority."""
    result = {
        "request_id": request.request_id, "comment_id": request.comment_id,
        "status": "blocked", "reason_code": "precheck-incomplete",
        "write_attempts": 0, "readback_verified": False,
        "page_id": None, "lesson_id": None, "revision": None,
    }
    try:
        lesson = dict(lesson_for(request.request_id))
        target = entry_for(request.request_id)["target_lesson_id"]
        if target != request.expected_lesson_id:
            raise WriteBlocked("reviewed-target-lesson-mismatch")
        source_id = notion_id(client.verify_binding())
        _check_schema(client.schema(), source_id, lesson)
        if target is not None:
            existing = _find_lesson_id(client, source_id, target)
            if existing is None:
                raise WriteBlocked("update-target-missing")
        else:
            existing = _find_title(client, source_id, lesson)
        page_id = None
        if existing is not None:
            page_id = _page(existing, source_id)
            existing = client.get_page(page_id)
            _page(existing, source_id, page_id)
            if target is not None and _lesson_id(existing) != target:
                raise WriteBlocked("lesson-identity-changed")
            result.update(page_id=page_id, lesson_id=_lesson_id(existing),
                          revision=existing["last_edited_time"])
            if _values(existing, lesson) == lesson:
                result.update(status="unchanged", reason_code="identical-canonical-content", readback_verified=True)
                return result
            if target is None:
                # A create entry never overwrites; refinement needs a reviewed
                # update entry bound to the canonical Lesson ID.
                result.update(status="conflict", reason_code="existing-lesson-requires-reviewed-update-entry")
                return result
            if request.expected_revision != existing["last_edited_time"]:
                result.update(status="conflict", reason_code="stale-revision-refused")
                return result
            # Reacquire at the mutation boundary. Never overwrite a newer page.
            current = client.get_page(page_id)
            _page(current, source_id, page_id)
            if current != existing:
                result.update(status="conflict", reason_code="page-changed-before-write")
                return result
        elif _find_title(client, source_id, lesson) is not None:
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
            written = notion_id(receipt.get("id"))
            if page_id is not None and written != page_id:
                receipt_mismatch = True
            else:
                page_id = written
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
        if _values(readback, lesson) != lesson:
            result.update(reason_code="canonical-readback-mismatch")
            return result
        if existing is not None:
            before = {key: value for key, value in existing["properties"].items() if key not in lesson}
            after = {key: value for key, value in readback["properties"].items() if key not in lesson}
            if before != after:
                result.update(reason_code="non-routine-property-changed")
                return result
        result.update(status="persisted", reason_code="exact-canonical-readback-confirmed",
                      readback_verified=True, lesson_id=_lesson_id(readback),
                      revision=readback["last_edited_time"])
    except WriteBlocked as exc:
        result["reason_code"] = str(exc)
    except Exception:
        result["reason_code"] = "provider-capability-or-read-unavailable"
    return result
