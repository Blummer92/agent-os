from __future__ import annotations

import copy

import pytest

from workflow_scheduler.adapters.github_ruleset_admin_adapter import (
    AUTHORIZATION_ISSUE,
    REPOSITORY,
    RULESET_ID,
    GitHubRulesetAdminAdapter,
    mutation_prestate_sha256,
    required_status_rule,
)
from workflow_scheduler.models import Task


def ruleset():
    return {
        "id": RULESET_ID,
        "name": "Protect main",
        "target": "branch",
        "source_type": "Repository",
        "source": REPOSITORY,
        "enforcement": "active",
        "conditions": {"ref_name": {"exclude": [], "include": ["~DEFAULT_BRANCH"]}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": False,
                    "required_reviewers": [],
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": True,
                    "require_extra_approval_for_unattributed_changes": True,
                    "allowed_merge_methods": ["merge", "squash", "rebase"],
                },
            },
        ],
        "bypass_actors": [],
    }


def task(prestate, **overrides):
    payload = {
        "action": "apply_1883_required_validation_gate",
        "repository_full_name": REPOSITORY,
        "ruleset_id": RULESET_ID,
        "authorization_issue": AUTHORIZATION_ISSUE,
        "expected_prestate_sha256": mutation_prestate_sha256(prestate),
    }
    payload.update(overrides)
    return Task(
        id="ruleset-admin",
        workflow_id="gh-admin1",
        type="github_ruleset_admin",
        owner="GitHub Service Agent",
        action="apply_1883_required_validation_gate",
        idempotency_key="gh-admin1-1883",
        payload=payload,
    )


class FakeTransport:
    def __init__(self, current):
        self.current = copy.deepcopy(current)
        self.gets = 0
        self.puts = []

    def get(self, url, headers, timeout):
        self.gets += 1
        assert url.endswith(f"/repos/{REPOSITORY}/rulesets/{RULESET_ID}")
        assert "Authorization" in headers
        return copy.deepcopy(self.current)

    def put(self, url, headers, body, timeout):
        self.puts.append(copy.deepcopy(body))
        self.current.update(copy.deepcopy(body))
        return copy.deepcopy(self.current)


def test_exact_request_performs_one_put_and_immediate_readback():
    before = ruleset()
    transport = FakeTransport(before)
    adapter = GitHubRulesetAdminAdapter(token="not-a-real-token", http_get=transport.get, http_put=transport.put)
    result = adapter.execute(task(before))
    assert result["status"] == "success"
    assert result["output"]["mutation_attempted"] is True
    assert result["output"]["credential_value_exposed"] is False
    assert transport.gets == 2
    assert len(transport.puts) == 1
    body = transport.puts[0]
    assert body["rules"][:-1] == before["rules"]
    assert body["rules"][-1] == required_status_rule()
    assert body["conditions"] == before["conditions"]
    assert body["bypass_actors"] == before["bypass_actors"]


def test_moved_prestate_fails_before_mutation():
    before = ruleset()
    moved = ruleset()
    moved["rules"].append({"type": "creation"})
    transport = FakeTransport(moved)
    adapter = GitHubRulesetAdminAdapter(token="x", http_get=transport.get, http_put=transport.put)
    result = adapter.execute(task(before))
    assert result["status"] == "failure"
    assert "pre-state moved" in result["message"]
    assert transport.gets == 1
    assert transport.puts == []


def test_conflicting_required_status_rule_fails_closed():
    before = ruleset()
    before["rules"].append({
        "type": "required_status_checks",
        "parameters": {
            "required_status_checks": [{"context": "Other check", "integration_id": 15368}],
            "strict_required_status_checks_policy": True,
            "do_not_enforce_on_create": False,
        },
    })
    transport = FakeTransport(before)
    adapter = GitHubRulesetAdminAdapter(token="x", http_get=transport.get, http_put=transport.put)
    result = adapter.execute(task(before))
    assert result["status"] == "failure"
    assert "conflicting" in result["message"]
    assert transport.puts == []


def test_already_converged_is_idempotent_zero_write():
    before = ruleset()
    before["rules"].append(required_status_rule())
    transport = FakeTransport(before)
    adapter = GitHubRulesetAdminAdapter(token="x", http_get=transport.get, http_put=transport.put)
    result = adapter.execute(task(before))
    assert result["status"] == "success"
    assert result["output"]["mutation_attempted"] is False
    assert transport.gets == 2
    assert transport.puts == []


def test_arbitrary_target_or_extra_payload_is_rejected_before_network():
    before = ruleset()
    called = []
    adapter = GitHubRulesetAdminAdapter(
        token="x",
        http_get=lambda *_: called.append("get"),
        http_put=lambda *_: called.append("put"),
    )
    result = adapter.execute(task(before, repository_full_name="other/repo"))
    assert result["status"] == "failure"
    assert called == []

    result = adapter.execute(task(before, arbitrary_url="https://example.invalid"))
    assert result["status"] == "failure"
    assert called == []


def test_readback_nonconvergence_is_terminal_failure_without_retry():
    before = ruleset()
    reads = [copy.deepcopy(before), copy.deepcopy(before)]
    puts = []
    adapter = GitHubRulesetAdminAdapter(
        token="x",
        http_get=lambda *_: reads.pop(0),
        http_put=lambda _url, _headers, body, _timeout: puts.append(body) or body,
    )
    result = adapter.execute(task(before))
    assert result["status"] == "failure"
    assert "did not converge" in result["message"]
    assert "retry_after" not in result
    assert len(puts) == 1


class TestCanonicalGatewayMigration:
    """#2507: the adapter's bespoke urllib transport is retired behind the
    canonical agent_os_github_issue_provider gateway. Domain policy (fixed
    operation shape, prestate binding, terminal-failure contract) is unchanged;
    only client construction and request execution move to the shared boundary.
    """

    def test_bespoke_urllib_transport_is_deleted(self):
        import workflow_scheduler.adapters.github_ruleset_admin_adapter as module

        assert not hasattr(module, "urllib"), "bespoke urllib import must be deleted"
        source = open(module.__file__, encoding="utf-8").read()
        assert "urllib.request" not in source
        assert "urlopen" not in source
        assert hasattr(module, "build_token_client")
        assert hasattr(module, "request_json")

    def test_client_routes_through_canonical_builder(self, monkeypatch):
        import workflow_scheduler.adapters.github_ruleset_admin_adapter as module
        from workflow_scheduler.adapters.github_ruleset_admin_adapter import (
            GitHubRulesetAdminAdapter,
        )

        seen = {}
        sentinel = object()

        def fake_build_token_client(environment, user_agent=None):
            seen["environment"] = environment
            seen["user_agent"] = user_agent
            return sentinel

        monkeypatch.setattr(module, "build_token_client", fake_build_token_client)
        adapter = GitHubRulesetAdminAdapter(token="canonical-token")

        assert adapter._client() is sentinel
        assert seen["environment"]["GITHUB_TOKEN"] == "canonical-token"
        assert seen["user_agent"] == "workflow-scheduler/github-ruleset-admin"

    def test_gh_token_convention_honored_without_constructor_token(self, monkeypatch):
        from workflow_scheduler.adapters.github_ruleset_admin_adapter import (
            GitHubRulesetAdminAdapter,
        )

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "gh-token-convention")
        adapter = GitHubRulesetAdminAdapter(token=None)

        # Building the client performs no I/O; the convention token is honored.
        assert adapter._client() is not None

    def test_missing_token_fails_closed_as_adapter_error(self, monkeypatch):
        from workflow_scheduler.adapters.github_ruleset_admin_adapter import (
            GitHubRulesetAdminAdapter,
            GitHubRulesetAdminAdapterError,
        )

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        adapter = GitHubRulesetAdminAdapter(token=None)

        with pytest.raises(GitHubRulesetAdminAdapterError):
            adapter._client()

    def test_missing_token_surfaces_as_execute_failure_without_retry(self, monkeypatch):
        from workflow_scheduler.adapters.github_ruleset_admin_adapter import (
            GitHubRulesetAdminAdapter,
        )

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        adapter = GitHubRulesetAdminAdapter(token=None)

        result = adapter.execute(task(ruleset()))

        assert result["status"] == "failure"
        assert "retry_after" not in result

    def test_canonical_path_rejects_off_base_url(self):
        from workflow_scheduler.adapters.github_ruleset_admin_adapter import (
            GitHubRulesetAdminAdapter,
            GitHubRulesetAdminAdapterError,
        )

        adapter = GitHubRulesetAdminAdapter(token="x")

        with pytest.raises(GitHubRulesetAdminAdapterError):
            adapter._canonical_path("https://example.invalid/repos/x/rulesets/1")

    def test_transport_failures_are_terminal_never_retryable(self, monkeypatch):
        import workflow_scheduler.adapters.github_ruleset_admin_adapter as module
        from scripts.agent_os_github_issue_provider.request import GitHubRequestError
        from workflow_scheduler.adapters.github_ruleset_admin_adapter import (
            GitHubRulesetAdminAdapter,
        )

        cases = [
            (GitHubRequestError("http-error", status=403, attempts=()), "HTTP 403"),
            (GitHubRequestError("http-error", status=500, attempts=()), "HTTP 500"),
            (GitHubRequestError("rate-limited", status=429, attempts=()), "rate-limited"),
            (GitHubRequestError("transport-unavailable", status=None, attempts=()), "transport failed"),
            (GitHubRequestError("internal-error", status=None, attempts=()), "invalid response"),
        ]
        for error, fragment in cases:
            def fake_request_json(*args, **kwargs):
                raise error

            monkeypatch.setattr(module, "request_json", fake_request_json)
            adapter = GitHubRulesetAdminAdapter(token="x")
            result = adapter.execute(task(ruleset()))

            assert result["status"] == "failure", error.kind
            assert fragment in result["message"], error.kind
            assert "retry_after" not in result, error.kind

    def test_canonical_requests_use_single_attempt_and_fixed_path(self, monkeypatch):
        import workflow_scheduler.adapters.github_ruleset_admin_adapter as module
        from scripts.agent_os_github_issue_provider.request import GitHubRequestResult
        from workflow_scheduler.adapters.github_ruleset_admin_adapter import (
            REPOSITORY,
            RULESET_ID,
            GitHubRulesetAdminAdapter,
        )

        calls = []
        sentinel_client = object()

        def fake_request_json(client, method, path, **kwargs):
            calls.append((method, path, kwargs))
            return GitHubRequestResult(headers={}, payload=ruleset(), attempts=())

        monkeypatch.setattr(module, "request_json", fake_request_json)
        monkeypatch.setattr(
            GitHubRulesetAdminAdapter, "_client", lambda self: sentinel_client
        )
        adapter = GitHubRulesetAdminAdapter(token="x")
        url = f"https://api.github.com/repos/{REPOSITORY}/rulesets/{RULESET_ID}"

        adapter._canonical_get(url, {}, 10.0)
        adapter._canonical_put(url, {}, {"rules": []}, 10.0)

        assert [c[0] for c in calls] == ["GET", "PUT"]
        assert all(
            path == f"/repos/{REPOSITORY}/rulesets/{RULESET_ID}" for _, path, _ in calls
        )
        assert all(kwargs["max_attempts"] == 1 for _, _, kwargs in calls)
        assert calls[0][2]["input_payload"] is None
        assert calls[1][2]["input_payload"] == {"rules": []}
