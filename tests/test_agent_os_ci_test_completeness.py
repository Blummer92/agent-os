"""Real-pytest negative controls for the executed-vs-reference completeness check.

Regression for the #3816 false green (PR #3817): the authoritative aggregate
passed while tests excluded by configuration never executed. Every control here
runs the real ``scripts/validate-all.sh`` with real pytest against a small
fixture repository. The fixture tests all *pass* when executed, so a red result
can only come from the completeness check (or pytest rejecting the option),
never from a test body failing.

Proven boundary is configuration, plus conftest collection influence via
the independent (--noconftest) reference collection: a ``collect_ignore`` or
``pytest_collection_modifyitems`` hook that narrows collection identically
for the reference and the real run is caught as a reference disagreement.
NOT covered: a candidate that edits this check (or its runner) itself; this
is not CI trust certification.
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


def test_conftest_collect_ignore_is_caught(tmp_path: Path) -> None:
    """NC08 repair: conftest.py narrows the reference and the real run
    identically, so the check compares the reference against a second,
    conftest-free (--noconftest) collection and fails closed on disagreement."""
    files = {"tests/conftest.py": "collect_ignore = ['sub', 'test_ut.py']\n"}
    junit_dir = tmp_path / "junit"
    result = _run(_repo(tmp_path, files), junit_dir)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "OVERALL STATUS\nFAIL" in output
    row = _completeness(junit_dir)
    assert row[2:5] == ("FAIL", "2", "TEST_COLLECTION_ERROR")
    receipt = json.loads((junit_dir / "test-completeness-root.json").read_text(encoding="utf-8"))
    assert receipt["verdict"] == "ERROR"
    assert "reference collections disagree" in receipt["error"]
    assert sorted(receipt["reference_noconftest_only"]) == [
        "tests/sub/test_guard.py::test_guard_regression",
        "tests/test_ut.py::T::test_ut_regression",
    ]
    assert receipt["reference_only"] == []


def test_conftest_modifyitems_drop_is_caught(tmp_path: Path) -> None:
    """NC08 hosted escape, replayed locally: the exact defect — a
    pytest_collection_modifyitems hook dropping one mandatory test from both
    collections. The independent reference still collects it, so the check
    fails closed instead of passing."""
    files = {
        "tests/conftest.py": (
            "def pytest_collection_modifyitems(config, items):\n"
            "    items[:] = [i for i in items if i.nodeid != "
            "'tests/sub/test_guard.py::test_guard_regression']\n"
        ),
    }
    junit_dir = tmp_path / "junit"
    result = _run(_repo(tmp_path, files), junit_dir)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    row = _completeness(junit_dir)
    assert row[2:5] == ("FAIL", "2", "TEST_COLLECTION_ERROR")
    receipt = json.loads((junit_dir / "test-completeness-root.json").read_text(encoding="utf-8"))
    assert receipt["verdict"] == "ERROR"
    assert receipt["reference_noconftest_only"] == [
        "tests/sub/test_guard.py::test_guard_regression"
    ]
    assert receipt["reference_only"] == []


def test_conftest_marker_only_passes_complete(tmp_path: Path) -> None:
    """A conftest that only adds markers (like the real root conftest) collects
    identically in both references: legitimate conftests are unaffected."""
    files = {
        "tests/conftest.py": (
            "import pytest\n\n\n"
            "def pytest_collection_modifyitems(config, items):\n"
            "    for item in items:\n"
            "        if 'unit' in str(item.fspath):\n"
            "            item.add_marker(pytest.mark.unit)\n"
        ),
        "pytest.ini": (
            "[pytest]\naddopts = -v --strict-markers\nmarkers =\n    unit: marks tests as unit tests\n"
        ),
    }
    junit_dir = tmp_path / "junit"
    result = _run(_repo(tmp_path, files), junit_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _completeness(junit_dir)[2:5] == ("PASS", "0", "COMPLETE")
    receipt = json.loads((junit_dir / "test-completeness-root.json").read_text(encoding="utf-8"))
    assert receipt["verdict"] == "COMPLETE"
    # On repaired code the dual collection ran and agreed; .get() keeps this
    # positive control green on unrepaired code too (its job is to prove the
    # repair does not break legitimate conftests, not to prove the repair).
    assert receipt.get("reference_noconftest_only", []) == []
    assert receipt.get("reference_only", []) == []


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
