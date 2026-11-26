"""Measure lifecycle elapsed time from durable PR and issue timestamps."""

from .metrics import _distribution, _hours_between, _linked_prs, _merged_first, _metric, _parse_iso
from collections.abc import Mapping
from typing import Any


def lifecycle(admitted, window):
    """Return the lifecycle metric rows without mutating the inputs."""
    metrics = []
    merged_prs = [pr for pr in _linked_prs(admitted) if pr.get("merged") is True]
    merged_first = _merged_first(admitted)
    validation_times = [
        h
        for h in (
            _hours_between(
                _parse_iso(pr.get("created_at")),
                _parse_iso(pr.get("first_terminal_validation_at")),
            )
            for pr in merged_prs
        )
        if h is not None
    ]
    metrics.append(
        _metric(
            "pr_to_first_terminal_validation",
            definition="PR creation -> first exact-head terminal validation.",
            population=f"merged implementation PRs with validation evidence, window {window}",
            n=len(validation_times),
            evidence_source="first_terminal_validation_at on the PR record",
            confidence="measured" if validation_times else "unknown",
            elapsed_hours=_distribution(validation_times),
            note=(
                "Not recomputed here: CI/build/validation timing is owned by "
                "#520; this metric only consumes already-durable validation "
                "timestamps."
            ),
        )
    )
    convergence_pairs: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for r in admitted:
        prs = r.get("implementation_prs") or []
        if not prs or prs[0].get("merged") is not True:
            continue
        if r.get("issue_state") == "closed" and r.get("issue_closed_at"):
            convergence_pairs.append((prs[0], r))
    convergence_hours = [
        h
        for h in (
            _hours_between(
                _parse_iso(pr.get("merged_at")), _parse_iso(r.get("issue_closed_at"))
            )
            for pr, r in convergence_pairs
        )
        if h is not None
    ]
    metrics.append(
        _metric(
            "merge_to_issue_convergence",
            definition=(
                "Merged first implementation PRs whose linked issue closed "
                "after the merge (lifecycle convergence)."
            ),
            population=f"merged first implementation PRs of admitted missions, window {window}",
            n=len(merged_first),
            evidence_source="GitHub merged_at + issue closed_at timestamps",
            confidence="measured" if merged_first else "unknown",
            numerator=len(convergence_pairs),
            denominator=len(merged_first) or None,
            elapsed_hours=_distribution(convergence_hours),
            note="Elapsed time is merge -> issue close.",
        )
    )
    return metrics
