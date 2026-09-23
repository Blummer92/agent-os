"""Focused AOS-AUTO1F freshness/invalidation tests for the #755 compiler."""

from __future__ import annotations

import pytest

from scripts.agent_os_candidate_packet.freshness import (
    build_invalidation_manifest,
    evaluate_freshness_bindings,
)
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase
from tests.agent_os_candidate_packet.test_compiler import valid_approval_ready_input


def test_freshness_bindings_pass_for_an_untouched_valid_input() -> None:
    result = evaluate_freshness_bindings(valid_approval_ready_input())

    assert result.fresh is True
    assert result.reason_code is None


def test_freshness_bindings_fail_closed_on_source_revision_drift() -> None:
    compiler_input = valid_approval_ready_input(expected_source_revision="github-issue-v1:" + "0" * 64)

    result = evaluate_freshness_bindings(compiler_input)

    assert result.fresh is False
    assert result.reason_code == "source-stage.source-revision-mismatch"
    assert result.observed_identity is not None


def test_freshness_bindings_fail_closed_on_freshness_boundary_drift() -> None:
    compiler_input = valid_approval_ready_input(freshness_boundary="main@somethingelse")

    result = evaluate_freshness_bindings(compiler_input)

    assert result.fresh is False
    assert result.reason_code == "issueplan.freshness-boundary-mismatch"


def test_freshness_bindings_fail_closed_on_scanner_result_fingerprint_drift() -> None:
    compiler_input = valid_approval_ready_input(expected_scanner_result_fingerprint="2" * 64)

    result = evaluate_freshness_bindings(compiler_input)

    assert result.fresh is False
    assert result.reason_code == "issueplan.fingerprint-mismatch"


def test_invalidation_manifest_rejects_non_phase_input() -> None:
    with pytest.raises(TypeError):
        build_invalidation_manifest("approval-ready")


def test_invalidation_manifest_is_deterministic_and_sorted() -> None:
    manifest = build_invalidation_manifest(CandidatePacketPhase.APPROVAL_READY)

    assert manifest == tuple(sorted(manifest))
    assert manifest == build_invalidation_manifest(CandidatePacketPhase.APPROVAL_READY)


def test_approval_ready_manifest_omits_execution_only_targets() -> None:
    manifest = build_invalidation_manifest(CandidatePacketPhase.APPROVAL_READY)

    joined = "|".join(manifest)
    assert "execution-packet" not in joined
    assert "validation-plan:execution-request" not in joined


def test_execution_candidate_manifest_includes_validation_targets() -> None:
    manifest = build_invalidation_manifest(CandidatePacketPhase.EXECUTION_CANDIDATE)

    joined = "|".join(manifest)
    assert "execution-packet" in joined
    assert any(entry.startswith("tested-sha:") and "validation" in entry for entry in manifest)


def test_every_trigger_produces_a_non_empty_entry_in_execution_candidate_phase() -> None:
    manifest = build_invalidation_manifest(CandidatePacketPhase.EXECUTION_CANDIDATE)

    for entry in manifest:
        trigger, _, targets = entry.partition(":")
        assert trigger
        assert targets
