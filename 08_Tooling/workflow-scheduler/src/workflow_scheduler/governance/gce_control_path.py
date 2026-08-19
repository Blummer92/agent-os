"""Pure bounded GCE control-path contract for Agent OS governed invocation.

This module models the #1217 GitHub OIDC -> GCE control path without performing
network, subprocess, credential, GitHub, Google API, Scheduler, lease, retry, or
persistence I/O. All external effects are delegated to one injected adapter.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Literal, Mapping, Protocol, runtime_checkable

CONTROL_PATH_SCHEMA_NAME = "agent-os-gce-control-path"
CONTROL_PATH_SCHEMA_VERSION = "1.0"
DISCOVERY_PATH_SCHEMA_NAME = "agent-os-gce-discovery-path"
DISCOVERY_PATH_SCHEMA_VERSION = "1.0"
FIXED_ENTRYPOINT = "/usr/local/libexec/agent-os-governed-resume"
#: The #1284 read-only locator entrypoint. It is a separate fixed path from the
#: resume entrypoint so that discovery can never reach the execution binary and
#: host readiness for one says nothing about the other.
FIXED_DISCOVERY_ENTRYPOINT = "/usr/local/libexec/agent-os-handoff-discovery"
HANDOFF_RE = re.compile(r"^executor-handoff:[0-9a-f]{64}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)
DISCOVERY_STATUSES = ("found", "not-found", "needs-decision")


class VmState(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    STAGING = "staging"
    STOPPING = "stopping"
    SUSPENDING = "suspending"
    UNKNOWN = "unknown"
    UNREACHABLE = "unreachable"


class ControlPathStatus(str, Enum):
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs-decision"


class ControlPathReason(str, Enum):
    ACCEPTED = "accepted"
    CLAIMS_REJECTED = "claims-rejected"
    RESOURCE_MISMATCH = "resource-mismatch"
    HANDOFF_INVALID = "handoff-invalid"
    VM_TRANSITIONAL = "vm-transitional"
    VM_START_FAILED = "vm-start-failed"
    HOST_NOT_READY = "host-not-ready"
    HOST_INVOCATION_BLOCKED = "host-invocation-blocked"
    HOST_INVOCATION_UNAVAILABLE = "host-invocation-unavailable"
    SHUTDOWN_WITHHELD = "shutdown-withheld"
    SHUTDOWN_FAILED = "shutdown-failed"
    # #1284 read-only discovery outcomes. They share this transport vocabulary
    # because discovery reuses the same control path; only the terminal step and
    # the returned projection differ.
    DISCOVERY_COMPLETED = "discovery-completed"
    DISCOVERY_IDENTITY_INVALID = "discovery-identity-invalid"
    DISCOVERY_EVIDENCE_UNAVAILABLE = "discovery-evidence-unavailable"


@dataclass(frozen=True, slots=True, kw_only=True)
class GceResourceTuple:
    project: str
    zone: str
    instance: str

    def __post_init__(self) -> None:
        for name in ("project", "zone", "instance"):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError(f"{name} must be non-empty exact text")
            if len(value) > 128:
                raise ValueError(f"{name} exceeds bounded length")


@dataclass(frozen=True, slots=True, kw_only=True)
class OidcTrustPolicy:
    repository: str
    repository_owner: str
    workflow_ref: str
    ref: str
    audience: str

    def __post_init__(self) -> None:
        for name in ("repository", "repository_owner", "workflow_ref", "ref", "audience"):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError(f"{name} must be non-empty exact text")
            if len(value) > 1024:
                raise ValueError(f"{name} exceeds bounded length")

    def accepts(self, claims: Mapping[str, object]) -> bool:
        if not isinstance(claims, Mapping):
            return False
        expected = {
            "repository": self.repository,
            "repository_owner": self.repository_owner,
            "workflow_ref": self.workflow_ref,
            "ref": self.ref,
            "aud": self.audience,
        }
        return all(
            type(claims.get(key)) is str and claims.get(key) == value
            for key, value in expected.items()
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class HostInvocationEvidence:
    invoked: bool
    accepted: bool
    scheduler_invocation_id: str | None = None
    execution_id: str | None = None
    terminal_status: str | None = None
    termination_confirmed: bool = False
    lease_released: bool = False
    cleanup_complete: bool = False
    retained_lease: bool = False
    quarantined: bool = False
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        if self.accepted and not self.invoked:
            raise ValueError("accepted host evidence requires an invocation attempt")
        for name in ("scheduler_invocation_id", "execution_id", "terminal_status"):
            value = getattr(self, name)
            if value is not None and (
                type(value) is not str or not value or len(value) > 512
            ):
                raise ValueError(f"{name} must be bounded text when present")
        for item in self.evidence_refs:
            if type(item) is not str or not item or len(item) > 512:
                raise ValueError("evidence_refs must contain bounded text")
        if len(self.evidence_refs) > 32:
            raise ValueError("too many evidence refs")


@dataclass(frozen=True, slots=True, kw_only=True)
class GceControlPathResult:
    schema_name: Literal["agent-os-gce-control-path"]
    schema_version: Literal["1.0"]
    result_id: str
    status: ControlPathStatus
    reason_codes: tuple[ControlPathReason, ...]
    request_id: str
    handoff_id: str
    resource: GceResourceTuple
    vm_initial_state: VmState | None
    vm_final_state: VmState | None
    start_issued: bool
    host_ready: bool
    host_invoked: bool
    host_accepted: bool
    scheduler_invocation_id: str | None
    execution_id: str | None
    terminal_status: str | None
    shutdown_eligible: bool
    shutdown_issued: bool
    side_effects_performed: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    retry_attempted: Literal[False] = field(default=False, init=False)
    arbitrary_command_authorized: Literal[False] = field(default=False, init=False)
    scheduler_authorized_by_transport: Literal[False] = field(default=False, init=False)
    lease_authorized_by_transport: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_name != CONTROL_PATH_SCHEMA_NAME
            or self.schema_version != CONTROL_PATH_SCHEMA_VERSION
        ):
            raise ValueError("unsupported control-path schema")
        canonical = tuple(sorted(set(self.reason_codes), key=lambda item: item.value))
        if self.reason_codes != canonical or not canonical:
            raise ValueError("reason_codes must be sorted, unique, and non-empty")
        object.__setattr__(
            self, "side_effects_performed", tuple(self.side_effects_performed)
        )
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        if self.result_id != _result_id(self):
            raise ValueError("result_id does not match result payload")


@dataclass(frozen=True, slots=True, kw_only=True)
class HostDiscoveryEvidence:
    """Bounded projection of one canonical #1242 discovery result from the host.

    The host is the only party that reads the checkpoint store. This structure
    carries its answer back across the transport without granting authority: a
    ``found`` status names an already-existing immutable handoff and nothing
    more. Currentness stays with #1218 and admission stays with the Scheduler.
    """

    invoked: bool
    status: str
    reason_codes: tuple[str, ...]
    repository: str
    issue_number: int
    matching_descriptor_count: int | None
    handoff_id: str | None
    result_id: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        if type(self.invoked) is not bool:
            raise TypeError("invoked must be bool")
        if self.status not in DISCOVERY_STATUSES:
            raise ValueError("status must be a canonical discovery status")
        if not self.reason_codes or len(self.reason_codes) > 8:
            raise ValueError("reason_codes must be a bounded non-empty tuple")
        for item in self.reason_codes:
            if type(item) is not str or not item or len(item) > 80:
                raise ValueError("reason_codes must contain bounded text")
        if not validate_repository(self.repository):
            raise ValueError("repository must use bounded owner/name syntax")
        if not validate_issue_number(self.issue_number):
            raise ValueError("issue_number must be a bounded positive integer")
        if self.matching_descriptor_count is not None and (
            type(self.matching_descriptor_count) is not int
            or self.matching_descriptor_count < 0
        ):
            raise TypeError("matching_descriptor_count must be a non-negative integer")
        if self.result_id is not None and (
            type(self.result_id) is not str
            or not self.result_id
            or len(self.result_id) > 512
        ):
            raise ValueError("result_id must be bounded non-empty text when present")
        # A host that could not produce a canonical #1242 result may omit the
        # count and result identity, but it can never omit them and still claim
        # to have found a handoff.
        if self.status == "found":
            if not validate_handoff_id(self.handoff_id):
                raise ValueError("found evidence requires a canonical handoff identity")
            if self.matching_descriptor_count != 1:
                raise ValueError("found evidence requires exactly one descriptor")
            if type(self.result_id) is not str:
                raise ValueError("found evidence requires a canonical result identity")
        elif self.handoff_id is not None:
            raise ValueError("non-found evidence must not expose a handoff identity")


@runtime_checkable
class GceControlAdapter(Protocol):
    def observe_state(self, resource: GceResourceTuple) -> VmState: ...
    def start(self, resource: GceResourceTuple) -> bool: ...
    def wait_until_running(self, resource: GceResourceTuple) -> VmState: ...
    def probe_ready(self, resource: GceResourceTuple) -> bool: ...
    def invoke(
        self, resource: GceResourceTuple, argv: tuple[str, ...]
    ) -> HostInvocationEvidence: ...
    def stop(self, resource: GceResourceTuple) -> bool: ...


@runtime_checkable
class GceDiscoveryAdapter(Protocol):
    """Read-only adapter surface. It has no ``invoke`` and no ``stop``."""

    def observe_state(self, resource: GceResourceTuple) -> VmState: ...
    def start(self, resource: GceResourceTuple) -> bool: ...
    def wait_until_running(self, resource: GceResourceTuple) -> VmState: ...
    def probe_discovery_ready(self, resource: GceResourceTuple) -> bool: ...
    def discover(
        self, resource: GceResourceTuple, argv: tuple[str, ...]
    ) -> HostDiscoveryEvidence: ...


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _result_payload(result: GceControlPathResult) -> dict[str, object]:
    return {
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "status": result.status.value,
        "reason_codes": [item.value for item in result.reason_codes],
        "request_id": result.request_id,
        "handoff_id": result.handoff_id,
        "resource": {
            "project": result.resource.project,
            "zone": result.resource.zone,
            "instance": result.resource.instance,
        },
        "vm_initial_state": (
            None if result.vm_initial_state is None else result.vm_initial_state.value
        ),
        "vm_final_state": (
            None if result.vm_final_state is None else result.vm_final_state.value
        ),
        "start_issued": result.start_issued,
        "host_ready": result.host_ready,
        "host_invoked": result.host_invoked,
        "host_accepted": result.host_accepted,
        "scheduler_invocation_id": result.scheduler_invocation_id,
        "execution_id": result.execution_id,
        "terminal_status": result.terminal_status,
        "shutdown_eligible": result.shutdown_eligible,
        "shutdown_issued": result.shutdown_issued,
        "side_effects_performed": list(result.side_effects_performed),
        "evidence_refs": list(result.evidence_refs),
    }


def _result_id(result: GceControlPathResult) -> str:
    digest = hashlib.sha256(
        b"agent-os-gce-control-path:v1\0" + _canonical_bytes(_result_payload(result))
    ).hexdigest()
    return f"gce-control-path:{digest}"


def _make_result(**kwargs: object) -> GceControlPathResult:
    status = kwargs["status"]
    reason_codes = kwargs["reason_codes"]
    resource = kwargs["resource"]
    vm_initial_state = kwargs["vm_initial_state"]
    vm_final_state = kwargs["vm_final_state"]
    payload = {
        "schema_name": kwargs["schema_name"],
        "schema_version": kwargs["schema_version"],
        "status": status.value,
        "reason_codes": [item.value for item in reason_codes],
        "request_id": kwargs["request_id"],
        "handoff_id": kwargs["handoff_id"],
        "resource": {
            "project": resource.project,
            "zone": resource.zone,
            "instance": resource.instance,
        },
        "vm_initial_state": (
            None if vm_initial_state is None else vm_initial_state.value
        ),
        "vm_final_state": None if vm_final_state is None else vm_final_state.value,
        "start_issued": kwargs["start_issued"],
        "host_ready": kwargs["host_ready"],
        "host_invoked": kwargs["host_invoked"],
        "host_accepted": kwargs["host_accepted"],
        "scheduler_invocation_id": kwargs["scheduler_invocation_id"],
        "execution_id": kwargs["execution_id"],
        "terminal_status": kwargs["terminal_status"],
        "shutdown_eligible": kwargs["shutdown_eligible"],
        "shutdown_issued": kwargs["shutdown_issued"],
        "side_effects_performed": list(kwargs["side_effects_performed"]),
        "evidence_refs": list(kwargs["evidence_refs"]),
    }
    digest = hashlib.sha256(
        b"agent-os-gce-control-path:v1\0" + _canonical_bytes(payload)
    ).hexdigest()
    return GceControlPathResult(
        result_id=f"gce-control-path:{digest}",
        **kwargs,  # type: ignore[arg-type]
    )


def validate_handoff_id(handoff_id: str) -> bool:
    return type(handoff_id) is str and HANDOFF_RE.fullmatch(handoff_id) is not None


def validate_repository(repository: object) -> bool:
    return (
        type(repository) is str
        and len(repository) <= 512
        and REPOSITORY_RE.fullmatch(repository) is not None
    )


def validate_issue_number(issue_number: object) -> bool:
    return type(issue_number) is int and 1 <= issue_number <= 2_147_483_647


def fixed_host_argv(handoff_id: str) -> tuple[str, ...]:
    if not validate_handoff_id(handoff_id):
        raise ValueError("handoff_id must be canonical executor-handoff identity")
    return (FIXED_ENTRYPOINT, "--handoff-id", handoff_id)


def fixed_discovery_argv(repository: str, issue_number: int) -> tuple[str, ...]:
    """Build the only argv the read-only discovery entrypoint ever receives.

    No store root, path, handoff, branch, flag, or free-form text is accepted.
    """
    if not validate_repository(repository):
        raise ValueError("repository must use bounded owner/name syntax")
    if not validate_issue_number(issue_number):
        raise ValueError("issue_number must be a bounded positive integer")
    return (
        FIXED_DISCOVERY_ENTRYPOINT,
        "--repository",
        repository,
        "--issue-number",
        str(issue_number),
    )


def _shutdown_eligible(evidence: HostInvocationEvidence) -> bool:
    if evidence.retained_lease or evidence.quarantined:
        return False
    if evidence.terminal_status in {"succeeded", "validation-failed"}:
        return (
            evidence.termination_confirmed
            and evidence.lease_released
            and evidence.cleanup_complete
        )
    if evidence.terminal_status == "blocked-before-execution":
        return (
            (not evidence.accepted)
            and evidence.termination_confirmed
            and evidence.lease_released
            and evidence.cleanup_complete
        )
    return False


@dataclass(frozen=True, slots=True, kw_only=True)
class _HostReadiness:
    """Outcome of the shared start-if-stopped and readiness-probe sequence."""

    initial_state: VmState | None
    final_state: VmState | None
    start_issued: bool
    effects: tuple[str, ...]
    failure_status: ControlPathStatus | None
    failure_reason: ControlPathReason | None


def _reach_ready_host(
    resource: GceResourceTuple,
    adapter: object,
    probe: Callable[[GceResourceTuple], bool],
) -> _HostReadiness:
    """Bring the fixed host to a probe-confirmed ready state, at most once.

    Both the resume control path and the #1284 read-only discovery path share
    this sequence so there is exactly one VM lifecycle implementation. The only
    thing that varies is which fixed entrypoint the caller probes for.
    """
    effects: list[str] = []

    def failed(
        *,
        status: ControlPathStatus,
        reason: ControlPathReason,
        initial: VmState | None = None,
        final: VmState | None = None,
        start_issued: bool = False,
    ) -> _HostReadiness:
        return _HostReadiness(
            initial_state=initial,
            final_state=final,
            start_issued=start_issued,
            effects=tuple(effects),
            failure_status=status,
            failure_reason=reason,
        )

    try:
        initial = adapter.observe_state(resource)
    except (TypeError, ValueError, RuntimeError, OSError):
        initial = None
    if type(initial) is not VmState:
        return failed(
            status=ControlPathStatus.NEEDS_DECISION,
            reason=ControlPathReason.HOST_INVOCATION_UNAVAILABLE,
        )

    final = initial
    start_issued = False
    if initial is VmState.STOPPED:
        try:
            started = adapter.start(resource)
        except (TypeError, ValueError, RuntimeError, OSError):
            started = False
        if started is not True:
            return failed(
                status=ControlPathStatus.BLOCKED,
                reason=ControlPathReason.VM_START_FAILED,
                initial=initial,
                final=final,
            )
        effects.append("vm-start")
        start_issued = True
        try:
            running = adapter.wait_until_running(resource)
        except (TypeError, ValueError, RuntimeError, OSError):
            running = VmState.UNKNOWN
        final = running
        if running is not VmState.RUNNING:
            return failed(
                status=ControlPathStatus.BLOCKED,
                reason=ControlPathReason.VM_START_FAILED,
                initial=initial,
                final=final,
                start_issued=True,
            )
    elif initial is not VmState.RUNNING:
        return failed(
            status=ControlPathStatus.BLOCKED,
            reason=ControlPathReason.VM_TRANSITIONAL,
            initial=initial,
            final=final,
        )

    try:
        ready = probe(resource)
    except (TypeError, ValueError, RuntimeError, OSError):
        ready = False
    if ready is not True:
        return failed(
            status=ControlPathStatus.BLOCKED,
            reason=ControlPathReason.HOST_NOT_READY,
            initial=initial,
            final=final,
            start_issued=start_issued,
        )

    return _HostReadiness(
        initial_state=initial,
        final_state=final,
        start_issued=start_issued,
        effects=tuple(effects),
        failure_status=None,
        failure_reason=None,
    )


def run_gce_control_path(
    *,
    request_id: str,
    claims: Mapping[str, object],
    trust_policy: OidcTrustPolicy,
    resource: GceResourceTuple,
    expected_resource: GceResourceTuple,
    handoff_id: str,
    adapter: GceControlAdapter,
    allow_shutdown: bool = True,
) -> GceControlPathResult:
    """Execute one bounded control-plane attempt with no retries.

    The function validates immutable transport data first, then performs at most
    one VM start, one readiness probe, one fixed host invocation, and, only when
    explicitly enabled, one evidence-gated stop through the injected adapter.
    """
    if type(request_id) is not str or not request_id or len(request_id) > 512:
        raise ValueError("request_id must be bounded non-empty text")
    if type(allow_shutdown) is not bool:
        raise TypeError("allow_shutdown must be bool")
    if not isinstance(trust_policy, OidcTrustPolicy):
        raise TypeError("trust_policy must be OidcTrustPolicy")
    if (
        type(resource) is not GceResourceTuple
        or type(expected_resource) is not GceResourceTuple
    ):
        raise TypeError("resource values must be exact GceResourceTuple")
    if not isinstance(adapter, GceControlAdapter):
        raise TypeError("adapter must satisfy GceControlAdapter")

    base = dict(
        schema_name=CONTROL_PATH_SCHEMA_NAME,
        schema_version=CONTROL_PATH_SCHEMA_VERSION,
        request_id=request_id,
        handoff_id=handoff_id,
        resource=resource,
        vm_initial_state=None,
        vm_final_state=None,
        start_issued=False,
        host_ready=False,
        host_invoked=False,
        host_accepted=False,
        scheduler_invocation_id=None,
        execution_id=None,
        terminal_status=None,
        shutdown_eligible=False,
        shutdown_issued=False,
        side_effects_performed=(),
        evidence_refs=(),
    )

    if not trust_policy.accepts(claims):
        return _make_result(
            status=ControlPathStatus.BLOCKED,
            reason_codes=(ControlPathReason.CLAIMS_REJECTED,),
            **base,
        )
    if resource != expected_resource:
        return _make_result(
            status=ControlPathStatus.BLOCKED,
            reason_codes=(ControlPathReason.RESOURCE_MISMATCH,),
            **base,
        )
    if not validate_handoff_id(handoff_id):
        return _make_result(
            status=ControlPathStatus.BLOCKED,
            reason_codes=(ControlPathReason.HANDOFF_INVALID,),
            **base,
        )

    readiness = _reach_ready_host(resource, adapter, adapter.probe_ready)
    effects: list[str] = list(readiness.effects)
    base["vm_initial_state"] = readiness.initial_state
    base["vm_final_state"] = readiness.final_state
    base["start_issued"] = readiness.start_issued
    base["side_effects_performed"] = readiness.effects
    if readiness.failure_reason is not None:
        return _make_result(
            status=readiness.failure_status,
            reason_codes=(readiness.failure_reason,),
            **base,
        )
    base["host_ready"] = True

    argv = fixed_host_argv(handoff_id)
    try:
        evidence = adapter.invoke(resource, argv)
    except (TypeError, ValueError, RuntimeError, OSError):
        base["side_effects_performed"] = tuple(effects)
        return _make_result(
            status=ControlPathStatus.NEEDS_DECISION,
            reason_codes=(ControlPathReason.HOST_INVOCATION_UNAVAILABLE,),
            **base,
        )
    if type(evidence) is not HostInvocationEvidence:
        base["side_effects_performed"] = tuple(effects)
        return _make_result(
            status=ControlPathStatus.NEEDS_DECISION,
            reason_codes=(ControlPathReason.HOST_INVOCATION_UNAVAILABLE,),
            **base,
        )
    effects.append("host-invocation")
    base.update(
        host_invoked=evidence.invoked,
        host_accepted=evidence.accepted,
        scheduler_invocation_id=evidence.scheduler_invocation_id,
        execution_id=evidence.execution_id,
        terminal_status=evidence.terminal_status,
        evidence_refs=evidence.evidence_refs,
    )

    eligible = _shutdown_eligible(evidence)
    base["shutdown_eligible"] = eligible
    reasons: list[ControlPathReason] = []
    status = (
        ControlPathStatus.ACCEPTED if evidence.accepted else ControlPathStatus.BLOCKED
    )
    reasons.append(
        ControlPathReason.ACCEPTED
        if evidence.accepted
        else ControlPathReason.HOST_INVOCATION_BLOCKED
    )

    if eligible and allow_shutdown:
        try:
            stopped = adapter.stop(resource)
        except (TypeError, ValueError, RuntimeError, OSError):
            stopped = False
        if stopped is True:
            effects.append("vm-stop")
            base["shutdown_issued"] = True
            base["vm_final_state"] = VmState.STOPPED
        else:
            reasons.append(ControlPathReason.SHUTDOWN_FAILED)
            status = ControlPathStatus.NEEDS_DECISION
    elif evidence.invoked:
        reasons.append(ControlPathReason.SHUTDOWN_WITHHELD)

    base["side_effects_performed"] = tuple(effects)
    return _make_result(
        status=status,
        reason_codes=tuple(sorted(set(reasons), key=lambda item: item.value)),
        **base,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class GceDiscoveryPathResult:
    """Bounded, non-authorizing result of one read-only discovery attempt."""

    schema_name: Literal["agent-os-gce-discovery-path"]
    schema_version: Literal["1.0"]
    result_id: str
    status: ControlPathStatus
    reason_codes: tuple[ControlPathReason, ...]
    request_id: str
    repository: str
    issue_number: int
    resource: GceResourceTuple
    vm_initial_state: VmState | None
    vm_final_state: VmState | None
    start_issued: bool
    host_ready: bool
    host_invoked: bool
    discovery_status: str | None
    discovery_reason_codes: tuple[str, ...]
    matching_descriptor_count: int | None
    handoff_id: str | None
    discovery_result_id: str | None
    side_effects_performed: tuple[str, ...]
    #: Discovery is a locator. Every one of these stays false by construction,
    #: including on a ``found`` result.
    execution_authorized: Literal[False] = field(default=False, init=False)
    scheduler_invoked: Literal[False] = field(default=False, init=False)
    lease_acquired: Literal[False] = field(default=False, init=False)
    handoff_persisted: Literal[False] = field(default=False, init=False)
    checkpoint_store_written: Literal[False] = field(default=False, init=False)
    retry_attempted: Literal[False] = field(default=False, init=False)
    arbitrary_command_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_name != DISCOVERY_PATH_SCHEMA_NAME
            or self.schema_version != DISCOVERY_PATH_SCHEMA_VERSION
        ):
            raise ValueError("unsupported discovery-path schema")
        canonical = tuple(sorted(set(self.reason_codes), key=lambda item: item.value))
        if self.reason_codes != canonical or not canonical:
            raise ValueError("reason_codes must be sorted, unique, and non-empty")
        object.__setattr__(
            self, "side_effects_performed", tuple(self.side_effects_performed)
        )
        object.__setattr__(
            self, "discovery_reason_codes", tuple(self.discovery_reason_codes)
        )
        if not validate_repository(self.repository):
            raise ValueError("repository must use bounded owner/name syntax")
        if not validate_issue_number(self.issue_number):
            raise ValueError("issue_number must be a bounded positive integer")
        if self.handoff_id is not None:
            if self.discovery_status != "found":
                raise ValueError("only a found discovery may expose a handoff identity")
            if not validate_handoff_id(self.handoff_id):
                raise ValueError("handoff_id must be canonical")
        if self.result_id != _discovery_result_id(self):
            raise ValueError("result_id does not match result payload")

    def to_dict(self) -> dict[str, object]:
        return _discovery_payload(self)


def _discovery_payload(result: GceDiscoveryPathResult) -> dict[str, object]:
    return {
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "status": result.status.value,
        "reason_codes": [item.value for item in result.reason_codes],
        "request_id": result.request_id,
        "repository": result.repository,
        "issue_number": result.issue_number,
        "resource": {
            "project": result.resource.project,
            "zone": result.resource.zone,
            "instance": result.resource.instance,
        },
        "vm_initial_state": (
            None if result.vm_initial_state is None else result.vm_initial_state.value
        ),
        "vm_final_state": (
            None if result.vm_final_state is None else result.vm_final_state.value
        ),
        "start_issued": result.start_issued,
        "host_ready": result.host_ready,
        "host_invoked": result.host_invoked,
        "discovery_status": result.discovery_status,
        "discovery_reason_codes": list(result.discovery_reason_codes),
        "matching_descriptor_count": result.matching_descriptor_count,
        "handoff_id": result.handoff_id,
        "discovery_result_id": result.discovery_result_id,
        "side_effects_performed": list(result.side_effects_performed),
        "execution_authorized": False,
        "scheduler_invoked": False,
        "lease_acquired": False,
        "handoff_persisted": False,
        "checkpoint_store_written": False,
        "retry_attempted": False,
        "arbitrary_command_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "issue_closure_authorized": False,
    }


def _discovery_identity_material(
    *,
    status: ControlPathStatus,
    reason_codes: tuple[ControlPathReason, ...],
    request_id: str,
    repository: str,
    issue_number: int,
    resource: GceResourceTuple,
    vm_initial_state: VmState | None,
    vm_final_state: VmState | None,
    start_issued: bool,
    host_ready: bool,
    host_invoked: bool,
    discovery_status: str | None,
    discovery_reason_codes: tuple[str, ...],
    matching_descriptor_count: int | None,
    handoff_id: str | None,
    discovery_result_id: str | None,
    side_effects_performed: tuple[str, ...],
) -> str:
    payload = {
        "schema_name": DISCOVERY_PATH_SCHEMA_NAME,
        "schema_version": DISCOVERY_PATH_SCHEMA_VERSION,
        "status": status.value,
        "reason_codes": [item.value for item in reason_codes],
        "request_id": request_id,
        "repository": repository,
        "issue_number": issue_number,
        "resource": {
            "project": resource.project,
            "zone": resource.zone,
            "instance": resource.instance,
        },
        "vm_initial_state": (
            None if vm_initial_state is None else vm_initial_state.value
        ),
        "vm_final_state": None if vm_final_state is None else vm_final_state.value,
        "start_issued": start_issued,
        "host_ready": host_ready,
        "host_invoked": host_invoked,
        "discovery_status": discovery_status,
        "discovery_reason_codes": list(discovery_reason_codes),
        "matching_descriptor_count": matching_descriptor_count,
        "handoff_id": handoff_id,
        "discovery_result_id": discovery_result_id,
        "side_effects_performed": list(side_effects_performed),
    }
    digest = hashlib.sha256(
        b"agent-os-gce-discovery-path:v1\0" + _canonical_bytes(payload)
    ).hexdigest()
    return f"gce-discovery-path:{digest}"


def _discovery_result_id(result: GceDiscoveryPathResult) -> str:
    return _discovery_identity_material(
        status=result.status,
        reason_codes=result.reason_codes,
        request_id=result.request_id,
        repository=result.repository,
        issue_number=result.issue_number,
        resource=result.resource,
        vm_initial_state=result.vm_initial_state,
        vm_final_state=result.vm_final_state,
        start_issued=result.start_issued,
        host_ready=result.host_ready,
        host_invoked=result.host_invoked,
        discovery_status=result.discovery_status,
        discovery_reason_codes=result.discovery_reason_codes,
        matching_descriptor_count=result.matching_descriptor_count,
        handoff_id=result.handoff_id,
        discovery_result_id=result.discovery_result_id,
        side_effects_performed=result.side_effects_performed,
    )


def _make_discovery_result(**kwargs: object) -> GceDiscoveryPathResult:
    return GceDiscoveryPathResult(
        schema_name=DISCOVERY_PATH_SCHEMA_NAME,
        schema_version=DISCOVERY_PATH_SCHEMA_VERSION,
        result_id=_discovery_identity_material(**kwargs),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def run_gce_discovery_path(
    *,
    request_id: str,
    claims: Mapping[str, object],
    trust_policy: OidcTrustPolicy,
    resource: GceResourceTuple,
    expected_resource: GceResourceTuple,
    repository: str,
    issue_number: int,
    adapter: GceDiscoveryAdapter,
) -> GceDiscoveryPathResult:
    """Run one bounded read-only handoff lookup over the existing transport.

    This is the same trust boundary, the same fixed resource, and the same
    one-attempt lifecycle as ``run_gce_control_path``. The differences are the
    whole point of #1284: the terminal step is the fixed read-only discovery
    entrypoint instead of the resume entrypoint, no Scheduler or lease is ever
    reached, and the returned handoff identity is evidence rather than
    authority. It never shuts the host down, never retries, and never selects
    between candidate descriptors -- that judgement stays inside canonical
    #1242 on the host.
    """
    if type(request_id) is not str or not request_id or len(request_id) > 512:
        raise ValueError("request_id must be bounded non-empty text")
    if not isinstance(trust_policy, OidcTrustPolicy):
        raise TypeError("trust_policy must be OidcTrustPolicy")
    if (
        type(resource) is not GceResourceTuple
        or type(expected_resource) is not GceResourceTuple
    ):
        raise TypeError("resource values must be exact GceResourceTuple")
    if not isinstance(adapter, GceDiscoveryAdapter):
        raise TypeError("adapter must satisfy GceDiscoveryAdapter")

    identity_valid = validate_repository(repository) and validate_issue_number(
        issue_number
    )
    base = dict(
        request_id=request_id,
        repository=repository if validate_repository(repository) else "invalid/invalid",
        issue_number=issue_number if validate_issue_number(issue_number) else 1,
        resource=resource,
        vm_initial_state=None,
        vm_final_state=None,
        start_issued=False,
        host_ready=False,
        host_invoked=False,
        discovery_status=None,
        discovery_reason_codes=(),
        matching_descriptor_count=None,
        handoff_id=None,
        discovery_result_id=None,
        side_effects_performed=(),
    )

    if not trust_policy.accepts(claims):
        return _make_discovery_result(
            status=ControlPathStatus.BLOCKED,
            reason_codes=(ControlPathReason.CLAIMS_REJECTED,),
            **base,
        )
    if resource != expected_resource:
        return _make_discovery_result(
            status=ControlPathStatus.BLOCKED,
            reason_codes=(ControlPathReason.RESOURCE_MISMATCH,),
            **base,
        )
    if not identity_valid:
        return _make_discovery_result(
            status=ControlPathStatus.BLOCKED,
            reason_codes=(ControlPathReason.DISCOVERY_IDENTITY_INVALID,),
            **base,
        )

    readiness = _reach_ready_host(resource, adapter, adapter.probe_discovery_ready)
    base["vm_initial_state"] = readiness.initial_state
    base["vm_final_state"] = readiness.final_state
    base["start_issued"] = readiness.start_issued
    base["side_effects_performed"] = readiness.effects
    if readiness.failure_reason is not None:
        return _make_discovery_result(
            status=readiness.failure_status,
            reason_codes=(readiness.failure_reason,),
            **base,
        )
    base["host_ready"] = True

    argv = fixed_discovery_argv(repository, issue_number)
    try:
        evidence = adapter.discover(resource, argv)
    except (TypeError, ValueError, RuntimeError, OSError):
        return _make_discovery_result(
            status=ControlPathStatus.NEEDS_DECISION,
            reason_codes=(ControlPathReason.DISCOVERY_EVIDENCE_UNAVAILABLE,),
            **base,
        )
    if type(evidence) is not HostDiscoveryEvidence or not evidence.invoked:
        return _make_discovery_result(
            status=ControlPathStatus.NEEDS_DECISION,
            reason_codes=(ControlPathReason.DISCOVERY_EVIDENCE_UNAVAILABLE,),
            **base,
        )
    # The host answers about the identity this transport asked about, or its
    # answer is not usable evidence. A mismatched echo fails closed rather than
    # being reported against the requested issue.
    if (
        evidence.repository.casefold() != repository.casefold()
        or evidence.issue_number != issue_number
    ):
        base["side_effects_performed"] = tuple(
            (*readiness.effects, "discovery-invocation")
        )
        base["host_invoked"] = True
        return _make_discovery_result(
            status=ControlPathStatus.NEEDS_DECISION,
            reason_codes=(ControlPathReason.DISCOVERY_EVIDENCE_UNAVAILABLE,),
            **base,
        )

    base["side_effects_performed"] = tuple((*readiness.effects, "discovery-invocation"))
    base["host_invoked"] = True
    base["discovery_status"] = evidence.status
    base["discovery_reason_codes"] = tuple(sorted(set(evidence.reason_codes)))
    base["matching_descriptor_count"] = evidence.matching_descriptor_count
    base["handoff_id"] = evidence.handoff_id
    base["discovery_result_id"] = evidence.result_id
    status = (
        ControlPathStatus.ACCEPTED
        if evidence.status in ("found", "not-found")
        else ControlPathStatus.NEEDS_DECISION
    )
    return _make_discovery_result(
        status=status,
        reason_codes=(ControlPathReason.DISCOVERY_COMPLETED,),
        **base,
    )
