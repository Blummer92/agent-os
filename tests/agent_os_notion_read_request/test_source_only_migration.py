"""Migration proof: Teacher OS does not require static per-unit registrations."""

from scripts.agent_os_notion_read_request.catalog import load_catalog
from scripts.agent_os_notion_read_request.teacher_os import (
    read_unit_lessons,
    read_units,
)

from .test_teacher_os import Stub, UNIT_B, GEN, _admitted, _unit, _lesson


def source_only_catalog():
    return load_catalog(sources_only=True)


def test_new_unit_discovery_without_static_unit_catalog():
    catalog = source_only_catalog()
    assert catalog.canonical_units == ()
    assert catalog.requests == ()

    stub = Stub([_unit(UNIT_B, "Live Notion Unit")])
    result = read_units(catalog, _admitted(), stub.factory, generated_at=GEN)

    assert result["status"] == "ok"
    assert result["units"] == [
        {"unit_id": UNIT_B, "title": "Live Notion Unit"}
    ]


def test_new_unit_lessons_without_static_unit_catalog():
    catalog = source_only_catalog()
    stub = Stub(
        [_unit(UNIT_B, "Live Notion Unit")],
        {UNIT_B: [_lesson(UNIT_B, 1)]},
    )

    result = read_unit_lessons(
        catalog, _admitted(), stub.factory, UNIT_B, generated_at=GEN
    )

    assert result["status"] == "ok"
    assert len(result["lessons"]) == 1
    assert result["lessons"][0]["canonical_unit"] == {
        "page_id": UNIT_B
    }


def test_unapproved_unit_stays_blocked_without_static_catalog():
    catalog = source_only_catalog()
    stub = Stub([_unit(UNIT_B, "Unapproved", status="Draft")])

    result = read_units(catalog, _admitted(), stub.factory, generated_at=GEN)
    assert result["status"] == "empty"
    assert result["units"] == []


def test_source_only_parser_does_not_require_unit_registrations():
    from scripts.agent_os_notion_read_request.catalog import CATALOG_PATH, parse_catalog
    import json
    import pytest
    from scripts.agent_os_notion_read_request.models import NotionReadRequestError

    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    payload["canonical_units"] = []
    payload["requests"] = []

    with pytest.raises(NotionReadRequestError):
        parse_catalog(payload)

    catalog = parse_catalog(payload, sources_only=True)
    assert catalog.canonical_units == ()
    assert catalog.requests == ()
    assert catalog.source("canonical-unit").dispatchable
    assert catalog.source("daily-generation-packet").dispatchable


def test_source_only_catalog_cannot_admit_legacy_request():
    from scripts.agent_os_notion_read_request.admission import admit_notion_read_request
    from scripts.agent_os_notion_read_request.catalog import load_catalog
    from .notion_read_support import ACTOR, transport

    catalog = load_catalog(sources_only=True)
    assert catalog.request("candy-branding-lesson-content") is None

    decision = admit_notion_read_request(
        transport(
            request_id="candy-branding-lesson-content",
            issue_number=3580,
        ),
        catalog=catalog,
        expected_repository=catalog.repository,
        expected_actor=ACTOR,
    )
    assert decision.status == "rejected"
    assert decision.reason_codes == ("request-id-unknown",)
    assert decision.secret_dispatch_authorized is False
