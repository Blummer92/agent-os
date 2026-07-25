"""Focused, architecture-boundary, and tamper-detection tests for WSC5R."""

from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from workflow_scheduler.execution import quarantine_review as qr
from workflow_scheduler.execution.single_issue_pilot import SingleIssuePilotResult

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = (
    REPO_ROOT
    / "08_Tooling"
    / "workflow-scheduler"
    / "src"
    / "workflow_scheduler"
    / "execution"
    / "quarantine_review.py"
)


def _result(**overrides: object) -> SingleIssuePilotResult:
    base: dict[str, object] = dict(
        schema_name="agent-os-wsc5-single-issue-pilot",
        schema_version="1.0",
        result_id="",
        phase="finalization",
        primary_status="quarantined",
        status="quarantined",
        repository="Blummer92/agent-os",
        base_branch="main",
        branch="agent/588-wsc5r",
        issue_numbers=(588,),
        invocation_id="invocation-588-0001",
        base_sha="a" * 40,
        source_head_sha="b" * 40,
        tested_sha="c" * 40,
        projection_id="projection-1",
        proposal_id="proposal-1",
        approval_id="approval-1",
        approval_revision="1",
        issueplan_evidence_id="issueplan-1",
        plan_id="plan-1",
        bundle_id="bundle-1",
        advisory_result_id="advisory-1",
        advisory_render_id="render-1",
        lease_identity="lease-1",
        lease_holder_identity="holder-1",
        lease_generation=1,
        lease_acquire_attempts=1,
        lease_acquired=True,
        lease_release_attempts=1,
        lease_released=True,
        workspace_identity="workspace-1",
        workspace_create_attempts=1,
        workspace_created=True,
        workspace_inspected=True,
        workspace_safe=False,
        workspace_cleanup_attempts=1,
        workspace_filesystem_cleaned=True,
        workspace_metadata_cleaned=True,
        executor_dispatch_attempts=1,
        executor_called=True,
        executor_started=True,
        cancellation_requested=False,
        termination_confirmed=True,
        possible_partial_effects=False,
        validation_attempts=1,
        validation_attempted=True,
        validation_passed=False,
        changed_paths=(),
        required_tests=(),
        completed_tests=(),
        reason_codes=("validation.failed",),
        details=("bounded detail",),
        primary_error=None,
        cleanup_errors=(),
        release_errors=(),
    )
    base.update(overrides)
    return SingleIssuePilotResult(**base)  # type: ignore[arg-type]


def _packet(**overrides: object) -> qr.QuarantineEvidencePacket:
    return qr.build_quarantine_evidence_packet(_result(**overrides))


# --------------------------------------------------------------------------
# Frozen operator-state classification
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reason_codes", "termination_confirmed", "possible_partial_effects", "expected"),
    [
        (("validation.failed",), True, False, "contained-evidence-incomplete"),
        (("evidence.bundle-mismatch",), True, False, "stop-all-scheduler-execution"),
        (("changed-paths.forbidden",), True, False, "stop-all-scheduler-execution"),
        (("executor.termination-unconfirmed",), False, False, "termination-unresolved"),
        (("executor.possible-partial-effects",), True, True, "partial-effects-confirmed"),
        (("lease.holder-drift",), True, False, "lease-ownership-unresolved"),
        (("workspace.dirty",), True, False, "repository-state-unresolved"),
        (("workspace.filesystem-cleanup-failed",), True, False, "manual-cleanup-required"),
    ],
)
def test_every_quarantine_reason_family_maps_to_an_allowed_state(
    reason_codes, termination_confirmed, possible_partial_effects, expected
) -> None:
    overrides: dict[str, object] = dict(
        reason_codes=reason_codes,
        termination_confirmed=termination_confirmed,
        possible_partial_effects=possible_partial_effects,
    )
    if expected == "lease-ownership-unresolved":
        overrides["lease_acquired"] = True
        overrides["lease_released"] = False
    if expected == "repository-state-unresolved":
        overrides["workspace_inspected"] = False
    if expected == "manual-cleanup-required":
        overrides["workspace_filesystem_cleaned"] = False
    state = qr.classify_quarantine_state(_result(**overrides))
    assert state == expected
    assert state in qr.QUARANTINE_REVIEW_STATES


def test_contained_no_effects_proven_when_executor_never_called() -> None:
    state = qr.classify_quarantine_state(
        _result(
            reason_codes=(),
            executor_called=False,
            executor_started=False,
            lease_acquired=False,
            workspace_created=False,
            validation_attempted=False,
            validation_passed=False,
        )
    )
    assert state == "contained-no-effects-proven"


def test_classify_rejects_non_quarantined_result() -> None:
    with pytest.raises(qr.QuarantineReviewError):
        qr.classify_quarantine_state(_result(status="failed", primary_status="failed"))


# --------------------------------------------------------------------------
# Original pilot result remains immutable
# --------------------------------------------------------------------------


def test_original_pilot_result_remains_immutable() -> None:
    result = _result()
    with pytest.raises(FrozenInstanceError):
        result.status = "completed"  # type: ignore[misc]
    packet = qr.build_quarantine_evidence_packet(result)
    assert packet.result_id == result.result_id
    assert result.status == "quarantined"


# --------------------------------------------------------------------------
# Packet identity / tamper detection
# --------------------------------------------------------------------------


def test_packet_identity_is_deterministic_and_content_bound() -> None:
    packet_a = _packet()
    packet_b = _packet()
    assert packet_a.packet_id == packet_b.packet_id

    different = _packet(details=("a different bounded detail",))
    assert different.packet_id != packet_a.packet_id


def test_packet_serialization_detects_tampering() -> None:
    packet = _packet()
    tampered = replace(packet, packet_id="quarantine-evidence:" + "0" * 64)
    with pytest.raises(qr.QuarantineReviewError):
        qr.serialize_quarantine_evidence_packet(tampered)


def test_packet_rejects_non_quarantined_status_directly() -> None:
    with pytest.raises(qr.QuarantineReviewError):
        qr.QuarantineEvidencePacket(
            schema_name=qr.QUARANTINE_REVIEW_SCHEMA_NAME,
            schema_version=qr.QUARANTINE_REVIEW_SCHEMA_VERSION,
            packet_id="quarantine-evidence:" + "0" * 64,
            result_id="r",
            repository="Blummer92/agent-os",
            issue_numbers=(588,),
            invocation_id="invocation-1",
            base_sha="a" * 40,
            source_head_sha="b" * 40,
            tested_sha="c" * 40,
            primary_status="failed",
            status="failed",
            initial_review_state="contained-evidence-incomplete",
            paused=False,
            executor_called=False,
            executor_started=False,
            cancellation_requested=False,
            termination_confirmed=True,
            possible_partial_effects=False,
            lease_identity=None,
            lease_holder_identity=None,
            lease_generation=None,
            lease_acquired=False,
            lease_released=False,
            workspace_identity=None,
            workspace_created=False,
            workspace_inspected=False,
            workspace_filesystem_cleaned=False,
            workspace_metadata_cleaned=False,
            changed_paths=(),
            reason_codes=(),
            details=(),
            primary_error=None,
            cleanup_errors=(),
            release_errors=(),
        )


# --------------------------------------------------------------------------
# Append-only review events
# --------------------------------------------------------------------------


def test_append_only_review_events_have_deterministic_identity() -> None:
    packet = _packet()
    event = qr.append_review_event(
        packet=packet,
        prior_events=(),
        reviewer_identity="operator-1",
        review_timestamp="2026-07-25T00:00:00Z",
        disposition="preserve-and-investigate",
        rationale="initial triage",
        machine_verified=False,
    )
    assert event.prior_event_id == packet.packet_id
    assert event.sequence == 1
    assert event.event_id == qr.review_event_id(event)

    other_packet_same_content = qr.build_quarantine_evidence_packet(_result())
    replay = qr.append_review_event(
        packet=other_packet_same_content,
        prior_events=(),
        reviewer_identity="operator-1",
        review_timestamp="2026-07-25T00:00:00Z",
        disposition="preserve-and-investigate",
        rationale="initial triage",
        machine_verified=False,
    )
    assert replay.event_id == event.event_id


def test_review_event_mismatched_packet_identity_fails_closed() -> None:
    packet = _packet()
    foreign_event = qr.append_review_event(
        packet=_packet(details=("other candidate detail",)),
        prior_events=(),
        reviewer_identity="operator-1",
        review_timestamp="2026-07-25T00:00:00Z",
        disposition="preserve-and-investigate",
        rationale="unrelated packet",
        machine_verified=False,
    )
    with pytest.raises(qr.QuarantineReviewError):
        qr.append_review_event(
            packet=packet,
            prior_events=(foreign_event,),
            reviewer_identity="operator-1",
            review_timestamp="2026-07-25T00:01:00Z",
            disposition="preserve-and-investigate",
            rationale="second look",
            machine_verified=False,
        )


def test_review_event_out_of_order_or_duplicate_sequence_fails_closed() -> None:
    packet = _packet()
    first = qr.append_review_event(
        packet=packet,
        prior_events=(),
        reviewer_identity="operator-1",
        review_timestamp="2026-07-25T00:00:00Z",
        disposition="preserve-and-investigate",
        rationale="first",
        machine_verified=False,
    )
    duplicate = replace(first, event_id=first.event_id)
    with pytest.raises(qr.QuarantineReviewError):
        qr.append_review_event(
            packet=packet,
            prior_events=(first, duplicate),
            reviewer_identity="operator-1",
            review_timestamp="2026-07-25T00:02:00Z",
            disposition="preserve-and-investigate",
            rationale="third",
            machine_verified=False,
        )


def test_review_event_chain_references_prior_event_identity() -> None:
    packet = _packet()
    first = qr.append_review_event(
        packet=packet,
        prior_events=(),
        reviewer_identity="operator-1",
        review_timestamp="2026-07-25T00:00:00Z",
        disposition="require-workspace-inspection",
        rationale="need inspection",
        machine_verified=False,
    )
    second = qr.append_review_event(
        packet=packet,
        prior_events=(first,),
        reviewer_identity="operator-1",
        review_timestamp="2026-07-25T00:05:00Z",
        disposition="preserve-and-investigate",
        rationale="still investigating",
        machine_verified=False,
    )
    assert second.prior_event_id == first.event_id
    assert second.sequence == 2


def test_review_event_serialization_detects_tampering() -> None:
    packet = _packet()
    event = qr.append_review_event(
        packet=packet,
        prior_events=(),
        reviewer_identity="operator-1",
        review_timestamp="2026-07-25T00:00:00Z",
        disposition="preserve-and-investigate",
        rationale="triage",
        machine_verified=False,
    )
    tampered = replace(event, rationale="a different rationale entirely")
    with pytest.raises(qr.QuarantineReviewError):
        qr.serialize_review_event(tampered)


# --------------------------------------------------------------------------
# Termination / partial effects / lease / cleanup remain unresolved
# --------------------------------------------------------------------------


def test_termination_unresolved_requires_pause() -> None:
    packet = _packet(termination_confirmed=False, reason_codes=("executor.termination-unconfirmed",))
    assert packet.initial_review_state == "termination-unresolved"
    assert packet.paused is True
    assert qr.requires_pause(packet.initial_review_state) is True


def test_cleanup_path_absent_without_metadata_proof_remains_unresolved() -> None:
    packet = _packet(
        workspace_filesystem_cleaned=False,
        workspace_metadata_cleaned=True,
        reason_codes=(),
    )
    assert packet.initial_review_state == "manual-cleanup-required"
    assert packet.paused is True


def test_lease_holder_generation_ambiguity_remains_unresolved() -> None:
    packet = _packet(
        reason_codes=("lease.holder-drift",),
        lease_acquired=True,
        lease_released=False,
    )
    assert packet.initial_review_state == "lease-ownership-unresolved"
    assert packet.paused is True


# --------------------------------------------------------------------------
# Downgrade protection / stop-all dominance / fresh-invocation identity
# --------------------------------------------------------------------------


def test_partial_effects_cannot_become_no_effects_proven_without_evidence() -> None:
    packet = _packet(possible_partial_effects=True, reason_codes=("executor.possible-partial-effects",))
    assert packet.initial_review_state == "partial-effects-confirmed"
    with pytest.raises(qr.QuarantineReviewError):
        qr.append_review_event(
            packet=packet,
            prior_events=(),
            reviewer_identity="operator-1",
            review_timestamp="2026-07-25T00:00:00Z",
            disposition="confirm-no-effects-with-evidence",
            rationale="looks fine",
            machine_verified=True,
        )


def test_termination_unresolved_cannot_be_downgraded_without_verification() -> None:
    packet = _packet(termination_confirmed=False, reason_codes=("executor.termination-unconfirmed",))
    with pytest.raises(qr.QuarantineReviewError):
        qr.append_review_event(
            packet=packet,
            prior_events=(),
            reviewer_identity="operator-1",
            review_timestamp="2026-07-25T00:00:00Z",
            disposition="confirm-no-effects-with-evidence",
            rationale="assumed fine",
            machine_verified=False,
        )


def test_stop_all_dominates_narrower_dispositions() -> None:
    packet = _packet(reason_codes=("changed-paths.forbidden",))
    assert packet.initial_review_state == "stop-all-scheduler-execution"
    event = qr.append_review_event(
        packet=packet,
        prior_events=(),
        reviewer_identity="operator-1",
        review_timestamp="2026-07-25T00:00:00Z",
        disposition="require-repository-inspection",
        rationale="checking scope",
        machine_verified=True,
    )
    assert event.resulting_state == "stop-all-scheduler-execution"


def test_fresh_invocation_recommendation_cannot_reuse_invocation_identity() -> None:
    packet = _packet()
    with pytest.raises(qr.QuarantineReviewError):
        qr.append_review_event(
            packet=packet,
            prior_events=(),
            reviewer_identity="operator-1",
            review_timestamp="2026-07-25T00:00:00Z",
            disposition="recommend-fresh-invocation",
            rationale="rerun same",
            machine_verified=True,
            new_invocation_id=packet.invocation_id,
        )


def test_fresh_invocation_recommendation_resolves_with_new_identity_and_handoff() -> None:
    packet = _packet(reason_codes=(), possible_partial_effects=False, termination_confirmed=True)
    event = qr.append_review_event(
        packet=packet,
        prior_events=(),
        reviewer_identity="operator-1",
        review_timestamp="2026-07-25T00:00:00Z",
        disposition="recommend-fresh-invocation",
        rationale="recovery gates satisfied",
        machine_verified=True,
        new_invocation_id="invocation-588-0002",
    )
    assert event.resulting_state == "recovery-completed"
    handoff = qr.build_manual_recovery_handoff_packet(
        packet=packet,
        resolving_event=event,
        new_invocation_id="invocation-588-0002",
        recommended_by="operator-1",
        rationale="recovery gates satisfied",
    )
    assert handoff.new_invocation_id != handoff.original_invocation_id
    assert handoff.original_result_id == packet.result_id


def test_stop_all_state_still_permits_fresh_invocation_recovery_path() -> None:
    packet = _packet(reason_codes=("changed-paths.forbidden",))
    event = qr.append_review_event(
        packet=packet,
        prior_events=(),
        reviewer_identity="operator-1",
        review_timestamp="2026-07-25T00:00:00Z",
        disposition="recommend-fresh-invocation",
        rationale="fully remediated and verified",
        machine_verified=True,
        new_invocation_id="invocation-588-0003",
    )
    assert event.resulting_state == "recovery-completed"


# --------------------------------------------------------------------------
# Review capacity / backlog thresholds
# --------------------------------------------------------------------------


def test_review_capacity_breach_never_silently_drops_evidence() -> None:
    observation = qr.evaluate_review_capacity(
        open_review_count=qr.MAX_OPEN_REVIEWS + 1,
        unresolved_stop_all_count=0,
        oldest_open_sequence_age=1,
    )
    assert observation.breach is True


def test_review_capacity_breach_forces_stop_all_via_append() -> None:
    packet = _packet()
    events: tuple[qr.ReviewEvent, ...] = ()
    for index in range(qr.MAX_OPEN_REVIEWS):
        events = events + (
            qr.append_review_event(
                packet=packet,
                prior_events=events,
                reviewer_identity="operator-1",
                review_timestamp=f"2026-07-25T00:{index:02d}:00Z",
                disposition="preserve-and-investigate",
                rationale=f"observation {index}",
                machine_verified=False,
            ),
        )
    breach_event = qr.append_review_event(
        packet=packet,
        prior_events=events,
        reviewer_identity="operator-1",
        review_timestamp="2026-07-25T01:00:00Z",
        disposition="preserve-and-investigate",
        rationale="over capacity observation",
        machine_verified=False,
    )
    assert breach_event.disposition == "pause-all-scheduler-execution"
    assert breach_event.resulting_state == "stop-all-scheduler-execution"


# --------------------------------------------------------------------------
# Redaction / bounding
# --------------------------------------------------------------------------


def test_secret_like_strings_are_redacted_with_hash_and_marker() -> None:
    redacted = qr.redact_text("token=ghp_abcdefghijklmnopqrstuvwx", name="detail")
    assert "ghp_abcdefghijklmnopqrstuvwx" not in redacted
    assert "redacted" in redacted
    assert "sha256:" in redacted


def test_secret_like_strings_are_rejected_when_required() -> None:
    with pytest.raises(qr.QuarantineReviewError):
        qr.reject_if_secret_like("api_key: sk-abcdefghijklmnopqrstuvwx", name="rationale")


def test_oversized_output_is_bounded_with_truncation_evidence() -> None:
    oversized = "x" * (qr.MAX_FIELD_LENGTH + 500)
    redacted = qr.redact_text(oversized, name="output")
    assert "truncated:" in redacted
    assert len(redacted) < len(oversized) + 200


def test_reviewer_identity_and_rationale_are_bounded() -> None:
    packet = _packet()
    with pytest.raises(qr.QuarantineReviewError):
        qr.append_review_event(
            packet=packet,
            prior_events=(),
            reviewer_identity="",
            review_timestamp="2026-07-25T00:00:00Z",
            disposition="preserve-and-investigate",
            rationale="triage",
            machine_verified=False,
        )


# --------------------------------------------------------------------------
# Architecture boundary: no execution/persistence/network/GitHub/retry authority
# --------------------------------------------------------------------------


_FORBIDDEN_IMPORT_ROOTS = (
    "subprocess",
    "socket",
    "urllib",
    "http",
    "requests",
    "sqlite3",
    "threading",
    "multiprocessing",
    "asyncio",
    "queue",
    "shutil",
    "os",
)

_FORBIDDEN_MODULE_SUBSTRINGS = (
    "executor",
    "request_dispatch",
    "retry_manager",
    "single_issue_runtime",
    "single_issue_adapters",
    "github",
    "scheduler_core",
)


def test_module_imports_no_execution_persistence_or_network_authority() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    for module_name in imported_modules:
        root = module_name.split(".")[0]
        assert root not in _FORBIDDEN_IMPORT_ROOTS, f"forbidden import root: {module_name}"
        lowered = module_name.lower()
        for forbidden in _FORBIDDEN_MODULE_SUBSTRINGS:
            assert forbidden not in lowered, f"forbidden import: {module_name}"


def test_module_defines_no_network_subprocess_or_persistence_calls() -> None:
    source = inspect.getsource(qr)
    for forbidden_token in ("subprocess.", "socket.", "open(", "os.remove", "os.system", "requests."):
        assert forbidden_token not in source


def test_no_disposition_produces_an_executable_side_effect() -> None:
    packet = _packet()
    for disposition in qr.ALLOWED_REVIEW_DISPOSITIONS:
        event = qr.append_review_event(
            packet=packet,
            prior_events=(),
            reviewer_identity="operator-1",
            review_timestamp="2026-07-25T00:00:00Z",
            disposition=disposition,  # type: ignore[arg-type]
            rationale=f"exercising {disposition}",
            machine_verified=True,
            new_invocation_id="invocation-588-9999" if disposition == "recommend-fresh-invocation" else None,
        )
        assert isinstance(event, qr.ReviewEvent)
        assert event.resulting_state in qr.QUARANTINE_REVIEW_STATES
