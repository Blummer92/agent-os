"""False-green controls for the focused/manifest JUnit evidence validator."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent_os_ci_junit_validate.py"


@pytest.mark.parametrize(
    ("xml", "expected"),
    [
        ('<testsuite tests="1" failures="0" errors="0"><testcase classname="t" name="ok"/></testsuite>', 0),
        ('<testsuite tests="1" failures="1" errors="0"><testcase classname="t" name="bad"><failure/></testcase></testsuite>', 1),
        ('<testsuite tests="1" failures="0" errors="1"><testcase classname="t" name="bad"><error/></testcase></testsuite>', 1),
        ('<testsuite tests="1" failures="0" errors="0"><testcase classname="t" name="bad"><failure/></testcase></testsuite>', 2),
        ('<testsuite tests="0" failures="0" errors="0"></testsuite>', 2),
        ('<testsuite', 2),
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
