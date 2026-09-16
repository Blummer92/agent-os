from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .legacy_preflight import LegacyIssueSnapshot
from .readiness import ReadinessOutcome, evaluate_issue_readiness


class BodyNormalizationClassification(str, Enum):
    CANONICAL_NO_CHANGE = "canonical-no-change"
    MECHANICAL_CANDIDATE = "mechanical-candidate"
    STALE_DURABLE_DECISION = "stale-durable-decision"
    READINESS_BODY_CONFLICT = "readiness-body-conflict"
    MANUAL_REVIEW = "manual-review"
    CLOSED_IMMUTABLE = "closed-immutable"


@dataclass(frozen=True)
class BodyNormalizationAssessment:
    number: int
    classification: BodyNormalizationClassification
    reason_codes: tuple[str, ...]
    proposed_sections: tuple[str, ...] = ()
    route_issue: int | None = None
    authority_created: bool = False
    side_effects_performed: bool = False


@dataclass(frozen=True)
class BodyNormalizationPlan:
    assessments: tuple[BodyNormalizationAssessment, ...]
    proposed_mutation_count: int
    manual_review_count: int
    authority_created: bool = False
    side_effects_performed: bool = False


_HEADING_RE = re.compile(r"(?m)^#{2,3}\s+(.+?)\s*$")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_READINESS_RE = re.compile(
    r"(?im)^\s*(?:readiness(?: candidate)?\s*:\s*)?"
    r"status:(ready|blocked|needs-decision)\s*$"
)
_REQUIRED_FIELDS = {
    "issue tier": ("issue tier",),
    "owner": ("owner", "primary owner", "owner routing"),
    "readiness": ("readiness", "readiness candidate"),
    "source of truth": ("source of truth",),
    "external write boundary": ("external write boundary", "external write surface"),
    "prior scope review": ("prior scope, duplicate, and supersession review",),
    "documentation impact": ("documentation impact",),
}
_STALE_MARKERS = (
    "durable decision superseded",
    "body synchronization required",
    "stale durable decision",
)
_DURABLE_DECISION_HEADINGS = {
    "objective": ("objective", "objective and value"),
    "owner": ("owner", "primary owner", "owner routing"),
    "scope": ("scope", "bounded scope", "scope and non-goals"),
    "non-goals": ("non-goals", "scope and non-goals"),
    "protected-surfaces": ("protected surfaces", "forbidden actions", "safety boundaries"),
    "dependencies": ("dependencies", "dependencies and blockers"),
    "lifecycle-disposition": ("lifecycle disposition", "current disposition", "final disposition"),
}
_TRANSIENT_DECISION_FIELDS = {
    "main-sha", "pr-head", "head-sha", "branch-freshness", "check-conclusion",
    "ci-state", "runtime-state", "executor-availability", "lease-generation",
}


def durable_decision_sync_required(
    body: str, decision_field: str, decision_value: str, *, state: str = "open"
) -> bool | None:
    """Return True for stale durable body authority, False for no sync, None for review."""
    if state != "open":
        return False
    field = re.sub(r"[_\s]+", "-", decision_field.strip().casefold())
    if field in _TRANSIENT_DECISION_FIELDS:
        return False
    headings = _DURABLE_DECISION_HEADINGS.get(field)
    if not headings or not decision_value.strip():
        return None
    sections = _matching_sections(_COMMENT_RE.sub("", body), headings)
    if len(sections) != 1:
        return None
    wanted = _normalize_text(decision_value)
    visible_lines = {_normalize_text(line) for line in sections[0].splitlines() if line.strip()}
    return wanted not in visible_lines


def plan_body_normalization(
    snapshots: Iterable[LegacyIssueSnapshot],
) -> BodyNormalizationPlan:
    """Return a deterministic finite normalization plan and perform zero writes."""
    selected: dict[int, LegacyIssueSnapshot] = {}
    for snapshot in snapshots:
        if type(snapshot) is not LegacyIssueSnapshot:
            raise TypeError("snapshots must contain LegacyIssueSnapshot values")
        current = selected.get(snapshot.number)
        if current is None or (snapshot.updated_at or "") > (current.updated_at or ""):
            selected[snapshot.number] = snapshot
    assessments = tuple(_assess(selected[number]) for number in sorted(selected))
    return BodyNormalizationPlan(
        assessments,
        sum(
            a.classification is BodyNormalizationClassification.MECHANICAL_CANDIDATE
            for a in assessments
        ),
        sum(
            a.classification is BodyNormalizationClassification.MANUAL_REVIEW
            for a in assessments
        ),
    )


def _assess(snapshot: LegacyIssueSnapshot) -> BodyNormalizationAssessment:
    if snapshot.state != "open":
        return BodyNormalizationAssessment(
            snapshot.number,
            BodyNormalizationClassification.CLOSED_IMMUTABLE,
            ("closed-issue-immutable",),
        )
    body = snapshot.body or ""
    readiness = evaluate_issue_readiness(body)
    claims = tuple(sorted(set(_READINESS_RE.findall(body))))
    if len(claims) > 1:
        return BodyNormalizationAssessment(
            snapshot.number,
            BodyNormalizationClassification.MANUAL_REVIEW,
            ("multiple-current-readiness-claims",),
        )
    if claims and claims[0] != readiness.outcome.value:
        return BodyNormalizationAssessment(
            snapshot.number,
            BodyNormalizationClassification.READINESS_BODY_CONFLICT,
            (f"body-readiness-drift:{claims[0]}->{readiness.outcome.value}",),
            route_issue=2442,
        )
    lowered = body.casefold()
    if any(marker in lowered for marker in _STALE_MARKERS):
        return BodyNormalizationAssessment(
            snapshot.number,
            BodyNormalizationClassification.STALE_DURABLE_DECISION,
            ("stale-durable-decision-evidence",),
            route_issue=2441,
        )
    missing = _missing_fields(body)
    if not missing and readiness.outcome is ReadinessOutcome.READY:
        return BodyNormalizationAssessment(
            snapshot.number,
            BodyNormalizationClassification.CANONICAL_NO_CHANGE,
            ("canonical-equivalent-body",),
        )
    mechanical = tuple(field for field in missing if _explicit_equivalent(body, field))
    decisions = tuple(field for field in missing if field not in mechanical)
    if decisions:
        return BodyNormalizationAssessment(
            snapshot.number,
            BodyNormalizationClassification.MANUAL_REVIEW,
            tuple(f"decision-required:{field}" for field in decisions),
        )
    if mechanical:
        return BodyNormalizationAssessment(
            snapshot.number,
            BodyNormalizationClassification.MECHANICAL_CANDIDATE,
            tuple(f"explicit-equivalent:{field}" for field in mechanical),
            proposed_sections=mechanical,
        )
    return BodyNormalizationAssessment(
        snapshot.number,
        BodyNormalizationClassification.CANONICAL_NO_CHANGE,
        ("functionally-equivalent-body",),
    )


def _matching_sections(body: str, aliases: tuple[str, ...]) -> tuple[str, ...]:
    headings = list(_HEADING_RE.finditer(body))
    wanted = {_normalize_text(alias) for alias in aliases}
    return tuple(
        body[match.end() : headings[index + 1].start() if index + 1 < len(headings) else len(body)].strip()
        for index, match in enumerate(headings)
        if _normalize_text(match.group(1)) in wanted
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _missing_fields(body: str) -> tuple[str, ...]:
    headings = {
        re.sub(r"\s+", " ", match.group(1).strip().casefold())
        for match in _HEADING_RE.finditer(body)
    }
    return tuple(
        field
        for field, aliases in _REQUIRED_FIELDS.items()
        if not any(alias in headings for alias in aliases)
    )


def _explicit_equivalent(body: str, field: str) -> bool:
    patterns = {
        "issue tier": r"(?im)^\s*issue tier\s*:\s*(?:tier:)?[012](?:\b|[- ])",
        "owner": r"(?im)^\s*(?:primary )?owner\s*:\s*[^\n]+$",
        "readiness": r"(?im)^\s*readiness(?: candidate)?\s*:\s*status:(?:ready|blocked|needs-decision)\s*$",
        "source of truth": r"(?im)^\s*source of truth\s*:\s*github\s*$",
        "external write boundary": r"(?im)^\s*external write (?:boundary|surface)\s*:\s*(?:no-external-write|none)\s*$",
        "prior scope review": r"(?im)^\s*prior scope(?:, duplicate, and supersession review)?\s*:\s*\S.+$",
        "documentation impact": r"(?im)^\s*documentation impact\s*:\s*docs-(?:required|not-required|needs-decision)\s*$",
    }
    return bool(re.search(patterns[field], body))
