"""Immutable, pure-local approval records for IssuePlanCore proposals."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Protocol

from .issueplan_current_state import IssuePlanCurrentStateEvidence

APPROVAL_RECORD_SCHEMA_VERSION = "1.0"
_WSC3_PROPOSAL_VERSION = "0.1.0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


class ApprovalKind(str, Enum):
    """Non-interchangeable governed approval purposes."""

    IMPLEMENTATION = "implementation"
    SOURCE_MUTATION = "source-mutation"
    REPAIR = "repair"
    PUBLICATION = "publication"


class ApprovalState(str, Enum):
    """Immutable approval revision states."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"


class ApprovalInvalidationEvent(str, Enum):
    """Explicit governed events mapped to canonical invalidation reasons."""

    DIRECT_HUMAN_EDIT = "direct-human-edit"
    MANUAL_MERGE = "manual-merge"
    EXPLICIT_INVALIDATION = "explicit-invalidation"


class _CohortLike(Protocol):
    node_ids: tuple[str, ...]
    classification: str
    reason_codes: tuple[str, ...]


class DraftTaskProposalLike(Protocol):
    """Structural WSC3 proposal boundary that avoids a Scheduler import cycle."""

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
    cohort_summaries: tuple[_CohortLike, ...]
    issueplan_current_state_evidence_id: str
    repository_state_evidence_id: str


_APPLICABILITY_STATUSES = frozenset(
    {"applicable", "stale", "blocked", "invalid", "needs-decision"}
)
_REASON_CODES = frozenset(
    {
        "source.revision-changed",
        "source.freshness-boundary-changed",
        "source.partial",
        "source.inaccessible",
        "source.unsupported",
        "source.unknown-pagination",
        "scanner.multiple-identical",
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
        "projection.incomplete",
        "projection.lookup-failed",
        "version.unsupported",
    }
)
_INVALID_REASONS = frozenset({"identity.quarantined", "version.unsupported"})
_NEEDS_DECISION_REASONS = frozenset(
    {
        "source.partial",
        "source.inaccessible",
        "source.unknown-pagination",
        "scanner.unknown-governed-field",
        "projection.incomplete",
        "projection.lookup-failed",
    }
)
_BLOCKED_REASONS = frozenset(
    {
        "source.unsupported",
        "scanner.multiple-identical",
        "scanner.multiple-conflicting",
        "scanner.malformed-candidate",
    }
)
_TERMINAL_STATES = frozenset(
    {
        ApprovalState.REJECTED,
        ApprovalState.EXPIRED,
        ApprovalState.INVALIDATED,
        ApprovalState.SUPERSEDED,
    }
)
_EVENT_REASONS = {
    ApprovalInvalidationEvent.DIRECT_HUMAN_EDIT: "candidate.changed",
    ApprovalInvalidationEvent.MANUAL_MERGE: "source.revision-changed",
    ApprovalInvalidationEvent.EXPLICIT_INVALIDATION: "approval.invalidated",
}
_STATE_REASONS = {
    ApprovalState.EXPIRED: "approval.expired",
    ApprovalState.INVALIDATED: "approval.invalidated",
    ApprovalState.SUPERSEDED: "approval.superseded",
}


class _ProposalVerificationError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class ApprovalBinding:
    """Canonical content, source, repository, and implementation binding."""

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
        _text(self.proposal_version, "proposal_version")
        if not self.proposal_id.startswith("draft-task-proposal:"):
            raise ValueError("proposal_id must use the WSC3 identity prefix")
        for name in (
            "handoff_digest",
            "graph_digest",
            "planning_result_digest",
            "cohort_fingerprint",
            "source_snapshot_fingerprint",
            "scanner_result_fingerprint",
            "implementation_contract_fingerprint",
        ):
            _digest_text(getattr(self, name), name)
        for name in (
            "repository",
            "base_branch",
            "issueplan_current_state_evidence_id",
            "repository_state_evidence_id",
        ):
            _text(getattr(self, name), name)
        _sha40(self.evaluated_repository_sha, "evaluated_repository_sha")
        _sha40(self.evaluator_commit_sha, "evaluator_commit_sha")
        for name in (
            "supplied_node_ids",
            "allowed_files",
            "forbidden_paths",
            "required_tests",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """One immutable content-verified approval decision revision."""

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
        if self.approval_revision == 1 and self.supersedes_approval_id is not None:
            raise ValueError("first approval revision cannot supersede another record")
        if self.approval_revision > 1:
            _text(self.supersedes_approval_id, "supersedes_approval_id")
        reasons = set(_reasons(self.reason_codes))
        required_reason = _STATE_REASONS.get(self.state)
        if required_reason is not None:
            reasons.add(required_reason)
        object.__setattr__(self, "reason_codes", tuple(sorted(reasons)))
        expected_id = _approval_id_from_fields(
            approval_revision=self.approval_revision,
            approval_kind=self.approval_kind,
            state=self.state,
            binding=self.binding,
            authorizer_id=self.authorizer_id,
            decision_id=self.decision_id,
            decision_at=self.decision_at,
            expires_at=self.expires_at,
            supersedes_approval_id=self.supersedes_approval_id,
            reason_codes=self.reason_codes,
        )
        if self.approval_id != expected_id:
            raise ValueError("approval_id does not match approval revision content")


@dataclass(frozen=True, slots=True)
class ApprovalApplicabilityResult:
    """Deterministic approval applicability evidence with no execution authority."""

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
        _text(self.approval_id, "approval_id")
        _text(self.current_proposal_id, "current_proposal_id")
        object.__setattr__(self, "reason_codes", _reasons(self.reason_codes))
        object.__setattr__(
            self, "changed_bindings", _strings(self.changed_bindings)
        )
        if self.approval_applicable != (self.status == "applicable"):
            raise ValueError("approval_applicable must match status")


def build_approval_candidate(
    proposal: DraftTaskProposalLike,
    issueplan_current_state_evidence: IssuePlanCurrentStateEvidence,
    *,
    approval_kind: ApprovalKind,
    authorizer_id: str,
    decision_id: str,
    decision_at: str,
    expires_at: str | None = None,
) -> ApprovalRecord:
    """Build one deterministic pending candidate from complete canonical evidence."""

    if not isinstance(approval_kind, ApprovalKind):
        raise TypeError("approval_kind must be ApprovalKind")
    _text(authorizer_id, "authorizer_id")
    _text(decision_id, "decision_id")
    _timestamp(decision_at)
    if expires_at is not None:
        _timestamp(expires_at)
    _require_approvable_evidence(issueplan_current_state_evidence)
    binding = _build_binding(
        proposal,
        issueplan_current_state_evidence,
        require_evidence_match=True,
    )
    return _record(
        approval_revision=1,
        approval_kind=approval_kind,
        state=ApprovalState.PENDING,
        binding=binding,
        authorizer_id=authorizer_id,
        decision_id=decision_id,
        decision_at=decision_at,
        expires_at=expires_at,
        supersedes_approval_id=None,
        reason_codes=(),
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
    """Create a new deterministic revision without mutating approval history."""

    if not isinstance(candidate, ApprovalRecord):
        raise TypeError("candidate must be ApprovalRecord")
    if not isinstance(state, ApprovalState):
        raise TypeError("state must be ApprovalState")
    if candidate.state in _TERMINAL_STATES:
        raise ValueError("terminal approval revisions cannot be revised")
    allowed = (
        {
            ApprovalState.APPROVED,
            ApprovalState.REJECTED,
            ApprovalState.EXPIRED,
            ApprovalState.INVALIDATED,
            ApprovalState.SUPERSEDED,
        }
        if candidate.state is ApprovalState.PENDING
        else {
            ApprovalState.EXPIRED,
            ApprovalState.INVALIDATED,
            ApprovalState.SUPERSEDED,
        }
    )
    if state not in allowed:
        raise ValueError("unsupported approval state transition")
    return _record(
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
    current_proposal: DraftTaskProposalLike,
    current_issueplan_evidence: IssuePlanCurrentStateEvidence,
    *,
    evaluated_at: str,
    invalidation_events: tuple[ApprovalInvalidationEvent, ...] = (),
) -> ApprovalApplicabilityResult:
    """Compare a revision with current explicit inputs and perform no I/O."""

    if not isinstance(approval_record, ApprovalRecord):
        raise TypeError("approval_record must be ApprovalRecord")
    evaluated = _parse_timestamp(evaluated_at)
    try:
        current = _build_binding(
            current_proposal,
            current_issueplan_evidence,
            require_evidence_match=False,
        )
    except _ProposalVerificationError as exc:
        return _result(
            approval_record,
            str(getattr(current_proposal, "proposal_id", "unknown")),
            "invalid",
            (exc.reason_code,),
            ("proposal_id",),
        )
    except (AttributeError, TypeError, ValueError):
        return _result(
            approval_record,
            str(getattr(current_proposal, "proposal_id", "unknown")),
            "invalid",
            ("candidate.changed",),
            ("proposal_id",),
        )

    changed = tuple(
        name
        for name in ApprovalBinding.__dataclass_fields__
        if getattr(approval_record.binding, name) != getattr(current, name)
    )
    reasons = set(_evidence_reasons(current_issueplan_evidence))
    reasons.update(_reason_for_change(name) for name in changed)
    reasons.update(_event_reasons(invalidation_events))
    reasons.update(approval_record.reason_codes)

    if (
        approval_record.expires_at is not None
        and evaluated >= _parse_timestamp(approval_record.expires_at)
    ):
        reasons.add("approval.expired")
    status = _applicability_status(approval_record.state, reasons)
    return _result(
        approval_record,
        current.proposal_id,
        status,
        tuple(reasons),
        changed,
    )


def _build_binding(
    proposal: DraftTaskProposalLike,
    evidence: IssuePlanCurrentStateEvidence,
    *,
    require_evidence_match: bool,
) -> ApprovalBinding:
    if not isinstance(evidence, IssuePlanCurrentStateEvidence):
        raise TypeError("issueplan evidence must use the canonical model")
    if evidence.implementation_contract_fingerprint is None:
        raise ValueError("implementation contract fingerprint is required")
    _verify_proposal(proposal)
    if require_evidence_match:
        _verify_evidence_matches_proposal(proposal, evidence)
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
        supplied_node_ids=proposal.supplied_node_ids,
        cohort_fingerprint=_digest(_cohort_payload(proposal.cohort_summaries)),
        issueplan_current_state_evidence_id=evidence.evidence_id,
        repository_state_evidence_id=proposal.repository_state_evidence_id,
        source_snapshot_fingerprint=evidence.source_snapshot_fingerprint,
        scanner_result_fingerprint=evidence.scanner_result_fingerprint,
        implementation_contract_fingerprint=(
            evidence.implementation_contract_fingerprint
        ),
        allowed_files=evidence.allowed_files,
        forbidden_paths=evidence.forbidden_paths,
        required_tests=evidence.required_tests,
    )


def _verify_proposal(proposal: DraftTaskProposalLike) -> None:
    if proposal.proposal_version != _WSC3_PROPOSAL_VERSION:
        raise _ProposalVerificationError(
            "version.unsupported", "unsupported WSC3 proposal version"
        )
    expected = _proposal_id_from_fields(proposal)
    if proposal.proposal_id != expected:
        raise _ProposalVerificationError(
            "candidate.changed", "proposal_id does not match proposal content"
        )


def _verify_evidence_matches_proposal(
    proposal: DraftTaskProposalLike,
    evidence: IssuePlanCurrentStateEvidence,
) -> None:
    matches = (
        proposal.issueplan_current_state_evidence_id == evidence.evidence_id,
        proposal.repository == evidence.repository,
        proposal.base_branch == evidence.base_branch,
        proposal.evaluated_repository_sha == evidence.evaluated_repository_sha,
        proposal.handoff_digest == evidence.handoff_reference,
        proposal.graph_digest == evidence.graph_reference,
        proposal.planning_result_digest == evidence.planning_result_reference,
        _strings(proposal.supplied_node_ids) == evidence.supplied_node_ids,
    )
    if not all(matches):
        raise ValueError("proposal and IssuePlan evidence bindings do not match")


def _require_approvable_evidence(evidence: IssuePlanCurrentStateEvidence) -> None:
    if not isinstance(evidence, IssuePlanCurrentStateEvidence):
        raise TypeError("issueplan evidence must use the canonical model")
    snapshot = evidence.source_snapshot
    if snapshot.retrieval_status != "present":
        raise ValueError("approval candidate requires present source evidence")
    if snapshot.completeness_status != "complete":
        raise ValueError("approval candidate requires complete source evidence")
    if snapshot.metadata_status not in {"present", "duplicate-identical"}:
        raise ValueError("approval candidate requires usable metadata evidence")
    if evidence.reason_codes:
        raise ValueError("approval candidate requires evidence without findings")


def _proposal_id_from_fields(proposal: DraftTaskProposalLike) -> str:
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
        "issueplan_current_state_evidence_id": (
            proposal.issueplan_current_state_evidence_id
        ),
        "repository_state_evidence_id": proposal.repository_state_evidence_id,
    }
    return f"draft-task-proposal:{_digest(payload)}"


def _cohort_payload(cohorts: tuple[_CohortLike, ...]) -> list[dict[str, Any]]:
    values = [
        {
            "node_ids": list(_strings(cohort.node_ids)),
            "classification": cohort.classification,
            "reason_codes": list(_strings(cohort.reason_codes)),
        }
        for cohort in cohorts
    ]
    return sorted(
        values,
        key=lambda item: (
            item["classification"],
            item["node_ids"],
            item["reason_codes"],
        ),
    )


def _record(
    *,
    approval_revision: int,
    approval_kind: ApprovalKind,
    state: ApprovalState,
    binding: ApprovalBinding,
    authorizer_id: str,
    decision_id: str,
    decision_at: str,
    expires_at: str | None,
    supersedes_approval_id: str | None,
    reason_codes: tuple[str, ...],
) -> ApprovalRecord:
    reasons = set(_reasons(reason_codes))
    required_reason = _STATE_REASONS.get(state)
    if required_reason is not None:
        reasons.add(required_reason)
    canonical_reasons = tuple(sorted(reasons))
    approval_id = _approval_id_from_fields(
        approval_revision=approval_revision,
        approval_kind=approval_kind,
        state=state,
        binding=binding,
        authorizer_id=authorizer_id,
        decision_id=decision_id,
        decision_at=decision_at,
        expires_at=expires_at,
        supersedes_approval_id=supersedes_approval_id,
        reason_codes=canonical_reasons,
    )
    return ApprovalRecord(
        approval_id=approval_id,
        approval_revision=approval_revision,
        approval_kind=approval_kind,
        state=state,
        binding=binding,
        authorizer_id=authorizer_id,
        decision_id=decision_id,
        decision_at=decision_at,
        expires_at=expires_at,
        supersedes_approval_id=supersedes_approval_id,
        reason_codes=canonical_reasons,
    )


def _approval_id_from_fields(
    *,
    approval_revision: int,
    approval_kind: ApprovalKind,
    state: ApprovalState,
    binding: ApprovalBinding,
    authorizer_id: str,
    decision_id: str,
    decision_at: str,
    expires_at: str | None,
    supersedes_approval_id: str | None,
    reason_codes: tuple[str, ...],
) -> str:
    payload = {
        "schema_version": APPROVAL_RECORD_SCHEMA_VERSION,
        "approval_revision": approval_revision,
        "approval_kind": approval_kind.value,
        "state": state.value,
        "binding": _binding_payload(binding),
        "authorizer_id": authorizer_id,
        "decision_id": decision_id,
        "decision_at": decision_at,
        "expires_at": expires_at,
        "supersedes_approval_id": supersedes_approval_id,
        "reason_codes": list(_reasons(reason_codes)),
    }
    return f"approval:{_digest(payload)}"


def _binding_payload(binding: ApprovalBinding) -> dict[str, Any]:
    return {
        name: list(value) if isinstance(value, tuple) else value
        for name, value in (
            (name, getattr(binding, name))
            for name in ApprovalBinding.__dataclass_fields__
        )
    }


def _evidence_reasons(evidence: IssuePlanCurrentStateEvidence) -> tuple[str, ...]:
    if not isinstance(evidence, IssuePlanCurrentStateEvidence):
        raise TypeError("issueplan evidence must use the canonical model")
    return _reasons(evidence.reason_codes)


def _event_reasons(
    values: tuple[ApprovalInvalidationEvent, ...],
) -> tuple[str, ...]:
    events = tuple(values)
    if not all(isinstance(value, ApprovalInvalidationEvent) for value in events):
        raise TypeError("invalidation_events must use ApprovalInvalidationEvent")
    return tuple(sorted({_EVENT_REASONS[value] for value in events}))


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
    if name in {
        "repository",
        "base_branch",
        "evaluated_repository_sha",
        "evaluator_commit_sha",
        "issueplan_current_state_evidence_id",
        "repository_state_evidence_id",
        "source_snapshot_fingerprint",
        "scanner_result_fingerprint",
    }:
        return "source.revision-changed"
    if name == "proposal_version":
        return "version.unsupported"
    return "candidate.changed"


def _applicability_status(state: ApprovalState, reasons: set[str]) -> str:
    if reasons & _INVALID_REASONS:
        return "invalid"
    if reasons & _NEEDS_DECISION_REASONS:
        return "needs-decision"
    if state is not ApprovalState.APPROVED or reasons & _BLOCKED_REASONS:
        return "blocked"
    if reasons:
        return "stale"
    return "applicable"


def _result(
    record: ApprovalRecord,
    proposal_id: str,
    status: str,
    reasons: tuple[str, ...],
    changed: tuple[str, ...],
) -> ApprovalApplicabilityResult:
    return ApprovalApplicabilityResult(
        status=status,
        approval_id=record.approval_id,
        approval_revision=record.approval_revision,
        current_proposal_id=proposal_id,
        reason_codes=tuple(sorted(set(reasons))),
        changed_bindings=tuple(sorted(set(changed))),
        approval_applicable=status == "applicable",
    )


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _strings(values: Any) -> tuple[str, ...]:
    items = tuple(values)
    if any(not isinstance(value, str) or not value for value in items):
        raise ValueError("values must be non-empty strings")
    return tuple(sorted(set(items)))


def _reasons(values: Any) -> tuple[str, ...]:
    reasons = _strings(values)
    if not set(reasons) <= _REASON_CODES:
        raise ValueError("reason_codes contain an unowned value")
    return reasons


def _text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _digest_text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{name} must be a SHA-256 digest")


def _sha40(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _SHA40_RE.fullmatch(value):
        raise ValueError(f"{name} must be a 40-character SHA")


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be an explicit UTC timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("timestamp must be a valid UTC timestamp") from exc


def _timestamp(value: Any) -> None:
    _parse_timestamp(value)
