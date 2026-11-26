"""Pure metric row, distribution, and elapsed-time helpers; stdlib only."""

from datetime import datetime, timezone
from statistics import median
from typing import Any, Sequence

def _parse_iso(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp to an aware UTC datetime, or None."""
    if type(value) is not str:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.astimezone(timezone.utc)
    except OverflowError:
        return None


def _hours_between(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    delta_hours = (end - start).total_seconds() / 3600.0
    if delta_hours < 0:
        return None
    return delta_hours


def _distribution(hours: Sequence[float]) -> dict[str, Any] | None:
    """median/p90/min/max over a non-empty hour list; None when empty."""
    values = sorted(hours)
    if not values:
        return None
    n = len(values)
    p90_index = min(n - 1, int(0.9 * n))
    return {
        "n": n,
        "min": values[0],
        "median": median(values),
        "p90": values[p90_index],
        "max": values[-1],
    }


def _metric(
    name: str,
    *,
    definition: str,
    population: str,
    n: int,
    evidence_source: str,
    confidence: str,
    numerator: int | None = None,
    denominator: int | None = None,
    elapsed_hours: dict[str, Any] | None = None,
    note: str = "",
) -> dict[str, Any]:
    ratio: float | None = None
    if numerator is not None and denominator not in (None, 0):
        ratio = numerator / denominator
    return {
        "metric": name,
        "definition": definition,
        "population": population,
        "n": n,
        "numerator": numerator,
        "denominator": denominator,
        "ratio": ratio,
        "elapsed_hours": elapsed_hours,
        "evidence_source": evidence_source,
        "confidence": confidence,
        "note": note,
    }


def _linked_prs(admitted):
    """Return all linked implementation PRs for admitted records."""
    return [pr for record in admitted for pr in (record.get("implementation_prs") or [])]


def _merged_first(admitted):
    """Return first implementation PRs with affirmative merge evidence."""
    return [r["implementation_prs"][0] for r in admitted if r.get("implementation_prs")
            and r["implementation_prs"][0].get("merged") is True]
