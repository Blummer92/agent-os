from __future__ import annotations

import pytest
import os
import functools
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_os_execution_service.runtime_execution_request import RuntimeExecutionRequest
from agent_os_execution_service.production_host_state_sources import ProductionHostStateSources, CurrentInvocationResolutionError
from scripts.agent_os_execution_checkpoint.invocation_descriptor import GovernedInvocationDescriptor
from agent_os_execution_service.executor_routing import ExecutorRouteDecision, ExecutorHandoff, ExecutorRoute
from agent_os_execution_service.governed_resume_restart_capsule import GovernedResumeRestartCapsule
from scripts.agent_os_candidate_packet.models import CandidatePacket, CandidatePacketPhase
from agent_os_execution_service.production_host_bootstrap import (
    build_production_host_bootstrap,
    build_repository_observation_reader,
    build_required_environment_spec_reader,
    ProductionHostConfiguration,
)
from agent_os_execution_service.production_host_composition import build_production_governed_resume_bindings
from agent_os_execution_service.execution_authorization_source import ExecutionAuthorizationSourceTransport
from scripts.agent_os_candidate_packet.repository_stage import RepositoryObservation
from scripts.agent_os_execution_capabilities.models import RepositoryIdentity, RepositoryEvidenceType, WorktreeState

HANDOFF_ID = "executor-handoff:" + "a" * 64

@pytest.fixture
def descriptor():
    return GovernedInvocationDescriptor(
        schema_name="agent-os.governed-invocation-descriptor",
        schema_version="1.0",
        repository="Blummer92/agent-os",
        issue_number=1338,
        issue_or_handoff_identity=HANDOFF_ID,
        handoff_id=HANDOFF_ID,
        route_decision_id="route-decision:" + "b" * 64,
        execution_service_request_fingerprint="fingerprint:" + "c" * 64,
        authorization_id="authorization:" + "d" * 64,
        source_ref="refs/heads/main",
        source_sha="e" * 40,
        checkpoint_id="checkpoint:" + "f" * 64,
        resume_plan_id="resume-plan:" + "0" * 64,
        environment_profile_id="env-profile",
        environment_health_evidence_id="env-health",
        required_environment_id="req-env",
        dependency_readiness_evidence_id="dep-readiness",
        execution_surface_id="surface",
        workspace_identity="workspace",
        workflow_runtime_identity="workflow",
        candidate_packet_id="packet",
        runtime_configuration_fingerprint="config-fingerprint",
        execution_id="exec",
        invocation_id="inv",
    )

@pytest.fixture
def runtime_request(descriptor):
    route_decision = MagicMock(spec=ExecutorRouteDecision)
    route_decision.decision_id = descriptor.route_decision_id
    route_decision.repository = descriptor.repository
    route_decision.issue_or_handoff_identity = descriptor.issue_or_handoff_identity
    route_decision.selected_route = ExecutorRoute.CHATGPT_GOVERNED_RUNNER

    handoff = MagicMock(spec=ExecutorHandoff)
    handoff.handoff_id = descriptor.handoff_id
    handoff.route_decision_id = descriptor.route_decision_id
    handoff.repository = descriptor.repository
    handoff.issue_or_handoff_identity = descriptor.issue_or_handoff_identity
    handoff.destination_route = ExecutorRoute.CHATGPT_GOVERNED_RUNNER

    packet = MagicMock(spec=CandidatePacket)
    packet.packet_id = descriptor.candidate_packet_id
    packet.repository = descriptor.repository
    packet.issue_number = descriptor.issue_number
    packet.invocation_id = descriptor.invocation_id
    packet.candidate_sha = descriptor.source_sha
    packet.phase = CandidatePacketPhase.EXECUTION_CANDIDATE
    packet.base_branch = "main"
    packet.base_sha = "4" * 40
    packet.freshness_boundary = "2026-08-28T12:00:00Z"
    packet.external_build_sha = None

    capsule = MagicMock(spec=GovernedResumeRestartCapsule)
    capsule.handoff_id = descriptor.handoff_id
    capsule.candidate_packet = packet
    capsule.approval_record.binding.implementation_contract_fingerprint = "5" * 64
    capsule.required_environment_spec.required_environment_id = descriptor.required_environment_id

    request = MagicMock(spec=RuntimeExecutionRequest)
    request.handoff_id = HANDOFF_ID
    request.route_decision = route_decision
    request.handoff = handoff
    request.invocation_descriptor = descriptor
    request.restart_capsule = capsule
    return request

def test_canonical_present_performs_zero_standalone_reads(tmp_path, descriptor, runtime_request):
    observation = RepositoryObservation(
        producer_adapter="test",
        producer_adapter_version="1.0",
        correlation_id="test",
        repository_identity=RepositoryIdentity(host="github.com", owner="Blummer92", repository="agent-os"),
        base_ref="refs/heads/main",
        base_sha="1" * 40,
        head_ref="refs/heads/branch",
        head_sha="2" * 40,
        requested_ref=None,
        requested_sha=None,
        observed_sha="2" * 40,
        tested_sha=None,
        pushed_sha=None,
        proposed_pr_sha=None,
        synthetic_merge_sha=None,
        external_build_sha=None,
        evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        contract_fingerprint="3" * 64,
        worktree_state=WorktreeState.CLEAN,
        observed_at="2026-08-28T12:00:00Z",
        freshness_boundary="2026-08-28T12:00:00Z",
    )
    
    # Readers built WITH runtime_request
    obs_reader = build_repository_observation_reader(
        configuration=ProductionHostConfiguration(
            checkpoint_store_root=tmp_path,
            repository_root=tmp_path,
            workspace_parent=tmp_path,
            lease_directory=tmp_path,
            delegated_parent_cgroup=None,
            repository_host="github.com",
        ),
        evaluated_at="2026-08-28T12:00:00Z",
        run_verifier=lambda x: "verifier-stdout",
        runtime_request=runtime_request
    )
    env_reader = build_required_environment_spec_reader(
        store_root=tmp_path,
        runtime_request=runtime_request
    )

    sources = ProductionHostStateSources(
        checkpoint_store_root=tmp_path,
        issue_reader=MagicMock(),
        repository_reader=MagicMock(),
        repository_observation_reader=obs_reader,
        required_environment_spec_reader=env_reader,
        evaluated_at="2026-08-28T12:00:00Z",
        repository_root=tmp_path,
        workspace_parent=tmp_path,
        lease_directory=tmp_path,
        runtime_request=runtime_request,
    )

    with patch("agent_os_execution_service.production_host_state_sources.load_route_decision") as mock_route, \
         patch("agent_os_execution_service.production_host_state_sources.load_executor_handoff") as mock_handoff, \
         patch("agent_os_execution_service.production_host_state_sources.load_restart_capsule") as mock_capsule, \
         patch("agent_os_execution_service.production_host_bootstrap.load_restart_capsule") as mock_capsule_obs, \
         patch("agent_os_execution_service.governed_resume_restart_capsule.load_restart_capsule") as mock_capsule_env, \
         patch("agent_os_execution_service.production_host_bootstrap.build_repository_observation_from_verifier_stdout", return_value=observation):
        
        assert sources.route_decision(descriptor) is runtime_request.route_decision
        assert sources.handoff(descriptor, None) is runtime_request.handoff
        
        # Reader calls should use runtime_request and avoid standalone capsule reads
        assert sources.repository_observation_reader(descriptor) is observation
        assert sources.required_environment_spec_reader(descriptor) is runtime_request.restart_capsule.required_environment_spec

        mock_route.assert_not_called()
        mock_handoff.assert_not_called()
        mock_capsule.assert_not_called()
        mock_capsule_obs.assert_not_called()
        mock_capsule_env.assert_not_called()

def test_tampered_canonical_evidence_fails_closed(tmp_path, descriptor, runtime_request):
    # Tamper with the request so it doesn't match the descriptor
    tampered_request = MagicMock(spec=RuntimeExecutionRequest)
    tampered_request.handoff_id = "executor-handoff:" + "f" * 64 # Mismatch
    
    sources = ProductionHostStateSources(
        checkpoint_store_root=tmp_path,
        issue_reader=MagicMock(),
        repository_reader=MagicMock(),
        repository_observation_reader=MagicMock(),
        required_environment_spec_reader=MagicMock(),
        evaluated_at="2026-08-28T12:00:00Z",
        repository_root=tmp_path,
        workspace_parent=tmp_path,
        lease_directory=tmp_path,
        runtime_request=tampered_request,
    )

    with pytest.raises(CurrentInvocationResolutionError, match="does not match canonical runtime request"):
        sources.route_decision(descriptor)

def test_legacy_fallback_when_canonical_absent(tmp_path, descriptor):
    sources = ProductionHostStateSources(
        checkpoint_store_root=tmp_path,
        issue_reader=MagicMock(),
        repository_reader=MagicMock(),
        repository_observation_reader=MagicMock(),
        required_environment_spec_reader=MagicMock(),
        evaluated_at="2026-08-28T12:00:00Z",
        repository_root=tmp_path,
        workspace_parent=tmp_path,
        lease_directory=tmp_path,
        runtime_request=None,
    )

    with patch("agent_os_execution_service.production_host_state_sources.load_route_decision") as mock_route:
        try:
            sources.route_decision(descriptor)
        except:
            pass
        mock_route.assert_called_once()

def test_bootstrap_propagates_runtime_request(tmp_path, runtime_request):
    config = ProductionHostConfiguration(
        checkpoint_store_root=tmp_path,
        repository_root=tmp_path,
        workspace_parent=tmp_path,
        lease_directory=tmp_path,
        delegated_parent_cgroup=None,
        repository_host="github.com"
    )
    
    issue_transport = MagicMock()
    issue_transport.get_issue = lambda x, y: None
    
    auth_transport = MagicMock(spec=ExecutionAuthorizationSourceTransport)
    
    repo_reader = MagicMock()
    repo_reader.read_dependency_evidence = lambda x, y: None
    repo_reader.read_validation_evidence = lambda x, y: None
    
    with patch("agent_os_execution_service.production_host_bootstrap.load_production_host_configuration", return_value=config), \
         patch("agent_os_execution_service.production_host_bootstrap.canonical_evaluated_at", return_value="2026-08-28T12:00:00Z"), \
         patch("agent_os_execution_service.production_host_bootstrap.build_repository_observation_reader"), \
         patch("agent_os_execution_service.production_host_bootstrap.build_required_environment_spec_reader"):
             
        bootstrap = build_production_host_bootstrap(
            issue_transport=issue_transport,
            authorization_transport=auth_transport,
            repository_evidence_reader=repo_reader,
            run_verifier=MagicMock(),
            runtime_request=runtime_request
        )
        
        assert bootstrap.runtime_request is runtime_request
        assert bootstrap.sources.runtime_request is runtime_request

def test_composition_uses_runtime_request_descriptor(tmp_path, runtime_request):
    # Mock environment variable for checkpoint store root
    with patch.dict("os.environ", {"AGENT_OS_CHECKPOINT_STORE_ROOT": str(tmp_path)}):
        with patch("agent_os_execution_service.production_host_composition.load_invocation_descriptor") as mock_load:
            with patch("agent_os_execution_service.production_host_composition.reconstruct_governed_invocation") as mock_reconstruct:
                
                auth_transport = MagicMock(spec=ExecutionAuthorizationSourceTransport)
                bindings = build_production_governed_resume_bindings(
                    lease_directory=str(tmp_path),
                    route_decision_reader=MagicMock(),
                    handoff_reader=MagicMock(),
                    checkpoint_reader=MagicMock(),
                    resume_plan_reader=MagicMock(),
                    candidate_packet_rebuilder=MagicMock(),
                    runtime_configuration_builder=MagicMock(),
                    pilot_input_builder=MagicMock(),
                    authorization_transport=auth_transport,
                    runtime_configuration_provider=MagicMock(),
                    evaluated_at="2026-08-28T12:00:00Z",
                    cancelled=lambda: False,
                    runtime_request=runtime_request
                )
                
                bindings.reconstruct(HANDOFF_ID)
                
                # Check the descriptor_loader passed to reconstruct_governed_invocation
                args, kwargs = mock_reconstruct.call_args
                descriptor_loader = kwargs['descriptor_loader']
                
                # Strengthening: prove zero standalone descriptor reads
                desc = descriptor_loader(HANDOFF_ID)
                assert desc is runtime_request.invocation_descriptor
                mock_load.assert_not_called()
                
                # Try a different handoff_id, it should fall back to mock_load
                other_id = "executor-handoff:" + "f" * 64
                with patch("agent_os_execution_service.production_host_composition.load_invocation_descriptor") as mock_load_fallback:
                    try:
                        descriptor_loader(other_id)
                    except:
                        pass
                    mock_load_fallback.assert_called_once()
