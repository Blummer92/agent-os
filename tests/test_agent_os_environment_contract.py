"""Contract tests for the `agent-os-codespaces-v1` profile (#891).

Checks the shape and safety boundaries of the allowlisted files rather than
re-deriving worktree, scheduler, or repository-state behavior, which stays
owned by scripts/prepare-issue-worktree.sh and scripts/verify-repo-state.sh.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEVCONTAINER_DIR = ROOT / ".devcontainer"
HEALTH_SCRIPT = ROOT / "scripts" / "agent-os-environment-health.py"
RUNBOOK = ROOT / "docs" / "AGENT_OS_CODESPACES_RUNBOOK.md"


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


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=check, text=True, capture_output=True, env=_env(repo.parent)
    )


# --- devcontainer.json --------------------------------------------------


def test_devcontainer_json_is_valid_and_bounded_to_two_cores() -> None:
    payload = json.loads((DEVCONTAINER_DIR / "devcontainer.json").read_text(encoding="utf-8"))
    assert payload["hostRequirements"]["cpus"] == 2
    assert "image" in payload
    assert payload["postCreateCommand"] == "bash .devcontainer/post-create.sh"
    assert payload["remoteEnv"]["AGENT_OS_NETWORK_MODE"] == "local-only"


def test_devcontainer_json_contains_no_credentials_or_secrets() -> None:
    text = (DEVCONTAINER_DIR / "devcontainer.json").read_text(encoding="utf-8").lower()
    for forbidden in ("secret", "password", "token=", "credential"):
        assert forbidden not in text


def test_no_dockerfile_was_created() -> None:
    """The base devcontainer image satisfies the bounded runtime contract."""
    assert not (DEVCONTAINER_DIR / "Dockerfile").exists()


def test_no_conditional_environment_report_script_was_created() -> None:
    """Health output stayed focused and bounded in one command."""
    assert not (ROOT / "scripts" / "agent-os-environment-report.py").exists()


# --- post-create.sh -------------------------------------------------------


def test_post_create_script_is_executable_and_fail_closed() -> None:
    script = DEVCONTAINER_DIR / "post-create.sh"
    assert script.exists()
    assert os.access(script, os.X_OK)
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in text


def test_post_create_script_never_pushes_or_writes_credentials() -> None:
    text = (DEVCONTAINER_DIR / "post-create.sh").read_text(encoding="utf-8")
    for forbidden in ("git push", "gh auth login", "GITHUB_TOKEN=", "pip install --upgrade pip"):
        assert forbidden not in text


def test_post_create_script_calls_environment_health_check() -> None:
    text = (DEVCONTAINER_DIR / "post-create.sh").read_text(encoding="utf-8")
    assert "scripts/agent-os-environment-health.py" in text
    assert "requirements-dev.txt" in text


# --- health script packaging ----------------------------------------------


def test_environment_health_script_compiles() -> None:
    compile(
        HEALTH_SCRIPT.read_text(encoding="utf-8"),
        str(HEALTH_SCRIPT),
        "exec",
    )


def test_environment_health_script_does_not_reimplement_worktree_management() -> None:
    text = HEALTH_SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("git worktree add", "git clone", "git push"):
        assert forbidden not in text


# --- runbook documentation -------------------------------------------------


def test_runbook_exists_and_is_under_the_line_limit() -> None:
    assert RUNBOOK.exists()
    # Mirrors 07_Agent_Tests/validate-repo-structure.sh's `wc -l` line count.
    assert RUNBOOK.read_text(encoding="utf-8").count("\n") < 100


def test_runbook_documents_required_topics() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    required_phrases = (
        "2-core",
        "local-only",
        "github-connected",
        "#807",
        "#858",
        "idle timeout",
        "rollback",
        "token",
        "process",
        "stop/start",
        "validate-all.sh",
        "Non-authorization",
    )
    for phrase in required_phrases:
        assert phrase in text, f"runbook missing required topic: {phrase}"


# --- registry / changelog bookkeeping --------------------------------------


def test_module_version_map_registers_the_profile() -> None:
    text = (ROOT / "04_Registry" / "module-version-map.md").read_text(encoding="utf-8")
    assert "Agent OS Codespaces Profile" in text
    # Mirrors 07_Agent_Tests/validate-repo-structure.sh's `wc -l` line count.
    assert text.count("\n") < 100


def test_changelog_references_the_issue() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "#891" in text
    assert "agent-os-codespaces-v1" in text


# --- reuse proof: existing #807/repo-state contracts stay authoritative ----


def test_prepare_issue_worktree_script_remains_callable_and_unduplicated(tmp_path: Path) -> None:
    """Exercises the existing, unmodified script -- proves compatibility
    without re-deriving its worktree logic (requirement 8)."""
    bare = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--quiet", "--bare", "--initial-branch=main", str(bare)],
        check=True, capture_output=True, env=_env(tmp_path),
    )
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "--quiet", str(bare), str(seed)], check=True, capture_output=True, env=_env(tmp_path))
    (seed / "base.txt").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "base.txt")
    _git(seed, "commit", "-q", "-m", "base commit")
    _git(seed, "push", "-q", "--set-upstream", "origin", "main")

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "--quiet", str(bare), str(clone)], check=True, capture_output=True, env=_env(tmp_path))

    worktree_root = tmp_path / "worktrees"
    repository = f"{bare.parent.name}/{bare.name[: -len('.git')]}"
    result = subprocess.run(
        [
            "bash", str(ROOT / "scripts" / "prepare-issue-worktree.sh"),
            "--issue", "891",
            "--repository", repository,
            "--ref", "main",
            "--worktree-root", str(worktree_root),
        ],
        cwd=clone,
        check=False,
        text=True,
        capture_output=True,
        env=_env(tmp_path),
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["status"] == "prepared"
    assert payload["merge_authorized"] is False


def test_verify_repo_state_script_remains_callable() -> None:
    """Existing repository-state verifier still runs against this checkout."""
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "verify-repo-state.sh"), "--help"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode in (0, 2)


# --- #972 additive runtime evidence ----------------------------------------


def _load_health_contract() -> dict:
    namespace = __import__("runpy").run_path(str(HEALTH_SCRIPT))
    return namespace["build_evidence"].__globals__


def _stub_health_checks(health: dict, monkeypatch) -> None:
    monkeypatch.setitem(
        health,
        "check_repository_identity",
        lambda _root: {"name": "repository-identity", "passed": True, "detail": {}},
    )
    monkeypatch.setitem(
        health,
        "check_checkout_identity",
        lambda _root: {"name": "checkout-identity", "passed": True, "detail": {}},
    )
    monkeypatch.setitem(
        health,
        "check_tooling",
        lambda _root: {
            "name": "tooling",
            "passed": True,
            "detail": {
                "git": {"available": True, "state": "available", "version": "git 2"},
                "pip": {"available": True, "state": "available", "version": "pip 25"},
                "gh": {"available": True, "state": "available", "version": "gh 2"},
                "python": {"available": True, "state": "available", "version": "3.11"},
            },
        },
    )
    monkeypatch.setitem(
        health,
        "check_process_execution",
        lambda: {
            "name": "process-execution",
            "passed": True,
            "detail": {"state": "available", "mechanism": "python-subprocess"},
        },
    )
    monkeypatch.setitem(
        health,
        "check_disk_space",
        lambda _root, _minimum: {"name": "disk-space", "passed": True, "detail": {}},
    )
    monkeypatch.setitem(
        health,
        "check_validation_commands",
        lambda _root: {"name": "validation-commands", "passed": True, "detail": {}},
    )
    monkeypatch.setitem(
        health,
        "check_github_auth_capability",
        lambda: {
            "name": "github-auth-capability",
            "passed": True,
            "detail": {"capable": True, "state": "authenticated", "source": "gh-cli"},
        },
    )


def test_972_evidence_id_binds_surface_and_freshness(tmp_path: Path, monkeypatch) -> None:
    health = _load_health_contract()
    _stub_health_checks(health, monkeypatch)
    first = health["build_evidence"](
        tmp_path,
        "local-only",
        500,
        execution_surface_id="codespace:test-a",
        observed_at="2026-08-09T15:00:00Z",
    )
    same = health["build_evidence"](
        tmp_path,
        "local-only",
        500,
        execution_surface_id="codespace:test-a",
        observed_at="2026-08-09T15:00:00Z",
    )
    newer = health["build_evidence"](
        tmp_path,
        "local-only",
        500,
        execution_surface_id="codespace:test-a",
        observed_at="2026-08-09T15:00:01Z",
    )
    other_surface = health["build_evidence"](
        tmp_path,
        "local-only",
        500,
        execution_surface_id="codespace:test-b",
        observed_at="2026-08-09T15:00:00Z",
    )
    assert first["environment_health_evidence_id"] == same["environment_health_evidence_id"]
    assert first["environment_health_evidence_id"] != newer["environment_health_evidence_id"]
    assert first["environment_health_evidence_id"] != other_surface["environment_health_evidence_id"]
    assert health["evidence_matches_surface"](first, "codespace:test-a") is True
    assert health["evidence_matches_surface"](first, "codespace:test-b") is False
    assert all(value is False for value in first["authority"].values())


def test_972_surface_and_timestamp_validation_fail_closed(tmp_path: Path, monkeypatch) -> None:
    health = _load_health_contract()
    monkeypatch.delenv("AGENT_OS_EXECUTION_SURFACE_ID", raising=False)
    monkeypatch.setenv("CODESPACE_NAME", "teacher-dev-42")
    assert health["_execution_surface_id"](tmp_path) == "codespace:teacher-dev-42"
    try:
        health["_execution_surface_id"](tmp_path, "bad surface id")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid surface ID must fail closed")
    assert health["_canonical_observed_at"]("2026-08-09T15:00:00Z") == "2026-08-09T15:00:00Z"
    for invalid in ("2026-08-09 15:00:00", "2026-99-99T99:99:99Z"):
        try:
            health["_canonical_observed_at"](invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid timestamp accepted: {invalid}")


def test_972_tool_states_versions_and_process_execution_are_bounded(monkeypatch) -> None:
    health = _load_health_contract()
    monkeypatch.setattr(health["shutil"], "which", lambda _name: "/fake/tool")
    monkeypatch.setitem(health, "_run", lambda _cmd, cwd=None: (True, "v" * 500))
    tooling = health["check_tooling"](ROOT)
    assert tooling["detail"]["gh"]["state"] == "available"
    assert tooling["detail"]["gh"]["version"] == "v" * health["MAX_TOOL_VERSION_CHARS"]
    process = health["check_process_execution"]()
    assert process["passed"] is True
    assert process["detail"]["state"] == "available"

    monkeypatch.setitem(health, "_run", lambda _cmd, cwd=None: (False, "timeout"))
    tooling = health["check_tooling"](ROOT)
    assert tooling["detail"]["gh"]["state"] == "unknown"
    assert tooling["detail"]["gh"]["available"] is False
    process = health["check_process_execution"]()
    assert process["passed"] is False
    assert process["detail"]["state"] == "unknown"


def test_972_missing_gh_and_auth_probe_fail_closed(monkeypatch) -> None:
    health = _load_health_contract()
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(health["shutil"], "which", lambda _name: None)
    tooling = health["check_tooling"](ROOT)
    assert tooling["detail"]["gh"] == {
        "available": False,
        "state": "unavailable",
        "version": None,
    }
    auth = health["check_github_auth_capability"]()
    assert auth["detail"] == {"capable": False, "state": "unknown", "source": "none"}


def test_972_github_auth_distinguishes_unauthenticated_and_unknown(monkeypatch) -> None:
    health = _load_health_contract()
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(health["shutil"], "which", lambda _name: "/fake/gh")
    monkeypatch.setattr(
        health["subprocess"],
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "not authenticated"),
    )
    auth = health["check_github_auth_capability"]()
    assert auth["detail"] == {
        "capable": False,
        "state": "unauthenticated",
        "source": "gh-cli",
    }

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], health["SUBPROCESS_TIMEOUT_SECONDS"])

    monkeypatch.setattr(health["subprocess"], "run", timeout)
    auth = health["check_github_auth_capability"]()
    assert auth["detail"] == {"capable": False, "state": "unknown", "source": "gh-cli"}


def test_972_contract_bookkeeping_and_boundaries() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    for phrase in (
        "execution_surface_id",
        "observed_at",
        "environment_health_evidence_id",
        "process-execution",
        "Issue #918",
    ):
        assert phrase in runbook
    module_map = (ROOT / "04_Registry" / "module-version-map.md").read_text(encoding="utf-8")
    assert "| Agent OS Codespaces Profile | 0.2.0 |" in module_map
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Agent OS Codespaces Profile from `0.1.0` to `0.2.0` for #972" in changelog
    core = HEALTH_SCRIPT.read_text(encoding="utf-8").lower()
    for forbidden in (
        "google drive",
        "notion api",
        "chrome devtools",
        "connector discovery",
        "provider discovery",
    ):
        assert forbidden not in core
