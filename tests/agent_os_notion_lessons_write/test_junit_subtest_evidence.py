"""Focused CI must receive a JUnit testcase for every executed pytest subtest.

The first PR #4099 hosted report had 157 testcase nodes but claimed 295 tests:
138 unittest subtests were collapsed into their parent case nodes.  Never fix
this by relaxing the strict JUnit count and failure checks in the CI runner.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest


def _source_conftest() -> str:
    """Load the canonical sibling fixture or give a useful failure if moved."""
    source = Path(__file__).resolve().parent / "conftest.py"
    if not source.is_file():
        pytest.fail(f"Canonical subtest conftest fixture missing: {source}", pytrace=False)
    return source.read_text(encoding="utf-8")


@pytest.mark.parametrize("failing", [False, True])
def test_unittest_subtests_emit_distinct_case_evidence(tmp_path: Path, failing: bool) -> None:
    # JUnit is finalized at pytest session end; a subprocess verifies real output.
    (tmp_path / "conftest.py").write_text(
        _source_conftest(),
        encoding="utf-8",
    )
    assertion = "self.assertLess(value, 2)" if failing else "self.assertLess(value, 3)"
    (tmp_path / "test_nested.py").write_text(
        "import unittest\n"
        "class Nested(unittest.TestCase):\n"
        "    def test_all_branches(self):\n"
        "        for value in range(3):\n"
        "            with self.subTest(value=value):\n"
        f"                {assertion}\n",
        encoding="utf-8",
    )
    report = tmp_path / "nested.xml"
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_nested.py", f"--junitxml={report}"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert (completed.returncode != 0) is failing, completed.stdout + completed.stderr
    root = ET.parse(report).getroot()
    suites = list(root)
    assert root.tag == "testsuites" and len(suites) == 1
    suite = suites[0]
    cases = suite.findall("testcase")
    # A success with silently collapsed subtests is invalid test evidence.
    assert int(suite.attrib["tests"]) == len(cases) == 4
    assert len({(case.get("classname"), case.get("name")) for case in cases}) == 4
    assert int(suite.attrib["failures"]) == (1 if failing else 0)
    assert int(suite.attrib["errors"]) == 0
    assert int(suite.attrib["skipped"]) == 0
    assert sum(bool(case.findall("failure")) for case in cases) == (1 if failing else 0)


def test_conftest_import_priority_is_stable_with_preexisting_pythonpath(tmp_path: Path) -> None:
    """Subprocess collection must prefer CKR2, then repo src, then scheduler."""
    nested = tmp_path / "tests" / "agent_os_notion_lessons_write"
    nested.mkdir(parents=True)
    (nested / "conftest.py").write_text(
        _source_conftest(),
        encoding="utf-8",
    )
    paths = [
        tmp_path / "08_Tooling" / "agent-memory-context-manager" / "src",
        tmp_path / "src",
        tmp_path / "08_Tooling" / "workflow-scheduler" / "src",
    ]
    for location, origin in zip(paths, ("memory", "repo", "scheduler")):
        location.mkdir(parents=True)
        (location / "agent_os_path_priority_probe.py").write_text(
            f"ORIGIN = {origin!r}\n", encoding="utf-8"
        )
    (nested / "test_import_priority.py").write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "import agent_os_path_priority_probe as probe\n"
        "def test_canonical_path_priority():\n"
        "    root = Path(__file__).resolve().parents[2]\n"
        "    expected = (root / '08_Tooling' / 'agent-memory-context-manager' / 'src',\n"
        "                root / 'src',\n"
        "                root / '08_Tooling' / 'workflow-scheduler' / 'src')\n"
        "    positions = [sys.path.index(str(p)) for p in expected]\n"
        "    assert positions == sorted(positions)\n"
        "    assert all(sys.path.count(str(p)) == 1 for p in expected)\n"
        "    assert probe.ORIGIN == 'memory'\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    # Deliberately invert the initial priority to exercise reordering.
    env["PYTHONPATH"] = os.pathsep.join(str(p) for p in reversed(paths))
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q",
         "tests/agent_os_notion_lessons_write/test_import_priority.py"],
        cwd=tmp_path, env=env, text=True, capture_output=True,
        check=False, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_subtest_report_hook_only_changes_call_phase(tmp_path: Path) -> None:
    """Even if future pytest emits phase-bearing reports, do not split identities."""
    (tmp_path / "conftest.py").write_text(
        _source_conftest(),
        encoding="utf-8",
    )
    (tmp_path / "test_phase.py").write_text(
        "import pytest\n"
        "import conftest\n"
        "def test_subtest_phase_identity():\n"
        "    if conftest.SubtestReport is None:\n"
        "        pytest.skip('subtest report implementation unavailable')\n"
        "    report = object.__new__(conftest.SubtestReport)\n"
        "    report.nodeid = 'phase-test::case'\n"
        "    report.when = 'setup'\n"
        "    conftest.pytest_runtest_logreport(report)\n"
        "    assert report.nodeid == 'phase-test::case'\n"
        "    report.when = 'teardown'\n"
        "    conftest.pytest_runtest_logreport(report)\n"
        "    assert report.nodeid == 'phase-test::case'\n"
        "    report.when = 'call'\n"
        "    conftest.pytest_runtest_logreport(report)\n"
        "    assert report.nodeid == 'phase-test::case::subtest[1]'\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_phase.py"],
        cwd=tmp_path, env=env, text=True, capture_output=True,
        check=False, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
