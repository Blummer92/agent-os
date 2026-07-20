import pytest

from scripts.agent_os_issue_acceptance.sprint_dashboard import (
    Compatibility,
    RecommendationAction,
    RiskCategory,
    RiskEvidence,
    RiskSeverity,
    RiskStatus,
    SprintLaneEvidence,
    SprintMode,
    SuppliedSprintEvidence,
    recommended_merge_order,
    render_execution_prompt,
    render_risk_review_prompt,
    render_sprint_dashboard,
    risk_delta,
)


def _schema_risk():
    return RiskEvidence(
        risk_id="R-001",
        summary="renderer schema may drift before #379 is approved",
        category=RiskCategory.ARCHITECTURE,
        severity=RiskSeverity.HIGH,
        status=RiskStatus.ACTIVE,
        owner="issue:#379",
        affected_refs=("issue:#375", "issue:#379"),
        recommended_action=RecommendationAction.UPDATE_EXISTING_ISSUE,
        due_phase="before-merge",
        evidence_refs=("issue:#379",),
        previous_severity=RiskSeverity.MEDIUM,
        previous_status=RiskStatus.NEW,
    )


def _evidence(*, freshness="current"):
    return SuppliedSprintEvidence(
        sprint_goal="Test sprint",
        evaluated_at="2026-07-20T02:30:00Z",
        source_ids=("issue:374", "issue:375", "issue:376"),
        freshness=freshness,
        lanes=(
            SprintLaneEvidence(
                issue=374,
                title="Parent",
                mode=SprintMode.PLANNING_ONLY,
                compatibility=Compatibility.COMPATIBLE,
            ),
            SprintLaneEvidence(
                issue=375,
                title="Renderer",
                mode=SprintMode.IMPLEMENTATION,
                compatibility=Compatibility.COMPATIBLE,
                pull_request=401,
                risks=(_schema_risk(),),
            ),
            SprintLaneEvidence(
                issue=376,
                title="Evidence adapter",
                mode=SprintMode.REVIEW,
                compatibility=Compatibility.SEQUENTIAL_ONLY,
                blockers=("wait for renderer schema",),
            ),
        ),
        cloud_build_runs=None,
        builds_avoided=None,
    )


def test_dashboard_preserves_unknown_metrics_and_provenance():
    rendered = render_sprint_dashboard("Blummer92/agent-os", _evidence())

    assert "Mode: `supplied-evidence`" in rendered
    assert "Schema: `0.1.0` (provisional)" in rendered
    assert "Freshness: `current`" in rendered
    assert "Cloud Build runs: `unknown`" in rendered
    assert "Builds avoided: `unknown`" in rendered
    assert "`issue:374`" in rendered


def test_dashboard_risk_register_names_severity_issues_owner_and_action():
    rendered = render_sprint_dashboard("Blummer92/agent-os", _evidence())

    assert "## Risk register" in rendered
    assert "R-001" in rendered
    assert "high" in rendered
    assert "issue:#375, issue:#379" in rendered
    assert "issue:#379" in rendered
    assert "update-existing-issue" in rendered
    assert "## Recommended GitHub changes" in rendered


def test_risk_delta_tracks_new_status_and_severity_changes():
    evidence = SuppliedSprintEvidence(
        sprint_goal="Risk delta",
        evaluated_at="2026-07-20T02:30:00Z",
        source_ids=("issue:375",),
        freshness="current",
        lanes=(
            SprintLaneEvidence(
                issue=375,
                title="Renderer",
                mode=SprintMode.IMPLEMENTATION,
                compatibility=Compatibility.COMPATIBLE,
                risks=(
                    RiskEvidence(
                        risk_id="R-NEW",
                        summary="new validation risk",
                        category=RiskCategory.VALIDATION,
                        severity=RiskSeverity.HIGH,
                        status=RiskStatus.NEW,
                        owner="issue:#375",
                        affected_refs=("issue:#375",),
                        recommended_action=RecommendationAction.UPDATE_EXISTING_ISSUE,
                        due_phase="this-sprint",
                        previous_severity=RiskSeverity.MEDIUM,
                    ),
                    RiskEvidence(
                        risk_id="R-CLOSED",
                        summary="closed documentation risk",
                        category=RiskCategory.DOCUMENTATION,
                        severity=RiskSeverity.LOW,
                        status=RiskStatus.CLOSED,
                        owner="roadmap:#378",
                        affected_refs=("roadmap:#378",),
                        recommended_action=RecommendationAction.NO_ACTION,
                        due_phase="closed",
                        previous_severity=RiskSeverity.HIGH,
                    ),
                ),
            ),
        ),
    )

    assert risk_delta(evidence) == {
        "new": 1,
        "mitigated": 0,
        "closed": 1,
        "severity-increased": 1,
        "severity-decreased": 1,
        "unowned": 0,
    }


def test_risk_requires_owner_and_affected_reference():
    with pytest.raises(ValueError, match="owner"):
        RiskEvidence(
            risk_id="R-BAD",
            summary="unowned risk",
            category=RiskCategory.GOVERNANCE,
            severity=RiskSeverity.HIGH,
            status=RiskStatus.NEW,
            owner="",
            affected_refs=("issue:#375",),
            recommended_action=RecommendationAction.NEEDS_DECISION,
            due_phase="this-sprint",
        )

    with pytest.raises(ValueError, match="affect"):
        RiskEvidence(
            risk_id="R-BAD-2",
            summary="orphan risk",
            category=RiskCategory.GOVERNANCE,
            severity=RiskSeverity.HIGH,
            status=RiskStatus.NEW,
            owner="issue:#375",
            affected_refs=(),
            recommended_action=RecommendationAction.NEEDS_DECISION,
            due_phase="this-sprint",
        )


def test_stale_dashboard_warns_and_requires_review_state():
    rendered = render_sprint_dashboard(
        "Blummer92/agent-os", _evidence(freshness="stale")
    )

    assert "Sprint state: `review`" in rendered
    assert "requires manual review" in rendered


def test_prompts_are_short_and_name_all_issues():
    evidence = _evidence()
    execution = render_execution_prompt("Blummer92/agent-os", evidence)
    review = render_risk_review_prompt("Blummer92/agent-os", evidence)

    for value in ("#374", "#375", "#376"):
        assert value in execution
        assert value in review
    assert len(execution.splitlines()) < 12
    assert len(review.splitlines()) < 12


def test_merge_order_prioritizes_planning_and_review_before_implementation():
    assert recommended_merge_order(_evidence().lanes) == (374, 376, 375)


def test_duplicate_issue_numbers_are_rejected():
    lane = SprintLaneEvidence(
        issue=375,
        title="Renderer",
        mode=SprintMode.IMPLEMENTATION,
        compatibility=Compatibility.COMPATIBLE,
    )

    with pytest.raises(ValueError, match="unique"):
        SuppliedSprintEvidence(
            sprint_goal="Bad sprint",
            evaluated_at="2026-07-20T02:30:00Z",
            source_ids=("issue:375",),
            freshness="current",
            lanes=(lane, lane),
        )


def test_duplicate_risk_ids_are_rejected_across_lanes():
    risk = _schema_risk()
    with pytest.raises(ValueError, match="risk ids"):
        SuppliedSprintEvidence(
            sprint_goal="Bad risks",
            evaluated_at="2026-07-20T02:30:00Z",
            source_ids=("issue:375", "issue:379"),
            freshness="current",
            lanes=(
                SprintLaneEvidence(
                    issue=375,
                    title="Renderer",
                    mode=SprintMode.IMPLEMENTATION,
                    compatibility=Compatibility.COMPATIBLE,
                    risks=(risk,),
                ),
                SprintLaneEvidence(
                    issue=379,
                    title="Schema",
                    mode=SprintMode.PLANNING_ONLY,
                    compatibility=Compatibility.COMPATIBLE,
                    risks=(risk,),
                ),
            ),
        )


def test_unsupported_provisional_schema_version_is_rejected():
    with pytest.raises(ValueError, match="unsupported"):
        SuppliedSprintEvidence(
            sprint_goal="Bad version",
            evaluated_at="2026-07-20T02:30:00Z",
            source_ids=("issue:375",),
            freshness="current",
            lanes=(
                SprintLaneEvidence(
                    issue=375,
                    title="Renderer",
                    mode=SprintMode.IMPLEMENTATION,
                    compatibility=Compatibility.COMPATIBLE,
                ),
            ),
            schema_version="9.9.9",
        )
