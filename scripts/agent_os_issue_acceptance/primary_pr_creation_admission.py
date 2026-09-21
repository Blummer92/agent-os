"""Pure admission guard for one Agent OS issue's primary Draft PR creation.

The caller must supply fresh canonical primary-PR evidence immediately before
materializing a Draft PR. This module performs no GitHub reads or writes and
grants no repository or lifecycle authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PrimaryPrCreationAction(str, Enum):
    CREATE_PRIMARY_PR = "create-primary-pr"
    REUSE_EXISTING_PRIMARY_PR = "reuse-existing-primary-pr"
    MANUAL_RECONCILIATION = "manual-reconciliation"


@dataclass(frozen=True, slots=True)
class ActivePrimaryPr:
    pull_request_number: int
    branch: str
    head_sha: str

    def __post_init__(self) -> None:
        if type(self.pull_request_number) is not int or self.pull_request_number < 1:
            raise TypeError("pull_request_number must be a positive built-in integer")
        if type(self.branch) is not str or not self.branch:
            raise ValueError("branch must be a non-empty string")
        if (
            type(self.head_sha) is not str
            or len(self.head_sha) != 40
            or any(character not in "0123456789abcdef" for character in self.head_sha)
        ):
            raise ValueError("head_sha must be a lowercase 40-character SHA")


@dataclass(frozen=True, slots=True)
class PrimaryPrCreationAdmission:
    action: PrimaryPrCreationAction
    existing_pull_request_number: int | None
    reason_codes: tuple[str, ...]
    github_writes_authorized: bool = False

    @property
    def creation_admitted(self) -> bool:
        return self.action is PrimaryPrCreationAction.CREATE_PRIMARY_PR


def evaluate_primary_pr_creation_admission(
    *,
    issue_number: int,
    issue_open: bool,
    evidence_current: bool,
    active_primary_prs: tuple[ActivePrimaryPr, ...],
) -> PrimaryPrCreationAdmission:
    """Classify create/reuse/conflict from fresh canonical primary-PR evidence."""
    if type(issue_number) is not int or issue_number < 1:
        raise TypeError("issue_number must be a positive built-in integer")
    if type(issue_open) is not bool or type(evidence_current) is not bool:
        raise TypeError("issue_open and evidence_current must be built-in bools")
    if type(active_primary_prs) is not tuple or any(
        type(item) is not ActivePrimaryPr for item in active_primary_prs
    ):
        raise TypeError("active_primary_prs must be an exact tuple of ActivePrimaryPr values")

    ordered = tuple(sorted(active_primary_prs, key=lambda item: item.pull_request_number))
    if len({item.pull_request_number for item in ordered}) != len(ordered):
        raise ValueError("active_primary_prs contains duplicate pull request numbers")

    if not issue_open:
        return PrimaryPrCreationAdmission(
            action=PrimaryPrCreationAction.MANUAL_RECONCILIATION,
            existing_pull_request_number=None,
            reason_codes=("issue.not-open",),
        )
    if not evidence_current:
        return PrimaryPrCreationAdmission(
            action=PrimaryPrCreationAction.MANUAL_RECONCILIATION,
            existing_pull_request_number=None,
            reason_codes=("primary-pr-evidence.stale",),
        )
    if not ordered:
        return PrimaryPrCreationAdmission(
            action=PrimaryPrCreationAction.CREATE_PRIMARY_PR,
            existing_pull_request_number=None,
            reason_codes=("primary-pr.none-active",),
        )
    if len(ordered) == 1:
        return PrimaryPrCreationAdmission(
            action=PrimaryPrCreationAction.REUSE_EXISTING_PRIMARY_PR,
            existing_pull_request_number=ordered[0].pull_request_number,
            reason_codes=("primary-pr.existing-active",),
        )
    return PrimaryPrCreationAdmission(
        action=PrimaryPrCreationAction.MANUAL_RECONCILIATION,
        existing_pull_request_number=None,
        reason_codes=("primary-pr.multiple-active",),
    )


@dataclass(frozen=True, slots=True)
class BatchIssuePrimaryPrEvidence:
    """Fresh canonical per-issue lineage evidence for one batch member."""

    issue_number: int
    issue_open: bool
    objective_ref: str
    active_primary_prs: tuple[ActivePrimaryPr, ...] = ()

    def __post_init__(self) -> None:
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise TypeError("issue_number must be a positive built-in integer")
        if type(self.issue_open) is not bool:
            raise TypeError("issue_open must be a built-in bool")
        if type(self.objective_ref) is not str or not self.objective_ref:
            raise ValueError("objective_ref must be non-empty canonical issue objective evidence")
        if type(self.active_primary_prs) is not tuple or any(
            type(item) is not ActivePrimaryPr for item in self.active_primary_prs
        ):
            raise TypeError("active_primary_prs must be an exact tuple of ActivePrimaryPr values")


@dataclass(frozen=True, slots=True)
class BatchPrimaryPrPackagingAdmission:
    packaging_admitted: bool
    issue_numbers: tuple[int, ...]
    per_issue_admissions: tuple[tuple[int, PrimaryPrCreationAdmission], ...]
    reason_codes: tuple[str, ...]
    github_writes_authorized: bool = False


def evaluate_batch_primary_pr_packaging(
    *,
    issue_evidence: tuple[BatchIssuePrimaryPrEvidence, ...],
    evidence_current: bool,
) -> BatchPrimaryPrPackagingAdmission:
    """Preserve independent primary-PR lineage across one batch (#2447).

    Batching is a sequencing mechanism, not permission to erase issue/PR lineage.
    Every per-issue create/reuse/reconcile decision is delegated to
    ``evaluate_primary_pr_creation_admission`` so no second lifecycle exists here,
    and multi-issue packaging is admitted only when the supplied canonical
    objective evidence proves one focused implementation objective owns them.
    """
    if type(issue_evidence) is not tuple or not issue_evidence:
        raise TypeError("issue_evidence must be a non-empty exact tuple")
    if any(type(item) is not BatchIssuePrimaryPrEvidence for item in issue_evidence):
        raise TypeError("issue_evidence must be an exact tuple of BatchIssuePrimaryPrEvidence values")
    if type(evidence_current) is not bool:
        raise TypeError("evidence_current must be a built-in bool")

    ordered = tuple(sorted(issue_evidence, key=lambda item: item.issue_number))
    issue_numbers = tuple(item.issue_number for item in ordered)
    if len(set(issue_numbers)) != len(issue_numbers):
        raise ValueError("issue_evidence must carry unique issue numbers")

    per_issue = tuple(
        (
            item.issue_number,
            evaluate_primary_pr_creation_admission(
                issue_number=item.issue_number,
                issue_open=item.issue_open,
                evidence_current=evidence_current,
                active_primary_prs=item.active_primary_prs,
            ),
        )
        for item in ordered
    )

    reasons: list[str] = []
    creation_blocked = False
    for _, admission in per_issue:
        if not admission.creation_admitted:
            creation_blocked = True
            reasons.extend(admission.reason_codes)

    # One issue trivially shares its own objective, so this single expression
    # covers both the single-issue and the multi-issue packaging question.
    shared_objective = len({item.objective_ref for item in ordered}) == 1
    if not shared_objective:
        reasons.append("primary-pr.independent-issues-require-separate-prs")
    elif not creation_blocked:
        reasons.append(
            "primary-pr.single-issue"
            if len(ordered) == 1
            else "primary-pr.shared-focused-objective-proven"
        )

    return BatchPrimaryPrPackagingAdmission(
        packaging_admitted=shared_objective and not creation_blocked,
        issue_numbers=issue_numbers,
        per_issue_admissions=per_issue,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )
