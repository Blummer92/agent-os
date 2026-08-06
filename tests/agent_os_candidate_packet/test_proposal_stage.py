"""AOS-AUTO1C repository-evidence and WSC3 proposal coordinator tests (#752)."""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

from workflow_scheduler.planning.draft_ingestion import DraftTaskProposal

from scripts.agent_os_candidate_packet import proposal_stage
from scripts.agent_os_candidate_packet.planning_stage import (
    PlanningHandoffStageStatus,
    prepare_planning_handoff,
)
from scripts.agent_os_candidate_packet.proposal_stage import (
    WSC3_STATUS_UNMAPPED,
    RepositoryProposalStageResult,
    RepositoryProposalStageStatus,
    draft_task_proposal_from_dict,
    draft_task_proposal_to_dict,
    prepare_repository_and_proposal,
)
from scripts.agent_os_candidate_packet.readiness_stage import prepare_issue_readiness
from scripts.agent_os_candidate_packet.repository_stage import (
    RepositoryObservation,
    RepositoryStageStatus,
)
from scripts.agent_os_candidate_packet.stage_models import (
    DependencyEvidence,
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
    EvidenceStatus,
)
from scripts.agent_os_execution_capabilities import (
    RepositoryEvidenceType,
    RepositoryIdentity,
    WorktreeState,
)
from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    compute_issueplan_current_state_fingerprint,
)
from tests.agent_os_candidate_packet.test_readiness_stage import (
    _FakeIssueReader,
    _FakeRepositoryReader,
    _request,
)

_SHA = "b89de18da472a3cd79877c4f7ee13b49bd7014eb"
_BASE_SHA = "b" * 40
_OTHER_SHA = "c" * 40
_CONTRACT = "3" * 64
_OTHER_CONTRACT = "4" * 64
_PLANNED_AT = "2026-08-03T18:00:00Z"
_CREATED_AT = "2026-08-06T04:00:00Z"


def _no_dependencies() -> DependencyIdentityEvidence:
    return DependencyIdentityEvidence(
        status=DependencyIdentityStatus.ABSENT,
        provenance=("fixture:no-dependencies",),
    )


def _readiness(*, dependency=None, dependency_identity=None):
    result = prepare_issue_readiness(
        _request(governed_field_names=("owner_agent", "source_of_truth")),
        _FakeIssueReader(),
        _FakeRepositoryReader(dependency=dependency),
        dependency_identity_evidence=dependency_identity,
    )
    return replace(
        result,
        issueplan_current_state_evidence=replace(
            result.issueplan_current_state_evidence,
            base_branch="main",
            evaluated_repository_sha=_SHA,
        ),
    )


def _rebind(evidence, handoff, **overrides):
    """Bind IssuePlan evidence to a handoff and recompute its canonical identity."""
    values = dict(
        repository=handoff.repository,
        base_branch=handoff.base_branch,
        evaluated_repository_sha=handoff.evaluated_repository_sha,
        implementation_contract_fingerprint=_CONTRACT,
        graph_reference=handoff.graph_digest,
        planning_result_reference=handoff.planning_result_digest,
        handoff_reference=handoff.handoff_digest,
        supplied_node_ids=handoff.supplied_node_ids,
    )
    values.update(overrides)
    rebound = replace(evidence, **values)
    return replace(
        rebound,
        evidence_id=(
            "issueplan-current-state:"
            + compute_issueplan_current_state_fingerprint(rebound)
        ),
    )


def _planning(*, dependency=None, dependency_identity=None, evidence_overrides=None):
    """A planning result whose IssuePlan evidence matches its own handoff."""
    result = prepare_planning_handoff(
        _readiness(
            dependency=dependency,
            dependency_identity=(
                _no_dependencies() if dependency_identity is None else dependency_identity
            ),
        ),
        evaluator_sha=_SHA,
        created_at=_PLANNED_AT,
    )
    return replace(
        result,
        issueplan_current_state_evidence=_rebind(
            result.issueplan_current_state_evidence,
            result.handoff,
            **(evidence_overrides or {}),
        ),
    )


def _identity(**overrides) -> RepositoryIdentity:
    values = dict(host="github.com", owner="blummer92", repository="agent-os")
    values.update(overrides)
    return RepositoryIdentity(**values)


def _observation(**overrides) -> RepositoryObservation:
    values = dict(
        producer_adapter="fixture-read-only-adapter",
        producer_adapter_version="1.0",
        correlation_id="issue-752",
        repository_identity=_identity(),
        base_ref="main",
        base_sha=_BASE_SHA,
        head_ref="agent/752-repository-proposal-coordinator",
        head_sha=_SHA,
        requested_ref="agent/752-repository-proposal-coordinator",
        requested_sha=_SHA,
        observed_sha=_SHA,
        tested_sha=_SHA,
        pushed_sha=None,
        proposed_pr_sha=None,
        synthetic_merge_sha=None,
        external_build_sha=None,
        evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        contract_fingerprint=_CONTRACT,
        worktree_state=WorktreeState.CLEAN,
        observed_at="2026-08-06T03:50:00Z",
        freshness_boundary="main@41ebab11",
    )
    values.update(overrides)
    return RepositoryObservation(**values)


def _prepare(planning=None, observation=None, created_at=_CREATED_AT):
    return prepare_repository_and_proposal(
        planning if planning is not None else _planning(),
        observation if observation is not None else _observation(),
        created_at=created_at,
    )


# --------------------------------------------------------------------------
# Eligible outcome.
# --------------------------------------------------------------------------


def test_verified_planning_and_observation_produce_both_canonical_objects() -> None:
    planning = _planning()

    result = _prepare(planning)

    assert result.status is RepositoryProposalStageStatus.ELIGIBLE
    assert result.repository_stage.status is RepositoryStageStatus.VALID
    assert result.repository_state_evidence is result.repository_stage.evidence
    assert result.proposal_result.status == "eligible"
    assert result.proposal is result.proposal_result.proposals[0]
    assert result.proposal.repository == planning.handoff.repository
    assert result.proposal.base_branch == planning.handoff.base_branch
    assert result.proposal.evaluated_repository_sha == (
        planning.handoff.evaluated_repository_sha
    )
    assert result.proposal.evaluator_commit_sha == (
        planning.handoff.evaluator_commit_sha
    )
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_no_caller_has_to_copy_a_proposal_or_evidence_identity() -> None:
    planning = _planning()

    result = _prepare(planning)

    assert result.proposal.issueplan_current_state_evidence_id == (
        planning.issueplan_current_state_evidence.evidence_id
    )
    assert result.proposal.repository_state_evidence_id == (
        result.repository_state_evidence.evidence_id
    )
    assert result.proposal.handoff_digest == planning.handoff.handoff_digest
    assert result.proposal.graph_digest == planning.handoff.graph_digest
    assert result.proposal.planning_result_digest == (
        planning.handoff.planning_result_digest
    )


def test_the_exact_preserved_issueplan_object_reaches_wsc3(monkeypatch) -> None:
    planning = _planning()
    seen: dict[str, object] = {}
    original = proposal_stage.build_draft_task_proposals

    def _spy(handoff, issueplan, repository, *, created_at):
        seen["handoff"] = handoff
        seen["issueplan"] = issueplan
        seen["repository"] = repository
        seen["created_at"] = created_at
        return original(handoff, issueplan, repository, created_at=created_at)

    monkeypatch.setattr(proposal_stage, "build_draft_task_proposals", _spy)

    result = _prepare(planning)

    assert result.status is RepositoryProposalStageStatus.ELIGIBLE
    # Identity, not equality: no reconstruction from an ID, digest, node
    # provenance, handoff bytes, or any other partial representation.
    assert seen["issueplan"] is planning.issueplan_current_state_evidence
    assert seen["handoff"] is planning.handoff
    assert seen["repository"] is result.repository_state_evidence
    assert seen["created_at"] == _CREATED_AT


def test_proposal_identity_is_deterministic_and_excludes_created_at() -> None:
    first = _prepare()
    second = _prepare()
    later = _prepare(created_at="2026-08-06T23:59:59Z")

    assert first.proposal.proposal_id == second.proposal.proposal_id
    assert later.proposal.proposal_id == first.proposal.proposal_id
    assert later.proposal.created_at == "2026-08-06T23:59:59Z"
    assert first.repository_state_evidence.evidence_id == (
        second.repository_state_evidence.evidence_id
    )


# --------------------------------------------------------------------------
# Planning-stage gates.
# --------------------------------------------------------------------------


def test_invalid_planning_input_is_never_repaired() -> None:
    readiness = prepare_issue_readiness(
        _request(governed_field_names=("owner_agent", "source_of_truth")),
        _FakeIssueReader(),
        _FakeRepositoryReader(),
    )
    planning = prepare_planning_handoff(
        readiness, evaluator_sha=_SHA, created_at=_PLANNED_AT
    )

    result = _prepare(planning)

    assert planning.status is PlanningHandoffStageStatus.INVALID_INPUT
    assert result.status is RepositoryProposalStageStatus.INVALID_INPUT
    assert "planning-stage-invalid-input" in result.reason_codes
    assert "missing-base-branch" in result.reason_codes
    assert result.repository_stage is None
    assert result.repository_state_evidence is None
    assert result.proposal_result is None
    assert result.proposal is None


def test_a_planning_result_without_issueplan_evidence_fails_closed() -> None:
    """The coordinator re-checks completeness rather than trusting its input.

    ``PlanningHandoffStageResult`` already forbids this shape, so the field is
    forced past that invariant to prove the coordinator's own gate holds and
    never falls back to rebuilding the evidence.
    """
    planning = _planning()
    object.__setattr__(planning, "issueplan_current_state_evidence", None)

    result = _prepare(planning)

    assert result.status is RepositoryProposalStageStatus.INVALID_INPUT
    assert "planning-stage-partial" in result.reason_codes
    assert result.repository_stage is None
    assert result.proposal_result is None


def test_a_non_suppliable_planning_result_never_reaches_wsc3() -> None:
    planning = replace(_planning(), wsc3_suppliable=False)

    result = _prepare(planning)

    assert result.status is RepositoryProposalStageStatus.INVALID_INPUT
    assert "planning-stage-not-suppliable" in result.reason_codes
    assert result.proposal_result is None


def test_blocked_planning_outcomes_are_preserved_without_calling_wsc3() -> None:
    planning = _planning(
        dependency=DependencyEvidence(
            EvidenceStatus.RESOLVED_BLOCKED,
            reason_codes=("dependency.explicitly-blocked",),
        )
    )

    result = _prepare(planning)

    assert planning.status is PlanningHandoffStageStatus.BLOCKED
    assert result.status is RepositoryProposalStageStatus.BLOCKED
    assert result.proposal_result is None
    assert result.proposal is None
    # The repository evidence is still produced and surfaced.
    assert result.repository_stage.status is RepositoryStageStatus.VALID
    assert result.repository_state_evidence is not None


def test_needs_decision_planning_outcomes_are_preserved() -> None:
    planning = _planning(
        dependency_identity=DependencyIdentityEvidence(
            status=DependencyIdentityStatus.UNRESOLVED,
            reason_codes=("dependency-identity.unresolved",),
        )
    )

    result = _prepare(planning)

    assert planning.status is PlanningHandoffStageStatus.NEEDS_DECISION
    assert result.status is RepositoryProposalStageStatus.NEEDS_DECISION
    assert result.proposal_result is None
    assert result.proposal is None
    assert result.repository_state_evidence is not None
    assert "dependency-identity-incomplete" in result.reason_codes


# --------------------------------------------------------------------------
# Repository gates.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            {"worktree_state": WorktreeState.DIRTY},
            RepositoryProposalStageStatus.BLOCKED,
        ),
        (
            {"worktree_state": WorktreeState.INDETERMINATE},
            RepositoryProposalStageStatus.NEEDS_DECISION,
        ),
        ({"tested_sha": None}, RepositoryProposalStageStatus.STALE),
        ({"head_sha": "not-a-sha"}, RepositoryProposalStageStatus.INVALID),
    ],
)
def test_unverified_repository_evidence_never_reaches_wsc3(change, expected) -> None:
    result = _prepare(observation=_observation(**change))

    assert result.status is expected
    assert result.proposal_result is None
    assert result.proposal is None


def test_head_sha_drift_from_the_handoff_is_reported() -> None:
    result = _prepare(
        observation=_observation(
            head_sha=_OTHER_SHA,
            requested_sha=_OTHER_SHA,
            observed_sha=_OTHER_SHA,
            tested_sha=_OTHER_SHA,
        )
    )

    assert result.status is RepositoryProposalStageStatus.STALE
    assert "ref.branch-moved" in result.reason_codes
    assert result.proposal_result is None


def test_base_branch_drift_from_the_handoff_is_reported() -> None:
    result = _prepare(observation=_observation(base_ref="release"))

    assert result.status is RepositoryProposalStageStatus.STALE
    assert "ref.base-mismatch" in result.reason_codes


def test_contract_fingerprint_mismatch_is_reported() -> None:
    result = _prepare(observation=_observation(contract_fingerprint=_OTHER_CONTRACT))

    assert result.status is RepositoryProposalStageStatus.STALE
    assert "ref.contract-mismatch" in result.reason_codes
    assert result.proposal_result is None


def test_repository_identity_mismatch_against_the_handoff_is_reported() -> None:
    result = _prepare(
        observation=_observation(repository_identity=_identity(owner="someone-else"))
    )

    assert result.status is RepositoryProposalStageStatus.STALE
    assert "repo.identity-mismatch" in result.reason_codes
    assert result.proposal_result is None
    # The evidence itself is still valid in isolation -- only the binding failed.
    assert result.repository_stage.status is RepositoryStageStatus.VALID


def test_repository_identity_is_compared_case_insensitively() -> None:
    result = _prepare(
        observation=_observation(
            repository_identity=_identity(owner="BlUmMeR92", repository="Agent-OS")
        )
    )

    assert result.status is RepositoryProposalStageStatus.ELIGIBLE


# --------------------------------------------------------------------------
# WSC3 non-eligible outcomes are mapped, not re-derived.
# --------------------------------------------------------------------------


def test_handoff_binding_drift_reaches_wsc3_and_returns_stale() -> None:
    planning = _planning()
    drifted = replace(
        planning,
        issueplan_current_state_evidence=_rebind(
            planning.issueplan_current_state_evidence,
            planning.handoff,
            graph_reference="9" * 64,
        ),
    )

    result = _prepare(drifted)

    assert result.status is RepositoryProposalStageStatus.STALE
    assert result.proposal_result is not None
    assert result.proposal_result.status == "stale"
    assert "planning-state-mismatch" in result.reason_codes
    assert result.proposal is None


def test_a_missing_contract_fingerprint_is_never_assumed() -> None:
    planning = _planning(
        evidence_overrides={"implementation_contract_fingerprint": None}
    )

    result = _prepare(planning)

    assert result.status is RepositoryProposalStageStatus.STALE
    assert result.proposal_result.status == "stale"
    assert result.proposal is None


def test_issueplan_evidence_with_a_broken_identity_returns_invalid() -> None:
    planning = _planning()
    tampered = replace(
        planning.issueplan_current_state_evidence,
        evidence_id="issueplan-current-state:" + "0" * 64,
    )

    result = _prepare(replace(planning, issueplan_current_state_evidence=tampered))

    assert result.status is RepositoryProposalStageStatus.INVALID
    assert result.proposal_result.status == "invalid"
    assert result.proposal is None


def test_an_unmappable_wsc3_status_fails_closed(monkeypatch) -> None:
    """A status added by WSC3 must not escape as a KeyError.

    WSC3 constrains its own vocabulary, so the result is forced past that
    invariant to prove this coordinator still returns one deterministic result.
    """
    real = proposal_stage.build_draft_task_proposals
    planning = _planning()

    def _unmapped(handoff, issueplan, repository, *, created_at):
        result = real(handoff, issueplan, repository, created_at=created_at)
        object.__setattr__(result, "status", "some-future-status")
        object.__setattr__(result, "proposals", ())
        return result

    monkeypatch.setattr(proposal_stage, "build_draft_task_proposals", _unmapped)

    result = _prepare(planning)

    assert result.status is RepositoryProposalStageStatus.INVALID
    assert WSC3_STATUS_UNMAPPED in result.reason_codes
    assert result.proposal is None
    assert result.repository_state_evidence is not None
    assert result.execution_authorized is False


def test_wsc3_reason_codes_are_carried_through_unchanged() -> None:
    result = _prepare()

    assert "approval-not-evaluated" in result.reason_codes
    assert set(result.proposal_result.reason_codes) <= set(result.reason_codes)


# --------------------------------------------------------------------------
# Proposal round trip.
# --------------------------------------------------------------------------


def test_proposal_round_trips_without_drift() -> None:
    original = _prepare().proposal

    payload = draft_task_proposal_to_dict(original)
    rebuilt = draft_task_proposal_from_dict(
        json.loads(json.dumps(payload, sort_keys=True))
    )

    assert rebuilt == original
    assert rebuilt.proposal_id == original.proposal_id
    assert draft_task_proposal_to_dict(rebuilt) == payload
    assert rebuilt.execution_authorized is False
    assert rebuilt.authorization_status == "not-evaluated"


def test_proposal_serializer_shape_cannot_drift_from_the_dataclass() -> None:
    """`to_dict` emits exactly the fields `from_dict` requires."""
    payload = draft_task_proposal_to_dict(_prepare().proposal)

    assert set(payload) == {
        item.name for item in dataclasses.fields(DraftTaskProposal)
    }


def test_proposal_round_trip_rejects_malformed_cohort_summaries() -> None:
    payload = draft_task_proposal_to_dict(_prepare().proposal)

    with pytest.raises(ValueError, match="cohort summary must be a mapping"):
        draft_task_proposal_from_dict({**payload, "cohort_summaries": ["nope"]})

    incomplete = [dict(payload["cohort_summaries"][0])]
    incomplete[0].pop("classification")
    with pytest.raises(ValueError, match="cohort summary is missing field"):
        draft_task_proposal_from_dict({**payload, "cohort_summaries": incomplete})

    with pytest.raises(ValueError, match="cohort_summaries must be a list"):
        draft_task_proposal_from_dict({**payload, "cohort_summaries": {}})


def test_proposal_round_trip_rejects_a_tampered_identity() -> None:
    payload = draft_task_proposal_to_dict(_prepare().proposal)
    payload["evaluated_repository_sha"] = _OTHER_SHA

    with pytest.raises(ValueError, match="proposal_id does not match"):
        draft_task_proposal_from_dict(payload)


def test_proposal_round_trip_rejects_authority_escalation() -> None:
    payload = draft_task_proposal_to_dict(_prepare().proposal)

    with pytest.raises(ValueError, match="execution_authorized"):
        draft_task_proposal_from_dict({**payload, "execution_authorized": True})
    with pytest.raises(ValueError, match="authorization_status"):
        draft_task_proposal_from_dict({**payload, "authorization_status": "approved"})
    with pytest.raises(ValueError, match="always eligible"):
        draft_task_proposal_from_dict({**payload, "eligibility_status": "blocked"})


def test_proposal_round_trip_rejects_unknown_and_missing_fields() -> None:
    payload = draft_task_proposal_to_dict(_prepare().proposal)

    with pytest.raises(ValueError, match="unsupported field"):
        draft_task_proposal_from_dict({**payload, "surprise": 1})

    incomplete = dict(payload)
    incomplete.pop("proposal_id")
    with pytest.raises(ValueError, match="missing field"):
        draft_task_proposal_from_dict(incomplete)

    with pytest.raises(ValueError, match="must be a mapping"):
        draft_task_proposal_from_dict([])


def test_proposal_serializer_rejects_a_foreign_object() -> None:
    with pytest.raises(TypeError, match="DraftTaskProposal"):
        draft_task_proposal_to_dict(_observation())


# --------------------------------------------------------------------------
# Input contract, result invariants, and authority.
# --------------------------------------------------------------------------


def test_coordinator_rejects_foreign_inputs() -> None:
    with pytest.raises(TypeError, match="PlanningHandoffStageResult"):
        prepare_repository_and_proposal(
            {"status": "ready"}, _observation(), created_at=_CREATED_AT
        )
    with pytest.raises(TypeError, match="RepositoryObservation"):
        prepare_repository_and_proposal(
            _planning(), {"head_sha": _SHA}, created_at=_CREATED_AT
        )


def test_created_at_must_be_an_explicit_utc_timestamp() -> None:
    with pytest.raises(ValueError, match="created_at"):
        _prepare(created_at="2026-08-06")


def test_result_invariants_cannot_be_bypassed() -> None:
    eligible = _prepare()

    with pytest.raises(ValueError, match="own proposal object"):
        replace(eligible, proposal=None)
    with pytest.raises(ValueError, match="eligible WSC3 result"):
        RepositoryProposalStageResult(
            status=RepositoryProposalStageStatus.ELIGIBLE,
            repository_stage=eligible.repository_stage,
            repository_state_evidence=eligible.repository_state_evidence,
            proposal_result=None,
            proposal=None,
        )
    with pytest.raises(ValueError, match="cannot carry a proposal"):
        replace(eligible, status=RepositoryProposalStageStatus.STALE)
    with pytest.raises(ValueError, match="repository stage's own evidence"):
        replace(eligible, repository_state_evidence=None)
    with pytest.raises(ValueError, match="without its repository stage"):
        RepositoryProposalStageResult(
            status=RepositoryProposalStageStatus.STALE,
            repository_stage=None,
            repository_state_evidence=eligible.repository_state_evidence,
            proposal_result=None,
            proposal=None,
        )


def test_every_outcome_keeps_authority_false() -> None:
    outcomes = [
        _prepare(),
        _prepare(observation=_observation(worktree_state=WorktreeState.DIRTY)),
        _prepare(observation=_observation(head_sha="not-a-sha")),
        _prepare(
            _planning(
                dependency=DependencyEvidence(
                    EvidenceStatus.RESOLVED_BLOCKED,
                    reason_codes=("dependency.explicitly-blocked",),
                )
            )
        ),
    ]

    for result in outcomes:
        assert result.execution_authorized is False
        assert result.side_effects_performed is False
        if result.proposal_result is not None:
            assert result.proposal_result.execution_authorized is False
            assert result.proposal_result.side_effects_performed is False
            assert result.proposal_result.authorization_status == "not-evaluated"
        if result.proposal is not None:
            assert result.proposal.execution_authorized is False
        with pytest.raises(ValueError, match="init=False"):
            replace(result, execution_authorized=True)


_PROHIBITED_MODULES = frozenset(
    {
        "os",
        "io",
        "pathlib",
        "shutil",
        "socket",
        "ssl",
        "subprocess",
        "tempfile",
        "urllib",
        "urllib.request",
        "http",
        "http.client",
        "requests",
        "git",
        "github",
    }
)

_PROHIBITED_CALLS = frozenset(
    {
        "open",
        "system",
        "run",
        "Popen",
        "call",
        "check_output",
        "check_call",
        "connect",
        "send",
        "sendall",
        "urlopen",
        "request",
        "write",
        "writelines",
        "write_text",
        "write_bytes",
        "mkdir",
        "makedirs",
        "unlink",
        "remove",
        "rmtree",
        "rename",
        "chmod",
    }
)


def test_coordinator_reaches_no_io_execution_or_persistence_surface() -> None:
    """Static proof of the read-only, no-side-effect boundary.

    Scope is this module only: it does not follow imports, so it proves this
    file reaches no I/O surface directly, not that its whole dependency tree is
    I/O-free. The package-level boundary is covered separately by
    `tests/test_workflow_scheduler_packaging.py`.
    """
    source = Path(inspect.getfile(proposal_stage)).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            imported.add(node.module or "")
        elif isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Attribute):
                called.add(function.attr)
            elif isinstance(function, ast.Name):
                called.add(function.id)

    assert imported & _PROHIBITED_MODULES == set()
    assert called & _PROHIBITED_CALLS == set()
    # The Scheduler is only ever asked to build a proposal -- never to execute.
    assert "workflow_scheduler.planning.draft_ingestion" in imported
    assert not any(
        module.startswith("workflow_scheduler")
        and module != "workflow_scheduler.planning.draft_ingestion"
        for module in imported
    )
