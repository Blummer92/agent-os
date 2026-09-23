from __future__ import annotations

import pytest
from scripts.agent_os_github_issue_provider.revision import (
    canonical_issue_payload,
    issue_source_revision,
)

BASE_ISSUE = {
    "number": 123,
    "title": "Test Issue",
    "state": "open",
    "body": "This is a test issue.",
    "html_url": "https://github.com/owner/repo/issues/123",
    "created_at": "2024-05-20T10:00:00Z",
    "updated_at": "2024-05-20T10:00:00Z",
    "labels": [{"name": "bug"}, {"name": "priority"}],
}

def test_canonical_payload_minimal():
    payload = canonical_issue_payload(BASE_ISSUE)
    assert isinstance(payload, bytes)
    # Check stable keys
    import json
    data = json.loads(payload.decode("utf-8"))
    assert data["number"] == 123
    assert data["labels"] == ["bug", "priority"]
    assert data["is_pull_request"] is False

def test_canonical_payload_is_pull_request():
    issue = BASE_ISSUE.copy()
    issue["pull_request"] = {}
    payload = canonical_issue_payload(issue)
    import json
    data = json.loads(payload.decode("utf-8"))
    assert data["is_pull_request"] is True

def test_canonical_payload_labels_as_strings():
    issue = BASE_ISSUE.copy()
    issue["labels"] = ["bug", "priority"]
    payload = canonical_issue_payload(issue)
    import json
    data = json.loads(payload.decode("utf-8"))
    assert data["labels"] == ["bug", "priority"]

def test_canonical_payload_missing_required_fields():
    issue = {"number": 123}
    with pytest.raises(ValueError, match="missing revision field"):
        canonical_issue_payload(issue)

def test_issue_source_revision_stable():
    rev1 = issue_source_revision(BASE_ISSUE)
    rev2 = issue_source_revision(BASE_ISSUE)
    assert rev1 == rev2
    assert rev1.startswith("github-issue-v1:")

def test_issue_source_revision_regression_2024_05_20():
    # Fixed revision for a specific input to detect accidental changes in normalization
    issue = {
        "number": 42,
        "title": "The Answer",
        "state": "closed",
        "body": None,
        "html_url": "https://github.com/owner/repo/issues/42",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "labels": ["science", "fiction"],
        "state_reason": "completed",
        "closed_at": "2024-01-02T00:00:00Z",
    }
    revision = issue_source_revision(issue)
    # This value should be stable. If normalization changes, this test will fail.
    # Calculated hash: 
    # {"body":"","closed_at":"2024-01-02T00:00:00Z","created_at":"2024-01-01T00:00:00Z",
    #  "html_url":"https://github.com/owner/repo/issues/42","is_pull_request":false,
    #  "labels":["fiction","science"],"number":42,"state":"closed","state_reason":"completed",
    #  "title":"The Answer","updated_at":"2024-01-01T00:00:00Z"}
    # (Note: json.dumps with sort_keys=True and separators=(',', ':'))
    
    expected = "github-issue-v1:a0f816094a93d391c3df6c0e5b3be80dab923000f9366148e35be5b9c4c980e2"
    assert revision == expected
