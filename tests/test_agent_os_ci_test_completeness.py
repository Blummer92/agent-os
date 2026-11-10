"""Real-pytest negative controls for the executed-vs-reference completeness check.

Regression for the #3816 false green (PR #3817): the authoritative aggregate
passed while tests excluded by configuration never executed. Every control here
runs the real ``scripts/validate-all.sh`` with real pytest against a small
fixture repository. The fixture tests all *pass* when executed, so a red result
can only come from the completeness check (or pytest rejecting the option),
never from a test body failing.

Proven boundary is configuration. ``conftest.py`` manipulation is NOT covered
(see ``test_conftest_collect_ignore_is_a_documented_gap``); this is not CI
trust certification.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
RUNNER_FILES = ("validate-all.sh", "agent_os_ci_test_completeness.py", "agent_os_ci_junit_diff.py")
PYTEST_VERSION = tuple(int(part) for part in pytest.__version__.split(".")[:2])

PASSING = "def test_{}():\n    assert True\n"
BASE = {
    "pytest.ini": "[pytest]\naddopts = -v --strict-markers\n",
    "tests/__init__.py": "",
    "tests/test_a.py": PASSING.format("a1") + PASSING.format("a2"),
    "tests/sub/test_guard.py": PASSING.format("guard_regression"),
    "tests/test_ut.py": (
        "import unittest\n\n\nclass T(unittest.TestCase):\n"
        "    def test_ut_regression(self):\n        self.assertTrue(True)\n"
    ),
}
BROKEN = "raise RuntimeError('collection boom')\n"
LEGIT = {
    "tests/test_legit.py": (
        "import secrets\n\nimport pytest\n\n\n"
        "@pytest.mark.skip(reason='env')\ndef test_skipped():\n    raise AssertionError\n\n\n"
        "@pytest.mark.xfail(reason='known')\ndef test_xfail():\n    raise AssertionError\n\n\n"
        "@pytest.mark.parametrize('token', [secrets.token_urlsafe(8)])\n"
        "def test_regenerated(token):\n    assert token\n\n\n"
        "@pytest.mark.parametrize('value', [1, 2], ids=['a::b', 'c d'])\n"
        "def test_odd_ids(value):\n    assert value\n\n\n"
        "class TestGroup:\n    def test_member(self):\n        assert True\n"
    ),
    "tests/test_modskip.py": "import pytest\n\npytest.skip('module skipped', allow_module_level=True)\n",
    "tests/test_sub.py": (
        "import unittest\n\n\nclass S(unittest.TestCase):\n    def test_sub(self):\n"
        "        for i in range(3):\n            with self.subTest(i=i):\n                self.assertTrue(i >= 0)\n"
    ),
    # Excluded by pytest's own default norecursedirs, in the real run and the reference.
    "tests/venv/test_ignored.py": "def test_ignored():\n    raise AssertionError\n",
    "tests/node_modules/test_ignored.py": "def test_ignored():\n    raise AssertionError\n",
}
REGISTRY = "08_Tooling/reusable-capability-registry"
FIXTURE_SUITE = {
    "pyproject.toml": '[tool.pytest.ini_options]\nnorecursedirs = ["fixtures", ".*", "build", "dist", "*.egg", "__pycache__"]\n',
    "tests/test_ok.py": PASSING.format("ok"),
    "tests/fixtures/test_example.py": "def test_example():\n    raise AssertionError\n",
}


def _repo(tmp_path: Path, files: dict[str, str], *, drop: tuple[str, ...] = ()) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    for name in RUNNER_FILES:
        shutil.copy2(SCRIPTS / name, root / "scripts" / name)
    structural = root / "07_Agent_Tests" / "validate-repo-structure.sh"
    structural.parent.mkdir()
    structural.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (root / "ruff.toml").write_text('exclude = ["scripts"]\n', encoding="utf-8")  # only the fixtures are linted
    for rel, content in {**{k: v for k, v in BASE.items() if k not in drop}, **files}.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _run(repo: Path, junit_dir: Path | None = None, **env: str) -> subprocess.CompletedProcess[str]:
    merged = {key: value for key, value in os.environ.items() if key not in ("CI_JUNIT_DIR", "PYTEST_ADDOPTS")}
    merged["PYTHON_BIN"] = sys.executable
    if junit_dir is not None:
        merged["CI_JUNIT_DIR"] = str(junit_dir)
    merged.update(env)
    return subprocess.run(
        ["bash", "scripts/validate-all.sh"], cwd=repo, env=merged, text=True,
        capture_output=True, check=False, timeout=120,
    )


def _rows(junit_dir: Path) -> dict[str, tuple[str, ...]]:
    lines = (junit_dir / "manifest.tsv").read_text(encoding="utf-8").splitlines()[1:]
    return {fields[0]: tuple(fields[1:]) for fields in (line.split("\t") for line in lines)}


def _completeness(junit_dir: Path, suite: str = "root") -> tuple[str, ...]:
    return _rows(junit_dir)[f"test selection completeness: {suite}"]


def _control(cid, files, expected, *, drop=(), min_pytest=(0, 0)):
    skip = pytest.mark.skipif(PYTEST_VERSION < min_pytest, reason=f"needs pytest >= {min_pytest}")
    return pytest.param(files, drop, expected, id=cid, marks=skip)


CONTROLS = [
    _control("NC01-root-ini-deselect-3816",
             {"pytest.ini": "[pytest]\naddopts = -v --deselect tests/sub/test_guard.py::test_guard_regression\n"}, "INCOMPLETE"),
    _control("NC02-root-ini-collect-only",
             {"pytest.ini": "[pytest]\naddopts = -v --collect-only\n"}, "INCOMPLETE"),
    _control("NC03-tests-ini-python_files",
             {"tests/pytest.ini": "[pytest]\npython_files = test_a.py\n"}, "INCOMPLETE"),
    _control("NC04-tests-ini-collect-only",
             {"tests/pytest.ini": "[pytest]\naddopts = --collect-only\n"}, "INCOMPLETE"),
    _control("NC05-dot-pytest-ini",
             {".pytest.ini": "[pytest]\npython_files = test_a.py\n"}, "INCOMPLETE", drop=("pytest.ini",), min_pytest=(8, 1)),
    _control("NC06-pytest-toml",
             {"pytest.toml": '[pytest]\npython_files = ["test_a.py"]\n'}, "INCOMPLETE", drop=("pytest.ini",), min_pytest=(9, 0)),
    _control("NC07-pyproject-tool-pytest",
             {"pyproject.toml": '[tool.pytest]\npython_files = ["test_a.py"]\n'}, "INCOMPLETE", drop=("pytest.ini",), min_pytest=(9, 0)),
    _control("NC08-no-unittest-plugin",
             {"pytest.ini": "[pytest]\naddopts = -v -p no:unittest\n"}, "INCOMPLETE"),
    _control("NC10-root-ini-setup-only",
             {"pytest.ini": "[pytest]\naddopts = -v --setup-only\n"}, "REJECTED"),
    _control("NC11-tests-ini-setup-plan",
             {"tests/pytest.ini": "[pytest]\naddopts = --setup-plan\n"}, "REJECTED"),
    _control("NC12-ignore-hides-broken-module",
             {"tests/test_broken.py": BROKEN, "pytest.ini": "[pytest]\naddopts = -v --ignore=tests/test_broken.py\n"}, "ERROR"),
    _control("NC13-norecursedirs-hides-broken-module",
             {"tests/sub/test_broken.py": BROKEN, "tests/pytest.ini": "[pytest]\nnorecursedirs = sub\n"}, "ERROR"),
    _control("NC14-bundled-qk",
             {"pytest.ini": '[pytest]\naddopts = -qk "not guard_regression"\n'}, "INCOMPLETE"),
    _control("NC15-collect_imported_tests-false",
             {"tests/guards.py": PASSING.format("imported_guard"),
              "tests/test_main.py": "from tests.guards import test_imported_guard  # noqa: F401\n",
              "pytest.ini": "[pytest]\naddopts = -v\ncollect_imported_tests = false\n"}, "INCOMPLETE"),
    _control("NC16-omitted-param-not-masked-by-regenerated-sibling",
             {"tests/test_regen.py": (
                 "import secrets\n\nimport pytest\n\n\n"
                 "@pytest.mark.parametrize('value', [secrets.token_urlsafe(8), 'fixed'])\n"
                 "def test_mixed(value):\n    assert value\n"),
              "pytest.ini": "[pytest]\naddopts = -v --deselect tests/test_regen.py::test_mixed[fixed]\n"}, "INCOMPLETE"),
]


@pytest.mark.parametrize(("files", "drop", "expected"), CONTROLS)
def test_configuration_narrowing_cannot_pass(
    tmp_path: Path, files: dict[str, str], drop: tuple[str, ...], expected: str
) -> None:
    junit_dir = tmp_path / "junit"
    result = _run(_repo(tmp_path, files, drop=drop), junit_dir)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "OVERALL STATUS\nFAIL" in output
    rows = _rows(junit_dir)
    if expected == "REJECTED":
        # pytest itself refuses the option: the suite never executes and never reads EXECUTED_PASS.
        assert "unrecognized arguments" in output
        assert rows["root"][2:5] == ("FAIL", "4", "NOT_EXECUTED_SETUP_FAILURE")
        assert "test selection completeness: root" not in rows
        return
    assert rows["root"][4] == "EXECUTED_PASS"  # the suite passed on what it ran; the gate is the completeness row
    row = _completeness(junit_dir)
    classification = {"INCOMPLETE": "TEST_SELECTION_INCOMPLETE", "ERROR": "TEST_COLLECTION_ERROR"}[expected]
    assert row[2:5] == ("FAIL", "1" if expected == "INCOMPLETE" else "2", classification)
    receipt = json.loads((junit_dir / "test-completeness-root.json").read_text(encoding="utf-8"))
    assert receipt["verdict"] == expected
    assert (receipt["missing_count"] > 0) == (expected == "INCOMPLETE")


@pytest.mark.parametrize("extra", [{}, LEGIT])
def test_legitimate_suites_pass_complete(tmp_path: Path, extra: dict[str, str]) -> None:
    """Skip, xfail, module skip, regenerated params, odd ids, subtests and pytest's
    default-excluded directories are not omissions."""
    junit_dir = tmp_path / "junit"
    result = _run(_repo(tmp_path, extra), junit_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _completeness(junit_dir)[2:5] == ("PASS", "0", "COMPLETE")
    receipt = json.loads((junit_dir / "test-completeness-root.json").read_text(encoding="utf-8"))
    assert receipt["verdict"] == "COMPLETE" and receipt["missing"] == []
    assert receipt["regenerated_param_count"] == (1 if extra else 0)


def test_registry_fixture_exclusion_is_allowlisted_by_suite_name(tmp_path: Path) -> None:
    junit_dir = tmp_path / "junit"
    suites = {f"{REGISTRY}/{rel}": content for rel, content in FIXTURE_SUITE.items()}
    result = _run(_repo(tmp_path, suites), junit_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _completeness(junit_dir, REGISTRY)[2:5] == ("PASS", "0", "COMPLETE")


def test_same_exclusion_in_any_other_suite_is_an_omission(tmp_path: Path) -> None:
    junit_dir = tmp_path / "junit"
    suites = {f"08_Tooling/other/{rel}": content for rel, content in FIXTURE_SUITE.items()}
    result = _run(_repo(tmp_path, suites), junit_dir)
    assert result.returncode == 1, result.stdout + result.stderr
    assert _completeness(junit_dir, "08_Tooling/other")[2:5] == ("FAIL", "1", "TEST_SELECTION_INCOMPLETE")


@pytest.mark.xfail(strict=True, reason="documented boundary: conftest.py manipulation is not detected")
def test_conftest_collect_ignore_is_a_documented_gap(tmp_path: Path) -> None:
    """conftest.py narrows the reference and the real run identically. Strict xfail:
    if this starts failing, the boundary moved and the docs/claims must be updated."""
    files = {"tests/conftest.py": "collect_ignore = ['sub', 'test_ut.py']\n"}
    result = _run(_repo(tmp_path, files), tmp_path / "junit")
    assert result.returncode == 1, result.stdout + result.stderr


def test_default_local_run_is_checked_without_publishing_junit(tmp_path: Path) -> None:
    """No CI_JUNIT_DIR: the narrowing is still caught, nothing is published, and the
    private JUnit path is not shown in the command text."""
    files = {"pytest.ini": "[pytest]\naddopts = -v --deselect tests/sub/test_guard.py::test_guard_regression\n"}
    repo = _repo(tmp_path, files)
    result = _run(repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAIL | test selection completeness: root" in result.stdout
    assert "--junitxml=" not in result.stdout
    assert not (tmp_path / "junit").exists()


def test_pytest_addopts_env_is_unset_before_suites_run(tmp_path: Path) -> None:
    """PYTEST_ADDOPTS would narrow the reference and the real run identically, so the
    runner unsets it: the suite runs in full and reconciles COMPLETE."""
    junit_dir = tmp_path / "junit"
    result = _run(_repo(tmp_path, {}), junit_dir, PYTEST_ADDOPTS="--deselect tests/test_a.py::test_a1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PYTEST_ADDOPTS is set" in result.stderr
    assert 'name="test_a1"' in (junit_dir / "root.xml").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("helper", "code", "classification"),
    [
        ("import sys\nsys.exit(3)\n", "3", "TEST_COLLECTION_ERROR"),
        # An uncaught exception also exits 1, but without this attempt's INCOMPLETE receipt.
        ("raise RuntimeError('unhandled helper exception')\n", "1", "TEST_COLLECTION_ERROR"),
        ("raise SystemExit(0)\n", "2", "TEST_COLLECTION_ERROR"),  # success without a COMPLETE receipt
    ],
    ids=["crash-exit-3", "uncaught-exception-exit-1", "success-without-receipt"],
)
def test_helper_failures_fail_closed_and_ignore_stale_receipts(
    tmp_path: Path, helper: str, code: str, classification: str
) -> None:
    repo = _repo(tmp_path, {})
    (repo / "scripts" / "agent_os_ci_test_completeness.py").write_text(helper, encoding="utf-8")
    junit_dir = tmp_path / "junit"
    junit_dir.mkdir()
    (junit_dir / "test-completeness-root.json").write_text('{"verdict": "INCOMPLETE"}', encoding="utf-8")
    result = _run(repo, junit_dir)
    assert result.returncode == 1, result.stdout + result.stderr
    row = _completeness(junit_dir)
    assert row[2:5] == ("FAIL", code, classification)
    assert row[1] == "no"  # the stale receipt was cleared, never reused as evidence


# --- NC09 JUnit outcome oracle ------------------------------------------------

# check_suite imports agent_os_ci_junit_diff as a top-level module (the
# script runs with scripts/ on sys.path); direct unit tests do the same.
@pytest.fixture
def _scripts_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))


def _direct_suite(tmp_path: Path) -> Path:
    """A minimal real suite dir whose reference collection yields two tests."""
    suite = tmp_path / "suite"
    (suite / "tests").mkdir(parents=True)
    (suite / "tests" / "test_a.py").write_text(
        "def test_a1():\n    assert True\n\n\ndef test_a2():\n    assert True\n", encoding="utf-8"
    )
    return suite


def _direct_junit(tmp_path: Path, *, failing: str | None = None, erroring: str | None = None) -> Path:
    def case(name: str) -> str:
        if name == failing:
            return f'<testcase classname="tests.test_a" name="{name}"><failure message="boom"/></testcase>'
        if name == erroring:
            return f'<testcase classname="tests.test_a" name="{name}"><error message="crash"/></testcase>'
        return f'<testcase classname="tests.test_a" name="{name}"/>'

    failures = 1 if failing else 0
    errors = 1 if erroring else 0
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="2" '
        f'failures="{failures}" errors="{errors}" skipped="0">'
        + case("test_a1") + case("test_a2") + "</testsuite></testsuites>",
        encoding="utf-8",
    )
    return junit


def test_junit_failure_vetoes_pass_despite_executed_identity(tmp_path: Path, _scripts_on_path) -> None:
    """NC09, direct: the reference tests are all present as <testcase> nodes,
    so identity alone would say COMPLETE; one <failure> child must veto it."""
    from scripts.agent_os_ci_test_completeness import check_suite

    suite = _direct_suite(tmp_path)
    result = check_suite(sys.executable, suite, "root", _direct_junit(tmp_path, failing="test_a2"))
    assert result["verdict"] == "OUTCOME_FAILED"
    assert result["outcome"]["failures"] == 1
    assert result["outcome"]["failed_nodes"] == ["tests.test_a::test_a2"]
    assert result["missing_count"] == 0  # identity is complete; the outcome is the veto


def test_junit_error_vetoes_pass_and_clean_report_stays_complete(tmp_path: Path, _scripts_on_path) -> None:
    from scripts.agent_os_ci_test_completeness import check_suite

    suite = _direct_suite(tmp_path)
    result = check_suite(sys.executable, suite, "root", _direct_junit(tmp_path, erroring="test_a1"))
    assert result["verdict"] == "OUTCOME_FAILED"
    assert result["outcome"]["errors"] == 1
    clean = check_suite(sys.executable, suite, "root", _direct_junit(tmp_path))
    assert clean["verdict"] == "COMPLETE"
    assert clean["outcome"] == {
        "schema": "agent-os-ci-junit-outcome/1",
        "tests": 2, "failures": 0, "errors": 0, "skipped": 0,
        "failed_count": 0, "failed_nodes": [],
    }


def test_contradictory_junit_outcome_fails_closed(tmp_path: Path, _scripts_on_path) -> None:
    """A <failure> child the suite attributes deny is inconsistent evidence:
    ERROR, never a pass and never a silent INCOMPLETE."""
    from scripts.agent_os_ci_test_completeness import check_suite

    suite = _direct_suite(tmp_path)
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="2" '
        'failures="0" errors="0" skipped="0">'
        '<testcase classname="tests.test_a" name="test_a1"/>'
        '<testcase classname="tests.test_a" name="test_a2"><failure message="boom"/></testcase>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    result = check_suite(sys.executable, suite, "root", junit)
    assert result["verdict"] == "ERROR"
    assert "junit-outcome-count-mismatch" in result["error"]


def _swallow_root_exit(repo: Path) -> None:
    """Replay the exact NC09 runner defect in the fixture copy only: force
    the root suite's recorded exit code to 0 when pytest failed."""
    runner = repo / "scripts" / "validate-all.sh"
    text = runner.read_text(encoding="utf-8")
    snippet = '  (cd "$workdir" && "$@")\n  local code=$?\n'
    assert text.count(snippet) == 1
    runner.write_text(
        text.replace(
            snippet,
            snippet
            + '  if [ "$name" = "root" ] && [ "$code" -ne 0 ]; then\n'
            '    echo "NC09 replay: swallowing root pytest exit $code" >&2\n'
            "    code=0\n"
            "  fi\n",
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("swallow", [True, False], ids=["swallowed-exit", "honest-exit"])
def test_nc09_swallowed_root_exit_cannot_pass(tmp_path: Path, swallow: bool) -> None:
    """Hosted NC09 replayed locally: one failing root test plus (when
    ``swallow``) the injected runner defect that forced the root exit to 0.
    Pre-fix the swallowed run escaped as overall PASS with EXECUTED_PASS /
    COMPLETE; with the outcome oracle it must fail, and the manifest must
    never record the failed suite as EXECUTED_PASS. Without the swallow the
    ordinary failing-suite path (EXECUTED_FAIL, no completeness row) is
    preserved."""
    junit_dir = tmp_path / "junit"
    repo = _repo(tmp_path, {"tests/test_failing.py": "def test_failing():\n    assert False\n"})
    if swallow:
        _swallow_root_exit(repo)
    result = _run(repo, junit_dir)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "OVERALL STATUS\nFAIL" in output
    rows = _rows(junit_dir)
    if swallow:
        assert rows["root"][2:5] == ("FAIL", "0", "TEST_OUTCOME_FAILED")
        assert _completeness(junit_dir)[2:5] == ("FAIL", "1", "TEST_OUTCOME_FAILED")
        receipt = json.loads((junit_dir / "test-completeness-root.json").read_text(encoding="utf-8"))
        assert receipt["verdict"] == "OUTCOME_FAILED"
        assert receipt["outcome"]["failures"] == 1
        assert receipt["outcome"]["failed_nodes"] == ["tests.test_failing::test_failing"]
        # No row anywhere in the published manifest may claim a pass for it.
        assert "EXECUTED_PASS" not in (junit_dir / "manifest.tsv").read_text(encoding="utf-8")
    else:
        assert rows["root"][2:5] == ("FAIL", "1", "EXECUTED_FAIL")
        assert "test selection completeness: root" not in rows


@pytest.mark.parametrize("outcome", [
    '<error>suite error</error>',
    '<wrapper><failure/></wrapper>',
])
def test_nonstandard_outcomes_never_certify_complete(tmp_path: Path, _scripts_on_path, outcome: str) -> None:
    from scripts.agent_os_ci_test_completeness import check_suite

    suite = _direct_suite(tmp_path)
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuite tests="2">'
        '<testcase classname="tests.test_a" name="test_a1"/>'
        '<testcase classname="tests.test_a" name="test_a2"/>'
        f'{outcome}</testsuite>', encoding="utf-8",
    )
    result = check_suite(sys.executable, suite, "root", junit)
    assert result["verdict"] == "ERROR"
    assert "junit-unsupported-outcome-placement" in result["error"]
