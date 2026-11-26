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
from scripts.agent_os_remote_validation import (
    PrePrValidationPlan,
    PrePrValidationSubject,
    load_rule_map,
    pre_pr_validation_plan_id,
    pre_pr_validation_subject_id,
    select_pre_pr_validation_plan,
)

from .approval_stage import ApprovalProjectionStageResult, ApprovalProjectionStageStatus
from .validation_stage import ValidationStageDisposition, ValidationStageResult

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

    upstream = approval_projection_stage_result
    if upstream.status is not ApprovalProjectionStageStatus.COMPLETE:
        return _blocked("upstream-projection-not-complete")
    projection = upstream.projection
    if projection is None or not getattr(projection, "complete", False):
        return _blocked("upstream-projection-missing")

    repository = getattr(projection, "repository", None)
    base_branch = getattr(projection, "base_branch", None)
    base_sha = getattr(projection, "evaluated_repository_sha", None)
    tested_sha = getattr(projection, "tested_repository_sha", None)
    evaluator_sha = getattr(projection, "evaluator_commit_sha", None)
    allowed_files = tuple(getattr(projection, "allowed_files", ()))
    forbidden_paths = tuple(getattr(projection, "forbidden_paths", ()))
    required_tests = tuple(getattr(projection, "required_tests", ()))

    identity_repository = (
        f"{candidate_inputs.repository_identity.owner}/"
        f"{candidate_inputs.repository_identity.repository}"
    )
    if type(repository) is not str or repository.casefold() != identity_repository.casefold():
        return _blocked("repository-binding-mismatch")
    if candidate_inputs.tested_sha != tested_sha:
        return _blocked("tested-sha-mismatch")
    if candidate_inputs.evaluator_sha != evaluator_sha:
        return _blocked("evaluator-sha-mismatch")
    if candidate_inputs.required_tests != required_tests:
        return _blocked("required-tests-mismatch")
    if candidate_inputs.repository_state_evidence.tested_sha != tested_sha:
        return _blocked("repository-evidence-tested-sha-mismatch")
    if any(path not in allowed_files for path in candidate_inputs.expected_changed_paths):
        return _blocked("expected-changed-paths-outside-allowlist")

    try:
        subject = PrePrValidationSubject(
            repository=repository,
            issue_number=candidate_inputs.issue_number,
            invocation_id=candidate_inputs.invocation_id,
            base_branch=base_branch,
            base_sha=base_sha,
            branch=candidate_inputs.candidate_branch,
            expected_source_sha=candidate_inputs.candidate_sha,
            tested_sha=candidate_inputs.tested_sha,
            allowed_files=allowed_files,
            forbidden_paths=forbidden_paths,
            required_command_identities=required_tests,
            approval_id=getattr(projection, "approval_id", ""),
            approval_revision=getattr(projection, "approval_revision_number", 0),
            projection_id=getattr(projection, "projection_id", ""),
            implementation_contract_fingerprint=getattr(
                projection, "implementation_contract_fingerprint", ""
            ),
            expected_changed_paths=candidate_inputs.expected_changed_paths,
            execution_mode="validation-only",
            candidate_bound=True,
        )
        plan = select_pre_pr_validation_plan(subject, load_rule_map())
    except (TypeError, ValueError):
        return _blocked("canonical-validation-construction-failed")

    return ValidationStageResult(
        disposition=ValidationStageDisposition.GO,
        subject=subject,
        validation_plan=plan,
        subject_id=pre_pr_validation_subject_id(subject),
        validation_plan_id=pre_pr_validation_plan_id(plan),
        repository=repository,
        issue_number=candidate_inputs.issue_number,
        invocation_id=candidate_inputs.invocation_id,
        base_sha=base_sha,
        source_sha=candidate_inputs.candidate_sha,
        tested_sha=candidate_inputs.tested_sha,
        evaluator_sha=candidate_inputs.evaluator_sha,
        candidate_sha=candidate_inputs.candidate_sha,
    )


def _blocked(reason: str) -> ValidationStageResult:
    return ValidationStageResult(
        disposition=ValidationStageDisposition.BLOCKED,
        subject=None,
        validation_plan=None,
        subject_id=None,
        validation_plan_id=None,
        repository=None,
        issue_number=None,
        invocation_id=None,
        base_sha=None,
        source_sha=None,
        tested_sha=None,
        evaluator_sha=None,
        candidate_sha=None,
        reason_codes=(reason,),
    )
