from __future__ import annotations

from agent_os_execution_service.executor_routing import (
    EXECUTOR_ROUTING_SCHEMA_VERSION,
    ExecutorCapability,
    ExecutorHandoff,
    ExecutorRoute,
    executor_handoff_id,
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
    return ExecutorHandoff(schema_version=EXECUTOR_ROUTING_SCHEMA_VERSION,route=ExecutorRoute.CHATGPT_GOVERNED_RUNNER,repository="Blummer92/agent-os",issue_or_handoff_identity="issue:1239",requested_operation="pre-pr-developer-loop",source_sha=SHA,expected_changed_paths=("README.md",),required_tests=("focused",),required_capabilities=(ExecutorCapability.TEST_EXECUTION,),authorization_id=AUTH,checkpoint_id=CHECKPOINT,resume_plan_id=PLAN,execution_service_request_fingerprint="request:"+"3"*64,validation_command_plan_id="command-plan:"+"4"*64,repository_state_evidence_id="repository-state:"+"5"*64,environment_profile_id="environment-profile:"+"6"*64,environment_health_evidence_id="environment-health:"+"7"*64,workflow_runtime_identity="workflow-runtime:production-gce",required_return_evidence=("exact-head-sha",),stop_conditions=("scope-expanded",),created_at="2026-09-05T22:00:00Z",expires_at="2026-09-05T23:00:00Z")


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
