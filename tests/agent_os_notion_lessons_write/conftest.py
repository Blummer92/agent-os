"""Use canonical source packages for the root pytest developer loop."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Centralized collection-time setup for the real CKR2/CKR11 source package.
MEMORY_SRC = ROOT / "08_Tooling" / "agent-memory-context-manager" / "src"
if str(MEMORY_SRC) not in sys.path:
    sys.path.insert(0, str(MEMORY_SRC))
for source in (ROOT / "src", ROOT / "08_Tooling/workflow-scheduler/src"):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))


# Pytest 9 reports unittest subtests in the JUnit suite's "tests" total,
# but its default JUnit reporter can collapse all subtests onto the parent's
# single <testcase>.  The focused CI gate correctly rejects that contradiction.
# Give *each executed subtest report* a distinct node identity before JUnit
# serialization. This preserves failures, skips and the strict count oracle;
# it does not synthesize tests or modify the production validation gate.
from collections import defaultdict

import pytest
from _pytest.subtests import SubtestReport


_SUBTEST_SEQUENCE = defaultdict(int)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report):
    if not isinstance(report, SubtestReport):
        return
    parent_nodeid = report.nodeid
    _SUBTEST_SEQUENCE[parent_nodeid] += 1
    report.nodeid = f"{parent_nodeid}::subtest[{_SUBTEST_SEQUENCE[parent_nodeid]}]"
