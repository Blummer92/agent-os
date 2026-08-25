from __future__ import annotations

from dataclasses import dataclass, field

from scripts.agent_os_github_git_objects import BranchUpdateObservation
from scripts.agent_os_issue_labels.pr_branch_refresh import (
    BranchRefreshValidationResult,
    PullRequestBranchSnapshot,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_provider import (
    ProductionPullRequestBranchRefreshProvider,
)
from scripts.agent_os_issue_labels.pr_reconciler import LivePullRequestSnapshot

OLD = "1" * 40
BASE = "2" * 40
MAIN = "3" * 40
NEW = "4" * 40


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
    runner = FakeRunner(
        [
            observation(),
            observation(stdout=f"{NEW}\n"),
            observation(stdout=f"{OLD}\trefs/heads/agent/1237-publication-required-continuation\n"),
            observation(),
            observation(stdout=f"{NEW}\trefs/heads/agent/1237-publication-required-continuation\n"),
        ]
    )

    result = invoke(provider(backing, runner))

    assert result.status == "updated"
    assert result.old_head_sha == OLD
    assert result.new_head_sha == NEW
    assert result.reason_code == "branch-updated"
    assert runner.calls[0][0] == (
        "git",
        "rebase",
        "--no-autostash",
        "--onto",
        MAIN,
        BASE,
        OLD,
    )
    assert runner.calls[1][0] == ("git", "rev-parse", "--verify", "HEAD^{commit}")
    assert runner.calls[2][0] == (
        "git",
        "ls-remote",
        "--heads",
        "origin",
        "refs/heads/agent/1237-publication-required-continuation",
    )
    assert runner.calls[3][0] == (
        "git",
        "push",
        f"--force-with-lease=refs/heads/agent/1237-publication-required-continuation:{OLD}",
        "origin",
        f"{NEW}:refs/heads/agent/1237-publication-required-continuation",
    )
    assert sum("push" in call[0] for call in runner.calls) == 1


def test_moved_head_blocks_before_any_git_command():
    backing = FakeBacking(snapshot(head="5" * 40))
    runner = FakeRunner([])

    result = invoke(provider(backing, runner))

    assert result.status == "blocked"
    assert result.reason_code == "head.moved-before-preparation"
    assert runner.calls == []


def test_moved_main_blocks_before_any_git_command():
    backing = FakeBacking(snapshot(main="6" * 40))
    runner = FakeRunner([])

    result = invoke(provider(backing, runner))

    assert result.status == "blocked"
    assert result.reason_code == "base.moved-before-preparation"
    assert runner.calls == []


def test_conflicted_branch_blocks_before_any_git_command():
    backing = FakeBacking(snapshot(mergeability="conflicted"))
    runner = FakeRunner([])

    result = invoke(provider(backing, runner))

    assert result.status == "blocked"
    assert result.reason_code == "branch.refresh-not-eligible-before-preparation"
    assert runner.calls == []


def test_rebase_failure_is_bounded_and_does_not_attempt_push():
    backing = FakeBacking(snapshot())
    runner = FakeRunner([observation(return_code=1)])

    result = invoke(provider(backing, runner))

    assert result.status == "blocked"
    assert result.reason_code == "rebase-rejected"
    assert len(runner.calls) == 1
    assert all("push" not in call[0] for call in runner.calls)


def test_rebase_timeout_is_ambiguous_and_does_not_retry():
    backing = FakeBacking(snapshot())
    runner = FakeRunner([observation(return_code=None, timed_out=True, termination_confirmed=False)])

    result = invoke(provider(backing, runner))

    assert result.status == "ambiguous"
    assert result.reason_code == "rebase-outcome-uncertain"
    assert len(runner.calls) == 1


def test_unproven_rebased_head_blocks_before_remote_transport():
    backing = FakeBacking(snapshot())
    runner = FakeRunner([observation(), observation(stdout="not-a-sha\n")])

    result = invoke(provider(backing, runner))

    assert result.status == "blocked"
    assert result.reason_code == "rebased-head-unavailable"
    assert len(runner.calls) == 2
    assert all("push" not in call[0] for call in runner.calls)


def test_transport_uncertainty_maps_to_ambiguous_without_retry():
    backing = FakeBacking(snapshot())
    runner = FakeRunner(
        [
            observation(),
            observation(stdout=f"{NEW}\n"),
            observation(stdout=f"{OLD}\trefs/heads/agent/1237-publication-required-continuation\n"),
            observation(return_code=None, timed_out=True, termination_confirmed=False),
        ]
    )

    result = invoke(provider(backing, runner))

    assert result.status == "ambiguous"
    assert result.reason_code == "transport.push-outcome-uncertain"
    assert sum("push" in call[0] for call in runner.calls) == 1


def test_label_and_validation_operations_delegate_to_existing_backing_provider():
    backing = FakeBacking(snapshot())
    subject = provider(backing, FakeRunner([]))

    subject.add_label("Blummer92/agent-os", 1363, "branch:current")
    subject.remove_label("Blummer92/agent-os", 1363, "branch:behind")
    validation = subject.run_required_validation(
        "Blummer92/agent-os",
        1363,
        head_sha=NEW,
        command_ids=("focused", "aggregate"),
    )

    assert backing.added == ["branch:current"]
    assert backing.removed == ["branch:behind"]
    assert validation.status == "green"
    assert backing.validation_calls == [
        ("Blummer92/agent-os", 1363, NEW, ("focused", "aggregate"))
    ]
