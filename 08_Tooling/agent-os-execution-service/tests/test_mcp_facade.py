from __future__ import annotations

import pytest

from agent_os_execution_service.mcp_facade import (
    classify_agent_os_continuation,
    plan_agent_os_continuation,
)


def test_plan_without_handoff_requires_server_side_discovery() -> None:
    result = plan_agent_os_continuation(
        repository="Blummer92/agent-os", issue_number=1233
    )
    assert result["next_operation"] == "discover-current-handoff"
    assert result["handoff_id"] is None
    assert result["ingress"] is None
    assert result["execution_authorized"] is False
    assert result["github_writes_authorized"] is False
    assert result["scheduler_invoked"] is False
    assert result["side_effects_performed"] is False


def test_plan_preserves_canonical_handoff_byte_for_byte() -> None:
    handoff = "executor-handoff:" + "a" * 64
    result = plan_agent_os_continuation(
        repository="Blummer92/agent-os",
        issue_number=1233,
        canonical_handoff_id=handoff,
    )
    assert result["next_operation"] == "resume-existing-handoff"
    assert result["handoff_id"] == handoff
    assert result["ingress"] == f"/agent-os resume {handoff}"


def test_plan_rejects_noncanonical_handoff_instead_of_guessing() -> None:
    with pytest.raises(ValueError, match="canonical executor-handoff"):
        plan_agent_os_continuation(
            repository="Blummer92/agent-os",
            issue_number=1233,
            canonical_handoff_id="executor-handoff:latest",
        )


def test_local_gh_absence_is_not_an_input_to_agent_os_plan() -> None:
    result = plan_agent_os_continuation(
        repository="Blummer92/agent-os", issue_number=1233
    )
    assert "gh" not in result
    assert result["status"] == "agent-os-route"


def test_capability_alternative_continues_same_lineage() -> None:
    result = classify_agent_os_continuation(
        repository="Blummer92/agent-os",
        issue_number=1213,
        operation_id="replace-exact-changelog",
        surface_outcome="selected-surface-unavailable",
        approved_alternative_capability="github-exact-blob-read",
        branch="agent/issue-1213",
        pull_request=1263,
        target_identity_reacquired=True,
        requires_exact_blob_identity=True,
        exact_blob_identity_reacquired=True,
    )
    assert result["classification"] == "capability-alternative-available"
    assert result["continue_automatically"] is True
    assert result["mutation_permitted"] is True
    assert result["lineage"]["issue_number"] == 1213
    assert result["lineage"]["pull_request"] == 1263
    assert result["github_writes_authorized"] is False
    assert result["scheduler_invoked"] is False


def test_ambiguous_prior_effect_requires_readback() -> None:
    result = classify_agent_os_continuation(
        repository="Blummer92/agent-os",
        issue_number=1213,
        operation_id="replace-exact-changelog",
        surface_outcome="selected-surface-unavailable",
        approved_alternative_capability="github-exact-blob-read",
        prior_effect="ambiguous",
    )
    assert result["classification"] == "partial-effect-reconciliation-required"
    assert "read-back-canonical-state" in result["obligations"]
    assert result["mutation_permitted"] is False


def test_desired_state_already_present_suppresses_duplicate_mutation() -> None:
    result = classify_agent_os_continuation(
        repository="Blummer92/agent-os",
        issue_number=1213,
        operation_id="replace-exact-changelog",
        surface_outcome="selected-surface-unavailable",
        approved_alternative_capability="github-exact-blob-read",
        prior_effect="desired-state-already-present",
        target_identity_reacquired=True,
    )
    assert result["classification"] == "capability-alternative-available"
    assert result["continue_automatically"] is True
    assert result["mutation_permitted"] is False
    assert "suppress-duplicate-mutation" in result["obligations"]


def test_active_foreign_lease_never_creates_competing_execution() -> None:
    result = classify_agent_os_continuation(
        repository="Blummer92/agent-os",
        issue_number=1233,
        operation_id="governed-resume",
        surface_outcome="selected-surface-unavailable",
        approved_alternative_capability="governed-runner",
        active_foreign_lease=True,
    )
    assert result["classification"] == "authority-or-scope-boundary"
    assert result["continue_automatically"] is False
    assert result["lease_acquired"] is False
    assert result["competing_lineage_created"] is False


def test_cross_surface_transition_delegates_compatibility_until_proven() -> None:
    result = classify_agent_os_continuation(
        repository="Blummer92/agent-os",
        issue_number=1233,
        operation_id="governed-resume",
        surface_outcome="selected-surface-unavailable",
        approved_alternative_capability="governed-runner",
        target_identity_reacquired=True,
        runtime_surface_transition=True,
        evidence_compatibility_confirmed=False,
    )
    assert result["classification"] == "currentness-or-identity-unproven"
    assert result["delegated_owner"] == "#1201"


def test_repeated_equivalent_transition_delegates_to_no_progress_owner() -> None:
    result = classify_agent_os_continuation(
        repository="Blummer92/agent-os",
        issue_number=1233,
        operation_id="governed-resume",
        surface_outcome="selected-surface-unavailable",
        approved_alternative_capability="governed-runner",
        equivalent_transition_repeated=True,
    )
    assert result["classification"] == "no-capable-authorized-route"
    assert result["delegated_owner"] == "#1200"


@pytest.mark.parametrize("domain", ["base-drift", "red-ci", "stale-gate"])
def test_adjacent_lifecycles_are_not_absorbed(domain: str) -> None:
    with pytest.raises(ValueError, match="must not absorb"):
        classify_agent_os_continuation(
            repository="Blummer92/agent-os",
            issue_number=1233,
            operation_id="bounded-operation",
            surface_outcome="selected-surface-unavailable",
            non_absorbed_domain=domain,
        )
