from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import workflow_scheduler.execution.git_worktree_adapter as module
from scripts.agent_os_execution_capabilities.models import RepositoryIdentity
from workflow_scheduler.execution.git_worktree_adapter import (
    GitObservation,
    GitWorktreeAdapter,
    GitWorktreeAdapterError,
    WorkspacePreparationRequest,
)
from workflow_scheduler.execution.single_issue_pilot import (
    WorkspaceAdapter,
    WorkspaceHandle,
    WorkspaceRequest,
    pilot_workspace_identity,
)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_TERMINAL_PROMPT": "0",
        },
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, Path, WorkspaceRequest]:
    root, parent = tmp_path / "repo", tmp_path / "worktrees"
    root.mkdir()
    parent.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Agent OS Tests")
    git(root, "config", "user.email", "tests@example.invalid")
    (root / "README.md").write_text("initial\n")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "initial")
    git(root, "branch", "agent/596-work")
    request = WorkspaceRequest(
        workspace_request_id="workspace-596",
        repository="Blummer92/agent-os",
        branch="agent/596-work",
        expected_revision=git(root, "rev-parse", "agent/596-work"),
    )
    return root, parent, request


def identity() -> RepositoryIdentity:
    return RepositoryIdentity(
        host="github.com",
        owner="Blummer92",
        repository="agent-os",
        repository_id=1289370915,
        default_branch="main",
    )


def adapter(root: Path, parent: Path, **kwargs: object) -> GitWorktreeAdapter:
    return GitWorktreeAdapter(
        repository_root=str(root),
        workspace_parent=str(parent),
        repository_identity=identity(),
        **kwargs,
    )


def created(repo: tuple[Path, Path, WorkspaceRequest]):
    root, parent, request = repo
    instance = adapter(root, parent)
    handle = instance.create(request)
    assert handle.created
    return instance, request, handle, Path(instance.workspace_path or "")


def test_clean_lifecycle_protocol_and_canonical_validation(repo, monkeypatch) -> None:
    calls: list[object] = []
    original = module.validate_repository_state_evidence

    def tracking(value: object, **kwargs: object) -> object:
        calls.append((value, kwargs))
        return original(value, **kwargs)

    monkeypatch.setattr(module, "validate_repository_state_evidence", tracking)
    instance, request, handle, path = created(repo)
    assert isinstance(instance, WorkspaceAdapter)
    assert handle.workspace_identity == pilot_workspace_identity(request)
    inspection = instance.inspect(handle)
    assert inspection.resolved and inspection.clean and inspection.locked_expected
    assert inspection.branch == request.branch
    assert inspection.actual_revision == request.expected_revision
    assert len(calls) == 1
    cleanup = instance.cleanup(handle)
    assert cleanup.filesystem_removed and cleanup.metadata_removed
    assert cleanup.path_absent and not cleanup.force_required and not path.exists()


def test_create_fails_before_mutation_for_revision_repository_and_reuse(repo) -> None:
    root, parent, request = repo
    wrong_revision = WorkspaceRequest(
        workspace_request_id=request.workspace_request_id,
        repository=request.repository,
        branch=request.branch,
        expected_revision="f" * 40,
    )
    result = adapter(root, parent).create(wrong_revision)
    assert not result.created and "revision" in result.reason
    assert not tuple(parent.iterdir())

    wrong_repo = WorkspaceRequest(
        workspace_request_id=request.workspace_request_id,
        repository="other/repository",
        branch=request.branch,
        expected_revision=request.expected_revision,
    )
    with pytest.raises(GitWorktreeAdapterError, match="repository"):
        adapter(root, parent).create(wrong_repo)

    full_ref = WorkspaceRequest(
        workspace_request_id=request.workspace_request_id,
        repository=request.repository,
        branch="refs/heads/agent/596-work",
        expected_revision=request.expected_revision,
    )
    with pytest.raises(GitWorktreeAdapterError, match="short name"):
        adapter(root, parent).create(full_ref)

    external = parent / "external"
    git(root, "worktree", "add", str(external), request.branch)
    reused = adapter(root, parent).create(request)
    assert not reused.created and "already in use" in reused.reason


def test_create_is_one_shot(repo) -> None:
    root, parent, request = repo
    instance = adapter(root, parent)
    assert instance.create(request).created
    with pytest.raises(RuntimeError, match="at most once"):
        instance.create(request)


@pytest.mark.parametrize("state", ["dirty", "detached", "wrong-revision", "wrong-lock"])
def test_inspection_fails_closed_for_unsafe_states(repo, state: str) -> None:
    root, _, _ = repo
    instance, _, handle, path = created(repo)
    if state == "dirty":
        (path / "dirty.txt").write_text("dirty\n")
    elif state == "detached":
        git(path, "checkout", "--detach")
    elif state == "wrong-revision":
        (path / "next.txt").write_text("next\n")
        git(path, "add", "next.txt")
        git(path, "commit", "-m", "move")
    else:
        git(root, "worktree", "unlock", str(path))
        git(root, "worktree", "lock", "--reason", "other", str(path))
    inspection = instance.inspect(handle)
    assert not inspection.resolved
    assert inspection.reason
    if state == "dirty":
        cleanup = instance.cleanup(handle)
        assert not cleanup.filesystem_removed and "non-force" in cleanup.reason
        assert "locked agent-os:" in git(root, "worktree", "list", "--porcelain")


def test_filesystem_and_metadata_divergence_remain_independent(repo) -> None:
    instance, _, handle, path = created(repo)
    shutil.rmtree(path)
    inspection = instance.inspect(handle)
    assert not inspection.resolved and inspection.missing
    cleanup = instance.cleanup(handle)
    assert cleanup.path_absent
    assert not cleanup.filesystem_removed

    instance, _, handle, path = created(repo)
    admin = Path((path / ".git").read_text().strip().removeprefix("gitdir: "))
    shutil.rmtree(admin)
    cleanup = instance.cleanup(handle)
    assert path.exists() and not cleanup.path_absent
    assert not cleanup.filesystem_removed and not cleanup.metadata_removed


def test_cleanup_is_exactly_once_and_refuses_unbound_handle(repo) -> None:
    root, parent, _ = repo
    instance, _, handle, _ = created(repo)
    assert instance.cleanup(handle).metadata_removed
    with pytest.raises(RuntimeError, match="at most once"):
        instance.cleanup(handle)
    forged = WorkspaceHandle(created=True, workspace_identity="forged")
    with pytest.raises(GitWorktreeAdapterError, match="no created workspace"):
        adapter(root, parent).cleanup(forged)


class RecordingRunner:
    def __init__(self, observations: list[GitObservation]) -> None:
        self.observations = list(observations)
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv, **kwargs) -> GitObservation:
        self.calls.append(tuple(argv))
        if not self.observations:
            raise AssertionError("unexpected retry")
        return self.observations.pop(0)


def success(stdout: str = "") -> GitObservation:
    return GitObservation(
        started=True,
        return_code=0,
        timed_out=False,
        termination_confirmed=True,
        stdout=stdout,
    )


def test_timeout_is_bounded_and_not_retried(repo) -> None:
    root, parent, request = repo
    runner = RecordingRunner(
        [
            GitObservation(
                started=True,
                return_code=None,
                timed_out=True,
                termination_confirmed=False,
            )
        ]
    )
    result = adapter(root, parent, runner=runner).create(request)
    assert not result.created and len(runner.calls) == 1


def test_partial_creation_is_bound_for_cleanup_evidence(repo) -> None:
    root, parent, request = repo
    workspace_identity = pilot_workspace_identity(request)
    suffix = module.hashlib.sha256(workspace_identity.encode()).hexdigest()[:24]
    path = parent / f"agent-os-worktree-{suffix}"
    primary = (
        f"worktree {root}\x00HEAD {request.expected_revision}\x00"
        "branch refs/heads/main\x00\x00"
    )
    partial = primary + (
        f"worktree {path}\x00HEAD {request.expected_revision}\x00"
        f"branch refs/heads/{request.branch}\x00"
        f"locked agent-os:{workspace_identity}\x00\x00"
    )
    runner = RecordingRunner(
        [
            success(request.branch + "\n"),
            success(request.expected_revision + "\n"),
            success(primary),
            GitObservation(
                started=True,
                return_code=1,
                timed_out=False,
                termination_confirmed=True,
            ),
            success(partial),
        ]
    )
    instance = adapter(root, parent, runner=runner)
    handle = instance.create(request)
    assert handle.created and "partial" in handle.reason
    assert instance.workspace_path == str(path) and len(runner.calls) == 5


@pytest.mark.parametrize(
    "text,match",
    [
        ("worktree /tmp/w\x00branch refs/heads/x\x00\x00", "required"),
        (
            "worktree relative\x00HEAD "
            + "a" * 40
            + "\x00branch refs/heads/x\x00\x00",
            "absolute",
        ),
        (
            "worktree /tmp/w\x00HEAD bad\x00branch refs/heads/x\x00\x00",
            "HEAD",
        ),
        (
            "worktree /tmp/w\x00HEAD "
            + "a" * 40
            + "\x00branch refs/heads/x\x00detached\x00\x00",
            "ambiguous",
        ),
        (
            "worktree /tmp/w\x00HEAD "
            + "a" * 40
            + "\x00branch refs/heads/x\x00unknown x\x00\x00",
            "unsupported",
        ),
    ],
)
def test_porcelain_parser_rejects_malformed_evidence(text: str, match: str) -> None:
    with pytest.raises(GitWorktreeAdapterError, match=match):
        module._parse_porcelain(text)


def test_porcelain_parser_rejects_duplicate_fields_and_records() -> None:
    duplicate_field = (
        "worktree /tmp/w\x00HEAD "
        + "a" * 40
        + "\x00HEAD "
        + "b" * 40
        + "\x00branch refs/heads/x\x00\x00"
    )
    with pytest.raises(GitWorktreeAdapterError, match="duplicate field"):
        module._parse_porcelain(duplicate_field)
    record = (
        "worktree /tmp/w\x00HEAD "
        + "a" * 40
        + "\x00branch refs/heads/x\x00locked reason\x00\x00"
    )
    with pytest.raises(GitWorktreeAdapterError, match="duplicated"):
        module._parse_porcelain(record + record)


def test_porcelain_parser_preserves_lock_and_prunable_evidence() -> None:
    text = (
        "worktree /tmp/w\x00HEAD "
        + "a" * 40
        + "\x00branch refs/heads/x\x00locked agent-os\x00"
        + "prunable missing gitdir\x00\x00"
    )
    (record,) = module._parse_porcelain(text)
    assert record.locked and record.lock_reason == "agent-os"
    assert record.prunable and record.prunable_reason == "missing gitdir"


def test_configuration_bounds_and_malformed_unicode(repo) -> None:
    root, parent, _ = repo
    with pytest.raises(GitWorktreeAdapterError, match="timeout"):
        adapter(root, parent, timeout_seconds=float("nan"))
    with pytest.raises(GitWorktreeAdapterError, match="output"):
        adapter(root, parent, max_output_bytes=module.MAX_GIT_OUTPUT_BYTES + 1)
    with pytest.raises(GitWorktreeAdapterError, match="UTF-8"):
        adapter(root, parent, git_binary="git\ud800")
    with pytest.raises(GitWorktreeAdapterError, match="environment"):
        adapter(root, parent, environment={"BAD=KEY": "value"})
    with pytest.raises(GitWorktreeAdapterError, match="protected"):
        adapter(root, parent, environment={"GIT_TERMINAL_PROMPT": "1"})


def test_architecture_boundaries_and_no_force_or_prune() -> None:
    source = Path(module.__file__).read_text()
    tree = ast.parse(source)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert not imports & {
        "subprocess",
        "signal",
        "threading",
        "multiprocessing",
        "asyncio",
        "queue",
        "requests",
        "urllib",
        "github",
    }
    assert '"prune"' not in source
    assert '"--force"' not in source
    assert "shell=True" not in source
    assert "workflow_dispatch" not in source

def preparation_request(
    *,
    workspace_request_id: str,
    requested_ref: str,
    expected_revision: str,
    mode: str,
) -> WorkspacePreparationRequest:
    return WorkspacePreparationRequest(
        workspace_request_id=workspace_request_id,
        repository="Blummer92/agent-os",
        requested_ref=requested_ref,
        expected_revision=expected_revision,
        mode=mode,
    )


def preparation_contract(instance, request):
    identity, path, requested_ref, resolved_ref = instance._bind_preparation(request)
    fingerprint = instance._preparation_contract_fingerprint(
        mode=request.mode,
        requested_ref=requested_ref,
        resolved_ref=resolved_ref,
        exact_sha=request.expected_revision,
    )
    return identity, path, requested_ref, resolved_ref, f"agent-os:{identity}:{fingerprint}"


def preparation_prefix_observations(mode: str, sha: str) -> list[GitObservation]:
    if mode in ("branch", "tag"):
        return [success(), success(sha + "\n"), success(sha + "\n")]
    return [success(sha + "\n")]


def worktree_record(
    path: str | Path,
    sha: str,
    *,
    branch: str | None = None,
    detached: bool = False,
    lock_reason: str | None = None,
    prunable: bool = False,
) -> str:
    mode = "detached\x00" if detached else f"branch {branch}\x00"
    locked = "" if lock_reason is None else f"locked {lock_reason}\x00"
    stale = "prunable missing gitdir\x00" if prunable else ""
    return f"worktree {path}\x00HEAD {sha}\x00{mode}{locked}{stale}\x00"


def test_prepare_attached_branch_success(repo) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "agent/596-work")
    request = preparation_request(
        workspace_request_id="prep-596",
        requested_ref="agent/596-work",
        expected_revision=sha,
        mode="branch",
    )
    result = adapter(root, parent).prepare(request)
    assert result.outcome == "prepared"
    assert result.exact_sha == sha
    assert result.side_effect_state == "verified-prepared"
    assert not result.reused and result.locked and result.clean
    assert git(Path(result.path), "symbolic-ref", "--short", "HEAD") == request.requested_ref


def test_prepare_lightweight_tag_and_movement(repo) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "HEAD")
    git(root, "tag", "v1.0.0", sha)
    request = preparation_request(
        workspace_request_id="prep-tag",
        requested_ref="v1.0.0",
        expected_revision=sha,
        mode="tag",
    )
    first = adapter(root, parent).prepare(request)
    assert first.outcome == "prepared"
    assert git(Path(first.path), "rev-parse", "HEAD") == sha
    assert git(Path(first.path), "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"

    (root / "move.txt").write_text("move\n")
    git(root, "add", "move.txt")
    git(root, "commit", "-m", "move-commit")
    new_sha = git(root, "rev-parse", "HEAD")
    git(root, "tag", "-f", "v1.0.0", new_sha)
    moved = preparation_request(
        workspace_request_id="prep-tag",
        requested_ref="v1.0.0",
        expected_revision=new_sha,
        mode="tag",
    )
    second = adapter(root, parent).prepare(moved)
    assert second.outcome == "manual-review"
    assert "conflicts" in second.reason


def test_prepare_annotated_tag_success(repo) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "HEAD")
    git(root, "tag", "-a", "v2.0.0", "-m", "version 2", sha)
    request = preparation_request(
        workspace_request_id="prep-annotated",
        requested_ref="v2.0.0",
        expected_revision=sha,
        mode="tag",
    )
    result = adapter(root, parent).prepare(request)
    assert result.outcome == "prepared"
    assert result.exact_sha == sha


def test_prepare_branch_tag_short_name_ambiguity_is_exact(repo) -> None:
    root, parent, _ = repo
    branch_sha = git(root, "rev-parse", "HEAD")
    git(root, "branch", "ambiguous")
    (root / "other.txt").write_text("other\n")
    git(root, "add", "other.txt")
    git(root, "commit", "-m", "other-commit")
    tag_sha = git(root, "rev-parse", "HEAD")
    git(root, "tag", "ambiguous", tag_sha)

    branch_result = adapter(root, parent).prepare(
        preparation_request(
            workspace_request_id="prep-br",
            requested_ref="ambiguous",
            expected_revision=branch_sha,
            mode="branch",
        )
    )
    assert branch_result.outcome == "prepared"
    assert branch_result.exact_sha == branch_sha
    assert git(Path(branch_result.path), "symbolic-ref", "HEAD") == "refs/heads/ambiguous"

    tag_result = adapter(root, parent).prepare(
        preparation_request(
            workspace_request_id="prep-tg",
            requested_ref="ambiguous",
            expected_revision=tag_sha,
            mode="tag",
        )
    )
    assert tag_result.outcome == "prepared"
    assert tag_result.exact_sha == tag_sha
    assert git(Path(tag_result.path), "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"


@pytest.mark.parametrize("mode,bad_ref", [("branch", "main^"), ("tag", "v1~1")])
def test_prepare_rejects_revision_expression_refs(repo, mode: str, bad_ref: str) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "main")
    git(root, "tag", "v1", sha)
    result = adapter(root, parent).prepare(
        preparation_request(
            workspace_request_id=f"bad-{mode}",
            requested_ref=bad_ref,
            expected_revision=sha,
            mode=mode,
        )
    )
    assert result.outcome == "blocked"
    assert "exact valid Git ref" in result.reason
    assert not tuple(parent.iterdir())


def test_prepare_detached_sha_validation(repo) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "main")
    valid = preparation_request(
        workspace_request_id="prep-sha",
        requested_ref=sha,
        expected_revision=sha,
        mode="detached-sha",
    )
    result = adapter(root, parent).prepare(valid)
    assert result.outcome == "prepared"
    assert result.exact_sha == sha

    for bad_ref in (sha.upper(), sha[:10], "not-a-sha", ""):
        bad = preparation_request(
            workspace_request_id="prep-bad-sha",
            requested_ref=bad_ref,
            expected_revision=sha,
            mode="detached-sha",
        )
        blocked = adapter(root, parent).prepare(bad)
        assert blocked.outcome == "blocked"

    missing_expected = preparation_request(
        workspace_request_id="missing-expected",
        requested_ref=sha,
        expected_revision="",
        mode="detached-sha",
    )
    assert adapter(root, parent).prepare(missing_expected).outcome == "blocked"

    unresolved = preparation_request(
        workspace_request_id="unresolved-sha",
        requested_ref="f" * 40,
        expected_revision="f" * 40,
        mode="detached-sha",
    )
    assert adapter(root, parent).prepare(unresolved).outcome == "unavailable"


def test_prepare_detached_contradictory_sha_routes_manual_review(repo) -> None:
    root, parent, _ = repo
    old_sha = git(root, "rev-parse", "HEAD")
    (root / "next.txt").write_text("next\n")
    git(root, "add", "next.txt")
    git(root, "commit", "-m", "next")
    new_sha = git(root, "rev-parse", "HEAD")
    result = adapter(root, parent).prepare(
        preparation_request(
            workspace_request_id="contradictory",
            requested_ref=old_sha,
            expected_revision=new_sha,
            mode="detached-sha",
        )
    )
    assert result.outcome == "manual-review"


@pytest.mark.parametrize("mode", ["branch", "tag", "detached-sha"])
def test_prepare_exact_idempotent_reuse(repo, mode: str) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "main")
    requested_ref = "agent/596-work"
    if mode == "tag":
        requested_ref = "reuse-tag"
        git(root, "tag", requested_ref, sha)
    elif mode == "detached-sha":
        requested_ref = sha
    request = preparation_request(
        workspace_request_id=f"reuse-{mode}",
        requested_ref=requested_ref,
        expected_revision=sha,
        mode=mode,
    )
    first = adapter(root, parent).prepare(request)
    second = adapter(root, parent).prepare(request)
    assert first.outcome == "prepared"
    assert second.outcome == "already-prepared"
    assert second.reused and second.clean and second.locked
    assert second.side_effect_state == "verified-reused"


@pytest.mark.parametrize("conflict", ["tag-ref", "mode"])
def test_prepare_same_logical_identity_contract_conflict_is_manual_review(
    repo, conflict: str
) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "main")
    git(root, "tag", "contract-v1", sha)
    git(root, "tag", "contract-v2", sha)
    first = preparation_request(
        workspace_request_id="same-contract-id",
        requested_ref="contract-v1",
        expected_revision=sha,
        mode="tag",
    )
    assert adapter(root, parent).prepare(first).outcome == "prepared"
    second = preparation_request(
        workspace_request_id="same-contract-id",
        requested_ref="contract-v2" if conflict == "tag-ref" else sha,
        expected_revision=sha,
        mode="tag" if conflict == "tag-ref" else "detached-sha",
    )
    result = adapter(root, parent).prepare(second)
    assert result.outcome == "manual-review"
    assert "conflicts" in result.reason


def test_prepare_same_logical_identity_conflicting_sha_is_manual_review(repo) -> None:
    root, parent, _ = repo
    old_sha = git(root, "rev-parse", "HEAD")
    first = preparation_request(
        workspace_request_id="same-sha-id",
        requested_ref=old_sha,
        expected_revision=old_sha,
        mode="detached-sha",
    )
    assert adapter(root, parent).prepare(first).outcome == "prepared"
    (root / "new.txt").write_text("new\n")
    git(root, "add", "new.txt")
    git(root, "commit", "-m", "new")
    new_sha = git(root, "rev-parse", "HEAD")
    second = preparation_request(
        workspace_request_id="same-sha-id",
        requested_ref=new_sha,
        expected_revision=new_sha,
        mode="detached-sha",
    )
    assert adapter(root, parent).prepare(second).outcome == "manual-review"


def test_prepare_branch_claimed_elsewhere_is_blocked(repo) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "agent/596-work")
    first = preparation_request(
        workspace_request_id="branch-owner-1",
        requested_ref="agent/596-work",
        expected_revision=sha,
        mode="branch",
    )
    second = preparation_request(
        workspace_request_id="branch-owner-2",
        requested_ref="agent/596-work",
        expected_revision=sha,
        mode="branch",
    )
    assert adapter(root, parent).prepare(first).outcome == "prepared"
    result = adapter(root, parent).prepare(second)
    assert result.outcome == "blocked"
    assert "branch" in result.reason


@pytest.mark.parametrize("state", ["dirty", "unlocked", "wrong-lock"])
def test_prepare_reuse_fails_closed_for_worktree_state(repo, state: str) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "agent/596-work")
    request = preparation_request(
        workspace_request_id=f"reuse-state-{state}",
        requested_ref="agent/596-work",
        expected_revision=sha,
        mode="branch",
    )
    first = adapter(root, parent).prepare(request)
    assert first.outcome == "prepared"
    path = Path(first.path)
    if state == "dirty":
        (path / "dirty.txt").write_text("dirty\n")
    else:
        git(root, "worktree", "unlock", str(path))
        if state == "wrong-lock":
            git(root, "worktree", "lock", "--reason", "other", str(path))
    result = adapter(root, parent).prepare(request)
    assert result.outcome == "blocked"


def test_prepare_prunable_reuse_is_blocked(repo) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "main")
    request = preparation_request(
        workspace_request_id="prunable-reuse",
        requested_ref=sha,
        expected_revision=sha,
        mode="detached-sha",
    )
    instance = adapter(root, parent)
    identity, path, _, resolved_ref, lock_reason = preparation_contract(instance, request)
    primary = worktree_record(root, sha, branch="refs/heads/main")
    stale = worktree_record(
        path, sha, detached=True, lock_reason=lock_reason, prunable=True
    )
    runner = RecordingRunner([success(sha + "\n"), success(primary + stale)])
    result = adapter(root, parent, runner=runner).prepare(request)
    assert result.outcome == "blocked"
    assert "metadata" in result.reason or "collision" in result.reason


def test_prepare_duplicate_logical_identity_metadata_is_blocked(repo) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "main")
    request = preparation_request(
        workspace_request_id="duplicate-identity",
        requested_ref=sha,
        expected_revision=sha,
        mode="detached-sha",
    )
    instance = adapter(root, parent)
    identity, path, _, _, lock_reason = preparation_contract(instance, request)
    primary = worktree_record(root, sha, branch="refs/heads/main")
    duplicate = worktree_record(path, sha, detached=True, lock_reason=lock_reason)
    other = worktree_record(
        parent / "other", sha, detached=True, lock_reason=lock_reason
    )
    runner = RecordingRunner([success(sha + "\n"), success(primary + duplicate + other)])
    result = adapter(root, parent, runner=runner).prepare(request)
    assert result.outcome == "blocked"
    assert "duplicate" in result.reason


def test_prepare_symlink_and_normalized_path_escape_are_rejected(repo, monkeypatch) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "main")
    request = preparation_request(
        workspace_request_id="path-safety",
        requested_ref="main",
        expected_revision=sha,
        mode="branch",
    )
    probe = adapter(root, parent)
    _, path, _, _ = probe._bind_preparation(request)
    outside = parent.parent / "outside"
    outside.mkdir()
    Path(path).symlink_to(outside, target_is_directory=True)
    assert adapter(root, parent).prepare(request).outcome == "blocked"
    Path(path).unlink()

    escaped_path = str(outside / "escaped")
    with monkeypatch.context() as patch:
        patch.setattr(module.os.path, "join", lambda *_: escaped_path)
        escaped = adapter(root, parent).prepare(request)
    assert escaped.outcome == "blocked"
    assert "escape" in escaped.reason


def test_prepare_failed_creation_with_no_workspace_is_truthful(repo) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "agent/596-work")
    request = preparation_request(
        workspace_request_id="no-partial",
        requested_ref="agent/596-work",
        expected_revision=sha,
        mode="branch",
    )
    primary = worktree_record(root, sha, branch="refs/heads/main")
    runner = RecordingRunner(
        preparation_prefix_observations("branch", sha)
        + [
            success(primary),
            GitObservation(
                started=True,
                return_code=1,
                timed_out=False,
                termination_confirmed=True,
                reason="failed",
            ),
            success(primary),
        ]
    )
    instance = adapter(root, parent, runner=runner)
    result = instance.prepare(request)
    assert result.outcome == "unavailable"
    assert result.side_effect_state == "creation-attempted-no-workspace"
    assert not result.locked
    with pytest.raises(GitWorktreeAdapterError, match="no created workspace"):
        instance.cleanup(WorkspaceHandle(created=True, workspace_identity=result.workspace_identity))


@pytest.mark.parametrize("partial_state", ["path-only", "unlocked", "wrong-lock"])
def test_prepare_unsafe_partial_creation_is_not_bound(
    repo, monkeypatch, partial_state: str
) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "agent/596-work")
    request = preparation_request(
        workspace_request_id=f"partial-{partial_state}",
        requested_ref="agent/596-work",
        expected_revision=sha,
        mode="branch",
    )
    probe = adapter(root, parent)
    identity, path, _, resolved_ref, lock_reason = preparation_contract(probe, request)
    primary = worktree_record(root, sha, branch="refs/heads/main")
    partial = primary
    if partial_state == "unlocked":
        partial += worktree_record(path, sha, branch=resolved_ref)
    elif partial_state == "wrong-lock":
        partial += worktree_record(path, sha, branch=resolved_ref, lock_reason="other")
    observations = preparation_prefix_observations("branch", sha) + [
        success(primary),
        GitObservation(
            started=True,
            return_code=1,
            timed_out=False,
            termination_confirmed=True,
            reason="failed",
        ),
        success(partial),
    ]
    if partial_state == "path-only":
        calls = iter((False, True))
        monkeypatch.setattr(module.os.path, "lexists", lambda _path: next(calls))
    instance = adapter(root, parent, runner=RecordingRunner(observations))
    result = instance.prepare(request)
    assert result.side_effect_state == "partial-creation-observed"
    assert not result.locked
    with pytest.raises(GitWorktreeAdapterError, match="no created workspace"):
        instance.cleanup(WorkspaceHandle(created=True, workspace_identity=identity))


@pytest.mark.parametrize("mode", ["branch", "tag", "detached-sha"])
def test_prepare_safe_partial_creation_preserves_cleanup(repo, mode: str) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "main")
    requested_ref = "agent/596-work"
    if mode == "tag":
        requested_ref = "partial-tag"
    elif mode == "detached-sha":
        requested_ref = sha
    request = preparation_request(
        workspace_request_id=f"safe-partial-{mode}",
        requested_ref=requested_ref,
        expected_revision=sha,
        mode=mode,
    )
    probe = adapter(root, parent)
    identity, path, _, resolved_ref, lock_reason = preparation_contract(probe, request)
    primary = worktree_record(root, sha, branch="refs/heads/main")
    target = worktree_record(
        path,
        sha,
        branch=resolved_ref if mode == "branch" else None,
        detached=mode != "branch",
        lock_reason=lock_reason,
    )
    unlocked = worktree_record(
        path,
        sha,
        branch=resolved_ref if mode == "branch" else None,
        detached=mode != "branch",
    )
    runner = RecordingRunner(
        preparation_prefix_observations(mode, sha)
        + [
            success(primary),
            GitObservation(
                started=True,
                return_code=1,
                timed_out=False,
                termination_confirmed=True,
                reason="failed",
            ),
            success(primary + target),
            success(primary + target),
            success(),
            success(primary + unlocked),
            success(),
            success(primary),
        ]
    )
    instance = adapter(root, parent, runner=runner)
    result = instance.prepare(request)
    assert result.outcome == "unavailable"
    assert result.side_effect_state == "partial-creation-observed"
    assert result.locked
    cleanup = instance.cleanup(
        WorkspaceHandle(created=True, workspace_identity=identity)
    )
    assert cleanup.metadata_removed and cleanup.path_absent


@pytest.mark.parametrize("mode", ["tag", "detached-sha"])
def test_prepare_detached_successful_cleanup(repo, mode: str) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "main")
    requested_ref = "cleanup-tag" if mode == "tag" else sha
    if mode == "tag":
        git(root, "tag", requested_ref, sha)
    request = preparation_request(
        workspace_request_id=f"cleanup-{mode}",
        requested_ref=requested_ref,
        expected_revision=sha,
        mode=mode,
    )
    instance = adapter(root, parent)
    result = instance.prepare(request)
    assert result.outcome == "prepared"
    cleanup = instance.cleanup(
        WorkspaceHandle(created=True, workspace_identity=result.workspace_identity)
    )
    assert cleanup.filesystem_removed and cleanup.metadata_removed and cleanup.path_absent


@pytest.mark.parametrize(
    "state,expected_reason",
    [
        ("wrong-head", "HEAD"),
        ("wrong-mode", "checkout mode"),
        ("wrong-branch", "branch"),
        ("wrong-lock", "lock ownership"),
        ("prunable", "prunable"),
        ("dirty", "dirty"),
    ],
)
def test_prepare_post_creation_verification_fails_closed(
    repo, state: str, expected_reason: str
) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "agent/596-work")
    other_sha = "a" * 40 if sha != "a" * 40 else "b" * 40
    request = preparation_request(
        workspace_request_id=f"verify-{state}",
        requested_ref="agent/596-work",
        expected_revision=sha,
        mode="branch",
    )
    probe = adapter(root, parent)
    identity, path, _, resolved_ref, lock_reason = preparation_contract(probe, request)
    primary = worktree_record(root, sha, branch="refs/heads/main")
    kwargs = {
        "branch": resolved_ref,
        "detached": False,
        "lock_reason": lock_reason,
        "prunable": False,
    }
    head = sha
    if state == "wrong-head":
        head = other_sha
    elif state == "wrong-mode":
        kwargs.update(branch=None, detached=True)
    elif state == "wrong-branch":
        kwargs["branch"] = "refs/heads/other"
    elif state == "wrong-lock":
        kwargs["lock_reason"] = "other"
    elif state == "prunable":
        kwargs["prunable"] = True
    target = worktree_record(path, head, **kwargs)
    observations = preparation_prefix_observations("branch", sha) + [
        success(primary),
        success(),
        success(primary + target),
    ]
    if state == "dirty":
        observations.append(success("dirty\x00"))
    result = adapter(root, parent, runner=RecordingRunner(observations)).prepare(request)
    assert result.outcome == "unavailable"
    assert expected_reason in result.reason


def test_prepare_invalid_inputs_are_bounded_and_deterministic(repo, monkeypatch) -> None:
    root, parent, _ = repo
    wrong_type = adapter(root, parent).prepare(object())
    assert wrong_type.outcome == "blocked"
    assert wrong_type.repository == "" and wrong_type.requested_ref == ""

    malformed = WorkspacePreparationRequest(
        workspace_request_id=object(),
        repository=object(),
        requested_ref=object(),
        expected_revision=object(),
        mode=object(),
    )
    first = adapter(root, parent).prepare(malformed)
    second = adapter(root, parent).prepare(malformed)
    assert first == second
    assert first.repository == "" and first.requested_ref == ""
    assert first.mode == "branch"

    oversized = WorkspacePreparationRequest(
        workspace_request_id="x" * (module.MAX_TEXT_BYTES + 1),
        repository="Blummer92/agent-os",
        requested_ref="main",
        expected_revision=git(root, "rev-parse", "main"),
        mode="branch",
    )
    bounded = adapter(root, parent).prepare(oversized)
    assert bounded.outcome == "blocked"
    assert len(bounded.reason.encode()) <= module.MAX_REASON_BYTES

    request = preparation_request(
        workspace_request_id="long-reason",
        requested_ref="main",
        expected_revision=git(root, "rev-parse", "main"),
        mode="branch",
    )
    with monkeypatch.context() as patch:
        def fail_bind(self, value):
            raise GitWorktreeAdapterError("z" * 5000)
        patch.setattr(GitWorktreeAdapter, "_bind_preparation", fail_bind)
        long_reason = adapter(root, parent).prepare(request)
    assert len(long_reason.reason.encode()) == module.MAX_REASON_BYTES


def test_preparation_result_vocabulary_authority_and_immutability() -> None:
    for outcome in module._PREPARATION_OUTCOMES:
        result = module._preparation_result(outcome=outcome)
        assert result.outcome == outcome
        assert result.side_effect_state in module._PREPARATION_SIDE_EFFECTS
        for field in (
            "repository_implementation_authorized",
            "execution_authorized",
            "github_writes_authorized",
            "merge_authorized",
        ):
            assert getattr(result, field) is False
        with pytest.raises(FrozenInstanceError):
            result.merge_authorized = True

    with pytest.raises(GitWorktreeAdapterError, match="outcome"):
        module._preparation_result(outcome="unknown")
    with pytest.raises(GitWorktreeAdapterError, match="side-effect"):
        module._preparation_result(outcome="blocked", side_effect_state="unknown")


def test_prepare_at_most_once(repo) -> None:
    root, parent, _ = repo
    sha = git(root, "rev-parse", "main")
    request = preparation_request(
        workspace_request_id="prep-once",
        requested_ref="main",
        expected_revision=sha,
        mode="branch",
    )
    instance = adapter(root, parent)
    instance.prepare(request)
    with pytest.raises(RuntimeError, match="at most once"):
        instance.prepare(request)


def test_inspect_complete_state_reuses_bound_runner_and_root(repo) -> None:
    """Regression: #760's evidence integration reuses this adapter's own
    GitRunner/root/env rather than constructing a second Git runner."""
    root, parent, request = repo
    instance, request, handle, path = created(repo)
    initial = instance.inspect_complete_state(handle, observation_kind="initial")
    assert initial.observation_kind == "initial"
    assert initial.complete and initial.is_clean
    assert initial.workspace_path == str(path)
    (path / "scratch.txt").write_text("noise\n")
    final = instance.inspect_complete_state(handle, observation_kind="final")
    assert final.observation_kind == "final"
    assert final.complete and not final.is_clean
    assert {item.path for item in final.untracked} == {"scratch.txt"}
