"""Read-only merge-admission bridge: exact selectors and canonical source, no merge."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime

from scripts.agent_os_issue_acceptance import merge_admission_actions as actions
from scripts.agent_os_issue_acceptance import merge_authorization as mauth
from scripts.agent_os_issue_acceptance.merge_admission_actions import (
    evaluate_merge_admission_transport,
)
from scripts.agent_os_issue_acceptance.merge_authorization import (
    MERGE_AUTHORIZATION_CURRENT_SCHEMA_VERSION,
    MergeAuthorizationBindingV2,
    MergeAuthorizationRecord,
    MergeAuthorizationState,
    MergeCheckEvidence,
    MergeReviewEvidence,
    pr_metadata_fingerprint,
    record_merge_authorization_decision,
)
from scripts.agent_os_issue_acceptance.merge_authorization_source import (
    serialize_merge_authorization_comment,
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


# ---------------------------------------------------------------------------
# Trusted-record fixtures: real MergeAuthorizationRecords built through the
# canonical producer path, serialized exactly as an owner would post them.
# ---------------------------------------------------------------------------

NOW = "2026-10-19T20:00:00Z"


def make_binding(**overrides):
    check = MergeCheckEvidence(
        context="Agent OS Validation Gate",
        app_identity="github-actions",
        tested_sha=HEAD,
        evidence_id="",
        state="success",
    )
    values = dict(
        repository=REPO,
        pull_request_number=3659,
        exact_head_sha=HEAD,
        target_base_branch="main",
        base_sha_or_evidence_id="b" * 40,
        permitted_merge_method="merge",
        changed_scope_fingerprint="e" * 64,
        allowed_files=(),
        forbidden_paths=(),
        required_tests=(),
        required_check_evidence=(check,),
        review_evidence=MergeReviewEvidence(
            blocking_review_present=False,
            unresolved_conversation_count=0,
            exact_head_reviewed=True,
        ),
        pr_metadata_sha256=pr_metadata_fingerprint("test PR", BODY),
        closure_admission_ids=(),
        draft_ready_state="ready",
    )
    values.update(overrides)
    return MergeAuthorizationBindingV2(**values)


def authorized_record(*, binding=None, decision_at="2026-10-19T18:00:00Z",
                      expires_at="2026-10-19T23:00:00Z", emergency=None):
    pending = MergeAuthorizationRecord(
        schema_version=MERGE_AUTHORIZATION_CURRENT_SCHEMA_VERSION,
        authorization_id="",
        authorization_revision="",
        revision_number=1,
        previous_revision=None,
        state=MergeAuthorizationState.PENDING,
        binding=binding if binding is not None else make_binding(),
        authorizer_id="Blummer92",
        decision_id="decision-1",
        decision_at=decision_at,
        expires_at=expires_at,
        supersedes_authorization_id=None,
        revoked_authorization_id=None,
        consumed_observation_id=None,
        emergency_override_reason=emergency,
        emergency_override_audit_location=(
            "https://example.invalid/audit" if emergency is not None else None
        ),
        reason_codes=(),
    )
    return record_merge_authorization_decision(
        pending,
        state=MergeAuthorizationState.AUTHORIZED,
        decision_id="decision-2",
        authorizer_id="Blummer92",
        decision_at=decision_at,
    )


class FakeComment:
    def __init__(self, comment_id, login, body):
        self.id = comment_id
        self.user = Ref(login=login)
        self.created_at = datetime(2026, 10, 19, 18, 30, 0)
        self.body = body


class RecordRepo(FakeRepo):
    def __init__(self, comments, **kwargs):
        super().__init__(**kwargs)
        self._comments = comments

    def get_issue(self, number):
        assert number == 3659
        return Ref(get_comments=lambda: iter(self._comments))


def owner_comment(record, comment_id=777001):
    return FakeComment(
        comment_id, "Blummer92", serialize_merge_authorization_comment(record)
    )


def _pending_for(record):
    pending = replace(
        record, authorization_revision="", revision_number=1,
        previous_revision=None, state=MergeAuthorizationState.PENDING,
        decision_id="decision-1", reason_codes=(), details=(),
    )
    assert pending.authorization_revision == record.previous_revision
    return pending


def check_with_records(records, *, repo_kwargs=None, evaluated_at=NOW, filler=0):
    comments = [FakeComment(900000 + i, "Blummer92", f"filler {i}") for i in range(filler)]
    history = []
    for record in records:
        if record.state is MergeAuthorizationState.AUTHORIZED and record.revision_number == 2:
            history.append(_pending_for(record))
        history.append(record)
    comments += [owner_comment(record, 777001 + i) for i, record in enumerate(history)]
    repo = RecordRepo(comments, **(repo_kwargs or {}))
    return evaluate_merge_admission_transport(
        trigger(), repository=REPO, github_client=FakeClient(repo),
        evaluated_at=evaluated_at,
    )


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


# ---------------------------------------------------------------------------
# Phase 3 repairs: canonical binding reconciliation, expiry, record identity.
# ---------------------------------------------------------------------------

def test_fully_matching_record_yields_non_authorizing_candidate_receipt():
    receipt = check_with_records([authorized_record()])
    assert receipt["status"] == "blocked"
    assert receipt["merge_authorized"] is False
    assert receipt["canonical_applicability_evaluated"] is False
    assert receipt["reason_codes"] == ["approval-and-applicability-evidence-not-wired"]
    assert receipt["authorization_id"]
    assert receipt["authorization_revision"]
    assert receipt["authorization_expires_at"] == "2026-10-19T23:00:00Z"
    assert receipt["binding_changed_fields"] == []
    assert receipt["authorization_record_count"] == 1
    assert receipt["evaluated_at"] == NOW
    assert receipt["emergency_override_present"] is False
    assert receipt["side_effects_performed"] is False
    contract = receipt["host_dispatch_contract"]
    assert contract["consumer"].startswith("chatgpt-github-connector")
    assert "receipt.status == 'awaiting-human-attestation'" in contract["merge_dispatch_allowed_only_when_all_true"]
    assert any("fresh per-call runtime human approval card was tapped" in item for item in contract["merge_dispatch_allowed_only_when_all_true"])


def test_expired_record_is_rejected_not_matched():
    record = authorized_record(expires_at="2026-10-19T19:00:00Z")
    receipt = check_with_records([record], evaluated_at="2026-10-19T20:00:00Z")
    assert receipt["merge_authorized"] is False
    assert "authorization.expired" in receipt["reason_codes"]
    assert "approval-and-applicability-evidence-not-wired" not in receipt["reason_codes"]
    assert receipt["authorization_id"] is None


def test_expired_record_among_valid_ones_is_skipped():
    expired = authorized_record(expires_at="2026-10-19T19:00:00Z")
    fresh = authorized_record(expires_at="2026-10-19T23:00:00Z")
    receipt = check_with_records([expired, fresh], evaluated_at="2026-10-19T20:00:00Z")
    assert receipt["reason_codes"] == ["approval-and-applicability-evidence-not-wired"]
    assert receipt["authorization_id"] == fresh.authorization_id


def test_ready_state_drift_against_record_is_blocked():
    record = authorized_record(binding=make_binding(draft_ready_state="draft"))
    receipt = check_with_records([record])
    assert receipt["merge_authorized"] is False
    assert "authorization.binding-mismatch" in receipt["reason_codes"]
    assert "pull-request.ready-state-changed" in receipt["reason_codes"]
    assert "draft_ready_state" in receipt["candidate_records"][0]["changed_fields"]


def test_method_drift_against_record_is_blocked():
    record = authorized_record(binding=make_binding(permitted_merge_method="squash"))
    receipt = check_with_records([record])
    assert "merge.method-changed" in receipt["reason_codes"]
    assert "authorization.binding-mismatch" in receipt["reason_codes"]


def test_head_drift_against_record_is_blocked():
    record = authorized_record(binding=make_binding(exact_head_sha="f" * 40))
    receipt = check_with_records([record])
    assert "pull-request.head-changed" in receipt["reason_codes"]
    assert receipt["authorization_id"] is None


def test_metadata_drift_against_record_is_blocked():
    record = authorized_record(binding=make_binding(pr_metadata_sha256="0" * 64))
    receipt = check_with_records([record])
    assert "pull-request.metadata-changed" in receipt["reason_codes"]


def test_base_branch_drift_against_record_is_blocked():
    record = authorized_record(binding=make_binding(target_base_branch="other"))
    receipt = check_with_records([record])
    assert "pull-request.base-changed" in receipt["reason_codes"]


def test_binding_reason_mapping_matches_canonical():
    canonical = mauth._binding_reasons
    for field, reason in actions._BINDING_FIELD_REASONS.items():
        assert canonical([field]) == {reason}, field


def test_binding_field_coverage_partitions_canonical_binding():
    from dataclasses import fields as dataclass_fields
    declared = {f.name for f in dataclass_fields(mauth.MergeAuthorizationBindingV2)}
    assert (set(actions._LIVE_BINDING_FIELDS)
            | set(actions._NON_RECOMPUTABLE_BINDING_FIELDS)) == declared
    assert not (set(actions._LIVE_BINDING_FIELDS)
                & set(actions._NON_RECOMPUTABLE_BINDING_FIELDS))


def test_many_comments_still_reach_canonical_source_bounds():
    receipt = check_with_records([authorized_record()], filler=300)
    assert receipt["reason_codes"] == ["approval-and-applicability-evidence-not-wired"]
    assert receipt["authorization_record_count"] == 1


def test_expired_revision_is_reported_not_current():
    pending = authorized_record().binding  # reuse binding only
    expired_pending = MergeAuthorizationRecord(
        schema_version=MERGE_AUTHORIZATION_CURRENT_SCHEMA_VERSION,
        authorization_id="", authorization_revision="",
        revision_number=1, previous_revision=None,
        state=MergeAuthorizationState.PENDING, binding=pending,
        authorizer_id="Blummer92", decision_id="d1",
        decision_at="2026-10-19T17:00:00Z", expires_at="2026-10-19T18:00:00Z",
        supersedes_authorization_id=None, revoked_authorization_id=None,
        consumed_observation_id=None, emergency_override_reason=None,
        emergency_override_audit_location=None, reason_codes=(),
    )
    expired = record_merge_authorization_decision(
        expired_pending, state=MergeAuthorizationState.EXPIRED,
        decision_id="d2", authorizer_id="Blummer92",
        decision_at="2026-10-19T19:00:00Z",
    )
    receipt = check_with_records([expired_pending, expired])
    assert "authorization.consumed-or-not-current" in receipt["reason_codes"]
    assert receipt["merge_authorized"] is False


def test_emergency_override_is_surfaced_not_authorized():
    record = authorized_record(emergency="incident-override")
    receipt = check_with_records([record])
    assert receipt["emergency_override_present"] is True
    assert receipt["merge_authorized"] is False
    assert receipt["reason_codes"] == ["approval-and-applicability-evidence-not-wired"]


def test_evaluated_at_defaults_to_utc_now():
    record = authorized_record(expires_at="2030-01-01T00:00:00Z")
    comments = [owner_comment(_pending_for(record)), owner_comment(record, 777002)]
    repo = RecordRepo(comments)
    receipt = evaluate_merge_admission_transport(
        trigger(), repository=REPO, github_client=FakeClient(repo))
    assert receipt["reason_codes"] == ["approval-and-applicability-evidence-not-wired"]
    assert actions._parse_timestamp(receipt["evaluated_at"]) is not None


def test_malformed_evaluated_at_fails_closed():
    comments = [owner_comment(authorized_record())]
    repo = RecordRepo(comments)
    receipt = evaluate_merge_admission_transport(
        trigger(), repository=REPO, github_client=FakeClient(repo),
        evaluated_at="not-a-timestamp")
    assert receipt["merge_authorized"] is False
    assert receipt["reason_codes"] == ["evaluator-clock-malformed"]
