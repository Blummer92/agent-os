from dataclasses import replace

import pytest

from scripts.agent_os_pr_remediation.code_review_benchmark import (
    AnswerDefect, AnswerKey, CaseOutcome, Detectability, ReviewerPacket,
)
from scripts.agent_os_pr_remediation.models import EvidenceValidationError
from scripts.agent_os_pr_remediation.review_findings import FindingSeverity
from scripts.agent_os_pr_remediation.time_to_find_bugs_benchmark import *

SHA = "a" * 40


def phase1_case(case_id="TTFD-A02"):
    packet = ReviewerPacket(
        case_id, CASE_VERSION, SHA, "crh8a-v1",
        ("src/subject.py", "tests/subject.py"),
        ("attack-bounded",),
        ("bounded subject evidence", "bounded test evidence"),
    )
    answer = AnswerKey(
        case_id, CASE_VERSION, CaseOutcome.DEFECT, Detectability.STATIC_CODE,
        (AnswerDefect(
            "defect-bounded", ("attack-bounded",), FindingSeverity.HIGH,
            ("src/subject.py",), ("bounded-regression",),
        ),),
        ("canonical-positive-evidence",), ("historical-identity",),
    )
    return TTFDCase(packet, answer, ("canonical-owner:test",))


def timeline(times=(0, 1, 2, 3, 4, 5)):
    return tuple(TimelinePoint(event, value) for event, value in zip(TraceEvent, times))


def run(case, **overrides):
    values = dict(
        benchmark_version=BENCHMARK_VERSION,
        scorer_version=SCORER_VERSION,
        case_id=case.packet.case_id,
        case_version=case.packet.case_version,
        packet_fingerprint=case.packet.fingerprint,
        model_identity="gpt-test",
        reasoning_setting="high",
        run_number=1,
        tool_profile=("github-read",),
        baseline_sha=SHA,
        fixture_sha=SHA,
        timeline=timeline(),
        actions=(DiagnosticAction(1, ActionKind.AUTHORITATIVE_READ, "canonical:test"),),
        discovered_outcome="defect-bounded",
        classification_correct=True,
        owner_next_action_correct=True,
        repository_conformance=ConformanceResult.PASS,
    )
    values.update(overrides)
    return TTFDRun(**values)


def eligible_canary(**overrides):
    values = dict(
        host_surface="chatgpt",
        tool_profile_fingerprint="tool-profile-v1",
        continuation_contract_fingerprint="continuation-v1",
        parent_lineage_identity="issue:2230",
        observed_sequence_fingerprint="sequence-v1",
        comparability_class=ComparabilityClass.BEHAVIORALLY_ELIGIBLE,
        next_admitted_operation_executed=True,
        genuine_terminal_blocker=False,
    )
    values.update(overrides)
    return NativeCanaryEvidence(**values)


def test_phase1_matrix_is_exact_and_versioned():
    assert PHASE1_CASES == (
        "TTFD-A02", "TTFD-B01", "TTFD-B02", "TTFD-B05", "TTFD-C01",
        "TTFD-D01", "TTFD-D02", "TTFD-E02", "TTFD-F01", "TTFD-G04",
    )
    case = phase1_case()
    assert case.fingerprint == replace(case).fingerprint


def test_subject_packet_reuses_crh8a_leakage_guard():
    case = phase1_case()
    leaked = replace(case.packet, visible_context=("issue #1608 reveals answer",))
    with pytest.raises(EvidenceValidationError):
        TTFDCase(leaked, replace(case.answer_key, case_id=leaked.case_id), ("canonical-owner:test",))


def test_timeline_requires_exact_t0_t5_order_and_monotonic_time():
    case = phase1_case()
    bad_order = tuple(reversed(timeline()))
    with pytest.raises(EvidenceValidationError):
        score_run(case, run(case, timeline=bad_order))
    with pytest.raises(EvidenceValidationError):
        score_run(case, run(case, timeline=timeline((0, 1, 2, 1, 4, 5))))


def test_ttcd_is_confirmation_time_not_hypothesis_time():
    case = phase1_case()
    score = score_run(case, run(case, timeline=timeline((10, 11, 12, 15, 16, 17))))
    assert score.ttfh == 2
    assert score.ttcd == 5


def test_d01_repository_pass_without_live_canary_is_incomplete_not_pass():
    case = phase1_case("TTFD-D01")
    score = score_run(case, run(
        case,
        native_host_conformance=ConformanceResult.INCOMPLETE,
        native_canary=None,
    ))
    assert score.result == "integration-evidence-incomplete"


def test_d01_native_failure_overrides_repository_pass():
    case = phase1_case("TTFD-D01")
    canary = eligible_canary(next_admitted_operation_executed=False)
    score = score_run(case, run(
        case,
        native_host_conformance=ConformanceResult.FAIL,
        native_canary=canary,
    ))
    assert score.result == "fail"
    assert score.premature_stop is True


def test_d02_requires_parent_resumption_and_next_operation():
    case = phase1_case("TTFD-D02")
    canary = eligible_canary(next_admitted_operation_executed=False)
    actions = (
        DiagnosticAction(1, ActionKind.SUBORDINATE_MUTATION, "issue-write"),
        DiagnosticAction(2, ActionKind.PARENT_RESUMPTION, "parent-reacquired"),
    )
    score = score_run(case, run(
        case, actions=actions, native_host_conformance=ConformanceResult.FAIL,
        native_canary=canary,
    ))
    assert score.parent_mission_resumptions == 1
    assert score.premature_stop is True


def test_missing_runtime_identity_does_not_invalidate_behavioral_failure():
    canary = eligible_canary(
        native_runtime_identity_available=False,
        native_runtime_identity_if_exposed="",
        next_admitted_operation_executed=False,
    )
    assert canary.comparability_class is ComparabilityClass.BEHAVIORALLY_ELIGIBLE


def test_runtime_exact_comparability_requires_runtime_identity():
    with pytest.raises(EvidenceValidationError):
        eligible_canary(comparability_class=ComparabilityClass.RUNTIME_EXACT_COMPARABLE)


def test_surface_failure_plus_alternate_route_records_recovery():
    case = phase1_case("TTFD-C01")
    actions = (
        DiagnosticAction(1, ActionKind.SURFACE_FAILURE, "logs-insufficient"),
        DiagnosticAction(2, ActionKind.ALTERNATE_ROUTE, "check-run-metadata"),
        DiagnosticAction(3, ActionKind.AUTHORITATIVE_READ, "canonical-check"),
    )
    score = score_run(case, run(case, actions=actions))
    assert score.surface_failures_recovered == 1
    assert score.authoritative_reads == 1


def test_b01_stale_evidence_attempt_is_explicit_metric():
    case = phase1_case("TTFD-B01")
    score = score_run(case, run(case, actions=(
        DiagnosticAction(1, ActionKind.STALE_EVIDENCE, "old-head-green"),
        DiagnosticAction(2, ActionKind.AUTHORITATIVE_READ, "current-head"),
    )))
    assert score.stale_evidence_attempts == 1


def test_b02_duplicate_validation_attempt_is_explicit_metric():
    case = phase1_case("TTFD-B02")
    score = score_run(case, run(case, actions=(
        DiagnosticAction(1, ActionKind.DUPLICATE_VALIDATION, "equivalent-current-head-run"),
    )))
    assert score.duplicate_validation_attempts == 1


def test_b05_transport_success_cannot_override_semantic_validation_failure():
    case = phase1_case("TTFD-B05")
    score = score_run(case, run(case, repository_conformance=ConformanceResult.FAIL))
    assert score.result == "fail"


def test_e02_semantic_no_progress_is_bounded_metric():
    case = phase1_case("TTFD-E02")
    score = score_run(case, run(case, actions=(
        DiagnosticAction(1, ActionKind.NO_PROGRESS, "equivalent-transition-1"),
        DiagnosticAction(2, ActionKind.NO_PROGRESS, "equivalent-transition-2"),
    )))
    assert score.no_progress_transitions == 2


def test_f01_stale_diagnostics_after_head_movement_are_visible():
    case = phase1_case("TTFD-F01")
    score = score_run(case, run(case, actions=(
        DiagnosticAction(1, ActionKind.STALE_EVIDENCE, "diagnostic-bound-to-old-head"),
        DiagnosticAction(2, ActionKind.AUTHORITATIVE_READ, "reacquired-current-head"),
    )))
    assert (score.stale_evidence_attempts, score.authoritative_reads) == (1, 1)


def test_g04_mergeable_false_can_still_pass_after_deterministic_reconciliation():
    case = phase1_case("TTFD-G04")
    score = score_run(case, run(case, discovered_outcome="reconciliation-succeeds"))
    assert score.result == "pass"


def test_clean_false_positive_is_automatic_failure():
    case = phase1_case()
    score = score_run(case, run(case, false_positive=True))
    assert score.result == "fail"
    assert score.false_positive is True


def test_contaminated_run_is_ineligible_and_non_authorizing():
    case = phase1_case()
    score = score_run(case, run(
        case, contaminated=True, contamination_reasons=("answer-leakage",),
    ))
    assert score.eligible is False
    assert score.result == "ineligible"
    assert not any((
        score.execution_authorized, score.merge_authorized, score.closure_authorized,
        score.external_write_authorized, score.side_effects_performed,
    ))


def test_run_identity_is_deterministic_and_preserves_fresh_run_number():
    case = phase1_case()
    first = run(case, run_number=1)
    same = replace(first)
    second = replace(first, run_number=2)
    assert first.run_identity == same.run_identity
    assert first.run_identity != second.run_identity


def test_telemetry_cannot_synthesize_continuation():
    case = phase1_case("TTFD-D01")
    canary = eligible_canary(next_admitted_operation_executed=False)
    score = score_run(case, run(
        case,
        actions=(DiagnosticAction(1, ActionKind.DISCOVERY, "schema-discovered"),),
        native_host_conformance=ConformanceResult.FAIL,
        native_canary=canary,
    ))
    assert score.premature_stop is True
    assert score.parent_mission_resumptions == 0
