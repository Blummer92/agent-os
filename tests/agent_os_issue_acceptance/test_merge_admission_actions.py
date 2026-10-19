"""Read-only merge-admission bridge: exact selectors and canonical source, no merge."""
from __future__ import annotations

import hashlib

from scripts.agent_os_issue_acceptance.merge_admission_actions import (
    evaluate_merge_admission_transport,
)

REPO = "Blummer92/agent-os"
HEAD = "a" * 40
BODY = "example body"
BODY_SHA = hashlib.sha256(BODY.encode()).hexdigest()


class Ref:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class EmptyComments:
    def __iter__(self):
        return iter(())


class FakeRepo:
    owner = Ref(login="Blummer92", type="User")

    def __init__(self, *, head=HEAD, body=BODY, draft=False, base="main", mergeable=True):
        self.pr = Ref(
            number=3659,
            state="open",
            draft=draft,
            merged=False,
            head=Ref(sha=head),
            base=Ref(ref=base, sha="b" * 40),
            body=body,
            title="test PR",
            mergeable=mergeable,
        )

    def get_pull(self, number):
        assert number == 3659
        return self.pr

    def get_issue(self, number):
        assert number == 3659
        return Ref(get_comments=lambda: EmptyComments())


class FakeClient:
    def __init__(self, repo):
        self.repo = repo

    def get_repo(self, name):
        assert name == REPO
        return self.repo


def trigger():
    return {
        "status": "accepted",
        "reason": "accepted-merge-admission-envelope",
        "repository": REPO,
        "issue_number": 3463,
        "comment_id": 91111,
        "logical_trigger_id_or_none": "issue-comment-trigger:" + "c" * 64,
        "merge_admission_pr_number_or_none": 3659,
        "merge_admission_head_sha_or_none": HEAD,
        "merge_admission_body_sha256_or_none": BODY_SHA,
        "merge_admission_method_or_none": "merge",
    }


def check(t, repo=None):
    return evaluate_merge_admission_transport(t, repository=REPO, github_client=FakeClient(repo or FakeRepo()))


def test_no_authorization_source_refuses_even_clean_pr():
    receipt = check(trigger())
    assert receipt["status"] == "blocked"
    assert receipt["merge_authorized"] is False
    assert receipt["canonical_applicability_evaluated"] is False
    assert "authorization.absent" in receipt["reason_codes"]
    assert receipt["side_effects_performed"] is False


def test_stale_head_and_body_refused_before_source_lookup():
    assert "stale-head" in check(trigger(), FakeRepo(head="f" * 40))["reason_codes"]
    assert "stale-body" in check(trigger(), FakeRepo(body="modified"))["reason_codes"]


def test_not_ready_nonmergeable_or_wrong_base_refused():
    assert "pr-not-ready" in check(trigger(), FakeRepo(draft=True))["reason_codes"]
    assert "pr-mergeability-not-clean" in check(trigger(), FakeRepo(mergeable=False))["reason_codes"]
    assert "base-not-main" in check(trigger(), FakeRepo(base="other"))["reason_codes"]


def test_malformed_forged_transport_refused():
    invalids = [
        None,
        {},
        {**trigger(), "reason": "accepted-ready-admission-envelope"},
        {**trigger(), "repository": "other/repo"},
        {**trigger(), "merge_admission_head_sha_or_none": "not a sha"},
        {**trigger(), "merge_admission_body_sha256_or_none": "not a hash"},
        {**trigger(), "merge_admission_method_or_none": "force"},
        {**trigger(), "merge_admission_pr_number_or_none": True},
        {**trigger(), "logical_trigger_id_or_none": None},
    ]
    for value in invalids:
        receipt = check(value)
        assert receipt["status"] == "blocked"
        assert receipt["merge_authorized"] is False
        assert receipt["reason_codes"]


def test_provider_outage_is_never_merge_authority():
    class Offline:
        def get_repo(self, _):
            raise RuntimeError("unavailable")
    result = evaluate_merge_admission_transport(trigger(), repository=REPO, github_client=Offline())
    assert result["merge_authorized"] is False
    assert result["reason_codes"] == ["canonical-github-evidence-unavailable"]
