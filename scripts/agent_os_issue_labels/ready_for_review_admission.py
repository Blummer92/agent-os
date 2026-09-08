from __future__ import annotations

import re
from dataclasses import dataclass, field

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_FINAL_CANDIDATE_MODE = "draft-final-candidate"


@dataclass(frozen=True, slots=True)
class ReadyForReviewAdmissionResult:
    repository: str
    pr_number: int
    expected_head_sha: str
    observed_head_sha: str
    validation_head_sha: str
    validation_admission_mode: str
    transition_admissible: bool
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
    requested_changes: bool,
    blocking_unresolved: int,
    ready_for_review_authority_supplied: bool,
) -> ReadyForReviewAdmissionResult:
    """Fail closed before Draft -> Ready until the final candidate has converged.

    This is a non-authorizing projection over caller-supplied canonical evidence.
    It does not run validation, mark a PR ready, resolve review threads, or grant
    authority. It only prevents Ready-for-Review from being used as the trigger
    for the aggregate validation that should already have run through the
    existing exact-head Draft final-candidate path.
    """
    _validate_identity(repository, pr_number)
    _validate_bool(requested_changes, "requested_changes")
    _validate_bool(ready_for_review_authority_supplied, "ready_for_review_authority_supplied")
    if type(blocking_unresolved) is not int or blocking_unresolved < 0:
        raise ValueError("blocking_unresolved must be a non-negative built-in integer")

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
    if validation_admission_mode != _FINAL_CANDIDATE_MODE:
        reasons.append("draft-final-candidate-validation-not-proven")
    if aggregate_status != "success":
        reasons.append("authoritative-aggregate-not-green")
    if requested_changes:
        reasons.append("requested-changes-unresolved")
    if blocking_unresolved:
        reasons.append("blocking-review-conversation-unresolved")
    if not ready_for_review_authority_supplied:
        reasons.append("ready-for-review-authority-missing")

    if reasons:
        if "exact-head-drift" in reasons or "stale-validation-head" in reasons:
            next_action = "reacquire-current-head-and-validation"
        elif "draft-final-candidate-validation-not-proven" in reasons or "authoritative-aggregate-not-green" in reasons:
            next_action = "run-draft-final-candidate-aggregate"
        elif "requested-changes-unresolved" in reasons or "blocking-review-conversation-unresolved" in reasons:
            next_action = "resolve-review-before-ready"
        elif "ready-for-review-authority-missing" in reasons:
            next_action = "request-ready-for-review-authorization"
        else:
            next_action = "reacquire-ready-for-review-evidence"
        admissible = False
    else:
        next_action = "perform-ready-for-review-at-exact-head"
        admissible = True
        reasons.append("draft-final-candidate-ready-converged")

    return ReadyForReviewAdmissionResult(
        repository=repository,
        pr_number=pr_number,
        expected_head_sha=expected_head_sha,
        observed_head_sha=observed_head_sha,
        validation_head_sha=validation_head_sha,
        validation_admission_mode=validation_admission_mode,
        transition_admissible=admissible,
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
