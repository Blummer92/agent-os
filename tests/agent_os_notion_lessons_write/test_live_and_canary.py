"""Finite REST shapes, canonical reader regression, and one-shot canary gates."""
from copy import deepcopy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.request

from tests.agent_os_notion_lessons_write.test_writer import Client, CONTEXT, PAGE_ID, REVISION, SOURCE_ID, event, page
from scripts.agent_os_notion_lessons_write.admission import (
    AdmittedRequest, OWNER_ID, REPOSITORY, REPOSITORY_ID, WriteBlocked,
)
from scripts.agent_os_notion_lessons_write.canary import (
    AUTH_COMMENT_ID, AUTH_MARKER, BRANCH, WORKFLOW_PATH, admit_canary, execute_canary,
)
from scripts.agent_os_notion_lessons_write.catalog import REQUEST_ID, WRITABLE_TYPES
from scripts.agent_os_notion_lessons_write.currentness import verify_current_request
from scripts.agent_os_notion_lessons_write.live import LiveLessonsClient, _NoRedirect
from scripts.agent_os_notion_lessons_write.writer import properties

SHA = "a" * 40
ROOT = Path(__file__).resolve().parents[2]


class LiveTests(unittest.TestCase):
    def test_missing_existing_credential_refuses_without_network(self):
        with patch.dict("os.environ", {}, clear=True), patch("urllib.request.build_opener", side_effect=AssertionError):
            with self.assertRaisesRegex(WriteBlocked, "credential-unavailable"):
                LiveLessonsClient()

    def test_missing_source_refuses_without_network(self):
        with patch.dict("os.environ", {"NOTION_TOKEN": "test-only"}, clear=True):
            with self.assertRaisesRegex(WriteBlocked, "invalid-notion-identity"):
                LiveLessonsClient()

    def client(self):
        client = object.__new__(LiveLessonsClient)
        client.source_id = SOURCE_ID
        client._token = "test-only-not-a-real-credential"
        from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter
        client._reader = NotionReadOnlyAdapter(token="test-only")
        return client

    def test_only_fixed_create_and_update_rest_shapes_are_possible(self):
        class Response(io.BytesIO):
            pass
        class Opener:
            def __init__(self):
                self.requests = []
            def open(self, request, timeout):
                self.requests.append(request)
                return Response(json.dumps({"id": PAGE_ID}).encode())
        client = self.client()
        client._opener = Opener()
        client.create(properties())
        client.update(PAGE_ID, properties())
        create, update = client._opener.requests
        self.assertEqual(create.full_url, "https://api.notion.com/v1/pages")
        self.assertEqual(create.method, "POST")
        self.assertEqual(json.loads(create.data), {"parent": {"type": "data_source_id", "data_source_id": SOURCE_ID}, "properties": properties()})
        self.assertEqual(update.full_url, "https://api.notion.com/v1/pages/" + PAGE_ID)
        self.assertEqual(update.method, "PATCH")
        self.assertEqual(set(json.loads(update.data)), {"properties"})

    def test_governed_fields_schema_and_private_content_refused_at_live_boundary(self):
        client = self.client()
        for key, value in (("Approval", {"checkbox": True}), ("schema", {}), ("What Happened", {"rich_text": [{"text": {"content": "private student details"}}]})):
            intended = properties()
            intended[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(WriteBlocked, "reviewed-narrative"):
                client.create(intended)

    def test_redirects_are_refused(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))

    def test_canonical_binding_anchor_rejects_wrong_existing_source(self):
        client = self.client()
        result = {"lessons_learned": {"data_source_id": PAGE_ID}}
        with patch("scripts.agent_os_notion_read_request.binding_verification.verify_lessons_learned_binding", return_value=result):
            with self.assertRaisesRegex(WriteBlocked, "canonical-lessons-destination-mismatch"):
                client.verify_binding()

    def test_read_adapter_stays_structurally_read_only(self):
        from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter
        from workflow_scheduler.models import Task
        adapter = NotionReadOnlyAdapter(token="test-only")
        self.assertFalse({"create_page", "update_page", "archive_page", "delete_page"} & set(adapter.ACTIONS))
        for action in ("create_page", "update_page"):
            task = Task(id="test", workflow_id="test", type="write", owner="test", action=action, idempotency_key="test", payload={"action": action})
            self.assertEqual(adapter.execute(task)["status"], "failure")

    def test_2283_allowlist_still_refuses_writes(self):
        from scripts.agent_os_notion_read_request.live_executor import build_live_notion_executor_factory
        from scripts.agent_os_notion_read_request.models import NotionReadRequestError
        from scripts.agent_os_notion_read_request.execution import _bounded_read_task_executor
        from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter
        executor = _bounded_read_task_executor(build_live_notion_executor_factory(adapter_factory=lambda: NotionReadOnlyAdapter(token="test-only"))())
        with self.assertRaises(NotionReadRequestError):
            executor({"action": "create_page"})

    def test_ckr6_composition_constructs_read_tasks_only(self):
        import runpy
        # Exercise the immutable canonical module directly: the partial local
        # source mirror need not initialize the unrelated execution-service API.
        resolve_lesson_read_route = runpy.run_path(str(ROOT / "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/lesson_reader_composition.py"))["resolve_lesson_read_route"]
        from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter
        class Reader(NotionReadOnlyAdapter):
            def execute(self, task):
                self.task = task
                return {"status": "success", "output": {"results": []}}
        reader = Reader(token="test-only")
        route = resolve_lesson_read_route(data_source_id=SOURCE_ID, adapter=reader)
        route.execute_read({"page_size": 1})
        self.assertEqual(reader.task.type, "read")
        self.assertEqual(reader.task.action, "query_data_source")


class CurrentnessTests(unittest.TestCase):
    def test_current_owner_comment_is_read_back_before_write(self):
        e = event()
        comment = {**e["comment"], "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/3305"}
        with patch("scripts.agent_os_notion_lessons_write.currentness._get", side_effect=[e["issue"], comment]):
            verify_current_request(e, AdmittedRequest(100), context=CONTEXT)

    def test_closed_or_edited_current_comment_refuses(self):
        e = event()
        comment = {**e["comment"], "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/3305"}
        for kind in ("closed", "edited"):
            issue, value = deepcopy(e["issue"]), deepcopy(comment)
            if kind == "closed":
                issue["state"] = "closed"
            else:
                value["updated_at"] = "changed"
            with patch("scripts.agent_os_notion_lessons_write.currentness._get", side_effect=[issue, value]), self.assertRaises(WriteBlocked):
                verify_current_request(e, AdmittedRequest(100), context=CONTEXT)


class CanaryTests(unittest.TestCase):
    def setup_evidence(self):
        repo = {"id": REPOSITORY_ID, "full_name": REPOSITORY}
        pr = {"number": 999, "state": "open", "draft": True, "merged": False,
              "user": {"id": OWNER_ID, "login": "Blummer92"}, "base": {"ref": "main"},
              "head": {"sha": SHA, "ref": BRANCH, "repo": repo}}
        e = {"action": "opened", "repository": repo, "pull_request": pr}
        binding = {"repository": REPOSITORY, "issue_number": 3305, "branch": BRANCH, "head_sha": SHA,
                   "request_id": REQUEST_ID, "max_write_attempts": 1,
                   "operation": "one-create-or-update-then-canonical-readback", "fields": list(WRITABLE_TYPES)}
        comment = {"user": {"id": OWNER_ID}, "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/3305",
                   "body": "Explicit owner authorization." + AUTH_MARKER + json.dumps(binding)}
        history = {"total_count": 1, "workflow_runs": [{"id": 123, "path": WORKFLOW_PATH, "head_sha": SHA, "run_attempt": 1, "event": "pull_request"}]}
        context = {**CONTEXT, "event_name": "pull_request", "ref": "refs/pull/999/merge",
                   "workflow_ref": f"{REPOSITORY}/{WORKFLOW_PATH}@refs/pull/999/merge", "run_id": "123"}
        return e, [pr, {"state": "open"}, comment, history], context

    def test_exact_bound_first_canary_is_admitted(self):
        e, evidence, context = self.setup_evidence()
        with patch("scripts.agent_os_notion_lessons_write.canary._get", side_effect=evidence):
            self.assertEqual(admit_canary(e, **context), AdmittedRequest(AUTH_COMMENT_ID))

    def test_other_branch_fork_ready_pr_rerun_and_synchronize_are_refused(self):
        for kind in ("branch", "fork", "ready", "rerun", "synchronize"):
            e, evidence, context = self.setup_evidence()
            if kind == "branch":
                e["pull_request"]["head"]["ref"] = "other"
            elif kind == "fork":
                e["pull_request"]["head"]["repo"] = {"id": 1, "full_name": "other/repo"}
            elif kind == "ready":
                e["pull_request"]["draft"] = False
            elif kind == "rerun":
                context["run_attempt"] = "2"
            else:
                e["action"] = "synchronize"
            with self.subTest(kind=kind), patch("scripts.agent_os_notion_lessons_write.canary._get", side_effect=evidence), self.assertRaises(WriteBlocked):
                admit_canary(e, **context)

    def test_missing_or_expanded_authority_and_advanced_head_are_refused(self):
        for kind in ("missing", "expanded", "head", "closed"):
            e, evidence, context = self.setup_evidence()
            if kind == "missing":
                evidence[2]["body"] = "No authorization."
            elif kind == "expanded":
                evidence[2]["body"] = evidence[2]["body"].replace('"max_write_attempts": 1', '"max_write_attempts": 2')
            elif kind == "head":
                evidence[0] = deepcopy(evidence[0])
                evidence[0]["head"]["sha"] = "b" * 40
            else:
                evidence[1]["state"] = "closed"
            with self.subTest(kind=kind), patch("scripts.agent_os_notion_lessons_write.canary._get", side_effect=evidence), self.assertRaises(WriteBlocked):
                admit_canary(e, **context)

    def test_duplicate_or_incomplete_workflow_history_refuses_replay(self):
        for kind in ("duplicate", "incomplete", "wrong-run"):
            e, evidence, context = self.setup_evidence()
            if kind == "duplicate":
                evidence[3]["workflow_runs"].append(deepcopy(evidence[3]["workflow_runs"][0]))
                evidence[3]["total_count"] = 2
            elif kind == "incomplete":
                evidence[3]["total_count"] = 101
            else:
                context["run_id"] = "321"
            with self.subTest(kind=kind), patch("scripts.agent_os_notion_lessons_write.canary._get", side_effect=evidence), self.assertRaises(WriteBlocked):
                admit_canary(e, **context)

    def test_canary_uses_same_writer_for_one_exact_update(self):
        client = Client(page(intended=False))
        result = execute_canary(AdmittedRequest(AUTH_COMMENT_ID), client)
        self.assertEqual(result["status"], "persisted")
        self.assertEqual(client.calls.count("write"), 1)
        self.assertEqual(client.calls[-2:], ["write", "get"])

    def test_canary_duplicate_refuses_before_write(self):
        client = Client(page())
        client.rows.append(page())
        with self.assertRaises(WriteBlocked):
            execute_canary(AdmittedRequest(AUTH_COMMENT_ID), client)
        self.assertNotIn("write", client.calls)


class WorkflowTests(unittest.TestCase):
    def test_workflow_exposes_existing_secret_only_after_admission(self):
        import yaml
        value = yaml.safe_load((ROOT / WORKFLOW_PATH).read_text())
        self.assertEqual(value["permissions"], {"contents": "read"})
        self.assertFalse(value["concurrency"]["cancel-in-progress"])
        triggers = value.get("on", value.get(True))
        self.assertEqual(set(triggers), {"issue_comment", "pull_request"})
        self.assertEqual(triggers["pull_request"]["types"], ["opened"])
        steps = value["jobs"]["lessons_write"]["steps"]
        secrets = [step for step in steps if "NOTION_TOKEN" in step.get("env", {})]
        self.assertEqual(len(secrets), 1)
        self.assertGreater(steps.index(secrets[0]), 2)
        self.assertEqual(secrets[0]["env"]["NOTION_TOKEN"], "${{ secrets.NOTION_TOKEN }}")
        self.assertEqual(secrets[0]["env"]["AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID"], "${{ vars.AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID }}")
        self.assertNotIn("continue-on-error", str(steps))


if __name__ == "__main__":
    unittest.main()
