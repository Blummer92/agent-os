"""Integration tests for the owner-operated schema-1.2 producer console.

These tests run the real canonical domain objects (candidate construction,
trusted-source reacquisition, applicability evaluation, decision transition)
against PyGithub-shaped fake clients. No network, no GitHub writes, no token:
the fake client mirrors the PyGithub 2.10 attributes the console touches
(verified against the installed PyGithub source), and every guard the
console claims is exercised through ``prepare`` / ``decide`` / ``verify``.

Scope note: this proves the producer CLI against canonical contracts. It
does not prove human origin — only a first-party owner browser post, read
back through the trusted source, can do that — and a verified record is
never a runtime merge approval (see docs/3463-merge-admission.md S2).
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_os_issue_acceptance import (  # noqa: E402
    merge_admission_actions as admission,
    merge_authorization_owner_console as console,
)
from scripts.agent_os_issue_acceptance.merge_applicability import (  # noqa: E402
    evaluate_merge_dispatch_applicability,
)
from scripts.agent_os_issue_acceptance.merge_authorization import (  # noqa: E402
    MergeAuthorizationState,
    changed_scope_fingerprint,
    record_merge_authorization_decision,
)
from scripts.agent_os_issue_acceptance.merge_authorization_source import (  # noqa: E402
    serialize_merge_authorization_comment,
)

REPO = "Blummer92/agent-os"
HEAD = "11" * 20
BASE = "22" * 20
BLOB = "33" * 20
AGGREGATE = "agent-os/authoritative-aggregate"
FUTURE = "2099-01-01T00:00:00Z"
WHEN1 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
WHEN2 = datetime(2026, 11, 1, 12, 5, tzinfo=timezone.utc)


# ---------------------------------------------------------------- fakes
class FakeApp:
    def __init__(self, slug, app_id):
        self.slug = slug
        self.id = app_id


class FakeRun:
    def __init__(self, name, run_id, conclusion, app):
        self.name = name
        self.id = run_id
        self.conclusion = conclusion
        self.app = app


class FakeStatus:
    def __init__(self, context, status_id, state, creator_login, creator_id):
        self.context = context
        self.id = status_id
        self.state = state
        self.creator = SimpleNamespace(login=creator_login, id=creator_id)


class FakeCommit:
    def __init__(self, runs=(), statuses=()):
        self._runs = list(runs)
        self._statuses = list(statuses)

    def get_check_runs(self):
        return list(self._runs)

    def get_statuses(self):
        return list(self._statuses)


class FakeFile:
    def __init__(self, filename, sha):
        self.filename = filename
        self.sha = sha


class FakeReview:
    def __init__(self, state, commit_id):
        self.state = state
        self.commit_id = commit_id


class FakePart:
    def __init__(self, ref, sha):
        self.ref = ref
        self.sha = sha


class FakeComment:
    def __init__(self, comment_id, author, created, body, app_slug=None):
        self.id = comment_id
        self.user = SimpleNamespace(login=author)
        self.created_at = created
        self.body = body
        self.performed_via_github_app = (
            None if app_slug is None else SimpleNamespace(slug=app_slug)
        )


class FakeIssue:
    def __init__(self, comments=(), sequence=None):
        self._comments = list(comments)
        self._sequence = sequence
        self._calls = 0

    def get_comments(self):
        self._calls += 1
        if self._sequence is not None:
            index = min(self._calls - 1, len(self._sequence) - 1)
            return list(self._sequence[index])
        return list(self._comments)

    def add(self, comment):
        self._comments.append(comment)


class FakePR:
    def __init__(self, *, head=HEAD, base=BASE, title="Test PR",
                 body="Part of #2410", files=None, reviews=(),
                 draft=False, merged=False, mergeable=True):
        self.head = FakePart("agent/test", head)
        self.base = FakePart("main", base)
        self.title = title
        self.body = body
        self._files = list(files if files is not None
                           else [FakeFile("tests/test_a.py", BLOB)])
        self._reviews = list(reviews)
        self.number = 3752
        self.state = "closed" if merged else "open"
        self.merged = merged
        self.draft = draft
        self.mergeable = mergeable

    def get_files(self):
        return list(self._files)

    def get_reviews(self):
        return list(self._reviews)

    def get_labels(self):
        return []


class FakeRequester:
    """GraphQL review-thread pages: list of (nodes, has_next) per cursor."""

    def __init__(self, pages=(((), False),)):
        self._pages = pages

    def graphql_query(self, query, variables):
        cursor = variables.get("cursor")
        index = 0 if cursor is None else 1
        if index >= len(self._pages):
            index = len(self._pages) - 1
        nodes, has_next = self._pages[index]
        return {}, {
            "data": {"repository": {"pullRequest": {"reviewThreads": {
                "nodes": [{"isResolved": resolved} for resolved in nodes],
                "pageInfo": {"hasNextPage": has_next,
                             "endCursor": "c1" if has_next else None},
            }}}},
        }


class FakeRepo:
    def __init__(self, pr, commit, issue, *, owner_login="Blummer92",
                 owner_type="User", default_branch="main"):
        self._pr = pr
        self._commit = commit
        self._issue = issue
        self.owner = SimpleNamespace(login=owner_login, type=owner_type)
        self.default_branch = default_branch
        self._pull_calls = 0
        self.on_pull = None

    def get_pull(self, number):
        self._pull_calls += 1
        if self.on_pull is not None:
            self.on_pull(self._pull_calls, self._pr)
        # One independent snapshot per read, copying every stored field:
        # no hand-kept field list, so base.ref or state drift is visible.
        snapshot = copy.copy(self._pr)
        snapshot.head, snapshot.base = copy.copy(self._pr.head), copy.copy(self._pr.base)
        return snapshot

    def get_commit(self, sha):
        assert sha == self._pr.head.sha
        return self._commit

    def get_issue(self, number):
        return self._issue


class FakeClient:
    def __init__(self, repo, requester=None):
        self._repo = repo
        self.requester = requester or FakeRequester()

    def get_repo(self, name):
        assert name == REPO
        return self._repo


def green_commit():
    return FakeCommit(
        runs=[FakeRun(AGGREGATE, 10, "success",
                      FakeApp("github-actions", 15368))],
        statuses=[FakeStatus(AGGREGATE, 20, "success",
                             "github-actions[bot]", 41898282)],
    )


def make_client(*, pr=None, commit=None, comments=(), threads=(((), False),),
                sequence=None):
    pr = pr or FakePR()
    commit = commit if commit is not None else green_commit()
    issue = FakeIssue(comments, sequence=sequence)
    return FakeClient(FakeRepo(pr, commit, issue), FakeRequester(threads))


def policy(**overrides):
    data = {
        "repository": REPO, "pr_number": 3752, "merge_method": "squash",
        "allowed_files": ["tests/test_a.py"],
        "forbidden_paths": [".github/workflows/**"],
        "required_tests": ["tests/test_a.py"],
        "required_check_contexts": [AGGREGATE],
        "decision_id": "owner-20261101-pr3752",
        "expires_at": FUTURE,
    }
    data.update(overrides)
    return data


def prepare(client, **overrides):
    return console.prepare(policy(**overrides), client)


def post_owner(client, body, comment_id, when):
    client._repo._issue.add(FakeComment(comment_id, "Blummer92", when, body))


def posted_pending(client):
    """prepare -> owner posts PENDING (no decide yet)."""
    pending = prepare(client)
    post_owner(client, pending["pending_comment"], 1001, WHEN1)
    return pending


def decided_pending(client):
    """prepare -> owner posts PENDING -> decide (AUTHORIZED not posted)."""
    pending = posted_pending(client)
    decided = console.decide(
        pending, client, decision_id="owner-decision-2",
        confirmation=f"{REPO}#3752@{HEAD}:squash")
    return pending, decided


def full_flow(client):
    """prepare -> owner posts PENDING -> decide -> owner posts AUTHORIZED."""
    pending, decided = decided_pending(client)
    post_owner(client, decided["authorized_comment"], 1002, WHEN2)
    return pending, decided


def transport(body="Part of #2410"):
    """Owner merge-admission request naming the authorized binding."""
    return {
        "status": "accepted", "reason": "accepted-merge-admission-envelope",
        "repository": REPO, "issue_number": 3463, "comment_id": 101,
        "actor": "Blummer92", "run_attempt": 1,
        "logical_trigger_id_or_none": "issue-comment-trigger:" + "e" * 64,
        "merge_admission_pr_number_or_none": 3752,
        "merge_admission_head_sha_or_none": HEAD,
        "merge_admission_body_sha256_or_none": sha256(body.encode()).hexdigest(),
        "merge_admission_method_or_none": "squash",
    }


def dispatch(client):
    """The real dispatch consumer, on the producer's own fake GitHub."""
    return evaluate_merge_dispatch_applicability(
        transport(), repository=REPO, github_client=client,
        evaluated_at=console.utcnow())


def drift_on(client, read, mutate):
    client._repo.on_pull = lambda call, pr: mutate(pr) if call == read else None


# ---------------------------------------------------------------- happy path
def test_prepare_produces_pending_with_real_canonical_binding():
    client = make_client()
    result = prepare(client)
    assert result["status"] == "PENDING_OWNER_PUBLICATION"
    assert result["merge_authorized"] is False
    assert result["side_effects_performed"] is False
    assert result["head_sha"] == HEAD and result["base_sha"] == BASE
    assert result["scope_fingerprint"] == changed_scope_fingerprint(
        [("tests/test_a.py", BLOB)])
    record = console.comment_to_record(result["pending_comment"])
    assert record.state is MergeAuthorizationState.PENDING
    assert record.authorization_id == result["authorization_id"]
    assert record.binding.exact_head_sha == HEAD
    assert record.binding.permitted_merge_method == "squash"
    lines = result["pending_comment"].split("\n")
    assert len(lines) == 2 and lines[0] == "agent-os-merge-authorization/v1"
    # Read budget: exactly one gated read plus one gated renewal, so
    # dropping the time-separated renewal or adding reads both fail.
    assert client._repo._pull_calls == 2


def test_full_owner_flow_verifies_with_both_revisions_and_no_merge_authority():
    client = make_client()
    pending, decided = full_flow(client)
    assert decided["status"] == "AWAITING_OWNER_PUBLICATION_AND_READBACK"
    assert decided["pending_revision"] == pending["authorization_revision"]
    approved = console.comment_to_record(decided["authorized_comment"])
    assert approved.state is MergeAuthorizationState.AUTHORIZED
    assert approved.previous_revision == pending["authorization_revision"]
    assert approved.binding == console.comment_to_record(
        pending["pending_comment"]).binding
    verified = console.verify(decided, client)
    assert verified["status"] == "SOURCE_CURRENT_CONTENT_APPLICABLE"
    assert verified["merge_authorized"] is False
    assert verified["human_origin_attested"] is False
    assert verified["source_comment_ids"] == [1001, 1002]
    assert verified["side_effects_performed"] is False


def test_prepare_mirrors_live_3752_scope_shape():
    files = [
        FakeFile("08_Tooling/workflow-scheduler/tests/test_ready_recovery_dispatch.py",
                 "2e61c73b8d7f39a567b7905599bec27adb9bdf82"),
        FakeFile("tests/test_2410_ready_recovery_ingress_workflow.py",
                 "a734c5f00958bd19f6f57335a620fccb8bf623e7"),
        FakeFile("tests/test_agent_os_ready_admission_workflow.py",
                 "157723f4eb8c5948c901588a1e028aad01cd4f73"),
    ]
    client = make_client(pr=FakePR(files=files))
    result = console.prepare(policy(
        allowed_files=[f.filename for f in files],
        forbidden_paths=[".github/workflows/**", "00_Governance/**",
                         "scripts/agent_os_issue_acceptance/merge_authorization.py"],
        required_tests=[f.filename for f in files],
    ), client)
    assert result["scope_fingerprint"] == changed_scope_fingerprint(
        [(f.filename, f.sha) for f in files])
    assert result["status"] == "PENDING_OWNER_PUBLICATION"


def test_latest_status_wins_over_older_failure():
    commit = FakeCommit(statuses=[
        FakeStatus(AGGREGATE, 5, "failure", "github-actions[bot]", 41898282),
        FakeStatus(AGGREGATE, 9, "success", "github-actions[bot]", 41898282),
    ])
    assert prepare(make_client(commit=commit))["status"] == \
        "PENDING_OWNER_PUBLICATION"


def test_prepare_refuses_check_run_only_aggregate_without_commit_status():
    # Dispatch-aligned: the producer requires the aggregate to be a real
    # commit status, even when the check-run publisher verifies. A
    # status-only aggregate is covered by test_latest_status_wins, and
    # run+status by green_commit.
    commit = FakeCommit(runs=[FakeRun(AGGREGATE, 10, "success",
                                      FakeApp("github-actions", 15368))])
    with pytest.raises(ValueError, match="commit status"):
        prepare(make_client(commit=commit))


def test_exact_head_review_is_audit_only_not_a_gate():
    pr = FakePR(reviews=[FakeReview("APPROVED", "99" * 20)])
    assert prepare(make_client(pr=pr))["status"] == "PENDING_OWNER_PUBLICATION"


# ---------------------------------------------------------------- prepare negatives
def test_prepare_refuses_wrong_publisher_status_and_check_run():
    bad_status = FakeCommit(statuses=[FakeStatus(
        AGGREGATE, 20, "success", "someone-else", 123)])
    with pytest.raises(ValueError, match="publisher"):
        prepare(make_client(commit=bad_status))
    bad_run = FakeCommit(runs=[FakeRun(AGGREGATE, 10, "success",
                                       FakeApp("rogue-app", 999))])
    with pytest.raises(ValueError, match="publisher"):
        prepare(make_client(commit=bad_run))


def test_prepare_refuses_missing_failed_and_disagreeing_aggregate():
    with pytest.raises(ValueError, match="required check"):
        prepare(make_client(commit=FakeCommit()))
    failed = FakeCommit(statuses=[FakeStatus(
        AGGREGATE, 20, "failure", "github-actions[bot]", 41898282)])
    with pytest.raises(ValueError, match="required check"):
        prepare(make_client(commit=failed))
    disagree = FakeCommit(
        runs=[FakeRun(AGGREGATE, 10, "success",
                      FakeApp("github-actions", 15368))],
        statuses=[FakeStatus(AGGREGATE, 20, "failure",
                             "github-actions[bot]", 41898282)])
    with pytest.raises(ValueError, match="required check"):
        prepare(make_client(commit=disagree))


def test_prepare_refuses_out_of_scope_and_forbidden_paths():
    pr = FakePR(files=[FakeFile("src/evil.py", BLOB)])
    with pytest.raises(ValueError, match="outside explicit owner scope"):
        prepare(make_client(pr=pr))
    pr = FakePR(files=[FakeFile(".github/workflows/x.yml", BLOB)])
    with pytest.raises(ValueError, match="forbidden"):
        prepare(make_client(pr=pr), allowed_files=[
            ".github/workflows/x.yml"])


def test_policy_allows_empty_forbidden_paths():
    # An empty exclusion list adds no restriction beyond allowed_files.
    assert prepare(make_client(), forbidden_paths=[])["status"] == \
        "PENDING_OWNER_PUBLICATION"


def test_prepare_refuses_unresolved_threads_across_pages():
    with pytest.raises(ValueError, match="unresolved"):
        prepare(make_client(threads=(((True,), True), ((False,), False))))
    with pytest.raises(ValueError, match="unresolved"):
        prepare(make_client(threads=(((False,), True), ((True,), False))))


def test_prepare_refuses_blocking_review_even_at_stale_commit():
    pr = FakePR(reviews=[FakeReview("CHANGES_REQUESTED", "99" * 20)])
    with pytest.raises(ValueError, match="blocking review"):
        prepare(make_client(pr=pr))


def test_fake_get_pull_exposes_target_ref_and_state_drift():
    # Non-vacuity: the drift tests below are meaningless unless a later
    # read really shows a retarget at the same base SHA, and a closed
    # state independent of merged, without leaking into earlier reads.
    repo = make_client()._repo
    first = repo.get_pull(3752)
    repo._pr.base.ref, repo._pr.state = "release", "closed"
    second = repo.get_pull(3752)
    assert (first.base.ref, first.state) == ("main", "open")
    assert (second.base.ref, second.base.sha, second.state, second.merged) == \
        ("release", BASE, "closed", False)


# Field inventory from the consumer, not from the renewal predicate: each
# drift maps to the reason the dispatch admission gate gives for the same
# PR state, and that consumer is asserted on the same fake below.
LIFECYCLE_DRIFT = {
    "base-ref-same-sha": (lambda pr: setattr(pr.base, "ref", "release"),
                          "base-not-main"),
    "draft": (lambda pr: setattr(pr, "draft", True), "pr-not-ready"),
    "closed-unmerged": (lambda pr: setattr(pr, "state", "closed"),
                        "pr-not-ready"),
    "merged": (lambda pr: pr.__dict__.update(state="closed", merged=True),
               "pr-not-ready"),
    "mergeable-false": (lambda pr: setattr(pr, "mergeable", False),
                        "pr-mergeability-not-clean"),
    "mergeable-unknown": (lambda pr: setattr(pr, "mergeable", None),
                          "pr-mergeability-not-clean"),
}


@pytest.mark.parametrize("read", [1, 2], ids=["first-read", "renewal-read"])
@pytest.mark.parametrize("name", sorted(LIFECYCLE_DRIFT))
def test_prepare_refuses_lifecycle_drift_the_dispatch_consumer_refuses(
        name, read):
    mutate, consumer_reason = LIFECYCLE_DRIFT[name]
    client = make_client()
    drift_on(client, read, mutate)
    prefix = "changed during evidence collection: " if read == 2 else ""
    with pytest.raises(ValueError, match=prefix + ".*(Ready|main|mergeability)"):
        prepare(client)
    assert client._repo._issue._comments == []
    receipt = admission.evaluate_merge_admission_transport(
        transport(), repository=REPO, github_client=client,
        evaluated_at=console.utcnow())
    assert consumer_reason in receipt["reason_codes"]


@pytest.mark.parametrize("mutate", [
    lambda pr: setattr(pr.head, "sha", "44" * 20),
    lambda pr: setattr(pr.base, "sha", "44" * 20),
    lambda pr: setattr(pr, "title", "Edited title"),
    lambda pr: setattr(pr, "body", "Edited body"),
], ids=["head-sha", "base-sha", "title", "body"])
def test_prepare_refuses_identity_drift_between_reads(mutate):
    client = make_client()
    drift_on(client, 2, mutate)
    with pytest.raises(ValueError, match="changed during evidence collection"):
        prepare(client)


AGGREGATE_SHAPES = {
    "status-and-run": (lambda repo: None, True),
    "status-only": (lambda repo: setattr(repo, "_commit", FakeCommit(
        statuses=green_commit()._statuses)), True),
    "check-run-only-trusted-app": (lambda repo: setattr(
        repo, "_commit", FakeCommit(runs=green_commit()._runs)), False),
    "status-wrong-publisher": (lambda repo: setattr(repo, "_commit", FakeCommit(
        statuses=[FakeStatus(AGGREGATE, 20, "success", "someone-else", 123)])),
        False),
    "head-moved": (lambda repo: setattr(repo._pr.head, "sha", "55" * 20),
                   False),
}


@pytest.mark.parametrize("shape", sorted(AGGREGATE_SHAPES))
def test_producer_verification_never_outruns_dispatch_consumer(shape):
    # One fake GitHub, one exact-head evidence state, two components: a
    # producer SOURCE_CURRENT verdict must be consumable by the real
    # dispatch consumer, and a consumer refusal must be a producer refusal.
    change, accepted = AGGREGATE_SHAPES[shape]
    client = make_client()
    _, decided = full_flow(client)
    change(client._repo)
    try:
        producer = console.verify(decided, client)["status"] == \
            "SOURCE_CURRENT_CONTENT_APPLICABLE"
    except ValueError:
        producer = False
    receipt = dispatch(client)
    consumer = receipt["dispatch_checks_passed"] is True and \
        receipt["status"] == "awaiting-human-attestation"
    assert (producer, consumer) == (accepted, accepted), receipt["reason_codes"]
    # Content admission never substitutes for runtime human-origin approval.
    assert receipt["merge_authorized"] is False


def test_prepare_refuses_closing_reference_but_allows_nonclosing_part_of():
    pr = FakePR(body="Closes #2410")
    with pytest.raises(ValueError, match="unauthorized-closing"):
        prepare(make_client(pr=pr))
    pr = FakePR(body="Part of #2410")
    assert prepare(make_client(pr=pr))["status"] == \
        "PENDING_OWNER_PUBLICATION"


def test_prepare_refuses_existing_pending_current_and_malformed_chains():
    # Pending-only chain: source is STALE, must still be reconciled first.
    client = make_client()
    posted_pending(client)
    with pytest.raises(ValueError, match="reconciled first"):
        prepare(client)
    # Malformed trusted record: source is NEEDS_DECISION, refused too.
    client2 = make_client(comments=[FakeComment(
        2001, "Blummer92", WHEN1,
        "agent-os-merge-authorization/v1\nnot-json")])
    with pytest.raises(ValueError, match="reconciled first"):
        prepare(client2)


def test_prepare_refuses_org_owned_repository():
    repo = FakeRepo(FakePR(), green_commit(), FakeIssue(),
                    owner_type="Organization")
    with pytest.raises(ValueError, match="verified User"):
        prepare(FakeClient(repo))


# ---------------------------------------------------------------- decide negatives
def test_decide_refuses_without_owner_posted_predecessor():
    client = make_client()
    pending = prepare(client)
    with pytest.raises(ValueError, match="predecessor not verified"):
        console.decide(pending, client, decision_id="d2",
                       confirmation=f"{REPO}#3752@{HEAD}:squash")


def test_decide_refuses_app_performed_and_footer_predecessors():
    for body_suffix, app in (("", "chatgpt-connector"),
                             ("\nAgent footer: generated", None)):
        client = make_client()
        pending = prepare(client)
        post_owner(client, pending["pending_comment"] + body_suffix, 1001,
                   WHEN1)
        if app is not None:
            client._repo._issue._comments[-1].performed_via_github_app = \
                SimpleNamespace(slug=app)
        with pytest.raises(ValueError, match="predecessor not verified"):
            console.decide(pending, client, decision_id="d2",
                           confirmation=f"{REPO}#3752@{HEAD}:squash")


def test_decide_refuses_wrong_confirmation_and_moved_head():
    client = make_client()
    pending = posted_pending(client)
    with pytest.raises(ValueError, match="confirmation does not match"):
        console.decide(pending, client, decision_id="d2",
                       confirmation=f"{REPO}#3752@{'44' * 20}:squash")
    client._repo._pr.head.sha = "55" * 20
    with pytest.raises(ValueError, match="stale"):
        console.decide(pending, client, decision_id="d2",
                       confirmation=f"{REPO}#3752@{HEAD}:squash")


def test_decide_refuses_wrong_author_posting():
    client = make_client()
    pending = prepare(client)
    client._repo._issue.add(FakeComment(
        1001, "someone-else", WHEN1, pending["pending_comment"]))
    with pytest.raises(ValueError, match="predecessor not verified"):
        console.decide(pending, client, decision_id="d2",
                       confirmation=f"{REPO}#3752@{HEAD}:squash")


# ---------------------------------------------------------------- verify negatives
def test_verify_refuses_missing_second_revision_and_wrong_author():
    # Only the pending comment was ever posted for this client.
    client2 = make_client()
    _, decided2 = decided_pending(client2)
    with pytest.raises(ValueError, match="not current"):
        console.verify(decided2, client2)
    # Authorized comment posted by someone else is ignored by the reader.
    client2._repo._issue.add(FakeComment(
        1002, "someone-else", WHEN2, decided2["authorized_comment"]))
    with pytest.raises(ValueError, match="not current"):
        console.verify(decided2, client2)


def test_verify_refuses_replayed_authorized_revision():
    client = make_client()
    pending, decided = full_flow(client)
    client._repo._issue.add(FakeComment(
        1003, "Blummer92", datetime(2026, 11, 1, 12, 6, tzinfo=timezone.utc),
        decided["authorized_comment"]))
    with pytest.raises(ValueError, match="not current"):
        console.verify(decided, client)


def test_verify_refuses_superseded_chain_and_source_drift():
    client = make_client()
    pending, decided = full_flow(client)
    record = console.comment_to_record(decided["authorized_comment"])
    # Decision time must be after the authorized record's real decision_at
    # and before the 2099 expiry, so use 2098 for this synthetic third
    # revision; the source reader still rejects the superseded chain.
    third = record_merge_authorization_decision(
        record, state=MergeAuthorizationState.SUPERSEDED,
        decision_id="owner-decision-3", authorizer_id="Blummer92",
        decision_at="2098-01-01T00:00:00Z")
    post_owner(client, serialize_merge_authorization_comment(third), 1003,
               datetime(2098, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="not current"):
        console.verify(decided, client)
    # Source drift between the two verification reads: reset the comment
    # call counter so verify's first read sees both comments and its
    # second read sees only the pending one.
    client2 = make_client()
    pending2, decided2 = full_flow(client2)
    first, second = list(client2._repo._issue._comments), \
        [client2._repo._issue._comments[0]]
    client2._repo._issue._sequence = [first, second]
    client2._repo._issue._calls = 0
    with pytest.raises(ValueError, match="changed during verification"):
        console.verify(decided2, client2)


def test_verify_refuses_expired_record(monkeypatch):
    client = make_client()
    monkeypatch.setattr(console, "utcnow",
                        lambda: "2026-01-01T00:00:00Z")
    pending = console.prepare(policy(expires_at="2026-01-02T00:00:00Z"),
                              client)
    post_owner(client, pending["pending_comment"], 1001,
               datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
    decided = console.decide(
        pending, client, decision_id="d2",
        confirmation=f"{REPO}#3752@{HEAD}:squash")
    post_owner(client, decided["authorized_comment"], 1002,
               datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc))
    monkeypatch.undo()
    with pytest.raises(ValueError, match="inapplicable"):
        console.verify(decided, client)


# ---------------------------------------------------------------- policy / surface
def test_comment_to_record_rejects_extra_line_wrong_marker_and_noncanonical():
    client = make_client()
    result = prepare(client)
    body = result["pending_comment"]
    with pytest.raises(ValueError, match="exactly two"):
        console.comment_to_record(body + "\nAgent footer: generated")
    with pytest.raises(ValueError, match="marker"):
        console.comment_to_record(body.split("\n", 1)[1])
    tampered = body.split("\n")
    tampered[1] = tampered[1][:-2] + "00"
    with pytest.raises(ValueError):
        console.comment_to_record("\n".join(tampered))


def test_policy_validation_rejects_blind_template_reuse_and_bad_fields():
    base = policy()
    for mutate in (
        lambda d: d.update(extra=1),
        lambda d: d.update(required_check_contexts=["other"]),
        lambda d: d.update(allowed_files=["a.py", "a.py"]),
        lambda d: d.update(allowed_files=[]),
        lambda d: d.update(merge_method="fast-forward"),
        lambda d: d.update(expires_at="2000-01-01T00:00:00Z"),
        lambda d: d.update(expires_at="REPLACE_WITH_FRESH_UTC_EXPIRY_BEFORE_USE"),
        lambda d: d.update(decision_id="PENDING-NO-OWNER-MERGE-DECISION"),
        lambda d: d.update(decision_id="  "),
        # Canonical _repository rules: a loose one-slash check would
        # admit both of these; the reused validator refuses them.
        lambda d: d.update(repository="owner name/agent-os"),
        lambda d: d.update(repository="../agent-os"),
    ):
        data = dict(base)
        mutate(data)
        with pytest.raises(ValueError):
            console.strict_policy(data)


def test_output_never_overwrites_and_never_claims_side_effects(tmp_path):
    client = make_client()
    result = prepare(client)
    target = tmp_path / "out.json"
    console.write_new_json(str(target), result)
    assert json.loads(target.read_text())["side_effects_performed"] is False
    with pytest.raises(FileExistsError):
        console.write_new_json(str(target), result)


def test_console_contains_no_github_write_route():
    source = Path(console.__file__).read_text(encoding="utf-8")
    for forbidden in ("create_issue_comment(", "create_comment(",
                      "merge_pull_request(", "update_branch(",
                      "create_pull(", "edit(", "delete_branch(",
                      "add_to_labels(", "create_label("):
        assert forbidden not in source, forbidden


def test_client_from_environment_requires_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "")
    with pytest.raises(ValueError, match="GITHUB_TOKEN"):
        console.client_from_environment()


def test_main_maps_client_failure_to_blocked_exit(monkeypatch, capsys,
                                                  tmp_path):
    class Broken:
        def get_repo(self, name):
            raise RuntimeError("network down")
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy()))
    monkeypatch.setattr(console, "client_from_environment",
                        lambda: Broken())
    code = console.main(["prepare", "--policy", str(policy_path),
                         "--output", str(tmp_path / "out.json")])
    assert code == 2
    assert "BLOCKED" in capsys.readouterr().err
