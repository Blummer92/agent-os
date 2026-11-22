"""D133: fail-closed CI evidence contracts and mutation-sensitive regression tests.

Tests only. Historical reference: 537dec4d295657cea6f8e70b0945bab3d07773c0.
No provider, Notion, GitHub or other external writes are performed.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from scripts.agent_os_ci_evidence_health import (
    StreamObservation,
    build_health_receipt,
    classify_stream,
    extract_subtest_markers,
    format_subtest_marker,
    validate_junit,
)
from scripts.agent_os_ci_evidence_collector import build_verified_receipt, classify_junit_artifact


HEAD = "a" * 40
RUN_ID = 100
AGGREGATE_JOB = "Run aggregate validation"


def _zip(members: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return output.getvalue()


def _junit_two_files() -> bytes:
    return (
        '<testsuites><testsuite name="pytest" tests="2" '
        'failures="0" errors="0" skipped="0">'
        '<testcase name="same" classname="" file="one.py"/>'
        '<testcase name="same" classname="" file="two.py"/>'
        '</testsuite></testsuites>'
    ).encode()


def _junit_one() -> bytes:
    return (
        '<testsuites><testsuite name="pytest" tests="1" '
        'failures="0" errors="0" skipped="0">'
        '<testcase classname="module" name="test_ok"/>'
        '</testsuite></testsuites>'
    ).encode()


def _marker() -> bytes:
    counts = {
        "passed": 2, "skipped": 0, "xfailed": 0, "failed": 0,
        "errors": 0, "subtests_passed": 1, "junit_tests": 3,
        "junit_sha256": "c" * 64,
    }
    return (format_subtest_marker(counts, "root") + "\n").encode()


def _observation(status: str) -> StreamObservation:
    return StreamObservation(
        stream="pyan", obligation="required",
        source_head=HEAD, reported_head=HEAD,
        run_attempt=1, artifact_attempt=1, job_id=7, artifact_job_id=7,
        artifact_present=True, artifact_expired=False, schema_valid=True,
        job_conclusion="success", scanner_status="completed",
        job_status=status, artifact_bytes=b"{}", claimed_sha256=None,
    )


def _health() -> dict:
    return build_health_receipt(
        stream="aggregate", classification="EVIDENCE_VALID",
        run_id=RUN_ID, run_attempt=1, job_id=7, head_sha=HEAD,
        generate_outcome="success", report_path="junit-aggregate.xml",
    )


def test_d133_foreign_job_marker_cannot_corroborate_with_job_only_binding() -> None:
    """Kills #13: AND -> OR must not broaden a one-sided scope binding."""
    correct = _zip({f"{AGGREGATE_JOB}/15_{AGGREGATE_JOB}.txt": _marker()})
    assert extract_subtest_markers(
        correct, job_name=AGGREGATE_JOB, step_name=None
    )["root"]["subtests_passed"] == 1
    foreign = _zip({f"Foreign job/15_{AGGREGATE_JOB}.txt": _marker()})
    with pytest.raises(ValueError, match="subtest-marker-out-of-scope"):
        extract_subtest_markers(foreign, job_name=AGGREGATE_JOB, step_name=None)
    benign = _zip({"Foreign job/01_other.txt": b"ordinary log\n"})
    assert extract_subtest_markers(
        benign, job_name=AGGREGATE_JOB, step_name=None
    ) == {}


def test_d133_queued_job_never_becomes_valid_completed_evidence() -> None:
    """Kills #17: queued is not a completed job even with green metadata."""
    for status in ("queued", "waiting", "in_progress"):
        assert classify_stream(_observation(status)) == "INCOMPLETE"
    assert classify_stream(_observation("completed")) == "EVIDENCE_VALID"


def test_d133_empty_classname_uses_file_for_distinct_junit_identity() -> None:
    """Kills #23: removal of reporter file fallback must be detected."""
    xml = _junit_two_files()
    ids, totals = validate_junit(xml)
    assert ids == ("pytest::one.py::same", "pytest::two.py::same")
    assert totals == {"tests": 2, "failures": 0, "errors": 0, "skipped": 0}
    collector = classify_junit_artifact(_zip({"root.xml": xml}))
    assert collector["classification"] == "EVIDENCE_VALID"
    assert collector["node_count"] == 2
    assert collector["counts"]["testcase_elements"] == 2


def test_d133_validate_junit_propagates_caller_maximum_size() -> None:
    """Kills #31: parser default must not override stricter caller bound."""
    xml = _junit_one()
    assert validate_junit(xml, max_bytes=len(xml))[1]["tests"] == 1
    with pytest.raises(ValueError, match="unsafe-or-empty-junit"):
        validate_junit(xml, max_bytes=len(xml) - 1)
    with pytest.raises(ValueError, match="unsafe-or-empty-junit"):
        validate_junit(xml, max_bytes=8)


def test_d133_health_receipt_preserves_run_id_exact_field() -> None:
    """Kills #33 and #36: malformed or case-changed identity keys."""
    result = _health()
    assert result["run_id"] == RUN_ID
    assert result["run_attempt"] == 1
    assert result["head_sha"] == HEAD
    assert "XXrun_idXX" not in result
    assert "RUN_ID" not in result
    assert result["merge_authority"] is False


def test_d133_health_receipt_preserves_report_path_exact_field() -> None:
    """Kills #34: machine-readable report_path may not be renamed."""
    result = _health()
    assert result["report_present"] is True
    assert result["report_path"] == "junit-aggregate.xml"
    assert "XXreport_pathXX" not in result


def test_d133_collector_accepts_distinct_nodes_but_rejects_missing_provenance() -> None:
    """Pure collector end-to-end positive and adversarial JUnit controls."""
    run = {
        "id": RUN_ID, "head_sha": HEAD,
        "path": ".github/workflows/agent-os-validation.yml",
        "status": "completed",
    }
    jobs = [
        {"id": 10, "name": "Run validation plan", "status": "completed",
         "conclusion": "success", "run_attempt": 1, "steps": []},
        {"id": 11, "name": AGGREGATE_JOB, "status": "completed",
         "conclusion": "success", "run_attempt": 1,
         "steps": [{"name": AGGREGATE_JOB, "conclusion": "success"}]},
    ]
    artifact = {
        "id": 82, "name": "junit-aggregate-1", "expired": False, "digest": None,
        "workflow_run": {"id": RUN_ID, "head_sha": HEAD},
    }

    def build(xml: dict[str, bytes]) -> dict:
        return build_verified_receipt(
            source_run=run, jobs=jobs, artifacts=[artifact],
            downloads={"82": _zip(xml)}, source_attempt=1,
            collector_head="c" * 40, live_trigger=False,
        )

    good = build({"root.xml": _junit_two_files()})
    assert good["streams"]["aggregate"]["classification"] == "EVIDENCE_VALID"
    assert good["streams"]["junit"]["junit-aggregate-1"]["node_count"] == 2
    assert good["sheets_written"] is False

    duplicate = build({"a.xml": _junit_one(), "b.xml": _junit_one()})
    assert duplicate["streams"]["aggregate"]["classification"] == "REJECT_SCHEMA"

    inflated = _junit_one().replace(b'tests="1"', b'tests="3"')
    without_receipt = build({"root.xml": inflated})
    assert without_receipt["streams"]["aggregate"]["classification"] == "REJECT_SCHEMA"
