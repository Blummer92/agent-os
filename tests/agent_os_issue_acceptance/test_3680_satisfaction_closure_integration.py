"""Tests for #3680: satisfaction evidence in reconciliation + closure packet.

Connects the merged #3678 satisfaction record to (a) post-merge lifecycle
reconciliation reporting and (b) the #3489 closure-admission judgment
packet, without giving satisfaction any closure authority.

Option B contract: the reporting-side producer hands the record over as
a plain mapping snapshot of exactly
``{issue_body_digest, status, criteria: [{index, identity, disposition,
reason_code, evidence}]}`` — the approval-domain consumers import nothing
from ``criterion_satisfaction`` (architecture dependency-direction
contract). Each consumer strictly validates the snapshot at its input
boundary (exact key sets, exact built-in types, 1..N contiguous indexes,
and a declared status that must agree with the criteria under the
projector's own derivation) and stores a defensive copy, so forged
completeness, inconsistent criteria, malformed evidence, and later
mutation of the caller's mapping are all rejected or neutralized.
Satisfaction remains evidence for QA judgment: a complete record alone
never admits closure — the recorded owner decision, independent QA
acceptance, and exact-issue admission remain the only closure path,
proven end-to-end through ``run_closure_batch``.

Fixture builders follow the established patterns of
``test_lifecycle_reconciliation.py`` and
``test_closure_admission_actions.py``.
"""

from __future__ import annotations

import copy

import pytest

from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    ClosureAcceptanceEvidence,
    ClosureIssueReadback,
    ClosureWriteUncertain,
    IssueClosureRequest,
    evaluate_issue_closure,
    run_closure_batch,
    verify_closure_admission_receipt,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    DependencyState,
    FreshnessState,
    IssueOperationalEvidence,
    IssueState,
    LifecycleStage,
    PrimaryIssueClaim,
    ReadinessState,
    SourceState,
    TerminalDisposition,
    ValidationState,
    build_issue_operational_state,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
    produce_lifecycle_mutation_authorization,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    AdmissionStatus,
    LifecycleMutationAdmissionResult,
    LifecycleStateSnapshot,
)
from scripts.agent_os_issue_acceptance.lifecycle_reconciliation import (
    ActionCategory,
    LifecycleReconciliationInput,
    PullRequestEvidence,
    PullRequestState,
    reconcile_lifecycle,
    serialize_lifecycle_reconciliation_input,
    serialize_lifecycle_reconciliation_result,
)

# ---------------------------------------------------------------------------
# Satisfaction snapshots, as plain mappings in the exact block shape the
# reporting-side producer serializes (no SatisfactionProjection anywhere).
# ---------------------------------------------------------------------------

DIGEST = "c" * 64


def criterion(index, disposition, *, identity=None, reason_code=None, evidence=None):
    return {
        "index": index,
        "identity": identity or f"criterion-{index}-a1b2c3",
        "disposition": disposition,
        "reason_code": reason_code or f"reason-{disposition}",
        "evidence": (
            evidence
            if evidence is not None
            else [f"pr:997@{'b' * 40}/qa-verdict-{index}"]
        ),
    }


def snapshot(status, criteria, *, digest=DIGEST):
    return {"issue_body_digest": digest, "status": status, "criteria": criteria}


def complete_snapshot():
    return snapshot("complete", [criterion(i, "satisfied") for i in (1, 2, 3)])


def incomplete_snapshot():
    return snapshot(
        "incomplete",
        [criterion(1, "satisfied"), criterion(2, "missing"), criterion(3, "missing")],
    )


def stale_snapshot():
    return snapshot("incomplete", [criterion(i, "stale") for i in (1, 2, 3)])


def manual_review_snapshot():
    return snapshot(
        "manual-review",
        [criterion(1, "satisfied"), criterion(2, "manual-review"), criterion(3, "satisfied")],
    )


# ---------------------------------------------------------------------------
# Lifecycle reconciliation fixtures (pattern: test_lifecycle_reconciliation).
# ---------------------------------------------------------------------------

SOURCE = "a" * 40
HEAD = "b" * 40
APPROVAL = "approval:" + "1" * 64
EVIDENCE = "issueplan-current-state:" + "2" * 64


def authority(state: AuthorizationState) -> AuthorityProjection:
    return AuthorityProjection(
        state=state,
        evidence_id=(
            APPROVAL
            if state in {AuthorizationState.AUTHORIZED, AuthorizationState.STALE}
            else None
        ),
    )


def op_state(*, closure=AuthorizationState.NOT_AUTHORIZED):
    return build_issue_operational_state(
        IssueOperationalEvidence(
            repository="Blummer92/agent-os",
            issue_number=996,
            source_revision=SOURCE,
            observed_at="2026-08-09T17:10:00Z",
            evidence_ids=(EVIDENCE,),
            source_state=SourceState.COMPLETE,
            issue_state=IssueState.OPEN,
            lifecycle_stage=LifecycleStage.IMPLEMENTATION,
            terminal_disposition=TerminalDisposition.NONE,
            readiness=ReadinessState.READY,
            implementation_authorization=authority(AuthorizationState.AUTHORIZED),
            ready_for_review_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            execution_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            merge_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            closure_authorization=authority(closure),
            external_write_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            dependency_state=DependencyState.CLEAR,
            primary_claims=(
                PrimaryIssueClaim(
                    pull_request_number=997,
                    branch="agent/996-lifecycle-reconciliation",
                    head_sha=HEAD,
                    state="merged",
                ),
            ),
            validation_state=ValidationState.NOT_RUN,
            freshness_state=FreshnessState.CURRENT,
            observed_labels=("status:ready",),
        )
    )


def merged_snapshot() -> LifecycleStateSnapshot:
    return LifecycleStateSnapshot(
        repository="Blummer92/agent-os", issue_number=996,
        pull_request_number=997, source_head=HEAD, base_head=SOURCE,
        pr_state="ready", merged=True, issue_state="open",
        review_state="clear", unresolved_threads=0,
        lifecycle_labels=("status:ready",), observed_revision="revision-1",
    )


def merged_input(satisfaction=None, *, with_authority=False):
    current = op_state(
        closure=(
            AuthorizationState.AUTHORIZED
            if with_authority
            else AuthorizationState.NOT_AUTHORIZED
        )
    )
    snap = merged_snapshot()
    admissions = ()
    if with_authority:
        admissions = (
            LifecycleMutationAdmissionResult(
                requested_mutation="close-issue", admitted=True,
                status=AdmissionStatus.ADMITTED, reason_codes=(), details=(),
                authorization_id=current.closure_authorization.evidence_id,
                snapshot_id=snap.snapshot_id,
            ),
        )
    return LifecycleReconciliationInput(
        repository="Blummer92/agent-os", issue_number=996,
        operational_state=current, lifecycle_snapshot=snap,
        current_pull_request=PullRequestEvidence(
            997, "agent/996-lifecycle-reconciliation", HEAD,
            PullRequestState.MERGED, "pr:997",
        ),
        admissions=admissions,
        satisfaction=satisfaction,
    )


def close_actions(result):
    return [
        item
        for item in result.actions
        if item.reason_code == "lifecycle.merged-pr-open-issue"
    ]


# ---------------------------------------------------------------------------
# Reconciliation: satisfaction reporting (retained behavior).
# ---------------------------------------------------------------------------


def test_snapshot_fixtures_have_the_intended_shapes():
    complete = merged_input(complete_snapshot()).satisfaction
    assert complete.status == "complete"
    assert complete.complete is True
    incomplete = merged_input(incomplete_snapshot()).satisfaction
    assert incomplete.complete is False
    assert [item.disposition for item in incomplete.unsatisfied_criteria] == [
        "missing",
        "missing",
    ]
    stale = merged_input(stale_snapshot()).satisfaction
    assert stale.complete is False
    assert all(item.disposition == "stale" for item in stale.criteria)


def test_incomplete_record_reports_not_closure_ready_and_names_blockers():
    snap = incomplete_snapshot()
    result = reconcile_lifecycle(merged_input(snap, with_authority=True))
    actions = close_actions(result)
    assert len(actions) == 1
    action = actions[0]
    # No close-issue mutation is projected, even though closure
    # authorization and admission both exist.
    assert action.category is ActionCategory.MANUAL_DECISION
    assert action.required_mutation is None
    assert not any(
        item.required_mutation == "close-issue" for item in result.actions
    )
    # Every blocking criterion is named with its disposition.
    for item in snap["criteria"]:
        if item["disposition"] != "satisfied":
            assert f"{item['identity']}:{item['disposition']}" in action.observed
    # The serialized result carries the verbatim satisfaction block.
    block = result.to_dict()["satisfaction"]
    assert block["closure_ready"] is False
    assert block["status"] == "incomplete"
    assert block["issue_body_digest"] == DIGEST
    assert block["criteria"] == snap["criteria"]


def test_complete_record_keeps_existing_closure_projection():
    snap = complete_snapshot()
    result = reconcile_lifecycle(merged_input(snap, with_authority=True))
    actions = close_actions(result)
    assert len(actions) == 1
    action = actions[0]
    assert action.category is ActionCategory.GOVERNED_MUTATION
    assert action.required_mutation == "close-issue"
    block = result.to_dict()["satisfaction"]
    assert block["closure_ready"] is True
    assert block["criteria"] == snap["criteria"]


def test_complete_record_alone_never_creates_closure_authority():
    # Complete satisfaction, but no closure authorization/admission:
    # the pre-existing manual-decision flow is unchanged.
    result = reconcile_lifecycle(merged_input(complete_snapshot()))
    actions = close_actions(result)
    assert len(actions) == 1
    assert actions[0].category is ActionCategory.MANUAL_DECISION
    assert actions[0].authorization_id is None
    assert "authorization.closure-required" in result.reason_codes
    assert result.to_dict()["satisfaction"]["closure_ready"] is True


def test_stale_after_merge_record_reports_not_closure_ready():
    result = reconcile_lifecycle(merged_input(stale_snapshot(), with_authority=True))
    actions = close_actions(result)
    assert len(actions) == 1
    assert actions[0].category is ActionCategory.MANUAL_DECISION
    assert actions[0].required_mutation is None
    for item in stale_snapshot()["criteria"]:
        assert f"{item['identity']}:stale" in actions[0].observed
    assert result.to_dict()["satisfaction"]["closure_ready"] is False


def test_manual_review_record_reports_not_closure_ready():
    result = reconcile_lifecycle(
        merged_input(manual_review_snapshot(), with_authority=True)
    )
    actions = close_actions(result)
    assert len(actions) == 1
    assert actions[0].category is ActionCategory.MANUAL_DECISION
    assert actions[0].required_mutation is None
    assert "criterion-2-a1b2c3:manual-review" in actions[0].observed
    assert result.to_dict()["satisfaction"]["closure_ready"] is False


def test_empty_manual_review_snapshot_is_accepted_but_never_complete():
    # The projector's criteria-section-missing form: no criteria,
    # status manual-review. Accepted at the boundary, never complete.
    result = reconcile_lifecycle(
        merged_input(snapshot("manual-review", []), with_authority=True)
    )
    actions = close_actions(result)
    assert len(actions) == 1
    assert actions[0].category is ActionCategory.MANUAL_DECISION
    assert actions[0].required_mutation is None
    assert result.to_dict()["satisfaction"]["closure_ready"] is False


def test_absent_record_reproduces_pre_change_behavior_exactly():
    baseline_input = merged_input(None, with_authority=True)
    explicit_none = merged_input(None, with_authority=True)
    baseline = reconcile_lifecycle(baseline_input)
    candidate = reconcile_lifecycle(explicit_none)
    assert "satisfaction" not in baseline.to_dict()
    assert serialize_lifecycle_reconciliation_input(baseline_input) == (
        serialize_lifecycle_reconciliation_input(explicit_none)
    )
    assert baseline_input.input_id == explicit_none.input_id
    assert serialize_lifecycle_reconciliation_result(baseline) == (
        serialize_lifecycle_reconciliation_result(candidate)
    )
    assert baseline.result_id == candidate.result_id
    # And the governed close-issue projection is intact without a record.
    actions = close_actions(baseline)
    assert actions[0].category is ActionCategory.GOVERNED_MUTATION


def test_mutated_caller_snapshot_cannot_change_reconciliation():
    snap = incomplete_snapshot()
    original = copy.deepcopy(snap)
    built = merged_input(snap, with_authority=True)
    input_id_before = built.input_id
    # Mutate the caller's mapping in every way after construction.
    snap["status"] = "manual-review"
    snap["issue_body_digest"] = "d" * 64
    snap["criteria"][0]["disposition"] = "missing"
    snap["criteria"][1]["evidence"].append("pr:999@deadbeef/forged")
    snap["criteria"].append(criterion(4, "missing"))
    result = reconcile_lifecycle(built)
    assert built.input_id == input_id_before
    block = result.to_dict()["satisfaction"]
    assert block["status"] == original["status"]
    assert block["issue_body_digest"] == original["issue_body_digest"]
    assert block["criteria"] == original["criteria"]
    assert block["closure_ready"] is False


# ---------------------------------------------------------------------------
# Snapshot validation: forged, inconsistent, incomplete, malformed.
# Shared adversarial cases — both consumers must reject every one.
# ---------------------------------------------------------------------------


def _bad_snapshots():
    cases = {}

    forged = complete_snapshot()
    forged["criteria"][1]["disposition"] = "missing"
    cases["forged-complete-with-missing"] = forged

    forged_stale = complete_snapshot()
    forged_stale["criteria"][0]["disposition"] = "stale"
    cases["forged-complete-with-stale"] = forged_stale

    forged_unsatisfied = complete_snapshot()
    forged_unsatisfied["criteria"][2]["disposition"] = "unsatisfied"
    cases["forged-complete-with-unsatisfied"] = forged_unsatisfied

    cases["forged-complete-with-no-criteria"] = snapshot("complete", [])

    inconsistent = complete_snapshot()
    inconsistent["status"] = "incomplete"
    cases["inconsistent-all-satisfied-but-incomplete"] = inconsistent

    inconsistent_review = incomplete_snapshot()
    inconsistent_review["status"] = "manual-review"
    cases["inconsistent-review-without-review-criterion"] = inconsistent_review

    inconsistent_incomplete = manual_review_snapshot()
    inconsistent_incomplete["status"] = "incomplete"
    cases["inconsistent-incomplete-with-review-criterion"] = inconsistent_incomplete

    duplicate = snapshot(
        "incomplete", [criterion(1, "satisfied"), criterion(1, "missing")]
    )
    cases["duplicate-index"] = duplicate

    gap = snapshot(
        "incomplete", [criterion(1, "satisfied"), criterion(3, "missing")]
    )
    cases["non-contiguous-index"] = gap

    reordered = snapshot(
        "incomplete", [criterion(2, "missing"), criterion(1, "satisfied")]
    )
    cases["out-of-order-index"] = reordered

    for key in ("issue_body_digest", "status", "criteria"):
        missing = complete_snapshot()
        del missing[key]
        cases[f"missing-top-level-{key}"] = missing

    for key in ("index", "identity", "disposition", "reason_code", "evidence"):
        missing_field = complete_snapshot()
        del missing_field["criteria"][0][key]
        cases[f"missing-criterion-{key}"] = missing_field

    extra_top = complete_snapshot()
    extra_top["closure_ready"] = True
    cases["extra-top-level-key"] = extra_top

    extra_criterion = complete_snapshot()
    extra_criterion["criteria"][0]["text"] = "Alpha criterion is verified."
    cases["extra-criterion-key"] = extra_criterion

    bad_digest = complete_snapshot()
    bad_digest["issue_body_digest"] = "not-a-digest"
    cases["digest-not-hex"] = bad_digest

    upper_digest = complete_snapshot()
    upper_digest["issue_body_digest"] = "C" * 64
    cases["digest-uppercase"] = upper_digest

    short_digest = complete_snapshot()
    short_digest["issue_body_digest"] = "c" * 63
    cases["digest-too-short"] = short_digest

    bad_status = complete_snapshot()
    bad_status["status"] = "done"
    cases["unknown-status"] = bad_status

    bad_disposition = complete_snapshot()
    bad_disposition["criteria"][0]["disposition"] = "passed"
    cases["unknown-disposition"] = bad_disposition

    bool_index = complete_snapshot()
    bool_index["criteria"][0]["index"] = True
    cases["bool-index"] = bool_index

    string_index = complete_snapshot()
    string_index["criteria"][0]["index"] = "1"
    cases["string-index"] = string_index

    empty_identity = complete_snapshot()
    empty_identity["criteria"][0]["identity"] = ""
    cases["empty-identity"] = empty_identity

    empty_reason = complete_snapshot()
    empty_reason["criteria"][0]["reason_code"] = ""
    cases["empty-reason-code"] = empty_reason

    evidence_string = complete_snapshot()
    evidence_string["criteria"][0]["evidence"] = "pr:997@x/qa"
    cases["evidence-not-a-list"] = evidence_string

    evidence_empty = complete_snapshot()
    evidence_empty["criteria"][0]["evidence"] = []
    cases["evidence-empty"] = evidence_empty

    evidence_non_string = complete_snapshot()
    evidence_non_string["criteria"][0]["evidence"] = [7]
    cases["evidence-non-string-pointer"] = evidence_non_string

    evidence_blank = complete_snapshot()
    evidence_blank["criteria"][0]["evidence"] = [""]
    cases["evidence-blank-pointer"] = evidence_blank

    criteria_tuple = complete_snapshot()
    criteria_tuple["criteria"] = tuple(criteria_tuple["criteria"])
    cases["criteria-not-a-list"] = criteria_tuple

    criterion_list = complete_snapshot()
    criterion_list["criteria"][0] = ["not", "a", "dict"]
    cases["criterion-not-a-dict"] = criterion_list

    return cases


BAD_SNAPSHOTS = _bad_snapshots()


@pytest.mark.parametrize("name", sorted(BAD_SNAPSHOTS))
def test_reconciliation_rejects_bad_snapshots(name):
    with pytest.raises((TypeError, ValueError)):
        merged_input(BAD_SNAPSHOTS[name])


@pytest.mark.parametrize("name", sorted(BAD_SNAPSHOTS))
def test_closure_request_rejects_bad_snapshots(name):
    with pytest.raises((TypeError, ValueError)):
        closure_request(satisfaction=BAD_SNAPSHOTS[name])


@pytest.mark.parametrize(
    "value", ["complete", 7, [("status", "complete")], object()]
)
def test_snapshot_wrong_top_level_type_is_rejected(value):
    with pytest.raises(TypeError):
        merged_input(satisfaction=value)
    with pytest.raises(TypeError):
        closure_request(satisfaction=value)


# ---------------------------------------------------------------------------
# Closure packet fixtures (pattern: test_closure_admission_actions).
# ---------------------------------------------------------------------------

REPO = "Blummer92/agent-os"


def closure_snapshot(issue=3432, **changes):
    data = dict(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        source_head=None,
        base_head=None,
        pr_state="none",
        merged=False,
        issue_state="open",
        review_state="clear",
        unresolved_threads=0,
        lifecycle_labels=(),
        observed_revision=f"rev-{issue}-1",
    )
    data.update(changes)
    return LifecycleStateSnapshot(**data)


def closure_request(issue=3432, *, satisfaction=None, **kw):
    decision = LifecycleOwnerDecision(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        requested_mutations=("close-issue",),
        authorizer_id=kw.get("authorizer_id", "repository-owner"),
        decision_id=kw.get("decision_id", f"owner-decision-{issue}"),
        decision_recorded=kw.get("decision_recorded", True),
    )
    acceptance = ClosureAcceptanceEvidence(
        verdict=kw.get("verdict", "pass"),
        evidence_id=kw.get("evidence_id", f"qa-evidence-{issue}"),
        evaluator_id=kw.get("evaluator_id", "independent-qa"),
    )
    return IssueClosureRequest(
        decision=decision, acceptance=acceptance, satisfaction=satisfaction
    )


class FakeReader:
    def __init__(self, snapshots, *, closed_state_reasons=None, open_state_reasons=None):
        self._snapshots = dict(snapshots)
        self._closed_state_reasons = dict(closed_state_reasons or {})
        self._open_state_reasons = dict(open_state_reasons or {})
        self.reads = []

    def read_issue_snapshot(self, repository, issue_number):
        self.reads.append(issue_number)
        return self._snapshots[issue_number]

    def read_issue_readback(self, repository, issue_number):
        snap = self.read_issue_snapshot(repository, issue_number)
        if snap.issue_state == "closed":
            reason = self._closed_state_reasons.get(issue_number, "completed")
        else:
            reason = self._open_state_reasons.get(issue_number)
        return ClosureIssueReadback(snapshot=snap, state_reason=reason)

    def set(self, snap):
        self._snapshots[snap.issue_number] = snap


class FakeWriter:
    def __init__(self, reader, *, fail_for=(), uncertain_for=(), silent_for=()):
        self.reader = reader
        self.calls = []
        self.fail_for = set(fail_for)
        self.uncertain_for = set(uncertain_for)
        self.silent_for = set(silent_for)

    def close_issue(self, repository, issue_number, *, state_reason):
        self.calls.append((issue_number, state_reason))
        if issue_number in self.fail_for:
            raise RuntimeError("github-write-failed")
        if issue_number not in self.silent_for:
            current = self.reader._snapshots[issue_number]
            self.reader.set(
                closure_snapshot(
                    issue_number,
                    issue_state="closed",
                    observed_revision=current.observed_revision + "-closed",
                )
            )
        if issue_number in self.uncertain_for:
            raise ClosureWriteUncertain("response lost")


# ---------------------------------------------------------------------------
# Closure packet: fidelity, integrity, fail-closed behavior.
# ---------------------------------------------------------------------------


def test_packet_cites_satisfaction_verbatim():
    snap = complete_snapshot()
    receipt = evaluate_issue_closure(
        closure_request(satisfaction=snap), closure_snapshot()
    )
    assert receipt["admitted"] is True
    assert receipt["satisfaction"] == snap


def test_packet_without_satisfaction_is_byte_identical_in_shape():
    receipt = evaluate_issue_closure(closure_request(), closure_snapshot())
    assert receipt["admitted"] is True
    assert "satisfaction" not in receipt
    assert set(receipt) == {
        "schema_version", "operation", "repository", "issue_number",
        "admitted", "reason_codes", "authorization_id",
        "admission_result_id", "snapshot_id",
        "acceptance_evidence_id",
        "host_dispatch_contract", "next_action", "receipt_id",
        "closure_performed", "merge_authorized", "side_effects_performed",
    }


def test_tampered_satisfaction_block_fails_verify_gate():
    snap = complete_snapshot()
    req = closure_request(satisfaction=snap)
    closure_snap = closure_snapshot()
    receipt = evaluate_issue_closure(req, closure_snap)
    auth = produce_lifecycle_mutation_authorization(req.decision, closure_snap)
    assert verify_closure_admission_receipt(
        receipt, authorization=auth, fresh_snapshot=closure_snap,
        acceptance=req.acceptance,
    ) is True

    tampered = copy.deepcopy(receipt)
    tampered["satisfaction"]["criteria"][0]["disposition"] = "missing"
    assert verify_closure_admission_receipt(
        tampered, authorization=auth, fresh_snapshot=closure_snap,
        acceptance=req.acceptance,
    ) is False

    tampered_pointer = copy.deepcopy(receipt)
    tampered_pointer["satisfaction"]["criteria"][0]["evidence"] = [
        "pr:999@deadbeef/forged"
    ]
    assert verify_closure_admission_receipt(
        tampered_pointer, authorization=auth, fresh_snapshot=closure_snap,
        acceptance=req.acceptance,
    ) is False

    stripped = copy.deepcopy(receipt)
    del stripped["satisfaction"]
    assert verify_closure_admission_receipt(
        stripped, authorization=auth, fresh_snapshot=closure_snap,
        acceptance=req.acceptance,
    ) is False


def test_inconsistent_satisfaction_block_in_receipt_fails_verify_gate():
    # A block whose declared status disagrees with its own criteria is
    # rejected by the verifier's strict validation before any hash
    # comparison — forged completeness never reaches the gate as evidence.
    snap = complete_snapshot()
    req = closure_request(satisfaction=snap)
    closure_snap = closure_snapshot()
    receipt = evaluate_issue_closure(req, closure_snap)
    auth = produce_lifecycle_mutation_authorization(req.decision, closure_snap)
    forged = copy.deepcopy(receipt)
    forged["satisfaction"] = incomplete_snapshot()
    forged["satisfaction"]["status"] = "complete"
    assert verify_closure_admission_receipt(
        forged, authorization=auth, fresh_snapshot=closure_snap,
        acceptance=req.acceptance,
    ) is False


def test_mutated_caller_snapshot_cannot_change_receipt():
    snap = complete_snapshot()
    original = copy.deepcopy(snap)
    req = closure_request(satisfaction=snap)
    snap["criteria"][0]["disposition"] = "missing"
    snap["criteria"].append(criterion(4, "satisfied"))
    snap["issue_body_digest"] = "d" * 64
    receipt = evaluate_issue_closure(req, closure_snapshot())
    assert receipt["satisfaction"] == original


def test_complete_satisfaction_without_owner_decision_is_not_admitted():
    receipt = evaluate_issue_closure(
        closure_request(
            satisfaction=complete_snapshot(), decision_recorded=False
        ),
        closure_snapshot(),
    )
    assert receipt["admitted"] is False
    assert receipt["reason_codes"] == ["closure.authorization-not-recorded"]
    # The evidence is still cited in the (non-admitted) packet.
    assert receipt["satisfaction"]["status"] == "complete"


def test_incomplete_record_is_cited_but_never_the_admission_reason():
    # Satisfaction neither grants nor blocks admission: with the owner
    # decision and QA pass in place the packet admits on the governed
    # path and cites the incomplete record verbatim as evidence.
    snap = incomplete_snapshot()
    receipt = evaluate_issue_closure(
        closure_request(satisfaction=snap), closure_snapshot()
    )
    assert receipt["admitted"] is True
    assert receipt["satisfaction"] == snap


def test_complete_satisfaction_with_foreign_snapshot_is_not_admitted():
    receipt = evaluate_issue_closure(
        closure_request(satisfaction=complete_snapshot()),
        closure_snapshot(9999),
    )
    assert receipt["admitted"] is False
    assert receipt["reason_codes"] == ["closure.issue-identity-mismatch"]


def test_verify_gate_rejects_authorization_bound_to_another_issue():
    req = closure_request(satisfaction=complete_snapshot())
    closure_snap = closure_snapshot()
    receipt = evaluate_issue_closure(req, closure_snap)
    other = closure_request(3306, satisfaction=complete_snapshot())
    other_auth = produce_lifecycle_mutation_authorization(
        other.decision, closure_snapshot(3306)
    )
    assert verify_closure_admission_receipt(
        receipt, authorization=other_auth, fresh_snapshot=closure_snap,
        acceptance=req.acceptance,
    ) is False


def test_batch_executes_with_complete_satisfaction_and_readback_verifies():
    snap = complete_snapshot()
    req = closure_request(satisfaction=snap)
    reader = FakeReader({3432: closure_snapshot()})
    writer = FakeWriter(reader)
    outcomes = run_closure_batch((req,), reader=reader, writer=writer)
    assert [o.status for o in outcomes] == ["closed-verified"]
    assert outcomes[0].readback_verified is True
    assert writer.calls == [(3432, "completed")]
    assert outcomes[0].receipt["satisfaction"] == snap


def test_batch_with_complete_satisfaction_but_no_decision_never_writes():
    req = closure_request(
        satisfaction=complete_snapshot(), decision_recorded=False
    )
    reader = FakeReader({3432: closure_snapshot()})
    writer = FakeWriter(reader)
    outcomes = run_closure_batch((req,), reader=reader, writer=writer)
    assert outcomes[0].status == "blocked"
    assert outcomes[0].reason_codes == ("closure.authorization-not-recorded",)
    assert writer.calls == []
