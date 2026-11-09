"""Wave 3 NC15 candidate (FU-HOST-1 + FU-HOST-3): invalid envelope never dispatches.

Local-only candidate. Intended home (when filed): the existing test file
tests/agent_os_execution_interface/test_mutation_host_invalid_envelope_receipt.py.

Provenance: Wave 2 PR #3850's test kills its reconstructed mutant only by
receipt spelling (status "BLOCKED" vs "blocked") -- a contract kill, not an
authorization-consequence kill. The mutant receipt releases the claim and
finalises identically to the original downstream (gate2 collapses every
non-"completed" status to "blocked", gate2_production_controller.py:970), and
the test injects no dispatcher, so it cannot prove an invalid envelope never
dispatches.

This file adds the two missing detectors:

* FU-HOST-1 -- a raising dispatcher mock behind the full admitted
  composition. The envelope is admitted for the owner, then tampered to a
  wrong actor (the #3333 X01 shape), so every admission input is valid
  *except* the envelope itself. Mutant: remove the pre-execution envelope
  check in consume_fixed_codespace_pilot (fixed_codespace_pilot.py:194-195).
  The test must fail because the dispatcher is invoked (the mock records the
  call, then raises; production swallows the raise into a needs-decision
  receipt, so the failure surfaces on the never-invoked assertion).
* FU-HOST-3 -- the on-host branch duplicate of the envelope check
  (fixed_codespace_pilot.py:476-477). Mutant: flip that branch's receipt
  status "blocked" -> "completed". The existing on-host test asserts only
  the reason code, so it evades this mutant; this test asserts the status,
  which is the authorization-consequential field (a "completed" receipt
  releases the dispatch claim at gate2 :970).

Harness note: the admitted-composition scaffolding (_descriptor, _current,
_Loader, _Resolver, _Lease, canonical fixture) is copied from the neighbor
file tests/agent_os_execution_interface/test_fixed_codespace_pilot.py, which
owns it. When filed, prefer importing/reusing that harness over duplicating
it; this candidate is self-contained only so it can run standalone locally.

No live provider/SSH/GCE/Docs/Notion calls: the dispatcher is a mock, the
Codespace listing/SSH run are never reached, and the lease/resolver/loader
are in-memory fakes.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

import agent_os_execution_service.current_invocation_resolver as resolver_module
import agent_os_execution_service.invocation_reconstruction as reconstruction
from agent_os_execution_service.executor_routing import (
    ExecutorCapability,
    ExecutorRoute,
)
from agent_os_execution_service.invocation_reconstruction import (
    CurrentInvocationEvidence,
)
from agent_os_execution_service.production_host_composition import (
    ProductionAdmissionProviders,
)
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    INVOCATION_DESCRIPTOR_SCHEMA_NAME,
    INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
    GovernedInvocationDescriptor,
)
from scripts.agent_os_execution_interface.fixed_codespace_pilot import (
    ISSUE_NUMBER,
    consume_fixed_codespace_pilot,
    consume_fixed_codespace_pilot_on_host,
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
        self.calls = []

    def __call__(self, handoff):
        self.calls.append(handoff)
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


class _RaisingDispatcher:
    """Records any invocation, then raises: entry itself is the violation."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError("NC15: dispatcher must never run for an invalid envelope")


def _event(body=TRIGGER, *, issue=ISSUE_NUMBER, actor="Blummer92", action="created"):
    return {
        "action": action,
        "repository": {"full_name": REPO},
        "issue": {"number": issue},
        "comment": {"id": 101, "body": body, "user": {"login": actor}},
        "sender": {"login": actor},
    }


def _admit(payload, *, attempt=1):
    return admit_issue_comment_event(
        payload, expected_repository=REPO,
        allowed_actor="Blummer92", run_attempt=attempt,
    )


def _tampered_actor_envelope():
    """Valid in every field except the actor: the envelope alone is invalid."""
    return {**_admit(_event()).to_dict(), "actor": "mallory"}


@pytest.fixture
def canonical(monkeypatch):
    """Real reconstruction/currentness with a controllable cross-check."""
    monkeypatch.setattr(reconstruction, "SingleIssuePilotInput", _Pilot)
    monkeypatch.setattr(reconstruction, "_lease_request", lambda _pilot: LEASE_REQUEST)
    monkeypatch.setattr(reconstruction, "_cross_check", lambda *_a, **_k: set())
    monkeypatch.setattr(resolver_module, "_cross_check", lambda *_a, **_k: set())


def test_nc15_invalid_envelope_never_invokes_dispatcher(canonical):
    """FU-HOST-1: an invalid envelope never reaches the dispatcher.

    The full admitted composition is supplied, so the *only* thing standing
    between the envelope and dispatch is the pre-execution envelope check.
    The dispatcher mock records any call and raises; the test asserts it was
    never invoked, no provider was reached, and the receipt is the blocked
    invalid-envelope receipt with no authority and no side effects.
    """
    descriptor = _descriptor()
    loader = _Loader(descriptor)
    resolver = _Resolver(_current(descriptor))
    dispatcher = _RaisingDispatcher()

    receipt = consume_fixed_codespace_pilot(
        _tampered_actor_envelope(),
        descriptor_loader=loader,
        current_resolver=resolver,
        lease_reader=_Lease(),
        codespace_selection=CodespaceSelection(True, "selected", CODESPACE, "Available"),
        evaluated_at=EVALUATED_AT,
        dispatcher=dispatcher,
    )

    assert dispatcher.calls == []
    assert loader.calls == []
    assert resolver.calls == 0
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["invalid-fixed-operation-envelope"]
    assert receipt["execution_authorized"] is False
    assert receipt["side_effects_performed"] is False


def test_nc15_fuhost3_on_host_branch_receipt_status_is_blocked(canonical):
    """FU-HOST-3: the on-host envelope branch receipts "blocked", not other.

    The on-host entry duplicates the envelope check before any host read
    (fixed_codespace_pilot.py:476-477). The existing on-host test asserts
    only the reason code, so flipping this branch's status evades it -- but
    a "completed" status here would release the dispatch claim at gate2.
    The selection reader fails the test if it is ever consulted.
    """
    descriptor = _descriptor()
    providers = ProductionAdmissionProviders(
        descriptor_loader=_Loader(descriptor),
        current_resolver=_Resolver(_current(descriptor)),
        lease_reader=_Lease(),
        evaluated_at=EVALUATED_AT,
    )
    dispatcher = _RaisingDispatcher()

    receipt = consume_fixed_codespace_pilot_on_host(
        _tampered_actor_envelope(),
        providers=providers,
        resolve_selection=lambda: pytest.fail("selection must not be read"),
        dispatcher=dispatcher,
    )

    assert dispatcher.calls == []
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["invalid-fixed-operation-envelope"]
    assert receipt["execution_authorized"] is False
    assert receipt["side_effects_performed"] is False
