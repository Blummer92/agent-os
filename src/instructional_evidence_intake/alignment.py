"""Deterministic assignment-alignment rules for teacher-confirmed evidence."""

from __future__ import annotations

from typing import Any

DIMENSION_ORDER = (
    ("objective", "objective_refs", "academic"),
    ("prerequisite", "prerequisite_refs", "academic"),
    ("success-criteria", "success_criteria_refs", "academic"),
    ("depth", "depth_demands", "academic"),
    ("performance-format", "performance_formats", "academic"),
    ("tool-or-routine", "tools_and_routines", "context"),
    ("representation", "representation_demands", "context"),
    ("work-mode", "work_modes", "context"),
)


def _overlap(left: list[str], right: list[str]) -> list[str]:
    return sorted(set(left).intersection(right))


def build_alignment(payload: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic dimension findings and a fail-closed disposition."""
    observed = payload["observed_evidence"]
    current = payload["current_assignment"]
    source = payload["source_evidence"]
    context = payload["interpretation_context"]

    uncertain_reasons: list[str] = []
    if not source["privacy_eligible"]:
        uncertain_reasons.append("privacy-ineligible")
    if source["freshness"] != "current":
        uncertain_reasons.append("freshness-not-current")
    if source["measurement_quality"] != "sufficient":
        uncertain_reasons.append("measurement-quality-insufficient")
    if observed["evidence_quality"] == "insufficient":
        uncertain_reasons.append("evidence-quality-insufficient")
    if context["contradictions"]:
        uncertain_reasons.append("contradiction-unresolved")
    if context["uncertainties"]:
        uncertain_reasons.append("uncertainty-unresolved")
    if context["manual_review_requested"]:
        uncertain_reasons.append("manual-review-requested")

    findings: list[dict[str, Any]] = []
    academic_matches: list[str] = []
    context_matches: list[str] = []
    unmatched: list[str] = []

    for name, field, kind in DIMENSION_ORDER:
        matches = _overlap(observed[field], current[field])
        if uncertain_reasons:
            state = "uncertain"
        elif matches and kind == "academic":
            state = "direct-evidence"
            academic_matches.extend(matches)
        elif matches:
            state = "context-evidence"
            context_matches.extend(matches)
        else:
            state = "not-comparable"
            unmatched.append(name)
        findings.append(
            {
                "dimension": name,
                "evidence_kind": kind,
                "matched_refs": matches,
                "disposition": state,
            }
        )

    objective_match = bool(
        _overlap(observed["objective_refs"], current["objective_refs"])
        or _overlap(observed["prerequisite_refs"], current["prerequisite_refs"])
    )
    performance_match = bool(
        _overlap(observed["performance_formats"], current["performance_formats"])
    )
    evaluation_sufficient = observed["evaluation_basis"] in {
        "teacher-confirmed",
        "structured-rule",
    }

    if uncertain_reasons:
        overall = "uncertain"
    elif (
        objective_match
        and performance_match
        and evaluation_sufficient
        and observed["evidence_quality"] == "sufficient"
    ):
        overall = "direct-evidence"
    elif academic_matches:
        overall = "partial-evidence"
    elif context_matches:
        overall = "context-evidence"
    else:
        overall = "not-comparable"

    what_supported = sorted(set(academic_matches + context_matches))
    what_unmeasured = sorted(set(unmatched))
    if not evaluation_sufficient:
        what_unmeasured.append("correctness-without-supplied-evaluation")
        what_unmeasured = sorted(set(what_unmeasured))
        if overall == "direct-evidence":
            overall = "partial-evidence"

    manual_review = overall == "uncertain" or (
        observed["response_type"] == "open-ended"
        and observed["evaluation_basis"] != "teacher-confirmed"
    )
    if manual_review and overall != "uncertain":
        overall = "uncertain"
        uncertain_reasons.append("open-ended-judgment-required")
        findings = [{**finding, "disposition": "uncertain"} for finding in findings]

    confidence = "high"
    if overall in {"partial-evidence", "context-evidence"}:
        confidence = "medium"
    if overall == "uncertain":
        confidence = "low"

    return {
        "dimension_results": findings,
        "overall_disposition": overall,
        "what_supported": what_supported,
        "what_remains_unmeasured": what_unmeasured,
        "evidence_used": sorted(set(what_supported)),
        "evidence_excluded": sorted(set(uncertain_reasons)),
        "prior_opportunity_summary": "Evidence describes class-level prior opportunity only.",
        "transfer_summary": "Transfer remains advisory and limited to named comparable dimensions.",
        "confidence": confidence,
        "confidence_basis": sorted(
            set(
                [
                    f"evidence-quality:{observed['evidence_quality']}",
                    f"evaluation-basis:{observed['evaluation_basis']}",
                    f"measurement-quality:{source['measurement_quality']}",
                ]
                + uncertain_reasons
            )
        ),
        "manual_review_required": manual_review,
        "contradictions": list(context["contradictions"]),
        "uncertainties": list(context["uncertainties"]),
    }
