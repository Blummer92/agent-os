"""Frozen data models for the exact-issue readiness candidate-packet stage.

This module defines only data shapes (requests, evidence wrappers, results)
plus their canonical serialize/deserialize helpers. It does not reimplement
scanning, IssuePlan current-state projection, or readiness evaluation --
those live in ``scripts.agent_os_issue_acceptance`` and are reused as-is by
``readiness_stage.py``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping, Protocol

from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    IssuePlanCurrentStateEvidence,
    IssuePlanSourceSnapshot,
)
from scripts.agent_os_issue_acceptance.models import (
    AcceptanceReport,
    CheckResult,
    LinkedIssueCandidate,
    LinkedIssueParseResult,
    Status,
)
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome, ReadinessResult

STAGE_SCHEMA_VERSION = "1.0"


class IssueReadStatus(str, Enum):
    """Outcome of one read-only, single-issue fetch attempt."""

    OK = "ok"
    NOT_FOUND = "not-found"
    PERMISSION_DENIED = "permission-denied"
    SOURCE_INACCESSIBLE = "source-inaccessible"
    MALFORMED_RESPONSE = "malformed-response"
    API_ERROR = "api-error"


@dataclass(frozen=True, slots=True)
class IssueReadResult:
    """Read-only adapter response for one exact issue fetch."""

    status: IssueReadStatus
    item: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, IssueReadStatus):
            raise TypeError("status must be an IssueReadStatus")
        if self.status == IssueReadStatus.OK and self.item is None:
            raise ValueError("ok status requires an item")
        if self.status != IssueReadStatus.OK and self.item is not None:
            raise ValueError("non-ok status must not carry an item")


class EvidenceStatus(str, Enum):
    """Bounded tri-state (plus failure) outcome for one evidence adapter call."""

    RESOLVED_CLEAR = "resolved-clear"
    RESOLVED_BLOCKED = "resolved-blocked"
    NEEDS_DECISION = "needs-decision"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DependencyEvidence:
    """Explicit dependency-readiness adapter result. Never a guessed boolean."""

    status: EvidenceStatus
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    details: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.status, EvidenceStatus):
            raise TypeError("status must be an EvidenceStatus")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "details", tuple(self.details))


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    """Explicit validation-readiness adapter result. Never a guessed boolean."""

    status: EvidenceStatus
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    details: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.status, EvidenceStatus):
            raise TypeError("status must be an EvidenceStatus")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "details", tuple(self.details))


class IssueSourceReader(Protocol):
    """Read-only single-issue reader. No write method exists on this protocol."""

    def read_issue(self, repository: str, issue_number: int) -> IssueReadResult:
        """Return the current state of exactly one issue."""


class RepositoryEvidenceReader(Protocol):
    """Read-only dependency/validation evidence reader. No write methods exist."""

    def read_dependency_evidence(
        self, repository: str, issue_number: int
    ) -> DependencyEvidence:
        """Return dependency-readiness evidence for one issue."""

    def read_validation_evidence(
        self, repository: str, issue_number: int
    ) -> ValidationEvidence:
        """Return validation-readiness evidence for one issue."""


@dataclass(frozen=True, slots=True)
class IssueSnapshot:
    """Exact, preserved snapshot of one fetched GitHub issue."""

    repository: str
    issue_number: int
    url: str
    created_at: str
    updated_at: str
    body: str
    body_sha256: str
    source_revision: str
    retrieved_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.issue_number, int) or isinstance(self.issue_number, bool):
            raise TypeError("issue_number must be an int")
        expected_digest = hashlib.sha256(self.body.encode("utf-8")).hexdigest()
        if self.body_sha256 != expected_digest:
            raise ValueError("body_sha256 does not match body")


class IssueSourceStageStatus(str, Enum):
    RESOLVED = "resolved"
    SOURCE_FAILURE = "source-failure"
    INCOMPLETE_EVIDENCE = "incomplete-evidence"


@dataclass(frozen=True, slots=True)
class IssueSourceStageResult:
    """Result of resolving one exact issue snapshot, fail-closed on any doubt."""

    status: IssueSourceStageStatus
    snapshot: IssueSnapshot | None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    details: tuple[str, ...] = field(default_factory=tuple)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, IssueSourceStageStatus):
            raise TypeError("status must be an IssueSourceStageStatus")
        if self.status == IssueSourceStageStatus.RESOLVED and self.snapshot is None:
            raise ValueError("resolved status requires a snapshot")
        if self.status != IssueSourceStageStatus.RESOLVED and self.snapshot is not None:
            raise ValueError("non-resolved status must not carry a snapshot")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "details", tuple(self.details))


class IssueReadinessStageStatus(str, Enum):
    """Final, distinct stage outcomes -- never inferred from each other."""

    READY = "ready"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs-decision"
    SOURCE_FAILURE = "source-failure"
    INCOMPLETE_EVIDENCE = "incomplete-evidence"


_READINESS_OUTCOME_MAP = {
    ReadinessOutcome.READY: IssueReadinessStageStatus.READY,
    ReadinessOutcome.BLOCKED: IssueReadinessStageStatus.BLOCKED,
    ReadinessOutcome.NEEDS_DECISION: IssueReadinessStageStatus.NEEDS_DECISION,
}


@dataclass(frozen=True, slots=True)
class IssueReadinessStageRequest:
    """Bounded request describing exactly which issue snapshot to prepare."""

    repository: str
    issue_number: int
    observed_at: str
    freshness_boundary: str = "stage-observation"
    expected_source_revision: str | None = None
    governed_field_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.issue_number, int) or isinstance(self.issue_number, bool):
            raise TypeError("issue_number must be an int")
        object.__setattr__(
            self, "governed_field_names", tuple(self.governed_field_names)
        )


@dataclass(frozen=True, slots=True)
class IssueReadinessStageResult:
    """Round-trippable, read-only candidate-packet readiness stage output."""

    status: IssueReadinessStageStatus
    snapshot: IssueSnapshot | None
    issueplan_current_state_evidence: IssuePlanCurrentStateEvidence | None
    readiness_result: ReadinessResult | None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    details: tuple[str, ...] = field(default_factory=tuple)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, IssueReadinessStageStatus):
            raise TypeError("status must be an IssueReadinessStageStatus")
        resolved = self.status in {
            IssueReadinessStageStatus.READY,
            IssueReadinessStageStatus.BLOCKED,
            IssueReadinessStageStatus.NEEDS_DECISION,
        }
        if resolved and (self.snapshot is None or self.readiness_result is None):
            raise ValueError("resolved statuses require a snapshot and readiness result")
        if not resolved and (self.snapshot is not None or self.readiness_result is not None):
            raise ValueError("unresolved statuses must not carry snapshot/readiness evidence")
        if resolved and self.readiness_result is not None:
            expected = _READINESS_OUTCOME_MAP[self.readiness_result.outcome]
            if expected != self.status:
                raise ValueError("status must match the readiness outcome")
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        object.__setattr__(self, "details", tuple(self.details))


# --------------------------------------------------------------------------
# Canonical serialization -- round trip without semantic drift.
# --------------------------------------------------------------------------


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def issue_snapshot_to_dict(snapshot: IssueSnapshot) -> dict[str, Any]:
    return {
        "repository": snapshot.repository,
        "issue_number": snapshot.issue_number,
        "url": snapshot.url,
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
        "body": snapshot.body,
        "body_sha256": snapshot.body_sha256,
        "source_revision": snapshot.source_revision,
        "retrieved_at": snapshot.retrieved_at,
    }


def issue_snapshot_from_dict(payload: Mapping[str, Any]) -> IssueSnapshot:
    return IssueSnapshot(
        repository=payload["repository"],
        issue_number=payload["issue_number"],
        url=payload["url"],
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        body=payload["body"],
        body_sha256=payload["body_sha256"],
        source_revision=payload["source_revision"],
        retrieved_at=payload["retrieved_at"],
    )


def _check_result_to_dict(check: CheckResult) -> dict[str, Any]:
    return {
        "name": check.name,
        "status": check.status.value,
        "message": check.message,
        "evidence": list(check.evidence),
    }


def _check_result_from_dict(payload: Mapping[str, Any]) -> CheckResult:
    return CheckResult(
        name=payload["name"],
        status=Status(payload["status"]),
        message=payload["message"],
        evidence=list(payload.get("evidence", [])),
    )


def _linked_issue_candidate_to_dict(candidate: LinkedIssueCandidate) -> dict[str, Any]:
    return {
        "issue_number": candidate.issue_number,
        "repository": candidate.repository,
        "keyword": candidate.keyword,
        "source": candidate.source,
        "position": candidate.position,
        "raw_target": candidate.raw_target,
        "explicit": candidate.explicit,
    }


def _linked_issue_candidate_from_dict(payload: Mapping[str, Any]) -> LinkedIssueCandidate:
    return LinkedIssueCandidate(**payload)


def _linked_issue_result_to_dict(
    result: LinkedIssueParseResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "status": result.status.value,
        "issue_number": result.issue_number,
        "repository": result.repository,
        "explicit_candidates": [
            _linked_issue_candidate_to_dict(item) for item in result.explicit_candidates
        ],
        "bare_references": [
            _linked_issue_candidate_to_dict(item) for item in result.bare_references
        ],
        "reasons": list(result.reasons),
    }


def _linked_issue_result_from_dict(
    payload: Mapping[str, Any] | None,
) -> LinkedIssueParseResult | None:
    if payload is None:
        return None
    from scripts.agent_os_issue_acceptance.models import LinkedIssueParseStatus

    return LinkedIssueParseResult(
        status=LinkedIssueParseStatus(payload["status"]),
        issue_number=payload.get("issue_number"),
        repository=payload.get("repository"),
        explicit_candidates=[
            _linked_issue_candidate_from_dict(item)
            for item in payload.get("explicit_candidates", [])
        ],
        bare_references=[
            _linked_issue_candidate_from_dict(item)
            for item in payload.get("bare_references", [])
        ],
        reasons=list(payload.get("reasons", [])),
    )


def acceptance_report_to_dict(report: AcceptanceReport) -> dict[str, Any]:
    return {
        "linked_issue": report.linked_issue,
        "overall_status": report.overall_status.value,
        "checks": [_check_result_to_dict(item) for item in report.checks],
        "linked_issue_result": _linked_issue_result_to_dict(report.linked_issue_result),
        "manual_review_items": list(report.manual_review_items),
        "evidence": list(report.evidence),
        "blockers": list(report.blockers),
        "remaining_risks": list(report.remaining_risks),
        "informational_checks": [
            _check_result_to_dict(item) for item in report.informational_checks
        ],
    }


def acceptance_report_from_dict(payload: Mapping[str, Any]) -> AcceptanceReport:
    return AcceptanceReport(
        linked_issue=payload["linked_issue"],
        overall_status=Status(payload["overall_status"]),
        checks=[_check_result_from_dict(item) for item in payload["checks"]],
        linked_issue_result=_linked_issue_result_from_dict(
            payload.get("linked_issue_result")
        ),
        manual_review_items=list(payload.get("manual_review_items", [])),
        evidence=list(payload.get("evidence", [])),
        blockers=list(payload.get("blockers", [])),
        remaining_risks=list(payload.get("remaining_risks", [])),
        informational_checks=tuple(
            _check_result_from_dict(item)
            for item in payload.get("informational_checks", [])
        ),
    )


def readiness_result_to_dict(result: ReadinessResult) -> dict[str, Any]:
    return {
        "outcome": result.outcome.value,
        "report": acceptance_report_to_dict(result.report),
    }


def readiness_result_from_dict(payload: Mapping[str, Any]) -> ReadinessResult:
    return ReadinessResult(
        outcome=ReadinessOutcome(payload["outcome"]),
        report=acceptance_report_from_dict(payload["report"]),
    )


def _issueplan_source_snapshot_to_dict(
    snapshot: IssuePlanSourceSnapshot,
) -> dict[str, Any]:
    return {
        "source_locator": snapshot.source_locator,
        "source_family": snapshot.source_family,
        "source_revision": snapshot.source_revision,
        "retrieval_status": snapshot.retrieval_status,
        "completeness_status": snapshot.completeness_status,
        "metadata_status": snapshot.metadata_status,
        "governed_fields": [list(item) for item in snapshot.governed_fields],
        "omitted_fields": list(snapshot.omitted_fields),
        "provenance_references": list(snapshot.provenance_references),
        "candidate_set_fingerprint": snapshot.candidate_set_fingerprint,
        "scanner_result_fingerprint": snapshot.scanner_result_fingerprint,
        "reason_codes": list(snapshot.reason_codes),
    }


def _issueplan_source_snapshot_from_dict(
    payload: Mapping[str, Any],
) -> IssuePlanSourceSnapshot:
    return IssuePlanSourceSnapshot(
        source_locator=payload["source_locator"],
        source_family=payload["source_family"],
        source_revision=payload["source_revision"],
        retrieval_status=payload["retrieval_status"],
        completeness_status=payload["completeness_status"],
        metadata_status=payload["metadata_status"],
        governed_fields=tuple(
            tuple(item) for item in payload.get("governed_fields", [])
        ),
        omitted_fields=tuple(payload.get("omitted_fields", [])),
        provenance_references=tuple(payload.get("provenance_references", [])),
        candidate_set_fingerprint=payload["candidate_set_fingerprint"],
        scanner_result_fingerprint=payload["scanner_result_fingerprint"],
        reason_codes=tuple(payload.get("reason_codes", [])),
    )


def issueplan_current_state_evidence_to_dict(
    evidence: IssuePlanCurrentStateEvidence,
) -> dict[str, Any]:
    return {
        "schema_version": evidence.schema_version,
        "evidence_id": evidence.evidence_id,
        "observed_at": evidence.observed_at,
        "freshness_boundary": evidence.freshness_boundary,
        "source_snapshot": _issueplan_source_snapshot_to_dict(evidence.source_snapshot),
        "source_snapshot_fingerprint": evidence.source_snapshot_fingerprint,
        "scanner_result_fingerprint": evidence.scanner_result_fingerprint,
        "entity_ids": list(evidence.entity_ids),
        "candidate_revisions": list(evidence.candidate_revisions),
        "repository": evidence.repository,
        "base_branch": evidence.base_branch,
        "evaluated_repository_sha": evidence.evaluated_repository_sha,
        "implementation_contract_fingerprint": (
            evidence.implementation_contract_fingerprint
        ),
        "allowed_files": list(evidence.allowed_files),
        "forbidden_paths": list(evidence.forbidden_paths),
        "required_tests": list(evidence.required_tests),
        "graph_reference": evidence.graph_reference,
        "planning_result_reference": evidence.planning_result_reference,
        "handoff_reference": evidence.handoff_reference,
        "supplied_node_ids": list(evidence.supplied_node_ids),
        "reason_codes": list(evidence.reason_codes),
        "execution_authorized": False,
    }


def issueplan_current_state_evidence_from_dict(
    payload: Mapping[str, Any],
) -> IssuePlanCurrentStateEvidence:
    return IssuePlanCurrentStateEvidence(
        schema_version=payload["schema_version"],
        evidence_id=payload["evidence_id"],
        observed_at=payload["observed_at"],
        freshness_boundary=payload["freshness_boundary"],
        source_snapshot=_issueplan_source_snapshot_from_dict(
            payload["source_snapshot"]
        ),
        source_snapshot_fingerprint=payload["source_snapshot_fingerprint"],
        scanner_result_fingerprint=payload["scanner_result_fingerprint"],
        entity_ids=tuple(payload.get("entity_ids", [])),
        candidate_revisions=tuple(payload.get("candidate_revisions", [])),
        repository=payload.get("repository"),
        base_branch=payload.get("base_branch"),
        evaluated_repository_sha=payload.get("evaluated_repository_sha"),
        implementation_contract_fingerprint=payload.get(
            "implementation_contract_fingerprint"
        ),
        allowed_files=tuple(payload.get("allowed_files", [])),
        forbidden_paths=tuple(payload.get("forbidden_paths", [])),
        required_tests=tuple(payload.get("required_tests", [])),
        graph_reference=payload.get("graph_reference"),
        planning_result_reference=payload.get("planning_result_reference"),
        handoff_reference=payload.get("handoff_reference"),
        supplied_node_ids=tuple(payload.get("supplied_node_ids", [])),
        reason_codes=tuple(payload.get("reason_codes", [])),
    )


def issue_readiness_stage_result_to_dict(
    result: IssueReadinessStageResult,
) -> dict[str, Any]:
    return {
        "schema_version": STAGE_SCHEMA_VERSION,
        "status": result.status.value,
        "snapshot": (
            None if result.snapshot is None else issue_snapshot_to_dict(result.snapshot)
        ),
        "issueplan_current_state_evidence": (
            None
            if result.issueplan_current_state_evidence is None
            else issueplan_current_state_evidence_to_dict(
                result.issueplan_current_state_evidence
            )
        ),
        "readiness_result": (
            None
            if result.readiness_result is None
            else readiness_result_to_dict(result.readiness_result)
        ),
        "reason_codes": list(result.reason_codes),
        "details": list(result.details),
        "execution_authorized": False,
        "side_effects_performed": False,
    }


def issue_readiness_stage_result_from_dict(
    payload: Mapping[str, Any],
) -> IssueReadinessStageResult:
    if payload.get("schema_version") != STAGE_SCHEMA_VERSION:
        raise ValueError("unsupported stage schema_version")
    if payload.get("execution_authorized") is not False:
        raise ValueError("execution_authorized must be false")
    if payload.get("side_effects_performed") is not False:
        raise ValueError("side_effects_performed must be false")
    snapshot = payload.get("snapshot")
    evidence = payload.get("issueplan_current_state_evidence")
    readiness = payload.get("readiness_result")
    return IssueReadinessStageResult(
        status=IssueReadinessStageStatus(payload["status"]),
        snapshot=None if snapshot is None else issue_snapshot_from_dict(snapshot),
        issueplan_current_state_evidence=(
            None
            if evidence is None
            else issueplan_current_state_evidence_from_dict(evidence)
        ),
        readiness_result=(
            None if readiness is None else readiness_result_from_dict(readiness)
        ),
        reason_codes=tuple(payload.get("reason_codes", [])),
        details=tuple(payload.get("details", [])),
    )
