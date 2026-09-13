"""Bounded regression-test synthesis decision/evidence seam for #2315.

This module does not generate arbitrary test suites or grant repair/lifecycle
authority. It decides whether one already-bounded coding task needs a regression
test and validates the evidence returned by the existing semantic coding-worker
operation ``generate-regression-test``.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .coding_worker_contract import CodingWorkerOperation, CodingWorkerRequest, CodingWorkerResult


class RegressionTestDecision(str, Enum):
    TEST_NOT_NEEDED = "TEST_NOT_NEEDED"
    EXISTING_TEST_SUFFICIENT = "EXISTING_TEST_SUFFICIENT"
    REGRESSION_TEST_REQUIRED = "REGRESSION_TEST_REQUIRED"
    TEST_SYNTHESIS_UNSAFE_OR_AMBIGUOUS = "TEST_SYNTHESIS_UNSAFE_OR_AMBIGUOUS"


class RedBeforeGreenStatus(str, Enum):
    NOT_APPLICABLE = "not-applicable"
    EXPECTED_FAILURE_PROVEN = "expected-failure-proven"
    UNAVAILABLE = "unavailable"
    UNEXPECTED_PASS = "unexpected-pass"
    WRONG_REASON_FAILURE = "wrong-reason-failure"


@dataclass(frozen=True, slots=True, kw_only=True)
class RegressionTestSynthesisEvidence:
    decision: RegressionTestDecision
    reason: str
    behavioral_requirement_id: str | None = None
    existing_test_ids: tuple[str, ...] = ()
    generated_test_paths: tuple[str, ...] = ()
    red_before_green: RedBeforeGreenStatus = RedBeforeGreenStatus.NOT_APPLICABLE

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("reason is required")
        if len(set(self.existing_test_ids)) != len(self.existing_test_ids):
            raise ValueError("existing_test_ids must not contain duplicates")
        if len(set(self.generated_test_paths)) != len(self.generated_test_paths):
            raise ValueError("generated_test_paths must not contain duplicates")
        if self.decision is RegressionTestDecision.EXISTING_TEST_SUFFICIENT and not self.existing_test_ids:
            raise ValueError("EXISTING_TEST_SUFFICIENT requires existing test evidence")
        if self.decision is RegressionTestDecision.REGRESSION_TEST_REQUIRED:
            if not self.behavioral_requirement_id:
                raise ValueError("REGRESSION_TEST_REQUIRED requires a behavioral requirement")
        elif self.generated_test_paths:
            raise ValueError("generated tests are valid only for REGRESSION_TEST_REQUIRED")


def decide_regression_test_need(
    *,
    behavior_changed: bool,
    behavioral_requirement_id: str | None,
    existing_exact_test_ids: tuple[str, ...] = (),
    existing_indirect_test_ids: tuple[str, ...] = (),
    expectation_is_ambiguous: bool = False,
    canonical_test_surface_is_ambiguous: bool = False,
    requires_forbidden_external_io: bool = False,
    test_path_within_scope: bool = True,
) -> RegressionTestSynthesisEvidence:
    """Return one explainable, fail-closed synthesis decision from bounded evidence."""
    unsafe = (
        expectation_is_ambiguous
        or canonical_test_surface_is_ambiguous
        or requires_forbidden_external_io
        or not test_path_within_scope
    )
    if unsafe:
        return RegressionTestSynthesisEvidence(
            decision=RegressionTestDecision.TEST_SYNTHESIS_UNSAFE_OR_AMBIGUOUS,
            reason="bounded evidence cannot prove a safe in-scope deterministic regression test",
            behavioral_requirement_id=behavioral_requirement_id,
        )
    if existing_exact_test_ids or existing_indirect_test_ids:
        evidence = existing_exact_test_ids + existing_indirect_test_ids
        return RegressionTestSynthesisEvidence(
            decision=RegressionTestDecision.EXISTING_TEST_SUFFICIENT,
            reason="existing coverage already proves the bounded behavioral obligation",
            behavioral_requirement_id=behavioral_requirement_id,
            existing_test_ids=evidence,
        )
    if not behavior_changed:
        return RegressionTestSynthesisEvidence(
            decision=RegressionTestDecision.TEST_NOT_NEEDED,
            reason="the bounded change is non-behavioral and existing validation remains canonical",
            behavioral_requirement_id=behavioral_requirement_id,
        )
    if not behavioral_requirement_id:
        return RegressionTestSynthesisEvidence(
            decision=RegressionTestDecision.TEST_SYNTHESIS_UNSAFE_OR_AMBIGUOUS,
            reason="no single behavioral requirement is available to anchor a regression test",
        )
    return RegressionTestSynthesisEvidence(
        decision=RegressionTestDecision.REGRESSION_TEST_REQUIRED,
        reason="a bounded behavioral obligation lacks existing regression coverage",
        behavioral_requirement_id=behavioral_requirement_id,
    )


def validate_generated_regression_result(
    *,
    request: CodingWorkerRequest,
    result: CodingWorkerResult,
    evidence: RegressionTestSynthesisEvidence,
) -> RegressionTestSynthesisEvidence:
    """Validate worker evidence without turning generated tests into authority."""
    if evidence.decision is not RegressionTestDecision.REGRESSION_TEST_REQUIRED:
        raise ValueError("generated regression evidence requires REGRESSION_TEST_REQUIRED")
    if request.operation is not CodingWorkerOperation.GENERATE_REGRESSION_TEST:
        raise ValueError("request must use generate-regression-test operation")
    if result.request_id != request.request_id or result.base_sha != request.base_sha:
        raise ValueError("worker result is stale or belongs to another request")
    if not result.files_changed:
        raise ValueError("worker result contains no generated test path")
    for path in result.files_changed:
        if not any(path == root or path.startswith(root + "/") for root in request.allowed_paths):
            raise ValueError("generated test path exceeds allowed scope")
        if any(path == root or path.startswith(root + "/") for root in request.forbidden_paths):
            raise ValueError("generated test path enters forbidden scope")
    return RegressionTestSynthesisEvidence(
        decision=evidence.decision,
        reason=evidence.reason,
        behavioral_requirement_id=evidence.behavioral_requirement_id,
        existing_test_ids=evidence.existing_test_ids,
        generated_test_paths=result.files_changed,
        red_before_green=evidence.red_before_green,
    )


__all__ = [
    "RedBeforeGreenStatus",
    "RegressionTestDecision",
    "RegressionTestSynthesisEvidence",
    "decide_regression_test_need",
    "validate_generated_regression_result",
]
