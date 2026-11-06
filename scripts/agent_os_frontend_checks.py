"""Mandatory frontend checks for the Agent OS Validation Gate.

``scripts/validate-all.sh`` is Python-only, and the selector's ``aggregate``
profile carries only ``python -m pytest``. Before this module a pull request that
changed a Node project together with any workflow, ``pyproject.toml`` or other
unmapped executable file was therefore validated without running a single
frontend command, and the one path-filtered workflow that did run the full
Picture Perfect check was not a required status.

This module is the profile-independent frontend lane. The ``frontend`` job runs
it on every pull_request and workflow_dispatch run; ``aggregate-gate`` requires
that job's exact ``success`` (see ``agent_os_aggregate_gate.frontend_blocker``).
A PR that changes no Node project still gets a ``success`` from this job, with the
non-applicability printed, so the required decision always executes and a skipped
job can never be mistaken for proof.

Scope is deliberately whole-project: any changed path under a project directory
selects that project. Playwright browser suites stay in their own path-filtered
workflows (``teacher-os-react-ci``); they are advisory because a path-filtered
workflow cannot be globally required without stranding unrelated PRs.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, NamedTuple, Sequence

ROOT = Path(__file__).resolve().parents[1]


class Project(NamedTuple):
    name: str
    directory: str
    commands: tuple[tuple[str, ...], ...]


# Install commands mirror each project's existing plan: only the reference UI
# project has no committed lockfile, so it keeps ``npm install``.
PROJECTS: tuple[Project, ...] = (
    Project(
        "picture-perfect-coach",
        "08_Tooling/instructional-materials-coach/picture-perfect-coach",
        (("npm", "ci"), ("npm", "run", "check")),
    ),
    Project(
        "software-tutorial-capture",
        "08_Tooling/instructional-materials-coach/capture",
        (("npm", "ci"), ("npm", "test"), ("npm", "run", "check")),
    ),
    Project(
        "ui-cross-platform-reference",
        "05_Examples/ui-cross-platform-reference",
        (("npm", "install"), ("npm", "test")),
    ),
    Project(
        "teacher-os-web",
        "08_Tooling/teacher-os-web",
        (("npm", "ci"), ("npm", "run", "build"), ("npm", "run", "test:unit")),
    ),
)


def _normalize(path: str) -> str:
    return path.strip().replace("\\", "/").removeprefix("./")


def _under(path: str, directory: str) -> bool:
    return path == directory or path.startswith(directory + "/")


def applicable_projects(
    changed_files: Iterable[str], projects: Sequence[Project] = PROJECTS
) -> tuple[Project, ...]:
    """Projects with at least one changed path beneath their directory."""
    paths = [_normalize(p) for p in changed_files if p.strip()]
    return tuple(
        project
        for project in projects
        if any(_under(path, project.directory) for path in paths)
    )


def unregistered_changed_package_dirs(
    changed_files: Iterable[str],
    tracked_files: Iterable[str],
    projects: Sequence[Project] = PROJECTS,
) -> tuple[str, ...]:
    """Tracked Node project directories with changes that no project owns.

    A new ``package.json`` project must be registered here; otherwise its
    changes would silently bypass this lane. Untouched unregistered projects do
    not fail unrelated pull requests.
    """
    changed = [_normalize(p) for p in changed_files if p.strip()]
    owned = [project.directory for project in projects]
    package_dirs = sorted(
        {
            str(Path(_normalize(t)).parent).replace("\\", "/")
            for t in tracked_files
            if Path(_normalize(t)).name == "package.json"
        }
    )
    return tuple(
        directory
        for directory in package_dirs
        if directory not in owned
        and directory != "."
        and any(_under(path, directory) for path in changed)
    )


Runner = Callable[[Sequence[str], Path], int]


def _run_command(argv: Sequence[str], cwd: Path) -> int:
    return subprocess.run(list(argv), cwd=cwd, check=False).returncode


def run_projects(
    projects: Sequence[Project],
    *,
    root: Path = ROOT,
    runner: Runner = _run_command,
) -> dict[str, list[tuple[str, int]]]:
    """Execute each project's commands in order; stop a project at its first failure.

    Returns ``{project name: [(command text, exit code), ...]}``. Every selected
    project is recorded even when an earlier project failed, so the caller can
    prove nothing applicable was left unexecuted.
    """
    results: dict[str, list[tuple[str, int]]] = {}
    for project in projects:
        record: list[tuple[str, int]] = []
        results[project.name] = record
        for argv in project.commands:
            print(f"::group::{project.name}: {' '.join(argv)}", flush=True)
            code = runner(argv, root / project.directory)
            print("::endgroup::", flush=True)
            record.append((" ".join(argv), code))
            if code != 0:
                break
    return results


def evaluate(
    applicable: Sequence[Project], results: dict[str, list[tuple[str, int]]]
) -> list[str]:
    """Return failure reasons; empty means every applicable project fully passed."""
    problems: list[str] = []
    for project in applicable:
        record = results.get(project.name)
        if record is None:
            problems.append(f"{project.name}: applicable but not executed")
            continue
        if len(record) != len(project.commands) or any(code != 0 for _, code in record):
            failed = [f"`{cmd}` exit {code}" for cmd, code in record if code != 0]
            problems.append(f"{project.name}: " + (", ".join(failed) or "incomplete"))
    return problems


def _git(*args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=ROOT, check=True, text=True, stdout=subprocess.PIPE
    ).stdout


def changed_files_against_main() -> tuple[str, list[str]]:
    """Return ``(merge_base, changed paths)`` for HEAD against ``origin/main``.

    ``--no-renames`` reports both sides of a rename, so moving a file out of a
    project still selects that project. Failure to compute the diff raises and
    fails the job; it is never treated as "nothing changed".
    """
    base = _git("merge-base", "origin/main", "HEAD").strip()
    names = _git("diff", "--name-only", "--no-renames", base, "HEAD").splitlines()
    return base, [name for name in names if name]


def _summary(lines: Sequence[str]) -> None:
    text = "\n".join(lines)
    print(text)
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def main() -> int:
    expected = os.environ.get("EXPECTED_HEAD_SHA", "")
    head = _git("rev-parse", "HEAD").strip()
    if not expected or head != expected:
        print(f"checked-out SHA {head} does not match expected head {expected or 'unset'}", file=sys.stderr)
        return 1

    base, changed = changed_files_against_main()
    tracked = _git("ls-files").splitlines()
    lines = ["## Agent OS Frontend Checks", "", f"- Tested head SHA: `{head}`", f"- Diff base (merge-base with main): `{base}`", f"- Changed files: {len(changed)}"]

    orphans = unregistered_changed_package_dirs(changed, tracked)
    if orphans:
        lines.append("- FAIL: changed Node project(s) not registered in scripts/agent_os_frontend_checks.py: " + ", ".join(orphans))
        _summary(lines)
        return 1

    applicable = applicable_projects(changed)
    if not applicable:
        lines.append("- No Node project changed; no frontend command applies. This is non-applicability, not a skipped check.")
        _summary(lines)
        return 0

    results = run_projects(applicable)
    problems = evaluate(applicable, results)
    for project in applicable:
        for command, code in results.get(project.name, []):
            lines.append(f"- {project.name}: `{command}` exit {code}")
    if problems:
        lines.append("- FAIL: " + "; ".join(problems))
        _summary(lines)
        return 1
    lines.append("- All applicable frontend projects executed and passed: " + ", ".join(p.name for p in applicable))
    _summary(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
