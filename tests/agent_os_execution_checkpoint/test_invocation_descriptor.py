from __future__ import annotations

import hashlib
import json
from dataclasses import fields, replace

import pytest

from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    INVOCATION_DESCRIPTOR_SCHEMA_NAME,
    INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
    GovernedInvocationDescriptor,
    InvocationDescriptorIntegrityError,
    InvocationDescriptorNotFound,
    append_invocation_descriptor,
    deserialize_invocation_descriptor,
    invocation_descriptor_id,
    load_invocation_descriptor,
    serialize_invocation_descriptor,
)
from scripts.agent_os_execution_checkpoint.store import CheckpointStoreIntegrityConflict


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _id(prefix: str, label: str) -> str:
    return f"{prefix}:{_digest(label)}"


def _descriptor(**overrides: object) -> GovernedInvocationDescriptor:
    values: dict[str, object] = {
        "schema_name": INVOCATION_DESCRIPTOR_SCHEMA_NAME,
        "schema_version": INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
        "repository": "Blummer92/agent-os",
        "issue_number": 1218,
        "issue_or_handoff_identity": "issue:1218",
        "handoff_id": _id("executor-handoff", "handoff"),
        "route_decision_id": _id("executor-route-decision", "route"),
        "execution_service_request_fingerprint": _id("execution-request", "request"),
        "authorization_id": _id("authorization", "authorization"),
        "source_ref": "refs/heads/agent/1218-governed-invocation-descriptor",
        "source_sha": "a" * 40,
        "checkpoint_id": _id("agent-os.execution-checkpoint", "checkpoint"),
        "resume_plan_id": _id("agent-os.execution-checkpoint.resume-plan", "resume"),
        "environment_profile_id": _id("environment-profile", "profile"),
        "environment_health_evidence_id": _id("environment-health", "health"),
        "required_environment_id": _id("required-environment", "required-environment"),
        "dependency_readiness_evidence_id": _id("dependency-readiness", "readiness"),
        "execution_surface_id": "execution-surface:gce-agent-os-test",
        "workspace_identity": _id("pilot-workspace", "workspace"),
        "workflow_runtime_identity": _id("workflow-runtime", "runtime"),
        "candidate_packet_id": _id("candidate-packet", "packet"),
        "runtime_configuration_fingerprint": _id("concrete-adapters", "configuration"),
        "execution_id": "execution-1218-a",
        "invocation_id": "invocation-1218-a",
    }
    values.update(overrides)
    return GovernedInvocationDescriptor(**values)


def test_descriptor_is_deterministic_bounded_and_non_authorizing() -> None:
    first = _descriptor()
    second = _descriptor()
    assert first == second
    assert first.descriptor_id == invocation_descriptor_id(first)
    assert first.descriptor_id.startswith("agent-os.governed-invocation-descriptor:")
    assert len(serialize_invocation_descriptor(first)) < 16 * 1024
    assert first.repository_implementation_authorized is False
    assert first.execution_authorized is False
    assert first.github_writes_authorized is False
    assert first.merge_authorized is False
    assert first.issue_closure_authorized is False
    assert first.external_writes_authorized is False


def test_descriptor_binds_subject_workspace_and_execution_surface() -> None:
    descriptor = _descriptor()
    assert descriptor.issue_or_handoff_identity == "issue:1218"
    assert descriptor.execution_surface_id == "execution-surface:gce-agent-os-test"
    assert descriptor.workspace_identity.startswith("pilot-workspace:")
    assert replace(
        descriptor,
        workspace_identity=_id("pilot-workspace", "different"),
        descriptor_id="",
    ).descriptor_id != descriptor.descriptor_id


def test_descriptor_schema_contains_only_identity_references_not_execution_text() -> None:
    names = {item.name for item in fields(GovernedInvocationDescriptor)}
    forbidden_names = {
        "command",
        "argv",
        "shell",
        "prompt",
        "url",
        "package_command",
        "working_directory",
        "runtime_input",
        "single_issue_pilot_input",
    }
    assert not names & forbidden_names


def test_serialization_round_trip_is_byte_exact() -> None:
    descriptor = _descriptor()
    encoded = serialize_invocation_descriptor(descriptor)
    reconstructed = deserialize_invocation_descriptor(encoded)
    assert reconstructed == descriptor
    assert serialize_invocation_descriptor(reconstructed) == encoded


def test_deserialize_rejects_unknown_field_authority_and_tampering() -> None:
    descriptor = _descriptor()
    payload = json.loads(serialize_invocation_descriptor(descriptor))

    extra = dict(payload)
    extra["command"] = "rm -rf /"
    with pytest.raises(ValueError, match="unknown or missing"):
        deserialize_invocation_descriptor(
            json.dumps(extra, sort_keys=True, separators=(",", ":"))
        )

    authority = dict(payload)
    authority["execution_authorized"] = True
    with pytest.raises(ValueError, match="must remain false"):
        deserialize_invocation_descriptor(
            json.dumps(authority, sort_keys=True, separators=(",", ":"))
        )

    tampered = dict(payload)
    tampered["source_sha"] = "b" * 40
    with pytest.raises(ValueError, match="descriptor_id"):
        deserialize_invocation_descriptor(
            json.dumps(tampered, sort_keys=True, separators=(",", ":"))
        )


def test_append_and_direct_handoff_lookup_are_idempotent(tmp_path) -> None:
    descriptor = _descriptor()
    first = append_invocation_descriptor(tmp_path, descriptor)
    second = append_invocation_descriptor(tmp_path, descriptor)

    assert first.path == second.path
    assert first.already_present is False
    assert second.already_present is True
    assert first.path.parent == tmp_path / "invocations"
    assert first.path.name == f"{descriptor.handoff_id.rsplit(':', 1)[-1]}.json"
    assert load_invocation_descriptor(tmp_path, descriptor.handoff_id) == descriptor


def test_same_handoff_cannot_be_rebound_to_different_descriptor(tmp_path) -> None:
    original = _descriptor()
    append_invocation_descriptor(tmp_path, original)
    conflicting = _descriptor(candidate_packet_id=_id("candidate-packet", "different"))
    assert conflicting.handoff_id == original.handoff_id
    assert conflicting.descriptor_id != original.descriptor_id

    with pytest.raises(CheckpointStoreIntegrityConflict):
        append_invocation_descriptor(tmp_path, conflicting)


def test_missing_and_tampered_persisted_descriptor_fail_closed(tmp_path) -> None:
    descriptor = _descriptor()
    with pytest.raises(InvocationDescriptorNotFound):
        load_invocation_descriptor(tmp_path, descriptor.handoff_id)

    outcome = append_invocation_descriptor(tmp_path, descriptor)
    payload = json.loads(outcome.path.read_text(encoding="utf-8"))
    payload["source_sha"] = "b" * 40
    outcome.path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(InvocationDescriptorIntegrityError):
        load_invocation_descriptor(tmp_path, descriptor.handoff_id)


def test_malformed_handoff_and_descriptor_identity_are_rejected() -> None:
    with pytest.raises(ValueError, match="handoff_id"):
        _descriptor(handoff_id="not-a-handoff")

    valid = _descriptor()
    with pytest.raises(ValueError, match="descriptor_id"):
        replace(
            valid,
            descriptor_id=_id("agent-os.governed-invocation-descriptor", "wrong"),
        )
