"""Tests for Phase 3E: GitHubPRLabelAdapter, the second write-capable
adapter and the first real adapter to use the Phase 3D five-state
result contract (status/message) instead of the original success/
error/is_transient shape. All network access is mocked via an injected
http_post_label callable -- no live GitHub access or real token
required. Approval-gating tests exercise the full Executor +
StopConditionChecker lifecycle, mirroring the Phase 3C PR comment
adapter's tests."""

import inspect

import pytest

from workflow_scheduler.adapters import (
    GitHubPRLabelAdapter,
    GitHubPRLabelAdapterError,
    resolve_adapter,
)
from workflow_scheduler.adapters import github_pr_label_adapter as gpla_module
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.execution import Executor
from workflow_scheduler.execution.executor import _is_contract_result, _validate_adapter_result
from workflow_scheduler.models import ApprovalDecision, Task, TaskStatus
from workflow_scheduler.repository import SQLiteRepository


def make_task(task_id: str = "task-1", payload=None, **overrides) -> Task:
    defaults = dict(
        id=task_id,
        workflow_id="workflow-1",
        type="write",
        owner="system",
        action="label_pr",
        idempotency_key=f"key-{task_id}",
        payload=payload or {},
    )
    defaults.update(overrides)
    return Task(**defaults)


class FakeHttpPostLabel:
    def __init__(self, response=None, exc: Exception = None):
        self.response = response
        self.exc = exc
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body, timeout))
        if self.exc is not None:
            raise self.exc
        return self.response


@pytest.fixture
def repository():
    return SQLiteRepository(":memory:")


def make_executor(repository, adapter, max_workers: int = 1) -> Executor:
    audit_logger = AuditLogger(repository=repository)
    return Executor(adapter=adapter, repository=repository, audit_logger=audit_logger, max_workers=max_workers)


VALID_PAYLOAD = {
    "action": "add_pr_label",
    "repository_full_name": "Blummer92/agent-os",
    "pr_number": 31,
    "label": "automated-status",
}


class TestRegistry:
    def test_resolve_github_pr_label(self):
        adapter = resolve_adapter("github_pr_label")
        assert isinstance(adapter, GitHubPRLabelAdapter)

    def test_unknown_adapter_still_fails_cleanly(self):
        with pytest.raises(ValueError, match="Unknown adapter"):
            resolve_adapter("does-not-exist")


class TestSuccessfulWriteUsesContractResult:
    def test_add_pr_label_succeeds_with_contract_shape(self):
        http_post = FakeHttpPostLabel(response=[{"name": "automated-status"}, {"name": "bug"}])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD))

        result = adapter.execute(task)

        assert result["status"] == "success"
        assert "message" in result
        assert "success" not in result
        assert result["output"]["labels"] == ["automated-status", "bug"]
        assert http_post.calls[0][0] == "https://api.github.com/repos/Blummer92/agent-os/issues/31/labels"
        assert http_post.calls[0][2] == {"labels": ["automated-status"]}

    def test_result_is_recognized_as_a_contract_result(self):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD))

        result = adapter.execute(task)

        assert _is_contract_result(result) is True

    def test_token_sets_authorization_header(self):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(token="secret-token", http_post_label=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD))

        adapter.execute(task)

        headers = http_post.calls[0][1]
        assert headers["Authorization"] == "Bearer secret-token"

    def test_no_token_omits_authorization_header(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD))

        adapter.execute(task)

        headers = http_post.calls[0][1]
        assert "Authorization" not in headers


class TestPayloadValidationFailsCleanlyWithoutNetworkCalls:
    def test_missing_action(self):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload={"repository_full_name": "x/y", "pr_number": 1, "label": "bug"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "action" in result["message"]
        assert http_post.calls == []

    def test_unsupported_action(self):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload={"action": "remove_pr_label", "repository_full_name": "x/y", "pr_number": 1, "label": "bug"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "Unsupported action" in result["message"]
        assert http_post.calls == []

    @pytest.mark.parametrize(
        "action",
        [
            "delete_pr_label", "create_label", "edit_label", "remove_label",
            "edit_issue", "edit_pr", "create_review", "merge_pr", "comment_on_pr",
            "create_branch", "delete_branch", "edit_file", "push",
        ],
    )
    def test_write_like_action_names_are_all_unsupported(self, action):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload={"action": action, "repository_full_name": "x/y", "pr_number": 1, "label": "bug"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert http_post.calls == []

    def test_missing_repository_full_name(self):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload={"action": "add_pr_label", "pr_number": 1, "label": "bug"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "repository_full_name" in result["message"]
        assert http_post.calls == []

    @pytest.mark.parametrize("bad_repo", ["no-slash", "too/many/slashes", "/missing-owner", "missing-repo/", ""])
    def test_repository_full_name_must_be_owner_slash_repo_shape(self, bad_repo):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload={"action": "add_pr_label", "repository_full_name": bad_repo, "pr_number": 1, "label": "bug"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert http_post.calls == []

    def test_missing_pr_number(self):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload={"action": "add_pr_label", "repository_full_name": "x/y", "label": "bug"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "pr_number" in result["message"]
        assert http_post.calls == []

    @pytest.mark.parametrize("bad_pr_number", ["not-a-number", 0, -5, 1.5, True])
    def test_invalid_pr_number(self, bad_pr_number):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload={
            "action": "add_pr_label", "repository_full_name": "x/y", "pr_number": bad_pr_number, "label": "bug",
        })

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "pr_number" in result["message"]
        assert http_post.calls == []

    def test_missing_label(self):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload={"action": "add_pr_label", "repository_full_name": "x/y", "pr_number": 1})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "label" in result["message"]
        assert http_post.calls == []

    @pytest.mark.parametrize("empty_label", ["", "   ", "\n\t"])
    def test_empty_label(self, empty_label):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload={
            "action": "add_pr_label", "repository_full_name": "x/y", "pr_number": 1, "label": empty_label,
        })

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert http_post.calls == []


class TestConnectorFailuresBecomeContractResults:
    def test_post_raising_becomes_failure(self):
        http_post = FakeHttpPostLabel(exc=GitHubPRLabelAdapterError("boom", is_transient=False))
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD))

        result = adapter.execute(task)  # must not raise

        assert result["status"] == "failure"
        assert "boom" in result["message"]

    def test_post_raising_transient_becomes_retryable_with_retry_after(self):
        http_post = FakeHttpPostLabel(exc=GitHubPRLabelAdapterError("rate limited", is_transient=True, retry_after=12.5))
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD))

        result = adapter.execute(task)

        assert result["status"] == "retryable"
        assert result["retry_after"] == 12.5

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_5xx_and_429_return_retryable(self, status):
        http_post = FakeHttpPostLabel(exc=GitHubPRLabelAdapterError(f"HTTP {status}", is_transient=True))
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD))

        result = adapter.execute(task)

        assert result["status"] == "retryable"
        assert "retry_after" in result

    @pytest.mark.parametrize("status", [401, 403, 404])
    def test_401_403_404_return_failure(self, status):
        http_post = FakeHttpPostLabel(exc=GitHubPRLabelAdapterError(f"HTTP {status}", is_transient=False))
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD))

        result = adapter.execute(task)

        assert result["status"] == "failure"

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_5xx_and_429_are_transient_via_real_http_post(self, monkeypatch, status):
        import urllib.error

        def raising_urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, status, "server error", {}, None)

        monkeypatch.setattr(gpla_module.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(GitHubPRLabelAdapterError) as exc_info:
            gpla_module._default_http_post_label("https://api.github.com/x", {}, {}, 10.0)

        assert exc_info.value.is_transient is True

    @pytest.mark.parametrize("status", [401, 403, 404])
    def test_401_403_404_are_permanent_via_real_http_post(self, monkeypatch, status):
        import urllib.error

        def raising_urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, status, "client error", {}, None)

        monkeypatch.setattr(gpla_module.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(GitHubPRLabelAdapterError) as exc_info:
            gpla_module._default_http_post_label("https://api.github.com/x", {}, {}, 10.0)

        assert exc_info.value.is_transient is False

    def test_url_error_is_transient_via_real_http_post(self, monkeypatch):
        import urllib.error

        def raising_urlopen(request, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(gpla_module.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(GitHubPRLabelAdapterError) as exc_info:
            gpla_module._default_http_post_label("https://api.github.com/x", {}, {}, 10.0)

        assert exc_info.value.is_transient is True

    def test_timeout_is_transient_via_real_http_post(self, monkeypatch):
        def raising_urlopen(request, timeout):
            raise TimeoutError("timed out")

        monkeypatch.setattr(gpla_module.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(GitHubPRLabelAdapterError) as exc_info:
            gpla_module._default_http_post_label("https://api.github.com/x", {}, {}, 10.0)

        assert exc_info.value.is_transient is True


class TestResultsPassPhase3DContractValidation:
    @pytest.mark.parametrize(
        "payload",
        [dict(VALID_PAYLOAD), {"action": "nope"}, {}],
    )
    def test_result_shape_valid(self, payload):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        task = make_task(payload=payload)

        result = adapter.execute(task)

        assert _validate_adapter_result(result) is None


class TestApprovalGatingFullLifecycle:
    """Proves the adapter is only ever reached through the scheduler's
    existing approval gate -- the adapter itself has no approval logic,
    exactly like the Phase 3C PR comment adapter."""

    def test_approval_required_task_not_executed_before_approval(self, repository):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        executor = make_executor(repository, adapter)
        task = make_task(payload=dict(VALID_PAYLOAD), approval_required=True)
        repository.create_task(task)

        result = executor.execute(task)

        assert http_post.calls == []
        assert result.status == "blocked"
        assert "approval_engine_deferred" in result.blockers
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.APPROVAL_PENDING
        approval = repository.get_approval_request(task.id)
        assert approval is not None
        assert approval.decision == ApprovalDecision.PENDING

    def test_rejected_approval_does_not_execute_adapter(self, repository):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        executor = make_executor(repository, adapter)
        task = make_task(payload=dict(VALID_PAYLOAD), approval_required=True)
        repository.create_task(task)

        executor.execute(task)  # creates pending approval, adapter not called
        repository.update_approval_decision(task.id, ApprovalDecision.REJECTED, approver="reviewer", reason="no")

        result = executor.execute(task)  # must not raise, must not call adapter

        assert http_post.calls == []
        assert result.status == "blocked"
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.GOVERNANCE_BLOCKED

    def test_approved_task_executes_adapter_exactly_once(self, repository):
        http_post = FakeHttpPostLabel(response=[{"name": "automated-status"}])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        executor = make_executor(repository, adapter)
        task = make_task(payload=dict(VALID_PAYLOAD), approval_required=True)
        repository.create_task(task)

        first_result = executor.execute(task)
        assert http_post.calls == []
        assert first_result.status == "blocked"

        repository.update_approval_decision(task.id, ApprovalDecision.APPROVED, approver="reviewer")
        task.mark_approved()
        repository.update_task(task)

        second_result = executor.execute(task)

        assert len(http_post.calls) == 1
        assert second_result.success is True
        assert second_result.status == "pass"
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.COMPLETED

    def test_audit_log_records_approval_and_execution_path(self, repository):
        http_post = FakeHttpPostLabel(response=[])
        adapter = GitHubPRLabelAdapter(http_post_label=http_post)
        audit_logger = AuditLogger(repository=repository)
        executor = Executor(adapter=adapter, repository=repository, audit_logger=audit_logger)
        task = make_task(payload=dict(VALID_PAYLOAD), approval_required=True)
        repository.create_task(task)

        executor.execute(task)
        repository.update_approval_decision(task.id, ApprovalDecision.APPROVED, approver="reviewer")
        task.mark_approved()
        repository.update_task(task)
        executor.execute(task)

        events = audit_logger.get_events(task_id=task.id)
        event_types = [e.event_type for e in events]
        assert "approval_requested" in event_types
        assert "governance_check_passed" in event_types
        assert "task_completed" in event_types


class TestNoWriteOperationsBeyondTheOneEndpoint:
    """Defense-in-depth: the module must have no GET, PATCH, PUT, or
    DELETE call anywhere, exactly one POST call site pointed at the one
    hardcoded label-add endpoint, and no other reachable write surface."""

    def test_source_contains_no_get_patch_put_delete_verbs(self):
        source = inspect.getsource(gpla_module)
        for verb in ("GET", "PATCH", "PUT", "DELETE"):
            assert f'method="{verb}"' not in source
            assert f"method='{verb}'" not in source

    def test_source_contains_exactly_one_post_call_site(self):
        source = inspect.getsource(gpla_module)
        assert source.count('method="POST"') == 1

    def test_post_url_is_the_fixed_label_template(self):
        source = inspect.getsource(gpla_module)
        assert 'f"{GITHUB_API_BASE}/repos/{repository_full_name}/issues/{pr_number}/labels"' in source

    def test_only_one_place_issues_http_requests(self):
        source = inspect.getsource(gpla_module)
        assert source.count("urllib.request.Request(") == 1
        assert source.count("urllib.request.urlopen(") == 1

    def test_source_contains_no_merge_comment_review_branch_file_metadata_endpoints(self):
        source = inspect.getsource(gpla_module).lower()
        forbidden_fragments = [
            "/merge", "/comments", "/reviews", "/branches", "/contents",
            "git/refs", "review-comments", "/title", "/body",
        ]
        for fragment in forbidden_fragments:
            assert fragment not in source, f"unexpected reachable endpoint fragment: {fragment}"

    def test_adapter_has_no_extra_write_public_methods(self):
        allowed_write_verb = "add"  # this adapter's one job (add_pr_label / _action_add_pr_label)
        write_verbs = ("create", "update", "delete", "merge", "review", "remove", "push", "edit", "archive")
        public_methods = [
            name
            for name, _ in inspect.getmembers(GitHubPRLabelAdapter, predicate=inspect.isfunction)
            if not name.startswith("_")
        ]
        for name in public_methods:
            lowered = name.lower()
            assert allowed_write_verb not in lowered or name == "execute"
            for verb in write_verbs:
                assert verb not in lowered, f"unexpected write-like method name: {name}"

    def test_actions_dict_has_exactly_one_action(self):
        assert list(GitHubPRLabelAdapter.ACTIONS.keys()) == ["add_pr_label"]


class TestExistingAdaptersUnaffected:
    def test_fake_success_still_resolves_and_runs(self, repository):
        adapter = resolve_adapter("fake-success")
        executor = make_executor(repository, adapter)
        task = make_task(action="test_action")
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is True

    def test_noop_still_resolves(self):
        assert resolve_adapter("noop") is not None

    def test_github_readonly_still_resolves_and_is_unaffected(self):
        from workflow_scheduler.adapters import GitHubReadOnlyAdapter

        adapter = resolve_adapter("github_readonly")
        assert isinstance(adapter, GitHubReadOnlyAdapter)

    def test_notion_readonly_still_resolves_and_is_unaffected(self):
        from workflow_scheduler.adapters import NotionReadOnlyAdapter

        adapter = resolve_adapter("notion_readonly")
        assert isinstance(adapter, NotionReadOnlyAdapter)

    def test_github_pr_comment_still_resolves_and_is_unaffected(self):
        from workflow_scheduler.adapters import GitHubPRCommentAdapter

        adapter = resolve_adapter("github_pr_comment")
        assert isinstance(adapter, GitHubPRCommentAdapter)
