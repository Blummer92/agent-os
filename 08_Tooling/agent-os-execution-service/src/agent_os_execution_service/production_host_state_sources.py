"""Concrete production state sources for governed resume (#1303).

This module closes the seven ``HostCurrentInvocationSources`` slots without
creating another currentness, authorization, Scheduler, lease, retry, or store
owner. Four durable objects are loaded through #1304. Candidate semantics are
reacquired from the existing #750-#755 pipeline, approval applicability and the
portable projection are recomputed through their canonical owners, validation
and advisory evidence are rebuilt from the one bounded restart capsule, and the
complete ``SingleIssuePilotInput`` exists only in memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from scripts.agent_os_candidate_packet.approval_stage import (
    ApprovalProjectionStageResult,
    ApprovalProjectionStageStatus,
)
from scripts.agent_os_candidate_packet.cli import PreparedCandidatePacket, prepare_candidate_packet
from scripts.agent_os_candidate_packet.models import CandidatePacket, CandidatePacketPhase
from scripts.agent_os_candidate_packet.repository_stage import RepositoryObservation
from scripts.agent_os_candidate_packet.stage_models import (
    DependencyIdentityEvidence,
    IssueSourceReader,
    RepositoryEvidenceReader,
)
from scripts.agent_os_candidate_packet.validation_stage import (
    CandidateRuntimeInputs,
    ValidationStageDisposition,
    ValidationStageResult,
    prepare_validation_stage,
)
from scripts.agent_os_execution_capabilities.approved_projection import (
    consume_approved_projection_evidence,
)
from scripts.agent_os_execution_capabilities.dependencies import RequiredEnvironmentSpec
from scripts.agent_os_execution_checkpoint.invocation_descriptor import GovernedInvocationDescriptor
from scripts.agent_os_execution_checkpoint.resume_plan_store import load_resume_plan
from scripts.agent_os_execution_checkpoint.store import load_checkpoint_by_id
from scripts.agent_os_issue_acceptance.approval_records import evaluate_approval_applicability
from scripts.agent_os_issue_acceptance.approved_execution_projection import (
    build_approved_execution_projection,
)
from scripts.agent_os_remote_validation import (
    SelectionInput,
    SuppliedCommandResult,
    build_validation_evidence_bundle,
    evaluate_advisory_pre_pr_evidence,
    load_rule_map,
    render_advisory_evidence,
    select_validation_plan,
    validation_plan_id,
)
from workflow_scheduler.execution.runtime_configuration import (
    ConcreteRuntimeConfiguration,
    FrozenTestCommand,
)
from workflow_scheduler.execution.single_issue_pilot import SingleIssuePilotInput

from .current_invocation_resolver import CurrentInvocationResolutionError
from .governed_resume_restart_capsule import (
    GovernedResumeRestartCapsule,
    load_restart_capsule,
)
from .handoff_store import load_executor_handoff
from .route_decision_store import load_route_decision
from .runtime_execution_request import RuntimeExecutionRequest

RepositoryObservationReader = Callable[[GovernedInvocationDescriptor], RepositoryObservation]
RequiredEnvironmentSpecReader = Callable[[GovernedInvocationDescriptor], RequiredEnvironmentSpec]
DependencyIdentityEvidenceReader = Callable[
    [GovernedInvocationDescriptor], DependencyIdentityEvidence | None
]


@dataclass(frozen=True, slots=True)
class _CurrentState:
    descriptor_id: str
    capsule: GovernedResumeRestartCapsule
    prepared: PreparedCandidatePacket
    issueplan: object
    repository_state: object
    proposal: object
    approval_record: object
    projection: object
    validation_stage: ValidationStageResult
    validation_plan: object
    required_environment_spec: RequiredEnvironmentSpec


class ProductionHostStateSources:
    """One invocation-scoped composition of all seven production source slots."""

    def __init__(
        self,
        *,
        checkpoint_store_root: Path | str,
        issue_reader: IssueSourceReader,
        repository_reader: RepositoryEvidenceReader,
        repository_observation_reader: RepositoryObservationReader,
        required_environment_spec_reader: RequiredEnvironmentSpecReader,
        evaluated_at: str,
        repository_root: Path | str,
        workspace_parent: Path | str,
        lease_directory: Path | str,
        delegated_parent_cgroup: Path | str | None = None,
        dependency_identity_evidence_reader: DependencyIdentityEvidenceReader | None = None,
        runtime_request: RuntimeExecutionRequest | None = None,
    ) -> None:
        self.checkpoint_store_root = Path(checkpoint_store_root)
        self.issue_reader = issue_reader
        self.repository_reader = repository_reader
        self.repository_observation_reader = repository_observation_reader
        self.required_environment_spec_reader = required_environment_spec_reader
        self.dependency_identity_evidence_reader = dependency_identity_evidence_reader
        self.evaluated_at = _text(evaluated_at, "evaluated_at")
        self.repository_root = str(Path(repository_root))
        self.workspace_parent = str(Path(workspace_parent))
        self.lease_directory = str(Path(lease_directory))
        self.delegated_parent_cgroup = (
            None if delegated_parent_cgroup is None else str(Path(delegated_parent_cgroup))
        )
        self.runtime_request = runtime_request
        for name in (
            "repository_observation_reader",
            "required_environment_spec_reader",
        ):
            if not callable(getattr(self, name)):
                raise TypeError(f"{name} must be callable")
        if self.dependency_identity_evidence_reader is not None and not callable(
            self.dependency_identity_evidence_reader
        ):
            raise TypeError("dependency_identity_evidence_reader must be callable or None")
        self._cached_descriptor_id: str | None = None
        self._cached_state: _CurrentState | None = None

    def route_decision(self, descriptor: GovernedInvocationDescriptor) -> object:
        descriptor = _descriptor(descriptor)
        if self.runtime_request is not None:
            _check_descriptor_matches_request(descriptor, self.runtime_request)
            return self.runtime_request.route_decision
        return load_route_decision(self.checkpoint_store_root, descriptor.route_decision_id)

    def handoff(
        self,
        descriptor: GovernedInvocationDescriptor,
        route_decision: object,
    ) -> object:
        del route_decision
        descriptor = _descriptor(descriptor)
        if self.runtime_request is not None:
            _check_descriptor_matches_request(descriptor, self.runtime_request)
            return self.runtime_request.handoff
        return load_executor_handoff(self.checkpoint_store_root, descriptor.handoff_id)

    def checkpoint(self, descriptor: GovernedInvocationDescriptor) -> object:
        descriptor = _descriptor(descriptor)
        return load_checkpoint_by_id(
            self.checkpoint_store_root,
            descriptor.issue_number,
            descriptor.checkpoint_id,
        )

    def resume_plan(
        self,
        descriptor: GovernedInvocationDescriptor,
        checkpoint: object,
    ) -> object:
        del checkpoint
        descriptor = _descriptor(descriptor)
        return load_resume_plan(self.checkpoint_store_root, descriptor.resume_plan_id)

    def candidate_packet(self, descriptor: GovernedInvocationDescriptor) -> CandidatePacket:
        state = self._state(_descriptor(descriptor))
        return state.capsule.candidate_packet

    def runtime_configuration(
        self,
        descriptor: GovernedInvocationDescriptor,
        candidate_packet: object,
    ) -> ConcreteRuntimeConfiguration:
        descriptor = _descriptor(descriptor)
        state = self._state(descriptor)
        packet = state.capsule.candidate_packet
        if candidate_packet is not packet and candidate_packet != packet:
            raise CurrentInvocationResolutionError(
                "candidate packet argument does not match current restart capsule"
            )
        projection = state.projection
        repository_state = state.repository_state
        validation_plan = state.validation_plan
        commands_by_id = {name: argv for name, argv in packet.argv_bindings}
        try:
            frozen = tuple(
                FrozenTestCommand(test_id=test_id, argv=commands_by_id[test_id])
                for test_id in validation_plan.commands
            )
        except KeyError as exc:
            raise CurrentInvocationResolutionError(
                "current validation plan command has no candidate argv binding"
            ) from exc
        if tuple(item.test_id for item in frozen) != tuple(validation_plan.commands):
            raise CurrentInvocationResolutionError("validation command order drifted")
        if packet.per_command_timeout_seconds is None or packet.total_timeout_seconds is None:
            raise CurrentInvocationResolutionError("candidate packet lacks runtime timeout bounds")
        if packet.max_output_bytes is None:
            raise CurrentInvocationResolutionError("candidate packet lacks runtime output bound")

        identity = getattr(repository_state, "repository_identity", None)
        try:
            configuration = ConcreteRuntimeConfiguration.bind_candidate(
                repository=descriptor.repository,
                issue_number=descriptor.issue_number,
                invocation_id=descriptor.invocation_id,
                workspace_request_id=state.capsule.workspace_request_id,
                base_branch=projection.base_branch,
                base_sha=projection.evaluated_repository_sha,
                source_head_sha=descriptor.source_sha,
                tested_sha=projection.tested_repository_sha,
                branch=state.capsule.candidate_branch,
                projection_id=projection.projection_id,
                approval_id=projection.approval_id,
                validation_plan_id=state.capsule.validation_plan_id,
                validation_bundle_id=state.capsule.validation_bundle_id,
                advisory_result_id=state.capsule.advisory_result_id,
                advisory_render_id=state.capsule.advisory_render_id,
                repository_identity=identity,
                repository_root=self.repository_root,
                workspace_parent=self.workspace_parent,
                required_test_commands=frozen,
                allowed_files=tuple(projection.allowed_files),
                forbidden_paths=tuple(projection.forbidden_paths),
                executor_timeout_seconds=packet.per_command_timeout_seconds,
                executor_max_output_bytes=packet.max_output_bytes,
                validation_per_command_timeout_seconds=packet.per_command_timeout_seconds,
                validation_total_timeout_seconds=packet.total_timeout_seconds,
                validation_max_output_bytes=packet.max_output_bytes,
                lease_directory=self.lease_directory,
                delegated_parent_cgroup=self.delegated_parent_cgroup,
                required_environment_spec=state.required_environment_spec,
            )
        except (TypeError, ValueError) as exc:
            raise CurrentInvocationResolutionError(
                "current runtime configuration could not be rebuilt"
            ) from exc
        if configuration.configuration_fingerprint != descriptor.runtime_configuration_fingerprint:
            raise CurrentInvocationResolutionError(
                "rebuilt runtime configuration fingerprint does not match descriptor"
            )
        return configuration

    def pilot_input(
        self,
        descriptor: GovernedInvocationDescriptor,
        *,
        route_decision: object,
        handoff: object,
        authorization: object,
        checkpoint: object,
        resume_plan: object,
        candidate_packet: object,
        runtime_configuration: object,
        dependency_readiness: object,
    ) -> SingleIssuePilotInput:
        del route_decision, handoff, authorization, checkpoint, resume_plan, dependency_readiness
        descriptor = _descriptor(descriptor)
        state = self._state(descriptor)
        packet = state.capsule.candidate_packet
        if candidate_packet is not packet and candidate_packet != packet:
            raise CurrentInvocationResolutionError("pilot candidate packet drifted")
        if type(runtime_configuration) is not ConcreteRuntimeConfiguration:
            raise CurrentInvocationResolutionError("pilot runtime configuration is malformed")

        projection = state.projection
        repository_state = state.repository_state
        identity = getattr(repository_state, "repository_identity", None)
        evidence_type = getattr(repository_state, "evidence_type", None)
        try:
            governed_projection = consume_approved_projection_evidence(
                projection,
                repository_state,
                expected_repository=identity,
                expected_base_branch=projection.base_branch,
                expected_base_sha=projection.evaluated_repository_sha,
                expected_head_sha=descriptor.source_sha,
                expected_tested_sha=projection.tested_repository_sha,
                expected_projection_id=projection.projection_id,
                expected_approval_id=projection.approval_id,
                expected_proposal_id=projection.proposal_id,
                expected_repository_state_evidence_id=repository_state.evidence_id,
                expected_implementation_contract_fingerprint=(
                    projection.implementation_contract_fingerprint
                ),
                expected_repository_evidence_type=evidence_type,
            )
        except (TypeError, ValueError) as exc:
            raise CurrentInvocationResolutionError(
                "current governed projection evidence could not be rebuilt"
            ) from exc
        if governed_projection.status != "accepted":
            raise CurrentInvocationResolutionError(
                "current governed projection evidence is not accepted"
            )

        bundle_payload = state.capsule.validation_bundle_payload()
        validation_plan = state.validation_plan
        command_results = _supplied_command_results(bundle_payload)
        expectations = {
            "expected_repository": identity,
            "expected_pull_request": bundle_payload.get("pull_request"),
            "expected_base_branch": projection.base_branch,
            "expected_base_sha": projection.evaluated_repository_sha,
            "expected_source_head_sha": descriptor.source_sha,
            "expected_tested_sha": projection.tested_repository_sha,
            "expected_repository_evidence_type": evidence_type,
            "expected_projection_id": projection.projection_id,
            "expected_proposal_id": projection.proposal_id,
            "expected_approval_id": projection.approval_id,
            "expected_repository_state_evidence_id": repository_state.evidence_id,
            "expected_implementation_contract_fingerprint": (
                projection.implementation_contract_fingerprint
            ),
            "expected_selector_version": validation_plan.selector_version,
            "expected_profile": validation_plan.profile,
            "expected_command_set_digest": validation_plan.command_set_digest,
            "expected_plan_id": state.capsule.validation_plan_id,
            "runner_id": bundle_payload.get("runner_id"),
            "invocation_id": descriptor.invocation_id,
            "started_at": bundle_payload.get("started_at"),
            "completed_at": bundle_payload.get("completed_at"),
        }
        try:
            bundle = build_validation_evidence_bundle(
                governed_projection,
                validation_plan,
                command_results,
                **expectations,
            )
            if bundle.bundle_id != state.capsule.validation_bundle_id:
                raise CurrentInvocationResolutionError(
                    "rebuilt validation bundle identity does not match restart capsule"
                )
            advisory = evaluate_advisory_pre_pr_evidence(
                governed_projection,
                validation_plan,
                command_results,
                current_base_sha=projection.evaluated_repository_sha,
                current_source_head_sha=descriptor.source_sha,
                expected_bundle_id=state.capsule.validation_bundle_id,
                **expectations,
            )
            if advisory.result_id != state.capsule.advisory_result_id:
                raise CurrentInvocationResolutionError(
                    "rebuilt advisory identity does not match restart capsule"
                )
            render = render_advisory_evidence(advisory)
            if render.render_id != state.capsule.advisory_render_id:
                raise CurrentInvocationResolutionError(
                    "rebuilt advisory render identity does not match restart capsule"
                )
        except CurrentInvocationResolutionError:
            raise
        except (TypeError, ValueError) as exc:
            raise CurrentInvocationResolutionError(
                "validation/advisory evidence could not be rebuilt"
            ) from exc

        try:
            pilot = SingleIssuePilotInput(
                execution_mode=runtime_configuration.execution_mode,
                issue_numbers=(descriptor.issue_number,),
                requested_concurrency=1,
                repository=descriptor.repository,
                base_branch=projection.base_branch,
                base_sha=projection.evaluated_repository_sha,
                source_head_sha=descriptor.source_sha,
                tested_sha=projection.tested_repository_sha,
                branch=state.capsule.candidate_branch,
                invocation_id=descriptor.invocation_id,
                workspace_request_id=state.capsule.workspace_request_id,
                projection=projection,
                expected_projection_id=projection.projection_id,
                expected_proposal_id=projection.proposal_id,
                expected_approval_id=projection.approval_id,
                expected_issueplan_evidence=state.issueplan,
                current_issueplan_evidence=state.issueplan,
                approval_record=state.approval_record,
                current_proposal=state.proposal,
                repository_state_evidence=repository_state,
                evaluated_at=self.evaluated_at,
                validation_plan=validation_plan,
                expected_plan_id=state.capsule.validation_plan_id,
                evidence_bundle=bundle,
                expected_bundle_id=state.capsule.validation_bundle_id,
                advisory_result=advisory,
                expected_advisory_result_id=state.capsule.advisory_result_id,
                advisory_render=render,
                expected_advisory_render_id=state.capsule.advisory_render_id,
                allowed_files=tuple(projection.allowed_files),
                forbidden_paths=tuple(projection.forbidden_paths),
                required_tests=tuple(validation_plan.commands),
                invalidation_events=state.capsule.invalidation_events,
            )
            runtime_configuration.verify(pilot)
        except (TypeError, ValueError) as exc:
            raise CurrentInvocationResolutionError(
                "current SingleIssuePilotInput could not be constructed"
            ) from exc
        return pilot

    def _state(self, descriptor: GovernedInvocationDescriptor) -> _CurrentState:
        if self._cached_descriptor_id == descriptor.descriptor_id and self._cached_state is not None:
            return self._cached_state
        state = self._rebuild_current_state(descriptor)
        self._cached_descriptor_id = descriptor.descriptor_id
        self._cached_state = state
        return state

    def _rebuild_current_state(self, descriptor: GovernedInvocationDescriptor) -> _CurrentState:
        if self.runtime_request is not None:
            _check_descriptor_matches_request(descriptor, self.runtime_request)
            capsule = self.runtime_request.restart_capsule
        else:
            capsule = load_restart_capsule(self.checkpoint_store_root, descriptor.handoff_id)
        packet = capsule.candidate_packet
        if (
            packet.packet_id != descriptor.candidate_packet_id
            or packet.repository.casefold() != descriptor.repository.casefold()
            or packet.issue_number != descriptor.issue_number
            or packet.invocation_id != descriptor.invocation_id
            or packet.candidate_sha != descriptor.source_sha
            or packet.phase is not CandidatePacketPhase.EXECUTION_CANDIDATE
        ):
            raise CurrentInvocationResolutionError(
                "restart capsule candidate packet does not match invocation descriptor"
            )

        observation = self.repository_observation_reader(descriptor)
        if type(observation) is not RepositoryObservation:
            raise CurrentInvocationResolutionError(
                "repository_observation_reader must return exact RepositoryObservation"
            )
        dependency_identity = (
            None
            if self.dependency_identity_evidence_reader is None
            else self.dependency_identity_evidence_reader(descriptor)
        )
        try:
            prepared = prepare_candidate_packet(
                repository=descriptor.repository,
                issue_number=descriptor.issue_number,
                issue_reader=self.issue_reader,
                repository_reader=self.repository_reader,
                observed_at=self.evaluated_at,
                base_branch=packet.base_branch,
                evaluated_repository_sha=observation.base_sha,
                invocation_id=descriptor.invocation_id,
                evaluator_sha=packet.evaluator_sha,
                dependency_identity_evidence=dependency_identity,
                repository_observation=observation,
                requested_phase=CandidatePacketPhase.APPROVAL_READY,
                external_build_sha=packet.external_build_sha,
                compiler_evaluated_at=self.evaluated_at,
            )
        except (TypeError, ValueError) as exc:
            raise CurrentInvocationResolutionError(
                "current candidate stages could not be reacquired"
            ) from exc
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
            raise CurrentInvocationResolutionError(
                "current candidate stages are incomplete or blocked"
            )
        issueplan = readiness.issueplan_current_state_evidence
        repository_state = proposal_result.repository_state_evidence
        proposal = proposal_result.proposal

        expected = dict(packet.stage_identities)
        current_identities = {
            "source": readiness.snapshot.source_revision,
            "issueplan": issueplan.evidence_id,
            "planning-handoff": planning.handoff.handoff_digest,
            "repository-evidence": repository_state.evidence_id,
            "proposal": proposal.proposal_id,
        }
        for name, observed in current_identities.items():
            if expected.get(name) != observed:
                raise CurrentInvocationResolutionError(
                    f"current {name} identity does not match candidate packet"
                )

        approval_record = capsule.approval_record
        try:
            applicability = evaluate_approval_applicability(
                approval_record,
                proposal,
                issueplan,
                repository_state,
                evaluated_at=self.evaluated_at,
                invalidation_events=capsule.invalidation_events,
                planning_binding=proposal_result.planning_binding,
            )
            if applicability.status != "applicable" or not applicability.approval_applicable:
                raise CurrentInvocationResolutionError("current approval is not applicable")
            projection_result = build_approved_execution_projection(
                proposal=proposal,
                approval_record=approval_record,
                approval_applicability=applicability,
                issueplan_current_state_evidence=issueplan,
                repository_state_evidence=repository_state,
                projected_at=self.evaluated_at,
                planning_binding=proposal_result.planning_binding,
            )
        except CurrentInvocationResolutionError:
            raise
        except (TypeError, ValueError) as exc:
            raise CurrentInvocationResolutionError(
                "current approval/projection could not be reverified"
            ) from exc
        if not projection_result.complete or projection_result.projection is None:
            raise CurrentInvocationResolutionError("current approved projection is incomplete")
        projection = projection_result.projection
        approval_identity = f"{approval_record.approval_id}@{approval_record.approval_revision}"
        if expected.get("approval-decision") != approval_identity:
            raise CurrentInvocationResolutionError(
                "current approval decision does not match candidate packet"
            )
        if expected.get("projection") != projection.projection_id:
            raise CurrentInvocationResolutionError(
                "current projection does not match candidate packet"
            )

        required_environment = self.required_environment_spec_reader(descriptor)
        if type(required_environment) is not RequiredEnvironmentSpec:
            raise CurrentInvocationResolutionError(
                "required_environment_spec_reader must return exact RequiredEnvironmentSpec"
            )
        if required_environment.required_environment_id != descriptor.required_environment_id:
            raise CurrentInvocationResolutionError(
                "required environment specification does not match descriptor"
            )

        candidate_inputs = CandidateRuntimeInputs(
            repository_identity=repository_state.repository_identity,
            repository_state_evidence=repository_state,
            issue_number=descriptor.issue_number,
            invocation_id=descriptor.invocation_id,
            candidate_branch=capsule.candidate_branch,
            candidate_sha=descriptor.source_sha,
            tested_sha=projection.tested_repository_sha,
            evaluator_sha=projection.evaluator_commit_sha,
            expected_changed_paths=tuple(packet.expected_changed_paths),
            required_tests=tuple(projection.required_tests),
            created_at=capsule.created_at,
            expires_at=capsule.expires_at,
            evaluated_at=self.evaluated_at,
            repository_root=self.repository_root,
            workspace_parent=self.workspace_parent,
            validation_bundle_id=capsule.validation_bundle_id,
            advisory_result_id=capsule.advisory_result_id,
            advisory_render_id=capsule.advisory_render_id,
            runtime_capability_available=True,
            execution_authorization_present=False,
            required_environment_spec=required_environment,
        )
        current_approval_stage = ApprovalProjectionStageResult(
            status=ApprovalProjectionStageStatus.COMPLETE,
            pending_candidate=None,
            decision_revision=approval_record,
            applicability=applicability,
            projection_result=projection_result,
            projection=projection,
        )
        validation_stage = prepare_validation_stage(current_approval_stage, candidate_inputs)
        if (
            validation_stage.disposition is not ValidationStageDisposition.GO
            or validation_stage.validation_plan is None
        ):
            raise CurrentInvocationResolutionError(
                "current candidate-bound validation stage is not GO"
            )
        if expected.get("validation-subject") != validation_stage.subject_id:
            raise CurrentInvocationResolutionError(
                "current validation subject does not match candidate packet"
            )

        bundle_payload = capsule.validation_bundle_payload()
        pull_request = bundle_payload.get("pull_request")
        selector_version = bundle_payload.get("selector_version")
        if type(pull_request) is not int or isinstance(pull_request, bool) or pull_request <= 0:
            raise CurrentInvocationResolutionError("restart capsule has no valid pull request")
        if type(selector_version) is not str or not selector_version:
            raise CurrentInvocationResolutionError("restart capsule has no selector version")
        validation_plan = select_validation_plan(
            SelectionInput(
                repository=descriptor.repository,
                pull_request=pull_request,
                base_sha=projection.evaluated_repository_sha,
                head_sha=descriptor.source_sha,
                changed_files=tuple(packet.expected_changed_paths),
                selector_version=selector_version,
            ),
            load_rule_map(),
        )
        if validation_plan_id(validation_plan) != capsule.validation_plan_id:
            raise CurrentInvocationResolutionError(
                "fresh validation plan identity does not match restart capsule"
            )
        if tuple(validation_plan.commands) != tuple(packet.required_tests):
            raise CurrentInvocationResolutionError(
                "fresh validation plan commands do not match candidate packet"
            )

        return _CurrentState(
            descriptor_id=descriptor.descriptor_id,
            capsule=capsule,
            prepared=prepared,
            issueplan=issueplan,
            repository_state=repository_state,
            proposal=proposal,
            approval_record=approval_record,
            projection=projection,
            validation_stage=validation_stage,
            validation_plan=validation_plan,
            required_environment_spec=required_environment,
        )


def _descriptor(value: GovernedInvocationDescriptor) -> GovernedInvocationDescriptor:
    if type(value) is not GovernedInvocationDescriptor:
        raise TypeError("descriptor must be an exact GovernedInvocationDescriptor")
    return value


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise TypeError(f"{name} must be non-empty exact text")
    return value


def _supplied_command_results(payload: dict[str, object]) -> tuple[SuppliedCommandResult, ...]:
    raw = payload.get("command_results")
    if type(raw) is not list:
        raise CurrentInvocationResolutionError(
            "restart capsule validation command results are malformed"
        )
    results: list[SuppliedCommandResult] = []
    for item in raw:
        if type(item) is not dict:
            raise CurrentInvocationResolutionError(
                "restart capsule validation command result is malformed"
            )
        try:
            results.append(
                SuppliedCommandResult(
                    plan_id=item["plan_id"],
                    invocation_id=item["invocation_id"],
                    runner_id=item["runner_id"],
                    command_ordinal=item["command_ordinal"],
                    command=item["command"],
                    source_head_sha=item["source_head_sha"],
                    tested_sha=item["tested_sha"],
                    started_at=item["started_at"],
                    completed_at=item["completed_at"],
                    status=item["status"],
                    exit_code=item["exit_code"],
                    diagnostic_summary=item["diagnostic_summary"],
                    diagnostic_truncated=item["diagnostic_truncated"],
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CurrentInvocationResolutionError(
                "restart capsule validation command result is malformed"
            ) from exc
    return tuple(results)

def _check_descriptor_matches_request(
    descriptor: GovernedInvocationDescriptor, request: RuntimeExecutionRequest
) -> None:
    if descriptor.handoff_id != request.handoff_id:
        raise CurrentInvocationResolutionError(
            "invocation descriptor does not match canonical runtime request"
        )
