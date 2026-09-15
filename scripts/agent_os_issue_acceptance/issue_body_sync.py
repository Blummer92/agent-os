from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .legacy_preflight import LegacyIssueSnapshot
from .readiness import ReadinessOutcome, ReadinessResult, evaluate_issue_readiness


class BodyReadinessDriftStatus(str, Enum):
    NO_DRIFT = "no-drift"
    DRIFT = "drift"
    MANUAL_REVIEW = "manual-review"


class BodyNormalizationClassification(str, Enum):
    CANONICAL_NO_CHANGE = "canonical-no-change"
    MECHANICAL_CANDIDATE = "mechanical-candidate"
    STALE_DURABLE_DECISION = "stale-durable-decision"
    READINESS_BODY_CONFLICT = "readiness-body-conflict"
    MANUAL_REVIEW = "manual-review"
    CLOSED_IMMUTABLE = "closed-immutable"


@dataclass(frozen=True)
class BodyReadinessDrift:
    status: BodyReadinessDriftStatus
    claimed_readiness: str | None
    canonical_readiness: str
    reason_codes: tuple[str, ...]
    authority_created: bool = False
    side_effects_performed: bool = False


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


_READINESS_LINE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:readiness(?: candidate)?\s*:\s*)?"
    r"status:(ready|blocked|needs-decision)\s*$"
)
_HEADING_RE = re.compile(r"(?m)^#{2,3}\s+(.+?)\s*$")
_REQUIRED_NORMALIZATION_FIELDS = {
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


def detect_body_readiness_drift(
    issue_body: str,
    readiness: ReadinessResult,
) -> BodyReadinessDrift:
    """Compare explicit current body readiness prose with canonical readiness evidence.

    This is report-only. It never derives readiness from labels and never writes.
    """
    if type(readiness) is not ReadinessResult:
        raise TypeError("readiness must be a ReadinessResult")
    claims = tuple(sorted(set(_current_readiness_claims(issue_body))))
    canonical = readiness.outcome.value
    if len(claims) > 1:
        return BodyReadinessDrift(
            BodyReadinessDriftStatus.MANUAL_REVIEW,
            None,
            canonical,
            ("multiple-current-readiness-claims",),
        )
    if not claims:
        return BodyReadinessDrift(
            BodyReadinessDriftStatus.NO_DRIFT,
            None,
            canonical,
            ("no-explicit-current-readiness-claim",),
        )
    claim = claims[0]
    if claim != canonical:
        return BodyReadinessDrift(
            BodyReadinessDriftStatus.DRIFT,
            claim,
            canonical,
            (f"body-readiness-drift:{claim}->{canonical}",),
        )
    return BodyReadinessDrift(
        BodyReadinessDriftStatus.NO_DRIFT,
        claim,
        canonical,
        ("body-readiness-converged",),
    )


def plan_body_normalization(
    snapshots: Iterable[LegacyIssueSnapshot],
) -> BodyNormalizationPlan:
    """Classify a finite supplied issue population without performing writes."""
    selected: dict[int, LegacyIssueSnapshot] = {}
    for snapshot in snapshots:
        if type(snapshot) is not LegacyIssueSnapshot:
            raise TypeError("snapshots must contain LegacyIssueSnapshot values")
        current = selected.get(snapshot.number)
        if current is None or (snapshot.updated_at or "") > (current.updated_at or ""):
            selected[snapshot.number] = snapshot

    assessments = tuple(_assess(selected[number]) for number in sorted(selected))
    return BodyNormalizationPlan(
        assessments=assessments,
        proposed_mutation_count=sum(
            item.classification is BodyNormalizationClassification.MECHANICAL_CANDIDATE
            for item in assessments
        ),
        manual_review_count=sum(
            item.classification is BodyNormalizationClassification.MANUAL_REVIEW
            for item in assessments
        ),
    )


def _assess(snapshot: LegacyIssueSnapshot) -> BodyNormalizationAssessment:
    if snapshot.state != "open":
        return BodyNormalizationAssessment(
            snapshot.number,
            BodyNormalizationClassification.CLOSED_IMMUTABLE,
            ("closed-issue-immutable",),
        )

    readiness = evaluate_issue_readiness(snapshot.body)
    drift = detect_body_readiness_drift(snapshot.body, readiness)
    if drift.status is BodyReadinessDriftStatus.DRIFT:
        return BodyNormalizationAssessment(
            snapshot.number,
            BodyNormalizationClassification.READINESS_BODY_CONFLICT,
            drift.reason_codes,
            route_issue=2442,
        )
    if drift.status is BodyReadinessDriftStatus.MANUAL_REVIEW:
        return BodyNormalizationAssessment(
            snapshot.number,
            BodyNormalizationClassification.MANUAL_REVIEW,
            drift.reason_codes,
        )

    lowered = (snapshot.body or "").casefold()
    if any(marker in lowered for marker in _STALE_MARKERS):
        return BodyNormalizationAssessment(
            snapshot.number,
            BodyNormalizationClassification.STALE_DURABLE_DECISION,
            ("stale-durable-decision-evidence",),
            route_issue=2441,
        )

    missing = _missing_normalization_fields(snapshot.body)
    if not missing and readiness.outcome is ReadinessOutcome.READY:
        return BodyNormalizationAssessment(
            snapshot.number,
            BodyNormalizationClassification.CANONICAL_NO_CHANGE,
            ("canonical-equivalent-body",),
        )

    mechanical = tuple(field for field in missing if _explicit_equivalent_value(snapshot.body, field))
    decision_required = tuple(field for field in missing if field not in mechanical)
    if decision_required:
        return BodyNormalizationAssessment(
            snapshot.number,
            BodyNormalizationClassification.MANUAL_REVIEW,
            tuple(f"decision-required:{field}" for field in decision_required),
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


def _current_readiness_claims(body: str) -> tuple[str, ...]:
    text = body or ""
    claims: list[str] = []
    for match in _READINESS_LINE_RE.finditer(text):
        prefix = text[max(0, match.start() - 160):match.start()].casefold()
        if "historical" in prefix or "previous" in prefix or "formerly" in prefix:
            continue
        claims.append(match.group(1).casefold())
    return tuple(claims)


def _missing_normalization_fields(body: str) -> tuple[str, ...]:
    headings = {
        re.sub(r"\s+", " ", match.group(1).strip().casefold())
        for match in _HEADING_RE.finditer(body or "")
    }
    missing = []
    for field, aliases in _REQUIRED_NORMALIZATION_FIELDS.items():
        if not any(alias in headings for alias in aliases):
            missing.append(field)
    return tuple(missing)


def _explicit_equivalent_value(body: str, field: str) -> bool:
    text = body or ""
    patterns = {
        "issue tier": r"(?im)^\s*issue tier\s*:\s*(?:tier:)?[012](?:\b|[- ])",
        "owner": r"(?im)^\s*(?:primary )?owner\s*:\s*[^\n]+$",
        "readiness": r"(?im)^\s*readiness(?: candidate)?\s*:\s*status:(?:ready|blocked|needs-decision)\s*$",
        "source of truth": r"(?im)^\s*source of truth\s*:\s*github\s*$",
        "external write boundary": r"(?im)^\s*external write (?:boundary|surface)\s*:\s*(?:no-external-write|none)\s*$",
        "prior scope review": r"(?im)^\s*prior scope(?:, duplicate, and supersession review)?\s*:\s*\S.+$",
        "documentation impact": r"(?im)^\s*documentation impact\s*:\s*docs-(?:required|not-required|needs-decision)\s*$",
    }
    return bool(re.search(patterns[field], text))
