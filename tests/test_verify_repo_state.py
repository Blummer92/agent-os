"""Focused tests for scripts/verify-repo-state.sh.

Every test builds an isolated temporary bare "origin" plus one or more clones.
No live GitHub network access is used. Retry delays are injected through
VERIFY_REPO_STATE_RETRY_DELAYS so bounded-retry behavior is exercised without
sleeping for real backoff durations.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-repo-state.sh"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DIRTY = 3
EXIT_FETCH = 4
EXIT_BRANCH_MISSING = 5
EXIT_SWITCH = 6
EXIT_FAST_FORWARD = 7
EXIT_BASE = 8


def _env(home: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "Agent OS Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Agent OS Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            # Fast, deterministic: three attempts, no real sleeping.
            "VERIFY_REPO_STATE_RETRY_DELAYS": "0 0",
        }
    )
    env.update(extra)
    return env


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        text=True,
        capture_output=True,
        env=_env(repo.parent),
    )


def verify(
    repo: Path, *args: str, **env_extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=repo,
        check=False,
        text=True,
        capture_output=True,
        env=_env(repo.parent, **env_extra),
    )


def commit(repo: Path, name: str, message: str) -> None:
    (repo / name).write_text(f"{name}\n", encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-m", message)


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """A bare origin with `main` and a `feature/topic` branch one commit ahead."""
    bare = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--quiet", "--bare", "--initial-branch=main", str(bare)],
        check=True,
        capture_output=True,
        env=_env(tmp_path),
    )
    seed = tmp_path / "seed"
    subprocess.run(
        ["git", "clone", "--quiet", str(bare), str(seed)],
        check=True,
        capture_output=True,
        env=_env(tmp_path),
    )
    git(seed, "switch", "--quiet", "--create", "main")
    commit(seed, "base.txt", "base commit")
    git(seed, "push", "--quiet", "--set-upstream", "origin", "main")
    git(seed, "switch", "--quiet", "--create", "feature/topic")
    commit(seed, "topic.txt", "topic commit")
    git(seed, "push", "--quiet", "--set-upstream", "origin", "feature/topic")
    return bare


@pytest.fixture
def clone(tmp_path: Path, origin: Path) -> Path:
    target = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(target)],
        check=True,
        capture_output=True,
        env=_env(tmp_path),
    )
    return target


def parse_evidence(stdout: str) -> dict[str, object]:
    """Parse the stdout evidence contract, asserting its exact shape."""
    lines = stdout.splitlines()
    begin = lines.index("CHANGED_FILES_BEGIN")
    end = lines.index("CHANGED_FILES_END")
    assert end > begin
    assert end == len(lines) - 1, "CHANGED_FILES_END must be the final stdout line"
    fields = dict(line.split("=", 1) for line in lines[:begin])
    assert list(fields) == ["HEAD_REF", "HEAD_SHA", "BASE_REF", "BASE_SHA"]
    fields["changed_files"] = lines[begin + 1 : end]
    return fields


# --- 1/7/13/14: success paths and the stdout evidence contract --------------


def test_branch_exists_locally_and_remotely(clone: Path) -> None:
    git(clone, "switch", "--quiet", "--track", "--create", "feature/topic", "origin/feature/topic")
    result = verify(clone, "feature/topic", "main")
    assert result.returncode == EXIT_OK, result.stderr
    evidence = parse_evidence(result.stdout)
    assert evidence["HEAD_REF"] == "feature/topic"
    assert evidence["BASE_REF"] == "origin/main"
    assert evidence["HEAD_SHA"] == git(clone, "rev-parse", "HEAD").stdout.strip()
    assert evidence["changed_files"] == ["topic.txt"]


def test_branch_exists_only_remotely_creates_tracking_branch(clone: Path) -> None:
    assert "feature/topic" not in git(clone, "branch", "--list").stdout
    result = verify(clone, "feature/topic")
    assert result.returncode == EXIT_OK, result.stderr
    assert git(clone, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "feature/topic"
    upstream = git(clone, "rev-parse", "--abbrev-ref", "HEAD@{upstream}").stdout.strip()
    assert upstream == "origin/feature/topic"


def test_branch_exists_only_locally_reports_no_remote_update(clone: Path) -> None:
    git(clone, "switch", "--quiet", "--create", "local/only")
    commit(clone, "local.txt", "local only commit")
    result = verify(clone, "local/only")
    assert result.returncode == EXIT_OK, result.stderr
    assert "local-only" in result.stderr
    assert "no remote fast-forward" in result.stderr
    assert parse_evidence(result.stdout)["changed_files"] == ["local.txt"]


def test_successful_fast_forward_advances_head(clone: Path, origin: Path, tmp_path: Path) -> None:
    git(clone, "switch", "--quiet", "--track", "--create", "feature/topic", "origin/feature/topic")
    before = git(clone, "rev-parse", "HEAD").stdout.strip()

    pusher = tmp_path / "pusher"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(pusher)],
        check=True, capture_output=True, env=_env(tmp_path),
    )
    git(pusher, "switch", "--quiet", "--track", "--create", "feature/topic", "origin/feature/topic")
    commit(pusher, "advance.txt", "advance the remote")
    git(pusher, "push", "--quiet", "origin", "feature/topic")
    expected = git(pusher, "rev-parse", "HEAD").stdout.strip()

    result = verify(clone, "feature/topic")
    assert result.returncode == EXIT_OK, result.stderr
    after = git(clone, "rev-parse", "HEAD").stdout.strip()
    assert after == expected and after != before
    assert parse_evidence(result.stdout)["HEAD_SHA"] == expected


def test_empty_changed_file_section_when_branch_matches_base(clone: Path) -> None:
    """An empty section means HEAD introduces no changes relative to the base."""
    result = verify(clone, "main", "main")
    assert result.returncode == EXIT_OK, result.stderr
    evidence = parse_evidence(result.stdout)
    assert evidence["changed_files"] == []
    assert "CHANGED_FILES_BEGIN\nCHANGED_FILES_END" in result.stdout


def test_branch_name_with_slashes_is_supported(clone: Path) -> None:
    git(clone, "switch", "--quiet", "--create", "agent/602/deep/path")
    commit(clone, "deep.txt", "deep branch commit")
    result = verify(clone, "agent/602/deep/path")
    assert result.returncode == EXIT_OK, result.stderr
    assert parse_evidence(result.stdout)["HEAD_REF"] == "agent/602/deep/path"


# --- 12/13: stream separation ----------------------------------------------


def test_logs_go_to_stderr_and_stdout_holds_only_evidence(clone: Path) -> None:
    result = verify(clone, "feature/topic")
    assert result.returncode == EXIT_OK, result.stderr
    # parse_evidence asserts the exact field order and that the changed-file
    # block terminates stdout, so stdout can hold nothing else.
    evidence = parse_evidence(result.stdout)
    assert evidence["changed_files"] == ["topic.txt"]
    assert "verify-repo-state:" not in result.stdout
    assert "fetching origin" in result.stderr
    assert "verify-repo-state:" in result.stderr


def test_failure_diagnostics_never_touch_stdout(clone: Path) -> None:
    (clone / "base.txt").write_text("dirty\n", encoding="utf-8")
    result = verify(clone, "feature/topic")
    assert result.returncode == EXIT_DIRTY
    assert result.stdout == ""


# --- 5/6: dirty-tree policy -------------------------------------------------


def test_dirty_tracked_file_blocks_and_preserves_work(clone: Path) -> None:
    (clone / "base.txt").write_text("uncommitted edit\n", encoding="utf-8")
    result = verify(clone, "feature/topic")
    assert result.returncode == EXIT_DIRTY
    assert "base.txt" in result.stderr
    # User work is preserved: never stashed, reset, or cleaned.
    assert (clone / "base.txt").read_text(encoding="utf-8") == "uncommitted edit\n"
    assert git(clone, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"


def test_untracked_file_is_reported_but_not_blocking(clone: Path) -> None:
    (clone / "scratch.txt").write_text("scratch\n", encoding="utf-8")
    result = verify(clone, "feature/topic")
    assert result.returncode == EXIT_OK, result.stderr
    assert "untracked files present" in result.stderr
    assert "scratch.txt" in result.stderr
    assert (clone / "scratch.txt").exists()


def test_ignored_file_is_permitted_and_not_reported(clone: Path) -> None:
    git(clone, "switch", "--quiet", "main")
    (clone / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    git(clone, "add", ".gitignore")
    git(clone, "commit", "-m", "add gitignore")
    (clone / "ignored").mkdir()
    (clone / "ignored" / "artifact.log").write_text("noise\n", encoding="utf-8")
    result = verify(clone, "main", "main")
    assert result.returncode == EXIT_OK, result.stderr
    assert "artifact.log" not in result.stderr
    assert "untracked files present" not in result.stderr


# --- 4/17: missing branch ---------------------------------------------------


def test_missing_branch_fails_without_creation_permission(clone: Path) -> None:
    result = verify(clone, "agent/does-not-exist")
    assert result.returncode == EXIT_BRANCH_MISSING
    assert "does not exist locally or on origin" in result.stderr
    assert "--create-from-base" in result.stderr
    assert result.stdout == ""
    # No branch was invented.
    assert "agent/does-not-exist" not in git(clone, "branch", "--list").stdout


# --- 16: explicit branch creation ------------------------------------------


def test_create_from_base_creates_local_branch_only(clone: Path) -> None:
    result = verify(clone, "--create-from-base", "agent/new-work", "main")
    assert result.returncode == EXIT_OK, result.stderr
    assert git(clone, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "agent/new-work"
    assert (
        git(clone, "rev-parse", "HEAD").stdout.strip()
        == git(clone, "rev-parse", "origin/main").stdout.strip()
    )
    # Nothing was pushed: the remote still has no such branch.
    remote_branches = git(clone, "ls-remote", "--heads", "origin").stdout
    assert "agent/new-work" not in remote_branches
    assert parse_evidence(result.stdout)["changed_files"] == []


def test_create_from_base_rejects_missing_base(clone: Path) -> None:
    result = verify(clone, "--create-from-base", "agent/new-work", "no-such-base")
    assert result.returncode == EXIT_BASE
    assert "no-such-base" in result.stderr
    assert "agent/new-work" not in git(clone, "branch", "--list").stdout


def test_create_from_base_does_not_fire_for_existing_branch(clone: Path) -> None:
    """An existing branch is verified, never recreated from the base."""
    result = verify(clone, "--create-from-base", "feature/topic", "main")
    assert result.returncode == EXIT_OK, result.stderr
    assert parse_evidence(result.stdout)["changed_files"] == ["topic.txt"]


# --- 8: divergence ----------------------------------------------------------


def test_diverged_branch_fails_without_mutating_history(
    clone: Path, origin: Path, tmp_path: Path
) -> None:
    git(clone, "switch", "--quiet", "--track", "--create", "feature/topic", "origin/feature/topic")
    commit(clone, "local-side.txt", "local divergence")
    local_head = git(clone, "rev-parse", "HEAD").stdout.strip()

    pusher = tmp_path / "pusher"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(pusher)],
        check=True, capture_output=True, env=_env(tmp_path),
    )
    git(pusher, "switch", "--quiet", "--track", "--create", "feature/topic", "origin/feature/topic")
    commit(pusher, "remote-side.txt", "remote divergence")
    git(pusher, "push", "--quiet", "origin", "feature/topic")

    result = verify(clone, "feature/topic")
    assert result.returncode == EXIT_FAST_FORWARD
    assert "diverged" in result.stderr
    assert result.stdout == ""
    # No reset, rebase, or force-update happened.
    assert git(clone, "rev-parse", "HEAD").stdout.strip() == local_head


def test_local_branch_ahead_of_remote_is_not_an_error(clone: Path) -> None:
    git(clone, "switch", "--quiet", "--track", "--create", "feature/topic", "origin/feature/topic")
    commit(clone, "ahead.txt", "ahead of remote")
    head = git(clone, "rev-parse", "HEAD").stdout.strip()
    result = verify(clone, "feature/topic")
    assert result.returncode == EXIT_OK, result.stderr
    assert "ahead of origin" in result.stderr
    assert git(clone, "rev-parse", "HEAD").stdout.strip() == head


# --- 9: base reference ------------------------------------------------------


def test_missing_base_reference_fails(clone: Path) -> None:
    result = verify(clone, "feature/topic", "release-2099")
    assert result.returncode == EXIT_BASE
    assert "release-2099" in result.stderr
    assert result.stdout == ""


def test_shallow_clone_without_merge_base_reports_shallow_history(
    origin: Path, tmp_path: Path
) -> None:
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", "--no-single-branch",
         f"file://{origin}", str(shallow)],
        check=True, capture_output=True, env=_env(tmp_path),
    )
    result = verify(shallow, "feature/topic", "main")
    assert result.returncode == EXIT_BASE
    assert "shallow" in result.stderr
    assert "no merge base" in result.stderr
    assert result.stdout == ""


def test_restricted_refspec_is_not_reported_as_a_missing_branch(
    origin: Path, tmp_path: Path
) -> None:
    """A single-branch clone lacks remote-tracking refs; that is configuration,
    not evidence that the branch is absent from the remote."""
    single = tmp_path / "single"
    subprocess.run(
        ["git", "clone", "--quiet", "--single-branch", "--branch", "main",
         f"file://{origin}", str(single)],
        check=True, capture_output=True, env=_env(tmp_path),
    )
    result = verify(single, "feature/topic", "main")
    assert result.returncode == EXIT_BRANCH_MISSING
    assert "remote-tracking refs are incomplete" in result.stderr
    assert "does not exist locally or on origin" not in result.stderr
    assert result.stdout == ""


# --- 10/11: retry boundary --------------------------------------------------


def test_fetch_failure_retries_a_bounded_number_of_times(clone: Path) -> None:
    git(clone, "remote", "set-url", "origin", str(clone.parent / "missing-origin.git"))
    result = verify(clone, "feature/topic")
    assert result.returncode == EXIT_FETCH
    # Injected schedule "0 0" => 1 initial attempt + 2 retries.
    assert result.stderr.count("retrying in") == 2
    assert "fetch failed after 3 attempt(s)" in result.stderr
    assert result.stdout == ""


def test_default_retry_schedule_starts_at_two_seconds() -> None:
    """The documented default backoff is 2s then 4s, with no dead cap config."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'DEFAULT_RETRY_DELAYS="2 4"' in text
    assert "MAX_SLEEP" not in text


def test_local_failures_are_not_retried(clone: Path) -> None:
    """A dirty tree fails deterministically before any network operation."""
    (clone / "base.txt").write_text("dirty\n", encoding="utf-8")
    result = verify(clone, "feature/topic")
    assert result.returncode == EXIT_DIRTY
    assert "retrying in" not in result.stderr
    assert "fetching origin" not in result.stderr


def test_divergence_failure_is_not_retried(clone: Path, origin: Path, tmp_path: Path) -> None:
    git(clone, "switch", "--quiet", "--track", "--create", "feature/topic", "origin/feature/topic")
    commit(clone, "local-side.txt", "local divergence")
    pusher = tmp_path / "pusher"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(pusher)],
        check=True, capture_output=True, env=_env(tmp_path),
    )
    git(pusher, "switch", "--quiet", "--track", "--create", "feature/topic", "origin/feature/topic")
    commit(pusher, "remote-side.txt", "remote divergence")
    git(pusher, "push", "--quiet", "origin", "feature/topic")

    result = verify(clone, "feature/topic")
    assert result.returncode == EXIT_FAST_FORWARD
    assert "retrying in" not in result.stderr
    # Exactly one fetch was performed; no second network operation.
    assert result.stderr.count("fetching origin") == 1


# --- 2/18: argument validation and exit codes -------------------------------


def test_no_arguments_is_a_usage_error(clone: Path) -> None:
    result = verify(clone)
    assert result.returncode == EXIT_USAGE
    assert "a target branch is required" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "args",
    [
        ("--unknown-option", "main"),
        ("refs/heads/feature/topic",),
        ("bad branch name",),
        ("feature/topic", "main", "extra"),
    ],
)
def test_invalid_arguments_fail_before_touching_repository_state(
    clone: Path, args: tuple[str, ...]
) -> None:
    head_before = git(clone, "rev-parse", "HEAD").stdout.strip()
    result = verify(clone, *args)
    assert result.returncode == EXIT_USAGE
    assert result.stdout == ""
    assert "fetching origin" not in result.stderr
    assert git(clone, "rev-parse", "HEAD").stdout.strip() == head_before


def test_help_exits_zero_without_evidence(clone: Path) -> None:
    result = verify(clone, "--help")
    assert result.returncode == EXIT_OK
    assert result.stdout == ""
    assert "Usage: scripts/verify-repo-state.sh" in result.stderr


def test_missing_remote_is_a_usage_error(tmp_path: Path) -> None:
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main", str(lonely)],
        check=True, capture_output=True, env=_env(tmp_path),
    )
    commit(lonely, "solo.txt", "solo commit")
    result = verify(lonely, "main")
    assert result.returncode == EXIT_USAGE
    assert "remote 'origin' is not configured" in result.stderr


def test_outside_a_work_tree_is_a_usage_error(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    result = verify(plain, "main")
    assert result.returncode == EXIT_USAGE
    assert "not inside a Git work tree" in result.stderr
