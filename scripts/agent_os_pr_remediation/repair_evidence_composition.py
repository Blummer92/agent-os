"""Bounded repair-evidence composition for the existing #1540 PR summary.

This module consumes canonical typed outputs from #1611 and #1602 and renders
only repair-relevant evidence facts beside the existing ReviewMergeEvidenceSummary.
It does not reclassify provenance, infer repairs, publish comments, or grant any
authority.
"""

from __future__ import annotations

from .aggregate_failure_provenance import AggregateFailureEvidence
from .ci_evidence_recovery import CIEvidenceRecoveryPlan
from .merge_evidence_summary import (
    MAX_RENDERED_SUMMARY_CHARS,
    ReviewMergeEvidenceSummary,
    render_review_merge_evidence_summary,
)
from .models import EvidenceValidationError

MAX_ACTIONABLE_FAILURE_CHARS = 1_200
MAX_POST_REPAIR_VALIDATION_ITEMS = 8


def _bounded_items(values: tuple[str, ...] | list[str], field: str) -> tuple[str, ...]:
    if type(values) not in {tuple, list} or len(values) > 256:
        raise EvidenceValidationError(f"{field} must be a bounded list or tuple")
    result: list[str] = []
    for value in values:
        if type(value) is not str or not value or len(value) > 10_000:
            raise EvidenceValidationError(f"{field} items must be bounded non-empty strings")
        result.append(value)
    if len(set(result)) != len(result):
        raise EvidenceValidationError(f"{field} contains duplicates")
    return tuple(sorted(result))


def _non_authorizing_summary(summary: ReviewMergeEvidenceSummary) -> None:
    if any(
        value is not False
        for value in (
            summary.execution_authorized,
            summary.merge_authorized,
            summary.closure_authorized,
            summary.production_authorized,
            summary.external_write_authorized,
            summary.side_effects_performed,
        )
    ):
        raise EvidenceValidationError("repair evidence composition requires a non-authorizing summary")


def _non_authorizing_aggregate(evidence: AggregateFailureEvidence) -> None:
    if any(
        value is not False
        for value in (
            evidence.execution_authorized,
            evidence.merge_authorized,
            evidence.closure_authorized,
            evidence.production_authorized,
            evidence.external_write_authorized,
            evidence.side_effects_performed,
        )
    ):
        raise EvidenceValidationError("aggregate failure evidence must remain non-authorizing")


def _actionable_lines(value: str) -> list[str]:
    text = value[:MAX_ACTIONABLE_FAILURE_CHARS]
    lines = [f"    {line}" for line in text.splitlines()]
    if len(value) > MAX_ACTIONABLE_FAILURE_CHARS:
        lines.append("    …[truncated for summary]")
    return lines


def render_repair_evidence_summary(
    summary: ReviewMergeEvidenceSummary,
    *,
    ci_recovery: CIEvidenceRecoveryPlan | None = None,
    aggregate_failure: AggregateFailureEvidence | None = None,
    post_repair_validation: tuple[str, ...] | list[str] = (),
) -> str:
    """Render existing #1540 summary plus bounded canonical repair evidence.

    `CIEvidenceRecoveryPlan.next_path` is presented only as a diagnostic routing
    fact. No repair command or next action is inferred from it.
    """
    if type(summary) is not ReviewMergeEvidenceSummary:
        raise EvidenceValidationError("summary must be ReviewMergeEvidenceSummary")
    if ci_recovery is not None and type(ci_recovery) is not CIEvidenceRecoveryPlan:
        raise EvidenceValidationError("ci_recovery must be CIEvidenceRecoveryPlan when supplied")
    if aggregate_failure is not None and type(aggregate_failure) is not AggregateFailureEvidence:
        raise EvidenceValidationError("aggregate_failure must be AggregateFailureEvidence when supplied")

    _non_authorizing_summary(summary)
    head = summary.source_head_sha
    validation = _bounded_items(post_repair_validation, "post_repair_validation")

    lines = [render_review_merge_evidence_summary(summary)]
    repair_lines: list[str] = []

    if ci_recovery is not None:
        identity = ci_recovery.identity
        if (
            identity.repository != summary.repository
            or identity.pr_number != summary.pr_number
            or identity.head_sha != head
            or ci_recovery.current_head_sha != head
        ):
            raise EvidenceValidationError("CI recovery evidence is not current for the summary identity")
        if ci_recovery.evidence_usable_for_attribution and ci_recovery.actionable_failure:
            repair_lines.append("- actionable failure (sanitized canonical evidence):")
            repair_lines.extend(_actionable_lines(ci_recovery.actionable_failure))
        if ci_recovery.next_path is not None:
            repair_lines.append(f"- next diagnostic route: {ci_recovery.next_path}")
        if ci_recovery.reason_codes:
            repair_lines.append("- diagnostic reason codes: " + ", ".join(ci_recovery.reason_codes))

    if aggregate_failure is not None:
        _non_authorizing_aggregate(aggregate_failure)
        if aggregate_failure.current_head_sha != head:
            raise EvidenceValidationError("aggregate failure evidence is not current for the summary head")
        tested_sha = summary.aggregate_validation.tested_sha
        if tested_sha is not None and aggregate_failure.tested_sha != tested_sha:
            raise EvidenceValidationError("aggregate failure evidence does not match the aggregate tested SHA")
        repair_lines.extend(
            (
                f"- aggregate provenance: {aggregate_failure.provenance.value}",
                "- blocking PR failure: " + ("yes" if aggregate_failure.blocking_pr_failure else "no"),
                "- aggregate manual review required: " + ("yes" if aggregate_failure.requires_manual_review else "no"),
            )
        )

    if validation:
        visible = validation[:MAX_POST_REPAIR_VALIDATION_ITEMS]
        value = ", ".join(visible)
        hidden = len(validation) - len(visible)
        if hidden:
            value += f" (+{hidden} more)"
        repair_lines.append(f"- post-repair validation: {value}")

    if repair_lines:
        lines.extend(("", "### Repair evidence", *repair_lines))
        lines.append(
            "Routing and evidence facts only. They do not authorize or prescribe a repair, execution, readiness, merge, closure, production, or external write."
        )

    rendered = "\n".join(lines)
    if len(rendered) > MAX_RENDERED_SUMMARY_CHARS:
        raise EvidenceValidationError("rendered repair evidence summary exceeds the bounded mobile projection")
    return rendered
