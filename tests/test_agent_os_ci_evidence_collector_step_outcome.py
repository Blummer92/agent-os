from __future__ import annotations

import io
import json
import zipfile

from scripts.agent_os_ci_evidence_collector import (
    advisory_step_outcome,
    classify_advisory_artifact,
)

HEAD = "a" * 40


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _report(status: str = "ok") -> bytes:
    return json.dumps({"tool": "pyan3", "schema": "agent-os-pyan3-advisory/1", "status": status, "head_sha": HEAD}).encode()


def _artifact(name: str = "pyan3-advisory-3756") -> dict:
    return {"id": 1, "name": name, "expired": False, "workflow_run": {"id": 100, "head_sha": HEAD}}


def _job(*, status: str = "completed", conclusion: str = "success", steps: list | None = None, attempt: int = 1) -> dict:
    return {"id": 7, "name": "pyan3 call-graph advisory", "status": status, "conclusion": conclusion, "run_attempt": attempt, "steps": steps or []}


def test_in_progress_job_is_incomplete_even_with_success_conclusion() -> None:
    job = _job(status="in_progress", conclusion="success", steps=[{"name": "Generate report-only pyan3 evidence", "outcome": "success", "conclusion": "success"}])
    out = classify_advisory_artifact(stream="pyan", artifact=None, zip_bytes=None, expected_head=HEAD, job=job, source_run_id=100, source_attempt=1)
    assert out["classification"] == "INCOMPLETE"
    assert out["job_status"] == "in_progress"


def test_failed_generate_step_is_scanner_error_even_when_artifact_absent() -> None:
    job = _job(steps=[{"name": "Generate report-only pyan3 evidence", "outcome": "failure", "conclusion": "success"}])
    assert advisory_step_outcome(job) == "failure"
    out = classify_advisory_artifact(stream="pyan", artifact=None, zip_bytes=None, expected_head=HEAD, job=job, source_run_id=100, source_attempt=1)
    assert out["classification"] == "SCANNER_ERROR"


def test_failed_generate_step_beats_valid_report_and_success_conclusion() -> None:
    job = _job(steps=[{"name": "Generate report-only pyan3 evidence", "outcome": "failure", "conclusion": "success"}])
    data = _zip({"pyan3-advisory.json": _report()})
    out = classify_advisory_artifact(stream="pyan", artifact=_artifact(), zip_bytes=data, expected_head=HEAD, job=job, source_run_id=100, source_attempt=1)
    assert out["classification"] == "SCANNER_ERROR"


def test_successful_generate_step_with_valid_report_is_healthy() -> None:
    job = _job(steps=[{"name": "Generate report-only pyan3 evidence", "outcome": "success", "conclusion": "success"}])
    data = _zip({"pyan3-advisory.json": _report()})
    out = classify_advisory_artifact(stream="pyan", artifact=_artifact(), zip_bytes=data, expected_head=HEAD, job=job, source_run_id=100, source_attempt=1)
    assert out["classification"] == "EVIDENCE_VALID"
