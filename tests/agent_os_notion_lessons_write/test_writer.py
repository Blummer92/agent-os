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

    def find_create_candidates(self):
        self.calls.append("scan")
        return {"results": deepcopy(self.rows), "has_more": self.more}

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

    def reserve_create(self, request_id):
        # Offline fake accepts any reviewed catalog request. Atomic GitHub
        # create-only semantics are exercised by test_create_reservation.py.
        return None

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
        self.assertEqual((actual.request_id, actual.expected_lesson_id, actual.expected_revision), (UPDATE, "LL-93", REVISION))
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
        self.assertEqual(client.calls, ["binding", "schema", "query", "scan", "query", "scan", "write", "get"])

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

    def test_update_timeout_before_mutation_does_not_claim_persistence(self):
        class UnappliedTimeoutClient(Client):
            def update(self, page_id, intended):
                self.calls.append("write")
                self.sent.append(deepcopy(intended))
                raise TimeoutError("private-before-mutation")

        client = UnappliedTimeoutClient(page())
        before = deepcopy(client.page)
        result = execute(update_request(), client)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["write_attempts"], 1)
        self.assertFalse(result["readback_verified"])
        self.assertEqual(client.page, before)
        self.assertEqual(client.calls[-2:], ["write", "get"])
        self.assertNotIn("private-before-mutation", json.dumps(result))

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


class SemanticDuplicateCreateTests(unittest.TestCase):
    """#3417: a possible duplicate blocks BEFORE the create-once reservation."""

    def test_ll82_continuation_paraphrase_blocks_with_canonical_id(self):
        from scripts.agent_os_notion_lessons_write.catalog import CONTINUATION_CONSUMER_REQUEST_ID
        duplicate = page()
        duplicate["properties"]["Lesson ID"]["unique_id"]["number"] = 82
        title = "Native execution hosts must enforce continuation; emitted continuation metadata alone is insufficient"
        duplicate["properties"]["Lesson Learned"] = _prop("Lesson Learned", title)
        client = Client()
        client.rows = [duplicate]
        # The exact-title lookup is absent, but the bounded scan sees LL-82.
        client.find_exact = lambda _title: {"results": [], "has_more": False}
        result = execute(AdmittedRequest(100, request_id=CONTINUATION_CONSUMER_REQUEST_ID), client)
        self.assertEqual((result["status"], result["reason_code"]),
                         ("blocked", "possible-semantic-duplicate"))
        self.assertEqual(result["duplicate_lesson_ids"], ["LL-82"])
        self.assertEqual(result["write_attempts"], 0)
        self.assertNotIn("write", client.calls)

    def test_unrelated_title_is_not_semantically_blocked(self):
        from scripts.agent_os_notion_lessons_write.writer import _possible_same_lesson
        title = "Connect continuation decisions to an actual host consumer before claiming automatic execution"
        for other in (
            "CKR6 must run in the actual execution path",
            "Host deployment metadata needs privacy redaction",
            "Continuation logs must redact student identifiers before execution",
        ):
            with self.subTest(other=other):
                self.assertFalse(_possible_same_lesson(title, other))

    def test_incomplete_duplicate_scan_blocks_before_reservation(self):
        client = Client()
        client.more = True
        result = execute(AdmittedRequest(100), client)
        self.assertEqual((result["status"], result["reason_code"]),
                         ("blocked", "incomplete-duplicate-scan"))
        self.assertEqual(result["write_attempts"], 0)
        self.assertNotIn("write", client.calls)

    def test_ambiguous_duplicate_identity_blocks_without_mutation(self):
        from scripts.agent_os_notion_lessons_write.catalog import CONTINUATION_CONSUMER_REQUEST_ID
        duplicate = page()
        duplicate["properties"]["Lesson Learned"] = _prop(
            "Lesson Learned",
            "Native execution hosts must enforce continuation; emitted continuation metadata alone is insufficient",
        )
        duplicate["properties"]["Lesson ID"]["unique_id"]["number"] = None
        client = Client()
        client.rows = [duplicate]
        client.find_exact = lambda _title: {"results": [], "has_more": False}
        result = execute(AdmittedRequest(100, request_id=CONTINUATION_CONSUMER_REQUEST_ID), client)
        self.assertEqual((result["status"], result["reason_code"]),
                         ("blocked", "ambiguous-duplicate-scan"))
        self.assertEqual(result["write_attempts"], 0)
        self.assertNotIn("write", client.calls)


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

    def test_event_input_errors_cannot_construct_live_client(self):
        env = {"GITHUB_EVENT_NAME": CONTEXT["event_name"], "GITHUB_REF": CONTEXT["ref"],
               "GITHUB_WORKFLOW_REF": WORKFLOW_REF, "GITHUB_RUN_ATTEMPT": "1"}
        cases = ((b"{broken", "event-invalid-json"), (bytes([255]), "event-invalid-encoding"))
        for raw, reason in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", env, clear=True
            ):
                root = Path(directory)
                (root / "event.json").write_bytes(raw)
                with patch("scripts.agent_os_notion_lessons_write.live.LiveLessonsClient",
                           side_effect=AssertionError("provider must not be constructed")):
                    code = main(["--phase", "execute", "--event", str(root / "event.json"),
                                 "--output", str(root / "result.json")])
                receipt = json.loads((root / "result.json").read_text())
                verify = json.loads((root / "verification.json").read_text())
                self.assertEqual(code, 1)
                self.assertEqual(receipt["status"], "blocked")
                self.assertEqual(receipt["reason_code"], reason)
                self.assertEqual(receipt["write_attempts"], 0)
                self.assertEqual(verify["status"], "unverified")
                self.assertFalse(verify["persisted_state_verified"])

    def test_post_admission_failure_cannot_become_verified_persistence(self):
        env = {"GITHUB_EVENT_NAME": CONTEXT["event_name"], "GITHUB_REF": CONTEXT["ref"],
               "GITHUB_WORKFLOW_REF": WORKFLOW_REF, "GITHUB_RUN_ATTEMPT": "1"}
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", env, clear=True):
            root = Path(directory)
            (root / "event.json").write_text(json.dumps(event()), encoding="utf-8")
            with patch("scripts.agent_os_notion_lessons_write.runner.verify_current_request",
                       side_effect=RuntimeError("private-synthetic-diagnostic")), patch(
                "scripts.agent_os_notion_lessons_write.live.LiveLessonsClient",
                side_effect=AssertionError("client must not be constructed")
            ):
                code = main(["--phase", "execute", "--event", str(root / "event.json"),
                             "--output", str(root / "result.json")])
            receipt = json.loads((root / "result.json").read_text())
            verify = json.loads((root / "verification.json").read_text())
        self.assertEqual(code, 1)
        self.assertEqual(receipt["status"], "blocked")
        self.assertEqual(receipt["request_id"], REQUEST_ID)
        self.assertEqual(receipt["write_attempts"], 0)
        self.assertEqual(receipt["reason_code"], "bounded-request-unavailable")
        self.assertEqual(verify["status"], "unverified")
        self.assertFalse(verify["persisted_state_verified"])
        self.assertNotIn("private-synthetic-diagnostic", json.dumps((receipt, verify)))


    def test_oversized_non_object_and_missing_events_are_bounded(self):
        from scripts.agent_os_notion_lessons_write.admission import MAX_EVENT_BYTES
        env = {"GITHUB_EVENT_NAME": CONTEXT["event_name"], "GITHUB_REF": CONTEXT["ref"],
               "GITHUB_WORKFLOW_REF": WORKFLOW_REF, "GITHUB_RUN_ATTEMPT": "1"}
        cases = (
            (b"x" * (MAX_EVENT_BYTES + 1), "event-byte-bound-exceeded"),
            (b"[1,2,3]", "event-invalid-structure"),
            (b'"hello"', "event-invalid-structure"),
            (None, "event-unreadable"),
        )
        for raw, expected in cases:
            with self.subTest(expected=expected, raw=raw is not None), tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", env, clear=True
            ):
                root = Path(directory)
                event_file = root / "event.json"
                if raw is not None:
                    event_file.write_bytes(raw)
                with patch("scripts.agent_os_notion_lessons_write.live.LiveLessonsClient",
                           side_effect=AssertionError("provider must not be constructed")):
                    code = main(["--phase", "execute", "--event", str(event_file),
                                 "--output", str(root / "result.json")])
                result = json.loads((root / "result.json").read_text())
                verification = json.loads((root / "verification.json").read_text())
                self.assertEqual(code, 1)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["reason_code"], expected)
                self.assertEqual(result["write_attempts"], 0)
                self.assertEqual(verification["status"], "unverified")

    def test_unknown_admission_exception_is_never_a_raw_reason(self):
        env = {"GITHUB_EVENT_NAME": CONTEXT["event_name"], "GITHUB_REF": CONTEXT["ref"],
               "GITHUB_WORKFLOW_REF": WORKFLOW_REF, "GITHUB_RUN_ATTEMPT": "1"}
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", env, clear=True):
            root = Path(directory)
            (root / "event.json").write_text(json.dumps(event()))
            with patch("scripts.agent_os_notion_lessons_write.runner.admit",
                       side_effect=WriteBlocked("private-provider-synthetic-value")):
                code = main(["--phase", "execute", "--event", str(root / "event.json"),
                             "--output", str(root / "result.json")])
            result = json.loads((root / "result.json").read_text())
        self.assertEqual(code, 1)
        self.assertEqual(result["reason_code"], "bounded-request-unavailable")
        self.assertNotIn("private-provider-synthetic-value", json.dumps(result))

    def test_post_admission_write_blocked_never_invokes_verifier(self):
        env = {"GITHUB_EVENT_NAME": CONTEXT["event_name"], "GITHUB_REF": CONTEXT["ref"],
               "GITHUB_WORKFLOW_REF": WORKFLOW_REF, "GITHUB_RUN_ATTEMPT": "1"}
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", env, clear=True):
            root = Path(directory)
            (root / "event.json").write_text(json.dumps(event()))
            with patch("scripts.agent_os_notion_lessons_write.runner.verify_current_request",
                       side_effect=WriteBlocked("canonical-owner-request-changed")), patch(
                "scripts.agent_os_notion_lessons_write.verify_live_write.verify_persisted_write",
                side_effect=AssertionError("verifier must not be called")
            ):
                code = main(["--phase", "execute", "--event", str(root / "event.json"),
                             "--output", str(root / "result.json")])
            result = json.loads((root / "result.json").read_text())
            verification = json.loads((root / "verification.json").read_text())
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["request_id"], REQUEST_ID)
        self.assertEqual(result["reason_code"], "canonical-owner-request-changed")
        self.assertEqual(result["write_attempts"], 0)
        self.assertEqual(verification["status"], "unverified")

    def test_exception_after_writer_entry_is_uncertain_not_zero_attempts(self):
        env = {"GITHUB_EVENT_NAME": CONTEXT["event_name"], "GITHUB_REF": CONTEXT["ref"],
               "GITHUB_WORKFLOW_REF": WORKFLOW_REF, "GITHUB_RUN_ATTEMPT": "1"}
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", env, clear=True):
            root = Path(directory)
            (root / "event.json").write_text(json.dumps(event()))
            with patch("scripts.agent_os_notion_lessons_write.runner.verify_current_request", return_value=None), patch(
                "scripts.agent_os_notion_lessons_write.live.LiveLessonsClient", return_value=Client()
            ), patch("scripts.agent_os_notion_lessons_write.writer.execute",
                     side_effect=RuntimeError("private-after-write")), patch(
                "scripts.agent_os_notion_lessons_write.verify_live_write.verify_persisted_write",
                side_effect=AssertionError("must not verify an uncertain write")
            ):
                code = main(["--phase", "execute", "--event", str(root / "event.json"),
                             "--output", str(root / "result.json")])
            result = json.loads((root / "result.json").read_text())
            verification = json.loads((root / "verification.json").read_text())
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["write_attempts"], 1)
        self.assertFalse(result["readback_verified"])
        self.assertEqual(verification["status"], "unverified")
        self.assertNotIn("private-after-write", json.dumps((result, verification)))

    def test_forged_writer_request_identity_cannot_reach_verifier(self):
        env = {"GITHUB_EVENT_NAME": CONTEXT["event_name"], "GITHUB_REF": CONTEXT["ref"],
               "GITHUB_WORKFLOW_REF": WORKFLOW_REF, "GITHUB_RUN_ATTEMPT": "1"}
        forged = {"status": "persisted", "request_id": "another-registered-id",
                  "write_attempts": 1, "readback_verified": True}
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", env, clear=True):
            root = Path(directory)
            (root / "event.json").write_text(json.dumps(event()))
            with patch("scripts.agent_os_notion_lessons_write.runner.verify_current_request", return_value=None), patch(
                "scripts.agent_os_notion_lessons_write.live.LiveLessonsClient", return_value=Client()
            ), patch("scripts.agent_os_notion_lessons_write.writer.execute", return_value=forged), patch(
                "scripts.agent_os_notion_lessons_write.verify_live_write.verify_persisted_write",
                side_effect=AssertionError("identity mismatch must not reach verifier")
            ):
                code = main(["--phase", "execute", "--event", str(root / "event.json"),
                             "--output", str(root / "result.json")])
            verification = json.loads((root / "verification.json").read_text())
        self.assertEqual(code, 1)
        self.assertEqual(verification["reason_code"], "writer-request-binding-mismatch")



# ---------------------------------------------------------------- independent live-write verification

from scripts.agent_os_notion_lessons_write.verify_live_write import verify_persisted_write


class LostCreateReceiptRecoveryTests(unittest.TestCase):
    """An uncertain POST is never replayed; only exact state can be recovered."""

    class ReconciledClient(Client):
        # A real Notion data-source query can observe the newly created page
        # after the POST succeeded but its transport response was lost.
        def find_exact(self, title):
            if "write" in self.calls:
                self.rows = [deepcopy(self.page)]
            return super().find_exact(title)

    def test_lost_response_recovers_exact_page_without_second_post(self):
        client = self.ReconciledClient()
        client.raise_mutation = True
        outcome = execute(AdmittedRequest(100), client)
        self.assertEqual(outcome["status"], "persisted")
        self.assertEqual(outcome["reason_code"], "exact-canonical-readback-confirmed")
        self.assertTrue(outcome["create_receipt_recovered"])
        self.assertEqual(outcome["write_attempts"], 1)
        self.assertTrue(outcome["readback_verified"])
        self.assertEqual(outcome["page_id"], PAGE_ID)
        self.assertEqual(client.calls.count("write"), 1)
        self.assertEqual(client.calls[-3:], ["write", "query", "get"])
        self.assertNotIn("credential-class", json.dumps(outcome))

        # A second observer checks exact canonical current state, never writes.
        after = len(client.calls)
        verified = verify_persisted_write(
            outcome, lambda _request_id: client, expected_request_id=REQUEST_ID
        )
        self.assertEqual(verified["status"], "verified-current-state")
        self.assertTrue(verified["persisted_state_verified"])
        self.assertFalse(verified["write_causality_established"])
        self.assertEqual(client.calls[after:], ["binding", "get"])

        # A fresh owner attempt reconciles, rather than creating another row.
        client.raise_mutation = False
        again = execute(AdmittedRequest(101), client)
        self.assertEqual(again["status"], "unchanged")
        self.assertEqual(again["write_attempts"], 0)
        self.assertEqual(client.calls.count("write"), 1)

    def test_lost_response_without_visible_page_stays_uncertain(self):
        client = Client()
        client.raise_mutation = True
        outcome = execute(AdmittedRequest(100), client)
        self.assertEqual(outcome["status"], "uncertain")
        self.assertEqual(outcome["write_attempts"], 1)
        self.assertFalse(outcome["readback_verified"])
        self.assertIsNone(outcome["page_id"])
        self.assertEqual(outcome["recovery_reason"], "recovery-not-visible")
        self.assertNotIn("create_receipt_recovered", outcome)
        self.assertEqual(client.calls.count("write"), 1)
        self.assertEqual(client.calls[-2:], ["write", "query"])

    def test_ambiguous_or_incomplete_recovery_never_claims_success(self):
        for case in ("duplicate", "has_more", "wrong_identity", "query_failure"):
            class BadRecovery(self.ReconciledClient):
                def find_exact(self, title):
                    if "write" in self.calls and case == "query_failure":
                        self.calls.append("query")
                        raise TimeoutError("private-notion-query")
                    reply = super().find_exact(title)
                    if "write" in self.calls:
                        if case == "duplicate":
                            reply["results"].append(deepcopy(reply["results"][0]))
                        elif case == "has_more":
                            reply["has_more"] = True
                        elif case == "wrong_identity":
                            reply["results"][0]["parent"]["data_source_id"] = PAGE_ID
                    return reply

            with self.subTest(case=case):
                client = BadRecovery()
                client.raise_mutation = True
                outcome = execute(AdmittedRequest(100), client)
                self.assertEqual(outcome["status"], "uncertain")
                self.assertEqual(outcome["write_attempts"], 1)
                self.assertFalse(outcome["readback_verified"])
                self.assertNotIn("create_receipt_recovered", outcome)
                self.assertEqual(outcome["recovery_reason"], {
                    "duplicate": "recovery-ambiguous",
                    "has_more": "recovery-incomplete",
                    "wrong_identity": "recovery-identity-invalid",
                    "query_failure": "recovery-unavailable",
                }[case])
                self.assertEqual(client.calls.count("write"), 1)
                self.assertNotIn("private-notion-query", json.dumps(outcome))

    def test_recovered_page_with_different_content_is_not_persisted(self):
        client = self.ReconciledClient()
        client.raise_mutation = True
        client.readback_mismatch = True
        outcome = execute(AdmittedRequest(100), client)
        self.assertEqual(outcome["status"], "uncertain")
        self.assertEqual(outcome["reason_code"], "canonical-readback-mismatch")
        self.assertTrue(outcome["create_receipt_recovered"])
        self.assertFalse(outcome["readback_verified"])
        self.assertEqual(client.calls.count("write"), 1)

    def test_second_read_failure_after_recovery_is_not_success(self):
        client = self.ReconciledClient()
        client.raise_mutation = True
        client.fail_readback = True
        outcome = execute(AdmittedRequest(100), client)
        self.assertEqual(outcome["status"], "uncertain")
        self.assertFalse(outcome["readback_verified"])
        self.assertEqual(outcome["write_attempts"], 1)
        self.assertEqual(client.calls.count("write"), 1)

    def test_malformed_create_receipt_reconciles_only_if_state_matches(self):
        class MalformedReceipt(self.ReconciledClient):
            def create(self, intended):
                self.raise_mutation = False
                super().create(intended)
                return {}

        client = MalformedReceipt()
        outcome = execute(AdmittedRequest(100), client)
        self.assertEqual(outcome["status"], "persisted")
        self.assertTrue(outcome["create_receipt_recovered"])
        self.assertEqual(client.calls.count("write"), 1)


class ClaudeDurabilityQATests(unittest.TestCase):
    """Claude #4101 F3/F4/F7: safety, provenance, stable updates."""

    def test_foreign_activated_page_cannot_be_claimed_as_recovered_create(self):
        class ForeignActivated(Client):
            def create(self, intended):
                self.calls.append("write")
                raise TimeoutError("private-transport-after-no-commit")

            def find_exact(self, title):
                self.calls.append("query")
                if "write" not in self.calls:
                    return {"results": [], "has_more": False}
                self.page = page()
                self.page["properties"]["Status"] = {
                    "type": "select", "select": {"name": "Applied"},
                }
                self.page["properties"]["Surface Before Work?"] = {
                    "type": "checkbox", "checkbox": True,
                }
                return {"results": [deepcopy(self.page)], "has_more": False}

        client = ForeignActivated()
        outcome = execute(AdmittedRequest(100), client)
        self.assertEqual(outcome["status"], "uncertain")
        self.assertEqual(outcome["reason_code"], "protected-field-present-after-create")
        self.assertTrue(outcome["create_receipt_recovered"])
        self.assertFalse(outcome["readback_verified"])
        self.assertEqual(client.calls.count("write"), 1)

    def test_receipted_create_with_activated_protected_fields_is_uncertain(self):
        class ActivationByAutomation(Client):
            def create(self, intended):
                result = super().create(intended)
                self.page["properties"]["Surface Before Work?"]["checkbox"] = True
                return result

        outcome = execute(AdmittedRequest(100), ActivationByAutomation())
        self.assertEqual(outcome["status"], "uncertain")
        self.assertEqual(outcome["reason_code"], "protected-field-present-after-create")

    def test_status_new_default_is_nonactivated_with_surface_false(self):
        class NewByDefault(Client):
            def create(self, intended):
                result = super().create(intended)
                self.page["properties"]["Status"] = {
                    "type": "select", "select": {"name": "New"},
                }
                return result

        outcome = execute(AdmittedRequest(100), NewByDefault())
        self.assertEqual(outcome["status"], "persisted")
        self.assertTrue(outcome["readback_verified"])
        self.assertFalse(outcome["activation_prerequisites"]["required_fields_present"])

    def test_update_ignores_volatile_provider_request_id_but_checks_real_state(self):
        class RequestTaggedPages(Client):
            def get_page(self, page_id):
                item = super().get_page(page_id)
                item["request_id"] = f"provider-request-{self.reads}"
                return item

        client = RequestTaggedPages(page())
        outcome = execute(update_request(), client)
        self.assertEqual(outcome["status"], "persisted")
        self.assertEqual(outcome["write_attempts"], 1)
        self.assertEqual(client.calls.count("write"), 1)

    def test_update_timeout_records_recovered_receipt_without_claiming_causality(self):
        client = Client(page())
        client.raise_mutation = True
        outcome = execute(update_request(), client)
        self.assertEqual(outcome["status"], "persisted")
        self.assertIs(outcome["update_receipt_recovered"], True)
        self.assertEqual(client.calls.count("write"), 1)

    def test_runner_persists_uncertain_receipt_before_abnormal_termination(self):
        class AbruptWrite(Client):
            def create(self, intended):
                self.calls.append("write")
                raise KeyboardInterrupt("simulated abrupt process interruption")

        from scripts.agent_os_notion_lessons_write.runner import main

        env = {"GITHUB_EVENT_NAME": CONTEXT["event_name"],
               "GITHUB_REF": CONTEXT["ref"],
               "GITHUB_WORKFLOW_REF": WORKFLOW_REF,
               "GITHUB_RUN_ATTEMPT": "1"}
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", env, clear=True):
            root = Path(folder)
            (root / "event.json").write_text(json.dumps(event()))
            with patch(
                "scripts.agent_os_notion_lessons_write.live.LiveLessonsClient",
                return_value=AbruptWrite(),
            ), patch(
                "scripts.agent_os_notion_lessons_write.runner.verify_current_request",
                return_value=None,
            ), self.assertRaises(KeyboardInterrupt):
                main(["--phase", "execute", "--event", str(root / "event.json"),
                      "--output", str(root / "result.json")])
            receipt = json.loads((root / "result.json").read_text())
            self.assertEqual(receipt["status"], "uncertain")
            self.assertEqual(receipt["reason_code"], "execution-incomplete")
            self.assertEqual(receipt["write_attempts"], 1)
            self.assertFalse(receipt["readback_verified"])


class IndependentPersistedWriteTests(unittest.TestCase):
    def test_second_canonical_get_confirms_state_after_writer_attempt(self):
        client = Client()
        written = execute(AdmittedRequest(100), client)
        before = len(client.calls)
        verified = verify_persisted_write(written, lambda request_id: client)
        self.assertEqual(written["status"], "persisted")
        self.assertEqual(verified["status"], "verified-current-state")
        self.assertTrue(verified["independent_readback_verified"])
        self.assertTrue(verified["persisted_state_verified"])
        self.assertFalse(verified["verification_write_performed"])
        self.assertEqual(client.calls[before:], ["binding", "get"])

    def test_unchanged_is_not_misreported_as_a_new_write(self):
        client = Client(page())
        receipt = execute(AdmittedRequest(100), client)
        factories = []
        outcome = verify_persisted_write(receipt, lambda request_id: factories.append(request_id))
        self.assertEqual(outcome["status"], "no-new-write")
        self.assertFalse(outcome["persisted_state_verified"])
        self.assertEqual(factories, [])
        self.assertNotIn("write", client.calls)

    def test_no_verification_from_failure_or_fabricated_writer_success(self):
        invalid = (
            None, {}, {"status": "uncertain", "write_attempts": 1},
            {"status": "persisted", "write_attempts": 0, "readback_verified": True},
            {"status": "persisted", "write_attempts": 1, "readback_verified": False},
            {"status": "unchanged", "write_attempts": 1, "readback_verified": True},
        )
        for receipt in invalid:
            with self.subTest(receipt=receipt):
                called = []
                outcome = verify_persisted_write(receipt, lambda request_id: called.append(request_id))
                self.assertEqual(outcome["status"], "unverified")
                self.assertFalse(outcome["persisted_state_verified"])
                self.assertEqual(called, [])

    def test_exact_page_content_revision_identity_and_destination_are_checked(self):
        client = Client()
        receipt = execute(AdmittedRequest(100), client)
        cases = ("content", "revision", "lesson", "parent", "page")
        for case in cases:
            other = Client(deepcopy(client.page))
            altered = deepcopy(receipt)
            if case == "content":
                other.page["properties"]["Guardrail"]["rich_text"] = []
            elif case == "revision":
                other.page["last_edited_time"] = "2026-10-08T22:00:00.000Z"
            elif case == "lesson":
                other.page["properties"]["Lesson ID"]["unique_id"]["number"] = 94
            elif case == "parent":
                other.page["parent"]["data_source_id"] = PAGE_ID
            elif case == "page":
                altered["page_id"] = SOURCE_ID
            with self.subTest(case=case):
                outcome = verify_persisted_write(altered, lambda _request_id: other)
                self.assertEqual(outcome["status"], "unverified")
                self.assertFalse(outcome["persisted_state_verified"])
                self.assertTrue(outcome["read_performed"])

    def test_timeout_and_sensitive_provider_error_fail_closed(self):
        client = Client()
        receipt = execute(AdmittedRequest(100), client)
        class FailingReader:
            def verify_binding(self):
                return SOURCE_ID
            def get_page(self, _page_id):
                raise TimeoutError("private-synthetic-diagnostic")
        outcome = verify_persisted_write(receipt, lambda _: FailingReader())
        self.assertEqual(outcome["status"], "unverified")
        self.assertEqual(outcome["reason_code"], "independent-read-unavailable")
        self.assertNotIn("private-synthetic", json.dumps(outcome))
        self.assertFalse(outcome["verification_write_performed"])

    def test_only_registered_catalog_requests_can_be_independently_verified(self):
        client = Client()
        receipt = execute(AdmittedRequest(100), client)
        receipt["request_id"] = "unregistered-lesson"
        called = []
        outcome = verify_persisted_write(receipt, lambda request_id: called.append(request_id))
        self.assertEqual(outcome["status"], "unverified")
        self.assertEqual(called, [])

    def test_unchanged_receipt_is_also_bound_to_admitted_request(self):
        unchanged = execute(AdmittedRequest(101), Client(page()))
        self.assertEqual(unchanged["status"], "unchanged")
        calls = []
        outcome = verify_persisted_write(
            unchanged, lambda rid: calls.append(rid), expected_request_id="different-reviewed-request"
        )
        self.assertEqual(outcome["status"], "unverified")
        self.assertEqual(outcome["reason_code"], "writer-request-binding-mismatch")
        self.assertEqual(calls, [])

    def test_receipt_counters_reject_boolean_not_integers(self):
        client = Client()
        receipt = execute(AdmittedRequest(100), client)
        receipt["write_attempts"] = True
        called = []
        outcome = verify_persisted_write(receipt, lambda rid: called.append(rid))
        self.assertEqual(outcome["status"], "unverified")
        self.assertEqual(called, [])
        unchanged = execute(AdmittedRequest(101), Client(page()))
        unchanged["write_attempts"] = False
        second_called = []
        outcome = verify_persisted_write(unchanged, lambda rid: second_called.append(rid))
        self.assertEqual(outcome["status"], "unverified")
        self.assertEqual(second_called, [])

    def test_matching_preexisting_page_cannot_prove_this_run_wrote(self):
        client = Client(page())
        receipt = execute(AdmittedRequest(100), client)
        self.assertEqual(receipt["status"], "unchanged")
        self.assertNotIn("write", client.calls)
        forged = {**receipt, "status": "persisted", "write_attempts": 1}
        outcome = verify_persisted_write(forged, lambda _rid: client)
        self.assertEqual(outcome["status"], "verified-current-state")
        self.assertTrue(outcome["persisted_state_verified"])
        self.assertFalse(outcome["write_causality_established"])
        self.assertNotIn("write_verified", outcome)
        self.assertNotIn("write", client.calls)

    def test_receipt_must_match_exact_admitted_catalog_request(self):
        client = Client()
        receipt = execute(AdmittedRequest(100), client)
        called = []
        outcome = verify_persisted_write(
            receipt, lambda rid: called.append(rid), expected_request_id="different-reviewed-request"
        )
        self.assertEqual(outcome["reason_code"], "writer-request-binding-mismatch")
        self.assertEqual(called, [])


class RunnerIndependentReadbackTests(unittest.TestCase):
    def _execute(self, client):
        env = {"GITHUB_EVENT_NAME": CONTEXT["event_name"], "GITHUB_REF": CONTEXT["ref"],
               "GITHUB_WORKFLOW_REF": WORKFLOW_REF, "GITHUB_RUN_ATTEMPT": "1"}
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", env, clear=True):
            root = Path(directory)
            (root / "event.json").write_text(json.dumps(event()))
            with patch("scripts.agent_os_notion_lessons_write.live.LiveLessonsClient", return_value=client), patch(
                "scripts.agent_os_notion_lessons_write.runner.verify_current_request", return_value=None
            ):
                status = main(["--phase", "execute", "--event", str(root / "event.json"),
                               "--output", str(root / "result.json")])
            result = json.loads((root / "result.json").read_text())
            verification = json.loads((root / "verification.json").read_text())
        return status, result, verification

    def test_single_execute_run_writes_once_then_reads_twice(self):
        client = Client()
        status, result, verification = self._execute(client)
        self.assertEqual(status, 0)
        self.assertEqual(result["status"], "persisted")
        self.assertEqual(verification["status"], "verified-current-state")
        self.assertEqual(client.calls.count("write"), 1)
        self.assertEqual(client.calls.count("get"), 2)

    def test_lost_create_response_completes_only_after_two_exact_page_reads(self):
        client = LostCreateReceiptRecoveryTests.ReconciledClient()
        client.raise_mutation = True
        code, writer_result, independent = self._execute(client)
        self.assertEqual(code, 0)
        self.assertEqual(writer_result["status"], "persisted")
        self.assertTrue(writer_result["create_receipt_recovered"])
        self.assertEqual(writer_result["write_attempts"], 1)
        self.assertTrue(independent["persisted_state_verified"])
        self.assertFalse(independent["write_causality_established"])
        self.assertEqual(client.calls.count("write"), 1)
        self.assertEqual(client.calls.count("get"), 2)

    def test_lost_create_response_with_failed_independent_check_exits_nonzero(self):
        class IndependentDrift(LostCreateReceiptRecoveryTests.ReconciledClient):
            def get_page(self, page_id):
                value = super().get_page(page_id)
                if self.reads > 1:
                    value["last_edited_time"] = "2026-10-09T00:00:00.000Z"
                return value

        client = IndependentDrift()
        client.raise_mutation = True
        code, writer_result, independent = self._execute(client)
        self.assertEqual(code, 1)
        self.assertEqual(writer_result["status"], "persisted")
        self.assertTrue(writer_result["create_receipt_recovered"])
        self.assertFalse(independent["persisted_state_verified"])
        self.assertEqual(independent["reason_code"], "independent-revision-mismatch")
        self.assertEqual(client.calls.count("write"), 1)

    def test_independent_stale_revision_fails_the_runner_without_retry(self):
        class DriftClient(Client):
            def get_page(self, page_id):
                data = super().get_page(page_id)
                if self.reads > 1:
                    data["last_edited_time"] = "2026-10-09T00:00:00.000Z"
                return data
        client = DriftClient()
        status, result, verification = self._execute(client)
        self.assertEqual(status, 1)
        self.assertEqual(result["status"], "persisted")
        self.assertEqual(verification["reason_code"], "independent-revision-mismatch")
        self.assertEqual(client.calls.count("write"), 1)
        self.assertFalse(verification["persisted_state_verified"])


if __name__ == "__main__":
    unittest.main()
