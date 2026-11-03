"""Teacher OS read seam (#2801/#3580): discovery, membership proof and fail-closed controls.

The executor below is a deterministic stub of the #936 adapter output shape. It
is test-only and is NOT live Notion evidence.
"""

from __future__ import annotations

import copy
import json

import pytest

from scripts.agent_os_notion_read_request import parse_catalog
from scripts.agent_os_notion_read_request.teacher_os import (
    TeacherOsReadError,
    read_unit_lessons,
    read_units,
    run,
)

from .test_lesson_content import DATA_SOURCE_ID as LESSON_DS, _day1_record

UNIT_DS = "c5b202aa-83d1-4cc4-9992-f98af648e461"
UNIT_A = "3907ac78-3131-8132-8f84-f9fd633acba5"
UNIT_B = "aaaaaaaa-0000-4000-8000-000000000001"  # not in any catalog entry
GEN = "2026-11-03T12:00:00Z"


def _unit(page_id, title, status="Active", review=False, **extra):
    properties = {"Canonical Unit Name": {"type": "title", "title": [{"plain_text": title}]},
                  "Human Review Required": {"type": "checkbox", "checkbox": review}}
    if status is not None:
        properties["Canonical Status"] = {"type": "select", "select": {"name": status}}
    return {"id": page_id, "properties": properties, **extra}


def _output(records):
    return {"status": "success", "output": {"results": records, "has_more": False, "next_cursor": None}}


class Stub:
    def __init__(self, units, lessons_by_unit=None):
        self.units, self.lessons, self.calls = units, lessons_by_unit or {}, []

    def factory(self):
        return self.execute

    def execute(self, payload):
        self.calls.append(copy.deepcopy(dict(payload)))
        if payload["data_source_id"] == UNIT_DS:
            return _output(copy.deepcopy(self.units))
        assert payload["data_source_id"] == LESSON_DS
        unit = payload["filter"]["relation"]["contains"]
        return _output(copy.deepcopy(self.lessons.get(unit, [])))


def _lesson(unit_id, n):
    record = _day1_record()
    record["id"] = f"3717ac78-3131-8135-ae7c-f2ead0cf{n:04d}"
    record["properties"]["Canonical Unit"]["relation"] = [{"id": unit_id}]
    return record


def test_units_are_discovered_from_live_source_with_no_repository_unit_list(shipped_catalog) -> None:
    # UNIT_B is in no catalog or source file: it appears solely because the stub "Notion" lists it.
    stub = Stub([_unit(UNIT_B, "Zine Making"), _unit(UNIT_A, "Candy Branding"), _unit("bbbbbbbb-0000-4000-8000-000000000002", "Old", archived=True)])
    result = read_units(shipped_catalog, stub.factory, generated_at=GEN)
    assert result["status"] == "ok"
    assert [u["title"] for u in result["units"]] == ["Candy Branding", "Zine Making"]
    assert result["source"]["logical_source"] == "canonical-unit"
    assert [c["action"] for c in stub.calls] == ["query_data_source"]
    assert "filter" not in stub.calls[0]


@pytest.mark.parametrize("record", [
    _unit("cccccccc-0000-4000-8000-000000000003", "Draft", status="Draft"),
    _unit("cccccccc-0000-4000-8000-000000000004", "Planned", status="Planned"),
    _unit("cccccccc-0000-4000-8000-000000000005", "Archived", status="Archived"),
    _unit("cccccccc-0000-4000-8000-000000000006", "Needs review", review=True),
    _unit("cccccccc-0000-4000-8000-000000000007", "No status", status=None),
])
def test_only_active_unreviewed_units_are_approved(shipped_catalog, record) -> None:
    stub = Stub([_unit(UNIT_A, "Candy Branding"), record], {record["id"]: [_lesson(record["id"], 1)]})
    assert [u["title"] for u in read_units(shipped_catalog, stub.factory, generated_at=GEN)["units"]] == ["Candy Branding"]
    with pytest.raises(TeacherOsReadError) as exc:
        read_unit_lessons(shipped_catalog, stub.factory, record["id"], generated_at=GEN)
    assert exc.value.reason_code == "unit-not-approved"


def test_new_notion_unit_lessons_are_readable_without_any_per_unit_code(shipped_catalog) -> None:
    stub = Stub([_unit(UNIT_B, "Zine Making")], {UNIT_B: [_lesson(UNIT_B, 1), _lesson(UNIT_B, 2)]})
    result = read_unit_lessons(shipped_catalog, stub.factory, UNIT_B.upper(), generated_at=GEN)
    assert result["status"] == "ok"
    assert result["unit"] == {"unit_id": UNIT_B, "title": "Zine Making"}
    assert len(result["lessons"]) == 2
    assert all(l["canonical_unit"] == {"page_id": UNIT_B} for l in result["lessons"])
    assert "internal planning text" not in json.dumps(result)


def test_unit_not_listed_by_verified_source_is_rejected_before_any_lesson_query(shipped_catalog) -> None:
    stub = Stub([_unit(UNIT_A, "Candy Branding")], {UNIT_B: [_lesson(UNIT_B, 1)]})
    with pytest.raises(TeacherOsReadError) as exc:
        read_unit_lessons(shipped_catalog, stub.factory, UNIT_B, generated_at=GEN)
    assert exc.value.reason_code == "unit-not-approved"
    assert all(c["data_source_id"] == UNIT_DS for c in stub.calls)


@pytest.mark.parametrize("bad", ["", "not-a-uuid", "../../etc/passwd", UNIT_A + "0", "3907ac78313181328f84f9fd633acba5; rm -rf /"])
def test_malformed_unit_id_never_reaches_notion(shipped_catalog, bad) -> None:
    stub = Stub([_unit(UNIT_A, "Candy Branding")])
    with pytest.raises(TeacherOsReadError) as exc:
        read_unit_lessons(shipped_catalog, stub.factory, bad, generated_at=GEN)
    assert exc.value.reason_code == "invalid-request"
    assert stub.calls == []


def test_foreign_lesson_under_approved_unit_rejects_whole_read(shipped_catalog) -> None:
    stub = Stub([_unit(UNIT_A, "Candy Branding")], {UNIT_A: [_lesson(UNIT_A, 1), _lesson(UNIT_B, 2)]})
    code, payload = run(["--generated-at", GEN, "lessons", "--unit-id", UNIT_A], factory=stub.factory)
    assert (code, payload["status"], payload["reason_code"]) == (1, "error", "read-failed")
    assert "lessons" not in payload


def test_empty_unit_and_empty_source_are_reported_empty_not_filled(shipped_catalog) -> None:
    stub = Stub([_unit(UNIT_A, "Candy Branding")])
    assert read_unit_lessons(shipped_catalog, stub.factory, UNIT_A, generated_at=GEN)["status"] == "empty"
    assert read_units(shipped_catalog, Stub([]).factory, generated_at=GEN)["status"] == "empty"


def test_unbound_source_fails_closed_without_constructing_the_executor(catalog_payload) -> None:
    payload = copy.deepcopy(catalog_payload)
    for source in payload["sources"]:
        if source["logical_source"] == "canonical-unit":
            source["data_source_id"], source["verification_state"] = None, "unverified"
    def boom():  # pragma: no cover - must not run
        raise AssertionError("executor built for an unverified source")
    with pytest.raises(TeacherOsReadError) as exc:
        read_units(parse_catalog(payload), boom, generated_at=GEN)
    assert exc.value.reason_code == "source-unverified"


def test_missing_credential_is_unavailable_and_publishes_no_content(monkeypatch) -> None:
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    code, payload = run(["--generated-at", GEN, "units"])
    assert code == 1
    assert payload["status"] == "unavailable" and payload["reason_code"] == "not-configured"
    assert set(payload) == {"schema_version", "result_kind", "status", "reason_code"}


def test_provider_failure_and_incomplete_results_are_errors(shipped_catalog) -> None:
    class Failing(Stub):
        def execute(self, payload):
            return {"status": "failed", "output": {"message": "secret provider text"}}
    code, payload = run(["--generated-at", GEN, "units"], factory=Failing([]).factory)
    assert (code, payload["status"], payload["reason_code"]) == (1, "error", "read-failed")
    assert "secret" not in json.dumps(payload)

    class Truncated(Stub):
        def execute(self, payload):
            return {"status": "success", "output": {"results": [], "has_more": True, "next_cursor": "x"}}
    code, payload = run(["--generated-at", GEN, "units"], factory=Truncated([]).factory)
    assert code == 1 and payload["reason_code"] == "read-failed"
