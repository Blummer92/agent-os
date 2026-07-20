from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Literal

PROVISIONAL_SCHEMA_VERSION = "0.1.0"


class SprintMode(str, Enum):
    IMPLEMENTATION = "implementation"
    PLANNING_ONLY = "planning-only"
    REVIEW = "review"
    BLOCKED = "blocked"


class Compatibility(str, Enum):
    COMPATIBLE = "compatible"
    SEQUENTIAL_ONLY = "sequential-only"
    UNKNOWN = "unknown"
    REJECTED = "rejected"


class RiskCategory(str, Enum):
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    DEPENDENCY = "dependency"
    VALIDATION = "validation"
    COMPUTE = "compute"
    DOCUMENTATION = "documentation"
    GOVERNANCE = "governance"
    SECURITY = "security"
    TECHNICAL_DEBT = "technical-debt"


class RiskSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskStatus(str, Enum):
    NEW = "new"
    ACTIVE = "active"
    MITIGATED = "mitigated"
    BLOCKED = "blocked"
    CLOSED = "closed"


class RecommendationAction(str, Enum):
    UPDATE_EXISTING_ISSUE = "update-existing-issue"
    UPDATE_ROADMAP = "update-roadmap"
    CREATE_ADR = "create-adr"
    CREATE_NEW_ISSUE = "create-new-issue"
    CLOSE_OR_MERGE_DUPLICATE = "close-or-merge-duplicate"
    NEEDS_DECISION = "needs-decision"
    NO_ACTION = "no-action"


@dataclass(frozen=True)
class RiskEvidence:
    risk_id: str
    summary: str
    category: RiskCategory
    severity: RiskSeverity
    status: RiskStatus
    owner: str
    affected_refs: tuple[str, ...]
    recommended_action: RecommendationAction
    due_phase: str
    evidence_refs: tuple[str, ...] = ()
    previous_severity: RiskSeverity | None = None
    previous_status: RiskStatus | None = None

    def __post_init__(self) -> None:
        if not self.risk_id.strip():
            raise ValueError("risk_id is required")
        if not self.summary.strip():
            raise ValueError("risk summary is required")
        if not self.owner.strip():
            raise ValueError("risk owner is required")
        if not self.affected_refs:
            raise ValueError("risk must affect at least one issue, roadmap item, or ADR")
        if not self.due_phase.strip():
            raise ValueError("risk due_phase is required")
        object.__setattr__(
            self, "affected_refs", tuple(sorted(set(self.affected_refs)))
        )
        object.__setattr__(
            self, "evidence_refs", tuple(sorted(set(self.evidence_refs)))
        )


@dataclass(frozen=True)
class SprintLaneEvidence:
    issue: int
    title: str
    mode: SprintMode
    compatibility: Compatibility
    reason_codes: tuple[str, ...] = ()
    pull_request: int | None = None
    files_changed: tuple[str, ...] = ()
    tests_run: tuple[str, ...] = ()
    docs_updated: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    risks: tuple[RiskEvidence, ...] = ()

    def __post_init__(self) -> None:
        if self.issue <= 0:
            raise ValueError("issue must be positive")
        if not self.title.strip():
            raise ValueError("lane title is required")
        object.__setattr__(
            self, "reason_codes", tuple(sorted(set(self.reason_codes)))
        )
        object.__setattr__(
            self, "files_changed", tuple(sorted(set(self.files_changed)))
        )
        object.__setattr__(self, "tests_run", tuple(sorted(set(self.tests_run))))
        object.__setattr__(
            self, "docs_updated", tuple(sorted(set(self.docs_updated)))
        )
        object.__setattr__(self, "blockers", tuple(sorted(set(self.blockers))))
        ordered_risks = tuple(sorted(self.risks, key=lambda risk: risk.risk_id))
        if len({risk.risk_id for risk in ordered_risks}) != len(ordered_risks):
            raise ValueError("risk ids must be unique within a lane")
        object.__setattr__(self, "risks", ordered_risks)


@dataclass(frozen=True)
class SuppliedSprintEvidence:
    sprint_goal: str
    evaluated_at: str
    source_ids: tuple[str, ...]
    freshness: Literal["current", "stale", "incomplete", "conflicting"]
    lanes: tuple[SprintLaneEvidence, ...]
    cloud_build_runs: int | None = None
    builds_avoided: int | None = None
    schema_version: str = PROVISIONAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.sprint_goal.strip():
            raise ValueError("sprint_goal is required")
        if not self.evaluated_at.strip():
            raise ValueError("evaluated_at is required")
        if self.schema_version != PROVISIONAL_SCHEMA_VERSION:
            raise ValueError("unsupported provisional sprint schema version")
        if not 1 <= len(self.lanes) <= 3:
            raise ValueError("a sprint must contain one to three lanes")
        issue_ids = [lane.issue for lane in self.lanes]
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("lane issue numbers must be unique")
        all_risk_ids = [
            risk.risk_id for lane in self.lanes for risk in lane.risks
        ]
        if len(all_risk_ids) != len(set(all_risk_ids)):
            raise ValueError("risk ids must be unique across the sprint")
        if self.cloud_build_runs is not None and self.cloud_build_runs < 0:
            raise ValueError("cloud_build_runs cannot be negative")
        if self.builds_avoided is not None and self.builds_avoided < 0:
            raise ValueError("builds_avoided cannot be negative")
        object.__setattr__(self, "source_ids", tuple(sorted(set(self.source_ids))))
        object.__setattr__(
            self, "lanes", tuple(sorted(self.lanes, key=lambda lane: lane.issue))
        )


def _status(evidence: SuppliedSprintEvidence) -> str:
    if evidence.freshness != "current":
        return "review"
    if all(lane.mode is SprintMode.BLOCKED for lane in evidence.lanes):
        return "blocked"
    if any(lane.pull_request is not None for lane in evidence.lanes):
        return "active"
    return "planned"


def _fmt_metric(value: int | None) -> str:
    return "unknown" if value is None else str(value)


def _all_risks(evidence: SuppliedSprintEvidence) -> tuple[RiskEvidence, ...]:
    return tuple(
        sorted(
            (risk for lane in evidence.lanes for risk in lane.risks),
            key=lambda risk: risk.risk_id,
        )
    )


def render_execution_prompt(repository: str, evidence: SuppliedSprintEvidence) -> str:
    issue_list = ", ".join(f"#{lane.issue}" for lane in evidence.lanes)
    return (
        "@GitHub\n\n"
        "Use high thinking. Do not use deep research.\n\n"
        f"Repository: {repository}\n"
        f"Work on {issue_list} as one coordinated sprint using their current GitHub scopes. "
        "Use separate branches and draft PRs for implementation, preserve planning-only lanes, "
        "avoid overlapping files, minimize Cloud Build usage, track risks and dependencies, "
        "finish with one Sprint Dashboard, and do not merge."
    )


def render_risk_review_prompt(repository: str, evidence: SuppliedSprintEvidence) -> str:
    issue_list = ", ".join(f"#{lane.issue}" for lane in evidence.lanes)
    return (
        "@GitHub\n\n"
        "Use high thinking. Do not use deep research.\n\n"
        f"Repository: {repository}\n"
        f"Review sprint work for {issue_list}. Inspect PRs, tests, validation, file overlap, risks, "
        "and dependency changes. Update related existing issues when scope or acceptance criteria "
        "are stale; create new issues only for distinct work. Do not implement code. Finish with "
        "an updated Sprint Dashboard and the next three compatible issues."
    )


def recommended_merge_order(
    lanes: Iterable[SprintLaneEvidence],
) -> tuple[int, ...]:
    rank = {
        SprintMode.PLANNING_ONLY: 0,
        SprintMode.REVIEW: 1,
        SprintMode.IMPLEMENTATION: 2,
        SprintMode.BLOCKED: 3,
    }
    return tuple(
        lane.issue
        for lane in sorted(lanes, key=lambda lane: (rank[lane.mode], lane.issue))
    )


def risk_delta(evidence: SuppliedSprintEvidence) -> dict[str, int]:
    result = {
        "new": 0,
        "mitigated": 0,
        "closed": 0,
        "severity-increased": 0,
        "severity-decreased": 0,
        "unowned": 0,
    }
    severity_rank = {
        RiskSeverity.LOW: 0,
        RiskSeverity.MEDIUM: 1,
        RiskSeverity.HIGH: 2,
        RiskSeverity.CRITICAL: 3,
    }
    for risk in _all_risks(evidence):
        if risk.status is RiskStatus.NEW:
            result["new"] += 1
        if risk.status is RiskStatus.MITIGATED:
            result["mitigated"] += 1
        if risk.status is RiskStatus.CLOSED:
            result["closed"] += 1
        if not risk.owner.strip():
            result["unowned"] += 1
        if risk.previous_severity is not None:
            current = severity_rank[risk.severity]
            previous = severity_rank[risk.previous_severity]
            if current > previous:
                result["severity-increased"] += 1
            elif current < previous:
                result["severity-decreased"] += 1
    return result


def render_sprint_dashboard(repository: str, evidence: SuppliedSprintEvidence) -> str:
    lines = [
        f"# Sprint Dashboard — {evidence.sprint_goal}",
        "",
        f"- Repository: `{repository}`",
        "- Mode: `supplied-evidence`",
        f"- Schema: `{evidence.schema_version}` (provisional)",
        f"- Sprint state: `{_status(evidence)}`",
        f"- Evaluated at: `{evidence.evaluated_at}`",
        f"- Freshness: `{evidence.freshness}`",
        f"- Sources: {', '.join(f'`{source}`' for source in evidence.source_ids) or 'none supplied'}",
        f"- Cloud Build runs: `{_fmt_metric(evidence.cloud_build_runs)}`",
        f"- Builds avoided: `{_fmt_metric(evidence.builds_avoided)}`",
        "",
        "| Lane | Issue | Mode | Compatibility | PR | Reasons |",
        "|---|---:|---|---|---:|---|",
    ]
    for index, lane in enumerate(evidence.lanes, start=1):
        reasons = ", ".join(lane.reason_codes) or "none"
        pr = str(lane.pull_request) if lane.pull_request is not None else "—"
        lines.append(
            f"| {index} | #{lane.issue} | {lane.mode.value} | "
            f"{lane.compatibility.value} | {pr} | {reasons} |"
        )

    risks = _all_risks(evidence)
    lines.extend(
        [
            "",
            "## Risk register",
            "",
            "| Risk | Severity | Status | Affects | Owner | Action | Due |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for risk in risks:
        affected = ", ".join(risk.affected_refs)
        lines.append(
            f"| {risk.risk_id}: {risk.summary} | {risk.severity.value} | "
            f"{risk.status.value} | {affected} | {risk.owner} | "
            f"{risk.recommended_action.value} | {risk.due_phase} |"
        )
    if not risks:
        lines.append("| none | — | — | — | — | no-action | — |")

    delta = risk_delta(evidence)
    lines.extend(
        [
            "",
            "## Risk delta",
            "",
            "| Change | Count |",
            "|---|---:|",
            *(f"| {name} | {count} |" for name, count in delta.items()),
            "",
            "## Recommended GitHub changes",
        ]
    )
    for risk in risks:
        refs = ", ".join(risk.affected_refs)
        lines.append(
            f"- `{risk.recommended_action.value}` for {refs}: {risk.summary}"
        )
    if not risks:
        lines.append("- `no-action`: no risks recorded")

    blockers = sorted({item for lane in evidence.lanes for item in lane.blockers})
    order = " → ".join(
        f"#{issue}" for issue in recommended_merge_order(evidence.lanes)
    )
    lines.extend(
        [
            "",
            f"## Recommended merge order\n\n{order}",
            "",
            "## Blockers",
            *(f"- {item}" for item in blockers),
            *(["- none recorded"] if not blockers else []),
        ]
    )
    if evidence.freshness != "current":
        lines.extend(
            [
                "",
                "> Warning: this dashboard is based on non-current supplied evidence and requires manual review.",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
