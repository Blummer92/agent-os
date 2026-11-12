"""CI evidence-health classification for Agent OS (report-only, non-authoritative).

This module classifies *individual evidence streams* (pyan, jscpd, junit, aggregate)
from provider-verified metadata and report content. It never grants merge or Ready
authority, never executes untrusted code, and never trusts a self-reported head,
digest, or status over provider metadata.

Design correction over the earlier scratch validator: an intentionally deferred
Draft aggregate defers only the aggregate stream. It must never override another
stream's classification (e.g. a missing pyan report is EVIDENCE_MISSING even
when the aggregate stream is INTENTIONALLY_DEFERRED).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

SCHEMA = "agent-os-ci-evidence-health/1"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ADVISORY_SCHEMAS = {
    "pyan3": "agent-os-pyan3-advisory/1",
    "jscpd": "agent-os-jscpd-advisory/1",
}

# pytest 9 counts unittest/pytest subtests in the suite ``tests`` total
# without emitting one <testcase> per subtest, so a genuine aggregate
# report can declare more tests than it has testcase elements. A surplus
# is certified ONLY by a source-bound subtest receipt (see below): the
# receipt is producer evidence from the same run, bound by run id,
# attempt, head SHA and the JUnit file's own digest, and it must satisfy
# the passing-subtests-only equations in verify_subtest_receipt. A
# version string, a claimed count, or the surplus itself proves nothing.
SUBTEST_RECEIPT_SCHEMA = "agent-os-ci-junit-subtest-receipt/1"
SUBTEST_RECEIPT_PREFIX = "junit-subtest-receipt-"
_SUBTEST_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "junit_file",
        "junit_sha256",
        "source_run_id",
        "source_run_attempt",
        "source_head_sha",
        "passed",
        "skipped",
        "xfailed",
        "failed",
        "errors",
        "subtests_passed",
        "junit_tests",
        "junit_testcase_elements",
        "junit_failures",
        "junit_errors",
        "junit_skipped",
    }
)


@dataclass(frozen=True)
class StreamObservation:
    stream: str
    obligation: str  # required | deferred | not_applicable | reused
    source_head: str  # independently obtained from the Actions API
    reported_head: str  # self-reported, not automatically trusted
    run_attempt: int
    artifact_attempt: int
    job_id: int
    artifact_job_id: int
    artifact_present: bool
    artifact_expired: bool
    schema_valid: bool
    job_conclusion: str
    scanner_status: str = "completed"
    job_status: str = "completed"
    step_outcome: str | None = None
    artifact_bytes: bytes = b""
    claimed_sha256: str | None = None  # local content hash, not provider zip digest


@dataclass(frozen=True)
class AdvisoryReport:
    tool: str
    schema: str
    status: str
    head_sha: str


def classify_stream(o: StreamObservation) -> str:
    """Classify one stream only. Deferral never leaks to another stream."""
    if o.obligation == "deferred":
        return "INTENTIONALLY_DEFERRED"
    if o.obligation == "not_applicable":
        return "NOT_APPLICABLE"
    if o.obligation == "reused":
        return "REUSED_SOURCE_REQUIRED"
    if o.obligation != "required":
        return "REJECT_INVALID_OBLIGATION"
    if o.job_status in ("in_progress", "queued", "waiting"):
        return "INCOMPLETE"
    if o.step_outcome == "failure":
        return "REJECT_SCANNER_ERROR"
    if not _SHA.fullmatch(o.source_head) or o.reported_head != o.source_head:
        return "REJECT_WRONG_HEAD"
    if o.run_attempt < 1 or o.artifact_attempt != o.run_attempt:
        return "REJECT_WRONG_ATTEMPT"
    if o.job_id < 1 or o.artifact_job_id != o.job_id:
        return "REJECT_WRONG_JOB"
    if not o.artifact_present:
        return "EVIDENCE_MISSING"
    if o.artifact_expired:
        return "REJECT_EXPIRED"
    if not o.schema_valid:
        return "REJECT_SCHEMA"
    if o.claimed_sha256 is not None:
        if not _DIGEST.fullmatch(o.claimed_sha256) or hashlib.sha256(o.artifact_bytes).hexdigest() != o.claimed_sha256:
            return "REJECT_DIGEST"
    if o.scanner_status != "completed":
        return "REJECT_SCANNER_ERROR"
    if o.job_conclusion != "success":
        return "REJECT_JOB_NOT_SUCCESS"
    return "EVIDENCE_VALID"


def classify_provider_read(*, success: bool, pages_complete: bool) -> str:
    """A failed or truncated provider read is never proof of absence."""
    if not success or not pages_complete:
        return "PROVIDER_UNAVAILABLE"
    return "PROVIDER_OK"


_IAR_OVERALL = re.compile(r"Overall result:\s*([A-Za-z_-]+)")


def classify_issue_acceptance(text: str, *, workflow_conclusion: str) -> dict:
    """Preserve the Issue Acceptance checker's own verdict, separately from
    the workflow wrapper conclusion. A green wrapper with a manual-review
    checker verdict is MANUAL_REVIEW, never an acceptance pass; a missing
    Overall line is UNVERIFIED, never a pass."""
    match = _IAR_OVERALL.search(text or "")
    verdict = match.group(1).lower() if match else "unverified"
    if verdict not in ("pass", "warn", "manual-review", "fail"):
        verdict = "unverified"
    return {
        "checker_verdict": verdict,
        "workflow_conclusion": workflow_conclusion,
        "acceptance_pass": verdict == "pass" and workflow_conclusion == "success",
        "note": "Checker verdict and wrapper conclusion are distinct; only checker pass counts as acceptance pass.",
    }


def validate_advisory_report(report: AdvisoryReport | None, *, expected_head: str) -> str:
    if report is None:
        return "EVIDENCE_MISSING"
    if not _SHA.fullmatch(expected_head) or report.head_sha != expected_head:
        return "REJECT_WRONG_HEAD"
    if report.status == "scanner-error":
        return "REJECT_SCANNER_ERROR"
    if report.status != "ok":
        return "REJECT_SCHEMA"
    if _ADVISORY_SCHEMAS.get(report.tool) != report.schema:
        return "REJECT_SCHEMA"
    return "EVIDENCE_VALID"


def load_advisory_report(path: Path, *, tool: str) -> AdvisoryReport | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    head_sha = payload.get("head_sha")
    schema = payload.get("schema")
    if not isinstance(status, str) or not isinstance(head_sha, str) or not isinstance(schema, str):
        return None
    return AdvisoryReport(tool=tool, schema=schema, status=status, head_sha=head_sha)


def validate_advisory_report_file(path: Path, *, tool: str, expected_head: str) -> str:
    if not path.is_file():
        return "EVIDENCE_MISSING"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "REJECT_SCHEMA"
    if not isinstance(payload, dict):
        return "REJECT_SCHEMA"
    report = load_advisory_report(path, tool=tool)
    if report is None:
        return "REJECT_SCHEMA"
    return validate_advisory_report(report, expected_head=expected_head)


def parse_junit_report(xml: bytes, *, max_bytes: int = 8_000_000) -> tuple[tuple[str, ...], dict[str, int], tuple[tuple[int, int], ...]]:
    """Strict JUnit parse shared by the validator and the subtest receipt.

    Returns reporter-derived ids, counts, and per-suite (declared tests,
    testcase elements) shapes. ``counts`` carries the suite attribute
    totals plus per-element outcome counts: ``testcase_elements`` is the
    number of <testcase> elements actually present, and
    ``passed_elements`` / ``failed_elements`` / ``error_elements`` /
    ``skipped_elements`` count elements by the outcome child they carry
    (an element with no outcome child is a passed element). This function
    deliberately does NOT require declared tests to equal the element
    count: that equality is the validator's rule (see validate_junit),
    and the receipt verifier applies its own explained-surplus equations
    instead. Every other strictness is identical: unsafe/empty input,
    malformed XML, wrong root, missing suite name, non-numeric counts,
    missing node identity, duplicate identities, and subcounts larger
    than the declared total are all rejected here."""
    if not isinstance(xml, (bytes, bytearray)):
        raise ValueError("junit input must be bytes, not a path string")
    xml = bytes(xml)
    if not xml or len(xml) > max_bytes or b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ValueError("unsafe-or-empty-junit")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("invalid-junit-xml") from exc
    suites = [root] if root.tag == "testsuite" else list(root) if root.tag == "testsuites" else []
    if not suites or any(x.tag != "testsuite" for x in suites):
        raise ValueError("invalid-junit-root")
    ids: list[str] = []
    counts = {
        "tests": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "testcase_elements": 0,
        "passed_elements": 0,
        "failed_elements": 0,
        "error_elements": 0,
        "skipped_elements": 0,
    }
    suite_shapes: list[tuple[int, int]] = []
    for suite in suites:
        suite_name = suite.attrib.get("name", "")
        if not suite_name:
            raise ValueError("suite-name-missing")
        for field in ("tests", "failures", "errors", "skipped"):
            raw = suite.attrib.get(field, "")
            if not raw.isdigit():
                raise ValueError("invalid-junit-count")
            counts[field] += int(raw)
        cases = [x for x in suite if x.tag == "testcase"]
        counts["testcase_elements"] += len(cases)
        suite_shapes.append((int(suite.attrib["tests"]), len(cases)))
        for case in cases:
            # Real pytest output can emit a testcase with an empty classname
            # (e.g. a module-level node, observed in tests/agent_os_issue_acceptance:
            # classname="" with name="tests.agent_os_issue_acceptance.test_parse_pr_hypothesis").
            # Rejecting that whole report would be a false REJECT_SCHEMA on a real
            # 3,308-node run, so an empty classname is accepted as an empty
            # identity segment, falling back to the file attribute when present.
            # The name is still required, and duplicates are still rejected.
            classname = case.attrib.get("classname") or case.attrib.get("file") or ""
            name = case.attrib.get("name")
            if not name:
                raise ValueError("node-identity-missing")
            ids.append("::".join((suite_name, classname, name)))
            children = {x.tag for x in case}
            if "failure" in children:
                counts["failed_elements"] += 1
            if "error" in children:
                counts["error_elements"] += 1
            if "skipped" in children:
                counts["skipped_elements"] += 1
            if not children & {"failure", "error", "skipped"}:
                counts["passed_elements"] += 1
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("zero-or-duplicate-nodes")
    if any(v > counts["tests"] for k, v in counts.items() if k in ("failures", "errors", "skipped")):
        raise ValueError("invalid-subcount")
    return tuple(ids), counts, tuple(suite_shapes)


def validate_junit(xml: bytes, *, max_bytes: int = 8_000_000) -> tuple[tuple[str, ...], dict[str, int]]:
    """Strict JUnit validation. Returned ids are reporter-derived (suite +
    classname + name), NOT asserted to be full pytest nodeids.

    The declared suite total must equal the testcase elements present,
    per suite, exactly as before. A pytest 9 subtest surplus is NOT
    accepted here: it is accepted only in the collector, where a
    source-bound subtest receipt explains it (verify_subtest_receipt).
    An unexplained surplus stays rejected."""
    ids, counts, suite_shapes = parse_junit_report(xml, max_bytes=max_bytes)
    if any(elements != tests for tests, elements in suite_shapes):
        raise ValueError("testcase-count-mismatch")
    return ids, {k: counts[k] for k in ("tests", "failures", "errors", "skipped")}


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def load_subtest_receipts(receipt_files: dict[str, bytes]) -> dict[str, dict]:
    """Parse subtest receipt files from a JUnit artifact.

    ``receipt_files`` maps member name to bytes for members named
    ``junit-subtest-receipt-*.json``. Each file is one receipt entry (a
    JSON object, not a list). Returns junit_file -> entry. Any malformed
    file, wrong schema, unexpected field, or duplicate junit_file is a
    hard ValueError: a corrupt explanation poisons the artifact instead
    of being silently ignored."""
    out: dict[str, dict] = {}
    for name, data in receipt_files.items():
        try:
            payload = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"invalid-subtest-receipt: {name}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"invalid-subtest-receipt: {name}")
        if set(payload) != _SUBTEST_RECEIPT_KEYS:
            raise ValueError(f"invalid-subtest-receipt: {name}")
        if payload["schema"] != SUBTEST_RECEIPT_SCHEMA:
            raise ValueError(f"invalid-subtest-receipt: {name}")
        junit_file = payload["junit_file"]
        if not isinstance(junit_file, str) or not junit_file.endswith(".xml") or "/" in junit_file or "\\" in junit_file:
            raise ValueError(f"invalid-subtest-receipt: {name}")
        if junit_file in out:
            raise ValueError(f"duplicate-subtest-receipt: {junit_file}")
        out[junit_file] = payload
    return out


def verify_subtest_receipt(
    xml: bytes,
    entry: dict,
    *,
    source_run_id: int | None,
    source_run_attempt: int | None,
    source_head: str | None,
) -> tuple[tuple[str, ...], dict[str, int]]:
    """Accept a JUnit report whose declared total exceeds its testcase
    elements ONLY when a source-bound receipt explains the surplus as
    passing subtests. Returns (ids, counts) with the four validator
    counts plus ``subtests_passed`` and ``testcase_elements`` kept
    distinct: the certified evidence is the element identities plus the
    verified subtest count, never ``tests`` identities.

    The explanation must satisfy, against the actual XML bytes:
      * the entry's source run id, attempt and head SHA equal the
        provider-verified source (never None, never merely self-reported);
      * the entry's junit_sha256 equals the digest of these exact bytes;
      * the entry's recorded JUnit totals equal the parsed totals;
      * no failure or error anywhere (terminal counts, suite attributes,
        or outcome elements): an adverse subtest can never be reconciled
        away, and a failed suite is rejected on its own merits;
      * declared tests == passed + skipped + xfailed + failed + errors
        + subtests_passed (every report accounted for, nothing else);
      * suite skipped == terminal skipped + xfailed (xfail is a JUnit
        skip; no hidden skipped outcome);
      * passed elements == terminal passed, skipped elements == suite
        skipped, and every element is either passed or skipped. A
        skipped or xfailed subtest marks its (passed) parent element
        with a <skipped> child, so it breaks the element equation and
        stays rejected: only the all-passing-subtest shape is supported.
        Skipped/xfail/failed subtests, teardown errors, parallel and
        nested shapes are explicitly unsupported, not silently accepted.
      * the surplus (declared tests - elements) is positive and equals
        subtests_passed exactly; nothing is inferred from a missing
        receipt, and a missing receipt never implies zero subtests.

    Any violation raises ValueError. Callers must treat a raised error
    as REJECT_SCHEMA for that report."""
    if not isinstance(entry, dict) or set(entry) != _SUBTEST_RECEIPT_KEYS:
        raise ValueError("invalid-subtest-receipt-entry")
    if entry["schema"] != SUBTEST_RECEIPT_SCHEMA:
        raise ValueError("invalid-subtest-receipt-entry")
    for field in ("passed", "skipped", "xfailed", "failed", "errors", "subtests_passed",
                  "junit_tests", "junit_testcase_elements", "junit_failures", "junit_errors", "junit_skipped"):
        if not _is_non_negative_int(entry[field]):
            raise ValueError("invalid-subtest-receipt-entry")
    if source_run_id is None or source_run_attempt is None or source_head is None:
        raise ValueError("subtest-receipt-unbound")
    if entry["source_run_id"] != source_run_id or entry["source_run_attempt"] != source_run_attempt or entry["source_head_sha"] != source_head:
        raise ValueError("subtest-receipt-wrong-source")
    if not isinstance(entry["source_head_sha"], str) or not _SHA.fullmatch(entry["source_head_sha"]):
        raise ValueError("subtest-receipt-wrong-source")
    if not isinstance(entry["junit_sha256"], str) or not _DIGEST.fullmatch(entry["junit_sha256"]):
        raise ValueError("invalid-subtest-receipt-entry")
    if hashlib.sha256(bytes(xml)).hexdigest() != entry["junit_sha256"]:
        raise ValueError("subtest-receipt-digest-mismatch")
    ids, counts, suite_shapes = parse_junit_report(xml)
    if any(elements > tests for tests, elements in suite_shapes):
        # A suite with more elements than declared tests is the
        # --setup-only shape (passing-looking elements, tests="0"): never
        # an executed-tests explanation, even with a receipt.
        raise ValueError("testcase-count-mismatch")
    if (
        entry["junit_tests"] != counts["tests"]
        or entry["junit_testcase_elements"] != counts["testcase_elements"]
        or entry["junit_failures"] != counts["failures"]
        or entry["junit_errors"] != counts["errors"]
        or entry["junit_skipped"] != counts["skipped"]
    ):
        raise ValueError("subtest-receipt-count-mismatch")
    if (
        entry["failed"] != 0
        or entry["errors"] != 0
        or counts["failures"] != 0
        or counts["errors"] != 0
        or counts["failed_elements"] != 0
        or counts["error_elements"] != 0
    ):
        raise ValueError("subtest-receipt-adverse-outcome")
    if counts["tests"] != entry["passed"] + entry["skipped"] + entry["xfailed"] + entry["failed"] + entry["errors"] + entry["subtests_passed"]:
        raise ValueError("subtest-receipt-total-mismatch")
    if counts["skipped"] != entry["skipped"] + entry["xfailed"]:
        raise ValueError("subtest-receipt-skip-mismatch")
    if counts["passed_elements"] != entry["passed"] or counts["skipped_elements"] != counts["skipped"]:
        raise ValueError("subtest-receipt-element-mismatch")
    if counts["testcase_elements"] != counts["passed_elements"] + counts["skipped_elements"]:
        raise ValueError("subtest-receipt-element-mismatch")
    surplus = counts["tests"] - counts["testcase_elements"]
    if surplus <= 0 or surplus != entry["subtests_passed"]:
        raise ValueError("subtest-receipt-surplus-mismatch")
    return ids, {
        "tests": counts["tests"],
        "failures": counts["failures"],
        "errors": counts["errors"],
        "skipped": counts["skipped"],
        "subtests_passed": entry["subtests_passed"],
        "testcase_elements": counts["testcase_elements"],
    }


def dedup_action(existing: dict[str, str], key: str, content_digest: str) -> str:
    if not key or not _DIGEST.fullmatch(content_digest):
        return "REJECT_INVALID_KEY_OR_DIGEST"
    prior = existing.get(key)
    if prior is None:
        return "PROPOSE_APPEND"
    if prior == content_digest:
        return "SKIP_IDENTICAL"
    return "REJECT_CONFLICT"


def build_health_receipt(
    *,
    stream: str,
    classification: str,
    run_id: int | None,
    run_attempt: int | None,
    job_id: int | None,
    head_sha: str,
    generate_outcome: str | None,
    report_path: str | None,
) -> dict:
    return {
        "schema": SCHEMA,
        "stream": stream,
        "classification": classification,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "job_id": job_id,
        "head_sha": head_sha,
        "generate_outcome": generate_outcome,
        "report_present": report_path is not None,
        "report_path": report_path,
        "merge_authority": False,
        "note": "Report-only health signal; a classification here is not a merge or Ready decision.",
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", required=True, choices=sorted(_ADVISORY_SCHEMAS))
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--report", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--generate-outcome", default=None)
    parser.add_argument("--health-dir", required=True, type=Path)
    parser.add_argument("--run-id", type=int, default=None)
    parser.add_argument("--run-attempt", type=int, default=None)
    parser.add_argument("--job-id", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report_path = args.output_dir / args.report
    classification = validate_advisory_report_file(report_path, tool=args.tool, expected_head=args.head)
    if args.generate_outcome == "failure":
        # The generate step failed before continue-on-error; any report
        # present is stale or partial, not scanner success.
        classification = "REJECT_SCANNER_ERROR"
    receipt = build_health_receipt(
        stream=args.tool,
        classification=classification,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        job_id=args.job_id,
        head_sha=args.head,
        generate_outcome=args.generate_outcome,
        report_path=str(report_path) if report_path.is_file() else None,
    )
    try:
        args.health_dir.mkdir(parents=True, exist_ok=True)
        (args.health_dir / f"{args.tool}-health.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        print(f"health receipt write failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
