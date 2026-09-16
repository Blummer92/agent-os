from __future__ import annotations

from dataclasses import dataclass, field

TERMINAL_BRANCH_STATES = frozenset(
    {
        "resolved-supported",
        "resolved-not-supported",
        "blocked-with-owner-and-clearing-condition",
        "not-applicable-after-evidence",
    }
)
INTERMEDIATE_BRANCH_STATES = frozenset({"untouched", "in-progress"})


@dataclass(frozen=True, slots=True)
class InvestigationCompletionAdmission:
    repository: str
    issue_number: int
    material_branch_states: tuple[str, ...]
    executable_next_action_available: bool
    subordinate_write_performed: bool
    completion_admissible: bool
    reason_codes: tuple[str, ...]
    next_action: str
    github_writes_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)
    workflow_authorized: bool = field(default=False, init=False)
    production_authorized: bool = field(default=False, init=False)
    external_system_write_authorized: bool = field(default=False, init=False)


def evaluate_investigation_completion_admission(
    *,
    repository: str,
    issue_number: int,
    material_branch_states: tuple[str, ...],
    executable_next_action_available: bool,
    subordinate_write_performed: bool,
) -> InvestigationCompletionAdmission:
    """Project the existing investigation-terminal invariant into executable form.

    This guard consumes already-classified material investigation branches. It
    creates no research state model, performs no read or write, and grants no
    authority. A checkpoint/comment is subordinate progress only; completion is
    admissible only when every material branch has an existing terminal state.
    """
    _validate_identity(repository, issue_number)
    if type(material_branch_states) is not tuple or not material_branch_states:
        raise ValueError("material_branch_states must be a non-empty tuple")
    if type(executable_next_action_available) is not bool:
        raise TypeError("executable_next_action_available must be built-in bool")
    if type(subordinate_write_performed) is not bool:
        raise TypeError("subordinate_write_performed must be built-in bool")

    allowed = TERMINAL_BRANCH_STATES | INTERMEDIATE_BRANCH_STATES
    if any(type(state) is not str or state not in allowed for state in material_branch_states):
        raise ValueError("material_branch_states contains an unsupported classification")

    intermediate = tuple(state for state in material_branch_states if state in INTERMEDIATE_BRANCH_STATES)
    reasons: list[str] = []
    if intermediate:
        reasons.append("material-investigation-branch-remains-intermediate")
    if subordinate_write_performed and intermediate:
        reasons.append("subordinate-write-is-progress-not-investigation-completion")
    if executable_next_action_available:
        reasons.append("authorized-executable-next-action-remains")

    completion_admissible = not intermediate and not executable_next_action_available
    if completion_admissible:
        reasons.append("all-material-investigation-branches-terminal")
        next_action = "report-reconciled-investigation-result"
    elif executable_next_action_available:
        next_action = "continue-same-lineage-investigation"
    else:
        next_action = "report-investigation-blocker-with-clearing-condition"

    return InvestigationCompletionAdmission(
        repository=repository,
        issue_number=issue_number,
        material_branch_states=material_branch_states,
        executable_next_action_available=executable_next_action_available,
        subordinate_write_performed=subordinate_write_performed,
        completion_admissible=completion_admissible,
        reason_codes=tuple(reasons),
        next_action=next_action,
    )


def _validate_identity(repository: str, issue_number: int) -> None:
    if type(repository) is not str or "/" not in repository or not repository.strip():
        raise ValueError("repository must be non-empty owner/name text")
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("issue_number must be a positive built-in integer")
