from __future__ import annotations

import ast
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
