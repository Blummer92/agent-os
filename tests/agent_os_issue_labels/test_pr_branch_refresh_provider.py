from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from scripts.agent_os_github_git_objects import BranchUpdateObservation
from scripts.agent_os_issue_labels.pr_branch_refresh import (
    BranchRefreshValidationResult,
    PullRequestBranchRefreshRequest,
    PullRequestBranchSnapshot,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_provider import (
    GitHubPullRequestBranchRefreshBackingProvider,
    ProductionPullRequestBranchRefreshProvider,
)
from scripts.agent_os_issue_labels.pr_reconciler import LivePullRequestSnapshot

OLD = "1" * 40
BASE = "2" * 40
MAIN = "3" * 40
NEW = "4" * 40
MERGE_BASE = "0" * 40


@dataclass
class FakeRunner:
    observations: list[BranchUpdateObservation]
    calls: list[tuple[tuple[str, ...], str, dict[str, str]]] = field(default_factory=list)

    def run(self, argv, *, cwd, env):
        self.calls.append((tuple(argv), cwd, dict(env)))
        return self.observations.pop(0)


@dataclass
class FakeBacking:
    branch_snapshot: PullRequestBranchSnapshot
    labels: tuple[str, ...] = ("branch:behind",)
    branch_reads: int = 0
    validation_calls: list[tuple[str, int, str, tuple[str, ...]]] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def read_branch(self, repository, pr_number):
        self.branch_reads += 1
        return self.branch_snapshot

    def run_required_validation(self, repository, pr_number, *, head_sha, command_ids):
        self.validation_calls.append((repository, pr_number, head_sha, command_ids))
        return BranchRefreshValidationResult(head_sha=head_sha, status="green", command_ids=command_ids)

    def read(self, repository, pr_number):
        snapshot = self.branch_snapshot
        return LivePullRequestSnapshot(
            repository=repository,
            pr_number=pr_number,
            head_sha=snapshot.head_sha,
            draft=True,
            mergeable=True,
            conflicted=False,
            behind=snapshot.branch_state == "behind",
            validation_state="pending",
            blocking_review_threads=0,
            labels=self.labels,
        )

    def available_labels(self, repository):
        return ("branch:behind", "branch:current", "status:ready")

    def add_label(self, repository, pr_number, label):
        self.added.append(label)

    def remove_label(self, repository, pr_number, label):
        self.removed.append(label)


@dataclass
class FakeValidationExecutor:
    status: str = "green"

    def run_required_validation(self, repository, pr_number, *, head_sha, command_ids):
        return BranchRefreshValidationResult(head_sha=head_sha, status=self.status, command_ids=command_ids)


@dataclass
class FakeReviewThreadsReader:
    count: int = 0

    def blocking_review_threads(self, repository, pr_number):
        return self.count


class FakeIssue:
    def __init__(self, labels=("branch:behind",)):
        self.labels = [SimpleNamespace(name=label) for label in labels]
        self.added = []
        self.removed = []

    def add_to_labels(self, label):
        self.added.append(label)

    def remove_from_labels(self, label):
        self.removed.append(label)


class FakePull:
    def __init__(self):
        self.base = SimpleNamespace(ref="main")
        self.head = SimpleNamespace(ref="agent/1237-publication-required-continuation", sha=OLD)
        self.mergeable = True
        self.mergeable_state = "clean"
        self.draft = True

    def get_files(self):
        return [SimpleNamespace(filename="scripts/example.py")]


class FakeRepo:
    def __init__(self):
        self.pull = FakePull()
        self.issue = FakeIssue()

    def get_pull(self, pr_number):
        return self.pull

    def get_branch(self, branch):
        sha = MAIN if branch == "main" else BASE
        return SimpleNamespace(commit=SimpleNamespace(sha=sha))

    def compare(self, base, head):
        return SimpleNamespace(status="diverged")

    def get_issue(self, pr_number):
        return self.issue

    def get_labels(self):
        return [SimpleNamespace(name=label) for label in ("branch:behind", "branch:current", "pr:draft", "validation:pending", "review:clear")]


class FakeGithub:
    def __init__(self, repo=None, *, fail=False):
        self.repo = repo or FakeRepo()
        self.fail = fail

    def get_repo(self, repository):
        if self.fail:
            raise RuntimeError("unavailable")
        return self.repo


def observation(*, stdout="", return_code=0, started=True, timed_out=False, termination_confirmed=True):
    return BranchUpdateObservation(
        started=started,
        return_code=return_code,
        timed_out=timed_out,
        termination_confirmed=termination_confirmed,
        stdout=stdout,
    )


def snapshot(*, head=OLD, base=BASE, main=MAIN, state="behind", mergeability="mergeable"):
    return PullRequestBranchSnapshot(
        repository="Blummer92/agent-os",
        pr_number=1363,
        base_branch="main",
        base_sha=base,
        head_branch="agent/1237-publication-required-continuation",
        head_sha=head,
        current_main_sha=main,
        branch_state=state,
        mergeability=mergeability,
        changed_paths=("scripts/example.py",),
    )


def request(**overrides):
    values = dict(
        repository="Blummer92/agent-os",
        pr_number=1363,
        base_branch="main",
        expected_base_sha=MAIN,
        expected_head_sha=OLD,
        current_main_sha=MAIN,
        authorization_id="authorization-1365",
        authorization_current=True,
        allowed_changed_paths=("scripts/example.py",),
        forbidden_paths=(".github/workflows/x.yml",),
        required_validation_command_ids=("focused",),
        branch_refresh_authorized=True,
        label_write_authorized=True,
    )
    values.update(overrides)
    return PullRequestBranchRefreshRequest(**values)


def provider(backing, runner, **overrides):
    values = dict(
        backing=backing,
        runner=runner,
        repository_root="/workspace/agent-os",
        invocation_id="invocation-1365",
        authorization_id="authorization-1365",
        authorization_current=True,
        branch_update_authorized=True,
        environment={"GIT_CONFIG_NOSYSTEM": "1"},
    )
    values.update(overrides)
    return ProductionPullRequestBranchRefreshProvider(**values)


def invoke(subject):
    return subject.rebase_onto_main(
        "Blummer92/agent-os",
        1363,
        expected_head_sha=OLD,
        expected_base_sha=BASE,
        current_main_sha=MAIN,
    )


def test_rebase_preparation_then_expected_head_transport_updates_once():
    backing = FakeBacking(snapshot())
    runner = FakeRunner([
        observation(stdout=f"{MERGE_BASE}\n"),
        observation(),
        observation(stdout=f"{NEW}\n"),
        observation(stdout=f"{OLD}\trefs/heads/agent/1237-publication-required-continuation\n"),
        observation(),
        observation(stdout=f"{NEW}\trefs/heads/agent/1237-publication-required-continuation\n"),
    ])
    result = invoke(provider(backing, runner))
    assert result.status == "updated"
    assert result.old_head_sha == OLD and result.new_head_sha == NEW
    assert runner.calls[0][0] == ("git", "merge-base", OLD, MAIN)
    assert runner.calls[1][0] == ("git", "rebase", "--no-autostash", "--onto", MAIN, MERGE_BASE, OLD)
    assert sum("push" in call[0] for call in runner.calls) == 1


def test_moved_head_blocks_before_any_git_command():
    runner = FakeRunner([])
    result = invoke(provider(FakeBacking(snapshot(head="5" * 40)), runner))
    assert result.reason_code == "head.moved-before-preparation" and runner.calls == []


def test_moved_main_blocks_before_any_git_command():
    runner = FakeRunner([])
    result = invoke(provider(FakeBacking(snapshot(main="6" * 40)), runner))
    assert result.reason_code == "base.moved-before-preparation" and runner.calls == []


def test_conflicted_branch_blocks_before_any_git_command():
    runner = FakeRunner([])
    result = invoke(provider(FakeBacking(snapshot(mergeability="conflicted")), runner))
    assert result.reason_code == "branch.refresh-not-eligible-before-preparation" and runner.calls == []


def test_transport_authorization_blocks_before_local_preparation():
    runner = FakeRunner([])
    result = invoke(provider(FakeBacking(snapshot()), runner, authorization_current=False))
    assert result.reason_code == "authorization.refresh-required-before-preparation"
    assert runner.calls == []


def test_missing_merge_base_blocks_before_rebase_or_push():
    runner = FakeRunner([observation(return_code=1)])
    result = invoke(provider(FakeBacking(snapshot()), runner))
    assert result.reason_code == "merge-base-unavailable"
    assert len(runner.calls) == 1


def test_rebase_failure_is_bounded_and_does_not_attempt_push():
    runner = FakeRunner([observation(stdout=f"{MERGE_BASE}\n"), observation(return_code=1)])
    result = invoke(provider(FakeBacking(snapshot()), runner))
    assert result.reason_code == "rebase-rejected"
    assert all("push" not in call[0] for call in runner.calls)


def test_rebase_timeout_is_ambiguous_and_does_not_retry():
    runner = FakeRunner([observation(stdout=f"{MERGE_BASE}\n"), observation(return_code=None, timed_out=True, termination_confirmed=False)])
    result = invoke(provider(FakeBacking(snapshot()), runner))
    assert result.status == "ambiguous" and len(runner.calls) == 2


def test_unproven_rebased_head_blocks_before_remote_transport():
    runner = FakeRunner([observation(stdout=f"{MERGE_BASE}\n"), observation(), observation(stdout="not-a-sha\n")])
    result = invoke(provider(FakeBacking(snapshot()), runner))
    assert result.reason_code == "rebased-head-unavailable"
    assert all("push" not in call[0] for call in runner.calls)


def test_transport_uncertainty_maps_to_ambiguous_without_retry():
    runner = FakeRunner([
        observation(stdout=f"{MERGE_BASE}\n"), observation(), observation(stdout=f"{NEW}\n"),
        observation(stdout=f"{OLD}\trefs/heads/agent/1237-publication-required-continuation\n"),
        observation(return_code=None, timed_out=True, termination_confirmed=False),
    ])
    result = invoke(provider(FakeBacking(snapshot()), runner))
    assert result.status == "ambiguous"
    assert sum("push" in call[0] for call in runner.calls) == 1


def test_label_and_validation_operations_delegate_to_existing_backing_provider():
    backing = FakeBacking(snapshot())
    subject = provider(backing, FakeRunner([]))
    subject.add_label("Blummer92/agent-os", 1363, "branch:current")
    subject.remove_label("Blummer92/agent-os", 1363, "branch:behind")
    validation = subject.run_required_validation("Blummer92/agent-os", 1363, head_sha=NEW, command_ids=("focused", "aggregate"))
    assert backing.added == ["branch:current"] and backing.removed == ["branch:behind"]
    assert validation.status == "green"


def test_live_github_backing_normalizes_branch_scope_and_label_evidence():
    repo = FakeRepo()
    backing = GitHubPullRequestBranchRefreshBackingProvider(
        github_client=FakeGithub(repo),
        request=request(),
        validation_executor=FakeValidationExecutor(),
        review_threads_reader=FakeReviewThreadsReader(),
    )
    branch = backing.read_branch("Blummer92/agent-os", 1363)
    assert branch.head_sha == OLD and branch.current_main_sha == MAIN
    assert branch.branch_state == "behind" and branch.mergeability == "mergeable"
    assert branch.changed_paths == ("scripts/example.py",)
    live = backing.read("Blummer92/agent-os", 1363)
    assert live.draft is True and live.behind is True and live.blocking_review_threads == 0
    assert live.labels == ("branch:behind",)
    backing.add_label("Blummer92/agent-os", 1363, "branch:current")
    backing.remove_label("Blummer92/agent-os", 1363, "branch:behind")
    assert repo.issue.added == ["branch:current"] and repo.issue.removed == ["branch:behind"]


def test_live_github_read_failure_is_fail_closed_unknown_not_authority():
    backing = GitHubPullRequestBranchRefreshBackingProvider(
        github_client=FakeGithub(fail=True),
        request=request(),
        validation_executor=FakeValidationExecutor(),
        review_threads_reader=FakeReviewThreadsReader(),
    )
    branch = backing.read_branch("Blummer92/agent-os", 1363)
    assert branch.branch_state == "unknown" and branch.mergeability == "unknown"
    assert branch.changed_paths == ()
    assert backing.available_labels("Blummer92/agent-os") == ()


def test_validation_failure_is_projected_for_existing_lifecycle_owner():
    backing = GitHubPullRequestBranchRefreshBackingProvider(
        github_client=FakeGithub(),
        request=request(),
        validation_executor=FakeValidationExecutor(status="failing"),
        review_threads_reader=FakeReviewThreadsReader(),
    )
    result = backing.run_required_validation("Blummer92/agent-os", 1363, head_sha=NEW, command_ids=("focused",))
    assert result.status == "failing"
