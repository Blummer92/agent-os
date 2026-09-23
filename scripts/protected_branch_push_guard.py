from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import TextIO

PROTECTED_REF = "refs/heads/main"
HOOKS_PATH = ".githooks"
MARKER_NAME = "agent-os-protected-branch-hook.json"
_ALLOW_ENV = "AGENT_OS_ALLOW_PROTECTED_PUSH"
_REASON_ENV = "AGENT_OS_PROTECTED_PUSH_REASON"
_OBJECT_ID_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


class GuardInputError(ValueError):
    """Raised when pre-push input cannot be verified safely."""


class GuardInstallError(RuntimeError):
    """Raised when local hook installation cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class PushUpdate:
    local_ref: str
    local_object: str
    remote_ref: str
    remote_object: str


def parse_push_updates(text: str) -> tuple[PushUpdate, ...]:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise GuardInputError("pre-push input is empty")

    updates: list[PushUpdate] = []
    for line_number, line in enumerate(lines, start=1):
        fields = line.split()
        if len(fields) != 4:
            raise GuardInputError(
                f"pre-push line {line_number} must contain exactly four fields"
            )
        local_ref, local_object, remote_ref, remote_object = fields
        if local_ref != "(delete)" and not local_ref.startswith("refs/"):
            raise GuardInputError(f"pre-push line {line_number} has an invalid local ref")
        if not remote_ref.startswith("refs/"):
            raise GuardInputError(f"pre-push line {line_number} has an invalid remote ref")
        if not _OBJECT_ID_RE.fullmatch(local_object):
            raise GuardInputError(f"pre-push line {line_number} has an invalid local object")
        if not _OBJECT_ID_RE.fullmatch(remote_object):
            raise GuardInputError(f"pre-push line {line_number} has an invalid remote object")
        updates.append(PushUpdate(local_ref, local_object, remote_ref, remote_object))
    return tuple(updates)


def protected_updates(updates: tuple[PushUpdate, ...]) -> tuple[PushUpdate, ...]:
    return tuple(update for update in updates if update.remote_ref == PROTECTED_REF)


def bypass_is_authorized(environment: Mapping[str, str]) -> bool:
    return (
        environment.get(_ALLOW_ENV) == "1"
        and bool(environment.get(_REASON_ENV, "").strip())
    )


def evaluate_push(
    text: str,
    *,
    environment: Mapping[str, str] | None = None,
    stderr: TextIO | None = None,
) -> int:
    environment = os.environ if environment is None else environment
    stderr = sys.stderr if stderr is None else stderr
    try:
        updates = parse_push_updates(text)
    except GuardInputError as exc:
        print(f"Agent OS protected-branch guard: blocked: {exc}", file=stderr)
        return 1

    blocked = protected_updates(updates)
    if not blocked:
        return 0

    if bypass_is_authorized(environment):
        reason = environment[_REASON_ENV].strip()
        print(
            "WARNING: Agent OS protected-branch guard bypass used for "
            f"{PROTECTED_REF}. Reason: {reason}",
            file=stderr,
        )
        return 0

    print(
        "Agent OS protected-branch guard blocked an update to refs/heads/main.",
        file=stderr,
    )
    print(
        "Create or update a feature branch and use a pull request instead.",
        file=stderr,
    )
    print(
        "Emergency recovery requires explicit owner approval plus both "
        f"{_ALLOW_ENV}=1 and a non-empty {_REASON_ENV}.",
        file=stderr,
    )
    print("Using --no-verify is not authorization.", file=stderr)
    return 1


def _run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def repository_root(start: Path | None = None) -> Path:
    start = Path.cwd() if start is None else start
    try:
        result = _run_git(start, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GuardInstallError("not inside a Git working tree") from exc
    return Path(result.stdout.strip()).resolve()


def _git_dir(root: Path) -> Path:
    result = _run_git(root, "rev-parse", "--git-dir")
    path = Path(result.stdout.strip())
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def _configured_hooks_path(root: Path) -> str | None:
    result = _run_git(root, "config", "--local", "--get", "core.hooksPath", check=False)
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise GuardInstallError(result.stderr.strip() or "unable to read core.hooksPath")
    return result.stdout.strip()


def _marker_path(root: Path) -> Path:
    return _git_dir(root) / MARKER_NAME


def _read_marker(marker: Path) -> dict[str, object]:
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardInstallError("installer marker is unreadable or malformed") from exc
    if not isinstance(payload, dict):
        raise GuardInstallError("installer marker must contain a JSON object")
    if payload.get("installed_hooks_path") != HOOKS_PATH:
        raise GuardInstallError("installer marker is not recognized")
    if not isinstance(payload.get("changed_config"), bool):
        raise GuardInstallError("installer marker has an invalid changed_config value")
    previous = payload.get("previous_hooks_path")
    if previous is not None and not isinstance(previous, str):
        raise GuardInstallError("installer marker has an invalid previous_hooks_path value")
    return payload


def install(root: Path | None = None) -> int:
    root = repository_root(root)
    hook = root / HOOKS_PATH / "pre-push"
    if not hook.is_file():
        raise GuardInstallError(f"missing version-controlled hook: {hook}")

    current = _configured_hooks_path(root)
    if current not in {None, HOOKS_PATH}:
        raise GuardInstallError(
            "core.hooksPath already points elsewhere; refusing to overwrite "
            f"{current!r}"
        )

    marker = _marker_path(root)
    if marker.exists():
        _read_marker(marker)
        if current != HOOKS_PATH:
            raise GuardInstallError(
                "installer marker exists but core.hooksPath is not configured as expected"
            )
        hook.chmod(hook.stat().st_mode | 0o111)
        print(f"Agent OS protected-branch hook is already installed via {HOOKS_PATH}.")
        return 0

    payload = {
        "changed_config": current is None,
        "installed_hooks_path": HOOKS_PATH,
        "previous_hooks_path": current,
    }
    changed_config = current is None
    try:
        if changed_config:
            _run_git(root, "config", "--local", "core.hooksPath", HOOKS_PATH)
        hook.chmod(hook.stat().st_mode | 0o111)
        marker.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, subprocess.CalledProcessError) as exc:
        if changed_config:
            _run_git(root, "config", "--local", "--unset", "core.hooksPath", check=False)
        marker.unlink(missing_ok=True)
        raise GuardInstallError("installation failed and local configuration was rolled back") from exc

    print(f"Installed Agent OS protected-branch hook via {HOOKS_PATH}.")
    return 0


def remove(root: Path | None = None) -> int:
    root = repository_root(root)
    marker = _marker_path(root)
    if not marker.is_file():
        raise GuardInstallError("no Agent OS installer marker found; no changes made")

    payload = _read_marker(marker)
    current = _configured_hooks_path(root)
    if current != HOOKS_PATH:
        raise GuardInstallError(
            "core.hooksPath changed after installation; refusing to modify it"
        )

    if payload["changed_config"] is True:
        _run_git(root, "config", "--local", "--unset", "core.hooksPath")
    marker.unlink()
    print("Removed Agent OS protected-branch hook configuration safely.")
    return 0


def status(root: Path | None = None) -> int:
    root = repository_root(root)
    payload = {
        "configured_hooks_path": _configured_hooks_path(root),
        "expected_hooks_path": HOOKS_PATH,
        "hook_exists": (root / HOOKS_PATH / "pre-push").is_file(),
        "installer_marker_exists": _marker_path(root).is_file(),
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agent OS local protected-branch guard")
    parser.add_argument("command", choices=("check", "install", "remove", "status"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check":
            return evaluate_push(sys.stdin.read())
        if args.command == "install":
            return install()
        if args.command == "remove":
            return remove()
        return status()
    except (GuardInstallError, OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
        print(f"Agent OS protected-branch guard: {detail}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
