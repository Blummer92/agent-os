"""Fail-closed QA for the bounded #4092/#4093 exact-file route."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess

import pytest

from scripts.agent_os_issue_acceptance import exact_file_draft_route as route


BASE = "a" * 40
HEAD = "b" * 40


def owner_record(work: route.Workstream):
    body = (
        "## Owner authorization for `Blummer92/agent-os`\n"
        f"The base is `{route.BASE}` on `main`.\n"
        "Authorize at most one non-protected branch and one matching Draft PR per workstream.\n"
    )
    for w in route.WORKSTREAMS.values():
        body += f"\n### {w.label} — exact-file scope\n"
        body += f"SHA-256: `{w.expected_patch_sha}`\n"
        body += "\n".join(f"- `{p}`" for p in w.paths) + "\n"
    return {
        "id": route.GRANT_COMMENT,
        "user": {"id": route.OWNER_ID, "login": route.OWNER_LOGIN},
        "issue_url": f"https://api.github.com/repos/{route.REPO}/issues/{route.GRANT_ISSUE}",
        "created_at": "2026-11-22T21:00:00Z",
        "updated_at": "2026-11-22T21:00:00Z",
        "body": body,
    }


def pull_record(work: route.Workstream):
    headings = "\n".join(f"## {s}\nEvidence" for s in route.REPORT_HEADINGS)
    return {
        "number": work.pr_number, "state": "open", "draft": True,
        "base": {"sha": BASE, "repo": {"full_name": route.REPO}},
        "head": {"sha": HEAD, "ref": work.branch,
                 "repo": {"full_name": route.REPO}},
        "body": (
            "This is an exact-file GitHub Change Request.\n"
            f"Owner grant: {route.GRANT_URL}\n"
            f"Authorized cumulative patch SHA-256: `{work.expected_patch_sha}`.\n"
            + headings
        ),
    }


@pytest.mark.parametrize("n", [4092, 4093])
def test_current_owner_grant_shape_is_accepted(n):
    work = route.WORKSTREAMS[n]
    route.inspect_grant(owner_record(work), work)
    assert route.inspect_pr(pull_record(work), work, expected_head=HEAD) == HEAD


@pytest.mark.parametrize("field,bad", [
    ("created_at", ""), ("updated_at", "2026-11-22T21:00:01Z"),
    ("id", 1), ("issue_url", "https://api.github.com/repos/other/issues/4054"),
])
def test_rejects_mutated_provenance(field, bad):
    w = route.WORKSTREAMS[4092]
    c = owner_record(w); c[field] = bad
    with pytest.raises(route.VerificationFailure):
        route.inspect_grant(c, w)


def test_rejects_impersonated_owner_and_bad_patch():
    w = route.WORKSTREAMS[4092]
    c = owner_record(w); c["user"]["id"] = 1
    with pytest.raises(route.VerificationFailure, match="grant-author-invalid"):
        route.inspect_grant(c, w)
    c = owner_record(w); c["body"] = c["body"].replace(w.expected_patch_sha, "f"*64)
    with pytest.raises(route.VerificationFailure, match="grant-patch-digest-mismatch"):
        route.inspect_grant(c, w)


def test_rejects_grant_with_extra_path():
    w = route.WORKSTREAMS[4092]
    c = owner_record(w)
    c["body"] = c["body"].replace("### PR5", "- `.github/workflows/malicious.yml`\n### PR5")
    with pytest.raises(route.VerificationFailure, match="grant-path-scope-mismatch"):
        route.inspect_grant(c, w)


@pytest.mark.parametrize("mutator,code", [
    (lambda p: p.update(draft=False), "pr-must-be-open-draft"),
    (lambda p: p["head"].update(ref="unapproved"), "pr-head-branch-mismatch"),
    (lambda p: p.update(body=p["body"].replace(route.GRANT_URL, "")), "grant-link-ambiguous-or-missing"),
    (lambda p: p.update(body=p["body"] + "\nCloses #4054\n"), "pr-closing-keyword-present"),
    (lambda p: p.update(body=p["body"].replace("## Tests run", "## Other")), "pr-report-headings-missing"),
])
def test_rejects_unsafe_pr_changes(mutator, code):
    w = route.WORKSTREAMS[4093]
    p = pull_record(w); mutator(p)
    with pytest.raises(route.VerificationFailure, match=code):
        route.inspect_pr(p, w)


def test_rejects_changed_expected_head():
    p = pull_record(route.WORKSTREAMS[4092])
    with pytest.raises(route.VerificationFailure, match="pr-head-changed"):
        route.inspect_pr(p, route.WORKSTREAMS[4092], expected_head="c"*40)


def make_runner(work, *, changed=None, patch=b"expected patch", base_overlap=False):
    allowed = sorted(work.paths)
    changed = allowed if changed is None else changed
    def run(argv, *, capture_output, timeout, check):
        assert argv[0] == "git" and capture_output and timeout == 30 and not check
        if argv[1] == "merge-base": return subprocess.CompletedProcess(argv, 0, b"")
        if argv[1] == "cat-file": return subprocess.CompletedProcess(argv, 1, b"")
        if argv[1:3] == ["diff", "--name-only"]:
            if "--" in argv:
                return subprocess.CompletedProcess(argv, 0, b"x\0" if base_overlap else b"")
            return subprocess.CompletedProcess(argv, 0, b"".join(v.encode()+b"\0" for v in changed))
        if argv[1:3] == ["diff", "--name-status"]:
            return subprocess.CompletedProcess(argv, 0, b"".join(b"A\0"+v.encode()+b"\0" for v in changed))
        if argv[1] == "diff": return subprocess.CompletedProcess(argv, 0, patch)
        raise AssertionError(argv)
    return run


def test_git_exact_patch_and_scope_pass():
    raw = b"exact canonical patch\n"
    w = dataclasses.replace(route.WORKSTREAMS[4092], expected_patch_sha=hashlib.sha256(raw).hexdigest())
    route.inspect_git(w, pull_record(w), run=make_runner(w, patch=raw))


def test_git_rejects_digest_mismatch_extra_paths_and_base_overlap():
    w = route.WORKSTREAMS[4092]
    for runner,reason in [
        (make_runner(w), "cumulative-patch-digest-mismatch"),
        (make_runner(w, changed=list(w.paths)+[".github/workflows/new.yml"]), "pr-changed-path-scope-mismatch"),
        (make_runner(w, base_overlap=True), "base-scope-advanced"),
    ]:
        with pytest.raises(route.VerificationFailure, match=reason):
            route.inspect_git(w, pull_record(w), run=runner)


def test_live_pr_and_grant_are_used_not_untrusted_pr_body_as_grant():
    w = route.WORKSTREAMS[4092]
    p, o = pull_record(w), owner_record(w)
    hits = []
    def get(url):
        hits.append(url)
        return o if url == route.COMMENT_API else p
    result = route.verify(4092, get, expected_head=HEAD, check_git=False)
    assert result["verified"] is True
    assert result["authority"] == "owner-grant-verified-not-ckr6-admission"
    assert hits == [f"https://api.github.com/repos/{route.REPO}/pulls/4092", route.COMMENT_API]*2


def test_unlisted_pr_fails_closed():
    with pytest.raises(route.VerificationFailure, match="exact-file-pr-not-allowlisted"):
        route.verify(4000, lambda _: {}, check_git=False)


def test_no_token_leak_and_closed_verdict(capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "SUPERSECRET")
    monkeypatch.setattr(route, "_get_json", lambda url: {})
    assert route.main(["--repository", route.REPO, "--pr-number", "4092"]) == 1
    captured = capsys.readouterr().out
    assert "SUPERSECRET" not in captured
    assert json.loads(captured)["verified"] is False


def test_other_pr_uses_existing_issue_primary_path(capsys):
    assert route.main(["--repository", route.REPO, "--pr-number", "4100"]) == 3
    assert json.loads(capsys.readouterr().out)["route"] == "issue-primary"
