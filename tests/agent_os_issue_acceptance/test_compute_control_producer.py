"""Focused #1439 tests for the canonical #1419 production composition seam."""

from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.agent_os_issue_acceptance.coding_command_center_handoff import (
    CodingCommandCenterEvidence,
    build_coding_command_center_handoff,
)
from scripts.agent_os_issue_acceptance.compute_control_producer import (
    ComputeControlProductionEvidence,
    produce_compute_control_projection,
    produce_serialized_compute_control_projection,
)
from scripts.agent_os_issue_acceptance.compute_control_projection import (
    ActiveExecutionReference,
    ComputeDisposition,
    ValidationHeadReference,
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

REPOSITORY = "Blummer92/agent-os"
ISSUE = 1359
PR = 1360
HEAD = "c" * 40
OTHER_HEAD = "d" * 40
REVISION = "e" * 40
AUTH_ID = "approval:" + "a" * 64
DIGEST = "b" * 64
PLAN_ID = "validation-plan:" + "1" * 64
DISPATCH_ID = "validation-dispatch-decision:" + "2" * 64


def _authority(state: AuthorizationState) -> AuthorityProjection:
    return AuthorityProjection(
        state=state,
        evidence_id=AUTH_ID if state in {AuthorizationState.AUTHORIZED, AuthorizationState.STALE} else None,
    )


def _claim(*, head: str = HEAD, state: str = "ready") -> PrimaryIssueClaim:
    return PrimaryIssueClaim(
        pull_request_number=PR,
        branch="agent/1359-aggregate-timing",
        head_sha=head,
        state=state,
    )


def _state(
    *,
    claim: PrimaryIssueClaim | None = None,
    readiness: ReadinessState = ReadinessState.READY,
    freshness: FreshnessState = FreshnessState.CURRENT,
    authorization: AuthorizationState = AuthorizationState.AUTHORIZED,
):
    claim = claim or _claim()
    return build_issue_operational_state(
        IssueOperationalEvidence(
            repository=REPOSITORY,
            issue_number=ISSUE,
            source_revision=REVISION,
            observed_at="2026-08-27T21:00:00Z",
            evidence_ids=(),
            source_state=SourceState.COMPLETE,
            issue_state=IssueState.OPEN,
            lifecycle_stage=LifecycleStage.IMPLEMENTATION,
            terminal_disposition=TerminalDisposition.NONE,
            readiness=readiness,
            implementation_authorization=_authority(authorization),
            ready_for_review_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
            execution_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
            merge_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
            closure_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
            external_write_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
            dependency_state=DependencyState.CLEAR,
            primary_claims=(claim,),
            validation_state=ValidationState.NOT_RUN,
            freshness_state=freshness,
            observed_labels=("status:ready",),
        )
    )


def _handoff_evidence(state, *, observed_head: str = HEAD):
    return CodingCommandCenterEvidence(
        operational_state=state,
        source_revision=REVISION,
        observed_head_sha=observed_head,
    )


def _plan(*, head: str = HEAD, pull_request: int = PR, profile: str = "focused"):
    return ValidationPlan(
        selector_version="1.0.0",
        repository=REPOSITORY,
        pull_request=pull_request,
        base_sha=REVISION,
        head_sha=head,
        profile=profile,
        commands=("python -m pytest tests/test_validate_all_timing.py -q",),
        command_set_digest=DIGEST,
        reason_codes=("profile.focused-package",),
        remote_build_required=False,
    )


def _applicability(*, head: str = HEAD, evaluation_time: str = "2026-08-27T21:00:00Z"):
    normalized = NormalizedRemoteValidationEvidence(
        schema_name="agent-os-remote-validation-evidence",
        schema_version="1.0",
        evidence_id="evidence:1359-focused",
        source_type="provider-api",
        repository=REPOSITORY,
        pull_request=PR,
        head_sha=head,
        profile="focused",
        selector_version="1.0.0",
        command_set_digest=DIGEST,
        plan_id=PLAN_ID,
        dispatch_decision_id=DISPATCH_ID,
        build_id="build-1359-focused",
        provider="google-cloud-build",
        producer_identity="service-account:validation-verifier",
        trigger_identity="trigger:agent-os-pr-validation",
        terminal_status="succeeded",
        retrieved_at="2026-08-27T20:30:00Z",
        expires_at="2026-08-27T22:30:00Z",
        verifier_id="cloud-build-verifier:v1",
        trust_root_id="github-oidc:blummer92/agent-os",
        proof_verified=True,
        proof_digest="f" * 64,
    )
    expected = ExpectedEvidenceIdentity(
        repository=REPOSITORY,
        pull_request=PR,
        head_sha=head,
        plan_id=PLAN_ID,
        dispatch_decision_id=DISPATCH_ID,
        provider="google-cloud-build",
        producer_identity="service-account:validation-verifier",
        trigger_identity="trigger:agent-os-pr-validation",
    )
    return project_evidence_applicability(
        evidence=(normalized,),
        expected_identity=expected,
        evaluation_time=evaluation_time,
        seen_evidence_ids=(),
    )


def _production(**overrides) -> ComputeControlProductionEvidence:
    claim = overrides.pop("primary_claim", _claim())
    state = overrides.pop("operational_state", _state(claim=claim))
    values = dict(
        operational_state=state,
        current_head_sha=HEAD,
        primary_claim=claim,
        handoff_evidence=_handoff_evidence(state),
        validation_plan=_plan(),
    )
    values.update(overrides)
    return ComputeControlProductionEvidence(**values)


def test_1359_shaped_current_evidence_produces_canonical_projection():
    payload = produce_serialized_compute_control_projection(_production())
    assert payload["schema_name"] == "agent-os-compute-control-projection"
    assert payload["schema_version"] == "1.0"
    assert payload["repository"] == REPOSITORY
    assert payload["issue_number"] == ISSUE
    assert payload["pull_request_number"] == PR
    assert payload["current_head_sha"] == HEAD
    assert payload["compute_disposition"] == "focused-validation-first"
    assert payload["authority_created"] is False
    assert payload["side_effects_performed"] is False
    assert payload["notion_write_performed"] is False
    assert payload["projection_id"].startswith("compute-control-projection:")


def test_existing_1097_handoff_can_be_consumed_without_rebuilding_it():
    state = _state()
    handoff = build_coding_command_center_handoff(_handoff_evidence(state))
    result = produce_compute_control_projection(
        ComputeControlProductionEvidence(
            operational_state=state,
            current_head_sha=HEAD,
            primary_claim=_claim(),
            handoff=handoff,
            validation_plan=_plan(),
        )
    )
    assert result.base_handoff_projection_reference == handoff.handoff_id


def test_exact_same_evidence_is_deterministic():
    evidence = _production()
    first = produce_serialized_compute_control_projection(evidence)
    second = produce_serialized_compute_control_projection(evidence)
    assert first == second


def test_single_claim_requires_exact_claim_object():
    state = _state()
    with pytest.raises(ValueError, match="requires its exact PrimaryIssueClaim"):
        ComputeControlProductionEvidence(
            operational_state=state,
            current_head_sha=HEAD,
            handoff_evidence=_handoff_evidence(state),
            validation_plan=_plan(),
        )


def test_current_head_must_match_canonical_primary_claim():
    with pytest.raises(ValueError, match="current head conflicts"):
        _production(current_head_sha=OTHER_HEAD)


def test_claim_identity_cannot_be_swapped_between_lineages():
    canonical = _claim()
    state = _state(claim=canonical)
    other = PrimaryIssueClaim(
        pull_request_number=PR,
        branch="agent/1359-other-lineage",
        head_sha=HEAD,
        state="ready",
    )
    with pytest.raises(ValueError, match="identity conflicts"):
        _production(operational_state=state, primary_claim=other, handoff_evidence=_handoff_evidence(state))


def test_handoff_evidence_must_bind_same_operational_state():
    state = _state()
    stale_state = _state(freshness=FreshnessState.STALE)
    with pytest.raises(ValueError, match="different identities"):
        _production(operational_state=state, handoff_evidence=_handoff_evidence(stale_state))


def test_stale_operational_state_fails_closed_through_existing_1419_logic():
    claim = _claim()
    state = _state(claim=claim, freshness=FreshnessState.STALE)
    result = produce_compute_control_projection(
        _production(
            operational_state=state,
            primary_claim=claim,
            handoff_evidence=_handoff_evidence(state),
        )
    )
    assert result.compute_disposition is ComputeDisposition.UNAVAILABLE
    assert "compute.fail-closed-currentness" in result.reason_codes


def test_missing_implementation_authorization_uses_existing_operational_semantics():
    claim = _claim()
    state = _state(claim=claim, authorization=AuthorizationState.NEEDS_DECISION)
    result = produce_compute_control_projection(
        _production(
            operational_state=state,
            primary_claim=claim,
            handoff_evidence=_handoff_evidence(state),
        )
    )
    assert result.compute_disposition is ComputeDisposition.DO_NOT_SPEND_COMPUTE_YET
    assert "compute.implementation-not-authorized" in result.reason_codes


def test_validation_plan_identity_mismatch_fails_closed_in_1419():
    result = produce_compute_control_projection(_production(validation_plan=_plan(head=OTHER_HEAD)))
    assert result.compute_disposition is ComputeDisposition.UNAVAILABLE
    assert "compute.plan-identity-mismatch" in result.reason_codes


def test_stale_applicability_cannot_become_reuse():
    result = produce_compute_control_projection(
        _production(
            evidence_applicability=_applicability(evaluation_time="2026-08-28T21:00:00Z"),
            validation_head_reference=ValidationHeadReference(
                decision_id="validation-head-decision:" + "9" * 64,
                disposition="passed",
                prior_head_sha=HEAD,
                current_head_sha=HEAD,
                satisfies_current_head=True,
            ),
        )
    )
    assert result.compute_disposition is ComputeDisposition.FOCUSED_VALIDATION_FIRST


def test_stale_validation_head_cannot_satisfy_current_head():
    result = produce_compute_control_projection(
        _production(
            evidence_applicability=_applicability(),
            validation_head_reference=ValidationHeadReference(
                decision_id="validation-head-decision:" + "9" * 64,
                disposition="stale-head",
                prior_head_sha=OTHER_HEAD,
                current_head_sha=HEAD,
                satisfies_current_head=False,
            ),
        )
    )
    assert result.compute_disposition is ComputeDisposition.FOCUSED_VALIDATION_FIRST
    assert result.duplicate_or_stale_risk is True


def test_active_execution_uses_existing_duplicate_risk_semantics():
    result = produce_compute_control_projection(
        _production(
            active_execution=ActiveExecutionReference(
                reference="execution:1359-current",
                head_sha=HEAD,
                phase="in-progress",
            )
        )
    )
    assert result.compute_disposition is ComputeDisposition.DUPLICATE_OR_OBSOLETE_RUN_RISK
    assert result.active_execution_reference == "execution:1359-current"


def test_tampered_production_evidence_fails_closed_on_revalidation():
    evidence = _production()
    object.__setattr__(evidence, "current_head_sha", OTHER_HEAD)
    with pytest.raises(ValueError, match="current head conflicts"):
        produce_compute_control_projection(evidence)


def test_producer_module_contains_no_external_io_primitives():
    # This is intentionally a composition module: no injected network client,
    # filesystem path, subprocess runner, Notion client, or Scheduler handle is
    # part of the production contract.
    fields = set(ComputeControlProductionEvidence.__dataclass_fields__)
    forbidden = {"github_client", "notion_client", "scheduler", "subprocess", "path", "gcp_client"}
    assert fields.isdisjoint(forbidden)
