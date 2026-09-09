from __future__ import annotations

import pytest

from agent_os_execution_service.mcp_facade import (
    admit_agent_os_failed_repair,
    classify_agent_os_continuation,
    classify_agent_os_mission_completion,
    plan_agent_os_continuation,
)


def test_plan_without_handoff_requires_server_side_discovery() -> None:
    result = plan_agent_os_continuation(repository="Blummer92/agent-os", issue_number=1233)
    assert result["next_operation"] == "discover-current-handoff"
    assert result["handoff_id"] is None
    assert result["execution_authorized"] is False
    assert result["github_writes_authorized"] is False


def test_plan_preserves_canonical_handoff_byte_for_byte() -> None:
    handoff = "executor-handoff:" + "a" * 64
    result = plan_agent_os_continuation(repository="Blummer92/agent-os", issue_number=1233, canonical_handoff_id=handoff)
    assert result["handoff_id"] == handoff
    assert result["ingress"] == f"/agent-os resume {handoff}"


def test_plan_rejects_noncanonical_handoff_instead_of_guessing() -> None:
    with pytest.raises(ValueError, match="canonical executor-handoff"):
        plan_agent_os_continuation(repository="Blummer92/agent-os", issue_number=1233, canonical_handoff_id="executor-handoff:latest")


def test_mission_completion_drives_remaining_same_lineage_work() -> None:
    result = classify_agent_os_mission_completion(repository="Blummer92/agent-os", issue_number=2189, branch_exists=True, implementation_commit_count=1, draft_pr_exists=False, canonical_pr_readback_verified=False, capable_route_available=True, subordinate_writes_only=False)
    assert result["completion_admissible"] is False
    assert result["agent_os_continuation"]["action"] == "continue-same-lineage-on-capable-implementation-route"
    assert result["agent_os_continuation"]["terminal"] is False


def test_mission_completion_is_terminal_only_after_pr_readback() -> None:
    result = classify_agent_os_mission_completion(repository="Blummer92/agent-os", issue_number=2189, branch_exists=True, implementation_commit_count=2, draft_pr_exists=True, canonical_pr_readback_verified=True, capable_route_available=True, subordinate_writes_only=False)
    assert result["completion_admissible"] is True
    assert result["agent_os_continuation"]["terminal"] is True


def test_failed_repair_admission_is_consumed_after_lesson_activation() -> None:
    result = admit_agent_os_failed_repair(activation_result={"attempt_id": "attempt-1", "retry_reentry_outcome": "consumed", "selected_lesson_ids": ["63"], "mutation_admissible": True}, check_state="red", required_check_configuration_state="current", review_state="clear", branch_freshness="current", mergeability="mergeable")
    assert result["mutation_admissible"] is True
    assert result["agent_os_continuation"]["action"] == "continue-authorized-repair-mutation"


def test_capability_alternative_continues_same_lineage() -> None:
    result = classify_agent_os_continuation(repository="Blummer92/agent-os", issue_number=1213, operation_id="replace-exact-changelog", surface_outcome="selected-surface-unavailable", approved_alternative_capability="github-exact-blob-read", branch="agent/issue-1213", pull_request=1263, target_identity_reacquired=True, requires_exact_blob_identity=True, exact_blob_identity_reacquired=True)
    assert result["classification"] == "capability-alternative-available"
    assert result["continue_automatically"] is True
    assert result["mutation_permitted"] is True
    assert result["lineage"]["pull_request"] == 1263


def test_ambiguous_prior_effect_requires_readback() -> None:
    result = classify_agent_os_continuation(repository="Blummer92/agent-os", issue_number=1213, operation_id="replace-exact-changelog", surface_outcome="selected-surface-unavailable", approved_alternative_capability="github-exact-blob-read", prior_effect="ambiguous")
    assert result["classification"] == "partial-effect-reconciliation-required"
    assert "read-back-canonical-state" in result["obligations"]


def test_active_foreign_lease_never_creates_competing_execution() -> None:
    result = classify_agent_os_continuation(repository="Blummer92/agent-os", issue_number=1233, operation_id="governed-resume", surface_outcome="selected-surface-unavailable", approved_alternative_capability="governed-runner", active_foreign_lease=True)
    assert result["classification"] == "authority-or-scope-boundary"
    assert result["competing_lineage_created"] is False


def test_repeated_equivalent_transition_delegates_to_no_progress_owner() -> None:
    result = classify_agent_os_continuation(repository="Blummer92/agent-os", issue_number=1233, operation_id="governed-resume", surface_outcome="selected-surface-unavailable", approved_alternative_capability="governed-runner", equivalent_transition_repeated=True)
    assert result["classification"] == "no-capable-authorized-route"
    assert result["delegated_owner"] == "#1200"


@pytest.mark.parametrize("domain", ["base-drift", "red-ci", "stale-gate"])
def test_adjacent_lifecycles_are_not_absorbed(domain: str) -> None:
    with pytest.raises(ValueError, match="must not absorb"):
        classify_agent_os_continuation(repository="Blummer92/agent-os", issue_number=1233, operation_id="bounded-operation", surface_outcome="selected-surface-unavailable", non_absorbed_domain=domain)
