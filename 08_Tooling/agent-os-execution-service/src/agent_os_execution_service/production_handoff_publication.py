"""Bounded production-host activation for first governed handoff publication (#1411).

The module composes existing canonical evidence owners only. Caller input is three
content-addressed identities; host paths/configuration come only from the existing
production-host environment contract. The #1412 capsule remains non-authorizing,
execution authorization is reacquired independently, and the final publication
boundary is #1409 ``publish_authorized_validation_handoff``. No Scheduler, lease,
retry, provider fallback, arbitrary command, or caller-selected store path exists.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from scripts.agent_os_candidate_packet.approval_stage import (
    ApprovalProjectionStageResult,
    ApprovalProjectionStageStatus,
)
from scripts.agent_os_candidate_packet.cli import prepare_candidate_packet
from scripts.agent_os_candidate_packet.execution_packet_stage import (
    ExecutionPacketDisposition,
    prepare_execution_packet,
)
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase
from scripts.agent_os_candidate_packet.validation_stage import CandidateRuntimeInputs
from scripts.agent_os_candidate_packet_live_input.issue_reader import LiveIssueReader
from scripts.agent_os_candidate_packet_live_input.repository_reader import (
    LiveRepositoryEvidenceReader,
)
from scripts.agent_os_execution_capabilities.approved_projection import (
    GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION,
    GovernedProjectionEvidenceResult,
    consume_approved_projection_evidence,
)
from scripts.agent_os_execution_checkpoint.dependency_readiness_store import (
    load_dependency_readiness,
)
from scripts.agent_os_execution_checkpoint.resume_plan_store import load_resume_plan
from scripts.agent_os_execution_checkpoint.store import load_checkpoint_by_id
from scripts.agent_os_issue_acceptance.approval_records import (
    evaluate_approval_applicability,
)
from scripts.agent_os_issue_acceptance.approved_execution_projection import (
    build_approved_execution_projection,
)
from scripts.agent_os_remote_validation import (
    build_validation_evidence_bundle,
    evaluate_advisory_pre_pr_evidence,
    render_advisory_evidence,
    validation_plan_id,
)
from workflow_scheduler.execution.single_issue_pilot import SingleIssuePilotInput

from .authorized_validation import (
    AUTHORIZED_VALIDATION_PERMITTED_OPERATION,
    AuthorizedValidationLifecyclePolicy,
    build_authorized_validation_lifecycle_request,
)
from .authorized_validation_entrypoint import publish_authorized_validation_handoff
from .execution_authorization_source import (
    ExecutionAuthorizationSourceStatus,
    reacquire_execution_authorization,
)
from .executor_routing import ExecutorHandoff, ExecutorRoute
from .host_github_read_transport import build_host_github_read_transport_from_environment
from .pre_publication_evidence_store import load_pre_publication_evidence
from .production_governed_resume_factory import (
    _repository_evidence_type,
    _repository_identity,
    _required_text,
    _supplied_command_results,
    _validation_plan,
)
from .production_host_bootstrap import (
    PRODUCER_ADAPTER_VERSION,
    ProductionHostConfiguration,
    VerifierInvocation,
    build_subprocess_verifier_runner,
    canonical_evaluated_at,
    load_production_host_configuration,
)
from .production_host_repository_observation import (
    build_repository_observation_from_verifier_stdout,
)
from .route_decision_store import load_route_decision
from .models import parse_canonical_utc

PRE_PR_DEVELOPER_LOOP_OPERATION = "pre-pr-developer-loop"
REQUIRED_RETURN_EVIDENCE = ("exact-head-sha", "test-results")
STOP_CONDITIONS = ("excluded-surface-entered", "scope-expanded")
PRODUCER_ADAPTER = "agent-os-governed-handoff-publication"

_CAPSULE_ID_RE = re.compile(r"^pre-publication-evidence:[0-9a-f]{64}$", re.ASCII)
_ROUTE_ID_RE = re.compile(r"^executor-route-decision:[0-9a-f]{64}$", re.ASCII)
_DEPENDENCY_ID_RE = re.compile(r"^dependency-readiness:[0-9a-f]{64}$", re.ASCII)


class ProductionHandoffPublicationError(RuntimeError):
    """Finite fail-closed evidence that production publication is not admissible."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductionHandoffPublicationIdentity:
    """The only caller-controlled input: three immutable evidence identities."""

    capsule_id: str
    route_decision_id: str
    dependency_readiness_id: str

    def __post_init__(self) -> None:
        for value, pattern, name in (
            (self.capsule_id, _CAPSULE_ID_RE, "capsule_id"),
            (self.route_decision_id, _ROUTE_ID_RE, "route_decision_id"),
            (self.dependency_readiness_id, _DEPENDENCY_ID_RE, "dependency_readiness_id"),
        ):
            if type(value) is not str or not pattern.fullmatch(value):
                raise ValueError(f"{name} is malformed")


def publish_production_handoff(
    identity: ProductionHandoffPublicationIdentity,
    *,
    configuration: ProductionHostConfiguration | None = None,
    evaluated_at: str | None = None,
    transport: object | None = None,
    run_verifier=None,
) -> ExecutorHandoff:
    """Reacquire current first-publication evidence and delegate exactly once to #1409."""
    if type(identity) is not ProductionHandoffPublicationIdentity:
        raise TypeError("identity must be an exact ProductionHandoffPublicationIdentity")
    try:
        config = configuration or load_production_host_configuration()
        if type(config) is not ProductionHostConfiguration:
            raise ProductionHandoffPublicationError("host-configuration-malformed")
        now = evaluated_at or canonical_evaluated_at()
        parse_canonical_utc(now)
        github = transport or build_host_github_read_transport_from_environment()
        verifier = run_verifier or build_subprocess_verifier_runner()

        capsule = load_pre_publication_evidence(
            config.checkpoint_store_root, identity.capsule_id
        )
        packet = capsule.candidate_packet
        route = load_route_decision(
            config.checkpoint_store_root, identity.route_decision_id
        )
        if (
            route.selected_route is not ExecutorRoute.CHATGPT_GOVERNED_RUNNER
            or route.requested_operation != PRE_PR_DEVELOPER_LOOP_OPERATION
            or route.repository.casefold() != packet.repository.casefold()
            or route.issue_or_handoff_identity != f"issue:{packet.issue_number}"
            or route.checkpoint_id_or_none != capsule.checkpoint_id
            or route.resume_plan_id_or_none is None
            or route.authorization_id_or_none is None
        ):
            raise ProductionHandoffPublicationError("route-binding-mismatch")

        checkpoint = load_checkpoint_by_id(
            config.checkpoint_store_root, packet.issue_number, capsule.checkpoint_id
        )
        resume_plan = load_resume_plan(
            config.checkpoint_store_root, route.resume_plan_id_or_none
        )
        dependency = load_dependency_readiness(
            config.checkpoint_store_root, identity.dependency_readiness_id
        )
        if (
            checkpoint.checkpoint_id != capsule.checkpoint_id
            or checkpoint.repository.casefold() != packet.repository.casefold()
            or checkpoint.issue_number != packet.issue_number
            or checkpoint.invocation_id != packet.invocation_id
            or checkpoint.source_sha != packet.candidate_sha
            or checkpoint.tested_sha != packet.tested_sha
            or dependency.required_environment_id
            != capsule.required_environment_spec.required_environment_id
            or dependency.source_sha != packet.candidate_sha
            or not dependency.is_current(now)
            or route.environment_health_evidence_id_or_none
            != dependency.environment_health_evidence_id
        ):
            raise ProductionHandoffPublicationError("durable-evidence-binding-mismatch")

        payload = _bundle_payload(capsule.validation_bundle_json)
        advisory = _rebuild_advisory(packet, capsule, payload)
        repository_reader = LiveRepositoryEvidenceReader(
            repository=packet.repository,
            issue_number=packet.issue_number,
            required_environment_spec=capsule.required_environment_spec,
            dependency_readiness=dependency,
            validation_result=advisory,
            evaluated_at=now,
            expected_validation_plan_id=capsule.validation_plan_id,
        )
        observation = _repository_observation(
            config=config,
            packet=packet,
            capsule=capsule,
            payload=payload,
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
            prepared, packet, capsule, now
        )

        preauth_inputs = _runtime_inputs(
            packet=packet,
            capsule=capsule,
            repository_state=repository_state,
            projection=approval_stage.projection,
            configuration=config,
            evaluated_at=now,
            authorization_present=False,
        )
        preauth_stage = prepare_execution_packet(approval_stage, preauth_inputs)
        if (
            not preauth_stage.packet_complete
            or preauth_stage.request_fingerprint is None
            or preauth_stage.command_plan_id is None
        ):
            raise ProductionHandoffPublicationError("execution-packet-incomplete")

        authorization = reacquire_execution_authorization(
            github,
            repository=packet.repository,
            issue_number=packet.issue_number,
            expected_candidate_packet_id=packet.packet_id,
            expected_invocation_id=packet.invocation_id,
            expected_operation=AUTHORIZED_VALIDATION_PERMITTED_OPERATION,
            expected_request_fingerprint=preauth_stage.request_fingerprint,
            expected_command_plan_id=preauth_stage.command_plan_id,
            expected_sha=packet.candidate_sha,
            evaluated_at=now,
            expected_authorization_id=route.authorization_id_or_none,
        )
        if (
            authorization.status is not ExecutionAuthorizationSourceStatus.CURRENT
            or authorization.evidence is None
            or authorization.authorizer_id is None
        ):
            raise ProductionHandoffPublicationError("execution-authorization-not-current")

        execution_stage = prepare_execution_packet(
            approval_stage, replace(preauth_inputs, execution_authorization_present=True)
        )
        if (
            execution_stage.disposition is not ExecutionPacketDisposition.GO
            or not execution_stage.packet_complete
            or execution_stage.request is None
            or execution_stage.runtime_configuration is None
            or execution_stage.request_fingerprint != route.execution_service_request_fingerprint_or_none
            or execution_stage.command_plan_id != route.validation_command_plan_id_or_none
        ):
            raise ProductionHandoffPublicationError("execution-route-binding-mismatch")

        lifecycle = build_authorized_validation_lifecycle_request(
            candidate_packet=packet,
            approval_stage=approval_stage,
            execution_packet_stage=execution_stage,
            execution_authorization=authorization.evidence,
            authorizer_id=authorization.authorizer_id,
            authorized_candidate_packet_id=packet.packet_id,
            authorized_invocation_id=packet.invocation_id,
            lifecycle_policy=AuthorizedValidationLifecyclePolicy(
                expected_changed_paths=packet.expected_changed_paths
            ),
        )
        pilot_input = _pilot_input(
            packet=packet,
            capsule=capsule,
            payload=payload,
            issueplan=issueplan,
            proposal=proposal,
            repository_state=repository_state,
            approval_stage=approval_stage,
            runtime_configuration=execution_stage.runtime_configuration,
            evaluated_at=now,
        )
        return publish_authorized_validation_handoff(
            config.checkpoint_store_root,
            admission_request=lifecycle,
            route_decision=route,
            checkpoint=checkpoint,
            resume_plan=resume_plan,
            dependency_readiness=dependency,
            evaluated_at=now,
            pilot_input=pilot_input,
            required_return_evidence=REQUIRED_RETURN_EVIDENCE,
            stop_conditions=STOP_CONDITIONS,
        )
    except ProductionHandoffPublicationError:
        raise
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except (TypeError, ValueError, LookupError, OSError, RuntimeError) as exc:
        raise ProductionHandoffPublicationError("production-publication-failed-closed") from exc


def _bundle_payload(serialized: str) -> dict[str, object]:
    try:
        payload = json.loads(serialized)
    except json.JSONDecodeError as exc:
        raise ProductionHandoffPublicationError("validation-bundle-malformed") from exc
    if type(payload) is not dict:
        raise ProductionHandoffPublicationError("validation-bundle-malformed")
    return payload


def _rebuild_advisory(packet, capsule, payload):
    plan = _validation_plan(payload)
    if validation_plan_id(plan) != capsule.validation_plan_id:
        raise ProductionHandoffPublicationError("validation-plan-identity-mismatch")
    identity = _repository_identity(payload.get("repository_identity"))
    repository = f"{identity.owner}/{identity.repository}"
    if (
        repository.casefold() != packet.repository.casefold()
        or payload.get("source_head_sha") != packet.candidate_sha
        or payload.get("invocation_id") != packet.invocation_id
    ):
        raise ProductionHandoffPublicationError("validation-bundle-subject-mismatch")
    evidence_type = _repository_evidence_type(payload.get("repository_evidence_type"))
    governed = GovernedProjectionEvidenceResult(
        status="accepted",
        schema_version=GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION,
        projection_id=_required_text(payload, "projection_id"),
        proposal_id=_required_text(payload, "proposal_id"),
        approval_id=_required_text(payload, "approval_id"),
        repository_identity=identity,
        base_branch=_required_text(payload, "base_branch"),
        base_sha=_required_text(payload, "base_sha"),
        head_sha=_required_text(payload, "source_head_sha"),
        evaluated_sha=_required_text(payload, "base_sha"),
        tested_sha=_required_text(payload, "tested_sha"),
        repository_evidence_type=evidence_type,
        repository_state_evidence_id=_required_text(payload, "repository_state_evidence_id"),
        implementation_contract_fingerprint=_required_text(
            payload, "implementation_contract_fingerprint"
        ),
        reason_codes=(),
        details=(),
    )
    command_results = _supplied_command_results(payload)
    expectations = _validation_expectations(
        payload, plan, identity, evidence_type, packet.invocation_id, capsule.validation_plan_id
    )
    advisory = evaluate_advisory_pre_pr_evidence(
        governed,
        plan,
        command_results,
        current_base_sha=payload.get("base_sha"),
        current_source_head_sha=packet.candidate_sha,
        expected_bundle_id=capsule.validation_bundle_id,
        **expectations,
    )
    if advisory.result_id != capsule.advisory_result_id:
        raise ProductionHandoffPublicationError("advisory-identity-mismatch")
    return advisory


def _repository_observation(*, config, packet, capsule, payload, evaluated_at, run_verifier):
    stdout = run_verifier(
        VerifierInvocation(
            repository_root=config.repository_root,
            branch=packet.base_branch,
            base_branch=packet.base_branch,
        )
    )
    if type(stdout) is not str:
        raise ProductionHandoffPublicationError("repository-verifier-malformed")
    identity = _repository_identity(payload.get("repository_identity"))
    if identity.host != config.repository_host:
        raise ProductionHandoffPublicationError("repository-host-mismatch")
    from scripts.agent_os_execution_capabilities.models import RepositoryEvidenceType

    return build_repository_observation_from_verifier_stdout(
        stdout,
        producer_adapter=PRODUCER_ADAPTER,
        producer_adapter_version=PRODUCER_ADAPTER_VERSION,
        correlation_id=packet.invocation_id,
        repository_identity=identity,
        contract_fingerprint=capsule.approval_record.binding.implementation_contract_fingerprint,
        observed_at=evaluated_at,
        freshness_boundary=packet.freshness_boundary,
        evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        requested_ref=packet.base_branch,
        requested_sha=packet.base_sha,
        tested_sha=None,
        pushed_sha=None,
        proposed_pr_sha=None,
        synthetic_merge_sha=None,
        external_build_sha=packet.external_build_sha,
    )


def _rebuild_approval(prepared, packet, capsule, evaluated_at):
    readiness = prepared.readiness_stage_result
    planning = prepared.planning_stage_result
    proposal_result = prepared.proposal_stage_result
    if (
        readiness is None
        or planning is None
        or proposal_result is None
        or readiness.snapshot is None
        or readiness.issueplan_current_state_evidence is None
        or planning.handoff is None
        or proposal_result.proposal is None
        or proposal_result.repository_state_evidence is None
    ):
        raise ProductionHandoffPublicationError("current-candidate-stages-incomplete")
    issueplan = readiness.issueplan_current_state_evidence
    repository_state = proposal_result.repository_state_evidence
    proposal = proposal_result.proposal
    expected = dict(packet.stage_identities)
    current = {
        "source": readiness.snapshot.source_revision,
        "issueplan": issueplan.evidence_id,
        "planning-handoff": planning.handoff.handoff_digest,
        "repository-evidence": repository_state.evidence_id,
        "proposal": proposal.proposal_id,
    }
    if any(expected.get(name) != value for name, value in current.items()):
        raise ProductionHandoffPublicationError("candidate-stage-identity-drift")
    approval = capsule.approval_record
    applicability = evaluate_approval_applicability(
        approval,
        proposal,
        issueplan,
        repository_state,
        evaluated_at=evaluated_at,
        invalidation_events=capsule.invalidation_events,
        planning_binding=proposal_result.planning_binding,
    )
    if applicability.status != "applicable" or not applicability.approval_applicable:
        raise ProductionHandoffPublicationError("approval-not-current")
    projection_result = build_approved_execution_projection(
        proposal=proposal,
        approval_record=approval,
        approval_applicability=applicability,
        issueplan_current_state_evidence=issueplan,
        repository_state_evidence=repository_state,
        projected_at=evaluated_at,
        planning_binding=proposal_result.planning_binding,
    )
    if not projection_result.complete or projection_result.projection is None:
        raise ProductionHandoffPublicationError("projection-incomplete")
    projection = projection_result.projection
    approval_identity = f"{approval.approval_id}@{approval.approval_revision}"
    if (
        expected.get("approval-decision") != approval_identity
        or expected.get("projection") != projection.projection_id
    ):
        raise ProductionHandoffPublicationError("approval-projection-identity-drift")
    stage = ApprovalProjectionStageResult(
        status=ApprovalProjectionStageStatus.COMPLETE,
        pending_candidate=None,
        decision_revision=approval,
        applicability=applicability,
        projection_result=projection_result,
        projection=projection,
    )
    return stage, proposal, issueplan, repository_state


def _runtime_inputs(
    *, packet, capsule, repository_state, projection, configuration, evaluated_at, authorization_present
):
    return CandidateRuntimeInputs(
        repository_identity=repository_state.repository_identity,
        repository_state_evidence=repository_state,
        issue_number=packet.issue_number,
        invocation_id=packet.invocation_id,
        candidate_branch=capsule.candidate_branch,
        candidate_sha=packet.candidate_sha,
        tested_sha=packet.tested_sha,
        evaluator_sha=packet.evaluator_sha,
        expected_changed_paths=tuple(packet.expected_changed_paths),
        required_tests=tuple(projection.required_tests),
        created_at=capsule.created_at,
        expires_at=capsule.expires_at,
        evaluated_at=evaluated_at,
        repository_root=str(configuration.repository_root),
        workspace_parent=str(configuration.workspace_parent),
        validation_bundle_id=capsule.validation_bundle_id,
        advisory_result_id=capsule.advisory_result_id,
        advisory_render_id=capsule.advisory_render_id,
        runtime_capability_available=True,
        execution_authorization_present=authorization_present,
        required_environment_spec=capsule.required_environment_spec,
    )


def _validation_expectations(payload, plan, identity, evidence_type, invocation_id, plan_id):
    return dict(
        expected_repository=identity,
        expected_pull_request=payload.get("pull_request"),
        expected_base_branch=payload.get("base_branch"),
        expected_base_sha=payload.get("base_sha"),
        expected_source_head_sha=payload.get("source_head_sha"),
        expected_tested_sha=payload.get("tested_sha"),
        expected_repository_evidence_type=evidence_type,
        expected_projection_id=payload.get("projection_id"),
        expected_proposal_id=payload.get("proposal_id"),
        expected_approval_id=payload.get("approval_id"),
        expected_repository_state_evidence_id=payload.get("repository_state_evidence_id"),
        expected_implementation_contract_fingerprint=payload.get(
            "implementation_contract_fingerprint"
        ),
        expected_selector_version=plan.selector_version,
        expected_profile=plan.profile,
        expected_command_set_digest=plan.command_set_digest,
        expected_plan_id=plan_id,
        runner_id=payload.get("runner_id"),
        invocation_id=invocation_id,
        started_at=payload.get("started_at"),
        completed_at=payload.get("completed_at"),
    )


def _pilot_input(
    *, packet, capsule, payload, issueplan, proposal, repository_state, approval_stage,
    runtime_configuration, evaluated_at
):
    projection = approval_stage.projection
    if projection is None:
        raise ProductionHandoffPublicationError("projection-incomplete")
    governed = consume_approved_projection_evidence(
        projection,
        repository_state,
        expected_repository=repository_state.repository_identity,
        expected_base_branch=projection.base_branch,
        expected_base_sha=projection.evaluated_repository_sha,
        expected_head_sha=packet.candidate_sha,
        expected_tested_sha=projection.tested_repository_sha,
        expected_projection_id=projection.projection_id,
        expected_approval_id=projection.approval_id,
        expected_proposal_id=projection.proposal_id,
        expected_repository_state_evidence_id=repository_state.evidence_id,
        expected_implementation_contract_fingerprint=projection.implementation_contract_fingerprint,
        expected_repository_evidence_type=repository_state.evidence_type,
    )
    if governed.status != "accepted":
        raise ProductionHandoffPublicationError("governed-projection-not-accepted")
    plan = _validation_plan(payload)
    if validation_plan_id(plan) != capsule.validation_plan_id:
        raise ProductionHandoffPublicationError("validation-plan-identity-mismatch")
    command_results = _supplied_command_results(payload)
    expectations = _validation_expectations(
        payload,
        plan,
        repository_state.repository_identity,
        repository_state.evidence_type,
        packet.invocation_id,
        capsule.validation_plan_id,
    )
    bundle = build_validation_evidence_bundle(governed, plan, command_results, **expectations)
    if bundle.bundle_id != capsule.validation_bundle_id:
        raise ProductionHandoffPublicationError("validation-bundle-identity-mismatch")
    advisory = evaluate_advisory_pre_pr_evidence(
        governed,
        plan,
        command_results,
        current_base_sha=projection.evaluated_repository_sha,
        current_source_head_sha=packet.candidate_sha,
        expected_bundle_id=capsule.validation_bundle_id,
        **expectations,
    )
    if advisory.result_id != capsule.advisory_result_id:
        raise ProductionHandoffPublicationError("advisory-identity-mismatch")
    render = render_advisory_evidence(advisory)
    if render.render_id != capsule.advisory_render_id:
        raise ProductionHandoffPublicationError("advisory-render-identity-mismatch")
    pilot = SingleIssuePilotInput(
        execution_mode=runtime_configuration.execution_mode,
        issue_numbers=(packet.issue_number,),
        requested_concurrency=1,
        repository=packet.repository,
        base_branch=projection.base_branch,
        base_sha=projection.evaluated_repository_sha,
        source_head_sha=packet.candidate_sha,
        tested_sha=projection.tested_repository_sha,
        branch=capsule.candidate_branch,
        invocation_id=packet.invocation_id,
        workspace_request_id=capsule.workspace_request_id,
        projection=projection,
        expected_projection_id=projection.projection_id,
        expected_proposal_id=projection.proposal_id,
        expected_approval_id=projection.approval_id,
        expected_issueplan_evidence=issueplan,
        current_issueplan_evidence=issueplan,
        approval_record=capsule.approval_record,
        current_proposal=proposal,
        repository_state_evidence=repository_state,
        evaluated_at=evaluated_at,
        validation_plan=plan,
        expected_plan_id=capsule.validation_plan_id,
        evidence_bundle=bundle,
        expected_bundle_id=capsule.validation_bundle_id,
        advisory_result=advisory,
        expected_advisory_result_id=capsule.advisory_result_id,
        advisory_render=render,
        expected_advisory_render_id=capsule.advisory_render_id,
        allowed_files=tuple(projection.allowed_files),
        forbidden_paths=tuple(projection.forbidden_paths),
        required_tests=tuple(plan.commands),
        invalidation_events=capsule.invalidation_events,
    )
    runtime_configuration.verify(pilot)
    return pilot


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-os-publish-handoff")
    parser.add_argument("--capsule-id", required=True)
    parser.add_argument("--route-decision-id", required=True)
    parser.add_argument("--dependency-readiness-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    identity = ProductionHandoffPublicationIdentity(
        capsule_id=args.capsule_id,
        route_decision_id=args.route_decision_id,
        dependency_readiness_id=args.dependency_readiness_id,
    )
    handoff = publish_production_handoff(identity)
    print(handoff.handoff_id)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via module entrypoint
    raise SystemExit(main())
