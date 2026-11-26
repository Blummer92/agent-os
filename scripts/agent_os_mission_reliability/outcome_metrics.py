"""Measure finite-request delivery, bug recurrence, and retest evidence."""

from .metrics import _metric


def finite_requests(admitted, window):
    """Return the finite requests metric rows without mutating the inputs."""
    metrics = []
    finite = [
        r
        for r in admitted
        if type(r.get("requested_items")) is int and type(r.get("delivered_items")) is int
    ]
    requested_total = sum(r["requested_items"] for r in finite)  # type: ignore[index]
    delivered_total = sum(r["delivered_items"] for r in finite)  # type: ignore[index]
    metrics.append(
        _metric(
            "requested_vs_delivered",
            definition="Delivered items over requested items for finite missions with persisted counts.",
            population=f"finite missions with persisted counts, window {window}",
            n=len(finite),
            evidence_source="persisted requested/delivered counts (e.g. #2220/#2607 completion proof)",
            confidence="measured" if finite else "unknown",
            numerator=delivered_total if finite else None,
            denominator=requested_total or None,
            note="Unknown unless counts are persisted durably; never estimated from narrative.",
        )
    )
    return metrics


def learning(admitted, window):
    """Return the learning metric rows without mutating the inputs."""
    metrics = []
    recurrences = [
        r
        for r in admitted
        if r.get("bug_family") and r.get("prior_completed_fix_issue") is not None
    ]
    retested = [r for r in recurrences if r.get("retest_at")]
    metrics.append(
        _metric(
            "bug_family_recurrence",
            definition=(
                "Missions in a bug family with an explicit prior completed fix "
                "in the same family (recurrence after a completed fix)."
            ),
            population=f"admitted missions, window {window}",
            n=len(admitted),
            evidence_source="explicit bug-family lineage on the record",
            confidence="measured" if recurrences else "unknown",
            numerator=len(recurrences),
            denominator=len(admitted) or None,
            note=(
                f"{len(retested)} of {len(recurrences)} recurrences carry "
                "retest evidence."
            ),
        )
    )
    findings = [
        r
        for r in admitted
        if r.get("finding_issue") is not None
    ]
    findings_implemented = [
        r for r in findings if r.get("implementation_prs")
    ]
    findings_retested = [r for r in findings_implemented if r.get("retest_at")]
    metrics.append(
        _metric(
            "finding_to_implementation_to_retest",
            definition=(
                "Experiment findings (finding_issue set) that reached a linked "
                "implementation PR and then retest evidence."
            ),
            population=f"admitted missions with a finding_issue, window {window}",
            n=len(findings),
            evidence_source="explicit finding->issue->implementation->retest lineage on the record",
            confidence="measured" if findings else "unknown",
            numerator=len(findings_retested),
            denominator=len(findings) or None,
            note=(
                f"{len(findings_implemented)} of {len(findings)} findings reached "
                "implementation; retest completes the conversion."
            ),
        )
    )
    return metrics
