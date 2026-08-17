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
from typing import Literal, Mapping, Protocol, runtime_checkable

CONTROL_PATH_SCHEMA_NAME = "agent-os-gce-control-path"
CONTROL_PATH_SCHEMA_VERSION = "1.0"
FIXED_ENTRYPOINT = "/usr/local/libexec/agent-os-governed-resume"
HANDOFF_RE = re.compile(r"^executor-handoff:[0-9a-f]{64}$")


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


def fixed_host_argv(handoff_id: str) -> tuple[str, ...]:
    if not validate_handoff_id(handoff_id):
        raise ValueError("handoff_id must be canonical executor-handoff identity")
    return (FIXED_ENTRYPOINT, "--handoff-id", handoff_id)


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


def run_gce_control_path(
    *,
    request_id: str,
    claims: Mapping[str, object],
    trust_policy: OidcTrustPolicy,
    resource: GceResourceTuple,
    expected_resource: GceResourceTuple,
    handoff_id: str,
    adapter: GceControlAdapter,
) -> GceControlPathResult:
    """Execute one bounded control-plane attempt with no retries.

    The function validates immutable transport data first, then performs at most
    one VM start, one readiness probe, one fixed host invocation, and one
    evidence-gated stop through the injected adapter.
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

    effects: list[str] = []
    try:
        initial = adapter.observe_state(resource)
    except (TypeError, ValueError, RuntimeError, OSError):
        return _make_result(
            status=ControlPathStatus.NEEDS_DECISION,
            reason_codes=(ControlPathReason.HOST_INVOCATION_UNAVAILABLE,),
            **base,
        )
    if type(initial) is not VmState:
        return _make_result(
            status=ControlPathStatus.NEEDS_DECISION,
            reason_codes=(ControlPathReason.HOST_INVOCATION_UNAVAILABLE,),
            **base,
        )
    base["vm_initial_state"] = initial
    base["vm_final_state"] = initial

    if initial is VmState.STOPPED:
        try:
            started = adapter.start(resource)
        except (TypeError, ValueError, RuntimeError, OSError):
            started = False
        if started is not True:
            return _make_result(
                status=ControlPathStatus.BLOCKED,
                reason_codes=(ControlPathReason.VM_START_FAILED,),
                **base,
            )
        effects.append("vm-start")
        base["start_issued"] = True
        try:
            running = adapter.wait_until_running(resource)
        except (TypeError, ValueError, RuntimeError, OSError):
            running = VmState.UNKNOWN
        base["vm_final_state"] = running
        if running is not VmState.RUNNING:
            base["side_effects_performed"] = tuple(effects)
            return _make_result(
                status=ControlPathStatus.BLOCKED,
                reason_codes=(ControlPathReason.VM_START_FAILED,),
                **base,
            )
    elif initial is not VmState.RUNNING:
        return _make_result(
            status=ControlPathStatus.BLOCKED,
            reason_codes=(ControlPathReason.VM_TRANSITIONAL,),
            **base,
        )

    try:
        ready = adapter.probe_ready(resource)
    except (TypeError, ValueError, RuntimeError, OSError):
        ready = False
    if ready is not True:
        base["side_effects_performed"] = tuple(effects)
        return _make_result(
            status=ControlPathStatus.BLOCKED,
            reason_codes=(ControlPathReason.HOST_NOT_READY,),
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

    if eligible:
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
