"""Bounded lifecycle telemetry projection for host execution-batch ceilings (#2753).

This module accepts only host-observed structured facts. It does not inspect
chain-of-thought, infer hidden scheduling, persist mission state, or implement
continuation. Unknown host transitions remain explicit unknown evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


TransitionState = Literal["yes", "no", "unknown"]


@dataclass(frozen=True, slots=True)
class HostBatchLifecycleEvidence:
    parent_mission_identity: str
    batch_identity: str
    tool_budget_exhausted: bool
    last_successful_operation: str | None
    continuation_classification_attempted: TransitionState
    continuation_result_observed: TransitionState
    next_internal_batch_attempted: TransitionState
    terminal_reason: str | None
    execution_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        for name in ("parent_mission_identity", "batch_identity"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip() or len(value) > 256:
                raise ValueError(f"{name} must be bounded non-empty text")
        if type(self.tool_budget_exhausted) is not bool:
            raise TypeError("tool_budget_exhausted must be an exact boolean")
        for name in ("last_successful_operation", "terminal_reason"):
            value = getattr(self, name)
            if value is not None and (type(value) is not str or not value.strip() or len(value) > 512):
                raise ValueError(f"{name} must be None or bounded non-empty text")
        for name in (
            "continuation_classification_attempted",
            "continuation_result_observed",
            "next_internal_batch_attempted",
        ):
            if getattr(self, name) not in {"yes", "no", "unknown"}:
                raise ValueError(f"{name} must use yes/no/unknown")


def classify_ceiling_divergence(evidence: HostBatchLifecycleEvidence) -> str:
    """Return the first supported divergence without inventing unavailable facts."""
    if type(evidence) is not HostBatchLifecycleEvidence:
        raise TypeError("evidence must be exact HostBatchLifecycleEvidence")
    if not evidence.tool_budget_exhausted:
        return "not-a-tool-budget-ceiling"
    if evidence.continuation_classification_attempted == "no":
        return "continuation-classification-not-scheduled"
    if evidence.continuation_classification_attempted == "yes":
        if evidence.continuation_result_observed == "no":
            return "continuation-classification-result-not-observed"
        if evidence.continuation_result_observed == "yes":
            if evidence.next_internal_batch_attempted == "no":
                return "continuation-result-not-consumed-for-next-batch"
            if evidence.next_internal_batch_attempted == "yes":
                return "next-batch-attempted-after-ceiling"
    return "host-lifecycle-transition-unknown"
