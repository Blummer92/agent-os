"""Tests for merge_applicability.py: dispatch-time applicability consumer.

Every authorization artifact is built through the canonical producers; the
fake GitHub surface is read-only. The consumer must never emit
merge_authorized=true, even when every verifiable check passes.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.agent_os_issue_acceptance import (  # noqa: E402
    MergeCheckEvidence,
    MergeReviewEvidence,
    approval_applicability_identity,
    build_merge_authorization_candidate,
    record_merge_authorization_decision,
    serialize_approval_applicability_result,
    serialize_approval_record,
    serialize_approved_execution_projection,
)
from scripts.agent_os_issue_acceptance.merge_authorization_source import (  # noqa: E402
    serialize_merge_authorization_comment,
)
from scripts.agent_os_issue_acceptance.approval_source import (  # noqa: E402
    APPLICABILITY_MARKER,
    APPROVAL_MARKER,
    PROJECTION_MARKER,
    serialize_approval_comment,
)
from scripts.agent_os_issue_acceptance.merge_authorization import (  # noqa: E402
    changed_scope_fingerprint,
    pr_metadata_fingerprint,
)
from scripts.agent_os_issue_acceptance.merge_applicability import (  # noqa: E402
    evaluate_merge_dispatch_applicability,
)

_HERE = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("_tauth", _HERE / "test_merge_authorization.py")
_tauth = importlib.util.module_from_spec(_spec)
sys.modules["_tauth"] = _tauth
_spec.loader.exec_module(_tauth)

OWNER = "Blummer92"
REPO = "blummer92/agent-os"
PR_NUMBER = 630
HEAD = "a" * 40
BASE = "b" * 40
FILE_SHA = "c" * 40
NOW = "2026-07-26T15:00:00Z"
TITLE, BODY = "Merge the thing", "Body text"
BODY_SHA = sha256(BODY.encode("utf-8")).hexdigest()


def _timed_bundle(decision_at, expires_at, eval_at):
    handoff = _tauth._handoff()
    issueplan = _tauth._issueplan(handoff)
    repository = _tauth._repo()
    proposals = _tauth.build_draft_task_proposals(
        handoff, issueplan, repository, created_at="2026-07-26T14:00:00Z"
    )
    proposal = proposals.proposals[0]
    candidate = _tauth.build_approval_candidate(
        proposal, issueplan, repository,
        approval_kind=_tauth.ApprovalKind.IMPLEMENTATION,
        authorizer_id="operator-requester", decision_id="approval-request",
        decision_at="2026-07-26T14:00:00Z", expires_at=expires_at,
    )
    approval = _tauth.record_approval_decision(
        candidate, state=_tauth.ApprovalState.APPROVED,
        decision_id="approval-decision", authorizer_id="repository-owner",
        decision_at=decision_at,
    )
    applicability = _tauth.evaluate_approval_applicability(
        approval, proposal, issueplan, repository, evaluated_at=eval_at
    )
    assert applicability.status == "applicable"
    projection_result = _tauth.build_approved_execution_projection(
        proposal, approval, applicability, issueplan, repository, projected_at=eval_at
    )
    assert projection_result.status == "complete"
    return approval, applicability, projection_result.projection, proposal, issueplan, repository


ALLOWED_FILE = "scripts/agent_os_issue_acceptance/merge_authorization.py"


def _authorized_record(bundle, decision_at="2026-07-26T14:30:00Z",
                       expires_at="2026-07-26T15:30:00Z", **changes):
    approval, applicability, projection = bundle[0], bundle[1], bundle[2]
    scope = changed_scope_fingerprint([(ALLOWED_FILE, FILE_SHA)])
    values = dict(
        repository=REPO, pull_request_number=PR_NUMBER, head_sha=HEAD,
        base_branch="main", base_sha_or_evidence_id=BASE, draft=False,
        ready_for_review=True, proposed_merge_method="squash",
        changed_scope_fingerprint=scope,
        required_checks=(MergeCheckEvidence(
            context="CI", app_identity="github-actions",
            tested_sha=HEAD, evidence_id="", state="success"),),
        review_evidence=MergeReviewEvidence(
            blocking_review_present=False, unresolved_conversation_count=0,
            exact_head_reviewed=True),
        evidence_id="", pr_title=TITLE, pr_body=BODY,
        pr_metadata_sha256=pr_metadata_fingerprint(TITLE, BODY),
        closure_admissions=(),
    )
    values.update(changes)
    evidence = _tauth._pr(bundle, **values)
    candidate = build_merge_authorization_candidate(
        approval, applicability, projection, evidence,
        current_proposal=bundle[3], current_issueplan_evidence=bundle[4],
        current_repository_state_evidence=bundle[5],
        authorizer_id="repository-owner", decision_id="merge-request",
        decision_at=decision_at, expires_at=expires_at,
        permitted_merge_method="squash",
    )
    return record_merge_authorization_decision(
        candidate, state=_tauth.MergeAuthorizationState.AUTHORIZED,
        decision_id="authz-decision", authorizer_id="repository-owner",
        decision_at=decision_at,
    )


# ---------------------------------------------------------------- fakes
class _User:
    def __init__(self, login):
        self.login = login


class _Comment:
    def __init__(self, cid, body, author=OWNER):
        self.id = cid
        self.body = body
        self.user = _User(author)
        self.created_at = datetime(2026, 7, 26, 14, 50, tzinfo=timezone.utc)


class _File:
    def __init__(self, filename, sha):
        self.filename = filename
        self.sha = sha


class _CheckRun:
    def __init__(self, name, conclusion):
        self.name = name
        self.conclusion = conclusion


class _Status:
    def __init__(self, context, state):
        self.context = context
        self.state = state


class _Commit:
    def __init__(self, runs=(), statuses=()):
        self._runs = runs
        self._statuses = statuses

    def get_check_runs(self):
        return list(self._runs)

    def get_statuses(self):
        return list(self._statuses)


class _Review:
    def __init__(self, state, commit_id):
        self.state = state
        self.commit_id = commit_id


class _Label:
    def __init__(self, name):
        self.name = name


class _Ref:
    def __init__(self, ref, sha):
        self.ref = ref
        self.sha = sha


class _PR:
    def __init__(self, **changes):
        self.number = PR_NUMBER
        self.state = "open"
        self.draft = False
        self.merged = False
        self.mergeable = True
        self.title = TITLE
        self.body = BODY
        self.head = _Ref("feat", HEAD)
        self.base = _Ref("main", BASE)
        self._files = [_File(ALLOWED_FILE, FILE_SHA)]
        self._reviews = [_Review("APPROVED", HEAD)]
        self._labels = []
        self.__dict__.update(changes)

    def get_files(self):
        return list(self._files)

    def get_reviews(self):
        return list(self._reviews)

    def get_labels(self):
        return list(self._labels)


class _Issue:
    def __init__(self, comments):
        self._comments = comments

    def get_comments(self):
        return list(self._comments)


class _Owner:
    def __init__(self, login):
        self.login = login
        self.type = "User"


class _Repo:
    def __init__(self, pr, comments, commit=None):
        self.owner = _Owner(OWNER)
        self._pr = pr
        self._comments = comments
        self._commit = commit or _Commit(
            runs=[_CheckRun("CI", "success")])

    def get_pull(self, number):
        assert number == PR_NUMBER
        return self._pr

    def get_issue(self, number):
        assert number == PR_NUMBER
        return _Issue(self._comments)

    def get_commit(self, sha):
        assert sha == self._pr.head.sha
        return self._commit


class _Client:
    def __init__(self, repo):
        self._repo = repo

    def get_repo(self, name):
        assert name == REPO
        return self._repo


def _comments_for(bundle, record, start=11):
    approval, applicability, projection = bundle[0], bundle[1], bundle[2]
    return [
        _Comment(start, serialize_approval_comment(APPROVAL_MARKER, serialize_approval_record(approval))),
        _Comment(start + 1, serialize_approval_comment(APPLICABILITY_MARKER, serialize_approval_applicability_result(applicability))),
        _Comment(start + 2, serialize_approval_comment(PROJECTION_MARKER, serialize_approved_execution_projection(projection))),
        _Comment(start + 3, serialize_merge_authorization_comment(record)),
    ]


def _transport(**changes):
    values = dict(
        status="accepted", reason="accepted-merge-admission-envelope",
        repository=REPO, issue_number=3463, comment_id=101, actor=OWNER,
        logical_trigger_id_or_none="issue-comment-trigger:" + "e" * 64,
        run_attempt=1,
        merge_admission_pr_number_or_none=PR_NUMBER,
        merge_admission_head_sha_or_none=HEAD,
        merge_admission_body_sha256_or_none=BODY_SHA,
        merge_admission_method_or_none="squash",
    )
    values.update(changes)
    return values


def _run(bundle=None, record=None, pr=None, comments=None, transport=None,
         evaluated_at=NOW, commit=None):
    bundle = bundle or _tauth._bundle()
    record = record or _authorized_record(bundle)
    pr = pr or _PR()
    comments = comments if comments is not None else _comments_for(bundle, record)
    client = _Client(_Repo(pr, comments, commit=commit))
    return evaluate_merge_dispatch_applicability(
        transport or _transport(), repository=REPO,
        github_client=client, evaluated_at=evaluated_at,
    )


# ---------------------------------------------------------------- tests
def test_all_verifiable_checks_pass_but_never_authorizes():
    receipt = _run()
    assert receipt["dispatch_checks_passed"] is True
    assert receipt["merge_authorized"] is False
    assert receipt["reason_codes"] == ["merge-proposal-evidence-undefined"]
    assert receipt["verified"] == [
        "transport-and-record", "approval-source-current",
        "approval-binding-linkage", "file-scope",
        "checks", "reviews", "lifecycle-admission",
    ]
    assert receipt["missing_interfaces"]
    assert receipt["canonical_applicability_evaluated"] is False
    lifecycle = receipt["lifecycle_mutation_authorization"]
    assert lifecycle is not None
    assert lifecycle["expected_source_head"] == HEAD
    assert lifecycle["authorized_mutations"] == ["merge"]
    assert lifecycle["state"] == "authorized"


def test_changed_head_blocked_at_admission_layer():
    receipt = _run(pr=_PR(head=_Ref("refs/heads/feat", "f" * 40)))
    assert receipt["dispatch_checks_passed"] is False
    assert "merge-dispatch-blocked-by-admission" in receipt["reason_codes"]
    assert "stale-head" in receipt["reason_codes"]


def test_expired_authorization_blocked():
    # The canonical producer forbids an authorization that outlives its
    # approval, so expiry is exercised at the authorization layer: both the
    # record and its approval are past expiry at evaluation time.
    bundle = _timed_bundle(
        decision_at="2026-07-26T14:10:00Z",
        expires_at="2026-07-26T14:45:00Z",
        eval_at="2026-07-26T14:20:00Z",
    )
    record = _authorized_record(
        bundle, decision_at="2026-07-26T14:30:00Z",
        expires_at="2026-07-26T14:44:00Z",
    )
    receipt = _run(bundle=bundle, record=record, evaluated_at="2026-07-26T15:00:00Z")
    assert receipt["dispatch_checks_passed"] is False
    assert "merge-dispatch-blocked-by-admission" in receipt["reason_codes"]
    assert "authorization.expired" in receipt["reason_codes"]


def test_missing_approval_artifacts_blocked():
    bundle = _tauth._bundle()
    record = _authorized_record(bundle)
    comments = [_Comment(11, serialize_merge_authorization_comment(record))]
    receipt = _run(bundle=bundle, record=record, comments=comments)
    assert receipt["dispatch_checks_passed"] is False
    assert "approval-source-not-current" in receipt["reason_codes"]
    assert "approval.absent" in receipt["reason_codes"]


def test_approval_id_mismatch_blocked():
    bundle = _tauth._bundle()
    other = _tauth._bundle(approval_expires="2026-07-26T17:00:00Z")
    record = _authorized_record(bundle)
    comments = _comments_for(other, record)
    receipt = _run(bundle=other, record=record, comments=comments)
    assert receipt["dispatch_checks_passed"] is False
    assert "approval-source-not-current" in receipt["reason_codes"]


def test_failed_check_blocked():
    commit = _Commit(runs=[_CheckRun("CI", "failure")])
    receipt = _run(commit=commit)
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["reason_codes"] == ["checks.changed"]


def test_success_status_cannot_mask_failing_check_run():
    commit = _Commit(runs=[_CheckRun("CI", "failure")],
                    statuses=[_Status("CI", "success")])
    receipt = _run(commit=commit)
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["reason_codes"] == ["checks.changed"]


def test_failing_status_cannot_be_masked_by_success_run():
    commit = _Commit(runs=[_CheckRun("CI", "success")],
                    statuses=[_Status("CI", "failure")])
    receipt = _run(commit=commit)
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["reason_codes"] == ["checks.changed"]


def test_pending_duplicate_means_not_success():
    commit = _Commit(runs=[_CheckRun("CI", "success")],
                    statuses=[_Status("CI", "pending")])
    receipt = _run(commit=commit)
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["reason_codes"] == ["checks.changed"]


def test_skipped_run_cannot_ride_success_status():
    commit = _Commit(runs=[_CheckRun("CI", "skipped")],
                    statuses=[_Status("CI", "success")])
    receipt = _run(commit=commit)
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["reason_codes"] == ["checks.changed"]


def test_neutral_run_cannot_ride_success_status():
    commit = _Commit(runs=[_CheckRun("CI", "success")],
                    statuses=[_Status("CI", "success")],
                    )
    # control: all-success still passes (neutral added below instead)
    assert _run(commit=commit)["dispatch_checks_passed"] is True
    mixed = _Commit(runs=[_CheckRun("CI", "neutral")],
                   statuses=[_Status("CI", "success")])
    receipt = _run(commit=mixed)
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["reason_codes"] == ["checks.changed"]


def test_missing_required_check_blocked():
    receipt = _run(commit=_Commit(runs=[]))
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["reason_codes"] == ["checks.missing"]


def test_blocking_review_blocked():
    pr = _PR(_reviews=[_Review("CHANGES_REQUESTED", HEAD)])
    receipt = _run(pr=pr)
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["reason_codes"] == ["review.changed"]


def test_dismissed_head_approval_blocked():
    pr = _PR(_reviews=[_Review("COMMENTED", HEAD)])
    receipt = _run(pr=pr)
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["reason_codes"] == ["review.changed"]


def test_draft_drift_blocked():
    receipt = _run(pr=_PR(draft=True))
    assert receipt["dispatch_checks_passed"] is False
    assert "merge-dispatch-blocked-by-admission" in receipt["reason_codes"]


def test_invalidated_record_blocks_replay():
    bundle = _tauth._bundle()
    record = _authorized_record(bundle)
    invalidated = _tauth.record_merge_authorization_decision(
        record, state=_tauth.MergeAuthorizationState.INVALIDATED,
        decision_id="invalidate", authorizer_id="repository-owner",
        decision_at="2026-07-26T15:00:00Z",
        reason_codes=("authorization.revoked",),
    )
    comments = _comments_for(bundle, invalidated)
    receipt = _run(bundle=bundle, record=invalidated, comments=comments)
    assert receipt["dispatch_checks_passed"] is False
    assert "merge-dispatch-blocked-by-admission" in receipt["reason_codes"]


def test_unauthorized_actor_blocked():
    receipt = _run(transport=_transport(actor="mallory"))
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["reason_codes"] == ["lifecycle.actor-not-owner"]


def test_scope_expansion_blocked():
    pr = _PR(_files=[_File(ALLOWED_FILE, FILE_SHA), _File("evil.py", "f" * 40)])
    receipt = _run(pr=pr)
    assert receipt["dispatch_checks_passed"] is False
    assert "contract.scope-changed" in receipt["reason_codes"]


def test_malformed_clock_fails_closed():
    receipt = _run(evaluated_at="not-a-timestamp")
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["reason_codes"] == ["evaluator-clock-malformed"]


def test_repeated_evaluation_is_idempotent():
    first = _run()
    second = _run()
    assert first["dispatch_checks_passed"] is True
    assert first["receipt_id"] == second["receipt_id"]
    assert first["reason_codes"] == second["reason_codes"]


class TestChangedScopeFingerprint:
    def test_deterministic_and_order_independent(self):
        left = changed_scope_fingerprint([("b.py", "a" * 40), ("a.py", "b" * 40)])
        right = changed_scope_fingerprint([("a.py", "b" * 40), ("b.py", "a" * 40)])
        assert left == right and len(left) == 64

    def test_sensitive_to_path_and_sha(self):
        base = changed_scope_fingerprint([("a.py", "b" * 40)])
        assert changed_scope_fingerprint([("a.py", "c" * 40)]) != base
        assert changed_scope_fingerprint([("z.py", "b" * 40)]) != base

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            changed_scope_fingerprint([])
