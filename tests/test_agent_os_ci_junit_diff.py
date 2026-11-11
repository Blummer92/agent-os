from __future__ import annotations

import subprocess
import sys
from xml.etree import ElementTree as ET

import pytest

from scripts.agent_os_ci_junit_diff import diff_junit, junit_outcomes, node_ids


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


# --- NC09 JUnit outcome oracle ------------------------------------------------

def _outcome_xml(cases: str, *, tests: int, failures: int, errors: int, skipped: int) -> bytes:
    return (
        '<?xml version="1.0"?><testsuites><testsuite name="pytest" '
        f'tests="{tests}" failures="{failures}" errors="{errors}" skipped="{skipped}">{cases}'
        "</testsuite></testsuites>"
    ).encode()


def test_outcome_oracle_counts_failures_errors_and_skips() -> None:
    xml = _outcome_xml(
        '<testcase classname="m" name="ok"/>'
        '<testcase classname="m" name="bad"><failure message="boom"/></testcase>'
        '<testcase classname="m" name="err"><error message="crash"/></testcase>'
        '<testcase classname="m" name="skip"><skipped message="env"/></testcase>',
        tests=4, failures=1, errors=1, skipped=1,
    )
    out = junit_outcomes(xml)
    assert (out["tests"], out["failures"], out["errors"], out["skipped"]) == (4, 1, 1, 1)
    assert out["failed_nodes"] == ["m::bad", "m::err"]
    # Identity semantics are untouched: the same report still yields its nodes.
    assert node_ids(xml) == {"m::ok", "m::bad", "m::err", "m::skip"}


def test_outcome_oracle_passes_clean_and_skip_only_reports() -> None:
    xml = _outcome_xml(
        '<testcase classname="m" name="ok"/>'
        '<testcase classname="m" name="skip"><skipped message="env"/></testcase>',
        tests=2, failures=0, errors=0, skipped=1,
    )
    out = junit_outcomes(xml)
    assert (out["failures"], out["errors"], out["skipped"]) == (0, 0, 1)
    assert out["failed_nodes"] == []


def test_outcome_oracle_rejects_contradictory_counters() -> None:
    # Attribute claims no failures but a <failure> child is present: the
    # report contradicts itself, so it fails closed instead of passing.
    xml = _outcome_xml(
        '<testcase classname="m" name="bad"><failure message="boom"/></testcase>',
        tests=1, failures=0, errors=0, skipped=0,
    )
    with pytest.raises(ValueError, match="junit-outcome-count-mismatch"):
        junit_outcomes(xml)
    # And the reverse: attribute claims a failure no child evidences.
    xml = _outcome_xml('<testcase classname="m" name="ok"/>', tests=1, failures=1, errors=0, skipped=0)
    with pytest.raises(ValueError, match="junit-outcome-count-mismatch"):
        junit_outcomes(xml)


def test_outcome_oracle_rejects_empty_and_malformed_reports() -> None:
    for bad in (
        b"",
        b"<not-xml",
        b'<?xml version="1.0"?><weird><testcase classname="m" name="t"/></weird>',
    ):
        with pytest.raises(ValueError):
            junit_outcomes(bad)


def test_outcome_oracle_zero_case_report_counts_zero_and_never_vetoes() -> None:
    # A --collect-only report has no <testcase>: no failure to veto, and the
    # completeness check (not this oracle) reports it INCOMPLETE.
    out = junit_outcomes(_outcome_xml("", tests=0, failures=0, errors=0, skipped=0))
    assert (out["tests"], out["failures"], out["errors"], out["skipped"]) == (0, 0, 0, 0)


def test_outcome_oracle_tolerates_missing_counters_and_subtest_tests_attribute() -> None:
    # Counters absent: children alone decide. tests attribute above the
    # element count (pytest 9 subtests) is legitimate and not reconciled.
    xml = (
        b'<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="3">'
        b'<testcase classname="m" name="t"/></testsuite></testsuites>'
    )
    out = junit_outcomes(xml)
    assert (out["tests"], out["failures"], out["errors"], out["skipped"]) == (1, 0, 0, 0)
    # Nested <testsuites> shape, as pytest writes it.
    xml = _outcome_xml(
        '<testcase classname="m" name="bad"><failure message="boom"/></testcase>',
        tests=1, failures=1, errors=0, skipped=0,
    )
    assert junit_outcomes(xml)["failed_nodes"] == ["m::bad"]


@pytest.mark.parametrize("cases", ["", '<testcase classname="m" name="t"/>'])
def test_outcome_oracle_requires_tests_attribute_even_for_empty_suite(cases: str) -> None:
    """QA #5821733152: a missing tests count cannot certify an empty report."""
    xml = (
        '<testsuites><testsuite name="pytest" failures="0" errors="0" skipped="0">'
        f'{cases}</testsuite></testsuites>'
    ).encode()
    with pytest.raises(ValueError, match="junit-missing-or-invalid-tests-count"):
        junit_outcomes(xml)
    # The identity reader already denied this input; preserve that contract.
    with pytest.raises(ValueError, match="testcase-count-mismatch"):
        node_ids(xml)


def test_outcome_oracle_rejects_negative_tests_counter() -> None:
    xml = b'<testsuite name="pytest" tests="-1" failures="0" errors="0" skipped="0"/>'
    with pytest.raises(ValueError, match="junit-missing-or-invalid-tests-count"):
        junit_outcomes(xml)


@pytest.mark.parametrize("body", [
    '<testcase classname="m" name="t"><wrapper><failure/></wrapper></testcase>',
    '<testcase classname="m" name="t"><n:failure xmlns:n="urn:custom"/></testcase>',
    '<testcase classname="m" name="t"><n:error xmlns:n="urn:custom"/></testcase>',
    '<testcase classname="m" name="t"/><error>suite error</error>',
    '<testcase classname="m" name="t"><wrapper><skipped/></wrapper></testcase>',
    '<testcase classname="m" name="t"/><testsuite tests="1"><testcase name="hidden"><failure/></testcase></testsuite>',
    '<wrapper><testcase classname="m" name="hidden"/></wrapper>',
])
def test_outcome_oracle_rejects_unsupported_element_placement(body: str) -> None:
    # Missing optional counters must not turn unsupported outcomes into zero.
    xml = f'<testsuite tests="1">{body}</testsuite>'.encode()
    with pytest.raises(ValueError, match="junit-unsupported-"):
        junit_outcomes(xml)


@pytest.mark.parametrize(
    ("root_attributes", "reason"),
    [
        ('failures="1"', "junit-outcome-count-mismatch"),
        ('errors="1"', "junit-outcome-count-mismatch"),
        ('skipped="1"', "junit-outcome-count-mismatch"),
        ('tests="2"', "junit-outcome-count-mismatch"),
        ('failures="-1"', "junit-outcome-count-mismatch"),
        ('errors="not-an-int"', "junit-invalid-errors-attribute"),
    ],
)
def test_outcome_oracle_rejects_contradictory_root_counters(
    root_attributes: str, reason: str
) -> None:
    """Aggregate attributes cannot contradict clean child suite evidence."""
    xml = (
        f'<testsuites {root_attributes}><testsuite tests="1" '
        'failures="0" errors="0" skipped="0">'
        '<testcase classname="m" name="ok"/></testsuite></testsuites>'
    ).encode()
    with pytest.raises(ValueError, match=reason):
        junit_outcomes(xml)


def test_outcome_oracle_accepts_consistent_multi_suite_root_counters() -> None:
    """Root tests count declared subtests, not just testcase elements."""
    xml = (
        '<testsuites tests="4" failures="1" errors="0" skipped="1">'
        '<testsuite tests="3" failures="1" errors="0" skipped="0">'
        '<testcase classname="m" name="bad"><failure/></testcase></testsuite>'
        '<testsuite tests="1" failures="0" errors="0" skipped="1">'
        '<testcase classname="m" name="skip"><skipped/></testcase></testsuite>'
        '</testsuites>'
    ).encode()
    out = junit_outcomes(xml)
    assert (out["tests"], out["failures"], out["errors"], out["skipped"]) == (2, 1, 0, 1)
    assert out["failed_nodes"] == ["m::bad"]
