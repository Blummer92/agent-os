import json
from pathlib import Path

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_pr_remediation import (
    NormalizedReviewThread,
    normalize_pr_snapshot,
    normalize_review_threads,
    preflight,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "agent_os_pr_remediation"


def _snapshot():
    payload = json.loads((FIXTURES / "pr_snapshot.json").read_text())
    return normalize_pr_snapshot(payload)


def _threads():
    payload = json.loads((FIXTURES / "review_threads.json").read_text())
    return normalize_review_threads(payload)


def test_matching_head_and_scope_pass():
    result = preflight(
        _snapshot(),
        expected_head="2" * 40,
        allowed_files=["scripts/example.py", "tests/example.py"],
        review_threads=_threads(),
    )
    assert result.overall_status is Status.PASS
    assert result.outside_allowed_files == ()
    assert result.expected_head == "2" * 40
    assert result.allowed_files == ("scripts/example.py", "tests/example.py")
    assert result.execution_authorized is False


def test_moved_head_fails():
    result = preflight(
        _snapshot(),
        expected_head="3" * 40,
        allowed_files=["scripts/example.py", "tests/example.py"],
    )
    assert result.overall_status is Status.FAIL


def test_out_of_scope_file_fails():
    result = preflight(
        _snapshot(),
        expected_head="2" * 40,
        allowed_files=["scripts/example.py"],
    )
    assert result.overall_status is Status.FAIL
    assert result.outside_allowed_files == ("tests/example.py",)


def test_draft_incompatibility_fails():
    result = preflight(
        _snapshot(),
        expected_head="2" * 40,
        allowed_files=["scripts/example.py", "tests/example.py"],
        draft_allowed=False,
    )
    assert result.overall_status is Status.FAIL


def test_incomplete_current_thread_requires_manual_review():
    threads = list(_threads())
    thread = threads[0]
    threads[0] = NormalizedReviewThread(**{**thread.to_dict(), "line": None})
    result = preflight(
        _snapshot(),
        expected_head="2" * 40,
        allowed_files=["scripts/example.py", "tests/example.py"],
        review_threads=tuple(threads),
    )
    assert result.overall_status is Status.MANUAL_REVIEW
    assert result.manual_review_items


def test_duplicate_thread_identity_requires_manual_review():
    threads = _threads()
    result = preflight(
        _snapshot(),
        expected_head="2" * 40,
        allowed_files=["scripts/example.py", "tests/example.py"],
        review_threads=threads + (threads[0],),
    )
    assert result.overall_status is Status.MANUAL_REVIEW
    assert result.duplicate_thread_ids == ("PRRT_1",)


def test_package_has_no_external_execution_or_provider_paths():
    package = Path(__file__).parents[2] / "scripts" / "agent_os_pr_remediation"
    source = "\n".join(path.read_text() for path in package.glob("*.py")).lower()
    for banned in (
        "import requests",
        "import socket",
        "import subprocess",
        "github.",
        "openai",
        "anthropic",
        "resolve_review_thread",
    ):
        assert banned not in source
