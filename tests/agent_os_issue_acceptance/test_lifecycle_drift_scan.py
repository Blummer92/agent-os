from scripts.agent_os_issue_acceptance.lifecycle_drift_scan import LifecycleDriftEvidence, scan_lifecycle_drift


def test_scan_finds_merged_open_and_closed_stale_status_without_issue_numbers():
    result = scan_lifecycle_drift((LifecycleDriftEvidence(9, "closed", "closed", ("status:ready",)), LifecycleDriftEvidence(3, "open", "merged"), LifecycleDriftEvidence(4, "closed", "closed", ("human:keep",))))
    assert [(item.issue_number, item.reason_code) for item in result.candidates] == [(3, "reconciliation.merged-pr-open-issue"), (9, "reconciliation.closed-with-ready-label")]
    assert result.side_effects_performed is False


def test_scan_is_bounded_deterministic_and_reports_outstanding():
    result = scan_lifecycle_drift(tuple(LifecycleDriftEvidence(number, "open", "merged") for number in range(10, 0, -1)), limit=3)
    assert [item.issue_number for item in result.candidates] == [1, 2, 3]
    assert result.outstanding_count == 7


def test_scan_fails_closed_on_conflict_parent_or_stale_evidence():
    result = scan_lifecycle_drift((LifecycleDriftEvidence(1, "open", "merged", conflicting_primary_claim=True), LifecycleDriftEvidence(2, "open", "merged", parent_or_meta=True), LifecycleDriftEvidence(3, "open", "merged", stale=True)))
    assert result.candidates == ()
    assert result.excluded_issue_numbers == (1, 2, 3)
