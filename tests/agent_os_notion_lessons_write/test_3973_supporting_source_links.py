"""#3973: reviewed catalog + guarded writer may carry Supporting Source Links.

A separately reviewed, exact-revision-bound supporting-reference update
is permitted through the existing catalog/admission/writer boundaries:
one canonical ref per rich_text item, max five, distinct, this repo only.
Status / Surface Before Work? stay owner-only and unwritable.

The refs used here are the verified #3973 seed pair -- issue #2064
(original existing-bug backlog selection failure) and merged PR #2077
(explicitly `Fixes #2064`) -- used only as well-formed canonical refs in
a synthetic test-only entry, NOT as a reviewed proposal for any lesson.
"""
from copy import deepcopy
import unittest
from unittest.mock import patch

from scripts.agent_os_notion_lessons_write.admission import AdmittedRequest, admit
from scripts.agent_os_notion_lessons_write.catalog import LESSONS, validate_entry
from scripts.agent_os_notion_lessons_write.writer import execute, properties
from tests.agent_os_notion_lessons_write.test_writer import (
    CONTEXT, REVISION, Client, event, page, update_request,
)

REQUEST_ID = "ll-3973-supporting-refs-test-only"
SUPPORTING = (
    "https://github.com/Blummer92/agent-os/issues/2064",
    "https://github.com/Blummer92/agent-os/pull/2077",
)
GOVERNANCE_REF = "01_Shared_Standards/python/testing-standard.md"


def entry(properties, target="LL-93"):
    return {"target_lesson_id": target, "properties": properties}


def supporting_entry(refs=SUPPORTING):
    return entry({"Supporting Source Links": refs})


class CatalogSupportingRefsTests(unittest.TestCase):
    def test_reviewed_supporting_refs_entry_is_valid(self):
        validated = validate_entry(supporting_entry())
        self.assertEqual(validated["properties"]["Supporting Source Links"], SUPPORTING)

    def test_governance_path_supporting_ref_is_valid(self):
        validate_entry(supporting_entry((GOVERNANCE_REF,)))

    def test_invalid_supporting_refs_are_refused(self):
        invalid = {
            "foreign-repo": ("https://github.com/Other/repo/pull/1",),
            "malformed": ("not a url",),
            "duplicate": (SUPPORTING[0], SUPPORTING[0]),
            "too-many": tuple(
                f"https://github.com/Blummer92/agent-os/issues/{2064 + i}" for i in range(6)
            ),
            "oversized": ("https://github.com/Blummer92/agent-os/issues/2064" + "x" * 500,),
            "not-a-tuple": [SUPPORTING[0]],
            "empty": (),
            "non-string-item": (2064,),
        }
        for name, refs in invalid.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_entry(supporting_entry(refs))

    def test_supporting_refs_cannot_carry_activation_fields(self):
        with self.assertRaises(ValueError):
            validate_entry(entry({"Supporting Source Links": SUPPORTING, "Status": "Applied"}))
        with self.assertRaises(ValueError):
            validate_entry(entry({"Supporting Source Links": SUPPORTING, "Surface Before Work?": True}))


class WriterSupportingRefsTests(unittest.TestCase):
    def _client_with_empty_supporting_field(self):
        existing = page(metadata={"Area": "Governance", "Learning Type": "Mistake",
                                  "Applies To": ("Notion",), "Source Link": None})
        # Live Notion pages carry every database property, even when empty.
        existing["properties"]["Supporting Source Links"] = {"type": "rich_text", "rich_text": []}
        return Client(existing)

    def test_update_persists_one_item_per_ref_with_exact_readback(self):
        with patch("scripts.agent_os_notion_lessons_write.catalog.LESSONS",
                   {**LESSONS, REQUEST_ID: supporting_entry()}):
            request = admit(
                event(f"/agent-os notion-write {REQUEST_ID} LL-93 {REVISION}", number=3417),
                **CONTEXT,
            )
            client = self._client_with_empty_supporting_field()
            result = execute(request, client)
            self.assertEqual(result["status"], "persisted")
            self.assertTrue(result["readback_verified"])
            self.assertEqual(client.calls.count("write"), 1)
            sent = client.sent[0]["Supporting Source Links"]
            self.assertEqual(
                [item["text"]["content"] for item in sent["rich_text"]],
                list(SUPPORTING),
            )
            self.assertEqual(client.page["properties"]["Status"]["select"], None)
            self.assertFalse(client.page["properties"]["Surface Before Work?"]["checkbox"])
            # A second execution with the same reviewed entry is unchanged.
            self.assertEqual(execute(request, client)["status"], "unchanged")
            self.assertEqual(client.calls.count("write"), 1)

    def test_missing_live_schema_property_blocks_the_write(self):
        with patch("scripts.agent_os_notion_lessons_write.catalog.LESSONS",
                   {**LESSONS, REQUEST_ID: supporting_entry()}):
            request = AdmittedRequest(100, "LL-93", REVISION, REQUEST_ID, 3417)
            client = self._client_with_empty_supporting_field()
            del client.schema_value["properties"]["Supporting Source Links"]
            result = execute(request, client)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["reason_code"], "live-schema-drift")
            self.assertEqual(client.calls.count("write"), 0)

    def test_stale_revision_still_refuses_the_supporting_update(self):
        with patch("scripts.agent_os_notion_lessons_write.catalog.LESSONS",
                   {**LESSONS, REQUEST_ID: supporting_entry()}):
            stale = update_request(revision="2026-10-06T19:00:00.000Z")
            stale = AdmittedRequest(stale.comment_id, stale.expected_lesson_id,
                                    stale.expected_revision, REQUEST_ID, stale.issue_number)
            client = self._client_with_empty_supporting_field()
            result = execute(stale, client)
            self.assertEqual(result["status"], "conflict")
            self.assertEqual(result["reason_code"], "stale-revision-refused")
            self.assertEqual(client.calls.count("write"), 0)


if __name__ == "__main__":
    unittest.main()
