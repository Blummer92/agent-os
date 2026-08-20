from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_os_execution_service.handoff_publication as publication
from agent_os_execution_service.executor_routing import ExecutorRoute


class _Route:
    pass


class _Request:
    pass


class _Authorization:
    pass


class _Checkpoint:
    pass


class _ResumePlan:
    pass


class _Packet:
    pass


class _Configuration:
    pass


class _Readiness:
    pass


class _Pilot:
    pass


class _Descriptor:
    pass


class _Outcome:
    def __init__(
        self,
        *,
        handoff_id: str,
        descriptor_id: str,
        already_present: bool = False,
    ) -> None:
        self.handoff_id = handoff_id
        self.descriptor_id = descriptor_id
        self.already_present = already_present
        self.path = Path("/tmp/descriptor.json")


def _case(monkeypatch, *, events: list[str] | None = None):
    events = [] if events is None else events
    repository = "Blummer92/agent-os"
    request_fp = "execution-request:" + "1" * 64
    handoff_id = "executor-handoff:" + "2" * 64
    descriptor_id = "agent-os.governed-invocation-descriptor:" + "3" * 64

    route = _Route()
    route.repository = repository
    route.issue_or_handoff_identity = "issue:1243"
    route.requested_operation = "implement-handoff-publication"
    route.required_capabilities = ()
    route.governed_runner_capabilities = ()
    route.governed_runner_available = True
    route.external_fallback_available = False
    route.external_fallback_explicitly_permitted = False
    route.created_at = "2026-08-18T01:00:00Z"
    route.expires_at = "2026-08-18T03:00:00Z"
    route.invalidation_conditions = ("repository-head-changed",)
    route.authority_ambiguous = False
    route.ownership_ambiguous = False
    route.source_of_truth_ambiguous = False
    route.target_ambiguous = False
    route.scope_ambiguous = False
    route.excluded_surface_involved = False
    route.evidence_stale = False
    route.evidence_contradictory = False
    route.irreversible_or_uncertain_mutation = False
    route.execution_service_request_fingerprint_or_none = request_fp
    route.authorization_id_or_none = "authorization:" + "4" * 64
    route.validation_command_plan_id_or_none = "command-plan:" + "5" * 64
    route.operating_mode_decision_id_or_none = "operating-mode:current"
    route.executable_lane_selection_id_or_none = "lane-selection:current"
    route.repository_state_evidence_id_or_none = None
    route.worktree_preparation_evidence_id_or_none = None
    route.exact_head_package_id_or_none = None
    route.environment_profile_id_or_none = "environment-profile:current"
    route.environment_health_evidence_id_or_none = "environment-health:current"
    route.checkpoint_id_or_none = "checkpoint:current"
    route.resume_plan_id_or_none = "resume-plan:current"
    route.workflow_runtime_identity_or_none = "workflow-runtime:current"
    route.execution_authorized = True
    route.github_writes_authorized = False
    route.external_writes_authorized = False
    route.merge_authorized = False
    route.selected_route = ExecutorRoute.CHATGPT_GOVERNED_RUNNER
    route.decision_id = "executor-route-decision:" + "6" * 64

    request = _Request()
    request.repository_identity = SimpleNamespace(owner="Blummer92", repository="agent-os")
    request.issue_or_handoff_identity = route.issue_or_handoff_identity
    request.request_fingerprint = request_fp
    request.requested_ref = "agent/1243-handoff-publication"
    request.expected_sha = "a" * 40
    request.allowed_paths = ("08_Tooling/agent-os-execution-service",)
    request.forbidden_paths = (".github/workflows",)

    authorization = _Authorization()
    checkpoint = _Checkpoint()
    checkpoint.checkpoint_id = route.checkpoint_id_or_none
    checkpoint.issue_number = 1243
    resume = _ResumePlan()
    resume.plan_id = route.resume_plan_id_or_none
    packet = _Packet()
    configuration = _Configuration()
    readiness = _Readiness()
    pilot = _Pilot()

    handoff = SimpleNamespace(handoff_id=handoff_id)
    descriptor = _Descriptor()
    descriptor.repository = repository
    descriptor.issue_or_handoff_identity = route.issue_or_handoff_identity
    descriptor.execution_service_request_fingerprint = request_fp
    descriptor.source_ref = request.requested_ref
    descriptor.source_sha = request.expected_sha
    descriptor.descriptor_id = descriptor_id
    outcome = _Outcome(handoff_id=handoff_id, descriptor_id=descriptor_id)

    for name, value in (
        ("ExecutorRouteDecision", _Route),
        ("ExecutionServiceRequest", _Request),
        ("ExecutionAuthorizationEvidence", _Authorization),
        ("ExecutionCheckpoint", _Checkpoint),
        ("ResumePlan", _ResumePlan),
        ("CandidatePacket", _Packet),
        ("ConcreteRuntimeConfiguration", _Configuration),
        ("DependencyReadinessEvidence", _Readiness),
        ("SingleIssuePilotInput", _Pilot),
        ("AppendInvocationDescriptorOutcome", _Outcome),
    ):
        monkeypatch.setattr(publication, name, value)

    monkeypatch.setattr(
        publication,
        "validate_execution_service_request",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        publication,
        "select_executor_route",
        lambda **_kwargs: events.append("select") or route,
    )
    monkeypatch.setattr(
        publication,
        "build_executor_handoff",
        lambda *_args, **_kwargs: events.append("build") or handoff,
    )
    monkeypatch.setattr(
        publication,
        "build_current_invocation_descriptor",
        lambda **_kwargs: events.append("descriptor-preview") or descriptor,
    )
    monkeypatch.setattr(
        publication,
        "CurrentInvocationEvidence",
        lambda **kwargs: events.append("current-evidence") or SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        publication,
        "validate_current_invocation_bindings",
        lambda *_args, **_kwargs: events.append("validate-bindings") or set(),
    )
    monkeypatch.setattr(
        publication,
        "persist_current_invocation_descriptor",
        lambda *_args, **_kwargs: events.append("persist") or outcome,
    )
    monkeypatch.setattr(
        publication,
        "append_route_decision",
        lambda *_args, **_kwargs: events.append("route-decision-persist")
        or SimpleNamespace(decision_id=route.decision_id),
    )
    monkeypatch.setattr(
        publication,
        "append_executor_handoff",
        lambda *_args, **_kwargs: events.append("handoff-persist")
        or SimpleNamespace(handoff_id=handoff.handoff_id),
    )
    monkeypatch.setattr(
        publication,
        "append_resume_plan",
        lambda *_args, **_kwargs: events.append("resume-plan-persist")
        or SimpleNamespace(plan_id=resume.plan_id),
    )
    monkeypatch.setattr(
        publication,
        "load_checkpoint_by_id",
        lambda *_args, **_kwargs: events.append("checkpoint-durability-check")
        or checkpoint,
    )

    kwargs = dict(
        store_root="/tmp/checkpoints",
        request=request,
        route_decision=route,
        authorization=authorization,
        checkpoint=checkpoint,
        resume_plan=resume,
        candidate_packet=packet,
        runtime_configuration=configuration,
        dependency_readiness=readiness,
        pilot_input=pilot,
        evaluated_at="2026-08-18T02:00:00Z",
        required_return_evidence=("test-results",),
        stop_conditions=("scope-expanded",),
    )
    return SimpleNamespace(
        kwargs=kwargs,
        route=route,
        request=request,
        descriptor=descriptor,
        handoff=handoff,
        outcome=outcome,
        checkpoint=checkpoint,
        events=events,
    )


def test_success_orders_route_handoff_validation_persistence_then_return(monkeypatch) -> None:
    case = _case(monkeypatch)
    result = publication.publish_governed_handoff(**case.kwargs)
    assert result is case.handoff
    assert case.events == [
        "select",
        "build",
        "descriptor-preview",
        "current-evidence",
        "validate-bindings",
        "route-decision-persist",
        "handoff-persist",
        "resume-plan-persist",
        "checkpoint-durability-check",
        "persist",
    ]


def test_equivalent_repeat_publication_is_idempotent(monkeypatch) -> None:
    case = _case(monkeypatch)
    case.outcome.already_present = True
    first = publication.publish_governed_handoff(**case.kwargs)
    second = publication.publish_governed_handoff(**case.kwargs)
    assert first is second is case.handoff
    assert case.outcome.handoff_id == case.handoff.handoff_id
    assert case.checkpoint.checkpoint_id == "checkpoint:current"


def test_route_reselection_drift_blocks_before_handoff_build(monkeypatch) -> None:
    case = _case(monkeypatch)
    monkeypatch.setattr(publication, "select_executor_route", lambda **_kwargs: _Route())
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("route-reselection-mismatch",)
    assert "build" not in case.events
    assert "persist" not in case.events


def test_non_governed_route_emits_no_descriptor(monkeypatch) -> None:
    case = _case(monkeypatch)
    case.route.selected_route = ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("route-not-governed-runner",)
    assert "descriptor-preview" not in case.events
    assert "persist" not in case.events


def test_request_binding_drift_blocks_before_handoff_build(monkeypatch) -> None:
    case = _case(monkeypatch)
    case.request.request_fingerprint = "execution-request:" + "f" * 64
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("request-binding-mismatch",)
    assert "build" not in case.events


def test_descriptor_request_binding_drift_blocks_before_persistence(monkeypatch) -> None:
    case = _case(monkeypatch)
    case.descriptor.source_sha = "b" * 40
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("request-binding-mismatch",)
    assert "persist" not in case.events


def test_invalid_request_blocks_before_route_selection(monkeypatch) -> None:
    case = _case(monkeypatch)
    monkeypatch.setattr(
        publication,
        "validate_execution_service_request",
        lambda *_args, **_kwargs: (object(),),
    )
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("request-invalid",)
    assert "select" not in case.events


@pytest.mark.parametrize(
    "reason_name",
    [
        "AUTHORIZATION_MISMATCH",
        "SOURCE_MISMATCH",
        "CHECKPOINT_MISMATCH",
        "RESUME_PLAN_MISMATCH",
        "ENVIRONMENT_MISMATCH",
        "DEPENDENCY_READINESS_MISMATCH",
        "EXECUTION_SURFACE_MISMATCH",
        "WORKSPACE_MISMATCH",
        "CANDIDATE_PACKET_MISMATCH",
        "RUNTIME_CONFIGURATION_MISMATCH",
        "PILOT_INPUT_MISMATCH",
    ],
)
def test_canonical_binding_failures_block_before_persistence(monkeypatch, reason_name) -> None:
    case = _case(monkeypatch)
    reason = getattr(publication.InvocationReconstructionReason, reason_name)
    monkeypatch.setattr(
        publication,
        "validate_current_invocation_bindings",
        lambda *_args, **_kwargs: {reason},
    )
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == (reason.value,)
    assert "persist" not in case.events


def test_persistence_failure_returns_no_handoff_and_does_not_retry(monkeypatch) -> None:
    case = _case(monkeypatch)
    calls = 0

    def fail(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise OSError("store unavailable")

    monkeypatch.setattr(publication, "persist_current_invocation_descriptor", fail)
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("descriptor-persistence-failed",)
    assert calls == 1


def test_conflicting_descriptor_failure_does_not_retry(monkeypatch) -> None:
    case = _case(monkeypatch)
    calls = 0

    def conflict(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("descriptor integrity conflict")

    monkeypatch.setattr(publication, "persist_current_invocation_descriptor", conflict)
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("descriptor-persistence-failed",)
    assert calls == 1


def test_persistence_outcome_must_match_preview_descriptor_and_handoff(monkeypatch) -> None:
    case = _case(monkeypatch)
    case.outcome.descriptor_id = "agent-os.governed-invocation-descriptor:" + "e" * 64
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("descriptor-persistence-mismatch",)


def test_route_decision_persistence_failure_blocks_before_handoff_persistence(monkeypatch) -> None:
    case = _case(monkeypatch)

    def fail(*_args, **_kwargs):
        raise OSError("store unavailable")

    monkeypatch.setattr(publication, "append_route_decision", fail)
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("route-decision-persistence-failed",)
    assert "handoff-persist" not in case.events
    assert "persist" not in case.events


def test_route_decision_persistence_mismatch_blocks_before_handoff_persistence(monkeypatch) -> None:
    case = _case(monkeypatch)
    monkeypatch.setattr(
        publication,
        "append_route_decision",
        lambda *_args, **_kwargs: SimpleNamespace(decision_id="executor-route-decision:" + "f" * 64),
    )
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("route-decision-persistence-mismatch",)
    assert "handoff-persist" not in case.events


def test_handoff_persistence_failure_blocks_before_resume_plan_persistence(monkeypatch) -> None:
    case = _case(monkeypatch)

    def fail(*_args, **_kwargs):
        raise OSError("store unavailable")

    monkeypatch.setattr(publication, "append_executor_handoff", fail)
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("handoff-persistence-failed",)
    assert "route-decision-persist" in case.events
    assert "resume-plan-persist" not in case.events
    assert "persist" not in case.events


def test_handoff_persistence_mismatch_blocks_before_resume_plan_persistence(monkeypatch) -> None:
    case = _case(monkeypatch)
    monkeypatch.setattr(
        publication,
        "append_executor_handoff",
        lambda *_args, **_kwargs: SimpleNamespace(handoff_id="executor-handoff:" + "f" * 64),
    )
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("handoff-persistence-mismatch",)
    assert "resume-plan-persist" not in case.events


def test_resume_plan_persistence_failure_blocks_before_checkpoint_check(monkeypatch) -> None:
    case = _case(monkeypatch)

    def fail(*_args, **_kwargs):
        raise OSError("store unavailable")

    monkeypatch.setattr(publication, "append_resume_plan", fail)
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("resume-plan-persistence-failed",)
    assert "handoff-persist" in case.events
    assert "checkpoint-durability-check" not in case.events
    assert "persist" not in case.events


def test_resume_plan_persistence_mismatch_blocks_before_checkpoint_check(monkeypatch) -> None:
    case = _case(monkeypatch)
    monkeypatch.setattr(
        publication,
        "append_resume_plan",
        lambda *_args, **_kwargs: SimpleNamespace(plan_id="resume-plan:different"),
    )
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("resume-plan-persistence-mismatch",)
    assert "checkpoint-durability-check" not in case.events


@pytest.mark.parametrize(
    "raised",
    [
        lambda: publication.CheckpointNotFound("checkpoint:current"),
        lambda: publication.CheckpointQuarantined("checkpoint:current"),
        lambda: publication.CheckpointStoreUnavailable("store unavailable"),
    ],
)
def test_checkpoint_not_durable_blocks_before_descriptor_persistence(monkeypatch, raised) -> None:
    case = _case(monkeypatch)

    def fail(*_args, **_kwargs):
        raise raised()

    monkeypatch.setattr(publication, "load_checkpoint_by_id", fail)
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("checkpoint-not-durable",)
    assert "resume-plan-persist" in case.events
    assert "persist" not in case.events


def test_checkpoint_durability_read_back_mismatch_blocks_before_descriptor_persistence(
    monkeypatch,
) -> None:
    case = _case(monkeypatch)
    monkeypatch.setattr(
        publication,
        "load_checkpoint_by_id",
        lambda *_args, **_kwargs: object(),
    )
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("checkpoint-not-durable",)
    assert "persist" not in case.events


def test_recoverable_artifact_persistence_happens_between_validation_and_descriptor(
    monkeypatch,
) -> None:
    case = _case(monkeypatch)
    publication.publish_governed_handoff(**case.kwargs)
    validate_index = case.events.index("validate-bindings")
    persist_index = case.events.index("persist")
    for step in (
        "route-decision-persist",
        "handoff-persist",
        "resume-plan-persist",
        "checkpoint-durability-check",
    ):
        assert validate_index < case.events.index(step) < persist_index


def test_malformed_current_evidence_is_bounded_failure(monkeypatch) -> None:
    case = _case(monkeypatch)
    case.kwargs["authorization"] = object()
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("current-evidence-malformed",)


def test_build_or_preview_validation_error_is_bounded_failure(monkeypatch) -> None:
    case = _case(monkeypatch)
    monkeypatch.setattr(
        publication,
        "build_current_invocation_descriptor",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("drift")),
    )
    with pytest.raises(publication.HandoffPublicationError) as exc:
        publication.publish_governed_handoff(**case.kwargs)
    assert exc.value.reason_codes == ("current-evidence-malformed",)
    assert "persist" not in case.events


def test_process_control_exceptions_propagate_from_persistence(monkeypatch) -> None:
    case = _case(monkeypatch)
    monkeypatch.setattr(
        publication,
        "persist_current_invocation_descriptor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    with pytest.raises(KeyboardInterrupt):
        publication.publish_governed_handoff(**case.kwargs)


def test_publication_module_has_no_runtime_or_external_io_imports() -> None:
    source = inspect.getsource(publication)
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = ("subprocess", "socket", "requests", "urllib", "google.cloud", "boto", "github")
    assert not any(any(token in name.lower() for token in forbidden) for name in imported)
    for forbidden_call in (
        "run_single_issue_pilot(",
        "run_single_issue_runtime_entrypoint(",
        ".acquire(",
        ".release(",
        "subprocess.",
        "os.system(",
    ):
        assert forbidden_call not in source


def test_complete_pilot_input_is_never_serialized_or_written_here() -> None:
    source = inspect.getsource(publication)
    assert "serialize_single_issue" not in source
    assert "pickle" not in source
    assert "json.dumps(pilot_input" not in source
    assert "write_text" not in source
    assert "write_bytes" not in source


def test_descriptor_remains_non_authorizing_owner_contract() -> None:
    source = inspect.getsource(publication)
    for forbidden in (
        "merge_authorized = True",
        "github_writes_authorized = True",
        "external_writes_authorized = True",
        "issue_closure_authorized = True",
    ):
        assert forbidden not in source


def test_publication_point_is_after_descriptor_persistence() -> None:
    source = inspect.getsource(publication.publish_governed_handoff)
    assert source.index("build_executor_handoff(") < source.index(
        "build_current_invocation_descriptor("
    )
    assert source.index("validate_current_invocation_bindings(") < source.index(
        "persist_current_invocation_descriptor("
    )
    assert source.index("persist_current_invocation_descriptor(") < source.rindex(
        "return handoff"
    )


def test_no_retry_or_fallback_loop_exists() -> None:
    tree = ast.parse(inspect.getsource(publication.publish_governed_handoff))
    assert not any(isinstance(node, (ast.For, ast.While)) for node in ast.walk(tree))
