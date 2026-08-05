"""Focused tests for scripts/agent-os-environment-health.py.

Every test runs against an isolated temporary Git repository. No live
GitHub network access is used and no external tool beyond `git` is
required to be genuinely installed -- missing/available tooling is
simulated by controlling `PATH`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent-os-environment-health.py"

spec = importlib.util.spec_from_file_location("agent_os_environment_health", SCRIPT)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)  # type: ignore[union-attr]


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
        }
    )
    env.pop("GITHUB_TOKEN", None)
    env.pop("GH_TOKEN", None)
    env.update(extra)
    return env


def _init_repo(path: Path, origin_url: str | None, env: dict[str, str]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, env=env, check=True)
    (path / "README.md").write_text("agent os\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, env=env, check=True)
    if origin_url:
        subprocess.run(["git", "remote", "add", "origin", origin_url], cwd=path, env=env, check=True)


def run_cli(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo), *args],
        cwd=repo,
        check=False,
        text=True,
        capture_output=True,
        env=env if env is not None else _env(repo.parent),
    )


def _write_stub(bin_dir: Path, name: str, body: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / name
    script.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    _init_repo(target, "https://github.com/Blummer92/agent-os.git", _env(tmp_path))
    return target


# --- repository identity -----------------------------------------------------


def test_repository_identity_passes_for_expected_remote(repo: Path) -> None:
    result = run_cli(repo, "--check", "repository-identity")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["passed"] is True
    assert payload["detail"]["actual"] == "Blummer92/agent-os"


def test_repository_identity_fails_closed_for_wrong_remote(tmp_path: Path) -> None:
    target = tmp_path / "wrong-repo"
    _init_repo(target, "https://github.com/someone-else/other-repo.git", _env(tmp_path))
    result = run_cli(target, "--check", "repository-identity")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["passed"] is False
    assert payload["detail"]["actual"] == "someone-else/other-repo"


def test_repository_identity_fails_closed_without_origin(tmp_path: Path) -> None:
    target = tmp_path / "no-origin"
    _init_repo(target, None, _env(tmp_path))
    result = run_cli(target, "--check", "repository-identity")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["detail"]["actual"] is None


# --- checkout identity / worktree role --------------------------------------


def test_primary_checkout_named_like_issue_worktree_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "issue-42"
    _init_repo(target, "https://github.com/Blummer92/agent-os.git", _env(tmp_path))
    result = run_cli(target)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checkout = next(c for c in payload["checks"] if c["name"] == "checkout-identity")
    assert checkout["passed"] is False
    assert checkout["detail"]["primary_checkout_not_reused_as_issue_worktree"] is False


def test_linked_issue_worktree_passes_checkout_identity(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    env = _env(tmp_path)
    _init_repo(primary, "https://github.com/Blummer92/agent-os.git", env)
    subprocess.run(["git", "branch", "issue-branch"], cwd=primary, env=env, check=True)
    worktree = tmp_path / "worktrees" / "issue-42"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", str(worktree), "issue-branch"],
        cwd=primary,
        env=env,
        check=True,
    )
    result = run_cli(worktree)
    payload = json.loads(result.stdout)
    checkout = next(c for c in payload["checks"] if c["name"] == "checkout-identity")
    assert checkout["passed"] is True
    assert checkout["detail"]["worktree_role"] == "issue-worktree"


def test_ordinary_primary_checkout_passes_checkout_identity(repo: Path) -> None:
    result = run_cli(repo)
    payload = json.loads(result.stdout)
    checkout = next(c for c in payload["checks"] if c["name"] == "checkout-identity")
    assert checkout["passed"] is True
    assert checkout["detail"]["worktree_role"] == "primary"


# --- tooling ------------------------------------------------------------


def test_tooling_check_fails_closed_when_gh_missing(repo: Path) -> None:
    env = _env(repo.parent)
    result = run_cli(repo, env=env)
    payload = json.loads(result.stdout)
    tooling = next(c for c in payload["checks"] if c["name"] == "tooling")
    assert tooling["passed"] is False
    assert tooling["detail"]["gh"]["available"] is False
    assert payload["status"] == "fail"


def test_tooling_check_passes_when_all_required_tools_present(repo: Path, tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    _write_stub(fake_bin, "gh", 'echo "gh version 2.99.0 (fake)"')
    env = _env(repo.parent, PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    result = run_cli(repo, env=env)
    payload = json.loads(result.stdout)
    tooling = next(c for c in payload["checks"] if c["name"] == "tooling")
    assert tooling["passed"] is True
    assert tooling["detail"]["gh"]["available"] is True


# --- disk space ------------------------------------------------------------


def test_disk_space_fails_closed_below_minimum(repo: Path) -> None:
    result = run_cli(repo, "--min-free-mb", "999999999")
    payload = json.loads(result.stdout)
    disk = next(c for c in payload["checks"] if c["name"] == "disk-space")
    assert disk["passed"] is False
    assert payload["status"] == "fail"


def test_min_free_mb_must_be_positive(repo: Path) -> None:
    result = run_cli(repo, "--min-free-mb", "0")
    assert result.returncode == 2


# --- required validation commands -------------------------------------------


def test_validation_commands_check_fails_closed_when_missing(tmp_path: Path) -> None:
    target = tmp_path / "bare-repo"
    _init_repo(target, "https://github.com/Blummer92/agent-os.git", _env(tmp_path))
    result = run_cli(target)
    payload = json.loads(result.stdout)
    commands = next(c for c in payload["checks"] if c["name"] == "validation-commands")
    assert commands["passed"] is False
    assert commands["detail"]["scripts/validate-all.sh"] is False


def test_validation_commands_check_passes_against_real_repository() -> None:
    result = run_cli(ROOT)
    payload = json.loads(result.stdout)
    commands = next(c for c in payload["checks"] if c["name"] == "validation-commands")
    assert commands["passed"] is True
    assert all(commands["detail"].values())


# --- GitHub authentication capability, without revealing token contents ----


def test_github_auth_capability_reports_env_source_without_leaking_token(repo: Path) -> None:
    fake_token = "ghp_totallyfaketokenvalue1234567890"
    env = _env(repo.parent, GITHUB_TOKEN=fake_token)
    result = run_cli(repo, env=env)
    payload = json.loads(result.stdout)
    auth = next(c for c in payload["checks"] if c["name"] == "github-auth-capability")
    assert auth["passed"] is True
    assert auth["detail"]["source"] == "env"
    assert fake_token not in result.stdout
    assert fake_token not in result.stderr


def test_github_auth_capability_fails_closed_with_no_token_and_no_gh(repo: Path) -> None:
    env = _env(repo.parent)
    result = run_cli(repo, env=env)
    payload = json.loads(result.stdout)
    auth = next(c for c in payload["checks"] if c["name"] == "github-auth-capability")
    assert auth["passed"] is False
    assert auth["detail"]["source"] == "none"


def test_github_auth_capability_uses_gh_cli_status_when_no_token(repo: Path, tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin-gh"
    _write_stub(fake_bin, "gh", 'if [ "$1" = "auth" ]; then exit 0; fi\necho "gh version 2.99.0 (fake)"')
    env = _env(repo.parent, PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    result = run_cli(repo, env=env)
    payload = json.loads(result.stdout)
    auth = next(c for c in payload["checks"] if c["name"] == "github-auth-capability")
    assert auth["passed"] is True
    assert auth["detail"]["source"] == "gh-cli"


# --- authority fields always false ------------------------------------------


def test_all_authority_fields_are_false(repo: Path) -> None:
    result = run_cli(repo)
    payload = json.loads(result.stdout)
    assert payload["authority"], "authority block must be present"
    assert all(value is False for value in payload["authority"].values())


# --- credential redaction (white-box) ---------------------------------------


def test_redact_flags_and_masks_prohibited_credential_patterns() -> None:
    tainted = {"nested": ["fine", "ghp_ABCDEFGHIJ0123456789KLMN"]}
    redacted, found = health._redact(tainted)
    assert found is True
    assert redacted["nested"][1] == "[REDACTED]"
    assert redacted["nested"][0] == "fine"


def test_redact_leaves_ordinary_evidence_untouched() -> None:
    clean = {"branch": "main", "count": 3, "nested": {"ok": True}}
    redacted, found = health._redact(clean)
    assert found is False
    assert redacted == clean


def test_build_evidence_fails_closed_when_a_check_emits_credential_material(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _tainted_check(_repo_root: Path) -> dict:
        return {
            "name": "repository-identity",
            "passed": True,
            "detail": {"actual": "github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
        }

    monkeypatch.setattr(health, "check_repository_identity", _tainted_check)
    evidence = health.build_evidence(repo, "local-only", health.DEFAULT_MIN_FREE_MB)
    assert evidence["status"] == "fail"
    assert "prohibited-credential-material-detected" in evidence["failures"]
    dumped = json.dumps(evidence)
    assert "github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" not in dumped


# --- usage / malformed state --------------------------------------------


def test_rejects_non_git_repo_root(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    result = run_cli(not_a_repo)
    assert result.returncode == 2


def test_rejects_unsupported_network_mode(repo: Path) -> None:
    result = run_cli(repo, "--network-mode", "bogus-mode")
    assert result.returncode == 2
