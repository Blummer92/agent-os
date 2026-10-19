"""Authorizing merge-admission consumer: trusted approval root + QA gates."""
from __future__ import annotations

import hashlib

import pytest

from scripts.agent_os_issue_acceptance import merge_admission_applicability as app
from scripts.agent_os_issue_acceptance.approval_records import (
    ApprovalBinding,
    ApprovalKind,
    ApprovalRecord,
    ApprovalState,
    APPROVAL_RECORD_SCHEMA_VERSION,
    HandoffCohort,
    record_approval_decision,
)
from scripts.agent_os_issue_acceptance.approval_source import (
    APPROVAL_MARKER,
    ApprovalCommentSnapshot,
    ApprovalSourceSnapshot,
    ApprovalSourceStatus,
    reacquire_approval_source,
    serialize_approval_comment,
)
from scripts.agent_os_issue_acceptance.merge_admission_applicability import (
    evaluate_merge_admission_applicability,
)
from scripts.agent_os_issue_acceptance.merge_authorization import (
    MergeAuthorizationBinding,
    MergeAuthorizationRecord,
    MergeAuthorizationState,
    MergeCheckEvidence,
    MergeReviewEvidence,
    changed_scope_fingerprint,
    pr_metadata_fingerprint,
    record_merge_authorization_decision,
)
from scripts.agent_os_issue_acceptance.merge_authorization_source import (
    serialize_merge_authorization_comment,
)

REPO = "blummer92/agent-os"
HEAD = "a" * 40
BASE_SHA = "b" * 40
BODY = "example body"
BODY_SHA = hashlib.sha256(BODY.encode()).hexdigest()
NOW = "2026-10-19T20:00:00Z"
FUTURE = "2026-10-19T23:00:00Z"


class Ref:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


# ---------------------------------------------------------------------------
# Approval record fixtures
# ---------------------------------------------------------------------------

def _approval_binding(**overrides):
    cohort = HandoffCohort(
        node_ids=("issue-1",),
        classification="parallel-candidate",
        reason_codes=("covered-no-deterministic-conflict",),
    )
    values = dict(
        proposal_version="1.0",
        proposal_id="draft-task-proposal:" + "a" * 64,
        handoff_digest="a" * 64,
        graph_digest="b" * 64,
        planning_result_digest="c" * 64,
        repository=REPO,
        base_branch="main",
        evaluated_repository_sha="d" * 40,
        evaluator_commit_sha="e" * 40,
        supplied_node_ids=("issue-1",),
        cohort_summaries=(cohort,),
        issueplan_current_state_evidence_id="issueplan-current-state:" + "b" * 64,
        repository_state_evidence_id="c" * 64,
        repository_evidence_type="test",
        tested_repository_sha="f" * 40,
        source_snapshot_fingerprint="0" * 64,
        scanner_result_fingerprint="1" * 64,
        implementation_contract_fingerprint="2" * 64,
        allowed_files=(),
        forbidden_paths=(),
        required_tests=(),
    )
    values.update(overrides)
    return ApprovalBinding(**values)


def _approved_record(**overrides):
    pending = ApprovalRecord(
        schema_version=APPROVAL_RECORD_SCHEMA_VERSION,
        approval_id="",
        approval_revision="",
        revision_number=1,
        previous_revision=None,
        approval_kind=ApprovalKind.IMPLEMENTATION,
        state=ApprovalState.PENDING,
        binding=_approval_binding(),
        authorizer_id="Blummer92",
        decision_id="d0",
        decision_at="2026-10-19T16:00:00Z",
        expires_at=overrides.pop("expires_at", FUTURE),
        supersedes_approval_id=None,
        reason_codes=(),
    )
    record = record_approval_decision(
        pending,
        state=ApprovalState.APPROVED,
        decision_id="d1",
        authorizer_id="Blummer92",
        decision_at="2026-10-19T17:00:00Z",
    )
    if overrides:
        import dataclasses
        record = dataclasses.replace(record, **overrides)
    return record


def _approval_comment(record, *, author="Blummer92", comment_id=101):
    return ApprovalCommentSnapshot(
        comment_id=comment_id,
        author_login=author,
        created_at="2026-10-19T18:00:00Z",
        body=serialize_approval_comment(record),
    )


class _ApprovalTransport:
    def __init__(self, comments, owner_login="Blummer92"):
        self._comments = comments
        self._owner = owner_login

    def read_approval_source(self, repository, pr_number):
        return ApprovalSourceSnapshot(
            repository=repository,
            pr_number=pr_number,
            owner_login=self._owner,
            owner_type="User",
            comments_complete=True,
            comments=tuple(self._comments),
        )


def _read_approval(comments):
    return reacquire_approval_source(
        transport=_ApprovalTransport(comments),
        repository=REPO,
        pr_number=3659,
    )


# ---------------------------------------------------------------------------
# changed_scope_fingerprint
# ---------------------------------------------------------------------------

def test_scope_fingerprint_is_deterministic_and_order_independent():
    files_a = [("b.py", "a" * 40), ("a.py", "b" * 40)]
    files_b = [("a.py", "b" * 40), ("b.py", "a" * 40)]
    assert changed_scope_fingerprint(files_a) == changed_scope_fingerprint(files_b)


def test_scope_fingerprint_changes_on_any_file_difference():
    base = [("a.py", "b" * 40)]
    assert changed_scope_fingerprint(base) != changed_scope_fingerprint([("a.py", "c" * 40)])
    assert changed_scope_fingerprint(base) != changed_scope_fingerprint(base + [("b.py", "d" * 40)])
    assert changed_scope_fingerprint(base) != changed_scope_fingerprint([])


def test_scope_fingerprint_rejects_malformed_inputs():
    with pytest.raises(ValueError):
        changed_scope_fingerprint([("a.py", "not-a-sha")])
    with pytest.raises(ValueError):
        changed_scope_fingerprint([("", "b" * 40)])
    with pytest.raises(ValueError):
        changed_scope_fingerprint(["not-a-tuple"])


# ---------------------------------------------------------------------------
# approval_source
# ---------------------------------------------------------------------------

def test_approval_source_accepts_owner_authored_approved_record():
    record = _approved_record()
    result = _read_approval([_approval_comment(record)])
    assert result.status is ApprovalSourceStatus.CURRENT
    assert result.reason_codes == ("current",)
    assert len(result.records) == 1
    assert result.records[0].approval_id == record.approval_id


def test_approval_source_ignores_non_owner_comments():
    record = _approved_record()
    result = _read_approval([_approval_comment(record, author="someone-else")])
    assert result.status is ApprovalSourceStatus.BLOCKED
    assert result.reason_codes == ("approval.absent",)


def test_approval_source_rejects_malformed_record():
    bad = ApprovalCommentSnapshot(
        comment_id=102, author_login="Blummer92",
        created_at="2026-10-19T18:00:00Z",
        body=APPROVAL_MARKER + "\nnot-valid-json",
    )
    result = _read_approval([bad])
    assert result.status is ApprovalSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("source.trusted-record-malformed",)


def test_approval_source_rejects_wrong_repository():
    record = _approved_record()
    transport = _ApprovalTransport([_approval_comment(record)])
    result = reacquire_approval_source(
        transport=transport, repository="other/repo", pr_number=3659,
    )
    assert result.status is ApprovalSourceStatus.NEEDS_DECISION


def test_approval_source_filters_expected_approval_id():
    record = _approved_record()
    result = reacquire_approval_source(
        transport=_ApprovalTransport([_approval_comment(record)]),
        repository=REPO, pr_number=3659,
        expected_approval_id="approval:nonexistent",
    )
    assert result.status is ApprovalSourceStatus.BLOCKED


def _approved_with_files(*files):
    """Build an approved record whose binding carries the given allowed_files."""
    binding = _approval_binding(allowed_files=tuple(files))
    pending = ApprovalRecord(
        schema_version=APPROVAL_RECORD_SCHEMA_VERSION,
        approval_id="", approval_revision="", revision_number=1,
        previous_revision=None, approval_kind=ApprovalKind.IMPLEMENTATION,
        state=ApprovalState.PENDING, binding=binding,
        authorizer_id="Blummer92", decision_id="d0",
        decision_at="2026-10-19T16:00:00Z", expires_at=FUTURE,
        supersedes_approval_id=None, reason_codes=(),
    )
    return record_approval_decision(
        pending, state=ApprovalState.APPROVED, decision_id="d1",
        authorizer_id="Blummer92", decision_at="2026-10-19T17:00:00Z",
    )


def test_approval_source_returns_all_current_approvals():
    r1 = _approved_with_files("a.py")
    r2 = _approved_with_files("b.py")
    assert r1.approval_id != r2.approval_id
    comments = [
        _approval_comment(r1, comment_id=101),
        _approval_comment(r2, comment_id=102),
    ]
    result = _read_approval(comments)
    assert result.status is ApprovalSourceStatus.CURRENT
    assert len(result.records) == 2
    assert result.source_comment_ids == (101, 102)


# ---------------------------------------------------------------------------
# Consumer: fake GitHub surface
# ---------------------------------------------------------------------------

class _FakeCheckRun:
    def __init__(self, name, conclusion):
        self.name = name
        self.status = "completed"
        self.conclusion = conclusion


class _FakeStatus:
    def __init__(self, context, state):
        self.context = context
        self.state = state


class _FakeCommit:
    def __init__(self, check_runs=(), statuses=()):
        self._runs = check_runs
        self._statuses = statuses

    def get_check_runs(self):
        return list(self._runs)

    def get_statuses(self):
        return list(self._statuses)


class _FakeReview:
    def __init__(self, state):
        self.state = state


PR_NUMBER = 630
EMPTY_BODY_SHA = hashlib.sha256(b"").hexdigest()


class _FakePR:
    def __init__(self, *, head=HEAD, body="", draft=False, base="main",
                 mergeable=True, reviews=(), files=(), title=""):
        self.number = PR_NUMBER
        self.state = "open"
        self.draft = draft
        self.merged = False
        self.head = Ref(sha=head)
        self.base = Ref(ref=base, sha=BASE_SHA)
        self.body = body
        self.title = title
        self.mergeable = mergeable
        self._reviews = reviews
        self._files = files

    def get_reviews(self):
        return list(self._reviews)

    def get_files(self):
        return [Ref(filename=n, sha=s) for n, s in self._files]


class _FakeRepo:
    owner = Ref(login="Blummer92", type="User")

    def __init__(self, pr, auth_comments=(), approval_comments=(), check_runs=(), statuses=()):
        self._pr = pr
        self._auth_comments = auth_comments
        self._approval_comments = approval_comments
        self._commit = _FakeCommit(check_runs, statuses)

    def get_pull(self, number):
        assert number == PR_NUMBER
        return self._pr

    def get_issue(self, number):
        assert number == PR_NUMBER
        comments = list(self._auth_comments) + list(self._approval_comments)
        return Ref(get_comments=lambda: iter(comments))

    def get_commit(self, sha):
        assert sha == HEAD
        return self._commit


class _FakeClient:
    def __init__(self, repo):
        self._repo = repo

    def get_repo(self, name):
        assert name == REPO
        return self._repo


class _FakeComment:
    """Raw GitHub comment shape consumed by _GitHubSource/_GitHubApprovalSource."""
    def __init__(self, comment_id, body, author="Blummer92"):
        self.id = comment_id
        self.user = Ref(login=author)
        from datetime import datetime
        self.created_at = datetime(2026, 10, 19, 18, 0, 0)
        self.body = body


def _auth_comment(record, comment_id=201):
    return _FakeComment(comment_id, serialize_merge_authorization_comment(record))


def _approval_raw_comment(record, comment_id=101):
    return _FakeComment(comment_id, serialize_approval_comment(record))


def _bundle_record(*, expires_at=FUTURE, files=(("a.py", "b" * 40),)):
    """Build a canonical (record, approval) pair via the existing test bundle.

    The record's binding carries a real changed_scope_fingerprint computed
    from `files`, so the consumer's live scope check can pass.
    """
    import dataclasses
    import sys
    sys.path.insert(0, "tests/agent_os_issue_acceptance")
    import test_merge_authorization as t
    bundle = t._bundle(approval_expires="2026-10-20T00:00:00Z")
    approval = bundle[0]
    scope = changed_scope_fingerprint(list(files))
    pr = dataclasses.replace(
        t._pr(bundle), changed_scope_fingerprint=scope, evidence_id="",
    )
    record, _ = t._authorized(bundle, pr=pr, expires_at=expires_at)
    assert record.binding.approval_id == approval.approval_id
    return record, approval


def _transport(body_sha=EMPTY_BODY_SHA):
    return {
        "status": "accepted",
        "reason": "accepted-merge-admission-envelope",
        "repository": REPO,
        "merge_admission_pr_number_or_none": PR_NUMBER,
        "merge_admission_head_sha_or_none": HEAD,
        "merge_admission_body_sha256_or_none": body_sha,
        "merge_admission_method_or_none": "squash",
        "comment_id": 999001,
        "issue_number": 3463,
        "logical_trigger_id_or_none": "trigger-1",
    }


def _passing_repo(**pr_kwargs):
    files = pr_kwargs.pop("files", [("a.py", "b" * 40)])
    check_runs = pr_kwargs.pop("check_runs", (_FakeCheckRun("validate", "success"),))
    statuses = pr_kwargs.pop("statuses", ())
    reviews = pr_kwargs.pop("reviews", ())
    auth_record, approval = _bundle_record(files=files)
    pr = _FakePR(files=files, reviews=reviews, **pr_kwargs)
    repo = _FakeRepo(
        pr,
        auth_comments=[_auth_comment(auth_record)],
        approval_comments=[_approval_raw_comment(approval)],
        check_runs=check_runs,
        statuses=statuses,
    )
    return repo, approval, auth_record


def _evaluate(repo):
    return evaluate_merge_admission_applicability(
        _transport(), repository=REPO, github_client=_FakeClient(repo),
        evaluated_at=NOW,
    )


def test_full_pass_emits_authorizing_receipt():
    repo, approval, auth_record = _passing_repo()
    receipt = _evaluate(repo)
    assert receipt["merge_authorized"] is True, receipt["reason_codes"]
    assert receipt["status"] == "applicable"
    assert receipt["reason_codes"] == []
    assert receipt["authorization_id"] == auth_record.authorization_id
    assert receipt["expected_head_sha"] == HEAD
    assert receipt["canonical_applicability_evaluated"] is False


def test_approval_reason_codes():
    from scripts.agent_os_issue_acceptance.merge_admission_applicability import (
        _approval_reason_codes,
    )
    from datetime import datetime, timezone
    _, approval = _bundle_record()
    auth_record, _ = _bundle_record()
    now = datetime(2026, 10, 19, 20, 0, 0, tzinfo=timezone.utc)
    assert _approval_reason_codes(approval, auth_record, now) == []
    expired = Ref(
        state=approval.state,
        approval_id=approval.approval_id,
        approval_revision=approval.approval_revision,
        expires_at="2026-10-19T19:00:00Z",
    )
    assert "approval.expired" in _approval_reason_codes(expired, auth_record, now)
    mismatched = Ref(
        state=approval.state,
        approval_id="approval:other",
        approval_revision=approval.approval_revision,
        expires_at="2026-10-19T23:00:00Z",
    )
    assert "approval.mismatch" in _approval_reason_codes(mismatched, auth_record, now)
    rejected = Ref(
        state=ApprovalState.REJECTED,
        approval_id=approval.approval_id,
        approval_revision=approval.approval_revision,
        expires_at="2026-10-19T23:00:00Z",
    )
    assert "approval.not-approved" in _approval_reason_codes(rejected, auth_record, now)


def test_wrong_approval_id_blocks():
    # The approval source filters to the authorization's expected approval_id;
    # a comment carrying a different approval does not satisfy the gate.
    files = [("a.py", "b" * 40)]
    auth_record, approval = _bundle_record(files=files)
    other = _approved_with_files("other.py")
    assert other.approval_id != approval.approval_id
    pr = _FakePR(files=files)
    repo = _FakeRepo(
        pr,
        auth_comments=[_auth_comment(auth_record)],
        approval_comments=[_approval_raw_comment(other)],
        check_runs=(_FakeCheckRun("validate", "success"),),
    )
    receipt = _evaluate(repo)
    assert receipt["merge_authorized"] is False
    assert "approval.absent" in receipt["reason_codes"]


def test_missing_approval_blocks():
    files = [("a.py", "b" * 40)]
    auth_record, _ = _bundle_record(files=files)
    pr = _FakePR(files=files)
    repo = _FakeRepo(
        pr,
        auth_comments=[_auth_comment(auth_record)],
        approval_comments=[],
        check_runs=(_FakeCheckRun("validate", "success"),),
    )
    receipt = _evaluate(repo)
    assert receipt["merge_authorized"] is False
    assert "approval.absent" in receipt["reason_codes"]


def test_failing_checks_block():
    repo, _, _ = _passing_repo(check_runs=(_FakeCheckRun("validate", "failure"),))
    receipt = _evaluate(repo)
    assert receipt["merge_authorized"] is False
    assert "qa.checks-failing" in receipt["reason_codes"]


def test_no_check_evidence_blocks():
    repo, _, _ = _passing_repo(check_runs=(), statuses=())
    receipt = _evaluate(repo)
    assert receipt["merge_authorized"] is False
    assert "qa.no-check-evidence" in receipt["reason_codes"]


def test_changes_requested_review_blocks():
    repo, _, _ = _passing_repo(reviews=(_FakeReview("CHANGES_REQUESTED"),))
    receipt = _evaluate(repo)
    assert receipt["merge_authorized"] is False
    assert "review.changes-requested" in receipt["reason_codes"]


def test_closing_keyword_without_admission_blocks():
    closing_body = "This fixes #123."
    closing_sha = hashlib.sha256(closing_body.encode()).hexdigest()
    files = [("a.py", "b" * 40)]
    auth_record, approval = _bundle_record(files=files)
    pr = _FakePR(files=files, body=closing_body)
    repo = _FakeRepo(
        pr,
        auth_comments=[_auth_comment(auth_record)],
        approval_comments=[_approval_raw_comment(approval)],
        check_runs=(_FakeCheckRun("validate", "success"),),
    )
    transport = _transport(body_sha=closing_sha)
    receipt = evaluate_merge_admission_applicability(
        transport, repository=REPO, github_client=_FakeClient(repo),
        evaluated_at=NOW,
    )
    assert receipt["merge_authorized"] is False
    assert "closure.unauthorized-reference" in receipt["reason_codes"]


def test_scope_change_blocks():
    old_files = [("a.py", "b" * 40)]
    auth_record, approval = _bundle_record(files=old_files)
    new_files = [("a.py", "c" * 40)]
    pr = _FakePR(files=new_files)
    repo = _FakeRepo(
        pr,
        auth_comments=[_auth_comment(auth_record)],
        approval_comments=[_approval_raw_comment(approval)],
        check_runs=(_FakeCheckRun("validate", "success"),),
    )
    receipt = _evaluate(repo)
    assert receipt["merge_authorized"] is False
    assert "scope.changed" in receipt["reason_codes"]


def test_stale_head_blocks_without_authorization():
    repo, _, _ = _passing_repo()
    pr = repo._pr
    pr.head = Ref(sha="f" * 40)
    receipt = _evaluate(repo)
    assert receipt["merge_authorized"] is False
    assert "stale-head" in receipt["reason_codes"]


def test_malformed_transport_never_authorizes():
    repo, _, _ = _passing_repo()
    receipt = evaluate_merge_admission_applicability(
        {"status": "bogus"}, repository=REPO, github_client=_FakeClient(repo),
        evaluated_at=NOW,
    )
    assert receipt["merge_authorized"] is False
