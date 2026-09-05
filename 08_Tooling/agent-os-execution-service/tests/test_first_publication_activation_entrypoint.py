from __future__ import annotations

from agent_os_execution_service.executor_routing import (
    ExecutorCapability,
    ExecutorHandoff,
    build_executor_handoff,
    executor_handoff_id,
    select_executor_route,
)
from agent_os_execution_service.first_publication_activation_entrypoint import (
    FirstPublicationActivationIdentity,
    activate_and_publish_first_handoff,
)
from agent_os_execution_service.first_publication_producer import FirstPublicationProducerResult

CAPSULE="pre-publication-evidence:"+"a"*64
BOUND="pre-publication-evidence:"+"b"*64
ROUTE="executor-route-decision:"+"c"*64
DEP="dependency-readiness:"+"d"*64
CHECKPOINT="execution-checkpoint:"+"e"*64
PLAN="resume-plan:"+"f"*64
AUTH="execution-authorization:"+"1"*64
SHA="2"*40


def producer()->FirstPublicationProducerResult:
    return FirstPublicationProducerResult(checkpoint_id=CHECKPOINT,resume_plan_id=PLAN,route_decision_id=ROUTE,dependency_readiness_id=DEP,pre_publication_evidence_id=BOUND,authorization_id=AUTH,source_sha=SHA,tested_sha=SHA)


def handoff()->ExecutorHandoff:
    capabilities=(ExecutorCapability.TEST_EXECUTION,)
    decision=select_executor_route(
        repository="Blummer92/agent-os",
        issue_or_handoff_identity="issue:1239",
        requested_operation="first-publication-activation",
        required_capabilities=capabilities,
        governed_runner_capabilities=capabilities,
        governed_runner_available=True,
        external_fallback_available=False,
        external_fallback_explicitly_permitted=False,
        created_at="2026-09-05T22:00:00Z",
        expires_at="2026-09-05T23:00:00Z",
        invalidation_conditions=("authorization-changed","repository-head-changed"),
        execution_service_request_fingerprint_or_none="execution-request:abc123",
        operating_mode_decision_id_or_none="operating-mode:abc123",
        executable_lane_selection_id_or_none="lane-selection:abc123",
        validation_command_plan_id_or_none="command-plan:abc123",
        environment_profile_id_or_none="environment-profile:abc123",
        environment_health_evidence_id_or_none="environment-health:abc123",
        workflow_runtime_identity_or_none="workflow-runtime:abc123",
    )
    return build_executor_handoff(
        decision,
        source_ref_or_none="refs/heads/agent/1239-first-publication-activation",
        source_sha_or_none=SHA,
        allowed_paths=("08_Tooling/agent-os-execution-service",),
        forbidden_paths=(".github/workflows",),
        required_return_evidence=("exact-head-sha","test-results"),
        stop_conditions=("excluded-surface-entered","scope-expanded"),
        environment_profile_id_or_none="environment-profile:abc123",
    )


def test_activation_composes_existing_producer_then_publication_exactly_once()->None:
    calls=[];expected=handoff()
    def activate(identity):
        calls.append(("activate",identity.source_capsule_id));return producer()
    def publish(identity):
        calls.append(("publish",identity.capsule_id,identity.route_decision_id,identity.dependency_readiness_id));return expected
    result=activate_and_publish_first_handoff(FirstPublicationActivationIdentity(source_capsule_id=CAPSULE),activate=activate,publish=publish)
    assert calls==[("activate",CAPSULE),("publish",BOUND,ROUTE,DEP)]
    assert result.handoff_id==executor_handoff_id(expected)
    assert result.publication_invoked is True
    assert result.scheduler_invoked is False
    assert result.execution_lease_acquired is False
    assert result.resume_invoked is False
    assert result.retry_attempted is False
    assert result.provider_fallback_attempted is False


def test_activation_never_publishes_when_producer_fails()->None:
    published=[]
    def activate(_identity): raise ValueError("stale")
    def publish(_identity): published.append(True);return handoff()
    try:
        activate_and_publish_first_handoff(FirstPublicationActivationIdentity(source_capsule_id=CAPSULE),activate=activate,publish=publish)
    except RuntimeError:
        pass
    else:
        raise AssertionError("activation should fail closed")
    assert published==[]


def test_caller_cannot_supply_route_dependency_path_or_authority()->None:
    fields=set(FirstPublicationActivationIdentity.__dataclass_fields__)
    assert fields=={"source_capsule_id"}
