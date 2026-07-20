from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import subprocess

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


def update_line(
    remote_ref: str,
    *,
    local_ref: str = "refs/heads/feature/safe-change",
    local_object: str = ONE,
    remote_object: str = TWO,
) -> str:
    return f"{local_ref} {local_object} {remote_ref} {remote_object}\n"


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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
