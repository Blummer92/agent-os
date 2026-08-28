"""Focused #1097 coverage for the Coding Command Center handoff projection.

The case list mirrors the matrix frozen by #1062: executor-route coverage,
#988 classification coverage, #914 next-action preservation, blocked/unblocked
evidence, fail-closed currentness, unavailable PR identity, no progress
synthesis, no authority gain, determinism, bounded output, no external I/O, and
#926 visible ordering.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.agent_os_candidate_packet.post_pr_lane_plan import (
    POST_PR_LANE_PLAN_SCHEMA_NAME,
    POST_PR_LANE_PLAN_SCHEMA_VERSION,
    LanePlanOutcome,
    PostPrLanePlan,
)
from scripts.agent_os_issue_acceptance.coding_command_center_handoff import (
    CODING_COMMAND_CENTER_HANDOFF_SCHEMA_NAME,
    CODING_COMMAND_CENTER_HANDOFF_SCHEMA_VERSION,
    MAX_SERIALIZED_BYTES,
    CodingCommandCenterEvidence,
    build_coding_command_center_handoff,
    render_coding_command_center_handoff,
    serialize_coding_command_center_handoff,
)
from scripts.agent_os_issue_acceptance.executor_route import (
    CapabilityState,
    ExecutorRoute,
    ExecutorRouteEvidence,
    ExplicitExecutionSurface,
    RuntimeRequirement,
    evaluate_executor_route,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    DependencyState,
    FreshnessState,
    IssueOperationalEvidence,
    IssueState,
    LifecycleStage,
    OperationalOutcome,
    PrimaryIssueClaim,
    ReadinessState,
    SourceState,
    TerminalDisposition,
    ValidationState,
    build_issue_operational_state,
)
from scripts.agent_os_issue_acceptance.operating_mode import (
    OperatingModeOutcome,
    RequestedMode,
)
from scripts.agent_os_issue_acceptance.post_pr_state_audit import TerminalPrState
from scripts.agent_os_issue_acceptance.validation_failure_classifier import (
    EvidenceState,
    RequirementResult,
    ValidationFailureClassification,
    ValidationFailureEvidence,
    classify_validation_failure,
)

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "agent_os_issue_acceptance"
    / "coding_command_center_handoff.py"
)

SHA = "a" * 40
MAIN_SHA = "b" * 40
AUTH_ID = "approval:" + "c" * 64
MODE_ID = "operating-mode-decision:" + "2" * 64
SELECTION_ID = "executable-lane-selection:" + "3" * 64
AUDIT_ID = "post-pr-state-audit:" + "4" * 64


def _authority(state: AuthorizationState) -> AuthorityProjection:
    return AuthorityProjection(
        state=state,
        evidence_id=AUTH_ID if state in {AuthorizationState.AUTHORIZED, AuthorizationState.STALE} else None,
    )


def _state(**overrides):
    values = dict(
        repository="Blummer92/agent-os",
        issue_number=1097,
        source_revision=SHA,
        observed_at="2026-08-26T21:00:00Z",
        evidence_ids=(),
        source_state=SourceState.COMPLETE,
        issue_state=IssueState.OPEN,
        lifecycle_stage=LifecycleStage.IMPLEMENTATION,
        terminal_disposition=TerminalDisposition.NONE,
        readiness=ReadinessState.READY,
        implementation_authorization=_authority(AuthorizationState.AUTHORIZED),
        ready_for_review_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
        execution_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
        merge_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
        closure_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
        external_write_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
        dependency_state=DependencyState.CLEAR,
        primary_claims=(),
        validation_state=ValidationState.NOT_RUN,
        freshness_state=FreshnessState.CURRENT,
        observed_labels=(),
    )
    values.update(overrides)
    return build_issue_operational_state(IssueOperationalEvidence(**values))


def _handoff(state=None, **overrides):
    evidence = CodingCommandCenterEvidence(
        operational_state=state or _state(),
        source_revision=SHA,
        **overrides,
    )
    return build_coding_command_center_handoff(evidence)


def _route(**changes):
    baseline = ExecutorRouteEvidence(
        source_operational_state_id=_state().state_id,
        operational_outcome=OperationalOutcome.READY,
        source_operating_mode_decision_id=MODE_ID,
        operating_mode_outcome=OperatingModeOutcome.BUILT,
        requested_mode=RequestedMode.BUILD,
        implementation_authorization=AuthorizationState.AUTHORIZED,
        target="#1097",
        base_ref="main",
        source_revision=SHA,
        observed_revision=SHA,
        stop_condition="Open one Draft PR and stop.",
        goal="Project the Coding Command Center handoff.",
        scope=("coding command center handoff module", "focused tests"),
        validation=("pytest focused", "validate-all"),
        connector_state=CapabilityState.AVAILABLE,
        runner_state=CapabilityState.AVAILABLE,
        external_fallback_state=CapabilityState.AVAILABLE,
    )
    return evaluate_executor_route(replace(baseline, **changes))


def _classification(classification: ValidationFailureClassification):
    if classification is ValidationFailureClassification.PR_REGRESSION:
        evidence = ValidationFailureEvidence(
            pr_head_sha=SHA,
            comparison_main_sha=MAIN_SHA,
            command="pytest -q",
            failed_requirement="focused",
            error_excerpt="assert False",
            exit_code=1,
            evidence_state=EvidenceState.CURRENT,
            comparable_pr_and_main=True,
            same_requirement_executed=True,
            main_requirement_result=RequirementResult.PASS,
            pr_scope_attribution_supported=True,
        )
    elif classification is ValidationFailureClassification.INHERITED_MAIN_FAILURE:
        evidence = ValidationFailureEvidence(
            pr_head_sha=SHA,
            comparison_main_sha=MAIN_SHA,
            command="pytest -q",
            failed_requirement="focused",
            error_excerpt="assert False",
            exit_code=1,
            evidence_state=EvidenceState.CURRENT,
            comparable_pr_and_main=True,
            same_requirement_executed=True,
            main_requirement_result=RequirementResult.FAIL,
            materially_equivalent_failure=True,
        )
    elif classification is ValidationFailureClassification.CI_INFRASTRUCTURE_CONFIGURATION_FAILURE:
        evidence = ValidationFailureEvidence(
            pr_head_sha=SHA,
            comparison_main_sha=None,
            command="pytest -q",
            failed_requirement=None,
            error_excerpt="runner could not authenticate",
            exit_code=None,
            evidence_state=EvidenceState.CURRENT,
            infrastructure_configuration_failure_proven=True,
            infrastructure_authorization_boundary="workflow settings",
        )
    else:
        evidence = ValidationFailureEvidence(
            pr_head_sha=SHA,
            comparison_main_sha=None,
            command="pytest -q",
            failed_requirement=None,
            error_excerpt=None,
            exit_code=None,
            evidence_state=EvidenceState.UNAVAILABLE,
        )
    result = classify_validation_failure(evidence)
    assert result.classification is classification
    return result


def _lane_plan(**changes):
    values = dict(
        schema_name=POST_PR_LANE_PLAN_SCHEMA_NAME,
        schema_version=POST_PR_LANE_PLAN_SCHEMA_VERSION,
        source_executable_lane_selection_id=SELECTION_ID,
        source_post_pr_audit_id=AUDIT_ID,
        terminal_pr_state=TerminalPrState.MERGED,
        outcome=LanePlanOutcome.LANE_PLAN,
        selected_lane_issue_numbers=(1102,),
        primary_next_issue=1102,
        alternate_issue=None,
        recommended_executor_route=ExecutorRoute.CHATGPT_CONNECTOR,
        smallest_next_action="start #1102 on the governed lane",
        reason_codes=("plan.audit-recommendation-selected",),
        conflict_findings=(),
    )
    values.update(changes)
    return PostPrLanePlan(**values)


# --- executor-route coverage ------------------------------------------------


def test_connector_native_route_is_projected_unchanged():
    decision = _route()
    result = _handoff(executor_route_decision=decision)
    assert result.executor_route == "chatgpt_connector"
    assert result.executor_route_decision_id == decision.decision_id
    assert "route.route.chatgpt-connector" in result.reason_codes


def test_governed_runner_route_is_projected_unchanged():
    decision = _route(runtime_requirements=(RuntimeRequirement.TESTS,))
    result = _handoff(executor_route_decision=decision)
    assert result.executor_route == "governed_runner"
    assert result.executor_route_decision_id == decision.decision_id


def test_permitted_external_fallback_route_is_projected_unchanged():
    decision = _route(explicit_surface=ExplicitExecutionSurface.EXTERNAL_FALLBACK)
    result = _handoff(executor_route_decision=decision)
    assert result.executor_route == "external_fallback"


def test_human_decision_route_is_projected_unchanged():
    decision = _route(
        connector_state=CapabilityState.UNAVAILABLE,
        runner_state=CapabilityState.UNAVAILABLE,
        external_fallback_state=CapabilityState.UNAVAILABLE,
    )
    assert decision.route is ExecutorRoute.HUMAN_DECISION
    result = _handoff(executor_route_decision=decision)
    assert result.executor_route == "human_decision"


def test_absent_executor_route_stays_explicitly_unavailable():
    result = _handoff()
    assert result.executor_route is None
    assert result.executor_route_decision_id is None
    assert "handoff.executor-route-unavailable" in result.reason_codes


# --- validation coverage ----------------------------------------------------


def test_focused_pass_with_pending_aggregate_awaits_evidence():
    result = _handoff(_state(validation_state=ValidationState.PENDING))
    assert result.smallest_next_action == "await current validation evidence"
    assert result.primary_blocker == "validation.pending"


def test_exact_head_complete_validation_projects_head_identity():
    claim = PrimaryIssueClaim(
        pull_request_number=1416,
        branch="agent/1097-coding-command-center-handoff",
        head_sha=SHA,
        state="ready",
    )
    result = _handoff(
        _state(primary_claims=(claim,), validation_state=ValidationState.PASSED),
        observed_head_sha=SHA,
        validation_evidence_reference="check-run:aggregate-validation",
    )
    assert result.observed_head_sha == SHA
    assert result.pull_request_number == 1416
    assert result.validation_evidence_reference == "check-run:aggregate-validation"
    assert result.primary_blocker is None


@pytest.mark.parametrize(
    "classification",
    tuple(ValidationFailureClassification),
)
def test_each_validation_classification_is_preserved(classification):
    result = _handoff(validation_classification=_classification(classification))
    assert result.validation_classification == classification.value
    assert "handoff.validation-classification-present" in result.reason_codes


def test_classification_recommended_next_action_is_not_rewritten():
    canonical = _classification(ValidationFailureClassification.PR_REGRESSION)
    result = _handoff(validation_classification=canonical)
    assert result.smallest_next_action == canonical.recommended_next_action


# --- #914 preservation ------------------------------------------------------


def test_post_pr_next_action_is_preserved_without_reranking():
    plan = _lane_plan()
    result = _handoff(post_pr_lane_plan=plan)
    assert result.smallest_next_action == plan.smallest_next_action
    assert result.handoff_target == "issue:1102"
    assert "handoff.post-pr-next-action-preserved" in result.reason_codes


def test_explicit_handoff_target_outranks_derived_lane_target():
    result = _handoff(post_pr_lane_plan=_lane_plan(), handoff_target="agent:integration-manager")
    assert result.handoff_target == "agent:integration-manager"


# --- blocked / unblocked evidence -------------------------------------------


def test_blocked_state_surfaces_canonical_blocker_without_reranking():
    state = _state(
        readiness=ReadinessState.BLOCKED,
        implementation_authorization=_authority(AuthorizationState.NOT_AUTHORIZED),
    )
    result = _handoff(state)
    assert result.primary_blocker == state.blocker_codes[0]
    assert result.smallest_next_action == "clear the primary canonical blocker before continuing"
    assert "handoff.blocked" in result.reason_codes


def test_unblocked_state_carries_no_blocker_and_no_blocked_reason():
    result = _handoff()
    assert result.primary_blocker is None
    assert "handoff.blocked" not in result.reason_codes
    assert result.smallest_next_action == "continue with the canonical action for the current lifecycle stage"


def test_needs_decision_state_requires_a_human_decision():
    result = _handoff(_state(readiness=ReadinessState.NEEDS_DECISION))
    assert result.smallest_next_action == "obtain the required human decision before continuing"
    assert "handoff.needs-decision" in result.reason_codes


# --- fail-closed currentness ------------------------------------------------


def test_stale_state_fails_closed():
    result = _handoff(_state(freshness_state=FreshnessState.STALE))
    assert result.smallest_next_action.startswith("reacquire current canonical evidence")
    assert "handoff.fail-closed-currentness" in result.reason_codes


def test_conflicting_primary_claims_fail_closed_and_hide_pr_identity():
    claims = (
        PrimaryIssueClaim(
            pull_request_number=1416,
            branch="agent/1097-coding-command-center-handoff",
            head_sha=SHA,
            state="ready",
        ),
        PrimaryIssueClaim(
            pull_request_number=1417,
            branch="agent/1097-duplicate-lineage",
            head_sha=MAIN_SHA,
            state="ready",
        ),
    )
    result = _handoff(_state(primary_claims=claims))
    assert result.pull_request_number is None
    assert "handoff.primary-claim-conflicting" in result.reason_codes
    assert result.smallest_next_action.startswith("reacquire current canonical evidence")


def test_source_revision_conflict_fails_closed():
    with pytest.raises(ValueError, match="source_revision conflicts"):
        CodingCommandCenterEvidence(
            operational_state=_state(),
            source_revision="d" * 40,
        )


def test_tampered_state_identity_is_rejected():
    state = _state()
    object.__setattr__(state, "state_id", "issue-operational-state:" + "e" * 64)
    with pytest.raises(ValueError, match="operational state validation failed"):
        _handoff(state)


def test_malformed_observed_head_is_rejected():
    with pytest.raises(ValueError, match="observed_head_sha"):
        CodingCommandCenterEvidence(
            operational_state=_state(),
            source_revision=SHA,
            observed_head_sha="not-a-sha",
        )


# --- unavailable PR ---------------------------------------------------------


def test_unavailable_pull_request_is_explicitly_unavailable():
    result = _handoff()
    assert result.pull_request_number is None
    assert "Handoff target: unavailable" in render_coding_command_center_handoff(result)


def test_missing_optional_evidence_remains_explicitly_unavailable_in_rendering():
    rendered = render_coding_command_center_handoff(_handoff())
    assert "Route / escalation reason: unavailable" in rendered
    assert "validation=unavailable" in rendered
    assert "blocker=unavailable" in rendered


# --- no synthesis, no authority --------------------------------------------


def test_no_percentage_progress_is_synthesized():
    payload = serialize_coding_command_center_handoff(_handoff(_state(validation_state=ValidationState.PENDING)))
    assert not any("percent" in key or "progress" in key for key in payload)
    rendered = render_coding_command_center_handoff(_handoff())
    assert "%" not in rendered


def test_projection_creates_no_authority_and_performs_no_side_effects():
    result = _handoff(
        _state(
            merge_authorization=_authority(AuthorizationState.AUTHORIZED),
            closure_authorization=_authority(AuthorizationState.AUTHORIZED),
        )
    )
    assert result.authority_created is False
    assert result.side_effects_performed is False
    assert result.notion_write_performed is False
    payload = serialize_coding_command_center_handoff(result)
    assert payload["authority_created"] is False
    assert payload["side_effects_performed"] is False
    assert payload["notion_write_performed"] is False
    assert not any("authorized" in key for key in payload)


def test_ready_state_projects_canonical_identity():
    result = _handoff()
    assert result.schema_name == CODING_COMMAND_CENTER_HANDOFF_SCHEMA_NAME
    assert result.schema_version == CODING_COMMAND_CENTER_HANDOFF_SCHEMA_VERSION
    assert result.repository == "Blummer92/agent-os"
    assert result.issue_number == 1097
    assert result.current_stage == "implementation"
    assert result.canonical_state_reference == _state().state_id
    assert result.source_revision == SHA


# --- determinism and bounds -------------------------------------------------


def test_identical_input_produces_identical_deterministic_output():
    first = _handoff()
    second = _handoff()
    assert first == second
    assert first.handoff_id == second.handoff_id
    assert serialize_coding_command_center_handoff(first) == serialize_coding_command_center_handoff(second)
    assert render_coding_command_center_handoff(first) == render_coding_command_center_handoff(second)


def test_different_input_produces_a_different_handoff_identity():
    baseline = _handoff()
    changed = _handoff(observed_head_sha=MAIN_SHA)
    assert baseline.handoff_id != changed.handoff_id


def test_render_and_serialization_stay_bounded():
    result = _handoff(
        executor_route_decision=_route(runtime_requirements=(RuntimeRequirement.TESTS,)),
        validation_classification=_classification(ValidationFailureClassification.PR_REGRESSION),
        post_pr_lane_plan=_lane_plan(),
        observed_head_sha=SHA,
        validation_evidence_reference="check-run:aggregate-validation",
    )
    payload = serialize_coding_command_center_handoff(result)
    assert len(repr(payload).encode("utf-8")) < MAX_SERIALIZED_BYTES
    rendered = render_coding_command_center_handoff(result)
    assert len(rendered.encode("utf-8")) < MAX_SERIALIZED_BYTES
    assert len(rendered.splitlines()) == 10


def test_oversized_evidence_reference_is_rejected():
    with pytest.raises(ValueError, match="validation_evidence_reference"):
        CodingCommandCenterEvidence(
            operational_state=_state(),
            source_revision=SHA,
            validation_evidence_reference="x" * 4097,
        )


# --- no external I/O --------------------------------------------------------


def test_module_performs_no_external_io():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))
    forbidden = {
        "os",
        "io",
        "socket",
        "pathlib",
        "subprocess",
        "requests",
        "urllib",
        "http",
        "sqlite3",
        "shutil",
        "tempfile",
        "logging",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert not forbidden & imported
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not {"open", "eval", "exec", "__import__"} & called


# --- #926 ordering ----------------------------------------------------------


def test_rendering_preserves_required_visible_order():
    lines = render_coding_command_center_handoff(_handoff()).splitlines()
    assert lines[0].startswith("Current target:")
    assert lines[1].startswith("Smallest safe next action:")
    assert lines[2].startswith("Route / escalation reason:")
    assert lines[3].startswith("Validation or blocker evidence:")
    assert lines[4].startswith("Handoff target:")
    assert lines[5].startswith("Canonical state:")
    assert lines[6].startswith("Source revision:")


def test_rendering_repeats_the_non_authority_declaration():
    lines = render_coding_command_center_handoff(_handoff()).splitlines()
    assert lines[-3:] == [
        "authority_created: false",
        "side_effects_performed: false",
        "notion_write_performed: false",
    ]


def test_serialization_rejects_a_foreign_object():
    with pytest.raises(TypeError, match="exact CodingCommandCenterHandoff"):
        serialize_coding_command_center_handoff(object())
