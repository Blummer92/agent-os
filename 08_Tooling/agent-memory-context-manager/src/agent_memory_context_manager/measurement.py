"""Small measurement helpers for bounded, explicitly observed values."""

from __future__ import annotations


def measured_reduction(before: int | float | None, after: int | float | None) -> float | None:
    """Return fractional reduction only when both values and a baseline are measured.

    ``None`` means unavailable evidence and is never imputed. A zero baseline is
    also non-comparable for fractional reduction, including the ``0 -> 0`` case.
    """
    if before is None or after is None or before == 0:
        return None
    return (before - after) / before
