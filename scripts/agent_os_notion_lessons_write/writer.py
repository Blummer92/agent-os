"""One finite create/update with reconciliation and immediate exact readback.

The injected client owns credential/network capability. No raw response, private
value, credential or provider diagnostic is emitted as public result evidence.

Create entries reconcile by exact title and fail closed on a bounded semantic
duplicate-candidate scan before reserving or creating. Update entries (#3417) address their
reviewed target by canonical ``Lesson ID`` and require the owner command to bind
the exact current revision; a stale revision is refused with zero writes.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
import unicodedata
from .admission import AdmittedRequest, WriteBlocked, notion_id
from .catalog import LESSON_ID, MAX_SUPPORTING_REFS, NARRATIVE_TYPES, PROTECTED_FIELDS, REQUEST_ID, SUPPORTING_SOURCE_LINKS, WRITABLE_TYPES, entry_for, lesson_for


def properties(request_id: str = REQUEST_ID) -> dict:
    """Notion property payload for exactly the reviewed fields of one entry."""
    payload = {}
    for name, value in lesson_for(request_id).items():
        kind = WRITABLE_TYPES[name]
        if name == SUPPORTING_SOURCE_LINKS:
            # One canonical ref per rich_text item; the catalog already
            # bounded and validated the tuple (max five, distinct, canonical).
            # A GitHub ref also carries a link annotation with the same
            # URL: that annotation is what Notion renders clickable. A
            # plain-text URL sent through the API is not reliably linkified,
            # so without it the refs would be visible but not clickable.
            # The link belongs INSIDE the `text` object per the Notion
            # rich_text schema (responses mirror it as top-level `href`);
            # a top-level `link` key is not part of the API shape.
            # Repo-relative governance paths are not URLs and stay plain.
            items = []
            for ref in value:
                item = {"type": "text", "text": {"content": ref}}
                if ref.startswith("https://"):
                    item["text"]["link"] = {"url": ref}
                items.append(item)
            payload[name] = {"rich_text": items}
        elif kind in ("title", "rich_text"):
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
        if name == SUPPORTING_SOURCE_LINKS:
            # Read back one ref per rich_text item, in order; joining them
            # into one string would destroy the per-ref boundary the
            # catalog validated.
            items = prop.get("rich_text")
            if type(items) is not list:
                raise WriteBlocked("malformed-page-properties")
            values[name] = tuple(_text([item]) for item in items)
            continue
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


# Bounded, deterministic duplicate *qualification*, not semantic equivalence proof.
# Normalize common wording differences in lesson titles. A possible match is
# sent to reviewed Lesson-ID update; it is never modified by a create entry.
_DUPLICATE_WORDS = {
    "hosts": "host", "consumer": "host", "consumers": "host",
    "runtime": "host", "runtimes": "host", "runner": "host", "runners": "host",
    "continuation": "continue", "continuations": "continue",
    "continues": "continue", "continued": "continue",
    "resumption": "continue", "resume": "continue", "resuming": "continue",
    "execution": "execute", "executed": "execute", "executing": "execute",
    "dispatch": "execute", "dispatched": "execute", "dispatching": "execute",
    "automatic": "automate", "automatically": "automate", "automated": "automate",
    "payload": "signal", "payloads": "signal", "metadata": "signal",
    "decision": "signal", "decisions": "signal", "emitted": "signal",
    "emits": "signal", "emit": "signal", "signal": "signal", "signals": "signal",
}
_DUPLICATE_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "before", "by", "do",
    "for", "from", "in", "into", "is", "it", "must", "not", "of",
    "on", "or", "only", "the", "to", "when", "with", "without",
})
_MAX_DUPLICATE_ROWS = 200


def _title_terms(title: str) -> frozenset[str]:
    if type(title) is not str or not title.strip() or len(title) > 2000:
        raise WriteBlocked("malformed-duplicate-title")
    tokens = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", title).casefold())
    return frozenset(_DUPLICATE_WORDS.get(token, token) for token in tokens
                     if token not in _DUPLICATE_STOPWORDS)


def _possible_same_lesson(title: str, other_title: str) -> bool:
    """High-recall *review* signal, with shared concepts AND proportional overlap.

    This heuristic intentionally does not claim that distinct phrasing is proof
    of duplication. It only blocks risky automatic creation. Missing matches
    remain possible and must be covered by the human catalog review.
    """
    left, right = _title_terms(title), _title_terms(other_title)
    if not left or not right:
        raise WriteBlocked("malformed-duplicate-title")
    if left == right:
        return True
    shared = len(left & right)
    return shared >= 3 and 2 * shared >= min(len(left), len(right))


def _duplicate_evidence_review(row: Mapping, lesson: Mapping, lesson_id: str) -> dict:
    """Bounded, read-only handoff; not a claim of verified evidence or identity.

    Only reviewed catalog refs and field *names* enter the public receipt.
    Provider-supplied narrative, URLs and private property values never do.
    A reviewer must verify evidence and register a canonical Lesson-ID update
    separately; an overlap match alone does not authorize any mutation.
    """
    candidate_refs = tuple(dict.fromkeys(
        ([lesson["Source Link"]] if "Source Link" in lesson else [])
        + list(lesson.get(SUPPORTING_SOURCE_LINKS, ()))
    ))
    review = {
        "lesson_id": lesson_id,
        "candidate_source_refs_to_verify": list(candidate_refs),
        "new_source_refs_to_review": [],
        "source_comparison": "unavailable",
        "claim_fields_to_review": [],
        "claim_comparison": "unavailable",
        "review_action": "register-reviewed-lesson-id-update",
        "automatic_update_authorized": False,
    }
    try:
        current = _values(row, ("Source Link", SUPPORTING_SOURCE_LINKS))
        current_refs = set(current[SUPPORTING_SOURCE_LINKS])
        if current["Source Link"]:
            current_refs.add(current["Source Link"])
        if (len(current[SUPPORTING_SOURCE_LINKS]) > MAX_SUPPORTING_REFS
                or any(type(value) is not str or not value.strip() or len(value) > 512
                       for value in current_refs)):
            raise WriteBlocked("malformed-duplicate-source-state")
        additional = [value for value in candidate_refs if value not in current_refs]
        proposed = set(current[SUPPORTING_SOURCE_LINKS]) | set(additional)
        review.update(
            source_comparison="complete",
            new_source_refs_to_review=additional,
            supporting_source_capacity=("available" if len(proposed) <= MAX_SUPPORTING_REFS
                                        else "limit-exceeded"),
        )
    except WriteBlocked:
        # The duplicate still blocks create; never infer that missing source
        # metadata means the candidate's references are novel or safe.
        pass
    try:
        review["claim_fields_to_review"] = [
            field for field in NARRATIVE_TYPES
            if field in lesson and _values(row, (field,))[field] != lesson[field]
        ]
        review["claim_comparison"] = "text-difference-only"
    except WriteBlocked:
        # Semantic equivalence, contradiction and evidentiary weight require
        # independent human/source review even when texts compare cleanly.
        review["claim_fields_to_review"] = []
    return review


def _check_evidence_append(existing: Mapping, lesson: Mapping) -> tuple[str, ...] | None:
    """An evidence-only patch may append, never erase old supporting sources.

    Omitting Source Link preserves the primary source through the existing
    non-routine-property readback guard. Existing broader source repairs that
    deliberately replace Source Link remain separately reviewed operations.
    """
    if SUPPORTING_SOURCE_LINKS not in lesson or "Source Link" in lesson:
        return None
    old = _values(existing, (SUPPORTING_SOURCE_LINKS,))[SUPPORTING_SOURCE_LINKS]
    wanted = lesson[SUPPORTING_SOURCE_LINKS]
    if (len(old) > MAX_SUPPORTING_REFS or len(set(old)) != len(old)
            or not set(old).issubset(wanted)):
        raise WriteBlocked("supporting-evidence-would-be-lost")
    return tuple(value for value in wanted if value not in old)


def _find_semantic_duplicates(client, source_id: str, lesson: Mapping) -> tuple[tuple[str, ...], list[dict]]:
    """Inspect one complete, capped canonical catalog snapshot; never mutate.

    Incomplete pagination, malformed identities, duplicates and schema drift
    all refuse before reservation. Returned IDs are canonical and bounded;
    raw Notion content never enters public receipts.
    """
    result = client.find_create_candidates()
    if not isinstance(result, Mapping) or result.get("has_more") is not False:
        raise WriteBlocked("incomplete-duplicate-scan")
    rows = result.get("results")
    if type(rows) is not list or len(rows) > _MAX_DUPLICATE_ROWS:
        raise WriteBlocked("incomplete-duplicate-scan")
    matches = set()
    reviews = {}
    seen_page_ids = set()
    for row in rows:
        page_id = _page(row, source_id)
        if page_id in seen_page_ids:
            raise WriteBlocked("ambiguous-duplicate-scan")
        seen_page_ids.add(page_id)
        row_title = _values(row, ("Lesson Learned",))["Lesson Learned"]
        if _possible_same_lesson(lesson["Lesson Learned"], row_title):
            lesson_id = _lesson_id(row)
            if lesson_id is None or lesson_id in matches:
                raise WriteBlocked("ambiguous-duplicate-scan")
            matches.add(lesson_id)
            reviews[lesson_id] = _duplicate_evidence_review(row, lesson, lesson_id)
    if len(matches) > 10:
        raise WriteBlocked("ambiguous-duplicate-scan")
    ordered = tuple(sorted(matches, key=lambda value: int(value[3:])))
    return ordered, [reviews[lesson_id] for lesson_id in ordered]


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


def activation_prerequisites(page: Mapping) -> dict:
    """Report which CKR6-required fields are still missing on one canonical readback.

    A persisted lesson is not a retrievable lesson: the CKR6 reader needs Area,
    Learning Type, Status and a Source Link (without a usable one the lesson is
    only ``manual-review``), and retrieval needs Surface Before Work? checked.
    Status and Surface are owner-only (``PROTECTED_FIELDS``); the rest are
    reviewed catalog metadata.

    ``required_fields_present`` is a NECESSARY condition, never eligibility. It
    reads non-blank presence of those five fields only (Status as a ``select``,
    as the live schema requires). It still shows True for
    a present but unrecognized Area, Learning Type or Status, Status "Archived
    note", a Source Link the reader will not accept (anything but ``https://
    github.com/`` or a repo-relative governance path, or over 512 characters),
    and missing narrative fields the reader also needs. The reader alone decides
    eligibility; contract tests pin that it never selects a page this reports as
    incomplete. Nothing here is written or authorized.
    """
    props = page.get("properties") if isinstance(page, Mapping) else None
    props = props if isinstance(props, Mapping) else {}

    def selected(name: str) -> bool:
        prop = props.get(name)
        choice = prop.get("select") if isinstance(prop, Mapping) else None
        return isinstance(choice, Mapping) and type(choice.get("name")) is str and bool(choice["name"].strip())

    surface = props.get("Surface Before Work?")
    link = props.get("Source Link")
    present = {
        "Area": selected("Area"), "Learning Type": selected("Learning Type"), "Status": selected("Status"),
        "Source Link": isinstance(link, Mapping) and type(link.get("url")) is str and bool(link["url"].strip()),
        "Surface Before Work?": isinstance(surface, Mapping) and surface.get("checkbox") is True,
    }
    missing = [name for name, ok in present.items() if not ok]
    return {
        "required_fields_present": not missing,
        "missing_owner_activation": [name for name in missing if name in PROTECTED_FIELDS],
        "missing_reviewed_metadata": [name for name in missing if name not in PROTECTED_FIELDS],
    }


def _create_protected_fields_safe(page: Mapping) -> bool:
    """A newly created lesson cannot acquire owner-only activation by accident.

    The live database may default Status to New; Surface remains false. An
    unexpected activated or malformed state cannot certify a routine write.
    This is NOT proof the page was created by this request.
    """
    props = page.get("properties")
    if not isinstance(props, Mapping):
        return False
    status = props.get("Status")
    surface = props.get("Surface Before Work?")
    if (not isinstance(status, Mapping) or status.get("type") != "select"
            or not isinstance(surface, Mapping) or surface.get("type") != "checkbox"
            or surface.get("checkbox") is not False):
        return False
    selection = status.get("select")
    return selection is None or (
        isinstance(selection, Mapping) and selection.get("name") == "New"
    )


def _page_state(page: Mapping) -> tuple:
    """Compare write-relevant state, not volatile read-adapter request IDs."""
    return tuple(page.get(key) for key in (
        "id", "parent", "properties", "last_edited_time",
        "archived", "is_archived", "in_trash",
    ))


def execute(request: AdmittedRequest, client) -> dict:
    """Consume owner admission under the existing policy, never infer authority."""
    result = {
        "request_id": request.request_id, "comment_id": request.comment_id,
        "status": "blocked", "reason_code": "precheck-incomplete",
        "write_attempts": 0, "readback_verified": False,
        "page_id": None, "lesson_id": None, "revision": None,
        "activation_prerequisites": None,
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
            if existing is None:
                possible, reviews = _find_semantic_duplicates(client, source_id, lesson)
                if possible:
                    result.update(status="blocked", reason_code="possible-semantic-duplicate",
                                  duplicate_lesson_ids=list(possible), duplicate_evidence_reviews=reviews)
                    return result
        page_id = None
        if existing is not None:
            page_id = _page(existing, source_id)
            existing = client.get_page(page_id)
            _page(existing, source_id, page_id)
            if target is not None and _lesson_id(existing) != target:
                raise WriteBlocked("lesson-identity-changed")
            result.update(page_id=page_id, lesson_id=_lesson_id(existing),
                          revision=existing["last_edited_time"])
            added_supporting_refs = _check_evidence_append(existing, lesson) if target is not None else None
            if _values(existing, lesson) == lesson:
                result.update(status="unchanged", reason_code="identical-canonical-content", readback_verified=True,
                              activation_prerequisites=activation_prerequisites(existing))
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
            if _page_state(current) != _page_state(existing):
                result.update(status="conflict", reason_code="page-changed-before-write")
                return result
        elif _find_title(client, source_id, lesson) is not None:
            result.update(status="conflict", reason_code="lesson-appeared-before-create")
            return result
        elif target is None:
            # Close the read-only pre-reservation window; an ambiguous page
            # must never be resolved by POST or a force-rearmed tag.
            possible, reviews = _find_semantic_duplicates(client, source_id, lesson)
            if possible:
                result.update(status="blocked", reason_code="possible-semantic-duplicate",
                              duplicate_lesson_ids=list(possible), duplicate_evidence_reviews=reviews)
                return result
        intended = properties(request.request_id)
        if page_id is None:
            # Durable, atomic create-once reservation BEFORE any Notion POST.
            # GitHub's fixed ref namespace is keyed by normalized reviewed
            # title, so another authorized request cannot race a lagging
            # Notion title index. A failed/previously held reservation refuses
            # with ZERO Notion attempts; never reuse or automatically release.
            client.reserve_create(request.request_id)
            result["create_reservation_acquired"] = True
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
            if page_id is None:
                # The POST may have committed. Do not retry it. A bounded,
                # single title lookup may recover a candidate page identity.
                try:
                    recovered = _find_title(client, source_id, lesson)
                    if recovered is None:
                        result["recovery_reason"] = "recovery-not-visible"
                        return result
                    page_id = _page(recovered, source_id)
                except WriteBlocked as exc:
                    result["recovery_reason"] = {
                        "ambiguous-lesson": "recovery-ambiguous",
                        "incomplete-reconciliation": "recovery-incomplete",
                        "page-destination-mismatch": "recovery-identity-invalid",
                        "query-identity-mismatch": "recovery-identity-invalid",
                        "inactive-page": "recovery-identity-invalid",
                    }.get(str(exc), "recovery-unavailable")
                    return result
                except Exception:
                    result["recovery_reason"] = "recovery-unavailable"
                    return result
                # Recovered identity proves current state only, NOT causality.
                result["create_receipt_recovered"] = True
            else:
                # PATCH may have succeeded despite its missing response. The
                # original stable page identity permits a direct GET.
                result["update_receipt_recovered"] = True
        result["page_id"] = page_id
        readback = client.get_page(page_id)
        _page(readback, source_id, page_id)
        if existing is None and not _create_protected_fields_safe(readback):
            result.update(reason_code="protected-field-present-after-create")
            return result
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
                      revision=readback["last_edited_time"],
                      activation_prerequisites=activation_prerequisites(readback))
        if target is not None and added_supporting_refs is not None:
            # This is a writer readback receipt, not proof of independent
            # verification or of the credibility of the new evidence.
            result["evidence_update"] = {
                "target_lesson_id": target,
                "added_supporting_source_links": list(added_supporting_refs),
                "primary_source_preserved": True,
                "independent_verification_required": True,
            }
    except WriteBlocked as exc:
        result["reason_code"] = str(exc)
    except Exception:
        result["reason_code"] = "provider-capability-or-read-unavailable"
    return result
