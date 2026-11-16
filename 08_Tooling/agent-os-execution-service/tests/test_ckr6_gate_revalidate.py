"""Offline controls for the default-branch CKR6 comment revalidation lane."""
from __future__ import annotations

import pytest

from agent_os_execution_service import ckr6_gate_revalidate as r

SHA = "a" * 40
REPO = r.REPO
EVENT = {
    "repository": {"full_name": REPO},
    "issue": {"number": 2425},
    "comment": {
        "id": 100, "created_at": "2026-11-14T16:00:00Z",
        "updated_at": "2026-11-14T16:00:00Z",
        "user": {"id": r.OWNER_ID, "login": "Blummer92"},
        "body": '/agent-os ckr6 {"operation":"issue-start","repository":"Blummer92/agent-os",'
                '"issue_number":2425,"task_reference":"PR #3966 head ' + SHA + '"}',
    },
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
    with pytest.raises(ValueError, match="gate-run-association-unverified"):
        r.select_run(pr(3967), runs())
    assert r.select_run(pr(sha="b" * 40), runs()) is None
    assert r.select_run(pr(branch="another"), runs()) is None
    assert r.select_run({**pr(), "state": "closed"}, runs()) is None
    assert r.select_run({**pr(), "head": {**pr()["head"], "repo": {"full_name": "fork/name"}}}, runs()) is None


def test_missing_or_bad_association_is_never_accepted():
    data = runs()
    data["workflow_runs"][0]["pull_requests"] = []
    with pytest.raises(ValueError, match="association"):
        r.select_run(pr(), data)
    data["workflow_runs"][0]["pull_requests"] = None
    with pytest.raises(ValueError, match="association"):
        r.select_run(pr(), data)


def test_incomplete_run_page_never_selects_an_unproven_latest_run():
    page = runs()
    page["workflow_runs"] = page["workflow_runs"] * 100
    with pytest.raises(ValueError, match="incomplete"):
        r.select_run(pr(), page)


def test_no_matching_run_is_a_blocker_not_a_silent_success(monkeypatch):
    writes = []

    def fake(method, path, token):
        if method == "POST":
            writes.append(path)
        if path.startswith("/pulls?"):
            return [pr()]
        if path == "/pulls/3966":
            return pr()
        if path.startswith("/actions/workflows/"):
            return {"workflow_runs": []}
        raise AssertionError(path)

    monkeypatch.setattr(r, "api", fake)
    with pytest.raises(ValueError, match="gate-run-missing"):
        r.revalidate(EVENT, "token")
    assert writes == []


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
    assert requests == []  # no broad PR census: one explicit target only


def test_pr_thread_does_not_enumerate_issue_population():
    e = {**EVENT,
         "issue": {"number": 3966, "pull_request": {"url": "safe"}},
         "comment": {**EVENT["comment"], "body": EVENT["comment"]["body"].replace(
             '"issue_number":2425', '"issue_number":3966')}}
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
    assert [method for method, _ in calls] == ["GET", "GET", "POST"]


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
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in text
    assert "actions/checkout@v7" not in text
    assert "actions/setup-python@v7" not in text
    assert 'python3 -m venv "$RUNNER_TEMP/ckr6-venv"' in text


# #3418 live 2026-11-14: learning requests must not census three legacy Draft PRs.
def _event_for(data, *, issue_number=3418, pr_thread=False):
    import json
    event = {
        "repository": {"full_name": REPO},
        "issue": {"number": issue_number},
        "comment": {
            "id": 6880156571, "created_at": "2026-11-14T15:55:08Z",
            "updated_at": "2026-11-14T15:55:08Z",
            "user": {"id": r.OWNER_ID, "login": "Blummer92"},
            "body": "/agent-os ckr6 " + json.dumps(data, sort_keys=True, separators=(",", ":")),
        },
    }
    if pr_thread:
        event["issue"]["pull_request"] = {"url": "https://api.github.com/repos/Blummer92/agent-os/pulls/3824"}
    return event


def test_live_3418_positive_lesson_retrieval_does_not_census_prs(monkeypatch):
    payload = {
        "operation": "issue-start", "repository": REPO, "issue_number": 3418,
        "task_reference": "CKR6-POSITIVE-READ-20261114-R02: verify live eligible lesson selection",
        "ecosystem_hints": ["agent-os"], "language_hints": ["python"],
        "capability_keywords": ["testing", "failure-avoidance", "lessons-learned"],
        "target_path_hints": ["08_Tooling/agent-os-execution-service/src/agent_os_execution_service/lesson_learning_loop.py"],
        "canonical_rule_refs": ["https://github.com/Blummer92/agent-os/issues/3418"],
        "known_knowledge_refs": ["LL-87"], "specialized_knowledge_required": True,
    }
    monkeypatch.setattr(r, "api", lambda *_: pytest.fail("learning request must not read PR population"))
    result = r.evaluate(_event_for(payload), "unused")
    assert result["disposition"] == "not-applicable"
    assert result["run_ids"] == []


def test_live_3418_refinement_does_not_census_prs(monkeypatch):
    payload = {
        "operation": "lesson-refinement", "repository": REPO, "issue_number": 3418,
        "task_reference": "CKR7-LIVE-20261114-R03-verify-owner-LL87-use-receipt",
        "refinement": {
            "lesson_id": "LL-87", "source_revision": "2026-10-05T13:06:00.000Z",
            "receipt_refs": ["https://api.github.com/repos/Blummer92/agent-os/issues/comments/6880266923"],
            "evidence": [{
                "reference": "https://github.com/Blummer92/agent-os/pull/3824",
                "effect": "confirms",
                "canonical_github_refs": ["https://github.com/Blummer92/agent-os/issues/3418"],
                "evidence_refs": ["https://github.com/Blummer92/agent-os/pull/3824"],
            }],
        },
    }
    monkeypatch.setattr(r, "api", lambda *_: pytest.fail("refinement must not rerun unrelated PR gate"))
    result = r.evaluate(_event_for(payload), "unused")
    assert result == {"disposition": "not-applicable", "reason_code": "learning-operation", "run_ids": []}


def test_explicit_issue_pr_head_is_one_target_not_a_linked_pr_sweep():
    event = _event_for({
        "operation": "issue-start", "repository": REPO, "issue_number": 3418,
        "task_reference": "PR #3824 exact head " + SHA,
    })
    assert r.current_targets(event, "unused") == [3824]


def test_exact_pr_without_initial_run_stays_blocked(monkeypatch):
    event = _event_for({
        "operation": "issue-start", "repository": REPO, "issue_number": 3418,
        "task_reference": "PR #3824 exact head " + SHA,
    })
    writes = []
    def fake(method, path, token):
        if method == "POST":
            writes.append(path)
        if path == "/pulls/3824":
            return pr(number=3824, body="Part of #3418")
        if path.startswith("/actions/workflows/"):
            return {"total_count": 0, "workflow_runs": []}
        raise AssertionError(path)
    monkeypatch.setattr(r, "api", fake)
    with pytest.raises(r.RevalidationBlocked, match="gate-run-missing"):
        r.evaluate(event, "unused")
    assert writes == []


def test_closed_pr_is_not_a_rerun_target(monkeypatch):
    event = _event_for({
        "operation": "issue-start", "repository": REPO, "issue_number": 3418,
        "task_reference": "PR #3824 exact head " + SHA,
    })
    calls = []
    def fake(method, path, token):
        calls.append(path)
        assert path == "/pulls/3824"
        return pr(number=3824, body="Part of #3418") | {"state": "closed"}
    monkeypatch.setattr(r, "api", fake)
    assert r.evaluate(event, "unused")["reason_code"] == "pr-closed"
    assert calls == ["/pulls/3824"]


def test_missing_published_run_association_is_explicit_stop():
    data = runs(number=3966)
    data["workflow_runs"][0]["pull_requests"] = []
    with pytest.raises(r.RevalidationBlocked, match="gate-run-association-unverified"):
        r.select_run(pr(), data)


def test_real_api_permission_denial_does_not_log_body(monkeypatch):
    from urllib.error import HTTPError
    def forbidden(*args, **kwargs):
        raise HTTPError("https://api.github.com/", 403, "private-token-is-not-a-reason", {}, None)
    monkeypatch.setattr(r.urllib.request, "urlopen", forbidden)
    with pytest.raises(r.RevalidationBlocked, match="rerun-permission-denied"):
        r.api("POST", "/actions/runs/88/rerun", "secret-must-not-be-shown")


def test_edited_owner_record_fails_closed_even_if_head_is_exact(monkeypatch):
    event = _event_for({
        "operation": "issue-start", "repository": REPO, "issue_number": 3418,
        "task_reference": "PR #3824 exact head " + SHA,
    })
    event["comment"]["updated_at"] = "2026-11-14T15:56:08Z"
    monkeypatch.setattr(r, "api", lambda *_: pytest.fail("edited request cannot route"))
    with pytest.raises(r.RevalidationBlocked, match="request-provenance-unverified"):
        r.evaluate(event, "unused")

def test_postback_complete_refuses_missing_result_and_never_posts(monkeypatch):
    event = _event_for({
        "operation": "failed-repair", "repository": REPO, "issue_number": 3418,
        "task_reference": "PR #3824 exact head " + SHA,
        "attempt_id": "one", "failed_hypothesis": "h", "result_summary": "r",
        "repair_context": "ci-diagnosis",
    })
    calls = []
    def fake(method, path, token):
        calls.append((method, path))
        if "/comments?per_page=100&since=" in path:
            return []
        raise AssertionError(path)
    monkeypatch.setattr(r, "api", fake)
    with pytest.raises(r.RevalidationBlocked, match="result-not-returned"):
        r.evaluate(event, "unused", postback_complete=True)
    assert not any(method == "POST" for method, _ in calls)


def test_postback_complete_requires_single_correlated_bot_result(monkeypatch):
    from agent_os_execution_service.ckr6_github_bridge import serialize_ckr6_result_comment
    event = _event_for({
        "operation": "failed-repair", "repository": REPO, "issue_number": 3418,
        "task_reference": "PR #3824 exact head " + SHA,
        "attempt_id": "one", "failed_hypothesis": "h", "result_summary": "r",
        "repair_context": "ci-diagnosis",
    })
    result = {
        "operation": "failed-repair", "repository": REPO, "issue_number": 3418,
        "status": "insufficient", "attempt_id": "one",
        "selected_lesson_ids": [], "mutation_admissible": False,
    }
    receipt = {
        "id": 200, "user": {"id": r.BOT_ID},
        "created_at": "2026-11-14T15:56:08Z",
        "updated_at": "2026-11-14T15:56:08Z",
        "body": serialize_ckr6_result_comment(result, request_comment_id=6880156571),
    }
    calls = []
    def fake(method, path, token):
        calls.append((method, path))
        if "/comments?per_page=100&since=" in path:
            return [receipt]
        if path == "/pulls/3824":
            return pr(3824, sha=SHA, body="Part of #3418")
        if path.startswith("/actions/workflows/"):
            return runs()
        if path == "/actions/runs/88":
            return {"id": 88, "status": "completed", "run_attempt": 1}
        if path == "/actions/runs/88/rerun" and method == "POST":
            return None
        raise AssertionError(path)
    monkeypatch.setattr(r, "api", fake)
    # The request and receipt are verified, but the synthetic run association
    # belongs to PR #3966, so this must fail closed before any POST.
    with pytest.raises(r.RevalidationBlocked, match="gate-run"):
        r.evaluate(event, "unused", postback_complete=True)
    assert not any(method == "POST" for method, _ in calls)
    receipt["body"] = serialize_ckr6_result_comment(
        {**result, "attempt_id": "wrong"}, request_comment_id=6880156571
    )
    with pytest.raises(r.RevalidationBlocked, match="result-provenance-unverified"):
        r.evaluate(event, "unused", postback_complete=True)


RECEIPT_AT = "2026-11-14T15:56:08Z"


def test_postback_complete_rejects_active_or_repeated_run(monkeypatch):
    event = _event_for({
        "operation": "failed-repair", "repository": REPO, "issue_number": 3418,
        "task_reference": "PR #3824 exact head " + SHA,
        "attempt_id": "one", "failed_hypothesis": "h", "result_summary": "r",
        "repair_context": "ci-diagnosis",
    })
    # Exercise the completed-run guard after the separately tested receipt
    # check; never create a check or synthesize a successful gate.
    monkeypatch.setattr(r, "_completed_result_for_owner", lambda *_: {"status": "insufficient", "receipt_created_at": RECEIPT_AT})
    def fake(method, path, token):
        if path == "/pulls/3824":
            return pr(3824, sha=SHA, body="Part of #3418")
        if path.startswith("/actions/workflows/"):
            listing = runs()
            listing["workflow_runs"][0]["pull_requests"] = [{"number": 3824}]
            return listing
        if path == "/actions/runs/88":
            return {"id": 88, "status": "in_progress", "run_attempt": 1}
        if method == "POST":
            pytest.fail("active gate must not be rerun")
        raise AssertionError(path)
    monkeypatch.setattr(r, "api", fake)
    with pytest.raises(r.RevalidationBlocked, match="gate-run-in-progress"):
        r.evaluate(event, "unused", postback_complete=True)



def test_postback_waits_for_existing_gate_to_complete_then_reruns_once(monkeypatch):
    event, calls = _postback_fixture(monkeypatch, {
        "id": 88, "status": "completed", "run_attempt": 1,
        "run_started_at": "2026-11-14T15:50:00Z",
    })
    original = r.api
    count = {"n": 0}
    sleeps = []
    def fake(method, path, token):
        if method == "GET" and path == "/actions/runs/88":
            count["n"] += 1
            if count["n"] < 3:
                calls.append((method, path))
                return {"id": 88, "status": "in_progress", "run_attempt": 1}
        return original(method, path, token)
    monkeypatch.setattr(r, "api", fake)
    monkeypatch.setattr(r.time, "sleep", lambda seconds: sleeps.append(seconds))
    result = r.evaluate(event, "unused", postback_complete=True)
    assert result["disposition"] == "rerun-requested"
    assert count["n"] == 3
    assert sleeps == [5, 5]
    assert [x for x in calls if x[0] == "POST"] == [
        ("POST", "/actions/runs/88/rerun")
    ]


def test_postback_wait_timeout_is_finite_and_posts_nothing(monkeypatch):
    event, calls = _postback_fixture(monkeypatch, {
        "id": 88, "status": "in_progress", "run_attempt": 1,
    })
    sleeps = []
    monkeypatch.setattr(r.time, "sleep", lambda seconds: sleeps.append(seconds))
    with pytest.raises(r.RevalidationBlocked, match="gate-run-in-progress"):
        r.evaluate(event, "unused", postback_complete=True)
    assert len([x for x in calls if x == ("GET", "/actions/runs/88")]) == 13
    assert sleeps == [5] * 12
    assert not any(x[0] == "POST" for x in calls)


@pytest.mark.parametrize("payload", [
    {"id": 89, "status": "completed", "run_attempt": 1},
    {"id": 88, "status": "completed", "run_attempt": True},
    {"id": 88, "status": "unknown", "run_attempt": 1},
    {"id": 88, "status": "completed", "run_attempt": 0},
])
def test_postback_wait_rejects_invalid_run_without_post(monkeypatch, payload):
    event, calls = _postback_fixture(monkeypatch, payload)
    monkeypatch.setattr(r.time, "sleep", lambda _: pytest.fail("invalid state must not sleep"))
    with pytest.raises(r.RevalidationBlocked, match="gate-run-invalid"):
        r.evaluate(event, "unused", postback_complete=True)
    assert not any(x[0] == "POST" for x in calls)


def test_postback_immediate_completion_never_sleeps(monkeypatch):
    event, calls = _postback_fixture(monkeypatch, {
        "id": 88, "status": "completed", "run_attempt": 2,
        "run_started_at": "2026-11-14T15:56:09Z",
    })
    monkeypatch.setattr(r.time, "sleep", lambda _: pytest.fail("completed gate must not wait"))
    result = r.evaluate(event, "unused", postback_complete=True)
    assert result["reason_code"] == "already-rerun"
    assert not any(x[0] == "POST" for x in calls)


def test_producer_postback_job_separates_actions_write_from_notion_secret():
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github/workflows/agent-os-ckr6.yml").read_text()
    old = (root / ".github/workflows/agent-os-ckr6-comment-revalidation.yml").read_text()
    new_job = workflow.split("  revalidate-after-postback:", 1)[1].split("  report-failure:", 1)[0]
    assert "needs: [classify, execute]" in new_job
    assert "actions: write" in new_job
    assert "--postback-complete" in new_job
    assert "NOTION_TOKEN" not in new_job
    assert "contents: write" not in new_job
    assert "pull-requests: write" not in new_job
    assert "github.event.comment.user.id == 32861845" not in old
    assert "if: ${{ false }}" in old
    assert "github.event.comment.user.id == 41898282" not in old



def test_postback_comment_population_boundary_100_fails_closed_99_is_complete(monkeypatch):
    """One valid receipt does not make a full, possibly truncated page complete."""
    from agent_os_execution_service.ckr6_github_bridge import serialize_ckr6_result_comment

    event = _event_for({
        "operation": "failed-repair", "repository": REPO, "issue_number": 3418,
        "task_reference": "PR #3824 exact head " + SHA,
        "attempt_id": "one", "failed_hypothesis": "h", "result_summary": "r",
        "repair_context": "ci-diagnosis",
    })
    payload = {
        "operation": "failed-repair", "repository": REPO, "issue_number": 3418,
        "status": "insufficient", "attempt_id": "one",
        "selected_lesson_ids": [], "mutation_admissible": False,
    }
    receipt = {
        "id": 200, "user": {"id": r.BOT_ID},
        "created_at": "2026-11-14T15:56:08Z",
        "updated_at": "2026-11-14T15:56:08Z",
        "body": serialize_ckr6_result_comment(payload, request_comment_id=6880156571),
    }
    filler = [
        {"id": i + 300, "user": {"id": 12345},
         "created_at": "2026-11-14T15:56:09Z",
         "updated_at": "2026-11-14T15:56:09Z", "body": "irrelevant"}
        for i in range(99)
    ]
    state = {"count": 100}
    calls = []
    def fake(method, path, token):
        calls.append((method, path))
        assert method == "GET"
        assert "/comments?per_page=100&since=" in path
        return [receipt, *filler[:state["count"] - 1]]
    monkeypatch.setattr(r, "api", fake)
    with pytest.raises(r.RevalidationBlocked, match="result-provenance-unverified"):
        r._completed_result_for_owner(event, "unused")
    assert len(calls) == 1
    assert all(method != "POST" for method, _ in calls)

    state["count"] = 99
    calls.clear()
    result = r._completed_result_for_owner(event, "unused")
    assert result["request_comment_id"] == event["comment"]["id"]
    assert result["status"] == "insufficient"
    assert len(calls) == 1
    assert all(method != "POST" for method, _ in calls)


def _postback_fixture(monkeypatch, run_payload, receipt=None):
    event = _event_for({
        "operation": "failed-repair", "repository": REPO, "issue_number": 3418,
        "task_reference": "PR #3824 exact head " + SHA,
        "attempt_id": "one", "failed_hypothesis": "h", "result_summary": "r",
        "repair_context": "ci-diagnosis",
    })
    if receipt is None:
        receipt = {"status": "insufficient", "receipt_created_at": RECEIPT_AT}
    monkeypatch.setattr(r, "_completed_result_for_owner", lambda *_: receipt)
    calls = []

    def fake(method, path, token):
        calls.append((method, path))
        if path == "/pulls/3824":
            return pr(3824, sha=SHA, body="Part of #3418")
        if path.startswith("/actions/workflows/"):
            listing = runs()
            listing["workflow_runs"][0]["pull_requests"] = [{"number": 3824}]
            return listing
        if path == "/actions/runs/88":
            return run_payload
        if path == "/actions/runs/88/rerun" and method == "POST":
            return None
        raise AssertionError(path)
    monkeypatch.setattr(r, "api", fake)
    return event, calls


def test_second_request_same_head_reruns_attempt_two_finished_before_receipt(monkeypatch):
    event, calls = _postback_fixture(monkeypatch, {
        "id": 88, "status": "completed", "run_attempt": 2,
        "run_started_at": "2026-11-14T15:50:00Z",
        "updated_at": "2026-11-14T15:50:30Z"})
    result = r.evaluate(event, "unused", postback_complete=True)
    assert result["disposition"] == "rerun-requested"
    assert [c for c in calls if c[0] == "POST"] == [("POST", "/actions/runs/88/rerun")]


def test_straddling_attempt_started_before_receipt_finished_after_is_rerun(monkeypatch):
    event, calls = _postback_fixture(monkeypatch, {
        "id": 88, "status": "completed", "run_attempt": 2,
        "run_started_at": "2026-11-14T15:56:00Z", "updated_at": "2026-11-14T15:56:40Z"})
    assert r.evaluate(event, "unused", postback_complete=True)["disposition"] == "rerun-requested"
    assert [c for c in calls if c[0] == "POST"] == [("POST", "/actions/runs/88/rerun")]


def test_gate_attempt_started_after_receipt_is_not_rerun_again(monkeypatch):
    for started in ("2026-11-14T15:56:09Z", "2026-11-14T16:30:00Z"):
        event, calls = _postback_fixture(monkeypatch, {
            "id": 88, "status": "completed", "run_attempt": 2,
            "run_started_at": started, "updated_at": "2026-11-14T16:31:00Z"})
        assert r.evaluate(event, "unused", postback_complete=True) == {
            "disposition": "not-applicable", "reason_code": "already-rerun", "run_ids": []}
        assert not any(method == "POST" for method, _ in calls)


def test_missing_or_invalid_timing_fails_closed_without_rerun(monkeypatch):
    bad_runs = [
        {"id": 88, "status": "completed", "run_attempt": 1},
        {"id": 88, "status": "completed", "run_attempt": 1, "run_started_at": "yesterday"},
        {"id": 88, "status": "completed", "run_attempt": 1, "run_started_at": 5},
        # started in the same second as the receipt: ambiguous, fail closed
        {"id": 88, "status": "completed", "run_attempt": 1, "run_started_at": RECEIPT_AT},
        # updated_at alone is not accepted as the timing source
        {"id": 88, "status": "completed", "run_attempt": 1, "updated_at": "2026-11-14T15:50:00Z"},
    ]
    for payload in bad_runs:
        event, calls = _postback_fixture(monkeypatch, payload)
        with pytest.raises(r.RevalidationBlocked, match="gate-run-invalid"):
            r.evaluate(event, "unused", postback_complete=True)
        assert not any(method == "POST" for method, _ in calls)
    good = {"id": 88, "status": "completed", "run_attempt": 1, "run_started_at": "2026-11-14T15:50:00Z"}
    for receipt in ({"status": "insufficient"},
                    {"status": "insufficient", "receipt_created_at": "bad"}):
        event, calls = _postback_fixture(monkeypatch, good, receipt=receipt)
        with pytest.raises(r.RevalidationBlocked, match="gate-run-invalid"):
            r.evaluate(event, "unused", postback_complete=True)
        assert not any(method == "POST" for method, _ in calls)


def test_receipt_created_at_is_carried_from_the_matching_bot_receipt(monkeypatch):
    from agent_os_execution_service.ckr6_github_bridge import serialize_ckr6_result_comment
    event = _event_for({
        "operation": "failed-repair", "repository": REPO, "issue_number": 3418,
        "task_reference": "PR #3824 exact head " + SHA,
        "attempt_id": "one", "failed_hypothesis": "h", "result_summary": "r",
        "repair_context": "ci-diagnosis",
    })
    payload = {
        "operation": "failed-repair", "repository": REPO, "issue_number": 3418,
        "status": "insufficient", "attempt_id": "one",
        "selected_lesson_ids": [], "mutation_admissible": False,
    }
    receipt = {
        "id": 200, "user": {"id": r.BOT_ID},
        "created_at": "2026-11-14T15:56:08Z", "updated_at": "2026-11-14T15:56:08Z",
        "body": serialize_ckr6_result_comment(payload, request_comment_id=event["comment"]["id"]),
    }
    monkeypatch.setattr(r, "api", lambda *_: [receipt])
    got = r._completed_result_for_owner(event, "unused")
    assert got["receipt_created_at"] == "2026-11-14T15:56:08Z"
    assert r._parse_time("2026-11-14T15:56:08Z") is not None
    assert r._parse_time("2026-11-14T15:56:08") is None
    assert r._parse_time(None) is None


def test_revalidation_job_install_pins_full_runtime_graph_in_isolated_venv():
    from pathlib import Path
    import re
    root = Path(__file__).resolve().parents[3]
    text = (root / ".github/workflows/agent-os-ckr6.yml").read_text(encoding="utf-8")
    block = text.split("- name: Install revalidation runtime in isolated environment")[1]
    bounded = block.split("\n\n", 1)[0]
    installed = re.findall(r"^\s*-e\s+(\S+?)\s*\\?$", bounded, re.MULTILINE)
    assert installed == [
        "08_Tooling/reusable-capability-registry",
        "08_Tooling/agent-memory-context-manager",
        "08_Tooling/workflow-scheduler",
        "src",
        ".",
        "08_Tooling/agent-os-execution-service",
    ]
    assert 'ckr6-revalidation-venv/bin/python" -m pip install' in bounded
    # The step that runs the verifier must use that same isolated interpreter.
    assert "ckr6-revalidation-venv/bin/python" in block.split("Verify completed result", 1)[1]
