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


MISS_COUNTERS = {
    "miss_ecosystem_rows": 3,
    "miss_capability_rows": 2,
    "miss_exact_library_rows": 0,
    "miss_target_path_rows": 1,
    "miss_library_hints_not_named": 0,
}


def test_completed_no_match_diagnostics_keep_all_bounded_counters():
    event, result, diagnostics = fixture()
    diagnostics.update(MISS_COUNTERS)
    report = build_review_evidence(event, result, diagnostics, run_id=1, run_attempt=1)
    assert {key: report["retrieval"][key] for key in MISS_COUNTERS} == MISS_COUNTERS
    assert report["ckr6"]["selected_lesson_ids"] == []
    assert report["ckr6"]["selection_is_applicability_proof"] is False
    assert report["execution_authorized"] is False
    assert report["github_writes_authorized"] is False
    assert report["merge_authorized"] is False
    assert report["notion_writes_authorized"] is False


@pytest.mark.parametrize(("update", "expected"), [
    (lambda d: d.pop("miss_target_path_rows"), "diagnostic-miss-counter-shape"),
    (lambda d: d.update(selection_basis="exact-library"), "diagnostic-miss-counter-shape"),
    (lambda d: d.update(incomplete_reason_code="missing-cursor"), "diagnostic-miss-counter-shape"),
    (lambda d: d.update(miss_ecosystem_rows=True), "diagnostic-count"),
    (lambda d: d.update(miss_capability_rows=10_001), "diagnostic-count"),
    (lambda d: d.update(miss_exact_library_rows=-1), "diagnostic-count"),
    (lambda d: d.update(miss_target_path_rows="PRIVATE SENTINEL"), "diagnostic-count"),
])
def test_no_match_counter_signature_refused_when_incomplete_or_invalid(update, expected):
    event, result, diagnostics = fixture()
    diagnostics.update(MISS_COUNTERS)
    update(diagnostics)
    with pytest.raises(ValueError, match=f"^{expected}$"):
        build_review_evidence(event, result, diagnostics, run_id=1, run_attempt=1)


@pytest.mark.parametrize("field", [
    "miss_ecosystem_rows", "miss_capability_rows",
    "miss_exact_library_rows", "miss_target_path_rows",
])
def test_no_match_per_row_counter_cannot_exceed_normalized_population(field):
    event, result, diagnostics = fixture()
    diagnostics.update(MISS_COUNTERS)
    diagnostics[field] = diagnostics["normalized_rows"] + 1
    with pytest.raises(ValueError, match="^diagnostic-row-population$"):
        build_review_evidence(event, result, diagnostics, run_id=1, run_attempt=1)


def test_no_match_ecosystem_row_counter_can_match_entire_population():
    event, result, diagnostics = fixture()
    diagnostics.update(dict.fromkeys(MISS_COUNTERS, 0), miss_ecosystem_rows=87)
    projected = build_review_evidence(event, result, diagnostics, run_id=1, run_attempt=1)
    assert projected["retrieval"]["miss_ecosystem_rows"] == 87


def test_no_match_request_side_library_hint_count_is_not_row_population():
    event, result, diagnostics = fixture()
    diagnostics.update(dict.fromkeys(MISS_COUNTERS, 0),
                       observed_rows=0, normalized_rows=0, candidate_count=0)
    diagnostics["miss_library_hints_not_named"] = 2
    projected = build_review_evidence(event, result, diagnostics, run_id=1, run_attempt=1)
    assert projected["retrieval"]["normalized_rows"] == 0
    assert projected["retrieval"]["miss_library_hints_not_named"] == 2


@pytest.mark.parametrize("reason,expected", [
    ("notion-timeout", "notion-timeout"),
    ("notion-malformed-pagination", "notion-malformed-pagination"),
    ("notion-http-429", "notion-http-429"),
    ("notion-unrecognized-diagnostic", "unclassified-reason"),
])
def test_retrieval_reason_projects_only_known_metadata(reason, expected):
    e, r, d = fixture()
    d["retrieval_reason_code"] = reason
    result = build_review_evidence(e, r, d, run_id=1, run_attempt=1)
    assert result["retrieval"]["retrieval_reason_code"] == expected
    assert result["merge_authorized"] is False


@pytest.mark.parametrize("totals", [
    {"normalized_rows": 86},
    {"normalized_rows": 88},
    {"normalized_rows": 87, "skipped_rows": 1},
    {"normalized_rows": 85, "skipped_rows": 1, "incomplete_reason_code": "missing-cursor"},
])
def test_diagnostic_rows_cannot_disagree_with_normalization_ledger(totals):
    event, result, diagnostics = fixture()
    diagnostics.update(totals)
    with pytest.raises(ValueError, match="^diagnostic-row-accounting$"):
        build_review_evidence(event, result, diagnostics, run_id=1, run_attempt=1)


@pytest.mark.parametrize("incomplete", ["none", "missing-cursor"])
def test_diagnostic_rows_preserve_mixed_totals_even_when_later_retrieval_stops(incomplete):
    event, result, diagnostics = fixture()
    diagnostics.update(incomplete_reason_code=incomplete, normalized_rows=82, skipped_rows=5)
    projection = build_review_evidence(event, result, diagnostics, run_id=1, run_attempt=1)
    assert tuple(projection["retrieval"][name] for name in
                 ("observed_rows", "normalized_rows", "skipped_rows")) == (87, 82, 5)
    assert projection["execution_authorized"] is False


def test_raw_result_needs_an_independent_request_run_artifact_join():
    event, result, diagnostics = fixture()
    assert "request_comment_id" not in result
    first = build_review_evidence(event, result, diagnostics, run_id=1, run_attempt=1)
    other_event = {**event, "comment": {"id": event["comment"]["id"] + 1}}
    second = build_review_evidence(other_event, result, diagnostics, run_id=2, run_attempt=2)
    assert first["ckr6"] == second["ckr6"]
    assert first["source"]["request_comment_id"] != second["source"]["request_comment_id"]
    for bundle in (first, second):
        assert bundle["source"]["request_run_artifact_association"] == "supplied-unverified"
        assert "independently-verify-request-run-artifact-association" in bundle["review_requirements"]
        assert bundle["execution_authorized"] is False
        assert bundle["github_writes_authorized"] is False
        assert bundle["merge_authorized"] is False
        assert bundle["notion_writes_authorized"] is False


@pytest.mark.parametrize("bound_id", [7102293340, None, True, "7102293341"])
def test_optional_result_request_identity_cannot_contradict_event(bound_id):
    event, result, diagnostics = fixture()
    result["request_comment_id"] = bound_id
    with pytest.raises(ValueError, match="^result-request-identity$"):
        build_review_evidence(event, result, diagnostics, run_id=1, run_attempt=1)


def test_optional_matching_result_identity_is_still_only_supplied_metadata():
    event, result, diagnostics = fixture()
    result["request_comment_id"] = event["comment"]["id"]
    projected = build_review_evidence(event, result, diagnostics, run_id=1, run_attempt=1)
    assert projected["source"]["request_run_artifact_association"] == "supplied-unverified"
    assert projected["execution_authorized"] is False
