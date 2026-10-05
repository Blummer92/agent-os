from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from scripts.agent_os_issue_acceptance.validation_failure_classifier import (
    ValidationFailureClassification,
    ValidationFailureEvidence,
    classify_validation_failure,
)
from scripts.agent_os_issue_acceptance.zero_job_validation_recovery import (
    ZeroJobAdmissionEvidence,
    ZeroJobRecoveryProjection,
    project_zero_job_admission,
)
from .validation_supersession import (
    ValidationHeadDisposition,
    ValidationSupersessionEvidence,
    project_validation_head_disposition,
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


_DIAGNOSTIC_BLOCKER_KIND = "BLOCKED_DIAGNOSTIC_SURFACE"

_STALE_HEAD_DISPOSITIONS = frozenset(
    {
        ValidationHeadDisposition.STALE_HEAD,
        ValidationHeadDisposition.SUPERSEDED_BY_NEW_HEAD,
    }
)

# PR_REGRESSION is deliberately absent: it keeps ordinary authorized repair and
# carries the classifier's own focused -> exact-head aggregate ladder.
_FAILURE_GATE_ACTIONS = {
    ValidationFailureClassification.INHERITED_MAIN_FAILURE: "report-inherited-main-failure-blocker",
    ValidationFailureClassification.CI_INFRASTRUCTURE_CONFIGURATION_FAILURE: "stop-at-ci-infrastructure-authorization-boundary",
    ValidationFailureClassification.INSUFFICIENT_EVIDENCE_NEEDS_DECISION: "reacquire-missing-validation-failure-evidence",
}


@dataclass(frozen=True, slots=True)
class DiagnosticSurfaceEvidence:
    """Caller-supplied diagnostic-surface facts for the live failed-repair path (#3280).

    ``authorized_surfaces`` are the already-authorized canonical diagnostic
    surfaces for the exact failing operation; ``attempted_surfaces`` are the ones
    already tried. Both are compared as distinct surface identities, so a surface
    reported twice is one surface. This carries no retry count: the bound is that
    the finite authorized set is exhausted.
    """

    diagnostics_actionable: bool
    authorized_surfaces: tuple[str, ...] = ()
    attempted_surfaces: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.diagnostics_actionable) is not bool:
            raise TypeError("diagnostics_actionable must be built-in bool")
        for name in ("authorized_surfaces", "attempted_surfaces"):
            value = getattr(self, name)
            if type(value) is not tuple or any(
                type(item) is not str or not item.strip() for item in value
            ):
                raise TypeError(f"{name} must be an exact tuple of non-empty strings")


@dataclass(frozen=True, slots=True)
class DiagnosticSurfaceBlocker:
    """The one explicit terminal blocker once authorized alternatives are exhausted."""

    kind: str
    missing_evidence: str
    attempted_surfaces: tuple[str, ...]
    clearing_condition: str


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
    next_diagnostic_surface: str | None = None
    diagnostic_blocker: DiagnosticSurfaceBlocker | None = None
    validation_head_disposition: str | None = None
    validation_failure_classification: str | None = None
    validation_repair_ladder: str | None = None
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
    diagnostics: DiagnosticSurfaceEvidence | None = None,
    validation_head: ValidationSupersessionEvidence | None = None,
    validation_failure: ValidationFailureEvidence | None = None,
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

    When ``diagnostics`` evidence is supplied (#3280), the projection executes the
    overlay's bounded alternate-diagnosis rule: insufficient diagnostics with an
    unused already-authorized surface continue through that one bounded
    alternative (``next_diagnostic_surface``); once every distinct authorized
    surface has been attempted, exactly one explicit ``BLOCKED_DIAGNOSTIC_SURFACE``
    blocker is returned with the evidence that could not be obtained and its
    clearing condition. The bound is exhaustion of a finite set of distinct
    surfaces, not a retry count, and stays separate from #2281's semantic
    recovery progress.

    When ``validation_head`` evidence is supplied (#3280), the projection composes
    the canonical exact-head owner ``project_validation_head_disposition``: stale
    or superseded evidence, or a failure bound to a previous PR head, can never
    satisfy the current candidate, so repair is inadmissible and current-head
    validation evidence must be reacquired first. Any disposition other than a
    failure on the current head also fails closed to the owner's own action.

    When ``validation_failure`` evidence is supplied (#3280), the projection
    composes ``classify_validation_failure``. A PR regression keeps the
    deterministic ladder (authorized repair -> focused validation -> exact-head
    aggregate validation -> continue) as ``validation_repair_ladder``; inherited
    main failures, CI infrastructure/configuration failures and insufficient
    evidence make repair inadmissible and route to their own explicit action.
    If both are supplied the failure evidence must bind the current head.
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
    head_decision = None
    head_gate_action: str | None = None
    if validation_head is not None:
        head_decision = project_validation_head_disposition(validation_head)
        stale_failure = (
            head_decision.disposition is ValidationHeadDisposition.FAILED
            and head_decision.prior_head_sha != head_decision.current_head_sha
        )
        if head_decision.disposition in _STALE_HEAD_DISPOSITIONS or stale_failure:
            reasons.append("validation-head-stale-evidence-cannot-satisfy-current-head")
            head_gate_action = "reacquire-current-head-validation-evidence"
        elif head_decision.disposition is not ValidationHeadDisposition.FAILED:
            reasons.append(f"validation-head-disposition-{head_decision.disposition.value}")
            head_gate_action = "route-validation-head-disposition-to-canonical-owner"
    failure_result = None
    failure_gate_action: str | None = None
    if validation_failure is not None:
        failure_result = classify_validation_failure(validation_failure)
        bound_head = (
            validation_head.current_head_sha if validation_head is not None else None
        )
        if bound_head is not None and failure_result.pr_head_sha != bound_head:
            reasons.append("validation-failure-evidence-bound-to-non-current-head")
            failure_gate_action = "reacquire-current-head-validation-evidence"
        elif failure_result.classification in _FAILURE_GATE_ACTIONS:
            reasons.append(
                f"validation-failure-{failure_result.classification.value.replace('_', '-')}"
            )
            failure_gate_action = _FAILURE_GATE_ACTIONS[failure_result.classification]
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

    next_diagnostic_surface: str | None = None
    diagnostic_blocker: DiagnosticSurfaceBlocker | None = None
    if diagnostics is not None and not diagnostics.diagnostics_actionable:
        authorized = _distinct(diagnostics.authorized_surfaces)
        attempted = _distinct(diagnostics.attempted_surfaces)
        remaining = tuple(surface for surface in authorized if surface not in attempted)
        if remaining:
            next_diagnostic_surface = remaining[0]
            reasons.append("diagnostic-evidence-insufficient-alternate-surface-available")
        else:
            reasons.append("diagnostic-surface-exhausted")
            diagnostic_blocker = _diagnostic_blocker(authorized, attempted)
    bounded_continuation_admitted = False
    if reasons:
        if zero_job_projection is not None and zero_job_projection.gates_code_repair:
            next_action = zero_job_projection.next_action or "reacquire-independent-diagnostics"
            bounded_continuation_admitted = zero_job_projection.bounded_continuation
        elif head_gate_action is not None:
            next_action = head_gate_action
        elif failure_gate_action is not None:
            next_action = failure_gate_action
        elif diagnostic_blocker is not None:
            next_action = "blocked-diagnostic-surface"
        elif next_diagnostic_surface is not None:
            next_action = "diagnose-via-authorized-alternate-surface"
            bounded_continuation_admitted = True
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
        next_diagnostic_surface=next_diagnostic_surface,
        diagnostic_blocker=diagnostic_blocker,
        validation_head_disposition=(
            head_decision.disposition.value if head_decision is not None else None
        ),
        validation_failure_classification=(
            failure_result.classification.value if failure_result is not None else None
        ),
        validation_repair_ladder=(
            failure_result.recommended_next_action
            if failure_result is not None
            and failure_result.classification
            is ValidationFailureClassification.PR_REGRESSION
            else None
        ),
    )


def _distinct(surfaces: Sequence[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for surface in surfaces:
        seen.setdefault(surface.strip(), None)
    return tuple(seen)


def _diagnostic_blocker(
    authorized: tuple[str, ...], attempted: tuple[str, ...]
) -> DiagnosticSurfaceBlocker:
    tried = tuple(surface for surface in authorized if surface in attempted)
    if tried:
        missing = (
            "actionable failure diagnostics for the exact current head could not be "
            f"obtained from any authorized diagnostic surface ({', '.join(tried)})"
        )
    else:
        missing = (
            "actionable failure diagnostics for the exact current head could not be "
            "obtained and no authorized diagnostic surface is available"
        )
    return DiagnosticSurfaceBlocker(
        kind=_DIAGNOSTIC_BLOCKER_KIND,
        missing_evidence=missing,
        attempted_surfaces=tried,
        clearing_condition=(
            "an additional already-authorized diagnostic surface (or the missing "
            "connector or integration capability that exposes the evidence) becomes "
            "available and returns actionable evidence for the exact current head"
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
