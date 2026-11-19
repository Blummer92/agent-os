"""D07 fail-first evidence-integrity probes for the focused Python runner.

No production code is modified. The probes intentionally require truthful
nonzero JUnit evidence even when a stubbed pytest child exits with status 0.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "d07_ci_executor_under_test", ROOT / "scripts/agent_os_ci_validation.py"
)
assert spec and spec.loader
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


@pytest.mark.parametrize(
    ("xml", "reason"),
    [
        (None, "missing-report"),
        (b"<testsuites><testsuite", "malformed-report"),
        (b'<testsuite tests="0" failures="0" errors="0" skipped="0"/>', "zero-tests"),
        (
            b'<testsuite tests="1" failures="0" errors="0" skipped="1">'
            b'<testcase name="skipped"><skipped/></testcase></testsuite>',
            "all-skipped",
        ),
    ],
)
def test_d07_zero_exit_never_proves_unexecuted_pytest_cases(tmp_path, xml, reason):
    report = tmp_path / "junit.xml"
    if xml is not None:
        report.write_bytes(xml)
    # This is the actual runner classification used in command receipts.
    assert ci._pytest_classification(0, report) != "EXECUTED_PASS", reason


def test_d07_nonzero_real_test_evidence_still_classifies_failure(tmp_path):
    report = tmp_path / "failed.xml"
    report.write_bytes(
        b'<testsuite tests="1" failures="1" errors="0" skipped="0">'
        b'<testcase name="fails"><failure/></testcase></testsuite>'
    )
    assert ci._pytest_classification(1, report) == "EXECUTED_FAIL"


def test_d07_nonzero_pass_receipt_has_case_counts(tmp_path):
    report = tmp_path / "passed.xml"
    report.write_bytes(
        b'<testsuite tests="1" failures="0" errors="0" skipped="0">'
        b'<testcase name="passes"/></testsuite>'
    )
    assert ci._pytest_classification(0, report) == "EXECUTED_PASS"
