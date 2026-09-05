from __future__ import annotations

import copy

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
