from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts.agent_os_execution_capabilities.models import RepositoryIdentity
from workflow_scheduler.execution.git_worktree_adapter import (
    GitObservation,
    GitWorktreeAdapter,
    PosixGitRunner,
    WorkspacePreparationRequest,
)
from workflow_scheduler.execution.workspace_state_evidence import (
    ChangedPathObservation,
    WorkspaceLifecycleEvidence,
    WorkspaceStateEvidenceError,
    WorkspaceStateObservation,
    WorktreeListRecord,
    build_workspace_state_observation,
    canonical_changed_path,
    inspect_complete_workspace_state,
    parse_status_porcelain_v2,
)


# ---------------------------------------------------------------------------
# Repo fixtures
# ---------------------------------------------------------------------------


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


def identity() -> RepositoryIdentity:
    return RepositoryIdentity(
        host="github.com",
        owner="Blummer92",
        repository="agent-os",
        repository_id=1289370915,
        default_branch="main",
    )


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, Path]:
    root, parent = tmp_path / "repo", tmp_path / "worktrees"
    root.mkdir()
    parent.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Agent OS Tests")
    git(root, "config", "user.email", "tests@example.invalid")
    (root / "README.md").write_text("initial\n")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "initial")
    git(root, "branch", "agent/760-work")
    return root, parent


def make_adapter(root: Path, parent: Path) -> GitWorktreeAdapter:
    return GitWorktreeAdapter(
        repository_root=str(root),
        workspace_parent=str(parent),
        repository_identity=identity(),
    )


def prepared_workspace(repo: tuple[Path, Path]):
    root, parent = repo
    sha = git(root, "rev-parse", "agent/760-work")
    instance = make_adapter(root, parent)
    request = WorkspacePreparationRequest(
        workspace_request_id="wsc-760",
        repository="Blummer92/agent-os",
        requested_ref="agent/760-work",
        expected_revision=sha,
        mode="branch",
    )
    result = instance.prepare(request)
    assert result.outcome == "prepared", result.reason
    return instance, result, Path(result.path)


# ---------------------------------------------------------------------------
# canonical_changed_path
# ---------------------------------------------------------------------------


def test_canonical_path_accepts_nested_and_unusual_but_valid_paths() -> None:
    assert canonical_changed_path("a/b/c.txt") == "a/b/c.txt"
    assert canonical_changed_path("weird name (1).txt") == "weird name (1).txt"
    assert canonical_changed_path("dir/sub dir/file") == "dir/sub dir/file"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "/abs/path",
        "../escape",
        "a/../b",
        "./a",
        "a//b",
        "a\x00b",
        "a\x01b",
        "C:\\windows",
    ],
)
def test_canonical_path_rejects_noncanonical_or_unsafe_forms(bad: str) -> None:
    with pytest.raises(WorkspaceStateEvidenceError):
        canonical_changed_path(bad)


def test_canonical_path_never_normalizes_it_rejects() -> None:
    with pytest.raises(WorkspaceStateEvidenceError):
        canonical_changed_path("a/./b")


# ---------------------------------------------------------------------------
# parse_status_porcelain_v2 -- pure parser
# ---------------------------------------------------------------------------


def test_parse_empty_status_is_pristine() -> None:
    result = parse_status_porcelain_v2("")
    assert all(entries == () for entries in result.values())


def test_parse_staged_and_unstaged_distinct_categories() -> None:
    raw = "1 MM N... 100644 100644 100644 " + "a" * 40 + " " + "b" * 40 + " file.txt\x00"
    result = parse_status_porcelain_v2(raw)
    assert [item.path for item in result["staged"]] == ["file.txt"]
    assert [item.path for item in result["unstaged"]] == ["file.txt"]
    assert result["staged"][0].index_status == "M"
    assert result["unstaged"][0].worktree_status == "M"


def test_parse_staged_only() -> None:
    raw = "1 M. N... 100644 100644 100644 " + "a" * 40 + " " + "b" * 40 + " added.txt\x00"
    result = parse_status_porcelain_v2(raw)
    assert [item.path for item in result["staged"]] == ["added.txt"]
    assert result["unstaged"] == ()


def test_parse_untracked() -> None:
    raw = "? new-file.txt\x00"
    result = parse_status_porcelain_v2(raw)
    assert [item.path for item in result["untracked"]] == ["new-file.txt"]


def test_parse_ignored() -> None:
    raw = "! build/output.log\x00"
    result = parse_status_porcelain_v2(raw)
    assert [item.path for item in result["ignored"]] == ["build/output.log"]


def test_parse_rename_preserves_source_and_destination_identity() -> None:
    raw = (
        "2 R. N... 100644 100644 100644 "
        + "a" * 40
        + " "
        + "b" * 40
        + " R100 new.txt\x00old.txt\x00"
    )
    result = parse_status_porcelain_v2(raw)
    assert len(result["renamed"]) == 1
    entry = result["renamed"][0]
    assert entry.path == "new.txt"
    assert entry.orig_path == "old.txt"
    assert entry.rename_score == "R100"


def test_parse_copy_preserves_source_and_destination_identity() -> None:
    raw = (
        "2 C. N... 100644 100644 100644 "
        + "a" * 40
        + " "
        + "b" * 40
        + " C075 copy.txt\x00original.txt\x00"
    )
    result = parse_status_porcelain_v2(raw)
    assert len(result["copied"]) == 1
    entry = result["copied"][0]
    assert entry.path == "copy.txt"
    assert entry.orig_path == "original.txt"


def test_parse_deleted() -> None:
    raw = "1 D. N... 100644 000000 000000 " + "a" * 40 + " " + "0" * 40 + " gone.txt\x00"
    result = parse_status_porcelain_v2(raw)
    assert [item.path for item in result["deleted"]] == ["gone.txt"]
    assert [item.path for item in result["staged"]] == ["gone.txt"]


def test_parse_conflict_unmerged_is_never_a_plain_modified_path() -> None:
    raw = (
        "u UU N... 100644 100644 100644 100644 "
        + "a" * 40
        + " "
        + "b" * 40
        + " "
        + "c" * 40
        + " conflict.txt\x00"
    )
    result = parse_status_porcelain_v2(raw)
    assert [item.path for item in result["conflict"]] == ["conflict.txt"]
    assert result["staged"] == () and result["unstaged"] == ()


def test_parse_submodule_state_is_distinct_from_ordinary_modified() -> None:
    raw = "1 .M SC.U 160000 160000 160000 " + "a" * 40 + " " + "b" * 40 + " sub\x00"
    result = parse_status_porcelain_v2(raw)
    assert [item.path for item in result["submodule"]] == ["sub"]
    assert [item.path for item in result["unstaged"]] == ["sub"]


def test_parse_nested_and_unusual_path() -> None:
    raw = "? deeply/nested/dir with spaces/file (1).txt\x00"
    result = parse_status_porcelain_v2(raw)
    assert result["untracked"][0].path == "deeply/nested/dir with spaces/file (1).txt"


def test_parse_documented_header_lines_are_skipped_forward_compatibly() -> None:
    raw = "# branch.oid abc123\x00? new.txt\x00"
    result = parse_status_porcelain_v2(raw)
    assert [item.path for item in result["untracked"]] == ["new.txt"]


def test_parse_unknown_record_type_fails_closed() -> None:
    with pytest.raises(WorkspaceStateEvidenceError):
        parse_status_porcelain_v2("Z bogus\x00")


def test_parse_missing_terminal_nul_fails_closed() -> None:
    with pytest.raises(WorkspaceStateEvidenceError):
        parse_status_porcelain_v2("? new.txt")


def test_parse_truncated_rename_record_fails_closed() -> None:
    raw = "2 R. N... 100644 100644 100644 " + "a" * 40 + " " + "b" * 40 + " R100 new.txt\x00"
    with pytest.raises(WorkspaceStateEvidenceError):
        parse_status_porcelain_v2(raw)


def test_parse_duplicate_conflicting_records_fail_closed() -> None:
    raw = "? same.txt\x00? same.txt\x00"
    with pytest.raises(WorkspaceStateEvidenceError):
        parse_status_porcelain_v2(raw)


def test_parse_malformed_field_count_fails_closed() -> None:
    with pytest.raises(WorkspaceStateEvidenceError):
        parse_status_porcelain_v2("1 MM N... 100644 file.txt\x00")


def test_parse_oversized_evidence_fails_closed() -> None:
    raw = "".join(f"? file-{i}.txt\x00" for i in range(600))
    with pytest.raises(WorkspaceStateEvidenceError):
        parse_status_porcelain_v2(raw)


def test_parse_noncanonical_path_in_status_fails_closed() -> None:
    with pytest.raises(WorkspaceStateEvidenceError):
        parse_status_porcelain_v2("? ../escape.txt\x00")


# ---------------------------------------------------------------------------
# ChangedPathObservation / WorkspaceStateObservation model invariants
# ---------------------------------------------------------------------------


def test_changed_path_observation_requires_orig_path_for_rename() -> None:
    with pytest.raises(WorkspaceStateEvidenceError):
        ChangedPathObservation(category="renamed", path="new.txt")


def _empty_observation(*, kind: str, complete: bool = True, reason_codes: tuple[str, ...] = ()) -> WorkspaceStateObservation:
    return WorkspaceStateObservation(
        observation_kind=kind,
        repository_owner="Blummer92",
        repository_name="agent-os",
        workspace_path="/tmp/ws",
        branch="agent/760-work",
        expected_sha="a" * 40,
        observed_sha="a" * 40,
        worktree_record=WorktreeListRecord(
            path="/tmp/ws",
            head="a" * 40,
            branch="refs/heads/agent/760-work",
            detached=False,
            bare=False,
            locked=True,
            lock_reason="agent-os:test",
            prunable=False,
            prunable_reason="",
        ),
        observed_at="fixed-time",
        complete=complete,
        reason_codes=reason_codes,
    )


def test_deterministic_evidence_id_for_identical_content() -> None:
    first = _empty_observation(kind="initial")
    second = _empty_observation(kind="initial")
    assert first.evidence_id == second.evidence_id


def test_evidence_id_changes_with_content() -> None:
    first = _empty_observation(kind="initial")
    second = _empty_observation(kind="final")
    assert first.evidence_id != second.evidence_id


def test_is_clean_true_for_empty_complete_observation() -> None:
    assert _empty_observation(kind="initial").is_clean


def test_is_clean_false_when_incomplete() -> None:
    assert not _empty_observation(kind="initial", complete=False).is_clean


def test_is_clean_true_when_only_ignored_present() -> None:
    obs = WorkspaceStateObservation(
        observation_kind="initial",
        repository_owner="o",
        repository_name="r",
        workspace_path="/tmp/ws",
        branch="main",
        expected_sha="a" * 40,
        observed_sha="a" * 40,
        worktree_record=None,
        ignored=(ChangedPathObservation(category="ignored", path="build/x.log"),),
        observed_at="t",
        complete=True,
    )
    assert obs.is_clean


def test_categories_reject_out_of_order_entries() -> None:
    with pytest.raises(WorkspaceStateEvidenceError):
        WorkspaceStateObservation(
            observation_kind="initial",
            repository_owner="o",
            repository_name="r",
            workspace_path="/tmp/ws",
            branch="main",
            expected_sha="a" * 40,
            observed_sha="a" * 40,
            worktree_record=None,
            untracked=(
                ChangedPathObservation(category="untracked", path="z.txt"),
                ChangedPathObservation(category="untracked", path="a.txt"),
            ),
            observed_at="t",
            complete=True,
        )


def test_reconstruction_from_as_dict_matches_original_shape() -> None:
    obs = _empty_observation(kind="final")
    payload = obs.as_dict()
    assert payload["observation_kind"] == "final"
    assert payload["complete"] is True


# ---------------------------------------------------------------------------
# WorkspaceLifecycleEvidence invariants
# ---------------------------------------------------------------------------


def test_lifecycle_requires_matching_observation_kinds() -> None:
    initial = _empty_observation(kind="initial")
    with pytest.raises(WorkspaceStateEvidenceError):
        WorkspaceLifecycleEvidence(initial=initial, final=initial, validation_only=True)


def test_dirty_initial_state_blocks_before_validation() -> None:
    dirty_initial = WorkspaceStateObservation(
        observation_kind="initial",
        repository_owner="o",
        repository_name="r",
        workspace_path="/tmp/ws",
        branch="main",
        expected_sha="a" * 40,
        observed_sha="a" * 40,
        worktree_record=None,
        untracked=(ChangedPathObservation(category="untracked", path="x.txt"),),
        observed_at="t",
        complete=True,
    )
    final = _empty_observation(kind="final")
    evidence = WorkspaceLifecycleEvidence(
        initial=dirty_initial, final=final, validation_only=True
    )
    assert evidence.initial_blocks_validation
    assert not evidence.validation_only_success


def test_dirty_final_state_prevents_validation_only_success() -> None:
    initial = _empty_observation(kind="initial")
    dirty_final = WorkspaceStateObservation(
        observation_kind="final",
        repository_owner="o",
        repository_name="r",
        workspace_path="/tmp/ws",
        branch="main",
        expected_sha="a" * 40,
        observed_sha="a" * 40,
        worktree_record=None,
        staged=(ChangedPathObservation(category="staged", path="x.txt", index_status="M"),),
        observed_at="t",
        complete=True,
    )
    evidence = WorkspaceLifecycleEvidence(
        initial=initial, final=dirty_final, validation_only=True
    )
    assert evidence.final_prevents_success
    assert not evidence.validation_only_success


def test_clean_initial_and_final_yields_validation_only_success() -> None:
    initial = _empty_observation(kind="initial")
    final = _empty_observation(kind="final")
    evidence = WorkspaceLifecycleEvidence(
        initial=initial, final=final, validation_only=True
    )
    assert evidence.validation_only_success
    assert evidence.satisfies_expected_changed_paths(frozenset())


def test_expected_changed_paths_must_be_empty_for_success() -> None:
    initial = _empty_observation(kind="initial")
    final = _empty_observation(kind="final")
    evidence = WorkspaceLifecycleEvidence(
        initial=initial, final=final, validation_only=True
    )
    assert not evidence.satisfies_expected_changed_paths(frozenset({"x.txt"}))


def test_incomplete_observation_is_not_validation_only_success() -> None:
    initial = _empty_observation(kind="initial")
    final = _empty_observation(kind="final", complete=False, reason_codes=("status:timeout",))
    evidence = WorkspaceLifecycleEvidence(
        initial=initial, final=final, validation_only=True
    )
    assert not evidence.validation_only_success


def test_lifecycle_id_deterministic() -> None:
    initial = _empty_observation(kind="initial")
    final = _empty_observation(kind="final")
    a = WorkspaceLifecycleEvidence(initial=initial, final=final, validation_only=True)
    b = WorkspaceLifecycleEvidence(initial=initial, final=final, validation_only=True)
    assert a.lifecycle_id == b.lifecycle_id


# ---------------------------------------------------------------------------
# build_workspace_state_observation -- failure-injection via crafted GitObservation
# ---------------------------------------------------------------------------


def _obs(succeeded_stdout: str = "", **overrides: object) -> GitObservation:
    defaults: dict[str, object] = dict(
        started=True,
        return_code=0,
        timed_out=False,
        termination_confirmed=True,
        stdout=succeeded_stdout,
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        reason="",
    )
    defaults.update(overrides)
    return GitObservation(**defaults)


def _worktree_stdout(path: str, head: str, branch_ref: str) -> str:
    return f"worktree {path}\x00HEAD {head}\x00branch {branch_ref}\x00\x00"


def test_build_observation_complete_for_pristine_state() -> None:
    path = "/tmp/ws"
    head = "a" * 40
    wt = _obs(_worktree_stdout(path, head, "refs/heads/main"))
    status = _obs("")
    result = build_workspace_state_observation(
        observation_kind="initial",
        repository_identity=identity(),
        workspace_path=path,
        branch="main",
        expected_sha=head,
        lock_identity="",
        worktree_list_observation=wt,
        status_observation=status,
        observed_at="fixed",
    )
    assert result.complete
    assert result.is_clean
    assert result.worktree_record is not None
    assert result.observed_sha == head


def test_build_observation_timeout_is_incomplete() -> None:
    path = "/tmp/ws"
    head = "a" * 40
    wt = _obs(_worktree_stdout(path, head, "refs/heads/main"))
    status = _obs(started=True, return_code=None, timed_out=True, termination_confirmed=False)
    result = build_workspace_state_observation(
        observation_kind="final",
        repository_identity=identity(),
        workspace_path=path,
        branch="main",
        expected_sha=head,
        worktree_list_observation=wt,
        status_observation=status,
        observed_at="fixed",
    )
    assert not result.complete
    assert any("timeout" in code for code in result.reason_codes)
    assert not result.is_clean


def test_build_observation_truncated_status_is_incomplete() -> None:
    path = "/tmp/ws"
    head = "a" * 40
    wt = _obs(_worktree_stdout(path, head, "refs/heads/main"))
    status = _obs(started=True, return_code=0, stdout_truncated=True)
    result = build_workspace_state_observation(
        observation_kind="final",
        repository_identity=identity(),
        workspace_path=path,
        branch="main",
        expected_sha=head,
        worktree_list_observation=wt,
        status_observation=status,
        observed_at="fixed",
    )
    assert not result.complete


def test_build_observation_unavailable_worktree_list_is_incomplete() -> None:
    path = "/tmp/ws"
    wt = _obs(started=False, return_code=None, termination_confirmed=False, reason="git binary missing")
    status = _obs("")
    result = build_workspace_state_observation(
        observation_kind="initial",
        repository_identity=identity(),
        workspace_path=path,
        branch="main",
        expected_sha="a" * 40,
        worktree_list_observation=wt,
        status_observation=status,
        observed_at="fixed",
    )
    assert not result.complete
    assert any("not-started" in code for code in result.reason_codes)


def test_build_observation_missing_worktree_record_is_incomplete() -> None:
    path = "/tmp/ws"
    wt = _obs(_worktree_stdout("/other/path", "a" * 40, "refs/heads/main"))
    status = _obs("")
    result = build_workspace_state_observation(
        observation_kind="initial",
        repository_identity=identity(),
        workspace_path=path,
        branch="main",
        expected_sha="a" * 40,
        worktree_list_observation=wt,
        status_observation=status,
        observed_at="fixed",
    )
    assert not result.complete
    assert "worktree-list:record-missing" in result.reason_codes


def test_build_observation_malformed_status_is_incomplete() -> None:
    path = "/tmp/ws"
    head = "a" * 40
    wt = _obs(_worktree_stdout(path, head, "refs/heads/main"))
    status = _obs("Z bogus\x00")
    result = build_workspace_state_observation(
        observation_kind="initial",
        repository_identity=identity(),
        workspace_path=path,
        branch="main",
        expected_sha=head,
        worktree_list_observation=wt,
        status_observation=status,
        observed_at="fixed",
    )
    assert not result.complete
    assert any(code.startswith("status:malformed") for code in result.reason_codes)


def test_build_observation_lock_identity_mismatch_is_incomplete() -> None:
    path = "/tmp/ws"
    head = "a" * 40
    stdout = (
        f"worktree {path}\x00HEAD {head}\x00branch refs/heads/main\x00"
        "locked wrong-owner\x00\x00"
    )
    wt = _obs(stdout)
    status = _obs("")
    result = build_workspace_state_observation(
        observation_kind="initial",
        repository_identity=identity(),
        workspace_path=path,
        branch="main",
        expected_sha=head,
        lock_identity="expected-owner",
        worktree_list_observation=wt,
        status_observation=status,
        observed_at="fixed",
    )
    assert not result.complete
    assert "worktree-list:lock-identity-mismatch" in result.reason_codes


# ---------------------------------------------------------------------------
# End-to-end via real git through GitWorktreeAdapter / PosixGitRunner
# ---------------------------------------------------------------------------


def test_inspect_complete_workspace_state_pristine(repo: tuple[Path, Path]) -> None:
    instance, result, path = prepared_workspace(repo)
    obs = inspect_complete_workspace_state(
        runner=PosixGitRunner(),
        repository_root=str(repo[0]),
        workspace_path=str(path),
        repository_identity=identity(),
        branch="agent/760-work",
        expected_sha=result.exact_sha,
        observation_kind="initial",
        environment={"PATH": os.environ.get("PATH", "")},
    )
    assert obs.complete
    assert obs.is_clean
    assert obs.worktree_record is not None
    assert obs.worktree_record.locked


def test_inspect_complete_workspace_state_staged_unstaged_untracked(
    repo: tuple[Path, Path],
) -> None:
    instance, result, path = prepared_workspace(repo)
    (path / "README.md").write_text("changed\n")
    git(path, "add", "README.md")
    (path / "README.md").write_text("changed again\n")
    (path / "new.txt").write_text("new\n")
    obs = inspect_complete_workspace_state(
        runner=PosixGitRunner(),
        repository_root=str(repo[0]),
        workspace_path=str(path),
        repository_identity=identity(),
        branch="agent/760-work",
        expected_sha=result.exact_sha,
        observation_kind="final",
        environment={"PATH": os.environ.get("PATH", "")},
    )
    assert obs.complete
    assert not obs.is_clean
    assert {item.path for item in obs.staged} == {"README.md"}
    assert {item.path for item in obs.unstaged} == {"README.md"}
    assert {item.path for item in obs.untracked} == {"new.txt"}


def test_inspect_complete_workspace_state_ignored(repo: tuple[Path, Path]) -> None:
    instance, result, path = prepared_workspace(repo)
    (path / ".gitignore").write_text("ignored.log\n")
    git(path, "add", ".gitignore")
    git(path, "commit", "-m", "add gitignore")
    (path / "ignored.log").write_text("noise\n")
    obs = inspect_complete_workspace_state(
        runner=PosixGitRunner(),
        repository_root=str(repo[0]),
        workspace_path=str(path),
        repository_identity=identity(),
        branch="agent/760-work",
        expected_sha=result.exact_sha,
        observation_kind="final",
        environment={"PATH": os.environ.get("PATH", "")},
    )
    assert obs.complete
    assert {item.path for item in obs.ignored} == {"ignored.log"}
    assert obs.is_clean


def test_inspect_complete_workspace_state_rename(repo: tuple[Path, Path]) -> None:
    instance, result, path = prepared_workspace(repo)
    git(path, "mv", "README.md", "RENAMED.md")
    obs = inspect_complete_workspace_state(
        runner=PosixGitRunner(),
        repository_root=str(repo[0]),
        workspace_path=str(path),
        repository_identity=identity(),
        branch="agent/760-work",
        expected_sha=result.exact_sha,
        observation_kind="final",
        environment={"PATH": os.environ.get("PATH", "")},
    )
    assert obs.complete
    assert len(obs.renamed) == 1
    assert obs.renamed[0].path == "RENAMED.md"
    assert obs.renamed[0].orig_path == "README.md"


def test_inspect_complete_workspace_state_deleted(repo: tuple[Path, Path]) -> None:
    instance, result, path = prepared_workspace(repo)
    (path / "README.md").unlink()
    obs = inspect_complete_workspace_state(
        runner=PosixGitRunner(),
        repository_root=str(repo[0]),
        workspace_path=str(path),
        repository_identity=identity(),
        branch="agent/760-work",
        expected_sha=result.exact_sha,
        observation_kind="final",
        environment={"PATH": os.environ.get("PATH", "")},
    )
    assert obs.complete
    assert {item.path for item in obs.deleted} == {"README.md"}


def test_inspect_complete_workspace_state_conflict(repo: tuple[Path, Path]) -> None:
    root, parent = repo
    git(root, "checkout", "agent/760-work")
    (root / "README.md").write_text("branch-version\n")
    git(root, "commit", "-am", "branch change")
    git(root, "checkout", "main")
    (root / "README.md").write_text("main-version\n")
    git(root, "commit", "-am", "main change")
    with pytest.raises(subprocess.CalledProcessError):
        git(root, "merge", "agent/760-work")
    obs = inspect_complete_workspace_state(
        runner=PosixGitRunner(),
        repository_root=str(root),
        workspace_path=str(root),
        repository_identity=identity(),
        branch="main",
        expected_sha=git(root, "rev-parse", "HEAD"),
        observation_kind="final",
        environment={"PATH": os.environ.get("PATH", "")},
    )
    assert obs.complete
    assert {item.path for item in obs.conflict} == {"README.md"}
    git(root, "merge", "--abort")


def test_inspect_complete_workspace_state_submodule_like(repo: tuple[Path, Path]) -> None:
    root, parent = repo
    sub_root = parent.parent / "sub-repo"
    sub_root.mkdir()
    git(sub_root, "init", "-b", "main")
    git(sub_root, "config", "user.name", "Agent OS Tests")
    git(sub_root, "config", "user.email", "tests@example.invalid")
    (sub_root / "file.txt").write_text("x\n")
    git(sub_root, "add", "file.txt")
    git(sub_root, "commit", "-m", "initial")
    git(
        root,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        str(sub_root),
        "sub",
    )
    git(root, "commit", "-m", "add submodule")
    (sub_root_in_super := root / "sub" / "file.txt").write_text("changed\n")
    obs = inspect_complete_workspace_state(
        runner=PosixGitRunner(),
        repository_root=str(root),
        workspace_path=str(root),
        repository_identity=identity(),
        branch="main",
        expected_sha=git(root, "rev-parse", "HEAD"),
        observation_kind="final",
        environment={"PATH": os.environ.get("PATH", "")},
    )
    assert obs.complete
    assert {item.path for item in obs.submodule} == {"sub"}


def test_adapter_inspect_complete_state_reuses_bound_runner(repo: tuple[Path, Path]) -> None:
    instance, result, path = prepared_workspace(repo)
    handle = _handle_for(instance, result)
    initial = instance.inspect_complete_state(handle, observation_kind="initial")
    final = instance.inspect_complete_state(handle, observation_kind="final")
    assert initial.complete and initial.is_clean
    assert final.complete and final.is_clean
    evidence = WorkspaceLifecycleEvidence(
        initial=initial, final=final, validation_only=True
    )
    assert evidence.validation_only_success


def _handle_for(instance: GitWorktreeAdapter, result):
    from workflow_scheduler.execution.single_issue_pilot import WorkspaceHandle

    return WorkspaceHandle(
        created=True, workspace_identity=result.workspace_identity, reason=""
    )


def test_exactly_one_initial_and_one_final_observation_through_integration(
    repo: tuple[Path, Path],
) -> None:
    instance, result, path = prepared_workspace(repo)
    handle = _handle_for(instance, result)
    initial = instance.inspect_complete_state(handle, observation_kind="initial")
    (path / "scratch.txt").write_text("noise\n")
    final = instance.inspect_complete_state(handle, observation_kind="final")
    assert initial.observation_kind == "initial"
    assert final.observation_kind == "final"
    evidence = WorkspaceLifecycleEvidence(
        initial=initial, final=final, validation_only=True
    )
    assert evidence.initial_blocks_validation is False
    assert evidence.final_prevents_success is True
    assert not evidence.validation_only_success


def test_dirty_initial_workspace_blocks_via_real_adapter(repo: tuple[Path, Path]) -> None:
    instance, result, path = prepared_workspace(repo)
    (path / "dirty.txt").write_text("noise\n")
    handle = _handle_for(instance, result)
    initial = instance.inspect_complete_state(handle, observation_kind="initial")
    assert initial.complete
    assert not initial.is_clean
    final = instance.inspect_complete_state(handle, observation_kind="final")
    evidence = WorkspaceLifecycleEvidence(
        initial=initial, final=final, validation_only=True
    )
    assert evidence.initial_blocks_validation
    assert not evidence.validation_only_success


# ---------------------------------------------------------------------------
# Architecture / safety proofs
# ---------------------------------------------------------------------------


def test_module_defines_no_second_git_runner_or_worktree_manager() -> None:
    import workflow_scheduler.execution.workspace_state_evidence as module

    source = Path(module.__file__).read_text()
    assert "class PosixGitRunner" not in source
    assert "subprocess." not in source
    assert "os.fork" not in source
    assert "GitWorktreeAdapter(" not in source


def test_module_never_references_destructive_git_commands() -> None:
    import workflow_scheduler.execution.workspace_state_evidence as module

    source = Path(module.__file__).read_text()
    for forbidden in ('"reset"', "'reset'", '"stash"', "'stash'", '"clean"', "'clean'", "--force"):
        assert forbidden not in source, forbidden
    # "checkout" only appears as a substring of legitimate identifiers/comments
    # elsewhere in this subsystem; this module issues no checkout argv at all.
    assert '"checkout"' not in source and "'checkout'" not in source


def test_module_never_touches_network_provider_or_workflow_surfaces() -> None:
    import workflow_scheduler.execution.workspace_state_evidence as module

    source = Path(module.__file__).read_text()
    for forbidden in ("import requests", "import urllib", "import socket", "retry_manager", "workflow.yml", "workflows/"):
        assert forbidden not in source
