"""Compare two JUnit reports and reconcile removed test nodes.

Machine-verified mapping only: a removed node counts as mapped only when
its named replacement is present in the patched node set. A narrative
mapping file that names a replacement which does not exist in the patched
set, or no mapping file at all, leaves the node unmapped and the diff
verdict INCOMPLETE. This script never claims mutant-detection power: that
must come from separate mutant receipts, not from node identity alone.

Node identity here is ``classname::name`` (pytest JUnit identity), which is
the identity used by the #3756 node-diff evidence. It is not the health
verifier's ``suite::classname::name`` reporter identity; do not mix them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


def _parse_report_suites(xml: bytes) -> tuple[ET.Element, list[ET.Element]]:
    """Parse JUnit XML into its ``<testsuite>`` elements, strictly.

    Shared by identity and outcome reads so the two can never disagree about
    what counts as a report: empty, malformed, wrong-root, count-mismatched,
    identity-less, or duplicated reports are all rejected here.
    """
    if not xml:
        raise ValueError("empty-junit")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("invalid-junit-xml") from exc
    suites = [root] if root.tag == "testsuite" else list(root) if root.tag == "testsuites" else []
    if not suites or any(x.tag != "testsuite" for x in suites):
        raise ValueError("invalid-junit-root")
    return root, suites


def _suites(xml: bytes) -> list[ET.Element]:
    """Preserve the identity reader's original strict suite parser."""
    return _parse_report_suites(xml)[1]


def _int_attr(suite: ET.Element, name: str) -> int | None:
    """A suite counter attribute as an int, or ``None`` when absent.

    A present but non-integer counter is inconsistent evidence, not a zero.
    """
    raw = suite.attrib.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"junit-invalid-{name}-attribute") from exc


def junit_outcomes(xml: bytes) -> dict:
    """Count executed JUnit outcomes from ``<failure>``/``<error>``/``<skipped>`` children.

    NC09 (hosted, 2026-11-08): a deliberately swallowed root pytest exit left
    16 failed testcases in ``root.xml`` while the manifest said
    ``EXECUTED_PASS`` and completeness said ``COMPLETE``, because the only
    JUnit read was identity (``node_ids``), which never looks at outcomes.
    This oracle is the independent veto: a report with failures or errors
    can never be a pass, whatever exit code the runner reported.

    Counters are reconciled against the suite attributes when present: a
    ``failures``/``errors``/``skipped`` attribute that disagrees with its
    counted children is inconsistent evidence and fails closed
    (``junit-outcome-count-mismatch``). The ``tests`` attribute is NOT
    reconciled exactly — pytest 9 counts unittest subtests in ``tests``
    without a ``<testcase>`` each — only the existing
    ``testcase-count-mismatch`` bound (elements must not exceed ``tests``)
    applies. A report with zero testcases proves no execution and can never
    yield COMPLETE: with a non-empty reference the completeness check reports
    INCOMPLETE (a --collect-only report has no <testcase> and fails
    reconciliation, as before), and a zero-test reference cannot reach this
    oracle through a passing suite (pytest exits 5 when nothing is
    collected). Skips are counted honestly, never as passed executed bodies.
    """
    root, suites = _parse_report_suites(xml)
    # Outcome elements outside pytest's supported direct testcase shape are
    # not clean evidence. Reject them instead of silently ignoring a failure.
    for suite in suites:
        parents = {child: parent for parent in suite.iter() for child in parent}
        for element in suite.iter():
            if element.tag == "testsuite" and element is not suite:
                raise ValueError("junit-unsupported-nested-suite")
            if element.tag == "testcase" and parents.get(element) is not suite:
                raise ValueError("junit-unsupported-testcase-placement")
            local_tag = element.tag.rsplit("}", 1)[-1]
            if local_tag in {"testcase", "testsuite", "failure", "error", "skipped"} and local_tag != element.tag:
                raise ValueError("junit-unsupported-element-namespace")
            if element.tag in {"failure", "error", "skipped"}:
                parent = parents.get(element)
                if parent is None or parent.tag != "testcase" or parents.get(parent) is not suite:
                    raise ValueError("junit-unsupported-outcome-placement")
    tests = failures = errors = skipped = 0
    declared_tests_total = 0
    failed_nodes: list[str] = []
    for suite in suites:
        cases = [x for x in suite if x.tag == "testcase"]
        # pytest 9 counts unittest subtests in ``tests`` without a <testcase> each, so the
        # attribute may exceed the elements; elements beyond it (--setup-only/--setup-plan
        # report tests="0" with passing-looking elements) are not executed tests.
        # CI trust: the tests counter is mandatory even when there are no
        # testcase elements. An absent counter must not be treated as zero.
        declared_tests = _int_attr(suite, "tests")
        if declared_tests is None or declared_tests < 0:
            raise ValueError("junit-missing-or-invalid-tests-count")
        if len(cases) > declared_tests:
            raise ValueError("testcase-count-mismatch")
        declared_tests_total += declared_tests
        suite_failures = suite_errors = suite_skipped = 0
        for case in cases:
            classname = case.attrib.get("classname") or case.attrib.get("file") or ""
            name = case.attrib.get("name")
            if not name:
                raise ValueError("node-identity-missing")
            has_failure = any(x.tag == "failure" for x in case)
            has_error = any(x.tag == "error" for x in case)
            if has_failure:
                suite_failures += 1
            if has_error:
                suite_errors += 1
            if any(x.tag == "skipped" for x in case):
                suite_skipped += 1
            if has_failure or has_error:
                failed_nodes.append(f"{classname}::{name}")
        for attr, counted in (
            ("failures", suite_failures),
            ("errors", suite_errors),
            ("skipped", suite_skipped),
        ):
            declared = _int_attr(suite, attr)
            if declared is not None and declared != counted:
                raise ValueError("junit-outcome-count-mismatch")
        tests += len(cases)
        failures += suite_failures
        errors += suite_errors
        skipped += suite_skipped
    # Root aggregate attributes are optional, but when supplied they must
    # reconcile with child suite evidence. Test counters use declared child
    # counts (not testcase nodes), preserving legitimate pytest 9 subtests.
    if root.tag == "testsuites":
        for attr, counted in (
            ("tests", declared_tests_total),
            ("failures", failures),
            ("errors", errors),
            ("skipped", skipped),
        ):
            declared = _int_attr(root, attr)
            if declared is not None and (declared < 0 or declared != counted):
                raise ValueError("junit-outcome-count-mismatch")
    if len(set(failed_nodes)) != len(failed_nodes):
        raise ValueError("duplicate-nodes")
    return {
        "schema": "agent-os-ci-junit-outcome/1",
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "failed_count": len(failed_nodes),
        "failed_nodes": failed_nodes[:100],
    }


def node_ids(xml: bytes) -> set[str]:
    suites = _suites(xml)
    ids: list[str] = []
    for suite in suites:
        cases = [x for x in suite if x.tag == "testcase"]
        # pytest 9 counts unittest subtests in ``tests`` without a <testcase> each, so the
        # attribute may exceed the elements; elements beyond it (--setup-only/--setup-plan
        # report tests="0" with passing-looking elements) are not executed tests.
        if len(cases) > int(suite.attrib.get("tests", "-1")):
            raise ValueError("testcase-count-mismatch")
        for case in cases:
            classname = case.attrib.get("classname") or case.attrib.get("file") or ""
            name = case.attrib.get("name")
            if not name:
                raise ValueError("node-identity-missing")
            ids.append(f"{classname}::{name}")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate-nodes")
    return set(ids)


def diff_junit(
    baseline_xml: bytes,
    patched_xml: bytes,
    mapping: dict[str, list[str]] | None = None,
) -> dict:
    baseline = node_ids(baseline_xml)
    patched = node_ids(patched_xml)
    removed = sorted(baseline - patched)
    new = sorted(patched - baseline)
    unchanged = sorted(baseline & patched)
    mapping = mapping or {}
    mapped: dict[str, list[str]] = {}
    unmapped: list[str] = []
    for node in removed:
        replacements = mapping.get(node, [])
        # A replacement counts only if it exists in the patched set.
        present = [r for r in replacements if r in patched]
        if present:
            mapped[node] = present
        else:
            unmapped.append(node)
    return {
        "schema": "agent-os-ci-junit-diff/1",
        "baseline_count": len(baseline),
        "patched_count": len(patched),
        "unchanged_count": len(unchanged),
        "new_count": len(new),
        "removed_count": len(removed),
        "unchanged": unchanged,
        "new": new,
        "removed": removed,
        "mapped_removed_ids": sorted(mapped),
        "mapped_removed": mapped,
        "unmapped_removed_ids": unmapped,
        "verdict": "INCOMPLETE" if unmapped else "COMPLETE_WITH_MAPPING",
        "note": "Mapping proves node existence, not mutant-detection power.",
    }


def _load_mapping(path: Path | None) -> dict[str, list[str]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("mapping must be a JSON object")
    out: dict[str, list[str]] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            out[str(key)] = [value]
        elif isinstance(value, list) and all(isinstance(v, str) for v in value):
            out[str(key)] = list(value)
        else:
            raise ValueError("mapping values must be strings or lists of strings")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--patched", required=True, type=Path)
    parser.add_argument("--mapping", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        result = diff_junit(args.baseline.read_bytes(), args.patched.read_bytes(), _load_mapping(args.mapping))
    except (OSError, ValueError) as exc:
        print(f"junit diff failed: {exc}", file=sys.stderr)
        return 2
    result["baseline_sha256"] = hashlib.sha256(args.baseline.read_bytes()).hexdigest()
    result["patched_sha256"] = hashlib.sha256(args.patched.read_bytes()).hexdigest()
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["verdict"] == "COMPLETE_WITH_MAPPING" else 1


if __name__ == "__main__":
    raise SystemExit(main())
