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

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent-os-environment-health.py"

spec = importlib.util.spec_from_file_location("agent_os_environment_health", SCRIPT)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)  # type: ignore[union-attr]


def _env(home: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update({"HOME": str(home), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "Agent OS Test", "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_NAME": "Agent OS Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"})
    env.pop("GITHUB_TOKEN", None); env.pop("GH_TOKEN", None); env.update(extra); return env


def _init_repo(path: Path, origin_url: str | None, env: dict[str, str]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, env=env, check=True)
    (path / "README.md").write_text("agent os\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, env=env, check=True)
    if origin_url: subprocess.run(["git", "remote", "add", "origin", origin_url], cwd=path, env=env, check=True)


def run_cli(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), "--repo-root", str(repo), *args], cwd=repo, check=False, text=True, capture_output=True, env=env if env is not None else _env(repo.parent))


def _write_stub(bin_dir: Path, name: str, body: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True); script = bin_dir / name
    script.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _bin_without_gh(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin-without-gh"; bin_dir.mkdir(parents=True, exist_ok=True)
    for tool in ("git", "pip"):
        resolved = shutil.which(tool); assert resolved is not None
        link = bin_dir / tool
        if not link.exists(): link.symlink_to(resolved)
    assert shutil.which("gh", path=str(bin_dir)) is None
    return bin_dir


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    target = tmp_path / "repo"; _init_repo(target, "https://github.com/Blummer92/agent-os.git", _env(tmp_path)); return target


def test_repository_identity_passes_for_expected_remote(repo: Path) -> None:
    result = run_cli(repo, "--check", "repository-identity"); assert result.returncode == 0
    assert json.loads(result.stdout)["detail"]["actual"] == "Blummer92/agent-os"


def test_repository_identity_fails_closed_for_wrong_remote(tmp_path: Path) -> None:
    target = tmp_path / "wrong-repo"; _init_repo(target, "https://github.com/someone-else/other-repo.git", _env(tmp_path))
    assert run_cli(target, "--check", "repository-identity").returncode == 1


def test_repository_identity_fails_closed_without_origin(tmp_path: Path) -> None:
    target = tmp_path / "no-origin"; _init_repo(target, None, _env(tmp_path)); result = run_cli(target, "--check", "repository-identity")
    assert result.returncode == 1 and json.loads(result.stdout)["detail"]["actual"] is None


def test_primary_checkout_named_like_issue_worktree_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "issue-42"; _init_repo(target, "https://github.com/Blummer92/agent-os.git", _env(tmp_path)); payload = json.loads(run_cli(target).stdout)
    checkout = next(c for c in payload["checks"] if c["name"] == "checkout-identity"); assert checkout["passed"] is False


def test_ordinary_primary_checkout_passes_checkout_identity(repo: Path) -> None:
    payload = json.loads(run_cli(repo).stdout); checkout = next(c for c in payload["checks"] if c["name"] == "checkout-identity")
    assert checkout["passed"] is True and checkout["detail"]["worktree_role"] == "primary"


def test_tooling_check_fails_closed_when_gh_missing(repo: Path, tmp_path: Path) -> None:
    payload = json.loads(run_cli(repo, env=_env(repo.parent, PATH=str(_bin_without_gh(tmp_path)))).stdout)
    tooling = next(c for c in payload["checks"] if c["name"] == "tooling")
    assert tooling["detail"]["gh"] == {"available": False, "state": "unavailable", "version": None}


def test_tooling_check_passes_when_all_required_tools_present(repo: Path, tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"; _write_stub(fake_bin, "gh", 'echo "gh version 2.99.0 (fake)"')
    payload = json.loads(run_cli(repo, env=_env(repo.parent, PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}")).stdout)
    gh = next(c for c in payload["checks"] if c["name"] == "tooling")["detail"]["gh"]
    assert gh["available"] is True and gh["state"] == "available"


def test_process_execution_is_explicit(repo: Path) -> None:
    payload = json.loads(run_cli(repo).stdout); check = next(c for c in payload["checks"] if c["name"] == "process-execution")
    assert check == {"name": "process-execution", "passed": True, "detail": {"state": "available", "mechanism": "python-subprocess"}}


def test_github_auth_states_are_explicit(repo: Path, tmp_path: Path) -> None:
    payload = json.loads(run_cli(repo, env=_env(repo.parent, PATH=str(_bin_without_gh(tmp_path)))).stdout)
    auth = next(c for c in payload["checks"] if c["name"] == "github-auth-capability")
    assert auth["detail"] == {"capable": False, "state": "not-applicable", "source": "none"}


def test_github_auth_capability_reports_env_source_without_leaking_token(repo: Path) -> None:
    fake_token = "ghp_totallyfaketokenvalue1234567890"; result = run_cli(repo, env=_env(repo.parent, GITHUB_TOKEN=fake_token)); payload = json.loads(result.stdout)
    auth = next(c for c in payload["checks"] if c["name"] == "github-auth-capability")
    assert auth["detail"]["state"] == "authenticated" and fake_token not in result.stdout


def test_runtime_identity_and_timestamp_are_explicit(repo: Path) -> None:
    payload = json.loads(run_cli(repo, "--execution-surface-id", "codespace:test").stdout)
    assert payload["execution_surface_id"] == "codespace:test"
    assert payload["observed_at"].endswith("Z") and "T" in payload["observed_at"]
    assert payload["environment_health_evidence_id"].startswith("sha256:")


def test_evidence_identity_is_stable_across_observation_time(repo: Path) -> None:
    first = health.build_evidence(repo, "local-only", health.DEFAULT_MIN_FREE_MB, execution_surface_id="surface-a", observed_at="2026-08-09T12:00:00Z")
    second = health.build_evidence(repo, "local-only", health.DEFAULT_MIN_FREE_MB, execution_surface_id="surface-a", observed_at="2026-08-09T12:01:00Z")
    assert first["environment_health_evidence_id"] == second["environment_health_evidence_id"]


def test_evidence_identity_changes_with_surface(repo: Path) -> None:
    first = health.build_evidence(repo, "local-only", health.DEFAULT_MIN_FREE_MB, execution_surface_id="surface-a", observed_at="2026-08-09T12:00:00Z")
    second = health.build_evidence(repo, "local-only", health.DEFAULT_MIN_FREE_MB, execution_surface_id="surface-b", observed_at="2026-08-09T12:00:00Z")
    assert first["environment_health_evidence_id"] != second["environment_health_evidence_id"]
    assert health.evidence_matches_surface(first, "surface-a") is True
    assert health.evidence_matches_surface(first, "surface-b") is False


def test_invalid_surface_id_is_usage_error(repo: Path) -> None:
    result = run_cli(repo, "--execution-surface-id", "bad surface")
    assert result.returncode == 2 and "execution surface id" in result.stdout


def test_all_authority_fields_are_false(repo: Path) -> None:
    payload = json.loads(run_cli(repo).stdout); assert payload["authority"] and all(value is False for value in payload["authority"].values())


def test_redact_flags_and_masks_prohibited_credential_patterns() -> None:
    redacted, found = health._redact({"nested": ["fine", "ghp_ABCDEFGHIJ0123456789KLMN"]})
    assert found is True and redacted["nested"][1] == "[REDACTED]"


def test_rejects_non_git_repo_root(tmp_path: Path) -> None:
    target = tmp_path / "not-a-repo"; target.mkdir(); assert run_cli(target).returncode == 2
