"""Bounded exact-file PR provenance check for the two CKR Drafts (#4092/#4093).

This is NOT CKR6 admission and grants no write, merge, readiness, or issue
ownership. It reads the canonical PR and the owner's unedited grant, proves
that the Git diff from the authorized source snapshot matches the grant's
SHA256, and fails closed. An issue-primary PR follows its old route.

The exact two-workstream restriction is intentional. This is not a generalized
authorization framework; extending the route requires separate policy review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Mapping

from .parse_pr import (
    _mask_non_authoritative_markdown,
    detect_github_effective_closing_references,
    parse_linked_issue_result,
)

REPO = "Blummer92/agent-os"
OWNER_ID = 32861845
OWNER_LOGIN = "Blummer92"
GRANT_ISSUE = 4054
GRANT_COMMENT = 7085658027
GRANT_URL = (
    "https://github.com/Blummer92/agent-os/issues/4054"
    "#issuecomment-7085658027"
)
BASE = "de6c2c5e3f60e594a167140c5ee520a19d394289"
COMMENT_API = (
    "https://api.github.com/repos/Blummer92/agent-os"
    "/issues/comments/7085658027"
)
MAIN_API = f"https://api.github.com/repos/{REPO}/branches/main"
HASH_RE = re.compile(r"^[0-9a-f]{40}$")
GRANT_LINK_RE = re.compile(
    r"https://github\.com/Blummer92/agent-os/issues/\d+"
    r"#issuecomment-\d+"
)
# CKR6 treats standalone Part of as an implementation-thread selection.
# An exact-file route must not silently ignore such a claim.
PRIMARY_LINK_RE = re.compile(
    r"^[ \t]*(?:[-*][ \t]+)?Part[ \t]+of(?:[ \t]*:[ \t]*|[ \t]+)"
    r"(?:https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/"
    r"|(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#)\d+\b",
    re.IGNORECASE | re.MULTILINE,
)
REPORT_HEADINGS = (
    "Linked issue", "Summary", "Files changed", "Tests run", "Docs updated",
    "Unresolved blockers", "Handoff recommendations", "Remaining risks",
)

@dataclass(frozen=True)
class Workstream:
    pr_number: int
    label: str
    branch: str
    paths: tuple[str, ...]
    expected_patch_sha: str

WORKSTREAMS = {
    4092: Workstream(
        4092, "PR4", "ckr/pr4-trusted-evidence",
        ("scripts/agent_os_ckr_shadow_evidence.py",
         "tests/test_agent_os_ckr_shadow_evidence.py"),
        "0b50930c066cb92c6e06618d553e2d8aff9258890ac9b19dd8161d19f1497459",
    ),
    4093: Workstream(
        4093, "PR5", "ckr/pr5-experimental-comparator",
        ("docs/ckr-pr5-staging/evaluation.py",
         "docs/ckr-pr5-staging/synthetic_demo.py",
         "docs/ckr-pr5-staging/test_evaluation.py"),
        "efce7be5a447b8a283e00740e5d8ebd1f29852dbf7d02249ccbda3e70b6670a3",
    ),
}

class VerificationFailure(ValueError):
    """Finite, content-free route failure."""


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise VerificationFailure(reason)


def _exact_str(v: object) -> str:
    return v if type(v) is str else ""


def _path_set(raw: bytes) -> set[str]:
    values = raw.decode("utf-8", "strict").split("\0")
    if values[-1:] == [""]:
        values.pop()
    _require(len(values) == len(set(values)), "duplicate-changed-path")
    return set(values)


def _section(comment: str, label: str) -> str:
    # Delimit at the very next level-three heading, including a scope or
    # exclusion heading. Never accidentally absorb later policy prose as
    # part of the authenticated workstream's path/digest section.
    matches = list(re.finditer(r"(?m)^### ([^\n]+)$", comment))
    targets = [i for i, m in enumerate(matches)
               if m.group(1).startswith(label + " ")]
    _require(len(targets) == 1, "grant-section-invalid")
    i = targets[0]
    start = matches[i].end()
    end = matches[i+1].start() if i+1 < len(matches) else len(comment)
    return comment[start:end]


def inspect_grant(comment: Mapping[str, object], work: Workstream) -> None:
    actor = comment.get("user")
    _require(isinstance(actor, Mapping), "grant-author-invalid")
    _require(actor.get("id") == OWNER_ID and type(actor.get("id")) is int,
             "grant-author-invalid")
    _require(actor.get("login") == OWNER_LOGIN, "grant-author-invalid")
    created, updated = comment.get("created_at"), comment.get("updated_at")
    _require(type(created) is str and created and updated == created,
             "grant-edited-or-undated")
    _require(comment.get("id") == GRANT_COMMENT, "grant-identity-mismatch")
    _require(comment.get("issue_url") ==
             f"https://api.github.com/repos/{REPO}/issues/{GRANT_ISSUE}",
             "grant-issue-mismatch")
    body = _exact_str(comment.get("body"))
    _require(len(body.encode("utf-8")) <= 20000, "grant-body-oversized")
    _require(f"`{REPO}`" in body and f"`{BASE}`" in body,
             "grant-repository-or-base-mismatch")
    part = _section(body, work.label)
    shas = re.findall(r"(?m)^SHA-256:[ \t]*`([0-9a-f]{64})`[ \t]*$", part)
    paths = re.findall(r"(?m)^-[ \t]*`([^`\n]+)`[ \t]*$", part)
    _require(shas == [work.expected_patch_sha], "grant-patch-digest-mismatch")
    _require(len(paths) == len(work.paths) and set(paths) == set(work.paths),
             "grant-path-scope-mismatch")
    _require("at most one non-protected branch and one matching Draft PR" in body,
             "grant-operation-mismatch")


def inspect_pr(pr: Mapping[str, object], work: Workstream, *, expected_head: str = "") -> str:
    _require(pr.get("number") == work.pr_number and type(pr.get("number")) is int,
             "pr-identity-mismatch")
    _require(pr.get("state") == "open" and pr.get("draft") is True,
             "pr-must-be-open-draft")
    base, head = pr.get("base"), pr.get("head")
    _require(isinstance(base, Mapping) and isinstance(head, Mapping),
             "pr-refs-missing")
    base_repo, head_repo = base.get("repo"), head.get("repo")
    _require(isinstance(base_repo, Mapping) and base_repo.get("full_name") == REPO,
             "pr-repository-mismatch")
    _require(base.get("ref") == "main", "pr-base-branch-mismatch")
    _require(isinstance(head_repo, Mapping) and head_repo.get("full_name") == REPO and
             head.get("ref") == work.branch, "pr-head-branch-mismatch")
    base_sha, head_sha = base.get("sha"), head.get("sha")
    _require(type(base_sha) is str and HASH_RE.fullmatch(base_sha) is not None,
             "pr-base-invalid")
    _require(type(head_sha) is str and HASH_RE.fullmatch(head_sha) is not None,
             "pr-head-invalid")
    if expected_head:
        _require(head_sha == expected_head, "pr-head-changed")
    body = _exact_str(pr.get("body"))
    links = GRANT_LINK_RE.findall(body)
    _require(links == [GRANT_URL], "grant-link-ambiguous-or-missing")
    _require("exact-file GitHub Change Request" in body,
             "exact-file-route-not-declared")
    title = pr.get("title")
    _require(type(title) is str and bool(title), "pr-title-invalid")
    _require(not detect_github_effective_closing_references(body, title),
             "pr-closing-keyword-present")
    linkage = parse_linked_issue_result(body, title)
    _require(not linkage.explicit_candidates and
             not any(candidate.keyword for candidate in linkage.bare_references) and
             not PRIMARY_LINK_RE.search(_mask_non_authoritative_markdown(body)) and
             not PRIMARY_LINK_RE.search(_mask_non_authoritative_markdown(title)),
             "pr-conflicting-primary-linkage")
    for label in REPORT_HEADINGS:
        _require(re.search(rf"(?im)^##[ \t]+{re.escape(label)}[ \t]*$", body)
                 is not None, "pr-report-headings-missing")
    _require(work.expected_patch_sha in body, "pr-cumulative-digest-missing")
    return head_sha


def inspect_main(record: object) -> str:
    _require(isinstance(record, Mapping), "main-ref-invalid")
    commit = record.get("commit")
    _require(record.get("name") == "main" and isinstance(commit, Mapping),
             "main-ref-invalid")
    sha = _exact_str(commit.get("sha"))
    _require(HASH_RE.fullmatch(sha) is not None, "main-ref-invalid")
    return sha


def inspect_git(
    work: Workstream, pr: Mapping[str, object], *, current_main: str,
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> None:
    """Verify source preimage, exact path set and cumulative net patch digest.

    The approved base is immutable. A later main is acceptable only when it
    descends from that snapshot and has not changed one of the authorized
    paths. No commit is trusted solely because its branch exists.
    """
    head_sha = pr["head"]["sha"]

    def git(*args: str, ok: bool = True) -> subprocess.CompletedProcess[bytes]:
        p = run(["git", *args], capture_output=True, timeout=30, check=False)
        if ok:
            _require(p.returncode == 0, "git-evidence-unavailable")
        return p

    _require(git("merge-base", "--is-ancestor", BASE, current_main, ok=False).returncode == 0,
             "approved-base-not-ancestor")
    _require(git("merge-base", "--is-ancestor", pr["base"]["sha"], current_main,
                 ok=False).returncode == 0, "pr-base-not-on-main")
    _require(git("merge-base", "--is-ancestor", BASE, head_sha, ok=False).returncode == 0,
             "pr-head-not-from-approved-base")
    current_change = _path_set(git("diff", "--name-only", "-z", BASE, current_main,
                                  "--", *work.paths).stdout)
    _require(not current_change, "base-scope-advanced")
    for p in work.paths:
        _require(git("cat-file", "-e", f"{BASE}:{p}", ok=False).returncode != 0,
                 "approved-base-path-not-absent")
    changed = _path_set(git("diff", "--name-only", "-z", BASE, head_sha).stdout)
    _require(changed == set(work.paths), "pr-changed-path-scope-mismatch")
    statuses = git("diff", "--name-status", "-z", BASE, head_sha).stdout
    _require(all(pair == b"A" for pair in statuses.split(b"\0")[::2] if pair),
             "pr-non-additive-change")
    # Owner PR4's frozen patch uses git --full-index; PR5's uses abbreviated
    # index. Recompute both canonical representations; only the exact granted
    # digest is accepted. Do not try normalization or partial matching.
    hashes = set()
    for flag in ((), ("--full-index",)):
        patch = git("diff", "--no-ext-diff", "--binary", *flag, BASE, head_sha).stdout
        hashes.add(hashlib.sha256(patch).hexdigest())
    _require(work.expected_patch_sha in hashes, "cumulative-patch-digest-mismatch")


def verify(
    pr_number: int, get_json: Callable[[str], Mapping[str, object]],
    *, expected_head: str = "", check_git: bool = True,
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> dict[str, object]:
    work = WORKSTREAMS.get(pr_number)
    _require(work is not None, "exact-file-pr-not-allowlisted")
    pr = get_json(f"https://api.github.com/repos/{REPO}/pulls/{pr_number}")
    _require(isinstance(pr, Mapping), "pr-read-invalid")
    head = inspect_pr(pr, work, expected_head=expected_head)
    owner = get_json(COMMENT_API)
    _require(isinstance(owner, Mapping), "grant-read-invalid")
    inspect_grant(owner, work)
    current_main = inspect_main(get_json(MAIN_API))
    if check_git:
        inspect_git(work, pr, current_main=current_main, run=run)
    # Readback is separate from the first observation: a mutable PR head or
    # edited owner comment must not reuse a previously qualified snapshot.
    reread_pr = get_json(f"https://api.github.com/repos/{REPO}/pulls/{pr_number}")
    _require(isinstance(reread_pr, Mapping), "pr-readback-unavailable")
    inspect_pr(reread_pr, work, expected_head=head)
    _require(all(reread_pr.get(field) == pr.get(field)
                 for field in ("base", "title", "body")), "pr-observation-changed")
    reread_owner = get_json(COMMENT_API)
    _require(isinstance(reread_owner, Mapping), "grant-readback-unavailable")
    inspect_grant(reread_owner, work)
    _require(reread_owner.get("body") == owner.get("body") and
             reread_owner.get("updated_at") == owner.get("updated_at"),
             "grant-observation-changed")
    _require(inspect_main(get_json(MAIN_API)) == current_main, "main-observation-changed")
    return {
        "route": "exact-file", "verified": True, "pr_number": pr_number,
        "head_sha": head, "source_base": BASE, "current_main": current_main,
        "patch_sha256": work.expected_patch_sha,
        "changed_files": len(work.paths),
        "authority": "owner-grant-verified-not-ckr6-admission",
    }


def _get_json(url: str) -> Mapping[str, object]:
    _require(url.startswith(f"https://api.github.com/repos/{REPO}/"),
             "api-url-not-allowed")
    token = os.getenv("GITHUB_TOKEN")
    _require(type(token) is str and bool(token), "token-unavailable")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "agent-os-exact-file-route",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read(512 * 1024 + 1)
            _require(len(body) <= 512 * 1024, "api-response-oversized")
            obj = json.loads(body)
    except (OSError, ValueError, UnicodeError):
        raise VerificationFailure("api-read-unavailable") from None
    _require(isinstance(obj, dict), "api-object-invalid")
    return obj


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--expected-head", default="")
    args = parser.parse_args(argv)
    if args.repository != REPO:
        print('{"route":"blocked","reason_code":"repository-not-allowed"}')
        return 1
    if args.pr_number not in WORKSTREAMS:
        # All other PRs must follow the normal issue-primary route unchanged.
        print('{"route":"issue-primary","verified":false}')
        return 3
    try:
        report = verify(args.pr_number, _get_json, expected_head=args.expected_head)
    except (VerificationFailure, subprocess.TimeoutExpired) as exc:
        code = str(exc) if isinstance(exc, VerificationFailure) else "git-evidence-timeout"
        print(json.dumps({"route":"blocked", "verified": False,
                          "reason_code": code}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
