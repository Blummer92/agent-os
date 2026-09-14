from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    stable_id: str
    source: str
    revision: str

    def __post_init__(self) -> None:
        for name in ("stable_id", "source", "revision"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty text")


@dataclass(frozen=True, slots=True)
class GradingDecision:
    student: IdentityEvidence
    assignment: IdentityEvidence
    rubric: IdentityEvidence
    proposed_score: float
    feedback: str
    uncertainty: Literal["low", "medium", "high"]
    approval_state: ApprovalState
    provenance: tuple[str, ...]
    requested_target_platforms: tuple[str, ...]
    decision_id: str
    write_authorized: Literal[False] = field(default=False, init=False)
    external_action_authorized: Literal[False] = field(default=False, init=False)

    @property
    def downstream_eligible(self) -> bool:
        return self.approval_state is ApprovalState.APPROVED and self.uncertainty != "high"


def build_grading_decision(
    *,
    student: IdentityEvidence,
    assignment: IdentityEvidence,
    rubric: IdentityEvidence,
    proposed_score: float,
    feedback: str,
    uncertainty: str,
    approval_state: ApprovalState,
    provenance: tuple[str, ...],
    requested_target_platforms: tuple[str, ...],
) -> GradingDecision:
    if type(proposed_score) not in (int, float) or isinstance(proposed_score, bool):
        raise TypeError("proposed_score must be numeric")
    score = float(proposed_score)
    if not 0.0 <= score <= 100.0:
        raise ValueError("proposed_score must be between 0 and 100")
    if not isinstance(feedback, str):
        raise TypeError("feedback must be text")
    if uncertainty not in {"low", "medium", "high"}:
        raise ValueError("uncertainty must be low, medium, or high")
    if not isinstance(approval_state, ApprovalState):
        raise TypeError("approval_state must be ApprovalState")
    provenance = _bounded_strings(provenance, "provenance")
    platforms = _bounded_strings(requested_target_platforms, "requested_target_platforms")
    payload = {
        "student": _identity(student),
        "assignment": _identity(assignment),
        "rubric": _identity(rubric),
        "proposed_score": score,
        "feedback": feedback,
        "uncertainty": uncertainty,
        "approval_state": approval_state.value,
        "provenance": list(provenance),
        "requested_target_platforms": list(platforms),
    }
    digest = hashlib.sha256(
        b"agent-os-grading-decision:v1\0"
        + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return GradingDecision(
        student=student,
        assignment=assignment,
        rubric=rubric,
        proposed_score=score,
        feedback=feedback,
        uncertainty=uncertainty,
        approval_state=approval_state,
        provenance=provenance,
        requested_target_platforms=platforms,
        decision_id=f"grading-decision:{digest}",
    )


def _identity(value: IdentityEvidence) -> dict[str, str]:
    if not isinstance(value, IdentityEvidence):
        raise TypeError("identity evidence must use IdentityEvidence")
    return {"stable_id": value.stable_id, "source": value.source, "revision": value.revision}


def _bounded_strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value or len(value) > 32:
        raise ValueError(f"{name} must be a non-empty tuple of at most 32 values")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{name} values must be non-empty text")
    normalized = tuple(sorted(set(value)))
    if len(normalized) != len(value):
        raise ValueError(f"{name} must not contain duplicates")
    return normalized
