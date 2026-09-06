"""Bounded, non-authorizing ChatGPT MCP facade for Agent OS (#1966).

This module is deliberately transport-neutral.  It exposes the two finite tool
contracts used by the MCP protocol binding while reusing existing Agent OS
owners instead of creating a second router, discovery index, Scheduler, lease,
or write authority.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Literal, TypedDict

from agent_os_execution_service.execution_surface_availability import (
    ExecutionSurfaceAvailabilityOutcome,
)
from scripts.agent_os_execution_interface.post_selection_continuation import (
    ContinuationLineage,
    NonAbsorbedDomain,
    PostSelectionAttemptEvidence,
    PriorAttemptEffect,
    classify_post_selection_continuation,
)

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)
_HANDOFF_RE = re.compile(r"^executor-handoff:[0-9a-f]{64}$", re.ASCII)


class AgentOsContinuationPlan(TypedDict):
    status: Literal["agent-os-route", "needs-decision"]
    repository: str
    issue_number: int
    next_operation: Literal[
        "discover-current-handoff",
        "resume-existing-handoff",
        "reconcile-currentness",
    ]
    handoff_id: str | None
    ingress: str | None
    execution_authorized: Literal[False]
    github_writes_authorized: Literal[False]
    scheduler_invoked: Literal[False]
    side_effects_performed: Literal[False]


def _repository(value: object) -> str:
    if type(value) is not str or _REPOSITORY_RE.fullmatch(value) is None:
        raise ValueError("repository must use bounded owner/name syntax")
    return value


def _issue_number(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("issue_number must be a positive built-in integer")
    return value


def _handoff_id(value: object | None) -> str | None:
    if value is None:
        return None
    if type(value) is not str or _HANDOFF_RE.fullmatch(value) is None:
        raise ValueError("handoff_id must be a canonical executor-handoff identity")
    return value


def plan_agent_os_continuation(
    *, repository: str, issue_number: int, canonical_handoff_id: str | None = None
) -> AgentOsContinuationPlan:
    """Return one finite, non-authorizing Agent OS next-action receipt.

    ``canonical_handoff_id`` may be supplied only when a canonical upstream tool
    has already produced it.  This facade validates and preserves that identity;
    it never discovers, synthesizes, ranks, or guesses a handoff itself.  With no
    handoff, the only admitted next operation is the existing server-side
    discovery path owned by #1242/#1218.
    """

    repo = _repository(repository)
    issue = _issue_number(issue_number)
    handoff = _handoff_id(canonical_handoff_id)
    if handoff is None:
        return {
            "status": "agent-os-route",
            "repository": repo,
            "issue_number": issue,
            "next_operation": "discover-current-handoff",
            "handoff_id": None,
            "ingress": None,
            "execution_authorized": False,
            "github_writes_authorized": False,
            "scheduler_invoked": False,
            "side_effects_performed": False,
        }
    return {
        "status": "agent-os-route",
        "repository": repo,
        "issue_number": issue,
        "next_operation": "resume-existing-handoff",
        "handoff_id": handoff,
        "ingress": f"/agent-os resume {handoff}",
        "execution_authorized": False,
        "github_writes_authorized": False,
        "scheduler_invoked": False,
        "side_effects_performed": False,
    }


def classify_agent_os_continuation(
    *,
    repository: str,
    issue_number: int,
    operation_id: str,
    surface_outcome: str,
    approved_alternative_capability: str | None = None,
    branch: str | None = None,
    pull_request: int | None = None,
    checkpoint_id: str | None = None,
    lease_id: str | None = None,
    prior_effect: str = "none-proven",
    target_identity_reacquired: bool = False,
    requires_exact_blob_identity: bool = False,
    exact_blob_identity_reacquired: bool = False,
    runtime_surface_transition: bool = False,
    evidence_compatibility_confirmed: bool = False,
    active_foreign_lease: bool = False,
    equivalent_transition_repeated: bool = False,
    material_decision_required: bool = False,
    alternative_widens_authority: bool = False,
    non_absorbed_domain: str | None = None,
) -> dict[str, object]:
    """Project bounded structured attempt evidence through #1237's owner.

    The MCP facade does not define a continuation vocabulary.  It constructs the
    existing #1237 evidence model and delegates exactly once to
    ``classify_post_selection_continuation``.
    """

    repo = _repository(repository)
    issue = _issue_number(issue_number)
    if type(operation_id) is not str or not operation_id:
        raise ValueError("operation_id must be non-empty exact text")
    try:
        outcome = ExecutionSurfaceAvailabilityOutcome(surface_outcome)
        effect = PriorAttemptEffect(prior_effect)
        domain = None if non_absorbed_domain is None else NonAbsorbedDomain(non_absorbed_domain)
    except ValueError as exc:
        raise ValueError("unsupported finite Agent OS continuation value") from exc

    lineage = ContinuationLineage(
        repository=repo,
        issue_number=issue,
        branch=branch,
        pull_request=pull_request,
        checkpoint_id=checkpoint_id,
        lease_id=lease_id,
    )
    decision = classify_post_selection_continuation(
        PostSelectionAttemptEvidence(
            operation_id=operation_id,
            lineage=lineage,
            surface_outcome=outcome,
            approved_alternative_capability=approved_alternative_capability,
            alternative_widens_authority=alternative_widens_authority,
            prior_effect=effect,
            target_identity_reacquired=target_identity_reacquired,
            requires_exact_blob_identity=requires_exact_blob_identity,
            exact_blob_identity_reacquired=exact_blob_identity_reacquired,
            runtime_surface_transition=runtime_surface_transition,
            evidence_compatibility_confirmed=evidence_compatibility_confirmed,
            active_foreign_lease=active_foreign_lease,
            equivalent_transition_repeated=equivalent_transition_repeated,
            material_decision_required=material_decision_required,
            non_absorbed_domain=domain,
        )
    )
    payload = asdict(decision)
    payload["classification"] = decision.classification.value
    payload["reason_codes"] = [item.value for item in decision.reason_codes]
    payload["obligations"] = [item.value for item in decision.obligations]
    payload["lineage"] = asdict(decision.lineage)
    return payload
