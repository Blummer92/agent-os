"""Trusted-host caller for one authorized validation with #1830 source capture (#1929).

The caller consumes the existing content-addressed AuthorizedValidationLifecycleRequest
v1.1 envelope, reacquires current issue/repository/authorization truth through the
existing owners, rebuilds SingleIssuePilotInput in memory, and delegates exactly once
to #1830. It creates no new transport, authority, Scheduler, lease, store, retry, or
publication path.
"""
from __future__ import annotations

from dataclasses import dataclass

from scripts.agent_os_candidate_packet.cli import prepare_candidate_packet
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase
from scripts.agent_os_candidate_packet_live_input.issue_reader import LiveIssueReader
from scripts.agent_os_candidate_packet_live_input.repository_reader import LiveRepositoryEvidenceReader
from scripts.agent_os_remote_validation import serialize_validation_evidence_bundle
from workflow_scheduler.execution.single_issue_pilot import CancellationProbe

from .authorized_validation import (
    AUTHORIZED_VALIDATION_PERMITTED_OPERATION,
    AUTHORIZED_VALIDATION_VNEXT_SCHEMA_VERSION,
    pilot_reconstruction_evidence,
    reconstruct_authorized_validation_lifecycle_request,
)
from .execution_authorization_source import (
    ExecutionAuthorizationSourceStatus,
    reacquire_execution_authorization,
)
from .first_publication_source_capture import run_production_authorized_validation_with_source_capture
from .host_github_read_transport import build_host_github_read_transport_from_environment
from .models import parse_canonical_utc
from .production_handoff_publication import (
    _pilot_input,
    _rebuild_advisory,
    _rebuild_approval,
    _repository_observation,
)
from .production_host_bootstrap import (
    ProductionHostConfiguration,
    build_subprocess_verifier_runner,
    canonical_evaluated_at,
    load_production_host_configuration,
)


class ProductionAuthorizedValidationCallerError(RuntimeError):
    """Current pre-runtime evidence cannot safely enter #1830."""


@dataclass(frozen=True, slots=True, kw_only=True)
class _PreRuntimeCapsuleView:
    """In-memory compatibility view for existing pure reconstruction helpers."""

    validation_plan_id: str
    validation_bundle_id: str
    advisory_result_id: str
    advisory_render_id: str
    approval_record: object
    invalidation_events: tuple[str, ...]
    candidate_branch: str
    workspace_request_id: str


def run_production_authorized_validation(
    payload: object,
    *,
    cancelled: CancellationProbe,
    configuration: ProductionHostConfiguration | None = None,
    evaluated_at: str | None = None,
    transport: object | None = None,
    run_verifier=None,
    compatibility_decision: object | None = None,
    git_runner: object | None = None,
    process_cancelled: object | None = None,
    changed_paths_inspector: object | None = None,
):
    """Reacquire current truth, rebuild the pilot in memory, and call #1830 once."""
    try:
        request = reconstruct_authorized_validation_lifecycle_request(payload)
        if request.schema_version != AUTHORIZED_VALIDATION_VNEXT_SCHEMA_VERSION:
            raise ProductionAuthorizedValidationCallerError("authorized-validation-v1.1-required")
        bundle, invalidation_events = pilot_reconstruction_evidence(request)
        config = configuration or load_production_host_configuration()
        if type(config) is not ProductionHostConfiguration:
            raise ProductionAuthorizedValidationCallerError("host-configuration-malformed")
        now = evaluated_at or canonical_evaluated_at()
        parse_canonical_utc(now)
        github = transport or build_host_github_read_transport_from_environment()
        verifier = run_verifier or build_subprocess_verifier_runner()

        packet = request.candidate_packet
        runtime = request.execution_packet_stage.runtime_configuration
        if runtime is None or runtime.required_environment_spec is None:
            raise ProductionAuthorizedValidationCallerError("runtime-configuration-incomplete")
        approval = request.approval_stage.decision_revision
        if approval is None:
            raise ProductionAuthorizedValidationCallerError("approval-record-missing")

        view = _PreRuntimeCapsuleView(
            validation_plan_id=runtime.validation_plan_id,
            validation_bundle_id=runtime.validation_bundle_id,
            advisory_result_id=runtime.advisory_result_id,
            advisory_render_id=runtime.advisory_render_id,
            approval_record=approval,
            invalidation_events=invalidation_events,
            candidate_branch=runtime.branch,
            workspace_request_id=runtime.workspace_request_id,
        )
        bundle_payload = serialize_validation_evidence_bundle(bundle)
        advisory = _rebuild_advisory(packet, view, bundle_payload)
        repository_reader = LiveRepositoryEvidenceReader(
            repository=packet.repository,
            issue_number=packet.issue_number,
            required_environment_spec=runtime.required_environment_spec,
            validation_result=advisory,
            evaluated_at=now,
            expected_validation_plan_id=runtime.validation_plan_id,
        )
        observation = _repository_observation(
            config=config,
            packet=packet,
            capsule=view,
            payload=bundle_payload,
            evaluated_at=now,
            run_verifier=verifier,
        )
        prepared = prepare_candidate_packet(
            repository=packet.repository,
            issue_number=packet.issue_number,
            issue_reader=LiveIssueReader(github),
            repository_reader=repository_reader,
            observed_at=now,
            base_branch=packet.base_branch,
            evaluated_repository_sha=observation.base_sha,
            invocation_id=packet.invocation_id,
            evaluator_sha=packet.evaluator_sha,
            repository_observation=observation,
            requested_phase=CandidatePacketPhase.APPROVAL_READY,
            external_build_sha=packet.external_build_sha,
            compiler_evaluated_at=now,
        )
        approval_stage, proposal, issueplan, repository_state = _rebuild_approval(
            prepared, packet, view, now
        )
        if approval_stage.projection is None:
            raise ProductionAuthorizedValidationCallerError("projection-incomplete")
        original_projection = request.approval_stage.projection
        if original_projection is None or approval_stage.projection.projection_id != original_projection.projection_id:
            raise ProductionAuthorizedValidationCallerError("projection-binding-mismatch")

        authorization = reacquire_execution_authorization(
            transport=github,
            repository=packet.repository,
            issue_number=packet.issue_number,
            expected_candidate_packet_id=packet.packet_id,
            expected_invocation_id=packet.invocation_id,
            expected_operation=AUTHORIZED_VALIDATION_PERMITTED_OPERATION,
            expected_request_fingerprint=request.execution_authorization.request_fingerprint,
            expected_command_plan_id=request.execution_authorization.command_plan_id,
            expected_sha=packet.candidate_sha,
            evaluated_at=now,
            expected_authorization_id=request.execution_authorization.authorization_id,
        )
        if (
            authorization.status is not ExecutionAuthorizationSourceStatus.CURRENT
            or authorization.evidence != request.execution_authorization
            or authorization.authorizer_id != request.authorizer_id
            or authorization.authorized_candidate_packet_id != packet.packet_id
            or authorization.authorized_invocation_id != packet.invocation_id
            or authorization.authorized_operation != AUTHORIZED_VALIDATION_PERMITTED_OPERATION
        ):
            raise ProductionAuthorizedValidationCallerError("execution-authorization-not-current")

        pilot = _pilot_input(
            packet=packet,
            capsule=view,
            payload=bundle_payload,
            issueplan=issueplan,
            proposal=proposal,
            repository_state=repository_state,
            approval_stage=approval_stage,
            runtime_configuration=runtime,
            evaluated_at=now,
        )
        runtime.verify(pilot)
        return run_production_authorized_validation_with_source_capture(
            admission_request=request,
            evaluated_at=now,
            pilot_input=pilot,
            cancelled=cancelled,
            compatibility_decision=compatibility_decision,
            git_runner=git_runner,
            process_cancelled=process_cancelled,
            changed_paths_inspector=changed_paths_inspector,
        )
    except ProductionAuthorizedValidationCallerError:
        raise
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except (TypeError, ValueError, LookupError, OSError, RuntimeError) as exc:
        raise ProductionAuthorizedValidationCallerError("production-authorized-validation-failed-closed") from exc
