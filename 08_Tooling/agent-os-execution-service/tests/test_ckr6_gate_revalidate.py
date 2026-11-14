"""Offline controls for the default-branch CKR6 comment revalidation lane."""
from __future__ import annotations

import pytest

from agent_os_execution_service import ckr6_gate_revalidate as r

SHA = "a" * 40
REPO = r.REPO
EVENT = {
    "repository": {"full_name": REPO},
    "issue": {"number": 2425},
    "comment": {"id": 100, "user": {"id": r.OWNER_ID},
                "body": '/agent-os ckr6 {"operation":"issue-start"}'},
}


def pr(number=3966, sha=SHA, body="Part of #2425", branch="agent/test"):
    return {
        "number": number, "state": "open", "merged": False, "body": body,
        "head": {"sha": sha, "ref": branch, "repo": {"full_name": REPO}},
    }


def runs(number=3966, sha=SHA, branch="agent/test"):
    return {"workflow_runs": [{
        "id": 88, "created_at": "2026-11-14T04:00:00Z",
        "head_sha": sha, "head_branch": branch, "event": "pull_request",
        "path": ".github/workflows/" + r.WORKFLOW,
        "pull_requests": [{"number": number}],
    }]}


def test_trusted_owner_and_producer_trigger():
    assert r.triggered(EVENT)
    bot = {**EVENT, "comment": {"id": 101, "user": {"id": r.BOT_ID},
                                "body": "<!-- agent-os-ckr6-result:v1 -->\n{}"}}
    assert r.triggered(bot)


@pytest.mark.parametrize("change", [
    {"repository": {"full_name": "someone/else"}},
    {"issue": {"number": True}},
    {"comment": {"id": 1, "user": {"id": 6}, "body": "/agent-os ckr6 {}"}},
    {"comment": {"id": 1, "user": {"id": r.OWNER_ID}, "body": "ordinary comment"}},
    {"comment": {"id": 1, "user": {"id": r.BOT_ID}, "body": "/agent-os ckr6 {}"}},
])
def test_untrusted_comment_never_triggers(change):
    assert not r.triggered({**EVENT, **change})


def test_select_run_binds_exact_pr_head_and_identity():
    assert r.select_run(pr(), runs()) == 88
    assert r.select_run(pr(3967), runs()) is None
    assert r.select_run(pr(sha="b" * 40), runs()) is None
    assert r.select_run(pr(branch="another"), runs()) is None
    assert r.select_run({**pr(), "state": "closed"}, runs()) is None
    assert r.select_run({**pr(), "head": {**pr()["head"], "repo": {"full_name": "fork/name"}}}, runs()) is None


def test_missing_or_bad_association_is_never_accepted():
    data = runs()
    data["workflow_runs"][0]["pull_requests"] = []
    assert r.select_run(pr(), data) is None
    data["workflow_runs"][0]["pull_requests"] = None
    with pytest.raises(ValueError, match="association"):
        r.select_run(pr(), data)


def test_wrong_workflow_never_rerun():
    data = runs()
    data["workflow_runs"][0]["path"] = ".github/workflows/other.yml"
    assert r.select_run(pr(), data) is None


def test_issue_comment_selects_only_matching_pr(monkeypatch):
    requests = []
    def fake(method, path, token):
        requests.append((method, path))
        if path.startswith("/pulls?"):
            return [pr(), pr(4000, body="Part of #3418"),
                    pr(4001, body="Part of #2425\nPart of #3418")]
        raise AssertionError(path)
    monkeypatch.setattr(r, "api", fake)
    assert r.current_targets(EVENT, "token") == [3966]
    assert len(requests) == 1


def test_pr_thread_does_not_enumerate_issue_population():
    e = {**EVENT, "issue": {"number": 3966, "pull_request": {"url": "safe"}}}
    assert r.current_targets(e, "unused") == [3966]


def test_revalidate_reruns_only_verified_existing_run(monkeypatch):
    calls = []
    def fake(method, path, token):
        calls.append((method, path))
        if path.startswith("/pulls?"):
            return [pr()]
        if path == "/pulls/3966":
            return pr()
        if path.startswith("/actions/workflows/"):
            return runs()
        if path == "/actions/runs/88/rerun" and method == "POST":
            return None
        raise AssertionError((method, path))
    monkeypatch.setattr(r, "api", fake)
    assert r.revalidate(EVENT, "token") == [88]
    assert [method for method, _ in calls] == ["GET", "GET", "GET", "POST"]


def test_untrusted_trigger_never_fetches_or_writes(monkeypatch):
    monkeypatch.setattr(r, "api", lambda *_: pytest.fail("unauthorized provider call"))
    event = {**EVENT, "comment": {"id": 44, "user": {"id": 9}, "body": "noise"}}
    assert r.revalidate(event, "token") == []


def test_unverified_run_causes_no_post(monkeypatch):
    writes = []
    def fake(method, path, token):
        if method == "POST":
            writes.append(path)
        if path.startswith("/pulls?"):
            return [pr()]
        if path == "/pulls/3966":
            return pr()
        if path.startswith("/actions/workflows/"):
            return {"workflow_runs": [{"id": 88, "head_sha": SHA,
                                        "head_branch": "agent/test",
                                        "event": "pull_request",
                                        "path": ".github/workflows/" + r.WORKFLOW,
                                        "pull_requests": None}]}
        return None
    monkeypatch.setattr(r, "api", fake)
    with pytest.raises(ValueError):
        r.revalidate(EVENT, "token")
    assert writes == []


def test_live_workflow_has_no_status_creation_or_merge_rights():
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    text = (root / ".github/workflows/agent-os-ckr6-comment-revalidation.yml").read_text()
    assert "issue_comment:" in text
    assert "actions: write" in text
    assert "persist-credentials: false" in text
    assert "statuses: write" not in text
    assert "checks: write" not in text
    assert "contents: write" not in text
    assert "pull-requests: write" not in text
