from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .path_contract import DeclaredPathError, normalize_declared_path
from .readiness import ReadinessOutcome, evaluate_issue_readiness

_APPROVED_IMPACTS = {
    "docs-required",
    "docs-not-required",
    "docs-needs-decision",
}
_CANONICAL_HEADINGS = {
    "documentation impact": "documentation_impact",
    "required documentation paths or bounded areas": "required_docs",
    "expected documentation change": "documentation_expected_change",
    "documentation exemption reason": "documentation_exemption_reason",
}
_FENCED_RE = re.compile(r"```.*?```", re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")


@dataclass(frozen=True)
class LegacyIssueSnapshot:
    number: int
    title: str
    state: str
    body: str
    labels: tuple[str, ...]
    updated_at: str | None = None
    open_pr_numbers: tuple[int, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "LegacyIssueSnapshot":
        number = value.get("number")
        if isinstance(number, bool) or not isinstance(number, int):
            raise ValueError("snapshot number must be an integer")
        labels = tuple(sorted({str(item) for item in value.get("labels", []) if str(item)}))
        prs = tuple(
            sorted(
                {
                    int(item)
                    for item in value.get("open_pr_numbers", [])
                    if isinstance(item, int) and not isinstance(item, bool)
                }
            )
        )
        return cls(
            number=number,
            title=str(value.get("title") or ""),
            state=str(value.get("state") or "open").lower(),
            body=str(value.get("body") or ""),
            labels=labels,
            updated_at=str(value["updated_at"]) if value.get("updated_at") else None,
            open_pr_numbers=prs,
        )


@dataclass(frozen=True)
class LegacyIssueAssessment:
    number: int
    classification: str
    status_label: str | None
    open_pr_numbers: tuple[int, ...]
    documentation_impact: str
    predicted_documentation_status: str
    predicted_transition: str
    reason_codes: tuple[str, ...]
    recommended_action: str
    updated_at: str | None


@dataclass(frozen=True)
class LegacyPreflightReport:
    assessments: tuple[LegacyIssueAssessment, ...]
    metrics: dict[str, int | float]
    evaluator_sha: str | None = None


def evaluate_legacy_preflight(payload: dict[str, Any] | list[dict[str, Any]]) -> LegacyPreflightReport:
    if isinstance(payload, dict):
        raw_issues = payload.get("issues", [])
        evaluator_sha = str(payload["evaluator_sha"]) if payload.get("evaluator_sha") else None
    elif isinstance(payload, list):
        raw_issues = payload
        evaluator_sha = None
    else:
        raise ValueError("preflight payload must be a list or an object containing issues")

    snapshots = _dedupe_snapshots(LegacyIssueSnapshot.from_mapping(item) for item in raw_issues)
    assessments = tuple(
        assessment
        for snapshot in snapshots
        if snapshot.state == "open"
        for assessment in (classify_legacy_issue(snapshot),)
    )
    implementation = tuple(item for item in assessments if item.classification != "tracker-or-roadmap")
    manual_review = sum(item.predicted_documentation_status == "manual-review" for item in implementation)
    denominator = len(implementation)
    metrics: dict[str, int | float] = {
        "open_implementation_candidates": denominator,
        "missing_documentation_impact": _count_reason(implementation, "legacy-metadata-missing"),
        "currently_ready_label_missing_contract": sum(
            item.status_label == "status:ready" and "legacy-metadata-missing" in item.reason_codes
            for item in implementation
        ),
        "open_pr_linked_issue_missing_contract": sum(
            bool(item.open_pr_numbers) and "legacy-metadata-missing" in item.reason_codes
            for item in implementation
        ),
        "already_blocked_missing_contract": sum(
            item.status_label == "status:blocked" and "legacy-metadata-missing" in item.reason_codes
            for item in implementation
        ),
        "would_change_ready_to_needs_decision": sum(
            item.predicted_transition == "ready->needs-decision" for item in implementation
        ),
        "unknown_or_conflicting_contract": sum(
            bool(
                {"documentation-impact-unknown", "documentation-source-conflict"}
                & set(item.reason_codes)
            )
            for item in implementation
        ),
        "duplicate_heading_candidates": _count_reason(
            implementation, "duplicate-documentation-heading"
        ),
        "manual_review_rate_estimate": 0.0 if denominator == 0 else manual_review / denominator,
    }
    return LegacyPreflightReport(
        assessments=tuple(sorted(assessments, key=lambda item: item.number)),
        metrics=metrics,
        evaluator_sha=evaluator_sha,
    )


def classify_legacy_issue(snapshot: LegacyIssueSnapshot) -> LegacyIssueAssessment:
    status_label = next((label for label in snapshot.labels if label.startswith("status:")), None)
    if _is_tracker_or_roadmap(snapshot):
        return LegacyIssueAssessment(
            number=snapshot.number,
            classification="tracker-or-roadmap",
            status_label=status_label,
            open_pr_numbers=snapshot.open_pr_numbers,
            documentation_impact="not-applicable",
            predicted_documentation_status="not-applicable",
            predicted_transition="not-applicable",
            reason_codes=("tracker-or-roadmap",),
            recommended_action="Exclude from implementation-metadata backfill.",
            updated_at=snapshot.updated_at,
        )

    evidence = _documentation_evidence(snapshot.body)
    doc_status, reasons = _predict_documentation_status(evidence)
    existing = evaluate_issue_readiness(
        snapshot.body,
        dependency_blocked=status_label == "status:blocked",
    ).outcome
    transition = _predict_transition(existing, doc_status)

    if not reasons and doc_status == "pass":
        classification = "already-compliant"
        reasons = ["documentation-impact-present"]
        action = "No preflight remediation required."
    elif snapshot.open_pr_numbers:
        classification = "open-pr-linked"
        reasons.append("open-pr-linked")
        action = "Review before the linked pull request proceeds."
    elif status_label == "status:blocked":
        classification = "blocked-dependency"
        reasons.append("already-blocked")
        action = "Defer metadata backfill until the dependency is unblocked."
    elif status_label == "status:ready":
        classification = "active-implementation"
        reasons.append("currently-labeled-ready")
        action = "Prioritize operator review before strict readiness composition."
    elif status_label in {"status:deferred", "status:backlog", "status:inactive"}:
        classification = "stale-or-inactive"
        action = "Defer until the issue becomes active."
    else:
        classification = "manual-owner-decision"
        reasons.append("ambiguous-manual-review")
        action = "Confirm ownership and implementation intent manually."

    return LegacyIssueAssessment(
        number=snapshot.number,
        classification=classification,
        status_label=status_label,
        open_pr_numbers=snapshot.open_pr_numbers,
        documentation_impact=evidence["impact"] or "missing",
        predicted_documentation_status=doc_status,
        predicted_transition=transition,
        reason_codes=tuple(sorted(set(reasons))),
        recommended_action=action,
        updated_at=snapshot.updated_at,
    )


def render_legacy_preflight(report: LegacyPreflightReport) -> str:
    lines = ["Legacy Documentation Readiness Preflight", ""]
    if report.evaluator_sha:
        lines.append(f"evaluator_sha={report.evaluator_sha}")
    for key in sorted(report.metrics):
        lines.append(f"{key}={report.metrics[key]}")
    lines.append("")
    for item in report.assessments:
        prs = ",".join(str(number) for number in item.open_pr_numbers) or "none"
        reasons = ",".join(item.reason_codes) or "none"
        lines.append(
            f"issue={item.number}; classification={item.classification}; "
            f"status_label={item.status_label or 'none'}; open_prs={prs}; "
            f"impact={item.documentation_impact}; doc_status={item.predicted_documentation_status}; "
            f"transition={item.predicted_transition}; reasons={reasons}"
        )
    return "\n".join(lines) + "\n"


def legacy_preflight_to_dict(report: LegacyPreflightReport) -> dict[str, Any]:
    return {
        "evaluator_sha": report.evaluator_sha,
        "metrics": report.metrics,
        "issues": [
            {
                "number": item.number,
                "classification": item.classification,
                "status_label": item.status_label,
                "open_pr_numbers": list(item.open_pr_numbers),
                "documentation_impact": item.documentation_impact,
                "predicted_documentation_status": item.predicted_documentation_status,
                "predicted_transition": item.predicted_transition,
                "reason_codes": list(item.reason_codes),
                "recommended_action": item.recommended_action,
                "updated_at": item.updated_at,
            }
            for item in report.assessments
        ],
    }


def _documentation_evidence(body: str) -> dict[str, Any]:
    visible = _sanitize(body)
    sections: dict[str, list[list[str]]] = {field: [] for field in _CANONICAL_HEADINGS.values()}
    current: str | None = None
    for raw_line in visible.splitlines():
        match = _HEADING_RE.match(raw_line)
        if match:
            current = _CANONICAL_HEADINGS.get(_normalize_heading(match.group(1)))
            if current:
                sections[current].append([])
            continue
        if current and sections[current]:
            sections[current][-1].append(raw_line)

    yaml_values = _yaml_documentation_values(body)
    reasons: list[str] = []
    for field, occurrences in sections.items():
        if len(occurrences) > 1:
            reasons.append("duplicate-documentation-heading")

    body_values = {
        field: [_clean_line(line) for occurrence in occurrences for line in occurrence]
        for field, occurrences in sections.items()
    }
    body_values = {
        field: [value for value in values if value and value != "_No response_"]
        for field, values in body_values.items()
    }

    impact, impact_conflict = _resolve_scalar(
        yaml_values.get("documentation_impact"), body_values["documentation_impact"]
    )
    paths, paths_conflict = _resolve_list(
        yaml_values.get("required_docs", []), body_values["required_docs"]
    )
    expected, expected_conflict = _resolve_scalar(
        yaml_values.get("documentation_expected_change"),
        body_values["documentation_expected_change"],
        collapse=True,
    )
    exemption, exemption_conflict = _resolve_scalar(
        yaml_values.get("documentation_exemption_reason"),
        body_values["documentation_exemption_reason"],
        collapse=True,
    )
    if any((impact_conflict, paths_conflict, expected_conflict, exemption_conflict)):
        reasons.append("documentation-source-conflict")

    return {
        "impact": impact,
        "paths": paths,
        "expected": expected,
        "exemption": exemption,
        "reasons": reasons,
    }


def _yaml_documentation_values(body: str) -> dict[str, Any]:
    from .parse_issue import parse_issue_metadata

    metadata = parse_issue_metadata(body)
    if not metadata.present:
        return {}
    return {
        "documentation_impact": metadata.documentation_impact,
        "required_docs": metadata.required_docs,
        "documentation_expected_change": metadata.documentation_expected_change,
        "documentation_exemption_reason": metadata.documentation_exemption_reason,
    }


def _predict_documentation_status(evidence: dict[str, Any]) -> tuple[str, list[str]]:
    reasons = list(evidence["reasons"])
    impact = evidence["impact"]
    if reasons:
        return "manual-review", reasons
    if not impact:
        return "manual-review", ["legacy-metadata-missing"]
    if impact not in _APPROVED_IMPACTS:
        return "manual-review", ["documentation-impact-unknown"]
    if impact == "docs-needs-decision":
        return "manual-review", ["documentation-needs-decision"]
    if impact == "docs-required":
        if not evidence["paths"]:
            return "fail", ["documentation-path-missing"]
        malformed = []
        for path in evidence["paths"]:
            try:
                normalize_declared_path(path)
            except DeclaredPathError:
                malformed.append(path)
        if malformed:
            return "manual-review", ["documentation-path-malformed"]
        if not evidence["expected"]:
            return "fail", ["documentation-expected-change-missing"]
        if evidence["exemption"]:
            return "manual-review", ["documentation-exemption-conflict"]
        return "pass", []
    if not evidence["exemption"]:
        return "manual-review", ["documentation-exemption-missing"]
    if evidence["paths"]:
        return "manual-review", ["documentation-path-conflict"]
    if evidence["expected"]:
        return "manual-review", ["documentation-expected-change-conflict"]
    return "pass", []


def _predict_transition(existing: ReadinessOutcome, documentation_status: str) -> str:
    if existing == ReadinessOutcome.BLOCKED:
        return "blocked->blocked"
    if existing == ReadinessOutcome.NEEDS_DECISION:
        return "needs-decision->needs-decision"
    if documentation_status == "fail":
        return "ready->blocked"
    if documentation_status == "manual-review":
        return "ready->needs-decision"
    return "ready->ready"


def _resolve_scalar(
    yaml_value: Any,
    body_values: list[str],
    *,
    collapse: bool = False,
) -> tuple[str | None, bool]:
    yaml_text = _clean_scalar(yaml_value, collapse=collapse)
    clean_body = [_clean_scalar(value, collapse=collapse) for value in body_values]
    clean_body = [value for value in clean_body if value]
    if len(clean_body) > 1:
        return clean_body[0], True
    body_text = clean_body[0] if clean_body else None
    if yaml_text and body_text and yaml_text != body_text:
        return yaml_text, True
    return yaml_text or body_text, False


def _resolve_list(yaml_values: Iterable[Any], body_values: list[str]) -> tuple[list[str], bool]:
    yaml_list = sorted({str(value).strip() for value in yaml_values if str(value).strip()})
    body_list = sorted({value.strip() for value in body_values if value.strip()})
    if yaml_list and body_list and yaml_list != body_list:
        return yaml_list, True
    return yaml_list or body_list, False


def _clean_scalar(value: Any, *, collapse: bool) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "_No response_":
        return None
    return re.sub(r"\s+", " ", text) if collapse else text


def _clean_line(line: str) -> str:
    value = line.strip()
    if value.startswith("-"):
        value = value[1:].strip()
    if value.startswith("[") and "]" in value:
        value = value.split("]", 1)[1].strip()
    return value


def _sanitize(body: str) -> str:
    without_fences = _FENCED_RE.sub("", body or "")
    without_comments = _COMMENT_RE.sub("", without_fences)
    return "\n".join(
        line for line in without_comments.splitlines() if not line.lstrip().startswith(">")
    )


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _is_tracker_or_roadmap(snapshot: LegacyIssueSnapshot) -> bool:
    if "type:planning" not in snapshot.labels:
        return False
    return bool(
        re.search(
            r"(?i)\b(parent tracker only|roadmap|tracker-only|tracker only)\b",
            snapshot.body,
        )
    )


def _dedupe_snapshots(snapshots: Iterable[LegacyIssueSnapshot]) -> tuple[LegacyIssueSnapshot, ...]:
    selected: dict[int, LegacyIssueSnapshot] = {}
    for snapshot in snapshots:
        current = selected.get(snapshot.number)
        if current is None or (snapshot.updated_at or "") > (current.updated_at or ""):
            selected[snapshot.number] = snapshot
    return tuple(selected[number] for number in sorted(selected))


def _count_reason(items: Iterable[LegacyIssueAssessment], reason: str) -> int:
    return sum(reason in item.reason_codes for item in items)
