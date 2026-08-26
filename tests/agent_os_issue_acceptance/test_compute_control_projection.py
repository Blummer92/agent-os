"""Focused #1419 coverage for the compute-control decision projection.

The case list mirrors the matrix frozen by the #1419 issue contract: blocked
and unauthorized pre-execution gates, focused-first and final-cloud guidance,
exact-identity reuse, head change invalidating old evidence, duplicate/obsolete
active-run risk, roadmap-only coordination, stale/conflicting fail-closed,
missing evidence without fabrication, determinism, no authority gain, no
external I/O, and no Notion write.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.coding_command_center_handoff import (
    CodingCommandCenterEvidence,
    build_coding_command_center_handoff,
)
from scripts.agent_os_issue_acceptance.compute_control_projection import (
    COMPUTE_CONTROL_PROJECTION_SCHEMA_NAME,
    COMPUTE_CONTROL_PROJECTION_SCHEMA_VERSION,
    VALIDATION_HEAD_DISPOSITIONS,
    ActiveExecutionReference,
    ComputeControlEvidence,
    ComputeDisposition,
    ValidationHeadReference,
    build_compute_control_projection,
    render_compute_control_projection,
    serialize_compute_control_projection,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    DependencyState,
    FreshnessState,
    IssueOperationalEvidence,
    IssueState,
    LifecycleStage,
    PrimaryIssueClaim,
    ReadinessState,
    SourceState,
    TerminalDisposition,
    ValidationState,
    build_issue_operational_state,
)
from scripts.agent_os_remote_validation.models import ValidationPlan
from scripts.agent_os_remote_validation.provenance import (
    ExpectedEvidenceIdentity,
    NormalizedRemoteValidationEvidence,
    project_evidence_applicability,
)

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "agent_os_issue_acceptance"
    / "compute_control_projection.py"
)

HEAD = "a" * 40
NEW_HEAD = "b" * 40
REVISION = "e" * 40
AUTH_ID = "approval:" + "c" * 64
DIGEST = "c" * 64
PLAN_ID = "validation-plan:" + "1" * 64
DECISION_ID = "validation-dispatch-decision:" + "2" * 64
ROOT = "github-oidc:blummer92/agent-os"
VERIFIER = "cloud-build-verifier:v1"
EVALUATED_AT = "2026-07-27T18:00:00Z"
PR_NUMBER = 1420


def _authority(state: AuthorizationState) -> AuthorityProjection:
    return AuthorityProjection(
        state=state,
        evidence_id=AUTH_ID if state in {AuthorizationState.AUTHORIZED, AuthorizationState.STALE} else None,
    )


def _claim(**overrides):
    values = dict(
        pull_request_number=PR_NUMBER,
        branch="agent/1419-compute-control-projection",
        head_sha=HEAD,
        state="draft",
    )
    values.update(overrides)
    return PrimaryIssueClaim(**values)


def _state(**overrides):
    values = dict(
        repository="Blummer92/agent-os",
        issue_number=1419,
        source_revision=REVISION,
        observed_at="2026-08-26T23:00:00Z",
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
        primary_claims=(_claim(),),
        validation_state=ValidationState.NOT_RUN,
        freshness_state=FreshnessState.CURRENT,
        observed_labels=(),
    )
    values.update(overrides)
    return build_issue_operational_state(IssueOperationalEvidence(**values))


def _handoff(state, observed_head_sha=HEAD):
    return build_coding_command_center_handoff(
        CodingCommandCenterEvidence(
            operational_state=state,
            source_revision=REVISION,
            observed_head_sha=observed_head_sha,
        )
    )


def _plan(**overrides):
    values = dict(
        selector_version="1.0.0",
        repository="Blummer92/agent-os",
        pull_request=PR_NUMBER,
        base_sha=REVISION,
        head_sha=HEAD,
        profile="focused",
        commands=("python -m pytest tests/agent_os_issue_acceptance",),
        command_set_digest=DIGEST,
        reason_codes=("profile.focused-package",),
        remote_build_required=False,
    )
    values.update(overrides)
    return ValidationPlan(**values)


def _applicability(**overrides):
    evidence = NormalizedRemoteValidationEvidence(
        schema_name="agent-os-remote-validation-evidence",
        schema_version="1.0",
        evidence_id="evidence:build-1420-1",
        source_type="provider-api",
        repository="Blummer92/agent-os",
        pull_request=PR_NUMBER,
        head_sha=HEAD,
        profile="focused",
        selector_version="1.0.0",
        command_set_digest=DIGEST,
        plan_id=PLAN_ID,
        dispatch_decision_id=DECISION_ID,
        build_id="build-1420-1",
        provider="google-cloud-build",
        producer_identity="service-account:validation-verifier",
        trigger_identity="trigger:agent-os-pr-validation",
        terminal_status="succeeded",
        retrieved_at="2026-07-27T17:05:00Z",
        expires_at="2026-07-27T19:00:00Z",
        verifier_id=VERIFIER,
        trust_root_id=ROOT,
        proof_verified=True,
        proof_digest="d" * 64,
    )
    expected = ExpectedEvidenceIdentity(
        repository="Blummer92/agent-os",
        pull_request=PR_NUMBER,
        head_sha=HEAD,
        plan_id=PLAN_ID,
        dispatch_decision_id=DECISION_ID,
        provider="google-cloud-build",
        producer_identity="service-account:validation-verifier",
        trigger_identity="trigger:agent-os-pr-validation",
    )
    values = dict(
        evidence=(evidence,),
        expected_identity=expected,
        evaluation_time=EVALUATED_AT,
        seen_evidence_ids=(),
    )
    values.update(overrides)
    return project_evidence_applicability(**values)


def _head_reference(**overrides):
    values = dict(
        decision_id="validation-head-decision:" + "9" * 64,
        disposition="passed",
        prior_head_sha=HEAD,
        current_head_sha=HEAD,
        satisfies_current_head=True,
    )
    values.update(overrides)
    return ValidationHeadReference(**values)


def _projection(state=None, **overrides):
    state = state or _state()
    values = dict(
        handoff=_handoff(state),
        operational_state=state,
        current_head_sha=HEAD,
    )
    values.update(overrides)
    return build_compute_control_projection(ComputeControlEvidence(**values))


# --- pre-execution gate -----------------------------------------------------


def test_blocked_issue_does_not_spend_compute():
    state = _state(readiness=ReadinessState.BLOCKED)
    result = _projection(state, validation_plan=_plan())
    assert result.compute_disposition is ComputeDisposition.DO_NOT_SPEND_COMPUTE_YET
    assert result.primary_blocker == state.blocker_codes[0]
    assert "compute.blocked-prerequisite" in result.reason_codes


def test_ready_but_implementation_unauthorized_does_not_spend_compute():
    state = _state(implementation_authorization=_authority(AuthorizationState.NEEDS_DECISION))
    result = _projection(state, validation_plan=_plan())
    assert result.compute_disposition is ComputeDisposition.DO_NOT_SPEND_COMPUTE_YET
    assert "compute.implementation-not-authorized" in result.reason_codes


def test_unresolved_human_decision_does_not_spend_compute():
    result = _projection(_state(readiness=ReadinessState.NEEDS_DECISION), validation_plan=_plan())
    assert result.compute_disposition is ComputeDisposition.DO_NOT_SPEND_COMPUTE_YET
    assert "compute.human-decision-prerequisite" in result.reason_codes


def test_dependency_blocker_does_not_spend_compute():
    result = _projection(_state(dependency_state=DependencyState.BLOCKED), validation_plan=_plan())
    assert result.compute_disposition is ComputeDisposition.DO_NOT_SPEND_COMPUTE_YET


def test_terminal_state_does_not_spend_compute():
    state = _state(issue_state=IssueState.CLOSED, lifecycle_stage=LifecycleStage.CLOSED)
    result = _projection(state, validation_plan=_plan())
    assert result.compute_disposition is ComputeDisposition.DO_NOT_SPEND_COMPUTE_YET
    assert "compute.terminal-no-compute" in result.reason_codes


def test_roadmap_parent_never_admits_compute():
    result = _projection(_state(lifecycle_stage=LifecycleStage.PLANNING), validation_plan=_plan())
    assert result.compute_disposition is ComputeDisposition.DO_NOT_SPEND_COMPUTE_YET
    assert "compute.roadmap-only-coordination" in result.reason_codes


def test_manual_review_profile_does_not_spend_compute():
    result = _projection(validation_plan=_plan(profile="manual-review", reason_codes=("rule.ambiguous",)))
    assert result.compute_disposition is ComputeDisposition.DO_NOT_SPEND_COMPUTE_YET


# --- focused-first and final validation -------------------------------------


def test_authorized_implementation_with_focused_plan_runs_focused_first():
    result = _projection(validation_plan=_plan())
    assert result.compute_disposition is ComputeDisposition.FOCUSED_VALIDATION_FIRST
    assert result.recommended_validation_or_execution_class == "focused"
    assert "compute.profile-focused" in result.reason_codes


def test_focused_first_never_implies_final_validation_is_satisfied():
    rendered = render_compute_control_projection(_projection(validation_plan=_plan()))
    assert "focused-validation-first" in rendered
    assert "final-cloud-validation-required" not in rendered
    assert "satisfied" not in rendered


def test_review_stage_aggregate_plan_requires_final_cloud_validation():
    # Canonical IssueOperationalState reaches OperationalOutcome.READY only while
    # the implementation lane stays authorized, so a review-stage PR awaiting the
    # final aggregate keeps that authorization rather than dropping it.
    state = _state(
        lifecycle_stage=LifecycleStage.REVIEW,
        ready_for_review_authorization=_authority(AuthorizationState.AUTHORIZED),
        primary_claims=(_claim(state="ready"),),
    )
    result = _projection(
        state,
        validation_plan=_plan(profile="aggregate", reason_codes=("profile.aggregate-configuration",), remote_build_required=True),
    )
    assert result.compute_disposition is ComputeDisposition.FINAL_CLOUD_VALIDATION_REQUIRED
    assert result.recommended_validation_or_execution_class == "aggregate"


def test_static_profile_is_the_cheapest_immediately_runnable_step():
    result = _projection(validation_plan=_plan(profile="static", reason_codes=("profile.documentation-static",)))
    assert result.compute_disposition is ComputeDisposition.RUN_NOW


# --- evidence reuse ---------------------------------------------------------


def test_exact_applicable_evidence_permits_reuse():
    result = _projection(
        validation_plan=_plan(),
        evidence_applicability=_applicability(),
        validation_head_reference=_head_reference(),
    )
    assert result.compute_disposition is ComputeDisposition.REUSE_EXISTING_EVIDENCE
    assert result.last_applicable_validation_reference is not None
    assert "compute.exact-identity-reuse-proven" in result.reason_codes


def test_applicability_alone_never_authorizes_reuse():
    result = _projection(validation_plan=_plan(), evidence_applicability=_applicability())
    assert result.compute_disposition is ComputeDisposition.FOCUSED_VALIDATION_FIRST


def test_head_decision_alone_never_authorizes_reuse():
    result = _projection(validation_plan=_plan(), validation_head_reference=_head_reference())
    assert result.compute_disposition is ComputeDisposition.FOCUSED_VALIDATION_FIRST


def test_non_passing_head_decision_never_authorizes_reuse():
    result = _projection(
        validation_plan=_plan(),
        evidence_applicability=_applicability(),
        validation_head_reference=_head_reference(disposition="failed", satisfies_current_head=False),
    )
    assert result.compute_disposition is ComputeDisposition.FOCUSED_VALIDATION_FIRST


def test_stale_applicability_never_authorizes_reuse():
    stale = _applicability(evaluation_time="2026-07-28T18:00:00Z")
    assert stale.applicability != "fresh-and-applicable"
    result = _projection(
        validation_plan=_plan(),
        evidence_applicability=stale,
        validation_head_reference=_head_reference(),
    )
    assert result.compute_disposition is ComputeDisposition.FOCUSED_VALIDATION_FIRST


# --- head change invalidates old evidence -----------------------------------


def test_head_change_prevents_old_evidence_from_suppressing_validation():
    state = _state(primary_claims=(_claim(head_sha=NEW_HEAD),))
    result = build_compute_control_projection(
        ComputeControlEvidence(
            handoff=_handoff(state, observed_head_sha=NEW_HEAD),
            operational_state=state,
            current_head_sha=NEW_HEAD,
            validation_plan=_plan(head_sha=NEW_HEAD),
            evidence_applicability=_applicability(),
            validation_head_reference=_head_reference(current_head_sha=NEW_HEAD, satisfies_current_head=False),
        )
    )
    assert result.compute_disposition is ComputeDisposition.FOCUSED_VALIDATION_FIRST
    assert result.current_head_sha == NEW_HEAD


def test_head_reference_bound_to_another_head_fails_closed():
    result = _projection(
        validation_plan=_plan(),
        validation_head_reference=_head_reference(current_head_sha=NEW_HEAD),
    )
    assert result.compute_disposition is ComputeDisposition.UNAVAILABLE
    assert "compute.head-identity-conflict" in result.reason_codes


def test_plan_bound_to_another_identity_fails_closed():
    result = _projection(validation_plan=_plan(head_sha=NEW_HEAD))
    assert result.compute_disposition is ComputeDisposition.UNAVAILABLE
    assert "compute.plan-identity-mismatch" in result.reason_codes


def test_plan_bound_to_another_pull_request_fails_closed():
    result = _projection(validation_plan=_plan(pull_request=999))
    assert result.compute_disposition is ComputeDisposition.UNAVAILABLE


# --- duplicate / obsolete run risk ------------------------------------------


def test_active_execution_on_current_head_surfaces_duplicate_risk():
    result = _projection(
        validation_plan=_plan(),
        active_execution=ActiveExecutionReference(
            reference="build-1420-2", head_sha=HEAD, phase="in-progress"
        ),
    )
    assert result.compute_disposition is ComputeDisposition.DUPLICATE_OR_OBSOLETE_RUN_RISK
    assert result.duplicate_or_stale_risk is True
    assert result.active_execution_reference == "build-1420-2"
    assert "compute.active-execution-duplicate" in result.reason_codes


def test_active_execution_on_obsolete_head_surfaces_obsolete_risk():
    result = _projection(
        validation_plan=_plan(),
        active_execution=ActiveExecutionReference(
            reference="build-1420-old", head_sha=NEW_HEAD, phase="queued"
        ),
    )
    assert result.compute_disposition is ComputeDisposition.DUPLICATE_OR_OBSOLETE_RUN_RISK
    assert "compute.active-execution-obsolete-head" in result.reason_codes


def test_duplicate_risk_never_cancels_or_authorizes_anything():
    result = _projection(
        validation_plan=_plan(),
        active_execution=ActiveExecutionReference(
            reference="build-1420-2", head_sha=HEAD, phase="in-progress"
        ),
    )
    payload = serialize_compute_control_projection(result)
    assert payload["authority_created"] is False
    assert payload["side_effects_performed"] is False
    assert not any("cancel" in key for key in payload)


def test_stale_head_decision_is_warning_only_and_still_requires_validation():
    result = _projection(
        validation_plan=_plan(),
        evidence_applicability=_applicability(),
        validation_head_reference=_head_reference(
            disposition="stale-head", prior_head_sha=NEW_HEAD, satisfies_current_head=False
        ),
    )
    assert result.duplicate_or_stale_risk is True
    assert result.compute_disposition is ComputeDisposition.FOCUSED_VALIDATION_FIRST
    assert "compute.duplicate-or-stale-risk-observed" in result.reason_codes


# --- fail-closed currentness ------------------------------------------------


def test_stale_operational_state_fails_closed():
    result = _projection(_state(freshness_state=FreshnessState.STALE), validation_plan=_plan())
    assert result.compute_disposition is ComputeDisposition.UNAVAILABLE
    assert "compute.fail-closed-currentness" in result.reason_codes


def test_conflicting_primary_claims_fail_closed():
    claims = (_claim(), _claim(pull_request_number=1421, branch="agent/1419-duplicate", head_sha=NEW_HEAD))
    result = _projection(_state(primary_claims=claims), validation_plan=_plan())
    assert result.compute_disposition is ComputeDisposition.UNAVAILABLE


def test_handoff_head_conflicting_with_current_head_fails_closed():
    state = _state()
    result = build_compute_control_projection(
        ComputeControlEvidence(
            handoff=_handoff(state, observed_head_sha=NEW_HEAD),
            operational_state=state,
            current_head_sha=HEAD,
            validation_plan=_plan(),
        )
    )
    assert result.compute_disposition is ComputeDisposition.UNAVAILABLE
    assert "compute.head-identity-conflict" in result.reason_codes


def test_handoff_from_a_different_identity_is_rejected():
    state = _state()
    other = _state(issue_number=1418)
    with pytest.raises(ValueError, match="different identities"):
        ComputeControlEvidence(
            handoff=_handoff(other, observed_head_sha=HEAD),
            operational_state=state,
            current_head_sha=HEAD,
        )


def test_tampered_operational_state_is_rejected():
    state = _state()
    handoff = _handoff(state)
    object.__setattr__(state, "state_id", handoff.canonical_state_reference)
    evidence = ComputeControlEvidence(
        handoff=handoff, operational_state=state, current_head_sha=HEAD
    )
    object.__setattr__(state, "issue_number", 1418)
    with pytest.raises(ValueError, match="operational state validation failed"):
        build_compute_control_projection(evidence)


# --- missing evidence -------------------------------------------------------


def test_missing_validation_plan_fabricates_no_status():
    result = _projection()
    assert result.compute_disposition is ComputeDisposition.UNAVAILABLE
    assert result.recommended_validation_or_execution_class is None
    assert "compute.validation-plan-unavailable" in result.reason_codes


def test_missing_optional_references_stay_explicitly_unavailable():
    rendered = render_compute_control_projection(_projection())
    assert "Recommended validation class: unavailable" in rendered
    assert "Active execution: unavailable" in rendered
    assert "Last applicable validation: unavailable" in rendered
    assert "Measured compute metadata: unavailable" in rendered


def test_measured_compute_metadata_is_carried_only_as_a_reference():
    result = _projection(
        validation_plan=_plan(),
        measured_compute_metadata_reference="compute-evidence-summary:" + "7" * 64,
    )
    payload = serialize_compute_control_projection(result)
    assert payload["measured_compute_metadata_reference"].startswith("compute-evidence-summary:")
    assert not any("cost" in key or "dollar" in key or "estimate" in key for key in payload)


def test_no_percentage_progress_is_synthesized():
    assert "%" not in render_compute_control_projection(_projection(validation_plan=_plan()))


# --- determinism, authority, bounds -----------------------------------------


def test_identical_input_produces_identical_output():
    first = _projection(validation_plan=_plan())
    second = _projection(validation_plan=_plan())
    assert first == second
    assert first.projection_id == second.projection_id
    assert serialize_compute_control_projection(first) == serialize_compute_control_projection(second)
    assert render_compute_control_projection(first) == render_compute_control_projection(second)


def test_different_input_produces_a_different_projection_identity():
    baseline = _projection(validation_plan=_plan())
    changed = _projection(validation_plan=_plan(profile="static", reason_codes=("profile.documentation-static",)))
    assert baseline.projection_id != changed.projection_id


def test_projection_creates_no_authority_and_performs_no_side_effects():
    state = _state(
        merge_authorization=_authority(AuthorizationState.AUTHORIZED),
        closure_authorization=_authority(AuthorizationState.AUTHORIZED),
    )
    result = _projection(state, validation_plan=_plan())
    assert result.authority_created is False
    assert result.side_effects_performed is False
    assert result.notion_write_performed is False
    payload = serialize_compute_control_projection(result)
    assert payload["authority_created"] is False
    assert not any("authorized" in key for key in payload)


def test_no_notion_write_is_ever_performed_or_representable():
    payload = serialize_compute_control_projection(_projection(validation_plan=_plan()))
    assert payload["notion_write_performed"] is False
    source = MODULE_PATH.read_text(encoding="utf-8").lower()
    assert "notion_client" not in source and "notion-client" not in source


def test_canonical_identity_and_schema_are_preserved():
    result = _projection(validation_plan=_plan())
    assert result.schema_name == COMPUTE_CONTROL_PROJECTION_SCHEMA_NAME
    assert result.schema_version == COMPUTE_CONTROL_PROJECTION_SCHEMA_VERSION
    assert result.repository == "Blummer92/agent-os"
    assert result.issue_number == 1419
    assert result.pull_request_number == PR_NUMBER
    assert result.source_revision == REVISION
    assert result.base_handoff_projection_reference == _handoff(_state()).handoff_id


def test_render_and_serialization_stay_bounded():
    result = _projection(
        validation_plan=_plan(),
        evidence_applicability=_applicability(),
        validation_head_reference=_head_reference(),
        measured_compute_metadata_reference="compute-evidence-summary:" + "7" * 64,
    )
    rendered = render_compute_control_projection(result)
    assert len(rendered.encode("utf-8")) < 64 * 1024
    assert len(rendered.splitlines()) == 14


def test_serialization_rejects_a_foreign_object():
    with pytest.raises(TypeError, match="exact ComputeControlProjection"):
        serialize_compute_control_projection(object())


def test_head_disposition_vocabulary_mirrors_the_canonical_owner():
    supersession = (
        MODULE_PATH.resolve().parents[2]
        / "08_Tooling"
        / "agent-os-execution-service"
        / "src"
        / "agent_os_execution_service"
        / "validation_supersession.py"
    )
    tree = ast.parse(supersession.read_text(encoding="utf-8"), filename=str(supersession))
    canonical = {
        node.value.value
        for klass in tree.body
        if isinstance(klass, ast.ClassDef) and klass.name == "ValidationHeadDisposition"
        for node in klass.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
    }
    assert canonical == set(VALIDATION_HEAD_DISPOSITIONS)


def test_unsupported_head_disposition_is_rejected():
    with pytest.raises(ValueError, match="canonical validation-head vocabulary"):
        ValidationHeadReference(
            decision_id="validation-head-decision:" + "9" * 64,
            disposition="invented-disposition",
            prior_head_sha=HEAD,
            current_head_sha=HEAD,
            satisfies_current_head=True,
        )


def test_terminal_phase_is_not_an_active_execution():
    with pytest.raises(ValueError, match="non-terminal active execution phase"):
        ActiveExecutionReference(reference="build-1420-2", head_sha=HEAD, phase="terminal")


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
        "threading",
        "asyncio",
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


def test_module_creates_no_second_router_selector_or_scheduler():
    source = MODULE_PATH.read_text(encoding="utf-8").lower()
    for banned in ("workflow_scheduler", "dispatch(", "cancel(", "def select_", "def route_"):
        assert banned not in source
