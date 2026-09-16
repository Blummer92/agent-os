from __future__ import annotations

from scripts.agent_os_issue_acceptance.issue_body_maintenance import (
    assess_durable_decision_sync,
    current_readiness_claims,
)


def assess(field: str, value: str, *, body: str, state: str = "open"):
    return assess_durable_decision_sync(
        issue_state=state,
        issue_body=body,
        decision_field=field,
        decision_value=value,
    )


def test_2438_durable_owner_decision_requires_body_sync() -> None:
    result = assess(
        "owner", "owner:github-service-agent",
        body="## Primary owner\nowner:chatgpt-orchestrator\n",
    )
    assert result.disposition == "body-sync-required"


def test_transient_evidence_never_requests_body_sync() -> None:
    for field in ("pr-head", "ci-state", "runtime-state"):
        assert assess(field, "current", body="## Objective\nStable\n").disposition == "no-sync-required"


def test_durable_scope_and_protected_surface_changes_require_sync() -> None:
    for field in ("scope", "protected-surfaces"):
        assert assess(field, "changed", body="## Objective\nStable\n").disposition == "body-sync-required"


def test_unknown_or_duplicate_contract_fails_closed() -> None:
    assert assess("priority-vibe", "urgent", body="").disposition == "manual-review"
    duplicate = assess(
        "objective", "New",
        body="## Objective\nOld\n## Objective and value\nOlder\n",
    )
    assert duplicate.disposition == "manual-review"


def test_synchronized_body_is_noop_and_closed_body_is_immutable() -> None:
    synced = assess(
        "dependencies", "Depends on #2288 currentness.",
        body="## Dependencies\nDepends on #2288 currentness.\n",
    )
    assert synced.disposition == "no-sync-required"
    closed = assess("owner", "changed", body="## Primary owner\nold\n", state="closed")
    assert closed.disposition == "closed-immutable"
    assert closed.authority_created is False
    assert closed.side_effects_performed is False


def test_readback_mismatch_remains_sync_required() -> None:
    stale = "## Primary owner\nowner:chatgpt-orchestrator\n"
    for _ in range(2):
        assert assess("owner", "owner:github-service-agent", body=stale).disposition == "body-sync-required"


def test_shared_readiness_parser_ignores_historical_claims() -> None:
    assert current_readiness_claims(
        "Historical state: previously\nstatus:ready\nReadiness: status:blocked\n"
    ) == ("blocked",)
