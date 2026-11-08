from __future__ import annotations

import subprocess
import sys
from xml.etree import ElementTree as ET

import pytest

from scripts.agent_os_ci_junit_diff import diff_junit, node_ids


def _xml(nodes: list[tuple[str, str]]) -> bytes:
    cases = "".join(f'<testcase classname="{c}" name="{n}"/>' for c, n in nodes)
    return (
        f'<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="{len(nodes)}" '
        f'failures="0" errors="0" skipped="0">{cases}</testsuite></testsuites>'
    ).encode()


def test_mapped_replacement_is_machine_verified() -> None:
    out = diff_junit(
        _xml([("m", "old"), ("m", "kept")]),
        _xml([("m", "new"), ("m", "kept")]),
        {"m::old": ["m::new"]},
    )
    assert out["removed"] == ["m::old"]
    assert out["mapped_removed_ids"] == ["m::old"]
    assert out["unmapped_removed_ids"] == []
    assert out["verdict"] == "COMPLETE_WITH_MAPPING"


def test_unmapped_removed_is_incomplete() -> None:
    out = diff_junit(_xml([("m", "old"), ("m", "kept")]), _xml([("m", "kept")]))
    assert out["unmapped_removed_ids"] == ["m::old"]
    assert out["verdict"] == "INCOMPLETE"


def test_phantom_replacement_does_not_map() -> None:
    out = diff_junit(
        _xml([("m", "old")]),
        _xml([("m", "other")]),
        {"m::old": ["m::phantom"]},
    )
    assert out["mapped_removed_ids"] == []
    assert out["unmapped_removed_ids"] == ["m::old"]
    assert out["verdict"] == "INCOMPLETE"


def test_duplicate_nodes_and_count_mismatch_are_rejected() -> None:
    with pytest.raises(ValueError):
        diff_junit(_xml([("m", "t"), ("m", "t")]), _xml([("m", "t")]))
    # --setup-only/--setup-plan: passing-looking elements, tests="0".
    bad = b'<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="0" failures="0" errors="0" skipped="0"><testcase classname="m" name="t"/></testsuite></testsuites>'
    with pytest.raises(ValueError, match="testcase-count-mismatch"):
        diff_junit(bad, _xml([("m", "t")]))


def test_pytest9_subtests_raise_tests_attribute_without_extra_elements(tmp_path) -> None:
    """Real pytest 9 output: unittest subTests are counted in ``tests`` but
    are not <testcase> elements, so the attribute may exceed the elements."""
    subtests = tmp_path / "test_sub.py"
    subtests.write_text(
        "import unittest\n"
        "class T(unittest.TestCase):\n"
        "    def test_sub(self):\n"
        "        for i in range(3):\n"
        "            with self.subTest(i=i):\n"
        "                self.assertTrue(True)\n",
        encoding="utf-8",
    )
    report = tmp_path / "junit.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", str(subtests), "-q", "-p", "no:cacheprovider", f"--junitxml={report}"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    suite = ET.parse(report).getroot().find("testsuite")
    assert len(suite.findall("testcase")) == 1
    if int(suite.attrib["tests"]) == 1:
        pytest.skip("this pytest does not count subtests in the tests attribute")
    assert node_ids(report.read_bytes()) == {"test_sub.T::test_sub"}
