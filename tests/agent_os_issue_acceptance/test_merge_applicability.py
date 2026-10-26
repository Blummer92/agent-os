"""Tests for merge_applicability.py: dispatch-time applicability consumer.

Every authorization artifact is built through the canonical producers; the
fake GitHub surface is read-only. The consumer emits merge_authorized=true
only when every dispatch check passes AND the canonical evaluator returns
applicable for a typed MergeProposal; every negative case below must keep
merge_authorized false, and no case in this file performs a merge.
"""
from __future__ import annotations

import importlib.util
from dataclasses import replace
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

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
