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
    expected_projection_id: str | None = None,
    expected_approval_id: str | None = None,
    expected_proposal_id: str | None = None,
    schema_version: str = GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION,
) -> GovernedProjectionEvidenceResult:
    """Validate and compare one projection with one repository-state evidence value."""

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
        reasons.add("schema.unknown-field")
        details.add("expected-repository:invalid")
    if not isinstance(expected_base_branch, str) or not expected_base_branch.strip():
        reasons.add("schema.unknown-field")
        details.add("expected-base-branch:invalid")
    if not _is_sha(expected_base_sha):
        reasons.add("schema.unknown-field")
        details.add("expected-base-sha:invalid")
    if not _is_sha(expected_head_sha):
        reasons.add("schema.unknown-field")
        details.add("expected-head-sha:invalid")

    verified_projection = _verified_projection(projection, reasons, details)
    expected_contract = (
        verified_projection.implementation_contract_fingerprint
        if verified_projection is not None
        else None
    )
    repository_result = validate_repository_state_evidence(
        repository_state_evidence,
        expected_repository=expected_repository if valid_repository else None,
        expected_base_ref=(
            expected_base_branch
            if isinstance(expected_base_branch, str) and expected_base_branch.strip()
            else None
        ),
        expected_base_sha=expected_base_sha if _is_sha(expected_base_sha) else None,
        expected_head_sha=expected_head_sha if _is_sha(expected_head_sha) else None,
        expected_requested_sha=expected_head_sha if _is_sha(expected_head_sha) else None,
        expected_contract_fingerprint=expected_contract,
    )
    reasons.update(repository_result.reason_codes)
    details.update(f"repository:{item}" for item in repository_result.details)

    if verified_projection is not None:
        _compare_projection(
            verified_projection,
            repository_result,
            expected_repository=expected_repository if valid_repository else None,
            expected_base_branch=expected_base_branch,
            expected_head_sha=expected_head_sha,
            expected_projection_id=expected_projection_id,
            expected_approval_id=expected_approval_id,
            expected_proposal_id=expected_proposal_id,
            reasons=reasons,
            details=details,
        )

    status = _status_for(reasons, repository_result.outcome)
    return GovernedProjectionEvidenceResult(
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
        implementation_contract_fingerprint=(
            repository_result.contract_fingerprint
        ),
        reason_codes=tuple(reasons),
        details=tuple(details),
    )


def _verified_projection(
    projection: object,
    reasons: set[str],
    details: set[str],
):
    from scripts.agent_os_issue_acceptance.approved_execution_projection import (
        APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION,
        ApprovedExecutionProjection,
        serialize_approved_execution_projection,
    )

    if not isinstance(projection, ApprovedExecutionProjection):
        if isinstance(projection, Mapping):
            version = projection.get("schema_version")
            if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
                reasons.add("schema.malformed-version")
                details.add("projection-schema:malformed")
            elif version != APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION:
                reasons.add("schema.unsupported-version")
                details.add("projection-schema:unsupported")
            if projection.get("execution_authorized", False) is not False or projection.get(
                "side_effects_performed", False
            ) is not False or projection.get("authoritative", False) is not False:
                details.add("projection-authority:invalid")
            reasons.add("schema.unknown-field")
            details.add("projection:canonical-object-required")
        else:
            reasons.add("schema.unknown-field")
            details.add("projection:invalid-type")
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
    expected_head_sha: str,
    expected_projection_id: str | None,
    expected_approval_id: str | None,
    expected_proposal_id: str | None,
    reasons: set[str],
    details: set[str],
) -> None:
    if expected_repository is not None:
        expected_name = f"{expected_repository.owner}/{expected_repository.repository}"
        if projection.repository.lower() != expected_name:
            reasons.add("repo.identity-mismatch")
            details.add("projection-repository:mismatch")
    if projection.base_branch != expected_base_branch:
        reasons.add("ref.base-mismatch")
        details.add("projection-base-branch:mismatch")
    if projection.evaluated_repository_sha != expected_head_sha:
        reasons.add("ref.branch-moved")
        details.add("projection-evaluated-sha:mismatch")
    if (
        repository_result.head_sha is not None
        and projection.evaluated_repository_sha != repository_result.head_sha
    ):
        reasons.add("ref.branch-moved")
        details.add("projection-repository-head:mismatch")
    if projection.tested_repository_sha != repository_result.tested_sha:
        reasons.add("ref.test-sha-mismatch")
        details.add("projection-tested-sha:mismatch")
    if (
        repository_result.evidence_type is None
        or projection.repository_evidence_type != repository_result.evidence_type.value
    ):
        reasons.add("ref.test-sha-mismatch")
        details.add("projection-evidence-type:mismatch")
    if projection.repository_state_evidence_id != repository_result.evidence_id:
        reasons.add("ref.contract-mismatch")
        details.add("projection-repository-evidence-id:mismatch")
    if (
        projection.implementation_contract_fingerprint
        != repository_result.contract_fingerprint
    ):
        reasons.add("ref.contract-mismatch")
        details.add("projection-implementation-contract:mismatch")

    for expected, actual, label in (
        (expected_projection_id, projection.projection_id, "projection-id"),
        (expected_approval_id, projection.approval_id, "approval-id"),
        (expected_proposal_id, projection.proposal_id, "proposal-id"),
    ):
        if expected is not None and expected != actual:
            reasons.add("ref.contract-mismatch")
            details.add(f"{label}:mismatch")


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


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA40_RE.fullmatch(value) is not None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
