"""Execute the runner against independent fault producers and evidence fixtures.

The interpreter stand-in owns only the test producer: actual runner discovery,
status consumption, JUnit parsing, completeness reconciliation and manifest I/O
are executed unchanged. Positive real-pytest coverage uses the same fixture.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("VALIDATE_ALL_TEST_SOURCE", str(ROOT / "scripts" / "validate-all.sh")))
PASS_XML = ('<testsuites><testsuite name="pytest" tests="1" failures="0" errors="0" skipped="0">'
            '<testcase classname="m" name="t"/></testsuite></testsuites>')


def make_repo(path: Path, script: str | None = None) -> Path:
    path.mkdir(parents=True)
    (path / "scripts").mkdir()
    (path / "scripts" / "validate-all.sh").write_text(script or SOURCE.read_text())
    for helper in (ROOT / "scripts").glob("agent_os_ci_*.py"):
        shutil.copy2(helper, path / "scripts" / helper.name)
    structural = path / "07_Agent_Tests" / "validate-repo-structure.sh"
    structural.parent.mkdir()
    structural.write_text("#!/usr/bin/env bash\nexit 0\n")
    add_suite(path, ".")
    producer = path / "producer-python"
    producer.write_text("#!" + sys.executable + "\n" + r'''
import atexit, json, os, pathlib, sys, time
args = sys.argv[1:]
if args == ['-m', 'ruff', 'check', '.']:
    raise SystemExit(0)
if os.environ.get('QA_REAL_PYTEST') == '1':
    os.execv(sys.executable, [sys.executable, *args])
if args and args[0] == '-':
    sys.argv = args
    exec(compile(sys.stdin.read(), '<stdin>', 'exec'))
    raise SystemExit(0)
if args and args[0].endswith('.py'):
    os.execv(sys.executable, [sys.executable, *args])
if args == ['-m', 'pytest', '--version']:
    print('pytest producer fixture')
    raise SystemExit(0)
if args[:2] != ['-m', 'pytest']:
    raise SystemExit(3)
if '--collect-only' in args:
    print('m.py::t')
    raise SystemExit(0)
print('PRODUCER ' + args[2] + ' ADDOPTS=' + os.environ.get('PYTEST_ADDOPTS', ''))
if os.environ.get('QA_SCHEDULE_LOG'):
    def event(kind):
        record = {'kind': kind, 'suite': str(pathlib.Path.cwd().relative_to(os.environ['QA_REPO_ROOT'])),
                  'time': time.monotonic(), 'args': args,
                  'coverage_file': os.environ.get('COVERAGE_FILE', '')}
        with open(os.environ['QA_SCHEDULE_LOG'], 'a') as stream:
            stream.write(json.dumps(record) + '\n')
    event('start')
    atexit.register(event, 'end')
    time.sleep(0.15)
mode = os.environ.get('QA_FOCUS_FAULT', '') if args[2] != 'tests' else os.environ.get('QA_SUITE_FAULT', '')
xml = '<testsuites><testsuite name="pytest" tests="1" failures="0" errors="0" skipped="0"><testcase classname="m" name="t"/></testsuite></testsuites>'
if mode == 'malformed':
    xml = '<testsuite'
elif mode in ('failure', 'error', 'skipped'):
    plural = {'failure': 'failures', 'error': 'errors', 'skipped': 'skipped'}[mode]
    xml = '<testsuites><testsuite name="pytest" tests="1" ' + plural + '="1"><testcase classname="m" name="t"><' + mode + '/></testcase></testsuite></testsuites>'
for arg in args:
    if arg.startswith('--junitxml=') and mode != 'missing':
        report = pathlib.Path(arg.split('=', 1)[1])
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(xml)
raise SystemExit(0)
''')
    producer.chmod(0o755)
    return path


def add_suite(root: Path, name: str, *, src: bool = False) -> None:
    module = root / name / "tests" / "test_one.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text("def test_one():\n    assert True\n")
    if src:
        (root / name / "src").mkdir(exist_ok=True)


def run_repo(root: Path, *args: str, hook: str = "", **extra: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for name in ("CI_JUNIT_DIR", "CI_JUNIT_RUN_ID", "CI_JUNIT_RUN_ATTEMPT", "CI_JUNIT_HEAD_SHA", "BASH_ENV", "PYTEST_ADDOPTS"):
        env.pop(name, None)
    env.update(PYTHON_BIN=str(root / "producer-python"), CI_JUNIT_DIR=str(root / "evidence"),
               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", VALIDATE_ALL_MAX_PARALLEL="2")
    env.update(extra)
    if hook:
        startup = root / "fault.bash"
        startup.write_text(hook)
        env["BASH_ENV"] = str(startup)
    result = subprocess.run(["bash", str(root / "scripts" / "validate-all.sh"), *args], cwd=root,
                            env=env, text=True, capture_output=True, check=False, timeout=90)
    evidence = os.environ.get("VALIDATE_ALL_FAULT_EVIDENCE")
    if evidence:
        event = {"args": list(args), "exit": result.returncode, "stdout": result.stdout,
                 "stderr": result.stderr, "repo": str(root)}
        with Path(evidence).open("a") as stream:
            stream.write(json.dumps(event) + "\n")
    return result


def assert_failed(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode != 0, result.stdout + result.stderr
    assert "OVERALL STATUS\nPASS" not in result.stdout, result.stdout + result.stderr


def printf_fault(kind: str) -> str:
    if kind in ("header", "row"):
        condition = "[[ $1 == suite_name* ]]" if kind == "header" else "[[ $1 == '%s\\t%s\\t%s\\t%s\\t%s\\t%s\\n' ]]"
        return "printf() { if " + condition + "; then return 74; fi; builtin printf \"$@\"; }\n"
    records = {"missing": None, "truncated": "0|", "partial-line": "0|1\\n", "extra": "0|1|2|extra\\n",
               "trailing": "0|1|2\\ntrailing\\n", "empty": "0||2\\n", "nan": "0|NaN|2\\n",
               "no-newline": "0|1|2", "blank-lines": "0|1|2\\n\\n", "leading-zero": "0|08|09\\n",
               "nul": "0|1|2\\000\\n",
               "huge": "0|99999999999999999999999999999|99999999999999999999999999999\\n",
               "crash": "CRASH"}
    record = records[kind]
    action = "return 74" if record is None else "exit 44" if record == "CRASH" else "builtin printf '" + record + "'"
    return "printf() { if [[ $1 == '%s|%s|%s\\n' ]]; then " + action + "; return; fi; builtin printf \"$@\"; }\n"


@pytest.mark.parametrize("mode", ["missing", "malformed", "failure", "error", "skipped"])
def test_focused_evidence_fault_cannot_certify_success(tmp_path: Path, mode: str) -> None:
    repo = make_repo(tmp_path / "repo")
    result = run_repo(repo, "--focused", "tests/test_one.py", QA_FOCUS_FAULT=mode)
    assert_failed(result)


@pytest.mark.parametrize("kind", ["header", "row", "missing", "truncated", "partial-line", "extra", "trailing", "empty", "nan", "no-newline", "blank-lines", "leading-zero", "huge", "nul", "crash"])
def test_manifest_and_worker_faults_fail_closed(tmp_path: Path, kind: str) -> None:
    repo = make_repo(tmp_path / "repo")
    assert_failed(run_repo(repo, hook=printf_fault(kind)))


def test_manifest_directory_fails_closed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    (repo / "evidence" / "manifest.tsv").mkdir(parents=True)
    assert_failed(run_repo(repo))


@pytest.mark.parametrize("coach", [False, True])
def test_abnormal_worker_exit_vetoes_even_a_valid_pass_receipt(tmp_path: Path, coach: bool) -> None:
    repo = make_repo(tmp_path / "repo")
    if coach:
        add_suite(repo, "08_Tooling/instructional-materials-coach")
    expected = "08_Tooling/instructional-materials-coach" if coach else "root"
    hook = ('printf() { if [[ $1 == \'%s|%s|%s\\n\' ]] && [ "${suite_name:-}" = "' + expected + '" ]; then '
            'builtin printf "$@"; exit 44; fi; builtin printf "$@"; }\n')
    assert_failed(run_repo(repo, hook=hook))


def test_real_addopts_cannot_hide_the_only_test(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    result = run_repo(repo, QA_REAL_PYTEST="1", PYTEST_ADDOPTS="-k nonexistent")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    receipt = json.loads((repo / "evidence" / "test-completeness-root.json").read_text())
    assert receipt["expected_count"] == receipt["executed_count"] == 1


def test_scheduler_concurrency_coach_isolation_and_manifest_order(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    coach = "08_Tooling/instructional-materials-coach"
    scheduler = "08_Tooling/workflow-scheduler"
    for name in (coach, scheduler, "pkg-a", "nested/pkg"):
        add_suite(repo, name, src=name in (coach, scheduler, "nested/pkg"))
    events_path = tmp_path / "schedule.jsonl"
    result = run_repo(repo, QA_SCHEDULE_LOG=str(events_path), QA_REPO_ROOT=str(repo))
    assert result.returncode == 0, result.stdout + result.stderr
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    starts = {event["suite"]: event["time"] for event in events if event["kind"] == "start"}
    ends = {event["suite"]: event["time"] for event in events if event["kind"] == "end"}
    assert len(starts) == 5
    assert all(ends[coach] <= starts[name] for name in starts if name != coach)
    ordinary = [name for name in starts if name != coach]
    assert any(starts[a] < ends[b] and starts[b] < ends[a]
               for a in ordinary for b in ordinary if a != b)
    invocation = next(event for event in events if event["suite"] == scheduler and event["kind"] == "start")
    assert "--cov=src/workflow_scheduler" in invocation["args"]
    assert "--cov-report=term" in invocation["args"]
    assert invocation["coverage_file"].endswith("/08_Tooling/workflow-scheduler/.coverage")
    names = [row.split("\t")[0] for row in (repo / "evidence" / "manifest.tsv").read_text().splitlines()[1:]
             if not row.startswith("test selection completeness:")]
    assert names == [coach, scheduler, "nested/pkg", "pkg-a", "root"]


def test_stale_artifact_symlinks_are_unlinked_without_touching_external_targets(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    evidence = repo / "evidence"
    evidence.mkdir()
    outside = tmp_path / "unrelated.xml"
    outside.write_text("unrelated external content")
    for name in ("manifest.tsv", "root.xml", "focused__tests__test_one.py.xml", "junit-subtest-receipt-root.json"):
        (evidence / name).symlink_to(outside)
    result = run_repo(repo, "--focused", "tests/test_one.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert outside.read_text() == "unrelated external content"
    assert not (evidence / "root.xml").is_symlink()


def test_directory_substitution_never_becomes_current_xml(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    protected = repo / "evidence" / "root.xml"
    protected.mkdir(parents=True)
    (protected / "unrelated.txt").write_text("preserve")
    assert_failed(run_repo(repo))
    assert (protected / "unrelated.txt").read_text() == "preserve"


@pytest.mark.parametrize("kind", ["find", "sort", "empty", "suite-find", "partial-find", "partial-sort"])
def test_discovery_faults_fail_closed(tmp_path: Path, kind: str) -> None:
    repo = make_repo(tmp_path / "repo")
    hooks = {"find": 'find() { return 73; }\n', "sort": 'sort() { return 73; }\n',
             "empty": 'find() { return 0; }\n',
             "suite-find": 'find() { if [[ $1 == . ]]; then command find "$@"; else return 73; fi; }\n',
             "partial-find": 'find() { if [[ $1 == . ]]; then builtin printf "./tests\\n"; return 73; else command find "$@"; fi; }\n',
             "partial-sort": 'sort() { command sort "$@"; return 73; }\n'}
    assert_failed(run_repo(repo, hook=hooks[kind]))


def test_mapfile_unavailable_still_executes_suites(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    result = run_repo(repo, hook="enable -n mapfile\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "==> root" in result.stdout
    assert "root\troot.xml\tyes\tPASS" in (repo / "evidence" / "manifest.tsv").read_text()


def test_stale_focused_evidence_cannot_certify_current_attempt(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    evidence = repo / "evidence"
    evidence.mkdir()
    (evidence / "focused__tests__test_one.py.xml").write_text(PASS_XML)
    assert_failed(run_repo(repo, "--focused", "tests/test_one.py", QA_FOCUS_FAULT="missing"))


def test_stale_full_suite_evidence_cannot_certify_current_attempt(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    evidence = repo / "evidence"
    evidence.mkdir()
    (evidence / "root.xml").write_text(PASS_XML)
    assert_failed(run_repo(repo, QA_SUITE_FAULT="missing"))


@pytest.mark.parametrize("mode", ["missing", "malformed", "failure", "skipped"])
def test_local_focused_evidence_is_required_too(tmp_path: Path, mode: str) -> None:
    repo = make_repo(tmp_path / "repo")
    result = run_repo(repo, "--focused", "tests/test_one.py", QA_FOCUS_FAULT=mode, CI_JUNIT_DIR="")
    assert_failed(result)


def test_distinct_suites_with_colliding_keys_are_rejected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    add_suite(repo, "p/a")
    add_suite(repo, "p__a")
    result = run_repo(repo)
    assert_failed(result)
    assert "colliding JUnit artifact keys" in result.stderr


def test_addopts_cannot_narrow_authoritative_execution(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    result = run_repo(repo, PYTEST_ADDOPTS="-k nonexistent")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PRODUCER tests ADDOPTS=\n" in result.stdout
    assert "unsetting" in result.stderr


@pytest.mark.parametrize("relative", [False, True])
def test_real_pytest_root_nested_plain_src_and_multiple_focus_pass(tmp_path: Path, relative: bool) -> None:
    repo = make_repo(tmp_path / "repo")
    add_suite(repo, "plain")
    add_suite(repo, "nested/pkg", src=True)
    result = run_repo(repo, "--focused", "tests/test_one.py", "--focused", "nested/pkg/tests/test_one.py",
                      QA_REAL_PYTEST="1", CI_JUNIT_DIR="evidence" if relative else str(repo / "evidence"))
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = (repo / "evidence" / "manifest.tsv").read_text()
    assert manifest.count("EXECUTED_PASS") == 5
    assert manifest.count("COMPLETE") == 3
    assert "OVERALL STATUS\nPASS" in result.stdout


def test_manifest_failure_never_disagrees_with_terminal_status(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    result = run_repo(repo, "--focused", "tests/test_one.py", QA_FOCUS_FAULT="failure")
    assert_failed(result)
    rows = (repo / "evidence" / "manifest.tsv").read_text().splitlines()
    focused = next(row.split("\t") for row in rows if row.startswith("focused:"))
    assert focused[3] == "FAIL"
    assert focused[4] != "0"


def test_complete_allowlisted_skip_is_preserved(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    module = repo / "tests" / "test_one.py"
    module.write_text("import pytest\n@pytest.mark.skip(reason='approved fixture')\ndef test_one():\n    assert True\n")
    allowlist = {"schema": "agent-os-ci-skipped-allowlist/1", "suites": {"root": ["tests.test_one::test_one"]}}
    (repo / "scripts" / "agent_os_ci_skipped_allowlist.json").write_text(json.dumps(allowlist))
    result = run_repo(repo, QA_REAL_PYTEST="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "COMPLETE" in (repo / "evidence" / "manifest.tsv").read_text()
