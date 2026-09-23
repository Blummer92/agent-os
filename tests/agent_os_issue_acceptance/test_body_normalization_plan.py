from __future__ import annotations

from scripts.agent_os_issue_acceptance.batch_body_normalization_plan import (
    BodyNormalizationClassification,
    durable_decision_sync_required,
    plan_body_normalization,
)
from scripts.agent_os_issue_acceptance.legacy_preflight import LegacyIssueSnapshot


def _snapshot(number: int, body: str, *, state: str = "open", updated: str = "2026-09-15T00:00:00Z") -> LegacyIssueSnapshot:
    return LegacyIssueSnapshot(number, f"Issue {number}", state, body, (), updated_at=updated)


def _canonical() -> str:
    return """## Issue tier
tier:1-standard-implementation
## Objective and value
Value
## Primary owner
owner:chatgpt-orchestrator
## Readiness candidate
status:ready
## Source of truth
GitHub
## External write boundary
no-external-write
## Scope and non-goals
Scope
## Allowed files, areas, or governed surfaces
scripts/
## Prior scope, duplicate, and supersession review
No duplicate.
## Documentation impact
docs-not-required
## Documentation exemption reason
No public behavior.
## Required tests, validation, and documentation
Tests
## Dependencies and blockers
None
## Acceptance criteria and definition of done
Done
"""


def test_canonical_body_is_no_change() -> None:
    assert plan_body_normalization([_snapshot(1, _canonical())]).assessments[0].classification is BodyNormalizationClassification.CANONICAL_NO_CHANGE


def test_missing_governance_fields_is_manual_review() -> None:
    assert plan_body_normalization([_snapshot(2, "## Objective\nBug")]).assessments[0].classification is BodyNormalizationClassification.MANUAL_REVIEW


def test_readiness_conflict_routes_2442() -> None:
    body = _canonical().replace("## Documentation exemption reason\nNo public behavior.\n", "").replace("docs-not-required", "docs-needs-decision")
    result = plan_body_normalization([_snapshot(3, body)]).assessments[0]
    assert result.classification is BodyNormalizationClassification.READINESS_BODY_CONFLICT
    assert result.route_issue == 2442


def test_stale_marker_routes_2441() -> None:
    assert plan_body_normalization([_snapshot(4, _canonical() + "\nDurable decision superseded.\n")]).assessments[0].route_issue == 2441


def test_durable_decision_sync_is_section_scoped_and_visible() -> None:
    owner = "owner:github-service-agent"
    assert durable_decision_sync_required(f"## Primary owner\n{owner}\n", "owner", owner) is False
    assert durable_decision_sync_required(f"## Notes\n{owner}\n## Primary owner\nowner:chatgpt-orchestrator\n", "owner", owner) is True
    assert durable_decision_sync_required(f"## Primary owner\n<!-- {owner} -->\nowner:chatgpt-orchestrator\n", "owner", owner) is True
    assert durable_decision_sync_required(f"## Primary owner\n{owner}-legacy\n", "owner", owner) is True


def test_durable_decision_sync_fails_closed_on_ambiguous_structure() -> None:
    owner = "owner:github-service-agent"
    assert durable_decision_sync_required("## Notes\nnone\n", "owner", owner) is None
    assert durable_decision_sync_required(f"## Owner\n{owner}\n## Primary owner\n{owner}\n", "owner", owner) is None
    assert durable_decision_sync_required("", "unknown", "value") is None


def test_transient_and_closed_evidence_never_requests_durable_sync() -> None:
    for field in ("pr-head", "ci-state", "runtime-state"):
        assert durable_decision_sync_required("", field, "current") is False
    assert durable_decision_sync_required("", "owner", "changed", state="closed") is False


def test_closed_issue_is_immutable() -> None:
    assert plan_body_normalization([_snapshot(5, _canonical(), state="closed")]).assessments[0].classification is BodyNormalizationClassification.CLOSED_IMMUTABLE


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
    assert all(not item.side_effects_performed for item in plan.assessments)
