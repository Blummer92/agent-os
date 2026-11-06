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
TEACHER = "08_Tooling/teacher-os-web"


def names(files):
    return [p.name for p in fe.applicable_projects(files)]


def test_unrelated_paths_select_no_project():
    # Control 5: the frontend suite is not run for unrelated changes.
    assert names(["docs/readme.md", "scripts/validate-all.sh", "tests/test_x.py", ".github/workflows/x.yml"]) == []


def test_changed_path_under_project_selects_only_that_project():
    assert names([f"{PP}/src/a.ts"]) == ["picture-perfect-coach"]
    assert names([f"{TEACHER}/vite.config.ts"]) == ["teacher-os-web"]  # not covered by any selector rule


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


def test_deleted_or_renamed_away_paths_select_the_project():
    assert names([f"{PP}/src/removed.ts"]) == ["picture-perfect-coach"]


def test_every_tracked_node_project_is_registered():
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, text=True, stdout=subprocess.PIPE, check=True).stdout.splitlines()
    registered = {p.directory for p in fe.PROJECTS}
    package_dirs = {str(Path(t).parent) for t in tracked if Path(t).name == "package.json"}
    assert package_dirs <= registered, package_dirs - registered


def test_changes_in_unregistered_node_project_fail_closed():
    tracked = ["tools/new-ui/package.json", f"{PP}/package.json", "package.json"]
    assert fe.unregistered_changed_package_dirs(["tools/new-ui/src/a.ts"], tracked) == ("tools/new-ui",)
    assert fe.unregistered_changed_package_dirs(["docs/a.md"], tracked) == ()
    assert fe.unregistered_changed_package_dirs([f"{PP}/src/a.ts"], tracked) == ()


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


def test_applicable_project_missing_from_results_is_a_failure():
    problems = fe.evaluate([_project()], {})
    assert problems == ["p: applicable but not executed"]


def test_incomplete_command_record_is_a_failure():
    assert fe.evaluate([_project()], {"p": [("one", 0)]})  # zero exit codes but commands never ran


def test_failure_in_one_project_does_not_hide_another_projects_result():
    a, b = _project("a"), _project("b")
    results = fe.run_projects([a, b], runner=lambda argv, cwd: 1 if cwd.name == "d" and argv[0] == "one" else 0)
    assert set(results) == {"a", "b"}


def test_cli_rejects_head_sha_mismatch(monkeypatch):
    monkeypatch.setenv("EXPECTED_HEAD_SHA", "0" * 40)
    assert fe.main() == 1


def test_script_entrypoint_runs_as_a_file():
    done = subprocess.run([sys.executable, "scripts/agent_os_frontend_checks.py"], cwd=ROOT, env={"PATH": "/usr/bin:/bin", "EXPECTED_HEAD_SHA": "x"}, capture_output=True, text=True)
    assert done.returncode == 1 and "does not match expected head" in done.stderr


@pytest.mark.parametrize("project", fe.PROJECTS, ids=lambda p: p.name)
def test_registered_project_has_install_then_real_checks(project):
    assert (ROOT / project.directory / "package.json").is_file()
    assert project.commands[0][:2] in {("npm", "ci"), ("npm", "install")}
    assert len(project.commands) >= 2
