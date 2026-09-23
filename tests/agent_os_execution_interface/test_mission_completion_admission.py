from scripts.agent_os_execution_interface.mission_completion_admission import (
    LIVE_CONSUMER_OBSERVATION,
    evaluate_mission_completion_admission,
)


def admission(**overrides):
    values = {
        "repository": "Blummer92/agent-os",
        "issue_number": 1985,
        "branch_exists": True,
        "implementation_commit_count": 1,
        "draft_pr_exists": True,
        "canonical_pr_readback_verified": True,
        "capable_route_available": True,
        "subordinate_writes_only": False,
        "live_consumer_required": False,
        "live_consumer_requirement_source": None,
        "live_consumer_reachability_proven": False,
        "live_consumer_identity": None,
        "live_consumer_evidence_source": None,
        "live_consumer_evidence_current": False,
        "live_consumer_evidence_kind": None,
        "successor_issue_number": None,
        "successor_current": False,
        "successor_owns_residual_live_acceptance": False,
    }
    values.update(overrides)
    return evaluate_mission_completion_admission(**values)


def live_observation(**overrides):
    values = {
        "live_consumer_required": True,
        "live_consumer_requirement_source": "issue-contract:#2765",
        "live_consumer_reachability_proven": True,
        "live_consumer_identity": "agent-os:exact-live-consumer",
        "live_consumer_evidence_source": "canonical-host-observation:current",
        "live_consumer_evidence_current": True,
        "live_consumer_evidence_kind": LIVE_CONSUMER_OBSERVATION,
    }
    values.update(overrides)
    return admission(**values)


def test_canonical_pr_delivery_is_required_for_completion():
    result = admission()
    assert result.completion_admissible is True
    assert result.next_action == "report-canonically-verified-draft-pr-delivery"
    assert result.reason_codes == ("canonical-implementation-delivery-proven",)


def test_zero_commit_branch_is_implementation_not_started():
    result = admission(
        implementation_commit_count=0,
        draft_pr_exists=False,
        canonical_pr_readback_verified=False,
    )
    assert result.completion_admissible is False
    assert "implementation-not-started" in result.reason_codes
    assert "draft-pr-not-proven" in result.reason_codes
    assert result.next_action == "continue-same-lineage-on-capable-implementation-route"


def test_handoff_comment_cannot_complete_parent_mission():
    result = admission(
        implementation_commit_count=0,
        draft_pr_exists=False,
        canonical_pr_readback_verified=False,
        subordinate_writes_only=True,
    )
    assert result.completion_admissible is False
    assert "subordinate-write-is-not-parent-completion" in result.reason_codes
    assert result.next_action == "continue-same-lineage-on-capable-implementation-route"


def test_missing_canonical_pr_readback_blocks_success_claim():
    result = admission(canonical_pr_readback_verified=False)
    assert result.completion_admissible is False
    assert "canonical-pr-readback-not-proven" in result.reason_codes


def test_no_capable_route_reports_exact_blocker_without_false_completion():
    result = admission(
        implementation_commit_count=0,
        draft_pr_exists=False,
        canonical_pr_readback_verified=False,
        capable_route_available=False,
        subordinate_writes_only=True,
    )
    assert result.completion_admissible is False
    assert (
        result.next_action
        == "report-exact-patch-capability-blocker-without-completion-claim"
    )


def test_guard_grants_no_dangerous_authority():
    result = admission()
    assert result.github_writes_authorized is False
    assert result.merge_authorized is False
    assert result.issue_closure_authorized is False
    assert result.workflow_authorized is False
    assert result.production_authorized is False
    assert result.external_system_write_authorized is False


def test_repository_delivery_cannot_complete_feature_that_requires_unproven_live_consumer():
    result = admission(
        live_consumer_required=True,
        live_consumer_requirement_source="issue-contract:#2765",
        live_consumer_reachability_proven=False,
    )
    assert result.completion_admissible is False
    assert "required-live-consumer-reachability-not-proven" in result.reason_codes
    assert result.next_action == "reconcile-live-consumer-or-successor-evidence"


def test_required_live_consumer_allows_completion_only_with_current_bound_live_observation():
    result = live_observation()
    assert result.completion_admissible is True
    assert "required-live-consumer-current-observation-proven" in result.reason_codes


def test_live_consumer_requirement_must_come_from_explicit_contract_evidence():
    result = live_observation(live_consumer_requirement_source=None)
    assert result.completion_admissible is False
    assert "required-live-consumer-contract-source-not-proven" in result.reason_codes


def test_2525_2673_runtime_registration_is_not_live_consumer_observation():
    result = live_observation(
        live_consumer_identity="ppux-picture-perfect-prompt-projection",
        live_consumer_evidence_source="repository-runtime-registration:#2525",
        live_consumer_evidence_kind="repository-registration",
    )
    assert result.completion_admissible is False
    assert (
        "required-live-consumer-evidence-not-live-observation"
        in result.reason_codes
    )


def test_1621_2682_machine_test_is_not_self_defect_production_consumer():
    result = live_observation(
        live_consumer_identity="self-defect-triage-bridge",
        live_consumer_evidence_source="pytest:self-defect-bridge",
        live_consumer_evidence_kind="fixture-or-unit-test",
    )
    assert result.completion_admissible is False
    assert (
        "required-live-consumer-evidence-not-live-observation"
        in result.reason_codes
    )


def test_2528_2425_2763_missing_chatgpt_host_exposure_stays_nonterminal():
    result = admission(
        live_consumer_required=True,
        live_consumer_requirement_source="issue-contract:#2528",
        live_consumer_reachability_proven=False,
        live_consumer_identity="activate_agent_os_issue_start_lessons_tool",
        live_consumer_evidence_source="current-chatgpt-host-capability-readback",
        live_consumer_evidence_current=True,
    )
    assert result.completion_admissible is False
    assert "required-live-consumer-reachability-not-proven" in result.reason_codes


def test_repository_child_can_complete_when_current_successor_owns_residual_live_acceptance():
    result = admission(
        live_consumer_required=True,
        live_consumer_requirement_source="issue-contract:#2525",
        successor_issue_number=2673,
        successor_current=True,
        successor_owns_residual_live_acceptance=True,
    )
    assert result.completion_admissible is True
    assert (
        "residual-live-acceptance-owned-by-current-successor"
        in result.reason_codes
    )


def test_successor_delegation_fails_closed_when_currentness_is_unproven():
    result = admission(
        live_consumer_required=True,
        live_consumer_requirement_source="issue-contract:#1621",
        successor_issue_number=2682,
        successor_current=False,
        successor_owns_residual_live_acceptance=True,
    )
    assert result.completion_admissible is False
    assert "residual-live-successor-currentness-not-proven" in result.reason_codes


def test_repository_only_issue_does_not_require_live_consumer_evidence():
    result = admission(
        live_consumer_required=False,
        live_consumer_reachability_proven=False,
    )
    assert result.completion_admissible is True
