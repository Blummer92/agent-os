"""Phase 1 B5: ExecutableLaneSelection carries the population query/filter.

Covers: the additive `population_source_query` field, its binding into the
content-addressed selection_id, serialization round-trip, and backward
compatibility (payloads written before the field existed still deserialize;
selections without a query keep their historical selection_id).
"""

from __future__ import annotations

import json

import pytest

from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    DependencyState,
    FreshnessState,
    IssueOperationalEvidence,
    IssueState,
    LifecycleStage,
    ReadinessState,
    SourceState,
    TerminalDisposition,
    ValidationState,
    build_issue_operational_state,
)
from scripts.agent_os_issue_acceptance.operating_mode import (
    EnvironmentCapabilityEvidence,
    EnvironmentCapabilityState,
    evaluate_operating_mode_decision,
)
from scripts.agent_os_candidate_packet.executable_lane_selection import (
    CandidateIssueEvidence,
    deserialize_executable_lane_selection,
    select_executable_lanes,
    serialize_executable_lane_selection,
)

SOURCE_SHA = "a" * 40
APPROVAL_ID = "approval:" + "1" * 64
ENV_EVIDENCE_ID = "environment-capability:" + "2" * 64
QUERY = "repo=Blummer92/agent-os state=open"


def authority(state: AuthorizationState) -> AuthorityProjection:
    return AuthorityProjection(
        state=state,
        evidence_id=APPROVAL_ID
        if state
        in {
            AuthorizationState.AUTHORIZED,
            AuthorizationState.STALE,
            AuthorizationState.NEEDS_DECISION,
        }
        else None,
    )


def candidate(issue_number: int = 901) -> CandidateIssueEvidence:
    evidence = IssueOperationalEvidence(
        repository="Blummer92/agent-os",
        issue_number=issue_number,
        source_revision=SOURCE_SHA,
        observed_at="2026-08-04T12:00:00Z",
        evidence_ids=(APPROVAL_ID,),
        source_state=SourceState.COMPLETE,
        issue_state=IssueState.OPEN,
        lifecycle_stage=LifecycleStage.PLANNING,
        terminal_disposition=TerminalDisposition.NONE,
        readiness=ReadinessState.READY,
        implementation_authorization=authority(AuthorizationState.AUTHORIZED),
        ready_for_review_authorization=authority(AuthorizationState.AUTHORIZED),
        execution_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
        merge_authorization=authority(AuthorizationState.AUTHORIZED),
        closure_authorization=authority(AuthorizationState.AUTHORIZED),
        external_write_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
        dependency_state=DependencyState.CLEAR,
        primary_claims=(),
        validation_state=ValidationState.NOT_RUN,
        freshness_state=FreshnessState.CURRENT,
        observed_labels=(),
    )
    state = build_issue_operational_state(evidence)
    decision = evaluate_operating_mode_decision(
        state,
        "build",
        EnvironmentCapabilityEvidence(
            local_execution_state=EnvironmentCapabilityState.VERIFIED,
            push_state=EnvironmentCapabilityState.VERIFIED,
            evidence_id=ENV_EVIDENCE_ID,
            bound_source_revision=None,
            observed_source_revision=None,
        ),
    )
    return CandidateIssueEvidence(
        issue_number=issue_number,
        operational_state=state,
        mode_decision=decision,
        dependency_depth=0,
        substitutable=True,
    )


def select(**overrides):
    arguments = {
        "campaign_id": "campaign-b5",
        "requested_lane_count": 1,
        "substitution_allowed": False,
        "explicit_request_order": (),
        "candidates": (candidate(),),
    }
    arguments.update(overrides)
    return select_executable_lanes(**arguments)


def test_selection_carries_population_source_query() -> None:
    selection = select(population_source_query=QUERY)
    assert selection.population_source_query == QUERY
    assert selection.to_dict()["population_source_query"] == QUERY


def test_selection_defaults_to_no_population_query() -> None:
    selection = select()
    assert selection.population_source_query is None
    assert "population_source_query" not in selection.to_dict()


def test_query_binds_into_selection_id() -> None:
    without_query = select()
    with_query = select(population_source_query=QUERY)
    assert without_query.selection_id != with_query.selection_id
    assert with_query.selection_id.startswith("executable-lane-selection:")
    # Same query, same content: id is stable.
    assert select(population_source_query=QUERY).selection_id == with_query.selection_id
    # Different query: different id.
    other = select(population_source_query="repo=Blummer92/agent-os state=closed")
    assert other.selection_id != with_query.selection_id


def test_selection_id_unchanged_when_query_not_carried() -> None:
    """Backward compatibility: existing consumers keep their exact id."""
    first = select()
    second = select()
    assert first.selection_id == second.selection_id


def test_rejects_malformed_population_query() -> None:
    with pytest.raises((TypeError, ValueError)):
        select(population_source_query="")
    with pytest.raises((TypeError, ValueError)):
        select(population_source_query=123)
    with pytest.raises((TypeError, ValueError)):
        select(population_source_query="query\nwith-control")


def test_serialization_round_trip_with_query() -> None:
    selection = select(population_source_query=QUERY)
    restored = deserialize_executable_lane_selection(
        serialize_executable_lane_selection(selection)
    )
    assert restored.population_source_query == QUERY
    assert restored.selection_id == selection.selection_id


def test_legacy_payload_without_query_still_deserializes() -> None:
    """Payloads written before B5 had no population_source_query key."""
    selection = select()
    payload = json.loads(serialize_executable_lane_selection(selection))
    assert "population_source_query" not in payload
    restored = deserialize_executable_lane_selection(json.dumps(payload))
    assert restored.population_source_query is None
    assert restored.selection_id == selection.selection_id


def test_deserialize_rejects_unknown_extra_field() -> None:
    payload = json.loads(serialize_executable_lane_selection(select()))
    payload["population_source_query"] = QUERY
    payload["unexpected_field"] = "nope"
    with pytest.raises(ValueError, match="unknown fields"):
        deserialize_executable_lane_selection(json.dumps(payload))
