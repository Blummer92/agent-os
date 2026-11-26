"""Measure linked PR delivery and lifecycle timing; keep the two projections pure."""

from .metrics import _distribution, _hours_between, _linked_prs, _merged_first, _metric, _parse_iso


def delivery(admitted, window):
    """Return the delivery metric rows without mutating the inputs."""
    metrics = []
    first_prs = [r["implementation_prs"][0] for r in admitted if r.get("implementation_prs")]
    merged_first = _merged_first(admitted)
    repair_prs = [
        pr
        for r in admitted
        for pr in (r.get("implementation_prs") or [])
        if pr.get("repair") is True
    ]
    metrics.append(
        _metric(
            "issue_to_pr_conversion",
            definition="Admitted issues with at least one linked implementation PR.",
            population=f"admitted missions, window {window}",
            n=len(admitted),
            evidence_source="canonical closing-keyword linkage (parse_linked_issue) + agent/<issue>- branches",
            confidence="strongly_evidenced" if admitted else "unknown",
            numerator=len(first_prs),
            denominator=len(admitted),
            elapsed_hours=_distribution(
                [
                    h
                    for h in (
                        _hours_between(
                            _parse_iso(r.get("admitted_at")),
                            _parse_iso(pr.get("created_at")),
                        )
                        for r, pr in (
                            (r, r["implementation_prs"][0])
                            for r in admitted
                            if r.get("implementation_prs")
                        )
                    )
                    if h is not None
                ]
            ),
            note="Elapsed time is admitted_at -> first implementation PR creation.",
        )
    )
    all_prs = _linked_prs(admitted)
    merged_prs = [pr for pr in all_prs if pr.get("merged") is True]
    metrics.append(
        _metric(
            "pr_merge_conversion",
            definition="Linked implementation PRs that merged.",
            population=f"implementation PRs linked to admitted missions, window {window}",
            n=len(all_prs),
            evidence_source="GitHub PR merged flag + merged_at timestamp",
            confidence="measured" if all_prs else "unknown",
            numerator=len(merged_prs),
            denominator=len(all_prs),
            elapsed_hours=_distribution(
                [
                    h
                    for h in (
                        _hours_between(
                            _parse_iso(pr.get("created_at")),
                            _parse_iso(pr.get("merged_at")),
                        )
                        for pr in merged_prs
                    )
                    if h is not None
                ]
            ),
            note="Elapsed time is PR creation -> merge.",
        )
    )
    metrics.append(
        _metric(
            "repair_attempts_per_delivered_implementation",
            definition=(
                "Repair/follow-up PRs over delivered implementations "
                "(missions whose first implementation PR merged)."
            ),
            population=f"delivered implementations, window {window}",
            n=len(merged_first),
            evidence_source="repair flag on linked PRs ordered by creation time",
            confidence="weakly_evidenced" if merged_first else "unknown",
            numerator=len(repair_prs),
            denominator=len(merged_first) or None,
            note=(
                "Repair linkage is ordering-based; #2220/#2607 admission "
                "records are the authoritative source where present."
            ),
        )
    )
    reentry_missions = [
        r
        for r in admitted
        if sum(1 for pr in (r.get("implementation_prs") or []) if pr.get("repair") is True) >= 1
    ]
    metrics.append(
        _metric(
            "failed_repair_reentries",
            definition=(
                "Delivered implementations requiring at least one repair "
                "re-entry after the first implementation PR."
            ),
            population=f"delivered implementations, window {window}",
            n=len(merged_first),
            evidence_source="repair flag on linked PRs",
            confidence="weakly_evidenced" if merged_first else "unknown",
            numerator=len(reentry_missions),
            denominator=len(merged_first) or None,
        )
    )
    return metrics
