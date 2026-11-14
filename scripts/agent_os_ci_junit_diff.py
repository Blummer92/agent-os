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


def _testcases(xml: bytes) -> list[tuple[str, bool]]:
    """Strictly parsed ``(identity, was_skipped)`` pairs from a JUnit report.

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
    out: list[tuple[str, bool]] = []
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
            out.append((f"{classname}::{name}", any(x.tag == "skipped" for x in case)))
    if len({ident for ident, _ in out}) != len(out):
        raise ValueError("duplicate-nodes")
    return out


def node_ids(xml: bytes) -> set[str]:
    return {ident for ident, _ in _testcases(xml)}


def skipped_node_ids(xml: bytes) -> set[str]:
    """Identities whose ``<testcase>`` carries a ``<skipped>`` child.

    A skipped testcase is present in the report but its body never ran, so
    identity reconciliation alone cannot see it (NC07, hosted 2026-11-08:
    a mandatory test marked ``@pytest.mark.skip`` kept the aggregate green).
    The same strict parse as :func:`node_ids` applies, so a malformed report
    fails closed instead of reporting no skips.
    """
    return {ident for ident, skipped in _testcases(xml) if skipped}


def junit_outcomes(xml: bytes) -> dict:
    """Independently veto failed JUnit outcomes without changing NC07 identities.

    Read the SAME report as ``node_ids`` and ``skipped_node_ids``. Preserve
    NC07's strict node/count checks, while rejecting unsupported outcome
    placement and contradictory suite counters (NC09).
    """
    identities = _testcases(xml)  # identity, duplicate, and pytest-9 bounds
    root = ET.fromstring(xml)
    suites = [root] if root.tag == "testsuite" else list(root)
    failures = errors = skipped = 0
    declared_tests_total = 0
    failed_nodes: set[str] = set()
    for suite in suites:
        observed = {"failures": 0, "errors": 0, "skipped": 0}
        parents = {child: parent for parent in suite.iter() for child in parent}
        for element in suite.iter():
            local_tag = element.tag.rsplit("}", 1)[-1]
            if local_tag in {"testcase", "testsuite", "failure", "error", "skipped"}:
                if local_tag != element.tag:
                    raise ValueError("junit-unsupported-element-namespace")
            if element.tag == "testsuite" and element is not suite:
                raise ValueError("junit-unsupported-nested-suite")
            if element.tag == "testcase" and parents.get(element) is not suite:
                raise ValueError("junit-unsupported-testcase-placement")
            kind = {"failure": "failures", "error": "errors", "skipped": "skipped"}.get(element.tag)
            if kind is not None:
                case = parents.get(element)
                if case is None or case.tag != "testcase" or parents.get(case) is not suite:
                    raise ValueError("junit-unsupported-outcome-placement")
                observed[kind] += 1
                if element.tag in {"failure", "error"}:
                    classname = case.attrib.get("classname") or case.attrib.get("file") or ""
                    failed_nodes.add(f"{classname}::{case.attrib['name']}")
        for attr, actual in observed.items():
            if attr in suite.attrib:
                try:
                    claimed = int(suite.attrib[attr])
                except ValueError as exc:
                    raise ValueError(f"junit-invalid-{attr}-attribute") from exc
                if claimed != actual:
                    raise ValueError("junit-outcome-count-mismatch")
        failures += observed["failures"]
        errors += observed["errors"]
        skipped += observed["skipped"]
        # _testcases already rejected a suite whose ``tests`` attribute is
        # absent, non-integer, or smaller than its testcase count.
        declared_tests_total += int(suite.attrib["tests"])
    if root.tag == "testsuites":
        # A multi-suite document's root counters are evidence too: a present
        # but contradictory root counter fails closed, as each suite's does.
        for attr, actual in (
            ("tests", declared_tests_total),
            ("failures", failures),
            ("errors", errors),
            ("skipped", skipped),
        ):
            if attr in root.attrib:
                try:
                    claimed = int(root.attrib[attr])
                except ValueError as exc:
                    raise ValueError(f"junit-invalid-{attr}-attribute") from exc
                if claimed != actual:
                    raise ValueError("junit-outcome-count-mismatch")
    return {
        "tests": len(identities),
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "failed_nodes": sorted(failed_nodes),
    }


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
