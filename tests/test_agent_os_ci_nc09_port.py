"""NC07 + NC09 regression probes for the bounded post-NC07 parser port."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.agent_os_ci_junit_diff import junit_outcomes, node_ids, skipped_node_ids


@pytest.fixture(autouse=True)
def _source_script_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    # Production completeness script imports sibling modules by unqualified name.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))


def check_suite(*args, **kwargs) -> dict:
    from scripts.agent_os_ci_test_completeness import check_suite as source_check_suite

    return source_check_suite(*args, **kwargs)


def report(body: str, *, tests: int = 2, failures: int = 0, errors: int = 0, skipped: int = 0) -> bytes:
    return (
        f'<testsuites><testsuite tests="{tests}" failures="{failures}" '
        f'errors="{errors}" skipped="{skipped}">{body}</testsuite></testsuites>'
    ).encode()


GOOD = '<testcase classname="tests.test_a" name="test_a1"/><testcase classname="tests.test_a" name="test_a2"/>'
FAIL = '<testcase classname="tests.test_a" name="test_a1"/><testcase classname="tests.test_a" name="test_a2"><failure/></testcase>'
ERROR = '<testcase classname="tests.test_a" name="test_a1"><error/></testcase><testcase classname="tests.test_a" name="test_a2"/>'
SKIP = '<testcase classname="tests.test_a" name="test_a1"><skipped/></testcase><testcase classname="tests.test_a" name="test_a2"/>'


def test_clean_is_not_vetoed() -> None:
    assert junit_outcomes(report(GOOD))["failed_nodes"] == []
    assert node_ids(report(GOOD)) == {"tests.test_a::test_a1", "tests.test_a::test_a2"}


def test_failure_and_error_are_detected_with_same_node_identity() -> None:
    for xml, key, target in (
        (report(FAIL, failures=1), "failures", "tests.test_a::test_a2"),
        (report(ERROR, errors=1), "errors", "tests.test_a::test_a1"),
    ):
        outcomes = junit_outcomes(xml)
        assert outcomes[key] == 1
        assert outcomes["failed_nodes"] == [target]
        assert len(node_ids(xml)) == 2


def test_nc07_skip_reader_preserved() -> None:
    xml = report(SKIP, skipped=1)
    assert skipped_node_ids(xml) == {"tests.test_a::test_a1"}
    assert junit_outcomes(xml)["skipped"] == 1
    assert junit_outcomes(xml)["failures"] == 0


@pytest.mark.parametrize("xml", [
    report(FAIL, failures=0),
    report(GOOD, failures=1),
    report(ERROR, errors=0),
    report(SKIP, skipped=0),
    report(FAIL, failures=1).replace(b'failures="1"', b'failures="nope"'),
    report(GOOD).replace(b'tests="2"', b'tests="0"'),
    b'<testsuites><testsuite tests="2"><testcase name="x"/><testcase name="x"/></testsuite></testsuites>',
    b'<bad/>',
    b'',
    b'<testsuites><testsuite><testcase></testsuite></testsuites>',
])
def test_contradictory_malformed_or_duplicate_junit_rejects(xml: bytes) -> None:
    with pytest.raises(ValueError):
        junit_outcomes(xml)


@pytest.mark.parametrize("body", [
    GOOD + '<failure/>',
    '<testcase classname="m" name="x"/><system-out><error/></system-out>',
    '<testcase classname="m" name="x"><system-out><failure/></system-out></testcase>',
    '<testcase classname="m" name="x"><testcase classname="m" name="y"/></testcase>',
    '<testsuite tests="1"><testcase classname="m" name="x"/></testsuite>',
    '<testcase classname="m" name="x"><ns:failure xmlns:ns="test"/></testcase>',
])
def test_unsupported_placement_rejects(body: str) -> None:
    with pytest.raises(ValueError):
        junit_outcomes(report(body, tests=2))


def test_pytest9_subtest_count_surplus_valid() -> None:
    xml = report('<testcase classname="m" name="t"/>', tests=4)
    assert junit_outcomes(xml)["tests"] == 1


def suite(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / 'suite'
    (root / 'tests').mkdir(parents=True)
    (root / 'tests' / 'test_a.py').write_text(
        'def test_a1():\n    assert True\n\ndef test_a2():\n    assert True\n'
    )
    allowlist = tmp_path / 'absent-allowlist.json'
    return root, allowlist


@pytest.mark.parametrize(('xml', 'verdict'), [
    (report(GOOD), 'COMPLETE'),
    (report(FAIL, failures=1), 'OUTCOME_FAILED'),
    (report(ERROR, errors=1), 'OUTCOME_FAILED'),
    (report(SKIP, skipped=1), 'INCOMPLETE'),
    (report(FAIL, failures=0), 'ERROR'),
])
def test_check_suite_verdict_composes_nc07_nc09(
    tmp_path: Path, xml: bytes, verdict: str
) -> None:
    root, allowlist = suite(tmp_path)
    path = tmp_path / 'junit.xml'
    path.write_bytes(xml)
    result = check_suite(sys.executable, root, 'root', path, skip_allowlist=allowlist)
    assert result['verdict'] == verdict, result
    if verdict == 'OUTCOME_FAILED':
        assert result['missing_count'] == 0
        assert sum(result['outcome'][x] for x in ('failures', 'errors')) == 1


def test_cli_failure_returncode_and_receipt(tmp_path: Path) -> None:
    root, allowlist = suite(tmp_path)
    path = tmp_path / 'junit.xml'
    path.write_bytes(report(FAIL, failures=1))
    receipt = tmp_path / 'receipt.json'
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'agent_os_ci_test_completeness.py'
    proc = subprocess.run([
        sys.executable, str(source), '--suite-dir', str(root), '--suite-name', 'root',
        '--junit', str(path), '--python-bin', sys.executable, '--receipt', str(receipt),
        '--skip-allowlist', str(allowlist),
    ], capture_output=True, text=True, check=False)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert json.loads(receipt.read_text())['verdict'] == 'OUTCOME_FAILED'


def test_real_pytest9_skip_xfail_subtest_report(tmp_path: Path) -> None:
    p = tmp_path / 'test_real_junit.py'
    p.write_text(
        'import unittest\nimport pytest\n'
        'def test_pass():\n    assert True\n'
        '@pytest.mark.skip(reason="baseline")\ndef test_skip():\n    assert False\n'
        '@pytest.mark.xfail(reason="baseline")\ndef test_xfail():\n    assert False\n'
        'class TestSubs(unittest.TestCase):\n'
        '    def test_parts(self):\n'
        '        for n in range(3):\n'
        '            with self.subTest(n=n):\n'
        '                self.assertGreaterEqual(n, 0)\n'
    )
    report_path = tmp_path / 'junit.xml'
    proc = subprocess.run([
        sys.executable, '-m', 'pytest', str(p), '-q', '-p', 'no:cacheprovider',
        f'--junitxml={report_path}',
    ], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = junit_outcomes(report_path.read_bytes())
    assert out['failures'] == 0 and out['errors'] == 0
    assert out['skipped'] == 2
    assert len(skipped_node_ids(report_path.read_bytes())) == 2


def test_allowlisted_skip_preserves_nc07_baseline(tmp_path: Path) -> None:
    root, allowlist = suite(tmp_path)
    allowlist.write_text(json.dumps({
        'schema': 'agent-os-ci-skipped-allowlist/1',
        'suites': {'root': ['tests.test_a::test_a1']},
    }))
    p = tmp_path / 'junit.xml'
    p.write_bytes(report(SKIP, skipped=1))
    result = check_suite(sys.executable, root, 'root', p, skip_allowlist=allowlist)
    assert result['verdict'] == 'COMPLETE', result
    assert result['skipped_allowlisted'] == ['tests.test_a::test_a1']


def test_stale_skip_allowlist_remains_error(tmp_path: Path) -> None:
    root, allowlist = suite(tmp_path)
    allowlist.write_text(json.dumps({
        'schema': 'agent-os-ci-skipped-allowlist/1',
        'suites': {'root': ['tests.does_not_exist::test_gone']},
    }))
    p = tmp_path / 'junit.xml'
    p.write_bytes(report(GOOD))
    result = check_suite(sys.executable, root, 'root', p, skip_allowlist=allowlist)
    assert result['verdict'] == 'ERROR', result
    assert result['skip_allowlist_stale'] == ['tests.does_not_exist::test_gone']


def test_real_failed_pytest_junit_vetoes_swallowed_runner_status(tmp_path: Path) -> None:
    root, allowlist = suite(tmp_path)
    (root / 'tests' / 'test_a.py').write_text(
        'def test_a1():\n    assert True\n\ndef test_a2():\n    assert False\n'
    )
    report_path = tmp_path / 'failing-junit.xml'
    actual = subprocess.run([
        sys.executable, '-m', 'pytest', 'tests', '-q', '-p', 'no:cacheprovider',
        f'--junitxml={report_path}',
    ], cwd=root, capture_output=True, text=True, check=False)
    assert actual.returncode == 1, actual.stdout + actual.stderr
    # Simulate a wrapper that swallows the nonzero exit; the receipt checks
    # provider-independent executed JUnit bytes, not the wrapper's success.
    verdict = check_suite(sys.executable, root, 'root', report_path, skip_allowlist=allowlist)
    assert verdict['verdict'] == 'OUTCOME_FAILED', verdict
    assert verdict['outcome']['failures'] == 1
    assert verdict['missing_count'] == 0


# --- Shell-wrapper receipt classification (validate-all.sh manifest rows) -----
# These replay the hosted NC09 incident end to end through the real runner:
# the suite row, the completeness row, and the published manifest must never
# certify a pass on failed, invalid, or absent outcome evidence.

from tests.test_agent_os_ci_test_completeness import _completeness, _repo, _rows, _run


def _swallow_root_exit(repo: Path) -> None:
    """Replay the exact NC09 runner defect in the fixture copy only: force
    the root suite's recorded exit code to 0 when pytest failed."""
    runner = repo / "scripts" / "validate-all.sh"
    text = runner.read_text(encoding="utf-8")
    snippet = '  (cd "$workdir" && "$@")\n  local code=$?\n'
    assert text.count(snippet) == 1
    runner.write_text(
        text.replace(
            snippet,
            snippet
            + '  if [ "$name" = "root" ] && [ "$code" -ne 0 ]; then\n'
            '    echo "NC09 replay: swallowing root pytest exit $code" >&2\n'
            "    code=0\n"
            "  fi\n",
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("helper", "code", "classification"),
    [
        ("import sys\nsys.exit(3)\n", "3", "TEST_COLLECTION_ERROR"),
        # An uncaught exception also exits 1, but without this attempt's receipt.
        ("raise RuntimeError('unhandled helper exception')\n", "1", "TEST_COLLECTION_ERROR"),
        ("raise SystemExit(0)\n", "2", "TEST_COLLECTION_ERROR"),  # success without a COMPLETE receipt
    ],
    ids=["crash-exit-3", "uncaught-exception-exit-1", "success-without-receipt"],
)
def test_helper_failures_fail_closed_and_ignore_stale_receipts(
    tmp_path: Path, helper: str, code: str, classification: str
) -> None:
    repo = _repo(tmp_path, {})
    (repo / "scripts" / "agent_os_ci_test_completeness.py").write_text(helper, encoding="utf-8")
    junit_dir = tmp_path / "junit"
    junit_dir.mkdir()
    (junit_dir / "test-completeness-root.json").write_text('{"verdict": "INCOMPLETE"}', encoding="utf-8")
    result = _run(repo, junit_dir)
    assert result.returncode == 1, result.stdout + result.stderr
    row = _completeness(junit_dir)
    assert row[2:5] == ("FAIL", code, classification)
    assert row[1] == "no"  # the stale receipt was cleared, never reused as evidence
    # A missing receipt must fail the suite row closed too: no EXECUTED_PASS
    # may stand on absent outcome evidence. The runner's exit 0 is preserved
    # in the row, only its status fails.
    assert _rows(junit_dir)["root"][2:5] == ("FAIL", "0", "TEST_COLLECTION_ERROR")


@pytest.mark.parametrize("swallow", [True, False], ids=["swallowed-exit", "honest-exit"])
def test_nc09_swallowed_root_exit_cannot_pass(tmp_path: Path, swallow: bool) -> None:
    """Hosted NC09 replayed locally: one failing root test plus (when
    ``swallow``) the injected runner defect that forced the root exit to 0.
    Pre-fix the swallowed run escaped as overall PASS with EXECUTED_PASS /
    COMPLETE; with the outcome oracle it must fail, and the manifest must
    never record the failed suite as EXECUTED_PASS. Without the swallow the
    ordinary failing-suite path (EXECUTED_FAIL, no completeness row) is
    preserved."""
    junit_dir = tmp_path / "junit"
    repo = _repo(tmp_path, {"tests/test_failing.py": "def test_failing():\n    assert False\n"})
    if swallow:
        _swallow_root_exit(repo)
    result = _run(repo, junit_dir)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "OVERALL STATUS\nFAIL" in output
    rows = _rows(junit_dir)
    if swallow:
        assert rows["root"][2:5] == ("FAIL", "0", "TEST_OUTCOME_FAILED")
        assert _completeness(junit_dir)[2:5] == ("FAIL", "1", "TEST_OUTCOME_FAILED")
        receipt = json.loads((junit_dir / "test-completeness-root.json").read_text(encoding="utf-8"))
        assert receipt["verdict"] == "OUTCOME_FAILED"
        assert receipt["outcome"]["failures"] == 1
        assert receipt["outcome"]["failed_nodes"] == ["tests.test_failing::test_failing"]
        # No row anywhere in the published manifest may claim a pass for it.
        assert "EXECUTED_PASS" not in (junit_dir / "manifest.tsv").read_text(encoding="utf-8")
    else:
        assert rows["root"][2:5] == ("FAIL", "1", "EXECUTED_FAIL")
        assert "test selection completeness: root" not in rows


@pytest.mark.parametrize("corruption", ["root-counter", "suite-error"])
def test_invalid_outcome_evidence_vetoes_passing_suite_manifest(
    tmp_path: Path, corruption: str
) -> None:
    """A pytest exit 0 with invalid JUnit must not leave EXECUTED_PASS evidence.

    Corrupt only the disposable fixture's JUnit before its completeness helper
    reads it. The production runner and real pytest output are untouched.
    """
    repo = _repo(tmp_path, {})
    helper = repo / "scripts" / "agent_os_ci_test_completeness.py"
    original = helper.read_text(encoding="utf-8")
    anchor = "    result = check_suite(\n"
    assert original.count(anchor) == 1
    if corruption == "root-counter":
        alteration = "        tree.getroot().set('failures', '1')\n"
    else:
        alteration = (
            "        ET.SubElement(tree.getroot().find('testsuite'), 'error').text = 'invalid'\n"
        )
    injected = (
        "    if args.suite_name == 'root':\n"
        "        from xml.etree import ElementTree as ET\n"
        "        tree = ET.parse(args.junit)\n"
        + alteration
        + "        tree.write(args.junit, encoding='utf-8')\n"
    )
    helper.write_text(original.replace(anchor, injected + anchor), encoding="utf-8")
    junit_dir = tmp_path / "junit"
    result = _run(repo, junit_dir)
    assert result.returncode == 1, result.stdout + result.stderr
    rows = _rows(junit_dir)
    assert rows["root"][2:5] == ("FAIL", "0", "TEST_COLLECTION_ERROR")
    assert _completeness(junit_dir)[2:5] == ("FAIL", "2", "TEST_COLLECTION_ERROR")
    receipt = json.loads((junit_dir / "test-completeness-root.json").read_text(encoding="utf-8"))
    assert receipt["verdict"] == "ERROR"
    assert "junit-" in receipt["error"]
    assert "EXECUTED_PASS" not in (junit_dir / "manifest.tsv").read_text(encoding="utf-8")
