from __future__ import annotations

from dataclasses import dataclass, field
import os
import subprocess
from types import SimpleNamespace

from scripts.agent_os_github_git_objects import BranchUpdateObservation
from scripts.agent_os_issue_labels.pr_branch_refresh import (
    BranchRefreshValidationResult,
    PullRequestBranchRefreshRequest,
    PullRequestBranchSnapshot,
)
import scripts.agent_os_issue_labels.pr_branch_refresh_provider as provider_module
from scripts.agent_os_issue_labels.pr_branch_refresh_provider import (
    GitHubPullRequestBranchRefreshBackingProvider,
    ProductionPullRequestBranchRefreshProvider,
    run_production_pull_request_branch_refresh,
)
from scripts.agent_os_issue_labels.pr_reconciler import LivePullRequestSnapshot

OLD = "1" * 40
BASE = "2" * 40
MAIN = "3" * 40
NEW = "4" * 40
MERGED_TREE = "5" * 40
MERGE_COMMIT = "6" * 40
MERGE_BASE = "0" * 40
MAIN_EPOCH = "1700000000"


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
    assert runner.calls[1][0] == ("git", "rev-list", "--merges", f"{MERGE_BASE}..{OLD}")
    assert runner.calls[2][0] == ("git", "rebase", "--no-autostash", "--onto", MAIN, MERGE_BASE, OLD)
    assert all("merge-tree" not in call[0] for call in runner.calls)
    assert sum("push" in call[0] for call in runner.calls) == 1


def test_merge_shaped_candidate_uses_final_tree_and_expected_head_transport_once():
    backing = FakeBacking(snapshot())
    runner = FakeRunner([
        observation(stdout=f"{MERGE_BASE}\n"),
        observation(stdout=f"{MERGE_COMMIT}\n"),
        observation(stdout=f"{MERGED_TREE}\n"),
        observation(stdout=f"{MAIN_EPOCH}\n"),
        observation(stdout=f"{NEW}\n"),
        observation(),
        observation(stdout=f"{NEW}\n"),
        observation(stdout="scripts/example.py\n"),
        observation(stdout=f"{OLD}\trefs/heads/agent/1237-publication-required-continuation\n"),
        observation(),
        observation(stdout=f"{NEW}\trefs/heads/agent/1237-publication-required-continuation\n"),
    ])
    result = invoke(provider(
        backing,
        runner,
        environment={
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Untrusted Caller",
            "GIT_AUTHOR_EMAIL": "caller@example.invalid",
            "GIT_COMMITTER_NAME": "Different Caller",
            "GIT_COMMITTER_EMAIL": "different@example.invalid",
        },
    ))
    assert result.status == "updated"
    assert result.new_head_sha == NEW
    assert runner.calls[2][0] == ("git", "merge-tree", "--write-tree", MAIN, OLD)
    assert runner.calls[3][0] == ("git", "show", "-s", "--format=%ct", MAIN)
    assert runner.calls[4][0][:5] == ("git", "commit-tree", MERGED_TREE, "-p", MAIN)
    assert runner.calls[4][2]["GIT_AUTHOR_NAME"] == "Agent OS Branch Refresh"
    assert runner.calls[4][2]["GIT_AUTHOR_EMAIL"] == "agent-os-branch-refresh@localhost"
    assert runner.calls[4][2]["GIT_COMMITTER_NAME"] == "Agent OS Branch Refresh"
    assert runner.calls[4][2]["GIT_COMMITTER_EMAIL"] == "agent-os-branch-refresh@localhost"
    assert runner.calls[4][2]["GIT_AUTHOR_DATE"] == f"@{MAIN_EPOCH} +0000"
    assert runner.calls[4][2]["GIT_COMMITTER_DATE"] == f"@{MAIN_EPOCH} +0000"
    assert runner.calls[5][0] == ("git", "checkout", "--detach", NEW)
    assert runner.calls[7][0] == ("git", "diff", "--name-only", "--no-renames", MAIN, NEW)
    assert all("rebase" not in call[0] for call in runner.calls)
    assert sum("push" in call[0] for call in runner.calls) == 1


def test_merge_shaped_tree_conflict_blocks_without_transport_or_retry():
    runner = FakeRunner([
        observation(stdout=f"{MERGE_BASE}\n"),
        observation(stdout=f"{MERGE_COMMIT}\n"),
        observation(return_code=1),
    ])
    result = invoke(provider(FakeBacking(snapshot()), runner))
    assert result.reason_code == "topology-merge-tree-rejected"
    assert all("push" not in call[0] for call in runner.calls)
    assert len(runner.calls) == 3


def test_merge_shaped_uncertain_tree_blocks_without_transport():
    runner = FakeRunner([
        observation(stdout=f"{MERGE_BASE}\n"),
        observation(stdout=f"{MERGE_COMMIT}\n"),
        observation(return_code=None, timed_out=True, termination_confirmed=False),
    ])
    result = invoke(provider(FakeBacking(snapshot()), runner))
    assert result.status == "ambiguous"
    assert result.reason_code == "topology-merge-tree-outcome-uncertain"
    assert all("push" not in call[0] for call in runner.calls)


def test_merge_shaped_missing_main_timestamp_blocks_before_candidate_commit():
    runner = FakeRunner([
        observation(stdout=f"{MERGE_BASE}\n"),
        observation(stdout=f"{MERGE_COMMIT}\n"),
        observation(stdout=f"{MERGED_TREE}\n"),
        observation(stdout="not-a-timestamp\n"),
    ])
    result = invoke(provider(FakeBacking(snapshot()), runner))
    assert result.reason_code == "topology-main-timestamp-unavailable"
    assert all("commit-tree" not in call[0] for call in runner.calls)
    assert all("push" not in call[0] for call in runner.calls)


def test_merge_shaped_scope_mismatch_blocks_before_transport():
    runner = FakeRunner([
        observation(stdout=f"{MERGE_BASE}\n"),
        observation(stdout=f"{MERGE_COMMIT}\n"),
        observation(stdout=f"{MERGED_TREE}\n"),
        observation(stdout=f"{MAIN_EPOCH}\n"),
        observation(stdout=f"{NEW}\n"),
        observation(),
        observation(stdout=f"{NEW}\n"),
        observation(stdout="scripts/other.py\n"),
    ])
    result = invoke(provider(FakeBacking(snapshot()), runner))
    assert result.reason_code == "topology-candidate-scope-mismatch"
    assert all("push" not in call[0] for call in runner.calls)


def test_multiple_merge_commits_fail_closed_before_candidate_preparation():
    runner = FakeRunner([
        observation(stdout=f"{MERGE_BASE}\n"),
        observation(stdout=f"{MERGE_COMMIT}\n{'7' * 40}\n"),
    ])
    result = invoke(provider(FakeBacking(snapshot()), runner))
    assert result.reason_code == "topology-history-ambiguous"
    assert len(runner.calls) == 2
    assert all("merge-tree" not in call[0] for call in runner.calls)
    assert all("push" not in call[0] for call in runner.calls)


def test_ambiguous_topology_marker_fails_closed_before_candidate_preparation():
    runner = FakeRunner([
        observation(stdout=f"{MERGE_BASE}\n"),
        observation(stdout="not-a-sha\n"),
    ])
    result = invoke(provider(FakeBacking(snapshot()), runner))
    assert result.reason_code == "topology-history-ambiguous"
    assert len(runner.calls) == 2


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
    runner = FakeRunner([
        observation(stdout=f"{MERGE_BASE}\n"),
        observation(),
        observation(return_code=1),
    ])
    result = invoke(provider(FakeBacking(snapshot()), runner))
    assert result.reason_code == "rebase-rejected"
    assert all("push" not in call[0] for call in runner.calls)


def test_rebase_timeout_is_ambiguous_and_does_not_retry():
    runner = FakeRunner([
        observation(stdout=f"{MERGE_BASE}\n"),
        observation(),
        observation(return_code=None, timed_out=True, termination_confirmed=False),
    ])
    result = invoke(provider(FakeBacking(snapshot()), runner))
    assert result.status == "ambiguous" and len(runner.calls) == 3


def test_unproven_rebased_head_blocks_before_remote_transport():
    runner = FakeRunner([
        observation(stdout=f"{MERGE_BASE}\n"),
        observation(),
        observation(),
        observation(stdout="not-a-sha\n"),
    ])
    result = invoke(provider(FakeBacking(snapshot()), runner))
    assert result.reason_code == "rebased-head-unavailable"
    assert all("push" not in call[0] for call in runner.calls)


def test_transport_uncertainty_maps_to_ambiguous_without_retry():
    runner = FakeRunner([
        observation(stdout=f"{MERGE_BASE}\n"),
        observation(),
        observation(),
        observation(stdout=f"{NEW}\n"),
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
    live = backing.read("Blummer92/agent-os", 1363)
    assert live.mergeable is False and live.behind is False
    assert backing.available_labels("Blummer92/agent-os") == ()


def test_uncertain_branch_evidence_blocks_managed_label_catalog_before_write():
    repo = FakeRepo()
    repo.pull.mergeable = None
    repo.pull.mergeable_state = "unknown"
    backing = GitHubPullRequestBranchRefreshBackingProvider(
        github_client=FakeGithub(repo),
        request=request(),
        validation_executor=FakeValidationExecutor(),
        review_threads_reader=FakeReviewThreadsReader(),
    )
    live = backing.read("Blummer92/agent-os", 1363)
    assert live.mergeable is False
    assert backing.available_labels("Blummer92/agent-os") == ()
    assert repo.issue.added == [] and repo.issue.removed == []


def test_validation_failure_is_projected_for_existing_lifecycle_owner():
    backing = GitHubPullRequestBranchRefreshBackingProvider(
        github_client=FakeGithub(),
        request=request(),
        validation_executor=FakeValidationExecutor(status="failing"),
        review_threads_reader=FakeReviewThreadsReader(),
    )
    result = backing.run_required_validation("Blummer92/agent-os", 1363, head_sha=NEW, command_ids=("focused",))
    assert result.status == "failing"


def test_production_entrypoint_delegates_exactly_once_to_1187(monkeypatch):
    calls = []
    sentinel = object()

    def fake_refresh(provider, supplied_request):
        calls.append((provider, supplied_request))
        return sentinel

    monkeypatch.setattr(provider_module, "refresh_pull_request_branch", fake_refresh)
    supplied_request = request()
    runner = FakeRunner([])
    result = run_production_pull_request_branch_refresh(
        github_client=FakeGithub(),
        runner=runner,
        validation_executor=FakeValidationExecutor(),
        review_threads_reader=FakeReviewThreadsReader(),
        request=supplied_request,
        repository_root="/workspace/agent-os",
        invocation_id="invocation-1365",
        environment={"GIT_CONFIG_NOSYSTEM": "1"},
    )

    assert result is sentinel
    assert len(calls) == 1
    delegated_provider, delegated_request = calls[0]
    assert isinstance(delegated_provider, ProductionPullRequestBranchRefreshProvider)
    assert isinstance(delegated_provider.backing, GitHubPullRequestBranchRefreshBackingProvider)
    assert delegated_request is supplied_request
    assert delegated_provider.authorization_id == supplied_request.authorization_id
    assert delegated_provider.authorization_current is supplied_request.authorization_current
    assert delegated_provider.branch_update_authorized is supplied_request.branch_refresh_authorized
    assert runner.calls == []


@dataclass
class LocalGitRunner:
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def run(self, argv, *, cwd, env):
        self.calls.append(tuple(argv))
        try:
            completed = subprocess.run(
                list(argv),
                cwd=cwd,
                env=dict(env),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except subprocess.TimeoutExpired as error:
            return BranchUpdateObservation(
                started=True,
                return_code=None,
                timed_out=True,
                termination_confirmed=False,
                stdout=str(error.stdout or ""),
                stderr=str(error.stderr or ""),
            )
        return BranchUpdateObservation(
            started=True,
            return_code=completed.returncode,
            timed_out=False,
            termination_confirmed=True,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _git(repo, *args, check=True):
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if check and completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return completed


def _git_out(repo, *args):
    return _git(repo, *args).stdout.strip()


def test_merge_shaped_local_git_fixture_reproduces_old_rebase_rejection_and_v2_succeeds(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Agent OS Test")
    _git(repo, "config", "user.email", "agent-os-test@example.invalid")

    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-qm", "base")
    base = _git_out(repo, "rev-parse", "HEAD")

    _git(repo, "switch", "-qc", "feature-a")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "example.py").write_text("A\n", encoding="utf-8")
    _git(repo, "add", "scripts/example.py")
    _git(repo, "commit", "-qm", "feature A")
    feature_a = _git_out(repo, "rev-parse", "HEAD")

    _git(repo, "switch", "-qc", "feature-b", base)
    (repo / "scripts").mkdir(exist_ok=True)
    (repo / "scripts" / "example.py").write_text("B\n", encoding="utf-8")
    _git(repo, "add", "scripts/example.py")
    _git(repo, "commit", "-qm", "feature B")
    feature_b = _git_out(repo, "rev-parse", "HEAD")

    tree_b = _git_out(repo, "rev-parse", f"{feature_b}^{{tree}}")
    reconciled = _git_out(
        repo,
        "commit-tree",
        tree_b,
        "-p",
        feature_a,
        "-p",
        feature_b,
        "-m",
        "reconcile selected B",
    )
    _git(repo, "reset", "-q", "--hard", reconciled)
    (repo / "scripts" / "example.py").write_text("B\nrepair\n", encoding="utf-8")
    _git(repo, "add", "scripts/example.py")
    _git(repo, "commit", "-qm", "repair")
    feature_head = _git_out(repo, "rev-parse", "HEAD")

    _git(repo, "switch", "-qc", "main-new", base)
    (repo / "main.txt").write_text("main\n", encoding="utf-8")
    _git(repo, "add", "main.txt")
    _git(repo, "commit", "-qm", "main advance")
    current_main = _git_out(repo, "rev-parse", "HEAD")
    merge_base = _git_out(repo, "merge-base", feature_head, current_main)

    _git(repo, "checkout", "-q", "--detach", feature_head)
    old_rebase = _git(
        repo,
        "rebase",
        "--no-autostash",
        "--onto",
        current_main,
        merge_base,
        feature_head,
        check=False,
    )
    assert old_rebase.returncode != 0
    _git(repo, "rebase", "--abort")

    live = PullRequestBranchSnapshot(
        repository="Blummer92/agent-os",
        pr_number=1397,
        base_branch="main",
        base_sha=current_main,
        head_branch="agent/1387-governed-visual-identity",
        head_sha=feature_head,
        current_main_sha=current_main,
        branch_state="behind",
        mergeability="mergeable",
        changed_paths=("scripts/example.py",),
    )
    subject = ProductionPullRequestBranchRefreshProvider(
        backing=FakeBacking(live),
        runner=LocalGitRunner(),
        repository_root=str(repo),
        invocation_id="invocation-1463",
        authorization_id="authorization-1463",
        authorization_current=True,
        branch_update_authorized=True,
        environment=dict(os.environ),
    )
    candidate = subject._prepare_merge_shaped_candidate(
        expected_head_sha=feature_head,
        current_main_sha=current_main,
        admitted_paths=live.changed_paths,
    )

    assert isinstance(candidate, str)
    assert _git_out(repo, "rev-parse", f"{candidate}^1") == current_main
    assert _git_out(repo, "diff", "--name-only", "--no-renames", current_main, candidate) == "scripts/example.py"
    assert (repo / "scripts" / "example.py").read_text(encoding="utf-8") == "B\nrepair\n"
