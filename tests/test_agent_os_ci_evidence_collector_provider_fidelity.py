"""Provider-fidelity correction tests for the CI evidence collector.

Covers the 2026-11-02 independent review matrix PF01-PF11: attempt
identity must never fall back to an older attempt's artifact, scanner
cause must survive a missing report via the verified health receipt,
and the exact-attempt jobs endpoint must be used. These tests are
independent controls: they assert the corrected behavior and would
have failed (false-green / lost-cause) on the uncorrected patch.
"""
import io
import json
import zipfile

import pytest

from scripts.agent_os_ci_evidence_collector import (
    advisory_step_outcome,
    build_verified_receipt,
    classify_advisory_artifact,
    explicit_attempt_mismatch,
    health_classification_from_zip,
    job_by_name,
    legacy_unbound,
    select_advisory_artifact,
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
    d = {"id": artifact_id, "name": name, "expired": False, "digest": None,
         "workflow_run": {"id": 100, "head_sha": HEAD}}
    d.update(kw)
    return d


def _job(attempt: int = 2, **kw) -> dict:
    d = {"id": 7, "name": "pyan3 call-graph advisory", "conclusion": "success",
         "status": "completed", "run_id": 100, "run_attempt": attempt, "steps": []}
    d.update(kw)
    return d


def _rest_job(attempt: int = 2) -> dict:
    """Real GitHub REST jobs shape: steps carry name/status/conclusion/
    number only -- never 'outcome'. Verified live on #3756 job 125033542049."""
    return _job(attempt=attempt, steps=[
        {"name": "Generate report-only pyan3 evidence", "status": "completed",
         "conclusion": "success", "number": 5},
    ])


def _health_zip(classification: str, **fields) -> bytes:
    payload = {"schema": "agent-os-ci-evidence-health/1", "classification": classification,
               "run_id": 100, "run_attempt": 2, "head_sha": HEAD}
    payload.update(fields)
    return _zip({"pyan3-health.json": json.dumps(payload).encode()})


# PF01 -- selection never falls back to an explicitly mismatched attempt.
def test_pf01_no_fallback_to_older_attempt_artifact():
    arts = [_artifact("pyan3-advisory-3756-attempt-1", 15)]
    assert select_advisory_artifact(arts, "pyan", source_attempt=2) is None
    assert explicit_attempt_mismatch(arts, "pyan", 2) is True


def test_pf01_current_attempt_and_legacy_policy():
    arts = [_artifact("pyan3-advisory-3756-attempt-1", 15),
            _artifact("pyan3-advisory-3756-attempt-2", 16)]
    assert select_advisory_artifact(arts, "pyan", source_attempt=2)["id"] == 16
    legacy = [_artifact("pyan3-advisory-3756", 17)]
    assert select_advisory_artifact(legacy, "pyan", source_attempt=1)["id"] == 17
    assert select_advisory_artifact(legacy, "pyan", source_attempt=2) is None
    assert legacy_unbound(legacy, "pyan", 2) is True
    assert legacy_unbound(legacy, "pyan", 1) is False


# PF02 -- classifier validates attempt identity itself, without the selector.
def test_pf02_classifier_rejects_mismatched_artifact_directly():
    data = _zip({"pyan3-advisory.json": _pyan_report()})
    out = classify_advisory_artifact(
        stream="pyan", artifact=_artifact("pyan3-advisory-3756-attempt-1", 15),
        zip_bytes=data, expected_head=HEAD, job=_job(2), source_run_id=100, source_attempt=2)
    assert out["classification"] == "REJECT_WRONG_ATTEMPT"
    out = classify_advisory_artifact(
        stream="pyan", artifact=_artifact("pyan3-advisory-3756-attempt-2", 16),
        zip_bytes=data, expected_head=HEAD, job=_job(2), source_run_id=100, source_attempt=2)
    assert out["classification"] == "EVIDENCE_VALID"
    out = classify_advisory_artifact(
        stream="pyan", artifact=_artifact("pyan3-advisory-3756", 17),
        zip_bytes=data, expected_head=HEAD, job=_job(2), source_run_id=100, source_attempt=2)
    assert out["classification"] == "EVIDENCE_MISSING"
    assert "not attempt-bound" in out.get("detail", "")


# PF03 -- whole receipt: attempt-2 job + only attempt-1 artifact.
def test_pf03_receipt_rejects_wrong_attempt_and_accepts_current():
    run = {"id": 100, "head_sha": HEAD, "path": ".github/workflows/agent-os-validation.yml", "status": "completed"}
    jobs = [_job(2), {"id": 8, "name": "jscpd duplicate-code advisory", "conclusion": "skipped", "run_attempt": 2},
            {"id": 9, "name": "Run validation plan", "conclusion": "skipped", "run_attempt": 2}]
    data = _zip({"pyan3-advisory.json": _pyan_report()})
    receipt = build_verified_receipt(
        source_run=run, jobs=jobs, artifacts=[_artifact("pyan3-advisory-3756-attempt-1", 15)],
        downloads={"15": data}, source_attempt=2, collector_head="c" * 40, live_trigger=False)
    assert receipt["streams"]["pyan"]["classification"] == "REJECT_WRONG_ATTEMPT"
    receipt = build_verified_receipt(
        source_run=run, jobs=jobs, artifacts=[_artifact("pyan3-advisory-3756-attempt-2", 16)],
        downloads={"16": data}, source_attempt=2, collector_head="c" * 40, live_trigger=False)
    assert receipt["streams"]["pyan"]["classification"] == "EVIDENCE_VALID"


# PF04 -- health artifacts follow the same attempt policy.
def test_pf04_health_attempt_mismatch_not_used_and_match_used():
    run = {"id": 100, "head_sha": HEAD, "path": ".github/workflows/agent-os-validation.yml", "status": "completed"}
    jobs = [_job(2), {"id": 8, "name": "jscpd duplicate-code advisory", "conclusion": "skipped", "run_attempt": 2},
            {"id": 9, "name": "Run validation plan", "conclusion": "skipped", "run_attempt": 2}]
    data = _zip({"pyan3-advisory.json": _pyan_report()})
    health_old = _artifact("pyan3-health-3756-attempt-1", 21)
    receipt = build_verified_receipt(
        source_run=run, jobs=jobs, artifacts=[_artifact("pyan3-advisory-3756-attempt-2", 16), health_old],
        downloads={"16": data, "21": _health_zip("REJECT_SCANNER_ERROR", run_attempt=1)},
        source_attempt=2, collector_head="c" * 40, live_trigger=False)
    assert receipt["streams"]["pyan"]["classification"] == "EVIDENCE_VALID"
    health_now = _artifact("pyan3-health-3756-attempt-2", 22)
    receipt = build_verified_receipt(
        source_run=run, jobs=jobs, artifacts=[_artifact("pyan3-advisory-3756-attempt-2", 16), health_now],
        downloads={"16": data, "22": _health_zip("REJECT_SCANNER_ERROR")},
        source_attempt=2, collector_head="c" * 40, live_trigger=False)
    assert receipt["streams"]["pyan"]["classification"] == "REJECT_SCHEMA"


def test_pf04_health_receipt_identity_verified():
    assert health_classification_from_zip(_health_zip("EVIDENCE_VALID"), source_run_id=100, source_attempt=2, expected_head=HEAD) == "EVIDENCE_VALID"
    assert health_classification_from_zip(_health_zip("EVIDENCE_VALID"), source_run_id=999, source_attempt=2, expected_head=HEAD) is None
    assert health_classification_from_zip(_health_zip("EVIDENCE_VALID"), source_run_id=100, source_attempt=1, expected_head=HEAD) is None
    assert health_classification_from_zip(_health_zip("EVIDENCE_VALID"), source_run_id=100, source_attempt=2, expected_head="c" * 40) is None
    assert health_classification_from_zip(_health_zip("EVIDENCE_VALID", generate_outcome="failure"), source_run_id=100, source_attempt=2, expected_head=HEAD) == "REJECT_SCANNER_ERROR"


# PF05/PF06 -- REST-shaped job, absent report, health scanner error preserved.
def test_pf05_pf06_rest_job_scanner_cause_preserved_when_report_absent():
    assert advisory_step_outcome(_rest_job()) is None
    out = classify_advisory_artifact(
        stream="pyan", artifact=None, zip_bytes=None, expected_head=HEAD, job=_rest_job(),
        source_run_id=100, source_attempt=2, health_classification="REJECT_SCANNER_ERROR")
    assert out["classification"] == "REJECT_SCANNER_ERROR"
    assert out["missing_report"] is True
    out = classify_advisory_artifact(
        stream="pyan", artifact=None, zip_bytes=None, expected_head=HEAD, job=_rest_job(),
        source_run_id=100, source_attempt=2, health_classification=None)
    assert out["classification"] == "EVIDENCE_MISSING"
    out = classify_advisory_artifact(
        stream="pyan", artifact=None, zip_bytes=None, expected_head=HEAD, job=_rest_job(),
        source_run_id=100, source_attempt=2, health_classification="EVIDENCE_VALID")
    assert out["classification"] == "EVIDENCE_MISSING"


# PF07/PF08 -- exact-attempt endpoint, job identity, duplicates fail closed.
def test_pf07_main_uses_exact_attempt_endpoint_and_validates_jobs(monkeypatch, tmp_path):
    import scripts.agent_os_ci_evidence_collector as col

    seen_urls = []
    run_payload = {"id": 100, "head_sha": HEAD, "path": ".github/workflows/agent-os-validation.yml", "status": "completed"}
    jobs_payload = [_job(2)]
    data = _zip({"pyan3-advisory.json": _pyan_report()})
    arts = [_artifact("pyan3-advisory-3756-attempt-2", 16, archive_download_url="https://example.invalid/a")]

    def fake_paginate(url, token):
        seen_urls.append(url)
        if "/attempts/" in url:
            return jobs_payload
        if "/artifacts" in url:
            return arts
        raise AssertionError(url)

    monkeypatch.setattr(col, "_api_get", lambda url, token: (run_payload, {}))
    monkeypatch.setattr(col, "_paginate", fake_paginate)
    monkeypatch.setattr(col, "_api_get_bytes", lambda url, token: data)
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Blummer92/agent-os")
    out = tmp_path / "receipt.json"
    assert col.main(["--source-run-id", "100", "--source-head", HEAD, "--source-attempt", "2", "--output", str(out)]) == 0
    assert any("/attempts/2/jobs" in u for u in seen_urls)
    assert not any("attempt_number=" in u for u in seen_urls)
    assert json.loads(out.read_text())["streams"]["pyan"]["classification"] == "EVIDENCE_VALID"

    jobs_payload_bad = [_job(1)]
    monkeypatch.setattr(col, "_paginate", lambda url, token: jobs_payload_bad if "/attempts/" in url else arts)
    assert col.main(["--source-run-id", "100", "--source-head", HEAD, "--source-attempt", "2", "--output", str(out)]) == 2
    monkeypatch.setattr(col, "_paginate", lambda url, token: [] if "/attempts/" in url else arts)
    assert col.main(["--source-run-id", "100", "--source-head", HEAD, "--source-attempt", "2", "--output", str(out)]) == 2


def test_pf08_duplicate_job_identity_fails_closed():
    run = {"id": 100, "head_sha": HEAD, "path": ".github/workflows/agent-os-validation.yml", "status": "completed"}
    jobs = [_job(2), _job(2)]
    with pytest.raises(ValueError):
        build_verified_receipt(source_run=run, jobs=jobs, artifacts=[], downloads={}, source_attempt=2, collector_head="c" * 40, live_trigger=False)


# Receipt refinement must not override INCOMPLETE: a still-running job
# is not a wrong-attempt rejection, even when only an older attempt's
# artifact exists.
def test_receipt_mismatch_refinement_keeps_incomplete_precedence():
    run = {"id": 100, "head_sha": HEAD, "path": ".github/workflows/agent-os-validation.yml", "status": "completed"}
    jobs = [_job(2, status="in_progress", conclusion="success"),
            {"id": 8, "name": "jscpd duplicate-code advisory", "conclusion": "skipped", "run_attempt": 2},
            {"id": 9, "name": "Run validation plan", "conclusion": "skipped", "run_attempt": 2}]
    receipt = build_verified_receipt(
        source_run=run, jobs=jobs, artifacts=[_artifact("pyan3-advisory-3756-attempt-1", 15)],
        downloads={}, source_attempt=2, collector_head="c" * 40, live_trigger=False)
    assert receipt["streams"]["pyan"]["classification"] == "INCOMPLETE"


# Final-gate identity verification (2026-11-02 addendum): when the
# collector supplies expected identity, a missing or null schema, run
# id, attempt, or head SHA must NOT satisfy verification. Legacy
# behavior (no identity requested) is preserved exactly.
def _health_zip_full(classification: str, **fields) -> bytes:
    payload = {"schema": "agent-os-ci-evidence-health/1", "classification": classification,
               "run_id": 100, "run_attempt": 2, "head_sha": HEAD}
    payload.update(fields)
    return _zip({"pyan3-health.json": json.dumps(payload).encode()})


def _health_zip_missing(field: str) -> bytes:
    payload = {"schema": "agent-os-ci-evidence-health/1", "classification": "EVIDENCE_VALID",
               "run_id": 100, "run_attempt": 2, "head_sha": HEAD}
    del payload[field]
    return _zip({"pyan3-health.json": json.dumps(payload).encode()})


def test_final_gate_identity_missing_and_null_never_verify():
    for field in ("schema", "run_id", "run_attempt", "head_sha"):
        assert health_classification_from_zip(
            _health_zip_missing(field), source_run_id=100, source_attempt=2, expected_head=HEAD) is None
        assert health_classification_from_zip(
            _health_zip_full("EVIDENCE_VALID", **{field: None}),
            source_run_id=100, source_attempt=2, expected_head=HEAD) is None


def test_final_gate_identity_correct_incorrect_and_precedence():
    assert health_classification_from_zip(
        _health_zip_full("EVIDENCE_VALID"), source_run_id=100, source_attempt=2, expected_head=HEAD) == "EVIDENCE_VALID"
    assert health_classification_from_zip(
        _health_zip_full("EVIDENCE_VALID", run_id=999), source_run_id=100, source_attempt=2, expected_head=HEAD) is None
    assert health_classification_from_zip(
        _health_zip_full("EVIDENCE_VALID", schema="other/9"), source_run_id=100, source_attempt=2, expected_head=HEAD) is None
    # Scanner-error precedence, verified identity: outcome beats classification.
    assert health_classification_from_zip(
        _health_zip_full("EVIDENCE_VALID", generate_outcome="failure"),
        source_run_id=100, source_attempt=2, expected_head=HEAD) == "REJECT_SCANNER_ERROR"
    # Identity precedence over outcome: unverified receipt, even one
    # claiming a scanner failure, is None, never a cause assertion.
    assert health_classification_from_zip(
        _health_zip_missing("run_id"), source_run_id=100, source_attempt=2, expected_head=HEAD) is None
    assert health_classification_from_zip(
        _zip({"pyan3-health.json": json.dumps(
            {"schema": "agent-os-ci-evidence-health/1", "classification": "EVIDENCE_VALID",
             "run_attempt": 2, "head_sha": HEAD, "generate_outcome": "failure"}).encode()}),
        source_run_id=100, source_attempt=2, expected_head=HEAD) is None
    # Legacy preservation: no identity requested returns the field as before.
    assert health_classification_from_zip(_health_zip_missing("schema")) == "EVIDENCE_VALID"
    assert health_classification_from_zip(_health_zip_full("EVIDENCE_MISSING")) == "EVIDENCE_MISSING"


# PF10 -- missing job is NOT_APPLICABLE (never healthy); unfinished job is INCOMPLETE.
def test_pf10_missing_job_not_applicable_unfinished_incomplete():
    run = {"id": 100, "head_sha": HEAD, "path": ".github/workflows/agent-os-validation.yml", "status": "completed"}
    jobs = [{"id": 8, "name": "jscpd duplicate-code advisory", "conclusion": "skipped", "run_attempt": 2},
            {"id": 9, "name": "Run validation plan", "conclusion": "skipped", "run_attempt": 2}]
    receipt = build_verified_receipt(source_run=run, jobs=jobs, artifacts=[], downloads={}, source_attempt=2, collector_head="c" * 40, live_trigger=False)
    assert receipt["streams"]["pyan"]["classification"] == "NOT_APPLICABLE"
    out = classify_advisory_artifact(
        stream="pyan", artifact=_artifact("pyan3-advisory-3756-attempt-2", 16),
        zip_bytes=_zip({"pyan3-advisory.json": _pyan_report()}), expected_head=HEAD,
        job=_job(2, status="in_progress", conclusion="success"), source_run_id=100, source_attempt=2)
    assert out["classification"] == "INCOMPLETE"


# PF11 -- wrong head / digest corruption still rejected at the classifier.
def test_pf11_wrong_head_and_digest_rejected():
    data = _zip({"pyan3-advisory.json": _pyan_report()})
    out = classify_advisory_artifact(
        stream="pyan", artifact=_artifact("pyan3-advisory-3756-attempt-2", 16, workflow_run={"id": 100, "head_sha": "c" * 40}),
        zip_bytes=data, expected_head=HEAD, job=_job(2), source_run_id=100, source_attempt=2)
    assert out["classification"] == "REJECT_WRONG_HEAD"
    out = classify_advisory_artifact(
        stream="pyan", artifact=_artifact("pyan3-advisory-3756-attempt-2", 16, digest="sha256:" + "0" * 64),
        zip_bytes=data, expected_head=HEAD, job=_job(2), source_run_id=100, source_attempt=2)
    assert out["classification"] == "REJECT_DIGEST"
