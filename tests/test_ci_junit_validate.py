"""False-green controls for the focused/manifest JUnit evidence validator."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent_os_ci_junit_validate.py"


def test_focused_runner_forwards_required_execution_flag():
    """The shell wrapper must forward the flag, not merely mention it at callsite."""
    source = (ROOT / "scripts" / "validate-all.sh").read_text(encoding="utf-8")
    assert '"$PYTHON_BIN" scripts/agent_os_ci_junit_validate.py "$@"' in source
    assert 'verify_junit "$focused_junit_path" --require-executed' in source
    assert '"$PYTHON_BIN" scripts/agent_os_ci_junit_validate.py "$1"' not in source


@pytest.mark.parametrize(
    ("xml", "expected"),
    [
        ('<testsuite tests="1" failures="0" errors="0"><testcase classname="t" name="ok"/></testsuite>', 0),
        ('<testsuite tests="1" failures="1" errors="0"><testcase classname="t" name="bad"><failure/></testcase></testsuite>', 1),
        ('<testsuite tests="1" failures="0" errors="1"><testcase classname="t" name="bad"><error/></testcase></testsuite>', 1),
        ('<testsuite tests="1" failures="0" errors="0"><testcase classname="t" name="bad"><failure/></testcase></testsuite>', 2),
        ('<testsuite tests="0" failures="0" errors="0"></testsuite>', 2),
        ('<testsuite', 2),
        ('<?xml version="1.0" encoding="BOGUS"?><testsuite tests="1"><testcase name="ok"/></testsuite>', 2),
        ('<testsuites><testsuite tests="1"><testcase name="ok"/></testsuite><testsuite tests="999"/></testsuites>', 2),
        ('<testsuite tests="1" skipped="2"><testcase name="skip"><skipped/><skipped/></testcase></testsuite>', 2),
        ('<testsuites><testsuite tests="1"><testcase name="ok"/></testsuite><testsuite tests="0"/></testsuites>', 0),
        ('<testsuite tests="4" skipped="0"><testcase name="parent"/></testsuite>', 0),
    ],
)
def test_junit_validator_never_admits_missing_failed_or_malformed_outcomes(tmp_path, xml, expected):
    report = tmp_path / "run.xml"
    report.write_text(xml, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(report)],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == expected
    assert completed.stdout == ""


def test_junit_validator_missing_file_fails_closed(tmp_path):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "missing.xml")],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 2


def test_focused_junit_requires_an_executed_body(tmp_path):
    report = tmp_path / "skipped.xml"
    report.write_text(
        '<testsuite tests="1" failures="0" errors="0" skipped="1">'
        '<testcase classname="t" name="skipped"><skipped/></testcase></testsuite>',
        encoding="utf-8",
    )
    normal = subprocess.run(
        [sys.executable, str(SCRIPT), str(report)],
        capture_output=True, check=False,
    )
    focused = subprocess.run(
        [sys.executable, str(SCRIPT), str(report), "--require-executed"],
        capture_output=True, check=False,
    )
    assert normal.returncode == 0  # Full suites retain their skip allowlist.
    assert focused.returncode == 2  # Explicit focus cannot be all skipped.


@pytest.mark.parametrize("mode, expected", [("pass", 0), ("fail", 1), ("partial-skip", 0)])
def test_genuine_unittest_subtest_reports_preserve_outcomes(tmp_path, mode, expected):
    """Subtest counters count events while execution evidence names bodies."""
    statement = {
        "pass": "self.assertTrue(True)",
        "fail": "self.assertNotEqual(i, 1)",
        "partial-skip": "self.skipTest('approved subtest') if i < 2 else self.assertTrue(True)",
    }[mode]
    source = tmp_path / "test_subtests.py"
    source.write_text(
        "import unittest\n"
        "class T(unittest.TestCase):\n"
        "    def test_plain(self):\n"
        "        self.assertTrue(True)\n"
        "    def test_sub(self):\n"
        "        for i in range(3):\n"
        "            with self.subTest(i=i):\n"
        f"                {statement}\n",
        encoding="utf-8",
    )
    report = tmp_path / "junit.xml"
    produced = subprocess.run(
        [sys.executable, "-m", "pytest", str(source), "-q", "-p", "no:cacheprovider", f"--junitxml={report}"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert produced.returncode == (1 if mode == "fail" else 0), produced.stdout + produced.stderr
    validated = subprocess.run(
        [sys.executable, str(SCRIPT), str(report), "--require-executed"],
        capture_output=True, text=True, check=False,
    )
    assert validated.returncode == expected, validated.stdout + validated.stderr

