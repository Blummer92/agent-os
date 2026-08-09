"""Issue #917 natural-pipeline acceptance: readiness to eligible, untouched.

Every test here drives the *real* public API in its documented order:

    prepare_issue_readiness(...) -> prepare_planning_handoff(...)
        -> prepare_repository_and_proposal(...)

Nothing in this module uses ``dataclasses.replace`` on a pipeline artifact,
reconstructs IssuePlan evidence after planning, inserts a digest or a reference
by hand, or recomputes an evidence identity externally. The only inputs are the
explicit pre-planning context, the injected read-only fixtures already used by
the readiness tests, and one explicit repository observation.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from scripts.agent_os_candidate_packet.planning_stage import (
    PlanningHandoffStageStatus,
    prepare_planning_handoff,
)
from scripts.agent_os_candidate_packet.proposal_stage import (
    RepositoryProposalStageStatus,
    prepare_repository_and_proposal,
)
from scripts.agent_os_candidate_packet.readiness_stage import prepare_issue_readiness
from scripts.agent_os_candidate_packet.repository_stage import RepositoryObservation
from scripts.agent_os_candidate_packet.stage_models import (
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
    IssuePlanningContext,
    IssueReadinessStageStatus,
)
from scripts.agent_os_execution_capabilities import (
    RepositoryEvidenceType,
    RepositoryIdentity,
    WorktreeState,
)
from scripts.agent_os_issue_acceptance.planning_binding import (
    PlanningBindingEvidence,
    compute_planning_binding_fingerprint,
    reconstruct_planning_binding_evidence,
    serialize_planning_binding_evidence,
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
_EVALUATOR_SHA = "a" * 40
_BRANCH = "agent/750-candidate-packet"
_PLANNED_AT = "2026-08-03T18:00:00Z"
_PROPOSED_AT = "2026-08-06T04:00:00Z"


# --------------------------------------------------------------------------
# Inputs. Each is explicit, caller supplied, and probes nothing.
# --------------------------------------------------------------------------


def _context(**overrides) -> IssuePlanningContext:
    values = dict(
        repository="blummer92/agent-os",
        base_branch="main",
        evaluated_repository_sha=_SHA,
        implementation_contract_fingerprint=_CONTRACT,
        # Canonical declared-path syntax: no trailing separator, no globs.
        allowed_files=("scripts/agent_os_candidate_packet",),
        forbidden_paths=(".github/workflows",),
        required_tests=("tests/agent_os_candidate_packet",),
        provenance=("issue-917:acceptance-fixture",),
    )
    values.update(overrides)
    return IssuePlanningContext(**values)


def _identity(**overrides) -> RepositoryIdentity:
    values = dict(
        host="github.com",
        owner="blummer92",
        repository="agent-os",
        repository_id=917,
        is_fork=False,
        upstream_owner=None,
        upstream_repository=None,
        upstream_repository_id=None,
        default_branch="main",
    )
    values.update(overrides)
    return RepositoryIdentity(**values)


def _observation(**overrides) -> RepositoryObservation:
    values = dict(
        producer_adapter="fixture-read-only-adapter",
        producer_adapter_version="1.0",
        correlation_id="issue-917",
        repository_identity=_identity(),
        base_ref="main",
        base_sha=_BASE_SHA,
        head_ref=_BRANCH,
        head_sha=_SHA,
        requested_ref=_BRANCH,
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


def _dependencies() -> DependencyIdentityEvidence:
    return DependencyIdentityEvidence(
        status=DependencyIdentityStatus.ABSENT,
        provenance=("issue-917:no-dependencies",),
    )


def _run(
    *,
    planning_context=None,
    observation=None,
    planning_created_at=_PLANNED_AT,
    proposal_created_at=_PROPOSED_AT,
):
    """Drive the public pipeline exactly as Issue #917 specifies it."""

    readiness = prepare_issue_readiness(
        _request(),
        _FakeIssueReader(),
        _FakeRepositoryReader(),
        dependency_identity_evidence=_dependencies(),
        planning_context=planning_context if planning_context is not None else _context(),
    )
    planning = prepare_planning_handoff(
        readiness,
        evaluator_sha=_EVALUATOR_SHA,
        created_at=planning_created_at,
    )
    result = prepare_repository_and_proposal(
        planning,
        observation if observation is not None else _observation(),
        created_at=proposal_created_at,
    )
    return readiness, planning, result


# --------------------------------------------------------------------------
# The acceptance criterion: untouched pipeline reaches eligible.
# --------------------------------------------------------------------------


def test_untouched_public_pipeline_reaches_eligible() -> None:
    readiness, planning, result = _run()

    assert readiness.status is IssueReadinessStageStatus.READY
    assert planning.status is PlanningHandoffStageStatus.READY
    assert result.status is RepositoryProposalStageStatus.ELIGIBLE
    assert result.proposal is not None
    assert result.proposal_result is not None
    assert result.proposal_result.status == "eligible"


def test_pipeline_holds_authority_and_side_effect_flags_false() -> None:
    readiness, planning, result = _run()

    for artifact in (readiness, planning, result, planning.planning_binding):
        assert artifact.execution_authorized is False
        assert artifact.side_effects_performed is False
    assert readiness.issueplan_current_state_evidence.execution_authorized is False


@pytest.mark.parametrize(
    "artifact_name",
    ["execution_authorized", "side_effects_performed"],
)
def test_binding_authority_fields_are_not_constructible(artifact_name) -> None:
    _readiness, planning, _result = _run()
    binding = planning.planning_binding
    with pytest.raises(TypeError):
        PlanningBindingEvidence(
            **{
                **{
                    name: getattr(binding, name)
                    for name in (
                        "schema_version",
                        "binding_id",
                        "issueplan_current_state_evidence_id",
                        "repository",
                        "base_branch",
                        "evaluated_repository_sha",
                        "implementation_contract_fingerprint",
                        "handoff_contract_version",
                        "planning_result_version",
                        "graph_digest",
                        "planning_result_digest",
                        "handoff_digest",
                        "supplied_node_ids",
                        "created_at",
                    )
                },
                artifact_name: True,
            }
        )


# --------------------------------------------------------------------------
# Exact-object preservation. Identity, not equality.
# --------------------------------------------------------------------------


def test_issueplan_object_is_preserved_by_identity_through_the_pipeline() -> None:
    readiness, planning, _result = _run()

    evidence = readiness.issueplan_current_state_evidence
    assert evidence is not None
    # The same object, not an equal reconstruction.
    assert planning.issueplan_current_state_evidence is evidence


def test_no_post_planning_reconstruction_of_issueplan_evidence() -> None:
    readiness, planning, _result = _run()

    evidence = readiness.issueplan_current_state_evidence
    before = evidence.evidence_id
    # Planning produced downstream artifacts, yet the upstream object is
    # untouched: same identity, same evidence ID, still no self-references.
    assert planning.issueplan_current_state_evidence is evidence
    assert evidence.evidence_id == before
    assert evidence.graph_reference is None
    assert evidence.planning_result_reference is None
    assert evidence.handoff_reference is None


def test_readiness_projects_the_context_before_identity_is_fixed() -> None:
    readiness, _planning, _result = _run()
    evidence = readiness.issueplan_current_state_evidence
    context = _context()

    assert evidence.repository == context.repository
    assert evidence.base_branch == context.base_branch
    assert evidence.evaluated_repository_sha == context.evaluated_repository_sha
    assert (
        evidence.implementation_contract_fingerprint
        == context.implementation_contract_fingerprint
    )
    assert evidence.allowed_files == context.allowed_files
    assert evidence.forbidden_paths == context.forbidden_paths
    assert evidence.required_tests == context.required_tests


def test_context_repository_must_match_the_request() -> None:
    with pytest.raises(ValueError, match="planning_context.repository"):
        prepare_issue_readiness(
            _request(),
            _FakeIssueReader(),
            _FakeRepositoryReader(),
            dependency_identity_evidence=_dependencies(),
            planning_context=_context(repository="blummer92/other-repo"),
        )


# --------------------------------------------------------------------------
# Determinism, and the timestamps excluded from semantic identity.
# --------------------------------------------------------------------------


def test_repeated_semantic_inputs_produce_identical_identities() -> None:
    first_readiness, first_planning, first_result = _run()
    second_readiness, second_planning, second_result = _run()

    assert (
        first_readiness.issueplan_current_state_evidence.evidence_id
        == second_readiness.issueplan_current_state_evidence.evidence_id
    )
    assert first_planning.planning_binding == second_planning.planning_binding
    assert (
        first_planning.planning_binding.binding_id
        == second_planning.planning_binding.binding_id
    )
    assert first_planning.handoff.graph_digest == second_planning.handoff.graph_digest
    assert (
        first_planning.handoff.planning_result_digest
        == second_planning.handoff.planning_result_digest
    )
    assert (
        first_planning.handoff.handoff_digest == second_planning.handoff.handoff_digest
    )
    assert first_result.proposal.proposal_id == second_result.proposal.proposal_id


def test_proposal_created_at_is_excluded_from_proposal_identity() -> None:
    _r1, _planning, result = _run()
    _r2, _other_planning, other_result = _run(
        proposal_created_at="2026-09-10T10:10:10Z"
    )

    assert result.proposal.created_at != other_result.proposal.created_at
    assert result.proposal.proposal_id == other_result.proposal.proposal_id


def test_binding_created_at_is_excluded_from_binding_identity() -> None:
    """The binding's own provenance timestamp is outside its semantic identity.

    Varied directly on the binding, because the handoff digest legitimately
    covers the planning timestamp (a #751 contract this issue does not change);
    varying the pipeline's planning time would change the handoff, not isolate
    the binding's own rule.
    """

    _readiness, planning, _result = _run()
    binding = planning.planning_binding
    later = PlanningBindingEvidence(
        schema_version=binding.schema_version,
        binding_id=binding.binding_id,
        issueplan_current_state_evidence_id=(
            binding.issueplan_current_state_evidence_id
        ),
        repository=binding.repository,
        base_branch=binding.base_branch,
        evaluated_repository_sha=binding.evaluated_repository_sha,
        implementation_contract_fingerprint=(
            binding.implementation_contract_fingerprint
        ),
        handoff_contract_version=binding.handoff_contract_version,
        planning_result_version=binding.planning_result_version,
        graph_digest=binding.graph_digest,
        planning_result_digest=binding.planning_result_digest,
        handoff_digest=binding.handoff_digest,
        supplied_node_ids=binding.supplied_node_ids,
        created_at="2029-01-01T00:00:00Z",
    )

    assert later.created_at != binding.created_at
    assert compute_planning_binding_fingerprint(
        later
    ) == compute_planning_binding_fingerprint(binding)
    # The identity accepted the differing timestamp precisely because the
    # timestamp is not part of it.
    assert later.binding_id == binding.binding_id


# --------------------------------------------------------------------------
# The binding itself: canonical, frozen, closed schema, round-trippable.
# --------------------------------------------------------------------------


def test_binding_is_frozen_and_round_trips_exactly() -> None:
    _readiness, planning, _result = _run()
    binding = planning.planning_binding

    with pytest.raises(Exception):
        binding.graph_digest = _OTHER_CONTRACT

    payload = serialize_planning_binding_evidence(binding)
    restored = reconstruct_planning_binding_evidence(payload)
    assert restored == binding
    assert serialize_planning_binding_evidence(restored) == payload


def test_binding_rejects_unsupported_and_missing_payload_fields() -> None:
    _readiness, planning, _result = _run()
    payload = serialize_planning_binding_evidence(planning.planning_binding)
    import json

    raw = json.loads(payload.decode("utf-8"))

    with pytest.raises(ValueError, match="unsupported field"):
        reconstruct_planning_binding_evidence({**raw, "surprise": "value"})

    incomplete = dict(raw)
    incomplete.pop("graph_digest")
    with pytest.raises(ValueError, match="missing field"):
        reconstruct_planning_binding_evidence(incomplete)


def test_binding_carries_the_downstream_references_the_issueplan_does_not() -> None:
    readiness, planning, _result = _run()
    binding = planning.planning_binding
    handoff = planning.handoff
    evidence = readiness.issueplan_current_state_evidence

    assert binding.issueplan_current_state_evidence_id == evidence.evidence_id
    assert binding.graph_digest == handoff.graph_digest
    assert binding.planning_result_digest == handoff.planning_result_digest
    assert binding.handoff_digest == handoff.handoff_digest
    assert binding.supplied_node_ids == handoff.supplied_node_ids


# --------------------------------------------------------------------------
# Fail-closed behavior.
# --------------------------------------------------------------------------


def _tampered(binding: PlanningBindingEvidence, **fields) -> PlanningBindingEvidence:
    """Mutate a frozen binding in place, bypassing its constructor guard.

    This is deliberately hostile: it is the only way to produce an object whose
    ``binding_id`` no longer matches its content, which is exactly what the
    downstream verifier must detect.
    """

    clone = object.__new__(PlanningBindingEvidence)
    for slot in (
        "schema_version",
        "binding_id",
        "issueplan_current_state_evidence_id",
        "repository",
        "base_branch",
        "evaluated_repository_sha",
        "implementation_contract_fingerprint",
        "handoff_contract_version",
        "planning_result_version",
        "graph_digest",
        "planning_result_digest",
        "handoff_digest",
        "supplied_node_ids",
        "created_at",
        "execution_authorized",
        "side_effects_performed",
    ):
        object.__setattr__(clone, slot, fields.get(slot, getattr(binding, slot)))
    return clone


def test_tampered_binding_identity_fails_closed() -> None:
    _readiness, planning, _result = _run()
    tampered = _tampered(planning.planning_binding, graph_digest=_OTHER_CONTRACT)
    # The identity no longer covers the content.
    assert tampered.binding_id != (
        "planning-binding:" + compute_planning_binding_fingerprint(tampered)
    )

    result = prepare_repository_and_proposal(
        _replace_binding(planning, tampered),
        _observation(),
        created_at=_PROPOSED_AT,
    )
    assert result.status is RepositoryProposalStageStatus.STALE
    assert result.proposal is None


def test_binding_handoff_mismatch_fails_closed() -> None:
    """A binding that is internally valid but attests to a different handoff."""

    _readiness, planning, _result = _run()
    _other_readiness, other_planning, _other = _run(
        planning_context=_context(evaluated_repository_sha=_OTHER_SHA),
        observation=_observation(
            head_sha=_OTHER_SHA, requested_sha=_OTHER_SHA, observed_sha=_OTHER_SHA,
            tested_sha=_OTHER_SHA,
        ),
    )
    foreign = other_planning.planning_binding
    # Internally consistent, just not this pipeline's binding.
    assert foreign.binding_id == (
        "planning-binding:" + compute_planning_binding_fingerprint(foreign)
    )
    assert foreign.handoff_digest != planning.handoff.handoff_digest

    result = prepare_repository_and_proposal(
        _replace_binding(planning, foreign),
        _observation(),
        created_at=_PROPOSED_AT,
    )
    assert result.status is RepositoryProposalStageStatus.STALE
    assert result.proposal is None


def test_stale_repository_evidence_fails_closed() -> None:
    _readiness, _planning, result = _run(
        observation=_observation(
            head_sha=_OTHER_SHA,
            requested_sha=_OTHER_SHA,
            observed_sha=_OTHER_SHA,
            tested_sha=_OTHER_SHA,
        )
    )
    assert result.status is not RepositoryProposalStageStatus.ELIGIBLE
    assert result.proposal is None


def test_contract_fingerprint_mismatch_fails_closed() -> None:
    _readiness, _planning, result = _run(
        observation=_observation(contract_fingerprint=_OTHER_CONTRACT)
    )
    assert result.status is not RepositoryProposalStageStatus.ELIGIBLE
    assert result.proposal is None


def _replace_binding(planning, binding):
    """Swap only the binding on a planning result, leaving every other object.

    ``dataclasses.replace`` is not used on any pipeline artifact in the accepted
    path; this helper exists solely to inject hostile bindings into the
    fail-closed tests above.
    """

    from scripts.agent_os_candidate_packet.planning_stage import (
        PlanningHandoffStageResult,
    )

    return PlanningHandoffStageResult(
        status=planning.status,
        node=planning.node,
        graph=planning.graph,
        planning_result=planning.planning_result,
        handoff=planning.handoff,
        serialized_handoff=planning.serialized_handoff,
        handoff_validation=planning.handoff_validation,
        wsc3_suppliable=planning.wsc3_suppliable,
        reason_codes=planning.reason_codes,
        issueplan_current_state_evidence=(
            planning.issueplan_current_state_evidence
        ),
        planning_binding=binding,
    )


# --------------------------------------------------------------------------
# The accepted path uses none of the prohibited mechanisms.
# --------------------------------------------------------------------------


def test_accepted_path_uses_no_prohibited_mechanism() -> None:
    """Statically assert the pipeline driver avoids every banned shortcut."""

    source = inspect.getsource(_run)
    tree = ast.parse(source.strip())
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "replace" not in called
    for banned in (
        "dataclasses.replace",
        "build_issueplan_current_state_evidence",
        "compute_issueplan_current_state_fingerprint",
        "build_planning_binding_evidence",
        "graph_reference",
        "handoff_reference",
    ):
        assert banned not in source


def test_module_never_imports_dataclasses_replace() -> None:
    """No import of ``replace`` exists anywhere in this module.

    Checked structurally rather than by substring, so the assertion cannot be
    defeated -- or tripped -- by the text of the test itself.
    """

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "dataclasses":
            assert all(alias.name != "replace" for alias in node.names)
        if isinstance(node, ast.Import):
            assert all(alias.name != "dataclasses" for alias in node.names)
