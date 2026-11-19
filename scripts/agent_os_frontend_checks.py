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

Playwright browser suites for teacher-os-web run in this lane (the default
``playwright.config.ts`` suite, mirroring the selector's focused teacher-os-web
commands), so they survive aggregate-profile selection. The real-process
integration suite (``playwright.integration.config.ts``) still runs only in the
path-filtered advisory ``teacher-os-react-ci`` workflow; promoting it is a
separate owner decision. The Picture Perfect pinned tests run as their own
``npm test`` command in this lane, not only embedded inside ``npm run check``.
Both required browser/pinned test commands must provide structured case
evidence in addition to a successful subprocess exit.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
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


# The pinned Picture Perfect tests run as their own command (the same six files
# the selector's focused picture-perfect-coach command pins), before `check`
# re-runs the full vitest suite as part of typecheck/lint/test/build/guard.
# `check` alone cannot prove the pinned tests executed: its single exit code
# cannot distinguish a test failure from a typecheck/build failure, and a
# typecheck failure would stop the suite before any test ran.
_PICTURE_PERFECT_PINNED_TESTS = (
    "src/overlayIntegrity.test.ts",
    "src/exactComposite.test.ts",
    "src/exactCompositeSuite.test.ts",
    "src/framePlan.test.ts",
    "src/executorContract.test.ts",
    "src/provenanceValidator.test.ts",
)
_PP_TEST = ("npm", "test", "--", *_PICTURE_PERFECT_PINNED_TESTS)
_TEACHER_INSTALL = ("npx", "playwright", "install", "chromium")
_TEACHER_TEST = ("npx", "playwright", "test")
_TEACHER_PROJECTS = ("desktop", "phone")
# Matching by directory keeps the contract independent of the projects'
# editable command lists and display labels.
_REQUIRED_TEST_COMMANDS = {
    "08_Tooling/instructional-materials-coach/picture-perfect-coach": (_PP_TEST,),
    "08_Tooling/teacher-os-web": (_TEACHER_INSTALL, _TEACHER_TEST),
}
_MAX_TEST_REPORT_BYTES = 8 * 1024 * 1024
_TEST_EVIDENCE_FAILED = 78


# Install commands mirror each project's existing plan: the reference UI project has
# no committed lockfile, so it keeps ``npm install``; the workspace-automation-builder
# fixture validator needs no install (Node built-ins only).
PROJECTS: tuple[Project, ...] = (
    Project(
        "picture-perfect-coach",
        "08_Tooling/instructional-materials-coach/picture-perfect-coach",
        (
            ("npm", "ci"),
            _PP_TEST,
            ("npm", "run", "check"),
        ),
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
        (
            ("npm", "ci"),
            ("npm", "run", "build"),
            ("npm", "run", "test:unit"),
            # Playwright (default config only), mirroring the selector's focused
            # teacher-os-web commands. Without these, an aggregate-qualifying
            # file dropped Playwright from every required lane: the aggregate
            # job is Python-only and teacher-os-react-ci is advisory.
            _TEACHER_INSTALL,
            _TEACHER_TEST,
        ),
        "Playwright integration suite (playwright.integration.config.ts) still runs only in the advisory teacher-os-react-ci workflow.",
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


def _read_test_report(path: Path) -> dict:
    with path.open("rb") as handle:
        data = handle.read(_MAX_TEST_REPORT_BYTES + 1)
    if len(data) > _MAX_TEST_REPORT_BYTES:
        raise ValueError("oversized reporter output")
    report = json.loads(data)
    if not isinstance(report, dict):
        raise ValueError("reporter output is not an object")
    return report


def _vitest_counts(report: dict, cwd: Path) -> dict[str, int]:
    entries = report.get("testResults")
    if report.get("success") is not True or not isinstance(entries, list):
        raise ValueError("Vitest did not report success")
    counts: dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise ValueError("malformed Vitest file entry")
        path = Path(entry["name"])
        name = (path.relative_to(cwd.resolve()) if path.is_absolute() else path).as_posix()
        assertions = entry.get("assertionResults")
        if (
            name in counts or name not in _PICTURE_PERFECT_PINNED_TESTS
            or entry.get("status") != "passed" or not isinstance(assertions, list)
        ):
            raise ValueError("invalid pinned Vitest file receipt")
        if any(not isinstance(a, dict) or a.get("status") not in (
            "passed", "skipped", "pending", "todo", "disabled",
        ) for a in assertions):
            raise ValueError("invalid Vitest case receipt")
        counts[name] = sum(a["status"] == "passed" for a in assertions)
    total = report.get("numPassedTests")
    if (
        set(counts) != set(_PICTURE_PERFECT_PINNED_TESTS) or not all(counts.values())
        or type(total) is not int or total != sum(counts.values())
    ):
        raise ValueError("missing pinned Vitest file or passed case evidence")
    return counts


def _playwright_counts(report: dict) -> dict[str, int]:
    suites = report.get("suites")
    stats = report.get("stats")
    if (
        not isinstance(suites, list) or not isinstance(stats, dict)
        or any(type(stats.get(key)) is not int or stats[key] < 0 for key in (
            "expected", "flaky", "unexpected",
        ))
        or stats["unexpected"] != 0
        or report.get("errors") != []
    ):
        raise ValueError("Playwright did not report a clean run")
    counts = dict.fromkeys(_TEACHER_PROJECTS, 0)
    pending = list(suites)
    while pending:
        suite = pending.pop()
        if not isinstance(suite, dict):
            raise ValueError("malformed Playwright suite")
        child_suites, specs = suite.get("suites", []), suite.get("specs")
        if not isinstance(child_suites, list) or not isinstance(specs, list):
            raise ValueError("malformed Playwright specs")
        pending.extend(child_suites)
        for spec in specs:
            cases = spec.get("tests") if isinstance(spec, dict) else None
            if not isinstance(cases, list):
                raise ValueError("malformed Playwright cases")
            for case in cases:
                if not isinstance(case, dict) or case.get("projectName") not in _TEACHER_PROJECTS:
                    raise ValueError("unexpected Playwright project")
                results = case.get("results")
                if not isinstance(results, list):
                    raise ValueError("malformed Playwright case results")
                if (
                    case.get("expectedStatus") == "passed" and case.get("status") in ("expected", "flaky")
                    and results and isinstance(results[-1], dict) and results[-1].get("status") == "passed"
                ):
                    counts[case["projectName"]] += 1
    if not all(counts.values()) or sum(counts.values()) > stats["expected"] + stats["flaky"]:
        raise ValueError("both default Playwright projects must have passing cases")
    return counts


def _run_with_test_evidence(argv: tuple[str, ...], cwd: Path, env: dict[str, str]) -> int:
    with tempfile.TemporaryDirectory(prefix="agent-os-frontend-") as temp:
        report_path = Path(temp) / "test-results.json"
        if argv == _PP_TEST:
            reporters = ("--reporter=default", "--reporter=json", f"--outputFile.json={report_path}")
            if env.get("GITHUB_ACTIONS") == "true":
                reporters += ("--reporter=github-actions",)
        else:
            reporters = ("--reporter=dot,json",)
            env = {**env, "PLAYWRIGHT_JSON_OUTPUT_FILE": str(report_path)}
        code = subprocess.run([*argv, *reporters], cwd=cwd, check=False, env=env).returncode
        if code:
            return code
        try:
            report = _read_test_report(report_path)
            counts = _vitest_counts(report, cwd) if argv == _PP_TEST else _playwright_counts(report)
        except (OSError, ValueError, RecursionError):
            # Report files can contain arbitrary test output. Log no raw data.
            print(f"missing or invalid test-case evidence for `{' '.join(argv)}`", file=sys.stderr)
            return _TEST_EVIDENCE_FAILED
        print("frontend test evidence: " + json.dumps(counts, sort_keys=True), flush=True)
        return 0


def _run_command(argv: Sequence[str], cwd: Path) -> int:
    try:
        env = {**_NPM_RETRY_ENV, **os.environ}
        command = tuple(argv)
        if command in (_PP_TEST, _TEACHER_TEST):
            return _run_with_test_evidence(command, cwd, env)
        return subprocess.run(list(argv), cwd=cwd, check=False, env=env).returncode
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
        required = _REQUIRED_TEST_COMMANDS.get(project.directory, ())
        if tuple(argv for argv in project.commands if argv in required) != required:
            problems.append(f"{project.name}: required test commands missing, duplicated, or out of order")
            continue
        record = results.get(project.name)
        if record is None:
            problems.append(f"{project.name}: applicable but not executed")
            continue
        expected = [" ".join(argv) for argv in project.commands]
        if [cmd for cmd, _ in record] != expected[:len(record)]:
            problems.append(f"{project.name}: command receipt identity or order mismatch")
            continue
        failed = [f"`{cmd}` exit {code}" for cmd, code in record if type(code) is not int or code != 0]
        if failed:
            problems.append(f"{project.name}: " + ", ".join(failed))
        elif len(record) != len(expected):
            problems.append(f"{project.name}: incomplete")
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
