from scripts.agent_os_issue_acceptance.sprint_dashboard import (
    Compatibility,
    SprintLaneEvidence,
    SprintMode,
    SuppliedSprintEvidence,
    recommended_merge_order,
    render_execution_prompt,
    render_risk_review_prompt,
    render_sprint_dashboard,
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
                risks=("schema drift",),
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
    assert "Freshness: `current`" in rendered
    assert "Cloud Build runs: `unknown`" in rendered
    assert "Builds avoided: `unknown`" in rendered
    assert "`issue:374`" in rendered


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

    try:
        SuppliedSprintEvidence(
            sprint_goal="Bad sprint",
            evaluated_at="2026-07-20T02:30:00Z",
            source_ids=("issue:375",),
            freshness="current",
            lanes=(lane, lane),
        )
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate lane issues must fail")
