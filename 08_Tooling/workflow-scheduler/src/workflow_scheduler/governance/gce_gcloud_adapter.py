"""Concrete bounded gcloud/IAP adapter for the #1217 GCE control path.

The adapter is intentionally narrow: one exact GCE tuple, start-if-stopped,
IAP/OS Login SSH, and one fixed host argv supplied by ``gce_control_path``.
It has no retry loop for invocation, no arbitrary command API, and no stop
capability in the first activation.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Mapping, Sequence

from .gce_control_path import (
    FIXED_ENTRYPOINT,
    GceResourceTuple,
    HostInvocationEvidence,
    OidcTrustPolicy,
    VmState,
    run_gce_control_path,
    validate_handoff_id,
)
from .github_issue_comment_ingress import IssueCommentIngressResult
from .governed_invocation_binding import bind_ingress_to_gce

PROJECT = "agent-os-502614"
ZONE = "us-central1-a"
INSTANCE = "agent-os-test"
RESOURCE = GceResourceTuple(project=PROJECT, zone=ZONE, instance=INSTANCE)
DISCOVERY_MODULE = "agent_os_execution_service.handoff_discovery_entrypoint"
DISCOVERY_PROBE_COMMAND = f"/usr/bin/env python3 -c 'import {DISCOVERY_MODULE}'"
WORKFLOW_REF = (
    "Blummer92/agent-os/.github/workflows/"
    "agent-os-governed-invocation.yml@refs/heads/main"
)
WIF_PROVIDER = (
    "//iam.googleapis.com/projects/966859826758/locations/global/"
    "workloadIdentityPools/agent-os-github/providers/agent-os-main"
)


class GcloudCommandError(RuntimeError):
    """Raised when a bounded gcloud command cannot produce trusted evidence."""


def _run(argv: Sequence[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        tuple(argv),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _require_ok(result: subprocess.CompletedProcess[str], operation: str) -> str:
    if result.returncode != 0:
        raise GcloudCommandError(f"{operation} failed")
    return result.stdout.strip()


def _state(value: str) -> VmState:
    normalized = value.strip().upper()
    mapping = {
        "RUNNING": VmState.RUNNING,
        "TERMINATED": VmState.STOPPED,
        "STOPPED": VmState.STOPPED,
        "STAGING": VmState.STAGING,
        "STOPPING": VmState.STOPPING,
        "SUSPENDING": VmState.SUSPENDING,
    }
    return mapping.get(normalized, VmState.UNKNOWN)


def _discovery_command(*, repository: str, issue_number: int) -> str:
    if repository != "Blummer92/agent-os":
        raise GcloudCommandError("non-canonical discovery repository rejected")
    if type(issue_number) is not int or issue_number < 1:
        raise GcloudCommandError("non-canonical discovery issue rejected")
    return (
        f"/usr/bin/env python3 -m {DISCOVERY_MODULE} "
        f"--repository {repository} --issue-number {issue_number}"
    )


class GcloudIapAdapter:
    """One-attempt gcloud adapter with no VM-stop authority."""

    def __init__(self, *, poll_seconds: float = 2.0, max_polls: int = 30) -> None:
        if poll_seconds <= 0 or max_polls < 1:
            raise ValueError("poll bounds must be positive")
        self.poll_seconds = poll_seconds
        self.max_polls = max_polls

    @staticmethod
    def _resource_args(resource: GceResourceTuple) -> tuple[str, ...]:
        if resource != RESOURCE:
            raise GcloudCommandError("resource tuple is not the approved #1217 target")
        return ("--project", resource.project, "--zone", resource.zone)

    def observe_state(self, resource: GceResourceTuple) -> VmState:
        result = _run(
            (
                "gcloud", "compute", "instances", "describe", resource.instance,
                *self._resource_args(resource), "--format=value(status)",
            )
        )
        return _state(_require_ok(result, "observe instance state"))

    def start(self, resource: GceResourceTuple) -> bool:
        result = _run(
            (
                "gcloud", "compute", "instances", "start", resource.instance,
                *self._resource_args(resource), "--quiet",
            ),
            timeout=120,
        )
        return result.returncode == 0

    def wait_until_running(self, resource: GceResourceTuple) -> VmState:
        for _ in range(self.max_polls):
            state = self.observe_state(resource)
            if state is VmState.RUNNING:
                return state
            if state not in {VmState.STAGING, VmState.STOPPED}:
                return state
            time.sleep(self.poll_seconds)
        return VmState.UNKNOWN

    def _ssh(self, resource: GceResourceTuple, command: str) -> subprocess.CompletedProcess[str]:
        return _run(
            (
                "gcloud", "compute", "ssh", resource.instance,
                *self._resource_args(resource),
                "--tunnel-through-iap", "--quiet", "--command", command,
            ),
            timeout=180,
        )

    def probe_ready(self, resource: GceResourceTuple) -> bool:
        result = self._ssh(
            resource,
            f"test -x {FIXED_ENTRYPOINT}",
        )
        return result.returncode == 0

    def probe_discovery_ready(self, resource: GceResourceTuple) -> bool:
        result = self._ssh(resource, DISCOVERY_PROBE_COMMAND)
        return result.returncode == 0

    def discover(
        self,
        resource: GceResourceTuple,
        *,
        repository: str,
        issue_number: int,
    ) -> dict[str, object]:
        command = _discovery_command(
            repository=repository,
            issue_number=issue_number,
        )
        result = self._ssh(resource, command)
        if result.returncode != 0:
            raise GcloudCommandError("fixed host discovery failed")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GcloudCommandError("host discovery evidence was not JSON") from exc
        if type(payload) is not dict:
            raise GcloudCommandError("host discovery evidence must be an object")
        if payload.get("repository") != repository:
            raise GcloudCommandError("host discovery repository mismatch")
        if payload.get("issue_number") != issue_number:
            raise GcloudCommandError("host discovery issue mismatch")
        if payload.get("execution_authorized") is not False:
            raise GcloudCommandError("discovery must remain non-authorizing")
        if payload.get("side_effects_performed") is not False:
            raise GcloudCommandError("discovery must remain read-only")
        return payload

    def invoke(
        self, resource: GceResourceTuple, argv: tuple[str, ...]
    ) -> HostInvocationEvidence:
        if len(argv) != 3 or argv[0] != FIXED_ENTRYPOINT or argv[1] != "--handoff-id":
            raise GcloudCommandError("non-canonical host argv rejected")
        if not validate_handoff_id(argv[2]):
            raise GcloudCommandError("non-canonical handoff id rejected")
        command = f"{FIXED_ENTRYPOINT} --handoff-id {argv[2]}"
        result = self._ssh(resource, command)
        if result.returncode != 0:
            raise GcloudCommandError("fixed host invocation failed")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GcloudCommandError("host evidence was not JSON") from exc
        if type(payload) is not dict:
            raise GcloudCommandError("host evidence must be an object")
        refs = payload.get("evidence_refs", ())
        if type(refs) not in (list, tuple):
            raise GcloudCommandError("host evidence refs must be an array")
        return HostInvocationEvidence(
            invoked=True,
            accepted=payload.get("accepted") is True,
            scheduler_invocation_id=payload.get("scheduler_invocation_id"),
            execution_id=payload.get("execution_id"),
            terminal_status=payload.get("terminal_status"),
            termination_confirmed=payload.get("termination_confirmed") is True,
            lease_released=payload.get("lease_released") is True,
            cleanup_complete=payload.get("cleanup_complete") is True,
            retained_lease=payload.get("retained_lease") is True,
            quarantined=payload.get("quarantined") is True,
            evidence_refs=tuple(refs),
        )

    def stop(self, resource: GceResourceTuple) -> bool:
        # First activation is deliberately start/invoke only. The transport IAM
        # role has no compute.instances.stop permission. execute_transport also
        # disables the pure control path's shutdown actuation for this profile.
        return False


def _ingress_from_file(path: Path) -> IssueCommentIngressResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        raise ValueError("transport evidence must be an object")
    return IssueCommentIngressResult(**{
        key: payload[key]
        for key in (
            "schema_version", "status", "reason", "repository", "issue_number",
            "comment_id", "actor", "handoff_id_or_none",
            "logical_trigger_id_or_none", "run_attempt",
        )
    })


def execute_transport(
    ingress: IssueCommentIngressResult,
    *,
    claims: Mapping[str, object],
    adapter: GcloudIapAdapter,
) -> dict[str, object]:
    if ingress.reason == "accepted-discovery-envelope":
        if ingress.status != "accepted" or ingress.issue_number is None:
            raise ValueError("discovery requires accepted canonical issue evidence")
        if ingress.handoff_id_or_none is not None:
            raise ValueError("discovery must not carry a handoff identity")
        if ingress.run_attempt != 1:
            raise ValueError("workflow reruns cannot perform discovery")

        policy = OidcTrustPolicy(
            repository="Blummer92/agent-os",
            repository_owner="Blummer92",
            workflow_ref=WORKFLOW_REF,
            ref="refs/heads/main",
            audience=WIF_PROVIDER,
        )
        if not policy.accepts(claims):
            return {
                "discovery": {
                    "status": "blocked",
                    "reason_codes": ["claims-rejected"],
                    "repository": ingress.repository,
                    "issue_number": ingress.issue_number,
                    "handoff_id": None,
                    "execution_authorized": False,
                    "scheduler_invoked": False,
                    "side_effects_performed": False,
                }
            }

        initial = adapter.observe_state(RESOURCE)
        if initial is VmState.STOPPED:
            if not adapter.start(RESOURCE):
                return {
                    "discovery": {
                        "status": "needs-decision",
                        "reason_codes": ["vm-start-failed"],
                        "repository": ingress.repository,
                        "issue_number": ingress.issue_number,
                        "handoff_id": None,
                        "execution_authorized": False,
                        "scheduler_invoked": False,
                        "side_effects_performed": False,
                    }
                }
            state = adapter.wait_until_running(RESOURCE)
        else:
            state = initial

        if state is not VmState.RUNNING:
            return {
                "discovery": {
                    "status": "needs-decision",
                    "reason_codes": ["host-unavailable"],
                    "repository": ingress.repository,
                    "issue_number": ingress.issue_number,
                    "handoff_id": None,
                    "execution_authorized": False,
                    "scheduler_invoked": False,
                    "side_effects_performed": False,
                }
            }

        if not adapter.probe_discovery_ready(RESOURCE):
            return {
                "discovery": {
                    "status": "needs-decision",
                    "reason_codes": ["discovery-entrypoint-unavailable"],
                    "repository": ingress.repository,
                    "issue_number": ingress.issue_number,
                    "handoff_id": None,
                    "execution_authorized": False,
                    "scheduler_invoked": False,
                    "side_effects_performed": False,
                }
            }

        return {
            "discovery": adapter.discover(
                RESOURCE,
                repository=ingress.repository,
                issue_number=ingress.issue_number,
            )
        }

    binding = bind_ingress_to_gce(ingress, resource=RESOURCE)
    policy = OidcTrustPolicy(
        repository="Blummer92/agent-os",
        repository_owner="Blummer92",
        workflow_ref=WORKFLOW_REF,
        ref="refs/heads/main",
        audience=WIF_PROVIDER,
    )
    result = run_gce_control_path(
        request_id=binding.control_request_id,
        claims=claims,
        trust_policy=policy,
        resource=binding.resource,
        expected_resource=RESOURCE,
        handoff_id=binding.handoff_id,
        adapter=adapter,
        allow_shutdown=False,
    )
    return {
        "binding": binding.to_dict(),
        "control": {
            "result_id": result.result_id,
            "status": result.status.value,
            "reason_codes": [item.value for item in result.reason_codes],
            "request_id": result.request_id,
            "handoff_id": result.handoff_id,
            "start_issued": result.start_issued,
            "host_ready": result.host_ready,
            "host_invoked": result.host_invoked,
            "host_accepted": result.host_accepted,
            "scheduler_invocation_id": result.scheduler_invocation_id,
            "execution_id": result.execution_id,
            "terminal_status": result.terminal_status,
            "shutdown_eligible": result.shutdown_eligible,
            "shutdown_issued": result.shutdown_issued,
            "retry_attempted": False,
            "github_writes_authorized": False,
            "merge_authorized": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repository-owner", required=True)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--audience", required=True)
    args = parser.parse_args(argv)
    claims = {
        "repository": args.repository,
        "repository_owner": args.repository_owner,
        "workflow_ref": args.workflow_ref,
        "ref": args.ref,
        "aud": args.audience,
    }
    evidence = execute_transport(
        _ingress_from_file(args.transport),
        claims=claims,
        adapter=GcloudIapAdapter(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
