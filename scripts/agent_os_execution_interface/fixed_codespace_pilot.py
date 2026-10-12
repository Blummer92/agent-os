"""Fixed #3333 Codespaces admission consumer (no arbitrary shell or authority).

An issue comment is low-trust transport evidence only. This module can dispatch
a *read-only* exact-HEAD probe only when the canonical #1218 reconstruction,
current authorization and the existing current Codespace selection are supplied
by a qualified host. The GitHub Actions CLI fails closed until such a host-side
source is connected: it never synthesizes execution admission or runner health.

The real bounded engineering command plan/live synchronous pilot require a
separately admitted plan and host configuration. This probe does not grant that.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Callable

REPOSITORY = "Blummer92/agent-os"
ISSUE_NUMBER = 3333
OPERATION_ID = "codespace-implementation-pilot-v1"
ACCEPTED_REASON = "accepted-codespace-implementation-envelope"
FIXED_ARGV = ("git", "rev-parse", "HEAD")
_SHA40 = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_HANDOFF = re.compile(r"^executor-handoff:[0-9a-f]{64}$", re.ASCII)


def _receipt(status: str, reason: str, transport: dict[str, Any]) -> dict[str, object]:
    """Return a finite, non-authoritative, public-safe result."""
    return {
        "schema_version": "1.0",
        "operation_id": OPERATION_ID,
        "status": status,
        "reason_codes": [reason],
        "repository": REPOSITORY,
        "issue_number": ISSUE_NUMBER,
        "logical_trigger_id": transport.get("logical_trigger_id_or_none"),
        "handoff_id": transport.get("codespace_implementation_handoff_id_or_none"),
        "expected_sha": transport.get("codespace_implementation_sha_or_none"),
        "request_id": None,
        "codespace_name": None,
        "exit_status": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "execution_authorized": False,
        "github_writes_authorized": False,
        "external_writes_authorized": False,
        "publication_authorized": False,
        "merge_authorized": False,
        "scheduler_invoked": False,
        "side_effects_performed": False,
    }


def _valid_transport(transport: object) -> bool:
    if type(transport) is not dict:
        return False
    return (
        transport.get("schema_version") == "1.0"
        and transport.get("status") == "accepted"
        and transport.get("reason") == ACCEPTED_REASON
        and transport.get("repository") == REPOSITORY
        and type(transport.get("issue_number")) is int
        and transport.get("issue_number") == ISSUE_NUMBER
        and transport.get("actor") == "Blummer92"
        and transport.get("run_attempt") == 1
        and type(transport.get("logical_trigger_id_or_none")) is str
        and transport["logical_trigger_id_or_none"].startswith("issue-comment-trigger:")
        and type(transport.get("codespace_implementation_handoff_id_or_none")) is str
        and _HANDOFF.fullmatch(transport["codespace_implementation_handoff_id_or_none"]) is not None
        and type(transport.get("codespace_implementation_sha_or_none")) is str
        and _SHA40.fullmatch(transport["codespace_implementation_sha_or_none"]) is not None
    )


def consume_fixed_codespace_pilot(
    transport: object,
    *,
    descriptor_loader: Callable[..., object] | None = None,
    current_resolver: object = None,
    lease_reader: object = None,
    codespace_selection: object = None,
    evaluated_at: str | None = None,
    dispatcher: Callable[..., object] | None = None,
    reconstruct: Callable[..., object] | None = None,
) -> dict[str, object]:
    """Compose existing admission + #3333 dispatcher for a fixed safe preflight.

    Dependency injection is for the *trusted host*, not issue comment operands.
    In particular, no function, candidate, command, token, or path may be
    selected by the comment. Absence of any authoritative source fails closed.
    """
    envelope = transport if type(transport) is dict else {}
    if not _valid_transport(transport):
        return _receipt("blocked", "invalid-fixed-operation-envelope", envelope)
    receipt = _receipt("needs-decision", "canonical-admission-provider-unavailable", envelope)
    if any(item is None for item in (
        descriptor_loader, current_resolver, lease_reader, codespace_selection, evaluated_at
    )):
        return receipt
    # The existing #1287 production composition owns these exact providers.
    # An Actions job with only a parsed comment cannot reconstruct them.
    # Reject a partial host binding rather than treating its mere presence as
    # current execution authority.
    if not (
        callable(descriptor_loader)
        and callable(getattr(current_resolver, "reacquire", None))
        and callable(getattr(lease_reader, "inspect", None))
        and type(evaluated_at) is str
        and evaluated_at.endswith("Z")
    ):
        return _receipt("blocked", "canonical-host-binding-incomplete", envelope)

    from agent_os_execution_service.invocation_reconstruction import (
        InvocationReconstructionStatus,
        reconstruct_governed_invocation,
    )
    from agent_os_execution_service.current_invocation_resolver import (
        validate_current_invocation_bindings,
    )
    from agent_os_execution_service.executor_routing import ExecutorRoute
    from agent_os_execution_service.executor_routing import ExecutorCapability
    from scripts.agent_os_execution_interface.codespace_implementation_dispatch import (
        dispatch_admitted_operation_to_codespace,
        DispatchStatus,
    )
    from scripts.agent_os_execution_interface.governed_runner_preference import (
        GovernedRunnerCandidate,
        GovernedRunnerKind,
    )

    handoff = envelope["codespace_implementation_handoff_id_or_none"]
    sha = envelope["codespace_implementation_sha_or_none"]
    try:
        resolve = reconstruct or reconstruct_governed_invocation
        admitted = resolve(
            handoff,
            descriptor_loader=descriptor_loader,
            resolver=current_resolver,
            lease_reader=lease_reader,
            evaluated_at=evaluated_at,
        )
        if admitted.status is not InvocationReconstructionStatus.ADMITTED:
            return _receipt("blocked", "canonical-invocation-not-admitted", envelope)
        descriptor = descriptor_loader(handoff)
        current = current_resolver.reacquire(descriptor)
        if validate_current_invocation_bindings(
            descriptor, current, evaluated_at=evaluated_at
        ):
            return _receipt("blocked", "invocation-currentness-mismatch", envelope)
        pilot = current.pilot_input
        route = current.route_decision
        authorization = current.authorization
        if not all((
            descriptor.handoff_id == handoff,
            descriptor.repository == REPOSITORY,
            descriptor.issue_number == ISSUE_NUMBER,
            descriptor.source_sha == sha,
            admitted.handoff_id == handoff,
            admitted.repository == REPOSITORY,
            admitted.issue_number == ISSUE_NUMBER,
            admitted.pilot_input is not None,
            pilot.repository == REPOSITORY,
            pilot.issue_numbers == (ISSUE_NUMBER,),
            pilot.source_head_sha == sha,
            pilot.tested_sha == sha,
            current.handoff.source_sha_or_none == sha,
            authorization.execution_authorized is True,
            authorization.authorization_id == descriptor.authorization_id,
            authorization.expected_sha == sha,
            route.decision_id == descriptor.route_decision_id,
            route.requested_operation == "bounded-implementation",
            route.selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER,
            route.governed_runner_available is True,
            route.environment_health_evidence_id_or_none == descriptor.environment_health_evidence_id,
            route.environment_profile_id_or_none == descriptor.environment_profile_id,
            route.workflow_runtime_identity_or_none == descriptor.workflow_runtime_identity,
        )):
            return _receipt("blocked", "canonical-identity-or-authorization-mismatch", envelope)
        selection = codespace_selection
        if (
            getattr(selection, "selected", None) is not True
            or getattr(selection, "state", None) != "Available"
            or type(getattr(selection, "codespace_name", None)) is not str
            or descriptor.execution_surface_id != "codespace:" + selection.codespace_name
            or current.dependency_readiness.execution_surface_id != descriptor.execution_surface_id
        ):
            return _receipt("blocked", "codespace-currentness-or-health-unverified", envelope)
        if (
            type(route.required_capabilities) is not tuple
            or not route.required_capabilities
            or any(type(c) is not ExecutorCapability for c in route.required_capabilities)
        ):
            return _receipt("blocked", "runner-capabilities-unverified", envelope)
        codespaces = GovernedRunnerCandidate(
            kind=GovernedRunnerKind.CODESPACES,
            available=True,
            current=True,
            capabilities=route.governed_runner_capabilities,
            execution_surface_id=descriptor.execution_surface_id,
            environment_profile_id=descriptor.environment_profile_id,
            environment_health_evidence_id=descriptor.environment_health_evidence_id,
            workflow_runtime_identity=descriptor.workflow_runtime_identity,
        )
        gce = GovernedRunnerCandidate(
            kind=GovernedRunnerKind.GCE,
            available=False,
            current=False,
            capabilities=(),
            execution_surface_id="gce:not-selected",
            environment_profile_id="gce:not-selected",
            environment_health_evidence_id="gce:not-selected",
            workflow_runtime_identity="gce:not-selected",
        )
        if (
            type(route.operating_mode_decision_id_or_none) is not str
            or type(route.executable_lane_selection_id_or_none) is not str
            or type(route.execution_service_request_fingerprint_or_none) is not str
        ):
            return _receipt("blocked", "canonical-route-binding-unavailable", envelope)
        invoke = dispatcher or dispatch_admitted_operation_to_codespace
        outcome = invoke(
            issue_identity=descriptor.issue_or_handoff_identity,
            admission_id=authorization.authorization_id,
            requested_operation=route.requested_operation,
            required_capabilities=route.required_capabilities,
            codespaces_candidate=codespaces,
            gce_candidate=gce,
            argv=FIXED_ARGV,
            created_at=route.created_at,
            expires_at=route.expires_at,
            execution_service_request_fingerprint=route.execution_service_request_fingerprint_or_none,
            operating_mode_decision_id=route.operating_mode_decision_id_or_none,
            executable_lane_selection_id=route.executable_lane_selection_id_or_none,
            validation_command_plan_id_or_none=route.validation_command_plan_id_or_none,
            codespace_name_or_none=selection.codespace_name,
            base_sha_or_none=sha,
            timeout_seconds=90,
        )
        result = outcome.transport_result_or_none
        receipt = _receipt("blocked", "codespace-dispatch-not-completed", envelope)
        if outcome.status is not DispatchStatus.DISPATCHED or result is None:
            return receipt
        receipt["request_id"] = result.request_id
        receipt["codespace_name"] = result.codespace_name_or_none
        receipt["exit_status"] = result.exit_status_or_none
        receipt["stdout_tail"] = result.stdout_tail
        receipt["stderr_tail"] = result.stderr_tail
        if (
            result.exit_status_or_none == 0
            and result.stdout_tail.strip() == sha
            and not result.stdout_truncated
            and not result.stderr_truncated
            and result.codespace_name_or_none == selection.codespace_name
        ):
            receipt.update(status="completed", reason_codes=["fixed-head-probe-passed"])
        else:
            receipt.update(status="blocked", reason_codes=["codespace-head-or-transport-mismatch"])
        receipt["admission_id"] = authorization.authorization_id
        receipt["invocation_id"] = admitted.invocation_id
        receipt["descriptor_id"] = admitted.descriptor_id
        receipt["side_effects_performed"] = True
        return receipt
    except (AttributeError, TypeError, ValueError, RuntimeError, OSError):
        return _receipt("needs-decision", "current-evidence-unavailable", envelope)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--result-output", type=Path, required=True)
    args = parser.parse_args(argv)
    transport = json.loads(args.transport.read_text(encoding="utf-8"))
    # The hosted Actions runner does not own canonical descriptor/source/lease
    # configuration. It must fail closed until an authorized host attaches
    # those existing providers. Do not infer them from an issue comment.
    result = consume_fixed_codespace_pilot(transport)
    args.result_output.parent.mkdir(parents=True, exist_ok=True)
    args.result_output.write_text(
        json.dumps({"codespace_implementation": result}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"codespace_implementation": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
