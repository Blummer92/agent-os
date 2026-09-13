"""Trusted-host fixed first-run validation composition for #1972.

The transport supplies exactly one immutable selector — the 40-hex candidate SHA
from ``/agent-os validate-first-run <candidate-sha>`` — plus the repository and
issue identity taken from the trusted GitHub event envelope. Nothing else crosses
the boundary: no argv, shell text, approval, authority flag, runner identity,
timestamp, store path, credential, or runtime configuration.

This module is composition only. It owns no validation, approval, currentness,
custody, evidence, persistence, Scheduler, lease, transport, or retry system; it
calls the existing owners once each, in order, and fails closed between them:

``current candidate/provenance -> current approval -> #1985 fresh pre-validation
-> exact fixed validation-profile match -> existing GCE dev-validation runner ->
observed validation evidence -> existing PR-less evidence bundle -> bound
RequiredEnvironmentSpec -> non-authorizing execution-packet identity -> current
execution-authorization reacquisition -> #1970 request -> #1929/#1830 bounded
source/evidence capsule``.

The two surface-bound steps are named seams whose production bindings are the
existing owners: ``run_fixed_validation`` is the existing fixed GCE
dev-validation runner and ``run_authorized_validation`` is the existing #1929
production authorized-validation caller. Supplying a seam selects an existing
owner; it never creates a command surface or widens authority.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from typing import Callable, Literal

from scripts.agent_os_candidate_packet.approval_stage import ApprovalDecision
from scripts.agent_os_candidate_packet.execution_packet_stage import (
    CandidateRuntimeInputs,
    ExecutionPacketDisposition,
    prepare_execution_packet,
)
from scripts.agent_os_candidate_packet.models import CandidatePacket, CandidatePacketPhase
from scripts.agent_os_candidate_packet.pre_validation_stage import PreValidationCandidateInputs
from scripts.agent_os_execution_capabilities import (
    GovernedProjectionEvidenceResult,
    RepositoryEvidenceType,
    RepositoryIdentity,
)
from scripts.agent_os_remote_validation import ValidationEvidenceBundle
from scripts.agent_os_remote_validation.pre_pr_evidence_bundle import (
    build_pre_pr_validation_evidence_bundle,
)
from workflow_scheduler.governance.dev_validation import (
    DevValidationRequest,
    build_dev_validation_request,
)
from workflow_scheduler.governance.first_run_validation_observation import (
    observed_command_from_fixed_gce_evidence,
    resolve_fixed_first_run_validation_id,
)
from workflow_scheduler.governance.pre_pr_dev_validation_evidence import (
    supplied_command_results_from_dev_validation,
)

from .authorized_validation import (
    AUTHORIZED_VALIDATION_PERMITTED_OPERATION,
    AuthorizedValidationLifecyclePolicy,
    serialize_authorized_validation_lifecycle_request,
)
from .candidate_approval_provenance import CandidateApprovalProvenanceEvidence
from .candidate_environment_provenance import build_candidate_environment_provenance
from .execution_authorization_source import (
    ExecutionAuthorizationSourceStatus,
    ExecutionAuthorizationSourceTransport,
    reacquire_execution_authorization,
)
from .first_run_invalidation_projection import build_first_run_authorized_validation_request
from .fresh_pre_validation import prepare_fresh_pre_validation
from .validation_lifecycle_evidence import (
    ValidationLifecycleResult,
    ValidationLifecycleTerminalStatus,
)

FIRST_RUN_VALIDATION_SCHEMA_VERSION = "1.0"
CANONICAL_REPOSITORY = "Blummer92/agent-os"
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)

FixedValidationRunner = Callable[[DevValidationRequest], object]
AuthorizedValidationRunner = Callable[[dict], object]


class FirstRunValidationCompositionError(RuntimeError):
    """Current first-run evidence cannot safely reach authorized validation."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FirstRunValidationIdentity:
    """The only caller-derived first-run facts, all from trusted GitHub truth."""

    repository: str
    issue_number: int
    candidate_sha: str

    def __post_init__(self) -> None:
        if self.repository != CANONICAL_REPOSITORY:
            raise ValueError("non-canonical first-run repository rejected")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise ValueError("first-run issue number must be a positive exact integer")
        if type(self.candidate_sha) is not str or _SHA40_RE.fullmatch(self.candidate_sha) is None:
            raise ValueError("candidate_sha must be a full lowercase commit SHA")


@dataclass(frozen=True, slots=True, kw_only=True)
class FirstRunHostState:
    """Current truth the trusted host reacquired for exactly this candidate.

    Every field is host-observed. None of it is transport-supplied, and none of
    it carries or implies execution, approval, merge, or publication authority.
    """

    provenance: CandidateApprovalProvenanceEvidence
    approval_decision: ApprovalDecision
    candidate_inputs: PreValidationCandidateInputs
    execution_candidate_packet: CandidatePacket
    candidate_runtime_inputs: CandidateRuntimeInputs
    governed_projection: GovernedProjectionEvidenceResult
    repository_identity: RepositoryIdentity
    repository_evidence_type: RepositoryEvidenceType
    repository_state_evidence_id: str
    proposal_id: str
    repository_root: str
    lifecycle_policy: AuthorizedValidationLifecyclePolicy
    authorization_transport: ExecutionAuthorizationSourceTransport
    evaluated_at: str
    projected_at: str


@dataclass(frozen=True, slots=True, kw_only=True)
class FirstRunValidationResult:
    """Bounded non-authorizing evidence for one composed first-run validation."""

    schema_version: Literal["1.0"]
    repository: str
    issue_number: int
    candidate_sha: str
    validation_id: str
    profile_id: str
    dev_validation_request_id: str
    validation_plan_id: str
    validation_bundle_id: str
    environment_provenance_id: str
    execution_packet_request_fingerprint: str
    command_plan_id: str
    authorization_id: str
    authorized_validation_request_id: str
    source_capture_id: str
    pull_request: None = None
    execution_authorized: Literal[False] = field(default=False, init=False)
    scheduler_invoked: Literal[False] = field(default=False, init=False)
    publication_invoked: Literal[False] = field(default=False, init=False)
    execution_lease_acquired: Literal[False] = field(default=False, init=False)
    resume_invoked: Literal[False] = field(default=False, init=False)
    retry_attempted: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "candidate_sha": self.candidate_sha,
            "validation_id": self.validation_id,
            "profile_id": self.profile_id,
            "dev_validation_request_id": self.dev_validation_request_id,
            "validation_plan_id": self.validation_plan_id,
            "validation_bundle_id": self.validation_bundle_id,
            "environment_provenance_id": self.environment_provenance_id,
            "execution_packet_request_fingerprint": self.execution_packet_request_fingerprint,
            "command_plan_id": self.command_plan_id,
            "authorization_id": self.authorization_id,
            "authorized_validation_request_id": self.authorized_validation_request_id,
            "source_capture_id": self.source_capture_id,
            "pull_request": None,
            "execution_authorized": False,
            "scheduler_invoked": False,
            "publication_invoked": False,
            "execution_lease_acquired": False,
            "resume_invoked": False,
            "retry_attempted": False,
            "merge_authorized": False,
            "github_writes_authorized": False,
        }


def _bind_identity(identity: FirstRunValidationIdentity, host_state: FirstRunHostState) -> None:
    """Prove the host reacquired state for exactly this trusted candidate."""
    inputs = host_state.candidate_inputs
    packet = host_state.execution_candidate_packet
    runtime_inputs = host_state.candidate_runtime_inputs
    identity_repository = (
        f"{host_state.repository_identity.owner}/{host_state.repository_identity.repository}"
    )
    if identity_repository.casefold() != identity.repository.casefold():
        raise FirstRunValidationCompositionError("first-run-repository-binding-mismatch")
    if packet.phase is not CandidatePacketPhase.EXECUTION_CANDIDATE:
        raise FirstRunValidationCompositionError("first-run-candidate-packet-phase-invalid")
    if (
        inputs.candidate_sha != identity.candidate_sha
        or runtime_inputs.candidate_sha != identity.candidate_sha
        or packet.candidate_sha != identity.candidate_sha
    ):
        raise FirstRunValidationCompositionError("first-run-candidate-sha-binding-mismatch")
    if (
        inputs.issue_number != identity.issue_number
        or runtime_inputs.issue_number != identity.issue_number
        or packet.issue_number != identity.issue_number
    ):
        raise FirstRunValidationCompositionError("first-run-issue-binding-mismatch")
    if inputs.candidate_branch != runtime_inputs.candidate_branch:
        raise FirstRunValidationCompositionError("first-run-candidate-branch-binding-mismatch")


def _consume_authorized_validation_capture(capture: object, *, expected_request_id: str) -> str:
    """Validate the existing #1929/#1830 ``(result, source-capture id)`` pair.

    A non-success terminal result carries ``None`` and performs zero capture
    writes, so first-run reports it as a failure rather than as capture evidence.
    """
    if type(capture) is not tuple or len(capture) != 2:
        raise FirstRunValidationCompositionError("first-run-capture-result-malformed")
    lifecycle_result, source_capture_id = capture
    if type(lifecycle_result) is not ValidationLifecycleResult:
        raise FirstRunValidationCompositionError("first-run-capture-result-malformed")
    if lifecycle_result.request_id != expected_request_id:
        raise FirstRunValidationCompositionError("first-run-capture-request-binding-mismatch")
    if lifecycle_result.status is not ValidationLifecycleTerminalStatus.SUCCEEDED:
        raise FirstRunValidationCompositionError(
            "first-run-validation-not-succeeded:" + lifecycle_result.status.value
        )
    if lifecycle_result.execution_authorized is not False:
        raise FirstRunValidationCompositionError("first-run-capture-crossed-boundary")
    if type(source_capture_id) is not str or not source_capture_id:
        raise FirstRunValidationCompositionError("first-run-source-capture-identity-missing")
    return source_capture_id


def compose_first_run_validation(
    identity: FirstRunValidationIdentity,
    host_state: FirstRunHostState,
    *,
    run_fixed_validation: FixedValidationRunner,
    run_authorized_validation: AuthorizedValidationRunner,
) -> FirstRunValidationResult:
    """Compose the existing first-run owners once each and stop at #1830 capture."""
    if type(identity) is not FirstRunValidationIdentity:
        raise TypeError("identity must be an exact FirstRunValidationIdentity")
    if type(host_state) is not FirstRunHostState:
        raise TypeError("host_state must be an exact FirstRunHostState")
    if not callable(run_fixed_validation) or not callable(run_authorized_validation):
        raise TypeError("validation seams must be callable existing owners")
    try:
        _bind_identity(identity, host_state)

        # #1985 fresh pre-validation over current candidate provenance/approval.
        fresh = prepare_fresh_pre_validation(
            provenance=host_state.provenance,
            approval_decision=host_state.approval_decision,
            candidate_inputs=host_state.candidate_inputs,
            evaluated_at=host_state.evaluated_at,
            projected_at=host_state.projected_at,
        )
        plan = fresh.validation_stage_result.validation_plan
        if plan is None:
            raise FirstRunValidationCompositionError("first-run-validation-plan-missing")

        # The canonical plan may execute only when it is exactly one existing
        # fixed validation profile the current GCE runner already owns.
        validation_id = resolve_fixed_first_run_validation_id(plan)
        request = build_dev_validation_request(
            repository=identity.repository,
            issue_number=identity.issue_number,
            branch=host_state.candidate_inputs.candidate_branch,
            source_sha=identity.candidate_sha,
            validation_id=validation_id,
        )

        # Existing fixed GCE dev-validation runner; no argv is constructed here.
        evidence = run_fixed_validation(request)
        observed = observed_command_from_fixed_gce_evidence(
            evidence,
            expected_repository=identity.repository,
            expected_issue_number=identity.issue_number,
            expected_sha=identity.candidate_sha,
            expected_profile_id=request.profile_id,
            expected_request_id=request.request_id,
        )
        command_results = supplied_command_results_from_dev_validation(plan, (observed,))

        # Existing PR-less bundle: canonical, with no fabricated pull request.
        bundle = build_pre_pr_validation_evidence_bundle(
            host_state.governed_projection,
            plan,
            command_results,
            expected_repository=host_state.repository_identity,
            expected_repository_evidence_type=host_state.repository_evidence_type,
            expected_proposal_id=host_state.proposal_id,
            expected_repository_state_evidence_id=host_state.repository_state_evidence_id,
            runner_id=observed.runner_id,
            started_at=observed.started_at,
            completed_at=observed.completed_at,
        )
        if type(bundle) is not ValidationEvidenceBundle or bundle.pull_request is not None:
            raise FirstRunValidationCompositionError("first-run-bundle-must-remain-pr-less")

        # Content-addressed initial RequiredEnvironmentSpec bound to this candidate.
        environment = build_candidate_environment_provenance(
            candidate_provenance_id=host_state.provenance.evidence_id,
            candidate_sha=identity.candidate_sha,
            repository_root=host_state.repository_root,
            required_tests=tuple(host_state.candidate_inputs.required_tests),
        )
        if (
            host_state.candidate_runtime_inputs.required_environment_spec
            != environment.required_environment_spec
        ):
            raise FirstRunValidationCompositionError("first-run-environment-spec-binding-mismatch")

        # Non-authorizing execution-packet identity.
        packet_stage = prepare_execution_packet(
            fresh.approval_stage_result, host_state.candidate_runtime_inputs
        )
        if (
            packet_stage.disposition is not ExecutionPacketDisposition.GO
            or not packet_stage.packet_complete
            or packet_stage.request_fingerprint is None
            or packet_stage.command_plan_id is None
        ):
            raise FirstRunValidationCompositionError(
                "first-run-execution-packet-not-go:" + ",".join(packet_stage.reason_codes)
            )

        # Current execution authorization, reacquired server-side (#1929).
        authorization = reacquire_execution_authorization(
            transport=host_state.authorization_transport,
            repository=identity.repository,
            issue_number=identity.issue_number,
            expected_candidate_packet_id=host_state.execution_candidate_packet.packet_id,
            expected_invocation_id=host_state.execution_candidate_packet.invocation_id,
            expected_operation=AUTHORIZED_VALIDATION_PERMITTED_OPERATION,
            expected_request_fingerprint=packet_stage.request_fingerprint,
            expected_command_plan_id=packet_stage.command_plan_id,
            expected_sha=identity.candidate_sha,
            evaluated_at=host_state.evaluated_at,
        )
        if (
            authorization.status is not ExecutionAuthorizationSourceStatus.CURRENT
            or authorization.evidence is None
            or authorization.authorizer_id is None
            or authorization.authorized_candidate_packet_id
            != host_state.execution_candidate_packet.packet_id
            or authorization.authorized_invocation_id
            != host_state.execution_candidate_packet.invocation_id
            or authorization.authorized_operation != AUTHORIZED_VALIDATION_PERMITTED_OPERATION
        ):
            raise FirstRunValidationCompositionError("first-run-execution-authorization-not-current")

        # #1970 request: residual invalidation is projected from the bundle itself.
        lifecycle_request = build_first_run_authorized_validation_request(
            validation_evidence_bundle=bundle,
            candidate_packet=host_state.execution_candidate_packet,
            approval_stage=fresh.approval_stage_result,
            execution_packet_stage=packet_stage,
            execution_authorization=authorization.evidence,
            authorizer_id=authorization.authorizer_id,
            authorized_candidate_packet_id=authorization.authorized_candidate_packet_id,
            authorized_invocation_id=authorization.authorized_invocation_id,
            lifecycle_policy=host_state.lifecycle_policy,
        )

        # #1929/#1830 bounded source/evidence capsule. The existing owner returns
        # the canonical (lifecycle result, source-capture id) pair; a non-success
        # terminal result carries None and performs zero capture writes.
        capture = run_authorized_validation(
            serialize_authorized_validation_lifecycle_request(lifecycle_request)
        )
        source_capture_id = _consume_authorized_validation_capture(
            capture, expected_request_id=lifecycle_request.request_id
        )

        return FirstRunValidationResult(
            schema_version=FIRST_RUN_VALIDATION_SCHEMA_VERSION,
            repository=identity.repository,
            issue_number=identity.issue_number,
            candidate_sha=identity.candidate_sha,
            validation_id=request.validation_id,
            profile_id=request.profile_id,
            dev_validation_request_id=request.request_id,
            validation_plan_id=bundle.plan_id,
            validation_bundle_id=bundle.bundle_id,
            environment_provenance_id=environment.evidence_id,
            execution_packet_request_fingerprint=packet_stage.request_fingerprint,
            command_plan_id=packet_stage.command_plan_id,
            authorization_id=authorization.evidence.authorization_id,
            authorized_validation_request_id=lifecycle_request.request_id,
            source_capture_id=source_capture_id,
        )
    except FirstRunValidationCompositionError:
        raise
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except (TypeError, ValueError, LookupError, OSError, RuntimeError) as exc:
        raise FirstRunValidationCompositionError("first-run-validation-failed-closed") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", required=True, type=int)
    parser.add_argument("--candidate-sha", required=True)
    args = parser.parse_args(argv)
    identity = FirstRunValidationIdentity(
        repository=args.repository,
        issue_number=args.issue_number,
        candidate_sha=args.candidate_sha,
    )
    # Host-state acquisition and the production seam bindings are owned by the
    # separately authorized host-runtime activation described in
    # 08_Tooling/agent-os-execution-service/docs/FIRST_RUN_VALIDATION_START.md.
    # This repository change deliberately stops at the bounded composition
    # contract rather than deploying the host or invoking live GCE/IAP.
    raise FirstRunValidationCompositionError(
        "first-run-host-state-activation-required:" + identity.candidate_sha
    )


__all__ = [
    "FIRST_RUN_VALIDATION_SCHEMA_VERSION",
    "FirstRunHostState",
    "FirstRunValidationCompositionError",
    "FirstRunValidationIdentity",
    "FirstRunValidationResult",
    "compose_first_run_validation",
]

if __name__ == "__main__":
    raise SystemExit(main())
