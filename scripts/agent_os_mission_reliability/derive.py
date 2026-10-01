"""Pure derivation of mission-level reliability metrics for issue #2766.

Derivation only: every function here is a deterministic projection over
caller-supplied *normalized mission records* plus (optionally) read-only
GitHub acquisition via ``github_source.acquire_mission_records``. It performs
no I/O, no network, no subprocess, no retry, and no inference beyond what the
record fields already prove.

Read the metric definitions, derivation sources, and confidence rules in
``scripts/agent_os_mission_reliability/README.md`` before consuming output.

Confidence vocabulary (per the #2766 handoff):
- "measured": every record contributing to the metric carries primary
  evidence for every field used.
- "strongly_evidenced": derived from durable evidence with one documented
  linkage assumption (e.g. closing-keyword issue<->PR linkage).
- "weakly_evidenced": durable evidence exists but the linkage is heuristic
  (e.g. repair PRs ordered by creation time).
- "unknown": no durable evidence in the records; the metric is reported as
  unknown, never estimated.

This module never emits a composite health score: the #2766 handoff forbids
one. It also never recomputes CI/build/validation timing (owned by #520) and
never infers user interventions or cross-chat continuations from narrative
(unknown unless durable evidence exists).
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "2766-mission-reliability.v1"

# Normalized mission record fields consumed by derive_mission_reliability().
# All timestamps are ISO-8601 UTC strings (e.g. "2026-09-22T02:04:54Z").
#
# {
#   "issue_number": int,                       # required
#   "admitted": bool,                          # admitted mission in the frozen window
#   "admitted_at": str | None,                 # mission admission timestamp
#   "issue_state": "open" | "closed" | "unknown",
#   "issue_closed_at": str | None,
#   "implementation_prs": [                    # linked implementation PRs, oldest first
#       {"number": int, "created_at": str, "merged": bool,
#        "merged_at": str | None, "repair": bool,
#        "first_terminal_validation_at": str | None}
#   ],
#   "requested_items": int | None,             # finite mission requested count
#   "delivered_items": int | None,             # finite mission delivered count
#   "terminal_state": "completed_truthful" | "blocked_systemic" |
#                     "blocked_item_local" | "intermediate_stop" | "unknown",
#   "user_interventions": int | None,         # None = no durable evidence
#   "continuation_prompts": int | None,       # None = unknown (do not infer)
#   "bug_family": str | None,
#   "prior_completed_fix_issue": int | None,
#   "finding_issue": int | None,
#   "retest_at": str | None,
# }

_TERMINAL_STATES = frozenset(
    {
        "completed_truthful",
        "blocked_systemic",
        "blocked_item_local",
        "intermediate_stop",
        "unknown",
    }
)


def _parse_iso(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp to an aware UTC datetime, or None."""
    if type(value) is not str:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def _validate_records(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Type-check the normalized record envelope; raise TypeError on violation."""
    validated: list[Mapping[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise TypeError("each mission record must be a mapping")
        issue_number = record.get("issue_number")
        if type(issue_number) is not int:
            raise TypeError("mission record 'issue_number' must be an int")
        terminal_state = record.get("terminal_state", "unknown")
        if terminal_state not in _TERMINAL_STATES:
            raise TypeError(
                f"mission record 'terminal_state' must be one of "
                f"{sorted(_TERMINAL_STATES)}"
            )
        prs = record.get("implementation_prs") or []
        if not isinstance(prs, list):
            raise TypeError("mission record 'implementation_prs' must be a list")
        for pr in prs:
            if not isinstance(pr, Mapping):
                raise TypeError("each implementation PR must be a mapping")
        validated.append(record)
    return validated


def derive_mission_reliability(
    records: Sequence[Mapping[str, Any]], *, window: str
) -> dict[str, Any]:
    """Derive the #2766 minimal measurement set over normalized mission records.

    ``window`` names the frozen population (e.g. "2026-08-23..2026-09-21,
    Blummer92/agent-os, n frozen issue numbers").
    """
    if type(window) is not str or not window.strip():
        raise TypeError("window must be a non-empty string")
    mission_records = _validate_records(records)
    admitted = [r for r in mission_records if r.get("admitted") is True]

    metrics: list[dict[str, Any]] = []

    # ---- Mission completion -------------------------------------------------
    known_terminal = [
        r for r in admitted if r.get("terminal_state") != "unknown"
    ]
    truthful = [r for r in known_terminal if r.get("terminal_state") == "completed_truthful"]
    metrics.append(
        _metric(
            "admitted_missions",
            definition="Count of admitted missions in the frozen window.",
            population=f"frozen window {window}",
            n=len(mission_records),
            evidence_source="caller-frozen population",
            confidence="measured",
            numerator=len(admitted),
            denominator=len(mission_records),
        )
    )
    metrics.append(
        _metric(
            "truthful_terminal_completion",
            definition=(
                "Admitted missions reaching a truthful terminal state, over "
                "admitted missions with known terminal state."
            ),
            population=f"admitted missions with known terminal state, window {window}",
            n=len(known_terminal),
            evidence_source="normalized terminal_state field (durable mission evidence only)",
            confidence="measured" if known_terminal else "unknown",
            numerator=len(truthful),
            denominator=len(known_terminal),
            note=(
                f"{len(admitted) - len(known_terminal)} admitted missions have "
                "unknown terminal state and are excluded, not estimated."
                if admitted
                else "no admitted missions in the window"
            ),
        )
    )
    intermediate = [r for r in admitted if r.get("terminal_state") == "intermediate_stop"]
    systemic = [r for r in admitted if r.get("terminal_state") == "blocked_systemic"]
    item_local = [r for r in admitted if r.get("terminal_state") == "blocked_item_local"]
    metrics.append(
        _metric(
            "intermediate_stops",
            definition=(
                "Admitted missions stopped at an intermediate state "
                "(not terminal, not converging), over admitted missions."
            ),
            population=f"admitted missions, window {window}",
            n=len(admitted),
            evidence_source="normalized terminal_state field",
            confidence="measured" if admitted else "unknown",
            numerator=len(intermediate),
            denominator=len(admitted),
        )
    )
    metrics.append(
        _metric(
            "blocker_split",
            definition="Known-terminal blockers split into shared/systemic vs item-local.",
            population=f"admitted missions with known terminal state, window {window}",
            n=len(known_terminal),
            evidence_source="normalized terminal_state field",
            confidence="measured" if known_terminal else "unknown",
            numerator=None,
            denominator=None,
            note=(
                f"systemic={len(systemic)} item_local={len(item_local)}; no "
                "ratio is reported because the classes are disjoint counts, "
                "not a single conversion."
            ),
        )
    )

    # ---- User intervention / continuation (durable evidence only) ------------
    with_intervention_evidence = [
        r
        for r in admitted
        if type(r.get("user_interventions")) is int
    ]
    completed = [r for r in admitted if r.get("terminal_state") == "completed_truthful"]
    completed_with_evidence = [
        r for r in completed if type(r.get("user_interventions")) is int
    ]
    interventions_total = sum(r["user_interventions"] for r in completed_with_evidence)  # type: ignore[index]
    metrics.append(
        _metric(
            "user_interventions_per_completed_mission",
            definition=(
                "User interventions over completed-truthful missions with durable "
                "intervention evidence; unknown for all others."
            ),
            population=f"completed-truthful missions with durable evidence, window {window}",
            n=len(completed_with_evidence),
            evidence_source="durable user-intervention records only (none inferred)",
            confidence="measured" if completed_with_evidence else "unknown",
            numerator=interventions_total if completed_with_evidence else None,
            denominator=len(completed_with_evidence) or None,
            note=(
                "Per the #2766 handoff: unknown unless durable evidence exists; "
                "do not infer from memory or narrative."
            ),
        )
    )
    with_continuation_evidence = [
        r for r in admitted if type(r.get("continuation_prompts")) is int
    ]
    continuations_total = sum(r["continuation_prompts"] for r in with_continuation_evidence)  # type: ignore[index]
    metrics.append(
        _metric(
            "continuation_prompts",
            definition=(
                "User re-prompt / explicit-continuation counts over admitted "
                "missions with durable continuation evidence."
            ),
            population=f"admitted missions with durable evidence, window {window}",
            n=len(with_continuation_evidence),
            evidence_source="durable continuation records only (none inferred)",
            confidence="measured" if with_continuation_evidence else "unknown",
            numerator=continuations_total if with_continuation_evidence else None,
            denominator=len(with_continuation_evidence) or None,
            note="Unknown unless durable host evidence exists (#2753 owns host lifecycle telemetry).",
        )
    )

    # ---- Delivery / repair --------------------------------------------------
    first_prs = [r["implementation_prs"][0] for r in admitted if r.get("implementation_prs")]
    merged_first = [pr for pr in first_prs if pr.get("merged") is True]
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
    all_prs = [
        pr
        for r in admitted
        for pr in (r.get("implementation_prs") or [])
    ]
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

    # ---- Lifecycle time -----------------------------------------------------
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

    # ---- Requested vs delivered (finite missions) ---------------------------
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

    # ---- Recurrence / learning ----------------------------------------------
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

    return {
        "schema_version": SCHEMA_VERSION,
        "issue": 2766,
        "window": window,
        "records_considered": len(mission_records),
        "admitted": len(admitted),
        "metrics": metrics,
    }
