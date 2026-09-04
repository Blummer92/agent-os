from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from scripts.agent_os_github_git_objects import BranchUpdateObservation
from scripts.agent_os_issue_labels.pr_branch_refresh import (
    PullRequestBranchRefreshRequest,
    PullRequestBranchSnapshot,
    _admission_blocker,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
    preflight_production_branch_refresh,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_provider import (
    GitHubPullRequestBranchRefreshBackingProvider,
    ProductionPullRequestBranchRefreshProvider,
)

OLD = "1" * 40
BASE = MAIN = "2" * 40
MERGE_BASE = "0" * 40
MERGED_TREE = "3" * 40
NEW = "4" * 40
EPOCH = "1700000000"
PATH = "scripts/example.py"


def request() -> PullRequestBranchRefreshRequest:
    return PullRequestBranchRefreshRequest(
        repository="Blummer92/agent-os",
        pr_number=1849,
        base_branch="main",
        expected_base_sha=MAIN,
        expected_head_sha=OLD,
        current_main_sha=MAIN,
        authorization_id="refresh-1849",
        authorization_current=True,
        allowed_changed_paths=(PATH,),
        forbidden_paths=(),
        required_validation_command_ids=("focused",),
        branch_refresh_authorized=True,
        label_write_authorized=True,
    )


def snapshot(*, mergeability="conflicted", state="behind") -> PullRequestBranchSnapshot:
    return PullRequestBranchSnapshot(
        repository="Blummer92/agent-os",
        pr_number=1849,
        base_branch="main",
        base_sha=MAIN,
        head_branch="agent/1849",
        head_sha=OLD,
        current_main_sha=MAIN,
        branch_state=state,
        mergeability=mergeability,
        changed_paths=(PATH,),
    )


class Validation:
    def run_required_validation(self, *args, **kwargs):
        raise AssertionError("not used")


class Reviews:
    def blocking_review_threads(self, *args, **kwargs):
        return 0


class Pull:
    base = SimpleNamespace(ref="main")
    head = SimpleNamespace(ref="agent/1849", sha=OLD)
    mergeable = False
    mergeable_state = "dirty"
    draft = True

    def get_files(self):
        return [SimpleNamespace(filename=PATH)]


class Repo:
    def get_pull(self, number):
        return Pull()

    def get_branch(self, branch):
        return SimpleNamespace(commit=SimpleNamespace(sha=MAIN))

    def compare(self, base, head):
        return SimpleNamespace(status="diverged")

    def get_issue(self, number):
        return SimpleNamespace(labels=[])

    def get_labels(self):
        return []


class Github:
    def get_repo(self, repository):
        return Repo()


@dataclass
class Backing:
    branch: PullRequestBranchSnapshot = field(default_factory=snapshot)

    def read_branch(self, repository, pr_number):
        return self.branch

    def run_required_validation(self, *args, **kwargs):
        raise AssertionError("not used")

    def read(self, *args, **kwargs):
        raise AssertionError("not used")

    def available_labels(self, repository):
        return ()

    def add_label(self, *args, **kwargs):
        raise AssertionError("not used")

    def remove_label(self, *args, **kwargs):
        raise AssertionError("not used")


@dataclass
class Runner:
    observations: list[BranchUpdateObservation]
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def run(self, argv, *, cwd, env):
        self.calls.append(tuple(argv))
        return self.observations.pop(0)


def obs(stdout="", return_code=0):
    return BranchUpdateObservation(
        started=True,
        return_code=return_code,
        timed_out=False,
        termination_confirmed=True,
        stdout=stdout,
    )


def test_github_conflict_preserves_proven_diverged_branch_state():
    backing = GitHubPullRequestBranchRefreshBackingProvider(
        github_client=Github(),
        request=request(),
        validation_executor=Validation(),
        review_threads_reader=Reviews(),
    )
    result = backing.read_branch("Blummer92/agent-os", 1849)
    assert result.branch_state == "behind"
    assert result.mergeability == "conflicted"


def test_lifecycle_admits_conflicted_stale_branch_for_deterministic_provider():
    assert _admission_blocker(snapshot(), request()) is None
    assert _admission_blocker(snapshot(mergeability="unknown"), request()) == "branch.refresh-not-eligible"


def test_operator_preflight_does_not_veto_conflicted_stale_branch():
    result = preflight_production_branch_refresh(
        github_client=Github(),
        request=request(),
        repository_root="/workspace/agent-os",
    )
    assert result.ready is True
    assert "branch.mergeability-blocked" not in result.reason_codes


def test_conflicted_linear_history_uses_merge_tree_instead_of_rebase():
    runner = Runner([
        obs(f"{MERGE_BASE}\n"),
        obs(),
        obs(f"{MERGED_TREE}\n"),
        obs(f"{EPOCH}\n"),
        obs(f"{NEW}\n"),
        obs(),
        obs(f"{NEW}\n"),
        obs(f"{PATH}\n"),
        obs(f"{OLD}\trefs/heads/agent/1849\n"),
        obs(),
        obs(f"{NEW}\trefs/heads/agent/1849\n"),
    ])
    provider = ProductionPullRequestBranchRefreshProvider(
        backing=Backing(),
        runner=runner,
        repository_root="/workspace/agent-os",
        invocation_id="invocation-1849",
        authorization_id="refresh-1849",
        authorization_current=True,
        branch_update_authorized=True,
    )
    result = provider.rebase_onto_main(
        "Blummer92/agent-os",
        1849,
        expected_head_sha=OLD,
        expected_base_sha=MAIN,
        current_main_sha=MAIN,
    )
    assert result.status == "updated"
    assert ("git", "merge-tree", "--write-tree", MAIN, OLD) in runner.calls
    assert all("rebase" not in call for call in runner.calls)
    assert sum("push" in call for call in runner.calls) == 1


def test_true_merge_tree_conflict_is_bounded_and_never_pushes():
    runner = Runner([
        obs(f"{MERGE_BASE}\n"),
        obs(),
        obs(return_code=1),
    ])
    provider = ProductionPullRequestBranchRefreshProvider(
        backing=Backing(),
        runner=runner,
        repository_root="/workspace/agent-os",
        invocation_id="invocation-1849",
        authorization_id="refresh-1849",
        authorization_current=True,
        branch_update_authorized=True,
    )
    result = provider.rebase_onto_main(
        "Blummer92/agent-os",
        1849,
        expected_head_sha=OLD,
        expected_base_sha=MAIN,
        current_main_sha=MAIN,
    )
    assert result.status == "blocked"
    assert result.reason_code == "reconciliation.semantic-conflict"
    assert all("push" not in call for call in runner.calls)
