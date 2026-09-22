"""Deterministic LP2/LP14 comparable-run filtering for LP4."""

from __future__ import annotations

from typing import Any

from instructional_workflow_contracts import ContractValidationError, validate_stable_id

_USABLE_QUALITY = frozenset({"usable", "usable-with-limits"})
_EXCLUDED_QUALITY = frozenset({"unusable", "stale", "contradictory", "too-late", "privacy-blocked"})


def filter_comparable_runs(
    runs: object,
    *,
    objective_ref: str,
    work_mode: str | None,
) -> dict[str, Any]:
    """Filter prior runs using explicit identity/quality evidence, never similarity scores."""
    validate_stable_id(objective_ref, "objective_ref")
    if type(runs) is not list:
        raise ContractValidationError("handoff-wrong-type", "prior_runs must be a built-in list")
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    contexts: set[str] = set()

    for run in runs:
        if type(run) is not dict:
            raise ContractValidationError("handoff-wrong-type", "prior run must be a mapping")
        required = {"run_id", "objective_ref", "work_mode", "quality", "active_minutes", "elapsed_minutes", "context_ref"}
        if set(run) != required:
            raise ContractValidationError("handoff-invalid", "prior run fields are not canonical")
        run_id = validate_stable_id(run["run_id"], "run_id")
        validate_stable_id(run["objective_ref"], "prior objective_ref")
        validate_stable_id(run["context_ref"], "context_ref")
        active = run["active_minutes"]
        elapsed = run["elapsed_minutes"]
        if type(active) not in {int, float} or type(elapsed) not in {int, float} or active < 0 or elapsed <= 0:
            excluded.append({"run_id": run_id, "reason": "lp-evidence-run-interrupted-or-sparse"})
            continue
        if active > elapsed:
            excluded.append({"run_id": run_id, "reason": "lp-evidence-run-interrupted-or-sparse"})
            continue
        quality = run["quality"]
        if quality in _EXCLUDED_QUALITY:
            excluded.append({"run_id": run_id, "reason": "lp-evidence-observation-quality-unusable"})
            continue
        if quality not in _USABLE_QUALITY:
            excluded.append({"run_id": run_id, "reason": "lp-evidence-observation-quality-unusable"})
            continue
        if run["objective_ref"] != objective_ref:
            excluded.append({"run_id": run_id, "reason": "lp-evidence-objective-match-weak"})
            continue
        if work_mode is not None and run["work_mode"] != work_mode:
            excluded.append({"run_id": run_id, "reason": "lp-evidence-work-mode-incompatible"})
            continue
        included.append(run)
        contexts.add(run["context_ref"])

    confidence = "low"
    if len(included) >= 3 and len(contexts) >= 2:
        confidence = "medium"
    return {
        "included": included,
        "excluded": sorted(excluded, key=lambda item: item["run_id"]),
        "included_count": len(included),
        "excluded_count": len(excluded),
        "context_count": len(contexts),
        "comparability_confidence": confidence,
    }
