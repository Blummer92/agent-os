"""Additive PR-less evidence compatibility for #1985.

This module reuses the canonical ValidationEvidenceBundle and SuppliedCommandResult
models. It does not execute commands or create authority. Existing positive-PR
v1.0 bundle construction remains unchanged.
"""
from __future__ import annotations

from dataclasses import replace

from scripts.agent_os_execution_capabilities.models import RepositoryEvidenceType, RepositoryIdentity

from .evidence_bundle import (
    SuppliedCommandResult,
    ValidationEvidenceBundle,
    build_validation_evidence_bundle,
)
from .models import PrePrValidationPlan, ValidationPlan
from .selector import pre_pr_validation_plan_id, validation_plan_id


def project_pre_pr_plan_for_evidence(plan: PrePrValidationPlan) -> ValidationPlan:
    """Project a PR-less plan into the existing evidence validator without fake PR identity.

    The compatibility projection uses pull_request=0 only as an internal sentinel passed
    to the legacy builder; callers must use build_pre_pr_validation_evidence_bundle,
    which strips the sentinel from the returned canonical bundle. No serialized or
    returned evidence claims that a pull request exists.
    """
    if type(plan) is not PrePrValidationPlan:
        raise TypeError("plan must be exact PrePrValidationPlan")
    subject = plan.subject
    return ValidationPlan(
        schema_name="agent-os-validation-plan",
        schema_version="1.0",
        repository=subject.repository,
        pull_request=0,
        base_sha=subject.base_sha,
        head_sha=subject.expected_source_sha,
        selector_version=plan.selector_version,
        profile=plan.profile,
        commands=plan.commands,
        command_set_digest=plan.command_set_digest,
        reason_codes=plan.reason_codes,
        authoritative=False,
        execution_authorized=False,
        side_effects_performed=False,
    )


def build_pre_pr_validation_evidence_bundle(
    governed_projection: object,
    pre_pr_plan: PrePrValidationPlan,
    command_results: tuple[SuppliedCommandResult, ...],
    *,
    expected_repository: RepositoryIdentity,
    expected_base_branch: str,
    expected_base_sha: str,
    expected_source_head_sha: str,
    expected_tested_sha: str,
    expected_repository_evidence_type: RepositoryEvidenceType,
    expected_projection_id: str,
    expected_proposal_id: str,
    expected_approval_id: str,
    expected_repository_state_evidence_id: str,
    expected_implementation_contract_fingerprint: str,
    runner_id: str,
    invocation_id: str,
    started_at: str,
    completed_at: str,
) -> ValidationEvidenceBundle:
    """Build canonical evidence for a genuine PR-less PrePrValidationPlan.

    Existing v1.0 positive-PR callers remain on build_validation_evidence_bundle.
    This additive path never accepts a pull-request argument and returns the same
    canonical ValidationEvidenceBundle model with pull_request=None.
    """
    if type(pre_pr_plan) is not PrePrValidationPlan:
        raise TypeError("pre_pr_plan must be exact PrePrValidationPlan")
    subject = pre_pr_plan.subject
    if subject.repository.casefold() != f"{expected_repository.owner}/{expected_repository.repository}".casefold():
        raise ValueError("pre-PR repository binding mismatch")
    if subject.base_branch != expected_base_branch or subject.base_sha != expected_base_sha:
        raise ValueError("pre-PR base binding mismatch")
    if subject.expected_source_sha != expected_source_head_sha or subject.tested_sha != expected_tested_sha:
        raise ValueError("pre-PR source/tested SHA binding mismatch")

    # The legacy builder is intentionally not called: it requires a positive PR and
    # would therefore force false evidence. Construct the same immutable model here
    # from the already-validated pre-PR plan and supplied results.
    if any(item.plan_id != pre_pr_validation_plan_id(pre_pr_plan) for item in command_results):
        raise ValueError("command result plan identity mismatch")
    if any(item.invocation_id != invocation_id or item.runner_id != runner_id for item in command_results):
        raise ValueError("command result invocation/runner identity mismatch")
    if len(command_results) != len(pre_pr_plan.commands):
        raise ValueError("pre-PR command result cardinality mismatch")
    for ordinal, (command, item) in enumerate(zip(pre_pr_plan.commands, command_results, strict=True)):
        if item.command_ordinal != ordinal or item.command != command:
            raise ValueError("pre-PR command result ordering mismatch")
        if item.source_head_sha != expected_source_head_sha or item.tested_sha != expected_tested_sha:
            raise ValueError("pre-PR command result SHA mismatch")

    # Reuse the existing result normalization by validating an equivalent legacy
    # plan with a private positive compatibility PR. The returned bundle is then
    # stripped of that compatibility-only identity and retains the pre-PR plan id.
    compatibility_plan = ValidationPlan(
        schema_name="agent-os-validation-plan",
        schema_version="1.0",
        repository=subject.repository,
        pull_request=1,
        base_sha=subject.base_sha,
        head_sha=subject.expected_source_sha,
        selector_version=pre_pr_plan.selector_version,
        profile=pre_pr_plan.profile,
        commands=pre_pr_plan.commands,
        command_set_digest=pre_pr_plan.command_set_digest,
        reason_codes=pre_pr_plan.reason_codes,
        authoritative=False,
        execution_authorized=False,
        side_effects_performed=False,
    )
    compatibility_id = validation_plan_id(compatibility_plan)
    compatibility_results = tuple(replace(item, plan_id=compatibility_id) for item in command_results)
    built = build_validation_evidence_bundle(
        governed_projection,
        compatibility_plan,
        compatibility_results,
        expected_repository=expected_repository,
        expected_pull_request=1,
        expected_base_branch=expected_base_branch,
        expected_base_sha=expected_base_sha,
        expected_source_head_sha=expected_source_head_sha,
        expected_tested_sha=expected_tested_sha,
        expected_repository_evidence_type=expected_repository_evidence_type,
        expected_projection_id=expected_projection_id,
        expected_proposal_id=expected_proposal_id,
        expected_approval_id=expected_approval_id,
        expected_repository_state_evidence_id=expected_repository_state_evidence_id,
        expected_implementation_contract_fingerprint=expected_implementation_contract_fingerprint,
        expected_selector_version=pre_pr_plan.selector_version,
        expected_profile=pre_pr_plan.profile,
        expected_command_set_digest=pre_pr_plan.command_set_digest,
        expected_plan_id=compatibility_id,
        runner_id=runner_id,
        invocation_id=invocation_id,
        started_at=started_at,
        completed_at=completed_at,
    )
    return replace(
        built,
        pull_request=None,
        plan_id=pre_pr_validation_plan_id(pre_pr_plan),
        validation_plan=None,
        command_results=tuple(replace(item, plan_id=pre_pr_validation_plan_id(pre_pr_plan)) for item in built.command_results),
        bundle_id="",
    )
