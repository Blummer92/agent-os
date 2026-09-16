from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class DecisionEvidenceClass(str, Enum):
    DURABLE_CONTRACT = "durable-contract"
    TRANSIENT_OPERATIONAL = "transient-operational"
    AMBIGUOUS = "ambiguous"


class BodySyncDisposition(str, Enum):
    NO_SYNC_REQUIRED = "no-sync-required"
    BODY_SYNC_REQUIRED = "body-sync-required"
    MANUAL_REVIEW = "manual-review"
    CLOSED_IMMUTABLE = "closed-immutable"


@dataclass(frozen=True, slots=True)
class BodySyncAssessment:
    issue_number: int
    decision_field: str
    decision_class: DecisionEvidenceClass
    disposition: BodySyncDisposition
    reason_codes: tuple[str, ...]
    authority_created: bool = field(default=False, init=False)
    side_effects_performed: bool = field(default=False, init=False)


_HEADING_RE = re.compile(r"(?m)^#{2,3}\s+(.+?)\s*$")
_READINESS_LINE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:readiness(?: candidate)?\s*:\s*)?"
    r"status:(ready|blocked|needs-decision)\s*$"
)
_STALE_DURABLE_MARKERS = (
    "durable decision superseded",
    "body synchronization required",
    "stale durable decision",
)
_DURABLE_FIELD_HEADINGS: dict[str, tuple[str, ...]] = {
    "objective": ("objective", "objective and value"),
    "owner": ("owner", "primary owner", "owner routing"),
    "scope": (
        "scope",
        "bounded scope",
        "scope and non-goals",
        "allowed files, areas, or governed surfaces",
    ),
    "non-goals": ("non-goals", "scope and non-goals", "non-goals / excluded surfaces"),
    "protected-surfaces": (
        "protected surfaces",
        "forbidden actions",
        "safety boundaries",
        "non-goals / excluded surfaces",
    ),
    "dependencies": ("dependencies", "dependencies and blockers"),
    "lifecycle-disposition": (
        "lifecycle disposition",
        "current disposition",
        "final disposition",
    ),
}
_TRANSIENT_FIELDS = frozenset(
    {
        "main-sha",
        "pr-head",
        "head-sha",
        "branch-freshness",
        "check-conclusion",
        "ci-state",
        "runtime-state",
        "executor-availability",
        "lease-generation",
    }
)


def classify_decision_field(decision_field: str) -> DecisionEvidenceClass:
    field_name = _normalize_field(decision_field)
    if field_name in _DURABLE_FIELD_HEADINGS:
        return DecisionEvidenceClass.DURABLE_CONTRACT
    if field_name in _TRANSIENT_FIELDS:
        return DecisionEvidenceClass.TRANSIENT_OPERATIONAL
    return DecisionEvidenceClass.AMBIGUOUS


def assess_durable_decision_sync(
    *,
    issue_number: int,
    issue_state: str,
    issue_body: str,
    decision_field: str,
    decision_value: str,
) -> BodySyncAssessment:
    """Classify one supplied post-decision body-sync obligation without I/O.

    The caller supplies a freshly reacquired canonical issue body plus one already-
    persisted/consumed structured decision. This helper never reads comments,
    infers authority, performs a GitHub write, or makes a stale snapshot current.
    """
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("issue_number must be a positive built-in integer")
    if type(issue_state) is not str or not issue_state.strip():
        raise ValueError("issue_state must be non-empty text")
    if type(issue_body) is not str:
        raise TypeError("issue_body must be text")
    if type(decision_field) is not str or not decision_field.strip():
        raise ValueError("decision_field must be non-empty text")
    if type(decision_value) is not str:
        raise TypeError("decision_value must be text")

    field_name = _normalize_field(decision_field)
    decision_class = classify_decision_field(field_name)

    if issue_state.strip().casefold() != "open":
        return BodySyncAssessment(
            issue_number,
            field_name,
            decision_class,
            BodySyncDisposition.CLOSED_IMMUTABLE,
            ("closed-issue-body-immutable",),
        )

    if decision_class is DecisionEvidenceClass.TRANSIENT_OPERATIONAL:
        return BodySyncAssessment(
            issue_number,
            field_name,
            decision_class,
            BodySyncDisposition.NO_SYNC_REQUIRED,
            ("transient-operational-evidence-not-durable-body-contract",),
        )

    if decision_class is DecisionEvidenceClass.AMBIGUOUS or not decision_value.strip():
        return BodySyncAssessment(
            issue_number,
            field_name,
            DecisionEvidenceClass.AMBIGUOUS,
            BodySyncDisposition.MANUAL_REVIEW,
            ("durable-decision-classification-ambiguous",),
        )

    sections = _matching_sections(issue_body, _DURABLE_FIELD_HEADINGS[field_name])
    if len(sections) > 1:
        return BodySyncAssessment(
            issue_number,
            field_name,
            decision_class,
            BodySyncDisposition.MANUAL_REVIEW,
            ("multiple-authoritative-body-sections",),
        )

    normalized_decision = _normalize_text(decision_value)
    if len(sections) == 1 and normalized_decision in _normalize_text(sections[0]):
        return BodySyncAssessment(
            issue_number,
            field_name,
            decision_class,
            BodySyncDisposition.NO_SYNC_REQUIRED,
            ("durable-decision-already-synchronized",),
        )

    return BodySyncAssessment(
        issue_number,
        field_name,
        decision_class,
        BodySyncDisposition.BODY_SYNC_REQUIRED,
        ("durable-decision-not-in-authoritative-body",),
    )


def current_readiness_claims(body: str) -> tuple[str, ...]:
    """Return explicit current readiness claims from one authoritative body."""
    text = body or ""
    claims: list[str] = []
    for match in _READINESS_LINE_RE.finditer(text):
        prefix = text[max(0, match.start() - 160):match.start()].casefold()
        if "historical" in prefix or "previous" in prefix or "formerly" in prefix:
            continue
        claims.append(match.group(1).casefold())
    return tuple(claims)


def contains_stale_durable_decision_marker(body: str) -> bool:
    """Return only a report-only triage signal used by the legacy batch planner."""
    lowered = (body or "").casefold()
    return any(marker in lowered for marker in _STALE_DURABLE_MARKERS)


def _matching_sections(body: str, aliases: tuple[str, ...]) -> tuple[str, ...]:
    matches = list(_HEADING_RE.finditer(body or ""))
    values: list[str] = []
    normalized_aliases = {_normalize_heading(alias) for alias in aliases}
    for index, match in enumerate(matches):
        if _normalize_heading(match.group(1)) not in normalized_aliases:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        values.append((body[start:end] or "").strip())
    return tuple(values)


def _normalize_field(value: str) -> str:
    return re.sub(r"[_\s]+", "-", value.strip().casefold())


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())
