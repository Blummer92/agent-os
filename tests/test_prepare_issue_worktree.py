"""Focused tests for scripts/prepare-issue-worktree.sh.

Deterministic and fully offline: every test builds an isolated temporary bare
"origin" plus a clone under tmp_path. No live GitHub access, no credentials, no
Cloud calls, and no Workflow Scheduler execution occur. Bounded fetch retry is
exercised through VERIFY_REPO_STATE_RETRY_DELAYS -- the canonical
repository-state retry variable -- so no test sleeps for real backoff.

Covers the twenty behaviors required by issue #807.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare-issue-worktree.sh"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DIRTY = 3
EXIT_FETCH = 4
EXIT_REF_MISSING = 5
EXIT_WORKTREE = 6
EXIT_CONFLICT = 7
EXIT_BASE = 8

EVIDENCE_KEYS = [
    "schema",
    "status",
    "issue_number",
    "repository",
    "requested_ref",
    "resolved_ref",
    "resolved_sha",
    "checkout_mode",
    "head_state",
    "worktree_path",
    "worktree_reused",
    "working_tree_clean",
    "remote_fetch_performed",
    "branch_created",
    "side_effects_performed",
    "repository_implementation_authorized",
    "execution_authorized",
    "github_writes_authorized",
    "merge_authorized",
    "reason",
]

AUTHORITY_KEYS = [
    "repository_implementation_authorized",
    "execution_authorized",
    "github_writes_authorized",
    "merge_authorized",
]

MAX_REASON_CHARS = 200


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
            # Three bounded attempts, no real sleeping.
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


def commit(repo: Path, name: str, message: str) -> None:
    (repo / name).write_text(f"{name}\n", encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-m", message)


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """Bare origin with `main`, `feature/topic`, and an annotated tag."""
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
    commit(seed, "base.txt", "base commit")
    git(seed, "push", "--quiet", "--set-upstream", "origin", "main")
    git(seed, "switch", "--quiet", "--create", "feature/topic")
    commit(seed, "topic.txt", "topic commit")
    git(seed, "push", "--quiet", "--set-upstream", "origin", "feature/topic")
    git(seed, "tag", "--annotate", "v1.0.0", "--message", "release 1.0.0")
    git(seed, "tag", "lightweight-1.0.0")
    git(seed, "push", "--quiet", "origin", "v1.0.0", "lightweight-1.0.0")
    return bare


@pytest.fixture
def clone(tmp_path: Path, origin: Path) -> Path:
    target = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(target)],
        check=True, capture_output=True, env=_env(tmp_path),
    )
    return target


@pytest.fixture
def worktree_root(tmp_path: Path) -> Path:
    """Worktree root path; deliberately not created, so first-run creation runs."""
    return tmp_path / "agent-os-worktrees"


def repository_identity(origin: Path) -> str:
    """Identity the script derives from the origin URL: <owner>/<name>."""
    return f"{origin.parent.name}/{origin.name[: -len('.git')]}"


def prepare(
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


def request(
    clone: Path,
    origin: Path,
    root: Path,
    issue: str = "807",
    ref: str = "feature/topic",
    *extra: str,
    repository: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return prepare(
        clone,
        "--issue", issue,
        "--repository", repository or repository_identity(origin),
        "--ref", ref,
        "--worktree-root", str(root),
        *extra,
    )


def evidence(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    """Parse stdout as the evidence contract and assert its invariants."""
    parsed = json.loads(result.stdout)
    assert list(parsed) == EVIDENCE_KEYS, "evidence key order must be deterministic"
    assert parsed["schema"] == "agent-os.issue-worktree-preparation.v1"
    assert parsed["status"] in {
        "prepared", "already-prepared", "manual-review", "blocked", "unavailable",
    }
    # 20: checkout success -- and every other outcome -- leaves authority false.
    for key in AUTHORITY_KEYS:
        assert parsed[key] is False, f"{key} must never be true"
    assert len(str(parsed["reason"])) <= MAX_REASON_CHARS
    # 19: the human summary is on stderr; stdout carries evidence only.
    assert "STATUS=" in result.stderr
    return parsed


def remote_state(origin: Path) -> str:
    return subprocess.run(
        ["git", "ls-remote", str(origin)],
        check=True, text=True, capture_output=True, env=_env(origin.parent),
    ).stdout


def worktree_paths(clone: Path) -> list[str]:
    listing = git(clone, "worktree", "list", "--porcelain").stdout
    return [line[len("worktree "):] for line in listing.splitlines() if line.startswith("worktree ")]


# --- 2/3/4/5: success paths for branch, tag, and exact SHA ------------------


def test_existing_local_branch_prepares_detached_at_its_exact_commit(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    git(clone, "branch", "local/work", "origin/feature/topic")
    expected = git(clone, "rev-parse", "refs/heads/local/work").stdout.strip()

    result = request(clone, origin, worktree_root, ref="local/work")
    assert result.returncode == EXIT_OK, result.stderr
    parsed = evidence(result)
    assert parsed["status"] == "prepared"
    assert parsed["checkout_mode"] == "branch"
    assert parsed["head_state"] == "detached"
    assert parsed["resolved_ref"] == "refs/heads/local/work"
    assert parsed["resolved_sha"] == expected
    assert parsed["working_tree_clean"] is True
    assert parsed["branch_created"] is False

    path = Path(str(parsed["worktree_path"]))
    assert path == worktree_root / "issue-807"
    assert git(path, "rev-parse", "HEAD").stdout.strip() == expected
    # 5: detached preparation is reproducible -- HEAD is not on a branch.
    assert git(path, "symbolic-ref", "--quiet", "HEAD", check=False).returncode != 0


def test_remote_only_branch_prepares_without_creating_a_local_branch(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    assert "feature/topic" not in git(clone, "branch", "--list").stdout
    result = request(clone, origin, worktree_root)
    assert result.returncode == EXIT_OK, result.stderr
    parsed = evidence(result)
    assert parsed["resolved_ref"] == "refs/remotes/origin/feature/topic"
    assert parsed["branch_created"] is False
    # Checkout-only: no local branch was invented for the operator.
    assert "feature/topic" not in git(clone, "branch", "--list").stdout


@pytest.mark.parametrize("tag", ["v1.0.0", "lightweight-1.0.0"])
def test_tag_prepares_at_the_exact_tagged_commit(
    clone: Path, origin: Path, worktree_root: Path, tag: str
) -> None:
    expected = git(clone, "rev-parse", f"refs/tags/{tag}^{{commit}}").stdout.strip()
    result = request(clone, origin, worktree_root, ref=tag)
    assert result.returncode == EXIT_OK, result.stderr
    parsed = evidence(result)
    assert parsed["checkout_mode"] == "tag"
    assert parsed["resolved_ref"] == f"refs/tags/{tag}"
    assert parsed["resolved_sha"] == expected
    assert git(worktree_root / "issue-807", "rev-parse", "HEAD").stdout.strip() == expected


def test_exact_sha_prepares_a_detached_worktree(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    sha = git(clone, "rev-parse", "origin/main").stdout.strip()
    result = request(clone, origin, worktree_root, ref=sha)
    assert result.returncode == EXIT_OK, result.stderr
    parsed = evidence(result)
    assert parsed["checkout_mode"] == "detached-sha"
    assert parsed["head_state"] == "detached"
    assert parsed["resolved_ref"] == sha
    assert parsed["resolved_sha"] == sha
    assert git(worktree_root / "issue-807", "rev-parse", "HEAD").stdout.strip() == sha


def test_attached_branch_mode_checks_the_branch_out_in_the_worktree(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    git(clone, "branch", "local/work", "origin/feature/topic")
    result = request(clone, origin, worktree_root, "807", "local/work", "--attach-branch")
    assert result.returncode == EXIT_OK, result.stderr
    parsed = evidence(result)
    assert parsed["head_state"] == "attached"
    head_ref = git(worktree_root / "issue-807", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert head_ref == "local/work"


# --- 9: branch names containing slashes -------------------------------------


def test_branch_names_with_slashes_are_supported(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    git(clone, "branch", "agent/807/deep/path", "origin/feature/topic")
    result = request(clone, origin, worktree_root, ref="agent/807/deep/path")
    assert result.returncode == EXIT_OK, result.stderr
    assert evidence(result)["resolved_ref"] == "refs/heads/agent/807/deep/path"


# --- 6: missing branch, tag, and SHA fail closed ----------------------------


@pytest.mark.parametrize(
    "ref",
    [
        "agent/does-not-exist",
        "v9.9.9-missing",
        "0123456789012345678901234567890123456789",
    ],
)
def test_missing_targets_fail_closed_without_inference(
    clone: Path, origin: Path, worktree_root: Path, ref: str
) -> None:
    result = request(clone, origin, worktree_root, ref=ref)
    assert result.returncode == EXIT_REF_MISSING
    parsed = evidence(result)
    assert parsed["status"] == "blocked"
    assert parsed["resolved_sha"] == ""
    assert not worktree_root.exists(), "a failed request must not create the root"
    assert worktree_paths(clone) == [str(clone)]


def test_ambiguous_branch_and_tag_name_routes_to_manual_review(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    git(clone, "branch", "release-candidate", "origin/main")
    git(clone, "tag", "release-candidate", "origin/feature/topic")
    result = request(clone, origin, worktree_root, ref="release-candidate")
    assert result.returncode == EXIT_CONFLICT
    parsed = evidence(result)
    assert parsed["status"] == "manual-review"
    assert "ambiguous" in str(parsed["reason"])


def test_local_and_remote_branch_disagreement_routes_to_manual_review(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    git(clone, "branch", "feature/topic", "origin/main")  # deliberately stale
    result = request(clone, origin, worktree_root)
    assert result.returncode == EXIT_CONFLICT
    assert evidence(result)["status"] == "manual-review"
    assert not worktree_root.exists()


# --- 7/8: dirty and untracked policy ----------------------------------------


def test_dirty_tracked_state_blocks_reuse_without_losing_work(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    assert request(clone, origin, worktree_root).returncode == EXIT_OK
    dirty_file = worktree_root / "issue-807" / "topic.txt"
    dirty_file.write_text("operator edit in progress\n", encoding="utf-8")

    result = request(clone, origin, worktree_root)
    assert result.returncode == EXIT_DIRTY
    parsed = evidence(result)
    assert parsed["status"] == "blocked"
    assert parsed["side_effects_performed"] == []
    # Work is preserved: never stashed, reset, cleaned, or checked out over.
    assert dirty_file.read_text(encoding="utf-8") == "operator edit in progress\n"


def test_untracked_files_are_reported_but_never_block_or_change(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    assert request(clone, origin, worktree_root).returncode == EXIT_OK
    scratch = worktree_root / "issue-807" / "scratch.txt"
    scratch.write_text("scratch\n", encoding="utf-8")

    result = request(clone, origin, worktree_root)
    assert result.returncode == EXIT_OK, result.stderr
    assert evidence(result)["status"] == "already-prepared"
    assert "untracked files present" in result.stderr
    assert scratch.read_text(encoding="utf-8") == "scratch\n"


# --- 12/13: idempotency and conflicting requests ----------------------------


def test_duplicate_request_is_idempotent_and_performs_no_side_effects(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    first = request(clone, origin, worktree_root)
    assert first.returncode == EXIT_OK, first.stderr
    head_before = git(worktree_root / "issue-807", "rev-parse", "HEAD").stdout.strip()

    second = request(clone, origin, worktree_root)
    assert second.returncode == EXIT_OK, second.stderr
    parsed = evidence(second)
    assert parsed["status"] == "already-prepared"
    assert parsed["worktree_reused"] is True
    assert parsed["side_effects_performed"] == []
    assert git(worktree_root / "issue-807", "rev-parse", "HEAD").stdout.strip() == head_before


def test_same_issue_with_a_conflicting_ref_routes_to_manual_review(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    assert request(clone, origin, worktree_root).returncode == EXIT_OK
    head_before = git(worktree_root / "issue-807", "rev-parse", "HEAD").stdout.strip()

    result = request(clone, origin, worktree_root, ref="main")
    assert result.returncode == EXIT_CONFLICT
    parsed = evidence(result)
    assert parsed["status"] == "manual-review"
    assert parsed["side_effects_performed"] == []
    # The already-prepared worktree is left exactly as it was.
    assert git(worktree_root / "issue-807", "rev-parse", "HEAD").stdout.strip() == head_before


def test_worktree_prepared_for_another_issue_is_never_taken_over(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    assert request(clone, origin, worktree_root, issue="807").returncode == EXIT_OK
    marker = clone / ".git" / "worktrees" / "issue-807" / "agent-os-issue-identity"
    marker.write_text(
        marker.read_text(encoding="utf-8").replace("issue_number=807", "issue_number=726"),
        encoding="utf-8",
    )
    result = request(clone, origin, worktree_root, issue="807")
    assert result.returncode == EXIT_CONFLICT
    assert "owned by issue #726" in str(evidence(result)["reason"])


def test_reuse_requires_an_identity_record(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    assert request(clone, origin, worktree_root).returncode == EXIT_OK
    (clone / ".git" / "worktrees" / "issue-807" / "agent-os-issue-identity").unlink()
    result = request(clone, origin, worktree_root)
    assert result.returncode == EXIT_CONFLICT
    assert "identity" in str(evidence(result)["reason"])


def test_head_drift_in_a_prepared_worktree_fails_closed(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    assert request(clone, origin, worktree_root).returncode == EXIT_OK
    path = worktree_root / "issue-807"
    git(path, "checkout", "--detach", "origin/main")
    result = request(clone, origin, worktree_root)
    assert result.returncode == EXIT_CONFLICT
    assert "no longer matches" in str(evidence(result)["reason"])


# --- Multi-issue isolation ---------------------------------------------------


def test_separate_issues_use_separate_worktrees_and_never_move_the_primary(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    primary_head = git(clone, "rev-parse", "HEAD").stdout.strip()
    primary_branch = git(clone, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    assert request(clone, origin, worktree_root, issue="807").returncode == EXIT_OK
    assert request(clone, origin, worktree_root, issue="726", ref="main").returncode == EXIT_OK

    assert (worktree_root / "issue-807").is_dir()
    assert (worktree_root / "issue-726").is_dir()
    assert git(worktree_root / "issue-807", "rev-parse", "HEAD").stdout.strip() != \
        git(worktree_root / "issue-726", "rev-parse", "HEAD").stdout.strip()
    # The shared primary checkout is never switched as a substitute for isolation.
    assert git(clone, "rev-parse", "HEAD").stdout.strip() == primary_head
    assert git(clone, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == primary_branch


# --- 14: one branch is never claimed by two active worktrees ----------------


def test_branch_claimed_by_another_worktree_fails_closed(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    git(clone, "branch", "local/work", "origin/feature/topic")
    assert request(
        clone, origin, worktree_root, "807", "local/work", "--attach-branch"
    ).returncode == EXIT_OK

    result = request(clone, origin, worktree_root, "726", "local/work", "--attach-branch")
    assert result.returncode == EXIT_CONFLICT
    parsed = evidence(result)
    assert parsed["status"] == "manual-review"
    assert "already checked out" in str(parsed["reason"])
    assert not (worktree_root / "issue-726").exists()


def test_branch_checked_out_in_the_primary_worktree_is_not_claimed(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    """`main` is checked out in the shared primary checkout; it stays there."""
    result = request(clone, origin, worktree_root, "807", "main", "--attach-branch")
    assert result.returncode == EXIT_CONFLICT
    assert "already checked out" in str(evidence(result)["reason"])
    assert git(clone, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"


def test_remote_only_branch_cannot_be_attached_without_explicit_creation(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    result = request(clone, origin, worktree_root, "807", "feature/topic", "--attach-branch")
    assert result.returncode == EXIT_REF_MISSING
    assert evidence(result)["status"] == "blocked"
    assert "feature/topic" not in git(clone, "branch", "--list").stdout


# --- Branch-creation boundary ------------------------------------------------


def test_branch_creation_is_disabled_by_default(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    result = request(clone, origin, worktree_root, ref="agent/807-new")
    assert result.returncode == EXIT_REF_MISSING
    assert evidence(result)["branch_created"] is False
    assert "agent/807-new" not in git(clone, "branch", "--list").stdout


def test_authorized_branch_creation_is_local_only_and_never_pushed(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    before = remote_state(origin)
    result = request(
        clone, origin, worktree_root, "807", "agent/807-new",
        "--allow-branch-creation", "--base-ref", "main",
    )
    assert result.returncode == EXIT_OK, result.stderr
    parsed = evidence(result)
    assert parsed["branch_created"] is True
    assert parsed["head_state"] == "attached"
    assert parsed["resolved_sha"] == git(clone, "rev-parse", "origin/main").stdout.strip()
    assert "branch-created" in parsed["side_effects_performed"]
    # Nothing was pushed: origin is byte-for-byte unchanged.
    assert remote_state(origin) == before


def test_branch_creation_requires_an_existing_base_ref(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    result = request(
        clone, origin, worktree_root, "807", "agent/807-new",
        "--allow-branch-creation", "--base-ref", "release-2099",
    )
    assert result.returncode == EXIT_BASE
    assert evidence(result)["status"] == "blocked"
    assert "agent/807-new" not in git(clone, "branch", "--list").stdout


def test_branch_creation_does_not_fire_for_an_existing_branch(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    result = request(
        clone, origin, worktree_root, "807", "feature/topic",
        "--allow-branch-creation", "--base-ref", "main",
    )
    # feature/topic exists on origin, so creation is not applicable and the
    # attached request is refused rather than silently recreating the branch.
    assert result.returncode == EXIT_REF_MISSING
    assert evidence(result)["branch_created"] is False


# --- 10: malformed input is rejected before any mutation --------------------


@pytest.mark.parametrize(
    "args",
    [
        ("--issue", "0", "--ref", "feature/topic"),
        ("--issue", "abc", "--ref", "feature/topic"),
        ("--issue", "-5", "--ref", "feature/topic"),
        ("--issue", "807", "--ref", "refs/heads/feature/topic"),
        ("--issue", "807", "--ref", "bad ref name"),
        ("--issue", "807", "--ref", "-dashed"),
        ("--issue", "807", "--ref", "0123456789ab"),
    ],
)
def test_malformed_issue_or_ref_is_rejected_before_mutation(
    clone: Path, origin: Path, worktree_root: Path, args: tuple[str, ...]
) -> None:
    result = prepare(
        clone, *args,
        "--repository", repository_identity(origin),
        "--worktree-root", str(worktree_root),
    )
    assert result.returncode == EXIT_USAGE
    assert evidence(result)["status"] == "blocked"
    assert "fetching origin" not in result.stderr
    assert not worktree_root.exists()


@pytest.mark.parametrize(
    "root_suffix",
    ["relative/worktrees", "/tmp/has spaces/wt", "/tmp/wt/../escape"],
)
def test_malformed_worktree_root_is_rejected_before_mutation(
    clone: Path, origin: Path, root_suffix: str
) -> None:
    result = prepare(
        clone,
        "--issue", "807",
        "--repository", repository_identity(origin),
        "--ref", "feature/topic",
        "--worktree-root", root_suffix,
    )
    assert result.returncode == EXIT_USAGE
    assert evidence(result)["status"] == "blocked"
    assert "fetching origin" not in result.stderr


def test_repository_identity_drift_is_rejected_before_mutation(
    clone: Path, worktree_root: Path
) -> None:
    result = prepare(
        clone,
        "--issue", "807",
        "--repository", "SomeoneElse/other-repo",
        "--ref", "feature/topic",
        "--worktree-root", str(worktree_root),
    )
    assert result.returncode == EXIT_CONFLICT
    parsed = evidence(result)
    assert parsed["status"] == "manual-review"
    assert "identity drift" in str(parsed["reason"])
    assert "fetching origin" not in result.stderr
    assert not worktree_root.exists()


def test_base_ref_without_creation_authorization_is_rejected(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    result = request(clone, origin, worktree_root, "807", "feature/topic", "--base-ref", "main")
    assert result.returncode == EXIT_USAGE
    assert "only valid with --allow-branch-creation" in str(evidence(result)["reason"])


@pytest.mark.parametrize(
    "args",
    [(), ("--issue", "807"), ("--unknown-flag",), ("--issue",)],
)
def test_incomplete_invocations_are_usage_errors(
    clone: Path, args: tuple[str, ...]
) -> None:
    result = prepare(clone, *args)
    assert result.returncode == EXIT_USAGE
    assert evidence(result)["status"] == "blocked"


def test_help_exits_zero_without_emitting_evidence(clone: Path) -> None:
    result = prepare(clone, "--help")
    assert result.returncode == EXIT_OK
    assert result.stdout == ""
    assert "Usage: scripts/prepare-issue-worktree.sh" in result.stderr


# --- 1: repository discovery is explicit and bounded ------------------------


def test_running_outside_a_work_tree_is_explicit_and_never_clones(
    tmp_path: Path, origin: Path, worktree_root: Path
) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    result = prepare(
        plain,
        "--issue", "807",
        "--repository", repository_identity(origin),
        "--ref", "feature/topic",
        "--worktree-root", str(worktree_root),
    )
    assert result.returncode == EXIT_USAGE
    assert "never clones or discovers a repository" in str(evidence(result)["reason"])
    assert list(plain.iterdir()) == [], "no clone or scratch state may be created"


def test_missing_origin_remote_is_explicit(tmp_path: Path, worktree_root: Path) -> None:
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main", str(lonely)],
        check=True, capture_output=True, env=_env(tmp_path),
    )
    commit(lonely, "solo.txt", "solo commit")
    result = prepare(
        lonely,
        "--issue", "807",
        "--repository", "owner/lonely",
        "--ref", "main",
        "--worktree-root", str(worktree_root),
    )
    assert result.returncode == EXIT_USAGE
    assert "remote 'origin' is not configured" in str(evidence(result)["reason"])


def test_restricted_refspec_is_not_reported_as_a_missing_ref(
    origin: Path, tmp_path: Path, worktree_root: Path
) -> None:
    single = tmp_path / "single"
    subprocess.run(
        ["git", "clone", "--quiet", "--single-branch", "--branch", "main",
         f"file://{origin}", str(single)],
        check=True, capture_output=True, env=_env(tmp_path),
    )
    result = request(single, origin, worktree_root)
    assert result.returncode == EXIT_REF_MISSING
    parsed = evidence(result)
    assert "remote-tracking refs are incomplete" in str(parsed["reason"])
    assert "never inferred" not in str(parsed["reason"])


# --- 11: symlink escape and path collision ----------------------------------


def test_symlinked_worktree_root_is_rejected(
    clone: Path, origin: Path, tmp_path: Path
) -> None:
    real_root = tmp_path / "real-worktrees"
    real_root.mkdir()
    linked_root = tmp_path / "linked-worktrees"
    linked_root.symlink_to(real_root, target_is_directory=True)

    result = request(clone, origin, linked_root)
    assert result.returncode == EXIT_CONFLICT
    assert evidence(result)["status"] == "manual-review"
    assert list(real_root.iterdir()) == []


def test_symlinked_target_path_is_rejected(
    clone: Path, origin: Path, worktree_root: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    worktree_root.mkdir()
    (worktree_root / "issue-807").symlink_to(elsewhere, target_is_directory=True)

    result = request(clone, origin, worktree_root)
    assert result.returncode == EXIT_CONFLICT
    assert "symlink" in str(evidence(result)["reason"])
    assert list(elsewhere.iterdir()) == []


def test_occupied_target_path_is_rejected(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    occupied = worktree_root / "issue-807"
    occupied.mkdir(parents=True)
    (occupied / "someone-elses-file.txt").write_text("keep me\n", encoding="utf-8")

    result = request(clone, origin, worktree_root)
    assert result.returncode == EXIT_CONFLICT
    assert "not a registered worktree" in str(evidence(result)["reason"])
    assert (occupied / "someone-elses-file.txt").read_text(encoding="utf-8") == "keep me\n"


def test_target_path_containing_the_primary_checkout_is_rejected(
    clone: Path, origin: Path, tmp_path: Path
) -> None:
    """A root whose issue-<n> path *is* the primary checkout must fail closed."""
    root = tmp_path / "roots"
    root.mkdir()
    primary = root / "issue-807"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(primary)],
        check=True, capture_output=True, env=_env(tmp_path),
    )
    result = request(primary, origin, root)
    assert result.returncode == EXIT_CONFLICT
    assert "primary checkout" in str(evidence(result)["reason"])


# --- 17: locks, stale metadata, and non-destructive handoff -----------------


def test_locked_worktree_is_never_taken_over(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    assert request(clone, origin, worktree_root).returncode == EXIT_OK
    git(clone, "worktree", "lock", "--reason", "workflow-scheduler lease",
        str(worktree_root / "issue-807"))

    result = request(clone, origin, worktree_root)
    assert result.returncode == EXIT_CONFLICT
    parsed = evidence(result)
    assert parsed["status"] == "manual-review"
    assert "never taken over" in str(parsed["reason"])
    # The lease is still held: no unlock, no takeover, no removal.
    assert "locked" in git(clone, "worktree", "list", "--porcelain").stdout
    assert (worktree_root / "issue-807").is_dir()


def test_stale_worktree_metadata_hands_off_without_pruning(
    clone: Path, origin: Path, worktree_root: Path, tmp_path: Path
) -> None:
    assert request(clone, origin, worktree_root).returncode == EXIT_OK
    # Simulate an externally removed worktree directory.
    subprocess.run(["rm", "-rf", str(worktree_root / "issue-807")], check=True)

    result = request(clone, origin, worktree_root)
    assert result.returncode == EXIT_CONFLICT
    parsed = evidence(result)
    assert parsed["status"] == "manual-review"
    assert "Workflow Scheduler cleanup" in str(parsed["reason"])
    # Metadata is left intact for the owning cleanup lifecycle.
    assert str(worktree_root / "issue-807") in worktree_paths(clone)


def test_no_destructive_git_operations_are_reachable() -> None:
    """17: the command contains no force, reset, clean, prune, or delete path."""
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        r"git\s+push",
        r"git\s+commit",
        r"git\s+reset",
        r"git\s+clean",
        r"git\s+stash",
        r"git\s+rebase",
        r"git\s+worktree\s+(remove|prune|unlock|move)",
        r"git\s+branch\s+-[dDmM]",
        r"git\s+tag\s+-[dD]",
        r"--force",
        r"\bgh\b",
        r"\bcurl\b",
        r"rm\s+-rf",
    ]
    for pattern in forbidden:
        assert not re.search(pattern, text), f"forbidden operation reachable: {pattern}"


# --- 18: no repository, GitHub, Cloud, or external write --------------------


def test_successful_preparation_performs_no_external_write(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    before = remote_state(origin)
    primary_head = git(clone, "rev-parse", "HEAD").stdout.strip()
    commits_before = git(clone, "rev-list", "--count", "HEAD").stdout.strip()

    result = request(clone, origin, worktree_root)
    assert result.returncode == EXIT_OK, result.stderr

    assert remote_state(origin) == before, "origin must be untouched"
    assert git(clone, "rev-parse", "HEAD").stdout.strip() == primary_head
    assert git(clone, "rev-list", "--count", "HEAD").stdout.strip() == commits_before
    assert git(clone, "status", "--porcelain").stdout == ""
    # The only recorded side effects are local worktree preparation.
    assert set(evidence(result)["side_effects_performed"]) <= {
        "worktree-root-created", "worktree-created", "branch-created",
        "identity-marker-written",
    }


# --- 15/16: fetch failure classification and retry boundary -----------------


def test_fetch_failure_is_unavailable_not_a_missing_ref(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    git(clone, "remote", "set-url", "origin", str(clone.parent / "missing-origin.git"))
    result = request(clone, origin, worktree_root, repository="missing-origin-owner/x")
    # Identity is checked first, so use the derived identity for this clone.
    assert result.returncode == EXIT_CONFLICT

    identity = f"{clone.parent.name}/missing-origin"
    result = request(clone, origin, worktree_root, repository=identity)
    assert result.returncode == EXIT_FETCH
    parsed = evidence(result)
    assert parsed["status"] == "unavailable"
    assert parsed["remote_fetch_performed"] is False
    assert "not a missing ref" in str(parsed["reason"])
    # Bounded: the injected "0 0" schedule means one attempt plus two retries.
    assert result.stderr.count("retrying in") == 2
    assert "fetch failed after 3 attempt(s)" in result.stderr


def test_local_failures_are_never_retried(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    assert request(clone, origin, worktree_root).returncode == EXIT_OK
    (worktree_root / "issue-807" / "topic.txt").write_text("dirty\n", encoding="utf-8")

    result = request(clone, origin, worktree_root)
    assert result.returncode == EXIT_DIRTY
    assert "retrying in" not in result.stderr
    # The dirty gate runs before the network operation.
    assert "fetching origin" not in result.stderr


def test_missing_ref_performs_exactly_one_fetch(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    result = request(clone, origin, worktree_root, ref="agent/absent")
    assert result.returncode == EXIT_REF_MISSING
    assert result.stderr.count("fetching origin") == 1
    assert "retrying in" not in result.stderr


# --- 19: deterministic, bounded output --------------------------------------


def test_repeated_identical_requests_produce_identical_evidence(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    assert request(clone, origin, worktree_root).returncode == EXIT_OK
    first = request(clone, origin, worktree_root)
    second = request(clone, origin, worktree_root)
    assert first.stdout == second.stdout
    assert evidence(first)["status"] == "already-prepared"


def test_failure_evidence_is_deterministic_and_machine_readable(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    first = request(clone, origin, worktree_root, ref="agent/absent")
    second = request(clone, origin, worktree_root, ref="agent/absent")
    assert first.stdout == second.stdout
    assert evidence(first)["status"] == "blocked"


def test_reason_text_is_bounded_and_free_of_control_characters(
    clone: Path, origin: Path, tmp_path: Path
) -> None:
    deep_root = tmp_path / ("nested/" * 30).rstrip("/")
    result = request(clone, origin, deep_root, ref="agent/absent")
    parsed = evidence(result)
    reason = str(parsed["reason"])
    assert 0 < len(reason) <= MAX_REASON_CHARS
    assert not any(ord(ch) < 32 for ch in reason)


def test_human_summary_and_evidence_use_separate_streams(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    result = request(clone, origin, worktree_root)
    assert result.returncode == EXIT_OK, result.stderr
    json.loads(result.stdout)  # stdout is pure evidence
    assert "prepare-issue-worktree:" not in result.stdout
    assert "STATUS=prepared" in result.stderr
    assert "reason:" in result.stderr


# --- 20: authority never granted --------------------------------------------


def test_every_outcome_reports_false_authority(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    outcomes = {
        "prepared": request(clone, origin, worktree_root),
        "already-prepared": request(clone, origin, worktree_root),
        "blocked": request(clone, origin, worktree_root, ref="agent/absent"),
        "manual-review": request(clone, origin, worktree_root, ref="main"),
    }
    for expected_status, result in outcomes.items():
        parsed = evidence(result)  # asserts all four authority fields are false
        assert parsed["status"] == expected_status


def test_evidence_contract_documents_non_authorization(
    clone: Path, origin: Path, worktree_root: Path
) -> None:
    result = request(clone, origin, worktree_root)
    assert result.returncode == EXIT_OK, result.stderr
    assert "no implementation, execution, or GitHub authority is granted" in str(
        evidence(result)["reason"]
    )


def test_bounded_retry_reuses_the_canonical_repository_state_contract() -> None:
    """No second retry framework: same variable and default schedule as
    scripts/verify-repo-state.sh, per scripts/verify-repo-state-contract.md."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "VERIFY_REPO_STATE_RETRY_DELAYS" in text
    assert 'DEFAULT_RETRY_DELAYS="2 4"' in text
