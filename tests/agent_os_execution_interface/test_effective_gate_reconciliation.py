from dataclasses import replace

import pytest

from scripts.agent_os_execution_interface.effective_gate_reconciliation import (
    EffectiveGateState, EvidenceDisposition, GateEvidence, GateIdentity,
    GateMarker, reconcile_effective_gate,
)

IDENTITY = GateIdentity(repository="Blummer92/agent-os", issue_number=1235, pull_request_number=77, sha="a" * 40)
MARKER = GateMarker(gate_id="measurement", recorded_at="2026-08-17T00:00:00Z", evidence_owner="qa", source_ref="issue-body")

def ev(*, at="2026-08-18T00:00:00Z", disposition=EvidenceDisposition.SATISFIED, authoritative=True, owner="qa", identity=IDENTITY, ref="comment-1", gate_id="measurement"):
    return GateEvidence(gate_id=gate_id, recorded_at=at, evidence_owner=owner, source_ref=ref, disposition=disposition, identity=identity, authoritative=authoritative)

def test_newer_dependency_measurement_satisfies_stale_gate():
    assert reconcile_effective_gate(marker=MARKER, expected_identity=IDENTITY, evidence=[ev()]).state is EffectiveGateState.SATISFIED

def test_stale_block_label_is_not_decisive_when_newer_owner_evidence_satisfies():
    result = reconcile_effective_gate(marker=MARKER, expected_identity=IDENTITY, evidence=[ev(ref="dependency-520")])
    assert result.state is EffectiveGateState.SATISFIED
    assert result.selected_evidence_refs == ("dependency-520",)

def test_newer_informational_comment_does_not_supersede_gate():
    assert reconcile_effective_gate(marker=MARKER, expected_identity=IDENTITY, evidence=[ev(authoritative=False)]).state is EffectiveGateState.BLOCKED

def test_different_sha_pr_or_issue_is_ignored():
    wrong = GateIdentity(repository="Blummer92/agent-os", issue_number=1235, pull_request_number=77, sha="b" * 40)
    assert reconcile_effective_gate(marker=MARKER, expected_identity=IDENTITY, evidence=[ev(identity=wrong)]).state is EffectiveGateState.BLOCKED

def test_conflicting_newest_authoritative_evidence_requires_manual_review():
    result = reconcile_effective_gate(marker=MARKER, expected_identity=IDENTITY, evidence=[ev(ref="a"), ev(ref="b", disposition=EvidenceDisposition.BLOCKED)])
    assert result.state is EffectiveGateState.MANUAL_REVIEW

def test_dependency_closure_without_evidence_does_not_satisfy_gate():
    assert reconcile_effective_gate(marker=MARKER, expected_identity=IDENTITY, evidence=[]).state is EffectiveGateState.BLOCKED

def test_later_authoritative_evidence_can_reopen_blocker():
    result = reconcile_effective_gate(marker=MARKER, expected_identity=IDENTITY, evidence=[ev(at="2026-08-18T00:00:00Z"), ev(at="2026-08-19T00:00:00Z", disposition=EvidenceDisposition.BLOCKED, ref="reopened")])
    assert result.state is EffectiveGateState.BLOCKED
    assert result.selected_evidence_refs == ("reopened",)

def test_no_linked_evidence_owner_preserves_fail_closed_behavior():
    marker = GateMarker(gate_id="measurement", recorded_at=MARKER.recorded_at, evidence_owner=None, source_ref="issue-body")
    assert reconcile_effective_gate(marker=marker, expected_identity=IDENTITY, evidence=[ev()]).reason_codes == ("no-linked-evidence-owner",)

def test_duplicate_replayed_evidence_is_idempotent():
    evidence = ev(ref="same")
    one = reconcile_effective_gate(marker=MARKER, expected_identity=IDENTITY, evidence=[evidence])
    two = reconcile_effective_gate(marker=MARKER, expected_identity=IDENTITY, evidence=[evidence, evidence])
    assert one == two

def test_reconciliation_never_grants_excluded_authority():
    result = reconcile_effective_gate(marker=MARKER, expected_identity=IDENTITY, evidence=[ev()])
    assert result.repository_implementation_authorized is False
    assert result.merge_authorized is False
    assert result.issue_closure_authorized is False
    assert result.protected_setting_authorized is False
    assert result.production_authorized is False
    assert result.external_writes_authorized is False


@pytest.mark.parametrize("changes", [
    {"repository": "Other/agent-os"},
    {"issue_number": 999},
    {"pull_request_number": 999},
])
def test_each_identity_field_independently_blocks_unrelated_evidence(changes):
    wrong = replace(IDENTITY, **changes)
    result = reconcile_effective_gate(
        marker=MARKER, expected_identity=IDENTITY,
        evidence=[ev(identity=wrong)]
    )
    assert result.state is EffectiveGateState.BLOCKED
    assert result.selected_evidence_refs == ()

def test_invalid_non_string_timestamp_raises_value_error():
    with pytest.raises(ValueError, match="RFC3339"):
        reconcile_effective_gate(
            marker=replace(MARKER, recorded_at=None),
            expected_identity=IDENTITY,
            evidence=[]
        )

def test_missing_owner_preserves_explicit_blocked_state():
    result = reconcile_effective_gate(
        marker=replace(MARKER, evidence_owner=None),
        expected_identity=IDENTITY,
        evidence=[ev()]
    )
    assert result.state is EffectiveGateState.BLOCKED
    assert result.selected_evidence_refs == ()

def test_duplicate_before_newer_evidence_does_not_stop_reconciliation():
    old = ev(ref="old")
    newer = ev(
        at="2026-08-19T00:00:00Z",
        disposition=EvidenceDisposition.BLOCKED,
        ref="newer"
    )
    result = reconcile_effective_gate(
        marker=MARKER, expected_identity=IDENTITY,
        evidence=[old, old, newer]
    )
    assert result.state is EffectiveGateState.BLOCKED
    assert result.selected_evidence_refs == ("newer",)

def test_conflicting_newest_evidence_preserves_both_references():
    result = reconcile_effective_gate(
        marker=MARKER, expected_identity=IDENTITY,
        evidence=[
            ev(ref="a"),
            ev(ref="b", disposition=EvidenceDisposition.BLOCKED)
        ]
    )
    assert result.state is EffectiveGateState.MANUAL_REVIEW
    assert result.selected_evidence_refs == ("a", "b")
