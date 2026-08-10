from __future__ import annotations

import copy

import pytest

from scripts.agent_os_pr_remediation.evidence_assembly import assemble_prr_evidence
from scripts.agent_os_pr_remediation.models import EvidenceValidationError, canonical_json
from scripts.agent_os_pr_remediation.normalization import normalize_pr_snapshot, normalize_review_threads

HEAD = "a" * 40
BASE = "b" * 40
MOVED = "c" * 40


class FakeReader:
    def __init__(self, *, moved: bool = False, checks=None, threads=None):
        self.moved = moved
        self.calls: list[tuple] = []
        self._pr_reads = 0
        self.checks = checks if checks is not None else [
            {"name": "Agent OS Validation Gate", "conclusion": "success", "tested_sha": HEAD}
        ]
        self.threads = threads if threads is not None else [
            {
                "id": "thread-1",
                "is_resolved": False,
                "is_outdated": False,
                "path": "src/example.py",
                "line": 7,
                "original_line": 7,
                "diff_side": "RIGHT",
                "start_line": None,
                "start_diff_side": None,
                "comments": [
                    {
                        "id": 101,
                        "body": "Please fix this.",
                        "author": {"login": "reviewer"},
                        "created_at": "2026-08-10T12:00:00Z",
                        "updated_at": "2026-08-10T12:00:00Z",
                    }
                ],
            }
        ]

    def get_pull_request(self, repository, pr_number):
        self.calls.append(("get_pull_request", repository, pr_number))
        self._pr_reads += 1
        return {
            "base_branch": "main",
            "base_sha": BASE,
            "head_branch": "agent/example",
            "head_sha": MOVED if self.moved and self._pr_reads == 2 else HEAD,
            "state": "open",
            "merged": False,
            "draft": True,
            "captured_at": "2026-08-10T12:00:00Z",
            "source_revision": "github-live",
        }

    def list_changed_files(self, repository, pr_number):
        self.calls.append(("list_changed_files", repository, pr_number))
        return ["tests/example.py", "src/example.py"]

    def list_review_threads(self, repository, pr_number):
        self.calls.append(("list_review_threads", repository, pr_number))
        return copy.deepcopy(self.threads)

    def list_checks(self, repository, head_sha):
        self.calls.append(("list_checks", repository, head_sha))
        return copy.deepcopy(self.checks)


def test_assembles_exact_head_envelope_compatible_with_prr_normalizers():
    reader = FakeReader()
    result = assemble_prr_evidence("Blummer92/agent-os", 1009, reader)

    assert result.status == "assembled"
    assert result.initial_head_sha == result.final_head_sha == HEAD
    assert result.envelope is not None
    envelope = result.envelope
    assert envelope["expected_head"] == HEAD
    assert envelope["current_head_sha"] == HEAD
    assert envelope["final_captured_head_sha"] == HEAD
    assert envelope["changed_files"] == ["src/example.py", "tests/example.py"]
    assert envelope["allowed_files"] == envelope["changed_files"]
    assert normalize_pr_snapshot(envelope["snapshot"]).head_sha == HEAD
    assert normalize_review_threads(envelope["review_threads"])[0].thread_id == "thread-1"
    assert envelope["validation_evidence"][0]["tested_sha"] == HEAD
    assert envelope["validation_evidence"][0]["execution_status"] == "aggregate-pass"
    assert all(result.to_dict()[field] is False for field in (
        "execution_authorized", "external_write_authorized", "merge_authorized", "side_effects_performed"
    ))


def test_moved_head_fails_closed_without_mixed_envelope():
    result = assemble_prr_evidence("Blummer92/agent-os", 1009, FakeReader(moved=True))
    assert result.status == "stale-moved-head"
    assert result.envelope is None
    assert result.initial_head_sha == HEAD
    assert result.final_head_sha == MOVED
    assert result.reason_codes == ("head-moved-during-acquisition",)
    assert result.side_effects_performed is False


def test_missing_review_and_check_evidence_is_explicit():
    result = assemble_prr_evidence("Blummer92/agent-os", 1009, FakeReader(checks=[], threads=[]))
    assert result.status == "assembled"
    assert result.envelope is not None
    assert result.envelope["review_threads"] == []
    assert result.envelope["validation_evidence"] == []


def test_pending_check_is_normalized_as_unavailable_not_inferred_pass():
    result = assemble_prr_evidence(
        "Blummer92/agent-os",
        1009,
        FakeReader(checks=[{"name": "Required Check", "conclusion": None, "tested_sha": HEAD}]),
    )
    check = result.envelope["validation_evidence"][0]  # type: ignore[index]
    assert check["execution_status"] == "unavailable"
    assert check["evidence_available"] is False
    assert check["evidence_complete"] is False
    assert check["reason_codes"] == ["check-incomplete"]


def test_stale_check_sha_is_preserved_for_downstream_rejection():
    stale = "d" * 40
    result = assemble_prr_evidence(
        "Blummer92/agent-os",
        1009,
        FakeReader(checks=[{"name": "Required Check", "conclusion": "success", "tested_sha": stale}]),
    )
    check = result.envelope["validation_evidence"][0]  # type: ignore[index]
    assert check["expected_sha"] == HEAD
    assert check["tested_sha"] == stale


def test_identical_source_evidence_is_byte_stable():
    first = assemble_prr_evidence("Blummer92/agent-os", 1009, FakeReader())
    second = assemble_prr_evidence("Blummer92/agent-os", 1009, FakeReader())
    assert canonical_json(first.to_dict()) == canonical_json(second.to_dict())
    assert first.evidence_id == second.evidence_id


def test_rejects_duplicate_files_and_duplicate_check_categories():
    reader = FakeReader()
    reader.list_changed_files = lambda repository, pr_number: ["a.py", "a.py"]  # type: ignore[method-assign]
    with pytest.raises(EvidenceValidationError, match="duplicates"):
        assemble_prr_evidence("Blummer92/agent-os", 1009, reader)

    with pytest.raises(EvidenceValidationError, match="duplicate categories"):
        assemble_prr_evidence(
            "Blummer92/agent-os",
            1009,
            FakeReader(checks=[
                {"name": "same", "conclusion": "success", "tested_sha": HEAD},
                {"name": "same", "conclusion": "success", "tested_sha": HEAD},
            ]),
        )


def test_rejects_malformed_target_before_reader_calls():
    reader = FakeReader()
    with pytest.raises(EvidenceValidationError):
        assemble_prr_evidence("not-a-repository", 1009, reader)
    assert reader.calls == []


def test_reader_contract_has_no_mutation_methods():
    forbidden = {"merge", "resolve", "update", "create", "delete", "push", "execute", "run_validation"}
    public = {name for name in dir(FakeReader) if not name.startswith("_")}
    assert forbidden.isdisjoint(public)
