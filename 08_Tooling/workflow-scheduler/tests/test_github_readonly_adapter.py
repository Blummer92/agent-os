"""Tests for Phase 3A: GitHubReadOnlyAdapter, the first real (but
read-only) external adapter. All network access is mocked via an
injected `http_get` callable -- no live GitHub access required.

Phase 3F migrated this adapter's result shape from success/error/
is_transient to the Phase 3D five-state contract (status/message);
these tests assert the new shape throughout."""

import inspect

import pytest

from workflow_scheduler.adapters import (
    GitHubReadOnlyAdapter,
    GitHubReadOnlyAdapterError,
    resolve_adapter,
)
from workflow_scheduler.adapters import github_readonly_adapter as grao_module
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
        action="read:github",
        idempotency_key=f"key-{task_id}",
        payload=payload or {},
    )
    defaults.update(overrides)
    return Task(**defaults)


class FakeHttpGet:
    """Records calls; returns/raises whatever it's configured with."""

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
    def test_resolve_github_readonly(self):
        adapter = resolve_adapter("github_readonly")
        assert isinstance(adapter, GitHubReadOnlyAdapter)

    def test_registry_still_resolves_fake_and_noop_adapters(self):
        assert resolve_adapter("noop") is not None
        assert resolve_adapter("fake-success") is not None

    def test_unknown_adapter_still_fails_cleanly(self):
        with pytest.raises(ValueError, match="Unknown adapter"):
            resolve_adapter("does-not-exist")


class TestSupportedActionsSucceed:
    def test_get_repo(self):
        http_get = FakeHttpGet(response={
            "full_name": "Blummer92/agent-os",
            "description": "desc",
            "default_branch": "main",
            "stargazers_count": 1,
            "open_issues_count": 2,
            "private": False,
        })
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_repo", "repository_full_name": "Blummer92/agent-os"})

        result = adapter.execute(task)

        assert result["status"] == "success"
        assert "message" in result
        assert "success" not in result
        assert result["output"]["full_name"] == "Blummer92/agent-os"
        assert http_get.calls[0][0] == "https://api.github.com/repos/Blummer92/agent-os"

    def test_get_pr_info(self):
        http_get = FakeHttpGet(response={
            "number": 27,
            "title": "Some PR",
            "state": "open",
            "body": "body text",
            "user": {"login": "someone"},
            "merged": False,
            "created_at": "2026-07-01T00:00:00Z",
            "updated_at": "2026-07-02T00:00:00Z",
        })
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={
            "action": "get_pr_info",
            "repository_full_name": "Blummer92/agent-os",
            "pr_number": 27,
        })

        result = adapter.execute(task)

        assert result["status"] == "success"
        assert result["output"]["number"] == 27
        assert result["output"]["user"] == "someone"
        assert http_get.calls[0][0] == "https://api.github.com/repos/Blummer92/agent-os/pulls/27"

    def test_list_pr_changed_filenames(self):
        http_get = FakeHttpGet(response=[
            {"filename": "a.py"},
            {"filename": "b.py"},
        ])
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={
            "action": "list_pr_changed_filenames",
            "repository_full_name": "Blummer92/agent-os",
            "pr_number": 27,
        })

        result = adapter.execute(task)

        assert result["status"] == "success"
        assert result["output"]["filenames"] == ["a.py", "b.py"]
        assert http_get.calls[0][0] == "https://api.github.com/repos/Blummer92/agent-os/pulls/27/files"

    def test_list_recent_prs(self):
        http_get = FakeHttpGet(response=[
            {"number": 27, "title": "PR 27", "state": "open"},
            {"number": 26, "title": "PR 26", "state": "closed"},
        ])
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "list_recent_prs", "repository_full_name": "Blummer92/agent-os"})

        result = adapter.execute(task)

        assert result["status"] == "success"
        assert len(result["output"]["pull_requests"]) == 2
        assert "state=all" in http_get.calls[0][0]
        assert "per_page=10" in http_get.calls[0][0]

    def test_list_recent_prs_honors_state_and_limit(self):
        http_get = FakeHttpGet(response=[])
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={
            "action": "list_recent_prs",
            "repository_full_name": "Blummer92/agent-os",
            "state": "closed",
            "limit": 5,
        })

        adapter.execute(task)

        assert "state=closed" in http_get.calls[0][0]
        assert "per_page=5" in http_get.calls[0][0]

    def test_get_commit(self):
        http_get = FakeHttpGet(response={
            "sha": "abc123",
            "commit": {"message": "fix bug", "author": {"name": "someone", "date": "2026-07-01T00:00:00Z"}},
        })
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={
            "action": "get_commit",
            "repository_full_name": "Blummer92/agent-os",
            "sha": "abc123",
        })

        result = adapter.execute(task)

        assert result["status"] == "success"
        assert result["output"]["sha"] == "abc123"
        assert result["output"]["message"] == "fix bug"
        assert http_get.calls[0][0] == "https://api.github.com/repos/Blummer92/agent-os/commits/abc123"

    def test_token_sets_authorization_header(self):
        http_get = FakeHttpGet(response={"full_name": "x/y"})
        adapter = GitHubReadOnlyAdapter(token="secret-token", http_get=http_get)
        task = make_task(payload={"action": "get_repo", "repository_full_name": "x/y"})

        adapter.execute(task)

        headers = http_get.calls[0][1]
        assert headers["Authorization"] == "Bearer secret-token"

    def test_no_token_omits_authorization_header(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        http_get = FakeHttpGet(response={"full_name": "x/y"})
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_repo", "repository_full_name": "x/y"})

        adapter.execute(task)

        headers = http_get.calls[0][1]
        assert "Authorization" not in headers


class TestPayloadValidationFailsCleanlyWithoutNetworkCalls:
    def test_missing_action(self):
        http_get = FakeHttpGet(response={"ok": True})
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"repository_full_name": "x/y"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "action" in result["message"]
        assert http_get.calls == []

    def test_unsupported_action(self):
        http_get = FakeHttpGet(response={"ok": True})
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "delete_repo", "repository_full_name": "x/y"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "Unsupported action" in result["message"]
        assert http_get.calls == []

    def test_missing_required_field(self):
        http_get = FakeHttpGet(response={"ok": True})
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_repo"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "repository_full_name" in result["message"]
        assert http_get.calls == []

    def test_invalid_pr_number(self):
        http_get = FakeHttpGet(response={"ok": True})
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={
            "action": "get_pr_info",
            "repository_full_name": "x/y",
            "pr_number": "not-a-number",
        })

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "pr_number" in result["message"]
        assert http_get.calls == []

    def test_missing_pr_number(self):
        http_get = FakeHttpGet(response={"ok": True})
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_pr_info", "repository_full_name": "x/y"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert http_get.calls == []


class TestConnectorFailuresBecomeControlledResults:
    def test_http_get_raising_permanent_becomes_failure(self):
        http_get = FakeHttpGet(exc=GitHubReadOnlyAdapterError("boom", is_transient=False))
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_repo", "repository_full_name": "x/y"})

        result = adapter.execute(task)  # must not raise

        assert result["status"] == "failure"
        assert "boom" in result["message"]

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_5xx_and_429_are_transient_via_real_http_get(self, monkeypatch, status):
        import urllib.error

        def raising_urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, status, "server error", {}, None)

        monkeypatch.setattr(grao_module.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(GitHubReadOnlyAdapterError) as exc_info:
            grao_module._default_http_get("https://api.github.com/x", {}, 10.0)

        assert exc_info.value.is_transient is True

    @pytest.mark.parametrize("status", [404, 401, 403])
    def test_4xx_client_errors_are_not_transient_via_real_http_get(self, monkeypatch, status):
        import urllib.error

        def raising_urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, status, "client error", {}, None)

        monkeypatch.setattr(grao_module.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(GitHubReadOnlyAdapterError) as exc_info:
            grao_module._default_http_get("https://api.github.com/x", {}, 10.0)

        assert exc_info.value.is_transient is False

    def test_url_error_is_transient_via_real_http_get(self, monkeypatch):
        import urllib.error

        def raising_urlopen(request, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(grao_module.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(GitHubReadOnlyAdapterError) as exc_info:
            grao_module._default_http_get("https://api.github.com/x", {}, 10.0)

        assert exc_info.value.is_transient is True

    def test_transient_failure_returns_retryable_with_retry_after(self):
        http_get = FakeHttpGet(exc=GitHubReadOnlyAdapterError("rate limited", is_transient=True))
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_repo", "repository_full_name": "x/y"})

        result = adapter.execute(task)

        assert result["status"] == "retryable"
        assert "retry_after" in result

    def test_retry_after_uses_exponential_backoff_at_retry_count_zero(self):
        http_get = FakeHttpGet(exc=GitHubReadOnlyAdapterError("rate limited", is_transient=True))
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_repo", "repository_full_name": "x/y"}, retry_count=0)

        result = adapter.execute(task)

        assert result["retry_after"] == 5.0

    def test_retry_after_uses_exponential_backoff_at_nonzero_retry_count(self):
        """Proves this isn't a hardcoded flat delay: retry_after must
        grow with task.retry_count, matching RetryManager.compute_delay's
        5.0 * 2**retry_count formula (capped at 300.0)."""
        http_get = FakeHttpGet(exc=GitHubReadOnlyAdapterError("rate limited", is_transient=True))
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_repo", "repository_full_name": "x/y"}, retry_count=3)

        result = adapter.execute(task)

        assert result["retry_after"] == 40.0  # 5.0 * 2**3

    def test_retry_after_is_capped_at_300(self):
        http_get = FakeHttpGet(exc=GitHubReadOnlyAdapterError("rate limited", is_transient=True))
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_repo", "repository_full_name": "x/y"}, retry_count=10)

        result = adapter.execute(task)

        assert result["retry_after"] == 300.0


class TestResultsPassContractValidationAndAreRecognizedAsContractResults:
    @pytest.mark.parametrize(
        "payload",
        [
            {"action": "get_repo", "repository_full_name": "x/y"},
            {"action": "nope"},
            {},
        ],
    )
    def test_result_shape_valid(self, payload):
        http_get = FakeHttpGet(response={"full_name": "x/y"})
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload=payload)

        result = adapter.execute(task)

        assert _validate_adapter_result(result) is None

    def test_success_result_is_a_contract_result(self):
        http_get = FakeHttpGet(response={"full_name": "x/y"})
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        task = make_task(payload={"action": "get_repo", "repository_full_name": "x/y"})

        result = adapter.execute(task)

        assert _is_contract_result(result) is True

    def test_success_result_round_trips_through_executor(self, repository):
        http_get = FakeHttpGet(response={"full_name": "x/y"})
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        executor = make_executor(repository, adapter)
        task = make_task(payload={"action": "get_repo", "repository_full_name": "x/y"})
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is True

    def test_transient_failure_enters_retry_flow_through_executor(self, repository):
        http_get = FakeHttpGet(exc=GitHubReadOnlyAdapterError("rate limited", is_transient=True))
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        executor = make_executor(repository, adapter)
        task = make_task(payload={"action": "get_repo", "repository_full_name": "x/y"})
        repository.create_task(task)

        result = executor.execute(task)  # must not raise

        assert result.status in ("retry_scheduled", "fail")

    def test_permanent_failure_via_executor_does_not_crash(self, repository):
        http_get = FakeHttpGet(response={"ok": True})
        adapter = GitHubReadOnlyAdapter(http_get=http_get)
        executor = make_executor(repository, adapter)
        task = make_task(payload={"action": "unsupported_action"})
        repository.create_task(task)

        result = executor.execute(task)  # must not raise

        assert result.success is False
        assert result.status == "fail"


class TestNoWriteOperationsExposed:
    """Defense-in-depth: assert the module contains no write-verb HTTP
    call anywhere, not just trust the code review."""

    def test_source_contains_no_write_http_verbs(self):
        source = inspect.getsource(grao_module)
        for verb in ("POST", "PATCH", "PUT", "DELETE"):
            assert f'method="{verb}"' not in source
            assert f"method='{verb}'" not in source

    def test_only_one_place_issues_http_requests(self):
        source = inspect.getsource(grao_module)
        assert source.count("urllib.request.Request(") == 1
        assert source.count("urllib.request.urlopen(") == 1

    def test_adapter_has_no_write_public_methods(self):
        write_verbs = ("create", "update", "delete", "merge", "comment", "review", "label", "push", "edit")
        public_methods = [
            name
            for name, _ in inspect.getmembers(GitHubReadOnlyAdapter, predicate=inspect.isfunction)
            if not name.startswith("_")
        ]
        for name in public_methods:
            lowered = name.lower()
            for verb in write_verbs:
                assert verb not in lowered, f"unexpected write-like method name: {name}"

    def test_no_retry_manager_import(self):
        """RetryManager must not be imported into this adapters module --
        importing it would create a circular import with
        execution/executor.py, which already imports TaskAdapter from
        the adapters package. The backoff formula is inlined instead.
        (The docstring legitimately mentions "RetryManager" by name to
        explain this, so only import statements are checked here.)"""
        source = inspect.getsource(grao_module)
        assert "import RetryManager" not in source
        assert "from workflow_scheduler.execution" not in source
        assert "import workflow_scheduler.execution" not in source


class TestFakeAndNoopAdaptersStillWork:
    """Full existing scheduler suite is run separately; this is a light
    smoke check that the registry wiring didn't break existing entries,
    and that noop/fakes still exercise the original (non-contract) shape."""

    def test_fake_success_still_resolves_and_runs(self, repository):
        adapter = resolve_adapter("fake-success")
        executor = make_executor(repository, adapter)
        task = make_task(action="test_action")
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is True

    def test_fake_success_still_uses_legacy_shape(self):
        from workflow_scheduler.adapters import FakeSuccessAdapter

        result = FakeSuccessAdapter().execute(make_task())

        assert "success" in result
        assert _is_contract_result(result) is False
