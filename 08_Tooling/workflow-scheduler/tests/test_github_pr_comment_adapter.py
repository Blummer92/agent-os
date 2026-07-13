"""Tests for Phase 3C: GitHubPRCommentAdapter, the first write-capable
adapter. All network access is mocked via an injected
http_post_comment callable -- no live GitHub access or real token
required. Approval-gating tests exercise the full Executor +
StopConditionChecker lifecycle to prove the adapter is never called
before an explicit APPROVED decision, and that a REJECTED decision
never results in a call either.

Phase 3F migrated this adapter's result shape from success/error/
is_transient to the Phase 3D five-state contract (status/message);
these tests assert the new shape throughout. ExecutionResult-level
assertions (result.success/result.status/result.blockers) are
Executor-level and unaffected by the adapter's internal shape, so the
approval-gating lifecycle tests below are unchanged from Phase 3C."""

import inspect

import pytest

from workflow_scheduler.adapters import (
    GitHubPRCommentAdapter,
    GitHubPRCommentAdapterError,
    resolve_adapter,
)
from workflow_scheduler.adapters import github_pr_comment_adapter as gpca_module
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
        action="comment_on_pr",
        idempotency_key=f"key-{task_id}",
        payload=payload or {},
    )
    defaults.update(overrides)
    return Task(**defaults)


class FakeHttpPostComment:
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
    "action": "post_pr_comment",
    "repository_full_name": "Blummer92/agent-os",
    "pr_number": 29,
    "body": "Automated comment.",
}


class TestRegistry:
    def test_resolve_github_pr_comment(self):
        adapter = resolve_adapter("github_pr_comment")
        assert isinstance(adapter, GitHubPRCommentAdapter)

    def test_unknown_adapter_still_fails_cleanly(self):
        with pytest.raises(ValueError, match="Unknown adapter"):
            resolve_adapter("does-not-exist")


class TestSuccessfulWriteUsesContractResult:
    def test_post_pr_comment_succeeds(self):
        http_post = FakeHttpPostComment(response={
            "id": 12345,
            "html_url": "https://github.com/Blummer92/agent-os/pull/29#issuecomment-12345",
            "created_at": "2026-07-13T00:00:00Z",
        })
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD))

        result = adapter.execute(task)

        assert result["status"] == "success"
        assert "success" not in result
        assert result["output"]["id"] == 12345
        assert http_post.calls[0][0] == "https://api.github.com/repos/Blummer92/agent-os/issues/29/comments"
        assert http_post.calls[0][2] == {"body": "Automated comment."}

    def test_result_is_recognized_as_a_contract_result(self):
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD))

        result = adapter.execute(task)

        assert _is_contract_result(result) is True

    def test_token_sets_authorization_header(self):
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(token="secret-token", http_post_comment=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD))

        adapter.execute(task)

        headers = http_post.calls[0][1]
        assert headers["Authorization"] == "Bearer secret-token"

    def test_no_token_omits_authorization_header(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD))

        adapter.execute(task)

        headers = http_post.calls[0][1]
        assert "Authorization" not in headers


class TestPayloadValidationFailsCleanlyWithoutNetworkCalls:
    def test_missing_action(self):
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload={"repository_full_name": "x/y", "pr_number": 1, "body": "hi"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "action" in result["message"]
        assert http_post.calls == []

    def test_unsupported_action(self):
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload={"action": "edit_pr_comment", "repository_full_name": "x/y", "pr_number": 1, "body": "hi"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "Unsupported action" in result["message"]
        assert http_post.calls == []

    @pytest.mark.parametrize(
        "action",
        [
            "delete_pr_comment", "create_review", "add_label", "merge_pr",
            "create_branch", "delete_branch", "edit_file", "push", "edit_issue",
        ],
    )
    def test_write_like_action_names_are_all_unsupported(self, action):
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload={"action": action, "repository_full_name": "x/y", "pr_number": 1, "body": "hi"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert http_post.calls == []

    def test_missing_repository_full_name(self):
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload={"action": "post_pr_comment", "pr_number": 1, "body": "hi"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "repository_full_name" in result["message"]
        assert http_post.calls == []

    def test_missing_pr_number(self):
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload={"action": "post_pr_comment", "repository_full_name": "x/y", "body": "hi"})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "pr_number" in result["message"]
        assert http_post.calls == []

    @pytest.mark.parametrize("bad_pr_number", ["not-a-number", 0, -5, 1.5, True])
    def test_invalid_pr_number(self, bad_pr_number):
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload={
            "action": "post_pr_comment", "repository_full_name": "x/y", "pr_number": bad_pr_number, "body": "hi",
        })

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "pr_number" in result["message"]
        assert http_post.calls == []

    def test_missing_body(self):
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload={"action": "post_pr_comment", "repository_full_name": "x/y", "pr_number": 1})

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "body" in result["message"]
        assert http_post.calls == []

    @pytest.mark.parametrize("empty_body", ["", "   ", "\n\t"])
    def test_empty_body(self, empty_body):
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload={
            "action": "post_pr_comment", "repository_full_name": "x/y", "pr_number": 1, "body": empty_body,
        })

        result = adapter.execute(task)

        assert result["status"] == "failure"
        assert "body" in result["message"]
        assert http_post.calls == []


class TestConnectorFailuresBecomeContractResults:
    def test_post_raising_permanent_becomes_failure(self):
        http_post = FakeHttpPostComment(exc=GitHubPRCommentAdapterError("boom", is_transient=False))
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD))

        result = adapter.execute(task)  # must not raise

        assert result["status"] == "failure"
        assert "boom" in result["message"]

    def test_post_raising_transient_becomes_retryable(self):
        http_post = FakeHttpPostComment(exc=GitHubPRCommentAdapterError("rate limited", is_transient=True))
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD))

        result = adapter.execute(task)

        assert result["status"] == "retryable"
        assert "retry_after" in result

    def test_retry_after_uses_exponential_backoff_at_retry_count_zero(self):
        http_post = FakeHttpPostComment(exc=GitHubPRCommentAdapterError("rate limited", is_transient=True))
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD), retry_count=0)

        result = adapter.execute(task)

        assert result["retry_after"] == 5.0

    def test_retry_after_uses_exponential_backoff_at_nonzero_retry_count(self):
        """Proves this isn't a hardcoded flat delay: retry_after must
        grow with task.retry_count, matching RetryManager.compute_delay's
        5.0 * 2**retry_count formula (capped at 300.0)."""
        http_post = FakeHttpPostComment(exc=GitHubPRCommentAdapterError("rate limited", is_transient=True))
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD), retry_count=4)

        result = adapter.execute(task)

        assert result["retry_after"] == 80.0  # 5.0 * 2**4

    def test_retry_after_is_capped_at_300(self):
        http_post = FakeHttpPostComment(exc=GitHubPRCommentAdapterError("rate limited", is_transient=True))
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload=dict(VALID_PAYLOAD), retry_count=10)

        result = adapter.execute(task)

        assert result["retry_after"] == 300.0

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_5xx_and_429_are_transient_via_real_http_post(self, monkeypatch, status):
        import urllib.error

        def raising_urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, status, "server error", {}, None)

        monkeypatch.setattr(gpca_module.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(GitHubPRCommentAdapterError) as exc_info:
            gpca_module._default_http_post_comment("https://api.github.com/x", {}, {}, 10.0)

        assert exc_info.value.is_transient is True

    @pytest.mark.parametrize("status", [401, 403, 404])
    def test_401_403_404_are_permanent_via_real_http_post(self, monkeypatch, status):
        import urllib.error

        def raising_urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, status, "client error", {}, None)

        monkeypatch.setattr(gpca_module.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(GitHubPRCommentAdapterError) as exc_info:
            gpca_module._default_http_post_comment("https://api.github.com/x", {}, {}, 10.0)

        assert exc_info.value.is_transient is False

    def test_url_error_is_transient_via_real_http_post(self, monkeypatch):
        import urllib.error

        def raising_urlopen(request, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(gpca_module.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(GitHubPRCommentAdapterError) as exc_info:
            gpca_module._default_http_post_comment("https://api.github.com/x", {}, {}, 10.0)

        assert exc_info.value.is_transient is True

    def test_timeout_is_transient_via_real_http_post(self, monkeypatch):
        def raising_urlopen(request, timeout):
            raise TimeoutError("timed out")

        monkeypatch.setattr(gpca_module.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(GitHubPRCommentAdapterError) as exc_info:
            gpca_module._default_http_post_comment("https://api.github.com/x", {}, {}, 10.0)

        assert exc_info.value.is_transient is True


class TestResultsPassContractValidation:
    @pytest.mark.parametrize(
        "payload",
        [dict(VALID_PAYLOAD), {"action": "nope"}, {}],
    )
    def test_result_shape_valid(self, payload):
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
        task = make_task(payload=payload)

        result = adapter.execute(task)

        assert _validate_adapter_result(result) is None


class TestApprovalGatingFullLifecycle:
    """Proves the adapter is only ever reached through the scheduler's
    existing approval gate -- the adapter itself has no approval logic.
    ExecutionResult-level assertions here are Executor-level and
    unaffected by the Phase 3F result-shape migration."""

    def test_approval_required_task_not_executed_before_approval(self, repository):
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
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
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
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
        http_post = FakeHttpPostComment(response={
            "id": 999, "html_url": "https://github.com/x/y/pull/1#issuecomment-999", "created_at": "2026-07-13T00:00:00Z",
        })
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
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
        http_post = FakeHttpPostComment(response={"id": 1})
        adapter = GitHubPRCommentAdapter(http_post_comment=http_post)
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
    DELETE call anywhere, and exactly one POST call site pointed at the
    one hardcoded comment-creation endpoint."""

    def test_source_contains_no_get_patch_put_delete_verbs(self):
        source = inspect.getsource(gpca_module)
        for verb in ("GET", "PATCH", "PUT", "DELETE"):
            assert f'method="{verb}"' not in source
            assert f"method='{verb}'" not in source

    def test_source_contains_exactly_one_post_call_site(self):
        source = inspect.getsource(gpca_module)
        assert source.count('method="POST"') == 1

    def test_post_url_is_the_fixed_comment_template(self):
        source = inspect.getsource(gpca_module)
        assert 'f"{GITHUB_API_BASE}/repos/{repository_full_name}/issues/{pr_number}/comments"' in source

    def test_only_one_place_issues_http_requests(self):
        source = inspect.getsource(gpca_module)
        assert source.count("urllib.request.Request(") == 1
        assert source.count("urllib.request.urlopen(") == 1

    def test_source_contains_no_merge_label_review_branch_file_endpoints(self):
        source = inspect.getsource(gpca_module).lower()
        forbidden_fragments = [
            "/merge", "/labels", "/reviews", "/branches", "/contents", "/pulls/",
            "git/refs", "review-comments",
        ]
        for fragment in forbidden_fragments:
            assert fragment not in source, f"unexpected reachable endpoint fragment: {fragment}"

    def test_adapter_has_no_extra_write_public_methods(self):
        allowed_write_verb = "post"  # this adapter's one job
        write_verbs = ("create", "update", "delete", "merge", "review", "label", "push", "edit", "archive")
        public_methods = [
            name
            for name, _ in inspect.getmembers(GitHubPRCommentAdapter, predicate=inspect.isfunction)
            if not name.startswith("_")
        ]
        for name in public_methods:
            lowered = name.lower()
            assert allowed_write_verb not in lowered or name == "execute"
            for verb in write_verbs:
                assert verb not in lowered, f"unexpected write-like method name: {name}"

    def test_actions_dict_has_exactly_one_action(self):
        assert list(GitHubPRCommentAdapter.ACTIONS.keys()) == ["post_pr_comment"]

    def test_no_retry_manager_import(self):
        """RetryManager must not be imported into this adapters module --
        importing it would create a circular import with
        execution/executor.py, which already imports TaskAdapter from
        the adapters package. The backoff formula is inlined instead.
        (The docstring legitimately mentions "RetryManager" by name to
        explain this, so only import statements are checked here.)"""
        source = inspect.getsource(gpca_module)
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

    def test_noop_still_resolves(self):
        assert resolve_adapter("noop") is not None

    def test_github_readonly_still_resolves_and_is_unaffected(self):
        from workflow_scheduler.adapters import GitHubReadOnlyAdapter

        adapter = resolve_adapter("github_readonly")
        assert isinstance(adapter, GitHubReadOnlyAdapter)

    def test_github_pr_label_still_resolves_and_is_unaffected(self):
        from workflow_scheduler.adapters import GitHubPRLabelAdapter

        adapter = resolve_adapter("github_pr_label")
        assert isinstance(adapter, GitHubPRLabelAdapter)
