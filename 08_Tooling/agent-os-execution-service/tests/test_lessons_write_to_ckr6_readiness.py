"""Reviewed catalog -> governed Notion writer -> owner activation -> CKR6 retrieval.

Each stage was tested alone; nothing joined the writer's output to the reader's
eligibility rules, so the writer reported ``persisted`` for pages CKR6 would
silently skip. These offline tests drive the real catalog, the real writer and
the real CKR6 retrieval path against one stateful fake Notion that behaves like
the API (unset select -> null, unset checkbox -> false, plain_text populated).
The fake models the OWNER's separate Status/Surface edit; the writer never
sends those fields. No network, no credentials, no live Notion.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from agent_memory_context_manager.lesson_activation_bridge import (
    LessonActivationSkip,
    normalize_lesson_row,
)
from agent_os_execution_service.issue_start_lesson_preflight import activate_issue_start_lesson_preflight
from scripts.agent_os_notion_lessons_write import catalog
from scripts.agent_os_notion_lessons_write.admission import AdmittedRequest
from scripts.agent_os_notion_lessons_write.writer import activation_prerequisites, execute

SOURCE_ID = "00000000-0000-0000-0000-000000000001"
PAGE_ID = "00000000-0000-0000-0000-000000000002"
REVISION = "2026-10-06T20:00:00.000Z"
OPTIONS = {
    "Area": ["Governance", "Testing", "Curriculum", "Automation", "Dashboard", "Documentation"],
    "Learning Type": ["Mistake", "Testing lesson", "QA feedback"],
    "Applies To": ["Notion", "Drive"],
}
NARRATIVE = {
    "Lesson Learned": "Existing lesson title",
    "What Happened": "Existing context",
    "What To Do Next Time": "Existing next-time guidance",
    "Guardrail": "Existing guardrail",
}


def _item(text):
    return {"type": "text", "plain_text": text, "text": {"content": text}}


def _prop(kind, value):
    if kind in ("title", "rich_text"):
        return {"type": kind, kind: [_item(value)]}
    if kind == "select":
        return {"type": "select", "select": None if value is None else {"name": value}}
    if kind == "multi_select":
        return {"type": "multi_select", "multi_select": [{"name": item} for item in value]}
    return {"type": "url", "url": value}


def blank_page(number=93, narrative=None):
    """A page as Notion returns it: descriptive fields unset, owner fields unset."""
    values = {**(narrative or NARRATIVE), "Area": None, "Learning Type": None, "Applies To": (), "Source Link": None}
    props = {name: _prop(catalog.WRITABLE_TYPES[name], value) for name, value in values.items()}
    props["Status"] = {"type": "select", "select": None}
    props["Surface Before Work?"] = {"type": "checkbox", "checkbox": False}
    props["Lesson ID"] = {"type": "unique_id", "unique_id": {"prefix": "LL", "number": number}}
    return {
        "object": "page", "id": PAGE_ID, "url": f"https://www.notion.so/{PAGE_ID}",
        "parent": {"type": "data_source_id", "data_source_id": SOURCE_ID},
        "last_edited_time": REVISION, "properties": props, "archived": False, "in_trash": False,
    }


class FakeNotion:
    def __init__(self, existing=None, *, new_lesson_number=101):
        self.page = deepcopy(existing)
        self.number = new_lesson_number
        self.sent = []
        schema = {name: {"type": kind} for name, kind in
                  {**catalog.WRITABLE_TYPES, "Lesson ID": "unique_id", "Status": "select"}.items()}
        for name, options in OPTIONS.items():
            schema[name][catalog.WRITABLE_TYPES[name]] = {"options": [{"name": item} for item in options]}
        self._schema = {"id": SOURCE_ID, "properties": schema}

    def verify_binding(self):
        return SOURCE_ID

    def schema(self):
        return deepcopy(self._schema)

    def find_exact(self, title):
        return {"results": [deepcopy(self.page)] if self.page else [], "has_more": False}

    def find_lesson(self, number):
        return {"results": [deepcopy(self.page)] if self.page else [], "has_more": False}

    def get_page(self, page_id):
        return deepcopy(self.page)

    def _apply(self, intended):
        self.sent.append(deepcopy(intended))
        for name, value in intended.items():
            kind = catalog.WRITABLE_TYPES[name]
            if kind in ("title", "rich_text"):  # Notion fills plain_text on read
                value = {kind: [_item(part["text"]["content"]) for part in value[kind]]}
            self.page["properties"][name] = {"type": kind, **deepcopy(value)}

    def create(self, intended):
        self.page = blank_page(self.number, {name: "" for name in NARRATIVE})
        self._apply(intended)
        return {"id": PAGE_ID}

    def update(self, page_id, intended):
        self._apply(intended)
        self.page["last_edited_time"] = "2026-10-08T21:00:00.000Z"
        return {"id": PAGE_ID}

    def owner_activates(self, status="New", surface=True):
        """The owner's separate Notion edit; the writer has no path to this."""
        self.page["properties"]["Status"] = {"type": "select", "select": {"name": status}}
        self.page["properties"]["Surface Before Work?"] = {"type": "checkbox", "checkbox": surface}

    def read_executor(self):
        return lambda query: {"results": [deepcopy(self.page)], "has_more": False}


def ckr6_lookup(notion, lesson_id):
    return activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os", issue_number=3418, task_reference="issue:#3418",
        capability_keywords=("failure-avoidance",), known_knowledge_refs=(lesson_id,),
        specialized_knowledge_required=True, execute_read=notion.read_executor(),
    )


CREATE_WITH_METADATA = catalog.CONTINUATION_CONSUMER_REQUEST_ID
CREATE_WITHOUT_METADATA = catalog.REQUEST_ID
UPDATE_METADATA = catalog.LL93_METADATA_REQUEST_ID


def test_reviewed_create_with_metadata_becomes_ckr6_retrievable_only_after_owner_activation():
    notion = FakeNotion()
    result = execute(AdmittedRequest(100, issue_number=3417, request_id=CREATE_WITH_METADATA), notion)

    assert result["status"] == "persisted" and result["readback_verified"] is True
    assert result["lesson_id"] == "LL-101"
    assert result["activation_prerequisites"] == {
        "required_fields_present": False,
        "missing_owner_activation": ["Status", "Surface Before Work?"],
        "missing_reviewed_metadata": [],
    }
    # The writer never sent an activation field.
    assert not set(notion.sent[0]) & catalog.PROTECTED_FIELDS

    # Persisted but not yet retrievable: CKR6 cannot select it.
    before = ckr6_lookup(notion, "LL-101")
    assert before["selected_lessons"] == [] and before["lesson_retrieval_status"] != "sufficient"

    notion.owner_activates()
    after = ckr6_lookup(notion, "LL-101")
    assert after["lesson_retrieval_status"] == "sufficient"
    assert after["selected_lesson_ids"] == ["LL-101"]
    assert after["selected_lessons"][0]["source_revision"] == notion.page["last_edited_time"]

    # A re-run is `unchanged` and now reports the page ready.
    rerun = execute(AdmittedRequest(101, issue_number=3417, request_id=CREATE_WITH_METADATA), notion)
    assert rerun["status"] == "unchanged"
    assert rerun["activation_prerequisites"] == {
        "required_fields_present": True, "missing_owner_activation": [], "missing_reviewed_metadata": [],
    }


def test_reviewed_create_without_area_is_reported_unretrievable_and_owner_activation_cannot_fix_it():
    notion = FakeNotion()
    result = execute(AdmittedRequest(100, issue_number=3417, request_id=CREATE_WITHOUT_METADATA), notion)

    assert result["status"] == "persisted"
    assert result["activation_prerequisites"] == {
        "required_fields_present": False,
        "missing_owner_activation": ["Status", "Surface Before Work?"],
        "missing_reviewed_metadata": ["Area", "Learning Type", "Source Link"],
    }
    notion.owner_activates()
    assert activation_prerequisites(notion.page)["missing_reviewed_metadata"] == [
        "Area", "Learning Type", "Source Link"]
    outcome = ckr6_lookup(notion, "LL-101")
    # The warning is true: CKR6 still cannot use the page the owner activated.
    assert outcome["selected_lessons"] == [] and outcome["lesson_retrieval_status"] != "sufficient"
    assert isinstance(normalize_lesson_row(notion.page), LessonActivationSkip)


def test_reviewed_metadata_update_of_existing_lesson_reaches_retrieval_after_owner_activation():
    notion = FakeNotion(blank_page(93))
    request = AdmittedRequest(100, "LL-93", REVISION, UPDATE_METADATA, 3417)
    result = execute(request, notion)

    assert result["status"] == "persisted" and result["lesson_id"] == "LL-93"
    assert result["activation_prerequisites"]["missing_reviewed_metadata"] == []
    assert result["activation_prerequisites"]["missing_owner_activation"] == ["Status", "Surface Before Work?"]
    assert set(notion.sent[0]) == set(catalog.lesson_for(UPDATE_METADATA))

    notion.owner_activates()
    selected = ckr6_lookup(notion, "LL-93")
    assert selected["selected_lesson_ids"] == ["LL-93"]
    assert selected["selected_lessons"][0]["source_revision"] == result["revision"]


def test_readiness_is_reported_only_for_a_verified_readback():
    notion = FakeNotion(blank_page(93))
    stale = AdmittedRequest(100, "LL-93", "2026-01-01T00:00:00.000Z", UPDATE_METADATA, 3417)
    result = execute(stale, notion)
    assert result["status"] == "conflict" and result["reason_code"] == "stale-revision-refused"
    assert result["activation_prerequisites"] is None and notion.sent == []


LINK = "https://github.com/Blummer92/agent-os/issues/3305"


def modeled_page(*, status="New", surface=True, area="Governance", learning_type="Mistake", link=LINK):
    page = blank_page(77)
    props = page["properties"]
    props["Area"] = _prop("select", area)
    props["Learning Type"] = _prop("select", learning_type)
    props["Applies To"] = _prop("multi_select", ("Notion",))
    props["Source Link"] = _prop("url", link)
    props["Status"] = {"type": "select", "select": None if status is None else {"name": status}}
    props["Surface Before Work?"] = {"type": "checkbox", "checkbox": surface}
    return page


def ckr6_sufficient(page):
    notion = FakeNotion(page)
    return ckr6_lookup(notion, "LL-77")["lesson_retrieval_status"] == "sufficient"


@pytest.mark.parametrize("status", [None, "New"])
@pytest.mark.parametrize("surface", [False, True])
@pytest.mark.parametrize("area", [None, "Governance"])
@pytest.mark.parametrize("learning_type", [None, "Mistake"])
@pytest.mark.parametrize("link", [None, LINK])
def test_with_recognized_values_the_prerequisites_match_ckr6_eligibility_exactly(
    status, surface, area, learning_type, link
):
    page = modeled_page(status=status, surface=surface, area=area, learning_type=learning_type, link=link)
    prerequisites = activation_prerequisites(page)
    row = normalize_lesson_row(page)
    missing = set(prerequisites["missing_owner_activation"] + prerequisites["missing_reviewed_metadata"])

    # The reader skips exactly when Area, Learning Type or Status is missing.
    assert isinstance(row, LessonActivationSkip) == bool({"Area", "Learning Type", "Status"} & missing)
    # With recognized values, CKR6 reaches `sufficient` exactly when nothing is missing.
    assert prerequisites["required_fields_present"] is (not missing)
    assert ckr6_sufficient(page) is prerequisites["required_fields_present"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "Archived note"},
        {"status": "Bogus"},
        {"area": "Bogus"},
        {"learning_type": "Bogus"},
        {"link": "https://example.com/x"},
        {"link": "http://github.com/Blummer92/agent-os/issues/1"},
        {"link": "https://github.com/" + "x" * 600},
    ],
)
def test_presence_is_necessary_not_sufficient_and_the_writer_does_not_claim_eligibility(overrides):
    """Documented limit: unrecognized, archived or non-canonical values still read as present."""
    page = modeled_page(**overrides)
    prerequisites = activation_prerequisites(page)
    assert prerequisites["required_fields_present"] is True  # presence only
    assert not ckr6_sufficient(page)  # the reader alone rejects it
    assert set(prerequisites) == {"required_fields_present", "missing_owner_activation", "missing_reviewed_metadata"}
    assert "retrieval_ready" not in prerequisites and "eligible" not in prerequisites


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"area": "  "}, "Area"),
        ({"learning_type": " "}, "Learning Type"),
        ({"status": "\t"}, "Status"),
        ({"link": "   "}, "Source Link"),
    ],
)
def test_blank_values_count_as_missing_and_ckr6_agrees(overrides, field):
    page = modeled_page(**overrides)
    prerequisites = activation_prerequisites(page)
    assert field in prerequisites["missing_owner_activation"] + prerequisites["missing_reviewed_metadata"]
    assert prerequisites["required_fields_present"] is False
    assert not ckr6_sufficient(page)


@pytest.mark.parametrize("request_id", sorted(catalog.LESSONS))
def test_every_reviewed_catalog_entry_with_metadata_uses_vocabulary_the_reader_accepts(request_id):
    properties = dict(catalog.lesson_for(request_id))
    if "Area" not in properties and "Learning Type" not in properties:
        pytest.skip("narrative-only entry; metadata already lives on the existing page")
    assert {"Area", "Learning Type"} <= set(properties), "an entry naming one must name both"

    page = blank_page(55)
    for name, value in properties.items():
        page["properties"][name] = _prop(catalog.WRITABLE_TYPES[name], value)
    page["properties"]["Status"] = {"type": "select", "select": {"name": "New"}}
    page["properties"]["Surface Before Work?"] = {"type": "checkbox", "checkbox": True}

    row = normalize_lesson_row(page)
    assert not isinstance(row, LessonActivationSkip), getattr(row, "reason", None)
    assert activation_prerequisites(page)["required_fields_present"] is True
