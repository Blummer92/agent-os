from __future__ import annotations

from .impact_completeness import ImpactCompletenessResult, serialize_impact_completeness
from .merge_admission import MergeAdmissionResult, evaluate_merge_admission
from .models import ValidationPlan


def evaluate_pre_aggregate_admission(
    plan: object,
    evidence: object | None,
    *,
    impact: object,
    current_base_sha: object,
    current_head_sha: object,
) -> MergeAdmissionResult:
    """Compose finite impact completeness before broad validation admission.

    Complete or not-applicable impact evidence delegates unchanged to the existing
    #2235 admission evaluator. Mechanically proven incomplete coupling blocks before
    aggregate execution is requested. Ambiguous impact relationships route to
    manual review. Invalid impact evidence fails closed. This layer performs no I/O
    and grants no merge or execution authority.
    """
    if not isinstance(plan, ValidationPlan):
        return evaluate_merge_admission(
            plan,
            evidence,
            current_base_sha=current_base_sha,
            current_head_sha=current_head_sha,
        )

    impact_result = _validated_impact(impact)
    if impact_result is None:
        return _override(
            plan,
            evidence,
            current_base_sha,
            current_head_sha,
            status="block",
            obligation="manual-review",
            reasons=("impact.evidence-invalid",),
        )

    if impact_result.status in {"complete", "not-applicable"}:
        if impact_result.aggregate_escalation_required:
            return _override(
                plan,
                evidence,
                current_base_sha,
                current_head_sha,
                status="block",
                obligation="manual-review",
                reasons=("impact.evidence-invalid",),
            )
        return evaluate_merge_admission(
            plan,
            evidence,
            current_base_sha=current_base_sha,
            current_head_sha=current_head_sha,
        )

    if not impact_result.aggregate_escalation_required:
        return _override(
            plan,
            evidence,
            current_base_sha,
            current_head_sha,
            status="block",
            obligation="manual-review",
            reasons=("impact.evidence-invalid",),
        )

    if impact_result.status == "manual-review":
        return _override(
            plan,
            evidence,
            current_base_sha,
            current_head_sha,
            status="manual-review",
            obligation="manual-review",
            reasons=impact_result.reason_codes or ("impact.manual-review",),
        )

    if impact_result.status == "incomplete":
        return _override(
            plan,
            evidence,
            current_base_sha,
            current_head_sha,
            status="block",
            obligation="aggregate",
            reasons=impact_result.reason_codes or ("impact.incomplete",),
        )

    return _override(
        plan,
        evidence,
        current_base_sha,
        current_head_sha,
        status="block",
        obligation="manual-review",
        reasons=("impact.evidence-invalid",),
    )


def _validated_impact(value: object) -> ImpactCompletenessResult | None:
    if not isinstance(value, ImpactCompletenessResult):
        return None
    try:
        serialize_impact_completeness(value)
    except (TypeError, ValueError):
        return None
    return value


def _override(
    plan: ValidationPlan,
    evidence: object | None,
    current_base_sha: object,
    current_head_sha: object,
    *,
    status: str,
    obligation: str,
    reasons: tuple[str, ...],
) -> MergeAdmissionResult:
    """Reuse #2235 result identity and exact-revision checks."""
    baseline = evaluate_merge_admission(
        plan,
        evidence,
        current_base_sha=current_base_sha,
        current_head_sha=current_head_sha,
    )
    if baseline.reason_codes and baseline.reason_codes[0].startswith("revision."):
        return baseline

    from .merge_admission import _result

    return _result(plan, None, status, obligation, reasons)
