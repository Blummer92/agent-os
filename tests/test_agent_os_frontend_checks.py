"""Behavior of the profile-independent frontend lane (scripts/agent_os_frontend_checks.py)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
    state = {"head": "a" * 40, "changed": [], "tracked": [], "run": lambda projects: {p.name: [(" ".join(c), 0) for c in p.commands] for p in projects}}
    out, summary = tmp_path / "out.txt", tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("EXPECTED_HEAD_SHA", state["head"])

    def fake_git(*args):
        if args[:2] == ("rev-parse", "HEAD"):
            return state["head"] + "\n"
        if args[0] == "merge-base":
            return "b" * 40 + "\n"
        if args[0] == "diff":
            return "\n".join(state["changed"]) + "\n"
        if args[0] == "ls-files":
            return "\n".join(state["tracked"]) + "\n"
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
    assert lane["outputs"]() == {"tested_sha": "a" * 40, "applicable": "none"}


def test_main_applicable_success_reports_projects_and_tested_sha(lane, capsys):
    lane["changed"] = [f"{PP}/package-lock.json", "scripts/x.py"]
    assert fe.main() == 0
    assert "::notice title=Frontend checks::Executed and passed: picture-perfect-coach" in capsys.readouterr().out
    assert lane["outputs"]() == {"tested_sha": "a" * 40, "applicable": "picture-perfect-coach"}


def test_main_failing_project_exits_nonzero_with_error_annotation(lane, capsys):
    lane["changed"] = [f"{PP}/src/a.ts"]
    lane["run"] = lambda projects: {"picture-perfect-coach": [("npm ci", 0), ("npm run check", 1)]}
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


def test_main_teacher_os_note_discloses_advisory_playwright(lane):
    lane["changed"] = [f"{TEACHER}/src/App.tsx"]
    assert fe.main() == 0
    assert "Playwright browser suites run in teacher-os-react-ci (advisory)" in lane["summary_text"]()


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
