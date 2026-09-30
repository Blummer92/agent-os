from __future__ import annotations

from .main_health import MainHealthResult, serialize_main_health
from .merge_admission import MergeAdmissionResult, evaluate_merge_admission
from .models import ValidationPlan

#: Explicit routing disposition for a candidate whose recorded base is behind
#: exact-current main (#2637). The governed next action is the existing #1187
#: branch-refresh path, not candidate implementation repair. This reason is
#: deliberately *not* namespaced ``main-health.*``: the main-health gate owns
#: only the health question, while branch drift belongs to the refresh owner,
#: so a ``branch-refresh-required`` block must never be misread as a
#: main-health failure.
BRANCH_REFRESH_REQUIRED_REASON = "branch-refresh-required"


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

    Stale-base routing (#2637): when the candidate's recorded base -- which the
    validation plan agrees with -- is not exact-current main, the block is
    reported as ``branch-refresh-required`` so the governed #1187
    branch-refresh path is invoked instead of misattributing the failure to
    main-health evidence staleness. A plan bound to a different base than the
    candidate's recorded base keeps the ``main-health.evidence-stale``
    disposition: that is a plan/health rebind, not branch drift.
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
        if plan.base_sha == current_base_sha:
            # Branch drift, not a candidate-health failure: the candidate's
            # recorded base (which the plan agrees with) is behind
            # exact-current main, so the governed next action is the #1187
            # branch-refresh path. Surface the explicit refresh-required
            # disposition before ordinary final aggregate admission.
            return _blocked(
                plan, evidence, current_base_sha, current_head_sha, BRANCH_REFRESH_REQUIRED_REASON
            )
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
