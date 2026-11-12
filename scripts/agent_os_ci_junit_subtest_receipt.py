"""Producer-side pytest subtest receipt extractor for Agent OS CI.

Run by scripts/validate-all.sh after each suite's pytest invocation,
while CI_JUNIT_DIR is set. It reads the suite's captured pytest terminal
output and its JUnit file and writes one receipt JSON per suite into
CI_JUNIT_DIR, named ``junit-subtest-receipt-<junit-key>.json``.

The receipt is the collector's explanation for a pytest 9 subtest
surplus (declared suite tests exceeding testcase elements). It records
the terminal summary counts from the run itself -- an independent
channel from the JUnit file -- plus the JUnit file's digest and its own
recorded totals, bound to the workflow run id, attempt and head SHA
from the workflow environment. When those binding values are absent
(a local run) the receipt is written unbound (nulls) and the collector
will not accept it as an explanation: a local receipt can never
certify evidence.

A receipt is written ONLY when the terminal summary explicitly shows
a ``N subtests passed`` segment. Absence of the segment means either
no subtests ran or pytest ran too quietly to report them (the segment
needs -v, which the root pytest.ini supplies); absence is never read
as zero subtests, so no receipt is written and any surplus stays
rejected. Skipped, xfailed and failed subtests have no separate
terminal segment, so this channel cannot explain them: the collector
accepts only the all-passing-subtest shape, and every other shape
stays rejected by design.

Exit codes: 0 when a receipt was written or when no receipt applies
(no subtests segment); 2 on unreadable inputs, an unparseable JUnit
file, or invalid binding arguments. The caller (validate-all.sh)
never fails a suite over receipt extraction: a missing receipt only
means a surplus stays rejected downstream, which is the safe
direction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_os_ci_evidence_health import (  # noqa: E402
    SUBTEST_RECEIPT_SCHEMA,
    parse_junit_report,
)

_SHA = re.compile(r"^[0-9a-f]{40}$")

_SUMMARY_RE = re.compile(r"^=+\s+(.+?)\s+in\s+[0-9]+\.[0-9]+s(?:\s+\([^)]*\))?\s+=+\s*$")
_SEGMENT_RES = {
    "passed": re.compile(r"^([0-9]+) passed$"),
    "failed": re.compile(r"^([0-9]+) failed$"),
    "skipped": re.compile(r"^([0-9]+) skipped$"),
    "xfailed": re.compile(r"^([0-9]+) xfailed$"),
    "xpassed": re.compile(r"^([0-9]+) xpassed$"),
    "errors": re.compile(r"^([0-9]+) errors?$"),
    "warnings": re.compile(r"^([0-9]+) warnings?$"),
    "deselected": re.compile(r"^([0-9]+) deselected$"),
    "subtests_passed": re.compile(r"^([0-9]+) subtests passed$"),
}


def parse_pytest_summary(text: str) -> dict[str, int] | None:
    """Parse the final pytest session-summary line.

    Returns terminal counts, or None when no usable summary line exists
    (no summary, an unknown segment, or no explicit ``subtests passed``
    segment). The segment grammar is pinned to genuine pytest 9.2.0
    output; anything else fails closed with None instead of guessing.
    Deselected tests and warnings are parsed but do not enter the JUnit
    reconciliation: they were not executed / are not test outcomes."""
    candidates: list[str] = []
    for line in (text or "").splitlines():
        match = _SUMMARY_RE.match(line.strip())
        if match:
            candidates.append(match.group(1))
    if not candidates:
        return None
    # The session summary is the last matching line; earlier matches are
    # per-phase summaries (e.g. a warnings summary) that must not win.
    middle = candidates[-1]
    counts: dict[str, int] = {}
    for segment in middle.split(", "):
        segment = segment.strip()
        for key, pattern in _SEGMENT_RES.items():
            hit = pattern.match(segment)
            if hit:
                counts[key] = int(hit.group(1))
                break
        else:
            return None
    if "subtests_passed" not in counts:
        return None
    for key in ("passed", "failed", "skipped", "xfailed", "errors"):
        counts.setdefault(key, 0)
    counts.setdefault("xpassed", 0)
    return counts


def extract_entry(
    *,
    junit_bytes: bytes,
    pytest_output: str,
    junit_file: str,
    source_run_id: int | None,
    source_run_attempt: int | None,
    source_head: str | None,
) -> dict | None:
    """Build one receipt entry, or None when no explanation applies."""
    summary = parse_pytest_summary(pytest_output)
    if summary is None:
        return None
    _, counts, _ = parse_junit_report(junit_bytes)
    return {
        "schema": SUBTEST_RECEIPT_SCHEMA,
        "junit_file": junit_file,
        "junit_sha256": hashlib.sha256(junit_bytes).hexdigest(),
        "source_run_id": source_run_id,
        "source_run_attempt": source_run_attempt,
        "source_head_sha": source_head,
        "passed": summary["passed"],
        "skipped": summary["skipped"],
        "xfailed": summary["xfailed"],
        "failed": summary["failed"],
        "errors": summary["errors"],
        "subtests_passed": summary["subtests_passed"],
        "junit_tests": counts["tests"],
        "junit_testcase_elements": counts["testcase_elements"],
        "junit_failures": counts["failures"],
        "junit_errors": counts["errors"],
        "junit_skipped": counts["skipped"],
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("--pytest-output", required=True, type=Path)
    parser.add_argument("--suite-name", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--run-id", type=int, default=None)
    parser.add_argument("--run-attempt", type=int, default=None)
    parser.add_argument("--head-sha", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.run_id is not None and args.run_id < 1:
        print("subtest receipt: --run-id must be positive", file=sys.stderr)
        return 2
    if args.run_attempt is not None and args.run_attempt < 1:
        print("subtest receipt: --run-attempt must be positive", file=sys.stderr)
        return 2
    if args.head_sha is not None and not _SHA.fullmatch(args.head_sha):
        print("subtest receipt: --head-sha must be a 40-hex SHA", file=sys.stderr)
        return 2
    try:
        junit_bytes = args.junit.read_bytes()
    except OSError as exc:
        print(f"subtest receipt: cannot read junit file: {exc}", file=sys.stderr)
        return 2
    try:
        pytest_output = args.pytest_output.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"subtest receipt: cannot read pytest output: {exc}", file=sys.stderr)
        return 2
    try:
        entry = extract_entry(
            junit_bytes=junit_bytes,
            pytest_output=pytest_output,
            junit_file=args.junit.name,
            source_run_id=args.run_id,
            source_run_attempt=args.run_attempt,
            source_head=args.head_sha,
        )
    except ValueError as exc:
        print(f"subtest receipt: junit file is not a valid report: {exc}", file=sys.stderr)
        return 2
    if entry is None:
        print(
            f"subtest receipt: no explicit subtests-passed segment for suite "
            f"{args.suite_name}; no receipt written (any surplus stays rejected)",
            file=sys.stderr,
        )
        return 0
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(entry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"subtest receipt: cannot write receipt: {exc}", file=sys.stderr)
        return 2
    print(
        f"subtest receipt: wrote {args.output.name} for suite {args.suite_name}: "
        f"{entry['subtests_passed']} passing subtests, junit tests={entry['junit_tests']} "
        f"elements={entry['junit_testcase_elements']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
