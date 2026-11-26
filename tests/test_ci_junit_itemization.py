import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from scripts.agent_os_ci_evidence_health import validate_junit
from tests import junit_cases


def _junit(declared, rows):
    suite = ET.Element(
        "testsuite", name="root", tests=str(declared),
        failures="0", errors="0", skipped="0",
    )
    for index in range(rows):
        ET.SubElement(suite, "testcase", classname="fixture", name=f"case_{index:03}")
    return ET.tostring(suite, encoding="utf-8")


def test_224_counted_with_161_rows_is_rejected():
    with pytest.raises(ValueError, match="^testcase-count-mismatch$"):
        validate_junit(_junit(224, 161))


def test_224_counted_with_224_distinct_rows_is_accepted():
    node_ids, counts = validate_junit(_junit(224, 224))
    assert len(node_ids) == len(set(node_ids)) == counts["tests"] == 224
    assert counts["errors"] == counts["failures"] == counts["skipped"] == 0


def test_unittest_cases_emit_all_rows_including_a_failure(tmp_path):
    shutil.copy(junit_cases.__file__, tmp_path / "junit_cases.py")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_cases.py").write_text(
        "import unittest\n"
        "from junit_cases import collect_cases\n"
        "class TestRows(unittest.TestCase):\n"
        "    def setUp(self):\n"
        "        self.seen = []\n"
        "    def _check_row(self, value):\n"
        "        self.seen.append(value)\n"
        "        self.assertEqual(len(self.seen), 1)\n"
        "        self.assertNotEqual(value, 'fail')\n"
        "collect_cases(TestRows, TestRows._check_row, [('ok',), ('fail',), ('ok',)])\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.xml"
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_CURRENT_TEST"):
        env.pop(key, None)
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-c", "pytest.ini", "test_cases.py", f"--junitxml={report}"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 1, (run.stdout, run.stderr)
    data = report.read_bytes()
    ids, counts = validate_junit(data)
    assert len(ids) == counts["tests"] == 3
    assert counts["failures"] == 1 and counts["errors"] == counts["skipped"] == 0
    assert {
        case.get("name"): case.find("failure") is not None
        for case in ET.fromstring(data).iter("testcase")
    } == {"test_row_01": False, "test_row_02": True, "test_row_03": False}


def test_ckr4_harness_retains_standalone_unittest_entrypoint():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "tests/ckr4_harness/test_harness.py", "-q"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "Ran 10 tests" in result.stderr
