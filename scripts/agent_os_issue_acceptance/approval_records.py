"""Immutable, pure-local approval records for IssuePlanCore proposals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from .issueplan_current_state import IssuePlanCurrentStateEvidence

APPROVAL_RECORD_SCHEMA_VERSION = "1.0"


class ApprovalKind(str, Enum):
    IMPLEMENTATION = "implementation"
    SOURCE_MUTATION = "source-mutation"
    REPAIR = "repair"
    PUBLICATION = "publication"


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"


_APPLICABILITY_STATUSES = frozenset(
    {"applicable", "stale", "blocked", "invalid", "needs-decision"}
)
_REASON_CODES = frozenset(
    {
        "source.revision-changed",
        "source.partial",
        "source.inaccessible",
        "source.unknown-pagination",
        "scanner.multiple-conflicting",
        "scanner.malformed-candidate",
        "scanner.unknown-governed-field",
        "candidate.changed",
        "contract.scope-changed",
        "contract.allowlist-changed",
        "contract.required-tests-changed",
        "handoff.changed",
        "graph.changed",
        "approval.expired",
        "approval.invalidated",
        "approval.superseded",
        "identity.quarantined",
        "version.unsupported",
    }
)


@dataclass(frozen=True, slots=True)
class ApprovalBinding:
    proposal_version: str
    proposal_id: str
    handoff_digest: str
    graph_digest: str
    planning_result_digest: str
    repository: str
    base_branch: str
    evaluated_repository_sha: str
    evaluator_commit_sha: str
    supplied_node_ids: tuple[str, ...]
    cohort_fingerprint: str
    issueplan_current_state_evidence_id: str
    repository_state_evidence_id: str
    source_snapshot_fingerprint: str
    scanner_result_fingerprint: str
    implementation_contract_fingerprint: str
    allowed_files: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_tests: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "proposal_version",
            "proposal_id",
            "handoff_digest",
            "graph_digest",
            "planning_result_digest",
            "repository",
            "base_branch",
            "evaluated_repository_sha",
            "evaluator_commit_sha",
            "cohort_fingerprint",
            "issueplan_current_state_evidence_id",
            "repository_state_evidence_id",
            "source_snapshot_fingerprint",
            "scanner_result_fingerprint",
            "implementation_contract_fingerprint",
        ):
            _text(getattr(self, name), name)
        for name in (
            "supplied_node_ids",
            "allowed_files",
            "forbidden_paths",
            "required_tests",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    approval_id: str
    approval_revision: int
    approval_kind: ApprovalKind
    state: ApprovalState
    binding: ApprovalBinding
    authorizer_id: str
    decision_id: str
    decision_at: str
    expires_at: str | None = None
    supersedes_approval_id: str | None = None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _text(self.approval_id, "approval_id")
        if self.approval_revision < 1:
            raise ValueError("approval_revision must be positive")
        if not isinstance(self.approval_kind, ApprovalKind):
            raise TypeError("approval_kind must be ApprovalKind")
        if not isinstance(self.state, ApprovalState):
            raise TypeError("state must be ApprovalState")
        if not isinstance(self.binding, ApprovalBinding):
            raise TypeError("binding must be ApprovalBinding")
        _text(self.authorizer_id, "authorizer_id")
        _text(self.decision_id, "decision_id")
        _timestamp(self.decision_at)
        if self.expires_at is not None:
            _timestamp(self.expires_at)
        object.__setattr__(self, "reason_codes", _reasons(self.reason_codes))


@dataclass(frozen=True, slots=True)
class ApprovalApplicabilityResult:
    status: str
    approval_id: str
    approval_revision: int
    current_proposal_id: str
    reason_codes: tuple[str, ...]
    changed_bindings: tuple[str, ...]
    approval_applicable: bool
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.status not in _APPLICABILITY_STATUSES:
            raise ValueError("unsupported applicability status")
        object.__setattr__(self, "reason_codes", _reasons(self.reason_codes))
        object.__setattr__(self, "changed_bindings", _strings(self.changed_bindings))
        if self.approval_applicable != (self.status == "applicable"):
            raise ValueError("approval_applicable must match status")


def build_approval_candidate(
    proposal: Any,
    issueplan_current_state_evidence: IssuePlanCurrentStateEvidence,
    *,
    approval_kind: ApprovalKind,
    authorizer_id: str,
    decision_id: str,
    decision_at: str,
    expires_at: str | None = None,
) -> ApprovalRecord:
    """Build one deterministic pending approval candidate from verified inputs."""

    binding = _binding(proposal, issueplan_current_state_evidence)
    payload = {
        "schema_version": APPROVAL_RECORD_SCHEMA_VERSION,
        "approval_kind": approval_kind.value,
        "binding": _binding_payload(binding),
        "authorizer_id": authorizer_id,
        "decision_id": decision_id,
        "decision_at": decision_at,
        "expires_at": expires_at,
    }
    return ApprovalRecord(
        approval_id=f"approval:{_digest(payload)}",
        approval_revision=1,
        approval_kind=approval_kind,
        state=ApprovalState.PENDING,
        binding=binding,
        authorizer_id=authorizer_id,
        decision_id=decision_id,
        decision_at=decision_at,
        expires_at=expires_at,
    )


def record_approval_decision(
    candidate: ApprovalRecord,
    *,
    state: ApprovalState,
    decision_id: str,
    authorizer_id: str,
    decision_at: str,
    reason_codes: tuple[str, ...] = (),
) -> ApprovalRecord:
    """Create a new immutable revision; historical records remain unchanged."""

    if not isinstance(candidate, ApprovalRecord):
        raise TypeError("candidate must be ApprovalRecord")
    return ApprovalRecord(
        approval_id=candidate.approval_id,
        approval_revision=candidate.approval_revision + 1,
        approval_kind=candidate.approval_kind,
        state=state,
        binding=candidate.binding,
        authorizer_id=authorizer_id,
        decision_id=decision_id,
        decision_at=decision_at,
        expires_at=candidate.expires_at,
        supersedes_approval_id=candidate.approval_id,
        reason_codes=reason_codes,
    )


def evaluate_approval_applicability(
    approval_record: ApprovalRecord,
    current_proposal: Any,
    current_issueplan_evidence: IssuePlanCurrentStateEvidence,
    *,
    evaluated_at: str,
    invalidation_events: tuple[str, ...] = (),
) -> ApprovalApplicabilityResult:
    """Evaluate an approval against current immutable evidence, without I/O."""

    _timestamp(evaluated_at)
    try:
        current = _binding(current_proposal, current_issueplan_evidence)
    except (TypeError, ValueError):
        return _result(approval_record, str(getattr(current_proposal, "proposal_id", "unknown")), "invalid", ("candidate.changed",), ("proposal_id",))

    changed = tuple(
        name
        for name in ApprovalBinding.__dataclass_fields__
        if getattr(approval_record.binding, name) != getattr(current, name)
    )
    reasons = set(_reasons(invalidation_events))
    reasons.update(_reason_for_change(name) for name in changed)

    if approval_record.state == ApprovalState.SUPERSEDED:
        reasons.add("approval.superseded")
    elif approval_record.state == ApprovalState.INVALIDATED:
        reasons.add("approval.invalidated")
    elif approval_record.expires_at is not None and evaluated_at >= approval_record.expires_at:
        reasons.add("approval.expired")

    if approval_record.state != ApprovalState.APPROVED:
        status = "blocked"
    elif "version.unsupported" in reasons or "identity.quarantined" in reasons:
        status = "invalid"
    elif reasons & {"source.partial", "source.inaccessible", "source.unknown-pagination", "scanner.unknown-governed-field"}:
        status = "needs-decision"
    elif reasons:
        status = "stale"
    else:
        status = "applicable"
    return _result(
        approval_record,
        current.proposal_id,
        status,
        tuple(reasons),
        changed,
    )


def _binding(proposal: Any, evidence: IssuePlanCurrentStateEvidence) -> ApprovalBinding:
    if not isinstance(evidence, IssuePlanCurrentStateEvidence):
        raise TypeError("issueplan evidence must use the canonical model")
    if evidence.implementation_contract_fingerprint is None:
        raise ValueError("implementation contract fingerprint is required")
    expected_id = _proposal_id(proposal)
    if proposal.proposal_id != expected_id:
        raise ValueError("proposal_id does not match proposal content")
    return ApprovalBinding(
        proposal_version=proposal.proposal_version,
        proposal_id=proposal.proposal_id,
        handoff_digest=proposal.handoff_digest,
        graph_digest=proposal.graph_digest,
        planning_result_digest=proposal.planning_result_digest,
        repository=proposal.repository,
        base_branch=proposal.base_branch,
        evaluated_repository_sha=proposal.evaluated_repository_sha,
        evaluator_commit_sha=proposal.evaluator_commit_sha,
        supplied_node_ids=tuple(proposal.supplied_node_ids),
        cohort_fingerprint=_digest(_cohort_payload(proposal.cohort_summaries)),
        issueplan_current_state_evidence_id=evidence.evidence_id,
        repository_state_evidence_id=proposal.repository_state_evidence_id,
        source_snapshot_fingerprint=evidence.source_snapshot_fingerprint,
        scanner_result_fingerprint=evidence.scanner_result_fingerprint,
        implementation_contract_fingerprint=evidence.implementation_contract_fingerprint,
        allowed_files=evidence.allowed_files,
        forbidden_paths=evidence.forbidden_paths,
        required_tests=evidence.required_tests,
    )


def _proposal_id(proposal: Any) -> str:
    payload = {
        "proposal_version": proposal.proposal_version,
        "handoff_digest": proposal.handoff_digest,
        "graph_digest": proposal.graph_digest,
        "planning_result_digest": proposal.planning_result_digest,
        "repository": proposal.repository,
        "base_branch": proposal.base_branch,
        "evaluated_repository_sha": proposal.evaluated_repository_sha,
        "evaluator_commit_sha": proposal.evaluator_commit_sha,
        "supplied_node_ids": list(_strings(proposal.supplied_node_ids)),
        "cohort_summaries": _cohort_payload(proposal.cohort_summaries),
        "issueplan_current_state_evidence_id": proposal.issueplan_current_state_evidence_id,
        "repository_state_evidence_id": proposal.repository_state_evidence_id,
    }
    return f"draft-task-proposal:{_digest(payload)}"


def _cohort_payload(cohorts: Any) -> list[dict[str, Any]]:
    values = [
        {
            "node_ids": list(_strings(cohort.node_ids)),
            "classification": cohort.classification,
            "reason_codes": list(_strings(cohort.reason_codes)),
        }
        for cohort in cohorts
    ]
    return sorted(values, key=lambda item: (item["classification"], item["node_ids"], item["reason_codes"]))


def _binding_payload(binding: ApprovalBinding) -> dict[str, Any]:
    return {name: getattr(binding, name) for name in ApprovalBinding.__dataclass_fields__}


def _reason_for_change(name: str) -> str:
    if name == "handoff_digest":
        return "handoff.changed"
    if name in {"graph_digest", "cohort_fingerprint", "supplied_node_ids"}:
        return "graph.changed"
    if name == "allowed_files":
        return "contract.allowlist-changed"
    if name == "required_tests":
        return "contract.required-tests-changed"
    if name in {"forbidden_paths", "implementation_contract_fingerprint"}:
        return "contract.scope-changed"
    if name in {"source_snapshot_fingerprint", "scanner_result_fingerprint", "issueplan_current_state_evidence_id"}:
        return "source.revision-changed"
    if name == "proposal_version":
        return "version.unsupported"
    return "candidate.changed"


def _result(record: ApprovalRecord, proposal_id: str, status: str, reasons: tuple[str, ...], changed: tuple[str, ...]) -> ApprovalApplicabilityResult:
    return ApprovalApplicabilityResult(
        status=status,
        approval_id=record.approval_id,
        approval_revision=record.approval_revision,
        current_proposal_id=proposal_id,
        reason_codes=reasons,
        changed_bindings=changed,
        approval_applicable=status == "applicable",
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _strings(values: Any) -> tuple[str, ...]:
    result = tuple(sorted(set(values)))
    if any(not isinstance(value, str) or not value for value in result):
        raise ValueError("values must be non-empty strings")
    return result


def _reasons(values: Any) -> tuple[str, ...]:
    reasons = _strings(values)
    if not set(reasons) <= _REASON_CODES:
        raise ValueError("reason_codes contain an unowned value")
    return reasons


def _text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _timestamp(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("timestamp must be an explicit UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("timestamp must be a valid UTC timestamp") from exc
