"""Offline safety cases for one explicit Lessons Learned create/update."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.agent_os_notion_lessons_write.admission import (
    COMMAND_PREFIX, OWNER_ID, REPOSITORY, REPOSITORY_ID, WORKFLOW_REF,
    AdmittedRequest, WriteBlocked, admit,
)
from scripts.agent_os_notion_lessons_write.catalog import REQUEST_ID, WRITABLE_TYPES, lesson_for

LESSON = lesson_for(REQUEST_ID)
COMMAND = COMMAND_PREFIX + REQUEST_ID
from scripts.agent_os_notion_lessons_write.runner import main
from scripts.agent_os_notion_lessons_write.writer import execute, properties

SOURCE_ID = "00000000-0000-0000-0000-000000000001"
PAGE_ID = "00000000-0000-0000-0000-000000000002"
REVISION = "2026-10-06T20:00:00.000Z"
CONTEXT = dict(event_name="issue_comment", ref="refs/heads/main", workflow_ref=WORKFLOW_REF, run_attempt="1")


def event(body=COMMAND):
    return {"action": "created", "repository": {"full_name": REPOSITORY, "id": REPOSITORY_ID},
            "issue": {"number": 3305, "state": "open"},
            "comment": {"id": 100, "body": body, "created_at": REVISION, "updated_at": REVISION,
                        "user": {"id": OWNER_ID, "login": "Blummer92", "type": "User"}}}


def page(*, intended=True):
    props = {name: {"type": kind, **deepcopy(properties()[name])} for name, kind in WRITABLE_TYPES.items()}
    props["Owner / Agent"] = {"type": "rich_text", "rich_text": [{"type": "text", "plain_text": "existing owner"}]}
    if not intended:
        props["What Happened"]["rich_text"][0]["text"]["content"] = "Earlier context"
    return {"id": PAGE_ID, "parent": {"type": "data_source_id", "data_source_id": SOURCE_ID},
            "last_edited_time": REVISION, "properties": props, "archived": False, "in_trash": False}


class Client:
    def __init__(self, existing=None):
        self.page = deepcopy(existing)
        self.rows = [] if existing is None else [deepcopy(existing)]
        self.calls = []
        self.source = SOURCE_ID
        self.schema_value = {"id": SOURCE_ID, "properties": {
            name: {"type": kind} for name, kind in {**WRITABLE_TYPES, "Lesson ID": "unique_id", "Status": "select"}.items()}}
        self.more = False
        self.receipt_id = PAGE_ID
        self.raise_mutation = False
        self.fail_readback = False
        self.readback_mismatch = False
        self.change_protected = False
        self.query_count = 0
        self.appear = False
        self.reads = 0
        self.stale = False

    def verify_binding(self):
        self.calls.append("binding")
        return self.source

    def schema(self):
        self.calls.append("schema")
        return deepcopy(self.schema_value)

    def find_exact(self, title):
        self.calls.append("query")
        self.query_count += 1
        rows = [page(intended=False)] if self.appear and self.query_count > 1 else self.rows
        return {"results": deepcopy(rows), "has_more": self.more}

    def get_page(self, page_id):
        self.calls.append("get")
        self.reads += 1
        if self.fail_readback and "write" in self.calls:
            raise TimeoutError("provider private diagnostic")
        value = deepcopy(self.page)
        if self.stale and self.reads > 1:
            value["last_edited_time"] = "2026-10-06T21:00:00.000Z"
        if self.readback_mismatch and "write" in self.calls:
            value["properties"]["Guardrail"]["rich_text"] = []
        return value

    def create(self, intended):
        self.calls.append("write")
        self.page = page()
        if self.raise_mutation:
            raise TimeoutError("credential-class diagnostic")
        return {"id": self.receipt_id}

    def update(self, page_id, intended):
        self.calls.append("write")
        for name, value in intended.items():
            self.page["properties"][name] = {"type": WRITABLE_TYPES[name], **deepcopy(value)}
        if self.change_protected:
            self.page["properties"]["Approval"] = {"type": "checkbox", "checkbox": True}
        if self.raise_mutation:
            raise TimeoutError("credential-class diagnostic")
        return {"id": self.receipt_id}


class AdmissionTests(unittest.TestCase):
    def test_owner_create_is_admitted(self):
        self.assertEqual(admit(event(), **CONTEXT), AdmittedRequest(100))

    def test_exact_update_is_admitted(self):
        actual = admit(event(COMMAND + " " + PAGE_ID + " " + REVISION), **CONTEXT)
        self.assertEqual(actual.expected_page_id, PAGE_ID)
        self.assertEqual(actual.expected_revision, REVISION)

    def test_foreign_or_edited_or_closed_inputs_are_refused(self):
        cases = [("repository", "id", 123), ("repository", "full_name", "other/repo"),
                 ("issue", "number", 3306), ("issue", "state", "closed"),
                 ("comment", "updated_at", "edited"), ("comment", "id", True)]
        for section, key, value in cases:
            with self.subTest(section=section, key=key):
                value_event = event()
                value_event[section][key] = value
                with self.assertRaises(WriteBlocked):
                    admit(value_event, **CONTEXT)

    def test_pr_bot_and_foreign_actor_are_refused(self):
        for mutation in (lambda e: e["issue"].update(pull_request={}),
                         lambda e: e["comment"]["user"].update(id=1),
                         lambda e: e["comment"]["user"].update(type="Bot")):
            e = event()
            mutation(e)
            with self.assertRaises(WriteBlocked):
                admit(e, **CONTEXT)

    def test_rerun_schedule_and_branch_execution_are_refused(self):
        for key, value in (("run_attempt", "2"), ("event_name", "schedule"),
                           ("ref", "refs/heads/other"), ("workflow_ref", "other")):
            with self.subTest(key=key), self.assertRaises(WriteBlocked):
                admit(event(), **{**CONTEXT, key: value})

    def test_arbitrary_sensitive_schema_and_bulk_payloads_cannot_be_expressed(self):
        for body in (COMMAND + ' {"Approval":true}', COMMAND + ' {"student":"private"}',
                     COMMAND + " archive", COMMAND + " bulk", COMMAND + "\nprivate notes",
                     "/agent-os notion-write https://api.notion.com/v1/pages", COMMAND + " ",
                     COMMAND + " " + PAGE_ID + " invalid-revision", COMMAND + " ; echo token"):
            with self.subTest(body=body), self.assertRaises(WriteBlocked):
                admit(event(body), **CONTEXT)


class WriterTests(unittest.TestCase):
    def test_authorized_create_has_one_write_then_immediate_exact_readback(self):
        client = Client()
        result = execute(AdmittedRequest(100), client)
        self.assertEqual(result["status"], "persisted")
        self.assertTrue(result["readback_verified"])
        self.assertEqual(result["write_attempts"], 1)
        self.assertEqual(client.calls, ["binding", "schema", "query", "query", "write", "get"])

    def test_unchanged_skips_write_and_reads_exact_target(self):
        client = Client(page())
        result = execute(AdmittedRequest(100), client)
        self.assertEqual(result["status"], "unchanged")
        self.assertTrue(result["readback_verified"])
        self.assertEqual(result["write_attempts"], 0)
        self.assertNotIn("write", client.calls)

    def test_second_identical_request_cannot_duplicate(self):
        client = Client()
        self.assertEqual(execute(AdmittedRequest(100), client)["status"], "persisted")
        client.rows = [deepcopy(client.page)]
        self.assertEqual(execute(AdmittedRequest(101), client)["status"], "unchanged")
        self.assertEqual(client.calls.count("write"), 1)

    def test_differing_existing_content_requires_explicit_exact_update(self):
        client = Client(page(intended=False))
        result = execute(AdmittedRequest(100), client)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["page_id"], PAGE_ID)
        self.assertNotIn("write", client.calls)

    def test_exact_update_preserves_non_routine_fields(self):
        client = Client(page(intended=False))
        owner = deepcopy(client.page["properties"]["Owner / Agent"])
        result = execute(AdmittedRequest(100, PAGE_ID, REVISION), client)
        self.assertEqual(result["status"], "persisted")
        self.assertEqual(client.page["properties"]["Owner / Agent"], owner)
        self.assertEqual(client.calls[-2:], ["write", "get"])

    def test_stale_update_binding_performs_zero_writes(self):
        client = Client(page(intended=False))
        result = execute(AdmittedRequest(100, PAGE_ID, "old"), client)
        self.assertEqual(result["status"], "conflict")
        self.assertNotIn("write", client.calls)

    def test_concurrent_page_change_performs_zero_writes(self):
        client = Client(page(intended=False))
        client.stale = True
        result = execute(AdmittedRequest(100, PAGE_ID, REVISION), client)
        self.assertEqual(result["status"], "conflict")
        self.assertNotIn("write", client.calls)

    def test_duplicate_and_incomplete_queries_fail_closed(self):
        for kind in ("duplicate", "more"):
            client = Client(page())
            if kind == "duplicate":
                client.rows.append(page())
            else:
                client.more = True
            result = execute(AdmittedRequest(100), client)
            self.assertEqual(result["status"], "blocked")
            self.assertNotIn("write", client.calls)

    def test_appeared_target_prevents_create(self):
        client = Client()
        client.appear = True
        result = execute(AdmittedRequest(100), client)
        self.assertEqual(result["status"], "conflict")
        self.assertNotIn("write", client.calls)

    def test_missing_update_target_prevents_create(self):
        client = Client()
        result = execute(AdmittedRequest(100, PAGE_ID, REVISION), client)
        self.assertEqual(result["reason_code"], "update-target-missing")
        self.assertNotIn("write", client.calls)

    def test_schema_drift_and_wrong_destination_fail_before_write(self):
        for kind in ("type", "missing", "destination", "archived"):
            client = Client()
            if kind == "type":
                client.schema_value["properties"]["Guardrail"]["type"] = "relation"
            elif kind == "missing":
                del client.schema_value["properties"]["Lesson ID"]
            elif kind == "destination":
                client.schema_value["id"] = PAGE_ID
            else:
                client.schema_value["archived"] = True
            result = execute(AdmittedRequest(100), client)
            self.assertEqual(result["status"], "blocked")
            self.assertNotIn("write", client.calls)

    def test_wrong_parent_and_archived_target_are_refused(self):
        for kind in ("parent", "archived", "title"):
            existing = page()
            if kind == "parent":
                existing["parent"]["data_source_id"] = PAGE_ID
            elif kind == "archived":
                existing["archived"] = True
            else:
                existing["properties"]["Lesson Learned"]["title"] = []
            client = Client(existing)
            result = execute(AdmittedRequest(100), client)
            self.assertEqual(result["status"], "blocked")
            self.assertNotIn("write", client.calls)

    def test_readback_mismatch_and_failure_never_claim_persistence(self):
        for kind in ("mismatch", "failure"):
            client = Client()
            client.readback_mismatch = kind == "mismatch"
            client.fail_readback = kind == "failure"
            result = execute(AdmittedRequest(100), client)
            self.assertEqual(result["status"], "uncertain")
            self.assertFalse(result["readback_verified"])
            self.assertEqual(result["write_attempts"], 1)
            self.assertNotIn("provider private", json.dumps(result))

    def test_create_timeout_is_uncertain_and_never_retried(self):
        client = Client()
        client.raise_mutation = True
        result = execute(AdmittedRequest(100), client)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(client.calls.count("write"), 1)
        self.assertNotIn("credential-class", json.dumps(result))

    def test_update_timeout_is_followed_by_exact_readback(self):
        client = Client(page(intended=False))
        client.raise_mutation = True
        result = execute(AdmittedRequest(100, PAGE_ID, REVISION), client)
        self.assertEqual(result["status"], "persisted")
        self.assertEqual(client.calls[-2:], ["write", "get"])

    def test_receipt_identity_mismatch_stays_uncertain(self):
        client = Client(page(intended=False))
        client.receipt_id = SOURCE_ID
        result = execute(AdmittedRequest(100, PAGE_ID, REVISION), client)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["reason_code"], "write-receipt-target-mismatch")
        self.assertEqual(client.calls[-1], "get")

    def test_non_routine_provider_change_stays_uncertain(self):
        client = Client(page(intended=False))
        client.change_protected = True
        result = execute(AdmittedRequest(100, PAGE_ID, REVISION), client)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["reason_code"], "non-routine-property-changed")

    def test_public_projection_never_includes_raw_properties_or_values(self):
        client = Client(page())
        client.page["properties"]["Private"] = {"rich_text": [{"plain_text": "private student evidence"}]}
        result = execute(AdmittedRequest(100), client)
        value = json.dumps(result)
        self.assertNotIn("private student", value)
        self.assertNotIn("properties", value)
        self.assertNotIn(LESSON["What Happened"], value)


class RunnerTests(unittest.TestCase):
    def test_admission_has_no_provider_import_or_construction(self):
        env = {"GITHUB_EVENT_NAME": CONTEXT["event_name"], "GITHUB_REF": CONTEXT["ref"],
               "GITHUB_WORKFLOW_REF": WORKFLOW_REF, "GITHUB_RUN_ATTEMPT": "1"}
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", env, clear=True):
            root = Path(directory)
            (root / "event.json").write_text(json.dumps(event()))
            with patch("scripts.agent_os_notion_lessons_write.live.LiveLessonsClient", side_effect=AssertionError):
                code = main(["--phase", "admit", "--event", str(root / "event.json"), "--output", str(root / "result.json")])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads((root / "result.json").read_text())["status"], "admitted")

    def test_failed_admission_cannot_construct_secret_bearing_client(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            root = Path(directory)
            (root / "event.json").write_text(json.dumps(event()))
            with patch("scripts.agent_os_notion_lessons_write.live.LiveLessonsClient", side_effect=AssertionError):
                code = main(["--phase", "execute", "--event", str(root / "event.json"), "--output", str(root / "result.json")])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads((root / "result.json").read_text())["write_attempts"], 0)


if __name__ == "__main__":
    unittest.main()
