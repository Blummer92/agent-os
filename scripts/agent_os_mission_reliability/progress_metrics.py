"""Measure completion and human intervention from durable mission evidence."""

from .metrics import _metric


def completion(mission_records, admitted, window):
    """Return the completion metric rows without mutating the inputs."""
    metrics = []
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
    return metrics


def interaction(admitted, window):
    """Return the interaction metric rows without mutating the inputs."""
    metrics = []
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
    return metrics
