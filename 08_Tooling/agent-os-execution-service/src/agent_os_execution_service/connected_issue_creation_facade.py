"""ChatGPT-facing composition seam for canonical connected issue creation (#2363, #2629).

This module does not search or semantically classify issues itself. It consumes
bounded duplicate/recurrence evidence from the host, delegates managed-label
planning to the existing #1962 connected-creation owner, and returns a
non-authorizing host projection for the existing GitHub create/readback flow.
"""

from __future__ import annotations

from pathlib import Path

from scripts.agent_os_issue_labels.connected_issue_creation import (
    DuplicateReviewDisposition,
    evaluate_duplicate_review_admission,
    managed_labels_for_create,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]


def plan_connected_issue_creation_for_host(
    *,
    repository: str,
    issue_body: str,
    duplicate_review_disposition: DuplicateReviewDisposition | str | None = None,
    canonical_issue_number: int | None = None,
    distinct_repair_seam: bool = False,
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
        "reconciliation_owner": "#1962",
        "implementation_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "external_write_authorized": False,
        "side_effects_performed": False,
    }
