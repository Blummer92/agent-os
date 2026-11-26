"""Additive PR-less reader and writer for canonical ValidationEvidenceBundle.

Construction checks a supplied governed observation. Reconstruction verifies
canonical stored content and its own bindings, not projection authenticity
or currentness: this schema does not carry a projection observation.
"""
from __future__ import annotations

from dataclasses import replace

from scripts.agent_os_execution_capabilities.approved_projection import GovernedProjectionEvidenceResult
from scripts.agent_os_execution_capabilities.models import RepositoryEvidenceType, RepositoryIdentity

from .evidence_bundle import (
    MAX_BUNDLE_SERIALIZED_BYTES,
    VALIDATION_EVIDENCE_BUNDLE_SCHEMA_NAME,
    VALIDATION_EVIDENCE_BUNDLE_SCHEMA_VERSION,
    SuppliedCommandResult,
    ValidationEvidenceBundle,
    _BUNDLE_SERIALIZED_KEYS,
    _BUNDLE_STATUSES,
    _bundle_payload,
    _canonical_bytes,
    _closed_dict,
    _identifier,
    _reconstruct_command_results,
    _reconstruct_repository_identity,
    _run_identifier,
    _semantic_digest,
    _status_for,
    _timestamp,
    _validate_projection,
    _validate_results,
)
from .models import PRE_PR_EXECUTION_MODE, PrePrValidationPlan, PrePrValidationSubject
from .selector import (
    deserialize_pre_pr_validation_plan,
    pre_pr_validation_plan_id,
    serialize_pre_pr_validation_plan,
)

_AUTHORITY = ("authoritative", "execution_authorized", "merge_authorized",
              "attestation_verified", "side_effects_performed")
_ID_FIELDS = ("approval_id", "projection_id", "implementation_contract_fingerprint",
              "proposal_id", "repository_state_evidence_id")


def _text(value: object, field: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field} must be exact text")
    if not value.strip() or not _identifier(value):
        raise ValueError(f"{field} is missing or invalid")


def _plan_bindings(plan: PrePrValidationPlan) -> dict[str, object]:
    if type(plan) is not PrePrValidationPlan:
        raise TypeError("validation_plan must be exact PrePrValidationPlan")
    subject = plan.subject
    if type(subject) is not PrePrValidationSubject:
        raise TypeError("validation_plan.subject must be exact PrePrValidationSubject")
    if type(subject.execution_mode) is not str:
        raise TypeError("validation_plan.subject.execution_mode must be exact text")
    if subject.execution_mode != PRE_PR_EXECUTION_MODE:
        raise ValueError("pre-PR evidence requires validation-only execution mode")
    return {
        "base_branch": subject.base_branch,
        "base_sha": subject.base_sha,
        "source_head_sha": subject.expected_source_sha,
        "tested_sha": subject.tested_sha,
        "projection_id": subject.projection_id,
        "approval_id": subject.approval_id,
        "implementation_contract_fingerprint": subject.implementation_contract_fingerprint,
        "selector_version": plan.selector_version,
        "profile": plan.profile,
        "command_set_digest": plan.command_set_digest,
        "plan_id": pre_pr_validation_plan_id(plan),
        "invocation_id": subject.invocation_id,
    }


def _repository_binding(repository: RepositoryIdentity, plan: PrePrValidationPlan) -> None:
    if type(repository) is not RepositoryIdentity:
        raise TypeError("repository_identity must be exact RepositoryIdentity")
    if type(repository.is_fork) is not bool:
        raise TypeError("repository_identity.is_fork must be a boolean")
    if plan.subject.repository.casefold() != f"{repository.owner}/{repository.repository}".casefold():
        raise ValueError("repository_identity does not match pre-PR plan repository")


def _authority_is_false(value: dict[str, object]) -> None:
    for name in _AUTHORITY:
        if type(value[name]) is not bool:
            raise TypeError(f"{name} must be a boolean")
        if value[name] is not False:
            raise ValueError(f"{name} must remain false")


def _result_types(exit_code: object, status: object, command_ordinal: object) -> None:
    if exit_code is not None and type(exit_code) is not int:
        raise TypeError("command_result exit_code must be an exact integer or null")
    if type(status) is not str:
        raise TypeError("command_result status must be exact text")
    if type(command_ordinal) is not int:
        raise TypeError("command_result command_ordinal must be an exact integer")


def _check_size(payload: dict[str, object]) -> bytes:
    encoded = _canonical_bytes(payload)
    if len(encoded) > MAX_BUNDLE_SERIALIZED_BYTES:
        raise ValueError("validation evidence bundle exceeds canonical size limit")
    return encoded


def _bundle_id(payload: dict[str, object]) -> str:
    return "validation-evidence-bundle:" + _semantic_digest("agent-os-validation-evidence-bundle:v1", payload)


def _validated_payload(bundle: ValidationEvidenceBundle, plan: PrePrValidationPlan) -> dict[str, object]:
    if bundle.pull_request is not None:
        raise ValueError("pre-PR validation evidence must not carry a pull request")
    bindings = _plan_bindings(plan)
    if type(bundle.validation_plan) is not PrePrValidationPlan:
        raise TypeError("bundle must carry an exact PrePrValidationPlan")
    canonical_plan = serialize_pre_pr_validation_plan(plan)
    if plan is not bundle.validation_plan and _canonical_bytes(canonical_plan) != _canonical_bytes(
        serialize_pre_pr_validation_plan(bundle.validation_plan)
    ):
        raise ValueError("supplied validation_plan does not match bundle validation_plan")
    _repository_binding(bundle.repository_identity, plan)
    for name, expected in bindings.items():
        actual = getattr(bundle, name)
        if type(actual) is not type(expected):
            raise TypeError(f"{name} has noncanonical type")
        if actual != expected:
            raise ValueError(f"{name} does not match the canonical pre-PR plan")
    for name in _ID_FIELDS + ("runner_id", "started_at", "completed_at"):
        _text(getattr(bundle, name), name)
    if not _run_identifier(bundle.runner_id) or not _run_identifier(bundle.invocation_id):
        raise ValueError("runner_id or invocation_id is invalid")
    if type(bundle.repository_evidence_type) is not RepositoryEvidenceType:
        raise TypeError("repository_evidence_type must be exact RepositoryEvidenceType")
    if bundle.schema_name != VALIDATION_EVIDENCE_BUNDLE_SCHEMA_NAME or (
        bundle.schema_version != VALIDATION_EVIDENCE_BUNDLE_SCHEMA_VERSION
    ):
        raise ValueError("unsupported validation evidence bundle schema")
    if type(bundle.status) is not str:
        raise TypeError("bundle status must be exact text")
    if bundle.status not in _BUNDLE_STATUSES:
        raise ValueError("validation evidence bundle status is invalid")
    _authority_is_false({name: getattr(bundle, name) for name in _AUTHORITY})
    if bundle.status == "passed" and (
        len(bundle.command_results) != len(plan.commands)
        or any(item.status != "passed" for item in bundle.command_results)
        or bundle.reason_codes or bundle.details
        or not (_timestamp(bundle.started_at) and _timestamp(bundle.completed_at))
        or _timestamp(bundle.started_at) > _timestamp(bundle.completed_at)
    ):
        raise ValueError("passed bundle requires complete successful command evidence")
    return _bundle_payload(bundle, serialized_pre_pr_plan=canonical_plan)


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
    """Bind an independently supplied projection and canonical command evidence."""
    if type(governed_projection) is not GovernedProjectionEvidenceResult:
        raise TypeError("governed_projection must be exact GovernedProjectionEvidenceResult")
    bindings = _plan_bindings(validation_plan)
    _repository_binding(expected_repository, validation_plan)
    if type(expected_repository_evidence_type) is not RepositoryEvidenceType:
        raise TypeError("expected_repository_evidence_type must be exact RepositoryEvidenceType")
    if type(command_results) is not tuple:
        raise TypeError("command_results must be an exact tuple")
    for item in command_results:
        if type(item) is not SuppliedCommandResult:
            raise TypeError("command_results must contain exact SuppliedCommandResult objects")
        _result_types(item.exit_code, item.status, item.command_ordinal)

    facts = dict(
        **bindings, repository_evidence_type=expected_repository_evidence_type,
        proposal_id=expected_proposal_id, repository_state_evidence_id=expected_repository_state_evidence_id,
        runner_id=runner_id, started_at=started_at, completed_at=completed_at,
    )
    for name in ("proposal_id", "repository_state_evidence_id", "runner_id", "started_at", "completed_at"):
        _text(facts[name], name)
    expected = dict(facts, repository=expected_repository)
    invalid: set[str] = set()
    incomplete: set[str] = set()
    details: set[str] = set()
    needs_decision: set[str] = set()
    if governed_projection.status == "needs-decision":
        needs_decision.add("projection.needs-decision")
    elif governed_projection.status != "accepted":
        invalid.add("projection.not-accepted")
    else:
        _validate_projection(governed_projection, expected, invalid)
    bundle_start, bundle_end = _timestamp(started_at), _timestamp(completed_at)
    if bundle_start is None or bundle_end is None or bundle_end < bundle_start:
        invalid.add("bundle.timestamp")
    normalized = _validate_results(
        command_results, plan=validation_plan, expected=expected,
        bundle_start=bundle_start, bundle_end=bundle_end,
        invalid=invalid, incomplete=incomplete, details=details,
    )
    status, reasons = _status_for(invalid, needs_decision, incomplete,
                                  tuple(item.status for item in normalized))
    bundle = ValidationEvidenceBundle(
        schema_name=VALIDATION_EVIDENCE_BUNDLE_SCHEMA_NAME,
        schema_version=VALIDATION_EVIDENCE_BUNDLE_SCHEMA_VERSION,
        status=status, bundle_id="", repository_identity=expected_repository,
        pull_request=None, validation_plan=validation_plan,
        command_results=() if "results.invalid" in invalid else normalized,
        reason_codes=tuple(sorted(reasons)), details=tuple(sorted(details)), **facts,
    )
    payload = _validated_payload(bundle, validation_plan)
    identified = replace(bundle, bundle_id=_bundle_id(payload))
    _check_size(dict(payload, bundle_id=identified.bundle_id))
    return identified


def serialize_pre_pr_validation_evidence_bundle(
    bundle: ValidationEvidenceBundle,
    validation_plan: PrePrValidationPlan | None = None,
) -> dict[str, object]:
    """Verify plan/subject bindings independently of the bundle digest."""
    if type(bundle) is not ValidationEvidenceBundle:
        raise TypeError("bundle must be exact ValidationEvidenceBundle")
    plan = bundle.validation_plan if validation_plan is None else validation_plan
    payload = _validated_payload(bundle, plan)
    if bundle.bundle_id != _bundle_id(payload):
        raise ValueError("validation evidence bundle ID mismatch")
    result = dict(payload, bundle_id=bundle.bundle_id)
    _check_size(result)
    _read_results(result, plan)
    return result


def pre_pr_validation_evidence_bundle_id(
    bundle: ValidationEvidenceBundle,
    validation_plan: PrePrValidationPlan | None = None,
) -> str:
    serialize_pre_pr_validation_evidence_bundle(bundle, validation_plan)
    return bundle.bundle_id


def _read_results(value: dict[str, object], plan: PrePrValidationPlan):
    """Use the existing result evidence parser with PR-less exact JSON types."""
    results = value["command_results"]
    if type(results) is not list:
        raise TypeError("command_results must be a list")
    for item in results:
        if type(item) is not dict:
            raise TypeError("command_result must be an exact object")
        if {"exit_code", "status", "command_ordinal"} <= item.keys():
            _result_types(item["exit_code"], item["status"], item["command_ordinal"])
    return _reconstruct_command_results(
        results, plan=plan, expected=value, bundle_start=_timestamp(value["started_at"]),
        bundle_end=_timestamp(value["completed_at"]),
    )


def reconstruct_pre_pr_validation_evidence_bundle(payload: object) -> ValidationEvidenceBundle:
    """Verify and decode stored content; never synthesize/revalidate a projection."""
    if type(payload) is not dict:
        raise TypeError("payload must be an exact dictionary")
    value = _closed_dict(payload, _BUNDLE_SERIALIZED_KEYS, "validation evidence bundle")
    encoded = _check_size(value)
    if value["pull_request"] is not None:
        raise ValueError("pre-PR bundle pull_request must be null")
    _authority_is_false(value)
    for name in _ID_FIELDS + ("bundle_id", "runner_id", "started_at", "completed_at"):
        _text(value[name], name)
    plan = deserialize_pre_pr_validation_plan(value["validation_plan"])
    raw_repository = value["repository_identity"]
    if type(raw_repository) is not dict:
        raise TypeError("repository_identity must be an exact object")
    repository = _reconstruct_repository_identity(raw_repository)
    if type(value["repository_evidence_type"]) is not str:
        raise TypeError("repository_evidence_type must be exact text")
    evidence_type = RepositoryEvidenceType(value["repository_evidence_type"])
    normalized = _read_results(value, plan)
    fields = {name: value[name] for name in _BUNDLE_SERIALIZED_KEYS - set(_AUTHORITY) - {
        "repository_identity", "repository_evidence_type", "validation_plan", "command_results",
        "reason_codes", "details",
    }}
    for name in ("reason_codes", "details"):
        items = value[name]
        if type(items) is not list or any(type(item) is not str for item in items):
            raise TypeError(f"{name} must be a list of exact strings")
        fields[name] = tuple(items)
    bundle = ValidationEvidenceBundle(
        **fields, repository_identity=repository, repository_evidence_type=evidence_type,
        validation_plan=plan, command_results=normalized,
    )
    canonical = _validated_payload(bundle, plan)
    bundle_id = _bundle_id(canonical)
    if bundle.bundle_id != bundle_id:
        raise ValueError("validation evidence bundle ID mismatch")
    if _canonical_bytes(dict(canonical, bundle_id=bundle_id)) != encoded:
        raise ValueError("pre-PR validation evidence bundle is noncanonical")
    return bundle


__all__ = [
    "build_pre_pr_validation_evidence_bundle",
    "pre_pr_validation_evidence_bundle_id",
    "reconstruct_pre_pr_validation_evidence_bundle",
    "serialize_pre_pr_validation_evidence_bundle",
]
