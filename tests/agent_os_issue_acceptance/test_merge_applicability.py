"""Tests for merge_applicability.py: dispatch-time applicability consumer.

Every authorization artifact is built through the canonical producers; the
fake GitHub surface is read-only. The consumer emits merge_authorized=true
only when every dispatch check passes AND the canonical evaluator returns
applicable for a typed MergeProposal; every negative case below must keep
merge_authorized false, and no case in this file performs a merge.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import replace
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.agent_os_issue_acceptance import (  # noqa: E402
    MergeCheckEvidence,
    MergeReviewEvidence,
    record_merge_authorization_decision,
)
from scripts.agent_os_issue_acceptance.merge_authorization_source import (  # noqa: E402
    serialize_merge_authorization_comment,
)
from scripts.agent_os_issue_acceptance.merge_authorization import (  # noqa: E402
    build_merge_authorization_candidate_from_pr,
    changed_scope_fingerprint,
    pr_metadata_fingerprint,
)
from scripts.agent_os_issue_acceptance.merge_applicability import (  # noqa: E402
    evaluate_merge_dispatch_applicability,
    _unresolved_review_threads,
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




ALLOWED_FILE = "scripts/agent_os_issue_acceptance/merge_authorization.py"


def _authorized_record(bundle, decision_at="2026-07-26T14:30:00Z",
                       expires_at="2026-07-26T15:30:00Z", **changes):
    scope = changed_scope_fingerprint([(ALLOWED_FILE, FILE_SHA)])
    values = dict(
        repository=REPO, pull_request_number=PR_NUMBER, head_sha=HEAD,
        base_branch="main", base_sha_or_evidence_id=BASE, draft=False,
        ready_for_review=True, proposed_merge_method="squash",
        changed_scope_fingerprint=scope,
        required_checks=(
            MergeCheckEvidence(
                context="CI", app_identity="github-actions",
                tested_sha=HEAD, evidence_id="", state="success"),
            MergeCheckEvidence(
                context="agent-os/authoritative-aggregate",
                app_identity="github-actions",
                tested_sha=HEAD, evidence_id="", state="success"),
        ),
        review_evidence=MergeReviewEvidence(
            blocking_review_present=False, unresolved_conversation_count=0,
            exact_head_reviewed=True),
        evidence_id="", pr_title=TITLE, pr_body=BODY,
        pr_metadata_sha256=pr_metadata_fingerprint(TITLE, BODY),
        closure_admissions=(),
    )
    values.update(changes)
    evidence = _tauth._pr(bundle, **values)
    candidate = build_merge_authorization_candidate_from_pr(
        evidence,
        authorizer_id=OWNER, decision_id="merge-request",
        decision_at=decision_at, expires_at=expires_at,
    )
    return record_merge_authorization_decision(
        candidate, state=_tauth.MergeAuthorizationState.AUTHORIZED,
        decision_id="authz-decision", authorizer_id=OWNER,
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
    def __init__(self, name, conclusion, app_slug="github-actions",
                 app_id=15368, run_id=100):
        self.name = name
        self.conclusion = conclusion
        self.app = type("App", (), {"slug": app_slug, "id": app_id})()
        self.id = run_id


class _Status:
    def __init__(self, context, state, creator="github-actions[bot]",
                 creator_id=41898282, status_id=100):
        self.context = context
        self.state = state
        self.id = status_id
        self.creator = type("Creator", (), {
            "login": creator, "id": creator_id
        })()


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
    def __init__(self, pr, comments, commit=None, include_aggregate=True):
        self.owner = _Owner(OWNER)
        self._pr = pr
        self._comments = comments
        self._commit = commit or _Commit(runs=[_CheckRun("CI", "success")])
        if include_aggregate:
            self._commit._statuses = [
                *_Commit(statuses=self._commit._statuses).get_statuses(),
                _Status("agent-os/authoritative-aggregate", "success"),
            ]

    def get_pull(self, number):
        assert number == PR_NUMBER
        return self._pr

    def get_issue(self, number):
        assert number == PR_NUMBER
        return _Issue(self._comments)

    def get_commit(self, sha):
        assert sha == self._pr.head.sha
        return self._commit


class _Requester:
    def __init__(self, pages=None):
        self.pages = pages if pages is not None else [[{"isResolved": True}]]
        self.calls = []

    def graphql_query(self, query, variables):
        self.calls.append(variables)
        index = 0 if variables["cursor"] is None else int(variables["cursor"])
        if index >= len(self.pages):
            raise ValueError("missing review-thread page")
        data = {
            "data": {"repository": {"pullRequest": {
                "reviewThreads": {
                    "nodes": self.pages[index],
                    "pageInfo": {
                        "hasNextPage": index < len(self.pages) - 1,
                        "endCursor": str(index + 1) if index < len(self.pages) - 1 else None,
                    },
                },
            }}},
        }
        return {}, data


class _Client:
    def __init__(self, repo, requester=None):
        self._repo = repo
        self.requester = requester or _Requester()

    def get_repo(self, name):
        assert name == REPO
        return self._repo


def _pending_for(record):
    pending = replace(
        record, authorization_revision="", revision_number=1,
        previous_revision=None, state=_tauth.MergeAuthorizationState.PENDING,
        decision_id="merge-request", reason_codes=(), details=(),
    )
    assert pending.authorization_revision == record.previous_revision
    return pending


def _comments_for(bundle, record, start=11):
    # Native 1.2 dispatch needs only the merge authorization chain;
    # planning approval/applicability/projection comments are not
    # consulted (#3734). `bundle` is accepted for call-site compatibility.
    return [
        _Comment(start, serialize_merge_authorization_comment(_pending_for(record))),
        _Comment(start + 1, serialize_merge_authorization_comment(record)),
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
    bundle = bundle
    record = record or _authorized_record(bundle)
    pr = pr or _PR()
    comments = comments if comments is not None else _comments_for(bundle, record)
    client = _Client(_Repo(pr, comments, commit=commit))
    return evaluate_merge_dispatch_applicability(
        transport or _transport(), repository=REPO,
        github_client=client, evaluated_at=evaluated_at,
    )


# ---------------------------------------------------------------- tests
def test_all_verifiable_checks_pass_authorizes_via_canonical_applicability():
    receipt = _run()
    assert receipt["dispatch_checks_passed"] is True
    assert receipt["status"] == "awaiting-human-attestation"
    assert receipt["merge_authorized"] is False
    assert receipt["reason_codes"] == ["human-origin-attestation-required"]
    assert receipt["verified"] == [
        "transport-and-record", "native-merge-record", "file-scope",
        "checks", "reviews", "review-threads", "lifecycle-admission",
        "canonical-applicability",
    ]
    assert receipt["missing_interfaces"] == []
    assert receipt["canonical_applicability_evaluated"] is True
    canonical = receipt["canonical_applicability_result"]
    assert canonical is not None
    assert canonical["status"] == "applicable"
    assert canonical["merge_authorized"] is True
    assert canonical["changed_bindings"] == []
    assert canonical["reason_codes"] == []
    assert canonical["authorization_id"] == receipt["authorization_id"]
    assert receipt["expected_head_sha"] == HEAD
    assert receipt["authorization_expires_at"] is not None
    lifecycle = receipt["lifecycle_mutation_authorization"]
    assert lifecycle is not None
    assert lifecycle["expected_source_head"] == HEAD
    assert lifecycle["authorized_mutations"] == ["merge"]
    assert lifecycle["state"] == "authorized"


def test_wrong_merge_method_blocked():
    receipt = _run(transport=_transport(merge_admission_method_or_none="merge"))
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["merge_authorized"] is False
    assert "merge-dispatch-blocked-by-admission" in receipt["reason_codes"]


def test_base_not_main_blocked():
    receipt = _run(pr=_PR(base=_Ref("dev", BASE)))
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["merge_authorized"] is False
    assert "merge-dispatch-blocked-by-admission" in receipt["reason_codes"]
    assert "base-not-main" in receipt["reason_codes"]


def test_non_mergeable_protected_target_blocked():
    receipt = _run(pr=_PR(mergeable=False))
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["merge_authorized"] is False
    assert "pr-mergeability-not-clean" in receipt["reason_codes"]


class _BrokenClient:
    def get_repo(self, name):
        raise RuntimeError("provider unavailable")


def test_provider_error_fails_closed():
    receipt = evaluate_merge_dispatch_applicability(
        _transport(), repository=REPO, github_client=_BrokenClient(),
        evaluated_at=NOW,
    )
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["merge_authorized"] is False
    # _receipt sorts reason codes.
    assert receipt["reason_codes"] == [
        "canonical-github-evidence-unavailable",
        "merge-dispatch-blocked-by-admission",
    ]


def test_unauthorized_closing_reference_body_change_blocked():
    # A record built for the clean body cannot be reused after the live
    # body gains an unauthorized closing reference: the admission layer
    # already blocks on the metadata binding drift, before any canonical
    # step. The canonical evaluator independently refuses the same drift
    # (see test_merge_proposal.test_unauthorized_closing_reference_and_dual_claim_block).
    bundle = None
    body = "Fixes #999"
    receipt = _run(
        bundle=bundle, pr=_PR(body=body),
        transport=_transport(
            merge_admission_body_sha256_or_none=sha256(body.encode("utf-8")).hexdigest()
        ),
    )
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["merge_authorized"] is False
    assert "merge-dispatch-blocked-by-admission" in receipt["reason_codes"]
    assert "pull-request.metadata-changed" in receipt["reason_codes"]


def test_changed_head_blocked_at_admission_layer():
    receipt = _run(pr=_PR(head=_Ref("refs/heads/feat", "f" * 40)))
    assert receipt["dispatch_checks_passed"] is False
    assert "merge-dispatch-blocked-by-admission" in receipt["reason_codes"]
    assert "stale-head" in receipt["reason_codes"]


def test_expired_authorization_blocked():
    # The canonical producer forbids an authorization that outlives its
    # approval, so expiry is exercised at the authorization layer: both the
    # record and its approval are past expiry at evaluation time.
    bundle = None  # native 1.2: record expiry alone governs
    record = _authorized_record(
        bundle, decision_at="2026-07-26T14:30:00Z",
        expires_at="2026-07-26T14:44:00Z",
    )
    receipt = _run(bundle=bundle, record=record, evaluated_at="2026-07-26T15:00:00Z")
    assert receipt["dispatch_checks_passed"] is False
    assert "merge-dispatch-blocked-by-admission" in receipt["reason_codes"]
    assert "authorization.expired" in receipt["reason_codes"]


def test_planning_approval_artifacts_are_not_required_for_v2():
    bundle = None
    record = _authorized_record(bundle)
    comments = [
        _Comment(10, serialize_merge_authorization_comment(_pending_for(record))),
        _Comment(11, serialize_merge_authorization_comment(record)),
    ]
    receipt = _run(bundle=bundle, record=record, comments=comments)
    assert receipt["dispatch_checks_passed"] is True
    assert receipt["status"] == "awaiting-human-attestation"
    assert receipt["merge_authorized"] is False
    assert receipt["reason_codes"] == ["human-origin-attestation-required"]


def test_foreign_planning_approval_is_not_merge_authority():
    bundle = None
    other = None
    record = _authorized_record(bundle)
    comments = _comments_for(other, record)
    receipt = _run(bundle=other, record=record, comments=comments)
    assert receipt["dispatch_checks_passed"] is True
    assert receipt["status"] == "awaiting-human-attestation"
    assert receipt["merge_authorized"] is False


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


def test_missing_head_approval_not_blocking():
    # #3463 reviewer correction: APPROVED-at-head state is recorded,
    # not gated. A COMMENTED-only review set (no APPROVED review at the
    # head) must not block dispatch when no review is blocking and no
    # thread is unresolved; owner approval is the execution-time card
    # tap, not a review record.
    pr = _PR(_reviews=[_Review("COMMENTED", HEAD)])
    receipt = _run(pr=pr)
    assert receipt["dispatch_checks_passed"] is True
    assert receipt["status"] == "awaiting-human-attestation"
    canonical = receipt["canonical_applicability_result"]
    assert canonical["status"] == "applicable"
    assert canonical["changed_bindings"] == []
    assert canonical["reason_codes"] == []


def test_draft_drift_blocked():
    receipt = _run(pr=_PR(draft=True))
    assert receipt["dispatch_checks_passed"] is False
    assert "merge-dispatch-blocked-by-admission" in receipt["reason_codes"]


def test_invalidated_record_blocks_replay():
    bundle = None
    record = _authorized_record(bundle)
    invalidated = _tauth.record_merge_authorization_decision(
        record, state=_tauth.MergeAuthorizationState.INVALIDATED,
        decision_id="invalidate", authorizer_id="repository-owner",
        decision_at="2026-07-26T15:00:00Z",
        reason_codes=("authorization.revoked",),
    )
    # Include the pending and authorized predecessors, then the terminal
    # invalidation. A terminal record cannot stand alone as a valid chain.
    comments = _comments_for(bundle, record)
    comments.append(_Comment(16, serialize_merge_authorization_comment(invalidated)))
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
    # The new file is outside the allowlist, so the allowlist reason must
    # appear too (Loop 8, mutmut m220/221).
    assert "contract.allowlist-changed" in receipt["reason_codes"]


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



# Security regression checks: absence of positive review-thread evidence is
# never equivalent to zero unresolved threads.
def test_missing_graphql_review_thread_capability_fails_closed():
    class _RestOnlyClient:
        def __init__(self, repo):
            self._repo = repo

        def get_repo(self, name):
            return self._repo

    bundle = None
    record = _authorized_record(bundle)
    client = _RestOnlyClient(_Repo(_PR(), _comments_for(bundle, record)))
    receipt = evaluate_merge_dispatch_applicability(
        _transport(), repository=REPO, github_client=client, evaluated_at=NOW,
    )
    assert receipt["merge_authorized"] is False
    assert receipt["reason_codes"] == ["review.threads-unverifiable"]


def test_unresolved_thread_blocks_even_with_approved_head():
    bundle = None
    record = _authorized_record(bundle)
    client = _Client(
        _Repo(_PR(), _comments_for(bundle, record)),
        requester=_Requester([[{"isResolved": False}]]),
    )
    receipt = evaluate_merge_dispatch_applicability(
        _transport(), repository=REPO, github_client=client, evaluated_at=NOW,
    )
    assert receipt["merge_authorized"] is False
    assert receipt["reason_codes"] == ["review.unresolved"]


def test_review_threads_use_every_page():
    requester = _Requester([
        [{"isResolved": True}],
        [{"isResolved": False}, {"isResolved": True}],
    ])
    client = _Client(_Repo(_PR(), []), requester=requester)
    assert _unresolved_review_threads(client, REPO, PR_NUMBER) == 1
    assert [call["cursor"] for call in requester.calls] == [None, "1"]


@pytest.mark.parametrize("invalid_page", [
    [{"isResolved": "false"}],
    [None],
    [{"unexpected": True}],
])
def test_malformed_review_thread_page_fails_closed(invalid_page):
    client = _Client(_Repo(_PR(), []), requester=_Requester([invalid_page]))
    with pytest.raises(ValueError):
        _unresolved_review_threads(client, REPO, PR_NUMBER)


def test_forbidden_path_rechecked_even_when_authorized_fingerprint_matches():
    bundle = None
    original = _authorized_record(bundle)
    # The record is content-addressed and trusted, but its own forbidden
    # contract was not enforced at admission time. Current scope did not drift.
    forbidden_binding = replace(original.binding, forbidden_paths=("scripts/*",))
    pending = replace(
        _pending_for(original), binding=forbidden_binding,
        authorization_id="", authorization_revision="",
    )
    record = record_merge_authorization_decision(
        pending, state=_tauth.MergeAuthorizationState.AUTHORIZED,
        decision_id="authz-decision", authorizer_id=OWNER,
        decision_at=pending.decision_at,
    )
    comments = _comments_for(bundle, record)
    client = _Client(_Repo(_PR(), comments))
    receipt = evaluate_merge_dispatch_applicability(
        _transport(), repository=REPO, github_client=client, evaluated_at=NOW,
    )
    assert receipt["merge_authorized"] is False
    assert "contract.forbidden-paths-changed" in receipt["reason_codes"]


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


# Native schema 1.2 adversarial checks: the old source only checked names.
def test_correct_context_from_wrong_app_is_not_authority():
    receipt = _run(commit=_Commit(
        runs=[_CheckRun("CI", "success", app_slug="untrusted-app")]))
    assert receipt["merge_authorized"] is False
    assert "checks.publisher-unverifiable" in receipt["reason_codes"]


def test_forged_aggregate_commit_status_is_not_authority():
    bundle = None
    record = _authorized_record(bundle)
    commit = _Commit(
        runs=[_CheckRun("CI", "success")],
        statuses=[_Status("agent-os/authoritative-aggregate", "success",
                          creator="mallory", creator_id=999)],
    )
    client = _Client(_Repo(_PR(), _comments_for(bundle, record),
                           commit=commit, include_aggregate=False))
    receipt = evaluate_merge_dispatch_applicability(
        _transport(), repository=REPO, github_client=client, evaluated_at=NOW,
    )
    assert receipt["merge_authorized"] is False
    assert "checks.publisher-unverifiable" in receipt["reason_codes"]


def test_missing_live_aggregate_blocks():
    bundle = None
    record = _authorized_record(bundle)
    client = _Client(_Repo(
        _PR(), _comments_for(bundle, record),
        commit=_Commit(runs=[_CheckRun("CI", "success")]),
        include_aggregate=False,
    ))
    receipt = evaluate_merge_dispatch_applicability(
        _transport(), repository=REPO, github_client=client, evaluated_at=NOW,
    )
    assert receipt["merge_authorized"] is False
    assert "checks.missing" in receipt["reason_codes"]


def test_latest_commit_status_overrides_old_failure():
    from scripts.agent_os_issue_acceptance.merge_applicability import _latest_evidence
    commit = _Commit(statuses=[
        _Status("agent-os/authoritative-aggregate", "success", status_id=3),
        _Status("agent-os/authoritative-aggregate", "failure", status_id=2),
    ])
    assert _latest_evidence(commit)["agent-os/authoritative-aggregate"] == (
        "success", "github-actions", True,
    )


def test_latest_commit_status_failure_overrides_old_success():
    from scripts.agent_os_issue_acceptance.merge_applicability import _latest_evidence
    commit = _Commit(statuses=[
        _Status("agent-os/authoritative-aggregate", "failure", status_id=3),
        _Status("agent-os/authoritative-aggregate", "success", status_id=2),
    ])
    assert _latest_evidence(commit)["agent-os/authoritative-aggregate"][0] == "failure"


def test_extra_authorized_allowlist_paths_are_not_drift():
    from dataclasses import replace
    bundle = None
    original = _authorized_record(bundle)
    binding = replace(original.binding, allowed_files=(
        ALLOWED_FILE, "scripts/also-authorized.py",
    ))
    pending = replace(
        _pending_for(original), binding=binding,
        authorization_id="", authorization_revision="",
    )
    record = record_merge_authorization_decision(
        pending, state=_tauth.MergeAuthorizationState.AUTHORIZED,
        decision_id="authz-decision", authorizer_id=OWNER,
        decision_at=pending.decision_at,
    )
    receipt = _run(bundle=bundle, record=record)
    assert receipt["status"] == "awaiting-human-attestation"
    assert receipt["merge_authorized"] is False
    assert receipt["reason_codes"] == ["human-origin-attestation-required"]


def test_missing_publisher_fails_closed():
    receipt = _run(commit=_Commit(
        runs=[_CheckRun("CI", "success", app_slug=None)]))
    assert receipt["merge_authorized"] is False
    assert "checks.publisher-unverifiable" in receipt["reason_codes"]


# ---------------------------------------------------------------------------
# 2026-10-29 finish campaign (Workstream B2): duplicate check-run ordering.
#
# The pre-existing file tested latest *commit-status* ordering and single
# check-run vs status combinations, but never multiple check runs sharing
# one context. _latest_evidence selects by check-run ID (max wins, ties or
# missing IDs collapse to "unknown"), never by list position. Each case
# below is run in both API iteration orders where order could matter, so a
# last-element-wins mutant is detected by the reversed-order case.
# ---------------------------------------------------------------------------


def _duplicate_check_runs(runs):
    from scripts.agent_os_issue_acceptance.merge_applicability import (
        _latest_evidence,
    )

    return _latest_evidence(_Commit(runs=runs))


@pytest.mark.parametrize(
    "runs",
    [
        [_CheckRun("CI", "failure", run_id=10), _CheckRun("CI", "success", run_id=20)],
        [_CheckRun("CI", "success", run_id=20), _CheckRun("CI", "failure", run_id=10)],
    ],
)
def test_duplicate_check_runs_newer_success_wins_regardless_of_order(runs):
    assert _duplicate_check_runs(runs)["CI"] == ("success", "github-actions", False)


@pytest.mark.parametrize(
    "runs",
    [
        [_CheckRun("CI", "success", run_id=10), _CheckRun("CI", "failure", run_id=20)],
        [_CheckRun("CI", "failure", run_id=20), _CheckRun("CI", "success", run_id=10)],
    ],
)
def test_duplicate_check_runs_newer_failure_wins_regardless_of_order(runs):
    assert _duplicate_check_runs(runs)["CI"] == ("failure", "github-actions", False)


def test_duplicate_check_runs_skipped_and_pending_do_not_mask_latest():
    assert _duplicate_check_runs(
        [_CheckRun("CI", "skipped", run_id=10), _CheckRun("CI", "success", run_id=20)]
    )["CI"][0] == "success"
    assert _duplicate_check_runs(
        [_CheckRun("CI", "success", run_id=10), _CheckRun("CI", "skipped", run_id=20)]
    )["CI"][0] == "skipped"
    assert _duplicate_check_runs(
        [_CheckRun("CI", "success", run_id=10), _CheckRun("CI", None, run_id=20)]
    )["CI"][0] == "pending"


def test_duplicate_check_runs_missing_or_equal_ids_are_unknown_not_success():
    assert _duplicate_check_runs(
        [_CheckRun("CI", "success", run_id=None), _CheckRun("CI", "failure", run_id=None)]
    )["CI"][0] == "unknown"
    assert _duplicate_check_runs(
        [_CheckRun("CI", "success", run_id=20), _CheckRun("CI", "failure", run_id=20)]
    )["CI"][0] == "unknown"
    assert _duplicate_check_runs(
        [_CheckRun("CI", "success", run_id=None), _CheckRun("CI", "failure", run_id=20)]
    )["CI"][0] == "unknown"


def test_duplicate_check_runs_newer_success_from_other_publisher_is_recorded():
    result = _duplicate_check_runs(
        [
            _CheckRun("CI", "failure", run_id=10),
            _CheckRun("CI", "success", app_slug="other-app", app_id=999, run_id=20),
        ]
    )["CI"]
    assert result == ("success", "other-app", False)


def test_duplicate_check_runs_run_status_publisher_disagreement_is_unknown():
    from scripts.agent_os_issue_acceptance.merge_applicability import (
        _latest_evidence,
    )

    commit = _Commit(
        runs=[_CheckRun("CI", "success", run_id=20)],
        statuses=[_Status("CI", "success", creator="other[bot]", creator_id=1)],
    )
    assert _latest_evidence(commit)["CI"][0] == "unknown"


@pytest.mark.parametrize(
    "runs",
    [
        [_CheckRun("CI", "failure", run_id=10), _CheckRun("CI", "success", run_id=20)],
        [_CheckRun("CI", "success", run_id=20), _CheckRun("CI", "failure", run_id=10)],
    ],
)
def test_duplicate_check_runs_downstream_dispatch_uses_latest_success(runs):
    receipt = _run(commit=_Commit(runs=runs))
    assert receipt["dispatch_checks_passed"] is True
    assert receipt["status"] == "awaiting-human-attestation"
    assert receipt["merge_authorized"] is False
    assert receipt["reason_codes"] == ["human-origin-attestation-required"]


def test_duplicate_check_runs_downstream_dispatch_blocks_latest_failure():
    receipt = _run(
        commit=_Commit(
            runs=[
                _CheckRun("CI", "success", run_id=10),
                _CheckRun("CI", "failure", run_id=20),
            ]
        )
    )
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["merge_authorized"] is False
    assert "checks.changed" in receipt["reason_codes"]

# ---------------------------------------------------------------------------
# Loop 8 (2026-11-05): lane-03 mutation-survivor regression tests.
#
# Mutmut 3.8.1 over the whole merge_applicability module (1218 mutants,
# Loop 1 selection: 753 killed / 354 survived / 111 no-tests) left survivors
# whose behavior change no existing test catches. The tests below pin the
# exact behaviors those survivors change; each test names the mutant family
# it kills in its docstring. No test in this file performs a merge.
# ---------------------------------------------------------------------------

_TRIGGER_ID = "issue-comment-trigger:" + "e" * 64

_RECEIPT_KEYS = {
    "admission_receipt", "approval_id", "approval_revision",
    "authorization_expires_at", "authorization_id", "authorization_revision",
    "canonical_applicability_evaluated", "canonical_applicability_result",
    "dispatch_checks_passed", "evaluated_at", "expected_head_sha",
    "expected_method", "external_system_write_authorized",
    "human_origin_attestation", "issue_closure_authorized",
    "lifecycle_mutation_authorization", "lifecycle_snapshot_notes",
    "logical_trigger_id", "merge_authorized", "missing_interfaces",
    "observed_base_sha", "observed_head_sha", "operation", "pr_number",
    "production_authorized", "reason_codes", "receipt_id", "repository",
    "schema_version", "side_effects_performed", "status", "verified",
    "workflow_authorized",
}

_AUTHORIZATION_FLAGS = (
    "issue_closure_authorized", "workflow_authorized", "production_authorized",
    "external_system_write_authorized", "side_effects_performed",
)


def _recomputed_receipt_id(receipt):
    """Recompute receipt_id exactly as _receipt does (mutmut _receipt/m83-97)."""
    payload = {key: value for key, value in receipt.items() if key != "receipt_id"}
    ident = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return "merge-dispatch-applicability:" + ident


_MISSING = object()  # sentinel: attribute absent from the fake object


def _creator(login=_MISSING, user_id=_MISSING):
    attrs = {}
    if login is not _MISSING:
        attrs["login"] = login
    if user_id is not _MISSING:
        attrs["id"] = user_id
    return type("Creator", (), attrs)()


@pytest.mark.parametrize(
    "creator,expected",
    [
        (None, None),
        (_creator("github-actions[bot]", 41898282), "github-actions"),
        (_creator("github-actions[bot]", 1), "github-actions[bot]"),
        (_creator("someone", 41898282), "someone"),
        (_creator("mallory", 999), "mallory"),
        (_creator(123, 999), None),
        (_creator("", 999), None),
        (_creator("mallory", True), None),
        (_creator("mallory", "999"), None),
        (_creator("mallory", 0), None),
        (_creator("mallory", 1), "mallory"),
        (_creator("mallory", -5), None),
        (_creator(user_id=999), None),
        (_creator(login="mallory"), None),
    ],
)
def test_status_identity_matrix(creator, expected):
    """Pin _status_identity incl. the github-actions[bot] AND-check (mutmut_26).

    Kills _status_identity survivors 6, 15, 23, 26, 33, 34, 35, 36, 37, 38,
    39, 40: missing-attribute defaults, the bot login/id AND, the login and
    id type guards, and the id 0/1 boundaries.
    """
    from scripts.agent_os_issue_acceptance.merge_applicability import _status_identity

    assert _status_identity(SimpleNamespace(creator=creator)) == expected


def test_status_identity_missing_creator_attribute_is_unverified():
    """A status without a creator attribute is unverified (mutmut_6)."""
    from scripts.agent_os_issue_acceptance.merge_applicability import _status_identity

    assert _status_identity(type("Status", (), {})()) is None


def _app(slug=_MISSING, app_id=_MISSING):
    attrs = {}
    if slug is not _MISSING:
        attrs["slug"] = slug
    if app_id is not _MISSING:
        attrs["id"] = app_id
    return type("App", (), attrs)()


@pytest.mark.parametrize(
    "app,expected",
    [
        (None, None),
        (_app("github-actions", 15368), "github-actions"),
        (_app("github-actions", 999), None),
        (_app("other-app", 999), "other-app"),
        (_app(123, 1), None),
        (_app("x", True), None),
        (_app("x", 0), None),
        (_app("x", 1), "x"),
        (_app(app_id=999), None),
        (_app(slug="x"), None),
    ],
)
def test_check_run_identity_matrix(app, expected):
    """Pin _check_run_identity incl. the github-actions app-id guard (mutmut_41/42).

    Kills _check_run_identity survivors 6, 16, 27, 31, 34, 35, 37, 38, 41, 42:
    missing-attribute defaults, the slug type guard, the app_id bool guard,
    the id 0/1 boundaries, and the impersonation guard.
    """
    from scripts.agent_os_issue_acceptance.merge_applicability import _check_run_identity

    assert _check_run_identity(SimpleNamespace(app=app)) == expected


def test_check_run_identity_missing_app_attribute_is_unverified():
    """A run without an app attribute is unverified (mutmut_6)."""
    from scripts.agent_os_issue_acceptance.merge_applicability import _check_run_identity

    assert _check_run_identity(type("Run", (), {})()) is None


def test_success_receipt_pins_full_contract():
    """Pin every field the success receipt emits (mutmut _receipt/*).

    Kills all 63 _receipt survivors on the success path (key renames, value
    mutants, default-arg mutants, False->True flips, receipt_id hash mutants)
    plus evaluate survivors 25, 26, 76, 77, 82, 83, 89, 90, 91, 127, 159,
    163, 351, 373, 393, 398, 400, 508, 509, 510, 511, whose base_kwargs /
    lifecycle / canonical fields feed this receipt.
    """
    record = _authorized_record(None)
    receipt = _run()
    assert receipt["dispatch_checks_passed"] is True
    assert receipt["status"] == "awaiting-human-attestation"
    assert receipt["merge_authorized"] is False
    assert receipt["reason_codes"] == ["human-origin-attestation-required"]
    assert receipt["verified"] == [
        "transport-and-record", "native-merge-record", "file-scope",
        "checks", "reviews", "review-threads", "lifecycle-admission",
        "canonical-applicability",
    ]
    assert receipt["missing_interfaces"] == []
    assert receipt["schema_version"] == "1.0"
    assert receipt["operation"] == "merge-dispatch-applicability"
    assert receipt["repository"] == REPO
    assert receipt["pr_number"] == PR_NUMBER
    assert receipt["logical_trigger_id"] == _TRIGGER_ID
    assert receipt["expected_head_sha"] == HEAD
    assert receipt["expected_method"] == "squash"
    assert receipt["observed_head_sha"] == HEAD
    assert receipt["observed_base_sha"] == BASE
    assert receipt["evaluated_at"] == NOW
    assert receipt["authorization_id"] == record.authorization_id
    assert receipt["authorization_revision"] == record.authorization_revision
    assert receipt["authorization_expires_at"] == "2026-07-26T15:30:00Z"
    assert receipt["approval_id"] is None
    assert receipt["approval_revision"] is None
    assert receipt["admission_receipt"] is not None
    assert receipt["admission_receipt"]["operation"] == "merge-admit"
    assert receipt["lifecycle_snapshot_notes"] == [
        "unresolved_threads=0: verified through complete GitHub GraphQL "
        "review-thread readback."
    ]
    assert receipt["canonical_applicability_evaluated"] is True
    canonical = receipt["canonical_applicability_result"]
    assert set(canonical) == {
        "status", "authorization_id", "authorization_revision",
        "current_pull_request_evidence_id", "changed_bindings",
        "reason_codes", "merge_authorized",
    }
    assert canonical["status"] == "applicable"
    assert canonical["merge_authorized"] is True
    assert canonical["changed_bindings"] == []
    assert canonical["reason_codes"] == []
    assert canonical["authorization_id"] == record.authorization_id
    assert canonical["authorization_revision"] == record.authorization_revision
    assert canonical["current_pull_request_evidence_id"].startswith(
        "pull-request-merge-evidence:"
    )
    # Golden hash: exact_head_reviewed is hashed into the evidence id, so
    # pinning the exact value catches an APPROVED-at-head misread (Loop 8,
    # mutmut m295/296/297/298/300). The id is deterministic for these
    # fixtures; a canonical evidence-schema change must update it.
    assert canonical["current_pull_request_evidence_id"] == (
        "pull-request-merge-evidence:"
        "2d379415919679eae7b28e4a1a60e737400e2e0b34ad58db49d68be5a6c8b52e"
    )
    attestation = receipt["human_origin_attestation"]
    assert attestation["binding"] == {
        "repository": REPO,
        "pr_number": PR_NUMBER,
        "head_sha": HEAD,
        "base_branch": "main",
        "base_sha": BASE,
        "merge_method": "squash",
        "authorization_id": record.authorization_id,
        "authorization_revision": record.authorization_revision,
        "changed_scope_fingerprint": record.binding.changed_scope_fingerprint,
    }
    lifecycle = receipt["lifecycle_mutation_authorization"]
    assert lifecycle["expected_source_head"] == HEAD
    assert lifecycle["expected_base_head"] == BASE
    assert lifecycle["expected_pr_state"] == "ready"
    assert lifecycle["expected_merged"] is False
    assert lifecycle["expected_review_state"] == "clear"
    assert lifecycle["expected_unresolved_threads"] == 0
    assert lifecycle["state"] == "authorized"
    assert lifecycle["authorized_mutations"] == ["merge"]
    assert lifecycle["authorizer_id"] == OWNER
    assert lifecycle["decision_id"] == record.decision_id
    assert lifecycle["repository"] == REPO
    assert lifecycle["pull_request_number"] == PR_NUMBER
    assert lifecycle["observed_at_revision"] == HEAD
    for flag in _AUTHORIZATION_FLAGS:
        assert receipt[flag] is False
    assert set(receipt) == _RECEIPT_KEYS
    assert receipt["receipt_id"] == _recomputed_receipt_id(receipt)


def test_no_approval_at_head_pins_evidence_id():
    """No APPROVED review at head is recorded truthfully (mutmut m288/294).

    exact_head_reviewed does not gate admission (#3463), but it is hashed
    into the canonical evidence id, so a mutant that claims an approval
    existed must change the pinned hash.
    """
    receipt = _run(pr=_PR(_reviews=[]))
    assert receipt["dispatch_checks_passed"] is True
    assert receipt["status"] == "awaiting-human-attestation"
    canonical = receipt["canonical_applicability_result"]
    assert canonical["status"] == "applicable"
    assert canonical["current_pull_request_evidence_id"] == (
        "pull-request-merge-evidence:"
        "77464e7cc3ce8fc001955a6c9fdb72cdf4f01bb9c2ba551f6caa8f2caa072721"
    )


def test_stale_approval_at_other_commit_pins_evidence_id():
    """An APPROVED review at a stale commit is not approval at head (mutmut m294).

    The `and` in the APPROVED-at-head condition matters: an APPROVED review
    whose commit is not the head must leave exact_head_reviewed False, so
    the evidence id must equal the no-approval hash, not the success hash.
    """
    receipt = _run(pr=_PR(_reviews=[_Review("APPROVED", "d" * 40)]))
    assert receipt["dispatch_checks_passed"] is True
    assert receipt["status"] == "awaiting-human-attestation"
    canonical = receipt["canonical_applicability_result"]
    assert canonical["status"] == "applicable"
    assert canonical["current_pull_request_evidence_id"] == (
        "pull-request-merge-evidence:"
        "77464e7cc3ce8fc001955a6c9fdb72cdf4f01bb9c2ba551f6caa8f2caa072721"
    )


def test_blocked_receipt_pins_fail_closed_defaults():
    """Pin the fail-closed defaults on the blocked path (mutmut _receipt/*).

    Kills the _receipt default-arg and flag mutants on the blocked path
    (status "blocked", empty verified/missing_interfaces/notes, the five
    authorization flags False, canonical_applicability_evaluated False)
    plus the key-set and receipt_id mutants.
    """
    receipt = _run(evaluated_at="not-a-timestamp")
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["status"] == "blocked"
    assert receipt["merge_authorized"] is False
    assert receipt["reason_codes"] == ["evaluator-clock-malformed"]
    assert receipt["verified"] == []
    assert receipt["missing_interfaces"] == []
    assert receipt["lifecycle_snapshot_notes"] == []
    assert receipt["lifecycle_mutation_authorization"] is None
    assert receipt["canonical_applicability_evaluated"] is False
    assert receipt["canonical_applicability_result"] is None
    assert receipt["human_origin_attestation"]["binding"] is None
    assert receipt["admission_receipt"] is None
    assert receipt["pr_number"] is None
    assert receipt["logical_trigger_id"] is None
    assert receipt["authorization_id"] is None
    assert receipt["authorization_revision"] is None
    assert receipt["approval_id"] is None
    assert receipt["approval_revision"] is None
    assert receipt["expected_head_sha"] is None
    assert receipt["expected_method"] is None
    assert receipt["observed_head_sha"] is None
    assert receipt["observed_base_sha"] is None
    assert receipt["authorization_expires_at"] is None
    assert receipt["repository"] == REPO
    assert receipt["evaluated_at"] == "not-a-timestamp"
    assert receipt["schema_version"] == "1.0"
    assert receipt["operation"] == "merge-dispatch-applicability"
    for flag in _AUTHORIZATION_FLAGS:
        assert receipt[flag] is False
    assert set(receipt) == _RECEIPT_KEYS
    assert receipt["receipt_id"] == _recomputed_receipt_id(receipt)


# --- _latest_evidence regression tests -------------------------------------


def test_latest_evidence_reversed_order_statuses_pick_latest_run():
    """Newest-first ordering is by id, not list position (mutmut m90/91/95-99/102).

    The existing ordering tests list statuses newest-first, so a mutant that
    always treats the status id as None survives them; a reversed list kills
    it: the id-5 success must win over the id-1 pending.
    """
    from scripts.agent_os_issue_acceptance.merge_applicability import _latest_evidence

    commit = _Commit(
        statuses=[
            _Status("CI", "pending", status_id=1),
            _Status("CI", "success", status_id=5),
        ],
    )
    assert _latest_evidence(commit)["CI"] == ("success", "github-actions", True)


def test_latest_evidence_unidentified_status_pairs():
    """Unidentified statuses cannot outrank identified ones (mutmut m126-128/134/135/137-139).

    [None, 5] must be unknown (an identified status after an unidentified
    one cannot be compared); [5, None] keeps the identified success; [None,
    None] keeps the first entry.
    """
    from scripts.agent_os_issue_acceptance.merge_applicability import _latest_evidence

    assert _latest_evidence(
        _Commit(statuses=[
            _Status("CI", "failure", status_id=None),
            _Status("CI", "success", status_id=5),
        ])
    )["CI"] == ("unknown", None, True)
    assert _latest_evidence(
        _Commit(statuses=[
            _Status("CI", "success", status_id=5),
            _Status("CI", "failure", status_id=None),
        ])
    )["CI"] == ("success", "github-actions", True)
    assert _latest_evidence(
        _Commit(statuses=[
            _Status("CI", "failure", status_id=None),
            _Status("CI", "success", status_id=None),
        ])
    )["CI"] == ("failure", "github-actions", True)


def test_latest_evidence_equal_status_ids_keep_first():
    """Equal ids keep the first status, not the last (mutmut m129)."""
    from scripts.agent_os_issue_acceptance.merge_applicability import _latest_evidence

    assert _latest_evidence(
        _Commit(statuses=[
            _Status("CI", "success", status_id=5),
            _Status("CI", "failure", status_id=5),
        ])
    )["CI"] == ("success", "github-actions", True)


def test_latest_evidence_run_id_boundaries():
    """Run id 0 is unidentified and id 1 is the smallest real id (mutmut m31/32)."""
    from scripts.agent_os_issue_acceptance.merge_applicability import _latest_evidence

    assert _latest_evidence(
        _Commit(runs=[
            _CheckRun("CI", "failure", run_id=0),
            _CheckRun("CI", "success", run_id=1),
        ])
    )["CI"] == ("unknown", None, False)
    assert _latest_evidence(
        _Commit(runs=[
            _CheckRun("CI", "success", run_id=1),
            _CheckRun("CI", "failure", run_id=2),
        ])
    )["CI"] == ("failure", "github-actions", False)


def test_latest_evidence_status_id_boundaries():
    """Status id 0 is unidentified and id 1 is the smallest real id (mutmut m104/105)."""
    from scripts.agent_os_issue_acceptance.merge_applicability import _latest_evidence

    assert _latest_evidence(
        _Commit(statuses=[
            _Status("CI", "failure", status_id=0),
            _Status("CI", "success", status_id=1),
        ])
    )["CI"] == ("unknown", None, True)
    assert _latest_evidence(
        _Commit(statuses=[
            _Status("CI", "success", status_id=1),
            _Status("CI", "failure", status_id=2),
        ])
    )["CI"] == ("failure", "github-actions", True)


def test_latest_evidence_non_int_ids_are_unknown():
    """Non-int ids are unidentified, never ordered (mutmut m27/100/101/103)."""
    from scripts.agent_os_issue_acceptance.merge_applicability import _latest_evidence

    assert _latest_evidence(
        _Commit(runs=[
            _CheckRun("CI", "failure", run_id="abc"),
            _CheckRun("CI", "success", run_id=5),
        ])
    )["CI"] == ("unknown", None, False)
    assert _latest_evidence(
        _Commit(statuses=[
            _Status("CI", "failure", status_id="abc"),
            _Status("CI", "success", status_id=5),
        ])
    )["CI"] == ("unknown", None, True)
    assert _latest_evidence(
        _Commit(statuses=[
            _Status("CI", "failure", status_id=1.5),
            _Status("CI", "success", status_id=5),
        ])
    )["CI"] == ("unknown", None, True)


def test_latest_evidence_malformed_contexts_raise_with_message():
    """Malformed run/status contexts raise ValueError (mutmut m8/11/81/84).

    The empty-string context kills the `or`->`and` mutants: the original
    raises, the mutant silently accepts the empty context.
    """
    from scripts.agent_os_issue_acceptance.merge_applicability import _latest_evidence

    with pytest.raises(ValueError, match="check-run context unavailable"):
        _latest_evidence(_Commit(runs=[_CheckRun(None, "success")]))
    with pytest.raises(ValueError, match="check-run context unavailable"):
        _latest_evidence(_Commit(runs=[_CheckRun("", "success")]))
    with pytest.raises(ValueError, match="check-run context unavailable"):
        _latest_evidence(_Commit(runs=[_app_run_without_name()]))
    with pytest.raises(ValueError, match="commit-status context unavailable"):
        _latest_evidence(_Commit(statuses=[_Status(None, "success")]))
    with pytest.raises(ValueError, match="commit-status context unavailable"):
        _latest_evidence(_Commit(statuses=[_Status("", "success")]))
    with pytest.raises(ValueError, match="commit-status context unavailable"):
        _latest_evidence(_Commit(statuses=[_status_without_context()]))


def _app_run_without_name():
    app = type("App", (), {"slug": "github-actions", "id": 15368})()
    return type("Run", (), {"conclusion": "success", "id": 1, "app": app})()


def _status_without_context():
    return type("Status", (), {"state": "success", "id": 1})()


def test_latest_evidence_missing_id_attributes_are_unidentified():
    """Missing id/conclusion/state attributes default, not crash (mutmut m22/38/95/115)."""
    from scripts.agent_os_issue_acceptance.merge_applicability import _latest_evidence

    app = type("App", (), {"slug": "github-actions", "id": 15368})()
    run_without_id = type(
        "Run", (), {"name": "CI", "conclusion": "success", "app": app}
    )()
    assert _latest_evidence(_Commit(runs=[run_without_id]))["CI"] == (
        "success",
        "github-actions",
        False,
    )
    run_without_conclusion = type(
        "Run", (), {"name": "CI", "id": 1, "app": app}
    )()
    assert _latest_evidence(_Commit(runs=[run_without_conclusion]))["CI"] == (
        "pending",
        "github-actions",
        False,
    )
    status_without_id = type("Status", (), {"context": "CI", "state": "success"})()
    assert _latest_evidence(_Commit(statuses=[status_without_id]))["CI"] == (
        "success",
        None,
        True,
    )
    status_without_state = type("Status", (), {"context": "CI", "id": 1})()
    assert _latest_evidence(_Commit(statuses=[status_without_state]))["CI"] == (
        "unknown",
        None,
        True,
    )


def test_latest_evidence_unknown_conclusion_and_state():
    """Bogus conclusion/state strings are unknown, not crashes (mutmut m47/51/52/108/110/118/119)."""
    from scripts.agent_os_issue_acceptance.merge_applicability import _latest_evidence

    assert _latest_evidence(_Commit(runs=[_CheckRun("CI", "bogus")]))["CI"] == (
        "unknown",
        "github-actions",
        False,
    )
    assert _latest_evidence(_Commit(statuses=[_Status("CI", "bogus")]))["CI"] == (
        "unknown",
        "github-actions",
        True,
    )


def test_latest_evidence_agreement_and_disagreement_tuples():
    """Agreement/disagreement tuples carry both publisher and state (mutmut m168/172)."""
    from scripts.agent_os_issue_acceptance.merge_applicability import _latest_evidence

    commit = _Commit(
        runs=[_CheckRun("CI", "success", run_id=10)],
        statuses=[_Status("CI", "success", status_id=5)],
    )
    assert _latest_evidence(commit)["CI"] == ("success", "github-actions", True)
    commit = _Commit(
        runs=[_CheckRun("CI", "success", run_id=10)],
        statuses=[_Status("CI", "failure", status_id=5)],
    )
    assert _latest_evidence(commit)["CI"] == ("unknown", None, True)


# --- _unresolved_review_threads regression tests ---------------------------


def test_review_threads_graphql_contract():
    """The evaluate-level GraphQL contract: query, owner/name/number/cursor (mutmut m17/21-26/310).

    _unresolved_review_threads receives the PR number from evaluate, so a
    mutant passing None instead never reaches the GitHub read.
    """
    from scripts.agent_os_issue_acceptance.merge_applicability import _REVIEW_THREAD_QUERY

    class _RecordingRequester(_Requester):
        def __init__(self, pages=None):
            super().__init__(pages)
            self.queries = []

        def graphql_query(self, query, variables):
            self.queries.append(query)
            return super().graphql_query(query, variables)

    record = _authorized_record(None)
    comments = _comments_for(None, record)
    requester = _RecordingRequester([[{"isResolved": True}]])
    client = _Client(_Repo(_PR(), comments), requester=requester)
    receipt = evaluate_merge_dispatch_applicability(
        _transport(), repository=REPO, github_client=client, evaluated_at=NOW
    )
    assert receipt["dispatch_checks_passed"] is True
    assert requester.calls == [
        {"owner": "blummer92", "name": "agent-os", "number": PR_NUMBER, "cursor": None}
    ]
    assert requester.queries == [_REVIEW_THREAD_QUERY]


@pytest.mark.parametrize(
    "response",
    [
        {"errors": ["boom"]},
        ["not-a-dict"],
    ],
)
def test_review_thread_error_response_fails_closed(response):
    """Error / non-dict responses fail closed (mutmut m29/31/32/33)."""
    class _CannedRequester:
        def __init__(self, response):
            self.response = response

        def graphql_query(self, query, variables):
            return {}, self.response

    client = _Client(_Repo(_PR(), []), requester=_CannedRequester(response))
    with pytest.raises(ValueError, match="review threads unavailable"):
        _unresolved_review_threads(client, REPO, PR_NUMBER)


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"data": {}},
        {"data": {"repository": {"pullRequest": None}}},
        {"data": {"repository": {"pullRequest": {}}}},
        {"data": {"repository": {"pullRequest": {"reviewThreads": {}}}}},
        {"data": {"repository": {"pullRequest": {"reviewThreads": {
            "nodes": "not-a-list",
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        }}}}},
    ],
)
def test_review_thread_malformed_envelope_fails_closed(response):
    """Malformed envelopes fail closed (mutmut m43/45/47/49/59/64)."""
    class _CannedRequester:
        def __init__(self, response):
            self.response = response

        def graphql_query(self, query, variables):
            return {}, self.response

    client = _Client(_Repo(_PR(), []), requester=_CannedRequester(response))
    with pytest.raises(ValueError, match="review threads incomplete"):
        _unresolved_review_threads(client, REPO, PR_NUMBER)


@pytest.mark.parametrize("page_info", [None, {}])
def test_review_thread_malformed_page_info_fails_closed(page_info):
    """Missing/empty pageInfo fails closed (mutmut m100)."""
    class _CannedRequester:
        def __init__(self, page_info):
            self.page_info = page_info

        def graphql_query(self, query, variables):
            return {}, {"data": {"repository": {"pullRequest": {"reviewThreads": {
                "nodes": [{"isResolved": True}],
                "pageInfo": self.page_info,
            }}}}}

    client = _Client(_Repo(_PR(), []), requester=_CannedRequester(page_info))
    with pytest.raises(ValueError, match="review-thread pagination unavailable"):
        _unresolved_review_threads(client, REPO, PR_NUMBER)


def test_review_thread_page_boundaries():
    """100 nodes per page is allowed, 101 is malformed (mutmut m74/75)."""
    hundred = _Client(
        _Repo(_PR(), []),
        requester=_Requester([[{"isResolved": True}] * 100]),
    )
    assert _unresolved_review_threads(hundred, REPO, PR_NUMBER) == 0
    hundred_one = _Client(
        _Repo(_PR(), []),
        requester=_Requester([[{"isResolved": True}] * 101]),
    )
    with pytest.raises(ValueError, match="review threads malformed"):
        _unresolved_review_threads(hundred_one, REPO, PR_NUMBER)


def test_review_threads_accumulate_across_pages():
    """Unresolved counts accumulate across pages (mutmut m88)."""
    requester = _Requester([
        [{"isResolved": False}],
        [{"isResolved": False}, {"isResolved": True}],
    ])
    client = _Client(_Repo(_PR(), []), requester=requester)
    assert _unresolved_review_threads(client, REPO, PR_NUMBER) == 2


@pytest.mark.parametrize("end_cursor", ["1", 123, ""])
def test_review_thread_bad_cursor_fails_closed(end_cursor):
    """Repeating, non-string, or empty cursors fail closed (mutmut m120/121/128)."""
    class _FixedCursorRequester:
        def __init__(self, end_cursor):
            self.end_cursor = end_cursor
            self.calls = []

        def graphql_query(self, query, variables):
            self.calls.append(variables)
            return {}, {"data": {"repository": {"pullRequest": {"reviewThreads": {
                "nodes": [{"isResolved": True}],
                "pageInfo": {"hasNextPage": True, "endCursor": self.end_cursor},
            }}}}}

    client = _Client(_Repo(_PR(), []), requester=_FixedCursorRequester(end_cursor))
    with pytest.raises(ValueError, match="review-thread cursor unavailable"):
        _unresolved_review_threads(client, REPO, PR_NUMBER)


# --- evaluate_merge_dispatch_applicability regression tests -----------------


class _SecondReadRepo(_Repo):
    """Repo whose second get_issue/get_pull read sees a changed world (TOCTOU).

    Admission reads once; evaluate's reacquire reads again. A static fake
    cannot distinguish the two reads, so the dispatch-time guards that only
    fire when the world changed between them need a toggling repo.
    """

    def __init__(self, pr, comments, *, second_pr=None, second_comments=None,
                 commit=None):
        super().__init__(pr, comments, commit=commit)
        self._second_pr = second_pr if second_pr is not None else pr
        self._second_comments = (
            second_comments if second_comments is not None else comments
        )
        self._pull_calls = 0
        self._issue_calls = 0

    def get_pull(self, number):
        self._pull_calls += 1
        assert number == PR_NUMBER
        return self._pr if self._pull_calls == 1 else self._second_pr

    def get_issue(self, number):
        self._issue_calls += 1
        assert number == PR_NUMBER
        return _Issue(
            self._comments if self._issue_calls == 1 else self._second_comments
        )


def _record_with_binding(record, **binding_changes):
    """Rebuild an authorized record with a modified binding (mutmut m189-574).

    The record id/revision are content-derived, so the binding change must go
    through a fresh pending revision; a plain replace() would leave a stale
    authorization_id that __post_init__ rejects.
    """
    binding = replace(record.binding, **binding_changes)
    pending = replace(
        record, binding=binding, authorization_id="",
        authorization_revision="", revision_number=1, previous_revision=None,
        state=_tauth.MergeAuthorizationState.PENDING,
        decision_id="merge-request", reason_codes=(), details=(),
    )
    return record_merge_authorization_decision(
        pending, state=_tauth.MergeAuthorizationState.AUTHORIZED,
        decision_id="authz-decision", authorizer_id=OWNER,
        decision_at="2026-07-26T14:30:00Z",
    )


def _authorized_record_with_authorizer(authorizer_id):
    """Rebuild the authorized record chain with a different authorizer."""
    record = _authorized_record(None)
    pending = replace(
        record, authorizer_id=authorizer_id, authorization_id="",
        authorization_revision="", revision_number=1, previous_revision=None,
        state=_tauth.MergeAuthorizationState.PENDING,
        decision_id="merge-request", reason_codes=(), details=(),
    )
    return record_merge_authorization_decision(
        pending, state=_tauth.MergeAuthorizationState.AUTHORIZED,
        decision_id="authz-decision", authorizer_id=authorizer_id,
        decision_at="2026-07-26T14:30:00Z",
    )


def test_reacquire_absent_after_admission_passes_blocks():
    """A record that vanished between admission and dispatch blocks (mutmut m139/143/152-155).

    Admission passes on the first read; evaluate's reacquire sees a different
    authorization id and must return authorization.absent.
    """
    record = _authorized_record(None)
    # The authorization id hashes the binding and expires_at only, so the
    # second record differs by expiry, not by decision time.
    other = _authorized_record(None, expires_at="2026-07-26T16:30:00Z")
    first_comments = _comments_for(None, record)
    second_comments = _comments_for(None, other)
    repo = _SecondReadRepo(_PR(), first_comments, second_comments=second_comments)
    client = _Client(repo)
    receipt = evaluate_merge_dispatch_applicability(
        _transport(), repository=REPO, github_client=client, evaluated_at=NOW
    )
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["merge_authorized"] is False
    assert "authorization.record-unavailable-at-dispatch" in receipt["reason_codes"]
    assert "authorization.absent" in receipt["reason_codes"]


def test_historical_schema_version_is_not_dispatch_authority():
    """A schema 1.1 record passes admission but is not dispatch authority (mutmut m189-192).

    Admission never checks schema_version, so the historical record reaches
    the dispatch version guard, which must block it.
    """
    from scripts.agent_os_issue_acceptance.merge_authorization import (
        MERGE_AUTHORIZATION_SCHEMA_VERSION,
        MergeAuthorizationBinding,
        MergeAuthorizationRecord as _Record,
        MergeAuthorizationState,
    )

    record = _authorized_record(None)
    v2 = record.binding
    v1 = MergeAuthorizationBinding(
        repository=v2.repository, pull_request_number=v2.pull_request_number,
        exact_head_sha=v2.exact_head_sha,
        target_base_branch=v2.target_base_branch,
        base_sha_or_evidence_id=v2.base_sha_or_evidence_id,
        permitted_merge_method=v2.permitted_merge_method,
        approval_id="approval:" + "a" * 64,
        approval_revision="approval-revision:" + "b" * 64,
        approval_applicability_identity="approval-applicability:" + "c" * 64,
        approval_expires_at="2026-07-26T15:30:00Z",
        approved_execution_projection_id="approved-execution-projection:" + "d" * 64,
        changed_scope_fingerprint=v2.changed_scope_fingerprint,
        allowed_files=v2.allowed_files, forbidden_paths=v2.forbidden_paths,
        required_tests=v2.required_tests,
        required_check_evidence=v2.required_check_evidence,
        review_evidence=v2.review_evidence,
        pr_metadata_sha256=v2.pr_metadata_sha256,
        closure_admission_ids=v2.closure_admission_ids,
        draft_ready_state=v2.draft_ready_state,
    )
    pending = _Record(
        schema_version=MERGE_AUTHORIZATION_SCHEMA_VERSION,
        authorization_id="", authorization_revision="",
        revision_number=1, previous_revision=None,
        state=MergeAuthorizationState.PENDING, binding=v1,
        authorizer_id=OWNER, decision_id="merge-request",
        decision_at="2026-07-26T14:30:00Z", expires_at="2026-07-26T15:30:00Z",
        supersedes_authorization_id=None, revoked_authorization_id=None,
        consumed_observation_id=None, emergency_override_reason=None,
        emergency_override_audit_location=None, reason_codes=(),
    )
    historical = record_merge_authorization_decision(
        pending, state="authorized", decision_id="authz-decision",
        authorizer_id=OWNER, decision_at="2026-07-26T14:30:00Z",
    )
    receipt = _run(record=historical)
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["merge_authorized"] is False
    assert "version.unsupported-for-dispatch" in receipt["reason_codes"]


def test_non_owner_authorizer_is_not_dispatch_authority():
    """A record authorized by a non-owner passes admission but blocks (mutmut m194-197).

    Admission never checks authorizer_id, so the dispatch owner-provenance
    guard is the only check that catches a "mallory"-authorized record.
    """
    record = _authorized_record_with_authorizer("mallory")
    receipt = _run(record=record)
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["merge_authorized"] is False
    assert "authorization.owner-provenance-mismatch" in receipt["reason_codes"]


@pytest.mark.parametrize("file_count", [5000, 5001])
def test_file_count_boundary(file_count):
    """5000 files pass the scope bound; 5001 trip scope.unbounded (mutmut m202-206)."""
    pr = _PR(_files=[
        _File(f"f{i}.py", FILE_SHA) for i in range(file_count)
    ])
    receipt = _run(pr=pr)
    if file_count == 5000:
        assert "scope.unbounded" not in receipt["reason_codes"]
    else:
        assert "scope.unbounded" in receipt["reason_codes"]
        assert receipt["dispatch_checks_passed"] is False


def test_malformed_filename_reaches_forbidden_paths_guard():
    """A malformed filename trips the forbidden-paths guard, not a crash (mutmut m231-233).

    "a//b" raises DeclaredPathError (a ValueError) in normalize_declared_path,
    which the scope loop catches into the contract.forbidden-paths-changed
    branch.
    """
    pr = _PR(_files=[_File("a//b", FILE_SHA)])
    receipt = _run(pr=pr)
    assert receipt["dispatch_checks_passed"] is False
    assert "contract.forbidden-paths-changed" in receipt["reason_codes"]


def test_missing_authoritative_aggregate_blocks():
    """A record without the aggregate requirement blocks (mutmut m247-249)."""
    record = _authorized_record(None)
    ci_only = _record_with_binding(
        record,
        required_check_evidence=record.binding.required_check_evidence[:1],
    )
    receipt = _run(record=ci_only)
    assert receipt["dispatch_checks_passed"] is False
    assert "checks.authoritative-aggregate-missing" in receipt["reason_codes"]


def test_multiple_check_failures_are_all_reported():
    """The required-checks loop does not stop at the first failure (mutmut m256).

    A missing context first and a failing CI second must both appear; a
    `break` in place of the `continue` would drop the second.
    """
    record = _authorized_record(None)
    missing = MergeCheckEvidence(
        context="missing-ctx", app_identity="github-actions",
        tested_sha=HEAD, evidence_id="", state="success",
    )
    required = (missing,) + record.binding.required_check_evidence
    rebuilt = _record_with_binding(record, required_check_evidence=required)
    commit = _Commit(runs=[_CheckRun("CI", "failure")])
    client = _Client(_Repo(_PR(), _comments_for(None, rebuilt), commit=commit))
    receipt = evaluate_merge_dispatch_applicability(
        _transport(), repository=REPO, github_client=client, evaluated_at=NOW
    )
    assert receipt["dispatch_checks_passed"] is False
    assert "checks.missing" in receipt["reason_codes"]
    assert "checks.changed" in receipt["reason_codes"]


def test_forged_aggregate_is_unverifiable_not_just_unverifiable_publisher():
    """A run-only aggregate is unverifiable, not merely publisher-unverifiable (mutmut m272/276/277)."""
    record = _authorized_record(None)
    commit = _Commit(
        runs=[_CheckRun("agent-os/authoritative-aggregate", "success")],
        statuses=[],
    )
    client = _Client(_Repo(
        _PR(), _comments_for(None, record),
        commit=commit, include_aggregate=False,
    ))
    receipt = evaluate_merge_dispatch_applicability(
        _transport(), repository=REPO, github_client=client, evaluated_at=NOW
    )
    assert receipt["merge_authorized"] is False
    assert "checks.authoritative-aggregate-unverifiable" in receipt["reason_codes"]


def test_blocking_review_expected_but_live_clear_blocks():
    """A blocking review the record expects but the live PR lacks blocks (mutmut m292/399/401/402).

    The record expects a blocking review (blocking_review_present=True) while
    the live PR is clear: dispatch must fail and the lifecycle snapshot must
    expect the blocked review state.
    """
    record = _authorized_record(None)
    blocking = _record_with_binding(
        record,
        review_evidence=MergeReviewEvidence(
            blocking_review_present=True, unresolved_conversation_count=0,
            exact_head_reviewed=True,
        ),
    )
    receipt = _run(record=blocking)
    assert receipt["dispatch_checks_passed"] is False
    assert "review.changed" in receipt["reason_codes"]


def test_blocking_review_expected_and_live_present_blocks_at_canonical():
    """A blocking review the record expects and the live PR has (mutmut m292/399-402).

    Dispatch's review check passes (live matches the record), so the
    lifecycle snapshot must expect the blocked review state; canonical
    evaluation then blocks on the blocking review itself.
    """
    record = _authorized_record(None)
    blocking = _record_with_binding(
        record,
        review_evidence=MergeReviewEvidence(
            blocking_review_present=True, unresolved_conversation_count=0,
            exact_head_reviewed=True,
        ),
    )
    pr = _PR(_reviews=[_Review("CHANGES_REQUESTED", HEAD)])
    receipt = _run(record=blocking, pr=pr)
    assert receipt["dispatch_checks_passed"] is True
    assert receipt["status"] == "blocked"
    assert receipt["merge_authorized"] is False
    assert "review.blocked" in receipt["reason_codes"]
    lifecycle = receipt["lifecycle_mutation_authorization"]
    assert lifecycle is not None
    assert lifecycle["expected_review_state"] == "blocked"


def test_pr_turned_draft_between_admission_and_dispatch_blocks():
    """A PR that became a draft after admission blocks (mutmut m392/394/395).

    Admission saw draft=False; evaluate's read sees draft=True (TOCTOU).
    Dispatch's own checks pass (the draft is only visible to canonical
    evaluation and the lifecycle snapshot), so the receipt is dispatch-True
    but blocked, and the lifecycle snapshot must expect the draft state.
    """
    record = _authorized_record(None)
    comments = _comments_for(None, record)
    repo = _SecondReadRepo(_PR(), comments, second_pr=_PR(draft=True))
    client = _Client(repo)
    receipt = evaluate_merge_dispatch_applicability(
        _transport(), repository=REPO, github_client=client, evaluated_at=NOW
    )
    assert receipt["dispatch_checks_passed"] is True
    assert receipt["status"] == "blocked"
    assert receipt["merge_authorized"] is False
    assert "pull-request.draft" in receipt["reason_codes"]
    assert receipt["canonical_applicability_evaluated"] is True
    canonical = receipt["canonical_applicability_result"]
    assert canonical["status"] == "blocked"
    assert canonical["merge_authorized"] is False
    assert canonical["changed_bindings"] == ["draft_ready_state"]
    assert canonical["reason_codes"] == [
        "pull-request.draft",
        "pull-request.not-ready",
        "pull-request.ready-state-changed",
    ]
    lifecycle = receipt["lifecycle_mutation_authorization"]
    assert lifecycle is not None
    assert lifecycle["expected_pr_state"] == "draft"


def test_review_count_changed_between_record_and_live_blocks():
    """A record expecting 1 unresolved thread with 0 live blocks (mutmut m323-326)."""
    record = _authorized_record(None)
    one_unresolved = _record_with_binding(
        record,
        review_evidence=MergeReviewEvidence(
            blocking_review_present=False, unresolved_conversation_count=1,
            exact_head_reviewed=True,
        ),
    )
    receipt = _run(record=one_unresolved)
    assert receipt["dispatch_checks_passed"] is False
    assert "review.changed" in receipt["reason_codes"]


@pytest.mark.parametrize("actor", [None, 123, ""])
def test_unknown_lifecycle_actor_blocks(actor):
    """A non-owner transport actor blocks on lifecycle.actor-unknown (mutmut m339/342-345)."""
    receipt = _run(transport=_transport(actor=actor))
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["reason_codes"] == ["lifecycle.actor-unknown"]


def test_labels_read_failure_blocks_lifecycle_admission():
    """A get_labels() failure blocks on lifecycle.admission-failed (mutmut m412-415)."""
    class _FailingLabelsPR(_PR):
        def get_labels(self):
            raise RuntimeError("labels unavailable")

    receipt = _run(pr=_FailingLabelsPR())
    assert receipt["dispatch_checks_passed"] is False
    assert "lifecycle.admission-failed" in receipt["reason_codes"]


def test_unauthorized_closing_reference_blocks_at_canonical_evaluation():
    """An unauthorized closing reference blocks only at canonical evaluation (mutmut m552-574).

    The record is built with the plain body, so the candidate builder
    accepts it; admission reads the plain body and passes. Evaluate's read
    sees the body gain "Fixes #123" (TOCTOU): admission's metadata check
    already ran, dispatch's own checks do not look at closing references, so
    only the canonical second return catches it.
    """
    record = _authorized_record(None)
    comments = _comments_for(None, record)
    repo = _SecondReadRepo(_PR(), comments, second_pr=_PR(body="Fixes #123"))
    client = _Client(repo)
    receipt = evaluate_merge_dispatch_applicability(
        _transport(), repository=REPO, github_client=client, evaluated_at=NOW
    )
    assert receipt["dispatch_checks_passed"] is True
    assert receipt["status"] == "blocked"
    assert receipt["merge_authorized"] is False
    assert "pull-request.unauthorized-closing-reference" in receipt["reason_codes"]


def test_contextless_check_run_blocks_at_canonical_evaluation():
    """A context-less live check run blocks at canonical evaluation (mutmut m571-574).

    The run has no name, so _latest_evidence raises ValueError inside the
    canonical evaluation, which the outer except turns into a blocked receipt.
    """
    run_without_name = type(
        "Run", (), {"conclusion": "success", "id": 1}
    )()
    commit = _Commit(runs=[run_without_name])
    client = _Client(_Repo(_PR(), _comments_for(None, _authorized_record(None)),
                           commit=commit))
    receipt = evaluate_merge_dispatch_applicability(
        _transport(), repository=REPO, github_client=client, evaluated_at=NOW
    )
    assert receipt["dispatch_checks_passed"] is False
    assert "canonical-github-evidence-unavailable" in receipt["reason_codes"]


# --- main() CLI regression tests --------------------------------------------


def _validating_client(client):
    """Fake build_token_client that asserts its call arguments (mutmut main m37/38/40/42/43)."""
    def build(environ, user_agent=None):
        assert isinstance(environ, dict)
        assert user_agent == "agent-os-merge-dispatch/1"
        return client

    return build


def _stub_token_client(monkeypatch, build_client):
    """Point main()'s build_token_client import at a fake factory.

    The real auth module needs the uninstalled `github` package, so the stub
    is injected into sys.modules instead of importing it.
    """
    import types

    pkg = types.ModuleType("scripts.agent_os_github_issue_provider")
    pkg.__path__ = []
    auth = types.ModuleType("scripts.agent_os_github_issue_provider.auth")
    auth.build_token_client = build_client
    pkg.auth = auth
    monkeypatch.setitem(
        sys.modules, "scripts.agent_os_github_issue_provider", pkg
    )
    monkeypatch.setitem(
        sys.modules, "scripts.agent_os_github_issue_provider.auth", auth
    )


def test_main_happy_path_writes_receipt(tmp_path, monkeypatch, capsys):
    """main() writes the canonical receipt to --output and prints it (mutmut main/*).

    The record uses a far-future expiry because main() evaluates against the
    real clock, and the July 2026 record would be expired in November 2026.
    """
    from scripts.agent_os_issue_acceptance.merge_applicability import main

    record = _authorized_record(None, expires_at="2036-07-26T15:30:00Z")
    client = _Client(_Repo(_PR(), _comments_for(None, record)))
    _stub_token_client(monkeypatch, _validating_client(client))
    transport_path = tmp_path / "transport.json"
    transport_path.write_text(json.dumps(_transport()), encoding="utf-8")
    # Two missing levels: the output parent must be created recursively
    # (Loop 8, mutmut main m80/82/84).
    output_path = tmp_path / "a" / "b" / "receipt.json"
    assert main([
        "--transport", str(transport_path),
        "--repository", REPO,
        "--output", str(output_path),
    ]) == 0
    receipt = json.loads(output_path.read_text(encoding="utf-8"))
    assert output_path.read_text(encoding="utf-8") == (
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
    )
    assert capsys.readouterr().out == json.dumps(receipt, sort_keys=True) + "\n"
    assert receipt["dispatch_checks_passed"] is True
    assert receipt["status"] == "awaiting-human-attestation"
    assert receipt["merge_authorized"] is False
    assert receipt["receipt_id"] == _recomputed_receipt_id(receipt)


def test_main_client_build_failure_writes_fallback_receipt(tmp_path, monkeypatch, capsys):
    """A build_token_client failure writes the fail-closed fallback receipt (mutmut main/*)."""
    from scripts.agent_os_issue_acceptance.merge_applicability import main

    def _raise(environ, user_agent=None):
        raise RuntimeError("no token")

    _stub_token_client(monkeypatch, _raise)
    transport_path = tmp_path / "transport.json"
    transport_path.write_text(json.dumps(_transport()), encoding="utf-8")
    output_path = tmp_path / "receipt.json"
    assert main([
        "--transport", str(transport_path),
        "--repository", REPO,
        "--output", str(output_path),
    ]) == 0
    receipt = json.loads(output_path.read_text(encoding="utf-8"))
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["canonical-github-evidence-unavailable"]
    assert receipt["pr_number"] is None
    # Pin the fallback receipt's fail-closed fields (Loop 8, mutmut main
    # m52/53/55/57/58): repository, evaluated_at, and the empty lists.
    assert receipt["repository"] == REPO
    assert isinstance(receipt["evaluated_at"], str) and receipt["evaluated_at"]
    assert receipt["verified"] == []
    assert receipt["missing_interfaces"] == []
    assert receipt["lifecycle_snapshot_notes"] == []
    assert receipt["receipt_id"] == _recomputed_receipt_id(receipt)


def test_main_malformed_transport_writes_blocked_receipt(tmp_path, monkeypatch):
    """A malformed transport file blocks the receipt instead of crashing (mutmut main/*)."""
    from scripts.agent_os_issue_acceptance.merge_applicability import main

    record = _authorized_record(None, expires_at="2036-07-26T15:30:00Z")
    client = _Client(_Repo(_PR(), _comments_for(None, record)))
    _stub_token_client(monkeypatch, _validating_client(client))
    transport_path = tmp_path / "transport.json"
    transport_path.write_text("{not json", encoding="utf-8")
    output_path = tmp_path / "receipt.json"
    assert main([
        "--transport", str(transport_path),
        "--repository", REPO,
        "--output", str(output_path),
    ]) == 0
    receipt = json.loads(output_path.read_text(encoding="utf-8"))
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["status"] == "blocked"
    assert receipt["receipt_id"] == _recomputed_receipt_id(receipt)


@pytest.mark.parametrize(
    "argv",
    [
        ["--repository", REPO, "--output", "out.json"],
        ["--transport", "t.json", "--output", "out.json"],
        ["--transport", "t.json", "--repository", REPO],
    ],
)
def test_main_each_required_flag_is_required(argv, tmp_path):
    """Each of --transport/--repository/--output is individually required (mutmut main m4/7/11/13/15/18/20/23/27).

    main([]) alone cannot kill these mutants: omitting all three flags still
    exits 2 via the other two. Omitting exactly one flag must also exit 2;
    a mutant that makes one flag optional instead crashes or returns 0.
    """
    from scripts.agent_os_issue_acceptance.merge_applicability import main

    argv = [
        (str(tmp_path / arg) if arg in ("t.json", "out.json") else arg)
        for arg in argv
    ]
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == 2


def test_main_missing_required_flags_exits_nonzero():
    """main([]) exits nonzero on missing required flags (mutmut main/*)."""
    from scripts.agent_os_issue_acceptance.merge_applicability import main

    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
