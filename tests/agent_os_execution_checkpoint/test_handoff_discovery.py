from __future__ import annotations

import hashlib
import json

from scripts.agent_os_execution_checkpoint.handoff_discovery import (
    InvocationHandoffDiscoveryReason,
    InvocationHandoffDiscoveryStatus,
    discover_issue_handoff,
)
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    INVOCATION_DESCRIPTOR_SCHEMA_NAME,
    INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
    GovernedInvocationDescriptor,
    append_invocation_descriptor,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _id(prefix: str, label: str) -> str:
    return f"{prefix}:{_digest(label)}"


def _descriptor(label: str = "one", **overrides: object) -> GovernedInvocationDescriptor:
    values: dict[str, object] = {
        "schema_name": INVOCATION_DESCRIPTOR_SCHEMA_NAME,
        "schema_version": INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
        "repository": "Blummer92/agent-os",
        "issue_number": 1233,
        "issue_or_handoff_identity": "issue:1233",
        "handoff_id": _id("executor-handoff", f"handoff-{label}"),
        "route_decision_id": _id("executor-route-decision", f"route-{label}"),
        "execution_service_request_fingerprint": _id("execution-request", f"request-{label}"),
        "authorization_id": _id("authorization", f"authorization-{label}"),
        "source_ref": "refs/heads/agent/1233-cross-provider-aggregate-dedup",
        "source_sha": "a" * 40,
        "checkpoint_id": _id("agent-os.execution-checkpoint", f"checkpoint-{label}"),
        "resume_plan_id": _id("agent-os.execution-checkpoint.resume-plan", f"resume-{label}"),
        "environment_profile_id": _id("environment-profile", f"profile-{label}"),
        "environment_health_evidence_id": _id("environment-health", f"health-{label}"),
        "required_environment_id": _id("required-environment", f"required-{label}"),
        "dependency_readiness_evidence_id": _id("dependency-readiness", f"readiness-{label}"),
        "execution_surface_id": "execution-surface:gce-agent-os-test",
        "workspace_identity": _id("pilot-workspace", f"workspace-{label}"),
        "workflow_runtime_identity": _id("workflow-runtime", f"runtime-{label}"),
        "candidate_packet_id": _id("candidate-packet", f"packet-{label}"),
        "runtime_configuration_fingerprint": _id("concrete-adapters", f"configuration-{label}"),
        "execution_id": f"execution-1233-{label}",
        "invocation_id": f"invocation-1233-{label}",
    }
    values.update(overrides)
    return GovernedInvocationDescriptor(**values)


def test_empty_store_returns_not_found_without_authority(tmp_path) -> None:
    result = discover_issue_handoff(
        tmp_path, repository="Blummer92/agent-os", issue_number=1233
    )

    assert result.status is InvocationHandoffDiscoveryStatus.NOT_FOUND
    assert result.reason_codes == (
        InvocationHandoffDiscoveryReason.NO_MATCHING_DESCRIPTOR,
    )
    assert result.handoff_id is None
    assert result.matching_descriptor_count == 0
    assert result.repository_implementation_authorized is False
    assert result.execution_authorized is False
    assert result.github_writes_authorized is False
    assert result.merge_authorized is False
    assert result.issue_closure_authorized is False
    assert result.external_writes_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False


def test_exactly_one_matching_descriptor_returns_existing_handoff(tmp_path) -> None:
    matching = _descriptor()
    append_invocation_descriptor(tmp_path, matching)
    append_invocation_descriptor(
        tmp_path,
        _descriptor("other", issue_number=999, issue_or_handoff_identity="issue:999"),
    )

    result = discover_issue_handoff(
        tmp_path, repository="blummer92/AGENT-OS", issue_number=1233
    )

    assert result.status is InvocationHandoffDiscoveryStatus.FOUND
    assert result.reason_codes == (InvocationHandoffDiscoveryReason.FOUND,)
    assert result.handoff_id == matching.handoff_id
    assert result.matching_descriptor_count == 1


def test_multiple_matching_descriptors_fail_closed_without_selecting_one(tmp_path) -> None:
    append_invocation_descriptor(tmp_path, _descriptor("one"))
    append_invocation_descriptor(tmp_path, _descriptor("two"))

    result = discover_issue_handoff(
        tmp_path, repository="Blummer92/agent-os", issue_number=1233
    )

    assert result.status is InvocationHandoffDiscoveryStatus.NEEDS_DECISION
    assert result.reason_codes == (
        InvocationHandoffDiscoveryReason.MULTIPLE_MATCHING_DESCRIPTORS,
    )
    assert result.matching_descriptor_count == 2
    assert result.handoff_id is None


def test_tampered_descriptor_makes_discovery_needs_decision(tmp_path) -> None:
    descriptor = _descriptor()
    outcome = append_invocation_descriptor(tmp_path, descriptor)
    payload = json.loads(outcome.path.read_text(encoding="utf-8"))
    payload["source_sha"] = "b" * 40
    outcome.path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    result = discover_issue_handoff(
        tmp_path, repository="Blummer92/agent-os", issue_number=1233
    )

    assert result.status is InvocationHandoffDiscoveryStatus.NEEDS_DECISION
    assert result.reason_codes == (
        InvocationHandoffDiscoveryReason.DESCRIPTOR_INTEGRITY_UNVERIFIED,
    )
    assert result.handoff_id is None


def test_filename_rebinding_is_rejected_during_discovery(tmp_path) -> None:
    descriptor = _descriptor()
    outcome = append_invocation_descriptor(tmp_path, descriptor)
    rebound = outcome.path.with_name("0" * 64 + ".json")
    outcome.path.rename(rebound)

    result = discover_issue_handoff(
        tmp_path, repository="Blummer92/agent-os", issue_number=1233
    )

    assert result.status is InvocationHandoffDiscoveryStatus.NEEDS_DECISION
    assert result.reason_codes == (
        InvocationHandoffDiscoveryReason.DESCRIPTOR_INTEGRITY_UNVERIFIED,
    )
    assert result.handoff_id is None


def test_discovery_result_is_deterministic_for_same_store(tmp_path) -> None:
    descriptor = _descriptor()
    append_invocation_descriptor(tmp_path, descriptor)

    first = discover_issue_handoff(
        tmp_path, repository="Blummer92/agent-os", issue_number=1233
    )
    second = discover_issue_handoff(
        tmp_path, repository="Blummer92/agent-os", issue_number=1233
    )

    assert first == second
    assert first.result_id == second.result_id
