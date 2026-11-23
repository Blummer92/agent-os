"""Offline, no-provider regression tests for metadata-only CKR6 review intake."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.agent_os_ckr6_review_evidence import build_review_evidence


def fixture():
    event = {
        "repository": {"full_name": "Blummer92/agent-os"},
        "issue": {"number": 4094, "pull_request": {}},
        "comment": {"id": 7102293341},
    }
    result = {
        "repository": "Blummer92/agent-os", "issue_number": 4094,
        "operation": "issue-start", "status": "insufficient",
        "reason_codes": ["no-relevant-candidate"],
        "selected_lesson_ids": [],
        "rejected_candidate_provenance": [{
            "lesson_id": "LL-10", "source_revision": "2026-11-15T00:41:00.000Z",
            "currentness": "current", "provenance": "canonical-github-ref-present",
        }],
    }
    diagnostics = {
        "retrieval_reason_code": "none", "incomplete_reason_code": "none",
        "read_count": 1, "observed_rows": 87, "normalized_rows": 87,
        "skipped_rows": 0, "candidate_count": 5,
        "best_bucket_tied_identities": 0, "selection_basis": "no-relevant-signal",
    }
    return event, result, diagnostics


def test_metadata_only_never_admits_or_exposes_provider_content():
    event, result, diagnostics = fixture()
    result["lesson_proposal"] = {"title": "PRIVATE TITLE SENTINEL"}
    event["comment"]["body"] = "PRIVATE GUIDANCE SENTINEL"
    diagnostics["terminal_query_bucket"] = "workspace"
    report = build_review_evidence(event, result, diagnostics, run_id=451824, run_attempt=1)
    serialized = json.dumps(report)
    assert report["candidate_provenance"][0]["lesson_id"] == "LL-10"
    assert report["retrieval"]["observed_rows"] == 87
    assert "SENTINEL" not in serialized and "workspace" not in serialized
    assert report["review_state"] == "requires-independent-exact-revision-review"
    assert not report["merge_authorized"]
    assert not report["ckr6"]["selection_is_applicability_proof"]


@pytest.mark.parametrize("mutation", [
    lambda e, r, d: r.update(issue_number=4095),
    lambda e, r, d: e["repository"].update(full_name="untrusted/other"),
    lambda e, r, d: r["rejected_candidate_provenance"][0].update(lesson_id="LL-10 SECRET"),
    lambda e, r, d: r["rejected_candidate_provenance"].extend(r["rejected_candidate_provenance"] * 5),
    lambda e, r, d: d.update(read_count=True),
    lambda e, r, d: d.update(credential="PRIVATE TOKEN"),
    lambda e, r, d: d.update(selection_basis="PRIVATE TOKEN"),
])
def test_malformed_inputs_fail_closed(mutation):
    event, result, diagnostics = fixture()
    mutation(event, result, diagnostics)
    with pytest.raises(ValueError):
        build_review_evidence(event, result, diagnostics, run_id=1, run_attempt=1)


def test_unknown_reason_is_coarsened_without_echo():
    event, result, diagnostics = fixture()
    result["reason_codes"] = ["PRIVATE-TOKEN"]
    report = build_review_evidence(event, result, diagnostics, run_id=1, run_attempt=1)
    assert report["ckr6"]["reason_codes"] == ["unclassified-reason"]
    assert "PRIVATE" not in json.dumps(report)


def test_missing_diagnostics_does_not_claim_complete_retrieval():
    event, result, _ = fixture()
    report = build_review_evidence(event, result, None, run_id=1, run_attempt=1)
    assert report["retrieval"] == {"available": False}


def test_cli_never_prints_raw_exception_or_writes_on_bad_input(tmp_path):
    event, result, diagnostics = fixture()
    result["issue_number"] = 9999
    files = [tmp_path / name for name in ("event.json", "result.json", "diagnostics.json")]
    for path, value in zip(files, (event, result, diagnostics)):
        path.write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "review.json"
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run([
        sys.executable, str(root / "scripts/agent_os_ckr6_review_evidence.py"),
        "--event", str(files[0]), "--result", str(files[1]),
        "--diagnostics", str(files[2]), "--output", str(output),
        "--run-id", "123", "--run-attempt", "1",
    ], text=True, capture_output=True, check=False)
    assert completed.returncode == 2
    assert completed.stdout.strip() == "ckr6-review-evidence-unavailable"
    assert completed.stderr == ""
    assert not output.exists()
