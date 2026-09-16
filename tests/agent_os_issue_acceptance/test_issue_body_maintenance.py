from __future__ import annotations

from scripts.agent_os_issue_acceptance.issue_body_maintenance import (
    BodySyncDisposition,
    DecisionEvidenceClass,
    assess_durable_decision_sync,
    classify_decision_field,
    current_readiness_claims,
)


def assess(field: str, value: str, *, body: str, state: str = "open"):
    return assess_durable_decision_sync(
        issue_number=2438,
        issue_state=state,
        issue_body=body,
        decision_field=field,
        decision_value=value,
    )


def test_2438_durable_owner_decision_requires_body_sync() -> None:
    result = assess(
        "owner",
        "owner:github-service-agent",
        body="## Primary owner\nowner:chatgpt-orchestrator\n",
    )
    assert result.decision_class is DecisionEvidenceClass.DURABLE_CONTRACT
    assert result.disposition is BodySyncDisposition.BODY_SYNC_REQUIRED
    assert result.reason_codes == ("durable-decision-not-in-authoritative-body",)


def test_transient_pr_head_evidence_never_requests_body_sync() -> None:
    result = assess(
        "pr-head",
        "abc123",
        body="## Objective\nKeep the durable contract stable.\n",
    )
    assert result.decision_class is DecisionEvidenceClass.TRANSIENT_OPERATIONAL
    assert result.disposition is BodySyncDisposition.NO_SYNC_REQUIRED


def test_scope_and_protected_surface_changes_are_durable() -> None:
    for field, value in (
        ("scope", "scripts/agent_os_issue_acceptance/"),
        ("protected-surfaces", ".github/workflows/** remains excluded"),
    ):
        result = assess(field, value, body="## Objective\nBounded work\n")
        assert result.disposition is BodySyncDisposition.BODY_SYNC_REQUIRED


def test_unknown_decision_field_fails_closed_to_manual_review() -> None:
    result = assess("priority-vibe", "urgent", body="## Objective\nBounded work\n")
    assert result.decision_class is DecisionEvidenceClass.AMBIGUOUS
    assert result.disposition is BodySyncDisposition.MANUAL_REVIEW


def test_already_synchronized_durable_decision_is_noop() -> None:
    result = assess(
        "dependencies",
        "Depends on #2288 currentness.",
        body="## Dependencies\nDepends on #2288 currentness.\n",
    )
    assert result.disposition is BodySyncDisposition.NO_SYNC_REQUIRED
    assert result.reason_codes == ("durable-decision-already-synchronized",)


def test_duplicate_authoritative_sections_require_manual_review() -> None:
    result = assess(
        "objective",
        "New objective",
        body="## Objective\nOld\n## Objective and value\nOlder\n",
    )
    assert result.disposition is BodySyncDisposition.MANUAL_REVIEW
    assert result.reason_codes == ("multiple-authoritative-body-sections",)


def test_closed_issue_body_is_immutable() -> None:
    result = assess(
        "owner",
        "owner:github-service-agent",
        body="## Primary owner\nowner:chatgpt-orchestrator\n",
        state="closed",
    )
    assert result.disposition is BodySyncDisposition.CLOSED_IMMUTABLE
    assert result.side_effects_performed is False
    assert result.authority_created is False


def test_readback_mismatch_remains_sync_required() -> None:
    proposed = "owner:github-service-agent"
    prewrite = assess(
        "owner",
        proposed,
        body="## Primary owner\nowner:chatgpt-orchestrator\n",
    )
    postwrite = assess(
        "owner",
        proposed,
        body="## Primary owner\nowner:chatgpt-orchestrator\n",
    )
    assert prewrite.disposition is BodySyncDisposition.BODY_SYNC_REQUIRED
    assert postwrite.disposition is BodySyncDisposition.BODY_SYNC_REQUIRED


def test_readiness_parser_is_shared_and_ignores_historical_claims() -> None:
    claims = current_readiness_claims(
        "Historical state: previously\nstatus:ready\nReadiness: status:blocked\n"
    )
    assert claims == ("blocked",)


def test_classification_is_finite_and_non_authorizing() -> None:
    assert classify_decision_field("lifecycle-disposition") is DecisionEvidenceClass.DURABLE_CONTRACT
    result = assess("ci-state", "success", body="")
    assert result.authority_created is False
    assert result.side_effects_performed is False
