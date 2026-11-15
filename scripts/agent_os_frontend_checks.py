"""Mandatory frontend checks for the Agent OS Validation Gate.

``scripts/validate-all.sh`` is Python-only, and the selector's ``aggregate``
profile carries only ``python -m pytest``. Before this module a pull request that
changed a Node project together with any workflow, ``pyproject.toml`` or other
unmapped executable file was therefore validated without running a single
frontend command, and the one path-filtered workflow that did run the full
Picture Perfect check was not a required status.

This module is the profile-independent frontend lane. The ``frontend`` job runs
it on every pull_request and workflow_dispatch run; ``aggregate-gate`` requires
that job's exact ``success`` for the same SHA the authoritative status is minted
for (see ``agent_os_aggregate_gate.frontend_blocker``). A PR that changes no Node
project still gets a ``success`` from this job, with the non-applicability stated
in a check annotation and the step summary, so the required decision always
executes and a skipped job can never be mistaken for proof.

Applicability is whole-project: any changed path under a project directory selects
that project. Unknown projects fail closed: a changed ``package.json`` directory or
JS/TS source file that no registered project owns fails the job instead of being
silently unvalidated.

Playwright browser suites stay in their own path-filtered workflow
(``teacher-os-react-ci``): that workflow documents itself as not a Ready/merge
decision, and a path-filtered workflow cannot be globally required without
stranding unrelated PRs. Making them mandatory is an owner decision; the smallest
change is to add the two Playwright commands to the ``teacher-os-web`` entry.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, NamedTuple, Sequence

ROOT = Path(__file__).resolve().parents[1]

# A changed file with one of these suffixes that no registered project owns is an
# unknown JS/TS project and fails closed.
_NODE_SOURCE_SUFFIXES = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")


class Project(NamedTuple):
    name: str
    directory: str
    commands: tuple[tuple[str, ...], ...]
    note: str = ""
    # Other repo paths this project's tests read from outside ``directory``. A change
    # there must run the project too, or the lane would call it "not applicable".
    also_triggered_by: tuple[str, ...] = ()


# Install commands mirror each project's existing plan: the reference UI project has
# no committed lockfile, so it keeps ``npm install``; the workspace-automation-builder
# fixture validator needs no install (Node built-ins only).
PROJECTS: tuple[Project, ...] = (
    Project(
        "picture-perfect-coach",
        "08_Tooling/instructional-materials-coach/picture-perfect-coach",
        (("npm", "ci"), ("npm", "run", "check")),
        # src/uiEvidence.test.ts imports ../../capture/safe_recording.mjs
        also_triggered_by=("08_Tooling/instructional-materials-coach/capture",),
    ),
    Project(
        "software-tutorial-capture",
        "08_Tooling/instructional-materials-coach/capture",
        (("npm", "ci"), ("npm", "test"), ("npm", "run", "check")),
        # the *_capture_runtime_contract tests read the host scripts from process.cwd()/../../agent-os-execution-service/scripts
        also_triggered_by=("08_Tooling/agent-os-execution-service/scripts",),
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
        "Playwright browser suites run in teacher-os-react-ci (advisory) and are not part of this lane.",
    ),
    Project(
        "workspace-automation-builder",
        "08_Tooling/workspace-automation-builder",
        (("node", "tests/validate-fixtures.test.js"),),
    ),
)


def _normalize(path: str) -> str:
    # Paths arrive NUL-delimited from git, so names are exact (spaces and backslashes
    # are legal on Linux): never strip or rewrite them, only drop a leading "./".
    return path.removeprefix("./")


def _under(path: str, directory: str) -> bool:
    return path == directory or path.startswith(directory + "/")


def _selects(project: Project, path: str) -> bool:
    return _under(path, project.directory) or any(
        _under(path, extra) for extra in project.also_triggered_by
    )


def applicable_projects(
    changed_files: Iterable[str], projects: Sequence[Project] = PROJECTS
) -> tuple[Project, ...]:
    """Projects with a changed path beneath their directory or an ``also_triggered_by`` path."""
    paths = [_normalize(p) for p in changed_files if p]
    return tuple(
        project for project in projects if any(_selects(project, path) for path in paths)
    )


def unowned_node_changes(
    changed_files: Iterable[str],
    tracked_files: Iterable[str],
    projects: Sequence[Project] = PROJECTS,
) -> tuple[str, ...]:
    """Changed Node project files that no registered project owns (fail closed).

    ``changed_files`` must list only paths that still exist at HEAD: a deleted path has
    nothing left to validate, so removing a project (and its registration) can go green,
    while a project deleted but still registered fails with a named cause when it runs.

    Three signals, all independent of the registry: a changed ``package.json`` or
    lockfile in an unregistered directory, any changed path beneath an unregistered
    directory that HEAD tracks a ``package.json`` for, and a changed JS/TS source file
    outside every known project. A repo-root ``package.json`` or lockfile counts as its
    own project. Untouched unregistered projects never fail unrelated pull requests.
    """
    changed = [_normalize(p) for p in changed_files if p]
    # A path a registered project reads from outside its directory is known to the lane too.
    known = [project.directory for project in projects] + [
        extra for project in projects for extra in project.also_triggered_by
    ]

    def owned(path: str) -> bool:
        return any(_under(path, directory) for directory in known)

    unowned: set[str] = set()
    for path in changed:  # added or edited manifests, even where HEAD tracks nothing else (deleted paths are excluded upstream)
        if PurePosixPath(path).name in ("package.json", "package-lock.json"):
            directory = str(PurePosixPath(path).parent)
            if directory == ".":
                unowned.add("package.json (repository root)")
            elif not owned(directory):
                unowned.add(directory)
    for tracked in tracked_files:
        tracked = _normalize(tracked)
        if PurePosixPath(tracked).name != "package.json":
            continue
        directory = str(PurePosixPath(tracked).parent)
        if directory != "." and not owned(directory) and any(_under(path, directory) for path in changed):
            unowned.add(directory)
    unowned.update(
        path for path in changed if path.endswith(_NODE_SOURCE_SUFFIXES) and not owned(path)
    )
    return tuple(sorted(unowned))


Runner = Callable[[Sequence[str], Path], int]


# npm retries a failed registry fetch twice by default; a transient outage would otherwise turn a
# required status red (and a failure supersedes a reused success), so retry more patiently.
# Variables already set in the environment win.
_NPM_RETRY_ENV = {
    "npm_config_fetch_retries": "5",
    "npm_config_fetch_retry_mintimeout": "2000",
    "npm_config_fetch_retry_maxtimeout": "30000",
}


def _run_command(argv: Sequence[str], cwd: Path) -> int:
    try:
        return subprocess.run(
            list(argv), cwd=cwd, check=False, env={**_NPM_RETRY_ENV, **os.environ}
        ).returncode
    except OSError as exc:
        # A registered project whose directory or executable is missing (for example a
        # PR that deletes the project but keeps its registration) is a recorded failure
        # with a named cause, never a bare traceback.
        print(f"cannot run `{' '.join(argv)}` in {cwd}: {exc}", file=sys.stderr)
        return 127


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


def _git_paths(*args: str) -> list[str]:
    """Run a git command that lists paths and split its NUL-delimited (``-z``) output.

    Without ``-z`` git quotes and octal-escapes non-ASCII names, so a changed
    ``caf\u00e9.ts`` would never match its project directory and would read as
    "nothing changed".
    """
    return [path for path in _git(*args).split("\0") if path]


def changed_files_against_main() -> tuple[str, list[str], list[str]]:
    """Return ``(merge_base, changed paths, changed paths that still exist)`` for HEAD vs ``origin/main``.

    ``--no-renames`` reports both sides of a rename, so moving a file out of a
    project still selects that project. Deleted paths select a project (its tests
    must still pass) but never count as an unknown project. Failure to compute the
    diff raises and fails the job; it is never treated as "nothing changed".
    """
    base = _git("merge-base", "origin/main", "HEAD").strip()
    changed = _git_paths("diff", "--name-only", "-z", "--no-renames", base, "HEAD")
    present = _git_paths("diff", "--name-only", "-z", "--no-renames", "--diff-filter=d", base, "HEAD")
    return base, changed, present


def _set_output(name: str, value: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def _annotate(level: str, message: str) -> None:
    """Emit a workflow annotation so the outcome is visible on the check run itself.

    Annotations attach to the job's check run, the surface consumers read; the step
    summary alone is not visible there (#3587).
    """
    escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{level} title=Frontend checks::{escaped}", flush=True)


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
        message = f"checked-out SHA {head} does not match expected head {expected or 'unset'}"
        print(message, file=sys.stderr)
        _annotate("error", message)
        return 1
    _set_output("tested_sha", head)

    base, changed, present = changed_files_against_main()
    tracked = _git_paths("ls-files", "-z")
    lines = [
        "## Agent OS Frontend Checks",
        "",
        f"- Tested head SHA: `{head}`",
        f"- Diff base (merge-base with main): `{base}`",
        f"- Changed files: {len(changed)}",
    ]

    unowned = unowned_node_changes(present, tracked)
    if unowned:
        message = (
            "changed Node project file(s) not owned by a registered project in "
            "scripts/agent_os_frontend_checks.py: " + ", ".join(unowned)
        )
        lines.append(f"- FAIL: {message}")
        _summary(lines)
        _annotate("error", message)
        return 1

    applicable = applicable_projects(changed)
    if not applicable:
        message = "No Node project changed; no frontend command was executed or needed. This is non-applicability, not a skipped check."
        lines.append(f"- {message}")
        _summary(lines)
        _annotate("notice", message)
        return 0

    results = run_projects(applicable)
    problems = evaluate(applicable, results)
    for project in applicable:
        for command, code in results.get(project.name, []):
            lines.append(f"- {project.name}: `{command}` exit {code}")
        if project.note:
            lines.append(f"- {project.name} note: {project.note}")
    if problems:
        message = "; ".join(problems)
        lines.append(f"- FAIL: {message}")
        _summary(lines)
        _annotate("error", message)
        return 1
    message = "Executed and passed: " + ", ".join(p.name for p in applicable)
    lines.append(f"- All applicable frontend projects executed and passed: {', '.join(p.name for p in applicable)}")
    _summary(lines)
    _annotate("notice", message)
    return 0


def guarded_main() -> int:
    """Run :func:`main`, turning any unexpected exception into an annotated failure."""
    try:
        return main()
    except Exception as exc:  # noqa: BLE001 - the lane must fail closed with a visible cause
        message = f"frontend lane error: {type(exc).__name__}: {exc}"
        print(message, file=sys.stderr)
        _annotate("error", message)
        return 1


if __name__ == "__main__":
    sys.exit(guarded_main())
