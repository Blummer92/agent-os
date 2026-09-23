from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

from scripts.protected_branch_push_guard import (
    GuardInputError,
    GuardInstallError,
    HOOKS_PATH,
    MARKER_NAME,
    PROTECTED_REF,
    evaluate_push,
    install,
    parse_push_updates,
    remove,
)

ZERO = "0" * 40
ONE = "1" * 40
TWO = "2" * 40
COMMAND_TIMEOUT_SECONDS = 20
MAX_CAPTURE_CHARS = 8_192
SOURCE_ROOT = Path(__file__).resolve().parents[1]


def update_line(
    remote_ref: str,
    *,
    local_ref: str = "refs/heads/feature/safe-change",
    local_object: str = ONE,
    remote_object: str = TWO,
) -> str:
    return f"{local_ref} {local_object} {remote_ref} {remote_object}\n"


def bounded(text: str) -> str:
    return text[-MAX_CAPTURE_CHARS:]


def isolated_environment(**overrides: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
            "LANG": "C",
        }
    )
    environment.update(overrides)
    return environment


def run_command(
    repo: Path,
    command: list[str],
    *,
    check: bool = True,
    environment: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=repo,
            check=False,
            text=True,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=COMMAND_TIMEOUT_SECONDS,
            env=environment or isolated_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"command timed out after {COMMAND_TIMEOUT_SECONDS}s: {shlex.join(command)}"
        ) from exc

    bounded_result = subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=bounded(result.stdout),
        stderr=bounded(result.stderr),
    )
    if check and bounded_result.returncode != 0:
        raise AssertionError(
            "command failed: "
            f"{shlex.join(command)}\n"
            f"stdout:\n{bounded_result.stdout}\n"
            f"stderr:\n{bounded_result.stderr}"
        )
    return bounded_result


def git(
    repo: Path,
    *args: str,
    check: bool = True,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return run_command(
        repo,
        ["git", *args],
        check=check,
        environment=environment,
    )


def temporary_repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repository"
    repo.mkdir()
    git(repo, "init")
    hook = repo / HOOKS_PATH / "pre-push"
    hook.parent.mkdir()
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    return repo


def marker_path(repo: Path) -> Path:
    git_dir = Path(git(repo, "rev-parse", "--git-dir").stdout.strip())
    if not git_dir.is_absolute():
        git_dir = repo / git_dir
    return git_dir / MARKER_NAME


def configured_hooks_path(repo: Path) -> str | None:
    result = git(repo, "config", "--local", "--get", "core.hooksPath", check=False)
    return result.stdout.strip() if result.returncode == 0 else None


@dataclass(frozen=True)
class InstalledHookTopology:
    worktree: Path
    bare_remote: Path
    environment: dict[str, str]
    remote_name: str


def commit_file(topology: InstalledHookTopology, relative_path: str, content: str, message: str) -> str:
    path = topology.worktree / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git(topology.worktree, "add", relative_path, environment=topology.environment)
    git(topology.worktree, "commit", "-m", message, environment=topology.environment)
    return git(
        topology.worktree,
        "rev-parse",
        "HEAD",
        environment=topology.environment,
    ).stdout.strip()


def remote_ref(topology: InstalledHookTopology, ref: str) -> str | None:
    result = git(
        topology.bare_remote,
        "rev-parse",
        "--verify",
        "--quiet",
        ref,
        check=False,
        environment=topology.environment,
    )
    if result.returncode == 1:
        return None
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def installed_hook_topology(tmp_path: Path) -> InstalledHookTopology:
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    home.mkdir()
    xdg.mkdir()
    environment = isolated_environment(HOME=str(home), XDG_CONFIG_HOME=str(xdg))

    worktree = tmp_path / "worktree"
    bare_remote = tmp_path / "guarded-remote.git"
    worktree.mkdir()
    bare_remote.mkdir()
    git(worktree, "init", "-b", "main", environment=environment)
    git(bare_remote, "init", "--bare", environment=environment)
    git(worktree, "config", "user.name", "Agent OS Test", environment=environment)
    git(worktree, "config", "user.email", "agent-os-test@example.invalid", environment=environment)

    (worktree / ".githooks").mkdir()
    (worktree / "scripts").mkdir()
    shutil.copy2(SOURCE_ROOT / ".githooks" / "pre-push", worktree / ".githooks" / "pre-push")
    shutil.copy2(
        SOURCE_ROOT / "scripts" / "protected_branch_push_guard.py",
        worktree / "scripts" / "protected_branch_push_guard.py",
    )

    topology = InstalledHookTopology(
        worktree=worktree,
        bare_remote=bare_remote,
        environment=environment,
        remote_name="guarded",
    )
    commit_file(topology, "README.md", "initial\n", "initial commit")
    git(
        worktree,
        "remote",
        "add",
        topology.remote_name,
        str(bare_remote),
        environment=environment,
    )
    git(
        worktree,
        "push",
        topology.remote_name,
        "main",
        environment=environment,
    )

    install_result = run_command(
        worktree,
        [sys.executable, "scripts/protected_branch_push_guard.py", "install"],
        environment=environment,
    )
    assert "Installed Agent OS protected-branch hook" in install_result.stdout
    assert configured_hooks_path(worktree) == HOOKS_PATH
    assert os.access(worktree / HOOKS_PATH / "pre-push", os.X_OK)
    return topology


def test_exact_main_update_is_blocked_with_safe_guidance():
    stderr = StringIO()
    assert evaluate_push(update_line(PROTECTED_REF), environment={}, stderr=stderr) == 1
    message = stderr.getvalue()
    assert "blocked an update to refs/heads/main" in message
    assert "feature branch" in message
    assert "--no-verify is not authorization" in message


def test_main_deletion_and_one_protected_ref_in_multi_ref_push_are_blocked():
    deletion = update_line(
        PROTECTED_REF,
        local_ref="(delete)",
        local_object=ZERO,
    )
    assert evaluate_push(deletion, environment={}, stderr=StringIO()) == 1

    multi_ref = update_line("refs/heads/feature/one") + update_line(PROTECTED_REF)
    assert evaluate_push(multi_ref, environment={}, stderr=StringIO()) == 1


def test_similarly_named_branches_and_tags_are_allowed():
    payload = "".join(
        (
            update_line("refs/heads/main-fix"),
            update_line("refs/heads/feature/main"),
            update_line("refs/tags/main-release", local_ref="refs/tags/main-release"),
        )
    )
    assert evaluate_push(payload, environment={}, stderr=StringIO()) == 0


@pytest.mark.parametrize(
    "payload",
    (
        "",
        "not enough fields\n",
        f"local {ONE} refs/heads/main {TWO}\n",
        f"refs/heads/feature {ONE} main {TWO}\n",
        f"refs/heads/feature not-a-sha refs/heads/main {TWO}\n",
    ),
)
def test_empty_or_malformed_input_fails_closed(payload: str):
    stderr = StringIO()
    assert evaluate_push(payload, environment={}, stderr=stderr) == 1
    assert "blocked" in stderr.getvalue()


def test_parser_preserves_all_standard_fields():
    parsed = parse_push_updates(update_line("refs/heads/feature/example"))
    assert len(parsed) == 1
    assert parsed[0].local_ref == "refs/heads/feature/safe-change"
    assert parsed[0].remote_ref == "refs/heads/feature/example"
    assert parsed[0].local_object == ONE
    assert parsed[0].remote_object == TWO


def test_parser_rejects_invalid_object_length():
    with pytest.raises(GuardInputError):
        parse_push_updates(
            update_line(PROTECTED_REF, local_object="1" * 39)
        )


def test_bypass_requires_flag_and_nonempty_reason():
    payload = update_line(PROTECTED_REF)
    assert evaluate_push(
        payload,
        environment={"AGENT_OS_ALLOW_PROTECTED_PUSH": "1"},
        stderr=StringIO(),
    ) == 1
    assert evaluate_push(
        payload,
        environment={
            "AGENT_OS_ALLOW_PROTECTED_PUSH": "0",
            "AGENT_OS_PROTECTED_PUSH_REASON": "approved recovery",
        },
        stderr=StringIO(),
    ) == 1

    stderr = StringIO()
    assert evaluate_push(
        payload,
        environment={
            "AGENT_OS_ALLOW_PROTECTED_PUSH": "1",
            "AGENT_OS_PROTECTED_PUSH_REASON": "approved recovery",
        },
        stderr=stderr,
    ) == 0
    assert "WARNING" in stderr.getvalue()
    assert "approved recovery" in stderr.getvalue()


def test_install_is_repository_local_idempotent_and_removable(tmp_path: Path):
    repo = temporary_repository(tmp_path)
    hook = repo / HOOKS_PATH / "pre-push"
    assert configured_hooks_path(repo) is None

    assert install(repo) == 0
    assert configured_hooks_path(repo) == HOOKS_PATH
    assert os.access(hook, os.X_OK)
    payload = json.loads(marker_path(repo).read_text(encoding="utf-8"))
    assert payload == {
        "changed_config": True,
        "installed_hooks_path": HOOKS_PATH,
        "previous_hooks_path": None,
    }

    assert install(repo) == 0
    assert configured_hooks_path(repo) == HOOKS_PATH
    assert remove(repo) == 0
    assert configured_hooks_path(repo) is None
    assert not marker_path(repo).exists()


def test_existing_matching_hooks_path_is_preserved_on_remove(tmp_path: Path):
    repo = temporary_repository(tmp_path)
    git(repo, "config", "--local", "core.hooksPath", HOOKS_PATH)

    assert install(repo) == 0
    payload = json.loads(marker_path(repo).read_text(encoding="utf-8"))
    assert payload["changed_config"] is False
    assert remove(repo) == 0
    assert configured_hooks_path(repo) == HOOKS_PATH


def test_existing_unrelated_hooks_path_is_not_overwritten(tmp_path: Path):
    repo = temporary_repository(tmp_path)
    git(repo, "config", "--local", "core.hooksPath", ".custom-hooks")

    with pytest.raises(GuardInstallError, match="refusing to overwrite"):
        install(repo)
    assert configured_hooks_path(repo) == ".custom-hooks"
    assert not marker_path(repo).exists()


def test_malformed_marker_fails_safely_without_configuration_change(tmp_path: Path):
    repo = temporary_repository(tmp_path)
    git(repo, "config", "--local", "core.hooksPath", HOOKS_PATH)
    marker_path(repo).write_text("[]\n", encoding="utf-8")

    with pytest.raises(GuardInstallError, match="JSON object"):
        install(repo)
    assert configured_hooks_path(repo) == HOOKS_PATH


def test_remove_refuses_when_configuration_drifted(tmp_path: Path):
    repo = temporary_repository(tmp_path)
    install(repo)
    git(repo, "config", "--local", "core.hooksPath", ".changed-after-install")

    with pytest.raises(GuardInstallError, match="changed after installation"):
        remove(repo)
    assert configured_hooks_path(repo) == ".changed-after-install"
    assert marker_path(repo).exists()


def test_installed_hook_blocks_protected_updates_without_mutating_remote(
    installed_hook_topology: InstalledHookTopology,
):
    topology = installed_hook_topology
    initial_remote_main = remote_ref(topology, "refs/heads/main")
    assert initial_remote_main is not None

    git(topology.worktree, "checkout", "-b", "feature/safe", environment=topology.environment)
    safe_head = commit_file(topology, "safe.txt", "safe\n", "safe feature")
    safe_push = git(
        topology.worktree,
        "push",
        topology.remote_name,
        "feature/safe",
        environment=topology.environment,
    )
    assert safe_push.returncode == 0
    assert remote_ref(topology, "refs/heads/feature/safe") == safe_head

    git(topology.worktree, "checkout", "main", environment=topology.environment)
    blocked_main_head = commit_file(topology, "main.txt", "blocked\n", "blocked main update")
    blocked_push = git(
        topology.worktree,
        "push",
        topology.remote_name,
        "main",
        check=False,
        environment=topology.environment,
    )
    assert blocked_push.returncode != 0
    assert "blocked an update to refs/heads/main" in blocked_push.stderr
    assert remote_ref(topology, "refs/heads/main") == initial_remote_main

    blocked_delete = git(
        topology.worktree,
        "push",
        topology.remote_name,
        "--delete",
        "main",
        check=False,
        environment=topology.environment,
    )
    assert blocked_delete.returncode != 0
    assert "blocked an update to refs/heads/main" in blocked_delete.stderr
    assert remote_ref(topology, "refs/heads/main") == initial_remote_main

    git(topology.worktree, "checkout", "-b", "feature/multi", environment=topology.environment)
    commit_file(topology, "multi.txt", "multi\n", "multi-ref feature")
    blocked_multi = git(
        topology.worktree,
        "push",
        topology.remote_name,
        "main",
        "feature/multi",
        check=False,
        environment=topology.environment,
    )
    assert blocked_multi.returncode != 0
    assert "blocked an update to refs/heads/main" in blocked_multi.stderr
    assert remote_ref(topology, "refs/heads/main") == initial_remote_main
    assert remote_ref(topology, "refs/heads/feature/multi") is None

    bypass_environment = {
        **topology.environment,
        "AGENT_OS_ALLOW_PROTECTED_PUSH": "1",
        "AGENT_OS_PROTECTED_PUSH_REASON": "temporary fixture recovery",
    }
    bypass_push = git(
        topology.worktree,
        "push",
        topology.remote_name,
        "main",
        environment=bypass_environment,
    )
    assert "WARNING" in bypass_push.stderr
    assert "temporary fixture recovery" in bypass_push.stderr
    assert remote_ref(topology, "refs/heads/main") == blocked_main_head


def test_installed_wrapper_fails_closed_when_python_is_unavailable(
    installed_hook_topology: InstalledHookTopology,
    tmp_path: Path,
):
    topology = installed_hook_topology
    git_binary = shutil.which("git")
    assert git_binary is not None

    isolated_bin = tmp_path / "isolated-bin"
    isolated_bin.mkdir()
    git_shim = isolated_bin / "git"
    git_shim.write_text(
        "#!/bin/sh\n" f"exec {shlex.quote(git_binary)} \"$@\"\n",
        encoding="utf-8",
    )
    git_shim.chmod(0o755)

    environment = {
        **topology.environment,
        "PATH": str(isolated_bin),
    }
    result = run_command(
        topology.worktree,
        [str(topology.worktree / HOOKS_PATH / "pre-push"), topology.remote_name, str(topology.bare_remote)],
        check=False,
        environment=environment,
        input_text=update_line("refs/heads/feature/safe"),
    )
    assert result.returncode == 2
    assert "Python 3 is required" in result.stderr
