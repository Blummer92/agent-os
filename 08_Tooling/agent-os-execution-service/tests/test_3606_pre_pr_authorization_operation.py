"""Functional #3606 coverage: one pre-PR authorization operation end to end.

The publisher (#1411), the route producer (#1930) and the trusted-host
validation caller (#1929) must reacquire the owner execution authorization
with the same operation the canonical resolver (#1218) later demands for the
published descriptor: the route's ``pre-pr-developer-loop``. The #757
lifecycle permitted operation (``validation-only``) is a different field and
stays unchanged.

These tests drive the real entrypoints with the real
``reacquire_execution_authorization`` reading a fake owner-comment transport.
Only the evidence-rebuild stages that need live GitHub/repository/host state
are replaced, and each replacement is listed in ``_stub_publisher_stages``,
``_producer_case`` and ``_caller_case``.
"""
from __future__ import annotations

import ast
import inspect
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from types import SimpleNamespace

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXEC_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
TESTS_DIR = Path(__file__).resolve().parent
for _path in (REPOSITORY_ROOT, EXEC_SERVICE_SRC, SCHEDULER_SRC, TESTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from test_validation_lifecycle_evidence import _admission_request  # noqa: E402

import agent_os_execution_service.authorized_validation_entrypoint as entrypoint  # noqa: E402
import agent_os_execution_service.current_invocation_resolver as resolver_module  # noqa: E402
import agent_os_execution_service.execution_authorization_source as source_module  # noqa: E402
import agent_os_execution_service.first_publication_host_observation as producer  # noqa: E402
import agent_os_execution_service.production_authorized_validation_caller as caller  # noqa: E402
import agent_os_execution_service.production_handoff_publication as publication  # noqa: E402
import scripts.agent_os_candidate_packet.execution_packet_stage as execution_packet_stage  # noqa: E402
from agent_os_execution_service.authorization import ExecutionAuthorizationEvidence  # noqa: E402
from agent_os_execution_service.authorized_validation import (  # noqa: E402
    AUTHORIZED_VALIDATION_PERMITTED_OPERATION,
    AUTHORIZED_VALIDATION_VNEXT_SCHEMA_VERSION,
    AuthorizedValidationAdmissionStatus,
    verify_authorized_validation_admission,
)
from agent_os_execution_service.current_invocation_resolver import (  # noqa: E402
    CanonicalCurrentInvocationResolver,
    CurrentInvocationResolutionError,
    build_current_invocation_descriptor,
)
from agent_os_execution_service.execution_authorization_source import (  # noqa: E402
    ExecutionAuthorizationCommentSnapshot,
    ExecutionAuthorizationSourceReason,
    ExecutionAuthorizationSourceSnapshot,
    ExecutionAuthorizationSourceStatus,
    execution_authorization_id,
    reacquire_execution_authorization,
    serialize_execution_authorization_comment,
)
from agent_os_execution_service.executor_routing import (  # noqa: E402
    ExecutorCapability,
    ExecutorHandoff,
    ExecutorRoute,
    build_executor_handoff,
    select_executor_route,
)
from agent_os_execution_service.first_publication_host_observation import (  # noqa: E402
    FirstPublicationActivationIdentity,
    FirstPublicationHostObservationError,
)
from agent_os_execution_service.production_authorized_validation_caller import (  # noqa: E402
    ProductionAuthorizedValidationCallerError,
)
from agent_os_execution_service.production_handoff_publication import (  # noqa: E402
    PRE_PR_DEVELOPER_LOOP_OPERATION,
    ProductionHandoffPublicationError,
    ProductionHandoffPublicationIdentity,
    publish_production_handoff,
)
from agent_os_execution_service.production_host_bootstrap import (  # noqa: E402
    ProductionHostConfiguration,
)
from scripts.agent_os_candidate_packet_live_input.issue_reader import (  # noqa: E402
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
)
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (  # noqa: E402
    GovernedInvocationDescriptor,
    append_invocation_descriptor,
    load_invocation_descriptor,
)

# The #757/#761 compiled fixture is accepted at this instant (window 12:05-13:05).
NOW = "2026-08-11T12:10:00Z"
AUTHORIZED_AT = "2026-08-11T12:05:00Z"
EXPIRES_AT = "2026-08-11T13:05:00Z"
OWNER = "Blummer92"
CHECKPOINT_ID = "agent-os.execution-checkpoint:" + "1" * 64
RESUME_PLAN_ID = "agent-os.execution-checkpoint.resume-plan:" + "2" * 64
HEALTH_ID = "environment-health:" + "3" * 64
REQUIRED_ENVIRONMENT_ID = "required-environment:" + "4" * 64
READINESS_ID = "dependency-readiness:" + "5" * 64
PROJECTION_ID = "approved-execution-projection:" + "6" * 64
IDENTITY = ProductionHandoffPublicationIdentity(
    capsule_id="pre-publication-evidence:" + "a" * 64,
    route_decision_id="executor-route-decision:" + "b" * 64,
    dependency_readiness_id="dependency-readiness:" + "c" * 64,
)
RESERVED_PROBE_OPERATION = "codespace-implementation-pilot-v1"
RESERVED_PROBE_COMMENT_ID = 6176889694


class _ReachedPastAuthorization(Exception):
    """Raised by the first stage after the authorization gate (not fail-closed-caught)."""


# --------------------------------------------------------------------------
# Real compiled #757 fixture, owner records, and a fake owner-comment transport.
# --------------------------------------------------------------------------


def _subdir(tmp_path, name):
    path = tmp_path / name
    path.mkdir()
    return path


def _fixture(tmp_path):
    request = _admission_request(_subdir(tmp_path, "compiled-fixture"))
    return SimpleNamespace(
        packet=request.candidate_packet,
        approval=request.approval_stage,
        execution=request.execution_packet_stage,
    )


def _record(fixture, **changes):
    packet = fixture.packet
    values = {
        "issue_number": packet.issue_number,
        "authorizer_id": OWNER,
        "authorized_candidate_packet_id": packet.packet_id,
        "authorized_invocation_id": packet.invocation_id,
        "authorized_operation": PRE_PR_DEVELOPER_LOOP_OPERATION,
        "request_fingerprint": fixture.execution.request_fingerprint,
        "command_plan_id": fixture.execution.command_plan_id,
        "repository": packet.repository,
        "expected_sha": packet.candidate_sha,
        "authorized_at": AUTHORIZED_AT,
        "expires_at": EXPIRES_AT,
        "execution_authorized": True,
    }
    values.update(changes)
    return values


def _evidence(values) -> ExecutionAuthorizationEvidence:
    return ExecutionAuthorizationEvidence(
        authorization_id=execution_authorization_id(**values),
        request_fingerprint=values["request_fingerprint"],
        command_plan_id=values["command_plan_id"],
        repository=values["repository"],
        expected_sha=values["expected_sha"],
        authorized_at=values["authorized_at"],
        expires_at=values["expires_at"],
        execution_authorized=values["execution_authorized"],
    )


class _OwnerCommentTransport:
    """Serves owner-authored comments; also the single-issue read #1930 needs."""

    def __init__(self, packet, bodies) -> None:
        self.repository = packet.repository
        self.issue_number = packet.issue_number
        self.comments = tuple(
            ExecutionAuthorizationCommentSnapshot(
                comment_id=index + 1,
                author_login=OWNER,
                created_at=f"2026-08-11T12:0{6 + index}:00Z",
                body=body,
            )
            for index, body in enumerate(bodies)
        )
        self.authorization_reads: list[tuple[str, int]] = []

    def read_authorization_source(self, repository, issue_number):
        self.authorization_reads.append((repository, issue_number))
        return ExecutionAuthorizationSourceSnapshot(
            repository=self.repository,
            issue_number=self.issue_number,
            owner_login=OWNER,
            owner_type="User",
            comments_complete=True,
            comments=self.comments,
        )

    def get_issue(self, repository, issue_number):
        return SingleIssueTransportResult(
            outcome=SingleIssueTransportOutcome.OK,
            item={"number": issue_number, "state": "open", "body": "## Acceptance criteria\n- x"},
        )


def _transport(fixture, *records):
    return _OwnerCommentTransport(
        fixture.packet,
        tuple(serialize_execution_authorization_comment(**values) for values in records),
    )


class _SignatureBindingSpy:
    """Wrap the real reacquisition and bind every call against its real signature."""

    def __init__(self) -> None:
        self.real = reacquire_execution_authorization
        self.signature = inspect.signature(self.real)
        self.bound: list[dict[str, object]] = []
        self.bind_errors: list[str] = []
        self.results: list[object] = []

    def __call__(self, *args, **kwargs):
        try:
            arguments = self.signature.bind(*args, **kwargs).arguments
        except TypeError as exc:
            self.bind_errors.append(f"{exc} (positional={len(args)})")
            raise
        self.bound.append(dict(arguments))
        result = self.real(*args, **kwargs)
        self.results.append(result)
        return result


def _configuration(tmp_path) -> ProductionHostConfiguration:
    root = tmp_path / "host"
    return ProductionHostConfiguration(
        checkpoint_store_root=root / "checkpoints",
        repository_root=root / "repository",
        workspace_parent=root / "workspaces",
        lease_directory=root / "leases",
        delegated_parent_cgroup=None,
        repository_host="github.com",
    )


def _route(fixture, authorization_id, *, operation=PRE_PR_DEVELOPER_LOOP_OPERATION):
    packet = fixture.packet
    return select_executor_route(
        repository=packet.repository,
        issue_or_handoff_identity=f"issue:{packet.issue_number}",
        requested_operation=operation,
        required_capabilities=(ExecutorCapability.CHECKOUT,),
        governed_runner_capabilities=(ExecutorCapability.CHECKOUT,),
        governed_runner_available=True,
        external_fallback_available=False,
        external_fallback_explicitly_permitted=False,
        created_at="2026-08-11T12:00:00Z",
        expires_at="2026-08-11T14:00:00Z",
        invalidation_conditions=("repository-head-changed",),
        execution_service_request_fingerprint_or_none=fixture.execution.request_fingerprint,
        authorization_id_or_none=authorization_id,
        validation_command_plan_id_or_none=fixture.execution.command_plan_id,
        operating_mode_decision_id_or_none="operating-mode:3606",
        executable_lane_selection_id_or_none="lane-selection:3606",
        environment_profile_id_or_none="environment-profile:3606",
        environment_health_evidence_id_or_none=HEALTH_ID,
        checkpoint_id_or_none=CHECKPOINT_ID,
        resume_plan_id_or_none=RESUME_PLAN_ID,
        workflow_runtime_identity_or_none="workflow-runtime:3606",
        execution_authorized=True,
    )


def _host_objects(fixture):
    packet = fixture.packet
    checkpoint = SimpleNamespace(
        checkpoint_id=CHECKPOINT_ID,
        repository=packet.repository,
        issue_number=packet.issue_number,
        invocation_id=packet.invocation_id,
        execution_id="execution-3606",
        source_sha=packet.candidate_sha,
        tested_sha=packet.tested_sha,
    )
    readiness = SimpleNamespace(
        required_environment_id=REQUIRED_ENVIRONMENT_ID,
        dependency_readiness_evidence_id=READINESS_ID,
        environment_health_evidence_id=HEALTH_ID,
        execution_surface_id="execution-surface:gce-agent-os-test",
        source_sha=packet.candidate_sha,
        is_current=lambda _now: True,
    )
    pilot = SimpleNamespace(
        workspace_request_id="workspace-3606",
        repository=packet.repository,
        branch=fixture.execution.request.requested_ref,
        source_head_sha=packet.candidate_sha,
    )
    resume_plan = SimpleNamespace(plan_id=RESUME_PLAN_ID)
    return checkpoint, resume_plan, readiness, pilot


def _persist_descriptor(store_root, *, route_decision, handoff, authorization, checkpoint,
                        resume_plan, candidate_packet, runtime_configuration,
                        dependency_readiness, pilot_input) -> GovernedInvocationDescriptor:
    descriptor = build_current_invocation_descriptor(
        route_decision=route_decision,
        handoff=handoff,
        authorization=authorization,
        checkpoint=checkpoint,
        resume_plan=resume_plan,
        candidate_packet=candidate_packet,
        runtime_configuration=runtime_configuration,
        dependency_readiness=dependency_readiness,
        pilot_input=pilot_input,
    )
    append_invocation_descriptor(store_root, descriptor)
    return descriptor


# --------------------------------------------------------------------------
# Publisher (#1411) case.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _RuntimeInputs:
    """Stands in for CandidateRuntimeInputs; ``dataclasses.replace`` must work."""

    execution_authorization_present: bool


def _stub_publisher_stages(monkeypatch, fixture, route, checkpoint, resume_plan, readiness, pilot):
    """Replace only stages that need live host/GitHub/repository evidence.

    Stubbed: the five durable-store loaders (no real capsule/checkpoint store
    can be produced offline), advisory/observation/candidate rebuilds and the
    approval rebuild (they need live issue and git verifier output), runtime
    inputs + ``prepare_execution_packet`` (return the real compiled execution
    stage), and ``_pilot_input`` (needs a full SingleIssuePilotInput).
    Real: ``reacquire_execution_authorization``, ``_bundle_payload``,
    ``build_authorized_validation_lifecycle_request``,
    ``publish_authorized_validation_handoff`` (including the real #757
    admission), ``build_executor_handoff``, ``build_current_invocation_descriptor``
    and ``append_invocation_descriptor``.
    """
    packet = fixture.packet
    capsule = SimpleNamespace(
        candidate_packet=packet,
        checkpoint_id=CHECKPOINT_ID,
        validation_bundle_json="{}",
        required_environment_spec=SimpleNamespace(required_environment_id=REQUIRED_ENVIRONMENT_ID),
        validation_plan_id="validation-plan:3606",
    )
    monkeypatch.setattr(publication, "load_pre_publication_evidence", lambda _root, _id: capsule)
    monkeypatch.setattr(publication, "load_route_decision", lambda _root, _id: route)
    monkeypatch.setattr(publication, "load_checkpoint_by_id", lambda _root, _issue, _id: checkpoint)
    monkeypatch.setattr(publication, "load_resume_plan", lambda _root, _id: resume_plan)
    monkeypatch.setattr(publication, "load_dependency_readiness", lambda _root, _id: readiness)
    monkeypatch.setattr(publication, "_rebuild_advisory", lambda *_args: object())
    monkeypatch.setattr(publication, "LiveRepositoryEvidenceReader", lambda **_kwargs: object())
    monkeypatch.setattr(
        publication, "_repository_observation", lambda **_kwargs: SimpleNamespace(base_sha=packet.base_sha)
    )
    monkeypatch.setattr(publication, "LiveIssueReader", lambda _github: object())
    monkeypatch.setattr(publication, "post_approval_dependency_identity_evidence", lambda **_kwargs: None)
    monkeypatch.setattr(publication, "prepare_candidate_packet", lambda **_kwargs: object())
    monkeypatch.setattr(
        publication,
        "_rebuild_approval",
        lambda *_args: (fixture.approval, object(), object(), object()),
    )
    monkeypatch.setattr(
        publication,
        "_runtime_inputs",
        lambda **kwargs: _RuntimeInputs(
            execution_authorization_present=kwargs["authorization_present"]
        ),
    )
    stage_inputs: list[bool] = []

    def prepare(_approval, inputs):
        stage_inputs.append(inputs.execution_authorization_present)
        return fixture.execution

    monkeypatch.setattr(publication, "prepare_execution_packet", prepare)
    monkeypatch.setattr(publication, "_pilot_input", lambda **_kwargs: pilot)
    return stage_inputs


def _publisher_case(tmp_path, monkeypatch, *, records, route_record=None):
    fixture = _fixture(tmp_path)
    records = tuple(_record(fixture, **changes) for changes in records)
    bound = records[0] if route_record is None else _record(fixture, **route_record)
    route = _route(fixture, execution_authorization_id(**bound))
    checkpoint, resume_plan, readiness, pilot = _host_objects(fixture)
    stage_inputs = _stub_publisher_stages(
        monkeypatch, fixture, route, checkpoint, resume_plan, readiness, pilot
    )
    spy = _SignatureBindingSpy()
    monkeypatch.setattr(publication, "reacquire_execution_authorization", spy)
    configuration = _configuration(tmp_path)
    published: list[dict[str, object]] = []

    def publish_governed_handoff(store_root, **kwargs):
        # #1243 stand-in: the real seam needs a persisted ExecutionCheckpoint,
        # ResumePlan, DependencyReadinessEvidence, a bound RequiredEnvironmentSpec
        # and a full SingleIssuePilotInput, none of which the compiled fixture has.
        request = kwargs["request"]
        handoff = build_executor_handoff(
            kwargs["route_decision"],
            source_ref_or_none=request.requested_ref,
            source_sha_or_none=request.expected_sha,
            allowed_paths=request.allowed_paths,
            forbidden_paths=request.forbidden_paths,
            required_return_evidence=kwargs["required_return_evidence"],
            stop_conditions=kwargs["stop_conditions"],
            checkpoint_id_or_none=kwargs["checkpoint"].checkpoint_id,
            resume_plan_id_or_none=kwargs["resume_plan"].plan_id,
            environment_profile_id_or_none=kwargs["route_decision"].environment_profile_id_or_none,
        )
        descriptor = _persist_descriptor(
            store_root,
            route_decision=kwargs["route_decision"],
            handoff=handoff,
            authorization=kwargs["authorization"],
            checkpoint=kwargs["checkpoint"],
            resume_plan=kwargs["resume_plan"],
            candidate_packet=kwargs["candidate_packet"],
            runtime_configuration=kwargs["runtime_configuration"],
            dependency_readiness=kwargs["dependency_readiness"],
            pilot_input=kwargs["pilot_input"],
        )
        published.append({"store_root": store_root, "handoff": handoff, "descriptor": descriptor, **kwargs})
        return handoff

    monkeypatch.setattr(entrypoint, "publish_governed_handoff", publish_governed_handoff)
    transport = _transport(fixture, *records)
    return SimpleNamespace(
        fixture=fixture,
        records=records,
        route=route,
        checkpoint=checkpoint,
        resume_plan=resume_plan,
        readiness=readiness,
        pilot=pilot,
        spy=spy,
        configuration=configuration,
        transport=transport,
        published=published,
        stage_inputs=stage_inputs,
    )


def _publish(case):
    return publish_production_handoff(
        IDENTITY,
        configuration=case.configuration,
        evaluated_at=NOW,
        transport=case.transport,
        run_verifier=lambda _invocation: "",
    )


class _Sources:
    """InvocationEvidenceSources over the exact objects the publication used."""

    def __init__(self, *, route, handoff, checkpoint, resume_plan, packet, runtime, readiness, pilot):
        self._values = (route, handoff, checkpoint, resume_plan, packet, runtime, readiness, pilot)
        self.pilot_calls: list[dict[str, object]] = []

    def route_decision(self, _descriptor):
        return self._values[0]

    def handoff(self, _descriptor, _route):
        return self._values[1]

    def checkpoint(self, _descriptor):
        return self._values[2]

    def resume_plan(self, _descriptor, _checkpoint):
        return self._values[3]

    def candidate_packet(self, _descriptor):
        return self._values[4]

    def runtime_configuration(self, _descriptor, _packet):
        return self._values[5]

    def dependency_readiness(self, _descriptor):
        return self._values[6]

    def pilot_input(self, _descriptor, **kwargs):
        self.pilot_calls.append(kwargs)
        return self._values[7]


def _resolve(monkeypatch, case, *, route, handoff, descriptor, transport):
    # #1218 convention: the exact-type wrapper is bypassed because checkpoint,
    # resume plan, readiness and pilot are host-shaped stand-ins here; the
    # authorization reacquisition under test is the real one.
    monkeypatch.setattr(resolver_module, "CurrentInvocationEvidence", SimpleNamespace)
    sources = _Sources(
        route=route,
        handoff=handoff,
        checkpoint=case.checkpoint,
        resume_plan=case.resume_plan,
        packet=case.fixture.packet,
        runtime=case.fixture.execution.runtime_configuration,
        readiness=case.readiness,
        pilot=case.pilot,
    )
    resolver = CanonicalCurrentInvocationResolver(
        sources=sources, authorization_transport=transport, evaluated_at=NOW
    )
    return resolver.reacquire(descriptor), sources


# --------------------------------------------------------------------------
# Deliverables 1 + 2: D1 regression and publisher success path.
# --------------------------------------------------------------------------


def test_publisher_reacquires_with_keyword_transport_and_pre_pr_operation(tmp_path, monkeypatch):
    case = _publisher_case(tmp_path, monkeypatch, records=({},))

    handoff = _publish(case)

    assert case.spy.bind_errors == [], (
        "publish_production_handoff called reacquire_execution_authorization with "
        f"arguments its real signature rejects: {case.spy.bind_errors}"
    )
    assert len(case.spy.bound) == 1
    call = case.spy.bound[0]
    assert call["transport"] is case.transport
    assert call["expected_operation"] == PRE_PR_DEVELOPER_LOOP_OPERATION
    assert call["expected_authorization_id"] == case.route.authorization_id_or_none
    assert case.transport.authorization_reads == [
        (case.fixture.packet.repository, case.fixture.packet.issue_number)
    ]
    assert type(handoff) is ExecutorHandoff


def test_current_pre_pr_record_publishes_one_persisted_handoff(tmp_path, monkeypatch):
    case = _publisher_case(tmp_path, monkeypatch, records=({},))

    handoff = _publish(case)

    assert type(handoff) is ExecutorHandoff
    assert handoff.destination_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER
    assert handoff.requested_operation == PRE_PR_DEVELOPER_LOOP_OPERATION
    assert handoff.authorization_id_or_none == execution_authorization_id(**case.records[0])
    assert case.stage_inputs == [False, True]
    assert len(case.published) == 1
    published = case.published[0]
    assert published["handoff"] is handoff
    assert published["store_root"] == case.configuration.checkpoint_store_root
    assert published["authorization"] == _evidence(case.records[0])
    loaded = load_invocation_descriptor(case.configuration.checkpoint_store_root, handoff.handoff_id)
    assert loaded == published["descriptor"]
    assert loaded.authorization_id == handoff.authorization_id_or_none


# --------------------------------------------------------------------------
# Deliverable 3: D2 negatives at each call site.
# --------------------------------------------------------------------------

_EXPIRED = {"expires_at": "2026-08-11T12:08:00Z"}
_NEGATIVES = {
    "validation-only-operation": (
        ({"authorized_operation": AUTHORIZED_VALIDATION_PERMITTED_OPERATION},),
        None,
        ExecutionAuthorizationSourceReason.BINDING_MISMATCH,
    ),
    "other-operation": (
        ({"authorized_operation": "coding"},),
        None,
        ExecutionAuthorizationSourceReason.BINDING_MISMATCH,
    ),
    "expired": ((_EXPIRED,), None, ExecutionAuthorizationSourceReason.AUTHORIZATION_EXPIRED),
    "revoked-by-newer-record": (
        ({}, {"execution_authorized": False}),
        {},
        ExecutionAuthorizationSourceReason.AUTHORIZATION_REVOKED,
    ),
    "wrong-sha": (({"expected_sha": "e" * 40},), None, ExecutionAuthorizationSourceReason.BINDING_MISMATCH),
}
_SUPERSEDED = (
    ({}, {"expires_at": "2026-08-11T13:30:00Z"}),
    {},
    ExecutionAuthorizationSourceReason.AUTHORIZATION_SUPERSEDED,
)
_BOUND_NEGATIVES = {**_NEGATIVES, "superseded-by-newer-record": _SUPERSEDED}


@pytest.mark.parametrize("name", sorted(_BOUND_NEGATIVES))
def test_publisher_fails_closed_on_non_current_authorization(tmp_path, monkeypatch, name):
    records, route_record, reason = _BOUND_NEGATIVES[name]
    case = _publisher_case(tmp_path, monkeypatch, records=records, route_record=route_record)

    with pytest.raises(ProductionHandoffPublicationError) as raised:
        _publish(case)

    assert raised.value.args == ("execution-authorization-not-current",)
    assert case.spy.bind_errors == []
    assert case.spy.results[0].reason_codes == (reason,)
    assert case.spy.results[0].status is not ExecutionAuthorizationSourceStatus.CURRENT
    assert case.published == []
    assert case.stage_inputs == [False]


def _producer_case(tmp_path, monkeypatch, *, records):
    """#1930: stub host/GitHub-only rebuild stages; keep the real reacquisition.

    The first stage after the authorization gate (``verify_exact_lineage``)
    raises ``_ReachedPastAuthorization`` so a CURRENT authorization is observed
    without live lineage, git, governance or #1428 evidence.
    """
    fixture = _fixture(tmp_path)
    records = tuple(_record(fixture, **changes) for changes in records)
    packet = fixture.packet
    source = SimpleNamespace(
        capsule_id="pre-publication-evidence:" + "d" * 64,
        candidate_branch=fixture.execution.request.requested_ref,
        expires_at="2026-08-11T14:00:00Z",
        candidate_packet=packet,
        validation_bundle_json="{}",
        required_environment_spec=SimpleNamespace(required_environment_id=REQUIRED_ENVIRONMENT_ID),
        validation_plan_id="validation-plan:3606",
    )
    _checkpoint, _resume, readiness, _pilot = _host_objects(fixture)
    monkeypatch.setattr(producer, "load_source_pre_publication_evidence", lambda _root, _id: source)
    monkeypatch.setattr(producer, "_rebuild_advisory", lambda *_args: object())
    monkeypatch.setattr(producer, "_select_dependency_readiness", lambda _root, **_kwargs: readiness)
    monkeypatch.setattr(producer, "LiveRepositoryEvidenceReader", lambda **_kwargs: object())
    monkeypatch.setattr(
        producer, "_repository_observation", lambda **_kwargs: SimpleNamespace(base_sha=packet.base_sha)
    )
    monkeypatch.setattr(producer, "LiveIssueReader", lambda _transport: object())
    monkeypatch.setattr(producer, "post_approval_dependency_identity_evidence", lambda **_kwargs: None)
    monkeypatch.setattr(producer, "prepare_candidate_packet", lambda **_kwargs: object())
    monkeypatch.setattr(
        producer, "_rebuild_approval", lambda *_args: (fixture.approval, object(), object(), object())
    )
    monkeypatch.setattr(producer, "_runtime_inputs", lambda **_kwargs: object())
    monkeypatch.setattr(
        execution_packet_stage, "prepare_execution_packet", lambda _approval, _inputs: fixture.execution
    )

    def past_authorization(*_args, **_kwargs):
        raise _ReachedPastAuthorization

    monkeypatch.setattr(producer, "verify_exact_lineage", past_authorization)
    spy = _SignatureBindingSpy()
    monkeypatch.setattr(producer, "reacquire_execution_authorization", spy)
    return SimpleNamespace(
        fixture=fixture,
        spy=spy,
        configuration=_configuration(tmp_path),
        transport=_transport(fixture, *records),
    )


def _activate(case):
    return producer.activate_first_publication_from_host(
        FirstPublicationActivationIdentity(source_capsule_id="pre-publication-evidence:" + "d" * 64),
        configuration=case.configuration,
        evaluated_at=NOW,
        transport=case.transport,
        run_verifier=lambda _invocation: "",
        run_command=lambda _cwd, _argv: "",
        governance_blob_reader=lambda _repository, _revision, _path: "0" * 40,
    )


def test_route_producer_passes_the_gate_only_for_a_current_pre_pr_record(tmp_path, monkeypatch):
    case = _producer_case(tmp_path, monkeypatch, records=({},))

    with pytest.raises(_ReachedPastAuthorization):
        _activate(case)

    assert case.spy.bind_errors == []
    assert case.spy.bound[0]["transport"] is case.transport
    assert case.spy.bound[0]["expected_operation"] == PRE_PR_DEVELOPER_LOOP_OPERATION
    assert case.spy.results[0].status is ExecutionAuthorizationSourceStatus.CURRENT


@pytest.mark.parametrize("name", sorted(_NEGATIVES))
def test_route_producer_fails_closed_on_non_current_authorization(tmp_path, monkeypatch, name):
    records, _route_record, reason = _NEGATIVES[name]
    case = _producer_case(tmp_path, monkeypatch, records=records)

    with pytest.raises(FirstPublicationHostObservationError) as raised:
        _activate(case)

    assert raised.value.args == ("execution-authorization-not-current",)
    assert case.spy.results[0].reason_codes == (reason,)


def _caller_case(tmp_path, monkeypatch, *, records, request_record=None):
    """#1929: the v1.1 envelope reconstruction is stubbed (the compiled fixture
    has no bound RequiredEnvironmentSpec); the request still carries the exact
    evidence of the record it was issued under, and reacquisition is real."""
    fixture = _fixture(tmp_path)
    records = tuple(_record(fixture, **changes) for changes in records)
    bound = records[0] if request_record is None else _record(fixture, **request_record)
    packet = fixture.packet
    runtime = SimpleNamespace(
        required_environment_spec=object(),
        validation_plan_id="validation-plan:3606",
        validation_bundle_id="validation-bundle:3606",
        advisory_result_id="advisory-result:3606",
        advisory_render_id="advisory-render:3606",
        branch=fixture.execution.request.requested_ref,
        workspace_request_id="workspace-3606",
        verify=lambda _pilot: None,
    )
    projection = SimpleNamespace(projection_id=PROJECTION_ID)
    request = SimpleNamespace(
        schema_version=AUTHORIZED_VALIDATION_VNEXT_SCHEMA_VERSION,
        candidate_packet=packet,
        execution_packet_stage=SimpleNamespace(runtime_configuration=runtime),
        approval_stage=SimpleNamespace(decision_revision=object(), projection=projection),
        execution_authorization=_evidence(bound),
        authorizer_id=OWNER,
    )
    monkeypatch.setattr(caller, "reconstruct_authorized_validation_lifecycle_request", lambda _payload: request)
    monkeypatch.setattr(caller, "pilot_reconstruction_evidence", lambda _request: (object(), ()))
    monkeypatch.setattr(caller, "serialize_validation_evidence_bundle", lambda _bundle: {})
    monkeypatch.setattr(caller, "_rebuild_advisory", lambda *_args: object())
    monkeypatch.setattr(caller, "LiveRepositoryEvidenceReader", lambda **_kwargs: object())
    monkeypatch.setattr(
        caller, "_repository_observation", lambda **_kwargs: SimpleNamespace(base_sha=packet.base_sha)
    )
    monkeypatch.setattr(caller, "LiveIssueReader", lambda _github: object())
    monkeypatch.setattr(caller, "post_approval_dependency_identity_evidence", lambda **_kwargs: None)
    monkeypatch.setattr(caller, "prepare_candidate_packet", lambda **_kwargs: object())
    monkeypatch.setattr(
        caller,
        "_rebuild_approval",
        lambda *_args: (SimpleNamespace(projection=projection), object(), object(), object()),
    )
    monkeypatch.setattr(caller, "_pilot_input", lambda **_kwargs: object())
    delegated: list[dict[str, object]] = []
    returned = object()

    def delegate(**kwargs):
        delegated.append(kwargs)
        return returned

    monkeypatch.setattr(caller, "run_production_authorized_validation_with_source_capture", delegate)
    spy = _SignatureBindingSpy()
    monkeypatch.setattr(caller, "reacquire_execution_authorization", spy)
    return SimpleNamespace(
        fixture=fixture,
        request=request,
        spy=spy,
        delegated=delegated,
        returned=returned,
        configuration=_configuration(tmp_path),
        transport=_transport(fixture, *records),
    )


def _run_caller(case):
    return caller.run_production_authorized_validation(
        {"envelope": "stubbed"},
        cancelled=lambda: False,
        configuration=case.configuration,
        evaluated_at=NOW,
        transport=case.transport,
        run_verifier=lambda _invocation: "",
    )


def test_validation_caller_delegates_once_for_a_current_pre_pr_record(tmp_path, monkeypatch):
    case = _caller_case(tmp_path, monkeypatch, records=({},))

    assert _run_caller(case) is case.returned

    assert case.spy.bind_errors == []
    assert case.spy.bound[0]["transport"] is case.transport
    assert case.spy.bound[0]["expected_operation"] == PRE_PR_DEVELOPER_LOOP_OPERATION
    assert case.spy.results[0].evidence == case.request.execution_authorization
    assert len(case.delegated) == 1
    assert case.delegated[0]["admission_request"] is case.request


@pytest.mark.parametrize("name", sorted(_BOUND_NEGATIVES))
def test_validation_caller_fails_closed_on_non_current_authorization(tmp_path, monkeypatch, name):
    records, request_record, reason = _BOUND_NEGATIVES[name]
    case = _caller_case(tmp_path, monkeypatch, records=records, request_record=request_record)

    with pytest.raises(ProductionAuthorizedValidationCallerError) as raised:
        _run_caller(case)

    assert raised.value.args == ("execution-authorization-not-current",)
    assert case.spy.results[0].reason_codes == (reason,)
    assert case.delegated == []


# --------------------------------------------------------------------------
# Deliverable 4: publication-to-resolver integration.
# --------------------------------------------------------------------------


def test_published_descriptor_resolves_current_through_the_real_resolver(tmp_path, monkeypatch):
    case = _publisher_case(tmp_path, monkeypatch, records=({},))
    handoff = _publish(case)
    published = case.published[0]
    descriptor = load_invocation_descriptor(case.configuration.checkpoint_store_root, handoff.handoff_id)

    current, sources = _resolve(
        monkeypatch,
        case,
        route=published["route_decision"],
        handoff=handoff,
        descriptor=descriptor,
        transport=case.transport,
    )

    assert current.authorization == published["authorization"]
    assert current.authorization.authorization_id == descriptor.authorization_id
    assert current.handoff is handoff
    assert len(sources.pilot_calls) == 1
    assert len(case.transport.authorization_reads) == 2


def test_validation_only_record_is_rejected_by_publisher_and_resolver_alike(tmp_path, monkeypatch):
    validation_only = {"authorized_operation": AUTHORIZED_VALIDATION_PERMITTED_OPERATION}
    case = _publisher_case(tmp_path, monkeypatch, records=(validation_only,))

    # Before #3606 the publisher accepted this record and persisted a descriptor
    # the resolver could never reacquire (binding-mismatch). Both must now agree.
    with pytest.raises(ProductionHandoffPublicationError) as raised:
        _publish(case)
    assert raised.value.args == ("execution-authorization-not-current",)
    assert case.published == []

    request = case.fixture.execution.request
    handoff = build_executor_handoff(
        case.route,
        source_ref_or_none=request.requested_ref,
        source_sha_or_none=request.expected_sha,
        allowed_paths=request.allowed_paths,
        forbidden_paths=request.forbidden_paths,
        required_return_evidence=publication.REQUIRED_RETURN_EVIDENCE,
        stop_conditions=publication.STOP_CONDITIONS,
        checkpoint_id_or_none=CHECKPOINT_ID,
        resume_plan_id_or_none=RESUME_PLAN_ID,
        environment_profile_id_or_none=case.route.environment_profile_id_or_none,
    )
    descriptor = _persist_descriptor(
        tmp_path / "resolver-store",
        route_decision=case.route,
        handoff=handoff,
        authorization=_evidence(case.records[0]),
        checkpoint=case.checkpoint,
        resume_plan=case.resume_plan,
        candidate_packet=case.fixture.packet,
        runtime_configuration=case.fixture.execution.runtime_configuration,
        dependency_readiness=case.readiness,
        pilot_input=case.pilot,
    )
    with pytest.raises(CurrentInvocationResolutionError, match="binding-mismatch"):
        _resolve(monkeypatch, case, route=case.route, handoff=handoff, descriptor=descriptor,
                 transport=case.transport)


# --------------------------------------------------------------------------
# Deliverable 5: the #757 permitted-action boundary is a different field.
# --------------------------------------------------------------------------


def test_record_operation_and_lifecycle_permitted_operation_are_different_fields(tmp_path):
    fixture = _fixture(tmp_path)
    transport = _transport(fixture, _record(fixture))
    read = reacquire_execution_authorization(
        transport=transport,
        repository=fixture.packet.repository,
        issue_number=fixture.packet.issue_number,
        expected_candidate_packet_id=fixture.packet.packet_id,
        expected_invocation_id=fixture.packet.invocation_id,
        expected_operation=PRE_PR_DEVELOPER_LOOP_OPERATION,
        expected_request_fingerprint=fixture.execution.request_fingerprint,
        expected_command_plan_id=fixture.execution.command_plan_id,
        expected_sha=fixture.packet.candidate_sha,
        evaluated_at=NOW,
    )
    assert read.status is ExecutionAuthorizationSourceStatus.CURRENT
    assert read.authorized_operation == PRE_PR_DEVELOPER_LOOP_OPERATION
    assert "authorized_operation" not in {item.name for item in fields(ExecutionAuthorizationEvidence)}

    # The pre-pr record's evidence admits a validation-only lifecycle request...
    accepted = _admission_request(_subdir(tmp_path, "accepted"), execution_authorization=read.evidence)
    assert accepted.authorized_operation == AUTHORIZED_VALIDATION_PERMITTED_OPERATION
    result = verify_authorized_validation_admission(accepted, evaluated_at=NOW)
    assert result.status is AuthorizedValidationAdmissionStatus.ACCEPTED

    # ...but copying the record operation into the lifecycle field is blocked.
    aliased = _admission_request(
        _subdir(tmp_path, "aliased"),
        execution_authorization=read.evidence,
        authorized_operation=PRE_PR_DEVELOPER_LOOP_OPERATION,
    )
    blocked = verify_authorized_validation_admission(aliased, evaluated_at=NOW)
    assert blocked.status is AuthorizedValidationAdmissionStatus.BLOCKED
    assert blocked.reason_codes == ("authorization.operation-not-permitted",)


def test_published_lifecycle_request_keeps_validation_only_operation(tmp_path, monkeypatch):
    case = _publisher_case(tmp_path, monkeypatch, records=({},))
    admitted = []
    real_admission = entrypoint.verify_authorized_validation_admission

    def capture(request, *, evaluated_at):
        admitted.append(request)
        return real_admission(request, evaluated_at=evaluated_at)

    monkeypatch.setattr(entrypoint, "verify_authorized_validation_admission", capture)
    _publish(case)

    assert len(admitted) == 1
    assert admitted[0].authorized_operation == AUTHORIZED_VALIDATION_PERMITTED_OPERATION
    assert case.records[0]["authorized_operation"] == PRE_PR_DEVELOPER_LOOP_OPERATION


# --------------------------------------------------------------------------
# Deliverable 6: the #3333 reserved probe is a different record kind.
# --------------------------------------------------------------------------

_AUTHORIZATION_PATH_MODULES = (publication, producer, caller, resolver_module, source_module)


@pytest.mark.parametrize("module", _AUTHORIZATION_PATH_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_authorization_paths_never_consume_the_reserved_probe(module):
    source = Path(module.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("fixed_codespace_pilot" in name for name in imported)
    assert RESERVED_PROBE_OPERATION not in source
    assert str(RESERVED_PROBE_COMMENT_ID) not in source


def test_reserved_probe_comment_is_not_an_execution_authorization(tmp_path, monkeypatch):
    case = _publisher_case(tmp_path, monkeypatch, records=({},))
    probe = f"/agent-os codespace-implementation executor-handoff:{'b' * 64} {'a' * 40}"
    case.transport = _OwnerCommentTransport(case.fixture.packet, (probe,))

    with pytest.raises(ProductionHandoffPublicationError) as raised:
        _publish(case)

    assert raised.value.args == ("execution-authorization-not-current",)
    assert case.spy.results[0].reason_codes == (ExecutionAuthorizationSourceReason.AUTHORIZATION_MISSING,)
    assert case.published == []
