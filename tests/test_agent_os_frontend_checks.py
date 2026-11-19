"""Behavior of the profile-independent frontend lane (scripts/agent_os_frontend_checks.py)."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts import agent_os_frontend_checks as fe
from scripts.agent_os_remote_validation import SelectionInput, load_rule_map, select_validation_plan

ROOT = Path(__file__).resolve().parents[1]
PP = "08_Tooling/instructional-materials-coach/picture-perfect-coach"
CAPTURE = "08_Tooling/instructional-materials-coach/capture"
TEACHER = "08_Tooling/teacher-os-web"
WAB = "08_Tooling/workspace-automation-builder"


def names(files):
    return [p.name for p in fe.applicable_projects(files)]


def test_unrelated_paths_select_no_project():
    # Control 5: the frontend suite is not run for unrelated changes.
    assert names(["docs/readme.md", "scripts/validate-all.sh", "tests/test_x.py", ".github/workflows/x.yml"]) == []


def test_changed_path_under_project_selects_only_that_project():
    assert names([f"{PP}/src/a.ts"]) == ["picture-perfect-coach"]
    assert names([f"{TEACHER}/vite.config.ts"]) == ["teacher-os-web"]  # not covered by any selector rule
    assert names([f"{WAB}/schemas/x.json"]) == ["workspace-automation-builder"]


def test_sibling_directory_prefix_does_not_select_project():
    assert names([f"{PP}-other/src/a.ts", f"{TEACHER}x/a.ts"]) == []


def test_mixed_python_and_frontend_still_selects_frontend():
    # The selector's `aggregate` profile drops these; this lane must not.
    files = [f"{PP}/src/a.ts", "scripts/foo.py", ".github/workflows/x.yml"]
    plan = select_validation_plan(
        SelectionInput(repository="Blummer92/agent-os", pull_request=1, base_sha="a" * 40, head_sha="b" * 40, changed_files=tuple(files)),
        load_rule_map(),
    )
    assert plan.profile == "aggregate" and plan.commands == ("python -m pytest",)
    assert names(files) == ["picture-perfect-coach"]


# Track B (D07 G4/G12): the pinned Picture Perfect test selection must run as its
# own command in this lane, not only embedded inside `npm run check` (whose
# typecheck/lint/build/guard steps are not a test substitute and whose single
# exit code cannot prove the pinned tests executed).
_PP_PINNED_TESTS = (
    "src/overlayIntegrity.test.ts",
    "src/exactComposite.test.ts",
    "src/exactCompositeSuite.test.ts",
    "src/framePlan.test.ts",
    "src/executorContract.test.ts",
    "src/provenanceValidator.test.ts",
)


def _project_by_name(name):
    return next(p for p in fe.PROJECTS if p.name == name)


def test_picture_perfect_lane_runs_pinned_npm_test_as_its_own_command():
    project = _project_by_name("picture-perfect-coach")
    assert project.commands == (
        ("npm", "ci"),
        ("npm", "test", "--", *_PP_PINNED_TESTS),
        ("npm", "run", "check"),
    )


def test_picture_perfect_pinned_tests_match_the_selector_focused_command():
    # Drift guard: the lane's pinned files must be exactly the selector's
    # focused picture-perfect-coach command, so the two registries cannot
    # silently disagree about which tests are pinned.
    rule = next(r for r in load_rule_map()["focused_rules"] if r["name"] == "picture-perfect-coach")
    assert rule["commands"] == [
        "cd 08_Tooling/instructional-materials-coach/picture-perfect-coach && npm test -- "
        + " ".join(_PP_PINNED_TESTS)
    ]
    project = _project_by_name("picture-perfect-coach")
    assert project.commands[1] == ("npm", "test", "--", *_PP_PINNED_TESTS)


def test_teacher_os_lane_runs_playwright_in_the_required_lane():
    # Track B (D07 G5/G12): Playwright must run in this required lane. The
    # selector's focused teacher-os-web commands include it, but any
    # aggregate-qualifying file drops all five; the advisory path-filtered
    # teacher-os-react-ci workflow cannot gate a merge.
    project = _project_by_name("teacher-os-web")
    assert project.commands == (
        ("npm", "ci"),
        ("npm", "run", "build"),
        ("npm", "run", "test:unit"),
        ("npx", "playwright", "install", "chromium"),
        ("npx", "playwright", "test"),
    )


def test_teacher_os_playwright_commands_match_the_selector_focused_commands():
    rule = next(r for r in load_rule_map()["focused_rules"] if r["name"] == "teacher-os-web")
    assert rule["commands"][-2:] == [
        "cd 08_Tooling/teacher-os-web && npx playwright install chromium",
        "cd 08_Tooling/teacher-os-web && npx playwright test",
    ]
    project = _project_by_name("teacher-os-web")
    assert project.commands[-2:] == (
        ("npx", "playwright", "install", "chromium"),
        ("npx", "playwright", "test"),
    )


def test_teacher_os_playwright_failure_blocks_and_stops_later_commands():
    project = _project_by_name("teacher-os-web")
    seen = []

    def runner(argv, cwd):
        seen.append(" ".join(argv))
        return 1 if argv[:3] == ("npx", "playwright", "install") else 0

    results = fe.run_projects([project], runner=runner)
    assert seen == ["npm ci", "npm run build", "npm run test:unit", "npx playwright install chromium"]
    problems = fe.evaluate([project], results)
    assert len(problems) == 1 and "playwright" in problems[0] and "exit 1" in problems[0]


def test_teacher_os_record_missing_playwright_is_not_a_pass():
    # A record that stops after test:unit (skipped/aborted Playwright, or a
    # stale receipt from before Playwright joined the lane) must never read
    # as EXECUTED_PASS for the required lane.
    project = _project_by_name("teacher-os-web")
    record = [("npm ci", 0), ("npm run build", 0), ("npm run test:unit", 0)]
    problems = fe.evaluate([project], {"teacher-os-web": record})
    assert problems and problems[0].startswith("teacher-os-web:")


def test_picture_perfect_record_missing_pinned_test_is_not_a_pass():
    project = _project_by_name("picture-perfect-coach")
    record = [("npm ci", 0), ("npm run check", 0)]
    problems = fe.evaluate([project], {"picture-perfect-coach": record})
    assert problems and problems[0].startswith("picture-perfect-coach:")


def test_frontend_rejects_wrong_or_reordered_same_length_command_receipts():
    project = _project_by_name("teacher-os-web")
    correct = [(" ".join(argv), 0) for argv in project.commands]
    assert fe.evaluate([project], {project.name: correct}) == []
    wrong = [*correct[:-1], ("wrong command", 0)]
    swapped = [*correct[:-2], correct[-1], correct[-2]]
    for record in (wrong, swapped, [*correct, correct[-1]]):
        assert "identity or order mismatch" in fe.evaluate([project], {project.name: record})[0]


def test_frontend_rejects_removed_required_commands_even_if_the_registry_and_receipts_agree():
    for name, drop in (
        ("teacher-os-web", ("npx", "playwright", "test")),
        ("picture-perfect-coach", ("npm", "test", "--", *_PP_PINNED_TESTS)),
    ):
        original = _project_by_name(name)
        reduced = original._replace(commands=tuple(argv for argv in original.commands if argv != drop))
        receipts = fe.run_projects([reduced], runner=lambda argv, cwd: 0)
        assert "required test commands missing" in fe.evaluate([reduced], receipts)[0]


def _fixture_vitest(cwd):
    return {
        "success": True,
        "numPassedTests": len(_PP_PINNED_TESTS),
        "testResults": [
            {
                "name": str(cwd / path),
                "status": "passed",
                "assertionResults": [{"status": "passed"}],
            }
            for path in _PP_PINNED_TESTS
        ],
    }


def _fixture_playwright():
    return {
        "stats": {"expected": 2, "unexpected": 0, "flaky": 0, "skipped": 0},
        "errors": [],
        "suites": [{"specs": [], "suites": [{"specs": [{"tests": [
            {
                "projectName": name, "status": "expected", "expectedStatus": "passed",
                "results": [{"status": "passed"}],
            }
            for name in ("desktop", "phone")
        ]}]}]}],
    }


def test_pinned_vitest_uses_reporter_and_rejects_missing_zero_and_wrong_file_evidence():
    project = _project_by_name("picture-perfect-coach")
    expected = project.commands[1]
    with TemporaryDirectory() as temp:
        cwd = Path(temp).resolve()
        good = _fixture_vitest(cwd)
        missing = copy.deepcopy(good)
        missing["testResults"].pop()
        missing["numPassedTests"] -= 1
        skipped = copy.deepcopy(good)
        skipped["testResults"][0]["assertionResults"][0]["status"] = "skipped"
        skipped["numPassedTests"] -= 1
        wrong = copy.deepcopy(good)
        wrong["testResults"][0]["name"] = str(cwd / "src/anotherFile.test.ts")
        for body, expected_code in ((good, 0), (missing, 78), (skipped, 78), (wrong, 78), (None, 78)):
            def fake_run(argv, **kwargs):
                assert tuple(argv[:len(expected)]) == expected
                assert "--reporter=json" in argv
                target = next(arg for arg in argv if arg.startswith("--outputFile.json=")).split("=", 1)[1]
                if body is not None:
                    Path(target).write_text(json.dumps(body), encoding="utf-8")
                return SimpleNamespace(returncode=0)
            with patch.object(fe.subprocess, "run", fake_run):
                assert fe._run_command(expected, cwd) == expected_code


def test_playwright_requires_actual_passes_for_both_projects_and_keeps_real_exit():
    expected = _project_by_name("teacher-os-web").commands[-1]
    good = _fixture_playwright()
    missing_phone = copy.deepcopy(good)
    missing_phone["suites"][0]["suites"][0]["specs"][0]["tests"].pop()
    missing_phone["stats"]["expected"] = 1
    skipped_phone = copy.deepcopy(good)
    skipped_phone["suites"][0]["suites"][0]["specs"][0]["tests"][-1]["results"] = []
    malformed = "not-json"
    runs = ((good, 0, 0), (missing_phone, 0, 78), (skipped_phone, 0, 78), (None, 0, 78),
            (malformed, 0, 78), (None, 3, 3))
    with TemporaryDirectory() as temp:
        for body, returncode, expected_code in runs:
            def fake_run(argv, **kwargs):
                assert argv == [*expected, "--reporter=dot,json"]
                target = kwargs["env"]["PLAYWRIGHT_JSON_OUTPUT_FILE"]
                if body is not None:
                    payload = body if isinstance(body, str) else json.dumps(body)
                    Path(target).write_text(payload, encoding="utf-8")
                return SimpleNamespace(returncode=returncode)
            with patch.object(fe.subprocess, "run", fake_run):
                assert fe._run_command(expected, Path(temp)) == expected_code


def test_dependency_bot_lockfile_only_changes_select_every_touched_project():
    # Dependabot (#3743) and Renovate (#3789) PRs change only package(-lock).json.
    assert names([f"{PP}/package-lock.json", f"{CAPTURE}/package-lock.json"]) == [
        "picture-perfect-coach",
        "software-tutorial-capture",
    ]
    assert names([f"{PP}/package.json", f"{PP}/package-lock.json"]) == ["picture-perfect-coach"]


def test_deleted_or_renamed_away_paths_select_the_project():
    assert names([f"{PP}/src/removed.ts"]) == ["picture-perfect-coach"]


def _tracked():
    return subprocess.run(["git", "ls-files"], cwd=ROOT, text=True, stdout=subprocess.PIPE, check=True).stdout.splitlines()


def test_every_tracked_node_project_and_js_source_is_owned_today():
    # Drift guard: touching every tracked package.json directory and JS/TS source reports nothing unowned.
    tracked = _tracked()
    assert fe.unowned_node_changes(tracked, tracked) == ()


def test_dependabot_and_renovate_directories_are_registered():
    # Every directory a dependency bot can raise an npm PR for must be a registered project.
    registered = {p.directory for p in fe.PROJECTS}
    package_dirs = {str(Path(t).parent) for t in _tracked() if Path(t).name == "package.json"}
    assert package_dirs <= registered, package_dirs - registered


def test_unknown_package_json_project_fails_closed():
    tracked = ["tools/new-ui/package.json", f"{PP}/package.json"]
    assert fe.unowned_node_changes(["tools/new-ui/src/a.ts"], tracked) == ("tools/new-ui", "tools/new-ui/src/a.ts")
    assert fe.unowned_node_changes(["tools/new-ui/package.json"], tracked) == ("tools/new-ui",)
    assert fe.unowned_node_changes(["docs/a.md"], tracked) == ()
    assert fe.unowned_node_changes([f"{PP}/src/a.ts"], tracked) == ()


def test_new_repo_root_node_project_fails_closed_but_unrelated_changes_do_not():
    tracked = ["package.json", f"{PP}/package.json"]
    assert fe.unowned_node_changes(["package.json"], tracked) == ("package.json (repository root)",)
    assert fe.unowned_node_changes(["package-lock.json"], tracked) == ("package.json (repository root)",)
    assert fe.unowned_node_changes(["README.md", "src/x.py"], tracked) == ()


@pytest.mark.parametrize("suffix", [".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"])
def test_orphan_js_ts_source_outside_registered_projects_fails_closed(suffix):
    assert fe.unowned_node_changes([f"tools/solo/run{suffix}"], []) == (f"tools/solo/run{suffix}",)
    assert fe.unowned_node_changes([f"{TEACHER}/src/run{suffix}"], []) == ()


def test_non_js_files_never_count_as_unknown_projects():
    assert fe.unowned_node_changes(["tools/x.py", "tools/x.json", "tools/x.md", "tools/x.gs"], []) == ()


def _project(name="p"):
    return fe.Project(name, "d", (("one",), ("two",), ("three",)))


def test_all_commands_passing_is_success():
    project = _project()
    results = fe.run_projects([project], runner=lambda argv, cwd: 0)
    assert [c for c, _ in results["p"]] == ["one", "two", "three"]
    assert fe.evaluate([project], results) == []


def test_failing_command_fails_project_and_stops_its_later_commands():
    project = _project()
    seen = []

    def runner(argv, cwd):
        seen.append(argv[0])
        return 3 if argv[0] == "two" else 0

    results = fe.run_projects([project], runner=runner)
    assert seen == ["one", "two"]
    problems = fe.evaluate([project], results)
    assert problems and "exit 3" in problems[0]


def test_failure_in_one_project_still_runs_and_records_the_next_project():
    a = fe.Project("a", "dir-a", (("a1",), ("a2",)))
    b = fe.Project("b", "dir-b", (("b1",),))
    ran = []

    def runner(argv, cwd):
        ran.append((cwd.name, argv[0]))
        return 1 if argv[0] == "a1" else 0

    results = fe.run_projects([a, b], runner=runner)
    assert ran == [("dir-a", "a1"), ("dir-b", "b1")]
    problems = fe.evaluate([a, b], results)
    assert len(problems) == 1 and problems[0].startswith("a:")


def test_applicable_project_missing_from_results_is_a_failure():
    assert fe.evaluate([_project()], {}) == ["p: applicable but not executed"]


def test_incomplete_command_record_is_a_failure():
    assert fe.evaluate([_project()], {"p": [("one", 0)]})  # zero exit codes but commands never ran


@pytest.fixture
def lane(monkeypatch, tmp_path):
    """Drive main() against a fake git, recording outputs and annotations."""
    state = {"head": "a" * 40, "changed": [], "deleted": [], "tracked": [], "run": lambda projects: {p.name: [(" ".join(c), 0) for c in p.commands] for p in projects}}
    out, summary = tmp_path / "out.txt", tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("EXPECTED_HEAD_SHA", state["head"])

    def fake_git(*args):
        if args[:2] == ("rev-parse", "HEAD"):
            return state["head"] + "\n"
        if args[0] == "merge-base":
            return "b" * 40 + "\n"
        # Real git only emits unquoted names with -z; fail the test if the lane forgets it.
        if args[0] == "diff":
            assert "-z" in args, args
            paths = state["changed"] if "--diff-filter=d" in args else state["changed"] + state["deleted"]
            return "".join(path + "\0" for path in paths)
        if args[0] == "ls-files":
            assert "-z" in args, args
            return "".join(path + "\0" for path in state["tracked"])
        raise AssertionError(args)

    monkeypatch.setattr(fe, "_git", fake_git)
    monkeypatch.setattr(fe, "run_projects", lambda projects, **kw: state["run"](projects))
    state["outputs"] = lambda: dict(line.split("=", 1) for line in out.read_text().splitlines()) if out.exists() else {}
    state["summary_text"] = lambda: summary.read_text() if summary.exists() else ""
    return state


def test_main_non_applicable_succeeds_with_visible_nonapplicability(lane, capsys):
    lane["changed"] = ["docs/a.md", "scripts/x.py"]
    assert fe.main() == 0
    out = capsys.readouterr().out
    assert "::notice title=Frontend checks::No Node project changed" in out
    assert "not a skipped check" in lane["summary_text"]()
    assert lane["outputs"]() == {"tested_sha": "a" * 40}


def test_main_applicable_success_reports_projects_and_tested_sha(lane, capsys):
    lane["changed"] = [f"{PP}/package-lock.json", "scripts/x.py"]
    assert fe.main() == 0
    assert "::notice title=Frontend checks::Executed and passed: picture-perfect-coach" in capsys.readouterr().out
    assert lane["outputs"]() == {"tested_sha": "a" * 40}


def test_main_failing_project_exits_nonzero_with_error_annotation(lane, capsys):
    lane["changed"] = [f"{PP}/src/a.ts"]
    lane["run"] = lambda projects: {"picture-perfect-coach": [
        ("npm ci", 0), (" ".join(("npm", "test", "--", *_PP_PINNED_TESTS)), 0), ("npm run check", 1)
    ]}
    assert fe.main() == 1
    assert "::error title=Frontend checks::picture-perfect-coach: `npm run check` exit 1" in capsys.readouterr().out


def test_main_unowned_project_fails_before_running_anything(lane, capsys):
    lane["changed"] = ["tools/new-ui/package.json", "tools/new-ui/src/a.ts"]
    lane["tracked"] = ["tools/new-ui/package.json"]
    lane["run"] = lambda projects: pytest.fail("nothing may run when a project is unowned")
    assert fe.main() == 1
    assert "not owned by a registered project" in capsys.readouterr().out


def test_main_head_sha_mismatch_fails_and_publishes_no_tested_sha(lane, monkeypatch, capsys):
    monkeypatch.setenv("EXPECTED_HEAD_SHA", "0" * 40)
    assert fe.main() == 1
    assert "tested_sha" not in lane["outputs"]()
    assert "does not match expected head" in capsys.readouterr().err


def test_main_selects_project_for_non_ascii_and_spaced_paths(lane, capsys):
    # git quotes non-ASCII names unless -z is used; those files must still select their project.
    lane["changed"] = [f"{PP}/src/caf\u00e9.ts", f"{CAPTURE}/test/with space.test.mjs"]
    assert fe.main() == 0
    out = capsys.readouterr().out
    assert "Executed and passed: picture-perfect-coach, software-tutorial-capture" in out


def test_changed_files_against_main_requests_nul_delimited_output(monkeypatch):
    calls = []

    def fake_git(*args):
        calls.append(args)
        return "b" * 40 + "\n" if args[0] == "merge-base" else f"{PP}/src/caf\u00e9.ts\0docs/a.md\0"

    monkeypatch.setattr(fe, "_git", fake_git)
    base, changed, present = fe.changed_files_against_main()
    assert base == "b" * 40
    assert changed == present == [f"{PP}/src/caf\u00e9.ts", "docs/a.md"]
    assert "-z" in calls[1] and "-z" in calls[2]
    assert "--diff-filter=d" in calls[2] and "--diff-filter=d" not in calls[1]


def test_main_teacher_os_reports_playwright_commands_in_the_required_lane(lane, capsys):
    lane["changed"] = [f"{TEACHER}/src/App.tsx"]
    assert fe.main() == 0
    summary = lane["summary_text"]()
    assert "teacher-os-web: `npx playwright install chromium` exit 0" in summary
    assert "teacher-os-web: `npx playwright test` exit 0" in summary
    assert "teacher-os-react-ci (advisory)" not in summary


def test_script_entrypoint_runs_as_a_file():
    done = subprocess.run([sys.executable, "scripts/agent_os_frontend_checks.py"], cwd=ROOT, env={"PATH": "/usr/bin:/bin", "EXPECTED_HEAD_SHA": "x"}, capture_output=True, text=True)
    assert done.returncode == 1 and "does not match expected head" in done.stderr


@pytest.mark.parametrize("project", fe.PROJECTS, ids=lambda p: p.name)
def test_registered_project_has_install_when_packaged_then_real_checks(project):
    directory = ROOT / project.directory
    assert directory.is_dir()
    if (directory / "package.json").is_file():
        assert project.commands[0][:2] in {("npm", "ci"), ("npm", "install")}
        assert len(project.commands) >= 2
    else:
        assert project.commands and project.commands[0][0] == "node"
        assert (directory / project.commands[0][1]).is_file()


def test_exact_names_are_preserved_not_stripped_or_rewritten():
    # Paths arrive NUL-delimited from git; spaces and backslashes are legal Linux name characters.
    assert names([PP + "/src/trailing.ts "]) == ["picture-perfect-coach"]  # still beneath the project
    assert fe.unowned_node_changes(["tools/solo/trailing.ts "], []) == ()  # "x.ts " is not a .ts file
    assert fe.unowned_node_changes(["tools/solo/back\\slash.ts"], []) == ("tools/solo/back\\slash.ts",)
    assert names([PP + "\\src/a.ts"]) == []  # a backslash is part of the name, never a separator


def test_missing_project_directory_or_executable_is_a_recorded_failure(tmp_path, capsys):
    assert fe._run_command(("npm", "ci"), tmp_path / "does-not-exist") == 127
    assert "cannot run `npm ci`" in capsys.readouterr().err
    assert fe._run_command(("definitely-not-an-installed-binary",), tmp_path) == 127


def test_deleting_a_registered_project_without_unregistering_it_fails_with_a_named_cause(tmp_path):
    ghost = fe.Project("ghost", "08_Tooling/removed-project", (("npm", "ci"), ("npm", "test")))
    results = fe.run_projects([ghost], root=tmp_path)
    assert results == {"ghost": [("npm ci", 127)]}
    assert fe.evaluate([ghost], results) == ["ghost: `npm ci` exit 127"]


def test_guarded_main_turns_unexpected_exceptions_into_annotated_failures(monkeypatch, capsys):
    def boom():
        raise RuntimeError("git exploded")

    monkeypatch.setattr(fe, "main", boom)
    assert fe.guarded_main() == 1
    captured = capsys.readouterr()
    assert "::error title=Frontend checks::frontend lane error: RuntimeError: git exploded" in captured.out
    assert "git exploded" in captured.err


def test_every_node_project_in_the_selector_is_also_required_by_the_lane():
    # Drift guard between the two registries: a Node project the selector knows must be validated here.
    import re

    from scripts.agent_os_remote_validation.selector import _NODE_PROJECTS

    lane_directories = {p.directory for p in fe.PROJECTS}
    assert {directory for directory, _, _ in _NODE_PROJECTS} <= lane_directories
    rules = load_rule_map()["focused_rules"]
    selector_directories = {
        match.group(1)
        for rule in rules
        for command in rule["commands"]
        if (match := re.match(r"^cd (\S+) && (?:npm|npx|node)\b", command))
    }
    assert selector_directories and selector_directories <= lane_directories, selector_directories - lane_directories


HOST_SCRIPTS = "08_Tooling/agent-os-execution-service/scripts"


def test_cross_directory_dependencies_select_the_dependent_project():
    # capture's contract tests read the execution-service host scripts; Picture Perfect imports capture.
    assert names([f"{HOST_SCRIPTS}/agent-os-canva-browser-session"]) == ["software-tutorial-capture"]
    assert names([f"{CAPTURE}/safe_recording.mjs"]) == ["picture-perfect-coach", "software-tutorial-capture"]
    assert names([f"{HOST_SCRIPTS}-extra/x"]) == []  # a sibling prefix is not the dependency


def test_declared_trigger_paths_exist():
    for project in fe.PROJECTS:
        for extra in project.also_triggered_by:
            assert (ROOT / extra).exists(), (project.name, extra)


def test_project_sources_do_not_read_outside_their_directory_without_declaring_it():
    # Drift guard: a JS/TS string literal such as '../../x' (or process.cwd()/../../x) that resolves to an
    # existing repo path outside the project must be covered by also_triggered_by, otherwise a change to
    # that path would report "not applicable" while the project's tests depend on it.
    import os
    import re

    literal = re.compile(r"""['"](\.\./[^'"\s]*)['"]""")
    cwd_literal = re.compile(r"""process\.cwd\(\)\s*,\s*['"](\.\./[^'"\s]*)['"]""")
    suffixes = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
    tracked = _tracked()

    def inside(path: Path, directory: Path) -> bool:
        return path == directory or directory in path.parents

    problems = []
    for project in fe.PROJECTS:
        base = ROOT / project.directory
        declared = [ROOT / extra for extra in project.also_triggered_by]
        for rel in tracked:
            if not rel.startswith(project.directory + "/") or not rel.endswith(suffixes):
                continue
            source = ROOT / rel
            text = source.read_text(encoding="utf-8", errors="ignore")
            # A literal is file-relative (import.meta.url, import specifiers) unless it is passed to
            # process.cwd(), where it is relative to the project directory (npm runs tests from there).
            candidates = [(source.parent, found) for found in literal.findall(text)]
            candidates += [(base, found) for found in cwd_literal.findall(text)]
            for origin, found in candidates:
                target = Path(os.path.normpath(origin / found))
                if ROOT not in target.parents or not target.exists() or inside(target, base):
                    continue
                if not any(inside(target, directory) for directory in declared):
                    problems.append(f"{rel}: {found} -> {target.relative_to(ROOT)}")
    assert not problems, problems


def test_added_or_edited_unregistered_manifests_fail_closed_without_any_tracked_file():
    # The manifest signal reads the changed paths, so it works even when HEAD tracks nothing there.
    assert fe.unowned_node_changes(["tools/new/package.json", "tools/new/package-lock.json"], []) == ("tools/new",)
    assert fe.unowned_node_changes(["package.json"], []) == ("package.json (repository root)",)
    assert fe.unowned_node_changes([f"{PP}/package.json", f"{PP}/package-lock.json"], []) == ()
    assert fe.unowned_node_changes(["docs/package.json.md", "tools/package.jsonc"], []) == ()


def test_gate_decision_functions_have_no_production_caller_outside_the_cli_wrappers():
    # evaluate_aggregate_gate/decide_terminal_status default frontend_required=False for backward
    # compatibility; only the fail-closed CLI wrappers may call them. A new caller must opt in explicitly.
    found = subprocess.run(
        ["git", "grep", "-lE", r"\b(evaluate_aggregate_gate|decide_terminal_status)\(", "--", "scripts", "08_Tooling", ".github", "src"],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, check=False,
    ).stdout.split()
    assert set(found) <= {"scripts/agent_os_aggregate_gate.py"}, found


def test_main_removing_a_project_and_its_registration_is_not_an_unknown_project(lane, capsys):
    # Deleted paths still select a registered project, but never count as an unknown one.
    lane["changed"] = ["scripts/agent_os_frontend_checks.py"]
    lane["deleted"] = ["tools/gone/package.json", "tools/gone/package-lock.json", "tools/gone/src/a.ts", "tools/gone/run.mjs"]
    assert fe.main() == 0
    assert "No Node project changed" in capsys.readouterr().out


def test_main_deleted_files_inside_a_registered_project_still_run_that_project(lane, capsys):
    lane["deleted"] = [f"{PP}/src/removed.ts"]
    assert fe.main() == 0
    assert "Executed and passed: picture-perfect-coach" in capsys.readouterr().out


def test_main_new_unregistered_project_still_fails_when_files_exist(lane, capsys):
    lane["changed"] = ["tools/fresh/package.json", "tools/fresh/index.js"]
    lane["tracked"] = ["tools/fresh/package.json"]
    lane["run"] = lambda projects: pytest.fail("nothing may run when a project is unowned")
    assert fe.main() == 1
    assert "tools/fresh" in capsys.readouterr().out


def test_js_under_a_declared_trigger_path_is_known_not_an_unknown_project():
    assert fe.unowned_node_changes([f"{HOST_SCRIPTS}/helper.mjs", f"{CAPTURE}/x.mjs"], []) == ()
    assert names([f"{HOST_SCRIPTS}/helper.mjs"]) == ["software-tutorial-capture"]
    assert fe.unowned_node_changes([f"{HOST_SCRIPTS}-extra/helper.mjs"], []) == (f"{HOST_SCRIPTS}-extra/helper.mjs",)


def test_npm_commands_retry_registry_fetches_unless_the_environment_overrides(monkeypatch, tmp_path):
    seen = {}

    def fake_run(argv, cwd, check, env):
        seen["env"] = env
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(fe.subprocess, "run", fake_run)
    monkeypatch.delenv("npm_config_fetch_retries", raising=False)
    assert fe._run_command(("npm", "ci"), tmp_path) == 0
    assert seen["env"]["npm_config_fetch_retries"] == "5"
    monkeypatch.setenv("npm_config_fetch_retries", "1")
    assert fe._run_command(("npm", "ci"), tmp_path) == 0
    assert seen["env"]["npm_config_fetch_retries"] == "1"
