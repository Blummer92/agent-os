from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal

from scripts.agent_os_execution_capabilities.approved_projection import (
    GovernedProjectionEvidenceResult,
)
from scripts.agent_os_execution_capabilities.models import (
    RepositoryEvidenceType,
    RepositoryIdentity,
)

from .models import ValidationPlan
from .selector import (
    compute_command_set_digest,
    serialize_validation_plan,
    validate_validation_plan,
    validation_plan_id,
)

VALIDATION_EVIDENCE_BUNDLE_SCHEMA_NAME = "agent-os-validation-evidence-bundle"
VALIDATION_EVIDENCE_BUNDLE_SCHEMA_VERSION = "1.0"
MAX_RESULT_DIAGNOSTIC_LENGTH = 4096
MAX_RUN_ID_LENGTH = 256
MAX_BUNDLE_SERIALIZED_BYTES = 1_048_576

CommandOutcome = Literal[
    "passed",
    "failed",
    "timed-out",
    "cancelled",
    "unavailable",
    "infrastructure-error",
]
BundleStatus = Literal[
    "passed",
    "failed",
    "timed-out",
    "cancelled",
    "incomplete",
    "invalid",
    "needs-decision",
]

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SECRET = re.compile(
    r"(?i)(authorization\s*:|bearer\s+[A-Za-z0-9._-]{8,}|"
    r"(?:token|password|secret|api[_-]?key|private[_-]?key)\s*[:=])"
)
_OUTCOMES = frozenset(
    {
        "passed",
        "failed",
        "timed-out",
        "cancelled",
        "unavailable",
        "infrastructure-error",
    }
)
_BUNDLE_PAYLOAD_KEYS = frozenset(
    {
        "schema_name",
        "schema_version",
        "status",
        "bundle_id",
        "repository_identity",
        "pull_request",
        "base_branch",
        "base_sha",
        "source_head_sha",
        "tested_sha",
        "repository_evidence_type",
        "projection_id",
        "proposal_id",
        "approval_id",
        "repository_state_evidence_id",
        "implementation_contract_fingerprint",
        "selector_version",
        "profile",
        "command_set_digest",
        "plan_id",
        "runner_id",
        "invocation_id",
        "started_at",
        "completed_at",
        "validation_plan",
        "command_results",
        "reason_codes",
        "details",
        "authoritative",
        "execution_authorized",
        "merge_authorized",
        "attestation_verified",
        "side_effects_performed",
    }
)
_REPOSITORY_PAYLOAD_KEYS = frozenset(
    {
        "host",
        "owner",
        "repository",
        "repository_id",
        "is_fork",
        "upstream_owner",
        "upstream_repository",
        "upstream_repository_id",
        "default_branch",
    }
)
_PLAN_PAYLOAD_KEYS = frozenset(
    {
        "schema_name",
        "schema_version",
        "selector_version",
        "repository",
        "pull_request",
        "base_sha",
        "head_sha",
        "profile",
        "commands",
        "command_set_digest",
        "reason_codes",
        "remote_build_required",
        "execution_authorized",
        "side_effects_performed",
    }
)
_RESULT_PAYLOAD_KEYS = frozenset(
    {
        "result_id",
        "plan_id",
        "invocation_id",
        "runner_id",
        "command_ordinal",
        "command",
        "source_head_sha",
        "tested_sha",
        "started_at",
        "completed_at",
        "status",
        "exit_code",
        "diagnostic_summary",
        "diagnostic_truncated",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SuppliedCommandResult:
    plan_id: str
    invocation_id: str
    runner_id: str
    command_ordinal: int
    command: str
    source_head_sha: str
    tested_sha: str
    started_at: str
    completed_at: str
    status: CommandOutcome
    exit_code: int | None
    diagnostic_summary: str = ""
    diagnostic_truncated: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandResultEvidence:
    result_id: str
    plan_id: str
    invocation_id: str
    runner_id: str
    command_ordinal: int
    command: str
    source_head_sha: str
    tested_sha: str
    started_at: str
    completed_at: str
    status: CommandOutcome
    exit_code: int | None
    diagnostic_summary: str
    diagnostic_truncated: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationEvidenceBundle:
    schema_name: str
    schema_version: str
    status: BundleStatus
    bundle_id: str
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
    runner_id: str | None
    invocation_id: str | None
    started_at: str | None
    completed_at: str | None
    validation_plan: ValidationPlan | None
    command_results: tuple[CommandResultEvidence, ...]
    reason_codes: tuple[str, ...]
    details: tuple[str, ...]
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    attestation_verified: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def build_validation_evidence_bundle(
    governed_projection: object,
    validation_plan: object,
    command_results: tuple[SuppliedCommandResult, ...],
    *,
    expected_repository: RepositoryIdentity,
    expected_pull_request: int,
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
    expected_selector_version: str,
    expected_profile: str,
    expected_command_set_digest: str,
    expected_plan_id: str,
    runner_id: str,
    invocation_id: str,
    started_at: str,
    completed_at: str,
    schema_version: str = VALIDATION_EVIDENCE_BUNDLE_SCHEMA_VERSION,
) -> ValidationEvidenceBundle:
    """Bind supplied validation evidence without execution or external I/O."""
    invalid: set[str] = set()
    needs_decision: set[str] = set()
    incomplete: set[str] = set()
    details: set[str] = set()

    expected = {
        "repository": expected_repository,
        "pull_request": expected_pull_request,
        "base_branch": expected_base_branch,
        "base_sha": expected_base_sha,
        "source_head_sha": expected_source_head_sha,
        "tested_sha": expected_tested_sha,
        "repository_evidence_type": expected_repository_evidence_type,
        "projection_id": expected_projection_id,
        "proposal_id": expected_proposal_id,
        "approval_id": expected_approval_id,
        "repository_state_evidence_id": expected_repository_state_evidence_id,
        "implementation_contract_fingerprint": expected_implementation_contract_fingerprint,
        "selector_version": expected_selector_version,
        "profile": expected_profile,
        "command_set_digest": expected_command_set_digest,
        "plan_id": expected_plan_id,
        "runner_id": runner_id,
        "invocation_id": invocation_id,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    _validate_expectations(expected, schema_version, invalid)
    bundle_start = _timestamp(started_at)
    bundle_end = _timestamp(completed_at)

    projection = governed_projection if isinstance(governed_projection, GovernedProjectionEvidenceResult) else None
    if projection is None:
        invalid.add("projection.invalid-type")
    elif projection.status == "needs-decision":
        needs_decision.add("projection.needs-decision")
    elif projection.status != "accepted":
        invalid.add("projection.not-accepted")
    elif isinstance(expected_repository, RepositoryIdentity):
        _validate_projection(projection, expected, invalid)

    plan = validation_plan if isinstance(validation_plan, ValidationPlan) else None
    if plan is None:
        invalid.add("plan.invalid-type")
    else:
        plan_reasons = validate_validation_plan(plan)
        if plan_reasons:
            invalid.add("plan.invalid")
            details.update(f"plan:{reason}" for reason in plan_reasons)
        elif isinstance(expected_repository, RepositoryIdentity):
            _validate_plan(plan, expected, invalid, needs_decision)

    normalized: tuple[CommandResultEvidence, ...] = ()
    if not isinstance(command_results, tuple):
        invalid.add("results.invalid-collection")
    elif plan is not None and not validate_validation_plan(plan):
        normalized = _validate_results(
            command_results,
            plan=plan,
            expected=expected,
            bundle_start=bundle_start,
            bundle_end=bundle_end,
            invalid=invalid,
            incomplete=incomplete,
            details=details,
        )

    status, reasons = _status_for(invalid, needs_decision, incomplete, tuple(item.status for item in normalized))
    valid_plan = plan if plan is not None and not validate_validation_plan(plan) else None
    preliminary = ValidationEvidenceBundle(
        schema_name=VALIDATION_EVIDENCE_BUNDLE_SCHEMA_NAME,
        schema_version=VALIDATION_EVIDENCE_BUNDLE_SCHEMA_VERSION,
        status=status,
        bundle_id="",
        repository_identity=expected_repository if isinstance(expected_repository, RepositoryIdentity) else None,
        pull_request=expected_pull_request if _positive(expected_pull_request) else None,
        base_branch=_string_or_none(expected_base_branch),
        base_sha=_string_or_none(expected_base_sha),
        source_head_sha=_string_or_none(expected_source_head_sha),
        tested_sha=_string_or_none(expected_tested_sha),
        repository_evidence_type=expected_repository_evidence_type if isinstance(expected_repository_evidence_type, RepositoryEvidenceType) else None,
        projection_id=_string_or_none(expected_projection_id),
        proposal_id=_string_or_none(expected_proposal_id),
        approval_id=_string_or_none(expected_approval_id),
        repository_state_evidence_id=_string_or_none(expected_repository_state_evidence_id),
        implementation_contract_fingerprint=_string_or_none(expected_implementation_contract_fingerprint),
        selector_version=_string_or_none(expected_selector_version),
        profile=_string_or_none(expected_profile),
        command_set_digest=_string_or_none(expected_command_set_digest),
        plan_id=_string_or_none(expected_plan_id),
        runner_id=_string_or_none(runner_id),
        invocation_id=_string_or_none(invocation_id),
        started_at=_string_or_none(started_at),
        completed_at=_string_or_none(completed_at),
        validation_plan=valid_plan,
        command_results=normalized,
        reason_codes=tuple(sorted(reasons)),
        details=tuple(sorted(details)),
    )
    digest = _semantic_digest("agent-os-validation-evidence-bundle:v1", _bundle_payload(preliminary))
    return replace(preliminary, bundle_id=f"validation-evidence-bundle:{digest}")


def serialize_validation_evidence_bundle(bundle: ValidationEvidenceBundle) -> dict[str, object]:
    """Return canonical bundle data after verifying its semantic identity."""
    if not isinstance(bundle, ValidationEvidenceBundle):
        raise TypeError("bundle must be ValidationEvidenceBundle")
    payload = _bundle_payload(bundle)
    expected = "validation-evidence-bundle:" + _semantic_digest("agent-os-validation-evidence-bundle:v1", payload)
    if bundle.bundle_id != expected:
        raise ValueError("validation evidence bundle ID mismatch")
    serialized = dict(payload)
    serialized["bundle_id"] = bundle.bundle_id
    if len(_canonical_bytes(serialized)) > MAX_BUNDLE_SERIALIZED_BYTES:
        raise ValueError("validation evidence bundle exceeds canonical size limit")
    return serialized


def reconstruct_validation_evidence_bundle(payload: object) -> ValidationEvidenceBundle:
    """Reconstruct one exact canonical bundle without external I/O or authority."""
    value = _closed_mapping(payload, _BUNDLE_PAYLOAD_KEYS, "validation evidence bundle")
    for name in (
        "authoritative",
        "execution_authorized",
        "merge_authorized",
        "attestation_verified",
        "side_effects_performed",
    ):
        if value[name] is not False:
            raise ValueError(f"{name} must be false")
    if value["schema_name"] != VALIDATION_EVIDENCE_BUNDLE_SCHEMA_NAME:
        raise ValueError("validation evidence bundle schema name drift")
    if value["schema_version"] != VALIDATION_EVIDENCE_BUNDLE_SCHEMA_VERSION:
        raise ValueError("unsupported validation evidence bundle schema")
    repository = _reconstruct_repository_identity(value["repository_identity"])
    evidence_type = value["repository_evidence_type"]
    if type(evidence_type) is not str:
        raise ValueError("repository_evidence_type must be canonical text")
    try:
        repository_evidence_type = RepositoryEvidenceType(evidence_type)
    except ValueError as exc:
        raise ValueError("repository_evidence_type is unsupported") from exc
    validation_plan = _reconstruct_validation_plan(value["validation_plan"])
    command_results = _reconstruct_command_results(value["command_results"])
    reason_codes = _canonical_string_list(value["reason_codes"], "reason_codes")
    details = _canonical_string_list(value["details"], "details")
    bundle = ValidationEvidenceBundle(
        schema_name=value["schema_name"],
        schema_version=value["schema_version"],
        status=value["status"],
        bundle_id=value["bundle_id"],
        repository_identity=repository,
        pull_request=value["pull_request"],
        base_branch=value["base_branch"],
        base_sha=value["base_sha"],
        source_head_sha=value["source_head_sha"],
        tested_sha=value["tested_sha"],
        repository_evidence_type=repository_evidence_type,
        projection_id=value["projection_id"],
        proposal_id=value["proposal_id"],
        approval_id=value["approval_id"],
        repository_state_evidence_id=value["repository_state_evidence_id"],
        implementation_contract_fingerprint=value["implementation_contract_fingerprint"],
        selector_version=value["selector_version"],
        profile=value["profile"],
        command_set_digest=value["command_set_digest"],
        plan_id=value["plan_id"],
        runner_id=value["runner_id"],
        invocation_id=value["invocation_id"],
        started_at=value["started_at"],
        completed_at=value["completed_at"],
        validation_plan=validation_plan,
        command_results=command_results,
        reason_codes=reason_codes,
        details=details,
    )
    if serialize_validation_evidence_bundle(bundle) != dict(value):
        raise ValueError("validation evidence bundle is noncanonical")
    return bundle


def validation_evidence_bundle_id(bundle: ValidationEvidenceBundle) -> str:
    """Return the verified domain-separated semantic bundle identity."""
    return str(serialize_validation_evidence_bundle(bundle)["bundle_id"])


def _closed_mapping(value: object, keys: frozenset[str], name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    if set(value) != keys:
        raise ValueError(f"{name} fields drifted")
    return value


def _canonical_string_list(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise ValueError(f"{name} must be a list")
    result: list[str] = []
    for item in value:
        if type(item) is not str or not item or item != item.strip() or _CONTROL.search(item):
            raise ValueError(f"{name} contains noncanonical text")
        result.append(item)
    if tuple(sorted(set(result))) != tuple(result):
        raise ValueError(f"{name} must be canonically sorted and unique")
    return tuple(result)


def _reconstruct_repository_identity(payload: object) -> RepositoryIdentity:
    value = _closed_mapping(payload, _REPOSITORY_PAYLOAD_KEYS, "repository_identity")
    return RepositoryIdentity(**dict(value))


def _reconstruct_validation_plan(payload: object) -> ValidationPlan:
    value = _closed_mapping(payload, _PLAN_PAYLOAD_KEYS, "validation_plan")
    if value["schema_name"] != "agent-os-validation-plan":
        raise ValueError("validation plan schema name drift")
    if value["schema_version"] != "1.0":
        raise ValueError("unsupported validation plan schema")
    if value["execution_authorized"] is not False or value["side_effects_performed"] is not False:
        raise ValueError("validation plan authority fields must be false")
    if type(value["commands"]) is not list or type(value["reason_codes"]) is not list:
        raise ValueError("validation plan tuple fields must be lists")
    plan = ValidationPlan(
        selector_version=value["selector_version"],
        repository=value["repository"],
        pull_request=value["pull_request"],
        base_sha=value["base_sha"],
        head_sha=value["head_sha"],
        profile=value["profile"],
        commands=tuple(value["commands"]),
        command_set_digest=value["command_set_digest"],
        reason_codes=tuple(value["reason_codes"]),
        remote_build_required=value["remote_build_required"],
    )
    if serialize_validation_plan(plan) != dict(value):
        raise ValueError("validation plan is noncanonical")
    return plan


def _reconstruct_command_results(payload: object) -> tuple[CommandResultEvidence, ...]:
    if type(payload) is not list:
        raise ValueError("command_results must be a list")
    results: list[CommandResultEvidence] = []
    for raw in payload:
        value = _closed_mapping(raw, _RESULT_PAYLOAD_KEYS, "command result")
        result = CommandResultEvidence(**dict(value))
        expected_id = "command-result:" + _semantic_digest("agent-os-command-result:v1", _supplied_result_payload(SuppliedCommandResult(
            plan_id=result.plan_id,
            invocation_id=result.invocation_id,
            runner_id=result.runner_id,
            command_ordinal=result.command_ordinal,
            command=result.command,
            source_head_sha=result.source_head_sha,
            tested_sha=result.tested_sha,
            started_at=result.started_at,
            completed_at=result.completed_at,
            status=result.status,
            exit_code=result.exit_code,
            diagnostic_summary=result.diagnostic_summary,
            diagnostic_truncated=result.diagnostic_truncated,
        )))
        if result.result_id != expected_id:
            raise ValueError("command result ID mismatch")
        results.append(result)
    if tuple(item.command_ordinal for item in results) != tuple(range(len(results))):
        raise ValueError("command results must use canonical ordinal order")
    return tuple(results)


def _validate_expectations(value: dict[str, object], schema_version: object, invalid: set[str]) -> None:
    if schema_version != VALIDATION_EVIDENCE_BUNDLE_SCHEMA_VERSION:
        invalid.add("bundle.schema-version")
    if not isinstance(value["repository"], RepositoryIdentity):
        invalid.add("bundle.repository")
    if not _positive(value["pull_request"]):
        invalid.add("bundle.pull-request")
    if not _identifier(value["base_branch"]):
        invalid.add("bundle.base-branch")
    for key in ("base_sha", "source_head_sha", "tested_sha"):
        if not _fullmatch(_SHA40, value[key]):
            invalid.add(f"bundle.{key.replace('_', '-')}")
    if not isinstance(value["repository_evidence_type"], RepositoryEvidenceType):
        invalid.add("bundle.repository-evidence-type")
    for key in ("projection_id", "proposal_id", "approval_id", "repository_state_evidence_id", "selector_version", "profile", "plan_id"):
        if not _identifier(value[key]):
            invalid.add(f"bundle.{key.replace('_', '-')}")
    if not _fullmatch(_SHA256, value["implementation_contract_fingerprint"]):
        invalid.add("bundle.implementation-contract")
    digest = value["command_set_digest"]
    if value["profile"] == "manual-review":
        if digest != "unavailable":
            invalid.add("bundle.command-set-digest")
    elif not _fullmatch(_SHA256, digest):
        invalid.add("bundle.command-set-digest")
    for key in ("runner_id", "invocation_id"):
        if not _run_identifier(value[key]):
            invalid.add(f"bundle.{key.replace('_', '-')}")
    start, end = _timestamp(value["started_at"]), _timestamp(value["completed_at"])
    if start is None or end is None or end < start:
        invalid.add("bundle.timestamp")


def _validate_projection(projection: GovernedProjectionEvidenceResult, expected: dict[str, object], invalid: set[str]) -> None:
    checks = {
        "repository": (projection.repository_identity, expected["repository"]),
        "base-branch": (projection.base_branch, expected["base_branch"]),
        "base-sha": (projection.base_sha, expected["base_sha"]),
        "evaluated-sha": (projection.evaluated_sha, expected["base_sha"]),
        "source-head-sha": (projection.head_sha, expected["source_head_sha"]),
        "tested-sha": (projection.tested_sha, expected["tested_sha"]),
        "repository-evidence-type": (projection.repository_evidence_type, expected["repository_evidence_type"]),
        "projection-id": (projection.projection_id, expected["projection_id"]),
        "proposal-id": (projection.proposal_id, expected["proposal_id"]),
        "approval-id": (projection.approval_id, expected["approval_id"]),
        "repository-evidence-id": (projection.repository_state_evidence_id, expected["repository_state_evidence_id"]),
        "implementation-contract": (projection.implementation_contract_fingerprint, expected["implementation_contract_fingerprint"]),
    }
    for label, (actual, wanted) in checks.items():
        if actual != wanted:
            invalid.add(f"projection.{label}-mismatch")
    if any(value is not False for value in (projection.authoritative, projection.execution_authorized, projection.side_effects_performed)):
        invalid.add("projection.authority")


def _validate_plan(plan: ValidationPlan, expected: dict[str, object], invalid: set[str], needs_decision: set[str]) -> None:
    repository = expected["repository"]
    assert isinstance(repository, RepositoryIdentity)
    canonical_digest = plan.command_set_digest if plan.profile == "manual-review" else compute_command_set_digest(plan.selector_version, plan.commands)
    checks = {
        "repository": (plan.repository.lower(), f"{repository.owner}/{repository.repository}"),
        "pull-request": (plan.pull_request, expected["pull_request"]),
        "base-sha": (plan.base_sha, expected["base_sha"]),
        "source-head-sha": (plan.head_sha, expected["source_head_sha"]),
        "selector-version": (plan.selector_version, expected["selector_version"]),
        "profile": (plan.profile, expected["profile"]),
        "command-digest": (plan.command_set_digest, expected["command_set_digest"]),
        "recomputed-command-digest": (canonical_digest, expected["command_set_digest"]),
        "plan-id": (validation_plan_id(plan), expected["plan_id"]),
    }
    for label, (actual, wanted) in checks.items():
        if actual != wanted:
            invalid.add(f"plan.{label}-mismatch")
    if plan.profile == "manual-review":
        needs_decision.add("plan.manual-review")


def _validate_results(supplied: tuple[SuppliedCommandResult, ...], *, plan: ValidationPlan, expected: dict[str, object], bundle_start: datetime | None, bundle_end: datetime | None, invalid: set[str], incomplete: set[str], details: set[str]) -> tuple[CommandResultEvidence, ...]:
    if plan.profile in {"static", "manual-review"}:
        if supplied:
            invalid.add(f"results.{plan.profile}-extra")
        return ()
    if len(supplied) < len(plan.commands):
        incomplete.add("results.missing")
    if len(supplied) > len(plan.commands):
        invalid.add("results.extra")
    normalized: list[CommandResultEvidence] = []
    seen: set[int] = set()
    for position, item in enumerate(supplied):
        errors = _result_errors(item, position=position, plan=plan, expected=expected, bundle_start=bundle_start, bundle_end=bundle_end, seen=seen)
        if errors:
            invalid.add("results.invalid")
            details.update(f"result-{position}:{error}" for error in errors)
            continue
        assert isinstance(item, SuppliedCommandResult)
        seen.add(item.command_ordinal)
        payload = _supplied_result_payload(item)
        result_id = "command-result:" + _semantic_digest("agent-os-command-result:v1", payload)
        normalized.append(CommandResultEvidence(result_id=result_id, **payload))
    return tuple(normalized)


def _result_errors(item: object, *, position: int, plan: ValidationPlan, expected: dict[str, object], bundle_start: datetime | None, bundle_end: datetime | None, seen: set[int]) -> tuple[str, ...]:
    if not isinstance(item, SuppliedCommandResult):
        return ("invalid-item",)
    errors: set[str] = set()
    for label, actual, wanted in (
        ("plan-id", item.plan_id, expected["plan_id"]),
        ("runner-id", item.runner_id, expected["runner_id"]),
        ("invocation-id", item.invocation_id, expected["invocation_id"]),
        ("source-head-sha", item.source_head_sha, expected["source_head_sha"]),
        ("tested-sha", item.tested_sha, expected["tested_sha"]),
    ):
        if actual != wanted:
            errors.add(f"{label}-mismatch")
    if not _nonnegative(item.command_ordinal):
        errors.add("ordinal-invalid")
    else:
        if item.command_ordinal in seen:
            errors.add("ordinal-duplicate")
        if item.command_ordinal != position:
            errors.add("order-mismatch")
        if item.command_ordinal >= len(plan.commands):
            errors.add("ordinal-extra")
        elif item.command != plan.commands[item.command_ordinal]:
            errors.add("command-mismatch")
    if item.status not in _OUTCOMES:
        errors.add("status-invalid")
    elif item.status == "passed" and item.exit_code != 0:
        errors.add("exit-code-invalid")
    elif item.status == "failed" and (not isinstance(item.exit_code, int) or isinstance(item.exit_code, bool) or item.exit_code == 0):
        errors.add("exit-code-invalid")
    elif item.status not in {"passed", "failed"} and item.exit_code is not None:
        errors.add("exit-code-invalid")
    start, end = _timestamp(item.started_at), _timestamp(item.completed_at)
    if start is None or end is None or end < start:
        errors.add("timestamp-invalid")
    elif bundle_start is not None and bundle_end is not None and (start < bundle_start or end > bundle_end):
        errors.add("timestamp-outside-invocation")
    if not isinstance(item.diagnostic_summary, str) or len(item.diagnostic_summary) > MAX_RESULT_DIAGNOSTIC_LENGTH or _CONTROL.search(item.diagnostic_summary or "") or _SECRET.search(item.diagnostic_summary or ""):
        errors.add("diagnostic-invalid")
    if not isinstance(item.diagnostic_truncated, bool):
        errors.add("diagnostic-truncated-invalid")
    return tuple(sorted(errors))


def _status_for(invalid: set[str], needs_decision: set[str], incomplete: set[str], outcomes: tuple[str, ...]) -> tuple[BundleStatus, set[str]]:
    if invalid:
        return "invalid", invalid
    if needs_decision:
        return "needs-decision", needs_decision
    if incomplete:
        return "incomplete", incomplete
    if any(item in {"unavailable", "infrastructure-error"} for item in outcomes):
        return "needs-decision", {"results.unavailable"}
    if "timed-out" in outcomes:
        return "timed-out", {"results.timed-out"}
    if "cancelled" in outcomes:
        return "cancelled", {"results.cancelled"}
    if "failed" in outcomes:
        return "failed", {"results.failed"}
    return "passed", set()


def _bundle_payload(bundle: ValidationEvidenceBundle) -> dict[str, object]:
    return {
        "schema_name": bundle.schema_name,
        "schema_version": bundle.schema_version,
        "status": bundle.status,
        "repository_identity": _repository_payload(bundle.repository_identity),
        "pull_request": bundle.pull_request,
        "base_branch": bundle.base_branch,
        "base_sha": bundle.base_sha,
        "source_head_sha": bundle.source_head_sha,
        "tested_sha": bundle.tested_sha,
        "repository_evidence_type": bundle.repository_evidence_type.value if isinstance(bundle.repository_evidence_type, RepositoryEvidenceType) else None,
        "projection_id": bundle.projection_id,
        "proposal_id": bundle.proposal_id,
        "approval_id": bundle.approval_id,
        "repository_state_evidence_id": bundle.repository_state_evidence_id,
        "implementation_contract_fingerprint": bundle.implementation_contract_fingerprint,
        "selector_version": bundle.selector_version,
        "profile": bundle.profile,
        "command_set_digest": bundle.command_set_digest,
        "plan_id": bundle.plan_id,
        "runner_id": bundle.runner_id,
        "invocation_id": bundle.invocation_id,
        "started_at": bundle.started_at,
        "completed_at": bundle.completed_at,
        "validation_plan": serialize_validation_plan(bundle.validation_plan) if bundle.validation_plan is not None else None,
        "command_results": [_result_payload(item) for item in bundle.command_results],
        "reason_codes": list(bundle.reason_codes),
        "details": list(bundle.details),
        "authoritative": False,
        "execution_authorized": False,
        "merge_authorized": False,
        "attestation_verified": False,
        "side_effects_performed": False,
    }


def _supplied_result_payload(item: SuppliedCommandResult) -> dict[str, object]:
    return {
        "plan_id": item.plan_id,
        "invocation_id": item.invocation_id,
        "runner_id": item.runner_id,
        "command_ordinal": item.command_ordinal,
        "command": item.command,
        "source_head_sha": item.source_head_sha,
        "tested_sha": item.tested_sha,
        "started_at": item.started_at,
        "completed_at": item.completed_at,
        "status": item.status,
        "exit_code": item.exit_code,
        "diagnostic_summary": item.diagnostic_summary,
        "diagnostic_truncated": item.diagnostic_truncated,
    }


def _result_payload(item: CommandResultEvidence) -> dict[str, object]:
    payload = _supplied_result_payload(SuppliedCommandResult(
        plan_id=item.plan_id,
        invocation_id=item.invocation_id,
        runner_id=item.runner_id,
        command_ordinal=item.command_ordinal,
        command=item.command,
        source_head_sha=item.source_head_sha,
        tested_sha=item.tested_sha,
        started_at=item.started_at,
        completed_at=item.completed_at,
        status=item.status,
        exit_code=item.exit_code,
        diagnostic_summary=item.diagnostic_summary,
        diagnostic_truncated=item.diagnostic_truncated,
    ))
    return {"result_id": item.result_id, **payload}


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


def _semantic_digest(domain: str, payload: dict[str, object]) -> str:
    return hashlib.sha256(domain.encode("utf-8") + b"\0" + _canonical_bytes(payload)).hexdigest()


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= MAX_RUN_ID_LENGTH and _CONTROL.search(value) is None


def _run_identifier(value: object) -> bool:
    return _identifier(value) and isinstance(value, str) and _RUN_ID.fullmatch(value) is not None


def _fullmatch(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _positive(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None
