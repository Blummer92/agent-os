from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from scripts.agent_os_issue_acceptance.zero_job_validation_recovery import (
    ZeroJobAdmissionEvidence,
    ZeroJobRecoveryProjection,
    project_zero_job_admission,
)
from workflow_scheduler.execution.recovery_progress import (
    RecoveryProgressDisposition,
    RecoverySemanticEvidence,
    classify_recovery_progress,
)

_ALLOWED_MERGEABILITY = {"mergeable", "conflicting", "unknown"}
_ALLOWED_BRANCH_FRESHNESS = {"current", "behind", "conflicted", "unknown"}
_ALLOWED_REVIEW_STATE = {"clear", "requested-changes", "blocking-thread", "unknown"}
_ALLOWED_CHECK_STATE = {"green", "red", "pending", "missing", "unknown"}
_ALLOWED_REQUIRED_CHECK_STATE = {"current", "drifted", "unavailable", "unknown"}


@dataclass(frozen=True, slots=True)
class FailedRepairAdmissionRecord:
    attempt_id: str
    selected_lesson_ids: tuple[str, ...]
    retry_reentry_outcome: str
    check_state: str
    required_check_configuration_state: str
    review_state: str
    branch_freshness: str
    mergeability: str
    mutation_admissible: bool
    reason_codes: tuple[str, ...]
    next_action: str
    recovery_stalled: bool = False
    bounded_continuation_admitted: bool = False
    zero_job_recovery: ZeroJobRecoveryProjection | None = None
    github_writes_authorized: bool = field(default=False, init=False)
    workflow_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)
    protected_setting_authorized: bool = field(default=False, init=False)
    production_authorized: bool = field(default=False, init=False)
    external_system_write_authorized: bool = field(default=False, init=False)


def evaluate_failed_repair_admission(
    *,
    activation_result: Mapping[str, object],
    check_state: str,
    required_check_configuration_state: str,
    review_state: str,
    branch_freshness: str,
    mergeability: str,
    current: RecoverySemanticEvidence | None = None,
    prior: RecoverySemanticEvidence | None = None,
    prior_transition_fingerprint: str | None = None,
    zero_job: ZeroJobAdmissionEvidence | None = None,
) -> FailedRepairAdmissionRecord:
    """Gate the next repair mutation on retry-specific CKR6 and separated diagnostics.

    The CKR6 activation result must come from the existing failed-repair activation
    seam. This projection does not retrieve lessons, refresh branches, edit CI,
    resolve reviews, or infer conflicts. It only prevents the next mutation until
    the retry-specific lesson result and each independent diagnostic dimension are
    explicit enough to continue safely.

    When ``current`` recovery evidence is supplied (#2281), the projection also
    composes ``classify_recovery_progress``: repeated repairs require semantic
    progress. An EQUIVALENT observation (no semantic movement vs ``prior``)
    makes the mutation inadmissible; a RECOVERY_STALLED observation (the same
    equivalent transition observed again) additionally records ``recovery_stalled``
    so the caller can mark the host continuation stalled. INITIAL and PROGRESSED
    observations add no gating. The classification is a pure projection over
    caller-supplied semantic identities: no Notion read, CI execution, mutation,
    or retry happens inside it, and capability failures stay outside recurrence.
    All three recovery params are optional keyword-only so #3280's later
    additive params land cleanly.

    When ``zero_job`` run evidence is supplied (#3277), the projection also
    composes the surface-neutral zero-job classifier. Non-executed validation
    evidence (stale ``action_required``, pre-job failure, unproven currentness)
    is never a red code-test failure: repository repair is inadmissible and the
    CKR6 code-repair re-entry is not selected. Stale non-executed evidence
    projects the bounded exact-head re-dispatch (at most two attempts, fail
    closed when the PR head moved); an executed failure adds no gating. Actual
    dispatch capability remains owned by #2410.
    """
    attempt_id = _text(activation_result.get("attempt_id"), "attempt_id")
    retry_reentry_outcome = _text(
        activation_result.get("retry_reentry_outcome"), "retry_reentry_outcome"
    )
    selected_lesson_ids = _string_tuple(
        activation_result.get("selected_lesson_ids", ()), "selected_lesson_ids"
    )
    activation_mutation_admissible = activation_result.get("mutation_admissible")
    if type(activation_mutation_admissible) is not bool:
        raise TypeError("activation_result.mutation_admissible must be built-in bool")

    _enum(check_state, _ALLOWED_CHECK_STATE, "check_state")
    _enum(
        required_check_configuration_state,
        _ALLOWED_REQUIRED_CHECK_STATE,
        "required_check_configuration_state",
    )
    _enum(review_state, _ALLOWED_REVIEW_STATE, "review_state")
    _enum(branch_freshness, _ALLOWED_BRANCH_FRESHNESS, "branch_freshness")
    _enum(mergeability, _ALLOWED_MERGEABILITY, "mergeability")

    reasons: list[str] = []
    recovery_stalled = False
    zero_job_projection = None
    if zero_job is not None:
        zero_job_projection = project_zero_job_admission(zero_job)
        if zero_job_projection.gates_code_repair:
            reasons.extend(zero_job_projection.reason_codes)
    if current is not None:
        progress = classify_recovery_progress(
            current,
            prior=prior,
            prior_transition_fingerprint=prior_transition_fingerprint,
        )
        if progress.disposition is RecoveryProgressDisposition.EQUIVALENT:
            reasons.append("recovery-equivalent-no-semantic-progress")
        elif progress.disposition is RecoveryProgressDisposition.RECOVERY_STALLED:
            reasons.append("recovery-stalled-repeated-equivalent-transition")
            recovery_stalled = True
        # INITIAL and PROGRESSED add no recovery gating: the first observation
        # and genuine semantic movement continue through existing diagnostics.
    if retry_reentry_outcome != "consumed" or not activation_mutation_admissible:
        reasons.append("retry-specific-lessons-not-consumed")
    if required_check_configuration_state in {"unavailable", "unknown"}:
        reasons.append("required-check-configuration-unresolved")
    elif required_check_configuration_state == "drifted":
        reasons.append("required-check-configuration-drift")
    if check_state in {"pending", "missing", "unknown"}:
        reasons.append("check-state-unresolved")
    if review_state in {"requested-changes", "blocking-thread", "unknown"}:
        reasons.append("review-state-blocking-or-unresolved")
    if branch_freshness in {"behind", "conflicted", "unknown"}:
        reasons.append("branch-freshness-blocking-or-unresolved")
    if mergeability == "unknown":
        reasons.append("mergeability-unresolved")

    # `mergeability=conflicting` is only one diagnostic signal. It never grants
    # permission to edit workflows or bypass the existing branch-refresh/conflict
    # owner; callers must route it separately from check/review state.
    if mergeability == "conflicting":
        reasons.append("mergeability-conflict-signal")

    bounded_continuation_admitted = False
    if reasons:
        if zero_job_projection is not None and zero_job_projection.gates_code_repair:
            next_action = zero_job_projection.next_action or "reacquire-independent-diagnostics"
            bounded_continuation_admitted = zero_job_projection.bounded_continuation
        elif "retry-specific-lessons-not-consumed" in reasons:
            next_action = "reenter-ckr6-for-exact-failed-attempt"
        elif "required-check-configuration-drift" in reasons:
            next_action = "reconcile-required-check-configuration-before-code-repair"
        elif "branch-freshness-blocking-or-unresolved" in reasons or "mergeability-conflict-signal" in reasons:
            next_action = "route-branch-state-through-existing-refresh-conflict-owner"
        elif "review-state-blocking-or-unresolved" in reasons:
            next_action = "resolve-or-reacquire-review-state"
        elif "recovery-stalled-repeated-equivalent-transition" in reasons:
            next_action = "route-stalled-recovery-to-canonical-owner-for-human-decision"
        elif "recovery-equivalent-no-semantic-progress" in reasons:
            next_action = "record-equivalent-recovery-transition-before-retry"
        else:
            next_action = "reacquire-independent-diagnostics"
        mutation_admissible = False
    else:
        next_action = "continue-authorized-repair-mutation"
        mutation_admissible = True
        reasons.append("retry-lessons-and-diagnostics-converged")

    return FailedRepairAdmissionRecord(
        attempt_id=attempt_id,
        selected_lesson_ids=selected_lesson_ids,
        retry_reentry_outcome=retry_reentry_outcome,
        check_state=check_state,
        required_check_configuration_state=required_check_configuration_state,
        review_state=review_state,
        branch_freshness=branch_freshness,
        mergeability=mergeability,
        mutation_admissible=mutation_admissible,
        reason_codes=tuple(reasons),
        next_action=next_action,
        recovery_stalled=recovery_stalled,
        bounded_continuation_admitted=bounded_continuation_admitted,
        zero_job_recovery=(
            zero_job_projection.recovery if zero_job_projection is not None else None
        ),
    )


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be non-empty exact text")
    return value


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{name} must be a sequence of strings")
    result = tuple(value)
    if any(type(item) is not str or not item for item in result):
        raise ValueError(f"{name} must contain non-empty strings")
    return result


def _enum(value: str, allowed: set[str], name: str) -> None:
    if type(value) is not str or value not in allowed:
        raise ValueError(f"{name} must be one of {sorted(allowed)}")
