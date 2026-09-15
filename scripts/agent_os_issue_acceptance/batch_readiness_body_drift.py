from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .readiness import ReadinessResult


class BodyReadinessDriftStatus(str, Enum):
    NO_DRIFT = "no-drift"
    DRIFT = "drift"
    MANUAL_REVIEW = "manual-review"


@dataclass(frozen=True)
class BodyReadinessDrift:
    status: BodyReadinessDriftStatus
    claimed_readiness: str | None
    canonical_readiness: str
    reason_codes: tuple[str, ...]
    authority_created: bool = False
    side_effects_performed: bool = False


_READINESS_LINE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:readiness(?: candidate)?\s*:\s*)?"
    r"status:(ready|blocked|needs-decision)\s*$"
)


def detect_body_readiness_drift(
    issue_body: str,
    readiness: ReadinessResult,
) -> BodyReadinessDrift:
    """Compare explicit current body readiness prose with canonical readiness evidence.

    Report-only: labels are not inputs, no readiness is recomputed, and no writes
    or authority are created.
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


def _current_readiness_claims(body: str) -> tuple[str, ...]:
    text = body or ""
    claims: list[str] = []
    for match in _READINESS_LINE_RE.finditer(text):
        prefix = text[max(0, match.start() - 160):match.start()].casefold()
        if "historical" in prefix or "previous" in prefix or "formerly" in prefix:
            continue
        claims.append(match.group(1).casefold())
    return tuple(claims)
