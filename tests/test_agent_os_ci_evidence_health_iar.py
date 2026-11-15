from __future__ import annotations

import json

from scripts.agent_os_ci_evidence_health import (
    StreamObservation,
    classify_issue_acceptance,
    classify_stream,
    main,
)

HEAD = "a" * 40


def test_manual_review_with_green_wrapper_is_not_acceptance_pass() -> None:
    out = classify_issue_acceptance("Overall result: manual-review\n", workflow_conclusion="success")
    assert out["checker_verdict"] == "manual-review"
    assert out["acceptance_pass"] is False


def test_checker_pass_with_green_wrapper_is_acceptance_pass() -> None:
    out = classify_issue_acceptance("Overall result: pass\n", workflow_conclusion="success")
    assert out["acceptance_pass"] is True


def test_missing_overall_line_is_unverified_never_pass() -> None:
    out = classify_issue_acceptance("some log without a verdict\n", workflow_conclusion="success")
    assert out["checker_verdict"] == "unverified"
    assert out["acceptance_pass"] is False


def test_in_progress_stream_is_incomplete() -> None:
    obs = StreamObservation(
        stream="pyan", obligation="required", source_head=HEAD, reported_head=HEAD,
        run_attempt=1, artifact_attempt=1, job_id=7, artifact_job_id=7,
        artifact_present=True, artifact_expired=False, schema_valid=True,
        job_conclusion="success", job_status="in_progress",
    )
    assert classify_stream(obs) == "INCOMPLETE"


def test_failed_step_outcome_is_scanner_error() -> None:
    obs = StreamObservation(
        stream="pyan", obligation="required", source_head=HEAD, reported_head=HEAD,
        run_attempt=1, artifact_attempt=1, job_id=7, artifact_job_id=7,
        artifact_present=False, artifact_expired=False, schema_valid=True,
        job_conclusion="success", step_outcome="failure",
    )
    assert classify_stream(obs) == "REJECT_SCANNER_ERROR"


def test_generate_outcome_failure_overrides_stale_report(tmp_path) -> None:
    out_dir = tmp_path / "out"
    health_dir = tmp_path / "health"
    out_dir.mkdir()
    report = {"tool": "pyan3", "schema": "agent-os-pyan3-advisory/1", "status": "ok", "head_sha": HEAD}
    (out_dir / "pyan3-advisory.json").write_text(json.dumps(report), encoding="utf-8")
    rc = main(["--tool", "pyan3", "--output-dir", str(out_dir), "--report", "pyan3-advisory.json",
               "--head", HEAD, "--generate-outcome", "failure", "--health-dir", str(health_dir)])
    assert rc == 0
    receipt = json.loads((health_dir / "pyan3-health.json").read_text(encoding="utf-8"))
    assert receipt["classification"] == "REJECT_SCANNER_ERROR"
    assert receipt["generate_outcome"] == "failure"
