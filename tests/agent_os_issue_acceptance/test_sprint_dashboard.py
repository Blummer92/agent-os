import json

import pytest

from scripts.agent_os_issue_acceptance.sprint_dashboard import (
    Compatibility,
    DecisionEvidence,
    FinalHandoff,
    RecommendationAction,
    RecommendationEvidence,
    RiskCategory,
    RiskEvidence,
    RiskSeverity,
    RiskStatus,
    SourceEvidence,
    SprintLaneEvidence,
    SprintMode,
    SuppliedSprintEvidence,
    ValidationEvidence,
    canonical_sprint_payload,
    recommended_merge_order,
    render_execution_prompt,
    render_risk_review_prompt,
    render_sprint_dashboard,
    render_sprint_governance_report,
    risk_delta,
    serialize_sprint_evidence,
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
        evidence_refs=("pr:#381",),
        previous_severity=RiskSeverity.MEDIUM,
        previous_status=RiskStatus.NEW,
    )


def _evidence(*, freshness="current", mode="supplied-evidence"):
    state = "active" if freshness == "current" else "review"
    sources = ()
    if mode == "connected-read-only":
        sources = (
            SourceEvidence(
                object_type="issue",
                object_id="375",
                repository="Blummer92/agent-os",
                retrieved_at="2026-07-20T02:30:00Z",
                updated_at="2026-07-20T02:20:00Z",
                result_status="complete",
                permission_status="allowed",
                pagination_status="complete",
            ),
        )
    return SuppliedSprintEvidence(
        sprint_id="sprint-2026-07-20-a",
        sprint_goal="Test sprint",
        sprint_state=state,
        evidence_mode=mode,
        evaluated_at="2026-07-20T02:30:00Z",
        freshness=freshness,
        sources=sources,
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
                pull_request=380,
                risk_ids=("R-001",),
            ),
            SprintLaneEvidence(
                issue=376,
                title="Evidence adapter",
                mode=SprintMode.REVIEW,
                compatibility=Compatibility.SEQUENTIAL_ONLY,
                blockers=("wait for renderer schema",),
            ),
        ),
        risks=(_schema_risk(),),
        decisions=(
            DecisionEvidence(
                decision_id="D-001",
                summary="Keep evidence implementation sequential",
                rationale="The normalized schema must stabilize first",
                affected_refs=("issue:#376", "issue:#379"),
            ),
        ),
        recommendations=(
            RecommendationEvidence(
                recommendation_id="REC-001",
                action=RecommendationAction.UPDATE_EXISTING_ISSUE,
                targets=("issue:#375", "issue:#379"),
                rationale="Reconcile renderer fields with the approved schema",
                risk_ids=("R-001",),
            ),
        ),
        validation=ValidationEvidence(
            tests_run=("pytest test_sprint_dashboard.py",),
            docs_updated=("sprint-reporting-schema.md",),
            repository_validation="pending",
            status_checks="not-posted",
            cloud_build_runs=0,
            builds_avoided=None,
            evidence_refs=("pr:#380",),
        ),
        final_handoff=FinalHandoff(
            files_changed=("sprint_dashboard.py",),
            tests_run=("pytest test_sprint_dashboard.py",),
            docs_updated=("sprint-reporting-schema.md",),
            unresolved_blockers=("aggregate validation pending",),
            handoff_recommendations=("review schema first",),
            remaining_risks=("live evidence behavior unproven",),
        ),
    )


def test_dashboard_reports_schema_risks_issue_impact_and_validation():
    rendered = render_sprint_dashboard("Blummer92/agent-os", _evidence())

    assert "Mode: `supplied-evidence`" in rendered
    assert "Schema: `0.1.0`" in rendered
    assert "## Risk register" in rendered
    assert "R-001" in rendered
    assert "issue:#375, issue:#379" in rendered
    assert "## Issue impact" in rendered
    assert "update-existing-issue" in rendered
    assert "Repository validation: `pending`" in rendered
    assert "Status checks: `not-posted`" in rendered


def test_governance_report_includes_decisions_provenance_and_handoff():
    rendered = render_sprint_governance_report(
        "Blummer92/agent-os", _evidence(mode="connected-read-only")
    )

    assert "# Sprint Governance Report" in rendered
    assert "D-001" in rendered
    assert "issue:375" in rendered
    assert "## Final handoff" in rendered
    assert "aggregate validation pending" in rendered


def test_canonical_payload_is_deterministic_and_contains_risk_delta():
    evidence = _evidence()
    first = serialize_sprint_evidence(evidence)
    second = serialize_sprint_evidence(evidence)

    assert first == second
    payload = json.loads(first)
    assert payload["schema_version"] == "0.1.0"
    assert payload["risk_delta"]["severity-increased"] == 1
    assert canonical_sprint_payload(evidence)["risk_delta"]["unowned"] == 0


def test_risk_delta_tracks_lifecycle_and_unowned_risks():
    unowned = RiskEvidence(
        risk_id="R-NEW",
        summary="ownership decision required",
        category=RiskCategory.GOVERNANCE,
        severity=RiskSeverity.HIGH,
        status=RiskStatus.BLOCKED,
        owner="needs-decision",
        affected_refs=("roadmap:#378",),
        recommended_action=RecommendationAction.NEEDS_DECISION,
        due_phase="this-sprint",
    )
    closed = RiskEvidence(
        risk_id="R-CLOSED",
        summary="line limit fixed",
        category=RiskCategory.DOCUMENTATION,
        severity=RiskSeverity.LOW,
        status=RiskStatus.CLOSED,
        owner="issue:#376",
        affected_refs=("issue:#376",),
        recommended_action=RecommendationAction.NO_ACTION,
        due_phase="closed",
        previous_severity=RiskSeverity.HIGH,
        previous_status=RiskStatus.ACTIVE,
    )
    base = _evidence()
    evidence = SuppliedSprintEvidence(
        sprint_id=base.sprint_id,
        sprint_goal=base.sprint_goal,
        sprint_state=base.sprint_state,
        evidence_mode=base.evidence_mode,
        evaluated_at=base.evaluated_at,
        freshness=base.freshness,
        sources=base.sources,
        lanes=base.lanes,
        risks=(unowned, closed, _schema_risk()),
        decisions=base.decisions,
        recommendations=base.recommendations,
        validation=base.validation,
        final_handoff=base.final_handoff,
    )

    assert risk_delta(evidence) == {
        "new": 1,
        "mitigated": 0,
        "closed": 1,
        "severity-increased": 1,
        "severity-decreased": 1,
        "unowned": 1,
    }


def test_non_current_evidence_requires_review_state():
    base = _evidence()
    with pytest.raises(ValueError, match="non-current"):
        SuppliedSprintEvidence(
            sprint_id=base.sprint_id,
            sprint_goal=base.sprint_goal,
            sprint_state="active",
            evidence_mode=base.evidence_mode,
            evaluated_at=base.evaluated_at,
            freshness="stale",
            sources=base.sources,
            lanes=base.lanes,
            risks=base.risks,
            decisions=base.decisions,
            recommendations=base.recommendations,
            validation=base.validation,
            final_handoff=base.final_handoff,
        )


def test_connected_mode_requires_sources():
    base = _evidence()
    with pytest.raises(ValueError, match="requires sources"):
        SuppliedSprintEvidence(
            sprint_id=base.sprint_id,
            sprint_goal=base.sprint_goal,
            sprint_state=base.sprint_state,
            evidence_mode="connected-read-only",
            evaluated_at=base.evaluated_at,
            freshness=base.freshness,
            sources=(),
            lanes=base.lanes,
            risks=base.risks,
            decisions=base.decisions,
            recommendations=base.recommendations,
            validation=base.validation,
            final_handoff=base.final_handoff,
        )


def test_unresolved_lane_risk_is_rejected():
    base = _evidence()
    bad_lane = SprintLaneEvidence(
        issue=375,
        title="Renderer",
        mode=SprintMode.IMPLEMENTATION,
        compatibility=Compatibility.COMPATIBLE,
        risk_ids=("R-MISSING",),
    )
    with pytest.raises(ValueError, match="resolve"):
        SuppliedSprintEvidence(
            sprint_id=base.sprint_id,
            sprint_goal=base.sprint_goal,
            sprint_state=base.sprint_state,
            evidence_mode=base.evidence_mode,
            evaluated_at=base.evaluated_at,
            freshness=base.freshness,
            sources=base.sources,
            lanes=(bad_lane,),
            risks=base.risks,
            decisions=base.decisions,
            recommendations=base.recommendations,
            validation=base.validation,
            final_handoff=base.final_handoff,
        )


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
    base = _evidence()
    lane = base.lanes[0]
    with pytest.raises(ValueError, match="unique"):
        SuppliedSprintEvidence(
            sprint_id=base.sprint_id,
            sprint_goal=base.sprint_goal,
            sprint_state=base.sprint_state,
            evidence_mode=base.evidence_mode,
            evaluated_at=base.evaluated_at,
            freshness=base.freshness,
            sources=base.sources,
            lanes=(lane, lane),
            risks=base.risks,
            decisions=base.decisions,
            recommendations=base.recommendations,
            validation=base.validation,
            final_handoff=base.final_handoff,
        )


def test_invalid_timestamp_and_schema_version_are_rejected():
    base = _evidence()
    with pytest.raises(ValueError, match="RFC3339"):
        SuppliedSprintEvidence(
            sprint_id=base.sprint_id,
            sprint_goal=base.sprint_goal,
            sprint_state=base.sprint_state,
            evidence_mode=base.evidence_mode,
            evaluated_at="not-a-timestamp",
            freshness=base.freshness,
            sources=base.sources,
            lanes=base.lanes,
            risks=base.risks,
            decisions=base.decisions,
            recommendations=base.recommendations,
            validation=base.validation,
            final_handoff=base.final_handoff,
        )

    with pytest.raises(ValueError, match="unsupported"):
        SuppliedSprintEvidence(
            sprint_id=base.sprint_id,
            sprint_goal=base.sprint_goal,
            sprint_state=base.sprint_state,
            evidence_mode=base.evidence_mode,
            evaluated_at=base.evaluated_at,
            freshness=base.freshness,
            sources=base.sources,
            lanes=base.lanes,
            risks=base.risks,
            decisions=base.decisions,
            recommendations=base.recommendations,
            validation=base.validation,
            final_handoff=base.final_handoff,
            schema_version="9.9.9",
        )
