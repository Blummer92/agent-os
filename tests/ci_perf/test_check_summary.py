"""Contract checks for the read-only CI summary."""
import pytest

from scripts.ci_perf import check_summary as summary
from scripts.ci_perf.check_summary import AGG, BASELINE, CKR, UPLOAD, observe

HEAD = "a" * 40


def provider(key, *rows):
    return {key: list(rows), "total_count": len(rows)}


def job(**steps):
    return {
        "name": AGG, "head_sha": HEAD, "run_id": 17, "run_attempt": 2,
        "status": "completed", "conclusion": "success",
        "steps": [{"name": name, "status": "completed", "conclusion": outcome} for name, outcome in steps.items()],
    }


def report(jobs, checks=None, /):
    return "\n".join(observe(jobs, checks, head=HEAD, run=17, attempt=2))


def test_clean_execution_is_not_authority():
    result = report(provider("jobs", job(**dict.fromkeys((AGG, *UPLOAD), "success"))))
    assert "execution step succeeded" in result and "does not certify" in result
    assert "contents were not verified" in result


def test_main_block_does_not_blame_candidate():
    result = report(provider("jobs", job(**{BASELINE[1]: "failure", AGG: "skipped"})))
    assert "Main baseline: blocked before candidate" in result
    assert "no candidate test verdict" in result and "execution step failed" not in result


def test_aggregate_failure_and_missing_evidence_stay_distinct():
    result = report(provider("jobs", job(**{AGG: "failure", UPLOAD[0]: "failure"})))
    assert "execution step failed" in result and "Evidence: upload failed" in result
    assert "distinguish a test failure from infrastructure" in result


@pytest.mark.parametrize("field,value", [("head_sha", "b" * 40), ("run_id", 16), ("run_attempt", 1)])
def test_unbound_job_is_rejected(field, value):
    with pytest.raises(ValueError, match="binding"):
        report(provider("jobs", dict(job(), **{field: value})))


def test_incomplete_listing_and_duplicate_job_dont_look_clean():
    with pytest.raises(ValueError, match="incomplete"):
        report({"jobs": [], "total_count": 1})
    assert "no unique aggregate" in report(provider("jobs", job(), job()))


def check(identifier, outcome, *, head=HEAD, app="github-actions"):
    return {
        "name": CKR, "head_sha": head, "app": {"slug": app},
        "id": identifier, "status": "completed", "conclusion": outcome,
    }


def test_ckr_tracks_only_latest_exact_head_actions_check():
    checks = provider("check_runs", check(1, "success"), check(2, "failure"),
                      check(3, "success", head="b" * 40), check(4, "success", app="other"))
    result = report(provider("jobs", job(**{AGG: "success"})), checks)
    assert "CKR6: failure (separate" in result and "execution step succeeded" in result


def test_provider_text_never_becomes_summary_content():
    result = report(provider("jobs", job(**{AGG: "::error::untrusted"})))
    assert "no completed execution verdict" in result
    assert "untrusted" not in result


def test_pre_test_transport_failure_is_not_a_suite_failure():
    result = report(provider("jobs", job(**{
        "Recover missing exact-current main aggregate evidence": "failure", AGG: "skipped",
    })))
    assert "Infrastructure:" in result
    assert "no candidate test verdict" in result


def test_missing_ckr_metadata_cannot_hide_aggregate_observation():
    result = report(provider("jobs", job(**{AGG: "success"})), {"total_count": 2, "check_runs": []})
    assert "CKR6: unavailable" in result and "execution step succeeded" in result

@pytest.mark.parametrize("field,value", [("run", 0), ("attempt", 0), ("attempt", True), ("head", HEAD[:7])])
def test_invalid_bound_identity_does_not_count_even_a_missing_job(field, value):
    with pytest.raises(ValueError, match="unverified run identity"):
        observe(provider("jobs"), None, **dict({"head": HEAD, "run": 17, "attempt": 2}, **{field: value}))


def test_bool_provider_identity_cannot_match_run_one():
    with pytest.raises(ValueError, match="binding"):
        observe(provider("jobs", dict(job(), run_id=True)), None, head=HEAD, run=1, attempt=2)


def test_duplicate_or_unfinished_aggregate_steps_do_not_look_completed():
    a = job(**{AGG: "success"})
    a["steps"].append(dict(a["steps"][0]))
    assert "no completed execution verdict" in report(provider("jobs", a))
    a["steps"].pop()
    a["steps"][0]["status"] = "in_progress"
    assert "no completed execution verdict" in report(provider("jobs", a))


def test_incomplete_job_cannot_claim_successful_steps():
    a = dict(job(**{AGG: "success"}), status="in_progress")
    result = report(provider("jobs", a))
    assert "no completed aggregate job" in result and "step succeeded" not in result


@pytest.mark.parametrize("failed", [BASELINE[0], BASELINE[1], *summary.BOOTSTRAP])
def test_contradictory_success_and_admission_failure_refuses_observation(failed):
    with pytest.raises(ValueError, match="contradictory"):
        report(provider("jobs", job(**{AGG: "success", failed: "failure"})))


@pytest.mark.parametrize("step_status", ["success", "failure", "skipped"])
def test_one_upload_never_establishes_complete_evidence(step_status):
    a = job(**{AGG: step_status, UPLOAD[0]: "success", UPLOAD[1]: "skipped"})
    result = report(provider("jobs", a))
    assert "upload steps succeeded" not in result
    assert ("complete uploads are unverified" in result) == (step_status != "skipped")


def test_skipped_execution_does_not_credit_upload_artifacts_as_run_evidence():
    a = job(**{AGG: "skipped", UPLOAD[0]: "success", UPLOAD[1]: "success"})
    result = report(provider("jobs", a))
    assert "no candidate test verdict" in result and "upload steps succeeded" not in result


def test_invalid_ckr_status_is_not_echoed_or_treated_as_success():
    c = check(1, "unknown-result")
    rendered = report(provider("jobs"), provider("check_runs", c))
    assert "CKR6: unavailable" in rendered and "unknown-result" not in rendered


def test_optional_ckr_response_does_not_require_a_second_data_fixture(monkeypatch, tmp_path, capsys):
    job_file = tmp_path / "jobs.json"
    job_file.write_text('{"total_count": 0, "jobs": []}')
    ckr = tmp_path / "checks.json"
    ckr.write_text("malformed")
    monkeypatch.setattr("sys.argv", ["check_summary", "--head", HEAD, "--run", "17", "--attempt", "2",
                                  "--jobs", str(job_file), "--checks", str(ckr)])
    summary.main()
    assert "Aggregate: unavailable" in capsys.readouterr().out


def test_reader_refuses_oversize_json(monkeypatch, tmp_path):
    path = tmp_path / "provider.json"
    path.write_text(" " * 16 + "{}")
    monkeypatch.setattr(summary, "MAX_BYTES", 16)
    with pytest.raises(ValueError, match="bound"):
        summary.load_json(path)
