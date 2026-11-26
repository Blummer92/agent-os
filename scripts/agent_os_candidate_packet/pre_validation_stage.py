"""Pre-validation candidate inputs for the #1985 first-run evidence seam.

This module intentionally carries only facts available before validation evidence
exists. It delegates canonical subject/plan construction to the existing
validation-stage machinery without making #1104 evidence-reference IDs optional.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from scripts.agent_os_execution_capabilities import RepositoryIdentity, RepositoryStateEvidence
from .approval_stage import ApprovalProjectionStageResult
from .validation_stage import ValidationStageResult, _prepare_bound_validation

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True, kw_only=True)
class PreValidationCandidateInputs:
    """Exact candidate facts available before validation/advisory evidence exists."""

    repository_identity: RepositoryIdentity
    repository_state_evidence: RepositoryStateEvidence
    issue_number: int
    invocation_id: str
    candidate_branch: str
    candidate_sha: str
    tested_sha: str
    evaluator_sha: str
    expected_changed_paths: tuple[str, ...]
    required_tests: tuple[str, ...]
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.repository_identity) is not RepositoryIdentity:
            raise TypeError("repository_identity must be exact RepositoryIdentity")
        if type(self.repository_state_evidence) is not RepositoryStateEvidence:
            raise TypeError("repository_state_evidence must be exact RepositoryStateEvidence")
        if self.repository_state_evidence.repository_identity != self.repository_identity:
            raise ValueError("repository_state_evidence identity must match repository_identity")
        if type(self.issue_number) is not int or self.issue_number <= 0:
            raise TypeError("issue_number must be a positive exact integer")
        for name in ("invocation_id", "candidate_branch"):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise TypeError(f"{name} must be non-empty exact text")
        for name in ("candidate_sha", "tested_sha", "evaluator_sha"):
            value = getattr(self, name)
            if type(value) is not str or not _SHA40_RE.fullmatch(value):
                raise ValueError(f"{name} must be a full lowercase commit SHA")
        for name in ("expected_changed_paths", "required_tests"):
            value = getattr(self, name)
            if type(value) is not tuple or not all(type(item) is str and item for item in value):
                raise TypeError(f"{name} must be an exact tuple of non-empty strings")
            if value != tuple(sorted(set(value))):
                raise ValueError(f"{name} must be sorted and unique")


def prepare_pre_validation_stage(
    approval_projection_stage_result: ApprovalProjectionStageResult,
    candidate_inputs: PreValidationCandidateInputs,
) -> ValidationStageResult:
    """Build the existing canonical PR-less subject/plan from pre-validation facts only."""

    if type(approval_projection_stage_result) is not ApprovalProjectionStageResult:
        raise TypeError("approval_projection_stage_result must be exact ApprovalProjectionStageResult")
    if type(candidate_inputs) is not PreValidationCandidateInputs:
        raise TypeError("candidate_inputs must be exact PreValidationCandidateInputs")

    return _prepare_bound_validation(
        approval_projection_stage_result, candidate_inputs, first_run=True,
    )
