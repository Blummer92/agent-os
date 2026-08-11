"""Pure-local pre-PR validation packet preparation for AOS-AUTO1E (#754).

This stage consumes only the already-complete #753 approval/projection result and
explicit candidate/runtime evidence. It reuses the canonical candidate-bound
pre-PR validation subject and selector introduced by #1030. It never runs a
command, invokes a Scheduler lifecycle, or creates execution authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
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

from .approval_stage import (
    ApprovalProjectionStageResult,
    ApprovalProjectionStageStatus,
)

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


class ValidationStageDisposition(str, Enum):
    GO = "GO"
    NO_GO = "NO-GO"
    BLOCKED = "BLOCKED"
    NEEDS_DECISION = "NEEDS-DECISION"


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateRuntimeInputs:
    """Explicit candidate/runtime evidence; no field grants execution authority.

    Runtime-only values are carried here so ``execution_packet_stage`` can bind
    the canonical execution-service request and #1032 runtime-configuration
    seam without asking a caller to copy identities between intermediate
    objects. The evidence IDs are prior immutable evidence references; this
    stage never manufactures validation outcomes.
    """

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
    created_at: str
    expires_at: str
    evaluated_at: str
    repository_root: str
    workspace_parent: str
    validation_bundle_id: str
    advisory_result_id: str
    advisory_render_id: str
    request_revision: int = 1
    canonical_owner: str = "integration-manager"
    requesting_actor: str = "github-service-agent"
    inspected_file_count_limit: int = 10_000
    inspected_byte_limit: int = 50_000_000
    per_command_timeout_seconds: int = 30
    total_timeout_seconds: int = 300
    max_output_bytes: int = 65_536
    runtime_capability_available: bool = True
    execution_authorization_present: bool = False
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    automatic_retry: Literal[False] = field(default=False, init=False)
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
        if type(self.request_revision) is not int or self.request_revision <= 0:
            raise TypeError("request_revision must be a positive exact integer")
        for name in (
            "invocation_id",
            "candidate_branch",
            "created_at",
            "expires_at",
            "evaluated_at",
            "repository_root",
            "workspace_parent",
            "validation_bundle_id",
            "advisory_result_id",
            "advisory_render_id",
            "canonical_owner",
            "requesting_actor",
        ):
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
        for name in (
            "inspected_file_count_limit",
            "inspected_byte_limit",
            "per_command_timeout_seconds",
            "total_timeout_seconds",
            "max_output_bytes",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise TypeError(f"{name} must be a positive exact integer")
        if self.per_command_timeout_seconds > 30:
            raise ValueError("per-command timeout exceeds canonical 30-second ceiling")
        if self.total_timeout_seconds > 300:
            raise ValueError("total timeout exceeds canonical 300-second ceiling")
        if self.max_output_bytes > 65_536:
            raise ValueError("max_output_bytes exceeds canonical runtime ceiling")
        if type(self.runtime_capability_available) is not bool:
            raise TypeError("runtime_capability_available must be exact bool")
        if type(self.execution_authorization_present) is not bool:
            raise TypeError("execution_authorization_present must be exact bool")


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationStageResult:
    disposition: ValidationStageDisposition
    subject: PrePrValidationSubject | None
    validation_plan: PrePrValidationPlan | None
    subject_id: str | None
    validation_plan_id: str | None
    repository: str | None
    issue_number: int | None
    invocation_id: str | None
    base_sha: str | None
    source_sha: str | None
    tested_sha: str | None
    evaluator_sha: str | None
    candidate_sha: str | None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    automatic_retry: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.disposition) is not ValidationStageDisposition:
            raise TypeError("disposition must be ValidationStageDisposition")
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        if self.disposition is ValidationStageDisposition.GO:
            if type(self.subject) is not PrePrValidationSubject or type(self.validation_plan) is not PrePrValidationPlan:
                raise ValueError("GO requires canonical subject and validation plan")
            if not self.subject_id or not self.validation_plan_id:
                raise ValueError("GO requires subject and plan identities")
        elif self.subject is not None or self.validation_plan is not None:
            raise ValueError("non-GO validation results cannot carry partial canonical objects")


def prepare_validation_stage(
    approval_projection_stage_result: ApprovalProjectionStageResult,
    candidate_runtime_inputs: CandidateRuntimeInputs,
) -> ValidationStageResult:
    """Construct the canonical candidate-bound subject and validation plan only."""

    if type(approval_projection_stage_result) is not ApprovalProjectionStageResult:
        raise TypeError("approval_projection_stage_result must be exact ApprovalProjectionStageResult")
    if type(candidate_runtime_inputs) is not CandidateRuntimeInputs:
        raise TypeError("candidate_runtime_inputs must be exact CandidateRuntimeInputs")

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
        f"{candidate_runtime_inputs.repository_identity.owner}/"
        f"{candidate_runtime_inputs.repository_identity.repository}"
    )
    if type(repository) is not str or repository.casefold() != identity_repository.casefold():
        return _blocked("repository-binding-mismatch")
    if candidate_runtime_inputs.tested_sha != tested_sha:
        return _blocked("tested-sha-mismatch")
    if candidate_runtime_inputs.evaluator_sha != evaluator_sha:
        return _blocked("evaluator-sha-mismatch")
    if candidate_runtime_inputs.required_tests != required_tests:
        return _blocked("required-tests-mismatch")
    if candidate_runtime_inputs.repository_state_evidence.tested_sha != tested_sha:
        return _blocked("repository-evidence-tested-sha-mismatch")
    if any(path not in allowed_files for path in candidate_runtime_inputs.expected_changed_paths):
        return _blocked("expected-changed-paths-outside-allowlist")

    try:
        subject = PrePrValidationSubject(
            repository=repository,
            issue_number=candidate_runtime_inputs.issue_number,
            invocation_id=candidate_runtime_inputs.invocation_id,
            base_branch=base_branch,
            base_sha=base_sha,
            branch=candidate_runtime_inputs.candidate_branch,
            expected_source_sha=candidate_runtime_inputs.candidate_sha,
            tested_sha=candidate_runtime_inputs.tested_sha,
            allowed_files=allowed_files,
            forbidden_paths=forbidden_paths,
            required_command_identities=required_tests,
            approval_id=getattr(projection, "approval_id", ""),
            approval_revision=getattr(projection, "approval_revision_number", 0),
            projection_id=getattr(projection, "projection_id", ""),
            implementation_contract_fingerprint=getattr(
                projection, "implementation_contract_fingerprint", ""
            ),
            expected_changed_paths=candidate_runtime_inputs.expected_changed_paths,
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
        issue_number=candidate_runtime_inputs.issue_number,
        invocation_id=candidate_runtime_inputs.invocation_id,
        base_sha=base_sha,
        source_sha=candidate_runtime_inputs.candidate_sha,
        tested_sha=candidate_runtime_inputs.tested_sha,
        evaluator_sha=candidate_runtime_inputs.evaluator_sha,
        candidate_sha=candidate_runtime_inputs.candidate_sha,
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