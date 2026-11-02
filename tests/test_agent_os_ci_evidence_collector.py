from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from scripts.agent_os_ci_evidence_collector import (
    build_collector_receipt,
    validate_archive_members,
)


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_archive_traversal_rejected():
    with pytest.raises(ValueError):
        validate_archive_members(_zip_bytes({"../evil.txt": b"x"}))
    with pytest.raises(ValueError):
        validate_archive_members(_zip_bytes({"/abs.txt": b"x"}))


def test_archive_duplicate_and_oversize_rejected():
    # Duplicate names are rejected by construction of the member list.
    from scripts.agent_os_ci_evidence_collector import validate_archive_member_names

    with pytest.raises(ValueError):
        validate_archive_member_names(["a.xml", "a.xml"])
    with pytest.raises(ValueError):
        validate_archive_members(_zip_bytes({"a.xml": b"x" * 10}), max_total_bytes=5)


def test_archive_symlink_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("link.xml")
        info.external_attr = 0o120777 << 16  # symlink
        zf.writestr(info, b"target")
    with pytest.raises(ValueError):
        validate_archive_members(buf.getvalue())


def test_collector_receipt_per_stream_and_source_head():
    receipt = build_collector_receipt(
        source_run_id=41213379091,
        source_run_attempt=1,
        source_head="a" * 40,
        collector_head="c" * 40,
        streams=[
            {
                "stream": "pyan",
                "obligation": "required",
                "reported_head": "a" * 40,
                "artifact_attempt": 1,
                "job_id": 7,
                "artifact_job_id": 7,
                "artifact_present": False,
                "artifact_expired": False,
                "schema_valid": True,
                "job_conclusion": "success",
            },
            {
                "stream": "aggregate",
                "obligation": "deferred",
                "reported_head": "a" * 40,
                "artifact_attempt": 1,
                "job_id": 8,
                "artifact_job_id": 8,
                "artifact_present": False,
                "artifact_expired": False,
                "schema_valid": True,
                "job_conclusion": "skipped",
            },
        ],
        junit_files={},
    )
    assert receipt["schema"] == "agent-os-ci-evidence-collector/1"
    assert receipt["source_head"] == "a" * 40
    assert receipt["collector_head"] == "c" * 40
    assert receipt["streams"]["pyan"] == "EVIDENCE_MISSING"
    assert receipt["streams"]["aggregate"] == "INTENTIONALLY_DEFERRED"
    assert receipt["live_trigger"] is False
    assert receipt["sheets_written"] is False


def test_collector_receipt_wrong_head_and_reused():
    receipt = build_collector_receipt(
        source_run_id=1,
        source_run_attempt=1,
        source_head="a" * 40,
        collector_head="a" * 40,
        streams=[
            {
                "stream": "pyan",
                "obligation": "required",
                "reported_head": "b" * 40,
                "artifact_attempt": 1,
                "job_id": 7,
                "artifact_job_id": 7,
                "artifact_present": True,
                "artifact_expired": False,
                "schema_valid": True,
                "job_conclusion": "success",
            },
            {
                "stream": "aggregate",
                "obligation": "reused",
                "reported_head": "a" * 40,
                "artifact_attempt": 1,
                "job_id": 8,
                "artifact_job_id": 8,
                "artifact_present": True,
                "artifact_expired": False,
                "schema_valid": True,
                "job_conclusion": "success",
            },
        ],
        junit_files={},
    )
    assert receipt["streams"]["pyan"] == "REJECT_WRONG_HEAD"
    assert receipt["streams"]["aggregate"] == "REUSED_SOURCE_REQUIRED"


def test_collector_receipt_junit_valid_and_malformed():
    good = (
        '<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="1" '
        'failures="0" errors="0" skipped="0"><testcase classname="m" name="t"/></testsuite></testsuites>'
    ).encode()
    receipt = build_collector_receipt(
        source_run_id=1,
        source_run_attempt=1,
        source_head="a" * 40,
        collector_head="a" * 40,
        streams=[],
        junit_files={"root.xml": good, "bad.xml": b"not xml"},
    )
    assert receipt["junit"]["root.xml"]["classification"] == "EVIDENCE_VALID"
    assert receipt["junit"]["root.xml"]["counts"]["tests"] == 1
    assert receipt["junit"]["bad.xml"]["classification"] == "REJECT_SCHEMA"
    assert receipt["junit"]["bad.xml"]["counts"] is None


# ---- Pre-merge correction tests (P0/P1) — written red before the fix ----

from scripts.agent_os_ci_evidence_collector import (
    ARTIFACT_PREFIXES,
    aggregate_obligation,
    classify_advisory_artifact,
    classify_junit_artifact,
    job_by_name,
    select_advisory_artifact,
    verify_source_run,
)

HEAD = "b" * 40


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _pyan_report(status: str = "ok", head: str = HEAD) -> bytes:
    return json.dumps(
        {"tool": "pyan3", "schema": "agent-os-pyan3-advisory/1", "status": status, "head_sha": head}
    ).encode()


def _artifact(name: str, artifact_id: int = 1, **kw) -> dict:
    d = {"id": artifact_id, "name": name, "expired": False, "digest": None, "workflow_run": {"id": 100, "head_sha": HEAD}}
    d.update(kw)
    return d


def test_p0_pyan3_artifact_name_is_found():
    arts = [_artifact("pyan3-advisory-3755", 11), _artifact("jscpd-advisory-3755", 12)]
    found = select_advisory_artifact(arts, "pyan")
    assert found is not None and found["id"] == 11
    assert ARTIFACT_PREFIXES["pyan"] == "pyan3-advisory"


def test_p0_wrong_pyan_prefix_does_not_match():
    arts = [_artifact("pyan-advisory-3755", 11)]
    assert select_advisory_artifact(arts, "pyan") is None


def test_p0_jscpd_control_still_matches():
    arts = [_artifact("jscpd-advisory-3755", 12)]
    assert select_advisory_artifact(arts, "jscpd")["id"] == 12


def test_p0_attempt_suffix_selects_current_attempt_only():
    arts = [_artifact("pyan3-advisory-3755-attempt-1", 21), _artifact("pyan3-advisory-3755-attempt-2", 22)]
    assert select_advisory_artifact(arts, "pyan", source_attempt=2)["id"] == 22
    assert select_advisory_artifact(arts, "pyan", source_attempt=1)["id"] == 21


def test_p1_duplicate_artifact_name_is_rejected():
    arts = [_artifact("pyan3-advisory-3755", 11), _artifact("pyan3-advisory-3755", 13)]
    with pytest.raises(ValueError):
        select_advisory_artifact(arts, "pyan")


def test_p1_verify_source_run_rejects_wrong_head_and_wrong_path():
    run = {"id": 100, "head_sha": HEAD, "path": ".github/workflows/agent-os-validation.yml", "status": "completed"}
    verify_source_run(run, expected_run_id=100, expected_head=HEAD)
    with pytest.raises(ValueError):
        verify_source_run(run, expected_run_id=100, expected_head="c" * 40)
    with pytest.raises(ValueError):
        verify_source_run({**run, "path": ".github/workflows/other.yml"}, expected_run_id=100, expected_head=HEAD)
    with pytest.raises(ValueError):
        verify_source_run({**run, "status": "in_progress"}, expected_run_id=100, expected_head=HEAD)


def test_p1_job_by_name_filters_attempt_and_rejects_duplicates():
    jobs = [{"id": 1, "name": "pyan3 call-graph advisory", "conclusion": "success", "run_attempt": 1},
            {"id": 2, "name": "pyan3 call-graph advisory", "conclusion": "success", "run_attempt": 2}]
    assert job_by_name(jobs, "pyan3 call-graph advisory", expected_attempt=2)["id"] == 2
    assert job_by_name(jobs, "missing job") is None
    with pytest.raises(ValueError):
        job_by_name(jobs + [{"id": 3, "name": "pyan3 call-graph advisory", "conclusion": "success", "run_attempt": 2}],
                    "pyan3 call-graph advisory", expected_attempt=2)


def test_p1_aggregate_obligation_skipped_deferred_reused_required():
    assert aggregate_obligation({"conclusion": "skipped", "steps": []}) == "deferred"
    assert aggregate_obligation({"conclusion": "success", "steps": [{"name": "Run aggregate validation", "conclusion": "skipped"}]}) == "reused"
    assert aggregate_obligation({"conclusion": "success", "steps": [{"name": "Run aggregate validation", "conclusion": "success"}]}) == "required"
    assert aggregate_obligation(None) == "not_applicable"


def test_p1_downloaded_pyan_artifact_validates_and_checks_digest():
    data = _zip({"pyan3-advisory.json": _pyan_report()})
    art = _artifact("pyan3-advisory-3755", digest="sha256:" + hashlib.sha256(data).hexdigest())
    job = {"id": 7, "name": "pyan3 call-graph advisory", "conclusion": "success", "run_attempt": 1}
    out = classify_advisory_artifact(stream="pyan", artifact=art, zip_bytes=data, expected_head=HEAD, job=job, source_run_id=100, source_attempt=1)
    assert out["classification"] == "EVIDENCE_VALID" and out["digest_checked"] is True
    assert out["job_binding"] == "BY_NAME_DESIGN"


def test_p1_downloaded_controls_wrong_head_attempt_expired_digest_scanner():
    data = _zip({"pyan3-advisory.json": _pyan_report()})
    job = {"id": 7, "name": "pyan3 call-graph advisory", "conclusion": "success", "run_attempt": 1}
    kw = dict(stream="pyan", zip_bytes=data, expected_head=HEAD, source_run_id=100, source_attempt=1)
    assert classify_advisory_artifact(artifact=_artifact("pyan3-advisory-3755", workflow_run={"id": 100, "head_sha": "c" * 40}), job=job, **kw)["classification"] == "REJECT_WRONG_HEAD"
    assert classify_advisory_artifact(artifact=_artifact("pyan3-advisory-3755"), job={**job, "run_attempt": 2}, **kw)["classification"] == "REJECT_WRONG_ATTEMPT"
    assert classify_advisory_artifact(artifact=_artifact("pyan3-advisory-3755", expired=True), job=job, **kw)["classification"] == "REJECT_EXPIRED"
    assert classify_advisory_artifact(artifact=_artifact("pyan3-advisory-3755", digest="sha256:" + "0" * 64), job=job, **kw)["classification"] == "REJECT_DIGEST"
    bad = _zip({"pyan3-advisory.json": _pyan_report(status="scanner-error")})
    assert classify_advisory_artifact(stream="pyan", artifact=_artifact("pyan3-advisory-3755"), zip_bytes=bad, expected_head=HEAD, job=job, source_run_id=100, source_attempt=1)["classification"] == "REJECT_SCANNER_ERROR"
    assert classify_advisory_artifact(artifact=None, job=job, **kw)["classification"] == "EVIDENCE_MISSING"
    assert classify_advisory_artifact(stream="pyan", artifact=_artifact("pyan3-advisory-3755"), zip_bytes=b"not a zip", expected_head=HEAD, job=job, source_run_id=100, source_attempt=1)["classification"] == "REJECT_SCHEMA"
    assert classify_advisory_artifact(artifact=_artifact("pyan3-advisory-3755"), job={**job, "conclusion": "failure"}, **kw)["classification"] == "REJECT_JOB_NOT_SUCCESS"


def test_p1_junit_artifact_classification():
    xml = b'<testsuites><testsuite name="s" tests="1" failures="0" errors="0" skipped="0"><testcase classname="c" name="n"/></testsuite></testsuites>'
    out = classify_junit_artifact(_zip({"00.xml": xml}))
    assert out["classification"] == "EVIDENCE_VALID" and out["node_count"] == 1
    assert classify_junit_artifact(_zip({"a.xml": xml, "b.xml": xml}))["classification"] == "REJECT_SCHEMA"
    assert classify_junit_artifact(_zip({"manifest.tsv": b"a\tb"}))["classification"] == "EVIDENCE_MISSING"
    assert classify_junit_artifact(b"garbage")["classification"] == "REJECT_SCHEMA"


def test_p1_build_verified_receipt_draft_skipped_aggregate():
    from scripts.agent_os_ci_evidence_collector import build_verified_receipt

    data = _zip({"pyan3-advisory.json": _pyan_report()})
    run = {"id": 100, "head_sha": HEAD, "path": ".github/workflows/agent-os-validation.yml", "status": "completed"}
    jobs = [
        {"id": 7, "name": "pyan3 call-graph advisory", "conclusion": "success", "run_attempt": 1, "steps": []},
        {"id": 8, "name": "jscpd duplicate-code advisory", "conclusion": "success", "run_attempt": 1, "steps": []},
        {"id": 9, "name": "Run validation plan", "conclusion": "success", "run_attempt": 1, "steps": []},
        {"id": 10, "name": "Run aggregate validation", "conclusion": "skipped", "run_attempt": 1, "steps": []},
    ]
    arts = [_artifact("pyan3-advisory-3755", 11)]
    receipt = build_verified_receipt(source_run=run, jobs=jobs, artifacts=arts, downloads={"11": data}, source_attempt=1, collector_head="c" * 40, live_trigger=False)
    assert receipt["streams"]["pyan"]["classification"] == "EVIDENCE_VALID"
    assert receipt["streams"]["jscpd"]["classification"] == "EVIDENCE_MISSING"
    assert receipt["streams"]["aggregate"]["classification"] == "INTENTIONALLY_DEFERRED"
    assert receipt["per_job_join"] == "NOT_IMPLEMENTED_EXACT"
    assert receipt["sheets_written"] is False


def test_p1_health_receipt_conflict_downgrades_report():
    from scripts.agent_os_ci_evidence_collector import health_classification_from_zip

    data = _zip({"pyan3-advisory.json": _pyan_report()})
    job = {"id": 7, "name": "pyan3 call-graph advisory", "conclusion": "success", "run_attempt": 1}
    art = _artifact("pyan3-advisory-3755")
    assert health_classification_from_zip(_zip({"pyan3-health.json": json.dumps({"classification": "EVIDENCE_MISSING"}).encode()})) == "EVIDENCE_MISSING"
    assert classify_advisory_artifact(stream="pyan", artifact=art, zip_bytes=data, expected_head=HEAD, job=job, source_run_id=100, source_attempt=1, health_classification="EVIDENCE_MISSING")["classification"] == "REJECT_SCHEMA"
    assert classify_advisory_artifact(stream="pyan", artifact=art, zip_bytes=data, expected_head=HEAD, job=job, source_run_id=100, source_attempt=1, health_classification="EVIDENCE_VALID")["classification"] == "EVIDENCE_VALID"


def test_p1_wrong_attempt_junit_and_health_are_not_selected():
    from scripts.agent_os_ci_evidence_collector import build_verified_receipt

    xml = b'<testsuites><testsuite name="s" tests="1" failures="0" errors="0" skipped="0"><testcase classname="c" name="n"/></testsuite></testsuites>'
    run = {"id": 100, "head_sha": HEAD, "path": ".github/workflows/agent-os-validation.yml", "status": "completed"}
    jobs = [
        {"id": 7, "name": "pyan3 call-graph advisory", "conclusion": "success", "run_attempt": 2, "steps": []},
        {"id": 8, "name": "jscpd duplicate-code advisory", "conclusion": "skipped", "run_attempt": 2, "steps": []},
        {"id": 9, "name": "Run validation plan", "conclusion": "success", "run_attempt": 2,
         "steps": [{"name": "Run aggregate validation", "conclusion": "success"}]},
    ]
    arts = [_artifact("junit-aggregate-1", 31)]
    receipt = build_verified_receipt(source_run=run, jobs=jobs, artifacts=arts, downloads={"31": _zip({"00.xml": xml})}, source_attempt=2, collector_head="c" * 40, live_trigger=False)
    assert receipt["streams"]["aggregate"]["classification"] == "EVIDENCE_MISSING"
    assert "junit-aggregate-1" not in receipt.get("junit", {})

# #3762 Copilot review: the aggregate job is distinct from the plan job.
def _receipt_jobs(aggregate_conclusion="skipped", aggregate_step="skipped"):
    return [
        {"id": 10, "name": "Run validation plan", "status": "completed",
         "conclusion": "success", "run_attempt": 1, "steps": []},
        {"id": 11, "name": "Run aggregate validation", "status": "completed",
         "conclusion": aggregate_conclusion, "run_attempt": 1,
         "steps": [{"name": "Run aggregate validation", "conclusion": aggregate_step}]},
    ]


def _receipt_for_aggregate(jobs, artifacts=(), downloads=None):
    from scripts.agent_os_ci_evidence_collector import build_verified_receipt
    run = {"id": 100, "head_sha": HEAD,
           "path": ".github/workflows/agent-os-validation.yml", "status": "completed"}
    return build_verified_receipt(
        source_run=run, jobs=list(jobs), artifacts=list(artifacts),
        downloads=downloads or {}, source_attempt=1,
        collector_head="c" * 40, live_trigger=False,
    )


def test_review_3762_draft_plan_success_does_not_override_aggregate_skip():
    xml = b'<testsuites><testsuite name="s" tests="1" failures="0" errors="0" skipped="0"><testcase classname="c" name="n"/></testsuite></testsuites>'
    focused = _artifact("junit-plan-focused-1", 81)
    receipt = _receipt_for_aggregate(
        _receipt_jobs(), [focused], {"81": _zip({"focused.xml": xml})})
    assert receipt["streams"]["aggregate"]["classification"] == "INTENTIONALLY_DEFERRED"
    assert "junit" not in receipt["streams"]


def test_review_3762_focused_junit_cannot_substitute_for_missing_aggregate():
    xml = b'<testsuites><testsuite name="s" tests="1" failures="0" errors="0" skipped="0"><testcase classname="c" name="n"/></testsuite></testsuites>'
    focused = _artifact("junit-plan-focused-1", 81)
    receipt = _receipt_for_aggregate(
        _receipt_jobs("success", "success"), [focused],
        {"81": _zip({"focused.xml": xml})})
    assert receipt["streams"]["aggregate"]["classification"] == "EVIDENCE_MISSING"
    assert receipt["streams"]["junit"]["junit-plan-focused-1"]["classification"] == "EVIDENCE_VALID"


def test_review_3762_aggregate_junit_required_and_provider_unavailable_preserved():
    xml = b'<testsuites><testsuite name="s" tests="1" failures="0" errors="0" skipped="0"><testcase classname="c" name="n"/></testsuite></testsuites>'
    artifact = _artifact("junit-aggregate-1", 82)
    jobs = _receipt_jobs("success", "success")
    missing_download = _receipt_for_aggregate(jobs, [artifact])
    assert missing_download["streams"]["aggregate"]["classification"] == "PROVIDER_UNAVAILABLE"
    valid = _receipt_for_aggregate(jobs, [artifact], {"82": _zip({"aggregate.xml": xml})})
    assert valid["streams"]["aggregate"]["classification"] == "EVIDENCE_VALID"
    invalid = _receipt_for_aggregate(jobs, [artifact], {"82": _zip({"aggregate.xml": b"broken"})})
    assert invalid["streams"]["aggregate"]["classification"] == "REJECT_SCHEMA"
    failed_job = _receipt_for_aggregate(
        _receipt_jobs("failure", "failure"), [artifact], {"82": _zip({"aggregate.xml": xml})})
    assert failed_job["streams"]["aggregate"]["classification"] == "REJECT_JOB_NOT_SUCCESS"


def test_review_3762_zip_member_read_errors_reject_schema(monkeypatch):
    from scripts.agent_os_ci_evidence_collector import classify_junit_artifact
    xml = b'<testsuites><testsuite name="s" tests="1" failures="0" errors="0" skipped="0"><testcase classname="c" name="n"/></testsuite></testsuites>'
    zip_bytes = _zip({"aggregate.xml": xml})
    for error in (zipfile.BadZipFile("bad member"), RuntimeError("unsupported compression"),
                  KeyError("missing member")):
        with monkeypatch.context() as patch:
            def fail_read(self, name, *args, _error=error, **kwargs):
                raise _error
            patch.setattr(zipfile.ZipFile, "read", fail_read)
            assert classify_junit_artifact(zip_bytes)["classification"] == "REJECT_SCHEMA"


def test_review_3762_duplicate_or_expired_aggregate_cannot_be_green():
    xml = b'<testsuites><testsuite name="s" tests="1" failures="0" errors="0" skipped="0"><testcase classname="c" name="n"/></testsuite></testsuites>'
    zipped = _zip({"aggregate.xml": xml})
    artifacts = [_artifact("junit-aggregate-1", 82), _artifact("junit-aggregate-1", 83)]
    receipt = _receipt_for_aggregate(_receipt_jobs("success", "success"), artifacts,
                                     {"82": zipped, "83": zipped})
    assert receipt["streams"]["aggregate"]["classification"] == "REJECT_SCHEMA"
    expired = _receipt_for_aggregate(
        _receipt_jobs("success", "success"),
        [_artifact("junit-aggregate-1", 82, expired=True)], {"82": zipped})
    assert expired["streams"]["aggregate"]["classification"] == "REJECT_EXPIRED"
