from scripts.agent_os_issue_acceptance.issue_body_sync import (
    BodyNormalizationClassification,
    BodyReadinessDriftStatus,
    detect_body_readiness_drift,
    plan_body_normalization,
)
from scripts.agent_os_issue_acceptance.legacy_preflight import LegacyIssueSnapshot
from scripts.agent_os_issue_acceptance.readiness import evaluate_issue_readiness


def canonical_body(readiness: str = "ready") -> str:
    return f"""
Issue Tier: 1
## Objective
Add a report-only checker.
## Value
Keep issue contracts current.
## Owner
GitHub Service Agent
## Readiness candidate
status:{readiness}
## Source of truth
GitHub
## External write boundary
no-external-write
## Scope
Checker only.
## Non-goals
No writes.
## Allowed Files
scripts/agent_os_issue_acceptance/
## Validation
pytest tests/agent_os_issue_acceptance
## Documentation
Update issue lifecycle docs.
## Dependencies
none
## Acceptance Criteria
Checker reports deterministically.
## Definition Of Done
Focused tests pass.
## Prior scope, duplicate, and supersession review
Reviewed #2441 and #2442; no duplicate implementation owner.
## Documentation impact
docs-required
## Required documentation paths or bounded areas
01_Shared_Standards/github/issue-lifecycle-standard.md
## Expected documentation change
Document report-only issue body synchronization evidence.
"""


def snap(number: int, body: str, *, state: str = "open", updated_at: str = "2026-09-15T00:00:00Z") -> LegacyIssueSnapshot:
    return LegacyIssueSnapshot(
        number=number,
        title="Issue",
        state=state,
        body=body,
        labels=(),
        updated_at=updated_at,
    )


def test_ready_claim_drifting_to_needs_decision_is_reported() -> None:
    body = canonical_body().replace(
        "## Prior scope, duplicate, and supersession review\nReviewed #2441 and #2442; no duplicate implementation owner.\n",
        "",
    )
    result = detect_body_readiness_drift(body, evaluate_issue_readiness(body))
    assert result.status is BodyReadinessDriftStatus.DRIFT
    assert result.claimed_readiness == "ready"
    assert result.canonical_readiness == "needs-decision"
    assert result.side_effects_performed is False


def test_ready_claim_drifting_to_blocked_is_reported() -> None:
    body = canonical_body().replace("## Dependencies\nnone", "## Dependencies\nBlocked by: #100")
    result = detect_body_readiness_drift(body, evaluate_issue_readiness(body))
    assert result.status is BodyReadinessDriftStatus.DRIFT
    assert result.canonical_readiness == "blocked"


def test_matching_and_absent_claims_are_no_drift() -> None:
    body = canonical_body()
    matching = detect_body_readiness_drift(body, evaluate_issue_readiness(body))
    absent_body = body.replace("## Readiness candidate\nstatus:ready\n", "")
    absent = detect_body_readiness_drift(absent_body, evaluate_issue_readiness(absent_body))
    assert matching.status is BodyReadinessDriftStatus.NO_DRIFT
    assert absent.status is BodyReadinessDriftStatus.NO_DRIFT
    assert absent.claimed_readiness is None


def test_historical_readiness_does_not_create_current_claim() -> None:
    body = canonical_body().replace(
        "## Readiness candidate\nstatus:ready\n",
        "Historical readiness\nstatus:blocked\n\n",
    )
    result = detect_body_readiness_drift(body, evaluate_issue_readiness(body))
    assert result.status is BodyReadinessDriftStatus.NO_DRIFT
    assert result.claimed_readiness is None


def test_multiple_current_claims_fail_closed() -> None:
    body = canonical_body() + "\nReadiness: status:blocked\n"
    result = detect_body_readiness_drift(body, evaluate_issue_readiness(body))
    assert result.status is BodyReadinessDriftStatus.MANUAL_REVIEW


def test_canonical_body_requires_no_normalization() -> None:
    plan = plan_body_normalization((snap(1, canonical_body()),))
    assert plan.assessments[0].classification is BodyNormalizationClassification.CANONICAL_NO_CHANGE
    assert plan.proposed_mutation_count == 0
    assert plan.side_effects_performed is False


def test_explicit_equivalent_free_form_fields_can_be_mechanical_candidates() -> None:
    body = canonical_body().replace("## Source of truth\nGitHub\n", "Source of truth: GitHub\n")
    plan = plan_body_normalization((snap(2, body),))
    item = plan.assessments[0]
    assert item.classification is BodyNormalizationClassification.MECHANICAL_CANDIDATE
    assert item.proposed_sections == ("source of truth",)


def test_missing_governance_value_requires_manual_review() -> None:
    body = canonical_body().replace("## Source of truth\nGitHub\n", "")
    plan = plan_body_normalization((snap(3, body),))
    assert plan.assessments[0].classification is BodyNormalizationClassification.MANUAL_REVIEW
    assert "decision-required:source of truth" in plan.assessments[0].reason_codes


def test_readiness_conflict_routes_to_2442() -> None:
    body = canonical_body().replace(
        "## Prior scope, duplicate, and supersession review\nReviewed #2441 and #2442; no duplicate implementation owner.\n",
        "",
    )
    item = plan_body_normalization((snap(4, body),)).assessments[0]
    assert item.classification is BodyNormalizationClassification.READINESS_BODY_CONFLICT
    assert item.route_issue == 2442


def test_stale_marker_routes_to_2441() -> None:
    body = canonical_body() + "\nStale durable decision: body synchronization required.\n"
    item = plan_body_normalization((snap(5, body),)).assessments[0]
    assert item.classification is BodyNormalizationClassification.STALE_DURABLE_DECISION
    assert item.route_issue == 2441


def test_closed_is_immutable_and_batch_continues_after_manual_review() -> None:
    missing = canonical_body().replace("## Source of truth\nGitHub\n", "")
    plan = plan_body_normalization(
        (
            snap(6, missing),
            snap(7, canonical_body(), state="closed"),
            snap(8, canonical_body()),
        )
    )
    assert [item.classification for item in plan.assessments] == [
        BodyNormalizationClassification.MANUAL_REVIEW,
        BodyNormalizationClassification.CLOSED_IMMUTABLE,
        BodyNormalizationClassification.CANONICAL_NO_CHANGE,
    ]


def test_duplicate_snapshots_choose_newest_and_rerun_is_deterministic() -> None:
    old = snap(9, canonical_body().replace("## Source of truth\nGitHub\n", ""), updated_at="2026-09-14T00:00:00Z")
    new = snap(9, canonical_body(), updated_at="2026-09-15T00:00:00Z")
    first = plan_body_normalization((old, new))
    second = plan_body_normalization((old, new))
    assert first == second
    assert first.assessments[0].classification is BodyNormalizationClassification.CANONICAL_NO_CHANGE
    assert first.proposed_mutation_count == 0
