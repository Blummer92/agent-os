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
