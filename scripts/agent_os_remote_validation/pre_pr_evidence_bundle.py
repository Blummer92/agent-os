"""Additive PR-less evidence-bundle construction for #1985.

This module deliberately reuses ``ValidationEvidenceBundle`` and its canonical
content-addressed identity.  It does not introduce a second evidence model and
it leaves the existing positive-PR v1.0 builder unchanged.
"""
from __future__ import annotations

from dataclasses import replace

from scripts.agent_os_execution_capabilities.approved_projection import (
    GovernedProjectionEvidenceResult,
)
from scripts.agent_os_execution_capabilities.models import (
    RepositoryEvidenceType,
    RepositoryIdentity,
)

from .evidence_bundle import (
    VALIDATION_EVIDENCE_BUNDLE_SCHEMA_NAME,
    VALIDATION_EVIDENCE_BUNDLE_SCHEMA_VERSION,
    SuppliedCommandResult,
    ValidationEvidenceBundle,
    _bundle_payload,
    _semantic_digest,
    _status_for,
    _timestamp,
    _validate_projection,
    _validate_results,
)
from .models import PrePrValidationPlan
from .selector import (
    compute_command_set_digest,
    pre_pr_validation_plan_id,
    serialize_pre_pr_validation_plan,
)


def build_pre_pr_validation_evidence_bundle(
    governed_projection: GovernedProjectionEvidenceResult,
    validation_plan: PrePrValidationPlan,
    command_results: tuple[SuppliedCommandResult, ...],
    *,
    expected_repository: RepositoryIdentity,
    expected_repository_evidence_type: RepositoryEvidenceType,
    expected_proposal_id: str,
    expected_repository_state_evidence_id: str,
    runner_id: str,
    started_at: str,
    completed_at: str,
) -> ValidationEvidenceBundle:
    """Build the existing bundle type for one genuine PR-less validation plan."""
    if type(governed_projection) is not GovernedProjectionEvidenceResult:
        raise TypeError("governed_projection must be exact GovernedProjectionEvidenceResult")
    if type(validation_plan) is not PrePrValidationPlan:
        raise TypeError("validation_plan must be exact PrePrValidationPlan")
    if type(expected_repository) is not RepositoryIdentity:
        raise TypeError("expected_repository must be exact RepositoryIdentity")
    if type(expected_repository_evidence_type) is not RepositoryEvidenceType:
        raise TypeError("expected_repository_evidence_type must be exact RepositoryEvidenceType")
    if type(command_results) is not tuple:
        raise TypeError("command_results must be an exact tuple")
    for name, value in (
        ("expected_proposal_id", expected_proposal_id),
        ("expected_repository_state_evidence_id", expected_repository_state_evidence_id),
        ("runner_id", runner_id),
        ("started_at", started_at),
        ("completed_at", completed_at),
    ):
        if type(value) is not str or not value:
            raise TypeError(f"{name} must be non-empty exact text")

    subject = validation_plan.subject
    repository = f"{expected_repository.owner}/{expected_repository.repository}"
    if subject.repository.casefold() != repository.casefold():
        raise ValueError("pre-PR plan repository does not match expected repository")
    plan_id = pre_pr_validation_plan_id(validation_plan)
    command_digest = compute_command_set_digest(
        validation_plan.selector_version, validation_plan.commands
    )
    if command_digest != validation_plan.command_set_digest:
        raise ValueError("pre-PR plan command-set digest drift")

    expected: dict[str, object] = {
        "repository": expected_repository,
        "base_branch": subject.base_branch,
        "base_sha": subject.base_sha,
        "source_head_sha": subject.expected_source_sha,
        "tested_sha": subject.tested_sha,
        "repository_evidence_type": expected_repository_evidence_type,
        "projection_id": subject.projection_id,
        "proposal_id": expected_proposal_id,
        "approval_id": subject.approval_id,
        "repository_state_evidence_id": expected_repository_state_evidence_id,
        "implementation_contract_fingerprint": subject.implementation_contract_fingerprint,
        "selector_version": validation_plan.selector_version,
        "profile": validation_plan.profile,
        "command_set_digest": validation_plan.command_set_digest,
        "plan_id": plan_id,
        "runner_id": runner_id,
        "invocation_id": subject.invocation_id,
        "started_at": started_at,
        "completed_at": completed_at,
    }

    invalid: set[str] = set()
    incomplete: set[str] = set()
    details: set[str] = set()
    needs_decision: set[str] = set()
    _validate_projection(governed_projection, expected, invalid)
    bundle_start = _timestamp(started_at)
    bundle_end = _timestamp(completed_at)
    if bundle_start is None or bundle_end is None or bundle_end < bundle_start:
        invalid.add("bundle.timestamp")

    # Reuse the existing result validator by presenting only the plan surface it
    # consumes.  This adapter is local and non-authorizing; no positive PR is
    # fabricated and no v1.0 positive-PR behavior changes.
    class _ResultPlan:
        profile = validation_plan.profile
        commands = validation_plan.commands

    normalized = _validate_results(
        command_results,
        plan=_ResultPlan(),  # type: ignore[arg-type]
        expected=expected,
        bundle_start=bundle_start,
        bundle_end=bundle_end,
        invalid=invalid,
        incomplete=incomplete,
        details=details,
    )
    status, reasons = _status_for(
        invalid, needs_decision, incomplete, tuple(item.status for item in normalized)
    )
    preliminary = ValidationEvidenceBundle(
        schema_name=VALIDATION_EVIDENCE_BUNDLE_SCHEMA_NAME,
        schema_version=VALIDATION_EVIDENCE_BUNDLE_SCHEMA_VERSION,
        status=status,
        bundle_id="",
        repository_identity=expected_repository,
        pull_request=None,
        base_branch=subject.base_branch,
        base_sha=subject.base_sha,
        source_head_sha=subject.expected_source_sha,
        tested_sha=subject.tested_sha,
        repository_evidence_type=expected_repository_evidence_type,
        projection_id=subject.projection_id,
        proposal_id=expected_proposal_id,
        approval_id=subject.approval_id,
        repository_state_evidence_id=expected_repository_state_evidence_id,
        implementation_contract_fingerprint=subject.implementation_contract_fingerprint,
        selector_version=validation_plan.selector_version,
        profile=validation_plan.profile,
        command_set_digest=validation_plan.command_set_digest,
        plan_id=plan_id,
        runner_id=runner_id,
        invocation_id=subject.invocation_id,
        started_at=started_at,
        completed_at=completed_at,
        validation_plan=None,
        command_results=normalized,
        reason_codes=tuple(sorted(reasons)),
        details=tuple(sorted(details)),
    )
    digest = _semantic_digest(
        "agent-os-validation-evidence-bundle:v1", _pre_pr_payload(preliminary, validation_plan)
    )
    return replace(preliminary, bundle_id=f"validation-evidence-bundle:{digest}")


def serialize_pre_pr_validation_evidence_bundle(
    bundle: ValidationEvidenceBundle,
    validation_plan: PrePrValidationPlan,
) -> dict[str, object]:
    """Serialize a PR-less bundle while verifying its content-addressed identity."""
    payload = _pre_pr_payload(bundle, validation_plan)
    expected = "validation-evidence-bundle:" + _semantic_digest(
        "agent-os-validation-evidence-bundle:v1", payload
    )
    if bundle.bundle_id != expected:
        raise ValueError("validation evidence bundle ID mismatch")
    result = dict(payload)
    result["bundle_id"] = bundle.bundle_id
    return result


def pre_pr_validation_evidence_bundle_id(
    bundle: ValidationEvidenceBundle,
    validation_plan: PrePrValidationPlan,
) -> str:
    return str(serialize_pre_pr_validation_evidence_bundle(bundle, validation_plan)["bundle_id"])


def _pre_pr_payload(
    bundle: ValidationEvidenceBundle,
    validation_plan: PrePrValidationPlan,
) -> dict[str, object]:
    payload = _bundle_payload(bundle)
    payload["pull_request"] = None
    payload["validation_plan"] = serialize_pre_pr_validation_plan(validation_plan)
    return payload
