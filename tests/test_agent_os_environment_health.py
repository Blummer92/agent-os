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
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

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


def _bin_without_gh(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin-without-gh"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for tool in ("git", "pip"):
        resolved = shutil.which(tool)
        assert resolved is not None, f"{tool} is required to run this test"
        link = bin_dir / tool
        if not link.exists():
            link.symlink_to(resolved)
    assert shutil.which("gh", path=str(bin_dir)) is None
    return bin_dir


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    _init_repo(target, "https://github.com/Blummer92/agent-os.git", _env(tmp_path))
    return target


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
    assert json.loads(result.stdout)["detail"]["actual"] is None


def test_primary_checkout_named_like_issue_worktree_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "issue-42"
    _init_repo(target, "https://github.com/Blummer92/agent-os.git", _env(tmp_path))
    payload = json.loads(run_cli(target).stdout)
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
    payload = json.loads(run_cli(worktree).stdout)
    checkout = next(c for c in payload["checks"] if c["name"] == "checkout-identity")
    assert checkout["passed"] is True
    assert checkout["detail"]["worktree_role"] == "issue-worktree"


def test_ordinary_primary_checkout_passes_checkout_identity(repo: Path) -> None:
    payload = json.loads(run_cli(repo).stdout)
    checkout = next(c for c in payload["checks"] if c["name"] == "checkout-identity")
    assert checkout["passed"] is True
    assert checkout["detail"]["worktree_role"] == "primary"


def test_tooling_check_fails_closed_when_gh_missing(repo: Path, tmp_path: Path) -> None:
    env = _env(repo.parent, PATH=str(_bin_without_gh(tmp_path)))
    payload = json.loads(run_cli(repo, env=env).stdout)
    tooling = next(c for c in payload["checks"] if c["name"] == "tooling")
    assert tooling["detail"]["gh"] == {
        "available": False,
        "state": "unavailable",
        "version": None,
    }
    assert payload["status"] == "fail"


def test_tooling_check_passes_when_all_required_tools_present(repo: Path, tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    _write_stub(fake_bin, "gh", 'echo "gh version 2.99.0 (fake)"')
    env = _env(repo.parent, PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    payload = json.loads(run_cli(repo, env=env).stdout)
    gh = next(c for c in payload["checks"] if c["name"] == "tooling")["detail"]["gh"]
    assert gh["available"] is True
    assert gh["state"] == "available"


def test_tool_version_is_bounded(repo: Path, tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin-long-version"
    _write_stub(fake_bin, "gh", 'python -c "print(\"x\" * 500)"')
    env = _env(repo.parent, PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    payload = json.loads(run_cli(repo, env=env).stdout)
    gh = next(c for c in payload["checks"] if c["name"] == "tooling")["detail"]["gh"]
    assert gh["version"] == "x" * health.MAX_TOOL_VERSION_LENGTH


def test_process_execution_is_explicit(repo: Path) -> None:
    payload = json.loads(run_cli(repo).stdout)
    check = next(c for c in payload["checks"] if c["name"] == "process-execution")
    assert check == {
        "name": "process-execution",
        "passed": True,
        "detail": {"state": "available", "mechanism": "python-subprocess"},
    }


def test_process_execution_fails_closed_when_subprocess_is_blocked() -> None:
    with patch.object(health.subprocess, "run", side_effect=OSError("blocked")):
        check = health.check_process_execution()
    assert check["passed"] is False
    assert check["detail"]["state"] == "unavailable"


def test_disk_space_fails_closed_below_minimum(repo: Path) -> None:
    payload = json.loads(run_cli(repo, "--min-free-mb", "999999999").stdout)
    disk = next(c for c in payload["checks"] if c["name"] == "disk-space")
    assert disk["passed"] is False
    assert payload["status"] == "fail"


def test_min_free_mb_must_be_positive(repo: Path) -> None:
    assert run_cli(repo, "--min-free-mb", "0").returncode == 2


def test_validation_commands_check_fails_closed_when_missing(tmp_path: Path) -> None:
    target = tmp_path / "bare-repo"
    _init_repo(target, "https://github.com/Blummer92/agent-os.git", _env(tmp_path))
    payload = json.loads(run_cli(target).stdout)
    commands = next(c for c in payload["checks"] if c["name"] == "validation-commands")
    assert commands["passed"] is False
    assert commands["detail"]["scripts/validate-all.sh"] is False


def test_validation_commands_check_passes_against_real_repository() -> None:
    payload = json.loads(run_cli(ROOT).stdout)
    commands = next(c for c in payload["checks"] if c["name"] == "validation-commands")
    assert commands["passed"] is True
    assert all(commands["detail"].values())


def test_github_auth_capability_reports_env_source_without_leaking_token(repo: Path) -> None:
    token_value = "ghp_totallyfaketokenvalue1234567890"  # noqa: S105
    result = run_cli(repo, env=_env(repo.parent, GITHUB_TOKEN=token_value))
    payload = json.loads(result.stdout)
    auth = next(c for c in payload["checks"] if c["name"] == "github-auth-capability")
    assert auth["detail"] == {
        "capable": True,
        "state": "authenticated",
        "source": "env",
    }
    assert token_value not in result.stdout
    assert token_value not in result.stderr


def test_github_auth_capability_fails_closed_with_no_token_and_no_gh(
    repo: Path, tmp_path: Path
) -> None:
    env = _env(repo.parent, PATH=str(_bin_without_gh(tmp_path)))
    payload = json.loads(run_cli(repo, env=env).stdout)
    auth = next(c for c in payload["checks"] if c["name"] == "github-auth-capability")
    assert auth["detail"] == {
        "capable": False,
        "state": "not-applicable",
        "source": "none",
    }


def test_github_auth_capability_uses_gh_cli_status_when_no_token(repo: Path, tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin-gh"
    _write_stub(fake_bin, "gh", 'if [ "$1" = "auth" ]; then exit 0; fi\necho "gh version 2.99.0 (fake)"')
    env = _env(repo.parent, PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    payload = json.loads(run_cli(repo, env=env).stdout)
    auth = next(c for c in payload["checks"] if c["name"] == "github-auth-capability")
    assert auth["detail"] == {
        "capable": True,
        "state": "authenticated",
        "source": "gh-cli",
    }


def test_github_auth_capability_reports_unauthenticated(repo: Path, tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin-gh-unauthenticated"
    _write_stub(fake_bin, "gh", 'if [ "$1" = "auth" ]; then exit 1; fi\necho "gh version 2.99.0 (fake)"')
    env = _env(repo.parent, PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    payload = json.loads(run_cli(repo, env=env).stdout)
    auth = next(c for c in payload["checks"] if c["name"] == "github-auth-capability")
    assert auth["detail"] == {
        "capable": False,
        "state": "unauthenticated",
        "source": "gh-cli",
    }


def test_github_auth_capability_reports_unknown_on_timeout() -> None:
    with patch.object(health.shutil, "which", return_value="/fake/gh"):
        with patch.object(
            health.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["gh", "auth", "status"], 5),
        ):
            auth = health.check_github_auth_capability()
    assert auth["detail"] == {
        "capable": False,
        "state": "unknown",
        "source": "gh-cli",
    }


def test_runtime_identity_and_timestamp_are_explicit(repo: Path) -> None:
    payload = json.loads(run_cli(repo, "--execution-surface-id", "codespace:test").stdout)
    assert payload["execution_surface_id"] == "codespace:test"
    assert payload["observed_at"].endswith("Z")
    assert "T" in payload["observed_at"]
    assert payload["environment_health_evidence_id"].startswith("sha256:")


def test_supplied_observation_time_is_canonicalized(repo: Path) -> None:
    evidence = health.build_evidence(
        repo,
        "local-only",
        health.DEFAULT_MIN_FREE_MB,
        observed_at="2026-08-09T08:00:00-04:00",
    )
    assert evidence["observed_at"] == "2026-08-09T12:00:00Z"


def test_invalid_observation_time_is_rejected(repo: Path) -> None:
    with pytest.raises(ValueError, match="observed_at"):
        health.build_evidence(
            repo,
            "local-only",
            health.DEFAULT_MIN_FREE_MB,
            observed_at="not-a-timestamp",
        )


def test_evidence_identity_is_stable_across_observation_time(repo: Path) -> None:
    first = health.build_evidence(
        repo,
        "local-only",
        health.DEFAULT_MIN_FREE_MB,
        execution_surface_id="surface-a",
        observed_at="2026-08-09T12:00:00Z",
    )
    second = health.build_evidence(
        repo,
        "local-only",
        health.DEFAULT_MIN_FREE_MB,
        execution_surface_id="surface-a",
        observed_at="2026-08-09T12:01:00Z",
    )
    assert first["environment_health_evidence_id"] == second["environment_health_evidence_id"]


def test_evidence_identity_changes_with_surface(repo: Path) -> None:
    first = health.build_evidence(
        repo,
        "local-only",
        health.DEFAULT_MIN_FREE_MB,
        execution_surface_id="surface-a",
        observed_at="2026-08-09T12:00:00Z",
    )
    second = health.build_evidence(
        repo,
        "local-only",
        health.DEFAULT_MIN_FREE_MB,
        execution_surface_id="surface-b",
        observed_at="2026-08-09T12:00:00Z",
    )
    assert first["environment_health_evidence_id"] != second["environment_health_evidence_id"]
    assert health.evidence_matches_surface(first, "surface-a") is True
    assert health.evidence_matches_surface(first, "surface-b") is False


def test_invalid_surface_id_is_usage_error(repo: Path) -> None:
    result = run_cli(repo, "--execution-surface-id", "bad surface")
    assert result.returncode == 2
    assert "execution surface id" in result.stdout


def test_all_authority_fields_are_false(repo: Path) -> None:
    payload = json.loads(run_cli(repo).stdout)
    assert payload["authority"], "authority block must be present"
    assert all(value is False for value in payload["authority"].values())


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


CREDENTIAL_BEARING_EXPECTED_REMOTE = (
    "https://example-user:example-secret@github.com/Blummer92/agent-os.git"
)
CREDENTIAL_BEARING_WRONG_REMOTE = (
    "https://example-user:example-secret@github.com/Someone-Else/other-repo.git"
)


def test_check_repository_identity_cli_sanitizes_credential_bearing_expected_remote(
    tmp_path: Path,
) -> None:
    target = tmp_path / "credential-expected-repo"
    _init_repo(target, CREDENTIAL_BEARING_EXPECTED_REMOTE, _env(tmp_path))
    result = run_cli(target, "--check", "repository-identity")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["detail"]["actual"] == "Blummer92/agent-os"
    for secret in ("example-user", "example-secret", CREDENTIAL_BEARING_EXPECTED_REMOTE):
        assert secret not in result.stdout
        assert secret not in result.stderr


def test_check_repository_identity_cli_fails_closed_for_credential_bearing_wrong_remote(
    tmp_path: Path,
) -> None:
    target = tmp_path / "credential-wrong-repo"
    _init_repo(target, CREDENTIAL_BEARING_WRONG_REMOTE, _env(tmp_path))
    result = run_cli(target, "--check", "repository-identity")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["passed"] is False
    for secret in ("example-user", "example-secret", CREDENTIAL_BEARING_WRONG_REMOTE):
        assert secret not in result.stdout
        assert secret not in result.stderr


def test_redact_masks_https_userinfo_credentials() -> None:
    tainted = {"note": "see https://example-user:example-secret@example.com/x/y"}
    redacted, found = health._redact(tainted)
    assert found is True
    assert redacted["note"] == "[REDACTED]"


def test_check_repository_identity_cli_fails_closed_for_malformed_port(tmp_path: Path) -> None:
    remote = "https://github.com:not-a-port/Blummer92/agent-os.git"
    target = tmp_path / "malformed-port-repo"
    _init_repo(target, remote, _env(tmp_path))
    result = run_cli(target, "--check", "repository-identity")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    payload = json.loads(result.stdout)
    assert payload["detail"]["actual"] is None
    assert remote not in result.stdout
    assert remote not in result.stderr


def test_rejects_non_git_repo_root(tmp_path: Path) -> None:
    target = tmp_path / "not-a-repo"
    target.mkdir()
    assert run_cli(target).returncode == 2


def test_rejects_unsupported_network_mode(repo: Path) -> None:
    assert run_cli(repo, "--network-mode", "bogus-mode").returncode == 2
