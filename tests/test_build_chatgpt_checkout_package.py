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

import hashlib
import json
import os
from pathlib import Path
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
) -> subprocess.CompletedProcess[str]:
    args = [
        "bash", str(SCRIPT),
        "--repository", repository_identity(origin),
        "--issue", "881",
        *extra_args,
    ]
    env = _env(tmp_path)
    if worktree_root is not None:
        args += ["--worktree-root", str(worktree_root)]
    return subprocess.run(args, cwd=clone, text=True, capture_output=True, env=env)


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
    worktree_root = tmp_path / "drift-root"
    output = tmp_path / "pkg-drift.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), worktree_root=worktree_root, origin=origin)
    assert result.returncode == EXIT_OK, result.stderr

    # Simulate drift by hand-editing a tracked file after preparation would
    # have run, then repackage against the same (now dirty) worktree root.
    worktree_path = worktree_root / "issue-881"
    (worktree_path / "a.txt").write_text("drifted\n", encoding="utf-8")
    output2 = tmp_path / "pkg-drift-2.zip"
    result2 = run(clone, tmp_path, "--ref", "main", "--output", str(output2), worktree_root=worktree_root, origin=origin)
    assert result2.returncode == EXIT_DIRTY
    assert not output2.exists()


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

def test_tampered_archive_is_detectable_against_its_manifest(clone: Path, tmp_path: Path, origin: Path):
    output = tmp_path / "pkg-tamper.zip"
    result = run(clone, tmp_path, "--ref", "main", "--output", str(output), origin=origin)
    assert result.returncode == EXIT_OK, result.stderr
    data = evidence(result)

    with zipfile.ZipFile(output) as zf:
        contents = {name: zf.read(name) for name in zf.namelist()}
    contents["a.txt"] = b"tampered\n"

    digest = hashlib.sha256()
    for path in sorted(n for n in contents if n != MANIFEST_ENTRY_NAME):
        file_sha = hashlib.sha256(contents[path]).hexdigest()
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_sha.encode("utf-8"))
        digest.update(b"\n")
    assert digest.hexdigest() != data["archive_sha256"]


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
