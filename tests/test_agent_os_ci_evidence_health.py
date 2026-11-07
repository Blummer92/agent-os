from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.agent_os_ci_evidence_health import (
    AdvisoryReport,
    StreamObservation,
    classify_stream,
    dedup_action,
    validate_advisory_report,
    validate_junit,
)


def _obs(**overrides):
    base = dict(
        stream="pyan",
        obligation="required",
        source_head="a" * 40,
        reported_head="a" * 40,
        run_attempt=1,
        artifact_attempt=1,
        job_id=7,
        artifact_job_id=7,
        artifact_present=True,
        artifact_expired=False,
        schema_valid=True,
        job_conclusion="success",
        scanner_status="completed",
        artifact_bytes=b"{}",
        claimed_sha256=None,
    )
    base.update(overrides)
    return StreamObservation(**base)


def test_green_job_missing_artifact_is_evidence_missing_not_valid():
    assert classify_stream(_obs(artifact_present=False)) == "EVIDENCE_MISSING"


def test_valid_report_with_matching_head_is_valid():
    assert classify_stream(_obs()) == "EVIDENCE_VALID"


def test_draft_deferred_aggregate_does_not_defer_pyan_stream():
    # The whole-run bug: a deferred aggregate must not override pyan.
    assert classify_stream(_obs(stream="aggregate", obligation="deferred")) == "INTENTIONALLY_DEFERRED"
    assert classify_stream(_obs(stream="pyan", obligation="required", artifact_present=False)) == "EVIDENCE_MISSING"


def test_scanner_error_report_is_rejected_even_when_file_exists_and_job_green():
    assert classify_stream(_obs(scanner_status="scanner-error")) == "REJECT_SCANNER_ERROR"


def test_wrong_head_attempt_job_expired_digest_are_rejected():
    assert classify_stream(_obs(reported_head="b" * 40)) == "REJECT_WRONG_HEAD"
    assert classify_stream(_obs(artifact_attempt=2)) == "REJECT_WRONG_ATTEMPT"
    assert classify_stream(_obs(artifact_job_id=9)) == "REJECT_WRONG_JOB"
    assert classify_stream(_obs(artifact_expired=True)) == "REJECT_EXPIRED"
    assert classify_stream(_obs(schema_valid=False)) == "REJECT_SCHEMA"
    assert classify_stream(_obs(artifact_bytes=b"data", claimed_sha256="0" * 64)) == "REJECT_DIGEST"
    assert classify_stream(_obs(artifact_bytes=b"data", claimed_sha256=hashlib.sha256(b"data").hexdigest())) == "EVIDENCE_VALID"


def test_provider_unavailable_is_distinct_from_missing():
    # classify_stream takes an explicit provider_available flag via obligation
    # handling in the collector layer; here the health module must expose it.
    from scripts.agent_os_ci_evidence_health import classify_provider_read

    assert classify_provider_read(success=False, pages_complete=False) == "PROVIDER_UNAVAILABLE"
    assert classify_provider_read(success=True, pages_complete=False) == "PROVIDER_UNAVAILABLE"
    assert classify_provider_read(success=True, pages_complete=True) == "PROVIDER_OK"


def test_advisory_report_validation():
    report = AdvisoryReport(tool="pyan3", schema="agent-os-pyan3-advisory/1", status="ok", head_sha="a" * 40)
    assert validate_advisory_report(report, expected_head="a" * 40) == "EVIDENCE_VALID"
    assert validate_advisory_report(report, expected_head="b" * 40) == "REJECT_WRONG_HEAD"
    assert validate_advisory_report(AdvisoryReport(tool="pyan3", schema="agent-os-pyan3-advisory/1", status="scanner-error", head_sha="a" * 40), expected_head="a" * 40) == "REJECT_SCANNER_ERROR"
    assert validate_advisory_report(AdvisoryReport(tool="pyan3", schema="wrong", status="ok", head_sha="a" * 40), expected_head="a" * 40) == "REJECT_SCHEMA"
    assert validate_advisory_report(None, expected_head="a" * 40) == "EVIDENCE_MISSING"


def _junit_xml(*, tests=2, failures=0, cases=None):
    if cases is None:
        cases = "".join(
            f'<testcase classname="mod" name="test_{i}"/>' for i in range(tests)
        )
    return (
        f'<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="{tests}" '
        f'failures="{failures}" errors="0" skipped="0">{cases}</testsuite></testsuites>'
    ).encode()


def test_junit_valid_and_reporter_derived_ids():
    ids, counts = validate_junit(_junit_xml(tests=2))
    assert counts == {"tests": 2, "failures": 0, "errors": 0, "skipped": 0}
    assert ids == ("pytest::mod::test_0", "pytest::mod::test_1")


def test_junit_malformed_zero_duplicate_and_count_mismatch_rejected():
    with pytest.raises(ValueError):
        validate_junit(b"not xml")
    with pytest.raises(ValueError):
        validate_junit(_junit_xml(tests=0, cases=""))
    with pytest.raises(ValueError):
        validate_junit(_junit_xml(tests=2, cases='<testcase classname="m" name="t"/><testcase classname="m" name="t"/>'))
    with pytest.raises(ValueError):
        validate_junit(_junit_xml(tests=3, cases='<testcase classname="m" name="t"/>'))
    with pytest.raises(ValueError):
        validate_junit(b'<?xml version="1.0"?><!DOCTYPE testsuite [<!ENTITY x "y">]><testsuites/>')


def test_junit_empty_classname_from_real_pytest_is_accepted():
    xml = (
        '<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="1" '
        'failures="0" errors="0" skipped="0">'
        '<testcase classname="" name="tests.agent_os_issue_acceptance.test_parse_pr_hypothesis" time="0.000"/>'
        '</testsuite></testsuites>'
    ).encode()
    ids, counts = validate_junit(xml)
    assert counts["tests"] == 1
    assert ids[0].endswith("tests.agent_os_issue_acceptance.test_parse_pr_hypothesis")


def test_junit_string_path_input_is_rejected_as_value_error_not_type_error():
    with pytest.raises(ValueError):
        validate_junit("/tmp/focused-junit/00_python_-m_pytest_tests__agent_os_issue_acceptance.xml")  # type: ignore[arg-type]


def test_dedup_identical_skips_and_conflict_rejects():
    assert dedup_action({}, "k", "a" * 64) == "PROPOSE_APPEND"
    assert dedup_action({"k": "a" * 64}, "k", "a" * 64) == "SKIP_IDENTICAL"
    assert dedup_action({"k": "a" * 64}, "k", "b" * 64) == "REJECT_CONFLICT"
    assert dedup_action({}, "", "a" * 64) == "REJECT_INVALID_KEY_OR_DIGEST"


def test_health_receipt_json_shape(tmp_path: Path):
    from scripts.agent_os_ci_evidence_health import build_health_receipt

    receipt = build_health_receipt(
        stream="pyan",
        classification="EVIDENCE_MISSING",
        run_id=1,
        run_attempt=1,
        job_id=7,
        head_sha="a" * 40,
        generate_outcome="failure",
        report_path=None,
    )
    assert receipt["schema"] == "agent-os-ci-evidence-health/1"
    assert receipt["stream"] == "pyan"
    assert receipt["classification"] == "EVIDENCE_MISSING"
    assert receipt["report_present"] is False
    text = json.dumps(receipt, sort_keys=True)
    assert json.loads(text) == receipt
