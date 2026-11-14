"""Request an exact-head PR gate rerun after a relevant trusted CKR6 comment.

This lane never manufactures an initial workflow run, a check, or admission.
Learning-only comments and unbound issue-level preflights are not PR mutations.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from .ckr6_github_bridge import envelope_from_event, parse_ckr6_result_comment
from .ckr6_mutation_gate import _linked_issue_from_pr_body

REPO = "Blummer92/agent-os"
OWNER_ID = 32861845
BOT_ID = 41898282
WORKFLOW = "agent-os-ckr6-mutation-gate.yml"
RESULT_MARKER = "<!-- agent-os-ckr6-result:v1 -->"
MUTATION_OPERATIONS = frozenset({"issue-start", "failed-repair"})
PR_REFERENCE = re.compile(
    r"(?<!\w)PR\s*#([1-9][0-9]{0,6})(?!\d)"
    r"|https://github\.com/Blummer92/agent-os/pull/([1-9][0-9]{0,6})(?!\d)",
    re.IGNORECASE,
)
SHA_REFERENCE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{40}(?![0-9a-fA-F])")
ISSUE_URL = "https://api.github.com/repos/" + REPO + "/issues/"


class RevalidationBlocked(ValueError):
    """Finite reason only: never include untrusted GitHub response text."""

    ALLOWED = frozenset({
        "request-provenance-unverified", "request-envelope-invalid",
        "target-pr-ambiguous", "target-head-ambiguous", "target-head-mismatch",
        "pr-linkage-unverified", "pr-head-unavailable", "pr-state-unavailable",
        "gate-run-missing", "gate-run-association-unverified",
        "gate-run-population-incomplete", "gate-run-invalid",
        "rerun-permission-denied", "rerun-request-failed", "github-read-failed",
    })

    def __init__(self, code: str):
        super().__init__(code if code in self.ALLOWED else "github-read-failed")


def triggered(event):
    if not isinstance(event, dict):
        return False
    repo, issue, comment = event.get("repository"), event.get("issue"), event.get("comment")
    if not all(isinstance(x, dict) for x in (repo, issue, comment)):
        return False
    if repo.get("full_name") != REPO or type(issue.get("number")) is not int or issue["number"] <= 0:
        return False
    if issue.get("pull_request") is not None and not isinstance(issue["pull_request"], dict):
        return False
    user, body = comment.get("user"), comment.get("body")
    if not isinstance(user, dict) or not isinstance(body, str):
        return False
    return (
        (user.get("id") == OWNER_ID and body.startswith("/agent-os ckr6 "))
        or (user.get("id") == BOT_ID and body.startswith(RESULT_MARKER + "\n"))
    )


def api(method, endpoint, token):
    req = urllib.request.Request(
        "https://api.github.com/repos/" + REPO + endpoint,
        data=b"{}" if method == "POST" else None,
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            if method == "POST":
                if response.status != 201:
                    raise RevalidationBlocked("rerun-request-failed")
                return None
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if method == "POST":
            raise RevalidationBlocked(
                "rerun-permission-denied" if exc.code in (401, 403) else "rerun-request-failed"
            ) from None
        raise RevalidationBlocked("github-read-failed") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise RevalidationBlocked("rerun-request-failed" if method == "POST" else "github-read-failed") from None


def _unedited_comment(comment):
    return (
        isinstance(comment, dict)
        and isinstance(comment.get("id"), int) and not isinstance(comment["id"], bool)
        and isinstance(comment.get("created_at"), str)
        and comment["created_at"] == comment.get("updated_at")
    )


def _parse_owner_request(event, comment):
    if not _unedited_comment(comment):
        raise RevalidationBlocked("request-provenance-unverified")
    user = comment.get("user", {})
    if user.get("id") != OWNER_ID or user.get("login") != "Blummer92":
        raise RevalidationBlocked("request-provenance-unverified")
    try:
        return envelope_from_event(
            {**event, "comment": comment}, expected_repository=REPO, allowed_actor="Blummer92"
        )
    except (ValueError, TypeError):
        raise RevalidationBlocked("request-envelope-invalid") from None


def _request_for_event(event, token):
    """Return a validated request envelope or None for learning-only results.

    Bot payloads do not decide targets. Read back the correlated owner's request
    through the authenticated GitHub API before routing any rerun.
    """
    comment = event["comment"]
    if not _unedited_comment(comment):
        raise RevalidationBlocked("request-provenance-unverified")
    if comment["user"]["id"] == OWNER_ID:
        return _parse_owner_request(event, comment)
    try:
        result = parse_ckr6_result_comment(comment["body"])
    except (ValueError, TypeError):
        raise RevalidationBlocked("request-envelope-invalid") from None
    if result.get("operation") not in MUTATION_OPERATIONS:
        return None
    if result.get("repository") != REPO or result.get("issue_number") != event["issue"]["number"]:
        raise RevalidationBlocked("request-provenance-unverified")
    request_id = result.get("request_comment_id")
    if type(request_id) is not int or request_id <= 0:
        raise RevalidationBlocked("request-provenance-unverified")
    request = api("GET", f"/issues/comments/{request_id}", token)
    if not isinstance(request, dict) or request.get("id") != request_id:
        raise RevalidationBlocked("request-provenance-unverified")
    number = event["issue"]["number"]
    kind = "pull" if isinstance(event["issue"].get("pull_request"), dict) else "issues"
    expected_html = f"https://github.com/{REPO}/{kind}/{number}#issuecomment-{request_id}"
    if request.get("issue_url") != ISSUE_URL + str(number) or request.get("html_url") != expected_html:
        raise RevalidationBlocked("request-provenance-unverified")
    envelope = _parse_owner_request(event, request)
    if envelope.operation != result["operation"]:
        raise RevalidationBlocked("request-provenance-unverified")
    return envelope


def _target(event, token):
    """One exact PR + exact SHA; never census linked issue PRs."""
    envelope = _request_for_event(event, token)
    if envelope is None or envelope.operation not in MUTATION_OPERATIONS:
        return None, "learning-operation"
    reference = envelope.task_reference
    shas = {match.group(0).lower() for match in SHA_REFERENCE.finditer(reference)}
    if not shas:
        return None, "no-head-bound-request"
    if len(shas) != 1:
        raise RevalidationBlocked("target-head-ambiguous")
    sha = next(iter(shas))
    number = event["issue"]["number"]
    if isinstance(event["issue"].get("pull_request"), dict):
        return (number, sha), None
    numbers = {int(match.group(1) or match.group(2)) for match in PR_REFERENCE.finditer(reference)}
    if not numbers:
        return None, "no-applicable-pr"
    if len(numbers) != 1:
        raise RevalidationBlocked("target-pr-ambiguous")
    return (next(iter(numbers)), sha), None


def current_targets(event, token):
    """Compatibility surface; one explicit current-head target or none."""
    if not triggered(event):
        return []
    target, _ = _target(event, token)
    return [target[0]] if target is not None else []


def select_run(pr, listing):
    head = pr.get("head")
    if pr.get("state") != "open" or not isinstance(head, dict):
        return None
    repo = head.get("repo")
    if not isinstance(repo, dict) or repo.get("full_name") != REPO:
        return None
    sha, branch = head.get("sha"), head.get("ref")
    if not isinstance(sha, str) or SHA_REFERENCE.fullmatch(sha) is None:
        raise RevalidationBlocked("pr-head-unavailable")
    if not isinstance(branch, str) or not branch:
        raise RevalidationBlocked("pr-head-unavailable")
    if not isinstance(listing, dict) or not isinstance(listing.get("workflow_runs"), list):
        raise RevalidationBlocked("gate-run-invalid")
    rows = listing["workflow_runs"]
    count = listing.get("total_count")
    if len(rows) >= 100 or (type(count) is int and count != len(rows)):
        raise RevalidationBlocked("gate-run-population-incomplete")
    matches = []
    association_unverified = False
    for run in rows:
        if not isinstance(run, dict):
            raise RevalidationBlocked("gate-run-invalid")
        if run.get("head_sha") != sha or run.get("head_branch") != branch or run.get("event") != "pull_request":
            continue
        if run.get("path") != ".github/workflows/" + WORKFLOW:
            continue
        associations = run.get("pull_requests")
        if not isinstance(associations, list):
            raise RevalidationBlocked("gate-run-association-unverified")
        if not any(isinstance(x, dict) and x.get("number") == pr.get("number") for x in associations):
            association_unverified = True
            continue
        rid = run.get("id")
        if type(rid) is not int or rid <= 0 or not isinstance(run.get("created_at"), str):
            raise RevalidationBlocked("gate-run-invalid")
        matches.append((run["created_at"], rid))
    if matches:
        return max(matches)[1]
    if association_unverified:
        raise RevalidationBlocked("gate-run-association-unverified")
    return None


def evaluate(event, token):
    """Non-admission disposition for reporting; only an exact match may rerun."""
    if not triggered(event):
        return {"disposition": "not-applicable", "reason_code": "event-not-eligible", "run_ids": []}
    target, reason = _target(event, token)
    if target is None:
        return {"disposition": "not-applicable", "reason_code": reason, "run_ids": []}
    number, sha = target
    pr = api("GET", f"/pulls/{number}", token)
    if not isinstance(pr, dict) or pr.get("number") != number:
        raise RevalidationBlocked("pr-state-unavailable")
    if pr.get("state") == "closed":
        return {"disposition": "not-applicable", "reason_code": "pr-closed", "run_ids": []}
    if pr.get("state") != "open":
        raise RevalidationBlocked("pr-state-unavailable")
    head = pr.get("head")
    if (not isinstance(head, dict) or not isinstance(head.get("repo"), dict)
            or head["repo"].get("full_name") != REPO):
        raise RevalidationBlocked("pr-head-unavailable")
    if head.get("sha") != sha:
        raise RevalidationBlocked("target-head-mismatch")
    if not isinstance(event["issue"].get("pull_request"), dict):
        try:
            linked = _linked_issue_from_pr_body(pr.get("body"))
        except (ValueError, TypeError):
            raise RevalidationBlocked("pr-linkage-unverified") from None
        if linked != event["issue"]["number"]:
            raise RevalidationBlocked("pr-linkage-unverified")
    query = urllib.parse.urlencode({"head_sha": sha, "event": "pull_request", "per_page": 100})
    runs = api("GET", f"/actions/workflows/{WORKFLOW}/runs?{query}", token)
    run_id = select_run(pr, runs)
    if run_id is None:
        raise RevalidationBlocked("gate-run-missing")
    api("POST", f"/actions/runs/{run_id}/rerun", token)
    return {"disposition": "rerun-requested", "reason_code": "exact-head-run-verified", "run_ids": [run_id]}


def revalidate(event, token):
    """Compatibility wrapper used by existing tests/consumers."""
    return evaluate(event, token)["run_ids"]


def main():
    token = os.environ.get("GITHUB_TOKEN", "")
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not token or not path:
        print(json.dumps({"disposition": "blocked", "reason_code": "github-read-failed", "rerun_count": 0}))
        return 1
    try:
        with open(path, encoding="utf-8") as f:
            event = json.load(f)
        result = evaluate(event, token)
    except RevalidationBlocked as exc:
        print(json.dumps({"disposition": "blocked", "reason_code": str(exc), "rerun_count": 0}))
        return 1
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"disposition": "blocked", "reason_code": "github-read-failed", "rerun_count": 0}))
        return 1
    print(json.dumps({"disposition": result["disposition"],
                      "reason_code": result["reason_code"],
                      "rerun_count": len(result["run_ids"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
