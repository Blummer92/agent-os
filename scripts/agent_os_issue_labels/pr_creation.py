"""Fail-safe pull-request creation admission for Agent OS.

The connected GitHub create-pull-request surface defaults ``draft`` to false when
callers omit the argument. Agent OS policy requires the opposite behavior for
ordinary implementation PRs. This pure contract makes the required caller intent
explicit before any GitHub mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PullRequestCreationState(str, Enum):
    DRAFT = "draft"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class PullRequestCreationDecision:
    state: PullRequestCreationState
    draft: bool
    mutation_allowed: bool
    reason_codes: tuple[str, ...]


def decide_pull_request_creation(
    *,
    ready_requested: bool | None = None,
    ready_transition_authorized: bool = False,
    exact_head_validation_passed: bool = False,
    blockers_resolved: bool = False,
) -> PullRequestCreationDecision:
    """Return the explicit Draft/Ready argument for a PR creation call.

    Omitted or ambiguous readiness intent is fail-safe Draft. A caller may create
    directly Ready only when it explicitly requests Ready and supplies all
    existing Ready-for-Review prerequisites. This function grants no merge,
    closure, workflow, protected-setting, production, or external-write authority.
    """
    for name, value in (
        ("ready_transition_authorized", ready_transition_authorized),
        ("exact_head_validation_passed", exact_head_validation_passed),
        ("blockers_resolved", blockers_resolved),
    ):
        if type(value) is not bool:
            raise ValueError(f"{name} must be a boolean")
    if ready_requested is not None and type(ready_requested) is not bool:
        raise ValueError("ready_requested must be a boolean or None")

    if ready_requested is not True:
        return PullRequestCreationDecision(
            state=PullRequestCreationState.DRAFT,
            draft=True,
            mutation_allowed=True,
            reason_codes=("draft-by-default", "explicit-draft-argument-required"),
        )

    missing: list[str] = []
    if not ready_transition_authorized:
        missing.append("ready-transition-not-authorized")
    if not exact_head_validation_passed:
        missing.append("exact-head-validation-not-passed")
    if not blockers_resolved:
        missing.append("blockers-unresolved")
    if missing:
        return PullRequestCreationDecision(
            state=PullRequestCreationState.DRAFT,
            draft=True,
            mutation_allowed=True,
            reason_codes=("ready-request-fails-safe-to-draft", *missing),
        )

    return PullRequestCreationDecision(
        state=PullRequestCreationState.READY,
        draft=False,
        mutation_allowed=True,
        reason_codes=("explicit-ready-request", "ready-prerequisites-satisfied"),
    )
