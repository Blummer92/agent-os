"""Verify-open-before-mutate guard for new defect/process evidence (#2741).

Pure-local admission for mutations that persist newly discovered bug or
process evidence onto an issue. Before writing, the caller must supply the
target issue's freshly reacquired canonical open/closed state. A closed
target is refused fail-closed with a clear directive to an open owner (or to
create a new bug); it is never admitted as the active evidence owner.
Closed issues remain usable only as historical lineage references.

The check applies uniformly to defect evidence, process evidence, self-defect
logging, and subordinate bug capture during unfinished finite missions. The
module performs no GitHub reads or writes and introduces no second issue
registry, queue, scheduler, or lifecycle authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

EVIDENCE_KINDS = frozenset({"defect", "process"})


class DefectEvidenceMutationDecision(str, Enum):
    ADMITTED = "admitted"
    REFUSED = "refused"


class DefectEvidenceRefusalDirective(str, Enum):
    REACQUIRE_TARGET_STATE = "reacquire-target-state"
    ROUTE_TO_OPEN_OWNER = "route-to-open-owner"
    CREATE_NEW_BUG = "create-new-bug"


@dataclass(frozen=True, slots=True)
class DefectEvidenceMutationTarget:
    issue_number: int
    evidence_kind: Literal["defect", "process"]
    target_open: bool
    state_current: bool
    open_owner_issue_number: int | None = None
    historical_lineage_issue_number: int | None = None

    def __post_init__(self) -> None:
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise ValueError("issue_number must be a positive integer")
        if self.evidence_kind not in EVIDENCE_KINDS:
            raise ValueError("evidence_kind must be defect or process")
        if type(self.target_open) is not bool or type(self.state_current) is not bool:
            raise TypeError("target_open and state_current must be built-in bools")
        for name in ("open_owner_issue_number", "historical_lineage_issue_number"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError(f"{name} must be a positive integer or None")
        if (
            self.open_owner_issue_number is not None
            and self.open_owner_issue_number == self.issue_number
        ):
            raise ValueError("open_owner_issue_number cannot be the mutation target itself")


@dataclass(frozen=True, slots=True)
class DefectEvidenceMutationGuardResult:
    decision: DefectEvidenceMutationDecision
    directive: DefectEvidenceRefusalDirective | None
    issue_number: int
    evidence_kind: str
    open_owner_issue_number: int | None
    reason_codes: tuple[str, ...]
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.decision) is not DefectEvidenceMutationDecision:
            raise TypeError("decision must be DefectEvidenceMutationDecision")
        if self.directive is not None and type(self.directive) is not DefectEvidenceRefusalDirective:
            raise TypeError("directive must be DefectEvidenceRefusalDirective or None")
        if (self.decision is DefectEvidenceMutationDecision.ADMITTED) != (
            self.directive is None
        ):
            raise ValueError("admitted results carry no directive; refused results must")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str or not code for code in self.reason_codes
        ):
            raise TypeError("reason_codes must be an exact tuple of non-empty strings")
        if self.side_effects_performed:
            raise ValueError("guard result cannot perform side effects")


def _refuse(
    target: DefectEvidenceMutationTarget,
    directive: DefectEvidenceRefusalDirective,
    reason_codes: tuple[str, ...],
) -> DefectEvidenceMutationGuardResult:
    return DefectEvidenceMutationGuardResult(
        decision=DefectEvidenceMutationDecision.REFUSED,
        directive=directive,
        issue_number=target.issue_number,
        evidence_kind=target.evidence_kind,
        open_owner_issue_number=target.open_owner_issue_number,
        reason_codes=reason_codes,
    )


def evaluate_defect_evidence_mutation(
    target: DefectEvidenceMutationTarget,
) -> DefectEvidenceMutationGuardResult:
    """Admit or refuse persisting new defect/process evidence on the target.

    Currency is checked before openness: stale state evidence fails closed
    even when it claims the target is open, because the guard must verify the
    target is still open immediately before the write.
    """
    if type(target) is not DefectEvidenceMutationTarget:
        raise TypeError("target must be an exact DefectEvidenceMutationTarget")
    if not target.state_current:
        return _refuse(
            target,
            DefectEvidenceRefusalDirective.REACQUIRE_TARGET_STATE,
            ("mutation.target-state-not-current",),
        )
    if target.target_open:
        return DefectEvidenceMutationGuardResult(
            decision=DefectEvidenceMutationDecision.ADMITTED,
            directive=None,
            issue_number=target.issue_number,
            evidence_kind=target.evidence_kind,
            open_owner_issue_number=None,
            reason_codes=("mutation.target-open-verified",),
        )
    if target.open_owner_issue_number is not None:
        return _refuse(
            target,
            DefectEvidenceRefusalDirective.ROUTE_TO_OPEN_OWNER,
            (
                "mutation.target-closed-historical-only",
                "mutation.route-to-open-owner",
            ),
        )
    return _refuse(
        target,
        DefectEvidenceRefusalDirective.CREATE_NEW_BUG,
        (
            "mutation.target-closed-historical-only",
            "mutation.no-open-owner-create-new-bug",
        ),
    )
