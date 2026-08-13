"""Focused AOS-AUTO1F provenance tests for the #755 candidate-packet compiler."""

from __future__ import annotations

from scripts.agent_os_candidate_packet.models import CandidatePacketPhase
from scripts.agent_os_candidate_packet.provenance import (
    build_provenance_manifest,
    build_stage_identities,
    build_stage_payload_digests,
)
from tests.agent_os_candidate_packet.test_compiler import (
    valid_approval_ready_input,
    valid_execution_candidate_input,
)


def test_approval_ready_stage_identities_stop_before_execution_evidence() -> None:
    compiler_input = valid_approval_ready_input()

    identities = build_stage_identities(compiler_input)
    names = [name for name, _ in identities]

    assert names == ["source", "issueplan", "planning-handoff", "repository-evidence", "proposal", "approval-candidate"]


def test_execution_candidate_stage_identities_include_the_full_chain(tmp_path) -> None:
    compiler_input = valid_execution_candidate_input(tmp_path)

    identities = build_stage_identities(compiler_input)
    names = [name for name, _ in identities]

    assert names == [
        "source",
        "issueplan",
        "planning-handoff",
        "repository-evidence",
        "proposal",
        "approval-candidate",
        "approval-decision",
        "projection",
        "validation-subject",
        "validation-plan",
        "execution-request",
        "command-plan",
        "runtime-configuration",
    ]
    assert all(identity for _name, identity in identities)


def test_stage_payload_digests_are_domain_separated_and_ordered() -> None:
    compiler_input = valid_approval_ready_input()

    digests = build_stage_payload_digests(compiler_input)
    names = [name for name, _ in digests]

    assert names == ["readiness", "planning", "proposal", "approval"]
    for name, digest in digests:
        assert digest.startswith(f"candidate-packet-stage:{name}:")


def test_execution_candidate_stage_payload_digests_include_execution_packet(tmp_path) -> None:
    compiler_input = valid_execution_candidate_input(tmp_path)

    digests = dict(build_stage_payload_digests(compiler_input))

    assert "execution-packet" in digests
    assert digests["execution-packet"].startswith("candidate-packet-stage:execution-packet:")


def test_stage_payload_digests_are_deterministic_for_identical_inputs() -> None:
    first = build_stage_payload_digests(valid_approval_ready_input())
    second = build_stage_payload_digests(valid_approval_ready_input())

    assert first == second


def test_provenance_manifest_is_ordered_stage_colon_identity_strings() -> None:
    compiler_input = valid_approval_ready_input()

    manifest = build_provenance_manifest(compiler_input)
    identities = build_stage_identities(compiler_input)

    assert manifest == tuple(f"{stage}:{identity}" for stage, identity in identities)


def test_provenance_manifest_changes_when_candidate_sha_changes(tmp_path) -> None:
    first_manifest = build_provenance_manifest(valid_execution_candidate_input(tmp_path, candidate_sha="d" * 40))
    second_manifest = build_provenance_manifest(valid_execution_candidate_input(tmp_path, candidate_sha="e" * 40))

    assert first_manifest != second_manifest
