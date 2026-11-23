"""Teacher OS read seam (#2801/#3580): discovery, membership proof and fail-closed controls.

The executor below is a deterministic stub of the #936 adapter output shape. It
is test-only and is NOT live Notion evidence.
"""

from __future__ import annotations

import copy
import json

import pytest

from scripts.agent_os_notion_read_request import parse_catalog
from scripts.agent_os_notion_read_request.models import NotionReadAdmission
from scripts.agent_os_notion_read_request.teacher_os import (
    TeacherOsReadError,
    _approved,
    read_unit_lessons,
    read_units,
    run,
)

from .test_lesson_content import DATA_SOURCE_ID as LESSON_DS, _day1_record

UNIT_DS = "c5b202aa-83d1-4cc4-9992-f98af648e461"
UNIT_A = "3907ac78-3131-8132-8f84-f9fd633acba5"
UNIT_B = "aaaaaaaa-0000-4000-8000-000000000001"  # not in any catalog entry
GEN = "2026-11-03T12:00:00Z"


def _admitted():
    # The only admitted shape the scope-bound gate accepts: no single-unit
    # binding, required sources covering both the unit registry and lessons.
    return NotionReadAdmission(
        status="admitted",
        reason_codes=("admitted",),
        repository="Blummer92/agent-os",
        secret_dispatch_authorized=True,
        required_logical_sources=("canonical-unit", "daily-generation-packet"),
    )


def _admitted_wrong_scope(**overrides):
    kwargs = dict(
        status="admitted",
        reason_codes=("admitted",),
        repository="Blummer92/agent-os",
        secret_dispatch_authorized=True,
        required_logical_sources=("canonical-unit", "daily-generation-packet"),
    )
    kwargs.update(overrides)
    return NotionReadAdmission(**kwargs)


def _rejected():
    return NotionReadAdmission(
        status="rejected",
        reason_codes=("admission-rejected",),
        repository="Blummer92/agent-os",
        secret_dispatch_authorized=False,
    )


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
    result = read_units(shipped_catalog, _admitted(), stub.factory, generated_at=GEN)
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
    assert [u["title"] for u in read_units(shipped_catalog, _admitted(), stub.factory, generated_at=GEN)["units"]] == ["Candy Branding"]
    with pytest.raises(TeacherOsReadError) as exc:
        read_unit_lessons(shipped_catalog, _admitted(), stub.factory, record["id"], generated_at=GEN)
    assert exc.value.reason_code == "unit-not-approved"


def test_new_notion_unit_lessons_are_readable_without_any_per_unit_code(shipped_catalog) -> None:
    stub = Stub([_unit(UNIT_B, "Zine Making")], {UNIT_B: [_lesson(UNIT_B, 1), _lesson(UNIT_B, 2)]})
    result = read_unit_lessons(shipped_catalog, _admitted(), stub.factory, UNIT_B.upper(), generated_at=GEN)
    assert result["status"] == "ok"
    assert result["unit"] == {"unit_id": UNIT_B, "title": "Zine Making"}
    assert len(result["lessons"]) == 2
    assert all(l["canonical_unit"] == {"page_id": UNIT_B} for l in result["lessons"])
    assert "internal planning text" not in json.dumps(result)


def test_unit_not_listed_by_verified_source_is_rejected_before_any_lesson_query(shipped_catalog) -> None:
    stub = Stub([_unit(UNIT_A, "Candy Branding")], {UNIT_B: [_lesson(UNIT_B, 1)]})
    with pytest.raises(TeacherOsReadError) as exc:
        read_unit_lessons(shipped_catalog, _admitted(), stub.factory, UNIT_B, generated_at=GEN)
    assert exc.value.reason_code == "unit-not-approved"
    assert all(c["data_source_id"] == UNIT_DS for c in stub.calls)


@pytest.mark.parametrize("bad", ["", "not-a-uuid", "../../etc/passwd", UNIT_A + "0", "3907ac78313181328f84f9fd633acba5; rm -rf /"])
def test_malformed_unit_id_never_reaches_notion(shipped_catalog, bad) -> None:
    stub = Stub([_unit(UNIT_A, "Candy Branding")])
    with pytest.raises(TeacherOsReadError) as exc:
        read_unit_lessons(shipped_catalog, _admitted(), stub.factory, bad, generated_at=GEN)
    assert exc.value.reason_code == "invalid-request"
    assert stub.calls == []


def test_foreign_lesson_under_approved_unit_rejects_whole_read(shipped_catalog) -> None:
    stub = Stub([_unit(UNIT_A, "Candy Branding")], {UNIT_A: [_lesson(UNIT_A, 1), _lesson(UNIT_B, 2)]})
    code, payload = run(["--generated-at", GEN, "lessons", "--unit-id", UNIT_A], factory=stub.factory, admission=_admitted())
    assert (code, payload["status"], payload["reason_code"]) == (1, "error", "read-failed")
    assert "lessons" not in payload


def test_empty_unit_and_empty_source_are_reported_empty_not_filled(shipped_catalog) -> None:
    stub = Stub([_unit(UNIT_A, "Candy Branding")])
    assert read_unit_lessons(shipped_catalog, _admitted(), stub.factory, UNIT_A, generated_at=GEN)["status"] == "empty"
    assert read_units(shipped_catalog, _admitted(), Stub([]).factory, generated_at=GEN)["status"] == "empty"


def test_unbound_source_fails_closed_without_constructing_the_executor(catalog_payload) -> None:
    payload = copy.deepcopy(catalog_payload)
    for source in payload["sources"]:
        if source["logical_source"] == "canonical-unit":
            source["data_source_id"], source["verification_state"] = None, "unverified"
    def boom():  # pragma: no cover - must not run
        raise AssertionError("executor built for an unverified source")
    with pytest.raises(TeacherOsReadError) as exc:
        read_units(parse_catalog(payload), _admitted(), boom, generated_at=GEN)
    assert exc.value.reason_code == "source-unverified"


def test_missing_admission_never_dispatches_even_with_a_credential_present(monkeypatch) -> None:
    # The entry point cannot supply an admission, so it must fail closed even
    # when a token is present: no adapter is constructed and no content leaks.
    monkeypatch.setenv("NOTION_TOKEN", "test-token-that-must-never-be-used")
    code, payload = run(["--generated-at", GEN, "units"])
    assert code == 1
    assert payload["status"] == "error" and payload["reason_code"] == "admission-required"
    assert set(payload) == {"schema_version", "result_kind", "status", "reason_code"}


def test_admitted_caller_without_an_executor_is_not_configured(shipped_catalog) -> None:
    with pytest.raises(TeacherOsReadError) as exc:
        read_units(shipped_catalog, _admitted(), None, generated_at=GEN)
    assert exc.value.reason_code == "not-configured"
    code, payload = run(["--generated-at", GEN, "units"], admission=_admitted())
    assert (code, payload["status"], payload["reason_code"]) == (1, "unavailable", "not-configured")


def test_rejected_admission_never_constructs_the_executor(shipped_catalog) -> None:
    def boom():  # pragma: no cover - must not run
        raise AssertionError("executor built for a rejected admission")
    with pytest.raises(TeacherOsReadError) as exc:
        read_units(shipped_catalog, _rejected(), boom, generated_at=GEN)
    assert exc.value.reason_code == "admission-required"
    with pytest.raises(TeacherOsReadError) as exc:
        read_unit_lessons(shipped_catalog, None, boom, UNIT_A, generated_at=GEN)
    assert exc.value.reason_code == "admission-required"


@pytest.mark.parametrize("wrong_scope", [
    # Destination-verification shape: admitted, but no sources at all.
    _admitted_wrong_scope(required_logical_sources=()),
    # Single-unit lesson-content shape: admitted, but only the lesson source.
    _admitted_wrong_scope(required_logical_sources=("daily-generation-packet",)),
    # Unit-scoped curriculum shape: both sources, but bound to one unit.
    _admitted_wrong_scope(canonical_unit_key="candy-branding"),
])
def test_admission_for_another_purpose_never_authorizes_discovery(shipped_catalog, wrong_scope) -> None:
    def boom():  # pragma: no cover - must not run
        raise AssertionError("executor built for a wrong-scope admission")
    with pytest.raises(TeacherOsReadError) as exc:
        read_units(shipped_catalog, wrong_scope, boom, generated_at=GEN)
    assert exc.value.reason_code == "admission-required"


def _approval_unit(page_id, title, review_property):
    properties = {"Canonical Unit Name": {"type": "title", "title": [{"plain_text": title}]},
                  "Canonical Status": {"type": "select", "select": {"name": "Active"}}}
    if review_property is not None:
        properties["Human Review Required"] = review_property
    return {"id": page_id, "properties": properties}


@pytest.mark.parametrize("review_property,approved", [
    ({"type": "checkbox", "checkbox": False}, True),
    ({"type": "checkbox", "checkbox": True}, False),
    ({"type": "checkbox", "checkbox": "false"}, False),
    ({"type": "checkbox", "checkbox": None}, False),
    ({"type": "checkbox", "checkbox": 0}, False),
    ({"type": "checkbox"}, False),
    ({"type": "select", "select": {"name": "No"}}, False),
    (None, False),  # missing property entirely
])
def test_approval_requires_an_explicit_checkbox_false(shipped_catalog, review_property, approved) -> None:
    page_id = "dddddddd-0000-4000-8000-000000000009"
    stub = Stub([_approval_unit(page_id, "Candidate Unit", review_property)],
                {page_id: [_lesson(page_id, 1)]})
    titles = [u["title"] for u in read_units(shipped_catalog, _admitted(), stub.factory, generated_at=GEN)["units"]]
    assert ("Candidate Unit" in titles) is approved
    if approved:
        result = read_unit_lessons(shipped_catalog, _admitted(), stub.factory, page_id, generated_at=GEN)
        assert result["status"] == "ok"
    else:
        with pytest.raises(TeacherOsReadError) as exc:
            read_unit_lessons(shipped_catalog, _admitted(), stub.factory, page_id, generated_at=GEN)
        assert exc.value.reason_code == "unit-not-approved"


def test_provider_failure_and_incomplete_results_are_errors(shipped_catalog) -> None:
    class Failing(Stub):
        def execute(self, payload):
            return {"status": "failed", "output": {"message": "secret provider text"}}
    code, payload = run(["--generated-at", GEN, "units"], factory=Failing([]).factory, admission=_admitted())
    assert (code, payload["status"], payload["reason_code"]) == (1, "error", "read-failed")
    assert "secret" not in json.dumps(payload)

    class Truncated(Stub):
        def execute(self, payload):
            return {"status": "success", "output": {"results": [], "has_more": True, "next_cursor": "x"}}
    code, payload = run(["--generated-at", GEN, "units"], factory=Truncated([]).factory, admission=_admitted())
    assert code == 1 and payload["reason_code"] == "read-failed"


# --- Adapted from the eb3f95d9 head: review fail-closed and trashed-unit
# controls, updated for the admission gate (a scope-valid admission is
# required before any dispatch; the review/trash checks are unchanged). ---

@pytest.mark.parametrize("review", [
    None,
    {"type": "checkbox", "checkbox": "false"},
    {"type": "checkbox", "checkbox": True},
    {"type": "rich_text", "rich_text": []},
    {"checkbox": False},
])
def test_review_must_be_explicitly_unchecked(shipped_catalog, review):
    props = {
        "Canonical Status": {"type": "select", "select": {"name": "Active"}},
        "Canonical Unit Name": {
            "type": "title",
            "title": [{"plain_text": "Zine Making"}],
        },
    }
    if review is not None:
        props["Human Review Required"] = review

    assert _approved(props) is False
    stub = Stub([{"id": UNIT_B, "properties": props}])
    result = read_units(shipped_catalog, _admitted(), stub.factory, generated_at=GEN)
    assert result["status"] == "empty"
    assert result["units"] == []


def test_malformed_unit_properties_are_not_approved():
    assert _approved(None) is False
    assert _approved([]) is False


def test_trashed_unit_is_excluded_and_query_is_bounded(shipped_catalog):
    from navigation_registry.connectors.curriculum_execution_surface_router import MAX_RESULTS

    stub = Stub([_unit(UNIT_B, "Zine Making", in_trash=True)])
    result = read_units(shipped_catalog, _admitted(), stub.factory, generated_at=GEN)
    assert result["units"] == []
    assert stub.calls == [{
        "action": "query_data_source",
        "data_source_id": UNIT_DS,
        "page_size": MAX_RESULTS,
        "max_pages": 5,
        "max_results": MAX_RESULTS + 1,
    }]
