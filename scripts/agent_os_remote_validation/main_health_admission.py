from __future__ import annotations

from .main_health import MainHealthResult, serialize_main_health
from .merge_admission import MergeAdmissionResult, evaluate_merge_admission
from .models import ValidationPlan


def evaluate_final_validation_admission(
    plan: object,
    evidence: object | None,
    *,
    main_health: object,
    current_base_sha: object,
    current_head_sha: object,
) -> MergeAdmissionResult:
    """Compose exact-current main health before ordinary final candidate admission.

    This is a thin production composition seam over the existing #2235 candidate
    admission evaluator and #2236 main-health projection. It creates no new
    selector, health store, validation executor, or authority model.

    Exact healthy main delegates unchanged to ``evaluate_merge_admission``.
    Unhealthy or unproven main fails closed before an aggregate obligation can be
    requested. A separately requested recovery-only health projection may still
    evaluate the candidate so recovery validation remains representable; this
    function never grants merge, revert, closure, or execution authority.
    """
    health = _validated_main_health(main_health)
    if not isinstance(plan, ValidationPlan):
        return evaluate_merge_admission(
            plan,
            evidence,
            current_base_sha=current_base_sha,
            current_head_sha=current_head_sha,
        )

    if health is None:
        return _blocked(plan, evidence, current_base_sha, current_head_sha, "main-health.evidence-invalid")
    if health.repository != plan.repository:
        return _blocked(plan, evidence, current_base_sha, current_head_sha, "main-health.repository-mismatch")
    if health.main_sha != current_base_sha or health.main_sha != plan.base_sha:
        return _blocked(plan, evidence, current_base_sha, current_head_sha, "main-health.evidence-stale")

    if health.ordinary_admission_allowed:
        return evaluate_merge_admission(
            plan,
            evidence,
            current_base_sha=current_base_sha,
            current_head_sha=current_head_sha,
        )

    if health.disposition == "recovery-only" and health.recovery_admission_allowed:
        return evaluate_merge_admission(
            plan,
            evidence,
            current_base_sha=current_base_sha,
            current_head_sha=current_head_sha,
        )

    reason = (
        "main-health.exact-main-red"
        if health.health == "unhealthy"
        else health.reason_codes[0] if health.reason_codes else "main-health.unproven"
    )
    return _blocked(plan, evidence, current_base_sha, current_head_sha, reason)


def _validated_main_health(value: object) -> MainHealthResult | None:
    if not isinstance(value, MainHealthResult):
        return None
    try:
        serialize_main_health(value)
    except (TypeError, ValueError):
        return None
    return value


def _blocked(
    plan: ValidationPlan,
    evidence: object | None,
    current_base_sha: object,
    current_head_sha: object,
    reason: str,
) -> MergeAdmissionResult:
    """Reuse #2235's result model while replacing only the main-health disposition."""
    baseline = evaluate_merge_admission(
        plan,
        evidence,
        current_base_sha=current_base_sha,
        current_head_sha=current_head_sha,
    )
    # Import the existing private constructor deliberately: the result schema,
    # identity, bounds, and non-authorizing flags remain owned by #2235.
    from .merge_admission import _result

    return _result(
        plan,
        None,
        "block",
        baseline.validation_obligation,
        (reason,),
    )
