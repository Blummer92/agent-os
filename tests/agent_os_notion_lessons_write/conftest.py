"""Use canonical source packages for the root pytest developer loop."""
import sys
from pathlib import Path

# This conftest lives at <repo>/tests/agent_os_notion_lessons_write/.
ROOT = Path(__file__).resolve().parents[2]
# Explicit canonical import priority. Inserting in a loop at index 0 without
# reversing it would silently invert this order.
SOURCE_PATHS = (
    ROOT / "08_Tooling" / "agent-memory-context-manager" / "src",
    ROOT / "src",
    ROOT / "08_Tooling" / "workflow-scheduler" / "src",
)
for source in reversed(SOURCE_PATHS):
    if source.is_dir():
        entry = str(source)
        # Reposition existing PYTHONPATH entries for imports made AFTER
        # conftest loading. Already-imported sys.modules entries retain their
        # original origin; path reordering cannot retroactively replace them.
        sys.path[:] = [existing for existing in sys.path if existing != entry]
        sys.path.insert(0, entry)


# Pytest 9 reports unittest subtests in the JUnit suite's "tests" total,
# but its default JUnit reporter can collapse all subtests onto the parent's
# single <testcase>.  The focused CI gate correctly rejects that contradiction.
# Give *each executed subtest report* a distinct node identity before JUnit
# serialization. This preserves failures, skips and the strict count oracle;
# it does not synthesize tests or modify the production validation gate.
from collections import defaultdict

import pytest
# pytest >=9 provides native subtests. pytest 8 can supply the separate
# pytest-subtests plugin; without either implementation, no subtest report
# will be silently manufactured (the JUnit regression will fail closed).
try:
    from _pytest.subtests import SubtestReport
except ImportError:
    try:
        from pytest_subtests.plugin import SubTestReport as SubtestReport
    except ImportError:
        SubtestReport = None


_SUBTEST_SEQUENCE = defaultdict(int)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report):
    if SubtestReport is None or not isinstance(report, SubtestReport):
        return
    # Currently native/plugin subtests emit only call-phase reports. Guard
    # explicitly so future phase-bearing subtests cannot gain multiple IDs.
    if report.when != "call":
        return
    parent_nodeid = report.nodeid
    _SUBTEST_SEQUENCE[parent_nodeid] += 1
    report.nodeid = f"{parent_nodeid}::subtest[{_SUBTEST_SEQUENCE[parent_nodeid]}]"
