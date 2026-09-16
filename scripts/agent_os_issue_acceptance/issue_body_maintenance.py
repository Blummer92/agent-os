from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BodySyncAssessment:
    disposition: str
    reason_codes: tuple[str, ...]
    authority_created: bool = False
    side_effects_performed: bool = False


_READINESS_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:readiness(?: candidate)?\s*:\s*)?"
    r"status:(ready|blocked|needs-decision)\s*$"
)
_HEADING_RE = re.compile(r"(?m)^#{2,3}\s+(.+?)\s*$")
_DURABLE_FIELDS = {
    "objective": ("objective", "objective and value"),
    "owner": ("owner", "primary owner", "owner routing"),
    "scope": ("scope", "bounded scope", "scope and non-goals"),
    "non-goals": ("non-goals", "scope and non-goals"),
    "protected-surfaces": ("protected surfaces", "forbidden actions", "safety boundaries"),
    "dependencies": ("dependencies", "dependencies and blockers"),
    "lifecycle-disposition": ("lifecycle disposition", "current disposition", "final disposition"),
}
_TRANSIENT_FIELDS = {
    "main-sha", "pr-head", "head-sha", "branch-freshness", "check-conclusion",
    "ci-state", "runtime-state", "executor-availability", "lease-generation",
}
_STALE_MARKERS = (
    "durable decision superseded",
    "body synchronization required",
    "stale durable decision",
)


def assess_durable_decision_sync(
    *, issue_state: str, issue_body: str, decision_field: str, decision_value: str
) -> BodySyncAssessment:
    """Classify a supplied post-decision body-sync obligation without I/O."""
    field = re.sub(r"[_\s]+", "-", decision_field.strip().casefold())
    if issue_state.strip().casefold() != "open":
        return BodySyncAssessment("closed-immutable", ("closed-issue-body-immutable",))
    if field in _TRANSIENT_FIELDS:
        return BodySyncAssessment(
            "no-sync-required",
            ("transient-operational-evidence-not-durable-body-contract",),
        )
    aliases = _DURABLE_FIELDS.get(field)
    if not aliases or not decision_value.strip():
        return BodySyncAssessment(
            "manual-review", ("durable-decision-classification-ambiguous",)
        )
    sections = _sections(issue_body, aliases)
    if len(sections) > 1:
        return BodySyncAssessment("manual-review", ("multiple-authoritative-body-sections",))
    wanted = _normalize(decision_value)
    if sections and wanted in _normalize(sections[0]):
        return BodySyncAssessment(
            "no-sync-required", ("durable-decision-already-synchronized",)
        )
    return BodySyncAssessment(
        "body-sync-required", ("durable-decision-not-in-authoritative-body",)
    )


def current_readiness_claims(body: str) -> tuple[str, ...]:
    claims: list[str] = []
    text = body or ""
    for match in _READINESS_RE.finditer(text):
        prefix = text[max(0, match.start() - 160):match.start()].casefold()
        if not any(word in prefix for word in ("historical", "previous", "formerly")):
            claims.append(match.group(1).casefold())
    return tuple(claims)


def contains_stale_durable_decision_marker(body: str) -> bool:
    lowered = (body or "").casefold()
    return any(marker in lowered for marker in _STALE_MARKERS)


def _sections(body: str, aliases: tuple[str, ...]) -> tuple[str, ...]:
    headings = list(_HEADING_RE.finditer(body or ""))
    aliases = tuple(_normalize(alias) for alias in aliases)
    return tuple(
        (body[match.end() : headings[index + 1].start() if index + 1 < len(headings) else len(body)]).strip()
        for index, match in enumerate(headings)
        if _normalize(match.group(1)) in aliases
    )


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())
