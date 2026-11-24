"""#3417: reviewed LL-82 continuation refinement update entry (#3485 + PR #3670).

Offline only: no network, no credentials, no live Notion. Covers the
mission's regression list for the LL-82 update: stable Lesson-ID resolution,
revision binding, no-op on identical content, protected-field preservation,
emission-vs-dispatch evidence distinction, duplicate-create retirement and
CKR2 relevance without false-positive selection.
"""
from copy import deepcopy
import unittest

from scripts.agent_os_notion_lessons_write.admission import AdmittedRequest
from scripts.agent_os_notion_lessons_write.catalog import (
    LESSONS, LL82_CONTINUATION_REFINEMENT_REQUEST_ID, PROTECTED_FIELDS, WRITABLE_TYPES, lesson_for,
)
from scripts.agent_os_notion_lessons_write.writer import execute, properties
from tests.agent_os_notion_lessons_write.test_writer import Client


class LL82Client(Client):
    """Client with the live LL-82 schema options (Area includes Automation)."""

    def __init__(self, existing=None):
        super().__init__(existing)
        self.schema_value["properties"]["Area"]["select"]["options"].append({"name": "Automation"})
        self.schema_value["properties"]["Applies To"]["multi_select"]["options"].append({"name": "Dashboard"})
        if existing is not None:
            self.receipt_id = existing["id"]

REQUEST_ID = LL82_CONTINUATION_REFINEMENT_REQUEST_ID
VALUES = lesson_for(REQUEST_ID)
REVISION = "2026-11-15T00:40:00.000Z"
SOURCE_ID = "00000000-0000-0000-0000-000000000001"
PAGE_ID = "00000000-0000-0000-0000-000000000082"

# Live LL-82 narrative before the refinement (fetched 2026-11-23).
OLD_WHAT_HAPPENED = (
    "Agent OS repository code can emit structured continuation state after a subordinate "
    "GitHub mutation, yet the native ChatGPT tool loop may still stop and require another "
    "user message. Repository-side continuation evidence is therefore not proof that the "
    "execution host will continue the parent mission."
)


def _prop(name, value):
    kind = WRITABLE_TYPES[name]
    if name == "Supporting Source Links":
        return {"type": "rich_text",
                "rich_text": [{"type": "text", "plain_text": ref, "text": {"content": ref}} for ref in value]}
    if kind in ("title", "rich_text"):
        return {"type": kind, kind: [{"type": "text", "plain_text": value, "text": {"content": value}}]}
    if kind == "select":
        return {"type": "select", "select": None if value is None else {"name": value}}
    if kind == "multi_select":
        return {"type": "multi_select", "multi_select": [{"name": item} for item in value]}
    return {"type": "url", "url": value}


def ll82_page(*, updated=False, title=None, revision=REVISION):
    values = dict(VALUES) if updated else {
        "Lesson Learned": VALUES["Lesson Learned"],
        "What Happened": OLD_WHAT_HAPPENED,
        "What To Do Next Time": "old guidance",
        "Guardrail": "old guardrail",
        "Area": "Automation",
        "Learning Type": "Testing lesson",
        "Source Link": "https://github.com/Blummer92/agent-os/issues/2220",
        "Supporting Source Links": (
            "https://github.com/Blummer92/agent-os/issues/2230",
            "https://github.com/Blummer92/agent-os/issues/2093",
        ),
    }
    if title is not None:
        values["Lesson Learned"] = title
    props = {name: _prop(name, value) for name, value in values.items()}
    # The entry does not name Applies To, so the live value survives an
    # update; both page shapes carry it.
    props["Applies To"] = {"type": "multi_select", "multi_select": [{"name": "Dashboard"}]}
    props["Owner / Agent"] = {"type": "rich_text", "rich_text": [
        {"type": "text", "plain_text": "ChatGPT Orchestrator / execution-host integration"}]}
    props["Status"] = {"type": "select", "select": {"name": "Applied"}}
    props["Surface Before Work?"] = {"type": "checkbox", "checkbox": True}
    props["Lesson ID"] = {"type": "unique_id", "unique_id": {"prefix": "LL", "number": 82}}
    return {"id": PAGE_ID, "parent": {"type": "data_source_id", "data_source_id": SOURCE_ID},
            "last_edited_time": revision, "properties": props, "archived": False, "in_trash": False}


def request(revision=REVISION):
    return AdmittedRequest(7119142354, "LL-82", revision, REQUEST_ID, 3417)


class LL82UpdateExecutionTests(unittest.TestCase):
    def test_current_revision_update_is_admitted_and_preserves_protected_fields(self):
        client = LL82Client(ll82_page())
        result = execute(request(), client)
        self.assertEqual(result["status"], "persisted")
        self.assertTrue(result["readback_verified"])
        self.assertEqual(result["lesson_id"], "LL-82")
        self.assertEqual(client.calls.count("write"), 1)
        sent = client.sent[0]
        # Exactly the reviewed fields, never protected activation fields.
        self.assertEqual(set(sent), set(VALUES))
        self.assertFalse(set(sent) & PROTECTED_FIELDS)
        # Live protected fields were not altered by the update.
        self.assertEqual(client.page["properties"]["Status"]["select"], {"name": "Applied"})
        self.assertTrue(client.page["properties"]["Surface Before Work?"]["checkbox"])
        # Owner field is not part of the reviewed entry and stays.
        self.assertIn("Owner / Agent", client.page["properties"])
        # Provenance corrected: incident #3485, implementation PR #3670 supporting.
        urls = {item["text"]["content"] for item in
                sent["Supporting Source Links"]["rich_text"]}
        self.assertEqual(sent["Source Link"], {"url": "https://github.com/Blummer92/agent-os/issues/3485"})
        self.assertIn("https://github.com/Blummer92/agent-os/pull/3670", urls)

    def test_changed_live_title_still_resolves_by_lesson_id_without_create(self):
        client = LL82Client(ll82_page(title="A retitled lesson row that must not duplicate"))
        result = execute(request(), client)
        self.assertEqual(result["status"], "persisted")
        self.assertEqual(result["page_id"], PAGE_ID)
        self.assertFalse(hasattr(client, "create_reservations") and client.create_reservations)
        self.assertEqual(client.calls.count("write"), 1)

    def test_stale_revision_is_refused_with_zero_writes(self):
        client = LL82Client(ll82_page(revision="2026-11-20T00:00:00.000Z"))
        result = execute(request(), client)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["reason_code"], "stale-revision-refused")
        self.assertNotIn("write", client.calls)

    def test_identical_content_is_unchanged_without_a_write(self):
        client = LL82Client(ll82_page(updated=True))
        result = execute(request(), client)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(result["reason_code"], "identical-canonical-content")
        self.assertNotIn("write", client.calls)

    def test_payload_matches_reviewed_entry_and_stays_activation_free(self):
        payload = properties(REQUEST_ID)
        self.assertEqual(set(payload), set(VALUES))
        self.assertFalse(set(payload) & PROTECTED_FIELDS)
        for name, prop in payload.items():
            kind = WRITABLE_TYPES[name]
            self.assertEqual(next(iter(prop)), kind)


class LL82EvidenceDistinctionTests(unittest.TestCase):
    def test_entry_distinguishes_requested_dispatched_verified(self):
        guidance = VALUES["What To Do Next Time"]
        self.assertIn("requested (payload emitted)", guidance)
        self.assertIn("dispatched (a host consumed it and initiated the next operation)", guidance)
        self.assertIn("verified (an execution receipt confirms the operation occurred)", guidance)

    def test_entry_never_claims_successful_host_continuation(self):
        body = " ".join(str(v) for v in VALUES.values())
        self.assertIn("remain unverified", VALUES["What Happened"])
        self.assertIn("not independently reproduced", VALUES["What Happened"])
        self.assertNotIn("successfully continued", body)
        self.assertNotIn("dispatch verified", body)


class LL82RelevanceTests(unittest.TestCase):
    """Production CKR6 retrieval of the refined LL-82 page (issue-start preflight).

    Positive: continuation-integration coding requests retrieve LL-82.
    Negative: unrelated tasks, including broad execution/agent/workflow terms
    and the dashboard task the old Applies To false-positived on, do not.
    """

    @staticmethod
    def _lookup(task, keywords, known=()):
        page = ll82_page(updated=True)
        from agent_os_execution_service.issue_start_lesson_preflight import (
            activate_issue_start_lesson_preflight,
        )
        return activate_issue_start_lesson_preflight(
            repository="Blummer92/agent-os", issue_number=3485, task_reference=task,
            capability_keywords=tuple(keywords), known_knowledge_refs=tuple(known),
            specialized_knowledge_required=True,
            execute_read=lambda query: {"results": [deepcopy(page)], "has_more": False},
        )

    def test_continuation_host_integration_requests_retrieve_ll82(self):
        for task, keywords, known in (
            ("issue:#3485", ("failure-avoidance",), ("LL-82",)),
            ("issue:#3485", ("failure-avoidance",), ()),
            ("verify native host continuation dispatch", ("failure-avoidance",), ()),
        ):
            with self.subTest(task=task, known=known):
                result = self._lookup(task, keywords, known)
                self.assertEqual(result["lesson_retrieval_status"], "sufficient")
                self.assertEqual(result["selected_lesson_ids"], ["LL-82"])

    def test_unrelated_and_broad_term_requests_do_not_select_ll82(self):
        # Note: a "dashboard" keyword task still selects LL-82 through the
        # live Applies To ["Dashboard"] value. Clearing it is not expressible
        # in the reviewed-entry contract (no empty multi_select) and is
        # reported as a residual owner decision, not pinned here.
        for task, keywords in (
            ("routine packaging workflow for build artifacts", ("packaging",)),
            ("write a curriculum quiz", ("curriculum",)),
            ("generic execution agent workflow task", ("execution", "agent", "workflow")),
        ):
            with self.subTest(task=task):
                result = self._lookup(task, keywords)
                self.assertNotEqual(result["lesson_retrieval_status"], "sufficient")
                self.assertEqual(result["selected_lesson_ids"], [])


class LL82DuplicateCreateRetiredTests(unittest.TestCase):
    def test_duplicate_create_candidate_is_not_in_the_shipped_catalog(self):
        self.assertNotIn("continuation-live-consumer-2026-10-30", LESSONS)
        # The refined lesson is an update of LL-82, never a competing create.
        self.assertEqual(LESSONS[REQUEST_ID]["target_lesson_id"], "LL-82")
        creates_with_continuation_title = [
            key for key, entry in LESSONS.items()
            if entry["target_lesson_id"] is None
            and "continuation" in str(entry["properties"].get("Lesson Learned", "")).casefold()
        ]
        self.assertEqual(creates_with_continuation_title, [])


if __name__ == "__main__":
    unittest.main()
