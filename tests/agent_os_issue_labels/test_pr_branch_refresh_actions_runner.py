from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

from scripts.agent_os_issue_labels.pr_branch_refresh_actions import BranchRefreshActionsTrigger
from scripts.agent_os_issue_labels.pr_branch_refresh_actions_runner import run_branch_refresh_actions
from scripts.agent_os_issue_labels.pr_branch_refresh_authorization import (
    RefreshAuthorization,
    RefreshAuthorizationState,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_authorization_source import (
    serialize_refresh_authorization_comment,
)

REPO = "Blummer92/agent-os"
HEAD = "1" * 40
MAIN = "2" * 40


def authorization() -> RefreshAuthorization:
    return RefreshAuthorization(
        schema_version="1.0",
        repository=REPO,
        pr_number=1619,
        base_branch="main",
        expected_head_sha=HEAD,
        expected_main_sha=MAIN,
        allowed_changed_paths=("a.py",),
        forbidden_paths=(".github/workflows/",),
        required_validation_command_ids=("pytest:pr-branch-refresh",),
        branch_refresh_authorized=True,
        label_write_authorized=True,
        owner_decision_reference="github-owner-decision:1619",
        state=RefreshAuthorizationState.AUTHORIZED,
    )


@dataclass
class FakeComment:
    id: int
    body: str
    login: str = "Blummer92"

    @property
    def user(self):
        return SimpleNamespace(login=self.login)

    @property
    def created_at(self):
        return datetime(2026, 9, 4, tzinfo=timezone.utc)


class FakeIssue:
    def __init__(self, comments):
        self.comments = list(comments)
        self.created = []

    def get_comments(self):
        return iter(self.comments)

    def create_comment(self, body):
        self.created.append(body)


class FakeRepo:
    def __init__(self, comments):
        self.owner = SimpleNamespace(login="Blummer92", type="User")
        self.issue = FakeIssue(comments)
        self.pr = SimpleNamespace(
            head=SimpleNamespace(sha=HEAD),
            get_files=lambda: [SimpleNamespace(filename="a.py")],
        )

    def get_issue(self, number):
        assert number == 1619
        return self.issue

    def get_pull(self, number):
        assert number == 1619
        return self.pr

    def get_branch(self, name):
        assert name == "main"
        return SimpleNamespace(commit=SimpleNamespace(sha=MAIN))


class FakeGithub:
    def __init__(self, comments):
        self.repo = FakeRepo(comments)

    def get_repo(self, repository):
        assert repository == REPO
        return self.repo


def trigger():
    return BranchRefreshActionsTrigger(
        status="accepted",
        reason="finite-refresh-operation-requested",
        pr_number=1619,
        repository=REPO,
    )


def test_actions_runner_reacquires_owner_authorization_and_invokes_facade_once():
    auth = authorization()
    github = FakeGithub([FakeComment(10, serialize_refresh_authorization_comment(auth))])
    calls = []

    def refresh(**kwargs):
        calls.append(kwargs)
        return {
            "status": "converged",
            "authorization_id": auth.authorization_id,
            "authorization_consumed": True,
            "admitted_main_sha": MAIN,
            "old_head_sha": HEAD,
            "new_head_sha": "3" * 40,
            "mutation_count": 1,
            "validation_status": "green",
            "validation_head_sha": "3" * 40,
            "lifecycle_reconciliation_status": "converged",
            "final_current_proven": True,
            "blockers": (),
            "reason_codes": ("branch.current-proven",),
            "rollback_posture": "restore-old-head-with-separate-authorization",
            "side_effects_performed": True,
        }

    result = run_branch_refresh_actions(
        trigger=trigger(), github_client=github, repository_root="/repo",
        invocation_id="actions:1:1", environment={"GITHUB_TOKEN": "secret"},
        refresh_callable=refresh,
    )
    assert result.status == "converged"
    assert result.mutation_count == 1
    assert len(calls) == 1
    assert calls[0]["authorization_id"] == auth.authorization_id
    assert calls[0]["expected_head_sha"] == HEAD
    assert calls[0]["current_main_sha"] == MAIN
    assert github.repo.issue.created
    assert "secret" not in github.repo.issue.created[0]


def test_actions_runner_blocks_without_canonical_authorization_before_facade():
    github = FakeGithub([])
    calls = []
    result = run_branch_refresh_actions(
        trigger=trigger(), github_client=github, repository_root="/repo",
        invocation_id="actions:1:1", environment={"GITHUB_TOKEN": "secret"},
        refresh_callable=lambda **kwargs: calls.append(kwargs),
    )
    assert result.status == "blocked"
    assert result.mutation_count == 0
    assert not calls


def test_actions_runner_rejects_moved_head_before_facade():
    auth = authorization()
    github = FakeGithub([FakeComment(10, serialize_refresh_authorization_comment(auth))])
    github.repo.pr.head.sha = "4" * 40
    calls = []
    result = run_branch_refresh_actions(
        trigger=trigger(), github_client=github, repository_root="/repo",
        invocation_id="actions:1:1", environment={"GITHUB_TOKEN": "secret"},
        refresh_callable=lambda **kwargs: calls.append(kwargs),
    )
    assert result.status == "blocked"
    assert "head.moved" in result.reason_codes
    assert not calls


def test_actions_runner_never_publishes_receipt_when_no_mutation_attempted():
    auth = authorization()
    github = FakeGithub([FakeComment(10, serialize_refresh_authorization_comment(auth))])

    def refresh(**kwargs):
        return {
            "status": "blocked",
            "authorization_id": auth.authorization_id,
            "authorization_consumed": False,
            "old_head_sha": HEAD,
            "new_head_sha": None,
            "mutation_count": 0,
            "reason_codes": ("branch.refresh-not-required-or-unknown",),
            "side_effects_performed": False,
        }

    result = run_branch_refresh_actions(
        trigger=trigger(), github_client=github, repository_root="/repo",
        invocation_id="actions:1:1", environment={"GITHUB_TOKEN": "secret"},
        refresh_callable=refresh,
    )
    assert result.status == "blocked"
    assert result.mutation_count == 0
    assert not github.repo.issue.created
