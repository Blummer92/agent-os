import copy
import json
from pathlib import Path

import pytest

from scripts.agent_os_pr_remediation import (
    EvidenceValidationError,
    classify_review_thread_payload,
    normalize_pr_snapshot,
    normalize_review_thread,
    normalize_review_threads,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "agent_os_pr_remediation"


def _pr_payload():
    return json.loads((FIXTURES / "pr_snapshot.json").read_text())


def _thread_payloads():
    return json.loads((FIXTURES / "review_threads.json").read_text())


def test_pr_fixture_normalizes_deterministically():
    snapshot = normalize_pr_snapshot(_pr_payload())
    assert snapshot.changed_files == ("scripts/example.py", "tests/example.py")
    assert snapshot.execution_authorized is False
    assert len(snapshot.evidence_id) == 64


def test_review_fixture_preserves_identity_but_not_body():
    threads = normalize_review_threads(_thread_payloads())
    assert [thread.classification for thread in threads] == [
        "current-unresolved",
        "resolved",
        "superseded",
    ]
    assert threads[0].thread_id == "PRRT_1"
    assert threads[0].reply_ids == ("reply-1",)
    assert "Keep this as data only." not in repr(threads[0])
    assert len(threads[0].body_fingerprint) == 64


def test_missing_path_or_line_is_unavailable():
    payload = _thread_payloads()[0]
    payload["line"] = None
    assert normalize_review_thread(payload).classification == "unavailable"


def test_outdated_is_distinct_from_resolved():
    payload = _thread_payloads()[0]
    payload["outdated"] = True
    assert normalize_review_thread(payload).classification == "outdated"


def test_unknown_fields_fail_closed():
    payload = _pr_payload()
    payload["mystery"] = "nope"
    with pytest.raises(EvidenceValidationError):
        normalize_pr_snapshot(payload)


def test_malformed_timestamp_fails_closed():
    payload = _thread_payloads()[0]
    payload["updated_at"] = "yesterday"
    with pytest.raises(EvidenceValidationError):
        normalize_review_thread(payload)


def test_duplicate_thread_identity_fails_closed():
    payload = _thread_payloads()
    payload.append(copy.deepcopy(payload[0]))
    with pytest.raises(EvidenceValidationError):
        normalize_review_threads(payload)


def test_superseded_requires_evidence():
    payload = _thread_payloads()[0]
    payload["superseded"] = True
    with pytest.raises(EvidenceValidationError):
        normalize_review_thread(payload)


def test_body_at_configured_limit_is_accepted():
    payload = _thread_payloads()[0]
    payload["body"] = "x" * 100_000
    assert len(normalize_review_thread(payload).body_fingerprint) == 64


def test_oversized_body_fails_closed():
    payload = _thread_payloads()[0]
    payload["body"] = "x" * 100_001
    with pytest.raises(EvidenceValidationError):
        normalize_review_thread(payload)


def test_malformed_payload_has_explicit_classification():
    payload = _thread_payloads()[0]
    payload["top_level_comment_id"] = True
    assert classify_review_thread_payload(payload) == "malformed"
