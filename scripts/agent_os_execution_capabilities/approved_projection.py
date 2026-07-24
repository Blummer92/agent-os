from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from .models import (
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    RepositoryStateValidationResult,
)
from .reason_codes import normalize_reason_codes
from .repository_state import validate_repository_state_evidence

GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION = "1.0"

_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RESULT_STATUSES = frozenset(
    {"accepted", "stale", "blocked", "invalid", "needs-decision"}
)
_INVALID_REASON_CODES = frozenset(
    {
        "schema.malformed-version",
        "schema.unsupported-version",
        "schema.unknown-field",
        "adapter.incompatible",
    }
)
_BLOCKING_REASON_CODES = frozenset(
    {
        "worktree.uncommitted",
        "worktree.dirty",
        "worktree.untracked",
        "worktree.ignored-relevant",
        "worktree.operation-unresolved",
        "worktree.detached-head",
        "worktree.shallow-history",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernedProjectionEvidenceResult:
    """Deterministic, non-authoritative comparison of supplied immutable evidence."""

    status: str
    schema_version: str
    projection_id: str | None
    proposal_id: str | None
    approval_id: str | None
    repository_identity: RepositoryIdentity | None
    base_branch: str | None
    base_sha: str | None
    head_sha: str | None
    evaluated_sha: str | None
    tested_sha: str | None
    repository_evidence_type: RepositoryEvidenceType | None
    repository_state_evidence_id: str | None
    implementation_contract_fingerprint: str | None
    reason_codes: tuple[str, ...]
    details: tuple[str, ...]
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.status not in _RESULT_STATUSES:
            raise ValueError("unsupported governed projection evidence status")
        if self.schema_version != GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("unsupported governed projection evidence schema version")
        reasons = normalize_reason_codes(self.reason_codes)
        details = tuple(sorted(set(str(item) for item in self.details)))
        if self.status == "accepted" and reasons:
            raise ValueError("accepted evidence cannot carry reason codes")
        if self.status != "accepted" and not reasons:
            raise ValueError("non-accepted evidence requires reason codes")
        if self.status == "accepted" and not _accepted_bindings_complete(self):
            raise ValueError("accepted evidence requires complete governed bindings")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "details", details)


def consume_approved_projection_evidence(
    projection: object,
    repository_state_evidence: RepositoryStateEvidence | Mapping[str, object],
    *,
    expected_repository: RepositoryIdentity,
    expected_base_branch: str,
    expected_base_sha: str,
    expected_head_sha: str,
    expected_tested_sha: str,
    expected_projection_id: str,
    expected_approval_id: str,
    expected_proposal_id: str,
    expected_repository_state_evidence_id: str,
    expected_implementation_contract_fingerprint: str,
    expected_repository_evidence_type: RepositoryEvidenceType,
    schema_version: str = GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION,
) -> GovernedProjectionEvidenceResult:
    """Validate one canonical projection against supplied repository-state evidence."""

    reasons: set[str] = set()
    details: set[str] = set()

    if not isinstance(schema_version, str) or not _VERSION_RE.fullmatch(schema_version):
        reasons.add("schema.malformed-version")
        details.add("consumer-schema:malformed")
    elif schema_version != GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION:
        reasons.add("schema.unsupported-version")
        details.add("consumer-schema:unsupported")

    valid_repository = isinstance(expected_repository, RepositoryIdentity)
    if not valid_repository:
        _invalid_expectation(reasons, details, "repository")
    if not _nonempty_string(expected_base_branch):
        _invalid_expectation(reasons, details, "base-branch")
    if not _is_sha(expected_base_sha):
        _invalid_expectation(reasons, details, "base-sha")
    if not _is_sha(expected_head_sha):
        _invalid_expectation(reasons, details, "head-sha")
    if not _is_sha(expected_tested_sha):
        _invalid_expectation(reasons, details, "tested-sha")
    for label, value in (
        ("projection-id", expected_projection_id),
        ("approval-id", expected_approval_id),
        ("proposal-id", expected_proposal_id),
        ("repository-evidence-id", expected_repository_state_evidence_id),
    ):
        if not _nonempty_string(value):
            _invalid_expectation(reasons, details, label)
    if not _is_fingerprint(expected_implementation_contract_fingerprint):
        _invalid_expectation(reasons, details, "implementation-contract")
    if not isinstance(expected_repository_evidence_type, RepositoryEvidenceType):
        _invalid_expectation(reasons, details, "repository-evidence-type")

    verified_projection = _verified_projection(projection, reasons, details)
    repository_result = validate_repository_state_evidence(
        repository_state_evidence,
        expected_repository=expected_repository if valid_repository else None,
        expected_base_ref=(
            expected_base_branch if _nonempty_string(expected_base_branch) else None
        ),
        expected_base_sha=expected_base_sha if _is_sha(expected_base_sha) else None,
        expected_head_sha=expected_head_sha if _is_sha(expected_head_sha) else None,
        expected_requested_sha=expected_head_sha if _is_sha(expected_head_sha) else None,
        expected_contract_fingerprint=(
            expected_implementation_contract_fingerprint
            if _is_fingerprint(expected_implementation_contract_fingerprint)
            else None
        ),
    )
    reasons.update(repository_result.reason_codes)
    details.update(f"repository:{item}" for item in repository_result.details)

    if verified_projection is not None:
        _compare_projection(
            verified_projection,
            repository_result,
            expected_repository=expected_repository if valid_repository else None,
            expected_base_branch=expected_base_branch,
            expected_base_sha=expected_base_sha,
            expected_head_sha=expected_head_sha,
            expected_tested_sha=expected_tested_sha,
            expected_projection_id=expected_projection_id,
            expected_approval_id=expected_approval_id,
            expected_proposal_id=expected_proposal_id,
            expected_repository_state_evidence_id=(
                expected_repository_state_evidence_id
            ),
            expected_implementation_contract_fingerprint=(
                expected_implementation_contract_fingerprint
            ),
            expected_repository_evidence_type=expected_repository_evidence_type,
            reasons=reasons,
            details=details,
        )

    status = _status_for(reasons, repository_result.outcome)
    result = GovernedProjectionEvidenceResult(
        status=status,
        schema_version=GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION,
        projection_id=getattr(verified_projection, "projection_id", None),
        proposal_id=getattr(verified_projection, "proposal_id", None),
        approval_id=getattr(verified_projection, "approval_id", None),
        repository_identity=repository_result.repository_identity,
        base_branch=(
            getattr(verified_projection, "base_branch", None)
            or repository_result.base_ref
        ),
        base_sha=repository_result.base_sha,
        head_sha=repository_result.head_sha,
        evaluated_sha=getattr(
            verified_projection, "evaluated_repository_sha", None
        ),
        tested_sha=repository_result.tested_sha,
        repository_evidence_type=repository_result.evidence_type,
        repository_state_evidence_id=repository_result.evidence_id or None,
        implementation_contract_fingerprint=repository_result.contract_fingerprint,
        reason_codes=tuple(reasons),
        details=tuple(details),
    )
    if status == "accepted" and not _accepted_bindings_complete(result):
        return GovernedProjectionEvidenceResult(
            status="invalid",
            schema_version=GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION,
            projection_id=result.projection_id,
            proposal_id=result.proposal_id,
            approval_id=result.approval_id,
            repository_identity=result.repository_identity,
            base_branch=result.base_branch,
            base_sha=result.base_sha,
            head_sha=result.head_sha,
            evaluated_sha=result.evaluated_sha,
            tested_sha=result.tested_sha,
            repository_evidence_type=result.repository_evidence_type,
            repository_state_evidence_id=result.repository_state_evidence_id,
            implementation_contract_fingerprint=(
                result.implementation_contract_fingerprint
            ),
            reason_codes=("schema.unknown-field",),
            details=("accepted-bindings:incomplete",),
        )
    return result


def _verified_projection(
    projection: object,
    reasons: set[str],
    details: set[str],
):
    from scripts.agent_os_issue_acceptance.approved_execution_projection import (
        ApprovedExecutionProjection,
        serialize_approved_execution_projection,
    )

    if not isinstance(projection, ApprovedExecutionProjection):
        reasons.add("schema.unknown-field")
        details.add("projection:canonical-object-required")
        return None

    try:
        serialize_approved_execution_projection(projection)
    except (TypeError, ValueError):
        reasons.add("schema.unknown-field")
        details.add("projection:canonical-validation-failed")
        return None

    if (
        projection.complete is not True
        or projection.authoritative is not False
        or projection.execution_authorized is not False
        or projection.side_effects_performed is not False
    ):
        reasons.add("schema.unknown-field")
        details.add("projection-authority:invalid")
        return None

    decision_at = _timestamp(projection.approval_decision_at)
    projected_at = _timestamp(projection.projected_at)
    expires_at = (
        _timestamp(projection.approval_expires_at)
        if projection.approval_expires_at is not None
        else None
    )
    if decision_at is None or projected_at is None:
        reasons.add("schema.unknown-field")
        details.add("projection-timestamp:invalid")
    elif projected_at < decision_at:
        reasons.add("schema.unknown-field")
        details.add("projection-timestamp:precedes-approval")
    if expires_at is not None and projected_at is not None and projected_at >= expires_at:
        reasons.add("ref.contract-mismatch")
        details.add("approval:expired-at-projection-boundary")
    return projection


def _compare_projection(
    projection,
    repository_result: RepositoryStateValidationResult,
    *,
    expected_repository: RepositoryIdentity | None,
    expected_base_branch: str,
    expected_base_sha: str,
    expected_head_sha: str,
    expected_tested_sha: str,
    expected_projection_id: str,
    expected_approval_id: str,
    expected_proposal_id: str,
    expected_repository_state_evidence_id: str,
    expected_implementation_contract_fingerprint: str,
    expected_repository_evidence_type: RepositoryEvidenceType,
    reasons: set[str],
    details: set[str],
) -> None:
    if expected_repository is not None:
        expected_name = f"{expected_repository.owner}/{expected_repository.repository}"
        if projection.repository.lower() != expected_name:
            _stale(reasons, details, "repo.identity-mismatch", "projection-repository")
    if projection.base_branch != expected_base_branch:
        _stale(reasons, details, "ref.base-mismatch", "projection-base-branch")
    if projection.evaluated_repository_sha != expected_base_sha:
        _stale(reasons, details, "ref.base-mismatch", "projection-evaluated-sha")
    if (
        repository_result.base_sha is not None
        and projection.evaluated_repository_sha != repository_result.base_sha
    ):
        _stale(reasons, details, "ref.base-mismatch", "projection-repository-base")

    if repository_result.head_sha != expected_head_sha:
        _stale(reasons, details, "ref.branch-moved", "repository-head-sha")
    if projection.tested_repository_sha != expected_tested_sha:
        _stale(reasons, details, "ref.test-sha-mismatch", "projection-tested-sha")
    if repository_result.tested_sha != expected_tested_sha:
        _stale(reasons, details, "ref.test-sha-mismatch", "repository-tested-sha")

    expected_type_value = (
        expected_repository_evidence_type.value
        if isinstance(expected_repository_evidence_type, RepositoryEvidenceType)
        else None
    )
    if projection.repository_evidence_type != expected_type_value:
        _stale(reasons, details, "ref.test-sha-mismatch", "projection-evidence-type")
    if repository_result.evidence_type != expected_repository_evidence_type:
        _stale(reasons, details, "ref.test-sha-mismatch", "repository-evidence-type")

    for expected, actual, label in (
        (expected_projection_id, projection.projection_id, "projection-id"),
        (expected_approval_id, projection.approval_id, "approval-id"),
        (expected_proposal_id, projection.proposal_id, "proposal-id"),
        (
            expected_repository_state_evidence_id,
            projection.repository_state_evidence_id,
            "projection-repository-evidence-id",
        ),
        (
            expected_repository_state_evidence_id,
            repository_result.evidence_id,
            "repository-evidence-id",
        ),
        (
            expected_implementation_contract_fingerprint,
            projection.implementation_contract_fingerprint,
            "projection-implementation-contract",
        ),
        (
            expected_implementation_contract_fingerprint,
            repository_result.contract_fingerprint,
            "repository-implementation-contract",
        ),
    ):
        if expected != actual:
            _stale(reasons, details, "ref.contract-mismatch", label)


def _accepted_bindings_complete(result: GovernedProjectionEvidenceResult) -> bool:
    return (
        result.repository_identity is not None
        and _nonempty_string(result.projection_id)
        and _nonempty_string(result.proposal_id)
        and _nonempty_string(result.approval_id)
        and _nonempty_string(result.base_branch)
        and _is_sha(result.base_sha)
        and _is_sha(result.head_sha)
        and _is_sha(result.evaluated_sha)
        and _is_sha(result.tested_sha)
        and isinstance(result.repository_evidence_type, RepositoryEvidenceType)
        and _nonempty_string(result.repository_state_evidence_id)
        and _is_fingerprint(result.implementation_contract_fingerprint)
    )


def _status_for(reasons: set[str], repository_outcome: str) -> str:
    if not reasons and repository_outcome == "valid":
        return "accepted"
    if reasons & _INVALID_REASON_CODES or repository_outcome == "invalid":
        return "invalid"
    if "worktree.indeterminate" in reasons or repository_outcome == "needs-decision":
        return "needs-decision"
    if reasons & _BLOCKING_REASON_CODES or repository_outcome == "blocked":
        return "blocked"
    return "stale"


def _invalid_expectation(
    reasons: set[str], details: set[str], label: str
) -> None:
    reasons.add("schema.unknown-field")
    details.add(f"expected-{label}:invalid")


def _stale(
    reasons: set[str], details: set[str], reason: str, label: str
) -> None:
    reasons.add(reason)
    details.add(f"{label}:mismatch")


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA40_RE.fullmatch(value) is not None


def _is_fingerprint(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
