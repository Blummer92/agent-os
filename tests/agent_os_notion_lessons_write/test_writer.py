"""Offline safety cases for one explicit Lessons Learned create/update (#3305, #3417)."""
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
from scripts.agent_os_notion_lessons_write.catalog import (
    LL93_METADATA_REQUEST_ID, NARRATIVE_TYPES, REQUEST_ID, WRITABLE_TYPES, lesson_for,
)
from scripts.agent_os_notion_lessons_write.runner import main
from scripts.agent_os_notion_lessons_write.writer import execute, properties

LESSON = lesson_for(REQUEST_ID)
COMMAND = COMMAND_PREFIX + REQUEST_ID
UPDATE = LL93_METADATA_REQUEST_ID
SOURCE_ID = "00000000-0000-0000-0000-000000000001"
PAGE_ID = "00000000-0000-0000-0000-000000000002"
REVISION = "2026-10-06T20:00:00.000Z"
UPDATE_COMMAND = f"{COMMAND_PREFIX}{UPDATE} LL-93 {REVISION}"
CONTEXT = dict(event_name="issue_comment", ref="refs/heads/main", workflow_ref=WORKFLOW_REF, run_attempt="1")
OPTIONS = {"Area": ["Governance", "Testing"], "Learning Type": ["Mistake", "Testing lesson"],
           "Applies To": ["Notion", "Drive"]}


def event(body=COMMAND, *, number=3417, state="open"):
    return {"action": "created", "repository": {"full_name": REPOSITORY, "id": REPOSITORY_ID},
            "issue": {"number": number, "state": state},
            "comment": {"id": 100, "body": body, "created_at": REVISION, "updated_at": REVISION,
                        "user": {"id": OWNER_ID, "login": "Blummer92", "type": "User"}}}


def _prop(name, value):
    kind = WRITABLE_TYPES[name]
    if kind in ("title", "rich_text"):
        return {"type": kind, kind: [{"type": "text", "plain_text": value, "text": {"content": value}}]}
    if kind == "select":
        return {"type": "select", "select": None if value is None else {"name": value}}
    if kind == "multi_select":
        return {"type": "multi_select", "multi_select": [{"name": item} for item in value]}
    return {"type": "url", "url": value}


def page(*, intended=True, metadata=None):
    values = dict(LESSON)
    if not intended:
        values["What Happened"] = "Earlier context"
    values.update(metadata or {"Area": None, "Learning Type": None, "Applies To": (), "Source Link": None})
    props = {name: _prop(name, value) for name, value in values.items()}
    props["Owner / Agent"] = {"type": "rich_text", "rich_text": [{"type": "text", "plain_text": "existing owner"}]}
    props["Status"] = {"type": "select", "select": None}
    props["Surface Before Work?"] = {"type": "checkbox", "checkbox": False}
    props["Lesson ID"] = {"type": "unique_id", "unique_id": {"prefix": "LL", "number": 93}}
    return {"id": PAGE_ID, "parent": {"type": "data_source_id", "data_source_id": SOURCE_ID},
            "last_edited_time": REVISION, "properties": props, "archived": False, "in_trash": False}


class Client:
    def __init__(self, existing=None):
        self.page = deepcopy(existing)
        self.rows = [] if existing is None else [deepcopy(existing)]
        self.calls = []
        self.source = SOURCE_ID
        schema = {name: {"type": kind} for name, kind in
                  {**WRITABLE_TYPES, "Lesson ID": "unique_id", "Status": "select"}.items()}
        for name, options in OPTIONS.items():
            schema[name][WRITABLE_TYPES[name]] = {"options": [{"name": item} for item in options]}
        self.schema_value = {"id": SOURCE_ID, "properties": schema}
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
        self.sent = []

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

    def find_lesson(self, number):
        self.calls.append("query-id")
        self.lesson_number = number
        return {"results": deepcopy(self.rows), "has_more": self.more}

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
        self.sent.append(deepcopy(intended))
        self.page = page()
        for name, value in intended.items():
            self.page["properties"][name] = {"type": WRITABLE_TYPES[name], **deepcopy(value)}
        if self.raise_mutation:
            raise TimeoutError("credential-class diagnostic")
        return {"id": self.receipt_id}

    def update(self, page_id, intended):
        self.calls.append("write")
        self.sent.append(deepcopy(intended))
        for name, value in intended.items():
            self.page["properties"][name] = {"type": WRITABLE_TYPES[name], **deepcopy(value)}
        self.page["last_edited_time"] = "2026-10-08T21:00:00.000Z"
        if self.change_protected:
            self.page["properties"]["Status"] = {"type": "select", "select": {"name": "Applied"}}
        if self.raise_mutation:
            raise TimeoutError("credential-class diagnostic")
        return {"id": self.receipt_id}


def update_request(revision=REVISION, lesson_id="LL-93"):
    return AdmittedRequest(100, lesson_id, revision, UPDATE, 3417)


class AdmissionTests(unittest.TestCase):
    def test_owner_create_is_admitted_on_any_ordinary_issue(self):
        # #3417 regression: the request surface no longer depends on #3305.
        for number, state in ((3305, "closed"), (3305, "open"), (3417, "open"), (9999, "closed")):
            with self.subTest(number=number, state=state):
                self.assertEqual(admit(event(number=number, state=state), **CONTEXT),
                                 AdmittedRequest(100, issue_number=number))

    def test_lesson_id_update_is_admitted_only_for_reviewed_target(self):
        actual = admit(event(UPDATE_COMMAND), **CONTEXT)
        self.assertEqual((actual.expected_lesson_id, actual.expected_revision), ("LL-93", REVISION))
        for body in (f"{COMMAND_PREFIX}{UPDATE} LL-94 {REVISION}", f"{COMMAND_PREFIX}{UPDATE}",
                     f"{COMMAND_PREFIX}{UPDATE} {PAGE_ID} {REVISION}", f"{COMMAND} LL-93 {REVISION}"):
            with self.subTest(body=body), self.assertRaises(WriteBlocked):
                admit(event(body), **CONTEXT)

    def test_foreign_or_edited_inputs_are_refused(self):
        cases = [("repository", "id", 123), ("repository", "full_name", "other/repo"),
                 ("issue", "number", 0), ("issue", "number", "3417"),
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
                     f"{COMMAND_PREFIX}{UPDATE} LL-93 invalid-revision", COMMAND + " ; echo token",
                     COMMAND + " Status=Applied", f"{COMMAND_PREFIX}{UPDATE} LL-93 {REVISION} Surface"):
            with self.subTest(body=body), self.assertRaises(WriteBlocked):
                admit(event(body), **CONTEXT)


class WriterTests(unittest.TestCase):
    def test_authorized_create_has_one_write_then_immediate_exact_readback(self):
        client = Client()
        result = execute(AdmittedRequest(100), client)
        self.assertEqual(result["status"], "persisted")
        self.assertTrue(result["readback_verified"])
        self.assertEqual(result["write_attempts"], 1)
        self.assertEqual(result["lesson_id"], "LL-93")
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

    def test_create_entry_never_overwrites_differing_existing_lesson(self):
        client = Client(page(intended=False))
        result = execute(AdmittedRequest(100), client)
        self.assertEqual((result["status"], result["reason_code"]),
                         ("conflict", "existing-lesson-requires-reviewed-update-entry"))
        self.assertEqual(result["page_id"], PAGE_ID)
        self.assertNotIn("write", client.calls)

    def test_lesson_id_update_writes_descriptive_metadata_and_preserves_other_fields(self):
        client = Client(page())
        protected = {name: deepcopy(client.page["properties"][name])
                     for name in ("Owner / Agent", "Status", "Surface Before Work?", *NARRATIVE_TYPES)}
        result = execute(update_request(), client)
        self.assertEqual((result["status"], result["lesson_id"]), ("persisted", "LL-93"))
        self.assertEqual(client.lesson_number, 93)
        self.assertEqual(client.calls, ["binding", "schema", "query-id", "get", "get", "write", "get"])
        self.assertEqual(set(client.sent[0]), {"Area", "Learning Type", "Applies To", "Source Link"})
        for name, value in protected.items():
            self.assertEqual(client.page["properties"][name], value)
        self.assertEqual(result["revision"], "2026-10-08T21:00:00.000Z")

    def test_identical_update_is_unchanged_without_revision_dependence(self):
        metadata = dict(lesson_for(UPDATE))
        client = Client(page(metadata=metadata))
        result = execute(update_request(revision="2020-01-01T00:00:00Z"), client)
        self.assertEqual(result["status"], "unchanged")
        self.assertNotIn("write", client.calls)

    def test_stale_revision_is_refused_with_zero_writes(self):
        client = Client(page())
        result = execute(update_request(revision="2026-10-01T00:00:00.000Z"), client)
        self.assertEqual((result["status"], result["reason_code"]), ("conflict", "stale-revision-refused"))
        self.assertNotIn("write", client.calls)

    def test_concurrent_page_change_performs_zero_writes(self):
        client = Client(page())
        client.stale = True
        result = execute(update_request(), client)
        self.assertEqual((result["status"], result["reason_code"]), ("conflict", "page-changed-before-write"))
        self.assertNotIn("write", client.calls)

    def test_request_target_must_match_reviewed_entry(self):
        for request in (AdmittedRequest(100, "LL-93", REVISION), update_request(lesson_id=None),
                        update_request(lesson_id="LL-94")):
            client = Client(page())
            with self.subTest(request=request):
                result = execute(request, client)
                self.assertEqual(result["reason_code"], "reviewed-target-lesson-mismatch")
                self.assertEqual(client.calls, [])

    def test_wrong_lesson_identity_row_is_refused(self):
        other = page()
        other["properties"]["Lesson ID"]["unique_id"]["number"] = 94
        client = Client(other)
        result = execute(update_request(), client)
        self.assertEqual(result["reason_code"], "query-identity-mismatch")
        self.assertNotIn("write", client.calls)

    def test_missing_update_target_never_creates(self):
        client = Client()
        result = execute(update_request(), client)
        self.assertEqual(result["reason_code"], "update-target-missing")
        self.assertNotIn("write", client.calls)

    def test_descriptive_value_outside_live_options_is_refused(self):
        # Writing an unknown select option would create schema; refuse instead.
        client = Client(page())
        client.schema_value["properties"]["Area"]["select"]["options"] = [{"name": "Testing"}]
        result = execute(update_request(), client)
        self.assertEqual(result["reason_code"], "descriptive-option-not-in-live-schema")
        self.assertNotIn("write", client.calls)

    def test_activation_fields_are_never_sent(self):
        for request_id in (REQUEST_ID, UPDATE):
            sent = properties(request_id)
            self.assertFalse({"Status", "Surface Before Work?"} & set(sent))

    def test_duplicate_and_incomplete_queries_fail_closed(self):
        for kind in ("duplicate", "more"):
            for request in (AdmittedRequest(100), update_request()):
                client = Client(page())
                if kind == "duplicate":
                    client.rows.append(page())
                else:
                    client.more = True
                result = execute(request, client)
                self.assertEqual(result["status"], "blocked")
                self.assertNotIn("write", client.calls)

    def test_appeared_target_prevents_create(self):
        client = Client()
        client.appear = True
        result = execute(AdmittedRequest(100), client)
        self.assertEqual(result["status"], "conflict")
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
        client = Client(page())
        client.raise_mutation = True
        result = execute(update_request(), client)
        self.assertEqual(result["status"], "persisted")
        self.assertEqual(client.calls[-2:], ["write", "get"])

    def test_receipt_identity_mismatch_stays_uncertain(self):
        client = Client(page())
        client.receipt_id = SOURCE_ID
        result = execute(update_request(), client)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["reason_code"], "write-receipt-target-mismatch")
        self.assertEqual(client.calls[-1], "get")

    def test_activation_field_change_during_write_stays_uncertain(self):
        client = Client(page())
        client.change_protected = True
        result = execute(update_request(), client)
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
            (root / "event.json").write_text(json.dumps(event(number=3305, state="closed")))
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
