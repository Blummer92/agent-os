from __future__ import annotations

from scripts.agent_os_issue_acceptance.batch_readiness_body_drift import (
    BodyReadinessDriftStatus,
    detect_body_readiness_drift,
)
from scripts.agent_os_issue_acceptance.models import AcceptanceReport, Status
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome, ReadinessResult


def _result(outcome: ReadinessOutcome) -> ReadinessResult:
    return ReadinessResult(
        outcome=outcome,
        report=AcceptanceReport(
            linked_issue=None,
            overall_status=Status.PASS,
            checks=[],
            manual_review_items=[],
            blockers=[],
            evidence=[],
            remaining_risks=[],
        ),
    )


def test_ready_claim_drift_to_needs_decision() -> None:
    result = detect_body_readiness_drift(
        "## Readiness candidate\nstatus:ready",
        _result(ReadinessOutcome.NEEDS_DECISION),
    )
    assert result.status is BodyReadinessDriftStatus.DRIFT
    assert result.reason_codes == ("body-readiness-drift:ready->needs-decision",)


def test_ready_claim_drift_to_blocked() -> None:
    result = detect_body_readiness_drift(
        "Readiness: status:ready", _result(ReadinessOutcome.BLOCKED)
    )
    assert result.status is BodyReadinessDriftStatus.DRIFT


def test_matching_claim_is_converged() -> None:
    result = detect_body_readiness_drift(
        "status:blocked", _result(ReadinessOutcome.BLOCKED)
    )
    assert result.status is BodyReadinessDriftStatus.NO_DRIFT


def test_absent_claim_is_not_inferred() -> None:
    result = detect_body_readiness_drift(
        "## Objective\nFix it", _result(ReadinessOutcome.READY)
    )
    assert result.claimed_readiness is None
    assert result.status is BodyReadinessDriftStatus.NO_DRIFT


def test_historical_claim_is_ignored() -> None:
    result = detect_body_readiness_drift(
        "Historical state: previously\nstatus:ready",
        _result(ReadinessOutcome.NEEDS_DECISION),
    )
    assert result.claimed_readiness is None


def test_multiple_current_claims_fail_closed() -> None:
    result = detect_body_readiness_drift(
        "status:ready\nstatus:blocked", _result(ReadinessOutcome.NEEDS_DECISION)
    )
    assert result.status is BodyReadinessDriftStatus.MANUAL_REVIEW


def test_projection_is_report_only() -> None:
    result = detect_body_readiness_drift(
        "status:ready", _result(ReadinessOutcome.READY)
    )
    assert result.authority_created is False
    assert result.side_effects_performed is False
