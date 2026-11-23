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


@pytest.mark.parametrize("failing", [False, True])
def test_unittest_subtests_emit_distinct_case_evidence(tmp_path: Path, failing: bool) -> None:
    # JUnit is finalized at pytest session end; a subprocess verifies real output.
    (tmp_path / "conftest.py").write_text(
        Path(__file__).with_name("conftest.py").read_text(encoding="utf-8"),
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
