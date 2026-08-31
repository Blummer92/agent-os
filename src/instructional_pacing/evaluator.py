"""Pure-local deterministic LP4 lesson pacing evaluator."""

from __future__ import annotations

from statistics import median
from typing import Any

from instructional_workflow_contracts import (
    FINGERPRINT_ALGORITHM,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    freeze_json,
    sha256_hex,
)

from .comparability import filter_comparable_runs
from .diagnosis import diagnose_dimensions
from .packet import NON_AUTHORITY_FIELDS, validate_pacing_packet


def _declared_range(functions: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "lower": sum(float(item["lower_minutes"]) for item in functions),
        "expected": sum(float(item["expected_minutes"]) for item in functions),
        "upper": sum(float(item["upper_minutes"]) for item in functions),
    }


def _calibrated_range(declared: dict[str, float], runs: list[dict[str, Any]]) -> dict[str, float]:
    if not runs:
        return declared
    active = sorted(float(run["active_minutes"]) for run in runs)
    observed_expected = float(median(active))
    lower = min(declared["lower"], active[0])
    upper = max(declared["upper"], active[-1])
    return {"lower": lower, "expected": observed_expected, "upper": upper}


def _classification(timing: dict[str, float], available: float, continuation_allowed: bool) -> tuple[str, str]:
    if timing["upper"] <= available:
        return "fits", "proceed-to-owner-review"
    if timing["expected"] <= available:
        return "fits-with-compression", "review-recommended"
    if continuation_allowed:
        return "split-required", "review-recommended"
    return "not-feasible", "hold"


def evaluate_lesson_pacing(value: object) -> ValidationResult:
    """Evaluate one LP4 packet without I/O, external state, or authority mutation."""
    try:
        packet = validate_pacing_packet(value)
        diagnosis = diagnose_dimensions(packet["demand_profile"])
        comparison = filter_comparable_runs(
            packet["prior_runs"],
            objective_ref=packet["objective_ref"],
            work_mode=packet.get("work_mode"),
        )
        available = float(packet["period_minutes"]) - float(packet["operational_minutes"])
        declared = _declared_range(packet["instructional_functions"])
        timing = _calibrated_range(declared, comparison["included"])
        classification, routing = _classification(timing, available, packet["continuation_allowed"])

        reasons: list[str] = []
        if comparison["included_count"] < 2:
            reasons.append("lp-evidence-comparable-runs-insufficient")
        if packet["privacy_disposition"] != "eligible":
            reasons.append("lp-evidence-privacy-ineligible")
            classification, routing = "insufficient-evidence", "hold"
        observation = packet["observation_quality"]
        if observation.get("status") not in {"usable", "usable-with-limits"}:
            reasons.append("lp-evidence-observation-quality-unusable")
            classification, routing = "insufficient-evidence", "hold"
        if packet["implementation_stage"] == "suspended":
            reasons.append("lp-calibration-revision-suspended")
            classification, routing = "insufficient-evidence", "hold"
        if classification == "not-feasible":
            reasons.append("lp-pacing-instruction-time-insufficient")
        elif classification == "split-required":
            reasons.append("lp-pacing-split-required")

        confidence = comparison["comparability_confidence"]
        if diagnosis["evidence_uncertainty"]["level"] == "high":
            confidence = "low"
            reasons.append("lp-pacing-uncertainty-too-high")
            classification, routing = "insufficient-evidence", "hold"
        if packet["implementation_stage"] in {"design-only", "shadow-mode"}:
            confidence = "low"

        preserved = sorted(item["name"] for item in packet["instructional_functions"] if item["protected"])
        payload = {
            "contract_version": packet["contract_version"],
            "record_id": packet["record_id"],
            "record_revision": packet["record_revision"],
            "objective_ref": packet["objective_ref"],
            "success_criteria_ref": packet["success_criteria_ref"],
            "available_lesson_minutes": available,
            "unadapted_range": declared,
            "adapted_range": timing,
            "advisory_assessment_outcome": classification,
            "routing_recommendation": routing,
            "confidence": confidence,
            "difficulty_diagnosis": diagnosis,
            "primary_time_drivers": sorted(
                dimension for dimension, item in diagnosis.items() if item["level"] == "high"
            ),
            "preserved_functions": preserved,
            "compressed_instances": [],
            "changed_formats": [],
            "deferred_functions": [],
            "split_plan": None,
            "teacher_decision": packet.get("teacher_decision"),
            "what_supported": packet.get("what_supported", []),
            "what_remains_unmeasured": packet.get("what_remains_unmeasured", []),
            "manual_review_required": bool(reasons) or routing != "proceed-to-owner-review",
            "unresolved_uncertainties": sorted(set(reasons)),
            "next_owner_recommendation": "Unit Alignment Agent",
            "evidence_summary": {
                "included_count": comparison["included_count"],
                "excluded_count": comparison["excluded_count"],
                "excluded": comparison["excluded"],
                "context_count": comparison["context_count"],
            },
            "implementation_stage": packet["implementation_stage"],
            "interval_coverage": "declared-and-observed-bounds" if comparison["included_count"] else "declared-bounds-only",
            "directional_risk": "underestimation-possible" if timing["upper"] > available else "bounded-within-supplied-evidence",
            **NON_AUTHORITY_FIELDS,
        }
        record = ValidatedRecord(
            contract_version=packet["contract_version"],
            record_id=packet["record_id"],
            record_revision=packet["record_revision"],
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(payload),
            payload=freeze_json(payload),
        )
        return ValidationResult(
            status=ValidationStatus.VALID,
            record=record,
            reason_codes=(),
            blockers=(),
            details=(),
        )
    except Exception as exc:
        # Shared validators already sanitize and bound normal contract failures; keep
        # LP4 fail-closed and non-authorizing for all malformed supplied evidence.
        from instructional_workflow_contracts import ContractValidationError

        reason = exc.reason_code if isinstance(exc, ContractValidationError) else "handoff-invalid"
        detail = exc.detail if isinstance(exc, ContractValidationError) else "LP4 evaluation failed closed"
        return ValidationResult(
            status=ValidationStatus.INVALID,
            record=None,
            reason_codes=(reason,),
            blockers=(),
            details=(detail,),
        )
