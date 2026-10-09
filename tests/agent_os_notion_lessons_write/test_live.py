"""Finite REST shapes, canonical reader regression, and owner-request currentness."""
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
from scripts.agent_os_notion_lessons_write.catalog import REQUEST_ID, WRITABLE_TYPES
from scripts.agent_os_notion_lessons_write.admission import verify_current_request
from scripts.agent_os_notion_lessons_write.live import LiveLessonsClient, _NoRedirect
from scripts.agent_os_notion_lessons_write.writer import properties

WORKFLOW_PATH = ".github/workflows/agent-os-notion-lessons-write.yml"
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
        client.request_id = REQUEST_ID
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

    def test_lesson_id_query_is_bounded_to_reviewed_target(self):
        from scripts.agent_os_notion_lessons_write.catalog import LL93_METADATA_REQUEST_ID
        client = self.client()
        with self.assertRaisesRegex(WriteBlocked, "finite-lesson-identity"):
            client.find_lesson(93)  # create entry has no Lesson ID target
        client.request_id = LL93_METADATA_REQUEST_ID
        with self.assertRaisesRegex(WriteBlocked, "finite-lesson-identity"):
            client.find_lesson(94)
        with patch.object(LiveLessonsClient, "_read", return_value={"results": []}) as read:
            client.find_lesson(93)
        self.assertEqual(read.call_args.kwargs["filter"], {"property": "Lesson ID", "unique_id": {"equals": 93}})

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
    def comment(self, e, number):
        return {**e["comment"], "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/{number}"}

    def test_current_owner_comment_is_read_back_before_write(self):
        # #3417: the closed #3305 lifecycle no longer gates the request surface.
        for number, state in ((3417, "open"), (3305, "closed")):
            e = event(number=number, state=state)
            request = AdmittedRequest(100, issue_number=number)
            with self.subTest(number=number), patch(
                    "scripts.agent_os_notion_lessons_write.admission._get",
                    side_effect=[e["issue"], self.comment(e, number)]) as get:
                verify_current_request(e, request, context=CONTEXT)
            self.assertEqual([call.args[0] for call in get.call_args_list],
                             [f"/issues/{number}", "/issues/comments/100"])

    def test_edited_moved_or_pr_current_comment_refuses(self):
        e = event()
        request = AdmittedRequest(100, issue_number=3417)
        for kind in ("edited", "moved", "pull_request"):
            issue, value = deepcopy(e["issue"]), self.comment(e, 3417)
            if kind == "edited":
                value["updated_at"] = "changed"
            elif kind == "moved":
                value["issue_url"] = f"https://api.github.com/repos/{REPOSITORY}/issues/3305"
            else:
                issue["pull_request"] = {}
            with self.subTest(kind=kind), patch(
                    "scripts.agent_os_notion_lessons_write.admission._get",
                    side_effect=[issue, value]), self.assertRaises(WriteBlocked):
                verify_current_request(e, request, context=CONTEXT)


class WorkflowTests(unittest.TestCase):
    def test_workflow_exposes_existing_secret_only_after_admission(self):
        import yaml
        value = yaml.safe_load((ROOT / WORKFLOW_PATH).read_text())
        self.assertEqual(value["permissions"], {"contents": "read"})
        self.assertFalse(value["concurrency"]["cancel-in-progress"])
        triggers = value.get("on", value.get(True))
        self.assertEqual(set(triggers), {"issue_comment"})
        self.assertEqual(triggers["issue_comment"]["types"], ["created"])
        steps = value["jobs"]["lessons_write"]["steps"]
        secrets = [step for step in steps if "NOTION_TOKEN" in step.get("env", {})]
        self.assertEqual(len(secrets), 1)
        self.assertGreater(steps.index(secrets[0]), 2)
        self.assertEqual(secrets[0]["env"]["NOTION_TOKEN"], "${{ secrets.NOTION_TOKEN }}")
        self.assertEqual(secrets[0]["env"]["AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID"], "${{ vars.AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID }}")
        self.assertNotIn("continue-on-error", str(steps))

    def test_workflow_is_not_bound_to_one_implementation_issue(self):
        import yaml
        value = yaml.safe_load((ROOT / WORKFLOW_PATH).read_text())
        condition = value["jobs"]["lessons_write"]["if"]
        self.assertNotIn("issue.number", condition)
        self.assertIn("github.event.issue.pull_request == null", condition)
        self.assertIn("github.event.comment.user.id == 32861845", condition)


if __name__ == "__main__":
    unittest.main()
