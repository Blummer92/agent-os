from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable, Literal

SCHEMA_VERSION = "0.1.0"
PROVISIONAL_SCHEMA_VERSION = SCHEMA_VERSION
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


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
class SourceEvidence:
    object_type: Literal["issue", "pull-request", "check", "file-list"]
    object_id: str
    repository: str
    retrieved_at: str
    updated_at: str | None
    result_status: str
    permission_status: str
    pagination_status: str
    evidence_digest: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "object_id",
            "repository",
            "result_status",
            "permission_status",
            "pagination_status",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"source {name} is required")
        _require_timestamp(self.retrieved_at, "source retrieved_at")
        if self.updated_at is not None:
            _require_timestamp(self.updated_at, "source updated_at")


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
        if (
            self.owner == "needs-decision"
            and self.recommended_action is not RecommendationAction.NEEDS_DECISION
        ):
            raise ValueError("needs-decision owner requires needs-decision action")
        object.__setattr__(
            self, "affected_refs", tuple(sorted(set(self.affected_refs)))
        )
        object.__setattr__(
            self, "evidence_refs", tuple(sorted(set(self.evidence_refs)))
        )


@dataclass(frozen=True)
class DecisionEvidence:
    decision_id: str
    summary: str
    rationale: str
    affected_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.decision_id.strip() or not self.summary.strip():
            raise ValueError("decision id and summary are required")
        if not self.rationale.strip() or not self.affected_refs:
            raise ValueError("decision rationale and affected references are required")
        object.__setattr__(
            self, "affected_refs", tuple(sorted(set(self.affected_refs)))
        )


@dataclass(frozen=True)
class RecommendationEvidence:
    recommendation_id: str
    action: RecommendationAction
    targets: tuple[str, ...]
    rationale: str
    risk_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.recommendation_id.strip():
            raise ValueError("recommendation_id is required")
        if not self.targets or not self.rationale.strip():
            raise ValueError("recommendation targets and rationale are required")
        object.__setattr__(self, "targets", tuple(sorted(set(self.targets))))
        object.__setattr__(self, "risk_ids", tuple(sorted(set(self.risk_ids))))


@dataclass(frozen=True)
class ValidationEvidence:
    tests_run: tuple[str, ...]
    docs_updated: tuple[str, ...]
    repository_validation: Literal["passed", "failed", "pending", "unknown"]
    status_checks: Literal["passed", "failed", "pending", "unknown", "not-posted"]
    cloud_build_runs: int | None
    builds_avoided: int | None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.cloud_build_runs is not None and self.cloud_build_runs < 0:
            raise ValueError("cloud_build_runs cannot be negative")
        if self.builds_avoided is not None and self.builds_avoided < 0:
            raise ValueError("builds_avoided cannot be negative")
        object.__setattr__(self, "tests_run", tuple(sorted(set(self.tests_run))))
        object.__setattr__(
            self, "docs_updated", tuple(sorted(set(self.docs_updated)))
        )
        object.__setattr__(
            self, "evidence_refs", tuple(sorted(set(self.evidence_refs)))
        )


@dataclass(frozen=True)
class FinalHandoff:
    files_changed: tuple[str, ...]
    tests_run: tuple[str, ...]
    docs_updated: tuple[str, ...]
    unresolved_blockers: tuple[str, ...]
    handoff_recommendations: tuple[str, ...]
    remaining_risks: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(
                self, name, tuple(sorted(set(getattr(self, name))))
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
    risk_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.issue <= 0:
            raise ValueError("issue must be positive")
        if not self.title.strip():
            raise ValueError("lane title is required")
        if self.pull_request is not None and self.pull_request <= 0:
            raise ValueError("pull_request must be positive")
        for name in (
            "reason_codes",
            "files_changed",
            "tests_run",
            "docs_updated",
            "blockers",
            "risk_ids",
        ):
            object.__setattr__(
                self, name, tuple(sorted(set(getattr(self, name))))
            )


@dataclass(frozen=True)
class SuppliedSprintEvidence:
    sprint_id: str
    sprint_goal: str
    sprint_state: Literal["planned", "active", "review", "blocked", "complete"]
    evidence_mode: Literal["supplied-evidence", "connected-read-only"]
    evaluated_at: str
    freshness: Literal["current", "stale", "incomplete", "conflicting"]
    sources: tuple[SourceEvidence, ...]
    lanes: tuple[SprintLaneEvidence, ...]
    risks: tuple[RiskEvidence, ...]
    decisions: tuple[DecisionEvidence, ...]
    recommendations: tuple[RecommendationEvidence, ...]
    validation: ValidationEvidence
    final_handoff: FinalHandoff
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported sprint schema version")
        if not self.sprint_id.strip() or not self.sprint_goal.strip():
            raise ValueError("sprint_id and sprint_goal are required")
        _require_timestamp(self.evaluated_at, "evaluated_at")
        if not 1 <= len(self.lanes) <= 3:
            raise ValueError("a sprint must contain one to three lanes")
        if self.evidence_mode == "connected-read-only" and not self.sources:
            raise ValueError("connected-read-only mode requires sources")
        if self.freshness != "current":
            all_blocked = all(lane.mode is SprintMode.BLOCKED for lane in self.lanes)
            expected = "blocked" if all_blocked else "review"
            if self.sprint_state != expected:
                raise ValueError("non-current evidence requires review or blocked state")

        _require_unique((lane.issue for lane in self.lanes), "lane issue numbers")
        _require_unique((risk.risk_id for risk in self.risks), "risk ids")
        _require_unique(
            (decision.decision_id for decision in self.decisions), "decision ids"
        )
        _require_unique(
            (item.recommendation_id for item in self.recommendations),
            "recommendation ids",
        )

        risk_ids = {risk.risk_id for risk in self.risks}
        referenced_risks = {
            risk_id for lane in self.lanes for risk_id in lane.risk_ids
        }
        if not referenced_risks <= risk_ids:
            raise ValueError("lane risk ids must resolve to top-level risks")
        recommendation_risks = {
            risk_id
            for recommendation in self.recommendations
            for risk_id in recommendation.risk_ids
        }
        if not recommendation_risks <= risk_ids:
            raise ValueError("recommendation risk ids must resolve to top-level risks")

        object.__setattr__(
            self,
            "sources",
            tuple(
                sorted(
                    self.sources,
                    key=lambda source: (
                        source.repository,
                        source.object_type,
                        source.object_id,
                    ),
                )
            ),
        )
        object.__setattr__(
            self, "lanes", tuple(sorted(self.lanes, key=lambda lane: lane.issue))
        )
        object.__setattr__(
            self, "risks", tuple(sorted(self.risks, key=lambda risk: risk.risk_id))
        )
        object.__setattr__(
            self,
            "decisions",
            tuple(sorted(self.decisions, key=lambda item: item.decision_id)),
        )
        object.__setattr__(
            self,
            "recommendations",
            tuple(
                sorted(
                    self.recommendations,
                    key=lambda item: item.recommendation_id,
                )
            ),
        )


def _require_timestamp(value: str, name: str) -> None:
    if not _TIMESTAMP_RE.fullmatch(value):
        raise ValueError(f"{name} must be RFC3339 UTC")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{name} must be RFC3339 UTC") from exc


def _require_unique(values: Iterable[object], name: str) -> None:
    collected = tuple(values)
    if len(collected) != len(set(collected)):
        raise ValueError(f"{name} must be unique")


def _enum_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_enum_value(item) for item in value]
    if isinstance(value, list):
        return [_enum_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _enum_value(item) for key, item in value.items()}
    return value


def canonical_sprint_payload(evidence: SuppliedSprintEvidence) -> dict[str, object]:
    if not isinstance(evidence, SuppliedSprintEvidence):
        raise TypeError("evidence must be SuppliedSprintEvidence")
    payload = _enum_value(asdict(evidence))
    assert isinstance(payload, dict)
    payload["risk_delta"] = risk_delta(evidence)
    return payload


def serialize_sprint_evidence(evidence: SuppliedSprintEvidence) -> bytes:
    return json.dumps(
        canonical_sprint_payload(evidence),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


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
        "and dependency changes. Update existing issues or the roadmap when scope is stale; create "
        "new issues only for distinct work. Do not implement code. Finish with an updated Sprint "
        "Dashboard and the next three compatible issues."
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
    for risk in evidence.risks:
        if risk.previous_status is None and risk.status in {
            RiskStatus.NEW,
            RiskStatus.ACTIVE,
            RiskStatus.BLOCKED,
        }:
            result["new"] += 1
        if (
            risk.status is RiskStatus.MITIGATED
            and risk.previous_status not in {RiskStatus.MITIGATED, RiskStatus.CLOSED}
        ):
            result["mitigated"] += 1
        if risk.status is RiskStatus.CLOSED and risk.previous_status is not RiskStatus.CLOSED:
            result["closed"] += 1
        if risk.owner == "needs-decision":
            result["unowned"] += 1
        if risk.previous_severity is not None:
            current = severity_rank[risk.severity]
            previous = severity_rank[risk.previous_severity]
            if current > previous:
                result["severity-increased"] += 1
            elif current < previous:
                result["severity-decreased"] += 1
    return result


def _fmt_metric(value: int | None) -> str:
    return "unknown" if value is None else str(value)


def _join_or_unknown(values: Iterable[str]) -> str:
    collected = tuple(values)
    return ", ".join(collected) if collected else "unknown"


def _issue_impact(evidence: SuppliedSprintEvidence) -> tuple[tuple[object, ...], ...]:
    rows = []
    for lane in evidence.lanes:
        ref = f"issue:#{lane.issue}"
        related = [risk for risk in evidence.risks if ref in risk.affected_refs]
        active = sum(
            risk.status in {RiskStatus.NEW, RiskStatus.ACTIVE, RiskStatus.BLOCKED}
            for risk in related
        )
        closed = sum(risk.status is RiskStatus.CLOSED for risk in related)
        actions = {
            item.action.value
            for item in evidence.recommendations
            if ref in item.targets
        }
        rows.append(
            (
                lane.issue,
                active,
                closed,
                "yes" if RecommendationAction.UPDATE_EXISTING_ISSUE.value in actions else "no",
                "yes" if RecommendationAction.UPDATE_ROADMAP.value in actions else "no",
                "yes" if RecommendationAction.CREATE_NEW_ISSUE.value in actions else "no",
            )
        )
    return tuple(rows)


def render_sprint_dashboard(repository: str, evidence: SuppliedSprintEvidence) -> str:
    source_ids = (
        f"{source.object_type}:{source.object_id}" for source in evidence.sources
    )
    lines = [
        f"# Sprint Dashboard — {evidence.sprint_goal}",
        "",
        f"- Repository: `{repository}`",
        f"- Sprint ID: `{evidence.sprint_id}`",
        f"- Mode: `{evidence.evidence_mode}`",
        f"- Schema: `{evidence.schema_version}`",
        f"- Sprint state: `{evidence.sprint_state}`",
        f"- Evaluated at: `{evidence.evaluated_at}`",
        f"- Freshness: `{evidence.freshness}`",
        f"- Sources: {_join_or_unknown(source_ids)}",
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

    lines.extend(
        [
            "",
            "## Risk register",
            "",
            "| Risk | Severity | Status | Affects | Owner | Action | Due |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for risk in evidence.risks:
        lines.append(
            f"| {risk.risk_id}: {risk.summary} | {risk.severity.value} | "
            f"{risk.status.value} | {', '.join(risk.affected_refs)} | {risk.owner} | "
            f"{risk.recommended_action.value} | {risk.due_phase} |"
        )
    if not evidence.risks:
        lines.append("| none | — | — | — | — | no-action | — |")

    delta = risk_delta(evidence)
    lines.extend(
        [
            "",
            "## Risk Delta",
            "",
            "| Change | Count |",
            "|---|---:|",
            *(f"| {name} | {count} |" for name, count in delta.items()),
            "",
            "## Issue impact",
            "",
            "| Issue | Active risks | Closed risks | Update issue | Roadmap update | New issue |",
            "|---:|---:|---:|---|---|---|",
        ]
    )
    for issue, active, closed, update, roadmap, new_issue in _issue_impact(evidence):
        lines.append(
            f"| #{issue} | {active} | {closed} | {update} | {roadmap} | {new_issue} |"
        )

    lines.extend(["", "## Recommended GitHub changes"])
    for recommendation in evidence.recommendations:
        lines.append(
            f"- `{recommendation.action.value}` for {', '.join(recommendation.targets)}: "
            f"{recommendation.rationale}"
        )
    if not evidence.recommendations:
        lines.append("- `no-action`: no changes recommended")

    lines.extend(
        [
            "",
            "## Validation",
            f"- Repository validation: `{evidence.validation.repository_validation}`",
            f"- Status checks: `{evidence.validation.status_checks}`",
            f"- Cloud Build runs: `{_fmt_metric(evidence.validation.cloud_build_runs)}`",
            f"- Builds avoided: `{_fmt_metric(evidence.validation.builds_avoided)}`",
            f"- Tests: {_join_or_unknown(evidence.validation.tests_run)}",
            "",
            "## Recommended merge order",
            "",
            " → ".join(
                f"#{issue}" for issue in recommended_merge_order(evidence.lanes)
            ),
            "",
            "## Blockers",
        ]
    )
    blockers = sorted({item for lane in evidence.lanes for item in lane.blockers})
    lines.extend(f"- {item}" for item in blockers)
    if not blockers:
        lines.append("- none recorded")
    if evidence.freshness != "current":
        lines.extend(
            [
                "",
                "> Warning: non-current evidence requires manual review.",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_sprint_governance_report(
    repository: str, evidence: SuppliedSprintEvidence
) -> str:
    lines = [
        render_sprint_dashboard(repository, evidence).rstrip(),
        "",
        "# Sprint Governance Report",
        "",
        "## Decision log",
    ]
    for decision in evidence.decisions:
        lines.append(
            f"- `{decision.decision_id}` {decision.summary} — {decision.rationale} "
            f"({', '.join(decision.affected_refs)})"
        )
    if not evidence.decisions:
        lines.append("- none recorded")

    lines.extend(["", "## Provenance"])
    for source in evidence.sources:
        updated = source.updated_at or "unavailable"
        lines.append(
            f"- `{source.object_type}:{source.object_id}` retrieved {source.retrieved_at}; "
            f"updated {updated}; result `{source.result_status}`; permission "
            f"`{source.permission_status}`; pagination `{source.pagination_status}`"
        )
    if not evidence.sources:
        lines.append("- supplied evidence; no connected sources recorded")

    handoff = evidence.final_handoff
    lines.extend(
        [
            "",
            "## Final handoff",
            f"- Files changed: {_join_or_unknown(handoff.files_changed)}",
            f"- Tests run: {_join_or_unknown(handoff.tests_run)}",
            f"- Docs updated: {_join_or_unknown(handoff.docs_updated)}",
            f"- Unresolved blockers: {_join_or_unknown(handoff.unresolved_blockers)}",
            f"- Recommendations: {_join_or_unknown(handoff.handoff_recommendations)}",
            f"- Remaining risks: {_join_or_unknown(handoff.remaining_risks)}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
