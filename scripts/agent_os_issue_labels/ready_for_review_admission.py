from __future__ import annotations

import re
from dataclasses import dataclass, field

from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    IssueClosureAdmission,
)
from scripts.agent_os_issue_acceptance.parse_pr import (
    detect_github_effective_closing_references,
    dual_implemented_issue_claims,
    unauthorized_closing_targets,
)

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)

#: Closed vocabulary for ``validation_admission_mode`` (#3350). The mode label
#: names the validation story the caller ran; it is not a second authority and
#: never substitutes for the authoritative aggregate evidence itself.
FINAL_CANDIDATE_MODE = "draft-final-candidate"
DRAFT_FOCUSED_MODE = "pull-request-draft-focused"
VALIDATION_ADMISSION_MODES = frozenset({FINAL_CANDIDATE_MODE, DRAFT_FOCUSED_MODE})

_UNKNOWN_MODE_REASON = "unknown-validation-admission-mode"
_UNKNOWN_MODE_NEXT_ACTION = "supply-canonical-validation-admission-mode"
_MAX_CLOSURE_ADMISSIONS = 256


@dataclass(frozen=True, slots=True)
class ReadyForReviewAdmissionResult:
    repository: str
    pr_number: int
    expected_head_sha: str
    observed_head_sha: str
    validation_head_sha: str
    validation_admission_mode: str
    transition_admissible: bool
    provisional_ready: bool
    rollback_to_draft_required: bool
    reason_codes: tuple[str, ...]
    next_action: str
    ready_for_review_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)
    workflow_authorized: bool = field(default=False, init=False)
    protected_setting_authorized: bool = field(default=False, init=False)
    production_authorized: bool = field(default=False, init=False)
    external_system_write_authorized: bool = field(default=False, init=False)


def evaluate_ready_for_review_admission(
    *,
    repository: str,
    pr_number: int,
    pr_lifecycle_state: str,
    expected_head_sha: str,
    observed_head_sha: str,
    validation_head_sha: str,
    validation_admission_mode: str,
    aggregate_status: str,
    focused_status: str,
    requested_changes: bool,
    blocking_unresolved: int,
    ready_for_review_authority_supplied: bool,
    pr_title: str,
    pr_body: str,
    closure_admissions: tuple[IssueClosureAdmission, ...] = (),
) -> ReadyForReviewAdmissionResult:
    """Project ordinary or provisional Draft -> Ready admission.

    The ordinary path still requires a successful exact-head Draft final-candidate
    aggregate. The provisional path is deliberately narrower: when the exact
    current Draft has no review blocker or requested changes, Ready authority is
    supplied, and the authoritative aggregate is only missing/skipped because the
    Draft trigger deferred it, the existing reversible Ready transition may be
    used solely to trigger the repository's existing ready_for_review aggregate.

    This projection grants no merge, closure, workflow, protected-setting,
    production, or external-write authority. A provisional transition must be
    reconciled after the Ready-triggered aggregate; non-success or head drift
    requires conversion back to Draft before later lifecycle progression.

    ``validation_admission_mode`` belongs to the closed vocabulary
    ``VALIDATION_ADMISSION_MODES`` (``FINAL_CANDIDATE_MODE`` for the ordinary
    path, ``DRAFT_FOCUSED_MODE`` for the provisional path). The server derives
    the effective mode from the authoritative aggregate evidence: a successful
    authoritative aggregate proves final-candidate mode regardless of the label
    supplied (#3350), so a genuine exact-head success with a wrong or missing
    label converges instead of forcing re-dispatch. An uninterpretable mode
    with any other aggregate state fails closed with
    ``unknown-validation-admission-mode``; it can no longer silently select
    the provisional path.

    The Ready transition starts the merge path, so it also fails closed on
    GitHub-effective closing references (#3157): the same detected-targets
    minus canonically-authorized-targets comparison merge admission uses runs
    here, and any unauthorized closing target blocks the transition. It also
    fails closed on dual implemented-issue lineage (#2991): a primary PR
    title/body must not claim two distinct issues as implemented, even when
    both closing targets carry canonical close-issue admission — the second
    issue must be linked as dependency/consumer evidence instead. This
    grants no closure authority; it only blocks Ready.
    """
    _validate_identity(repository, pr_number)
    _validate_bool(requested_changes, "requested_changes")
    _validate_bool(ready_for_review_authority_supplied, "ready_for_review_authority_supplied")
    if type(validation_admission_mode) is not str:
        raise TypeError("validation_admission_mode must be a built-in string")
    if type(blocking_unresolved) is not int or blocking_unresolved < 0:
        raise ValueError("blocking_unresolved must be a non-negative built-in integer")
    if type(pr_title) is not str or type(pr_body) is not str:
        raise TypeError("pr_title and pr_body must be built-in strings")
    admissions = _validated_closure_admissions(closure_admissions)
    effective_mode = _derive_validation_admission_mode(
        validation_admission_mode=validation_admission_mode,
        aggregate_status=aggregate_status,
    )
    if effective_mode not in VALIDATION_ADMISSION_MODES:
        return ReadyForReviewAdmissionResult(
            repository=repository,
            pr_number=pr_number,
            expected_head_sha=expected_head_sha,
            observed_head_sha=observed_head_sha,
            validation_head_sha=validation_head_sha,
            validation_admission_mode=validation_admission_mode,
            transition_admissible=False,
            provisional_ready=False,
            rollback_to_draft_required=False,
            reason_codes=(_UNKNOWN_MODE_REASON,),
            next_action=_UNKNOWN_MODE_NEXT_ACTION,
        )

    reasons: list[str] = []
    if pr_lifecycle_state != "draft":
        reasons.append("pr-not-draft")
    if not _is_sha40(expected_head_sha) or not _is_sha40(observed_head_sha):
        reasons.append("invalid-head-identity")
    elif expected_head_sha != observed_head_sha:
        reasons.append("exact-head-drift")
    if not _is_sha40(validation_head_sha):
        reasons.append("invalid-validation-head")
    elif validation_head_sha != observed_head_sha:
        reasons.append("stale-validation-head")
    if requested_changes:
        reasons.append("requested-changes-unresolved")
    if blocking_unresolved:
        reasons.append("blocking-review-conversation-unresolved")
    if not ready_for_review_authority_supplied:
        reasons.append("ready-for-review-authority-missing")
    detected = detect_github_effective_closing_references(pr_body, pr_title)
    authorized = [
        admission.target
        for admission in admissions
        if admission.authorization.repository.lower() == repository.lower()
    ]
    if unauthorized_closing_targets(detected, tuple(authorized)):
        reasons.append("unauthorized-closing-reference")
    if dual_implemented_issue_claims(detected):
        reasons.append("multiple-implemented-issues-linked")

    final_candidate_green = (
        effective_mode == FINAL_CANDIDATE_MODE
        and aggregate_status == "success"
    )
    provisional_aggregate_missing = (
        effective_mode != FINAL_CANDIDATE_MODE
        and focused_status == "success"
        and aggregate_status in {"missing", "skipped"}
    )

    hard_blockers = bool(reasons)
    provisional_ready = False
    rollback_to_draft_required = False

    if not hard_blockers and final_candidate_green:
        next_action = "perform-ready-for-review-at-exact-head"
        admissible = True
        reasons.append("draft-final-candidate-ready-converged")
    elif not hard_blockers and provisional_aggregate_missing:
        next_action = "perform-provisional-ready-to-trigger-exact-head-aggregate"
        admissible = True
        provisional_ready = True
        rollback_to_draft_required = True
        reasons.append("provisional-ready-aggregate-trigger-admitted")
    else:
        if effective_mode != FINAL_CANDIDATE_MODE:
            reasons.append("draft-final-candidate-validation-not-proven")
        if focused_status != "success":
            reasons.append("focused-validation-not-green")
        if aggregate_status != "success":
            reasons.append("authoritative-aggregate-not-green")
        if "exact-head-drift" in reasons or "stale-validation-head" in reasons:
            next_action = "reacquire-current-head-and-validation"
        elif "requested-changes-unresolved" in reasons or "blocking-review-conversation-unresolved" in reasons:
            next_action = "resolve-review-before-ready"
        elif "ready-for-review-authority-missing" in reasons:
            next_action = "request-ready-for-review-authorization"
        elif "unauthorized-closing-reference" in reasons:
            next_action = "authorize-issue-closure-before-ready"
        elif "multiple-implemented-issues-linked" in reasons:
            next_action = "link-one-issue-as-implemented"
        else:
            next_action = "run-draft-final-candidate-aggregate"
        admissible = False

    return ReadyForReviewAdmissionResult(
        repository=repository,
        pr_number=pr_number,
        expected_head_sha=expected_head_sha,
        observed_head_sha=observed_head_sha,
        validation_head_sha=validation_head_sha,
        validation_admission_mode=validation_admission_mode,
        transition_admissible=admissible,
        provisional_ready=provisional_ready,
        rollback_to_draft_required=rollback_to_draft_required,
        reason_codes=tuple(reasons),
        next_action=next_action,
    )


def _validate_identity(repository: str, pr_number: int) -> None:
    if type(repository) is not str or "/" not in repository or not repository.strip():
        raise ValueError("repository must be non-empty owner/name text")
    if type(pr_number) is not int or pr_number < 1:
        raise ValueError("pr_number must be a positive built-in integer")


def _validate_bool(value: bool, field_name: str) -> None:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be built-in bool")


def _is_sha40(value: object) -> bool:
    return type(value) is str and _SHA40_RE.fullmatch(value) is not None


def _derive_validation_admission_mode(
    *, validation_admission_mode: str, aggregate_status: object
) -> str:
    """Derive the effective admission mode from authoritative aggregate evidence (#3350).

    The authoritative aggregate's terminal state is the evidence; the caller's
    mode label is only a claim about which validation story ran. A successful
    authoritative aggregate proves the final-candidate story regardless of the
    label supplied, so a genuine exact-head final-candidate success with a
    wrong or missing mode label still converges instead of forcing a wasted
    re-dispatch. Any other aggregate state leaves the caller's label in
    effect, and the closed-vocabulary guard then applies to it.
    """
    if aggregate_status == "success":
        return FINAL_CANDIDATE_MODE
    return validation_admission_mode


def _validated_closure_admissions(
    value: object,
) -> tuple[IssueClosureAdmission, ...]:
    if type(value) is not tuple:
        raise TypeError("closure_admissions must be an exact tuple")
    for item in value:
        if type(item) is not IssueClosureAdmission:
            raise TypeError("closure_admissions must contain IssueClosureAdmission")
    if len(value) > _MAX_CLOSURE_ADMISSIONS:
        raise ValueError("closure_admissions exceeds bounded item count")
    return value


@dataclass(frozen=True, slots=True)
class ProvisionalReadyReconciliationResult:
    repository: str
    pr_number: int
    expected_head_sha: str
    observed_head_sha: str
    aggregate_status: str
    ready_converged: bool
    rollback_to_draft_required: bool
    reason_codes: tuple[str, ...]
    next_action: str
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)


def evaluate_provisional_ready_reconciliation(
    *,
    repository: str,
    pr_number: int,
    pr_lifecycle_state: str,
    expected_head_sha: str,
    observed_head_sha: str,
    validation_head_sha: str,
    aggregate_status: str,
) -> ProvisionalReadyReconciliationResult:
    """Reconcile the reversible Ready validation trigger without granting release authority."""
    _validate_identity(repository, pr_number)
    reasons: list[str] = []
    if pr_lifecycle_state != "ready":
        reasons.append("pr-not-ready")
    if not _is_sha40(expected_head_sha) or not _is_sha40(observed_head_sha):
        reasons.append("invalid-head-identity")
    elif expected_head_sha != observed_head_sha:
        reasons.append("exact-head-drift")
    if not _is_sha40(validation_head_sha):
        reasons.append("invalid-validation-head")
    elif validation_head_sha != observed_head_sha:
        reasons.append("stale-validation-head")

    ready_converged = not reasons and aggregate_status == "success"
    if ready_converged:
        reasons.append("provisional-ready-aggregate-converged")
        rollback = False
        next_action = "retain-ready-and-reacquire-later-gates"
    else:
        if aggregate_status != "success":
            reasons.append("authoritative-aggregate-not-green")
        rollback = True
        if aggregate_status in {"pending", "queued", "in_progress"}:
            reasons.append("provisional-ready-aggregate-pending")
            next_action = "convert-pull-request-back-to-draft-and-await-exact-head-aggregate"
        else:
            next_action = "convert-pull-request-back-to-draft"

    return ProvisionalReadyReconciliationResult(
        repository=repository,
        pr_number=pr_number,
        expected_head_sha=expected_head_sha,
        observed_head_sha=observed_head_sha,
        aggregate_status=aggregate_status,
        ready_converged=ready_converged,
        rollback_to_draft_required=rollback,
        reason_codes=tuple(reasons),
        next_action=next_action,
    )
