"""Public read-only candidate-packet entrypoint (#1105, #749 Stage 7).

``prepare_candidate_packet(...)`` is the one programmatic integration surface
that composes the existing #750 -> #751 -> #752 -> #753 -> #754 -> #755
public pipeline in order, materializing #917's ``IssuePlanningContext``
itself from a deterministically derived ``implementation_contract_fingerprint``
(see ``contract_fingerprint.py``) instead of asking the caller to invent or
copy one. ``main(argv)`` is the operator-facing ``prepare-candidate-packet``
command over the same function, following this repository's existing
per-package ``cli.py`` convention (see
``scripts/agent_os_issue_acceptance/cli.py``) rather than introducing a new
CLI dispatch mechanism or ``__main__.py``.

This module performs no execution, mutation, authorization inference,
provider use, Scheduler execution, network write, credential use, or
external write. Every value it returns is either read directly off an
existing canonical stage-result object or is the caller's own explicit input;
nothing here invents an identity, an approval, or a timestamp.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Literal

from scripts.agent_os_execution_capabilities import RepositoryIdentity, RepositoryEvidenceType, WorktreeState
from scripts.agent_os_issue_acceptance import ApprovalKind, ApprovalState

from .approval_stage import (
    ApprovalCandidateContext,
    ApprovalDecision,
    ApprovalProjectionStageResult,
    prepare_approval_projection,
)
from .compiler import compile_candidate_packet
from .contract_fingerprint import (
    IMPLEMENTATION_CONTRACT_SCHEMA_NAME,
    IMPLEMENTATION_CONTRACT_SCHEMA_VERSION,
    compute_implementation_contract_fingerprint,
    derive_canonical_contract,
)
from .models import (
    COMPILER_SCHEMA_NAME,
    COMPILER_SCHEMA_VERSION,
    CandidatePacket,
    CandidatePacketCompilationFailure,
    CandidatePacketCompilerInput,
    CandidatePacketPhase,
    serialize_candidate_packet,
)
from .planning_stage import PlanningHandoffStageResult, prepare_planning_handoff
from .proposal_stage import RepositoryProposalStageResult, prepare_repository_and_proposal
from .readiness_stage import prepare_issue_readiness
from .repository_stage import RepositoryObservation, repository_state_evidence_from_dict
from .stage_models import (
    DependencyEvidence,
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
    EvidenceStatus,
    IssuePlanningContext,
    IssueReadinessStageRequest,
    IssueReadinessStageResult,
    IssueReadinessStageStatus,
    IssueReadResult,
    IssueReadStatus,
    IssueSourceReader,
    RepositoryEvidenceReader,
    ValidationEvidence,
)
from .validation_stage import CandidateRuntimeInputs

_DISPOSITION_APPROVAL_READY = "approval-ready"
_DISPOSITION_EXECUTION_CANDIDATE = "execution-candidate"
_DISPOSITION_BLOCKED = "blocked"
_DISPOSITION_NEEDS_DECISION = "needs-decision"
_DISPOSITION_INVALID = "invalid"

_READINESS_DISPOSITIONS = {
    IssueReadinessStageStatus.BLOCKED: _DISPOSITION_BLOCKED,
    IssueReadinessStageStatus.NEEDS_DECISION: _DISPOSITION_NEEDS_DECISION,
    IssueReadinessStageStatus.SOURCE_FAILURE: _DISPOSITION_INVALID,
    IssueReadinessStageStatus.INCOMPLETE_EVIDENCE: _DISPOSITION_INVALID,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class PreparedCandidatePacket:
    """One read-only aggregation of the pipeline evidence actually reached.

    This holds only references to existing canonical stage-result objects
    plus the derived fingerprint and a finite disposition string -- it is a
    reporting envelope, not a second model family. Every ``*_stage_result``
    field is ``None`` only when that stage was never legitimately reachable
    (a required upstream object was absent), never a placeholder.
    """

    source_revision: str | None
    implementation_contract_fingerprint: str | None
    implementation_contract_schema_name: str
    implementation_contract_schema_version: str
    stage_reached: str
    disposition: str
    readiness_stage_result: IssueReadinessStageResult | None
    planning_stage_result: PlanningHandoffStageResult | None
    proposal_stage_result: RepositoryProposalStageResult | None
    approval_stage_result: ApprovalProjectionStageResult | None
    execution_packet_stage_result: object | None
    packet: CandidatePacket | None
    compilation_failure: CandidatePacketCompilationFailure | None
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    automatic_retry: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.packet is not None and self.compilation_failure is not None:
            raise ValueError("packet and compilation_failure are mutually exclusive")


def prepare_candidate_packet(
    *,
    repository: str,
    issue_number: int,
    issue_reader: IssueSourceReader,
    repository_reader: RepositoryEvidenceReader,
    observed_at: str,
    base_branch: str,
    evaluated_repository_sha: str,
    invocation_id: str,
    evaluator_sha: str,
    freshness_boundary: str = "stage-observation",
    dependency_identity_evidence: DependencyIdentityEvidence | None = None,
    planning_evaluator_sha: str | None = None,
    planning_created_at: str | None = None,
    repository_observation: RepositoryObservation | None = None,
    proposal_created_at: str | None = None,
    candidate_context: ApprovalCandidateContext | None = None,
    approval_decision: ApprovalDecision | None = None,
    approval_evaluated_at: str | None = None,
    approval_projected_at: str | None = None,
    requested_phase: CandidatePacketPhase = CandidatePacketPhase.APPROVAL_READY,
    candidate_runtime_inputs: CandidateRuntimeInputs | None = None,
    external_build_sha: str | None = None,
    compiler_evaluated_at: str | None = None,
) -> PreparedCandidatePacket:
    """Compose #750-#755 end to end, stopping at the first truthful blocker.

    Every optional parameter names one external, real-world observation or
    human artifact this entrypoint cannot derive on its own (a repository
    observation, an explicit approval candidate context, a separately
    supplied human decision, or candidate-bound runtime inputs). Omitting one
    of them stops the pipeline truthfully at the last stage that could
    legitimately run -- it never invents the missing object to continue.

    Identity fields that *can* be derived from already-constructed canonical
    objects (source revision, IssuePlan fingerprints, the derived
    implementation-contract fingerprint, candidate ref, base/tested SHA) are
    derived here rather than asked of the caller a second time.
    """
    planning_evaluator_sha = planning_evaluator_sha or evaluator_sha
    planning_created_at = planning_created_at or observed_at
    proposal_created_at = proposal_created_at or observed_at
    approval_evaluated_at = approval_evaluated_at or observed_at
    approval_projected_at = approval_projected_at or observed_at
    compiler_evaluated_at = compiler_evaluated_at or observed_at

    # Pass 1: resolve the exact source snapshot and scan its governed
    # IssuePlan fields with no planning context yet -- this is the only way
    # to obtain the normalized semantic fields the fingerprint is derived
    # from before ``IssuePlanningContext`` can be built.
    request = IssueReadinessStageRequest(
        repository=repository,
        issue_number=issue_number,
        observed_at=observed_at,
        freshness_boundary=freshness_boundary,
    )
    precheck = prepare_issue_readiness(
        request,
        issue_reader,
        repository_reader,
        dependency_identity_evidence=dependency_identity_evidence,
        planning_context=None,
    )
    if precheck.status not in (
        IssueReadinessStageStatus.READY,
        IssueReadinessStageStatus.BLOCKED,
        IssueReadinessStageStatus.NEEDS_DECISION,
    ):
        return _stopped_at_readiness(precheck)

    assert precheck.snapshot is not None
    assert precheck.issueplan_current_state_evidence is not None
    canonical_contract = derive_canonical_contract(
        precheck.issueplan_current_state_evidence.source_snapshot
    )
    implementation_contract_fingerprint = compute_implementation_contract_fingerprint(
        canonical_contract=canonical_contract
    )
    allowed_files = tuple(canonical_contract["allowed_files"])
    forbidden_paths = tuple(canonical_contract["forbidden_paths"])
    required_tests = tuple(canonical_contract["required_tests"])

    planning_context = IssuePlanningContext(
        repository=repository,
        base_branch=base_branch,
        evaluated_repository_sha=evaluated_repository_sha,
        implementation_contract_fingerprint=implementation_contract_fingerprint,
        allowed_files=allowed_files,
        forbidden_paths=forbidden_paths,
        required_tests=required_tests,
        provenance=(
            f"agent-os-candidate-packet-cli:{repository}#{issue_number}"
            f"@{precheck.snapshot.source_revision}",
        ),
    )

    # Pass 2: the real readiness result, with the derived context projected
    # into IssuePlan evidence before that evidence's identity is computed.
    readiness = prepare_issue_readiness(
        request,
        issue_reader,
        repository_reader,
        dependency_identity_evidence=dependency_identity_evidence,
        planning_context=planning_context,
    )
    if readiness.status not in (
        IssueReadinessStageStatus.READY,
        IssueReadinessStageStatus.BLOCKED,
        IssueReadinessStageStatus.NEEDS_DECISION,
    ):
        return _stopped_at_readiness(
            readiness,
            implementation_contract_fingerprint=implementation_contract_fingerprint,
        )
    assert readiness.snapshot is not None

    planning = prepare_planning_handoff(
        readiness, evaluator_sha=planning_evaluator_sha, created_at=planning_created_at
    )

    proposal: RepositoryProposalStageResult | None = None
    approval: ApprovalProjectionStageResult | None = None
    execution_packet = None
    packet: CandidatePacket | None = None
    failure: CandidatePacketCompilationFailure | None = None

    if repository_observation is not None:
        proposal = prepare_repository_and_proposal(
            planning, repository_observation, created_at=proposal_created_at
        )

        if candidate_context is not None:
            approval = prepare_approval_projection(
                proposal,
                candidate_context=candidate_context,
                approval_decision=approval_decision,
                evaluated_at=approval_evaluated_at,
                projected_at=approval_projected_at,
            )

        if (
            requested_phase is CandidatePacketPhase.EXECUTION_CANDIDATE
            and approval is not None
            and candidate_runtime_inputs is not None
        ):
            from .execution_packet_stage import prepare_execution_packet

            execution_packet = prepare_execution_packet(approval, candidate_runtime_inputs)

        compiler_input = _build_compiler_input(
            repository=repository,
            issue_number=issue_number,
            invocation_id=invocation_id,
            base_branch=base_branch,
            evaluated_repository_sha=evaluated_repository_sha,
            evaluator_sha=evaluator_sha,
            external_build_sha=external_build_sha,
            freshness_boundary=freshness_boundary,
            requested_phase=requested_phase,
            implementation_contract_fingerprint=implementation_contract_fingerprint,
            readiness=readiness,
            planning=planning,
            proposal=proposal,
            approval=approval,
            execution_packet=execution_packet,
            candidate_runtime_inputs=candidate_runtime_inputs,
            repository_observation=repository_observation,
        )
        result = compile_candidate_packet(compiler_input, evaluated_at=compiler_evaluated_at)
        if isinstance(result, CandidatePacket):
            packet = result
        else:
            failure = result

    stage_reached, disposition = _classify(planning=planning, packet=packet, failure=failure)

    return PreparedCandidatePacket(
        source_revision=readiness.snapshot.source_revision,
        implementation_contract_fingerprint=implementation_contract_fingerprint,
        implementation_contract_schema_name=IMPLEMENTATION_CONTRACT_SCHEMA_NAME,
        implementation_contract_schema_version=IMPLEMENTATION_CONTRACT_SCHEMA_VERSION,
        stage_reached=stage_reached,
        disposition=disposition,
        readiness_stage_result=readiness,
        planning_stage_result=planning,
        proposal_stage_result=proposal,
        approval_stage_result=approval,
        execution_packet_stage_result=execution_packet,
        packet=packet,
        compilation_failure=failure,
    )


def _stopped_at_readiness(
    readiness: IssueReadinessStageResult,
    *,
    implementation_contract_fingerprint: str | None = None,
) -> PreparedCandidatePacket:
    return PreparedCandidatePacket(
        source_revision=None if readiness.snapshot is None else readiness.snapshot.source_revision,
        implementation_contract_fingerprint=implementation_contract_fingerprint,
        implementation_contract_schema_name=IMPLEMENTATION_CONTRACT_SCHEMA_NAME,
        implementation_contract_schema_version=IMPLEMENTATION_CONTRACT_SCHEMA_VERSION,
        stage_reached="readiness",
        disposition=_READINESS_DISPOSITIONS[readiness.status],
        readiness_stage_result=readiness,
        planning_stage_result=None,
        proposal_stage_result=None,
        approval_stage_result=None,
        execution_packet_stage_result=None,
        packet=None,
        compilation_failure=None,
    )


def _build_compiler_input(
    *,
    repository: str,
    issue_number: int,
    invocation_id: str,
    base_branch: str,
    evaluated_repository_sha: str,
    evaluator_sha: str,
    external_build_sha: str | None,
    freshness_boundary: str,
    requested_phase: CandidatePacketPhase,
    implementation_contract_fingerprint: str,
    readiness,
    planning,
    proposal: RepositoryProposalStageResult,
    approval: ApprovalProjectionStageResult | None,
    execution_packet,
    candidate_runtime_inputs: CandidateRuntimeInputs | None,
    repository_observation: RepositoryObservation,
) -> CandidatePacketCompilerInput:
    issueplan = readiness.issueplan_current_state_evidence
    snapshot = readiness.snapshot

    if candidate_runtime_inputs is not None:
        candidate_sha = candidate_runtime_inputs.candidate_sha
        source_sha = candidate_runtime_inputs.candidate_sha
        tested_sha = candidate_runtime_inputs.tested_sha
    else:
        candidate_sha = evaluated_repository_sha
        source_sha = evaluated_repository_sha
        evidence = proposal.repository_state_evidence
        tested_sha = evidence.tested_sha if evidence is not None else evaluated_repository_sha

    return CandidatePacketCompilerInput(
        compiler_schema_name=COMPILER_SCHEMA_NAME,
        compiler_schema_version=COMPILER_SCHEMA_VERSION,
        requested_phase=requested_phase,
        repository=repository,
        issue_number=issue_number,
        invocation_id=invocation_id,
        candidate_ref=repository_observation.head_ref,
        base_branch=base_branch,
        base_sha=evaluated_repository_sha,
        candidate_sha=candidate_sha,
        source_sha=source_sha,
        tested_sha=tested_sha,
        evaluator_sha=evaluator_sha,
        external_build_sha=external_build_sha,
        expected_source_revision=snapshot.source_revision,
        expected_source_snapshot_fingerprint=issueplan.source_snapshot_fingerprint,
        expected_scanner_result_fingerprint=issueplan.scanner_result_fingerprint,
        expected_candidate_set_fingerprint=issueplan.source_snapshot.candidate_set_fingerprint,
        expected_implementation_contract_fingerprint=implementation_contract_fingerprint,
        freshness_boundary=freshness_boundary,
        readiness_stage_result=readiness,
        planning_stage_result=planning,
        proposal_stage_result=proposal,
        approval_stage_result=approval,
        execution_packet_stage_result=execution_packet,
    )


def _classify(*, planning, packet, failure) -> tuple[str, str]:
    if packet is not None:
        return "packet", packet.phase.value
    if failure is not None:
        if failure.human_judgment_required or failure.external_authorization_required:
            return "packet-compilation", _DISPOSITION_NEEDS_DECISION
        if failure.reason_code.startswith(("compiler-input.", "serialization.")):
            return "packet-compilation", _DISPOSITION_INVALID
        return "packet-compilation", _DISPOSITION_BLOCKED
    # ``compile_candidate_packet`` is always attempted once a proposal stage
    # result exists (see ``prepare_candidate_packet``), so reaching this line
    # means no ``repository_observation`` was supplied at all: planning is the
    # last stage that legitimately ran. Its own status is already one of the
    # finite existing canonical values (``ready``, ``blocked``,
    # ``needs-decision``, ``invalid-input``) and is reported as-is rather than
    # force-mapped into the packet-level vocabulary.
    return "planning", planning.status.value


def prepared_candidate_packet_to_dict(result: PreparedCandidatePacket) -> dict[str, object]:
    """Deterministic machine-readable summary for CLI/JSON consumers.

    Nested stage objects are summarized by their own existing identities
    (never re-serialized here) except the packet itself, which reuses the
    canonical ``serialize_candidate_packet`` transport.
    """
    if not isinstance(result, PreparedCandidatePacket):
        raise TypeError("result must be a PreparedCandidatePacket")
    readiness = result.readiness_stage_result
    issueplan = None if readiness is None else readiness.issueplan_current_state_evidence
    planning = result.planning_stage_result
    proposal = result.proposal_stage_result
    approval = result.approval_stage_result

    return {
        "source_revision": result.source_revision,
        "implementation_contract_fingerprint": result.implementation_contract_fingerprint,
        "implementation_contract_schema_name": result.implementation_contract_schema_name,
        "implementation_contract_schema_version": result.implementation_contract_schema_version,
        "stage_reached": result.stage_reached,
        "disposition": result.disposition,
        "readiness_status": None if readiness is None else readiness.status.value,
        "issueplan_evidence_id": None if issueplan is None else issueplan.evidence_id,
        "planning_status": None if planning is None else planning.status.value,
        "handoff_digest": (
            None if planning is None or planning.handoff is None else planning.handoff.handoff_digest
        ),
        "proposal_status": None if proposal is None else proposal.status.value,
        "proposal_id": (
            None if proposal is None or proposal.proposal is None else proposal.proposal.proposal_id
        ),
        "approval_status": None if approval is None else approval.status.value,
        "pending_approval_id": (
            None
            if approval is None or approval.pending_candidate is None
            else approval.pending_candidate.approval_id
        ),
        "packet_id": None if result.packet is None else result.packet.packet_id,
        "packet_phase": None if result.packet is None else result.packet.phase.value,
        "packet": None if result.packet is None else serialize_candidate_packet(result.packet),
        "failure_reason_code": (
            None if result.compilation_failure is None else result.compilation_failure.reason_code
        ),
        "failure_class": (
            None
            if result.compilation_failure is None
            else result.compilation_failure.failure_class.value
        ),
        "human_judgment_required": (
            False
            if result.compilation_failure is None
            else result.compilation_failure.human_judgment_required
        ),
        "external_authorization_required": (
            False
            if result.compilation_failure is None
            else result.compilation_failure.external_authorization_required
        ),
        "execution_authorized": False,
        "merge_authorized": False,
        "automatic_retry": False,
        "side_effects_performed": False,
    }


def render_summary(result: PreparedCandidatePacket) -> str:
    """Concise human-readable operator summary."""
    lines = [
        f"stage reached: {result.stage_reached}",
        f"disposition: {result.disposition}",
        f"source revision: {result.source_revision}",
        f"implementation-contract fingerprint: {result.implementation_contract_fingerprint}",
    ]
    if result.packet is not None:
        lines.append(f"packet id: {result.packet.packet_id} (phase={result.packet.phase.value})")
    elif result.compilation_failure is not None:
        failure = result.compilation_failure
        lines.append(f"blocker: {failure.reason_code} (failure_class={failure.failure_class.value})")
        lines.append(f"human_judgment_required={failure.human_judgment_required}")
        lines.append(f"external_authorization_required={failure.external_authorization_required}")
    lines.append("execution_authorized=false merge_authorized=false side_effects_performed=false")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# CLI fixture parsing. The CLI never performs a live GitHub/network read
# itself -- it consumes an explicit, bounded JSON fixture describing the
# read-only issue/repository/candidate observations a caller already holds,
# matching the fixture-driven pattern already used by
# ``scripts/agent_os_issue_acceptance/cli.py``.
# --------------------------------------------------------------------------


class _FixtureIssueReader(IssueSourceReader):
    def __init__(self, item: dict[str, object]) -> None:
        self._item = item

    def read_issue(self, repository: str, issue_number: int) -> IssueReadResult:
        return IssueReadResult(status=IssueReadStatus.OK, item=dict(self._item))


class _FixtureRepositoryReader(RepositoryEvidenceReader):
    def __init__(
        self,
        dependency: DependencyEvidence | None,
        validation: ValidationEvidence | None,
    ) -> None:
        self._dependency = dependency or DependencyEvidence(
            status=EvidenceStatus.UNAVAILABLE, reason_codes=("dependency.no-structured-source",)
        )
        self._validation = validation or ValidationEvidence(
            status=EvidenceStatus.UNAVAILABLE, reason_codes=("validation.no-structured-source",)
        )

    def read_dependency_evidence(self, repository: str, issue_number: int) -> DependencyEvidence:
        return self._dependency

    def read_validation_evidence(self, repository: str, issue_number: int) -> ValidationEvidence:
        return self._validation


def _evidence_status_from_dict(
    data: dict[str, object] | None, cls: type[DependencyEvidence] | type[ValidationEvidence]
):
    if data is None:
        return None
    return cls(
        status=EvidenceStatus(data["status"]),
        reason_codes=tuple(data.get("reason_codes", ())),
        details=tuple(data.get("details", ())),
    )


def _dependency_identity_evidence_from_dict(
    data: dict[str, object] | None,
) -> DependencyIdentityEvidence | None:
    if data is None:
        return None
    return DependencyIdentityEvidence(
        status=DependencyIdentityStatus(data["status"]),
        dependency_ids=tuple(data.get("dependency_ids", ())),
        provenance=tuple(data.get("provenance", ())),
        reason_codes=tuple(data.get("reason_codes", ())),
    )


def _repository_identity_from_dict(data: dict[str, object]) -> RepositoryIdentity:
    return RepositoryIdentity(
        host=data["host"],
        owner=data["owner"],
        repository=data["repository"],
        repository_id=data.get("repository_id"),
        is_fork=data.get("is_fork", False),
        upstream_owner=data.get("upstream_owner"),
        upstream_repository=data.get("upstream_repository"),
        upstream_repository_id=data.get("upstream_repository_id"),
        default_branch=data.get("default_branch", "main"),
    )


def _repository_observation_from_dict(data: dict[str, object]) -> RepositoryObservation:
    return RepositoryObservation(
        producer_adapter=data["producer_adapter"],
        producer_adapter_version=data["producer_adapter_version"],
        correlation_id=data["correlation_id"],
        repository_identity=_repository_identity_from_dict(data["repository_identity"]),
        base_ref=data["base_ref"],
        base_sha=data["base_sha"],
        head_ref=data["head_ref"],
        head_sha=data["head_sha"],
        requested_ref=data.get("requested_ref"),
        requested_sha=data.get("requested_sha"),
        observed_sha=data["observed_sha"],
        tested_sha=data.get("tested_sha"),
        pushed_sha=data.get("pushed_sha"),
        proposed_pr_sha=data.get("proposed_pr_sha"),
        synthetic_merge_sha=data.get("synthetic_merge_sha"),
        external_build_sha=data.get("external_build_sha"),
        evidence_type=RepositoryEvidenceType(data["evidence_type"]),
        contract_fingerprint=data["contract_fingerprint"],
        worktree_state=WorktreeState(data["worktree_state"]),
        observed_at=data["observed_at"],
        freshness_boundary=data["freshness_boundary"],
        worktree_reason_codes=tuple(data.get("worktree_reason_codes", ())),
    )


def _candidate_context_from_dict(data: dict[str, object]) -> ApprovalCandidateContext:
    return ApprovalCandidateContext(
        approval_kind=ApprovalKind(data["approval_kind"]),
        authorizer_id=data["authorizer_id"],
        decision_id=data["decision_id"],
        decision_at=data["decision_at"],
        expires_at=data.get("expires_at"),
    )


def _approval_decision_from_dict(data: dict[str, object]) -> ApprovalDecision:
    return ApprovalDecision(
        state=ApprovalState(data["state"]),
        decision_id=data["decision_id"],
        authorizer_id=data["authorizer_id"],
        decision_at=data["decision_at"],
        reason_codes=tuple(data.get("reason_codes", ())),
        details=tuple(data.get("details", ())),
    )


def _candidate_runtime_inputs_from_dict(data: dict[str, object]) -> CandidateRuntimeInputs:
    repository_state_evidence = repository_state_evidence_from_dict(
        data["repository_state_evidence"]
    )
    return CandidateRuntimeInputs(
        repository_identity=repository_state_evidence.repository_identity,
        repository_state_evidence=repository_state_evidence,
        issue_number=data["issue_number"],
        invocation_id=data["invocation_id"],
        candidate_branch=data["candidate_branch"],
        candidate_sha=data["candidate_sha"],
        tested_sha=data["tested_sha"],
        evaluator_sha=data["evaluator_sha"],
        expected_changed_paths=tuple(data.get("expected_changed_paths", ())),
        required_tests=tuple(data["required_tests"]),
        created_at=data["created_at"],
        expires_at=data["expires_at"],
        evaluated_at=data["evaluated_at"],
        repository_root=data["repository_root"],
        workspace_parent=data["workspace_parent"],
        validation_bundle_id=data["validation_bundle_id"],
        advisory_result_id=data["advisory_result_id"],
        advisory_render_id=data["advisory_render_id"],
        execution_authorization_present=data.get("execution_authorization_present", False),
    )


def _prepare_from_fixture(fixture: dict[str, object]) -> PreparedCandidatePacket:
    dependency = _evidence_status_from_dict(fixture.get("dependency_evidence"), DependencyEvidence)
    validation = _evidence_status_from_dict(fixture.get("validation_evidence"), ValidationEvidence)
    repository_observation = fixture.get("repository_observation")
    candidate_context = fixture.get("candidate_context")
    approval_decision = fixture.get("approval_decision")
    candidate_runtime_inputs = fixture.get("candidate_runtime_inputs")
    requested_phase_value = fixture.get("requested_phase", CandidatePacketPhase.APPROVAL_READY.value)

    return prepare_candidate_packet(
        repository=fixture["repository"],
        issue_number=fixture["issue_number"],
        issue_reader=_FixtureIssueReader(fixture["issue"]),
        repository_reader=_FixtureRepositoryReader(dependency, validation),
        observed_at=fixture["observed_at"],
        base_branch=fixture["base_branch"],
        evaluated_repository_sha=fixture["evaluated_repository_sha"],
        invocation_id=fixture["invocation_id"],
        evaluator_sha=fixture["evaluator_sha"],
        freshness_boundary=fixture.get("freshness_boundary", "stage-observation"),
        dependency_identity_evidence=_dependency_identity_evidence_from_dict(
            fixture.get("dependency_identity_evidence")
        ),
        repository_observation=(
            None
            if repository_observation is None
            else _repository_observation_from_dict(repository_observation)
        ),
        candidate_context=(
            None if candidate_context is None else _candidate_context_from_dict(candidate_context)
        ),
        approval_decision=(
            None if approval_decision is None else _approval_decision_from_dict(approval_decision)
        ),
        requested_phase=CandidatePacketPhase(requested_phase_value),
        candidate_runtime_inputs=(
            None
            if candidate_runtime_inputs is None
            else _candidate_runtime_inputs_from_dict(candidate_runtime_inputs)
        ),
        external_build_sha=fixture.get("external_build_sha"),
    )


def main(argv: list[str] | None = None) -> int:
    """``prepare-candidate-packet`` operator entrypoint.

    Reads a bounded, explicit JSON fixture file describing the read-only
    issue/repository/candidate observations for one preparation request --
    never live GitHub/network access itself. Producing that fixture (e.g.
    from an actual GitHub read) is the caller's responsibility, matching
    every other fixture-driven CLI already in this repository.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Prepare one read-only Agent OS candidate packet from an explicit "
            "JSON fixture of issue/repository/candidate observations."
        )
    )
    parser.add_argument(
        "--request",
        required=True,
        help="Path to a JSON fixture matching the shape documented in README.md.",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    try:
        with open(args.request, encoding="utf-8") as handle:
            fixture = json.load(handle)
        result = _prepare_from_fixture(fixture)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(prepared_candidate_packet_to_dict(result), indent=2, sort_keys=True))
    else:
        print(render_summary(result), end="")
    return 0 if result.packet is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
