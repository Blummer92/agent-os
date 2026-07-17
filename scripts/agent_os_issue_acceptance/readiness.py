from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .models import AcceptanceReport, CheckResult, Status, strongest_status
from .parse_issue import parse_issue_metadata


class ReadinessOutcome(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs-decision"


@dataclass(frozen=True)
class ReadinessResult:
    outcome: ReadinessOutcome
    report: AcceptanceReport


_TIER_REQUIRED_SECTIONS = {
    0: ("objective", "owner", "allowed", "validation", "completion"),
    1: (
        "objective",
        "owner",
        "scope",
        "non-goals",
        "allowed",
        "validation",
        "documentation",
        "dependencies",
        "acceptance criteria",
        "definition of done",
    ),
    2: (
        "objective",
        "owner",
        "scope",
        "non-goals",
        "allowed",
        "validation",
        "documentation",
        "dependencies",
        "acceptance criteria",
        "definition of done",
        "authorization",
        "source of truth",
        "external",
        "rollback",
        "approval",
        "stop conditions",
    ),
}


def evaluate_issue_readiness(
    issue_body: str,
    *,
    dependency_blocked: bool = False,
    validation_pending: bool = False,
) -> ReadinessResult:
    """Evaluate one issue locally without network calls or metadata writes."""
    body = issue_body or ""
    metadata = parse_issue_metadata(body)
    tier = _parse_tier(body, metadata.raw.get("tier") if metadata.present else None)

    checks: list[CheckResult] = []
    blockers: list[str] = []
    manual_review_items: list[str] = []

    if tier is None:
        checks.append(CheckResult("issue tier", Status.MANUAL_REVIEW, "Issue tier is missing or invalid."))
        manual_review_items.append("Choose Tier 0, Tier 1, or Tier 2.")
    else:
        checks.append(CheckResult("issue tier", Status.PASS, f"Detected Tier {tier}."))
        missing = [name for name in _TIER_REQUIRED_SECTIONS[tier] if not _contains_field(body, name)]
        if missing:
            checks.append(
                CheckResult(
                    "required issue fields",
                    Status.FAIL,
                    "Required fields are missing for the selected tier.",
                    [f"missing={name}" for name in missing],
                )
            )
            blockers.extend(f"Missing required field: {name}." for name in missing)
        else:
            checks.append(CheckResult("required issue fields", Status.PASS, "Required tier fields are present."))

    if metadata.present and metadata.manual_review:
        checks.append(
            CheckResult(
                "declared decisions",
                Status.MANUAL_REVIEW,
                "The issue declares items requiring human judgment.",
                metadata.manual_review,
            )
        )
        manual_review_items.extend(metadata.manual_review)

    if _contains_needs_decision(body):
        checks.append(
            CheckResult(
                "unresolved decisions",
                Status.MANUAL_REVIEW,
                "The issue contains unresolved needs-decision values.",
            )
        )
        manual_review_items.append("Resolve all needs-decision fields.")

    if dependency_blocked or _declares_blocked_dependency(body):
        checks.append(CheckResult("dependencies", Status.FAIL, "A required dependency is blocked."))
        blockers.append("A required dependency is blocked.")

    if validation_pending:
        checks.append(CheckResult("required validation", Status.FAIL, "Required validation is pending."))
        blockers.append("Required validation is pending.")

    if not checks:
        checks.append(CheckResult("issue readiness", Status.MANUAL_REVIEW, "No readiness evidence was available."))

    overall = strongest_status(checks)
    outcome = _map_outcome(overall)
    report = AcceptanceReport(
        linked_issue=None,
        overall_status=overall,
        checks=checks,
        manual_review_items=manual_review_items,
        blockers=blockers,
        evidence=[f"readiness_outcome={outcome.value}"],
        remaining_risks=["A ready result is evidence only and does not authorize implementation or merge."],
    )
    return ReadinessResult(outcome=outcome, report=report)


def _map_outcome(status: Status) -> ReadinessOutcome:
    if status == Status.FAIL:
        return ReadinessOutcome.BLOCKED
    if status == Status.MANUAL_REVIEW:
        return ReadinessOutcome.NEEDS_DECISION
    return ReadinessOutcome.READY


def _parse_tier(body: str, metadata_tier: object) -> int | None:
    values = [metadata_tier]
    match = re.search(r"(?im)^\s*(?:issue\s+)?tier\s*[:|-]\s*(?:tier:)?\s*([012])\b", body)
    if match:
        values.append(match.group(1))
    match = re.search(r"(?im)\btier:([012])(?:-|\b)", body)
    if match:
        values.append(match.group(1))
    for value in values:
        try:
            tier = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if tier in _TIER_REQUIRED_SECTIONS:
            return tier
    return None


def _contains_field(body: str, name: str) -> bool:
    aliases = {
        "allowed": ("allowed", "likely files", "files", "areas", "governed surfaces"),
        "validation": ("validation", "tests"),
        "documentation": ("documentation", "docs"),
        "completion": ("completion", "definition of done"),
        "source of truth": ("source of truth", "canonical surface"),
        "external": ("external write", "external surface"),
        "approval": ("approval", "human approval"),
    }
    terms = aliases.get(name, (name,))
    lowered = body.lower()
    return any(term in lowered for term in terms)


def _contains_needs_decision(body: str) -> bool:
    return bool(re.search(r"(?i)\bneeds[- ]decision\b", body))


def _declares_blocked_dependency(body: str) -> bool:
    return bool(re.search(r"(?im)^\s*(?:blocked by|blockers?)\s*:\s*(?!none\b).+", body))
