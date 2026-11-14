"""Rerun the existing CKR6 PR gate for current heads after trusted comments.

Default-branch-only issue_comment workflow. This does not grant admission or
publish a status: the original PR gate independently verifies comment evidence.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

from .ckr6_mutation_gate import _linked_issue_from_pr_body

REPO = "Blummer92/agent-os"
OWNER_ID = 32861845
BOT_ID = 41898282
WORKFLOW = "agent-os-ckr6-mutation-gate.yml"


def triggered(event):
    if not isinstance(event, dict):
        return False
    repo, issue, comment = event.get("repository"), event.get("issue"), event.get("comment")
    if not all(isinstance(x, dict) for x in (repo, issue, comment)):
        return False
    if repo.get("full_name") != REPO or type(issue.get("number")) is not int:
        return False
    user, body = comment.get("user"), comment.get("body")
    if not isinstance(user, dict) or not isinstance(body, str):
        return False
    return (
        (user.get("id") == OWNER_ID and body.startswith("/agent-os ckr6 "))
        or (user.get("id") == BOT_ID and body.startswith("<!-- agent-os-ckr6-result:v1 -->"))
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
    with urllib.request.urlopen(req, timeout=30) as response:
        if method == "POST":
            if response.status != 201:
                raise ValueError("rerun declined")
            return None
        return json.load(response)


def current_targets(event, token):
    number = event["issue"]["number"]
    if event["issue"].get("pull_request") is not None:
        numbers = [number]
    else:
        numbers = []
        for page in range(1, 6):
            rows = api("GET", f"/pulls?state=open&per_page=100&page={page}", token)
            if not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows):
                raise ValueError("PR population invalid")
            for row in rows:
                try:
                    linked = _linked_issue_from_pr_body(row.get("body"))
                except ValueError:
                    continue
                if linked == number:
                    numbers.append(row.get("number"))
            if len(rows) < 100:
                break
        else:
            raise ValueError("PR population truncated")
    if len(numbers) > 10 or any(type(n) is not int or n <= 0 for n in numbers):
        raise ValueError("PR targets invalid")
    return sorted(set(numbers))


def select_run(pr, listing):
    head = pr.get("head")
    if pr.get("state") != "open" or not isinstance(head, dict):
        return None
    repo = head.get("repo")
    if not isinstance(repo, dict) or repo.get("full_name") != REPO:
        return None
    sha, branch = head.get("sha"), head.get("ref")
    if not isinstance(sha, str) or len(sha) != 40 or not all(c in "0123456789abcdefABCDEF" for c in sha):
        raise ValueError("head SHA invalid")
    if not isinstance(branch, str) or not branch:
        raise ValueError("head branch invalid")
    if not isinstance(listing, dict) or not isinstance(listing.get("workflow_runs"), list):
        raise ValueError("run list invalid")
    # A full page does not prove that an older/latest matching run wasn't
    # omitted. No rerun is safe without complete source-run evidence.
    if len(listing["workflow_runs"]) >= 100:
        raise ValueError("workflow run population incomplete")
    matches = []
    for run in listing["workflow_runs"]:
        if not isinstance(run, dict):
            raise ValueError("run record invalid")
        if run.get("head_sha") != sha or run.get("head_branch") != branch or run.get("event") != "pull_request":
            continue
        if not str(run.get("path", "")).endswith("/" + WORKFLOW):
            continue
        associations = run.get("pull_requests")
        if not isinstance(associations, list):
            raise ValueError("run association unavailable")
        if not any(isinstance(x, dict) and x.get("number") == pr.get("number") for x in associations):
            continue
        rid = run.get("id")
        if type(rid) is not int or rid <= 0:
            raise ValueError("run ID invalid")
        matches.append((str(run.get("created_at", "")), rid))
    return max(matches)[1] if matches else None


def revalidate(event, token):
    if not triggered(event):
        return []
    run_ids = []
    for number in current_targets(event, token):
        pr = api("GET", f"/pulls/{number}", token)
        if not isinstance(pr, dict) or pr.get("number") != number:
            raise ValueError("current PR read invalid")
        head = pr.get("head")
        if not isinstance(head, dict) or not isinstance(head.get("sha"), str):
            raise ValueError("current head unavailable")
        query = urllib.parse.urlencode({
            "head_sha": head["sha"], "event": "pull_request", "per_page": 100,
        })
        runs = api("GET", f"/actions/workflows/{WORKFLOW}/runs?{query}", token)
        run_id = select_run(pr, runs)
        if run_id is None:
            raise ValueError("no verifiable current-head CKR6 gate run")
        run_ids.append(run_id)
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("duplicate rerun target")
    for rid in run_ids:
        api("POST", f"/actions/runs/{rid}/rerun", token)
    return run_ids


def main():
    token = os.environ.get("GITHUB_TOKEN", "")
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not token or not path:
        return 1
    try:
        with open(path, encoding="utf-8") as f:
            event = json.load(f)
        runs = revalidate(event, token)
    except (OSError, ValueError, TypeError):
        print("CKR6 rerun unavailable; no admission granted", file=sys.stderr)
        return 1
    print(json.dumps({"rerun_count": len(runs)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
