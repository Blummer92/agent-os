"""#3417 reviewed mutation-identity catalog candidate: bounded, activation-free."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from scripts.agent_os_notion_lessons_write.admission import admit, AdmittedRequest, WriteBlocked
from scripts.agent_os_notion_lessons_write.catalog import (
    LESSONS, PROTECTED_FIELDS, lesson_for, target_for, validate_entry,
)
from scripts.agent_os_notion_lessons_write.writer import execute, properties
from tests.agent_os_notion_lessons_write.test_writer import Client, CONTEXT, event

KEY = "ckr6-mutation-identity-executed-code"
TITLE = "Verify the executed code identity before trusting mutation-test results"


def entry(properties_value, target=None):
    return {"target_lesson_id": target, "properties": properties_value}


def qa_client():
    # The shared fake's schema stub predates the live "QA feedback" option; the
    # live data source carries it (LL-97 readback). Mirror live, nothing else.
    client = Client()
    client.schema_value["properties"]["Learning Type"]["select"]["options"].append({"name": "QA feedback"})
    return client


class MutationIdentityCatalogEntryTests(unittest.TestCase):
    def test_reviewed_entry_is_valid_bounded_and_activation_free(self):
        self.assertIs(validate_entry(LESSONS[KEY]), LESSONS[KEY])
        self.assertIsNone(target_for(KEY))
        values = lesson_for(KEY)
        self.assertEqual(values["Lesson Learned"], TITLE)
        self.assertEqual(values["Area"], "Testing")
        self.assertEqual(values["Learning Type"], "QA feedback")
        self.assertEqual(values["Source Link"], "https://github.com/Blummer92/agent-os/issues/4026")
        self.assertEqual(values["Supporting Source Links"],
                         ("https://github.com/Blummer92/agent-os/pull/4114",))
        self.assertFalse(PROTECTED_FIELDS & set(values))
        for name, value in values.items():
            if isinstance(value, str):
                self.assertLessEqual(len(value), 512, name)

    def test_owner_comment_admission_then_one_write_exact_readback(self):
        request = admit(event("/agent-os notion-write " + KEY, number=3417, state="closed"), **CONTEXT)
        self.assertEqual(request.request_id, KEY)
        self.assertIsNone(request.expected_lesson_id)
        client = qa_client()
        result = execute(request, client)
        self.assertEqual(result["status"], "persisted")
        self.assertTrue(result["readback_verified"])
        self.assertEqual(client.calls.count("write"), 1)
        self.assertEqual(set(client.sent[0]), set(lesson_for(KEY)))

    def test_second_identical_request_cannot_duplicate(self):
        request = AdmittedRequest(200, request_id=KEY)
        client = qa_client()
        self.assertEqual(execute(request, client)["status"], "persisted")
        client.rows = [deepcopy(client.page)]
        self.assertEqual(execute(AdmittedRequest(201, request_id=KEY), client)["status"], "unchanged")
        self.assertEqual(client.calls.count("write"), 1)

    def test_differing_same_title_lesson_is_conflict_never_overwrite(self):
        request = AdmittedRequest(202, request_id=KEY)
        client = qa_client()
        self.assertEqual(execute(request, client)["status"], "persisted")
        client.page["properties"]["Guardrail"]["rich_text"] = [
            {"type": "text", "plain_text": "someone else's weaker guardrail",
             "text": {"content": "someone else's weaker guardrail"}}]
        client.rows = [deepcopy(client.page)]
        result = execute(AdmittedRequest(203, request_id=KEY), client)
        self.assertEqual((result["status"], result["reason_code"]),
                         ("conflict", "existing-lesson-requires-reviewed-update-entry"))
        self.assertEqual(client.calls.count("write"), 1)

    def test_field_validation_refuses_unreviewed_variants_with_zero_writes(self):
        base = dict(lesson_for(KEY))
        invalid = {
            "status": entry({**base, "Status": "Applied"}),
            "surface": entry({**base, "Surface Before Work?": True}),
            "oversized": entry({**base, "Guardrail": "x" * 513}),
            "foreign-link": entry({**base, "Source Link": "https://example.com/x"}),
            "missing-narrative": entry({"Area": "Testing"}),
            "duplicate-supporting": entry({**base, "Supporting Source Links": base["Supporting Source Links"] * 2}),
        }
        for name, value in invalid.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_entry(value)
                with patch("scripts.agent_os_notion_lessons_write.catalog.LESSONS", {name: value}):
                    client = Client()
                    self.assertEqual(execute(AdmittedRequest(204, request_id=name), client)["status"], "blocked")
                    self.assertEqual(client.calls, [])

    def test_unknown_request_and_edited_command_are_refused(self):
        for command in ("/agent-os notion-write ckr6-mutation-identity",
                        "/agent-os notion-write " + KEY + " LL-93"):
            with self.subTest(command=command), self.assertRaises(WriteBlocked):
                admit(event(command, number=3417, state="closed"), **CONTEXT)


if __name__ == "__main__":
    unittest.main()
