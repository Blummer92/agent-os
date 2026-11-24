"""Offline evidence comparison and append controls; no live provider."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from scripts.agent_os_notion_lessons_write import writer
from scripts.agent_os_notion_lessons_write.admission import AdmittedRequest
from scripts.agent_os_notion_lessons_write.catalog import SUPPORTING_SOURCE_LINKS
from tests.agent_os_notion_lessons_write import test_writer as fixtures

OLD = "https://github.com/Blummer92/agent-os/issues/3485"
NEW = "https://github.com/Blummer92/agent-os/pull/3670"
PRIMARY = "https://github.com/Blummer92/agent-os/issues/3690"

def supporting(ref):
    return {"type": "rich_text", "rich_text": [
        {"type": "text", "plain_text": ref, "text": {"content": ref}},
    ]}

class EvidenceReviewIndependentTests(unittest.TestCase):
    def duplicate(self, defect=None):
        client, request_id = fixtures.DuplicateEvidenceReviewTests()._duplicate_client()
        row = client.rows[0]
        if defect == "missing-url":
            del row["properties"]["Source Link"]["url"]
        elif defect == "invalid-url-type":
            row["properties"]["Source Link"]["url"] = False
        elif defect == "malformed-legacy-text":
            row["properties"]["Supporting Source Links"]["rich_text"] = [
                {"type": "text", "text": None},
            ]
        elif defect == "duplicate-support":
            entry = supporting(OLD)
            row["properties"][SUPPORTING_SOURCE_LINKS] = entry
            entry["rich_text"].append(deepcopy(entry["rich_text"][0]))
        elif defect == "link-divergence":
            row["properties"][SUPPORTING_SOURCE_LINKS] = supporting(OLD)
            row["properties"][SUPPORTING_SOURCE_LINKS]["rich_text"][0]["href"] = PRIMARY
        return writer.execute(AdmittedRequest(100, request_id=request_id), client), client

    def test_malformed_sources_are_not_novel_evidence(self):
        for defect in ("missing-url", "invalid-url-type", "malformed-legacy-text",
                       "duplicate-support", "link-divergence"):
            with self.subTest(defect=defect):
                out, client = self.duplicate(defect)
                self.assertEqual(out["reason_code"], "possible-semantic-duplicate")
                review, = out["duplicate_evidence_reviews"]
                self.assertEqual(review["source_comparison"], "unavailable")
                self.assertEqual(review["new_source_refs_to_review"], [])
                self.assertEqual(review["claim_comparison"], "text-difference-only")
                self.assertNotIn("write", client.calls)

    def run_append(self, mutation=None):
        existing = fixtures.page()
        existing["properties"][SUPPORTING_SOURCE_LINKS] = supporting(OLD)
        existing["properties"]["Source Link"] = {"type": "url", "url": PRIMARY}
        if mutation == "no-primary":
            del existing["properties"]["Source Link"]
        if mutation == "known-blank-primary":
            existing["properties"]["Source Link"]["url"] = None
        client = fixtures.Client(existing)
        if mutation in ("corrupt-primary-after-write", "corrupt-support-link-after-write"):
            get_page = client.get_page
            def readback(page_id):
                observed = get_page(page_id)
                if "write" in client.calls:
                    if mutation == "corrupt-primary-after-write":
                        observed["properties"]["Source Link"]["url"] = None
                    else:
                        observed["properties"][SUPPORTING_SOURCE_LINKS]["rich_text"][-1]["href"] = PRIMARY
                return observed
            client.get_page = readback
        wanted = {SUPPORTING_SOURCE_LINKS: (OLD, NEW)}
        with patch.object(writer, "lesson_for", return_value=wanted), patch.object(
            writer, "entry_for", return_value={"target_lesson_id": "LL-93"}
        ):
            result = writer.execute(AdmittedRequest(100, "LL-93", fixtures.REVISION, "test-append", 3417), client)
        return result, client

    def test_append_reports_only_after_actual_readback(self):
        result, client = self.run_append()
        self.assertEqual(result["status"], "persisted")
        self.assertTrue(result["readback_verified"])
        self.assertEqual(result["evidence_update"]["added_supporting_source_links"], [NEW])
        self.assertTrue(result["evidence_update"]["primary_source_preserved"])
        self.assertEqual(client.page["properties"]["Source Link"]["url"], PRIMARY)
        self.assertNotIn("Source Link", client.sent[0])

    def test_known_blank_primary_is_not_missing_metadata(self):
        result, client = self.run_append("known-blank-primary")
        self.assertEqual(result["status"], "persisted")
        self.assertIsNone(client.page["properties"]["Source Link"]["url"])

    def test_append_requires_observable_primary_even_when_not_modified(self):
        result, client = self.run_append("no-primary")
        self.assertFalse(result["readback_verified"])
        self.assertNotIn("evidence_update", result)
        self.assertNotIn("write", client.calls)

    def test_append_has_no_receipt_when_primary_changes_or_link_diverges(self):
        for revision in ("corrupt-primary-after-write", "corrupt-support-link-after-write"):
            with self.subTest(revision=revision):
                result, client = self.run_append(revision)
                self.assertEqual(result["write_attempts"], 1)
                self.assertFalse(result["readback_verified"])
                self.assertNotIn("evidence_update", result)
