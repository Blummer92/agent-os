"""ChatGPT-facing composition seam for canonical connected issue creation (#2363, #2629).

This module does not search or semantically classify issues itself. It consumes
bounded duplicate/recurrence evidence from the host, delegates managed-label
planning to the existing #1962 connected-creation owner, and returns a
non-authorizing host projection for the existing GitHub create/readback flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from scripts.agent_os_issue_labels.connected_issue_creation import (
    DuplicateCandidateEvidence,
    DuplicateReviewDisposition,
    evaluate_duplicate_review_admission,
    managed_labels_for_create,
)


class ConnectedIssueCreateProvider(Protocol):
    """Minimal native-create/readback surface used by the host adapter."""

    def create(self, repository: str, title: str, body: str, labels: tuple[str, ...]) -> int: ...
    def read_labels(self, repository: str, issue_number: int) -> tuple[str, ...]: ...
    def reconcile(self, repository: str, issue_number: int) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class ConnectedIssueCreateResult:
    repository: str
    issue_number: int
    required_managed_labels: tuple[str, ...]
    observed_managed_labels: tuple[str, ...]
    terminal_success: bool
    reconciliation_performed: bool
    reason_codes: tuple[str, ...]


_REPO_ROOT = Path(__file__).resolve().parents[4]


def plan_connected_issue_creation_for_host(
    *,
    repository: str,
    issue_body: str,
    duplicate_review_disposition: DuplicateReviewDisposition | str | None = None,
    canonical_issue_number: int | None = None,
    distinct_repair_seam: bool = False,
    candidate_evidence: tuple[DuplicateCandidateEvidence, ...] = (),
    candidate_enumeration_complete: bool = False,
    issue_form_path: str | Path = _REPO_ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml",
    label_map_path: str | Path = _REPO_ROOT / ".github/labeler/agent-os-issue-label-map.yml",
) -> dict[str, object]:
    """Return the bounded pre-create projection without creating write authority."""
    if type(repository) is not str or repository.count("/") != 1 or not all(repository.split("/")):
        raise ValueError("repository must use bounded owner/name syntax")
    if type(issue_body) is not str or not issue_body.strip():
        raise ValueError("issue_body must be non-empty canonical text")

    labels = managed_labels_for_create(
        issue_body,
        issue_form_path=issue_form_path,
        label_map_path=label_map_path,
    )
    duplicate_review = evaluate_duplicate_review_admission(
        issue_body,
        disposition=duplicate_review_disposition,
        canonical_issue_number=canonical_issue_number,
        distinct_repair_seam=distinct_repair_seam,
        candidate_evidence=candidate_evidence,
        candidate_enumeration_complete=candidate_enumeration_complete,
        issue_form_path=issue_form_path,
    )
    return {
        "repository": repository,
        "proposed_labels": list(labels),
        "duplicate_review_disposition": duplicate_review.disposition.value,
        "canonical_issue_number": duplicate_review.canonical_issue_number,
        "duplicate_review_reason_codes": list(duplicate_review.reason_codes),
        "create_allowed": duplicate_review.create_allowed,
        "next_operation": duplicate_review.next_operation,
        "create_contract": "canonical-labels-readback-convergence-required",
        "create_response_terminal": False,
        "post_create_readback_required": duplicate_review.create_allowed,
        "post_create_reconciliation_required_on_mismatch": duplicate_review.create_allowed,
        "required_managed_label_readback": list(labels) if duplicate_review.create_allowed else [],
        "missing_required_managed_label_action": "reconcile-via-1962-before-terminal" if duplicate_review.create_allowed else None,
        "terminal_success_requires_label_convergence": duplicate_review.create_allowed,
        "reconciliation_owner": "#1962",
        "implementation_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "external_write_authorized": False,
        "side_effects_performed": False,
    }


def create_connected_issue_for_host(
    provider: ConnectedIssueCreateProvider,
    *,
    repository: str,
    title: str,
    issue_body: str,
    duplicate_review_disposition: DuplicateReviewDisposition | str | None = None,
    canonical_issue_number: int | None = None,
    distinct_repair_seam: bool = False,
    candidate_evidence: tuple[DuplicateCandidateEvidence, ...] = (),
    candidate_enumeration_complete: bool = False,
    issue_form_path: str | Path = _REPO_ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml",
    label_map_path: str | Path = _REPO_ROOT / ".github/labeler/agent-os-issue-label-map.yml",
) -> ConnectedIssueCreateResult:
    """Consume create -> canonical readback -> existing #1962 reconciliation."""
    plan = plan_connected_issue_creation_for_host(
        repository=repository,
        issue_body=issue_body,
        duplicate_review_disposition=duplicate_review_disposition,
        canonical_issue_number=canonical_issue_number,
        distinct_repair_seam=distinct_repair_seam,
        candidate_evidence=candidate_evidence,
        candidate_enumeration_complete=candidate_enumeration_complete,
        issue_form_path=issue_form_path,
        label_map_path=label_map_path,
    )
    if not plan["create_allowed"]:
        raise ValueError("connected issue creation not admitted: " + str(plan["next_operation"]))
    if type(title) is not str or not title.strip():
        raise ValueError("title must be non-empty canonical text")

    required = tuple(sorted(plan["required_managed_label_readback"]))
    issue_number = provider.create(repository, title.strip(), issue_body, required)
    if type(issue_number) is not int or issue_number <= 0:
        raise ValueError("native create did not return a valid issue number")

    observed = tuple(sorted(provider.read_labels(repository, issue_number)))
    reconciled = False
    if not set(required).issubset(observed):
        provider.reconcile(repository, issue_number)
        reconciled = True
        observed = tuple(sorted(provider.read_labels(repository, issue_number)))

    missing = tuple(sorted(set(required) - set(observed)))
    terminal = not missing
    reasons = (
        ("connected-create-label-convergence-proven",)
        if terminal
        else ("connected-create-label-convergence-not-proven",)
    )
    return ConnectedIssueCreateResult(
        repository, issue_number, required, observed, terminal, reconciled, reasons
    )
