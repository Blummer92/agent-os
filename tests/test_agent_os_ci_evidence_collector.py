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
        {"id": 9, "name": "Run validation plan", "conclusion": "success", "run_attempt": 2, "steps": []},
        {"id": 10, "name": "Run aggregate validation", "conclusion": "success", "run_attempt": 2,
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


# ---------------------------------------------------------------------------
# Step-log fetch route (Candidate A, verified on agent-os 2026-11-13):
# main() must fetch the bound aggregate step's log from the provider's
# step-log endpoint (jobs/{job_id}/steps/{step_number}/logs), resolving
# the step number from the provider's own jobs payload, and must fail
# closed with NO fallback to the job-scoped log route when the step
# identity is unresolved or the fetch fails.
# ---------------------------------------------------------------------------

import urllib.error as _urllib_error

from scripts import agent_os_ci_evidence_collector as _collector

_STEP_RUN_ID = 43241120512
_STEP_HEAD = "5e3d9f2ec70d672b67f191523e11bd32dfb464d7"
_STEP_JOB_ID = 131261469158
# Genuine marker line captured from the provider's step-log endpoint for
# run 43241120512 job 131261469158 step 15 (public repo evidence).
_REAL_MARKER_LINE = (
    "2026-11-12T14:56:16.3568886Z AGENT_OS_JUNIT_SUBTEST_RECEIPT suite=root"
    " passed=11877 skipped=31 xfailed=1 failed=0 errors=0 subtests_passed=119"
    " junit_tests=12028"
    " junit_sha256=fc16b2d2ef9d7b7273f3f53af5f9fedf5c639e7db90f293fbeefa812e42d6dd4\n"
).encode()


def _step(n: int, name: str, conclusion: str = "success", status: str = "completed") -> dict:
    return {"number": n, "name": name, "status": status, "conclusion": conclusion}


# Modeled on the provider's real step list for job 131261469158 (run
# 43241120512): 21 steps in the live payload, several skipped; the
# aggregate step is 15. This fixture keeps a representative subset.
_REAL_SHAPE_STEPS = [
    _step(1, "Set up job"),
    _step(2, "Check out workflow source for ingress verification", "skipped"),
    _step(3, "Admit exact-head Draft final candidate"),
    _step(7, "Check out repository"),
    _step(10, "Recover missing exact-current main aggregate evidence", "skipped"),
    _step(11, "Stop candidate while exact-current main recovery runs", "skipped"),
    _step(13, "Set up Python"),
    _step(14, "Install validation dependencies"),
    _step(15, "Run aggregate validation"),
    _step(16, "Record not-executed infrastructure receipt", "skipped"),
    _step(17, "Upload aggregate JUnit evidence"),
    _step(18, "Publish validation summary"),
    _step(37, "Complete job"),
]


def _step_job(steps, conclusion: str = "success") -> dict:
    return {
        "id": _STEP_JOB_ID,
        "name": "Run aggregate validation",
        "conclusion": conclusion,
        "run_id": _STEP_RUN_ID,
        "run_attempt": 1,
        "steps": steps,
    }


def test_resolve_aggregate_step_number_real_shape() -> None:
    assert _collector.resolve_aggregate_step_number(_step_job(_REAL_SHAPE_STEPS)) == 15


def test_resolve_aggregate_step_number_unresolved_and_ambiguous() -> None:
    # Only a skipped aggregate step: it did not execute, cannot corroborate.
    with pytest.raises(ValueError, match="aggregate-step-unresolved"):
        _collector.resolve_aggregate_step_number(_step_job([_step(15, "Run aggregate validation", "skipped")]))
    # No same-named step at all.
    with pytest.raises(ValueError, match="aggregate-step-unresolved"):
        _collector.resolve_aggregate_step_number(_step_job([_step(1, "Set up job")]))
    # Missing steps payload.
    with pytest.raises(ValueError, match="aggregate-step-unresolved"):
        _collector.resolve_aggregate_step_number({"id": _STEP_JOB_ID, "steps": None})
    # Two executed same-named steps: provider anomaly, never a choice.
    dup = [_step(15, "Run aggregate validation"), _step(16, "Run aggregate validation")]
    with pytest.raises(ValueError, match="aggregate-step-ambiguous"):
        _collector.resolve_aggregate_step_number(_step_job(dup))
    # A still-running same-named step cannot corroborate yet.
    with pytest.raises(ValueError, match="aggregate-step-unresolved"):
        _collector.resolve_aggregate_step_number(
            _step_job([_step(15, "Run aggregate validation", None, "in_progress")]))


def _patch_provider(monkeypatch, jobs, bytes_handler):
    run_payload = {
        "id": _STEP_RUN_ID,
        "head_sha": _STEP_HEAD,
        "path": ".github/workflows/agent-os-validation.yml",
        "status": "completed",
    }

    def fake_api_get(url, token):
        if "/attempts/" in url:
            return {"jobs": jobs}, {}
        if url.endswith("/artifacts?per_page=100"):
            return {"artifacts": []}, {}
        return dict(run_payload), {}

    monkeypatch.setattr(_collector, "_api_get", fake_api_get)
    monkeypatch.setattr(_collector, "_api_get_bytes", bytes_handler)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Blummer92/agent-os")
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)


def _run_main(tmp_path) -> tuple[int, dict]:
    out = tmp_path / "receipt.json"
    rc = _collector.main([
        "--source-run-id", str(_STEP_RUN_ID),
        "--source-head", _STEP_HEAD,
        "--source-attempt", "1",
        "--output", str(out),
    ])
    return rc, json.loads(out.read_text())


def test_main_fetches_bound_step_log_route(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    def fake_bytes(url, token):
        calls.append(url)
        return _REAL_MARKER_LINE

    _patch_provider(monkeypatch, [_step_job(_REAL_SHAPE_STEPS)], fake_bytes)
    rc, receipt = _run_main(tmp_path)
    assert rc == 0
    assert calls == [
        f"https://api.github.com/repos/Blummer92/agent-os/actions/jobs/{_STEP_JOB_ID}/steps/15/logs"
    ]
    assert receipt["subtest_log_corroboration"] == "ok"


def test_main_uses_provider_step_number_not_observed_position(monkeypatch, tmp_path) -> None:
    # The step number comes from the provider payload, never a hardcoded
    # position: same job shape but the aggregate step sits at number 7
    # (the real job has it at 15).
    calls: list[str] = []

    def fake_bytes(url, token):
        calls.append(url)
        return _REAL_MARKER_LINE

    steps = [
        _step(1, "Set up job"),
        _step(7, "Run aggregate validation"),
        _step(9, "Complete job"),
    ]
    assert _collector.resolve_aggregate_step_number(_step_job(steps)) == 7
    _patch_provider(monkeypatch, [_step_job(steps)], fake_bytes)
    rc, receipt = _run_main(tmp_path)
    assert rc == 0
    assert calls == [
        f"https://api.github.com/repos/Blummer92/agent-os/actions/jobs/{_STEP_JOB_ID}/steps/7/logs"
    ]
    assert receipt["subtest_log_corroboration"] == "ok"


def test_main_step_unresolved_fetches_no_log(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    def fake_bytes(url, token):
        calls.append(url)
        return _REAL_MARKER_LINE

    job = _step_job([_step(15, "Run aggregate validation", "skipped")])
    _patch_provider(monkeypatch, [job], fake_bytes)
    rc, receipt = _run_main(tmp_path)
    assert rc == 0
    # Fail closed: no log URL is fetched at all when the step identity
    # is unresolved - in particular no silent job-scoped fallback.
    assert [u for u in calls if u.endswith("/logs")] == []
    assert receipt["subtest_log_corroboration"] == "unavailable"
    assert receipt["subtest_log_error"]["stage"] == "aggregate_step_resolution"


def test_main_step_log_fetch_failure_has_no_fallback(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    def fake_bytes(url, token):
        calls.append(url)
        raise RuntimeError("provider download failed: HTTP 404") from _urllib_error.HTTPError(
            url, 404, "not found", {}, None)

    _patch_provider(monkeypatch, [_step_job(_REAL_SHAPE_STEPS)], fake_bytes)
    rc, receipt = _run_main(tmp_path)
    assert rc == 0
    # Exactly one attempt, at the step route; the job-scoped route is
    # never tried.
    assert calls == [
        f"https://api.github.com/repos/Blummer92/agent-os/actions/jobs/{_STEP_JOB_ID}/steps/15/logs"
    ]
    assert receipt["subtest_log_corroboration"] == "unavailable"
    assert receipt["subtest_log_error"]["stage"] == "aggregate_step_log_download"
    assert receipt["subtest_log_error"]["http_status"] == 404


def test_main_duplicate_aggregate_steps_fail_closed(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    def fake_bytes(url, token):
        calls.append(url)
        return _REAL_MARKER_LINE

    dup = [_step(15, "Run aggregate validation"), _step(16, "Run aggregate validation")]
    _patch_provider(monkeypatch, [_step_job(dup)], fake_bytes)
    rc, receipt = _run_main(tmp_path)
    assert rc == 0
    assert [u for u in calls if u.endswith("/logs")] == []
    assert receipt["subtest_log_corroboration"] == "unavailable"
    assert receipt["subtest_log_error"]["stage"] == "aggregate_step_resolution"
