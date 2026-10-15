"""#3333 fixed host-ingress consumer: safe defaults and bounded identity."""
from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

import agent_os_execution_service.current_invocation_resolver as resolver_module
import agent_os_execution_service.invocation_reconstruction as reconstruction
import agent_os_execution_service.production_host_composition as composition_module
import scripts.agent_os_execution_interface.fixed_codespace_pilot as pilot_module
from agent_os_execution_service.executor_routing import (
    ExecutorCapability,
    ExecutorRoute,
)
from agent_os_execution_service.invocation_reconstruction import (
    CurrentInvocationEvidence,
    InvocationReconstructionReason,
)
from agent_os_execution_service.production_host_composition import (
    CHECKPOINT_STORE_ROOT_ENV_VAR,
    ProductionAdmissionProviders,
    build_production_admission_providers,
)
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    INVOCATION_DESCRIPTOR_SCHEMA_NAME,
    INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
    GovernedInvocationDescriptor,
    InvocationDescriptorNotFound,
)
from scripts.agent_os_execution_interface.codespace_implementation_dispatch import (
    DispatchStatus,
    dispatch_admitted_operation_to_codespace,
)
from scripts.agent_os_execution_interface.codespaces_orchestrator_transport import (
    MAX_EVIDENCE_CHARS,
    CodespaceCandidate,
)
from scripts.agent_os_execution_interface.fixed_codespace_pilot import (
    ACCEPTED_REASON,
    FIXED_ARGV,
    ISSUE_NUMBER,
    OPERATION_ID,
    consume_fixed_codespace_pilot,
    consume_fixed_codespace_pilot_on_host,
    main,
)
from workflow_scheduler.execution.host_local_lease_adapter import (
    HostLocalLeaseObservation,
)
from workflow_scheduler.execution.single_issue_pilot import (
    PilotLeaseRequest,
    pilot_lease_identity,
)
from workflow_scheduler.governance.dev_validation_codespaces import (
    CodespaceSelection,
)
from workflow_scheduler.governance.github_issue_comment_ingress import (
    admit_issue_comment_event,
)

REPO = "Blummer92/agent-os"
SHA = "a" * 40
HANDOFF = "executor-handoff:" + "b" * 64
TRIGGER = f"/agent-os codespace-implementation {HANDOFF} {SHA}"


def event(body=TRIGGER, *, issue=ISSUE_NUMBER, actor="Blummer92", action="created"):
    return {
        "action": action,
        "repository": {"full_name": REPO},
        "issue": {"number": issue},
        "comment": {"id": 101, "body": body, "user": {"login": actor}},
        "sender": {"login": actor},
    }


def admit(payload, *, attempt=1):
    return admit_issue_comment_event(
        payload, expected_repository=REPO,
        allowed_actor="Blummer92", run_attempt=attempt,
    )


def test_fixed_operation_is_admitted_only_as_transport_evidence():
    result = admit(event())
    assert result.status == "accepted"
    assert result.reason == ACCEPTED_REASON
    assert result.codespace_implementation_handoff_id_or_none == HANDOFF
    assert result.codespace_implementation_sha_or_none == SHA
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False
    receipt = consume_fixed_codespace_pilot(result.to_dict())
    assert receipt["status"] == "needs-decision"
    assert receipt["reason_codes"] == ["canonical-admission-provider-unavailable"]
    assert receipt["request_id"] is None
    assert receipt["side_effects_performed"] is False
    assert receipt["operation_id"] == OPERATION_ID


def test_duplicate_event_uses_deterministic_identity():
    first = admit(event()).to_dict()
    second = event()
    second["comment"]["id"] = 102
    other = admit(second).to_dict()
    assert first["logical_trigger_id_or_none"] == other["logical_trigger_id_or_none"]


def test_wrong_issue_cannot_invoke_fixed_operation():
    result = admit(event(issue=3334))
    assert result.status == "blocked"
    assert result.reason == "codespace-implementation-issue-mismatch"


def test_nonowner_and_rerun_are_blocked():
    assert admit(event(actor="untrusted")).reason == "actor-not-allowed"
    assert admit(event(), attempt=2).reason == "workflow-rerun"


def test_extra_tokens_and_shell_syntax_are_rejected():
    for body in (
        TRIGGER + " --force",
        TRIGGER + "; git push origin main",
        TRIGGER.replace(SHA, "not-a-sha"),
        TRIGGER.replace(HANDOFF, "arbitrary-command"),
        "/agent-os codespace-implementation",
    ):
        result = admit(event(body))
        assert result.status != "accepted"


def test_noncanonical_or_tampered_receipt_fails_closed():
    accepted = admit(event()).to_dict()
    for field, value in (
        ("repository", "someone/else"),
        ("issue_number", 3334),
        ("actor", "mallory"),
        ("run_attempt", 2),
        ("codespace_implementation_sha_or_none", "bad"),
        ("codespace_implementation_handoff_id_or_none", "bad"),
        ("status", "ignored"),
        ("reason", "accepted-discovery-envelope"),
    ):
        tampered = {**accepted, field: value}
        result = consume_fixed_codespace_pilot(tampered)
        assert result["status"] == "blocked"
        assert result["reason_codes"] == ["invalid-fixed-operation-envelope"]
        assert result["side_effects_performed"] is False


def test_existing_discovery_ingress_unchanged():
    result = admit(event("/agent-os discover"))
    assert result.status == "accepted"
    assert result.reason == "accepted-discovery-envelope"
    assert result.codespace_implementation_handoff_id_or_none is None


def test_incomplete_production_host_binding_is_refused():
    transport = admit(event()).to_dict()
    result = consume_fixed_codespace_pilot(
        transport,
        descriptor_loader=lambda handoff: object(),
        current_resolver=object(),
        lease_reader=object(),
        codespace_selection=object(),
        evaluated_at="2026-10-09T19:00:00Z",
    )
    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["canonical-host-binding-incomplete"]
    assert result["side_effects_performed"] is False
    assert result["request_id"] is None


# ---------------------------------------------------------------------------
# Trusted-host connection (#1287 providers -> fixed consumer) and the
# fail-closed regression matrix. Admission runs through the real
# ``reconstruct_governed_invocation`` and the real post-admission currentness
# re-check; dispatch runs through the real #3373 dispatcher and #3335
# transport. Only the two external callables (Codespace listing and SSH run)
# are fakes, plus the same canonical-internals patches the #1218 suite uses
# for its cross-check and lease cases.
# ---------------------------------------------------------------------------

CODESPACE = "happy-codespace"
EVALUATED_AT = "2026-10-14T12:00:00Z"
CAPS = tuple(
    sorted(
        (
            ExecutorCapability.CHECKOUT,
            ExecutorCapability.ISOLATED_WORKTREE,
            ExecutorCapability.DEPENDENCY_INSTALLATION,
            ExecutorCapability.PROCESS_EXECUTION,
            ExecutorCapability.TEST_EXECUTION,
            ExecutorCapability.GIT_RECONCILIATION,
        ),
        key=lambda item: item.value,
    )
)


def _hid(prefix: str, label: str) -> str:
    return f"{prefix}:{hashlib.sha256(label.encode()).hexdigest()}"


def _descriptor(**overrides) -> GovernedInvocationDescriptor:
    values = {
        "schema_name": INVOCATION_DESCRIPTOR_SCHEMA_NAME,
        "schema_version": INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
        "repository": REPO,
        "issue_number": ISSUE_NUMBER,
        "issue_or_handoff_identity": "issue:3333",
        "handoff_id": HANDOFF,
        "route_decision_id": _hid("executor-route-decision", "route"),
        "execution_service_request_fingerprint": _hid("execution-request", "request"),
        "authorization_id": _hid("authorization", "authorization"),
        "source_ref": "refs/heads/agent/3333-probe",
        "source_sha": SHA,
        "checkpoint_id": _hid("agent-os.execution-checkpoint", "checkpoint"),
        "resume_plan_id": _hid("agent-os.execution-checkpoint.resume-plan", "resume"),
        "environment_profile_id": _hid("environment-profile", "profile"),
        "environment_health_evidence_id": _hid("environment-health", "health"),
        "required_environment_id": _hid("required-environment", "required"),
        "dependency_readiness_evidence_id": _hid("dependency-readiness", "readiness"),
        "execution_surface_id": "codespace:" + CODESPACE,
        "workspace_identity": _hid("pilot-workspace", "workspace"),
        "workflow_runtime_identity": _hid("workflow-runtime", "runtime"),
        "candidate_packet_id": _hid("candidate-packet", "packet"),
        "runtime_configuration_fingerprint": _hid("concrete-adapters", "configuration"),
        "execution_id": "execution-3333-probe",
        "invocation_id": "invocation-3333-probe",
    }
    values.update(overrides)
    return GovernedInvocationDescriptor(**values)


class _Pilot:
    """Stands in for SingleIssuePilotInput, as in the #1218 lease cases."""

    def __init__(self, **values):
        self.__dict__.update(values)


def _current(descriptor: GovernedInvocationDescriptor) -> CurrentInvocationEvidence:
    route = SimpleNamespace(
        decision_id=descriptor.route_decision_id,
        requested_operation="pre-pr-developer-loop",
        selected_route=ExecutorRoute.CHATGPT_GOVERNED_RUNNER,
        governed_runner_available=True,
        environment_health_evidence_id_or_none=descriptor.environment_health_evidence_id,
        environment_profile_id_or_none=descriptor.environment_profile_id,
        workflow_runtime_identity_or_none=descriptor.workflow_runtime_identity,
        required_capabilities=CAPS,
        governed_runner_capabilities=CAPS,
        operating_mode_decision_id_or_none="operating-mode:3333-probe",
        executable_lane_selection_id_or_none="lane-selection:3333-probe",
        execution_service_request_fingerprint_or_none=(
            descriptor.execution_service_request_fingerprint
        ),
        validation_command_plan_id_or_none="command-plan:3333-probe",
        created_at="2026-10-14T11:00:00Z",
        expires_at="2026-10-14T13:00:00Z",
    )
    current = object.__new__(CurrentInvocationEvidence)
    for name, value in {
        "route_decision": route,
        "handoff": SimpleNamespace(source_sha_or_none=descriptor.source_sha),
        "authorization": SimpleNamespace(
            execution_authorized=True,
            authorization_id=descriptor.authorization_id,
            expected_sha=descriptor.source_sha,
        ),
        "dependency_readiness": SimpleNamespace(
            execution_surface_id=descriptor.execution_surface_id
        ),
        "pilot_input": _Pilot(
            repository=REPO,
            issue_numbers=(ISSUE_NUMBER,),
            source_head_sha=SHA,
            tested_sha=SHA,
        ),
    }.items():
        object.__setattr__(current, name, value)
    return current


LEASE_REQUEST = PilotLeaseRequest(
    repository=REPO,
    issue_number=ISSUE_NUMBER,
    invocation_id="invocation-3333-probe",
    branch="agent/3333-probe",
    workspace_request_id="workspace-3333-probe",
    projection_id="projection-3333-probe",
    approval_id="approval-3333-probe",
    source_head_sha=SHA,
)


class _Loader:
    def __init__(self, value):
        self.value = value

    def __call__(self, _handoff):
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


class _Resolver:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def reacquire(self, _descriptor):
        self.calls += 1
        return self.value


class _Lease:
    def __init__(self, *, active=False, ambiguous=False, identity=None):
        self.observation = HostLocalLeaseObservation(
            lease_identity=identity or pilot_lease_identity(LEASE_REQUEST),
            active=active,
            ambiguous=ambiguous,
            generation=1,
            holder_identity="pilot-holder:other" if active else None,
        )

    def inspect(self, _request):
        return self.observation


class _Run:
    def __init__(self, result=(0, SHA + "\n", "")):
        self.result = result
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv, *, timeout_seconds):
        self.calls.append(argv)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _listed(name=CODESPACE):
    return lambda: (
        CodespaceCandidate(
            name=name, state="Available", repository_full_name=REPO, owner_login="Blummer92"
        ),
    )


@pytest.fixture
def canonical(monkeypatch):
    """Real reconstruction/currentness with a controllable cross-check."""
    reasons: set = set()
    monkeypatch.setattr(reconstruction, "SingleIssuePilotInput", _Pilot)
    monkeypatch.setattr(reconstruction, "_lease_request", lambda _pilot: LEASE_REQUEST)
    monkeypatch.setattr(reconstruction, "_cross_check", lambda *_a, **_k: set(reasons))
    monkeypatch.setattr(resolver_module, "_cross_check", lambda *_a, **_k: set(reasons))
    return reasons


def _consume(descriptor=None, current=None, *, lease=None, selection=None, run=None, listed=None,
             loader=None, transport=None):
    descriptor = descriptor or _descriptor()
    run = run or _Run()
    receipt = consume_fixed_codespace_pilot(
        transport or admit(event()).to_dict(),
        descriptor_loader=loader or _Loader(descriptor),
        current_resolver=_Resolver(current or _current(descriptor)),
        lease_reader=lease or _Lease(),
        codespace_selection=selection or CodespaceSelection(True, "selected", CODESPACE, "Available"),
        evaluated_at=EVALUATED_AT,
        dispatcher=functools.partial(
            dispatch_admitted_operation_to_codespace,
            list_candidates=listed or _listed(),
            run=run,
        ),
    )
    return receipt, run


def _assert_no_authority(receipt):
    for flag in (
        "execution_authorized",
        "github_writes_authorized",
        "external_writes_authorized",
        "publication_authorized",
        "merge_authorized",
        "scheduler_invoked",
    ):
        assert receipt[flag] is False


def test_fixed_operation_identity_is_pinned_to_literals():
    # Literals, not the module constants on both sides: a change to the fixed
    # operation must not be able to move the assertion that guards it.
    assert OPERATION_ID == "codespace-implementation-pilot-v1"
    assert ISSUE_NUMBER == 3333
    assert FIXED_ARGV == ("git", "rev-parse", "HEAD")


def test_probe_route_operation_is_the_one_every_production_publisher_binds():
    # Literal on one side: a change to either operation must not move the guard.
    from agent_os_execution_service.production_handoff_publication import (
        PRE_PR_DEVELOPER_LOOP_OPERATION,
    )

    assert pilot_module.ROUTE_OPERATION == "pre-pr-developer-loop"
    assert pilot_module.ROUTE_OPERATION == PRE_PR_DEVELOPER_LOOP_OPERATION


def test_route_operation_and_reserved_envelope_identity_stay_distinct(canonical):
    """The route operation admits the mission; the envelope identity names the reserved probe."""
    seen = {}

    def dispatcher(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(status=DispatchStatus.NOT_DISPATCHED, transport_result_or_none=None)

    descriptor = _descriptor()
    receipt = consume_fixed_codespace_pilot(
        admit(event()).to_dict(),
        descriptor_loader=_Loader(descriptor),
        current_resolver=_Resolver(_current(descriptor)),
        lease_reader=_Lease(),
        codespace_selection=CodespaceSelection(True, "selected", CODESPACE, "Available"),
        evaluated_at=EVALUATED_AT,
        dispatcher=dispatcher,
    )
    assert seen["requested_operation"] == "pre-pr-developer-loop"
    assert seen["argv"] == ("git", "rev-parse", "HEAD")
    assert receipt["operation_id"] == "codespace-implementation-pilot-v1"
    assert receipt["operation_id"] != seen["requested_operation"]
    _assert_no_authority(receipt)


def test_admitted_probe_runs_only_the_fixed_argv_on_the_selected_codespace(canonical):
    receipt, run = _consume()
    assert receipt["status"] == "completed"
    assert receipt["reason_codes"] == ["fixed-head-probe-passed"]
    assert receipt["codespace_name"] == CODESPACE
    assert receipt["exit_status"] == 0
    assert receipt["request_id"]
    assert run.calls == [
        ("gh", "codespace", "ssh", "-c", CODESPACE, "--", "git", "rev-parse", "HEAD")
    ]
    _assert_no_authority(receipt)


def test_completed_receipt_keeps_the_transport_timing_and_truncation_evidence(canonical):
    """#3333 Gate 5 R-1: the receipt must not drop the TransportResult evidence."""
    receipt, _run = _consume()
    assert receipt["status"] == "completed"
    assert receipt["argv"] == ["git", "rev-parse", "HEAD"]
    assert receipt["stdout_truncated"] is False
    assert receipt["stderr_truncated"] is False
    assert type(receipt["duration_ms"]) is int and receipt["duration_ms"] >= 0
    for key in ("started_at", "ended_at"):
        assert type(receipt[key]) is str and receipt[key].endswith("Z")
    assert receipt["started_at"] <= receipt["ended_at"]
    json.dumps(receipt)


def test_truncated_receipt_records_which_stream_was_truncated(canonical):
    receipt, _run = _consume(run=_Run((0, SHA, "y" * (MAX_EVIDENCE_CHARS + 1))))
    assert receipt["status"] == "blocked"
    assert receipt["stdout_truncated"] is False
    assert receipt["stderr_truncated"] is True


def test_preflight_refusal_claims_no_execution_timing(canonical):
    receipt, run = _consume(loader=_Loader(InvocationDescriptorNotFound(HANDOFF)))
    assert run.calls == []
    assert receipt["argv"] == ["git", "rev-parse", "HEAD"]
    assert (receipt["started_at"], receipt["ended_at"], receipt["duration_ms"]) == (None, None, None)
    assert receipt["stdout_truncated"] is False and receipt["stderr_truncated"] is False


@pytest.mark.parametrize(
    "lease,status",
    [
        (_Lease(active=True), "blocked"),
        (_Lease(ambiguous=True), "blocked"),
        (_Lease(identity="pilot-lease:" + "0" * 64), "blocked"),
    ],
    ids=["conflicting-lease", "ambiguous-lease", "foreign-lease"],
)
def test_conflicting_or_ambiguous_lease_never_dispatches(canonical, lease, status):
    receipt, run = _consume(lease=lease)
    assert receipt["status"] == status
    assert receipt["reason_codes"] == ["canonical-invocation-not-admitted"]
    assert run.calls == []
    assert receipt["side_effects_performed"] is False


def test_missing_descriptor_never_dispatches(canonical):
    receipt, run = _consume(loader=_Loader(InvocationDescriptorNotFound(HANDOFF)))
    assert receipt["reason_codes"] == ["canonical-invocation-not-admitted"]
    assert run.calls == []


@pytest.mark.parametrize(
    "reason",
    [
        InvocationReconstructionReason.CHECKPOINT_NOT_CURRENT,
        InvocationReconstructionReason.RESUME_PLAN_MISMATCH,
        InvocationReconstructionReason.AUTHORIZATION_NOT_CURRENT,
        InvocationReconstructionReason.AUTHORIZATION_MISMATCH,
        InvocationReconstructionReason.SOURCE_MISMATCH,
    ],
)
def test_stale_checkpoint_or_authorization_never_dispatches(canonical, reason):
    canonical.add(reason)
    receipt, run = _consume()
    assert receipt["reason_codes"] == ["canonical-invocation-not-admitted"]
    assert run.calls == []


def test_currentness_drift_after_admission_never_dispatches(canonical, monkeypatch):
    monkeypatch.setattr(
        resolver_module,
        "_cross_check",
        lambda *_a, **_k: {InvocationReconstructionReason.CHECKPOINT_NOT_CURRENT},
    )
    receipt, run = _consume()
    assert receipt["reason_codes"] == ["invocation-currentness-mismatch"]
    assert run.calls == []


def _mutated(path, value):
    descriptor = _descriptor()
    current = _current(descriptor)
    parent, name = path.split(".")
    setattr(getattr(current, parent), name, value)
    return descriptor, current


@pytest.mark.parametrize(
    "path,value",
    [
        ("authorization.execution_authorized", False),
        ("authorization.authorization_id", _hid("authorization", "expired")),
        ("authorization.expected_sha", "c" * 40),
        ("handoff.source_sha_or_none", "c" * 40),
        ("pilot_input.issue_numbers", (3334,)),
        ("pilot_input.source_head_sha", "c" * 40),
        # SingleIssuePilotInput requirements: repository, issue, source and tested SHA.
        ("pilot_input.tested_sha", "c" * 40),
        ("pilot_input.repository", "Blummer92/other-repository"),
        ("route_decision.requested_operation", "arbitrary-shell"),
        # The retired probe operation and the lifecycle-only validation operation
        # are both different operations from the one the probe is admitted under.
        ("route_decision.requested_operation", "bounded-implementation"),
        ("route_decision.requested_operation", "validation-only"),
        # The comparison is exact: no case folding and no prefix matching.
        ("route_decision.requested_operation", "PRE-PR-DEVELOPER-LOOP"),
        ("route_decision.requested_operation", "pre-pr-developer-loop-x"),
        ("route_decision.selected_route", ExecutorRoute.HUMAN_DECISION_REQUIRED),
        ("route_decision.governed_runner_available", False),
        ("route_decision.environment_health_evidence_id_or_none", None),
    ],
    ids=[
        "authorization-not-granted",
        "authorization-replaced",
        "authorization-stale-sha",
        "stale-source-sha",
        "mismatched-issue",
        "stale-pilot-head",
        "stale-pilot-tested-sha",
        "mismatched-pilot-repository",
        "unauthorized-operation",
        "retired-bounded-implementation-operation",
        "validation-only-operation",
        "operation-case-variant",
        "operation-suffix-variant",
        "route-not-governed-runner",
        "governed-runner-unavailable",
        "missing-environment-health",
    ],
)
def test_identity_authorization_or_health_mismatch_never_dispatches(canonical, path, value):
    descriptor, current = _mutated(path, value)
    receipt, run = _consume(descriptor, current)
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["canonical-identity-or-authorization-mismatch"]
    assert run.calls == []


def test_mismatched_handoff_or_issue_descriptor_never_dispatches(canonical):
    for descriptor in (
        _descriptor(issue_number=3334, issue_or_handoff_identity="issue:3334"),
        _descriptor(source_sha="c" * 40),
    ):
        receipt, run = _consume(descriptor, _current(_descriptor()))
        assert receipt["status"] == "blocked"
        assert run.calls == []
    receipt, run = _consume(_descriptor(handoff_id="executor-handoff:" + "d" * 64))
    assert receipt["reason_codes"] == ["canonical-invocation-not-admitted"]
    assert run.calls == []


@pytest.mark.parametrize(
    "selection",
    [
        CodespaceSelection(True, "selected", "other-codespace", "Available"),
        CodespaceSelection(True, "selected", CODESPACE, "Shutdown"),
        CodespaceSelection(False, "codespaces-not-available"),
        CodespaceSelection(False, "multiple-qualified-codespaces"),
        # Not selected must refuse even when a surface name and state are attached.
        CodespaceSelection(False, "multiple-qualified-codespaces", CODESPACE, "Available"),
    ],
    ids=[
        "changed-codespace",
        "not-available",
        "none-selected",
        "ambiguous",
        "ambiguous-with-named-surface",
    ],
)
def test_changed_or_unqualified_codespace_selection_never_dispatches(canonical, selection):
    receipt, run = _consume(selection=selection)
    assert receipt["reason_codes"] == ["codespace-currentness-or-health-unverified"]
    assert run.calls == []


def test_transport_cannot_silently_switch_to_another_codespace(canonical):
    receipt, run = _consume(listed=_listed("other-codespace"))
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["codespace-head-or-transport-mismatch"]
    assert receipt["exit_status"] is None
    assert run.calls == []


def test_unsupported_capability_never_dispatches(canonical):
    descriptor, current = _mutated("route_decision.required_capabilities", ("shell",))
    receipt, run = _consume(descriptor, current)
    assert receipt["reason_codes"] == ["runner-capabilities-unverified"]
    assert run.calls == []
    descriptor, current = _mutated("route_decision.required_capabilities", ())
    receipt, run = _consume(descriptor, current)
    assert receipt["reason_codes"] == ["runner-capabilities-unverified"]
    assert run.calls == []
    descriptor, current = _mutated(
        "route_decision.governed_runner_capabilities", (ExecutorCapability.CHECKOUT,)
    )
    receipt, run = _consume(descriptor, current)
    assert receipt["reason_codes"] == ["codespace-dispatch-not-completed"]
    assert run.calls == []


@pytest.mark.parametrize(
    "field",
    [
        "operating_mode_decision_id_or_none",
        "executable_lane_selection_id_or_none",
        "execution_service_request_fingerprint_or_none",
    ],
)
def test_missing_route_binding_identity_never_dispatches(canonical, field):
    descriptor, current = _mutated(f"route_decision.{field}", None)
    receipt, run = _consume(descriptor, current)
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["canonical-route-binding-unavailable"]
    assert run.calls == []


class _FlakyLoader:
    """Serves the descriptor to reconstruction, then fails the currentness re-read."""

    def __init__(self, descriptor, failure):
        self.descriptor = descriptor
        self.failure = failure
        self.calls = 0

    def __call__(self, _handoff):
        self.calls += 1
        if self.calls > 1:
            raise self.failure
        return self.descriptor


@pytest.mark.parametrize("failure", ["store-unreadable", "evidence-field-missing"])
def test_evidence_that_becomes_unavailable_after_admission_never_dispatches(canonical, failure):
    descriptor = _descriptor()
    current = _current(descriptor)
    loader = _Loader(descriptor)
    if failure == "store-unreadable":
        loader = _FlakyLoader(descriptor, OSError("store unreadable"))
    else:
        del current.route_decision.requested_operation
    receipt, run = _consume(descriptor, current, loader=loader)
    assert receipt["status"] == "needs-decision"
    assert receipt["reason_codes"] == ["current-evidence-unavailable"]
    assert receipt["side_effects_performed"] is False
    assert run.calls == []


@pytest.mark.parametrize(
    "result",
    [
        (0, "not-a-sha\n", ""),
        (0, "c" * 40 + "\n", ""),
        (128, "", "fatal: not a git repository"),
        # Matching stdout must not turn a failed command into a completed probe.
        (1, SHA + "\n", ""),
        # The kept tail strips to exactly the SHA; only truncation rejects it.
        (0, "x" * 10 + " " * (MAX_EVIDENCE_CHARS - 40) + SHA, ""),
        (0, SHA, "y" * (MAX_EVIDENCE_CHARS + 1)),
    ],
    ids=[
        "malformed",
        "stale-remote-head",
        "nonzero-exit",
        "nonzero-exit-with-matching-stdout",
        "truncated-stdout",
        "truncated-stderr",
    ],
)
def test_malformed_or_truncated_receipt_is_not_completed(canonical, result):
    receipt, run = _consume(run=_Run(result))
    assert len(run.calls) == 1
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["codespace-head-or-transport-mismatch"]
    _assert_no_authority(receipt)


def test_ssh_timeout_is_not_completed(canonical):
    receipt, run = _consume(run=_Run(subprocess.TimeoutExpired(cmd="gh", timeout=90)))
    assert len(run.calls) == 1
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["codespace-head-or-transport-mismatch"]
    assert receipt["exit_status"] is None
    # A dispatched-but-failed transport still keeps its attempt timing.
    assert type(receipt["started_at"]) is str and type(receipt["ended_at"]) is str
    assert type(receipt["duration_ms"]) is int


def test_receipt_from_a_different_codespace_than_the_selected_one_is_blocked(canonical):
    """The consumer re-checks receipt identity itself, independent of the transport."""
    descriptor = _descriptor()
    transport_result = SimpleNamespace(
        request_id="request-3333-probe",
        codespace_name_or_none="other-codespace",
        exit_status_or_none=0,
        stdout_tail=SHA + "\n",
        stderr_tail="",
        stdout_truncated=False,
        stderr_truncated=False,
        argv=FIXED_ARGV,
        started_at_or_none="2026-10-14T00:00:00Z",
        ended_at_or_none="2026-10-14T00:00:01Z",
        duration_ms=1000,
    )
    receipt = consume_fixed_codespace_pilot(
        admit(event()).to_dict(),
        descriptor_loader=_Loader(descriptor),
        current_resolver=_Resolver(_current(descriptor)),
        lease_reader=_Lease(),
        codespace_selection=CodespaceSelection(True, "selected", CODESPACE, "Available"),
        evaluated_at=EVALUATED_AT,
        dispatcher=lambda **_kwargs: SimpleNamespace(
            status=DispatchStatus.DISPATCHED, transport_result_or_none=transport_result
        ),
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["codespace-head-or-transport-mismatch"]
    _assert_no_authority(receipt)


def test_receipt_reporting_a_different_argv_than_the_fixed_one_is_blocked(canonical):
    """A dispatcher that ran anything but the fixed argv cannot yield a completed probe."""
    descriptor = _descriptor()
    transport_result = SimpleNamespace(
        request_id="request-3333-probe",
        codespace_name_or_none=CODESPACE,
        exit_status_or_none=0,
        stdout_tail=SHA + "\n",
        stderr_tail="",
        stdout_truncated=False,
        stderr_truncated=False,
        argv=("git", "log", "-1", "--format=%H"),
        started_at_or_none="2026-10-14T00:00:00Z",
        ended_at_or_none="2026-10-14T00:00:01Z",
        duration_ms=1000,
    )
    receipt = consume_fixed_codespace_pilot(
        admit(event()).to_dict(),
        descriptor_loader=_Loader(descriptor),
        current_resolver=_Resolver(_current(descriptor)),
        lease_reader=_Lease(),
        codespace_selection=CodespaceSelection(True, "selected", CODESPACE, "Available"),
        evaluated_at=EVALUATED_AT,
        dispatcher=lambda **_kwargs: SimpleNamespace(
            status=DispatchStatus.DISPATCHED, transport_result_or_none=transport_result
        ),
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["codespace-head-or-transport-mismatch"]
    assert receipt["argv"] == ["git", "log", "-1", "--format=%H"]
    _assert_no_authority(receipt)


def test_unauthorized_envelope_operation_never_reaches_providers(canonical):
    accepted = admit(event()).to_dict()
    for field, value in (
        ("reason", "accepted-dev-validation-envelope"),
        ("codespace_implementation_handoff_id_or_none", "git push origin main"),
    ):
        receipt, run = _consume(transport={**accepted, field: value})
        assert receipt["reason_codes"] == ["invalid-fixed-operation-envelope"]
        assert run.calls == []


# --- the on-host entry --------------------------------------------------------


def _host_providers(tmp_path, monkeypatch):
    store = tmp_path / "checkpoint-store"
    store.mkdir()
    monkeypatch.setenv(CHECKPOINT_STORE_ROOT_ENV_VAR, str(store))

    def unreachable(*_args, **_kwargs):
        raise AssertionError("current-evidence sources must not be reached")

    return build_production_admission_providers(
        lease_directory=str(tmp_path / "leases"),
        route_decision_reader=unreachable,
        handoff_reader=unreachable,
        checkpoint_reader=unreachable,
        resume_plan_reader=unreachable,
        candidate_packet_rebuilder=unreachable,
        runtime_configuration_builder=unreachable,
        pilot_input_builder=unreachable,
        authorization_transport=SimpleNamespace(read_authorization_source=unreachable),
        evaluated_at=EVALUATED_AT,
    )


def test_host_entry_with_real_providers_fails_closed_on_an_empty_descriptor_store(
    tmp_path, monkeypatch
):
    run = _Run()
    receipt = consume_fixed_codespace_pilot_on_host(
        admit(event()).to_dict(),
        providers=_host_providers(tmp_path, monkeypatch),
        resolve_selection=lambda: CodespaceSelection(True, "selected", CODESPACE, "Available"),
        dispatcher=functools.partial(
            dispatch_admitted_operation_to_codespace, list_candidates=_listed(), run=run
        ),
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["canonical-invocation-not-admitted"]
    assert run.calls == []
    assert receipt["side_effects_performed"] is False


def test_host_entry_requires_the_exact_canonical_provider_bundle():
    lookalike = SimpleNamespace(
        descriptor_loader=lambda handoff: _descriptor(),
        current_resolver=_Resolver(None),
        lease_reader=_Lease(),
        evaluated_at=EVALUATED_AT,
    )
    for providers in (None, lookalike):
        receipt = consume_fixed_codespace_pilot_on_host(
            admit(event()).to_dict(),
            providers=providers,
            resolve_selection=lambda: pytest.fail("selection must not be read"),
        )
        assert receipt["status"] == "needs-decision"
        assert receipt["reason_codes"] == ["canonical-admission-provider-unavailable"]


def test_host_entry_rejects_a_noncanonical_selection(tmp_path, monkeypatch):
    providers = _host_providers(tmp_path, monkeypatch)
    for resolve in (
        lambda: SimpleNamespace(selected=True, state="Available", codespace_name=CODESPACE),
        lambda: (_ for _ in ()).throw(OSError("gh unavailable")),
    ):
        receipt = consume_fixed_codespace_pilot_on_host(
            admit(event()).to_dict(), providers=providers, resolve_selection=resolve
        )
        assert receipt["reason_codes"] == ["codespace-currentness-or-health-unverified"]
        assert receipt["side_effects_performed"] is False


def test_host_entry_checks_the_envelope_before_any_host_read(tmp_path, monkeypatch):
    receipt = consume_fixed_codespace_pilot_on_host(
        {**admit(event()).to_dict(), "issue_number": 3334},
        providers=_host_providers(tmp_path, monkeypatch),
        resolve_selection=lambda: pytest.fail("selection must not be read"),
    )
    assert receipt["reason_codes"] == ["invalid-fixed-operation-envelope"]


def test_host_entry_hands_each_provider_to_the_matching_consumer_input(monkeypatch):
    providers = ProductionAdmissionProviders(
        descriptor_loader=_Loader(_descriptor()),
        current_resolver=_Resolver(None),
        lease_reader=_Lease(),
        evaluated_at="2026-10-14T12:34:56Z",
    )
    selection = CodespaceSelection(True, "selected", CODESPACE, "Available")
    transport = admit(event()).to_dict()
    dispatcher = object()
    delegated: dict[str, object] = {}
    sentinel = {"status": "delegated"}

    def delegate(received, **kwargs):
        delegated["transport"] = received
        delegated.update(kwargs)
        return sentinel

    monkeypatch.setattr(pilot_module, "consume_fixed_codespace_pilot", delegate)

    result = consume_fixed_codespace_pilot_on_host(
        transport,
        providers=providers,
        resolve_selection=lambda: selection,
        dispatcher=dispatcher,
    )

    assert result is sentinel
    assert delegated["transport"] is transport
    assert delegated["descriptor_loader"] is providers.descriptor_loader
    assert delegated["current_resolver"] is providers.current_resolver
    assert delegated["lease_reader"] is providers.lease_reader
    assert delegated["evaluated_at"] == "2026-10-14T12:34:56Z"
    assert delegated["codespace_selection"] is selection
    assert delegated["dispatcher"] is dispatcher
    # Nothing beyond the reviewed inputs reaches the existing consumer.
    assert set(delegated) == {
        "transport",
        "descriptor_loader",
        "current_resolver",
        "lease_reader",
        "evaluated_at",
        "codespace_selection",
        "dispatcher",
    }


def _direct_providers(descriptor):
    return ProductionAdmissionProviders(
        descriptor_loader=_Loader(descriptor),
        current_resolver=_Resolver(_current(descriptor)),
        lease_reader=_Lease(),
        evaluated_at=EVALUATED_AT,
    )


def test_host_entry_default_selection_is_the_shared_resolver_through_the_execution_service(
    canonical, monkeypatch
):
    selection = CodespaceSelection(True, "selected", CODESPACE, "Available")
    monkeypatch.setattr(composition_module, "resolve_current_codespace", lambda: selection)
    run = _Run()
    receipt = consume_fixed_codespace_pilot_on_host(
        admit(event()).to_dict(),
        providers=_direct_providers(_descriptor()),
        dispatcher=functools.partial(
            dispatch_admitted_operation_to_codespace, list_candidates=_listed(), run=run
        ),
    )
    assert receipt["status"] == "completed"
    assert run.calls == [
        ("gh", "codespace", "ssh", "-c", CODESPACE, "--", "git", "rev-parse", "HEAD")
    ]


def test_host_entry_with_the_real_resolver_and_no_credential_never_dispatches(
    canonical, monkeypatch
):
    # Without GH_TOKEN the shared resolver answers "not selected" before any
    # network call, so this exercises the real default read with no effects.
    monkeypatch.delenv("GH_TOKEN", raising=False)
    run = _Run()
    receipt = consume_fixed_codespace_pilot_on_host(
        admit(event()).to_dict(),
        providers=_direct_providers(_descriptor()),
        dispatcher=functools.partial(
            dispatch_admitted_operation_to_codespace, list_candidates=_listed(), run=run
        ),
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["codespace-currentness-or-health-unverified"]
    assert run.calls == []
    _assert_no_authority(receipt)


def test_host_entry_admits_the_fixed_probe_through_directly_bound_providers(canonical):
    descriptor = _descriptor()
    resolver = _Resolver(_current(descriptor))
    run = _Run()
    providers = ProductionAdmissionProviders(
        descriptor_loader=_Loader(descriptor),
        current_resolver=resolver,
        lease_reader=_Lease(),
        evaluated_at=EVALUATED_AT,
    )
    dispatcher = functools.partial(
        dispatch_admitted_operation_to_codespace, list_candidates=_listed(), run=run
    )

    def probe(bound):
        return consume_fixed_codespace_pilot_on_host(
            admit(event()).to_dict(),
            providers=bound,
            resolve_selection=lambda: CodespaceSelection(True, "selected", CODESPACE, "Available"),
            dispatcher=dispatcher,
        )

    receipt = probe(providers)
    assert receipt["status"] == "completed"
    assert receipt["reason_codes"] == ["fixed-head-probe-passed"]
    assert resolver.calls >= 1
    assert run.calls == [
        ("gh", "codespace", "ssh", "-c", CODESPACE, "--", "git", "rev-parse", "HEAD")
    ]
    _assert_no_authority(receipt)

    # The lease observed is the bundle's own: a conflicting one blocks the same entry.
    conflicting = dataclasses.replace(providers, lease_reader=_Lease(active=True))
    blocked = probe(conflicting)
    assert blocked["status"] == "blocked"
    assert blocked["reason_codes"] == ["canonical-invocation-not-admitted"]
    assert len(run.calls) == 1


def test_actions_entry_still_fails_closed_without_a_host(tmp_path):
    transport = tmp_path / "transport.json"
    output = tmp_path / "result.json"
    transport.write_text(json.dumps(admit(event()).to_dict()), encoding="utf-8")
    assert main(["--transport", str(transport), "--result-output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))["codespace_implementation"]
    assert result["reason_codes"] == ["canonical-admission-provider-unavailable"]
    assert result["side_effects_performed"] is False
