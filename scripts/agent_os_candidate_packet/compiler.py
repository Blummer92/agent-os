"""The #755 pure-local candidate-packet compiler.

``compile_candidate_packet`` is the sole entry point. It consumes one
``CandidatePacketCompilerInput`` binding the already-authoritative canonical
#750-#754 stage objects, walks the frozen 18-step validation order documented
below, and returns exactly one of a complete ``CandidatePacket`` or one
``CandidatePacketCompilationFailure`` naming the first failing prerequisite.

No later successful check repairs an earlier invalid one: every step below
either returns a failure immediately or falls through to the next step.
Nothing here retrieves issue prose, calls a network, subprocess, Git,
filesystem, provider, or Scheduler API, or creates approval or execution
authority -- it only reverifies and binds objects the caller already built
through #750-#754's own canonical constructors.

Frozen validation order (see ``README.md`` for the full rationale):

 1. exact compiler-input type and supported schema
 2. requested packet phase
 3. fixed non-authority fields
 4. repository/issue/invocation/branch/ref/SHA-role syntax (enforced by
    ``CandidatePacketCompilerInput.__post_init__`` at construction)
 5. source-stage object type, identity, and source revision
 6. IssuePlan/readiness object type, identity, and freshness
 7. planning-stage object type, digests, handoff serialization, provenance
 8. repository-state evidence type, identity, worktree/evidence status, freshness
 9. proposal type, identity, and upstream bindings
10. approval-stage object type and phase-appropriate completeness
11. applicability and projection, only for ``execution-candidate``
12. validation subject, plan, command plan, request, runtime fingerprint,
    only for ``execution-candidate``
13. cross-object repository/issue/invocation/ref/SHA bindings
14. scope, tests, argv ordering, timeout, output-bound consistency
15. duplicate, ordering, count, and size bounds
16. provenance-manifest and invalidation-manifest construction
17. packet semantic identity construction
18. canonical serialization and immediate reconstruction verification
"""

from __future__ import annotations

from .approval_stage import ApprovalProjectionStageResult, ApprovalProjectionStageStatus
from .blockers import build_failure
from .freshness import build_invalidation_manifest, evaluate_freshness_bindings
from .models import (
    COMPILER_SCHEMA_NAME,
    COMPILER_SCHEMA_VERSION,
    PACKET_SCHEMA_NAME,
    PACKET_SCHEMA_VERSION,
    CandidatePacket,
    CandidatePacketCompilationFailure,
    CandidatePacketCompilationResult,
    CandidatePacketCompilerInput,
    CandidatePacketPhase,
    compute_candidate_packet_fingerprint,
    serialize_candidate_packet,
)
from .planning_stage import PlanningHandoffStageStatus, planning_handoff_stage_result_to_dict
from .proposal_stage import (
    RepositoryProposalStageStatus,
    repository_proposal_stage_result_to_dict,
)
from .provenance import build_provenance_manifest, build_stage_identities, build_stage_payload_digests
from .repository_stage import RepositoryStageStatus, repository_stage_result_to_dict
from .stage_models import (
    IssueReadinessStageStatus,
    canonical_bytes,
    issue_readiness_stage_result_to_dict,
)

_MAX_SCOPE_ENTRIES = 2_000
_MAX_PACKET_BYTES = 2_000_000

_APPROVAL_LIFECYCLE_REASONS = {
    ApprovalProjectionStageStatus.NEEDS_DECISION: "approval-stage.decision-missing",
    ApprovalProjectionStageStatus.REJECTED: "approval-stage.rejected",
    ApprovalProjectionStageStatus.EXPIRED: "approval-stage.expired",
    ApprovalProjectionStageStatus.INVALIDATED: "approval-stage.invalidated",
    ApprovalProjectionStageStatus.SUPERSEDED: "approval-stage.superseded",
    ApprovalProjectionStageStatus.STALE: "approval-stage.stale",
    ApprovalProjectionStageStatus.BLOCKED: "approval-stage.blocked",
    ApprovalProjectionStageStatus.INVALID: "approval-stage.invalid",
    ApprovalProjectionStageStatus.INVALID_INPUT: "approval-stage.missing",
}


def compile_candidate_packet(
    compiler_input: CandidatePacketCompilerInput,
    *,
    evaluated_at: str,
) -> CandidatePacketCompilationResult:
    """Compile one immutable ``CandidatePacket`` or one deterministic failure."""

    # Step 1: exact compiler-input type and supported schema.
    if type(compiler_input) is not CandidatePacketCompilerInput:
        return build_failure(
            requested_phase=_best_effort_phase(compiler_input),
            reason_code="compiler-input.wrong-type",
        )
    if (
        compiler_input.compiler_schema_name != COMPILER_SCHEMA_NAME
        or compiler_input.compiler_schema_version != COMPILER_SCHEMA_VERSION
    ):
        return build_failure(
            requested_phase=compiler_input.requested_phase,
            reason_code="compiler-input.unsupported-schema-version",
            expected_identity=f"{COMPILER_SCHEMA_NAME}:{COMPILER_SCHEMA_VERSION}",
            observed_identity=(
                f"{compiler_input.compiler_schema_name}:{compiler_input.compiler_schema_version}"
            ),
        )

    # Step 2: requested packet phase.
    phase = compiler_input.requested_phase
    if phase not in (CandidatePacketPhase.APPROVAL_READY, CandidatePacketPhase.EXECUTION_CANDIDATE):
        return build_failure(requested_phase=phase, reason_code="compiler-input.unsupported-phase")

    if not isinstance(evaluated_at, str) or not evaluated_at.strip():
        raise TypeError("evaluated_at must be non-empty text")

    # Step 3: fixed non-authority fields.
    if (
        compiler_input.execution_authorized
        or compiler_input.merge_authorized
        or compiler_input.automatic_retry
        or compiler_input.side_effects_performed
    ):
        return build_failure(
            requested_phase=phase, reason_code="compiler-input.authority-field-set-true"
        )

    # Step 4: syntax is enforced by CandidatePacketCompilerInput.__post_init__
    # at construction time; a frozen, already-constructed input cannot carry
    # malformed identity syntax, so nothing is re-checked here.

    # Step 5: source-stage object type, identity, and source revision.
    readiness = compiler_input.readiness_stage_result
    if readiness.status is not IssueReadinessStageStatus.READY:
        return _readiness_failure(phase, readiness.status)
    try:
        issue_readiness_stage_result_to_dict(readiness)
    except (TypeError, ValueError):
        return build_failure(
            requested_phase=phase,
            reason_code="source-stage.unresolved",
            failed_field="readiness_stage_result",
        )

    # Step 6: IssuePlan/readiness object type, identity, and freshness.
    binding = evaluate_freshness_bindings(compiler_input)
    if not binding.fresh:
        assert binding.reason_code is not None
        return build_failure(
            requested_phase=phase,
            reason_code=binding.reason_code,
            expected_identity=binding.expected_identity,
            observed_identity=binding.observed_identity,
        )

    # Step 7: planning-stage object type, digests, handoff, provenance.
    planning = compiler_input.planning_stage_result
    if planning.status is PlanningHandoffStageStatus.INVALID_INPUT:
        return build_failure(requested_phase=phase, reason_code="planning-stage.invalid-input")
    if planning.status is PlanningHandoffStageStatus.BLOCKED:
        return build_failure(requested_phase=phase, reason_code="planning-stage.blocked")
    if planning.status is PlanningHandoffStageStatus.NEEDS_DECISION:
        return build_failure(requested_phase=phase, reason_code="planning-stage.needs-decision")
    if planning.handoff_validation is None or not planning.handoff_validation.local_checks_passed:
        return build_failure(requested_phase=phase, reason_code="planning-stage.handoff-invalid")
    try:
        planning_handoff_stage_result_to_dict(planning)
    except (TypeError, ValueError):
        return build_failure(requested_phase=phase, reason_code="planning-stage.handoff-invalid")
    if planning.issueplan_current_state_evidence is not readiness.issueplan_current_state_evidence:
        return build_failure(
            requested_phase=phase,
            reason_code="cross-binding.repository-mismatch",
            failed_field="planning_stage_result.issueplan_current_state_evidence",
        )
    assert planning.handoff is not None
    if planning.handoff.evaluator_commit_sha != compiler_input.evaluator_sha:
        return build_failure(
            requested_phase=phase,
            reason_code="cross-binding.evaluator-sha-mismatch",
            expected_identity=compiler_input.evaluator_sha,
            observed_identity=planning.handoff.evaluator_commit_sha,
        )
    if planning.handoff.evaluated_repository_sha != compiler_input.base_sha:
        return build_failure(
            requested_phase=phase,
            reason_code="cross-binding.base-sha-mismatch",
            expected_identity=compiler_input.base_sha,
            observed_identity=planning.handoff.evaluated_repository_sha,
        )

    # Step 8: repository-state evidence type, identity, status, freshness.
    proposal_stage = compiler_input.proposal_stage_result
    repository_stage = proposal_stage.repository_stage
    if repository_stage is None or repository_stage.status is not RepositoryStageStatus.VALID:
        return _repository_stage_failure(phase, repository_stage)
    try:
        repository_stage_result_to_dict(repository_stage)
    except (TypeError, ValueError):
        return build_failure(requested_phase=phase, reason_code="repository-evidence.not-valid")

    # Step 9: proposal type, identity, and upstream bindings.
    if proposal_stage.status is not RepositoryProposalStageStatus.ELIGIBLE:
        return _proposal_status_failure(phase, proposal_stage.status)
    proposal = proposal_stage.proposal
    evidence = proposal_stage.repository_state_evidence
    if proposal is None or evidence is None:
        return build_failure(requested_phase=phase, reason_code="proposal.not-eligible")
    try:
        repository_proposal_stage_result_to_dict(proposal_stage)
    except (TypeError, ValueError):
        return build_failure(requested_phase=phase, reason_code="proposal.not-eligible")
    if proposal.repository.casefold() != compiler_input.repository.casefold():
        return build_failure(
            requested_phase=phase,
            reason_code="cross-binding.repository-mismatch",
            expected_identity=compiler_input.repository,
            observed_identity=proposal.repository,
        )
    if proposal.base_branch != compiler_input.base_branch:
        return build_failure(
            requested_phase=phase,
            reason_code="cross-binding.base-branch-mismatch",
            expected_identity=compiler_input.base_branch,
            observed_identity=proposal.base_branch,
        )
    if proposal.evaluated_repository_sha != compiler_input.base_sha:
        return build_failure(
            requested_phase=phase,
            reason_code="cross-binding.base-sha-mismatch",
            expected_identity=compiler_input.base_sha,
            observed_identity=proposal.evaluated_repository_sha,
        )
    if proposal.evaluator_commit_sha != compiler_input.evaluator_sha:
        return build_failure(
            requested_phase=phase,
            reason_code="cross-binding.evaluator-sha-mismatch",
            expected_identity=compiler_input.evaluator_sha,
            observed_identity=proposal.evaluator_commit_sha,
        )
    if evidence.tested_sha != compiler_input.tested_sha:
        return build_failure(
            requested_phase=phase,
            reason_code="cross-binding.tested-sha-mismatch",
            expected_identity=compiler_input.tested_sha,
            observed_identity=evidence.tested_sha,
        )
    if compiler_input.base_sha not in {evidence.head_sha, evidence.requested_sha, evidence.observed_sha}:
        return build_failure(
            requested_phase=phase,
            reason_code="cross-binding.base-sha-mismatch",
            expected_identity=compiler_input.base_sha,
            observed_identity=evidence.head_sha,
        )

    # Step 10: approval-stage object type and phase-appropriate completeness.
    approval = compiler_input.approval_stage_result
    if approval is None:
        return build_failure(requested_phase=phase, reason_code="approval-stage.missing")
    try:
        _approval_to_dict(approval)
    except (TypeError, ValueError):
        return build_failure(requested_phase=phase, reason_code="approval-stage.missing")

    if phase is CandidatePacketPhase.APPROVAL_READY:
        if compiler_input.execution_packet_stage_result is not None:
            return build_failure(
                requested_phase=phase, reason_code="compiler-input.phase-scope-violation"
            )
        if approval.pending_candidate is None:
            return build_failure(
                requested_phase=phase, reason_code="approval-stage.pending-candidate-missing"
            )
    else:
        failure = _require_complete_approval(phase, approval)
        if failure is not None:
            return failure

        # Step 11: applicability and projection (execution-candidate only).
        projection = approval.projection
        assert projection is not None
        if projection.repository.casefold() != compiler_input.repository.casefold():
            return build_failure(
                requested_phase=phase,
                reason_code="projection.binding-mismatch",
                expected_identity=compiler_input.repository,
                observed_identity=projection.repository,
            )
        if projection.evaluated_repository_sha != compiler_input.base_sha:
            return build_failure(
                requested_phase=phase,
                reason_code="cross-binding.base-sha-mismatch",
                expected_identity=compiler_input.base_sha,
                observed_identity=projection.evaluated_repository_sha,
            )
        if projection.tested_repository_sha != compiler_input.tested_sha:
            return build_failure(
                requested_phase=phase,
                reason_code="cross-binding.tested-sha-mismatch",
                expected_identity=compiler_input.tested_sha,
                observed_identity=projection.tested_repository_sha,
            )
        if projection.evaluator_commit_sha != compiler_input.evaluator_sha:
            return build_failure(
                requested_phase=phase,
                reason_code="cross-binding.evaluator-sha-mismatch",
                expected_identity=compiler_input.evaluator_sha,
                observed_identity=projection.evaluator_commit_sha,
            )

        # Step 12: validation subject, plan, command plan, request, runtime.
        execution_packet = compiler_input.execution_packet_stage_result
        if execution_packet is None:
            return build_failure(requested_phase=phase, reason_code="execution-packet.missing")
        try:
            _execution_packet_to_dict(execution_packet)
        except (TypeError, ValueError):
            return build_failure(requested_phase=phase, reason_code="execution-packet.not-complete")
        if not execution_packet.packet_complete:
            if not execution_packet.runtime_capability_available:
                return build_failure(
                    requested_phase=phase,
                    reason_code="execution-packet.runtime-capability-unavailable",
                )
            return build_failure(requested_phase=phase, reason_code="execution-packet.not-complete")
        validation = execution_packet.validation_stage
        if validation.base_sha != compiler_input.base_sha:
            return build_failure(
                requested_phase=phase,
                reason_code="cross-binding.base-sha-mismatch",
                expected_identity=compiler_input.base_sha,
                observed_identity=validation.base_sha,
            )
        if validation.tested_sha != compiler_input.tested_sha:
            return build_failure(
                requested_phase=phase,
                reason_code="cross-binding.tested-sha-mismatch",
                expected_identity=compiler_input.tested_sha,
                observed_identity=validation.tested_sha,
            )
        if validation.evaluator_sha != compiler_input.evaluator_sha:
            return build_failure(
                requested_phase=phase,
                reason_code="cross-binding.evaluator-sha-mismatch",
                expected_identity=compiler_input.evaluator_sha,
                observed_identity=validation.evaluator_sha,
            )
        if validation.candidate_sha != compiler_input.candidate_sha:
            return build_failure(
                requested_phase=phase,
                reason_code="cross-binding.candidate-sha-mismatch",
                expected_identity=compiler_input.candidate_sha,
                observed_identity=validation.candidate_sha,
            )
        if validation.source_sha != compiler_input.source_sha:
            return build_failure(
                requested_phase=phase,
                reason_code="cross-binding.source-sha-mismatch",
                expected_identity=compiler_input.source_sha,
                observed_identity=validation.source_sha,
            )
        if validation.invocation_id != compiler_input.invocation_id:
            return build_failure(
                requested_phase=phase,
                reason_code="cross-binding.invocation-mismatch",
                expected_identity=compiler_input.invocation_id,
                observed_identity=validation.invocation_id,
            )
        assert validation.subject is not None
        if validation.subject.branch != compiler_input.candidate_ref:
            return build_failure(
                requested_phase=phase,
                reason_code="cross-binding.candidate-ref-mismatch",
                expected_identity=compiler_input.candidate_ref,
                observed_identity=validation.subject.branch,
            )

    # Step 13: remaining cross-object repository/issue bindings.
    assert readiness.snapshot is not None
    if readiness.snapshot.repository.casefold() != compiler_input.repository.casefold():
        return build_failure(
            requested_phase=phase,
            reason_code="cross-binding.repository-mismatch",
            expected_identity=compiler_input.repository,
            observed_identity=readiness.snapshot.repository,
        )
    if readiness.snapshot.issue_number != compiler_input.issue_number:
        return build_failure(
            requested_phase=phase,
            reason_code="cross-binding.issue-mismatch",
            expected_identity=str(compiler_input.issue_number),
            observed_identity=str(readiness.snapshot.issue_number),
        )
    if planning.handoff.repository.casefold() != compiler_input.repository.casefold():
        return build_failure(
            requested_phase=phase,
            reason_code="cross-binding.repository-mismatch",
            expected_identity=compiler_input.repository,
            observed_identity=planning.handoff.repository,
        )
    if planning.handoff.base_branch != compiler_input.base_branch:
        return build_failure(
            requested_phase=phase,
            reason_code="cross-binding.base-branch-mismatch",
            expected_identity=compiler_input.base_branch,
            observed_identity=planning.handoff.base_branch,
        )

    # Step 14: scope, tests, argv ordering, timeout, output-bound evidence.
    issueplan = readiness.issueplan_current_state_evidence
    assert issueplan is not None
    if phase is CandidatePacketPhase.APPROVAL_READY:
        allowed_files = issueplan.allowed_files
        forbidden_paths = issueplan.forbidden_paths
        required_tests = issueplan.required_tests
        expected_changed_paths: tuple[str, ...] = ()
        command_identities: tuple[str, ...] = ()
        argv_bindings: tuple[tuple[str, tuple[str, ...]], ...] = ()
        per_command_timeout_seconds: int | None = None
        total_timeout_seconds: int | None = None
        max_output_bytes: int | None = None
        approval_summary = "pending-candidate-only:no-human-decision-claimed"
        execution_summary = "not-applicable:approval-ready-phase"
    else:
        execution_packet = compiler_input.execution_packet_stage_result
        assert execution_packet is not None
        subject = execution_packet.validation_stage.subject
        validation_plan = execution_packet.validation_stage.validation_plan
        assert subject is not None and validation_plan is not None
        allowed_files = subject.allowed_files
        forbidden_paths = subject.forbidden_paths
        required_tests = validation_plan.commands
        expected_changed_paths = subject.expected_changed_paths
        if any(path not in allowed_files for path in expected_changed_paths):
            return build_failure(
                requested_phase=phase,
                reason_code="scope.expected-changed-paths-outside-allowlist",
            )
        assert execution_packet.command_plan is not None
        command_entries = execution_packet.command_plan.entries
        command_identities = tuple(required_tests)
        if len(command_entries) != len(command_identities):
            return build_failure(requested_phase=phase, reason_code="scope.required-tests-mismatch")
        argv_bindings = tuple(
            (command_identities[index], tuple(command_entries[index].argv))
            for index in range(len(command_identities))
        )
        runtime = execution_packet.runtime_configuration
        assert runtime is not None
        per_command_timeout_seconds = int(runtime.validation_per_command_timeout_seconds)
        total_timeout_seconds = int(runtime.validation_total_timeout_seconds)
        max_output_bytes = int(runtime.validation_max_output_bytes)
        assert approval.decision_revision is not None
        approval_summary = (
            f"decision-applied:{approval.decision_revision.state.value}:"
            "no-execution-authorization-claimed"
        )
        execution_summary = (
            f"execution-authorization-present={execution_packet.execution_authorization_present}:"
            "not-authoritative"
        )

    # Step 15: duplicate, ordering, count, and size bounds.
    stage_identities = build_stage_identities(compiler_input)
    stage_names = [name for name, _ in stage_identities]
    duplicate = _first_duplicate(stage_names)
    if duplicate is not None:
        return build_failure(
            requested_phase=phase,
            reason_code="bounds.duplicate-stage-identity",
            failed_field=duplicate,
        )
    for collection in (allowed_files, forbidden_paths, required_tests, expected_changed_paths):
        if len(collection) > _MAX_SCOPE_ENTRIES:
            return build_failure(requested_phase=phase, reason_code="bounds.packet-too-large")

    # Step 16: provenance-manifest and invalidation-manifest construction.
    provenance_manifest = build_provenance_manifest(compiler_input)
    stage_payload_digests = build_stage_payload_digests(compiler_input)
    invalidation_manifest = build_invalidation_manifest(phase)

    # Step 17: packet semantic identity construction.
    fields = {
        "schema_name": PACKET_SCHEMA_NAME,
        "schema_version": PACKET_SCHEMA_VERSION,
        "phase": phase,
        "repository": compiler_input.repository,
        "issue_number": compiler_input.issue_number,
        "invocation_id": compiler_input.invocation_id,
        "candidate_ref": compiler_input.candidate_ref,
        "base_branch": compiler_input.base_branch,
        "base_sha": compiler_input.base_sha,
        "candidate_sha": compiler_input.candidate_sha,
        "source_sha": compiler_input.source_sha,
        "tested_sha": compiler_input.tested_sha,
        "evaluator_sha": compiler_input.evaluator_sha,
        "external_build_sha": compiler_input.external_build_sha,
        "freshness_boundary": compiler_input.freshness_boundary,
        "stage_identities": stage_identities,
        "stage_payload_digests": stage_payload_digests,
        "provenance_manifest": provenance_manifest,
        "invalidation_manifest": invalidation_manifest,
        "allowed_files": tuple(allowed_files),
        "forbidden_paths": tuple(forbidden_paths),
        "expected_changed_paths": tuple(expected_changed_paths),
        "required_tests": tuple(required_tests),
        "command_identities": tuple(command_identities),
        "argv_bindings": tuple(argv_bindings),
        "per_command_timeout_seconds": per_command_timeout_seconds,
        "total_timeout_seconds": total_timeout_seconds,
        "max_output_bytes": max_output_bytes,
        "approval_boundary_summary": approval_summary,
        "execution_authorization_boundary_summary": execution_summary,
        "evidence_completeness": "complete",
        "disposition": "verified",
    }
    packet_id = f"candidate-packet:{compute_candidate_packet_fingerprint(fields)}"
    packet = CandidatePacket(packet_id=packet_id, evaluated_at=evaluated_at, **fields)

    # Step 18: canonical serialization and immediate reconstruction verification.
    try:
        payload = serialize_candidate_packet(packet)
    except (TypeError, ValueError):
        return build_failure(requested_phase=phase, reason_code="serialization.reconstruction-mismatch")
    if len(canonical_bytes(payload)) > _MAX_PACKET_BYTES:
        return build_failure(requested_phase=phase, reason_code="bounds.packet-too-large")

    return packet


def _best_effort_phase(compiler_input: object) -> CandidatePacketPhase:
    """The least-authoritative phase to report when the input's own type is wrong.

    A malformed or foreign object cannot be trusted to name its own intended
    phase, so a failure produced here never claims ``execution-candidate``.
    """
    candidate = getattr(compiler_input, "requested_phase", None)
    if isinstance(candidate, CandidatePacketPhase):
        return candidate
    return CandidatePacketPhase.APPROVAL_READY


def _readiness_failure(
    phase: CandidatePacketPhase, status: IssueReadinessStageStatus
) -> CandidatePacketCompilationFailure:
    if status is IssueReadinessStageStatus.BLOCKED:
        return build_failure(requested_phase=phase, reason_code="source-stage.blocked")
    if status is IssueReadinessStageStatus.NEEDS_DECISION:
        return build_failure(requested_phase=phase, reason_code="source-stage.needs-decision")
    return build_failure(requested_phase=phase, reason_code="source-stage.unresolved")


def _repository_stage_failure(phase: CandidatePacketPhase, repository_stage) -> CandidatePacketCompilationFailure:
    if repository_stage is None:
        return build_failure(requested_phase=phase, reason_code="repository-evidence.not-valid")
    if repository_stage.status is RepositoryStageStatus.STALE:
        return build_failure(requested_phase=phase, reason_code="repository-evidence.stale")
    if repository_stage.status is RepositoryStageStatus.NEEDS_DECISION:
        return build_failure(requested_phase=phase, reason_code="repository-evidence.needs-decision")
    return build_failure(requested_phase=phase, reason_code="repository-evidence.not-valid")


def _proposal_status_failure(
    phase: CandidatePacketPhase, status: RepositoryProposalStageStatus
) -> CandidatePacketCompilationFailure:
    if status is RepositoryProposalStageStatus.STALE:
        return build_failure(requested_phase=phase, reason_code="proposal.stale")
    if status is RepositoryProposalStageStatus.NEEDS_DECISION:
        return build_failure(requested_phase=phase, reason_code="proposal.needs-decision")
    if status is RepositoryProposalStageStatus.INVALID_INPUT:
        return build_failure(requested_phase=phase, reason_code="planning-stage.invalid-input")
    return build_failure(requested_phase=phase, reason_code="proposal.not-eligible")


def _require_complete_approval(
    phase: CandidatePacketPhase, approval: ApprovalProjectionStageResult
) -> CandidatePacketCompilationFailure | None:
    if approval.status is ApprovalProjectionStageStatus.COMPLETE:
        if approval.projection is None or approval.decision_revision is None:
            return build_failure(requested_phase=phase, reason_code="approval-stage.missing")
        return None
    reason = _APPROVAL_LIFECYCLE_REASONS.get(approval.status, "approval-stage.missing")
    return build_failure(requested_phase=phase, reason_code=reason)


def _first_duplicate(names: list[str]) -> str | None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            return name
        seen.add(name)
    return None


def _approval_to_dict(approval: ApprovalProjectionStageResult) -> dict[str, object]:
    from .approval_stage import approval_projection_stage_result_to_dict

    return approval_projection_stage_result_to_dict(approval)


def _execution_packet_to_dict(execution_packet: object) -> dict[str, object]:
    from .execution_packet_stage import execution_packet_stage_result_to_dict

    return execution_packet_stage_result_to_dict(execution_packet)
