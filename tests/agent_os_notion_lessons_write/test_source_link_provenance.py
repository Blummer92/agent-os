"""Regression tests for the #3417/#3418 Source Link provenance catalog entries.

Offline only: no Notion, GitHub or network access. The writer path uses the
existing injected Client fake from test_writer.
"""
import unittest

from scripts.agent_os_notion_lessons_write.admission import AdmittedRequest, WriteBlocked, admit
from scripts.agent_os_notion_lessons_write.catalog import (
    LESSONS, PROTECTED_FIELDS, lesson_for, target_for, validate_entry,
)
from scripts.agent_os_notion_lessons_write.writer import execute, properties
from tests.agent_os_notion_lessons_write.test_writer import CONTEXT, PAGE_ID, SOURCE_ID, Client, _prop, event

LL65 = "ll-65-source-link-2026-11-03"
LL66 = "ll-66-source-link-2026-11-03"
LL68 = "ll-68-source-link-2026-11-03"
ISSUE_1904 = "https://github.com/Blummer92/agent-os/issues/1904"
ISSUE_229 = "https://github.com/Blummer92/agent-os/issues/229"
ISSUE_1602 = "https://github.com/Blummer92/agent-os/issues/1602"
LL65_REVISION = "2026-09-07T23:09:56.000Z"
LL66_REVISION = "2026-09-06T19:20:19.000Z"
LL68_REVISION = "2026-09-09T01:41:21.000Z"
PROVENANCE = (
    (LL65, "LL-65", ISSUE_1904, LL65_REVISION),
    (LL66, "LL-66", ISSUE_229, LL66_REVISION),
    (LL68, "LL-68", ISSUE_1602, LL68_REVISION),
)
NARRATIVE = {"Lesson Learned", "What Happened", "What To Do Next Time", "Guardrail"}
DESCRIPTIVE = {"Area", "Learning Type", "Applies To", "Source Link"}


def lesson_page(number, source_link=None, revision=LL66_REVISION):
    """A live-shaped page; Status and Surface Before Work? are set and must stay untouched."""
    values = {
        "Lesson Learned": "Synthetic lesson title",
        "What Happened": "Synthetic history",
        "What To Do Next Time": "Synthetic next step",
        "Guardrail": "Synthetic guardrail",
        "Area": "Testing", "Learning Type": "Testing lesson",
        "Applies To": ("Notion",), "Source Link": source_link,
    }
    props = {name: _prop(name, value) for name, value in values.items()}
    props["Owner / Agent"] = {"type": "rich_text", "rich_text": [
        {"type": "text", "plain_text": "existing owner", "text": {"content": "existing owner"}}]}
    props["Status"] = {"type": "select", "select": {"name": "Applied"}}
    props["Surface Before Work?"] = {"type": "checkbox", "checkbox": True}
    props["Lesson ID"] = {"type": "unique_id", "unique_id": {"prefix": "LL", "number": number}}
    return {"id": PAGE_ID, "parent": {"type": "data_source_id", "data_source_id": SOURCE_ID},
            "last_edited_time": revision, "properties": props, "archived": False, "in_trash": False}


def _without_source_link(page):
    return {name: value for name, value in page["properties"].items() if name != "Source Link"}


class ProvenanceCatalogEntryTests(unittest.TestCase):
    def test_exact_lesson_ids_and_authenticated_source_links(self):
        for request_id, lesson_id, url, _ in PROVENANCE:
            with self.subTest(request_id=request_id):
                self.assertEqual(target_for(request_id), lesson_id)
                self.assertEqual(lesson_for(request_id), {"Source Link": url})
                self.assertIs(validate_entry(LESSONS[request_id]), LESSONS[request_id])
                self.assertEqual(properties(request_id), {"Source Link": {"url": url}})

    def test_entries_exclude_protected_and_narrative_fields(self):
        for request_id, _, _, _ in PROVENANCE:
            with self.subTest(request_id=request_id):
                names = set(lesson_for(request_id))
                self.assertFalse(names & PROTECTED_FIELDS)
                self.assertFalse(names & NARRATIVE)
                self.assertTrue(names <= DESCRIPTIVE)

    def test_source_link_values_are_limited_to_repository_issue_or_pull_urls(self):
        refused = [
            "https://github.com/Blummer92/agent-os/issues/229/",
            "https://github.com/Blummer92/agent-os/issues/0",
            "https://github.com/Blummer92/agent-os/blob/main/README.md",
            "https://github.com/other/agent-os/issues/229",
            "http://github.com/Blummer92/agent-os/issues/229",
            "https://github.com/Blummer92/agent-os/issues/229 ",
        ]
        for url in refused:
            with self.subTest(url=url):
                entry = {"target_lesson_id": "LL-66", "properties": {"Source Link": url}}
                with self.assertRaisesRegex(ValueError, "reviewed-field-value-invalid"):
                    validate_entry(entry)

    def test_protected_activation_fields_cannot_be_registered(self):
        for name, value in (("Status", "Applied"), ("Surface Before Work?", True)):
            with self.subTest(field=name):
                entry = {"target_lesson_id": "LL-66",
                         "properties": {name: value, "Source Link": ISSUE_229}}
                with self.assertRaisesRegex(ValueError, "protected-activation-field-refused"):
                    validate_entry(entry)


class ProvenanceCommandAdmissionTests(unittest.TestCase):
    def test_update_command_binds_exact_lesson_and_revision(self):
        admitted = admit(event(f"/agent-os notion-write {LL66} LL-66 {LL66_REVISION}"), **CONTEXT)
        self.assertEqual((admitted.request_id, admitted.expected_lesson_id, admitted.expected_revision),
                         (LL66, "LL-66", LL66_REVISION))

    def test_wrong_lesson_or_missing_revision_is_refused(self):
        cases = (
            (f"/agent-os notion-write {LL66} LL-68 {LL66_REVISION}", "reviewed-target-lesson-mismatch"),
            (f"/agent-os notion-write {LL66} LL-66", "exact-update-binding-required"),
            (f"/agent-os notion-write {LL66}", "exact-update-binding-required"),
        )
        for command, reason in cases:
            with self.subTest(command=command):
                with self.assertRaisesRegex(WriteBlocked, reason):
                    admit(event(command), **CONTEXT)


class ProvenanceWriterTests(unittest.TestCase):
    def request(self, request_id, lesson_id, revision):
        return AdmittedRequest(100, lesson_id, revision, request_id, 3417)

    def test_writes_only_source_link_and_preserves_other_properties(self):
        existing = lesson_page(66)
        client = Client(existing=existing)
        result = execute(self.request(LL66, "LL-66", LL66_REVISION), client)
        self.assertEqual((result["status"], result["reason_code"], result["readback_verified"],
                          result["write_attempts"], result["lesson_id"]),
                         ("persisted", "exact-canonical-readback-confirmed", True, 1, "LL-66"))
        self.assertEqual(client.sent, [{"Source Link": {"url": ISSUE_229}}])
        self.assertEqual(client.calls.count("write"), 1)
        self.assertEqual(client.page["properties"]["Source Link"]["url"], ISSUE_229)
        self.assertEqual(_without_source_link(client.page), _without_source_link(existing))

    def test_each_registered_entry_writes_only_its_source_link(self):
        for request_id, lesson_id, url, revision in PROVENANCE:
            with self.subTest(request_id=request_id):
                existing = lesson_page(int(lesson_id.split("-")[1]), revision=revision)
                client = Client(existing=existing)
                result = execute(self.request(request_id, lesson_id, revision), client)
                self.assertEqual((result["status"], result["lesson_id"], result["write_attempts"]),
                                 ("persisted", lesson_id, 1))
                self.assertEqual(client.sent, [{"Source Link": {"url": url}}])
                self.assertEqual(_without_source_link(client.page), _without_source_link(existing))

    def test_stale_revision_is_refused_with_zero_writes(self):
        client = Client(existing=lesson_page(66))
        result = execute(self.request(LL66, "LL-66", "2026-09-06T19:20:18.000Z"), client)
        self.assertEqual((result["status"], result["reason_code"]), ("conflict", "stale-revision-refused"))
        self.assertEqual(client.calls.count("write"), 0)
        self.assertEqual(client.sent, [])

    def test_identical_existing_source_link_is_unchanged_with_zero_writes(self):
        client = Client(existing=lesson_page(68, source_link=ISSUE_1602, revision=LL68_REVISION))
        result = execute(self.request(LL68, "LL-68", LL68_REVISION), client)
        self.assertEqual((result["status"], result["reason_code"]),
                         ("unchanged", "identical-canonical-content"))
        self.assertEqual(client.calls.count("write"), 0)

    def test_page_with_different_lesson_identity_is_refused_with_zero_writes(self):
        client = Client(existing=lesson_page(68, revision=LL68_REVISION))
        result = execute(self.request(LL66, "LL-66", LL66_REVISION), client)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(client.calls.count("write"), 0)


if __name__ == "__main__":
    unittest.main()
