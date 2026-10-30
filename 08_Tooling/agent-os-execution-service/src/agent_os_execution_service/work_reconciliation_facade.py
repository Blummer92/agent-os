"""Read-only #3308 request-triage composition over already-acquired canonical evidence.

This is a host-consumed adapter, not a second search service, registry, classifier,
GitHub client, lifecycle evaluator, or issue-creation authority. The host acquires
bounded complete GitHub issue evidence, #3441 PR lineage, capability registry
matches, and conditional #3307 navigation preflight through their existing owners.
"""

from __future__ import annotations

_MAX_MATCHES = 128
_LINEAGE_KEYS = frozenset({
    "issue_number", "state", "match", "state_reason", "lifecycle_stage",
    "successor_issue_number", "successor_state", "successor_lifecycle_stage",
})
_CAPABILITY_KEYS = frozenset({"capability_id", "status"})
_EVIDENCE_KEYS = frozenset({
    "subject", "github_search_complete", "github_issue_evidence_current",
    "pr_lineage_evidence_current", "capability_registry_evidence_current",
    "lineage", "capabilities", "navigation_applicable",
    "navigation_evidence_current", "navigation_outcome",
})


def reconcile_proposed_work_for_host(evidence: dict[str, object]) -> dict[str, object]:
    """Return the classifier disposition or a fail-closed manual-review result.

    Caller-provided source/currentness assertions are *required* but never
    themselves grant any mutation or create authority. A title-keyword search,
    skipped pages, unverified GitHub issue/PR evidence, or missing registry
    acquisition must be represented as incomplete, not as zero matches.
    """
    # #3308: The privileged offline host-installer does not yet install the
    # Navigation Registry wheel. Keep existing MCP tools importable; a call
    # requiring the classifier fails closed instead of taking down the server.
    # This does not establish host activation or package-install authority.
    try:
        from navigation_registry.reconciliation import (
            CapabilityMatch,
            LineageCandidate,
            ReconciliationInput,
            classify_proposed_work,
        )
    except ImportError:
        return {
            "disposition": "manual-review",
            "reason_codes": ["triage.canonical-classifier-unavailable"],
            "owner_issue_number": None,
            "capability_id": None,
            "evidence_issue_numbers": [],
            "input_digest": None,
            "contract_version": "1.0",
            "live_verification_required": True,
            "authorizes_issue_creation": False,
            "authorizes_mutation": False,
            "execution_authorized": False,
            "source_evidence_complete": False,
        }

    subject = evidence.get("subject") if type(evidence) is dict else None
    if type(subject) is not str or not subject.strip() or len(subject) > 2048:
        subject = "unverified-proposed-work"

    def manual(reason: str) -> dict[str, object]:
        projected = classify_proposed_work(
            ReconciliationInput(subject=subject, github_search_complete=False)
        ).to_dict()
        projected["reason_codes"] = [reason, *projected["reason_codes"]]
        projected["source_evidence_complete"] = False
        return projected

    if type(evidence) is not dict or set(evidence) != _EVIDENCE_KEYS:
        return manual("triage.input-shape-incomplete")
    flags = (
        "github_search_complete", "github_issue_evidence_current",
        "pr_lineage_evidence_current", "capability_registry_evidence_current",
        "navigation_applicable", "navigation_evidence_current",
    )
    if any(type(evidence[key]) is not bool for key in flags):
        return manual("triage.source-flags-invalid")
    if not all(evidence[key] for key in flags[:4]):
        return manual("triage.github-or-registry-evidence-unverified")
    if evidence["navigation_applicable"] and not evidence["navigation_evidence_current"]:
        return manual("triage.navigation-evidence-unverified")

    rows, capabilities = evidence["lineage"], evidence["capabilities"]
    if (
        type(rows) is not list or type(capabilities) is not list
        or len(rows) > _MAX_MATCHES or len(capabilities) > _MAX_MATCHES
    ):
        return manual("triage.evidence-population-invalid")
    try:
        lineage = []
        for row in rows:
            if (
                type(row) is not dict
                or not {"issue_number", "state", "match"} <= set(row)
                or not set(row) <= _LINEAGE_KEYS
            ):
                return manual("triage.lineage-row-malformed")
            lineage.append(LineageCandidate(**row))
        matches = []
        for match in capabilities:
            if type(match) is not dict or set(match) != _CAPABILITY_KEYS:
                return manual("triage.capability-row-malformed")
            matches.append(CapabilityMatch(**match))
        result = classify_proposed_work(ReconciliationInput(
            subject=subject,
            github_search_complete=True,
            lineage=tuple(lineage),
            capabilities=tuple(matches),
            navigation_applicable=evidence["navigation_applicable"],
            navigation_outcome=evidence["navigation_outcome"],
        ))
    except (TypeError, ValueError):
        return manual("triage.evidence-conflicting-or-invalid")

    output = result.to_dict()
    output["source_evidence_complete"] = True
    return output
