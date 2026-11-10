"""Focused regression tests for the #3691 CKR6 infrastructure-failure reporter.

Defect: when the CKR6 workflow's classify or execute job failed before the
bridge could post (live proof: run 39665727697, install failure), the
originating issue received no result comment at all. The repair is a
job-level ``report-failure`` workflow job running the stdlib-only
``scripts/ckr6_failure_postback.py``. These tests cover the reporter
(positive, negative, dedupe, transport failure, install independence) and
the workflow gating (failure predicates, least privilege, no dependency on
the failed install graph, unchanged existing jobs).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge

ROOT = Path(__file__).resolve().parents[3]
REPORTER_PATH = ROOT / "scripts" / "ckr6_failure_postback.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "agent-os-ckr6.yml"

spec = importlib.util.spec_from_file_location("ckr6_failure_postback", REPORTER_PATH)
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)

REPOSITORY = "Blummer92/agent-os"
ISSUE_NUMBER = 3502
REQUEST_COMMENT_ID = 6328148451
ELIGIBLE_BODY = (
    '/agent-os ckr6 {"operation":"issue-start","repository":"Blummer92/agent-os",'
    '"issue_number":3502,"task_reference":"canary","specialized_knowledge_required":false}'
)


def _event(**comment_changes):
    comment = {
        "id": REQUEST_COMMENT_ID,
        "body": ELIGIBLE_BODY,
        "created_at": "2026-10-21T22:40:46Z",
        "user": {"login": "Blummer92"},
    }
    comment.update(comment_changes)
    return {
        "repository": {"full_name": REPOSITORY},
        "issue": {"number": ISSUE_NUMBER},
        "comment": comment,
    }


class _Response:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


class _Transport:
    """Fake urlopen: records requests, serves canned GET comments, POST ids."""

    def __init__(self, existing_comments=(), post_id=6328164937, fail_post=False, fail_get=False):
        self.existing = existing_comments if isinstance(existing_comments, dict) else list(existing_comments)
        self.post_id = post_id
        self.fail_post = fail_post
        self.fail_get = fail_get
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if request.get_method() == "GET":
            if self.fail_get:
                raise urllib.error.URLError("simulated lookup failure")
            return _Response(self.existing)
        if self.fail_post:
            raise urllib.error.URLError("simulated transport failure")
        return _Response({"id": self.post_id})

    @property
    def posts(self):
        return [r for r in self.requests if r.get_method() == "POST"]


@pytest.fixture
def transport(monkeypatch):
    fake = _Transport()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


def _post(transport, event=None):
    return reporter.post_failure_result(
        event=event if event is not None else _event(),
        repository=REPOSITORY,
        allowed_actor="Blummer92",
        api_url="https://api.github.com",
        token="test-token",
    )


# --- Positive: an eligible infrastructure failure yields one fallback ------


def test_infrastructure_failure_posts_one_correlated_fallback(transport):
    outcome = _post(transport)
    assert outcome == {
        "issue_number": ISSUE_NUMBER,
        "request_comment_id": REQUEST_COMMENT_ID,
        "posted_comment_id": 6328164937,
        "result_status": "manual-review",
        "deduplicated": False,
    }
    assert len(transport.posts) == 1
    post = transport.posts[0]
    assert post.full_url.endswith(f"/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}/comments")
    body = json.loads(post.data.decode("utf-8"))["body"]
    assert body.startswith(bridge.CKR6_RESULT_MARKER + "\n")
    payload = bridge.parse_ckr6_result_comment(body)
    assert payload["request_comment_id"] == REQUEST_COMMENT_ID
    assert payload["status"] == "manual-review"
    assert payload["reason_codes"] == ["ckr6-result-unavailable"]
    for flag in (
        "execution_authorized",
        "github_writes_authorized",
        "merge_authorized",
        "closure_authorized",
        "mutation_admissible",
        "side_effects_performed",
    ):
        assert payload[flag] is False
    # The posted payload must stay inside the bridge's result-field allowlist.
    assert set(payload) - {"request_comment_id"} <= bridge.RESULT_FIELDS


def test_reporter_fallback_matches_bridge_fallback_exactly():
    assert reporter.fallback_result(
        REPOSITORY, ISSUE_NUMBER
    ) == bridge._fallback_result(REPOSITORY, ISSUE_NUMBER)
    assert reporter.serialize_result_comment(
        reporter.fallback_result(REPOSITORY, ISSUE_NUMBER),
        request_comment_id=REQUEST_COMMENT_ID,
    ) == bridge.serialize_ckr6_result_comment(
        bridge._fallback_result(REPOSITORY, ISSUE_NUMBER),
        request_comment_id=REQUEST_COMMENT_ID,
    )


def test_cli_main_posts_and_returns_zero(transport, tmp_path, monkeypatch):
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(_event()), encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    assert (
        reporter.main(
            [
                "--event",
                str(event_path),
                "--repository",
                REPOSITORY,
                "--allowed-actor",
                "Blummer92",
            ]
        )
        == 0
    )
    assert len(transport.posts) == 1


# --- Dedupe: a rerun must not post a second result --------------------------


def test_existing_result_for_same_request_deduplicates(monkeypatch):
    existing_body = bridge.serialize_ckr6_result_comment(
        bridge._fallback_result(REPOSITORY, ISSUE_NUMBER),
        request_comment_id=REQUEST_COMMENT_ID,
    )
    fake = _Transport(existing_comments=[{"id": 7001, "body": existing_body}])
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    outcome = _post(fake)
    assert outcome["deduplicated"] is True
    assert outcome["posted_comment_id"] == 7001
    assert fake.posts == []


def test_existing_non_ascii_bridge_result_deduplicates(monkeypatch):
    # Regression (independent QA D1): the bridge canonicalizes with
    # ensure_ascii=False, so a genuine bridge result carrying non-ASCII
    # lesson/handoff text must still parse in the reporter's dedupe lookup;
    # otherwise the reporter would post a duplicate, contradictory fallback
    # for a request that already has its real result.
    result = {
        "operation": "issue-start",
        "repository": REPOSITORY,
        "issue_number": ISSUE_NUMBER,
        "status": "not-needed",
        "reason_codes": ["knowledge-not-needed"],
        "selected_lesson_ids": [],
        "canonical_github_refs": [],
        "handoff_projection": {
            "known_facts": ["leçon café — naïve façade"],
            "prior_decisions": [],
            "allowed_inspect_first": [],
            "stop_conditions": [],
        },
        "substantial_hypothesis_admissible": True,
        "mutation_admissible": False,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
    }
    existing_body = bridge.serialize_ckr6_result_comment(
        result, request_comment_id=REQUEST_COMMENT_ID
    )
    assert "leçon café" in existing_body  # bridge emits raw UTF-8, not \uXXXX
    assert (
        reporter.parse_result_comment(existing_body)["request_comment_id"]
        == REQUEST_COMMENT_ID
    )
    fake = _Transport(existing_comments=[{"id": 7002, "body": existing_body}])
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    outcome = _post(fake)
    assert outcome["deduplicated"] is True
    assert outcome["posted_comment_id"] == 7002
    assert fake.posts == []


def test_result_for_a_different_request_does_not_deduplicate(monkeypatch):
    other_body = bridge.serialize_ckr6_result_comment(
        bridge._fallback_result(REPOSITORY, ISSUE_NUMBER),
        request_comment_id=REQUEST_COMMENT_ID - 1,
    )
    fake = _Transport(existing_comments=[{"id": 7001, "body": other_body}])
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    outcome = _post(fake)
    assert outcome["deduplicated"] is False
    assert len(fake.posts) == 1


# --- Negative: ineligible events never produce a postback -------------------


@pytest.mark.parametrize(
    "event",
    [
        _event(body="an ordinary issue comment"),
        _event(body="/agent-os ckr6"),  # bare near-miss: gate stays silent
        _event(body="/agent-os validate-draft 3687 abc"),
        _event(user={"login": "SomebodyElse"}),
        {
            **_event(),
            "issue": {
                "number": ISSUE_NUMBER,
                "pull_request": {"url": "https://example.invalid/pr"},
            },
        },
        {**_event(), "repository": {"full_name": "Other/repo"}},
        {k: v for k, v in _event().items() if k != "comment"},
    ],
)
def test_ineligible_events_are_rejected_without_any_http(transport, event):
    with pytest.raises((TypeError, ValueError)):
        _post(transport, event=event)
    assert transport.requests == []


def test_missing_token_fails_closed_without_any_http(transport):
    with pytest.raises(ValueError):
        reporter.post_failure_result(
            event=_event(),
            repository=REPOSITORY,
            allowed_actor="Blummer92",
            api_url="https://api.github.com",
            token="",
        )
    assert transport.requests == []


# --- Transport failure is visible, never a success claim --------------------


def test_github_transport_failure_raises(monkeypatch):
    fake = _Transport(fail_post=True)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with pytest.raises(RuntimeError, match="failure postback failed"):
        _post(fake)


# --- Uncertain dedupe: post (never leave the requester without a result), then fail visibly ----
#
# The bridge prefers a duplicate, non-authorizing receipt over silence when the
# existing-result lookup is uncertain. The reporter follows that rule and then
# raises, so the uncertainty shows as a red job rather than a quiet success.
# Exactly-once is not claimed: lookup-then-post is not atomic.


def _unrelated_comments(count):
    return [{"id": 9000 + n, "body": "an ordinary comment"} for n in range(count)]


@pytest.mark.parametrize(
    ("fake_kwargs", "reason"),
    [
        ({"fail_get": True}, "lookup failed: URLError"),
        ({"existing_comments": {"message": "Bad credentials"}}, "lookup returned an unexpected response"),
        ({"existing_comments": _unrelated_comments(100)}, "lookup may be truncated"),
    ],
    ids=["get-raises", "non-list-response", "full-page-without-match"],
)
def test_uncertain_dedupe_posts_exactly_once_then_fails_visibly(monkeypatch, fake_kwargs, reason):
    fake = _Transport(**fake_kwargs)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with pytest.raises(RuntimeError) as raised:
        _post(fake)
    assert str(raised.value) == (
        f"CKR6 failure postback posted comment 6328164937 without verified dedupe: {reason}"
    )
    assert len(fake.posts) == 1


@pytest.mark.parametrize("created_at", [None, "", 20261021])
def test_missing_request_timestamp_posts_without_a_lookup_then_fails_visibly(transport, created_at):
    with pytest.raises(RuntimeError) as raised:
        _post(transport, event=_event(created_at=created_at))
    assert str(raised.value).endswith("without verified dedupe: request created_at missing")
    assert [r.get_method() for r in transport.requests] == ["POST"]


def test_uncertain_dedupe_with_a_failing_post_reports_the_transport_failure(monkeypatch):
    fake = _Transport(fail_get=True, fail_post=True)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with pytest.raises(RuntimeError, match="failure postback failed"):
        _post(fake)


def test_healthy_empty_lookup_posts_exactly_once_after_one_read(transport):
    outcome = _post(transport)
    assert [r.get_method() for r in transport.requests] == ["GET", "POST"]
    assert outcome["deduplicated"] is False


def test_a_match_on_a_partial_page_deduplicates_without_posting(monkeypatch):
    body = bridge.serialize_ckr6_result_comment(
        bridge._fallback_result(REPOSITORY, ISSUE_NUMBER), request_comment_id=REQUEST_COMMENT_ID
    )
    fake = _Transport(existing_comments=[*_unrelated_comments(99), {"id": 7002, "body": body}])
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert _post(fake)["posted_comment_id"] == 7002
    assert fake.posts == []


# --- Install independence: stdlib only, importable in isolation -------------


def test_reporter_imports_only_the_standard_library():
    tree = ast.parse(REPORTER_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names)
    assert "agent_os_execution_service" not in imported


def test_reporter_loads_with_isolated_interpreter_and_no_project(tmp_path):
    code = (
        "import importlib.util, sys;"
        f"spec = importlib.util.spec_from_file_location('rfp', r'{REPORTER_PATH}');"
        "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod);"
        "assert not any(name.startswith('agent_os') for name in sys.modules);"
        "print(mod.fallback_result('Blummer92/agent-os', 3502)['status'])"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "manual-review"


# --- Workflow gating ---------------------------------------------------------


def _workflow_text():
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _report_failure_block():
    text = _workflow_text()
    assert "\n  report-failure:" in text
    return text.split("\n  report-failure:", 1)[1]


def _failure_predicate(classify_result: str, execute_result: str) -> bool:
    # Mirror of the workflow predicate asserted verbatim below.
    return classify_result == "failure" or execute_result == "failure"


@pytest.mark.parametrize(
    "classify_result,execute_result,fires",
    [
        ("failure", "skipped", True),  # classify infra failure (run 39665727697 shape)
        ("success", "failure", True),  # execute infra failure
        ("failure", "failure", True),
        ("success", "success", False),  # happy path: no failure receipt
        ("skipped", "skipped", False),  # noncommand / PR comment / other actor
        ("success", "skipped", False),
        ("cancelled", "cancelled", False),
    ],
)
def test_failure_predicate_truth_table(classify_result, execute_result, fires):
    assert _failure_predicate(classify_result, execute_result) is fires


def test_workflow_report_failure_job_shape():
    text = _workflow_text()
    block = _report_failure_block()
    assert "needs: [classify, execute]" in block
    assert (
        "if: ${{ always() && (needs.classify.result == 'failure' || needs.execute.result == 'failure') }}"
        in block
    )
    # Job-scoped least privilege; top level unchanged.
    assert "permissions:\n      contents: read\n      issues: write" in block
    assert text.startswith(
        "name: Agent OS CKR6 Lessons Bridge\n\non:\n  issue_comment:\n    types: [created]\n\npermissions:\n  contents: read\n"
    )
    # Independence from the install graph it reports on.
    assert "pip install" not in block
    assert "agent_os_execution_service" not in block
    assert "scripts/ckr6_failure_postback.py" in block
    # The existing ingress gate and happy path are untouched.
    assert (
        "if: ${{ github.event.issue.pull_request == null && github.actor == 'Blummer92' && startsWith(github.event.comment.body, '/agent-os ckr6 ') }}"
        in text
    )
    assert text.count("- name: Install existing Agent OS runtime") == 2
    assert "- name: Post bounded CKR6 result to issue" in text
    assert (
        "concurrency:\n  group: agent-os-ckr6-${{ github.repository_id }}-${{ github.event.issue.number }}\n  cancel-in-progress: false"
        in text
    )


def test_workflow_yaml_parses_and_jobs_are_exactly_the_three_expected():
    yaml = pytest.importorskip("yaml")
    document = yaml.safe_load(_workflow_text())
    assert set(document["jobs"]) == {"classify", "execute", "report-failure"}
    job = document["jobs"]["report-failure"]
    assert job["needs"] == ["classify", "execute"]
    assert job["permissions"] == {"contents": "read", "issues": "write"}
