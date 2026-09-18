from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import LifecycleMutationAdmissionResult

from .issue_metadata import load_issue_form_fields, metadata_contract, parse_issue_form_body
from .issue_reconciler import IssueLabelProvider, IssueLabelReconciliationResult, reconcile_issue_labels
from .label_map import expected_labels, load_label_map

_MANAGED_PREFIXES = ("owner:", "status:", "type:", "epic:")
_MANAGED_EXACT = {"agent-os"}


class DuplicateReviewDisposition(str, Enum):
    NEW_DISTINCT_BUG = "NEW_DISTINCT_BUG"
    RECURRENCE_EXISTING_OWNER = "RECURRENCE_EXISTING_OWNER"
    DUPLICATE_EXISTING_OWNER = "DUPLICATE_EXISTING_OWNER"
    PARTIAL_OVERLAP = "PARTIAL_OVERLAP"
    FOCUSED_SUCCESSOR = "FOCUSED_SUCCESSOR"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass(frozen=True, slots=True)
class DuplicateReviewAdmission:
    disposition: DuplicateReviewDisposition
    canonical_issue_number: int | None
    prior_scope_review: tuple[str, ...]
    create_allowed: bool
    next_operation: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConnectedIssueCreationConvergence:
    repository: str
    issue_number: int
    labels_for_create: tuple[str, ...]
    reconciliation: IssueLabelReconciliationResult
    terminal_success: bool
    reason_codes: tuple[str, ...]


def evaluate_duplicate_review_admission(
    issue_body: str,
    *,
    disposition: DuplicateReviewDisposition | str | None,
    canonical_issue_number: int | None = None,
    distinct_repair_seam: bool = False,
    issue_form_path: str | Path,
) -> DuplicateReviewAdmission:
    fields = load_issue_form_fields(issue_form_path)
    metadata = parse_issue_form_body(issue_body, fields)
    review = tuple(metadata.get("prior-scope-review", ()))
    if not review:
        return DuplicateReviewAdmission(
            DuplicateReviewDisposition.MANUAL_REVIEW,
            None,
            (),
            False,
            "manual-review-duplicate-admission-required",
            ("duplicate-review.prior-scope-evidence-missing",),
        )

    try:
        resolved = DuplicateReviewDisposition(disposition) if disposition is not None else None
    except ValueError:
        resolved = None
    if resolved is None:
        return DuplicateReviewAdmission(
            DuplicateReviewDisposition.MANUAL_REVIEW,
            canonical_issue_number,
            review,
            False,
            "manual-review-duplicate-admission-required",
            ("duplicate-review.disposition-missing-or-invalid",),
        )

    canonical_required = resolved in {
        DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER,
        DuplicateReviewDisposition.DUPLICATE_EXISTING_OWNER,
        DuplicateReviewDisposition.FOCUSED_SUCCESSOR,
    }
    if canonical_required and (type(canonical_issue_number) is not int or canonical_issue_number <= 0):
        return DuplicateReviewAdmission(
            DuplicateReviewDisposition.MANUAL_REVIEW,
            None,
            review,
            False,
            "manual-review-duplicate-admission-required",
            ("duplicate-review.canonical-owner-unproven",),
        )

    if resolved is DuplicateReviewDisposition.NEW_DISTINCT_BUG:
        return DuplicateReviewAdmission(
            resolved,
            None,
            review,
            True,
            "create-then-canonical-readback-and-converge",
            ("duplicate-review.distinct-bug-proven",),
        )
    if resolved is DuplicateReviewDisposition.FOCUSED_SUCCESSOR:
        if not distinct_repair_seam:
            return DuplicateReviewAdmission(
                DuplicateReviewDisposition.MANUAL_REVIEW,
                canonical_issue_number,
                review,
                False,
                "manual-review-partial-overlap",
                ("duplicate-review.focused-successor-seam-unproven",),
            )
        return DuplicateReviewAdmission(
            resolved,
            canonical_issue_number,
            review,
            True,
            "create-then-canonical-readback-and-converge",
            ("duplicate-review.focused-successor-proven",),
        )
    if resolved is DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER:
        return DuplicateReviewAdmission(
            resolved,
            canonical_issue_number,
            review,
            False,
            "append-recurrence-evidence-to-canonical-issue",
            ("duplicate-review.recurrence-existing-owner",),
        )
    if resolved is DuplicateReviewDisposition.DUPLICATE_EXISTING_OWNER:
        return DuplicateReviewAdmission(
            resolved,
            canonical_issue_number,
            review,
            False,
            "reuse-canonical-issue-no-create",
            ("duplicate-review.duplicate-existing-owner",),
        )
    if resolved is DuplicateReviewDisposition.PARTIAL_OVERLAP:
        return DuplicateReviewAdmission(
            resolved,
            canonical_issue_number,
            review,
            False,
            "manual-review-partial-overlap",
            ("duplicate-review.partial-overlap",),
        )
    return DuplicateReviewAdmission(
        DuplicateReviewDisposition.MANUAL_REVIEW,
        canonical_issue_number,
        review,
        False,
        "manual-review-duplicate-admission-required",
        ("duplicate-review.manual-review",),
    )


def managed_labels_for_create(issue_body: str, *, issue_form_path: str | Path, label_map_path: str | Path) -> tuple[str, ...]:
    fields = load_issue_form_fields(issue_form_path)
    metadata = parse_issue_form_body(issue_body, fields)
    if metadata_contract(metadata) != "tiered":
        raise ValueError("canonical tiered metadata is required before connected issue creation")
    desired, unknown = expected_labels(metadata, load_label_map(label_map_path))
    if unknown:
        raise ValueError("unmapped canonical metadata cannot authorize managed labels")
    managed = tuple(sorted(label for label in desired if _is_managed(label)))
    owners = tuple(label for label in managed if label.startswith("owner:"))
    statuses = tuple(label for label in managed if label.startswith("status:"))
    if len(owners) != 1 or len(statuses) != 1:
        raise ValueError("connected issue creation requires one owner and one readiness label")
    return managed


def converge_connected_issue_creation(provider: IssueLabelProvider, repository: str, issue_number: int, *, issue_form_path: str | Path, label_map_path: str | Path, lifecycle_admission: LifecycleMutationAdmissionResult | None) -> ConnectedIssueCreationConvergence:
    initial = provider.read(repository, issue_number)
    labels_for_create = managed_labels_for_create(initial.body, issue_form_path=issue_form_path, label_map_path=label_map_path)
    reconciliation = reconcile_issue_labels(provider, repository, issue_number, issue_form_path=issue_form_path, label_map_path=label_map_path, dry_run=False, lifecycle_admission=lifecycle_admission)
    terminal = reconciliation.convergence_status in {"converged", "already-current"}
    reasons = set(reconciliation.reason_codes)
    reasons.add("connected-create-label-convergence-proven" if terminal else "connected-create-label-convergence-not-proven")
    return ConnectedIssueCreationConvergence(repository, issue_number, labels_for_create, reconciliation, terminal, tuple(sorted(reasons)))


def _is_managed(label: str) -> bool:
    return label in _MANAGED_EXACT or label.startswith(_MANAGED_PREFIXES)
