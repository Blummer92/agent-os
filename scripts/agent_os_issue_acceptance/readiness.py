from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

import yaml

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
        "value",
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
        "value",
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
        "compatibility",
    ),
}

_FIELD_ALIASES = {
    "objective": ("objective", "objective and value"),
    "value": ("value", "objective and value"),
    "owner": ("owner", "owner routing", "owner and source of truth", "primary owner"),
    "scope": ("scope", "scope and non-goals"),
    "non-goals": ("non-goals", "scope and non-goals"),
    "allowed": (
        "allowed files",
        "allowed files or areas",
        "allowed files, areas, or governed surfaces",
        "allowed and protected areas",
    ),
    "validation": (
        "validation",
        "required tests or validation",
        "required tests, validation, and documentation",
        "validation and documentation",
    ),
    "documentation": (
        "documentation",
        "required docs updates",
        "required tests, validation, and documentation",
        "validation and documentation",
    ),
    "dependencies": ("dependencies", "dependencies and blockers", "dependencies / blockers"),
    "acceptance criteria": ("acceptance criteria", "acceptance criteria and definition of done"),
    "definition of done": ("definition of done", "acceptance criteria and definition of done"),
    "completion": ("completion", "completion criterion", "definition of done", "acceptance criteria and definition of done"),
    "authorization": ("authorization", "tier 2 controls, when applicable"),
    "source of truth": ("source of truth", "owner and source of truth", "tier 2 controls, when applicable"),
    "external": ("external write boundary", "external write surface", "tier 2 controls, when applicable"),
    "rollback": ("rollback", "tier 2 controls, when applicable"),
    "approval": ("approval requirements", "human approval", "tier 2 controls, when applicable"),
    "stop conditions": ("stop conditions", "tier 2 controls, when applicable"),
    "compatibility": ("migration or compatibility planning", "compatibility", "tier 2 controls, when applicable"),
}

_FENCED_RE = re.compile(r"```.*?```", re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_METADATA_RE = re.compile(r"```(?:yaml|yml)\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$")


def evaluate_issue_readiness(
    issue_body: str,
    *,
    dependency_blocked: bool = False,
    validation_pending: bool = False,
) -> ReadinessResult:
    """Evaluate one issue locally without network calls or metadata writes."""
    body = issue_body or ""
    metadata = parse_issue_metadata(body)
    sections = _markdown_sections(body)
    tier = _parse_tier(body, metadata.raw.get("tier") if metadata.present else None)

    checks: list[CheckResult] = []
    blockers: list[str] = []
    manual_review_items: list[str] = []

    if _has_malformed_acceptance_metadata(body):
        checks.append(CheckResult("issue metadata", Status.MANUAL_REVIEW, "Acceptance metadata is malformed."))
        manual_review_items.append("Repair the agent_os_issue_acceptance YAML block.")

    if tier is None:
        checks.append(CheckResult("issue tier", Status.MANUAL_REVIEW, "Issue tier is missing or invalid."))
        manual_review_items.append("Choose Tier 0, Tier 1, or Tier 2.")
    else:
        checks.append(CheckResult("issue tier", Status.PASS, f"Detected Tier {tier}."))
        missing = [name for name in _TIER_REQUIRED_SECTIONS[tier] if not _contains_field(sections, name)]
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
        checks.append(CheckResult("unresolved decisions", Status.MANUAL_REVIEW, "The issue contains an unresolved decision value."))
        manual_review_items.append("Resolve all needs-decision fields.")

    if dependency_blocked or _declares_blocked_dependency(body):
        checks.append(CheckResult("dependencies", Status.FAIL, "A required dependency is blocked."))
        blockers.append("A required dependency is blocked.")

    if validation_pending:
        checks.append(CheckResult("required validation", Status.FAIL, "Required validation is pending."))
        blockers.append("Required validation is pending.")

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
    visible = _sanitize(body)
    for pattern in (
        r"(?im)^\s*(?:issue\s+)?tier\s*[:|-]\s*(?:tier:)?\s*([012])\b",
        r"(?im)^\s*tier:([012])(?:-|\b)",
    ):
        match = re.search(pattern, visible)
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


def _markdown_sections(body: str) -> dict[str, str]:
    visible = _sanitize(body)
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in visible.splitlines():
        if line.lstrip().startswith(">"):
            continue
        match = _HEADING_RE.match(line.strip())
        if match:
            current = _normalize(match.group(1))
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def _contains_field(sections: dict[str, str], name: str) -> bool:
    aliases = {_normalize(alias) for alias in _FIELD_ALIASES.get(name, (name,))}
    for heading, content in sections.items():
        if heading not in aliases:
            continue
        if not content or content == "_No response_":
            continue
        if heading == "tier 2 controls, when applicable" and name not in {"authorization", "source of truth", "external", "rollback", "approval", "stop conditions", "compatibility"}:
            continue
        if heading == "tier 2 controls, when applicable":
            return _contains_labeled_value(content, name)
        return True
    return False


def _contains_labeled_value(content: str, name: str) -> bool:
    labels = {
        "authorization": ("authorization",),
        "source of truth": ("source of truth", "canonical surface"),
        "external": ("external write", "external surface"),
        "rollback": ("rollback",),
        "approval": ("approval", "human approval"),
        "stop conditions": ("stop conditions",),
        "compatibility": ("compatibility", "migration"),
    }[name]
    return any(re.search(rf"(?im)^\s*(?:[-*]\s*)?{re.escape(label)}\s*:\s*\S.+$", content) for label in labels)


def _contains_needs_decision(body: str) -> bool:
    visible = _sanitize(body)
    return bool(
        re.search(
            r"(?im)^\s*(?:[-*]\s*)?(?:(?:owner|source of truth|external write boundary|authorization|readiness candidate)\s*:\s*)?(?:status:)?needs[- ]decision\s*$",
            visible,
        )
    )


def _declares_blocked_dependency(body: str) -> bool:
    visible = _sanitize(body)
    return bool(re.search(r"(?im)^\s*(?:blocked by|blockers?)\s*:\s*(?!none\b|not applicable\b).+", visible))


def _has_malformed_acceptance_metadata(body: str) -> bool:
    for match in _METADATA_RE.finditer(body):
        raw = match.group(1)
        if "agent_os_issue_acceptance" not in raw:
            continue
        try:
            parsed = yaml.safe_load(raw)
        except yaml.YAMLError:
            return True
        if not isinstance(parsed, dict) or not isinstance(parsed.get("agent_os_issue_acceptance"), dict):
            return True
    return False


def _sanitize(body: str) -> str:
    without_comments = _COMMENT_RE.sub("", body or "")
    return _FENCED_RE.sub("", without_comments)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())
