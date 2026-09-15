from __future__ import annotations

from scripts.agent_os_issue_acceptance.body_normalization_plan import (
    BodyNormalizationClassification,
    plan_body_normalization,
)
from scripts.agent_os_issue_acceptance.legacy_preflight import LegacyIssueSnapshot


def _snapshot(number: int, body: str, *, state: str = "open", updated: str = "2026-09-15T00:00:00Z") -> LegacyIssueSnapshot:
    return LegacyIssueSnapshot(number=number, body=body, state=state, updated_at=updated)


def _canonical() -> str:
    return """## Issue tier\ntier:1-standard-implementation\n## Objective and value\nValue\n## Primary owner\nowner:chatgpt-orchestrator\n## Readiness candidate\nstatus:ready\n## Source of truth\nGitHub\n## External write boundary\nno-external-write\n## Scope and non-goals\nScope\n## Allowed files, areas, or governed surfaces\nscripts/\n## Prior scope, duplicate, and supersession review\nNo duplicate.\n## Documentation impact\ndocs-not-required\n## Documentation exemption reason\nNo public behavior.\n## Required tests, validation, and documentation\nTests\n## Dependencies and blockers\nNone\n## Acceptance criteria and definition of done\nDone\n"""


def test_canonical_body_is_no_change() -> None:
    plan = plan_body_normalization([_snapshot(1, _canonical())])
    assert plan.assessments[0].classification is BodyNormalizationClassification.CANONICAL_NO_CHANGE


def test_missing_governance_fields_is_manual_review() -> None:
    plan = plan_body_normalization([_snapshot(2, "## Objective\nBug")])
    assert plan.assessments[0].classification is BodyNormalizationClassification.MANUAL_REVIEW


def test_readiness_conflict_routes_2442() -> None:
    body = _canonical().replace("## Documentation exemption reason\nNo public behavior.\n", "").replace("docs-not-required", "docs-needs-decision")
    plan = plan_body_normalization([_snapshot(3, body)])
    assert plan.assessments[0].classification is BodyNormalizationClassification.READINESS_BODY_CONFLICT
    assert plan.assessments[0].route_issue == 2442


def test_stale_marker_routes_2441() -> None:
    body = _canonical() + "\nDurable decision superseded.\n"
    plan = plan_body_normalization([_snapshot(4, body)])
    assert plan.assessments[0].route_issue == 2441


def test_closed_issue_is_immutable() -> None:
    plan = plan_body_normalization([_snapshot(5, _canonical(), state="closed")])
    assert plan.assessments[0].classification is BodyNormalizationClassification.CLOSED_IMMUTABLE


def test_batch_continues_after_manual_review() -> None:
    plan = plan_body_normalization([_snapshot(6, "## Objective\nMissing"), _snapshot(7, _canonical())])
    assert len(plan.assessments) == 2
    assert plan.assessments[1].classification is BodyNormalizationClassification.CANONICAL_NO_CHANGE


def test_newest_duplicate_snapshot_wins_deterministically() -> None:
    plan = plan_body_normalization([
        _snapshot(8, "## Objective\nOld", updated="2026-09-14T00:00:00Z"),
        _snapshot(8, _canonical(), updated="2026-09-15T00:00:00Z"),
    ])
    assert len(plan.assessments) == 1
    assert plan.assessments[0].classification is BodyNormalizationClassification.CANONICAL_NO_CHANGE


def test_plan_is_report_only() -> None:
    plan = plan_body_normalization([_snapshot(9, _canonical())])
    assert plan.authority_created is False
    assert plan.side_effects_performed is False
    assert all(a.side_effects_performed is False for a in plan.assessments)
