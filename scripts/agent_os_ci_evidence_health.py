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


def validate_junit(xml: bytes, *, max_bytes: int = 8_000_000) -> tuple[tuple[str, ...], dict[str, int]]:
    """Strict JUnit validation. Returned ids are reporter-derived (suite +
    classname + name), NOT asserted to be full pytest nodeids."""
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
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        suite_name = suite.attrib.get("name", "")
        if not suite_name:
            raise ValueError("suite-name-missing")
        for field in counts:
            raw = suite.attrib.get(field, "")
            if not raw.isdigit():
                raise ValueError("invalid-junit-count")
            counts[field] += int(raw)
        cases = [x for x in suite if x.tag == "testcase"]
        if len(cases) != int(suite.attrib["tests"]):
            raise ValueError("testcase-count-mismatch")
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
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("zero-or-duplicate-nodes")
    if any(v > counts["tests"] for k, v in counts.items() if k != "tests"):
        raise ValueError("invalid-subcount")
    return tuple(ids), counts


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
