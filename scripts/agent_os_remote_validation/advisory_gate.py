from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import Literal

from scripts.agent_os_execution_capabilities.approved_projection import (
    GovernedProjectionEvidenceResult,
)
from scripts.agent_os_execution_capabilities.models import (
    RepositoryEvidenceType,
    RepositoryIdentity,
)

from .evidence_bundle import (
    SuppliedCommandResult,
    ValidationEvidenceBundle,
    build_validation_evidence_bundle,
    serialize_validation_evidence_bundle,
    validation_evidence_bundle_id,
)
from .models import ValidationPlan
from .selector import (
    compute_command_set_digest,
    serialize_validation_plan,
    validate_validation_plan,
    validation_plan_id,
)

ADVISORY_EVIDENCE_SCHEMA_NAME = "agent-os-advisory-pre-pr-evidence"
ADVISORY_EVIDENCE_SCHEMA_VERSION = "1.0"
MAX_ADVISORY_STRING_LENGTH = 4096
MAX_ADVISORY_REASON_CODES = 64
MAX_ADVISORY_DETAILS = 64
MAX_ADVISORY_COMMAND_RESULTS = 64
MAX_ADVISORY_SERIALIZED_BYTES = 262_144

AdvisoryStatus = Literal[
    "passed",
    "failed",
    "incomplete",
    "stale",
    "invalid",
    "needs-decision",
]

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_RESULT_ID = re.compile(r"^command-result:[0-9a-f]{64}$")
_BUNDLE_ID = re.compile(r"^validation-evidence-bundle:[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EXPECTED_EXCEPTIONS = (TypeError, ValueError)


@dataclass(frozen=True, slots=True, kw_only=True)
class AdvisoryEvidenceResult:
    schema_name: str
    schema_version: str
    status: AdvisoryStatus
    result_id: str
    repository_identity: RepositoryIdentity | None
    pull_request: int | None
    base_branch: str | None
    base_sha: str | None
    source_head_sha: str | None
    tested_sha: str | None
    repository_evidence_type: RepositoryEvidenceType | None
    projection_id: str | None
    proposal_id: str | None
    approval_id: str | None
    repository_state_evidence_id: str | None
    implementation_contract_fingerprint: str | None
    selector_version: str | None
    profile: str | None
    command_set_digest: str | None
    plan_id: str | None
    bundle_id: str | None
    runner_id: str | None
    invocation_id: str | None
    command_result_ids: tuple[str, ...]
    command_result_statuses: tuple[str, ...]
    reason_codes: tuple[str, ...]
    details: tuple[str, ...]
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    attestation_verified: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def evaluate_advisory_pre_pr_evidence(
    governed_projection: object,
    validation_plan: object,
    command_results: object,
    *,
    expected_repository: object,
    expected_pull_request: object,
    expected_base_branch: object,
    expected_base_sha: object,
    expected_source_head_sha: object,
    expected_tested_sha: object,
    current_base_sha: object,
    current_source_head_sha: object,
    expected_repository_evidence_type: object,
    expected_projection_id: object,
    expected_proposal_id: object,
    expected_approval_id: object,
    expected_repository_state_evidence_id: object,
    expected_implementation_contract_fingerprint: object,
    expected_selector_version: object,
    expected_profile: object,
    expected_command_set_digest: object,
    expected_plan_id: object,
    runner_id: object,
    invocation_id: object,
    started_at: object,
    completed_at: object,
    expected_bundle_id: object | None = None,
    schema_version: object = ADVISORY_EVIDENCE_SCHEMA_VERSION,
) -> AdvisoryEvidenceResult:
    """Evaluate supplied pre-PR evidence without execution or external I/O."""
    invalid: set[str] = set()
    stale: set[str] = set()
    needs_decision: set[str] = set()
    incomplete: set[str] = set()
    failed: set[str] = set()
    details: set[str] = set()

    if schema_version != ADVISORY_EVIDENCE_SCHEMA_VERSION:
        invalid.add("advisory.schema-version")

    projection = (
        governed_projection
        if isinstance(governed_projection, GovernedProjectionEvidenceResult)
        else None
    )
    plan = validation_plan if isinstance(validation_plan, ValidationPlan) else None
    results = command_results if isinstance(command_results, tuple) else None
    repository = (
        expected_repository
        if isinstance(expected_repository, RepositoryIdentity)
        else None
    )
    evidence_type = (
        expected_repository_evidence_type
        if isinstance(expected_repository_evidence_type, RepositoryEvidenceType)
        else None
    )

    if projection is None:
        invalid.add("projection.invalid-type")
    if plan is None:
        invalid.add("plan.invalid-type")
    if results is None:
        invalid.add("results.invalid-collection")
    if repository is None:
        invalid.add("advisory.repository")
    if evidence_type is None:
        invalid.add("advisory.repository-evidence-type")

    for label, value in (
        ("expected-base-sha", expected_base_sha),
        ("expected-source-head-sha", expected_source_head_sha),
        ("expected-tested-sha", expected_tested_sha),
        ("current-base-sha", current_base_sha),
        ("current-source-head-sha", current_source_head_sha),
    ):
        if not _is_sha(value):
            invalid.add(f"advisory.{label}")

    if _is_sha(expected_base_sha) and _is_sha(current_base_sha):
        if expected_base_sha != current_base_sha:
            stale.add("revision.base-sha-stale")
    if _is_sha(expected_source_head_sha) and _is_sha(current_source_head_sha):
        if expected_source_head_sha != current_source_head_sha:
            stale.add("revision.source-head-sha-stale")

    if projection is not None:
        _classify_projection(projection, invalid, stale, needs_decision)

    if plan is not None:
        plan_reasons = validate_validation_plan(plan)
        if plan_reasons:
            invalid.add("plan.invalid")
            details.update(_bounded_prefixed("plan", plan_reasons))
        else:
            try:
                canonical_plan_id = validation_plan_id(plan)
                serialize_validation_plan(plan)
                if plan.profile != "manual-review":
                    canonical_digest = compute_command_set_digest(
                        plan.selector_version, plan.commands
                    )
                    if canonical_digest != plan.command_set_digest:
                        invalid.add("plan.command-set-digest-mismatch")
                if canonical_plan_id != expected_plan_id:
                    invalid.add("plan.id-mismatch")
            except _EXPECTED_EXCEPTIONS as error:
                invalid.add("plan.canonicalization-failed")
                details.add(_error_detail("plan", error))

    bundle: ValidationEvidenceBundle | None = None
    if not invalid or invalid <= {
        "projection.not-accepted",
    }:
        try:
            bundle = build_validation_evidence_bundle(
                governed_projection,
                validation_plan,
                command_results,
                expected_repository=expected_repository,
                expected_pull_request=expected_pull_request,
                expected_base_branch=expected_base_branch,
                expected_base_sha=expected_base_sha,
                expected_source_head_sha=expected_source_head_sha,
                expected_tested_sha=expected_tested_sha,
                expected_repository_evidence_type=expected_repository_evidence_type,
                expected_projection_id=expected_projection_id,
                expected_proposal_id=expected_proposal_id,
                expected_approval_id=expected_approval_id,
                expected_repository_state_evidence_id=(
                    expected_repository_state_evidence_id
                ),
                expected_implementation_contract_fingerprint=(
                    expected_implementation_contract_fingerprint
                ),
                expected_selector_version=expected_selector_version,
                expected_profile=expected_profile,
                expected_command_set_digest=expected_command_set_digest,
                expected_plan_id=expected_plan_id,
                runner_id=runner_id,
                invocation_id=invocation_id,
                started_at=started_at,
                completed_at=completed_at,
            )
            serialized_bundle = serialize_validation_evidence_bundle(bundle)
            verified_bundle_id = validation_evidence_bundle_id(bundle)
            if serialized_bundle.get("bundle_id") != verified_bundle_id:
                invalid.add("bundle.id-mismatch")
            if expected_bundle_id is not None:
                if not _is_bundle_id(expected_bundle_id):
                    invalid.add("bundle.expected-id-invalid")
                elif expected_bundle_id != verified_bundle_id:
                    invalid.add("bundle.expected-id-mismatch")
            _classify_bundle(
                bundle,
                projection=projection,
                invalid=invalid,
                needs_decision=needs_decision,
                incomplete=incomplete,
                failed=failed,
                details=details,
            )
        except _EXPECTED_EXCEPTIONS as error:
            invalid.add("bundle.canonicalization-failed")
            details.add(_error_detail("bundle", error))

    result_ids: tuple[str, ...] = ()
    result_statuses: tuple[str, ...] = ()
    if bundle is not None:
        result_ids = tuple(item.result_id for item in bundle.command_results)
        result_statuses = tuple(item.status for item in bundle.command_results)
        _validate_result_references(result_ids, result_statuses, invalid)

    status, reasons = _resolve_status(
        invalid=invalid,
        stale=stale,
        needs_decision=needs_decision,
        incomplete=incomplete,
        failed=failed,
    )

    preliminary = AdvisoryEvidenceResult(
        schema_name=ADVISORY_EVIDENCE_SCHEMA_NAME,
        schema_version=ADVISORY_EVIDENCE_SCHEMA_VERSION,
        status=status,
        result_id="",
        repository_identity=repository,
        pull_request=_positive_int_or_none(expected_pull_request),
        base_branch=_bounded_string_or_none(expected_base_branch),
        base_sha=_string_or_none(expected_base_sha),
        source_head_sha=_string_or_none(expected_source_head_sha),
        tested_sha=_string_or_none(expected_tested_sha),
        repository_evidence_type=evidence_type,
        projection_id=_bounded_string_or_none(expected_projection_id),
        proposal_id=_bounded_string_or_none(expected_proposal_id),
        approval_id=_bounded_string_or_none(expected_approval_id),
        repository_state_evidence_id=_bounded_string_or_none(
            expected_repository_state_evidence_id
        ),
        implementation_contract_fingerprint=_bounded_string_or_none(
            expected_implementation_contract_fingerprint
        ),
        selector_version=_bounded_string_or_none(expected_selector_version),
        profile=_bounded_string_or_none(expected_profile),
        command_set_digest=_bounded_string_or_none(expected_command_set_digest),
        plan_id=_bounded_string_or_none(expected_plan_id),
        bundle_id=bundle.bundle_id if bundle is not None else None,
        runner_id=_bounded_string_or_none(runner_id),
        invocation_id=_bounded_string_or_none(invocation_id),
        command_result_ids=result_ids[:MAX_ADVISORY_COMMAND_RESULTS],
        command_result_statuses=result_statuses[:MAX_ADVISORY_COMMAND_RESULTS],
        reason_codes=_bounded_sorted(reasons, MAX_ADVISORY_REASON_CODES),
        details=_bounded_sorted(details, MAX_ADVISORY_DETAILS),
    )
    payload = _advisory_payload(preliminary)
    if len(_canonical_bytes(payload)) > MAX_ADVISORY_SERIALIZED_BYTES:
        preliminary = replace(
            preliminary,
            status="invalid",
            reason_codes=("advisory.serialized-size",),
            details=(),
        )
        payload = _advisory_payload(preliminary)
    digest = _semantic_digest("agent-os-advisory-pre-pr-evidence:v1", payload)
    return replace(preliminary, result_id=f"advisory-evidence:{digest}")


def serialize_advisory_evidence_result(
    result: AdvisoryEvidenceResult,
) -> dict[str, object]:
    """Return canonical advisory evidence after verifying semantic identity."""
    if not isinstance(result, AdvisoryEvidenceResult):
        raise TypeError("result must be AdvisoryEvidenceResult")
    _validate_result_model(result)
    payload = _advisory_payload(result)
    expected = "advisory-evidence:" + _semantic_digest(
        "agent-os-advisory-pre-pr-evidence:v1", payload
    )
    if result.result_id != expected:
        raise ValueError("advisory evidence result ID mismatch")
    serialized = dict(payload)
    serialized["result_id"] = result.result_id
    if len(_canonical_bytes(serialized)) > MAX_ADVISORY_SERIALIZED_BYTES:
        raise ValueError("advisory evidence exceeds canonical size limit")
    return serialized


def advisory_evidence_result_id(result: AdvisoryEvidenceResult) -> str:
    """Return the verified domain-separated advisory evidence identity."""
    return str(serialize_advisory_evidence_result(result)["result_id"])


def _classify_projection(
    projection: GovernedProjectionEvidenceResult,
    invalid: set[str],
    stale: set[str],
    needs_decision: set[str],
) -> None:
    if any(
        value is not False
        for value in (
            projection.authoritative,
            projection.execution_authorized,
            projection.side_effects_performed,
        )
    ):
        invalid.add("projection.authority")
    if projection.status == "accepted":
        return
    if projection.status == "stale":
        stale.add("projection.stale")
    elif projection.status in {"blocked", "needs-decision"}:
        needs_decision.add(f"projection.{projection.status}")
    else:
        invalid.add(f"projection.{projection.status}")


def _classify_bundle(
    bundle: ValidationEvidenceBundle,
    *,
    projection: GovernedProjectionEvidenceResult | None,
    invalid: set[str],
    needs_decision: set[str],
    incomplete: set[str],
    failed: set[str],
    details: set[str],
) -> None:
    if any(
        value is not False
        for value in (
            bundle.authoritative,
            bundle.execution_authorized,
            bundle.merge_authorized,
            bundle.attestation_verified,
            bundle.side_effects_performed,
        )
    ):
        invalid.add("bundle.authority")

    reasons = set(bundle.reason_codes)
    if bundle.status == "invalid" and projection is not None and projection.status != "accepted":
        reasons.discard("projection.not-accepted")
        if reasons:
            invalid.add("bundle.invalid")
            details.update(_bounded_prefixed("bundle", reasons))
    elif bundle.status == "invalid":
        invalid.add("bundle.invalid")
        details.update(_bounded_prefixed("bundle", reasons))
    elif bundle.status == "incomplete":
        incomplete.add("bundle.incomplete")
        details.update(_bounded_prefixed("bundle", reasons))
    elif bundle.status == "needs-decision":
        needs_decision.add("bundle.needs-decision")
        details.update(_bounded_prefixed("bundle", reasons))
    elif bundle.status in {"failed", "timed-out", "cancelled"}:
        failed.add(f"bundle.{bundle.status}")
        details.update(_bounded_prefixed("bundle", reasons))
    elif bundle.status != "passed":
        invalid.add("bundle.status")


def _validate_result_references(
    result_ids: tuple[str, ...],
    result_statuses: tuple[str, ...],
    invalid: set[str],
) -> None:
    if len(result_ids) != len(result_statuses):
        invalid.add("results.reference-count-mismatch")
    if len(result_ids) > MAX_ADVISORY_COMMAND_RESULTS:
        invalid.add("results.reference-count")
    if len(set(result_ids)) != len(result_ids):
        invalid.add("results.duplicate-id")
    if any(not _RESULT_ID.fullmatch(item) for item in result_ids):
        invalid.add("results.id-invalid")


def _resolve_status(
    *,
    invalid: set[str],
    stale: set[str],
    needs_decision: set[str],
    incomplete: set[str],
    failed: set[str],
) -> tuple[AdvisoryStatus, set[str]]:
    if invalid:
        return "invalid", invalid
    if stale:
        return "stale", stale
    if needs_decision:
        return "needs-decision", needs_decision
    if incomplete:
        return "incomplete", incomplete
    if failed:
        return "failed", failed
    return "passed", set()


def _validate_result_model(result: AdvisoryEvidenceResult) -> None:
    if result.schema_name != ADVISORY_EVIDENCE_SCHEMA_NAME:
        raise ValueError("unsupported advisory evidence schema name")
    if result.schema_version != ADVISORY_EVIDENCE_SCHEMA_VERSION:
        raise ValueError("unsupported advisory evidence schema version")
    if result.status not in {
        "passed",
        "failed",
        "incomplete",
        "stale",
        "invalid",
        "needs-decision",
    }:
        raise ValueError("unsupported advisory evidence status")
    if any(
        value is not False
        for value in (
            result.authoritative,
            result.execution_authorized,
            result.merge_authorized,
            result.attestation_verified,
            result.side_effects_performed,
        )
    ):
        raise ValueError("advisory evidence authority flags must remain false")
    if len(result.command_result_ids) != len(result.command_result_statuses):
        raise ValueError("command result reference counts differ")
    if len(result.command_result_ids) > MAX_ADVISORY_COMMAND_RESULTS:
        raise ValueError("too many command result references")
    if len(result.reason_codes) > MAX_ADVISORY_REASON_CODES:
        raise ValueError("too many advisory reason codes")
    if len(result.details) > MAX_ADVISORY_DETAILS:
        raise ValueError("too many advisory details")
    for value in (
        *result.command_result_ids,
        *result.command_result_statuses,
        *result.reason_codes,
        *result.details,
    ):
        if not isinstance(value, str) or len(value) > MAX_ADVISORY_STRING_LENGTH:
            raise ValueError("advisory evidence string exceeds bounds")
        if _CONTROL.search(value):
            raise ValueError("advisory evidence contains a control character")


def _advisory_payload(result: AdvisoryEvidenceResult) -> dict[str, object]:
    return {
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "status": result.status,
        "repository_identity": _repository_payload(result.repository_identity),
        "pull_request": result.pull_request,
        "base_branch": result.base_branch,
        "base_sha": result.base_sha,
        "source_head_sha": result.source_head_sha,
        "tested_sha": result.tested_sha,
        "repository_evidence_type": (
            result.repository_evidence_type.value
            if isinstance(result.repository_evidence_type, RepositoryEvidenceType)
            else None
        ),
        "projection_id": result.projection_id,
        "proposal_id": result.proposal_id,
        "approval_id": result.approval_id,
        "repository_state_evidence_id": result.repository_state_evidence_id,
        "implementation_contract_fingerprint": (
            result.implementation_contract_fingerprint
        ),
        "selector_version": result.selector_version,
        "profile": result.profile,
        "command_set_digest": result.command_set_digest,
        "plan_id": result.plan_id,
        "bundle_id": result.bundle_id,
        "runner_id": result.runner_id,
        "invocation_id": result.invocation_id,
        "command_result_ids": list(result.command_result_ids),
        "command_result_statuses": list(result.command_result_statuses),
        "reason_codes": list(result.reason_codes),
        "details": list(result.details),
        "authoritative": False,
        "execution_authorized": False,
        "merge_authorized": False,
        "attestation_verified": False,
        "side_effects_performed": False,
    }


def _repository_payload(value: RepositoryIdentity | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "host": value.host,
        "owner": value.owner,
        "repository": value.repository,
        "repository_id": value.repository_id,
        "is_fork": value.is_fork,
        "upstream_owner": value.upstream_owner,
        "upstream_repository": value.upstream_repository,
        "upstream_repository_id": value.upstream_repository_id,
        "default_branch": value.default_branch,
    }


def _bounded_prefixed(prefix: str, values: object) -> set[str]:
    output: set[str] = set()
    if isinstance(values, (tuple, list, set, frozenset)):
        for value in values:
            if len(output) >= MAX_ADVISORY_DETAILS:
                break
            if isinstance(value, str):
                candidate = f"{prefix}:{value}"
                if len(candidate) <= MAX_ADVISORY_STRING_LENGTH and not _CONTROL.search(
                    candidate
                ):
                    output.add(candidate)
    return output


def _bounded_sorted(values: set[str], limit: int) -> tuple[str, ...]:
    return tuple(
        sorted(
            value
            for value in values
            if isinstance(value, str)
            and len(value) <= MAX_ADVISORY_STRING_LENGTH
            and not _CONTROL.search(value)
        )
    )[:limit]


def _error_detail(prefix: str, error: Exception) -> str:
    return f"{prefix}:{error.__class__.__name__}"


def _semantic_digest(domain: str, payload: dict[str, object]) -> str:
    return hashlib.sha256(
        domain.encode("utf-8") + b"\0" + _canonical_bytes(payload)
    ).hexdigest()


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA40.fullmatch(value) is not None


def _is_bundle_id(value: object) -> bool:
    return isinstance(value, str) and _BUNDLE_ID.fullmatch(value) is not None


def _positive_int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _bounded_string_or_none(value: object) -> str | None:
    if (
        isinstance(value, str)
        and len(value) <= MAX_ADVISORY_STRING_LENGTH
        and not _CONTROL.search(value)
    ):
        return value
    return None
