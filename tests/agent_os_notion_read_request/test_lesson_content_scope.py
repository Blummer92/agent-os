"""#3581 repair: unit scoping, record identity and completeness for lesson reads.

Regression tests for two confirmed defects in the #3580 lesson-content path:

A. Cross-unit contamination: the lesson query was unfiltered and returned
   records were published without checking their ``Canonical Unit`` relation.
B. Incomplete retrieval: one page was read and ``has_more`` was ignored, so a
   truncated read could be published as complete.

Pagination and filtering are exercised through the real #936
``NotionReadOnlyAdapter``; only its HTTP transport is faked, so the tests prove
the adapter's own bounded pagination is what the lesson path consumes.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from unittest.mock import patch

import pytest

from navigation_registry.connectors.curriculum_execution_surface_router import (
    _relation_filter,
    _scheduler_task_payload,
)
from scripts.agent_os_notion_read_request import (
    NotionReadRequestError,
    admit_notion_read_request,
    build_live_notion_executor_factory,
    parse_catalog,
)
from scripts.agent_os_notion_read_request.execution import (
    execute_lesson_content,
    resolve_lesson_unit_page_id,
)
from scripts.agent_os_notion_read_request.projection import (
    project_lesson_content_result,
    validate_lesson_unit_identity,
)
from scripts.agent_os_notion_read_request.runner import main, run_notion_read_request
from workflow_scheduler.adapters.notion_readonly_adapter import (
    NotionReadOnlyAdapter,
    NotionReadOnlyAdapterError,
)

from .notion_read_support import ACTOR, GENERATED_AT, REPOSITORY, transport

ISSUE = 3580
LESSON_REQUEST = "candy-branding-lesson-content"
DATA_SOURCE_ID = "64ec8493-ece7-41d4-b130-c48cc01742c0"
CANDY_UNIT = "3907ac78-3131-8132-8f84-f9fd633acba5"
PHOTO_UNIT = "2a07ac78-3131-8132-8f84-f9fd633acba5"
EXPECTED_FILTER = {"property": "Canonical Unit", "relation": {"contains": CANDY_UNIT}}
PUBLISH_CAPACITY = 24  # orchestrator MAX_RESULTS: the most lessons ever published


def _page_id(n: int) -> str:
    return f"3717ac78-3131-8135-ae7c-{n:012x}"


def _relation(*unit_ids):
    return {"type": "relation", "relation": [{"id": unit_id} for unit_id in unit_ids]}


def _lesson(n: int, unit=_relation(CANDY_UNIT)):
    properties = {
        "Daily Learning Target": {"type": "rich_text", "rich_text": [{"plain_text": f"target {n}"}]},
        "Daily Focus": {"type": "rich_text", "rich_text": [{"plain_text": f"focus {n}"}]},
        "Source Evidence": {"type": "rich_text", "rich_text": [{"plain_text": f"evidence {n}"}]},
        "Day / Lesson Number": {"type": "rich_text", "rich_text": [{"plain_text": f"Day {n}"}]},
    }
    if unit is not None:
        properties["Canonical Unit"] = unit
    return {
        "id": _page_id(n),
        "url": f"https://app.notion.com/p/{_page_id(n).replace('-', '')}",
        "properties": properties,
    }


def _page(records, *, has_more=False, next_cursor=None):
    return {"object": "list", "results": records, "has_more": has_more, "next_cursor": next_cursor}


class FakeNotionHttp:
    """Fake HTTP behind the real adapter: serves pages, records every request."""

    def __init__(self, pages):
        self._pages = list(pages)
        self.requests = []

    def post(self, url, headers, body, timeout):
        self.requests.append({"url": url, "body": copy.deepcopy(body)})
        page = self._pages[len(self.requests) - 1]
        if isinstance(page, BaseException):
            raise page
        return copy.deepcopy(page)

    def factory(self):
        return build_live_notion_executor_factory(
            adapter_factory=lambda: NotionReadOnlyAdapter(
                token="test-token", http_post_query_data_source=self.post
            )
        )


class CountingFactory:
    """Executor factory that records whether any Notion task was ever built."""

    def __init__(self):
        self.invocations = 0

    def __call__(self):
        self.invocations += 1
        raise AssertionError("no lesson query may be built after failed resolution")


def _admit(catalog):
    return admit_notion_read_request(
        transport(request_id=LESSON_REQUEST, issue_number=ISSUE),
        catalog=catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )


def _execute(catalog, http):
    decision = _admit(catalog)
    assert decision.status == "admitted"
    return execute_lesson_content(
        decision, catalog=catalog, scheduler_task_executor_factory=http.factory()
    )


def _run(catalog, http):
    return run_notion_read_request(
        transport(request_id=LESSON_REQUEST, issue_number=ISSUE),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
        generated_at=GENERATED_AT,
        catalog=catalog,
        scheduler_task_executor_factory=http.factory(),
    )


def _with_candy_unit(catalog_payload, **changes):
    payload = copy.deepcopy(catalog_payload)
    for unit in payload["canonical_units"]:
        if unit["canonical_unit_key"] == "candy-branding":
            unit.update(changes)
    return payload


# --------------------------------------------------------------------------
# Unit identity resolution happens before any lesson query
# --------------------------------------------------------------------------


def test_verified_candy_branding_unit_resolves(shipped_catalog) -> None:
    assert resolve_lesson_unit_page_id(shipped_catalog, "candy-branding") == CANDY_UNIT


def test_compact_uppercase_catalog_page_id_normalizes(catalog_payload) -> None:
    catalog = parse_catalog(
        _with_candy_unit(catalog_payload, provider_page_id=CANDY_UNIT.replace("-", "").upper())
    )
    assert resolve_lesson_unit_page_id(catalog, "candy-branding") == CANDY_UNIT


def test_missing_unit_fails_closed_without_query(shipped_catalog) -> None:
    catalog = dataclasses.replace(
        shipped_catalog,
        canonical_units=tuple(
            unit for unit in shipped_catalog.canonical_units
            if unit.canonical_unit_key != "candy-branding"
        ),
    )
    decision = _admit(catalog)
    assert decision.status == "rejected"
    assert decision.reason_codes == ("canonical-unit-unknown",)
    with pytest.raises(NotionReadRequestError, match="missing or ambiguous"):
        resolve_lesson_unit_page_id(catalog, "candy-branding")
    forged = dataclasses.replace(_admit(shipped_catalog))
    factory = CountingFactory()
    with pytest.raises(NotionReadRequestError, match="missing or ambiguous"):
        execute_lesson_content(forged, catalog=catalog, scheduler_task_executor_factory=factory)
    assert factory.invocations == 0


def test_duplicate_unit_key_rejected_by_existing_catalog_validation(catalog_payload) -> None:
    payload = copy.deepcopy(catalog_payload)
    candy = next(u for u in payload["canonical_units"] if u["canonical_unit_key"] == "candy-branding")
    duplicate = dict(candy, verification_title="Another title")
    payload["canonical_units"].append(duplicate)
    with pytest.raises(NotionReadRequestError, match="duplicate canonical unit key"):
        parse_catalog(payload)


def test_ambiguous_unit_identity_fails_closed_without_query(shipped_catalog) -> None:
    candy = shipped_catalog.canonical_unit("candy-branding")
    doubled = dataclasses.replace(
        shipped_catalog, canonical_units=shipped_catalog.canonical_units + (candy,)
    )
    factory = CountingFactory()
    with pytest.raises(NotionReadRequestError, match="missing or ambiguous"):
        execute_lesson_content(
            _admit(shipped_catalog), catalog=doubled, scheduler_task_executor_factory=factory
        )
    assert factory.invocations == 0


def test_page_id_bound_to_two_units_fails_closed_without_query(catalog_payload) -> None:
    payload = copy.deepcopy(catalog_payload)
    for unit in payload["canonical_units"]:
        if unit["canonical_unit_key"] == "motion-typography":
            unit["provider_page_id"] = CANDY_UNIT.replace("-", "")
            unit["verification_state"] = "verified-current"
    catalog = parse_catalog(payload)
    factory = CountingFactory()
    with pytest.raises(NotionReadRequestError, match="bound more than once"):
        execute_lesson_content(_admit(catalog), catalog=catalog, scheduler_task_executor_factory=factory)
    assert factory.invocations == 0


def test_unverified_unit_fails_closed_at_admission(catalog_payload) -> None:
    catalog = parse_catalog(
        _with_candy_unit(catalog_payload, provider_page_id=None, verification_state="unverified")
    )
    decision = _admit(catalog)
    assert decision.status == "rejected"
    assert decision.reason_codes == ("canonical-unit-unverified",)
    assert decision.secret_dispatch_authorized is False


def test_invalid_unit_page_id_fails_closed_without_query(catalog_payload) -> None:
    catalog = parse_catalog(_with_candy_unit(catalog_payload, provider_page_id="not-a-notion-id"))
    factory = CountingFactory()
    with pytest.raises(NotionReadRequestError, match="not a Notion id"):
        execute_lesson_content(_admit(catalog), catalog=catalog, scheduler_task_executor_factory=factory)
    assert factory.invocations == 0


# --------------------------------------------------------------------------
# Governed relation filter reaches the real #936 adapter on every request
# --------------------------------------------------------------------------


def test_filter_is_the_existing_relation_shape_with_verified_page_id(shipped_catalog) -> None:
    http = FakeNotionHttp([_page([_lesson(1)])])
    _execute(shipped_catalog, http)
    (request,) = http.requests
    assert request["url"].endswith(f"/data_sources/{DATA_SOURCE_ID}/query")
    assert request["body"]["filter"] == EXPECTED_FILTER
    assert request["body"]["filter"]["property"] == "Canonical Unit"
    assert list(request["body"]["filter"]["relation"]) == ["contains"]
    # Same shape the curriculum router builds: no second filter vocabulary.
    assert request["body"]["filter"] == _relation_filter(
        {"property": "Canonical Unit", "contains_page_id": CANDY_UNIT}
    )


def test_filter_present_on_every_paginated_request(shipped_catalog) -> None:
    http = FakeNotionHttp(
        [
            _page([_lesson(1)], has_more=True, next_cursor="cursor-a"),
            _page([_lesson(2)], has_more=True, next_cursor="cursor-b"),
            _page([_lesson(3)]),
        ]
    )
    execution = _execute(shipped_catalog, http)
    assert len(http.requests) == 3
    assert all(r["body"]["filter"] == EXPECTED_FILTER for r in http.requests)
    assert len(execution["records"]) == 3


def test_provider_rejected_filter_fails_closed_without_fallback(shipped_catalog) -> None:
    http = FakeNotionHttp([NotionReadOnlyAdapterError("Notion API error: invalid filter")])
    with pytest.raises(NotionReadRequestError, match="not successful"):
        _execute(shipped_catalog, http)
    # Exactly one request, and it was filtered: no unfiltered retry exists.
    assert len(http.requests) == 1
    assert http.requests[0]["body"]["filter"] == EXPECTED_FILTER


def test_unsupported_filter_shape_fails_closed_before_query(shipped_catalog) -> None:
    from navigation_registry.connectors.curriculum_execution_surface_router import (
        CurriculumSurfaceError,
    )

    factory = CountingFactory()
    with patch(
        "scripts.agent_os_notion_read_request.execution._relation_filter",
        side_effect=CurriculumSurfaceError("unsupported"),
    ):
        with pytest.raises(NotionReadRequestError, match="filter is unsupported"):
            execute_lesson_content(
                _admit(shipped_catalog),
                catalog=shipped_catalog,
                scheduler_task_executor_factory=factory,
            )
    assert factory.invocations == 0


def test_coursewide_checkbox_filtering_is_unchanged() -> None:
    # #3476/#3253: the curriculum router's checkbox shape and single-page bound
    # are untouched by the lesson repair.
    task = _scheduler_task_payload(
        "query_data_source",
        {
            "identity": {"data_source_id": "ds-visual"},
            "max_results": 5,
            "property_filter": {"property": "Coursewide", "checkbox": {"equals": True}},
        },
    )
    assert task == {
        "action": "query_data_source",
        "data_source_id": "ds-visual",
        "page_size": 5,
        "max_pages": 1,
        "max_results": 5,
        "filter": {"property": "Coursewide", "checkbox": {"equals": True}},
    }


# --------------------------------------------------------------------------
# Independent record identity validation before public projection
# --------------------------------------------------------------------------


def test_matching_candy_branding_lesson_published(shipped_catalog) -> None:
    evidence = _run(shipped_catalog, FakeNotionHttp([_page([_lesson(1)])]))
    assert evidence["dispatch_status"] == "completed"
    (lesson,) = evidence["result"]["lessons"]
    assert lesson["canonical_unit"] == {"page_id": CANDY_UNIT}
    assert lesson["daily_learning_target"] == "target 1"


def test_photography_lesson_under_candy_request_rejects_read(shipped_catalog) -> None:
    # The filter was sent, yet the provider returned a foreign record.
    http = FakeNotionHttp([_page([_lesson(1, unit=_relation(PHOTO_UNIT))])])
    with pytest.raises(NotionReadRequestError, match="different canonical unit"):
        _run(shipped_catalog, http)
    assert http.requests[0]["body"]["filter"] == EXPECTED_FILTER


@pytest.mark.parametrize(
    "unit",
    [
        None,  # property absent
        {"type": "relation", "relation": []},  # present, empty
    ],
    ids=["property-absent", "relation-empty"],
)
def test_unit_less_lesson_rejects_read(shipped_catalog, unit) -> None:
    http = FakeNotionHttp([_page([_lesson(1, unit=unit)])])
    with pytest.raises(NotionReadRequestError, match="no canonical unit relation"):
        _run(shipped_catalog, http)


def test_multiple_unit_relations_reject_read(shipped_catalog) -> None:
    http = FakeNotionHttp([_page([_lesson(1, unit=_relation(CANDY_UNIT, PHOTO_UNIT))])])
    with pytest.raises(NotionReadRequestError, match="ambiguous relations"):
        _run(shipped_catalog, http)


@pytest.mark.parametrize(
    ("unit", "message"),
    [
        ({"type": "relation", "relation": ["not-a-mapping"]}, "malformed relation"),
        ({"type": "relation", "relation": [{"id": ""}]}, "malformed relation"),
        ({"type": "relation", "relation": [{}]}, "malformed relation"),
        ({"type": "relation", "relation": [{"id": "candy-branding"}]}, "not a Notion id"),
        ({"type": "relation", "relation": "x"}, "malformed relations"),
        ({"type": "rich_text", "rich_text": []}, "not a relation"),
        (
            {"type": "relation", "relation": ["junk", {"id": CANDY_UNIT}]},
            "malformed relation",
        ),
    ],
    ids=["non-mapping", "empty-id", "missing-id", "non-uuid", "non-list", "wrong-type", "junk-plus-valid"],
)
def test_malformed_relation_rejects_read(shipped_catalog, unit, message) -> None:
    http = FakeNotionHttp([_page([_lesson(1, unit=unit)])])
    with pytest.raises(NotionReadRequestError, match=message):
        _run(shipped_catalog, http)


def test_compact_and_dashed_unit_ids_are_the_same_identity(shipped_catalog) -> None:
    compact = CANDY_UNIT.replace("-", "").upper()
    http = FakeNotionHttp([_page([_lesson(1, unit=_relation(compact)), _lesson(2)])])
    evidence = _run(shipped_catalog, http)
    assert [l["canonical_unit"] for l in evidence["result"]["lessons"]] == [
        {"page_id": CANDY_UNIT},
        {"page_id": CANDY_UNIT},
    ]


def test_mixed_valid_and_invalid_records_reject_whole_read(shipped_catalog) -> None:
    http = FakeNotionHttp(
        [_page([_lesson(1), _lesson(2, unit=_relation(PHOTO_UNIT)), _lesson(3)])]
    )
    with pytest.raises(NotionReadRequestError, match="different canonical unit"):
        _run(shipped_catalog, http)


def test_projection_independently_rejects_forged_execution_evidence(shipped_catalog) -> None:
    decision = _admit(shipped_catalog)
    foreign = _lesson(1, unit=_relation(PHOTO_UNIT))
    with pytest.raises(NotionReadRequestError, match="different canonical unit"):
        project_lesson_content_result(
            decision,
            {"canonical_unit_page_id": CANDY_UNIT, "records": [foreign]},
            catalog=shipped_catalog,
            generated_at=GENERATED_AT,
        )
    with pytest.raises(NotionReadRequestError, match="not scoped to the admitted unit"):
        project_lesson_content_result(
            decision,
            {"canonical_unit_page_id": PHOTO_UNIT, "records": [_lesson(1)]},
            catalog=shipped_catalog,
            generated_at=GENERATED_AT,
        )
    with pytest.raises(NotionReadRequestError, match="not scoped to the admitted unit"):
        project_lesson_content_result(
            decision, {"records": [_lesson(1)]}, catalog=shipped_catalog, generated_at=GENERATED_AT
        )


def test_validator_returns_normalized_identity() -> None:
    record = _lesson(1, unit=_relation(CANDY_UNIT.replace("-", "")))
    assert validate_lesson_unit_identity(record, CANDY_UNIT) == CANDY_UNIT


# --------------------------------------------------------------------------
# Bounded pagination and completeness through the existing adapter
# --------------------------------------------------------------------------


def test_single_complete_page(shipped_catalog) -> None:
    http = FakeNotionHttp([_page([_lesson(1), _lesson(2)])])
    execution = _execute(shipped_catalog, http)
    assert [r["id"] for r in execution["records"]] == [_page_id(1), _page_id(2)]
    assert execution["canonical_unit_page_id"] == CANDY_UNIT


def test_multiple_complete_pages_follow_opaque_cursors(shipped_catalog) -> None:
    http = FakeNotionHttp(
        [
            _page([_lesson(1)], has_more=True, next_cursor="opaque/Z"),
            _page([_lesson(2)], has_more=True, next_cursor="opaque/A"),
            _page([_lesson(3)]),
        ]
    )
    execution = _execute(shipped_catalog, http)
    assert len(execution["records"]) == 3
    # The lesson path always starts at the beginning of the query; cursors are
    # passed back verbatim, never ordered or synthesized.
    assert "start_cursor" not in http.requests[0]["body"]
    assert http.requests[1]["body"]["start_cursor"] == "opaque/Z"
    assert http.requests[2]["body"]["start_cursor"] == "opaque/A"


def test_bounds_sent_to_adapter(shipped_catalog) -> None:
    http = FakeNotionHttp([_page([_lesson(1)])])
    _execute(shipped_catalog, http)
    assert http.requests[0]["body"]["page_size"] == PUBLISH_CAPACITY


def test_exactly_capacity_lessons_complete(shipped_catalog) -> None:
    records = [_lesson(n) for n in range(1, PUBLISH_CAPACITY + 1)]
    evidence = _run(shipped_catalog, FakeNotionHttp([_page(records)]))
    assert len(evidence["result"]["lessons"]) == PUBLISH_CAPACITY


def test_missing_next_cursor_rejects_read(shipped_catalog) -> None:
    http = FakeNotionHttp([_page([_lesson(1)], has_more=True, next_cursor=None)])
    with pytest.raises(NotionReadRequestError, match="not successful"):
        _execute(shipped_catalog, http)


@pytest.mark.parametrize("cursor", ["", 7, {"c": 1}], ids=["empty", "number", "object"])
def test_malformed_cursor_rejects_read(shipped_catalog, cursor) -> None:
    http = FakeNotionHttp([_page([_lesson(1)], has_more=True, next_cursor=cursor)])
    with pytest.raises(NotionReadRequestError, match="not successful"):
        _execute(shipped_catalog, http)


def test_repeated_cursor_replaying_records_rejects_read(shipped_catalog) -> None:
    replay = _page([_lesson(1)], has_more=True, next_cursor="same")
    http = FakeNotionHttp([replay, replay, _page([_lesson(1)])])
    with pytest.raises(NotionReadRequestError, match="duplicate record"):
        _execute(shipped_catalog, http)


def test_repeated_cursor_never_terminating_rejects_read(shipped_catalog) -> None:
    pages = [
        _page([_lesson(n)], has_more=True, next_cursor="same") for n in range(1, 6)
    ]
    http = FakeNotionHttp(pages)
    with pytest.raises(NotionReadRequestError, match="incomplete"):
        _execute(shipped_catalog, http)
    assert len(http.requests) == 5


def test_has_more_at_max_pages_rejects_read(shipped_catalog) -> None:
    pages = [
        _page([_lesson(n)], has_more=True, next_cursor=f"c{n}") for n in range(1, 6)
    ] + [_page([_lesson(6)])]
    http = FakeNotionHttp(pages)
    with pytest.raises(NotionReadRequestError, match="incomplete"):
        _execute(shipped_catalog, http)
    # The adapter's max_pages bound stopped it; the sixth page was never read.
    assert len(http.requests) == 5


def test_has_more_at_max_results_rejects_read(shipped_catalog) -> None:
    first = [_lesson(n) for n in range(1, PUBLISH_CAPACITY + 1)]
    http = FakeNotionHttp(
        [
            _page(first, has_more=True, next_cursor="c1"),
            _page([_lesson(100), _lesson(101)], has_more=True, next_cursor="c2"),
        ]
    )
    with pytest.raises(NotionReadRequestError, match="incomplete|read bound"):
        _execute(shipped_catalog, http)


def test_page_larger_than_remaining_capacity_rejects_read(shipped_catalog) -> None:
    # The provider over-delivers on a terminal page; the adapter slices it at
    # its bound and reports has_more false. Completeness is still unproven.
    oversized = [_lesson(n) for n in range(1, PUBLISH_CAPACITY + 6)]
    http = FakeNotionHttp([_page(oversized, has_more=False)])
    with pytest.raises(NotionReadRequestError, match="read bound"):
        _execute(shipped_catalog, http)


def test_terminal_page_with_continuation_cursor_rejects_read(shipped_catalog) -> None:
    http = FakeNotionHttp([_page([_lesson(1)], has_more=False, next_cursor="dangling")])
    with pytest.raises(NotionReadRequestError, match="inconsistent"):
        _execute(shipped_catalog, http)


@pytest.mark.parametrize("has_more", [None, "false", 0], ids=["missing", "string", "int"])
def test_malformed_termination_metadata_rejects_read(shipped_catalog, has_more) -> None:
    class Executor:
        def __call__(self):
            return lambda payload: {
                "status": "success",
                "output": {"results": [_lesson(1)], "has_more": has_more, "next_cursor": None},
            }

    with pytest.raises(NotionReadRequestError, match="termination metadata is malformed"):
        execute_lesson_content(
            _admit(shipped_catalog), catalog=shipped_catalog, scheduler_task_executor_factory=Executor()
        )


@pytest.mark.parametrize("transient", [True, False], ids=["retryable", "failure"])
def test_adapter_failure_during_continuation_rejects_read(shipped_catalog, transient) -> None:
    http = FakeNotionHttp(
        [
            _page([_lesson(1)], has_more=True, next_cursor="c1"),
            NotionReadOnlyAdapterError("Notion API error", is_transient=transient),
        ]
    )
    with pytest.raises(NotionReadRequestError, match="not successful"):
        _execute(shipped_catalog, http)
    assert len(http.requests) == 2


def test_record_without_notion_id_rejects_read(shipped_catalog) -> None:
    record = _lesson(1)
    record["id"] = "lesson-1"
    with pytest.raises(NotionReadRequestError, match="no valid Notion id"):
        _execute(shipped_catalog, FakeNotionHttp([_page([record])]))


def test_incomplete_read_publishes_no_lessons_in_receipt(tmp_path, shipped_catalog) -> None:
    transport_path = tmp_path / "transport.json"
    transport_path.write_text(
        json.dumps(transport(request_id=LESSON_REQUEST, issue_number=ISSUE)), encoding="utf-8"
    )
    output = tmp_path / "result.json"
    http = FakeNotionHttp(
        [
            _page([_lesson(1)], has_more=True, next_cursor="c1"),
            _page([_lesson(2)], has_more=True, next_cursor="c2"),
            _page([_lesson(3)], has_more=True, next_cursor="c3"),
            _page([_lesson(4)], has_more=True, next_cursor="c4"),
            _page([_lesson(5)], has_more=True, next_cursor="c5"),
        ]
    )
    with patch(
        "scripts.agent_os_notion_read_request.runner.build_live_notion_executor_factory",
        return_value=http.factory(),
    ):
        code = main(
            [
                "--transport", str(transport_path),
                "--repository", REPOSITORY,
                "--allowed-actor", ACTOR,
                "--generated-at", GENERATED_AT,
                "--output", str(output),
                "--live-notion",
            ]
        )
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert code == 1
    assert receipt["dispatch_status"] == "failed"
    assert receipt["result"] is None
    assert "incomplete" in receipt["failure"]["detail"]
    for marker in ("target 1", "focus 1", "evidence 1", _page_id(1)):
        assert marker not in json.dumps(receipt)
