"""Executable admission gate for classroom-artifact comparative evaluation.

The gate is deliberately pure and offline.  It decides whether the exact artifacts
produced for the requested comparison are safe to hand to a downstream evaluator;
it does not generate artifacts, fetch substitutes, or perform external writes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal


AdmissionStatus = Literal["admit", "blocked"]


@dataclass(frozen=True)
class EvaluatorArtifact:
    """One evaluator input bound to an expected producing arm."""

    arm_id: str
    required_artifact_id: str
    produced_artifact_id: str | None
    artifact_role: str
    required_role: str
    inspectable: bool


@dataclass(frozen=True)
class EvaluatorAdmission:
    status: AdmissionStatus
    artifacts: tuple[EvaluatorArtifact, ...]
    blocked_arms: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def admitted(self) -> bool:
        return self.status == "admit"


def admit_comparative_evaluator(
    artifacts: Iterable[EvaluatorArtifact],
    *,
    minimum_artifacts: int = 2,
) -> EvaluatorAdmission:
    """Fail closed unless every exact producer-bound artifact is evaluator-ready.

    A required arm is blocked when its output is missing, cannot be inspected on
    the evaluator input surface, does not match the exact required producer
    identity, or has the wrong semantic artifact role.  This prevents a
    semantically similar Library/Drive/prior artifact from standing in for a
    missing arm.
    """
    bound = tuple(artifacts)
    reasons: list[str] = []
    blocked: list[str] = []

    if len(bound) < minimum_artifacts:
        reasons.append(
            f"insufficient-artifacts: expected at least {minimum_artifacts}, got {len(bound)}"
        )

    seen_arms: set[str] = set()
    for artifact in bound:
        if not artifact.arm_id or artifact.arm_id in seen_arms:
            reasons.append(f"invalid-arm-binding:{artifact.arm_id or '<missing>'}")
            blocked.append(artifact.arm_id or "<missing>")
            continue
        seen_arms.add(artifact.arm_id)

        arm_reasons: list[str] = []
        if not artifact.produced_artifact_id:
            arm_reasons.append("producer-output-missing")
        elif artifact.produced_artifact_id != artifact.required_artifact_id:
            arm_reasons.append("producer-identity-mismatch")
        if not artifact.inspectable:
            arm_reasons.append("artifact-not-inspectable")
        if artifact.artifact_role != artifact.required_role:
            arm_reasons.append("artifact-role-mismatch")

        if arm_reasons:
            blocked.append(artifact.arm_id)
            reasons.extend(f"{artifact.arm_id}:{reason}" for reason in arm_reasons)

    if reasons:
        return EvaluatorAdmission(
            status="blocked",
            artifacts=bound,
            blocked_arms=tuple(dict.fromkeys(blocked)),
            reasons=tuple(reasons),
        )

    return EvaluatorAdmission(
        status="admit",
        artifacts=bound,
        blocked_arms=(),
        reasons=(),
    )
