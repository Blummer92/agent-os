from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LifecycleOperation(str, Enum):
    CLOSE_ISSUE = "close-issue"
    UPDATE_ISSUE = "update-issue"
    UPDATE_PULL_REQUEST = "update-pull-request"
    MARK_PULL_REQUEST_READY = "mark-pull-request-ready"


class TargetKind(str, Enum):
    ISSUE = "issue"
    PULL_REQUEST = "pull-request"


_OPERATION_TARGET_KIND = {
    LifecycleOperation.CLOSE_ISSUE: TargetKind.ISSUE,
    LifecycleOperation.UPDATE_ISSUE: TargetKind.ISSUE,
    LifecycleOperation.UPDATE_PULL_REQUEST: TargetKind.PULL_REQUEST,
    LifecycleOperation.MARK_PULL_REQUEST_READY: TargetKind.PULL_REQUEST,
}


@dataclass(frozen=True, slots=True)
class OperationTargetAdmission:
    repository: str
    target_number: int
    operation: LifecycleOperation
    selected_target_kind: TargetKind
    expected_target_kind: TargetKind
    prior_effect_none_proven: bool
    current_target_reacquired: bool
    capable_alternative_available: bool
    mutation_admissible: bool
    reason_codes: tuple[str, ...]
    next_action: str
    github_writes_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)
    workflow_authorized: bool = field(default=False, init=False)
    production_authorized: bool = field(default=False, init=False)


def evaluate_operation_target_admission(
    *,
    repository: str,
    target_number: int,
    operation: LifecycleOperation,
    selected_target_kind: TargetKind,
    prior_effect_none_proven: bool,
    current_target_reacquired: bool,
    capable_alternative_available: bool,
) -> OperationTargetAdmission:
    """Fail closed when a lifecycle operation is bound to the wrong target kind.

    This pre-mutation guard does not choose a tool or grant write authority. When
    a wrong target/action selection is proven to have had zero effect and a
    capable authorized alternative exists, it requires currentness reacquisition
    and continuation through the existing #1237 post-selection seam instead of
    terminating the parent finite mission.
    """
    if type(repository) is not str or "/" not in repository or not repository.strip():
        raise ValueError("repository must be non-empty owner/name text")
    if type(target_number) is not int or target_number < 1:
        raise ValueError("target_number must be a positive built-in integer")
    if type(operation) is not LifecycleOperation:
        raise TypeError("operation must be an exact LifecycleOperation")
    if type(selected_target_kind) is not TargetKind:
        raise TypeError("selected_target_kind must be an exact TargetKind")
    for name, value in (
        ("prior_effect_none_proven", prior_effect_none_proven),
        ("current_target_reacquired", current_target_reacquired),
        ("capable_alternative_available", capable_alternative_available),
    ):
        if type(value) is not bool:
            raise TypeError(f"{name} must be built-in bool")

    expected = _OPERATION_TARGET_KIND[operation]
    reasons: list[str] = []
    if selected_target_kind is not expected:
        reasons.append("operation-target-kind-mismatch")
    if not prior_effect_none_proven:
        reasons.append("prior-effect-not-proven-zero")
    if not current_target_reacquired:
        reasons.append("current-target-not-reacquired")

    if not reasons:
        mutation_admissible = True
        next_action = "continue-selected-operation"
        reasons.append("operation-target-binding-current")
    else:
        mutation_admissible = False
        if "operation-target-kind-mismatch" in reasons and prior_effect_none_proven:
            if not current_target_reacquired:
                next_action = "reacquire-issue-currentness-before-alternative"
            elif capable_alternative_available:
                next_action = "continue-via-approved-alternative-on-same-lineage"
            else:
                next_action = "report-no-capable-authorized-alternative"
        elif "prior-effect-not-proven-zero" in reasons:
            next_action = "read-back-canonical-state-before-any-mutation"
        else:
            next_action = "reacquire-operation-bindings"

    return OperationTargetAdmission(
        repository=repository,
        target_number=target_number,
        operation=operation,
        selected_target_kind=selected_target_kind,
        expected_target_kind=expected,
        prior_effect_none_proven=prior_effect_none_proven,
        current_target_reacquired=current_target_reacquired,
        capable_alternative_available=capable_alternative_available,
        mutation_admissible=mutation_admissible,
        reason_codes=tuple(reasons),
        next_action=next_action,
    )
