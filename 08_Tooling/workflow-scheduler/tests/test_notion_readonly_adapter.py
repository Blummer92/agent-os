"""Tests for Phase 3B: NotionReadOnlyAdapter, the second real external
adapter, proving the Phase 2F/3A adapter pattern generalizes to a system
whose read operations aren't all GET. All network access is mocked via
injected HTTP callables -- no live
Notion access required.

Phase 3F migrated this adapter's result shape from success/error/
is_transient to the Phase 3D five-state contract (status/message);
these tests assert the new shape throughout."""

import inspect

import pytest

from workflow_scheduler.adapters import (
    NotionReadOnlyAdapter,
    NotionReadOnlyAdapterError,
    resolve_adapter,
)
from workflow_scheduler.adapters import notion_readonly_adapter as nrao_module
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.execution import Executor
from workflow_scheduler.execution.executor import _is_contract_result, _validate_adapter_result
from workflow_scheduler.models import Task
from workflow_scheduler.repository import SQLiteRepository


def make_task(task_id: str = "task-1", payload=None, **overrides) -> Task:
    defaults = dict(
        id=task_id,
        workflow_id="workflow-1",
        type="read",
        owner="system",
        action="read:notion",
        idempotency_key=f"key-{task_id}",
        payload=payload or {},
    )
    defaults.update(overrides)
    return Task(**defaults)


class FakeHttpGet:
    def __init__(self, response=None, exc: Exception = None):
        self.response = response
        self.exc = exc
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        if self.exc is not None:
            raise self.exc
        return self.response


@pytest.fixture
def repository():
    return SQLiteRepository(":memory:")


def make_executor(repository, adapter, max_workers: int = 1) -> Executor:
    audit_logger = AuditLogger(repository=repository)
    return Executor(adapter=adapter, repository=repository, audit_logger=audit_logger, max_workers=max_workers)


class TestRegistry:
    def test_resolve_notion_readonly(self):
        adapter = resolve_adapter("notion_readonly")
        assert isinstance(adapter, NotionReadOnlyAdapter)

    def test_registry_still_resolves_noop_fake_and_github_readonly_adapters(self):
        assert resolve_adapter("noop") is not None
        assert resolve_adapter("fake-success") is not None
        assert resolve_adapter("github_readonly") is not None

    def test_unknown_adapter_still_fails_cleanly(self):
        with pytest.raises(ValueError, match="Unknown adapter"):
            resolve_adapter("does-not-exist")


class TestSupportedActionsSucceed:
    def test_get_page(self):
        http_get = FakeHttpGet(response={
            "id": "page-1",
            "url": "https://notion.so/page-1",
            "public_url": None,
            "archived": False,
            "properties": {"Name": {"type": "title"}},
            "created_time": "2026-07-01T00:00:00Z",
            "last_edited_time": "2026-07-02T00:00:00Z",
        })
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_page", "page_id": "page-1"})

        result = adapter.execute(task)

        assert result["status"] == "success"
        assert "success" not in result
        assert result["output"]["id"] == "page-1"
        assert result["output"]["public_url"] is None
        assert http_get.calls[0][0] == "https://api.notion.com/v1/pages/page-1"

    def test_get_page_sends_notion_version_header(self):
        http_get = FakeHttpGet(response={"id": "page-1"})
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_page", "page_id": "page-1"})

        adapter.execute(task)

        headers = http_get.calls[0][1]
        assert headers["Notion-Version"] == nrao_module.NOTION_VERSION

    def test_get_block_children(self):
        http_get = FakeHttpGet(response={
            "results": [
                {"id": "block-1", "type": "paragraph", "has_children": False},
                {"id": "block-2", "type": "heading_1", "has_children": True},
            ],
            "has_more": False,
            "next_cursor": None,
        })
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_block_children", "block_id": "block-parent"})

        result = adapter.execute(task)

        assert result["status"] == "success"
        assert len(result["output"]["blocks"]) == 2
        assert result["output"]["blocks"][0]["id"] == "block-1"
        assert http_get.calls[0][0] == "https://api.notion.com/v1/blocks/block-parent/children?page_size=100"

    def test_get_block_children_honors_page_size(self):
        http_get = FakeHttpGet(response={"results": []})
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_block_children", "block_id": "block-parent", "page_size": 5})

        adapter.execute(task)

        assert "page_size=5" in http_get.calls[0][0]

    def test_get_database(self):
        http_get = FakeHttpGet(response={
            "id": "db-1",
            "url": "https://notion.so/db-1",
            "archived": False,
            "title": [{"plain_text": "My "}, {"plain_text": "Database"}],
            "properties": {"Name": {"type": "title"}},
            "created_time": "2026-07-01T00:00:00Z",
            "last_edited_time": "2026-07-02T00:00:00Z",
        })
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_database", "database_id": "db-1"})

        result = adapter.execute(task)

        assert result["status"] == "success"
        assert result["output"]["id"] == "db-1"
        assert result["output"]["title"] == "My Database"
        assert http_get.calls[0][0] == "https://api.notion.com/v1/databases/db-1"

    def test_token_sets_authorization_header(self):
        http_get = FakeHttpGet(response={"id": "page-1"})
        adapter = NotionReadOnlyAdapter(token="secret-token", http_get=http_get)
        task = make_task(payload={"action": "get_page", "page_id": "page-1"})

        adapter.execute(task)

        headers = http_get.calls[0][1]
        assert headers["Authorization"] == "Bearer secret-token"

    def test_no_token_omits_authorization_header(self, monkeypatch):
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        http_get = FakeHttpGet(response={"id": "page-1"})
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_page", "page_id": "page-1"})

        adapter.execute(task)

        headers = http_get.calls[0][1]
        assert "Authorization" not in headers


class TestPayloadValidationFailsCleanlyWithoutNetworkCalls:
    def test_missing_action(self):
        http_get = FakeHttpGet(response={"ok": True})
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"page_id": "page-1"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "action" in result["message"]
        assert http_get.calls == []

    def test_unsupported_action_fails_before_network_call(self):
        http_get = FakeHttpGet(response={"ok": True})
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "create_page", "page_id": "page-1"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "Unsupported action" in result["message"]
        assert http_get.calls == []

    @pytest.mark.parametrize(
        "action",
        ["update_page", "delete_page", "create_database", "update_database", "archive_page", "comment"],
    )
    def test_write_like_action_names_are_all_unsupported(self, action):
        http_get = FakeHttpGet(response={"ok": True})
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": action, "page_id": "page-1", "database_id": "db-1"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert http_get.calls == []

    def test_get_page_missing_page_id(self):
        http_get = FakeHttpGet(response={"ok": True})
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_page"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "page_id" in result["message"]
        assert http_get.calls == []

    def test_get_block_children_missing_block_id(self):
        http_get = FakeHttpGet(response={"ok": True})
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_block_children"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "block_id" in result["message"]
        assert http_get.calls == []

    def test_get_database_missing_database_id(self):
        http_get = FakeHttpGet(response={"ok": True})
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_database"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "database_id" in result["message"]
        assert http_get.calls == []

    def test_retired_query_database_action_is_unsupported(self):
        http_get = FakeHttpGet(response={"ok": True})
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "query_database", "database_id": "db-1"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "Unsupported action" in result["message"]
        assert http_get.calls == []


class TestConnectorFailuresBecomeControlledResults:
    def test_get_raising_permanent_becomes_failure(self):
        http_get = FakeHttpGet(exc=NotionReadOnlyAdapterError("boom", is_transient=False))
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_page", "page_id": "page-1"})

        result = adapter.execute(task)  # must not raise

        assert result["status"] == "failure"
        assert "boom" in result["message"]

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_5xx_and_429_are_transient_via_real_http_get(self, monkeypatch, status):
        import urllib.error

        def raising_urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, status, "server error", {}, None)

        monkeypatch.setattr(nrao_module.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(NotionReadOnlyAdapterError) as exc_info:
            nrao_module._default_http_get("https://api.notion.com/v1/x", {}, 10.0)

        assert exc_info.value.is_transient is True

    @pytest.mark.parametrize("status", [404, 401, 403])
    def test_4xx_client_errors_are_not_transient_via_real_http_get(self, monkeypatch, status):
        import urllib.error

        def raising_urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, status, "client error", {}, None)

        monkeypatch.setattr(nrao_module.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(NotionReadOnlyAdapterError) as exc_info:
            nrao_module._default_http_get("https://api.notion.com/v1/x", {}, 10.0)

        assert exc_info.value.is_transient is False

    def test_url_error_is_transient_via_real_http_get(self, monkeypatch):
        import urllib.error

        def raising_urlopen(request, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(nrao_module.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(NotionReadOnlyAdapterError) as exc_info:
            nrao_module._default_http_get("https://api.notion.com/v1/x", {}, 10.0)

        assert exc_info.value.is_transient is True

    def test_retry_after_uses_exponential_backoff_at_retry_count_zero(self):
        http_get = FakeHttpGet(exc=NotionReadOnlyAdapterError("rate limited", is_transient=True))
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_page", "page_id": "page-1"}, retry_count=0)

        result = adapter.execute(task)

        assert result["retry_after"] == 5.0

    def test_retry_after_uses_exponential_backoff_at_nonzero_retry_count(self):
        """Proves this isn't a hardcoded flat delay: retry_after must
        grow with task.retry_count, matching RetryManager.compute_delay's
        5.0 * 2**retry_count formula (capped at 300.0)."""
        http_get = FakeHttpGet(exc=NotionReadOnlyAdapterError("rate limited", is_transient=True))
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_page", "page_id": "page-1"}, retry_count=2)

        result = adapter.execute(task)

        assert result["retry_after"] == 20.0  # 5.0 * 2**2

    def test_retry_after_is_capped_at_300(self):
        http_get = FakeHttpGet(exc=NotionReadOnlyAdapterError("rate limited", is_transient=True))
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_page", "page_id": "page-1"}, retry_count=10)

        result = adapter.execute(task)

        assert result["retry_after"] == 300.0


class TestResultsPassContractValidationAndAreRecognizedAsContractResults:
    @pytest.mark.parametrize(
        "payload",
        [
            {"action": "get_page", "page_id": "page-1"},
            {"action": "nope"},
            {},
        ],
    )
    def test_result_shape_valid(self, payload):
        http_get = FakeHttpGet(response={"id": "page-1"})
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload=payload)

        result = adapter.execute(task)

        assert _validate_adapter_result(result) is None

    def test_success_result_is_a_contract_result(self):
        http_get = FakeHttpGet(response={"id": "page-1"})
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_page", "page_id": "page-1"})

        result = adapter.execute(task)

        assert _is_contract_result(result) is True

    def test_success_result_round_trips_through_executor(self, repository):
        http_get = FakeHttpGet(response={"id": "page-1"})
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        executor = make_executor(repository, adapter)
        task = make_task(payload={"action": "get_page", "page_id": "page-1"})
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is True

    def test_transient_failure_enters_retry_flow_through_executor(self, repository):
        http_get = FakeHttpGet(exc=NotionReadOnlyAdapterError("rate limited", is_transient=True))
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        executor = make_executor(repository, adapter)
        task = make_task(payload={"action": "get_page", "page_id": "page-1"})
        repository.create_task(task)

        result = executor.execute(task)  # must not raise

        assert result.status in ("retry_scheduled", "fail")

    def test_permanent_failure_via_executor_does_not_crash(self, repository):
        http_get = FakeHttpGet(response={"ok": True})
        adapter = NotionReadOnlyAdapter(http_get=http_get)
        executor = make_executor(repository, adapter)
        task = make_task(payload={"action": "unsupported_action"})
        repository.create_task(task)

        result = executor.execute(task)  # must not raise

        assert result.success is False
        assert result.status == "fail"


class TestNoWriteOperationsExposed:
    """Defense-in-depth: assert the module contains no PATCH/PUT/DELETE
    call anywhere, and exactly one hardcoded POST call site."""

    def test_source_contains_no_patch_put_delete_verbs(self):
        source = inspect.getsource(nrao_module)
        for verb in ("PATCH", "PUT", "DELETE"):
            assert f'method="{verb}"' not in source
            assert f"method='{verb}'" not in source

    def test_source_contains_exactly_one_post_call_site(self):
        source = inspect.getsource(nrao_module)
        assert source.count('method="POST"') == 1

    def test_legacy_database_query_endpoint_is_absent(self):
        source = inspect.getsource(nrao_module)
        assert "/databases/{database_id}/query" not in source
        assert '"query_database"' not in source

    def test_only_two_places_issue_http_requests(self):
        source = inspect.getsource(nrao_module)
        assert source.count("urllib.request.Request(") == 2
        assert source.count("urllib.request.urlopen(") == 2

    def test_adapter_has_no_write_public_methods(self):
        write_verbs = (
            "create", "update", "delete", "archive", "comment", "invite", "share", "restore", "move", "edit",
        )
        public_methods = [
            name
            for name, _ in inspect.getmembers(NotionReadOnlyAdapter, predicate=inspect.isfunction)
            if not name.startswith("_")
        ]
        for name in public_methods:
            lowered = name.lower()
            for verb in write_verbs:
                assert verb not in lowered, f"unexpected write-like method name: {name}"

    def test_actions_dict_contains_no_write_like_action_names(self):
        write_verbs = (
            "create", "update", "delete", "archive", "comment", "invite", "share", "restore", "move", "edit",
        )
        for action_name in NotionReadOnlyAdapter.ACTIONS:
            lowered = action_name.lower()
            for verb in write_verbs:
                assert verb not in lowered, f"unexpected write-like action name: {action_name}"

    def test_no_retry_manager_import(self):
        """RetryManager must not be imported into this adapters module --
        importing it would create a circular import with
        execution/executor.py, which already imports TaskAdapter from
        the adapters package. The backoff formula is inlined instead.
        (The docstring legitimately mentions "RetryManager" by name to
        explain this, so only import statements are checked here.)"""
        source = inspect.getsource(nrao_module)
        assert "import RetryManager" not in source
        assert "from workflow_scheduler.execution" not in source
        assert "import workflow_scheduler.execution" not in source


class TestExistingAdaptersUnaffected:
    def test_fake_success_still_resolves_and_runs(self, repository):
        adapter = resolve_adapter("fake-success")
        executor = make_executor(repository, adapter)
        task = make_task(action="test_action")
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is True

    def test_github_readonly_still_resolves_and_is_unaffected(self):
        from workflow_scheduler.adapters import GitHubReadOnlyAdapter

        adapter = resolve_adapter("github_readonly")
        assert isinstance(adapter, GitHubReadOnlyAdapter)


class TestHttpErrorBodyDiagnostics:
    """#2816 diagnostic hardening: a Notion HTTP error's JSON body carries the
    only provider-side subtype signal (Notion error code / message /
    request_id). The adapter must surface that sanitized detail instead of
    discarding it, while keeping the existing ``Notion API returned HTTP``
    prefix and the transient/failure taxonomy unchanged."""

    @staticmethod
    def _http_error(status: int, reason: str, body: bytes):
        import io
        import urllib.error

        return urllib.error.HTTPError(
            "https://api.notion.com/v1/data_sources/da5cba48/query",
            status,
            reason,
            {},
            io.BytesIO(body),
        )

    def test_notion_json_error_body_survives_in_adapter_message(self):
        import json

        body = json.dumps(
            {
                "object": "error",
                "status": 404,
                "code": "object_not_found",
                "message": "Could not find data source with ID: da5cba48-50fd-4377-9790-8df8f6f2c7dd.",
                "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            }
        ).encode("utf-8")
        exc = self._http_error(404, "Not Found", body)

        with pytest.raises(NotionReadOnlyAdapterError) as exc_info:
            nrao_module._raise_for_http_error(exc, "Notion API")

        message = str(exc_info.value)
        # The existing contracted prefix is preserved (consumers regex on it).
        assert message.startswith("Notion API returned HTTP 404:")
        # The provider subtype signal is no longer discarded.
        assert "object_not_found" in message
        assert "a1b2c3d4-e5f6-7890-abcd-ef1234567890" in message
        # Fail-closed taxonomy is unchanged: 404 stays non-transient.
        assert exc_info.value.is_transient is False

    def test_transient_status_keeps_transient_taxonomy_with_detail(self):
        import json

        body = json.dumps(
            {"object": "error", "status": 503, "code": "service_unavailable", "message": "Service unavailable."}
        ).encode("utf-8")
        exc = self._http_error(503, "Service Unavailable", body)

        with pytest.raises(NotionReadOnlyAdapterError) as exc_info:
            nrao_module._raise_for_http_error(exc, "Notion API")

        assert str(exc_info.value).startswith("Notion API returned HTTP 503:")
        assert "service_unavailable" in str(exc_info.value)
        assert exc_info.value.is_transient is True

    def test_non_json_error_body_keeps_existing_message_shape(self):
        exc = self._http_error(500, "Internal Server Error", b"<html>proxy error</html>")

        with pytest.raises(NotionReadOnlyAdapterError) as exc_info:
            nrao_module._raise_for_http_error(exc, "Notion API")

        assert str(exc_info.value) == "Notion API returned HTTP 500: Internal Server Error"
        assert exc_info.value.is_transient is True

    def test_empty_error_body_keeps_existing_message_shape(self):
        exc = self._http_error(403, "Forbidden", b"")

        with pytest.raises(NotionReadOnlyAdapterError) as exc_info:
            nrao_module._raise_for_http_error(exc, "Notion API")

        assert str(exc_info.value) == "Notion API returned HTTP 403: Forbidden"
        assert exc_info.value.is_transient is False

    def test_error_body_never_carries_authorization_material(self):
        import json

        body = json.dumps(
            {
                "object": "error",
                "status": 401,
                "code": "unauthorized",
                "message": "API token is invalid.",
                "request_id": "r-1",
            }
        ).encode("utf-8")
        headers = {"Authorization": "Bearer secret-token-value", "Notion-Version": "2026-03-11"}
        import io
        import urllib.error

        exc = urllib.error.HTTPError(
            "https://api.notion.com/v1/data_sources/da5cba48/query", 401, "Unauthorized", headers, io.BytesIO(body)
        )

        with pytest.raises(NotionReadOnlyAdapterError) as exc_info:
            nrao_module._raise_for_http_error(exc, "Notion API")

        assert "secret-token-value" not in str(exc_info.value)
        assert "Bearer" not in str(exc_info.value)
