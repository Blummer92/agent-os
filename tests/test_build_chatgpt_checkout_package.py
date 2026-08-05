"""Focused tests for scripts/build-chatgpt-checkout-package.sh.

Deterministic and fully offline: every test builds an isolated temporary bare
"origin" plus a clone under tmp_path, exactly like
tests/test_prepare_issue_worktree.py. No live GitHub access, no credentials,
no cloud calls, and no Workflow Scheduler execution occur.

This command reuses scripts/prepare-issue-worktree.sh (#807) for all
checkout/fetch/worktree behavior -- these tests do not re-verify #807's own
contract (see tests/test_prepare_issue_worktree.py for that); they verify
that this command delegates to it correctly and packages the result safely.

Covers the twenty behaviors required by issue #881.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build-chatgpt-checkout-package.sh"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DIRTY = 3
EXIT_FETCH = 4
EXIT_REF_MISSING = 5
EXIT_WORKTREE = 6
EXIT_CONFLICT = 7
EXIT_BASE = 8
EXIT_EVIDENCE = 9
EXIT_OUTPUT = 10
EXIT_SYMLINK = 11

MANIFEST_KEYS = [
    "schema_name",
    "schema_version",
    "repository",
    "issue_number",
    "requested_ref",
    "resolved_ref",
    "resolved_sha",
    "base_ref",
    "base_sha",
    "checkout_mode",
    "working_tree_clean",
    "package_format",
    "included_git_metadata",
    "file_count",
    "archive_sha256",
    "created_by_command_version",
    "side_effects_performed",
    "implementation_authorized",
    "execution_authorized",
    "github_writes_authorized",
    "merge_authorized",
]

AUTHORITY_KEYS = [
    "implementation_authorized",
    "execution_authorized",
    "github_writes_authorized",
    "merge_authorized",
]

MANIFEST_ENTRY_NAME = "agent-os-chatgpt-package-manifest.json"


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


def commit(repo: Path, name: str, message: str, content: str | None = None) -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(content if content is not None else f"{name}\n", encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-m", message)


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """Bare origin with `main`, a tag, and the two reused #807 scripts tracked."""
    bare = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--quiet", "--bare", "--initial-branch=main", str(bare)],
        check=True, capture_output=True, env=_env(tmp_path),
    )
    seed = tmp_path / "seed"
    subprocess.run(
        ["git", "clone", "--quiet", str(bare), str(seed)],
        check=True, capture_output=True, env=_env(tmp_path),
    )
    git(seed, "switch", "--quiet", "--create", "main")
    commit(seed, "a.txt", "base commit")
    (seed / "scripts").mkdir(exist_ok=True)
    (seed / "scripts" / "prepare-issue-worktree.sh").write_bytes(
        (ROOT / "scripts" / "prepare-issue-worktree.sh").read_bytes()
    )
    (seed / ".env").write_text("SECRET=should-never-ship\n", encoding="utf-8")
    git(seed, "add", "-A")
    git(seed, "commit", "-m", "add reused script and a tracked secret file")
    git(seed, "push", "--quiet", "--set-upstream", "origin", "main")
    git(seed, "tag", "v1.0")
    git(seed, "push", "--quiet", "origin", "v1.0")
    return bare


@pytest.fixture
def clone(tmp_path: Path, origin: Path) -> Path:
    dest = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(dest)],
        check=True, capture_output=True, env=_env(tmp_path),
    )
    return dest


def repository_identity(origin: Path) -> str:
    """Identity the reused #807 script derives from the local origin path."""
    return f"{origin.parent.name}/{origin.name[: -len('.git')]}"


def run(
    clone: Path, tmp_path: Path, *extra_args: str,
    origin: Path, worktree_root: Path | None = None,
    test_action: str | None = None,
) -> subprocess.CompletedProcess[str]:
    args = [
        "bash", str(SCRIPT),
        "--repository", repository_identity(origin),
        "--issue", "881",
        *extra_args,
    ]
    env = _env(tmp_path)
    if test_action is not None:
        # The builder's bounded test-only controls stay inert unless this
        # explicit guard is set; only two predefined action names are accepted.
        env["BUILD_CHATGPT_PACKAGE_TEST_HOOKS"] = "1"
        env["BUILD_CHATGPT_PACKAGE_TEST_ACTION"] = test_action
    if worktree_root is not None:
        args += ["--worktree-root", str(worktree_root)]
    return subprocess.run(args, cwd=clone, text=True, capture_output=True, env=env)


def temp_archives(directory: Path) -> list[Path]:
    """Private temporary archives the builder writes before publication."""
    return sorted(directory.glob(".agent-os-chatgpt-package.*"))


def evidence(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


# 1. exact branch package -----------------------------------------------------

def test_exact_branch_package(clone: Path, tmp_path: Path, origin: Path):
    output = tmp_path / "pkg-branch.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OK, result.stderr
    data = evidence(result)
    assert data["status"] == "built"
    assert data["checkout_mode"] == "branch"
    assert output.exists()
    with zipfile.ZipFile(output) as zf:
        assert "a.txt" in zf.namelist()


# 2. exact tag package ---------------------------------------------------------

def test_exact_tag_package(clone: Path, tmp_path: Path, origin: Path):
    output = tmp_path / "pkg-tag.zip"
    result = run(clone, tmp_path, "--ref", "v1.0", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OK, result.stderr
    data = evidence(result)
    assert data["checkout_mode"] == "tag"


# 3. exact SHA detached package ------------------------------------------------

def test_exact_sha_package(clone: Path, tmp_path: Path, origin: Path):
    sha = git(clone, "rev-parse", "main").stdout.strip()
    output = tmp_path / "pkg-sha.zip"
    result = run(clone, tmp_path, "--ref", sha, "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OK, result.stderr
    data = evidence(result)
    assert data["checkout_mode"] == "detached-sha"
    assert data["resolved_sha"] == sha


# 4. stale local refs refreshed only through the reused checkout boundary -----

def test_stale_local_ref_is_refreshed_through_reused_preparation(clone: Path, tmp_path: Path, origin: Path):
    # Advance origin/main after the clone was made, without touching `clone`.
    seed2 = tmp_path / "seed2"
    subprocess.run(["git", "clone", "--quiet", str(origin), str(seed2)], check=True,
                    capture_output=True, env=_env(tmp_path))
    commit(seed2, "b.txt", "second commit")
    git(seed2, "push", "--quiet", "origin", "main")
    new_sha = git(seed2, "rev-parse", "main").stdout.strip()

    # No local `main` branch in `clone` to disagree with origin: resolution
    # falls through to the freshly fetched origin/main, proving the refresh
    # comes from the reused fetch inside #807, not from a second one here.
    git(clone, "switch", "--quiet", "--detach", "HEAD")
    git(clone, "branch", "-D", "main")

    output = tmp_path / "pkg-refresh.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OK, result.stderr
    data = evidence(result)
    assert data["resolved_sha"] == new_sha
    with zipfile.ZipFile(output) as zf:
        assert "b.txt" in zf.namelist()


# 5. dirty tracked state blocks packaging -------------------------------------

def test_dirty_tracked_state_blocks_packaging(clone: Path, tmp_path: Path, origin: Path):
    worktree_root = tmp_path / "dirty-root"
    prep = subprocess.run(
        ["bash", str(ROOT / "scripts" / "prepare-issue-worktree.sh"),
         "--issue", "881", "--repository", repository_identity(origin), "--ref", "main",
         "--worktree-root", str(worktree_root)],
        cwd=clone, text=True, capture_output=True, env=_env(tmp_path),
    )
    assert prep.returncode == EXIT_OK, prep.stderr
    (worktree_root / "issue-881" / "a.txt").write_text("dirty\n", encoding="utf-8")

    output = tmp_path / "pkg-dirty.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), worktree_root=worktree_root, origin=origin)
    assert result.returncode == EXIT_DIRTY, result.stderr
    assert evidence(result)["status"] == "blocked"
    assert not output.exists()


# 6. untracked-file inclusion policy is explicit and safe ---------------------

def test_untracked_files_are_never_included(clone: Path, tmp_path: Path, origin: Path):
    (clone / "untracked.txt").write_text("not tracked\n", encoding="utf-8")
    output = tmp_path / "pkg-untracked.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OK, result.stderr
    with zipfile.ZipFile(output) as zf:
        assert "untracked.txt" not in zf.namelist()


# 7. output collision fails closed --------------------------------------------

def test_output_collision_fails_closed(clone: Path, tmp_path: Path, origin: Path):
    output = tmp_path / "pkg-exists.zip"
    output.write_text("pre-existing", encoding="utf-8")
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OUTPUT
    assert evidence(result)["status"] == "blocked"
    assert output.read_text(encoding="utf-8") == "pre-existing"


# 8. wrong repository, issue, ref, or SHA fails closed -------------------------

def test_wrong_repository_fails_closed(clone: Path, tmp_path: Path):
    output = tmp_path / "pkg-wrong-repo.zip"
    result = subprocess.run(
        ["bash", str(SCRIPT), "--repository", "someone/else", "--issue", "881",
         "--ref", "main", "--output", str(output)],
        cwd=clone, text=True, capture_output=True, env=_env(tmp_path),
    )
    assert result.returncode == EXIT_CONFLICT
    assert evidence(result)["status"] == "manual-review"
    assert not output.exists()


def test_missing_ref_fails_closed(clone: Path, tmp_path: Path, origin: Path):
    output = tmp_path / "pkg-missing-ref.zip"
    result = run(clone, tmp_path, "--ref", "no-such-branch", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_REF_MISSING
    assert evidence(result)["status"] == "blocked"
    assert not output.exists()


def test_malformed_sha_fails_closed(clone: Path, tmp_path: Path, origin: Path):
    output = tmp_path / "pkg-bad-sha.zip"
    result = run(clone, tmp_path, "--ref", "deadbeef", "--output", str(output), origin=origin)
    assert result.returncode != EXIT_OK
    assert not output.exists()


# 9. worktree or path collision fails closed -----------------------------------

def test_worktree_path_collision_with_foreign_identity_fails_closed(clone: Path, tmp_path: Path, origin: Path):
    worktree_root = tmp_path / "shared-root"
    worktree_root.mkdir()
    (worktree_root / "issue-881").mkdir()
    output = tmp_path / "pkg-collision.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), worktree_root=worktree_root, origin=origin)
    assert result.returncode != EXIT_OK
    assert not output.exists()


# 10 & 12. package manifest matches archive; entry ordering/digest deterministic

def test_manifest_matches_archive_and_is_deterministic(clone: Path, tmp_path: Path, origin: Path):
    output_a = tmp_path / "pkg-a.zip"
    output_b = tmp_path / "pkg-b.zip"
    result_a = run(clone, tmp_path, "--ref", "main", "--output", str(output_a), origin=origin)
    result_b = run(clone, tmp_path, "--ref", "main", "--output", str(output_b), origin=origin)
    assert result_a.returncode == EXIT_OK and result_b.returncode == EXIT_OK
    data_a, data_b = evidence(result_a), evidence(result_b)
    assert data_a["archive_sha256"] == data_b["archive_sha256"]
    assert data_a["file_count"] == data_b["file_count"] > 0

    with zipfile.ZipFile(output_a) as zf:
        names = zf.namelist()
        # Payload entries are written in sorted order; the manifest is
        # appended last since its own digest cannot include itself.
        assert names[-1] == MANIFEST_ENTRY_NAME
        assert names[:-1] == sorted(names[:-1])
        manifest = json.loads(zf.read(MANIFEST_ENTRY_NAME).decode("utf-8"))
        assert manifest["file_count"] == data_a["file_count"]
        assert manifest["archive_sha256"] == data_a["archive_sha256"]
        assert manifest["resolved_sha"] == data_a["resolved_sha"]
        for key in MANIFEST_KEYS:
            assert key in manifest


# 11. resolved SHA is rechecked immediately before archive creation -----------

def test_head_drift_between_preparation_and_packaging_is_rejected(clone: Path, tmp_path: Path, origin: Path):
    # The bounded `drift-head` control moves the prepared worktree's HEAD back
    # one commit inside the same invocation, after preparation and before the
    # exact-head verification -- the only way to reach the
    # `actual_head != RESOLVED_SHA` branch, which a dirty-tree proxy never
    # touches. The worktree stays clean, so EXIT_DIRTY cannot mask the result:
    # delete that check and this build succeeds instead.
    output = tmp_path / "pkg-drift.zip"
    result = run(
        clone, tmp_path, "--ref", "main", "--output", str(output),
        origin=origin, test_action="drift-head",
    )
    assert result.returncode == EXIT_EVIDENCE, result.stderr
    data = evidence(result)
    assert data["status"] == "manual-review"
    assert "no longer matches resolved commit" in data["reason"]
    assert not output.exists()
    assert temp_archives(tmp_path) == []


def test_drift_control_refuses_an_operator_supplied_worktree(clone: Path, tmp_path: Path, origin: Path):
    # The control may only write to a disposable worktree this run created. An
    # operator-supplied root survives cleanup, so a moved HEAD would outlive the
    # run — an unbounded side effect on a directory the command must not alter.
    worktree_root = tmp_path / "operator-root"
    prep = subprocess.run(
        ["bash", str(ROOT / "scripts" / "prepare-issue-worktree.sh"),
         "--issue", "881", "--repository", repository_identity(origin), "--ref", "main",
         "--worktree-root", str(worktree_root)],
        cwd=clone, text=True, capture_output=True, env=_env(tmp_path),
    )
    assert prep.returncode == EXIT_OK, prep.stderr
    worktree_path = worktree_root / "issue-881"
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=worktree_path, text=True,
        capture_output=True, env=_env(tmp_path),
    ).stdout.strip()

    output = tmp_path / "pkg-drift-supplied.zip"
    result = run(
        clone, tmp_path, "--ref", "main", "--output", str(output),
        worktree_root=worktree_root, origin=origin, test_action="drift-head",
    )
    assert result.returncode == EXIT_USAGE, result.stderr
    assert evidence(result)["status"] == "blocked"
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=worktree_path, text=True,
        capture_output=True, env=_env(tmp_path),
    ).stdout.strip()
    assert head_after == head_before
    assert not output.exists()


# 13. line endings and host paths are not silently transformed ----------------

def test_line_endings_are_preserved(clone: Path, tmp_path: Path, origin: Path):
    commit(clone, "crlf.txt", "crlf commit", content="line1\r\nline2\r\n")
    git(clone, "push", "origin", "main")
    output = tmp_path / "pkg-crlf.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OK, result.stderr
    with zipfile.ZipFile(output) as zf:
        assert zf.read("crlf.txt") == b"line1\r\nline2\r\n"


# 14. credentials, caches, and unrelated local artifacts are excluded ---------

def test_tracked_env_file_is_excluded(clone: Path, tmp_path: Path, origin: Path):
    output = tmp_path / "pkg-secrets.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OK, result.stderr
    with zipfile.ZipFile(output) as zf:
        assert ".env" not in zf.namelist()
    assert "excluding tracked path .env" in result.stderr


# 15. required Agent OS paths are present --------------------------------------

def test_required_paths_present(clone: Path, tmp_path: Path, origin: Path):
    output = tmp_path / "pkg-required.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OK, result.stderr
    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
        assert "scripts/prepare-issue-worktree.sh" in names
        assert "a.txt" in names


# 16. a package built for one head cannot claim another head ------------------

def test_manifest_head_is_not_reusable_for_a_different_head(clone: Path, tmp_path: Path, origin: Path):
    output_main = tmp_path / "pkg-main.zip"
    output_tag = tmp_path / "pkg-v1.zip"
    r1 = run(clone, tmp_path, "--ref", "main", "--output", str(output_main), origin=origin)
    r2 = run(clone, tmp_path, "--ref", "v1.0", "--output", str(output_tag), origin=origin)
    assert r1.returncode == EXIT_OK and r2.returncode == EXIT_OK
    d1, d2 = evidence(r1), evidence(r2)
    assert d1["resolved_sha"] == d2["resolved_sha"]  # v1.0 tags the same commit as main here
    assert d1["checkout_mode"] != d2["checkout_mode"]
    with zipfile.ZipFile(output_main) as zf:
        m1 = json.loads(zf.read(MANIFEST_ENTRY_NAME))
    with zipfile.ZipFile(output_tag) as zf:
        m2 = json.loads(zf.read(MANIFEST_ENTRY_NAME))
    assert m1["requested_ref"] != m2["requested_ref"]
    assert m1["resolved_ref"] != m2["resolved_ref"]


# 17. malformed or tampered manifest/archive fails verification ---------------

def test_tampered_archive_is_rejected_by_production_verification(clone: Path, tmp_path: Path, origin: Path):
    # The bounded `tamper-archive` control rewrites the real temporary ZIP on
    # disk after it is written and before the builder reopens it, keeping every
    # CRC valid so zipfile's own integrity check still passes. Only the
    # production reopen-and-recompute step can catch it: delete that step and
    # the tampered archive publishes successfully instead.
    output = tmp_path / "pkg-tamper.zip"
    result = run(
        clone, tmp_path, "--ref", "main", "--output", str(output),
        origin=origin, test_action="tamper-archive",
    )
    assert result.returncode == EXIT_EVIDENCE, result.stderr
    assert evidence(result)["status"] == "unavailable"
    assert "test-only control tampered with the temporary archive" in result.stderr
    assert "post-write archive digest does not match recorded archive_sha256" in result.stderr
    # A failed verification never publishes, and leaves no temporary behind.
    assert not output.exists()
    assert temp_archives(tmp_path) == []


# Regression: tracked symlinks are rejected, never dereferenced -------------

def test_tracked_symlink_pointing_outside_worktree_is_rejected(clone: Path, tmp_path: Path, origin: Path):
    outside_target = tmp_path / "outside-secret.txt"
    outside_target.write_text("outside the worktree\n", encoding="utf-8")
    link_path = clone / "link-outside"
    link_path.symlink_to(outside_target)
    git(clone, "add", "link-outside")
    git(clone, "commit", "-m", "add tracked symlink pointing outside the worktree")
    git(clone, "push", "origin", "main")

    output = tmp_path / "pkg-symlink.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_SYMLINK, result.stderr
    data = evidence(result)
    assert data["status"] == "blocked"
    assert "link-outside" in data["reason"]
    assert "symlink" in data["reason"]
    assert not output.exists()


# Regression: disposable worktree cleanup policy -----------------------------

def test_clean_disposable_worktree_is_removed_after_a_normal_run(clone: Path, tmp_path: Path, origin: Path):
    output = tmp_path / "pkg-cleanup-clean.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OK, result.stderr

    match = re.search(r"cleanup: disposable worktree removed: (\S+)", result.stderr)
    assert match, result.stderr
    removed_path = Path(match.group(1))
    assert not removed_path.exists()
    assert not removed_path.parent.exists()


def test_supplied_worktree_root_is_never_removed(clone: Path, tmp_path: Path, origin: Path):
    worktree_root = tmp_path / "operator-supplied-root"
    output = tmp_path / "pkg-cleanup-supplied.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), worktree_root=worktree_root, origin=origin)
    assert result.returncode == EXIT_OK, result.stderr
    assert "preserved operator-supplied worktree root" in result.stderr
    assert (worktree_root / "issue-881").is_dir()
    assert (worktree_root / "issue-881" / "a.txt").exists()


# A disposable worktree can only be dirty at cleanup time in a scenario this
# command cannot reach in one invocation (it fails closed on dirty state before
# ever reaching cleanup), so these exercise cleanup_worktree() directly -- the
# same defense-in-depth path the script's own EXIT trap runs.

# Every path below is interpolated into `bash -c` source, so the fixture root
# deliberately carries whitespace and shell metacharacters: without correct
# quoting Bash would parse different commands and the assertions would be
# meaningless.
HOSTILE_ROOT_NAME = "disposable root 'x' \"y\" $(touch pwned) `touch pwned2` ;&|*"


def run_cleanup(
    clone: Path, tmp_path: Path, disposable_root: Path, worktree_path: Path,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    script_snippet = f"""
set -uo pipefail
export BUILD_CHATGPT_PACKAGE_TEST_ONLY=1
source {shlex.quote(str(SCRIPT))}
WORKTREE_ROOT_PROVIDED=0
WORKTREE_ROOT={shlex.quote(str(disposable_root))}
WORKTREE_PATH={shlex.quote(str(worktree_path))}
cleanup_worktree
"""
    return subprocess.run(
        ["bash", "-c", script_snippet],
        cwd=cwd or clone, text=True, capture_output=True, env=_env(tmp_path),
    )


def add_disposable_worktree(clone: Path, tmp_path: Path, root_name: str = HOSTILE_ROOT_NAME):
    disposable_root = tmp_path / root_name
    worktree_path = disposable_root / "issue-881"
    subprocess.run(
        ["git", "worktree", "add", "--quiet", "--detach", str(worktree_path), "HEAD"],
        cwd=clone, check=True, capture_output=True, env=_env(tmp_path),
    )
    return disposable_root, worktree_path


def assert_no_shell_injection(tmp_path: Path) -> None:
    assert not list(tmp_path.rglob("pwned"))
    assert not list(tmp_path.rglob("pwned2"))


def test_tracked_changes_prevent_disposable_worktree_cleanup(clone: Path, tmp_path: Path):
    disposable_root, worktree_path = add_disposable_worktree(clone, tmp_path)
    (worktree_path / "a.txt").write_text("dirty\n", encoding="utf-8")

    result = run_cleanup(clone, tmp_path, disposable_root, worktree_path)
    assert result.returncode == 0, result.stderr
    assert "preserved without removal" in result.stderr
    assert (worktree_path / "a.txt").read_text(encoding="utf-8") == "dirty\n"
    assert_no_shell_injection(tmp_path)


def test_untracked_data_prevents_disposable_worktree_cleanup(clone: Path, tmp_path: Path):
    # `git status --porcelain` must report untracked files: hiding them with
    # --untracked-files=no and then removing --force would destroy data this
    # command never created.
    disposable_root, worktree_path = add_disposable_worktree(clone, tmp_path)
    unsaved = worktree_path / "operator-notes.txt"
    unsaved.write_text("unsaved work\n", encoding="utf-8")

    result = run_cleanup(clone, tmp_path, disposable_root, worktree_path)
    assert result.returncode == 0, result.stderr
    assert "preserved without removal" in result.stderr
    assert unsaved.read_text(encoding="utf-8") == "unsaved work\n"
    assert_no_shell_injection(tmp_path)


def test_failed_cleanup_preserves_the_worktree_as_evidence(clone: Path, tmp_path: Path, origin: Path):
    # A clean worktree whose removal Git refuses (here: attempted from a
    # different checkout, which does not own it) is preserved, not discarded.
    disposable_root, worktree_path = add_disposable_worktree(clone, tmp_path)
    other = tmp_path / "other-clone"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(other)],
        check=True, capture_output=True, env=_env(tmp_path),
    )

    result = run_cleanup(clone, tmp_path, disposable_root, worktree_path, cwd=other)
    assert result.returncode == 0, result.stderr
    assert "removal failed; preserved" in result.stderr
    assert worktree_path.is_dir()
    assert (worktree_path / "a.txt").exists()
    assert_no_shell_injection(tmp_path)


def test_unverifiable_cleanliness_preserves_the_directory(clone: Path, tmp_path: Path):
    # Cleanliness that cannot be determined is never treated as clean.
    disposable_root = tmp_path / HOSTILE_ROOT_NAME
    worktree_path = disposable_root / "issue-881"
    worktree_path.mkdir(parents=True)
    (worktree_path / "not-a-worktree.txt").write_text("opaque\n", encoding="utf-8")

    result = run_cleanup(clone, tmp_path, disposable_root, worktree_path, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "preserved without removal" in result.stderr
    assert (worktree_path / "not-a-worktree.txt").exists()
    assert_no_shell_injection(tmp_path)


# 18 & 19. no lifecycle mutation occurs; all authority fields stay false ------

def test_no_lifecycle_mutation_and_authority_fields_false(clone: Path, tmp_path: Path, origin: Path):
    before_sha = git(clone, "rev-parse", "HEAD").stdout.strip()
    before_branches = git(clone, "branch", "-a").stdout
    output = tmp_path / "pkg-authority.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OK, result.stderr
    data = evidence(result)
    for key in AUTHORITY_KEYS:
        assert data[key] is False
    assert git(clone, "rev-parse", "HEAD").stdout.strip() == before_sha
    assert git(clone, "branch", "-a").stdout == before_branches
    assert git(clone, "status", "--porcelain").stdout == ""


# 20. focused validation (usage/help) ------------------------------------------

def test_usage_error_on_missing_required_argument(clone: Path, tmp_path: Path):
    result = subprocess.run(
        ["bash", str(SCRIPT), "--repository", "origin/repo", "--issue", "881"],
        cwd=clone, text=True, capture_output=True, env=_env(tmp_path),
    )
    assert result.returncode == EXIT_USAGE


def test_output_must_be_absolute_zip_path(clone: Path, tmp_path: Path, origin: Path):
    result = run(clone, tmp_path, "--ref", "main", "--output", "relative.zip", origin=origin)
    assert result.returncode == EXIT_USAGE

    result2 = run(clone, tmp_path, "--ref", "main", "--output", str(tmp_path / "pkg.tar"), origin=origin)
    assert result2.returncode == EXIT_USAGE


def test_script_is_syntactically_valid_bash():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# Regression: stdout is one safely serialized JSON object ---------------------

HOSTILE_DIR_NAME = 'out dir \'q\' "d" $(touch pwned) `touch pwned2` ;&|* \\ back'
HOSTILE_ZIP_NAME = 'pkg "quoted" \\back space\nnewline.zip'


def test_accepted_hostile_output_path_round_trips_through_json(clone: Path, tmp_path: Path, origin: Path):
    # Quotes, backslashes, spaces, shell metacharacters, and a newline in an
    # accepted pathname must be escaped by the serializer, not interpolated
    # into JSON syntax or re-parsed by a shell.
    hostile_dir = tmp_path / HOSTILE_DIR_NAME
    hostile_dir.mkdir()
    output = hostile_dir / HOSTILE_ZIP_NAME

    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OK, result.stderr

    data = json.loads(result.stdout)  # fails outright if stdout is not one JSON object
    assert data["status"] == "built"
    assert data["output_path"] == str(output)
    assert output.exists()
    assert temp_archives(hostile_dir) == []
    assert_no_shell_injection(tmp_path)


def test_hostile_rejected_values_round_trip_through_json(clone: Path, tmp_path: Path, origin: Path):
    # The same guarantee on failure paths, where user-controlled values also
    # reach `reason`.
    hostile_ref = 'no-such-"branch" \\ $(touch pwned) ;&|*'
    output = tmp_path / "pkg-hostile-ref.zip"
    result = run(clone, tmp_path, "--ref", hostile_ref, "--output", str(output), origin=origin)
    assert result.returncode != EXIT_OK
    data = json.loads(result.stdout)
    assert data["requested_ref"] == hostile_ref
    assert data["status"] in {"blocked", "manual-review", "unavailable"}

    hostile_repo = 'ow"ner/re\\po $(touch pwned)'
    result2 = subprocess.run(
        ["bash", str(SCRIPT), "--repository", hostile_repo, "--issue", "881",
         "--ref", "main", "--output", str(tmp_path / "pkg-hostile-repo.zip")],
        cwd=clone, text=True, capture_output=True, env=_env(tmp_path),
    )
    assert result2.returncode != EXIT_OK
    data2 = json.loads(result2.stdout)
    assert data2["repository"] == hostile_repo
    # Numbers stay numbers, booleans stay booleans, nulls stay null.
    assert data2["issue_number"] == 881
    assert data2["file_count"] == 0
    assert data2["working_tree_clean"] is False
    assert data2["resolved_sha"] == ""
    assert_no_shell_injection(tmp_path)


def test_evidence_types_are_preserved_on_success(clone: Path, tmp_path: Path, origin: Path):
    output = tmp_path / "pkg-types.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OK, result.stderr
    data = json.loads(result.stdout)
    assert isinstance(data["issue_number"], int)
    assert isinstance(data["file_count"], int) and data["file_count"] > 0
    assert data["working_tree_clean"] is True
    assert data["included_git_metadata"] is False
    assert data["side_effects_performed"] == ["worktree-prepared", "archive-written"]
    for key in AUTHORITY_KEYS:
        assert data[key] is False


# Regression: atomic, no-replace archive publication --------------------------

def test_dangling_destination_symlink_is_rejected_and_its_target_untouched(clone: Path, tmp_path: Path, origin: Path):
    target = tmp_path / "never-created.txt"
    output = tmp_path / "pkg-dangling.zip"
    output.symlink_to(target)
    assert output.is_symlink() and not target.exists()

    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OUTPUT, result.stderr
    assert evidence(result)["status"] == "blocked"
    # The symlink is neither followed nor replaced, so its target is never made.
    assert output.is_symlink()
    assert not target.exists()
    assert temp_archives(tmp_path) == []


def test_second_publisher_cannot_replace_the_first_archive(clone: Path, tmp_path: Path, origin: Path):
    output = tmp_path / "pkg-once.zip"
    first = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert first.returncode == EXIT_OK, first.stderr
    original_bytes = output.read_bytes()

    second = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert second.returncode == EXIT_OUTPUT
    assert evidence(second)["status"] == "blocked"
    assert output.read_bytes() == original_bytes
    assert temp_archives(tmp_path) == []


def test_existing_directory_destination_is_rejected(clone: Path, tmp_path: Path, origin: Path):
    output = tmp_path / "pkg-dir.zip"
    output.mkdir()
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OUTPUT
    assert output.is_dir()
    assert temp_archives(tmp_path) == []


# Regression: packaged bytes come from RESOLVED_SHA, not the worktree ---------

def test_worktree_mutation_cannot_change_bytes_attributed_to_the_commit(clone: Path, tmp_path: Path, origin: Path):
    baseline_output = tmp_path / "pkg-baseline.zip"
    baseline = run(clone, tmp_path, "--ref", "main", "--output", str(baseline_output), origin=origin)
    assert baseline.returncode == EXIT_OK, baseline.stderr
    committed_bytes = zipfile.ZipFile(baseline_output).read("a.txt")

    worktree_root = tmp_path / "mutation-root"
    prep = subprocess.run(
        ["bash", str(ROOT / "scripts" / "prepare-issue-worktree.sh"),
         "--issue", "881", "--repository", repository_identity(origin), "--ref", "main",
         "--worktree-root", str(worktree_root)],
        cwd=clone, text=True, capture_output=True, env=_env(tmp_path),
    )
    assert prep.returncode == EXIT_OK, prep.stderr
    worktree_path = worktree_root / "issue-881"

    # Mutate a tracked file while keeping the worktree reported clean, which is
    # exactly the state a change landing after the clean-state check produces.
    # Reading bytes from the worktree would package "mutated"; reading them from
    # the commit object cannot.
    subprocess.run(
        ["git", "update-index", "--assume-unchanged", "a.txt"],
        cwd=worktree_path, check=True, capture_output=True, env=_env(tmp_path),
    )
    (worktree_path / "a.txt").write_text("mutated after verification\n", encoding="utf-8")

    output = tmp_path / "pkg-from-commit.zip"
    result = run(
        clone, tmp_path, "--ref", "main", "--output", str(output),
        worktree_root=worktree_root, origin=origin,
    )
    assert result.returncode == EXIT_OK, result.stderr
    with zipfile.ZipFile(output) as zf:
        assert zf.read("a.txt") == committed_bytes
        assert b"mutated" not in zf.read("a.txt")
    # The manifest digest therefore still describes the commit, unchanged.
    assert evidence(result)["archive_sha256"] == evidence(baseline)["archive_sha256"]


# Regression: unsupported Git modes are rejected before any read --------------
#
# Git's own object writer only emits 100644, 100755, 120000, 160000, and tree
# modes, so no deterministic fixture can produce a genuinely unknown mode; that
# branch is covered by construction instead -- MODE_CATEGORY is an allowlist, so
# anything unlisted is rejected rather than permitted by default.

def test_tracked_symlink_on_an_excluded_path_is_still_rejected(clone: Path, tmp_path: Path, origin: Path):
    # `secrets.pem` matches the static exclusion list. Filtering it away instead
    # of refusing it would let a tracked symlink pass silently.
    outside_target = tmp_path / "outside-key.txt"
    outside_target.write_text("outside the worktree\n", encoding="utf-8")
    (clone / "secrets.pem").symlink_to(outside_target)
    git(clone, "add", "secrets.pem")
    git(clone, "commit", "-m", "add tracked symlink on an excluded path")
    git(clone, "push", "origin", "main")

    output = tmp_path / "pkg-excluded-symlink.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_SYMLINK, result.stderr
    data = evidence(result)
    assert data["status"] == "blocked"
    assert "secrets.pem" in data["reason"]
    assert "symlink" in data["reason"]
    assert not output.exists()


def test_tracked_gitlink_is_rejected_without_opening_a_directory(clone: Path, tmp_path: Path, origin: Path):
    submodule_sha = git(clone, "rev-parse", "HEAD").stdout.strip()
    git(clone, "update-index", "--add", "--cacheinfo", f"160000,{submodule_sha},vendor/sub")
    (clone / "vendor" / "sub").mkdir(parents=True, exist_ok=True)
    git(clone, "commit", "-m", "add a tracked gitlink")
    git(clone, "push", "origin", "main")

    output = tmp_path / "pkg-gitlink.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_SYMLINK, result.stderr
    data = evidence(result)
    assert data["status"] == "blocked"
    assert "vendor/sub" in data["reason"]
    assert "gitlink" in data["reason"]
    # A defined rejection, not an uncontrolled error from open()ing a directory.
    assert "IsADirectoryError" not in result.stderr
    assert not output.exists()


def test_external_symlink_target_bytes_never_enter_any_archive(clone: Path, tmp_path: Path, origin: Path):
    secret = tmp_path / "outside-secret.txt"
    secret.write_text("SENTINEL-OUTSIDE-CONTENT\n", encoding="utf-8")
    (clone / "link-outside").symlink_to(secret)
    git(clone, "add", "link-outside")
    git(clone, "commit", "-m", "add tracked symlink pointing outside")
    git(clone, "push", "origin", "main")

    output = tmp_path / "pkg-no-leak.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_SYMLINK
    assert not output.exists()
    assert "SENTINEL-OUTSIDE-CONTENT" not in result.stdout
    for archive in tmp_path.rglob("*.zip"):
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                assert b"SENTINEL-OUTSIDE-CONTENT" not in zf.read(name)


# Regression: the generated manifest pathname is reserved and unique ----------

def test_commit_tracking_the_reserved_manifest_pathname_is_rejected(clone: Path, tmp_path: Path, origin: Path):
    commit(clone, MANIFEST_ENTRY_NAME, "track the reserved manifest pathname", content="{}\n")
    git(clone, "push", "origin", "main")

    output = tmp_path / "pkg-reserved.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_EVIDENCE, result.stderr
    data = evidence(result)
    assert data["status"] == "blocked"
    assert MANIFEST_ENTRY_NAME in data["reason"]
    assert not output.exists()
    assert temp_archives(tmp_path) == []


def test_archive_entry_names_are_unique_and_the_manifest_appears_once(clone: Path, tmp_path: Path, origin: Path):
    output = tmp_path / "pkg-unique.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OK, result.stderr
    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
    assert len(names) == len(set(names))
    assert names.count(MANIFEST_ENTRY_NAME) == 1
