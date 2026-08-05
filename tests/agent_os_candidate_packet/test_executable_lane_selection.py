"""AOS-QUEUE2 (#864): pure executable lane selection and replacement.

Covers queue classification, deterministic rank/tie-break, lane replacement
boundaries, duplicate-claim routing, canonical serialization, and the
no-authority / no-side-effect guarantees.
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
    PrimaryIssueClaim,
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
    EXECUTABLE_LANE_SELECTION_SCHEMA_NAME,
    EXECUTABLE_LANE_SELECTION_SCHEMA_VERSION,
    CandidateIssueEvidence,
    DuplicateClaimFinding,
    ExecutableLaneSelection,
    Queue,
    QueueClassification,
    RankEvidence,
    ReplacementRecord,
    deserialize_executable_lane_selection,
    select_executable_lanes,
    serialize_executable_lane_selection,
)

SOURCE_SHA = "a" * 40
APPROVAL_ID = "approval:" + "1" * 64
ENV_EVIDENCE_ID = "environment-capability:" + "2" * 64


def authority(state: AuthorizationState, evidence_id: str | None = None) -> AuthorityProjection:
    if evidence_id is None and state in {
        AuthorizationState.AUTHORIZED,
        AuthorizationState.STALE,
        AuthorizationState.NEEDS_DECISION,
    }:
        evidence_id = APPROVAL_ID
    return AuthorityProjection(state=state, evidence_id=evidence_id)


def evidence(issue_number: int = 901, **changes: object) -> IssueOperationalEvidence:
    data: dict[str, object] = {
        "repository": "Blummer92/agent-os",
        "issue_number": issue_number,
        "source_revision": SOURCE_SHA,
        "observed_at": "2026-08-04T12:00:00Z",
        "evidence_ids": (APPROVAL_ID,),
        "source_state": SourceState.COMPLETE,
        "issue_state": IssueState.OPEN,
        "lifecycle_stage": LifecycleStage.PLANNING,
        "terminal_disposition": TerminalDisposition.NONE,
        "readiness": ReadinessState.READY,
        "implementation_authorization": authority(AuthorizationState.AUTHORIZED),
        "ready_for_review_authorization": authority(AuthorizationState.AUTHORIZED),
        "execution_authorization": authority(AuthorizationState.NOT_AUTHORIZED),
        "merge_authorization": authority(AuthorizationState.AUTHORIZED),
        "closure_authorization": authority(AuthorizationState.AUTHORIZED),
        "external_write_authorization": authority(AuthorizationState.NOT_AUTHORIZED),
        "dependency_state": DependencyState.CLEAR,
        "primary_claims": (),
        "validation_state": ValidationState.NOT_RUN,
        "freshness_state": FreshnessState.CURRENT,
        "observed_labels": (),
    }
    data.update(changes)
    return IssueOperationalEvidence(**data)


def op_state(issue_number: int = 901, **changes: object):
    return build_issue_operational_state(evidence(issue_number, **changes))


def environment(**changes: object) -> EnvironmentCapabilityEvidence:
    data: dict[str, object] = {
        "local_execution_state": EnvironmentCapabilityState.VERIFIED,
        "push_state": EnvironmentCapabilityState.VERIFIED,
        "evidence_id": ENV_EVIDENCE_ID,
        "bound_source_revision": None,
        "observed_source_revision": None,
    }
    data.update(changes)
    return EnvironmentCapabilityEvidence(**data)


def mode_decision(state, requested_mode: str = "build", **env_changes: object):
    return evaluate_operating_mode_decision(state, requested_mode, environment(**env_changes))


def candidate(
    issue_number: int = 901,
    *,
    dependency_depth: int = 0,
    substitutable: bool = True,
    requested_mode: str = "build",
    state_changes: dict[str, object] | None = None,
    env_changes: dict[str, object] | None = None,
) -> CandidateIssueEvidence:
    state = op_state(issue_number, **(state_changes or {}))
    decision = mode_decision(state, requested_mode, **(env_changes or {}))
    return CandidateIssueEvidence(
        issue_number=issue_number,
        operational_state=state,
        mode_decision=decision,
        dependency_depth=dependency_depth,
        substitutable=substitutable,
    )


def primary_claim(pr_number: int, state: str = "ready") -> PrimaryIssueClaim:
    return PrimaryIssueClaim(
        pull_request_number=pr_number,
        branch=f"agent/{pr_number}-work",
        head_sha="d" * 40,
        state=state,
    )


def select(
    *,
    campaign_id: str = "campaign-864",
    requested_lane_count: int = 3,
    substitution_allowed: bool = True,
    explicit_request_order: tuple[int, ...] = (),
    candidates: tuple[CandidateIssueEvidence, ...],
) -> ExecutableLaneSelection:
    return select_executable_lanes(
        campaign_id=campaign_id,
        requested_lane_count=requested_lane_count,
        substitution_allowed=substitution_allowed,
        explicit_request_order=explicit_request_order,
        candidates=candidates,
    )


# ---------------------------------------------------------------------------
# Queue classification
# ---------------------------------------------------------------------------


def test_ready_for_implementation():
    c = candidate(901)
    result = select(candidates=(c,))
    assert result.queue_classifications[0].queue is Queue.READY_FOR_IMPLEMENTATION
    assert result.selected_lanes == (901,)


def test_ready_for_review_when_review_permitted():
    c = candidate(
        901,
        requested_mode="review",
        state_changes={
            "primary_claims": (primary_claim(55, "ready"),),
            "ready_for_review_authorization": authority(AuthorizationState.AUTHORIZED),
        },
    )
    result = select(candidates=(c,))
    assert result.queue_classifications[0].queue is Queue.READY_FOR_REVIEW


def test_single_claim_without_review_permission_waits_for_authorization():
    c = candidate(
        901,
        requested_mode="build",
        state_changes={"primary_claims": (primary_claim(55, "ready"),)},
    )
    result = select(candidates=(c,))
    assert result.queue_classifications[0].queue is Queue.WAITING_FOR_AUTHORIZATION


def test_duplicate_primary_claims_route_to_reconciliation():
    c = candidate(
        901,
        state_changes={
            "primary_claims": (primary_claim(55, "ready"), primary_claim(56, "draft")),
        },
    )
    result = select(candidates=(c,))
    assert result.queue_classifications[0].queue is Queue.NEEDS_RECONCILIATION
    assert result.duplicate_claim_findings == (
        DuplicateClaimFinding(
            issue_number=901, claim_count=2, reason_code="duplicate-claim.multiple-primary"
        ),
    )
    assert "duplicate-claim.multiple-primary" in result.reason_codes
    assert 901 not in result.selected_lanes


def test_waiting_for_dependency():
    c = candidate(901, state_changes={"dependency_state": DependencyState.BLOCKED})
    result = select(candidates=(c,))
    assert result.queue_classifications[0].queue is Queue.WAITING_FOR_DEPENDENCY


def test_waiting_for_authorization():
    c = candidate(
        901,
        state_changes={"implementation_authorization": authority(AuthorizationState.NOT_AUTHORIZED)},
    )
    result = select(candidates=(c,))
    assert result.queue_classifications[0].queue is Queue.WAITING_FOR_AUTHORIZATION


def test_merged_needs_closure():
    c = candidate(
        901,
        state_changes={
            "lifecycle_stage": LifecycleStage.MERGED,
            "primary_claims": (primary_claim(55, "merged"),),
        },
    )
    result = select(candidates=(c,))
    assert result.queue_classifications[0].queue is Queue.MERGED_NEEDS_CLOSURE


def test_planning_only():
    c = candidate(901, requested_mode="planning")
    result = select(candidates=(c,))
    assert result.queue_classifications[0].queue is Queue.PLANNING_ONLY


def test_terminal():
    c = candidate(
        901,
        state_changes={
            "issue_state": IssueState.CLOSED,
            "lifecycle_stage": LifecycleStage.CLOSED,
            "terminal_disposition": TerminalDisposition.COMPLETED,
        },
    )
    result = select(candidates=(c,))
    assert result.queue_classifications[0].queue is Queue.TERMINAL
    assert 901 not in result.selected_lanes


def test_invalid():
    c = candidate(901, state_changes={"source_state": SourceState.UNSUPPORTED})
    result = select(candidates=(c,))
    assert result.queue_classifications[0].queue is Queue.INVALID
    assert 901 not in result.selected_lanes


@pytest.mark.parametrize(
    "state_changes",
    [
        {"source_state": SourceState.PARTIAL},
        {"source_state": SourceState.MISSING},
    ],
)
def test_missing_or_partial_evidence_waits_for_authorization(state_changes):
    c = candidate(901, state_changes=state_changes)
    result = select(candidates=(c,))
    assert result.queue_classifications[0].queue is Queue.WAITING_FOR_AUTHORIZATION


def test_conflicting_evidence_waits_for_authorization():
    c = candidate(901, state_changes={"source_state": SourceState.CONFLICTING})
    result = select(candidates=(c,))
    assert result.queue_classifications[0].queue is Queue.WAITING_FOR_AUTHORIZATION


def test_stale_evidence_waits_for_authorization():
    c = candidate(
        901,
        state_changes={"freshness_state": FreshnessState.STALE},
    )
    result = select(candidates=(c,))
    assert result.queue_classifications[0].queue is Queue.WAITING_FOR_AUTHORIZATION


def test_every_supplied_issue_classified_exactly_once():
    candidates = (candidate(901), candidate(902, requested_mode="planning"), candidate(903))
    result = select(candidates=candidates)
    assert {qc.issue_number for qc in result.queue_classifications} == {901, 902, 903}
    assert len(result.queue_classifications) == 3


# ---------------------------------------------------------------------------
# Lane selection, counts, and ordering
# ---------------------------------------------------------------------------


def test_three_executable_issues_fill_three_lanes():
    candidates = tuple(candidate(n) for n in (901, 902, 903))
    result = select(candidates=candidates, requested_lane_count=3)
    assert result.selected_lanes == (901, 902, 903)
    assert result.deferred_candidates == ()


@pytest.mark.parametrize("lane_count", [1, 2, 3])
def test_requested_lane_counts(lane_count):
    candidates = tuple(candidate(n) for n in (901, 902, 903))
    result = select(candidates=candidates, requested_lane_count=lane_count)
    assert result.requested_lane_count == lane_count
    assert len(result.selected_lanes) == lane_count
    assert result.selected_lanes == (901, 902, 903)[:lane_count]


@pytest.mark.parametrize("lane_count", [0, 4, -1])
def test_invalid_lane_count_rejected(lane_count):
    with pytest.raises(ValueError):
        select(candidates=(candidate(901),), requested_lane_count=lane_count)


def test_explicit_request_order_wins_ties():
    candidates = tuple(candidate(n) for n in (901, 902))
    result = select(candidates=candidates, explicit_request_order=(902, 901), requested_lane_count=2)
    assert result.selected_lanes == (902, 901)
    assert [r.explicit_request_position for r in result.rank_evidence if r.issue_number == 902] == [0]
    assert [r.explicit_request_position for r in result.rank_evidence if r.issue_number == 901] == [1]


def test_dependency_depth_orders_non_requested_candidates():
    candidates = (
        candidate(901, dependency_depth=2),
        candidate(902, dependency_depth=0),
    )
    result = select(candidates=candidates, requested_lane_count=2)
    assert result.selected_lanes == (902, 901)


def test_issue_number_tie_breaks_equal_depth():
    candidates = (candidate(903), candidate(901), candidate(902))
    result = select(candidates=candidates, requested_lane_count=3)
    assert result.selected_lanes == (901, 902, 903)


def test_selected_lanes_never_exceed_requested_count():
    candidates = tuple(candidate(n) for n in range(901, 911))
    result = select(candidates=candidates, requested_lane_count=2)
    assert len(result.selected_lanes) == 2


# ---------------------------------------------------------------------------
# Replacement behavior
# ---------------------------------------------------------------------------


def test_blocked_preferred_issue_replaced_when_substitution_allowed():
    blocked = candidate(
        901,
        substitutable=True,
        state_changes={"implementation_authorization": authority(AuthorizationState.NOT_AUTHORIZED)},
    )
    other = candidate(902)
    result = select(
        candidates=(blocked, other),
        explicit_request_order=(901,),
        substitution_allowed=True,
        requested_lane_count=1,
    )
    assert result.selected_lanes == (902,)
    assert result.replacement_records == (
        ReplacementRecord(
            displaced_issue_number=901,
            replacement_issue_number=902,
            reason_code="replacement.blocked-preferred-substituted",
        ),
    )
    assert "replacement.blocked-preferred-substituted" in result.reason_codes


def test_blocked_exact_required_issue_not_replaced():
    blocked = candidate(
        901,
        substitutable=False,
        state_changes={"implementation_authorization": authority(AuthorizationState.NOT_AUTHORIZED)},
    )
    result = select(
        candidates=(blocked,),
        explicit_request_order=(901,),
        substitution_allowed=True,
        requested_lane_count=1,
    )
    assert result.selected_lanes == ()
    assert result.replacement_records == ()
    assert "replacement.blocked-exact-required-not-substituted" in result.reason_codes


def test_substitution_disallowed_globally_blocks_replacement():
    blocked = candidate(
        901,
        substitutable=True,
        state_changes={"implementation_authorization": authority(AuthorizationState.NOT_AUTHORIZED)},
    )
    other = candidate(902)
    result = select(
        candidates=(blocked, other),
        explicit_request_order=(901,),
        substitution_allowed=False,
        requested_lane_count=1,
    )
    assert result.replacement_records == ()
    assert 901 not in result.selected_lanes
    assert "replacement.blocked-substitution-disabled" in result.reason_codes
    assert "replacement.blocked-exact-required-not-substituted" not in result.reason_codes


def test_no_eligible_replacement_available():
    blocked = candidate(
        901,
        substitutable=True,
        state_changes={"implementation_authorization": authority(AuthorizationState.NOT_AUTHORIZED)},
    )
    result = select(
        candidates=(blocked,),
        explicit_request_order=(901,),
        substitution_allowed=True,
        requested_lane_count=1,
    )
    assert result.selected_lanes == ()
    assert result.replacement_records == ()
    assert "replacement.blocked-no-eligible-replacement" in result.reason_codes


# ---------------------------------------------------------------------------
# Input validation, tampering, and fail-closed behavior
# ---------------------------------------------------------------------------


def test_duplicate_issue_input_rejected():
    with pytest.raises(ValueError):
        select(candidates=(candidate(901), candidate(901)))


def test_explicit_request_order_duplicate_rejected():
    with pytest.raises(ValueError):
        select(candidates=(candidate(901),), explicit_request_order=(901, 901))


def test_explicit_request_order_unknown_issue_rejected():
    with pytest.raises(ValueError):
        select(candidates=(candidate(901),), explicit_request_order=(902,))


def test_tampered_issue_number_fails_closed():
    state = op_state(901)
    decision = mode_decision(state)
    with pytest.raises(ValueError):
        CandidateIssueEvidence(
            issue_number=902,
            operational_state=state,
            mode_decision=decision,
            dependency_depth=0,
        )


def test_tampered_mode_decision_binding_fails_closed():
    state_a = op_state(901)
    state_b = op_state(902)
    decision_for_a = mode_decision(state_a)
    with pytest.raises(ValueError):
        CandidateIssueEvidence(
            issue_number=902,
            operational_state=state_b,
            mode_decision=decision_for_a,
            dependency_depth=0,
        )


def test_non_candidate_input_fails_closed():
    with pytest.raises(TypeError):
        select(candidates=("not-a-candidate",))


def test_malformed_payload_fails_closed():
    with pytest.raises(ValueError):
        deserialize_executable_lane_selection("not json")


def test_unknown_field_fails_closed():
    result = select(candidates=(candidate(901),))
    payload = json.loads(serialize_executable_lane_selection(result))
    payload["unexpected"] = True
    with pytest.raises(ValueError):
        deserialize_executable_lane_selection(json.dumps(payload))


def test_unsupported_version_fails_closed():
    result = select(candidates=(candidate(901),))
    payload = json.loads(serialize_executable_lane_selection(result))
    payload["schema_version"] = "9.9"
    with pytest.raises(ValueError):
        deserialize_executable_lane_selection(json.dumps(payload))


def test_tampered_replacement_record_references_fail_closed():
    result = select(candidates=(candidate(901),))
    payload = json.loads(serialize_executable_lane_selection(result))
    payload["replacement_records"] = [
        {
            "displaced_issue_number": 999,
            "replacement_issue_number": 901,
            "reason_code": "replacement.blocked-preferred-substituted",
        }
    ]
    with pytest.raises(ValueError):
        deserialize_executable_lane_selection(json.dumps(payload))


def test_tampered_rank_evidence_duplicate_rank_fails_closed():
    result = select(candidates=(candidate(901), candidate(902)))
    payload = json.loads(serialize_executable_lane_selection(result))
    payload["rank_evidence"][1]["rank"] = payload["rank_evidence"][0]["rank"]
    with pytest.raises(ValueError):
        deserialize_executable_lane_selection(json.dumps(payload))


def test_tampered_semantic_identity_fails_closed():
    result = select(candidates=(candidate(901),))
    payload = json.loads(serialize_executable_lane_selection(result))
    payload["selection_id"] = "executable-lane-selection:" + "0" * 64
    with pytest.raises(ValueError):
        deserialize_executable_lane_selection(json.dumps(payload))


# ---------------------------------------------------------------------------
# Canonical serialization and round trip
# ---------------------------------------------------------------------------


def test_byte_stable_round_trip():
    candidates = (candidate(901), candidate(902, requested_mode="planning"))
    result = select(candidates=candidates, explicit_request_order=(902,))
    serialized_once = serialize_executable_lane_selection(result)
    restored = deserialize_executable_lane_selection(serialized_once)
    serialized_twice = serialize_executable_lane_selection(restored)
    assert serialized_once == serialized_twice
    assert restored.to_dict() == result.to_dict()


def test_exact_canonical_serialization_is_sorted_compact_json():
    result = select(candidates=(candidate(901),))
    serialized = serialize_executable_lane_selection(result)
    assert serialized == json.dumps(
        json.loads(serialized), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def test_schema_name_and_version():
    result = select(candidates=(candidate(901),))
    assert result.schema_name == EXECUTABLE_LANE_SELECTION_SCHEMA_NAME
    assert result.schema_version == EXECUTABLE_LANE_SELECTION_SCHEMA_VERSION


def test_selection_id_is_content_addressed():
    first = select(candidates=(candidate(901),))
    second = select(candidates=(candidate(901),))
    assert first.selection_id == second.selection_id
    assert first.selection_id.startswith("executable-lane-selection:")


# ---------------------------------------------------------------------------
# No authority, no side effects
# ---------------------------------------------------------------------------


def test_execution_and_side_effect_flags_always_false():
    result = select(candidates=(candidate(901), candidate(902, requested_mode="planning")))
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_queue_placement_never_broadens_authority():
    c = candidate(
        901,
        state_changes={"implementation_authorization": authority(AuthorizationState.NOT_AUTHORIZED)},
    )
    result = select(candidates=(c,))
    assert result.queue_classifications[0].queue is Queue.WAITING_FOR_AUTHORIZATION
    # The selection carries no authorization fields at all -- it only cites IDs.
    assert not hasattr(result, "implementation_authorization")


def test_no_network_filesystem_subprocess_or_external_path_reachable():
    import ast
    import inspect

    from scripts.agent_os_candidate_packet import executable_lane_selection as module

    tree = ast.parse(inspect.getsource(module))
    forbidden_modules = {
        "socket",
        "subprocess",
        "os",
        "requests",
        "urllib",
        "http",
        "shutil",
    }
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported & forbidden_modules == set()
