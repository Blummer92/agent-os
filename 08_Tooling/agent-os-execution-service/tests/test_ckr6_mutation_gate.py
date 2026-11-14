"""Adversarial tests for the CKR6 mutation-boundary gate (landing-only).

The gate enforces one property: governed work cannot land without a trusted
CKR6 admission bound to the newest owner request on the linked issue or PR
thread. Every test here is a bypass attempt or a fail-closed case: forged,
edited, mis-located, pre-dating, ambiguous, cross-target, stale, or
unanswered results must never admit, and a valid blocked result is STOP
evidence, not an admission.

Fixture records reuse the R07 consumer builders from
test_ckr6_result_consumption. The final class replays the live 2026-11-14
issue #2425 pair (request 6870478787 / result 6870493264, verified via the
GitHub API) verbatim: a real retrieval-required run whose bounded
insufficient result must block, not admit.
"""
from __future__ import annotations

import json

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge
from agent_os_execution_service.ckr6_github_reader import (GitHubIssueCommentReader, GitHubIssueCommentReadUnavailable)
from agent_os_execution_service.ckr6_mutation_gate import (
    ADMITTED,
    BOUNDARY_BLOCKED,
    HEAD_PROPOSAL_UNPROVEN,
    ISSUE_LINK_AMBIGUOUS,
    ISSUE_LINK_MISSING,
    READ_UNAVAILABLE,
    REQUEST_MISSING,
    REQUEST_HEAD_UNBOUND,
    REQUEST_STALE,
    REQUEST_UNANSWERED,
    RESULT_AMBIGUOUS,
    RESULT_INVALID,
    PaginatedIssueCommentReader,
    evaluate_mutation_boundary,
    run_gate,
    _linked_issue_from_pr_body,
)
from test_ckr6_result_consumption import (
    ISSUE,
    REPOSITORY,
    REQUEST_AT,
    REQUEST_ID,
    RESULT_AT,
    RESULT_ID,
    _comment,
    _failed_repair_result,
    _pr_comment,
    _result,
)

OWNER = "Blummer92"
# The owner's exact numeric GitHub account id, from the live 2026-11-14
# request record 6870478787; the gate pins identity to it, not to the login.
OWNER_ID = 32861845
SECOND_REQUEST_AT = "2026-11-11T10:01:00Z"


def _envelope(**changes):
    value = {
        "operation": "issue-start",
        "repository": REPOSITORY,
        "issue_number": ISSUE,
        "task_reference": "gate test",
    }
    value.update(changes)
    return value


def _request_record(envelope=None, *, comment_id=REQUEST_ID, login=OWNER,
                    account_id=OWNER_ID, created_at=REQUEST_AT, edited=False,
                    drop_updated=False, target="issue", body_override=None):
    if body_override is not None:
        body = body_override
    else:
        body = bridge.COMMAND_PREFIX + json.dumps(
            envelope if envelope is not None else _envelope(),
            sort_keys=True, separators=(",", ":"),
        )
    if target == "pr":
        html_url = f"https://github.com/{REPOSITORY}/pull/{ISSUE}#issuecomment-{comment_id}"
    else:
        html_url = f"https://github.com/{REPOSITORY}/issues/{ISSUE}#issuecomment-{comment_id}"
    record = {
        "id": comment_id,
        "body": body,
        "user": {"login": login, "id": account_id, "type": "User"},
        "created_at": created_at,
        "updated_at": created_at,
        "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE}",
        "html_url": html_url,
    }
    if edited:
        record["updated_at"] = SECOND_REQUEST_AT
    if drop_updated:
        del record["updated_at"]
    return record


def _gate(issue_comments, pr_number=None, pr_comments=(), issue_number=ISSUE):
    return evaluate_mutation_boundary(
        repository=REPOSITORY,
        issue_number=issue_number,
        issue_comments=issue_comments,
        pr_number=pr_number,
        pr_comments=pr_comments,
        allowed_actor=OWNER,
    )


# --- admissions ---------------------------------------------------------------

def test_not_needed_result_admits():
    decision = _gate([_request_record(), _comment(_result(status="not-needed",
        substantial_hypothesis_admissible=True, selected_lesson_ids=[], selected_lessons=[],
        reason_codes=["knowledge-not-needed"], notion_read_performed=False, retrieval_required=False))])
    assert decision.admitted is True
    assert decision.reason_code == ADMITTED
    assert decision.operation == "issue-start"
    assert decision.request_comment_id == REQUEST_ID


def test_sufficient_result_with_lessons_admits():
    decision = _gate([_request_record(), _comment(_result())])
    assert decision.admitted is True
    assert decision.status == "sufficient"


def test_failed_repair_result_admits_for_exact_attempt():
    envelope = _envelope(operation="failed-repair", attempt_id="attempt-42",
                         failed_hypothesis="h", result_summary="s")
    decision = _gate([_request_record(envelope), _comment(_failed_repair_result())])
    assert decision.admitted is True
    assert decision.operation == "failed-repair"


def test_pr_thread_pair_admits():
    request = _request_record(target="pr")
    decision = _gate([], pr_number=ISSUE, pr_comments=[request, _pr_comment(_result())])
    assert decision.admitted is True


# --- missing / stale requests fail closed -------------------------------------

def test_no_comments_fails_closed():
    decision = _gate([])
    assert decision.admitted is False
    assert decision.reason_code == REQUEST_MISSING


def test_newer_unanswered_request_not_rescued_by_older_admission():
    older = [_request_record(), _comment(_result())]
    newer_request = _request_record(comment_id=1002, created_at=SECOND_REQUEST_AT)
    decision = _gate(older + [newer_request])
    assert decision.admitted is False
    assert decision.reason_code == REQUEST_UNANSWERED
    assert decision.request_comment_id == 1002


def test_non_owner_request_ignored():
    decision = _gate([_request_record(login="someone-else"), _comment(_result())])
    assert decision.reason_code == REQUEST_MISSING


def test_edited_request_ignored():
    decision = _gate([_request_record(edited=True), _comment(_result())])
    assert decision.reason_code == REQUEST_MISSING


def test_request_without_updated_at_ignored():
    decision = _gate([_request_record(drop_updated=True), _comment(_result())])
    assert decision.reason_code == REQUEST_MISSING


def test_wrong_repository_envelope_ignored():
    decision = _gate([_request_record(_envelope(repository="Blummer92/other")), _comment(_result())])
    assert decision.reason_code == REQUEST_MISSING


def test_envelope_issue_mismatch_ignored():
    decision = _gate([_request_record(_envelope(issue_number=ISSUE + 1)), _comment(_result())])
    assert decision.reason_code == REQUEST_MISSING


def test_malformed_envelope_ignored():
    decision = _gate([_request_record(body_override="/agent-os ckr6 {not json"), _comment(_result())])
    assert decision.reason_code == REQUEST_MISSING


def test_oversized_request_ignored():
    body = "/agent-os ckr6 " + " " * (bridge.MAX_COMMENT_BYTES + 1)
    decision = _gate([_request_record(body_override=body), _comment(_result())])
    assert decision.reason_code == REQUEST_MISSING


def test_learning_operation_never_decides():
    learning = _request_record(
        {"operation": "lesson-candidate", "repository": REPOSITORY,
         "issue_number": ISSUE, "task_reference": "t", "candidate": {"kind": "ci"}},
        comment_id=1002, created_at=SECOND_REQUEST_AT)
    decision = _gate([_request_record(), _comment(_result()), learning])
    assert decision.admitted is True
    assert decision.operation == "issue-start"


# --- forged / invalid results fail closed -------------------------------------

def test_forged_result_author_unanswered():
    forged = _comment(_result(), login="Blummer92", account_id=22961190, account_type="User")
    decision = _gate([_request_record(), forged])
    assert decision.reason_code == REQUEST_UNANSWERED


def test_edited_result_unanswered():
    decision = _gate([_request_record(), _comment(_result(), updated_at="2026-11-11T10:05:00Z")])
    assert decision.reason_code == REQUEST_UNANSWERED


def test_result_predating_request_unanswered():
    decision = _gate([_request_record(), _comment(_result(), comment_id=REQUEST_ID - 1,
                                                  created_at="2026-11-11T09:59:00Z",
                                                  updated_at="2026-11-11T09:59:00Z")])
    assert decision.reason_code == REQUEST_UNANSWERED


def test_result_for_other_request_unanswered():
    decision = _gate([_request_record(), _comment(_result(), request_comment_id=9999)])
    assert decision.reason_code == REQUEST_UNANSWERED


def test_result_with_authority_flag_true_invalid():
    # Producer identity is valid, so the record passes selection's pre-filter;
    # the consumption binding then rejects the forbidden authority claim. The
    # verdict is result-invalid (anomalous trusted-identity payload), still
    # fail-closed.
    decision = _gate([_request_record(), _comment(_result(merge_authorized=True))])
    assert decision.admitted is False
    assert decision.reason_code == RESULT_INVALID


def test_result_with_unexpected_field_invalid():
    comment = _comment(_result())
    payload = bridge.parse_ckr6_result_comment(comment["body"])
    payload["smuggled"] = True
    body = bridge.CKR6_RESULT_MARKER + "\n" + json.dumps(payload, sort_keys=True, separators=(",", ":"))
    record = dict(comment, body=body)
    decision = _gate([_request_record(), record])
    assert decision.reason_code == RESULT_INVALID


def test_ambiguous_results_fail():
    first = _comment(_result())
    second = _comment(_result(reason_codes=["different"]), comment_id=RESULT_ID + 1,
                      created_at="2026-11-11T10:00:31Z", updated_at="2026-11-11T10:00:31Z")
    decision = _gate([_request_record(), first, second])
    assert decision.reason_code == RESULT_AMBIGUOUS


def test_identical_duplicate_results_collapse():
    first = _comment(_result())
    second = _comment(_result(), comment_id=RESULT_ID + 1,
                      created_at="2026-11-11T10:00:31Z", updated_at="2026-11-11T10:00:31Z")
    decision = _gate([_request_record(), first, second])
    assert decision.admitted is True


def test_cross_target_result_does_not_answer_issue_request():
    decision = _gate([_request_record(), _pr_comment(_result())])
    assert decision.reason_code == REQUEST_UNANSWERED


def test_failed_repair_result_without_attempt_invalid():
    envelope = _envelope(operation="failed-repair", attempt_id="attempt-42",
                         failed_hypothesis="h", result_summary="s")
    decision = _gate([_request_record(envelope), _comment(_failed_repair_result(attempt_id=None))])
    assert decision.reason_code == RESULT_INVALID


def test_failed_repair_result_for_other_attempt_invalid():
    envelope = _envelope(operation="failed-repair", attempt_id="attempt-42",
                         failed_hypothesis="h", result_summary="s")
    decision = _gate([_request_record(envelope), _comment(_failed_repair_result(attempt_id="attempt-99"))])
    assert decision.reason_code == RESULT_INVALID


# --- blocked results are STOP evidence, never admission ------------------------

def test_insufficient_result_blocks():
    decision = _gate([_request_record(), _comment(_result(
        status="insufficient", substantial_hypothesis_admissible=False,
        selected_lesson_ids=[], selected_lessons=[], reason_codes=["no-relevant-candidate"]))])
    assert decision.admitted is False
    assert decision.reason_code == BOUNDARY_BLOCKED
    assert decision.status == "insufficient"
    assert "no-relevant-candidate" in decision.detail


def test_infrastructure_fallback_blocks():
    fallback = {
        "operation": "unknown", "repository": REPOSITORY, "issue_number": ISSUE,
        "status": "manual-review", "reason_codes": ["ckr6-result-unavailable"],
        "substantial_hypothesis_admissible": False, "mutation_admissible": False,
        "execution_authorized": False, "github_writes_authorized": False,
        "merge_authorized": False, "closure_authorized": False,
        "side_effects_performed": False, "selected_lesson_ids": [],
    }
    decision = _gate([_request_record(), _comment(fallback)])
    assert decision.admitted is False
    assert decision.reason_code == BOUNDARY_BLOCKED
    assert decision.status == "manual-review"


def test_failed_repair_mutation_false_blocks():
    envelope = _envelope(operation="failed-repair", attempt_id="attempt-42",
                         failed_hypothesis="h", result_summary="s")
    blocked = _failed_repair_result(status="insufficient", mutation_admissible=False,
                                    retry_reentry_outcome="unavailable-or-failed")
    decision = _gate([_request_record(envelope), _comment(blocked)])
    assert decision.admitted is False
    assert decision.reason_code == BOUNDARY_BLOCKED


# --- trusted read path ---------------------------------------------------------

def test_unavailable_read_fails_closed():
    reader = GitHubIssueCommentReader(token_provider=None)
    decision = run_gate(reader=reader, repository=REPOSITORY, issue_number=ISSUE)
    assert decision.admitted is False
    assert decision.reason_code == READ_UNAVAILABLE
    assert decision.detail == "HOST_READ_PATH_UNAVAILABLE"


# --- linked-issue extraction ---------------------------------------------------

@pytest.mark.parametrize("body", [
    "Closes #2425",
    "Part of #2425",
    "Part of https://github.com/Blummer92/agent-os/issues/2425",
    "Part of #2425\n\nNon-closing: #2425, #3418",
    "Part of #2425\n\nCloses #2425",
    "fixed https://github.com/Blummer92/agent-os/issues/2425",
    "closes https://github.com/BLUMMER92/Agent-OS/issues/2425",
    "Closes #2425 twice: closes #2425",
    "Summary paragraph.\n\nResolves #2425\n\nAlso mentions #3000 non-closing.",
])
def test_linked_issue_extraction(body):
    assert _linked_issue_from_pr_body(body) == 2425


def test_linked_issue_missing_fails_closed():
    with pytest.raises(ValueError, match=ISSUE_LINK_MISSING):
        _linked_issue_from_pr_body("No issue link here. See #2425.")


@pytest.mark.parametrize("body", [
    "Part of #2425\nPart of #3418",
    "Part of #2425\nCloses #3418",
    "Closes #2425\nPart of #3418",
])
def test_non_closing_linkage_conflict_fails_closed(body):
    with pytest.raises(ValueError, match=ISSUE_LINK_AMBIGUOUS):
        _linked_issue_from_pr_body(body)


@pytest.mark.parametrize("body", [
    "Intro says Part of #2425 in prose.",
    "Non-closing: #2425",
    "```md\nPart of #2425\n```",
    "> Part of #2425",
    "Part of https://github.com/another/repo/issues/2425",
])
def test_non_authoritative_part_of_references_do_not_bind(body):
    with pytest.raises(ValueError, match=ISSUE_LINK_MISSING):
        _linked_issue_from_pr_body(body)


def test_linked_issue_ambiguous_fails_closed():
    with pytest.raises(ValueError, match=ISSUE_LINK_AMBIGUOUS):
        _linked_issue_from_pr_body("Closes #2425 and fixes #3000")


# --- live production replay: issue #2425, 2026-11-14 --------------------------
# Request 6870478787 (Blummer92 via chatgpt-codex-connector, 02:49:25Z) and
# result 6870493264 (github-actions[bot], 02:50:29Z), captured verbatim from
# the GitHub API. A real retrieval-required run on main 4c226b2d whose bounded
# insufficient result is valid STOP evidence: it must block, not admit.

REAL_REQUEST_RECORD = {'id': 6870478787, 'body': '/agent-os ckr6 {"operation":"issue-start","repository":"Blummer92/agent-os","issue_number":2425,"task_reference":"Investigate and fix CKR6 issue-start gate behavior evidenced by PR #3952 result #6870464285: specialized-knowledge-required HOST10 test-only repair returned insufficient/no-relevant-candidate after five rejected lessons LL-64 to LL-68; determine legitimate relevance, source metadata or materiality resolution without bypassing admission or unauthorized Notion changes","specialized_knowledge_required":true}', 'user': {'login': 'Blummer92', 'id': 32861845, 'type': 'User'}, 'created_at': '2026-11-14T02:49:25Z', 'updated_at': '2026-11-14T02:49:25Z', 'issue_url': 'https://api.github.com/repos/Blummer92/agent-os/issues/2425', 'html_url': 'https://github.com/Blummer92/agent-os/issues/2425#issuecomment-6870478787', 'performed_via_github_app': {'id': 1144995, 'client_id': 'Iv23liVemv8A9if9v0F2', 'slug': 'chatgpt-codex-connector', 'node_id': 'A_kwHOAOQ6Gs4AEXij', 'owner': {'login': 'openai', 'id': 14957082, 'node_id': 'MDEyOk9yZ2FuaXphdGlvbjE0OTU3MDgy', 'avatar_url': 'https://avatars.githubusercontent.com/u/14957082?v=4', 'gravatar_id': '', 'url': 'https://api.github.com/users/openai', 'html_url': 'https://github.com/openai', 'followers_url': 'https://api.github.com/users/openai/followers', 'following_url': 'https://api.github.com/users/openai/following{/other_user}', 'gists_url': 'https://api.github.com/users/openai/gists{/gist_id}', 'starred_url': 'https://api.github.com/users/openai/starred{/owner}{/repo}', 'subscriptions_url': 'https://api.github.com/users/openai/subscriptions', 'organizations_url': 'https://api.github.com/users/openai/orgs', 'repos_url': 'https://api.github.com/users/openai/repos', 'events_url': 'https://api.github.com/users/openai/events{/privacy}', 'received_events_url': 'https://api.github.com/users/openai/received_events', 'type': 'Organization', 'user_view_type': 'public', 'site_admin': False}, 'name': 'ChatGPT Codex Connector', 'description': 'Bring ChatGPT and Codex to your GitHub repositories.', 'external_url': 'https://www.chatgpt.com', 'html_url': 'https://github.com/apps/chatgpt-codex-connector', 'created_at': '2025-02-14T01:37:05Z', 'updated_at': '2026-09-23T18:52:59Z', 'permissions': {'actions': 'write', 'checks': 'read', 'contents': 'write', 'emails': 'read', 'issues': 'write', 'metadata': 'read', 'pull_requests': 'write', 'statuses': 'read', 'workflows': 'write'}, 'events': ['check_run', 'check_suite', 'commit_comment', 'issues', 'issue_comment', 'pull_request', 'pull_request_review', 'pull_request_review_comment', 'pull_request_review_thread', 'repository', 'status', 'sub_issues']}}
REAL_RESULT_RECORD = {'id': 6870493264, 'body': '<!-- agent-os-ckr6-result:v1 -->\n{"canonical_github_refs":[],"closure_authorized":false,"execution_authorized":false,"github_writes_authorized":false,"handoff_projection":{"allowed_inspect_first":[],"known_facts":["coding-knowledge-sufficiency:insufficient","coding-knowledge-materiality:caller-asserted-material"],"prior_decisions":[],"stop_conditions":["coding-knowledge:no-relevant-candidate"]},"issue_number":2425,"materiality_source":"caller-asserted-material","merge_authorized":false,"mutation_admissible":false,"operation":"issue-start","reason_codes":["no-relevant-candidate"],"rejected_candidate_provenance":[{"currentness":"current","lesson_id":"LL-64","provenance":"canonical-github-ref-present","source_revision":"2026-11-12T02:09:00.000Z"},{"currentness":"current","lesson_id":"LL-65","provenance":"canonical-github-ref-present","source_revision":"2026-11-04T12:58:00.000Z"},{"currentness":"current","lesson_id":"LL-66","provenance":"canonical-github-ref-present","source_revision":"2026-11-04T12:58:00.000Z"},{"currentness":"current","lesson_id":"LL-67","provenance":"canonical-github-ref-present","source_revision":"2026-11-04T12:59:00.000Z"},{"currentness":"current","lesson_id":"LL-68","provenance":"canonical-github-ref-present","source_revision":"2026-11-04T12:59:00.000Z"}],"repository":"Blummer92/agent-os","request_comment_id":6870478787,"selected_lesson_ids":[],"selected_lessons":[],"side_effects_performed":false,"status":"insufficient","substantial_hypothesis_admissible":false}', 'user': {'login': 'github-actions[bot]', 'id': 41898282, 'type': 'Bot'}, 'created_at': '2026-11-14T02:50:29Z', 'updated_at': '2026-11-14T02:50:29Z', 'issue_url': 'https://api.github.com/repos/Blummer92/agent-os/issues/2425', 'html_url': 'https://github.com/Blummer92/agent-os/issues/2425#issuecomment-6870493264', 'performed_via_github_app': {'id': 15368, 'client_id': 'Iv1.05c79e9ad1f6bdfa', 'slug': 'github-actions', 'node_id': 'MDM6QXBwMTUzNjg=', 'owner': {'login': 'github', 'id': 9919, 'node_id': 'MDEyOk9yZ2FuaXphdGlvbjk5MTk=', 'avatar_url': 'https://avatars.githubusercontent.com/u/9919?v=4', 'gravatar_id': '', 'url': 'https://api.github.com/users/github', 'html_url': 'https://github.com/github', 'followers_url': 'https://api.github.com/users/github/followers', 'following_url': 'https://api.github.com/users/github/following{/other_user}', 'gists_url': 'https://api.github.com/users/github/gists{/gist_id}', 'starred_url': 'https://api.github.com/users/github/starred{/owner}{/repo}', 'subscriptions_url': 'https://api.github.com/users/github/subscriptions', 'organizations_url': 'https://api.github.com/users/github/orgs', 'repos_url': 'https://api.github.com/users/github/repos', 'events_url': 'https://api.github.com/users/github/events{/privacy}', 'received_events_url': 'https://api.github.com/users/github/received_events', 'type': 'Organization', 'user_view_type': 'public', 'site_admin': False}, 'name': 'GitHub Actions', 'description': 'Automate your workflow from idea to production', 'external_url': 'https://help.github.com/en/actions', 'html_url': 'https://github.com/apps/github-actions', 'created_at': '2018-07-30T09:30:17Z', 'updated_at': '2026-06-18T16:17:48Z', 'permissions': {'actions': 'write', 'administration': 'read', 'artifact_metadata': 'write', 'attestations': 'write', 'checks': 'write', 'code_quality': 'write', 'contents': 'write', 'copilot_requests': 'write', 'deployments': 'write', 'discussions': 'write', 'drives': 'write', 'issues': 'write', 'merge_queues': 'write', 'metadata': 'read', 'models': 'read', 'packages': 'write', 'pages': 'write', 'pull_requests': 'write', 'repository_hooks': 'write', 'repository_projects': 'write', 'security_events': 'write', 'statuses': 'write', 'vulnerability_alerts': 'read'}, 'events': ['branch_protection_rule', 'check_run', 'check_suite', 'create', 'delete', 'deployment', 'deployment_status', 'discussion', 'discussion_comment', 'fork', 'gollum', 'issues', 'issue_comment', 'label', 'merge_group', 'milestone', 'page_build', 'public', 'pull_request', 'pull_request_review', 'pull_request_review_comment', 'push', 'registry_package', 'release', 'repository', 'repository_dispatch', 'status', 'watch', 'workflow_dispatch', 'workflow_run']}}


def test_live_2425_insufficient_pair_blocks():
    decision = evaluate_mutation_boundary(
        repository="Blummer92/agent-os",
        issue_number=2425,
        issue_comments=[REAL_REQUEST_RECORD, REAL_RESULT_RECORD],
        allowed_actor="Blummer92",
    )
    assert decision.admitted is False
    assert decision.reason_code == BOUNDARY_BLOCKED
    assert decision.operation == "issue-start"
    assert decision.status == "insufficient"
    assert decision.request_comment_id == 6870478787
    assert "no-relevant-candidate" in decision.detail


def test_live_2425_request_without_result_is_unanswered():
    decision = evaluate_mutation_boundary(
        repository="Blummer92/agent-os",
        issue_number=2425,
        issue_comments=[REAL_REQUEST_RECORD],
        allowed_actor="Blummer92",
    )
    assert decision.reason_code == REQUEST_UNANSWERED


# --- work-attempt (head) binding ----------------------------------------------
# A push after admission invalidates it: the newest trusted request must
# strictly postdate the server-recorded push that proposed the gated head.

HEAD_SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
HEAD_BRANCH = "agent/gate-test"
PUSH_AT = "2026-11-11T09:00:00Z"


class _FakeGateReader:
    """In-memory trusted read path: comments per thread plus a push time."""

    def __init__(self, comments_by_number, push_time=PUSH_AT):
        self._comments = comments_by_number
        self._push_time = push_time

    def read_issue_comments(self, repository, issue_number):
        return self._comments[issue_number]

    def read_head_observed_at(self, repository, branch, head_sha, pr_number):
        assert (branch, head_sha, pr_number) == (HEAD_BRANCH, HEAD_SHA, ISSUE + 10)
        return self._push_time


def _run_gate_with_head(comments_by_number, push_time=PUSH_AT, pr_number=ISSUE + 10):
    reader = _FakeGateReader(comments_by_number, push_time)
    return run_gate(
        reader=reader,
        repository=REPOSITORY,
        issue_number=ISSUE,
        pr_number=pr_number,
        allowed_actor=OWNER,
        head_repository=REPOSITORY,
        head_branch=HEAD_BRANCH,
        head_sha=HEAD_SHA,
    )


def _pr_thread_pair(pr):
    """A trusted request/result pair posted on the PR thread numbered ``pr``,
    with the request naming the exact gated head in task_reference."""
    request = _request_record(
        _envelope(issue_number=pr, task_reference=f"Admit head {HEAD_SHA} for landing"),
        target="pr",
    )
    request["issue_url"] = f"https://api.github.com/repos/{REPOSITORY}/issues/{pr}"
    request["html_url"] = (
        f"https://github.com/{REPOSITORY}/pull/{pr}#issuecomment-{REQUEST_ID}"
    )
    result = _pr_comment(
        _result(issue_number=pr),
        request_comment_id=REQUEST_ID,
        issue=pr,
        html_url=f"https://github.com/{REPOSITORY}/pull/{pr}#issuecomment-{RESULT_ID}",
    )
    return [request, result]


def test_request_postdating_head_push_admits():
    pr = ISSUE + 10
    decision = _run_gate_with_head({ISSUE: [], pr: _pr_thread_pair(pr)})
    assert decision.admitted is True
    assert decision.reason_code == ADMITTED


def test_request_predating_head_push_is_stale():
    # The admitted pair exists, but the current head was pushed AFTER it:
    # admit-once-then-change-the-work must not stay green.
    pr = ISSUE + 10
    decision = _run_gate_with_head(
        {ISSUE: [], pr: _pr_thread_pair(pr)},
        push_time="2026-11-11T11:00:00Z",
    )
    assert decision.admitted is False
    assert decision.reason_code == REQUEST_STALE
    assert decision.request_comment_id == REQUEST_ID


def test_head_push_not_visible_fails_closed():
    pr = ISSUE + 10
    decision = _run_gate_with_head(
        {ISSUE: [], pr: _pr_thread_pair(pr)}, push_time=None
    )
    assert decision.admitted is False
    assert decision.reason_code == HEAD_PROPOSAL_UNPROVEN


def test_evaluate_head_binding_directly():
    head_named = _request_record(
        _envelope(task_reference=f"Admit head {HEAD_SHA}")
    )
    admitted = evaluate_mutation_boundary(
        repository=REPOSITORY,
        issue_number=ISSUE,
        issue_comments=[head_named, _comment(_result())],
        head_proposed_at=PUSH_AT,
        head_sha=HEAD_SHA,
    )
    assert admitted.admitted is True
    stale = evaluate_mutation_boundary(
        repository=REPOSITORY,
        issue_number=ISSUE,
        issue_comments=[head_named, _comment(_result())],
        head_proposed_at="2026-11-11T12:00:00Z",
        head_sha=HEAD_SHA,
    )
    assert stale.admitted is False
    assert stale.reason_code == REQUEST_STALE


def test_fresh_request_not_naming_head_does_not_admit():
    # QA v2's reproduced gap: a fresh admitted request about unrelated work
    # on the linked issue must not admit this PR's head.
    fresh_unrelated = _request_record(
        _envelope(task_reference="Investigate unrelated CKR6 lesson relevance"),
        created_at="2026-11-11T10:30:00Z",
    )
    decision = evaluate_mutation_boundary(
        repository=REPOSITORY,
        issue_number=ISSUE,
        issue_comments=[fresh_unrelated, _comment(_result())],
        head_proposed_at=PUSH_AT,
        head_sha=HEAD_SHA,
    )
    assert decision.admitted is False
    assert decision.reason_code == REQUEST_HEAD_UNBOUND


def test_request_naming_a_different_head_does_not_admit():
    other_head = "f8e7d6c5b4a39281706f5e4d3c2b1a0987654321"
    request = _request_record(
        _envelope(task_reference=f"Admit head {other_head}")
    )
    decision = evaluate_mutation_boundary(
        repository=REPOSITORY,
        issue_number=ISSUE,
        issue_comments=[request, _comment(_result())],
        head_proposed_at=PUSH_AT,
        head_sha=HEAD_SHA,
    )
    assert decision.admitted is False
    assert decision.reason_code == REQUEST_HEAD_UNBOUND


def test_head_naming_is_case_insensitive_hex():
    request = _request_record(
        _envelope(task_reference=f"admit {HEAD_SHA.upper()} please")
    )
    decision = evaluate_mutation_boundary(
        repository=REPOSITORY,
        issue_number=ISSUE,
        issue_comments=[request, _comment(_result())],
        head_proposed_at=PUSH_AT,
        head_sha=HEAD_SHA,
    )
    assert decision.admitted is True


# --- owner identity pins the numeric account id --------------------------------

def test_request_with_owner_login_but_wrong_account_id_is_untrusted():
    decision = _gate(
        [_request_record(account_id=99999999), _comment(_result())]
    )
    assert decision.admitted is False
    assert decision.reason_code == REQUEST_MISSING


# --- producer records need the same unedited proof ------------------------------

def test_result_record_missing_updated_at_is_not_evidence():
    result = _comment(_result())
    del result["updated_at"]
    decision = _gate([_request_record(), result])
    assert decision.admitted is False
    assert decision.reason_code == REQUEST_UNANSWERED


def test_result_record_with_mismatched_updated_at_is_not_evidence():
    result = _comment(_result())
    result["updated_at"] = "2026-11-11T10:05:00Z"
    decision = _gate([_request_record(), result])
    assert decision.admitted is False
    assert decision.reason_code == REQUEST_UNANSWERED


def test_unrelated_comment_without_updated_at_does_not_matter():
    noise = {
        "id": 42,
        "body": "unrelated discussion",
        "user": {"login": "someone-else", "id": 7, "type": "User"},
        "created_at": "2026-11-11T09:30:00Z",
    }
    decision = _gate([noise, _request_record(), _comment(_result())])
    assert decision.admitted is True


# --- completeness-checked paginated reads ---------------------------------------

def _noise_comment(comment_id):
    return {
        "id": comment_id,
        "body": "routine discussion",
        "user": {"login": "someone-else", "id": 7, "type": "User"},
        "created_at": "2026-11-11T08:00:00Z",
        "updated_at": "2026-11-11T08:00:00Z",
    }


def _fake_http(pages):
    """pages: list of (status, payload) per comments/events page request."""
    calls = []

    def http_get(url, headers):
        calls.append(url)
        index = len(calls) - 1
        if index >= len(pages):
            return 200, b"[]"
        status, payload = pages[index]
        return status, json.dumps(payload).encode("utf-8")

    return http_get, calls


def _token_provider():
    class _Provider:
        def get_installation_token(self):
            return "token"

    return _Provider()


def test_paginated_read_finds_newest_request_beyond_first_page():
    # QA reproduction: an old ADMITTED pair fills the first (oldest-first)
    # page of 100 comments; the true newest owner request is comment 101 on
    # the second page. A single-page read admits; the gate must not.
    old_request = _request_record(comment_id=1, created_at="2026-11-11T08:00:00Z")
    old_result = _comment(_result(), request_comment_id=1, comment_id=2,
                          created_at="2026-11-11T08:01:00Z")
    page_one = [old_request, old_result] + [_noise_comment(i) for i in range(3, 101)]
    newer_request = _request_record(comment_id=101, created_at="2026-11-11T10:00:00Z")
    http_get, calls = _fake_http([(200, page_one), (200, [newer_request])])
    reader = PaginatedIssueCommentReader(token_provider=_token_provider(), http_get=http_get)
    comments = reader.read_issue_comments(REPOSITORY, ISSUE)
    assert len(comments) == 101
    decision = evaluate_mutation_boundary(
        repository=REPOSITORY, issue_number=ISSUE, issue_comments=comments,
        allowed_actor=OWNER,
    )
    assert decision.admitted is False
    assert decision.reason_code == REQUEST_UNANSWERED
    assert decision.request_comment_id == 101


def test_paginated_read_completes_on_full_page_plus_empty_page():
    page_one = [_request_record(comment_id=1, created_at="2026-11-11T08:00:00Z"),
                _comment(_result(), request_comment_id=1, comment_id=2,
                         created_at="2026-11-11T08:01:00Z")]
    page_one += [_noise_comment(i) for i in range(3, 101)]
    http_get, _ = _fake_http([(200, page_one), (200, [])])
    reader = PaginatedIssueCommentReader(token_provider=_token_provider(), http_get=http_get)
    comments = reader.read_issue_comments(REPOSITORY, ISSUE)
    assert len(comments) == 100
    decision = evaluate_mutation_boundary(
        repository=REPOSITORY, issue_number=ISSUE, issue_comments=comments,
        allowed_actor=OWNER,
    )
    assert decision.admitted is True


def test_paginated_read_fails_closed_beyond_bounded_page_count():
    page = [_noise_comment(i) for i in range(1, 101)]
    http_get, _ = _fake_http([(200, page)] * 60)
    reader = PaginatedIssueCommentReader(token_provider=_token_provider(), http_get=http_get)
    decision = run_gate(reader=reader, repository=REPOSITORY, issue_number=ISSUE)
    assert decision.admitted is False
    assert decision.reason_code == READ_UNAVAILABLE
    assert decision.detail == "github-api-unexpected-response"


def test_paginated_read_http_failure_fails_closed():
    http_get, _ = _fake_http([(500, {})])
    reader = PaginatedIssueCommentReader(token_provider=_token_provider(), http_get=http_get)
    decision = run_gate(reader=reader, repository=REPOSITORY, issue_number=ISSUE)
    assert decision.admitted is False
    assert decision.reason_code == READ_UNAVAILABLE
    assert decision.detail == "github-api-failure"


def test_paginated_read_requires_token():
    reader = PaginatedIssueCommentReader(token_provider=None)
    decision = run_gate(reader=reader, repository=REPOSITORY, issue_number=ISSUE)
    assert decision.reason_code == READ_UNAVAILABLE
    assert decision.detail == "HOST_READ_PATH_UNAVAILABLE"


# --- provider-created exact-head workflow observation ----------------------------

def _run_record(created_at, *, head=HEAD_SHA, branch=HEAD_BRANCH,
                repo=REPOSITORY, number=ISSUE + 10):
    return {
        "id": 12345, "event": "pull_request",
        "path": ".github/workflows/agent-os-ckr6-mutation-gate.yml",
        "head_sha": head, "head_branch": branch,
        "created_at": created_at,
        "repository": {"full_name": repo},
        "pull_requests": [{"number": number}],
    }


def _run_listing(rows):
    return {"total_count": len(rows), "workflow_runs": rows}


def _run_http(pages):
    calls = []
    def get(url, headers):
        calls.append(url)
        idx = len(calls) - 1
        return (200, json.dumps(pages[idx]).encode("utf-8"))
    return get, calls


def test_head_observation_uses_exact_provider_run_not_unrelated_runs():
    relevant = _run_record(PUSH_AT)
    wrong = [
        _run_record("2026-11-11T08:00:00Z", head="0" * 40),
        _run_record("2026-11-11T08:30:00Z", branch="other-branch"),
        _run_record("2026-11-11T08:45:00Z", number=999),
        relevant,
    ]
    http_get, calls = _run_http([_run_listing(wrong)])
    reader = PaginatedIssueCommentReader(token_provider=_token_provider(), http_get=http_get)
    assert reader.read_head_observed_at(REPOSITORY, HEAD_BRANCH, HEAD_SHA, ISSUE + 10) == PUSH_AT
    assert "event=pull_request" in calls[0]
    assert f"head_sha={HEAD_SHA}" in calls[0]


def test_head_observation_chooses_earliest_matching_run():
    rows = [_run_record("2026-11-11T10:00:00Z"), _run_record(PUSH_AT)]
    http_get, _ = _run_http([_run_listing(rows)])
    reader = PaginatedIssueCommentReader(token_provider=_token_provider(), http_get=http_get)
    assert reader.read_head_observed_at(REPOSITORY, HEAD_BRANCH, HEAD_SHA, ISSUE + 10) == PUSH_AT


def test_head_observation_paginates_and_rejects_incomplete_listing():
    rows = [_run_record("2026-11-11T10:00:00Z")] * 100
    http_get, _ = _run_http([_run_listing(rows), _run_listing([_run_record(PUSH_AT)])])
    reader = PaginatedIssueCommentReader(token_provider=_token_provider(), http_get=http_get)
    assert reader.read_head_observed_at(REPOSITORY, HEAD_BRANCH, HEAD_SHA, ISSUE + 10) == PUSH_AT


def test_head_observation_without_run_fails_closed():
    http_get, _ = _run_http([_run_listing([])])
    reader = PaginatedIssueCommentReader(token_provider=_token_provider(), http_get=http_get)
    assert reader.read_head_observed_at(REPOSITORY, HEAD_BRANCH, HEAD_SHA, ISSUE + 10) is None


@pytest.mark.parametrize("record", [
    {"total_count": "0", "workflow_runs": []},
    {"total_count": 1, "workflow_runs": [None]},
    {"total_count": 1, "workflow_runs": [_run_record(PUSH_AT) | {"created_at": "bad"}]},
    {"total_count": 1, "workflow_runs": [_run_record(PUSH_AT) | {"repository": None}]},
    {"total_count": 1, "workflow_runs": [_run_record(PUSH_AT) | {"pull_requests": None}]},
])
def test_head_observation_malformed_provider_evidence_fails_closed(record):
    http_get, _ = _run_http([record])
    reader = PaginatedIssueCommentReader(token_provider=_token_provider(), http_get=http_get)
    with pytest.raises(GitHubIssueCommentReadUnavailable):
        reader.read_head_observed_at(REPOSITORY, HEAD_BRANCH, HEAD_SHA, ISSUE + 10)


# --- linked-issue extraction: hostile bodies -------------------------------------

@pytest.mark.parametrize("body", [
    "Fixes https://github.com/other-owner/other-repo/issues/99",
    "`Closes #2425` in inline code",
    "```\nCloses #2425\n```",
    "~~~~\nCloses #2425\n~~~~",
    "<!-- Closes #2425 -->",
    "> Closes #2425",
    "    Closes #2425",
    "Closes Blummer92/agent-os#2425",
])
def test_linked_issue_extraction_rejects_non_authoritative(body):
    with pytest.raises(ValueError, match=ISSUE_LINK_MISSING):
        _linked_issue_from_pr_body(body)


@pytest.mark.parametrize("body", [
    "Closes #2425 and fixes #3000",
    "Summary. Resolves #2425. Also mentions #3000 non-closing.",
    "This does not close #2425.",
    "Addresses #2425",
    "This closes #2425 mid-sentence.",
    "Closes #2425\n\nCloses #3000",
])
def test_linked_issue_extraction_ambiguous_closing_looking(body):
    with pytest.raises(ValueError, match=ISSUE_LINK_AMBIGUOUS):
        _linked_issue_from_pr_body(body)
