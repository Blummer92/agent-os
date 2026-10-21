"""Evidence-backed per-item admission for an owner-approved finite campaign (#3502).

The #3502 defect: an explicitly approved multi-issue implementation campaign
ended with a generic "blocked" summary for every item although canonical
readiness was never evaluated, CKR6 was never attempted, the concurrency
source was never established, and the repository seam was never searched.

This module is a thin projection over existing owners. It creates no readiness
engine, lease, scheduler, queue, or executor:

- readiness is decided only by the canonical ``evaluate_issue_readiness``,
  executed here on the current issue body, so a label, a missing heading, or
  an owner approval can never stand in for READY;
- managed ``status:*`` labels are compared with the canonical
  ``issue_operational_state`` projection and are never mutated here;
- CKR6 admission is taken only from a canonical result (in-process owner or a
  correlated ``classify_ckr6_ingress_observation``), never synthesized;
- a Scheduler lease is concurrency authority only for Scheduler-run routes;
  missing lease evidence on another route is reported, never fabricated as
  clear or blocked;
- repository-only offline delivery is distinguished from separately
  authorized live acceptance.

Each item is ``admitted``, ``verified-blocker`` (every blocker comes from an
executed canonical evaluation or a supplied verified fact), or
``admission-not-completed`` (a required admission step was not run). Only
verified blockers become finite no-PR lane evidence for
``classify_issue_batch_completion``. Nothing here grants write, merge,
closure, label-mutation, workflow, or external-write authority.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping

from scripts.agent_os_issue_acceptance.issue_operational_state import (
    _MANAGED_READINESS_LABELS,
    ReadinessState,
)
from scripts.agent_os_issue_acceptance.readiness import evaluate_issue_readiness

from .ckr6_github_bridge import INGRESS_OBSERVATION_STATES

ADMITTED = "admitted"
VERIFIED_BLOCKER = "verified-blocker"
ADMISSION_NOT_COMPLETED = "admission-not-completed"

_CKR6_ROUTES = frozenset({"in-process", "github-ingress", "not-run"})
# Canonical CKR6 lesson-retrieval statuses that a returned result may carry.
_CKR6_RESULT_STATUSES = frozenset({
    "not-needed", "sufficient", "unavailable-safe-fallback", "insufficient", "manual-review", "rejected",
})
# Mirrors issue_start_lesson_preflight._ADMISSIBLE: the only statuses that
# admit the first substantial hypothesis.
_CKR6_ADMISSIBLE_STATUSES = frozenset({"not-needed", "sufficient", "unavailable-safe-fallback"})
_EXECUTION_ROUTES = frozenset({"connector-native", "governed-runner", "scheduler", "external-coding-agent"})
# Routes whose execution holds a Workflow Scheduler lease.
_LEASED_ROUTES = frozenset({"governed-runner", "scheduler"})
_LEASE_OBSERVATIONS = frozenset({"not-observed", "clear", "active", "unavailable"})
_SEAM_STATES = frozenset({"identified", "absent-verified", "not-investigated"})
_LIVE_ACCEPTANCE = frozenset({"none", "required-authorized", "required-not-authorized"})
_SHARED_BLOCKERS = frozenset({
    "authorization", "source-of-truth", "bounded-scope", "excluded-surface", "capability", "material-decision",
})
_DELIVERY_OBLIGATIONS = (
    "github-service-agent-writer",
    "one-issue-specific-branch",
    "focused-tests",
    "primary-pr-creation-admission-before-draft-pr",
    "draft-pr",
    "exact-head-readback",
)
_LABEL_BY_READINESS = {state.value: label for state, label in _MANAGED_READINESS_LABELS.items()}


def classify_campaign_item_admission(evidence: Mapping[str, object]) -> dict[str, object]:
    """Classify one campaign item from canonical evidence."""
    if not isinstance(evidence, Mapping):
        raise TypeError("item evidence must be a mapping")
    issue = _positive_int(evidence.get("issue_number"), "issue_number")
    issue_open = _bool(evidence.get("issue_open"), "issue_open")
    body = evidence.get("issue_body")
    if type(body) is not str:
        raise TypeError("issue_body must be the current canonical issue body text")
    labels = _strings(evidence.get("observed_labels", []), "observed_labels")
    ckr6 = _mapping(evidence.get("ckr6"), "ckr6")
    authorized = _bool(evidence.get("implementation_authorized"), "implementation_authorized")
    surfaces = _mapping(evidence.get("excluded_surfaces", {}), "excluded_surfaces")
    concurrency = _mapping(evidence.get("concurrency"), "concurrency")
    seam = _finite(evidence.get("repository_seam"), _SEAM_STATES, "repository_seam")
    seam_refs = _strings(evidence.get("repository_seam_refs", []), "repository_seam_refs")
    live = _finite(evidence.get("live_acceptance", "none"), _LIVE_ACCEPTANCE, "live_acceptance")

    blockers: list[str] = []
    unverified: list[str] = []
    owner_decisions: list[str] = []
    notes: list[str] = []

    if not issue_open:
        blockers.append("issue.not-open")

    readiness = evaluate_issue_readiness(body)
    outcome = readiness.outcome.value
    if outcome == ReadinessState.BLOCKED.value:
        blockers.append("readiness.blocked")
        owner_decisions.extend(readiness.report.blockers)
    elif outcome == ReadinessState.NEEDS_DECISION.value:
        blockers.append("readiness.needs-decision")
        owner_decisions.extend(readiness.report.manual_review_items)

    label = _label_projection(outcome, labels)
    if label["state"] == "conflicting":
        blockers.append("label.status-conflict")
    elif label["state"] == "mechanical-drift":
        notes.append("label.mechanical-drift-projection-repair-only")

    ckr6_state = _ckr6(ckr6)
    if ckr6_state["verified_blocker"] is not None:
        blockers.append(ckr6_state["verified_blocker"])
    elif ckr6_state["unverified"] is not None:
        unverified.append(ckr6_state["unverified"])

    if not authorized:
        blockers.append("authorization.implementation-not-granted")
        owner_decisions.append(f"Authorize bounded repository-only implementation of #{issue}.")
    required = set(_strings(surfaces.get("required", []), "excluded_surfaces.required"))
    granted = set(_strings(surfaces.get("separately_authorized", []), "excluded_surfaces.separately_authorized"))
    for surface in sorted(required - granted):
        blockers.append(f"authorization.excluded-surface:{surface}")
        owner_decisions.append(f"Separately authorize the exact {surface} change for #{issue}, or remove it from scope.")

    concurrency_state = _concurrency(concurrency)
    blockers.extend(concurrency_state["blockers"])
    unverified.extend(concurrency_state["unverified"])
    notes.extend(concurrency_state["notes"])

    if seam == "not-investigated":
        unverified.append("repository-seam.not-investigated")
    elif seam == "absent-verified":
        blockers.append("repository-seam.absent")
        owner_decisions.append(
            f"Decide where #{issue}'s repository seam belongs, or route it as host-only work."
        )
    elif not seam_refs:
        raise ValueError("an identified repository seam requires repository_seam_refs")

    live_pending = live == "required-not-authorized"
    if live_pending:
        notes.append("live-acceptance.separately-authorized-pending")

    if blockers:
        state = VERIFIED_BLOCKER
        next_action = "report-verified-item-blocker-and-continue-independent-items"
    elif unverified:
        state = ADMISSION_NOT_COMPLETED
        next_action = "complete-admission:" + ",".join(unverified)
    else:
        state = ADMITTED
        next_action = (
            "resume-existing-primary-pr" if concurrency_state["active_primary_prs"] == 1
            else "route-github-service-agent-branch-draft-pr"
        )

    return {
        "issue_number": issue,
        "admission_state": state,
        "verified_blocker_codes": blockers,
        "unverified_checks": unverified,
        "notes": notes,
        "next_action": next_action,
        "owner_decision_required": owner_decisions if state == VERIFIED_BLOCKER else [],
        "readiness": {
            "evaluator": "scripts.agent_os_issue_acceptance.readiness.evaluate_issue_readiness",
            "outcome": outcome,
            "checks": [
                {"name": check.name, "status": check.status.value, "evidence": list(check.evidence)}
                for check in readiness.report.checks
            ],
            "blockers": list(readiness.report.blockers),
            "manual_review_items": list(readiness.report.manual_review_items),
        },
        "label": label,
        "ckr6": ckr6_state["projection"],
        "concurrency": concurrency_state["projection"],
        "repository_seam": {"state": seam, "refs": seam_refs},
        "offline_delivery_admissible": state == ADMITTED,
        "live_acceptance": live,
        "live_acceptance_pending": live_pending,
        "delivery_obligations": list(_DELIVERY_OBLIGATIONS) if state == ADMITTED else [],
        "lane_evidence": _lane_evidence(issue, state, blockers),
        "label_mutation_performed": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "issue_closure_authorized": False,
        "workflow_authorized": False,
        "external_write_authorized": False,
    }


def classify_campaign_admission(
    items: list[Mapping[str, object]], *, shared_blockers: list[str] | None = None
) -> dict[str, object]:
    """Classify every item of one finite campaign in its supplied order.

    Item-local blockers never stop independent items. Only a supplied shared
    blocker (authorization, source of truth, bounded scope, excluded surface,
    capability, or material decision) stops the remaining non-terminal items,
    and each stopped item still keeps its own evidence row.
    """
    if type(items) is not list or not items:
        raise ValueError("items must be a non-empty list")
    shared = _strings(shared_blockers or [], "shared_blockers")
    unknown = sorted(set(shared) - _SHARED_BLOCKERS)
    if unknown:
        raise ValueError(f"unsupported shared blockers: {unknown}")
    results = [classify_campaign_item_admission(item) for item in items]
    numbers = [item["issue_number"] for item in results]
    if len(set(numbers)) != len(numbers):
        raise ValueError("campaign items must be unique issues")

    rows = []
    for result in results:
        disposition = result["admission_state"]
        if shared and disposition != VERIFIED_BLOCKER:
            disposition = "blocked-shared"
        rows.append({**result, "campaign_disposition": disposition})
    incomplete = [row["issue_number"] for row in rows if row["campaign_disposition"] == ADMISSION_NOT_COMPLETED]
    admitted = [row["issue_number"] for row in rows if row["campaign_disposition"] == ADMITTED]
    return {
        "items": rows,
        "admitted_issue_numbers": admitted,
        "verified_blocker_issue_numbers": [
            row["issue_number"] for row in rows if row["campaign_disposition"] == VERIFIED_BLOCKER
        ],
        "admission_not_completed_issue_numbers": incomplete,
        "shared_blockers": shared,
        "stop_permitted": not incomplete and not admitted,
        "next_actions": {str(row["issue_number"]): row["next_action"] for row in rows},
        "generic_blocked_summary_permitted": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "issue_closure_authorized": False,
    }


def _label_projection(outcome: str, labels: list[str]) -> dict[str, object]:
    observed = sorted(label for label in labels if label.startswith("status:"))
    expected = _LABEL_BY_READINESS.get(outcome)
    if not observed:
        state = "absent"
    elif observed == [expected]:
        state = "consistent"
    elif outcome == ReadinessState.READY.value and len(observed) == 1 and observed[0] in _LABEL_BY_READINESS.values():
        # Mirrors issue_operational_state: one stale managed label cannot veto
        # canonical READY; it is a projection-repair obligation only.
        state = "mechanical-drift"
    else:
        state = "conflicting"
    return {"observed_status_labels": observed, "expected_status_label": expected, "state": state}


def _ckr6(value: Mapping[str, object]) -> dict[str, object]:
    route = _finite(value.get("route"), _CKR6_ROUTES, "ckr6.route")
    admissible = value.get("substantial_hypothesis_admissible", False)
    if type(admissible) is not bool:
        raise TypeError("ckr6.substantial_hypothesis_admissible must be a built-in bool")
    projection: dict[str, object] = {"route": route, "substantial_hypothesis_admissible": admissible}
    if route == "not-run":
        return {"projection": projection, "verified_blocker": None, "unverified": "ckr6.not-run"}
    if route == "github-ingress":
        state = _finite(value.get("observation_state"), INGRESS_OBSERVATION_STATES, "ckr6.observation_state")
        projection["observation_state"] = state
        if state != "result-returned":
            if admissible:
                raise ValueError("only a returned CKR6 result can be admissible")
            return {"projection": projection, "verified_blocker": None, "unverified": f"ckr6.{state}"}
    status = _finite(value.get("result_status"), _CKR6_RESULT_STATUSES, "ckr6.result_status")
    projection["result_status"] = status
    if admissible is not (status in _CKR6_ADMISSIBLE_STATUSES):
        raise ValueError("ckr6 admissibility must match the canonical result status")
    if admissible:
        return {"projection": projection, "verified_blocker": None, "unverified": None}
    return {"projection": projection, "verified_blocker": f"ckr6.{status}", "unverified": None}


def _concurrency(value: Mapping[str, object]) -> dict[str, object]:
    route = _finite(value.get("execution_route"), _EXECUTION_ROUTES, "concurrency.execution_route")
    lease = _finite(value.get("lease_observation", "not-observed"), _LEASE_OBSERVATIONS, "concurrency.lease_observation")
    raw_prs = value.get("active_primary_prs", [])
    if type(raw_prs) is not list or any(type(item) is not int or item < 1 for item in raw_prs):
        raise TypeError("concurrency.active_primary_prs must be a list of positive integers")
    if len(set(raw_prs)) != len(raw_prs):
        raise ValueError("concurrency.active_primary_prs must be unique")
    blockers: list[str] = []
    unverified: list[str] = []
    notes: list[str] = []
    if len(raw_prs) > 1:
        blockers.append("claim.multiple-primary")
    if lease == "active":
        blockers.append("lease.active")
    elif route in _LEASED_ROUTES:
        if lease in {"not-observed", "unavailable"}:
            unverified.append("lease.evidence-unavailable")
    elif lease != "clear":
        # No Scheduler lease exists for this route; absence of lease evidence
        # is neither clearance nor a blocker.
        notes.append("lease.not-applicable-for-route")
    lease_authority = "workflow-scheduler-lease" if route in _LEASED_ROUTES else "not-applicable"
    return {
        "blockers": blockers,
        "unverified": unverified,
        "notes": notes,
        "active_primary_prs": len(raw_prs),
        "projection": {
            "execution_route": route,
            "authority": "github-primary-pr-claims",
            "lease_authority": lease_authority,
            "lease_observation": lease,
            "active_primary_prs": sorted(raw_prs),
        },
    }


def _lane_evidence(issue: int, state: str, blockers: list[str]) -> dict[str, object] | None:
    """Finite no-PR lane evidence for ``classify_issue_batch_completion``.

    Only a verified blocker yields terminal no-PR evidence; an incomplete
    admission yields none, so the batch classifier keeps that lane open.
    """
    if state != VERIFIED_BLOCKER:
        return None
    if "repository-seam.absent" in blockers:
        reason, gap = "no-repository-seam", "no"
    elif any(code.startswith("authorization.") for code in blockers):
        reason, gap = "authorization-blocked", "yes"
    else:
        reason, gap = "material-decision-required", "yes"
    return {
        "issue_number": issue,
        "current_state": "verified-blocker:" + blockers[0],
        "repository_gap": gap,
        "implementation_authorized": False,
        "pr_required": "no",
        "pr_number": None,
        "no_pr_reason": reason,
        "canonical_no_pr_evidence_verified": True,
        "remaining_owner": "repository owner",
    }


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def _strings(value: object, name: str) -> list[str]:
    if type(value) is not list or any(type(item) is not str or not item.strip() for item in value):
        raise TypeError(f"{name} must be a list of non-empty strings")
    return list(value)


def _finite(value: object, allowed: frozenset[str], name: str) -> str:
    if type(value) is not str or value not in allowed:
        raise ValueError(f"{name} must be one of {sorted(allowed)}")
    return value


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a built-in bool")
    return value


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise TypeError(f"{name} must be a positive built-in integer")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evidence", required=True, help="JSON file: {items: [...], shared_blockers: [...]}")
    args = parser.parse_args(argv)
    payload = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("evidence file must contain one JSON object")
    result = classify_campaign_admission(
        list(payload.get("items", [])), shared_blockers=list(payload.get("shared_blockers", []))
    )
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ADMISSION_NOT_COMPLETED",
    "ADMITTED",
    "VERIFIED_BLOCKER",
    "classify_campaign_admission",
    "classify_campaign_item_admission",
]
