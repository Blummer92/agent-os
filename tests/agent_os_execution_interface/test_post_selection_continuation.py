"""#1237 post-selection capability-transition conformance.

Covers the two locked #1237 regressions -- the historical missing-local-``gh``
case and the #1213 truncated-read -> exact-blob -> continue case -- plus the
adversarial acceptance scenarios that keep this seam from becoming a retry
engine, a second router, or an absorber of adjacent lifecycles.
"""

from __future__ import annotations

import dataclasses

import pytest

from agent_os_execution_service.execution_surface_availability import (
    ExecutionSurfaceAvailabilityOutcome,
    evaluate_execution_surface_availability,
)
from agent_os_execution_service.executor_routing import (
    ExecutorCapability,
    ExecutorRoute,
    select_executor_route,
)
from scripts.agent_os_execution_interface.post_selection_continuation import (
    ContinuationClassification,
    ContinuationDecision,
    ContinuationLineage,
    ContinuationObligation,
    ContinuationReason,
    EVIDENCE_COMPATIBILITY_OWNER,
    NON_ABSORBED_DOMAIN_OWNERS,
    NonAbsorbedDomain,
    POST_SELECTION_CONTINUATION_SCHEMA_NAME,
    POST_SELECTION_CONTINUATION_SCHEMA_VERSION,
    PostSelectionAttemptEvidence,
    PriorAttemptEffect,
    SEMANTIC_NO_PROGRESS_OWNER,
    classify_post_selection_continuation,
)


#: The one authorized #1213-shaped lineage every scenario continues.
LINEAGE = ContinuationLineage(
    repository="Blummer92/agent-os",
    issue_number=1213,
    branch="claude/1213-changelog",
    pull_request=1263,
    checkpoint_id="checkpoint:1213",
    lease_id="lease:1213",
)

UNAVAILABLE = ExecutionSurfaceAvailabilityOutcome.SELECTED_SURFACE_UNAVAILABLE


def evidence(**overrides) -> PostSelectionAttemptEvidence:
    values = {
        "operation_id": "replace-changelog-whole-file",
        "lineage": LINEAGE,
        "surface_outcome": UNAVAILABLE,
        "approved_alternative_capability": "github-exact-blob-read",
        "target_identity_reacquired": True,
    }
    values.update(overrides)
    return PostSelectionAttemptEvidence(**values)


# --------------------------------------------------------------------------
# Regression A -- historical missing local `gh` (#1233)
# --------------------------------------------------------------------------


def local_cli_route():
    return select_executor_route(
        repository="Blummer92/agent-os",
        issue_or_handoff_identity="issue:1213",
        requested_operation="replace-changelog-whole-file",
        required_capabilities=(ExecutorCapability.MULTI_FILE_IMPLEMENTATION,),
        governed_runner_capabilities=(),
        governed_runner_available=False,
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
        created_at="2026-08-20T00:00:00Z",
        expires_at="2026-08-20T01:00:00Z",
        invalidation_conditions=("repository-head-changed",),
        execution_service_request_fingerprint_or_none="execution-request:1213",
        operating_mode_decision_id_or_none="operating-mode:1213",
        executable_lane_selection_id_or_none="lane-selection:1213",
    )


def test_missing_local_gh_continues_through_the_approved_alternative():
    """A missing local `gh` is surface evidence, never a mission blocker."""
    route_decision = local_cli_route()
    assert route_decision.selected_route is ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK

    availability = evaluate_execution_surface_availability(
        route_decision,
        local_git_available=True,
        local_gh_available=False,
        connector_native_available=True,
        local_cli_explicitly_selected=True,
    )
    assert availability.outcome is UNAVAILABLE

    decision = classify_post_selection_continuation(
        evidence(
            surface_outcome=availability.outcome,
            approved_alternative_capability="governed-runner",
        )
    )

    assert (
        decision.classification
        is ContinuationClassification.CAPABILITY_ALTERNATIVE_AVAILABLE
    )
    assert decision.continue_automatically is True
    assert decision.blocker is None
    assert decision.capability_limitation_is_mission_blocker is False
    assert decision.lineage == LINEAGE


# --------------------------------------------------------------------------
# Regression B -- #1213 truncated read -> exact blob -> continue
# --------------------------------------------------------------------------


def test_truncated_whole_file_view_fails_closed_before_the_alternate_write():
    """A whole-file replacement may not proceed from a truncated view."""
    decision = classify_post_selection_continuation(
        evidence(requires_exact_blob_identity=True)
    )

    assert (
        decision.classification
        is ContinuationClassification.CURRENTNESS_OR_IDENTITY_UNPROVEN
    )
    assert ContinuationReason.EXACT_BLOB_IDENTITY_UNPROVEN in decision.reason_codes
    assert ContinuationObligation.REACQUIRE_EXACT_BLOB in decision.obligations
    assert decision.mutation_permitted is False
    assert decision.continue_automatically is False


def test_exact_blob_capability_clears_the_blocker_and_continues_the_same_lineage():
    """The locked #1213 regression: discovery is consumed, not reported."""
    decision = classify_post_selection_continuation(
        evidence(
            requires_exact_blob_identity=True,
            exact_blob_identity_reacquired=True,
        )
    )

    assert (
        decision.classification
        is ContinuationClassification.CAPABILITY_ALTERNATIVE_AVAILABLE
    )
    assert decision.continue_automatically is True
    assert decision.mutation_permitted is True
    assert decision.alternative_capability == "github-exact-blob-read"
    # Discovering the alternative must never surface as a handoff.
    assert decision.blocker is None
    assert decision.clearing_condition is None
    assert ContinuationObligation.PRESERVE_EXISTING_LINEAGE in decision.obligations
    assert ContinuationObligation.ROUTE_THROUGH_OWNING_WRITER in decision.obligations
    assert decision.lineage == LINEAGE


# --------------------------------------------------------------------------
# Prior-effect reconciliation
# --------------------------------------------------------------------------


def test_ambiguous_prior_effect_reads_back_before_any_alternate_write():
    decision = classify_post_selection_continuation(
        evidence(prior_effect=PriorAttemptEffect.AMBIGUOUS)
    )

    assert (
        decision.classification
        is ContinuationClassification.PARTIAL_EFFECT_RECONCILIATION_REQUIRED
    )
    assert ContinuationObligation.READ_BACK_CANONICAL_STATE in decision.obligations
    assert decision.mutation_permitted is False
    assert decision.continue_automatically is False


def test_already_achieved_state_converges_without_a_second_mutation():
    decision = classify_post_selection_continuation(
        evidence(prior_effect=PriorAttemptEffect.DESIRED_STATE_ALREADY_PRESENT)
    )

    assert (
        decision.classification
        is ContinuationClassification.CAPABILITY_ALTERNATIVE_AVAILABLE
    )
    assert decision.continue_automatically is True
    assert decision.mutation_permitted is False
    assert ContinuationObligation.SUPPRESS_DUPLICATE_MUTATION in decision.obligations
    assert ContinuationReason.DESIRED_STATE_ALREADY_PRESENT in decision.reason_codes


def test_proven_zero_effect_permits_the_alternate_mutation():
    decision = classify_post_selection_continuation(
        evidence(prior_effect=PriorAttemptEffect.NONE_PROVEN)
    )

    assert decision.mutation_permitted is True
    assert decision.continue_automatically is True


# --------------------------------------------------------------------------
# Currentness and runtime-surface transition
# --------------------------------------------------------------------------


def test_unreacquired_head_fails_closed_after_the_failure():
    decision = classify_post_selection_continuation(
        evidence(target_identity_reacquired=False)
    )

    assert (
        decision.classification
        is ContinuationClassification.CURRENTNESS_OR_IDENTITY_UNPROVEN
    )
    assert ContinuationObligation.REACQUIRE_EXACT_HEAD in decision.obligations
    assert decision.continue_automatically is False


def test_runtime_surface_transition_requires_1201_evidence_compatibility():
    decision = classify_post_selection_continuation(
        evidence(runtime_surface_transition=True)
    )

    assert (
        decision.classification
        is ContinuationClassification.CURRENTNESS_OR_IDENTITY_UNPROVEN
    )
    assert ContinuationReason.CROSS_SURFACE_EVIDENCE_UNVERIFIED in decision.reason_codes
    assert decision.delegated_owner == EVIDENCE_COMPATIBILITY_OWNER
    assert ContinuationObligation.REUSE_EVIDENCE_COMPATIBILITY in decision.obligations


def test_confirmed_cross_surface_evidence_continues_and_keeps_the_1201_obligation():
    decision = classify_post_selection_continuation(
        evidence(
            runtime_surface_transition=True,
            evidence_compatibility_confirmed=True,
        )
    )

    assert (
        decision.classification
        is ContinuationClassification.CAPABILITY_ALTERNATIVE_AVAILABLE
    )
    assert ContinuationObligation.REUSE_EVIDENCE_COMPATIBILITY in decision.obligations
    assert decision.delegated_owner == EVIDENCE_COMPATIBILITY_OWNER


# --------------------------------------------------------------------------
# Authority, scope, lease, and lineage boundaries
# --------------------------------------------------------------------------


def test_active_foreign_lease_prevents_a_competing_execution():
    decision = classify_post_selection_continuation(evidence(active_foreign_lease=True))

    assert decision.classification is ContinuationClassification.AUTHORITY_OR_SCOPE_BOUNDARY
    assert ContinuationReason.ACTIVE_FOREIGN_LEASE in decision.reason_codes
    assert decision.continue_automatically is False
    assert decision.lease_acquired is False
    assert decision.scheduler_invoked is False


def test_alternative_that_widens_authority_is_rejected():
    decision = classify_post_selection_continuation(
        evidence(alternative_widens_authority=True)
    )

    assert decision.classification is ContinuationClassification.AUTHORITY_OR_SCOPE_BOUNDARY
    assert ContinuationReason.ALTERNATIVE_WIDENS_AUTHORITY in decision.reason_codes


@pytest.mark.parametrize(
    "field_name, value",
    [
        ("branch", "claude/other-branch"),
        ("pull_request", 9999),
        ("checkpoint_id", "checkpoint:other"),
        ("issue_number", 1259),
    ],
)
def test_alternative_targeting_a_different_lineage_is_never_substituted(
    field_name, value
):
    decision = classify_post_selection_continuation(
        evidence(
            alternative_lineage=dataclasses.replace(LINEAGE, **{field_name: value})
        )
    )

    assert decision.classification is ContinuationClassification.AUTHORITY_OR_SCOPE_BOUNDARY
    assert (
        ContinuationReason.ALTERNATIVE_TARGETS_DIFFERENT_LINEAGE in decision.reason_codes
    )
    assert decision.competing_lineage_created is False


def test_material_decision_is_not_mechanically_substituted():
    decision = classify_post_selection_continuation(
        evidence(material_decision_required=True)
    )

    assert decision.classification is ContinuationClassification.MATERIAL_USER_DECISION
    assert decision.continue_automatically is False


def test_route_already_requiring_a_human_decision_stays_a_decision():
    decision = classify_post_selection_continuation(
        evidence(surface_outcome=ExecutionSurfaceAvailabilityOutcome.NEEDS_DECISION)
    )

    assert decision.classification is ContinuationClassification.MATERIAL_USER_DECISION


def test_a_transition_grants_no_merge_closure_or_external_authority():
    decision = classify_post_selection_continuation(evidence())

    assert decision.execution_authorized is False
    assert decision.github_writes_authorized is False
    assert decision.merge_authorized is False
    assert decision.issue_closure_authorized is False
    assert decision.external_writes_authorized is False
    assert decision.side_effects_performed is False


# --------------------------------------------------------------------------
# Stopping without a capable route, and without an unbounded retry loop
# --------------------------------------------------------------------------


def test_no_approved_alternative_returns_one_blocker_and_its_clearing_condition():
    decision = classify_post_selection_continuation(
        evidence(approved_alternative_capability=None)
    )

    assert (
        decision.classification is ContinuationClassification.NO_CAPABLE_AUTHORIZED_ROUTE
    )
    assert decision.blocker
    assert decision.clearing_condition
    assert decision.continue_automatically is False


def test_repeated_equivalent_transition_delegates_to_1200_instead_of_looping():
    decision = classify_post_selection_continuation(
        evidence(equivalent_transition_repeated=True)
    )

    assert (
        decision.classification is ContinuationClassification.NO_CAPABLE_AUTHORIZED_ROUTE
    )
    assert decision.delegated_owner == SEMANTIC_NO_PROGRESS_OWNER
    assert ContinuationReason.EQUIVALENT_TRANSITION_REPEATED in decision.reason_codes
    assert decision.continue_automatically is False


# --------------------------------------------------------------------------
# Adjacent lifecycles are refused, never absorbed
# --------------------------------------------------------------------------


@pytest.mark.parametrize("domain", tuple(NonAbsorbedDomain))
def test_adjacent_lifecycles_are_refused_and_name_their_owner(domain):
    with pytest.raises(ValueError) as excinfo:
        classify_post_selection_continuation(evidence(non_absorbed_domain=domain))

    assert NON_ABSORBED_DOMAIN_OWNERS[domain] in str(excinfo.value)


@pytest.mark.parametrize(
    "outcome",
    [
        ExecutionSurfaceAvailabilityOutcome.GOVERNED_RUNNER_AVAILABLE,
        ExecutionSurfaceAvailabilityOutcome.CONNECTOR_NATIVE_AVAILABLE,
        ExecutionSurfaceAvailabilityOutcome.LOCAL_CLI_SELECTED,
    ],
)
def test_an_available_surface_needs_no_continuation_decision(outcome):
    with pytest.raises(ValueError, match="only after a capability limitation"):
        classify_post_selection_continuation(evidence(surface_outcome=outcome))


# --------------------------------------------------------------------------
# Contract integrity
# --------------------------------------------------------------------------


def test_an_available_alternative_can_never_be_constructed_as_a_blocker():
    decision = classify_post_selection_continuation(evidence())
    with pytest.raises(ValueError, match="must not carry a blocker"):
        dataclasses.replace(decision, blocker="stopped to tell the user")


def test_a_non_continuing_classification_can_never_permit_mutation():
    decision = classify_post_selection_continuation(
        evidence(prior_effect=PriorAttemptEffect.AMBIGUOUS)
    )
    with pytest.raises(ValueError, match="only an available alternative may mutate"):
        dataclasses.replace(decision, mutation_permitted=True)


def test_decision_id_is_deterministic_and_tamper_evident():
    first = classify_post_selection_continuation(evidence())
    second = classify_post_selection_continuation(evidence())
    assert first == second
    assert first.decision_id.startswith("post-selection-continuation:")

    with pytest.raises(ValueError, match="decision_id does not match"):
        dataclasses.replace(first, operation_id="a-different-operation")


def test_schema_identity_is_pinned():
    decision = classify_post_selection_continuation(evidence())
    assert decision.schema_name == POST_SELECTION_CONTINUATION_SCHEMA_NAME
    assert decision.schema_version == POST_SELECTION_CONTINUATION_SCHEMA_VERSION
    assert type(decision) is ContinuationDecision


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"prior_effect": PriorAttemptEffect.AMBIGUOUS},
        {"approved_alternative_capability": None},
        {"active_foreign_lease": True},
        {"target_identity_reacquired": False},
        {"material_decision_required": True},
        {"equivalent_transition_repeated": True},
    ],
)
def test_every_classification_preserves_the_existing_lineage(overrides):
    decision = classify_post_selection_continuation(evidence(**overrides))

    assert decision.lineage == LINEAGE
    assert ContinuationObligation.PRESERVE_EXISTING_LINEAGE in decision.obligations
    assert ContinuationObligation.ROUTE_THROUGH_OWNING_WRITER in decision.obligations
    assert decision.competing_lineage_created is False


def test_lineage_rejects_malformed_identity():
    with pytest.raises(ValueError, match="owner/name"):
        ContinuationLineage(repository="agent-os", issue_number=1213)
    with pytest.raises(TypeError, match="issue_number"):
        ContinuationLineage(repository="Blummer92/agent-os", issue_number=0)
