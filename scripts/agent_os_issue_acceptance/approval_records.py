from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from scripts.agent_os_execution_capabilities import (
    RepositoryStateEvidence,
    RepositoryStateValidationResult,
    validate_repository_state_evidence,
)

from .issueplan_current_state import (
    IssuePlanCurrentStateEvidence,
    IssuePlanCurrentStateOutcome,
    compare_issueplan_current_state,
)
from .planning_binding import (
    PlanningBindingEvidence,
    compute_planning_binding_fingerprint,
)
from .scheduler_handoff import HandoffCohort

APPROVAL_RECORD_SCHEMA_VERSION = "1.0"
APPROVAL_RECORD_SEMANTIC_SCHEMA_VERSION = "1.1"
APPROVAL_RECORD_SUPPORTED_SCHEMA_VERSIONS = frozenset(
    {APPROVAL_RECORD_SCHEMA_VERSION, APPROVAL_RECORD_SEMANTIC_SCHEMA_VERSION}
)
SEMANTIC_APPROVAL_SUBJECT_SCHEMA_VERSION = "1.0"

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_APPROVAL_ID_RE = re.compile(r"^approval:[0-9a-f]{64}$")
_REVISION_ID_RE = re.compile(r"^approval-revision:[0-9a-f]{64}$")
_PROPOSAL_ID_RE = re.compile(r"^draft-task-proposal:[0-9a-f]{64}$")
_ISSUEPLAN_ID_RE = re.compile(r"^issueplan-current-state:[0-9a-f]{64}$")
_SEMANTIC_SUBJECT_ID_RE = re.compile(r"^semantic-approval-subject:[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

APPROVAL_INVALIDATION_REASON_CODES = frozenset(
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
        "capability.stale",
        "validation.stale",
        "identity.quarantined",
        "projection.incomplete",
        "projection.lookup-failed",
        "version.unsupported",
    }
)
_NEEDS_DECISION = frozenset(
    {
        "source.partial",
        "source.inaccessible",
        "source.unknown-pagination",
        "scanner.unknown-governed-field",
        "projection.incomplete",
        "projection.lookup-failed",
    }
)
_BLOCKED = frozenset(
    {
        "source.unsupported",
        "scanner.multiple-identical",
        "scanner.multiple-conflicting",
        "scanner.malformed-candidate",
        "identity.quarantined",
    }
)
_INVALID = frozenset({"version.unsupported"})
_LIFECYCLE_REASON = {
    "expired": "approval.expired",
    "invalidated": "approval.invalidated",
    "superseded": "approval.superseded",
}


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
    cohort_summaries: tuple[HandoffCohort, ...]
    issueplan_current_state_evidence_id: str
    repository_state_evidence_id: str
    repository_evidence_type: str
    tested_repository_sha: str
    source_snapshot_fingerprint: str
    scanner_result_fingerprint: str
    implementation_contract_fingerprint: str
    allowed_files: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_tests: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "proposal_version",
            "repository",
            "base_branch",
            "repository_evidence_type",
        ):
            _text(getattr(self, name), name)
        if not _PROPOSAL_ID_RE.fullmatch(self.proposal_id):
            raise ValueError("proposal_id is malformed")
        if not _ISSUEPLAN_ID_RE.fullmatch(
            self.issueplan_current_state_evidence_id
        ):
            raise ValueError("issueplan_current_state_evidence_id is malformed")
        _sha256(self.repository_state_evidence_id, "repository_state_evidence_id")
        for name in (
            "handoff_digest",
            "graph_digest",
            "planning_result_digest",
            "source_snapshot_fingerprint",
            "scanner_result_fingerprint",
            "implementation_contract_fingerprint",
        ):
            _sha256(getattr(self, name), name)
        for name in (
            "evaluated_repository_sha",
            "evaluator_commit_sha",
            "tested_repository_sha",
        ):
            _sha40(getattr(self, name), name)
        nodes = _strings(
            self.supplied_node_ids, "supplied_node_ids", allow_empty=False
        )
        cohorts = _cohorts(self.cohort_summaries)
        covered = tuple(
            sorted(node for cohort in cohorts for node in cohort.node_ids)
        )
        if covered != nodes:
            raise ValueError("cohort_summaries must cover supplied_node_ids exactly")
        object.__setattr__(self, "supplied_node_ids", nodes)
        object.__setattr__(self, "cohort_summaries", cohorts)
        object.__setattr__(
            self,
            "allowed_files",
            _strings(self.allowed_files, "allowed_files", allow_empty=True),
        )
        object.__setattr__(
            self,
            "forbidden_paths",
            _strings(self.forbidden_paths, "forbidden_paths", allow_empty=True),
        )
        object.__setattr__(
            self,
            "required_tests",
            _strings(self.required_tests, "required_tests", allow_empty=True),
        )


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    schema_version: str
    approval_id: str
    approval_revision: str
    revision_number: int
    previous_revision: str | None
    approval_kind: ApprovalKind
    state: ApprovalState
    binding: ApprovalBinding
    authorizer_id: str
    decision_id: str
    decision_at: str
    expires_at: str | None
    supersedes_approval_id: str | None
    reason_codes: tuple[str, ...]
    details: tuple[str, ...] = ()
    semantic_subject_id: str | None = None
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version not in APPROVAL_RECORD_SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError("unsupported approval schema version")
        if self.schema_version == APPROVAL_RECORD_SCHEMA_VERSION:
            if self.semantic_subject_id is not None:
                raise ValueError(
                    "schema 1.0 approval records cannot carry a semantic_subject_id"
                )
        elif not isinstance(
            self.semantic_subject_id, str
        ) or not _SEMANTIC_SUBJECT_ID_RE.fullmatch(self.semantic_subject_id):
            raise ValueError(
                "semantic-version approval records require a valid semantic_subject_id"
            )
        if not isinstance(self.approval_kind, ApprovalKind) or not isinstance(
            self.state, ApprovalState
        ):
            raise TypeError("approval kind and state must use canonical enums")
        if not isinstance(self.binding, ApprovalBinding):
            raise TypeError("binding must be ApprovalBinding")
        _text(self.authorizer_id, "authorizer_id")
        _text(self.decision_id, "decision_id")
        decision_time = _timestamp(self.decision_at, "decision_at")
        expiry_time = _optional_timestamp(self.expires_at, "expires_at")
        if (
            not isinstance(self.revision_number, int)
            or isinstance(self.revision_number, bool)
            or self.revision_number < 1
        ):
            raise ValueError("revision_number must be a positive integer")
        if self.revision_number == 1:
            if self.previous_revision is not None or self.state != ApprovalState.PENDING:
                raise ValueError("first revision must be pending with no predecessor")
        elif not isinstance(self.previous_revision, str) or not _REVISION_ID_RE.fullmatch(
            self.previous_revision
        ):
            raise ValueError("later revisions require previous_revision")
        elif self.state == ApprovalState.PENDING:
            raise ValueError("later revisions cannot return to pending")
        if self.supersedes_approval_id is not None and not _APPROVAL_ID_RE.fullmatch(
            self.supersedes_approval_id
        ):
            raise ValueError("supersedes_approval_id is malformed")
        if expiry_time is not None:
            if self.state == ApprovalState.EXPIRED:
                if decision_time < expiry_time:
                    raise ValueError(
                        "expired revisions require decision_at >= expires_at"
                    )
            elif decision_time >= expiry_time:
                raise ValueError("non-expiry decisions must occur before expires_at")
        elif self.state == ApprovalState.EXPIRED:
            raise ValueError("expired revisions require expires_at")
        reasons = _reason_codes(self.reason_codes)
        required = _LIFECYCLE_REASON.get(self.state.value)
        lifecycle_reasons = set(reasons) & set(_LIFECYCLE_REASON.values())
        if required is None and lifecycle_reasons:
            raise ValueError("lifecycle reason does not match approval state")
        if required is not None and lifecycle_reasons != {required}:
            raise ValueError(
                f"{self.state.value} revisions require only {required}"
            )
        if self.state == ApprovalState.PENDING and reasons:
            raise ValueError("pending candidates cannot carry invalidation reasons")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(
            self, "details", tuple(str(item) for item in self.details)
        )
        expected_id = _approval_id(
            self.approval_kind,
            self.binding,
            self.expires_at,
            self.supersedes_approval_id,
            schema_version=self.schema_version,
            semantic_subject_id=self.semantic_subject_id,
        )
        if self.approval_id and self.approval_id != expected_id:
            raise ValueError("approval_id does not match approval candidate content")
        object.__setattr__(self, "approval_id", expected_id)
        expected_revision = _approval_revision(self)
        if self.approval_revision and self.approval_revision != expected_revision:
            raise ValueError("approval_revision does not match record content")
        object.__setattr__(self, "approval_revision", expected_revision)


@dataclass(frozen=True, slots=True)
class ApprovalApplicabilityResult:
    status: str
    approval_id: str | None
    approval_revision: str | None
    current_proposal_id: str | None
    reason_codes: tuple[str, ...]
    changed_bindings: tuple[str, ...]
    approval_applicable: bool
    details: tuple[str, ...] = ()
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.status not in {
            "applicable",
            "stale",
            "blocked",
            "invalid",
            "needs-decision",
        }:
            raise ValueError("unsupported approval applicability status")
        if self.approval_applicable != (self.status == "applicable"):
            raise ValueError("approval_applicable must match applicable status")
        object.__setattr__(
            self, "reason_codes", _reason_codes(self.reason_codes)
        )
        object.__setattr__(
            self,
            "changed_bindings",
            tuple(sorted(set(str(item) for item in self.changed_bindings))),
        )
        object.__setattr__(
            self, "details", tuple(str(item) for item in self.details)
        )


def build_approval_candidate(
    proposal: object,
    issueplan_current_state_evidence: IssuePlanCurrentStateEvidence,
    repository_state_evidence: RepositoryStateEvidence | Mapping[str, Any],
    *,
    approval_kind: ApprovalKind | str,
    authorizer_id: str,
    decision_id: str,
    decision_at: str,
    expires_at: str | None = None,
    supersedes: ApprovalRecord | None = None,
    planning_binding: PlanningBindingEvidence | None = None,
    schema_version: str = APPROVAL_RECORD_SCHEMA_VERSION,
) -> ApprovalRecord:
    if schema_version not in APPROVAL_RECORD_SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError("unsupported approval schema version")
    binding, status, reasons, details = _current_binding(
        proposal,
        issueplan_current_state_evidence,
        repository_state_evidence,
        planning_binding,
    )
    if binding is None or status != "applicable":
        raise ValueError(
            "approval candidate requires current validated inputs: "
            + ",".join((*reasons, *details))
        )
    prior_id = None
    if supersedes is not None:
        prior = _verified_record(supersedes)
        if prior.state not in {
            ApprovalState.REJECTED,
            ApprovalState.EXPIRED,
            ApprovalState.INVALIDATED,
            ApprovalState.SUPERSEDED,
        }:
            raise ValueError(
                "replacement candidates require a terminal prior approval"
            )
        if _timestamp(decision_at, "decision_at") < _timestamp(
            prior.decision_at, "prior decision_at"
        ):
            raise ValueError("replacement candidate cannot predate prior approval")
        prior_id = prior.approval_id
    kind = ApprovalKind(approval_kind)
    semantic_subject_id = None
    if schema_version == APPROVAL_RECORD_SEMANTIC_SCHEMA_VERSION:
        semantic_subject_id = compute_semantic_approval_subject(
            binding,
            repository_state_evidence,
            approval_kind=kind,
            expires_at=expires_at,
            supersedes_approval_id=prior_id,
            planning_binding=planning_binding,
        )
    return ApprovalRecord(
        schema_version=schema_version,
        approval_id="",
        approval_revision="",
        revision_number=1,
        previous_revision=None,
        approval_kind=kind,
        state=ApprovalState.PENDING,
        binding=binding,
        authorizer_id=authorizer_id,
        decision_id=decision_id,
        decision_at=decision_at,
        expires_at=expires_at,
        supersedes_approval_id=prior_id,
        reason_codes=(),
        semantic_subject_id=semantic_subject_id,
    )


def record_approval_decision(
    current: ApprovalRecord,
    *,
    state: ApprovalState | str,
    decision_id: str,
    authorizer_id: str,
    decision_at: str,
    reason_codes: Iterable[str] = (),
    details: Iterable[str] = (),
) -> ApprovalRecord:
    current = _verified_record(current)
    target = ApprovalState(state)
    allowed = {
        ApprovalState.PENDING: {
            ApprovalState.APPROVED,
            ApprovalState.REJECTED,
            ApprovalState.EXPIRED,
            ApprovalState.INVALIDATED,
            ApprovalState.SUPERSEDED,
        },
        ApprovalState.APPROVED: {
            ApprovalState.EXPIRED,
            ApprovalState.INVALIDATED,
            ApprovalState.SUPERSEDED,
        },
    }
    if target not in allowed.get(current.state, set()):
        raise ValueError(
            f"invalid approval transition: {current.state.value} -> {target.value}"
        )
    decision_time = _timestamp(decision_at, "decision_at")
    if decision_time < _timestamp(current.decision_at, "current decision_at"):
        raise ValueError("decision revisions cannot move backward in time")
    expiry_time = _optional_timestamp(current.expires_at, "expires_at")
    if target == ApprovalState.EXPIRED:
        if expiry_time is None or decision_time < expiry_time:
            raise ValueError("expired revision requires decision_at >= expires_at")
    elif expiry_time is not None and decision_time >= expiry_time:
        raise ValueError("non-expiry decision must occur before expires_at")
    reasons = set(_reason_codes(reason_codes))
    lifecycle = _LIFECYCLE_REASON.get(target.value)
    if lifecycle is not None:
        reasons.add(lifecycle)
    return ApprovalRecord(
        schema_version=current.schema_version,
        approval_id=current.approval_id,
        approval_revision="",
        revision_number=current.revision_number + 1,
        previous_revision=current.approval_revision,
        approval_kind=current.approval_kind,
        state=target,
        binding=current.binding,
        authorizer_id=authorizer_id,
        decision_id=decision_id,
        decision_at=decision_at,
        expires_at=current.expires_at,
        supersedes_approval_id=current.supersedes_approval_id,
        reason_codes=tuple(sorted(reasons)),
        details=tuple(str(item) for item in details),
        semantic_subject_id=current.semantic_subject_id,
    )


def evaluate_approval_applicability(
    approval_record: ApprovalRecord | None,
    current_proposal: object,
    current_issueplan_evidence: IssuePlanCurrentStateEvidence,
    current_repository_state_evidence: RepositoryStateEvidence
    | Mapping[str, Any],
    *,
    evaluated_at: str,
    invalidation_events: Iterable[str] = (),
    planning_binding: PlanningBindingEvidence | None = None,
) -> ApprovalApplicabilityResult:
    evaluation_time = _timestamp(evaluated_at, "evaluated_at")
    if approval_record is None:
        return _result(
            "blocked",
            None,
            None,
            _proposal_id_or_none(current_proposal),
            (),
            (),
            ("approval-record:absent",),
        )
    try:
        approval = _verified_record(approval_record)
    except (TypeError, ValueError) as exc:
        reason = (
            "version.unsupported"
            if getattr(approval_record, "schema_version", None)
            not in APPROVAL_RECORD_SUPPORTED_SCHEMA_VERSIONS
            else "projection.incomplete"
        )
        return _result(
            "invalid",
            getattr(approval_record, "approval_id", None),
            getattr(approval_record, "approval_revision", None),
            _proposal_id_or_none(current_proposal),
            (reason,),
            (),
            (f"approval-record:{exc}",),
        )
    binding, current_status, current_reasons, current_details = _current_binding(
        current_proposal,
        current_issueplan_evidence,
        current_repository_state_evidence,
        planning_binding,
    )
    if binding is None:
        return _result(
            current_status,
            approval.approval_id,
            approval.approval_revision,
            _proposal_id_or_none(current_proposal),
            current_reasons,
            (),
            current_details,
        )
    reasons = set(approval.reason_codes) | set(
        _reason_codes(invalidation_events)
    )
    changed = _changed_bindings(approval.binding, binding)
    details = list(current_details)
    if (
        changed
        and approval.schema_version == APPROVAL_RECORD_SEMANTIC_SCHEMA_VERSION
        and approval.semantic_subject_id is not None
    ):
        try:
            current_subject = compute_semantic_approval_subject(
                binding,
                current_repository_state_evidence,
                approval_kind=approval.approval_kind,
                expires_at=approval.expires_at,
                supersedes_approval_id=approval.supersedes_approval_id,
                planning_binding=planning_binding,
            )
        except (TypeError, ValueError) as exc:
            current_subject = None
            details.append(f"semantic-carry-forward:unavailable:{exc}")
        if current_subject is not None and current_subject == approval.semantic_subject_id:
            changed = ()
            details.append("semantic-carry-forward:applied")
        elif current_subject is not None:
            details.append("semantic-carry-forward:subject-mismatch")
    if changed:
        reasons.update(_binding_reasons(changed))
    if approval.state in {ApprovalState.PENDING, ApprovalState.REJECTED}:
        return _result(
            "blocked",
            approval.approval_id,
            approval.approval_revision,
            binding.proposal_id,
            reasons,
            changed,
            (*details, f"approval-state:{approval.state.value}"),
        )
    lifecycle = _LIFECYCLE_REASON.get(approval.state.value)
    if lifecycle is not None:
        reasons.add(lifecycle)
    expiry_time = _optional_timestamp(approval.expires_at, "expires_at")
    if expiry_time is not None and evaluation_time >= expiry_time:
        reasons.add("approval.expired")
    reasons.update(current_reasons)
    status = _status_for_reasons(reasons)
    if status == "applicable" and (
        changed or approval.state != ApprovalState.APPROVED
    ):
        status = "stale" if changed else "blocked"
    return _result(
        status,
        approval.approval_id,
        approval.approval_revision,
        binding.proposal_id,
        reasons,
        changed,
        details,
    )


def _current_binding(
    proposal: object,
    issueplan: IssuePlanCurrentStateEvidence,
    repository_state: RepositoryStateEvidence | Mapping[str, Any],
    planning_binding: PlanningBindingEvidence | None = None,
) -> tuple[ApprovalBinding | None, str, tuple[str, ...], tuple[str, ...]]:
    try:
        proposal = _verified_proposal(proposal)
    except (TypeError, ValueError) as exc:
        return None, "invalid", ("candidate.changed",), (f"proposal:{exc}",)
    if not isinstance(issueplan, IssuePlanCurrentStateEvidence):
        return None, "invalid", ("projection.incomplete",), ("issueplan:type",)
    comparison = compare_issueplan_current_state(issueplan, issueplan)
    if comparison.outcome != IssuePlanCurrentStateOutcome.CURRENT:
        return (
            None,
            _issueplan_status(comparison.outcome),
            comparison.reason_codes,
            comparison.details,
        )
    repository = validate_repository_state_evidence(repository_state)
    if repository.outcome != "valid":
        return (
            None,
            repository.outcome,
            (),
            tuple(f"repository:{code}" for code in repository.reason_codes),
        )
    mismatch_reasons: set[str] = set()
    mismatch_details: list[str] = []

    def mismatch(condition: bool, reason: str, detail: str) -> None:
        if condition:
            mismatch_reasons.add(reason)
            mismatch_details.append(detail)

    mismatch(
        proposal.issueplan_current_state_evidence_id != issueplan.evidence_id,
        "candidate.changed",
        "issueplan-evidence-id:mismatch",
    )
    mismatch(
        proposal.repository_state_evidence_id != repository.evidence_id,
        "candidate.changed",
        "repository-evidence-id:mismatch",
    )
    mismatch(
        issueplan.repository is None
        or proposal.repository.casefold() != issueplan.repository.casefold(),
        "source.revision-changed",
        "repository:mismatch",
    )
    mismatch(
        issueplan.base_branch != proposal.base_branch,
        "source.revision-changed",
        "base-branch:mismatch",
    )
    mismatch(
        issueplan.evaluated_repository_sha != proposal.evaluated_repository_sha,
        "source.revision-changed",
        "source-head:mismatch",
    )
    if planning_binding is None:
        mismatch(
            issueplan.handoff_reference != proposal.handoff_digest,
            "handoff.changed",
            "handoff:mismatch",
        )
        mismatch(
            issueplan.graph_reference != proposal.graph_digest,
            "graph.changed",
            "graph:mismatch",
        )
        mismatch(
            issueplan.planning_result_reference != proposal.planning_result_digest,
            "graph.changed",
            "planning-result:mismatch",
        )
        mismatch(
            tuple(issueplan.supplied_node_ids) != tuple(proposal.supplied_node_ids),
            "candidate.changed",
            "supplied-node-ids:mismatch",
        )
    else:
        if not isinstance(planning_binding, PlanningBindingEvidence):
            return (
                None,
                "invalid",
                ("projection.incomplete",),
                ("planning-binding:type",),
            )
        expected_binding_id = "planning-binding:" + (
            compute_planning_binding_fingerprint(planning_binding)
        )
        if planning_binding.binding_id != expected_binding_id:
            return (
                None,
                "invalid",
                ("candidate.changed",),
                ("planning-binding:identity-mismatch",),
            )
        mismatch(
            planning_binding.issueplan_current_state_evidence_id
            != issueplan.evidence_id,
            "candidate.changed",
            "planning-binding-issueplan:mismatch",
        )
        mismatch(
            planning_binding.implementation_contract_fingerprint
            != issueplan.implementation_contract_fingerprint,
            "candidate.changed",
            "planning-binding-contract:mismatch",
        )
        mismatch(
            planning_binding.repository.casefold() != proposal.repository.casefold(),
            "source.revision-changed",
            "planning-binding-repository:mismatch",
        )
        mismatch(
            planning_binding.base_branch != proposal.base_branch,
            "source.revision-changed",
            "planning-binding-base-branch:mismatch",
        )
        mismatch(
            planning_binding.evaluated_repository_sha
            != proposal.evaluated_repository_sha,
            "source.revision-changed",
            "planning-binding-source-head:mismatch",
        )
        mismatch(
            planning_binding.handoff_digest != proposal.handoff_digest,
            "handoff.changed",
            "handoff:mismatch",
        )
        mismatch(
            planning_binding.graph_digest != proposal.graph_digest,
            "graph.changed",
            "graph:mismatch",
        )
        mismatch(
            planning_binding.planning_result_digest
            != proposal.planning_result_digest,
            "graph.changed",
            "planning-result:mismatch",
        )
        mismatch(
            tuple(planning_binding.supplied_node_ids)
            != tuple(proposal.supplied_node_ids),
            "candidate.changed",
            "supplied-node-ids:mismatch",
        )
    if issueplan.implementation_contract_fingerprint is None:
        return (
            None,
            "needs-decision",
            ("projection.incomplete",),
            ("implementation-contract:missing",),
        )
    if repository.repository_identity is None:
        return (
            None,
            "invalid",
            ("projection.incomplete",),
            ("repository-identity:missing",),
        )
    canonical_repository = (
        f"{repository.repository_identity.owner}/"
        f"{repository.repository_identity.repository}"
    )
    mismatch(
        proposal.repository.casefold() != canonical_repository.casefold(),
        "source.revision-changed",
        "repository-identity:mismatch",
    )
    mismatch(
        repository.base_ref != proposal.base_branch,
        "source.revision-changed",
        "repository-base:mismatch",
    )
    mismatch(
        repository.head_sha != proposal.evaluated_repository_sha,
        "source.revision-changed",
        "repository-head:mismatch",
    )
    mismatch(
        repository.requested_sha != proposal.evaluated_repository_sha,
        "source.revision-changed",
        "repository-requested:mismatch",
    )
    mismatch(
        repository.contract_fingerprint
        != issueplan.implementation_contract_fingerprint,
        "contract.scope-changed",
        "implementation-contract:mismatch",
    )
    if repository.tested_sha is None or repository.evidence_type is None:
        return (
            None,
            "needs-decision",
            ("projection.incomplete",),
            ("repository-tested-evidence:missing",),
        )
    if mismatch_reasons:
        return (
            None,
            _status_for_reasons(mismatch_reasons),
            tuple(sorted(mismatch_reasons)),
            tuple(sorted(mismatch_details)),
        )
    return (
        ApprovalBinding(
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
            cohort_summaries=tuple(proposal.cohort_summaries),
            issueplan_current_state_evidence_id=issueplan.evidence_id,
            repository_state_evidence_id=repository.evidence_id,
            repository_evidence_type=repository.evidence_type.value,
            tested_repository_sha=repository.tested_sha,
            source_snapshot_fingerprint=issueplan.source_snapshot_fingerprint,
            scanner_result_fingerprint=issueplan.scanner_result_fingerprint,
            implementation_contract_fingerprint=(
                issueplan.implementation_contract_fingerprint
            ),
            allowed_files=issueplan.allowed_files,
            forbidden_paths=issueplan.forbidden_paths,
            required_tests=issueplan.required_tests,
        ),
        "applicable",
        (),
        (),
    )


def compute_current_approval_binding(
    proposal: object,
    issueplan_current_state_evidence: IssuePlanCurrentStateEvidence,
    repository_state_evidence: RepositoryStateEvidence | Mapping[str, Any],
    planning_binding: PlanningBindingEvidence | None = None,
) -> ApprovalBinding:
    """Return the freshly computed CURRENT ApprovalBinding for exact-identity use.

    Unlike a stored ApprovalRecord.binding, this always reflects the current
    proposal/repository/planning identities -- required by #407 so a projection
    built after semantic carry-forward binds current exact IDs, not stale ones.
    """
    binding, status, reasons, details = _current_binding(
        proposal,
        issueplan_current_state_evidence,
        repository_state_evidence,
        planning_binding,
    )
    if binding is None or status != "applicable":
        raise ValueError(
            "current approval binding requires current validated inputs: "
            + ",".join((*reasons, *details))
        )
    return binding


def _repository_state_for_subject(
    value: RepositoryStateEvidence | Mapping[str, Any],
) -> RepositoryStateEvidence:
    if isinstance(value, RepositoryStateEvidence):
        return value
    if isinstance(value, Mapping):
        try:
            return RepositoryStateEvidence(**dict(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"repository_state_evidence is malformed: {exc}"
            ) from exc
    raise TypeError(
        "repository_state_evidence must be RepositoryStateEvidence or a mapping"
    )


def _semantic_subject_payload(
    binding: ApprovalBinding,
    repository_state_evidence: RepositoryStateEvidence | Mapping[str, Any],
    planning_binding: PlanningBindingEvidence | None,
    *,
    approval_kind: str,
    expires_at: str | None,
    supersedes_approval_id: str | None,
) -> dict[str, Any]:
    repository_state = _repository_state_for_subject(repository_state_evidence)
    if repository_state.evidence_id != binding.repository_state_evidence_id:
        raise ValueError(
            "repository_state_evidence does not match the current approval binding"
        )
    return {
        "subject_schema_version": SEMANTIC_APPROVAL_SUBJECT_SCHEMA_VERSION,
        "approval_kind": approval_kind,
        "expires_at": expires_at,
        "supersedes_approval_id": supersedes_approval_id,
        "proposal_version": binding.proposal_version,
        "repository": binding.repository.casefold(),
        "base_branch": binding.base_branch,
        "evaluated_repository_sha": binding.evaluated_repository_sha,
        "evaluator_commit_sha": binding.evaluator_commit_sha,
        "graph_digest": binding.graph_digest,
        "planning_result_digest": binding.planning_result_digest,
        "supplied_node_ids": list(binding.supplied_node_ids),
        "cohort_summaries": [
            {
                "node_ids": list(cohort.node_ids),
                "classification": cohort.classification,
                "reason_codes": list(cohort.reason_codes),
            }
            for cohort in binding.cohort_summaries
        ],
        "issueplan_current_state_evidence_id": (
            binding.issueplan_current_state_evidence_id
        ),
        "repository_evidence_type": binding.repository_evidence_type,
        "tested_repository_sha": binding.tested_repository_sha,
        "source_snapshot_fingerprint": binding.source_snapshot_fingerprint,
        "scanner_result_fingerprint": binding.scanner_result_fingerprint,
        "implementation_contract_fingerprint": (
            binding.implementation_contract_fingerprint
        ),
        "allowed_files": list(binding.allowed_files),
        "forbidden_paths": list(binding.forbidden_paths),
        "required_tests": list(binding.required_tests),
        "repository_identity": list(
            repository_state.repository_identity.canonical_key
        ),
        "head_ref": repository_state.head_ref,
        "requested_ref": repository_state.requested_ref,
        "producer_adapter": repository_state.producer_adapter,
        "producer_adapter_version": repository_state.producer_adapter_version,
        "evidence_schema_version": repository_state.evidence_schema_version,
        "base_sha": repository_state.base_sha,
        "head_sha": repository_state.head_sha,
        "requested_sha": repository_state.requested_sha,
        "pushed_sha": repository_state.pushed_sha,
        "proposed_pr_sha": repository_state.proposed_pr_sha,
        "synthetic_merge_sha": repository_state.synthetic_merge_sha,
        "external_build_sha": repository_state.external_build_sha,
        "contract_fingerprint": repository_state.contract_fingerprint,
        "worktree_state": repository_state.worktree_state.value,
        "worktree_reason_codes": list(repository_state.worktree_reason_codes),
        "freshness_boundary": repository_state.freshness_boundary,
        "handoff_contract_version": (
            planning_binding.handoff_contract_version
            if planning_binding is not None
            else None
        ),
        "planning_result_version": (
            planning_binding.planning_result_version
            if planning_binding is not None
            else None
        ),
    }


def compute_semantic_approval_subject(
    binding: ApprovalBinding,
    repository_state_evidence: RepositoryStateEvidence | Mapping[str, Any],
    *,
    approval_kind: ApprovalKind | str,
    expires_at: str | None = None,
    supersedes_approval_id: str | None = None,
    planning_binding: PlanningBindingEvidence | None = None,
) -> str:
    """Compute the versioned canonical semantic approval-subject identity.

    Includes all authority-relevant semantics and excludes only the approved
    audit/attempt metadata: RepositoryStateEvidence.observed_at and
    correlation_id, SchedulerPlanningHandoff.created_at (via
    PlanningBindingEvidence.handoff_digest, which is never used here),
    PlanningBindingEvidence.created_at, and DraftTaskProposal.created_at.
    """
    if not isinstance(binding, ApprovalBinding):
        raise TypeError("binding must be ApprovalBinding")
    if planning_binding is not None and not isinstance(
        planning_binding, PlanningBindingEvidence
    ):
        raise TypeError("planning_binding must be PlanningBindingEvidence or None")
    kind_value = ApprovalKind(approval_kind).value
    payload = _semantic_subject_payload(
        binding,
        repository_state_evidence,
        planning_binding,
        approval_kind=kind_value,
        expires_at=expires_at,
        supersedes_approval_id=supersedes_approval_id,
    )
    return f"semantic-approval-subject:{_digest(payload)}"


def _verified_proposal(proposal: object) -> Any:
    proposal_type = type(proposal)
    if proposal_type.__name__ != "DraftTaskProposal" or not (
        proposal_type.__module__.startswith("workflow_scheduler.planning")
    ):
        raise TypeError("proposal must be the public WSC3 DraftTaskProposal")
    verified = proposal_type(
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
        cohort_summaries=tuple(proposal.cohort_summaries),
        issueplan_current_state_evidence_id=(
            proposal.issueplan_current_state_evidence_id
        ),
        repository_state_evidence_id=proposal.repository_state_evidence_id,
        created_at=proposal.created_at,
    )
    if (
        verified.authorization_status != "not-evaluated"
        or verified.execution_authorized
    ):
        raise ValueError("proposal must remain unapproved and non-authorizing")
    if {
        cohort.classification for cohort in verified.cohort_summaries
    } != {"parallel-candidate"}:
        raise ValueError("only executable parallel-candidate cohorts may be approved")
    return verified


def _verified_record(record: ApprovalRecord) -> ApprovalRecord:
    if not isinstance(record, ApprovalRecord):
        raise TypeError("record must be ApprovalRecord")
    return ApprovalRecord(
        schema_version=record.schema_version,
        approval_id=record.approval_id,
        approval_revision=record.approval_revision,
        revision_number=record.revision_number,
        previous_revision=record.previous_revision,
        approval_kind=record.approval_kind,
        state=record.state,
        binding=record.binding,
        authorizer_id=record.authorizer_id,
        decision_id=record.decision_id,
        decision_at=record.decision_at,
        expires_at=record.expires_at,
        supersedes_approval_id=record.supersedes_approval_id,
        reason_codes=record.reason_codes,
        details=record.details,
        semantic_subject_id=record.semantic_subject_id,
    )


def _approval_id(
    kind: ApprovalKind,
    binding: ApprovalBinding,
    expires_at: str | None,
    supersedes_approval_id: str | None,
    *,
    schema_version: str = APPROVAL_RECORD_SCHEMA_VERSION,
    semantic_subject_id: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "approval_kind": kind.value,
        "binding": _binding_payload(binding),
        "expires_at": expires_at,
        "supersedes_approval_id": supersedes_approval_id,
    }
    if semantic_subject_id is not None:
        payload["semantic_subject_id"] = semantic_subject_id
    return f"approval:{_digest(payload)}"


def _approval_revision(record: ApprovalRecord) -> str:
    payload: dict[str, Any] = {
        "schema_version": record.schema_version,
        "approval_id": record.approval_id,
        "revision_number": record.revision_number,
        "previous_revision": record.previous_revision,
        "approval_kind": record.approval_kind.value,
        "state": record.state.value,
        "binding": _binding_payload(record.binding),
        "authorizer_id": record.authorizer_id,
        "decision_id": record.decision_id,
        "decision_at": record.decision_at,
        "expires_at": record.expires_at,
        "supersedes_approval_id": record.supersedes_approval_id,
        "reason_codes": list(record.reason_codes),
    }
    if record.semantic_subject_id is not None:
        payload["semantic_subject_id"] = record.semantic_subject_id
    return f"approval-revision:{_digest(payload)}"


def _binding_payload(binding: ApprovalBinding) -> dict[str, Any]:
    return {
        "proposal_version": binding.proposal_version,
        "proposal_id": binding.proposal_id,
        "handoff_digest": binding.handoff_digest,
        "graph_digest": binding.graph_digest,
        "planning_result_digest": binding.planning_result_digest,
        "repository": binding.repository.casefold(),
        "base_branch": binding.base_branch,
        "evaluated_repository_sha": binding.evaluated_repository_sha,
        "evaluator_commit_sha": binding.evaluator_commit_sha,
        "supplied_node_ids": list(binding.supplied_node_ids),
        "cohort_summaries": [
            {
                "node_ids": list(cohort.node_ids),
                "classification": cohort.classification,
                "reason_codes": list(cohort.reason_codes),
            }
            for cohort in binding.cohort_summaries
        ],
        "issueplan_current_state_evidence_id": (
            binding.issueplan_current_state_evidence_id
        ),
        "repository_state_evidence_id": binding.repository_state_evidence_id,
        "repository_evidence_type": binding.repository_evidence_type,
        "tested_repository_sha": binding.tested_repository_sha,
        "source_snapshot_fingerprint": binding.source_snapshot_fingerprint,
        "scanner_result_fingerprint": binding.scanner_result_fingerprint,
        "implementation_contract_fingerprint": (
            binding.implementation_contract_fingerprint
        ),
        "allowed_files": list(binding.allowed_files),
        "forbidden_paths": list(binding.forbidden_paths),
        "required_tests": list(binding.required_tests),
    }


def _changed_bindings(
    expected: ApprovalBinding, current: ApprovalBinding
) -> tuple[str, ...]:
    names = (
        "proposal_version",
        "proposal_id",
        "handoff_digest",
        "graph_digest",
        "planning_result_digest",
        "repository",
        "base_branch",
        "evaluated_repository_sha",
        "evaluator_commit_sha",
        "supplied_node_ids",
        "cohort_summaries",
        "issueplan_current_state_evidence_id",
        "repository_state_evidence_id",
        "repository_evidence_type",
        "tested_repository_sha",
        "source_snapshot_fingerprint",
        "scanner_result_fingerprint",
        "implementation_contract_fingerprint",
        "allowed_files",
        "forbidden_paths",
        "required_tests",
    )
    return tuple(
        sorted(
            name
            for name in names
            if getattr(expected, name) != getattr(current, name)
        )
    )


def _binding_reasons(changed: Iterable[str]) -> tuple[str, ...]:
    reasons: set[str] = set()
    for name in changed:
        if name == "handoff_digest":
            reasons.add("handoff.changed")
        elif name in {"graph_digest", "planning_result_digest"}:
            reasons.add("graph.changed")
        elif name == "allowed_files":
            reasons.add("contract.allowlist-changed")
        elif name == "required_tests":
            reasons.add("contract.required-tests-changed")
        elif name in {
            "forbidden_paths",
            "implementation_contract_fingerprint",
        }:
            reasons.add("contract.scope-changed")
        elif name in {
            "repository",
            "base_branch",
            "evaluated_repository_sha",
            "source_snapshot_fingerprint",
        }:
            reasons.add("source.revision-changed")
        elif name == "proposal_version":
            reasons.add("version.unsupported")
        else:
            reasons.add("candidate.changed")
    return tuple(sorted(reasons))


def _status_for_reasons(reasons: Iterable[str]) -> str:
    reason_set = set(reasons)
    if not reason_set:
        return "applicable"
    if reason_set & _INVALID:
        return "invalid"
    if reason_set & _NEEDS_DECISION:
        return "needs-decision"
    if reason_set & _BLOCKED:
        return "blocked"
    return "stale"


def _issueplan_status(outcome: IssuePlanCurrentStateOutcome) -> str:
    return {
        IssuePlanCurrentStateOutcome.CURRENT: "applicable",
        IssuePlanCurrentStateOutcome.STALE: "stale",
        IssuePlanCurrentStateOutcome.BLOCKED: "blocked",
        IssuePlanCurrentStateOutcome.INVALID: "invalid",
        IssuePlanCurrentStateOutcome.NEEDS_DECISION: "needs-decision",
    }[outcome]


def _result(
    status: str,
    approval_id: str | None,
    approval_revision: str | None,
    proposal_id: str | None,
    reasons: Iterable[str],
    changed: Iterable[str],
    details: Iterable[str],
) -> ApprovalApplicabilityResult:
    return ApprovalApplicabilityResult(
        status,
        approval_id,
        approval_revision,
        proposal_id,
        tuple(reasons),
        tuple(changed),
        status == "applicable",
        tuple(details),
    )


def _proposal_id_or_none(value: object) -> str | None:
    proposal_id = getattr(value, "proposal_id", None)
    return proposal_id if isinstance(proposal_id, str) else None


def _cohorts(values: Iterable[HandoffCohort]) -> tuple[HandoffCohort, ...]:
    cohorts = tuple(values)
    if not cohorts or not all(
        isinstance(item, HandoffCohort) for item in cohorts
    ):
        raise TypeError("cohort_summaries must contain HandoffCohort values")
    return tuple(
        sorted(
            cohorts,
            key=lambda item: (
                item.classification,
                tuple(item.node_ids),
                tuple(item.reason_codes),
            ),
        )
    )


def _strings(
    values: Iterable[str], name: str, *, allow_empty: bool
) -> tuple[str, ...]:
    result = tuple(sorted(set(values)))
    if (not allow_empty and not result) or not all(
        isinstance(item, str) and item for item in result
    ):
        raise ValueError(f"{name} must contain non-empty strings")
    return result


def _reason_codes(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError("reason_codes must be an iterable of codes")
    result = tuple(sorted(set(values)))
    if not set(result) <= APPROVAL_INVALIDATION_REASON_CODES:
        raise ValueError("reason_codes must use the ratified #347 vocabulary")
    return result


def _text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _sha40(value: object, name: str) -> None:
    if not isinstance(value, str) or not _SHA40_RE.fullmatch(value):
        raise ValueError(f"{name} must be a full lowercase commit SHA")


def _sha256(value: object, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{name} must be a SHA-256 digest")


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise ValueError(f"{name} must be an RFC3339 UTC timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid RFC3339 UTC timestamp") from exc


def _optional_timestamp(value: object, name: str) -> datetime | None:
    return None if value is None else _timestamp(value, name)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


_APPROVAL_BINDING_TRANSPORT_KEYS = frozenset(
    {
        "proposal_version",
        "proposal_id",
        "handoff_digest",
        "graph_digest",
        "planning_result_digest",
        "repository",
        "base_branch",
        "evaluated_repository_sha",
        "evaluator_commit_sha",
        "supplied_node_ids",
        "cohort_summaries",
        "issueplan_current_state_evidence_id",
        "repository_state_evidence_id",
        "repository_evidence_type",
        "tested_repository_sha",
        "source_snapshot_fingerprint",
        "scanner_result_fingerprint",
        "implementation_contract_fingerprint",
        "allowed_files",
        "forbidden_paths",
        "required_tests",
    }
)
_APPROVAL_RECORD_TRANSPORT_KEYS = frozenset(
    {
        "schema_version",
        "approval_id",
        "approval_revision",
        "revision_number",
        "previous_revision",
        "approval_kind",
        "state",
        "binding",
        "authorizer_id",
        "decision_id",
        "decision_at",
        "expires_at",
        "supersedes_approval_id",
        "reason_codes",
        "details",
        "execution_authorized",
        "side_effects_performed",
    }
)
_APPROVAL_RECORD_TRANSPORT_KEYS_SEMANTIC = _APPROVAL_RECORD_TRANSPORT_KEYS | {
    "semantic_subject_id"
}
_APPROVAL_APPLICABILITY_TRANSPORT_KEYS = frozenset(
    {
        "status",
        "approval_id",
        "approval_revision",
        "current_proposal_id",
        "reason_codes",
        "changed_bindings",
        "approval_applicable",
        "details",
        "execution_authorized",
        "side_effects_performed",
    }
)
_COHORT_TRANSPORT_KEYS = frozenset({"node_ids", "classification", "reason_codes"})


def serialize_approval_binding(binding: ApprovalBinding) -> bytes:
    """Serialize one verified approval binding as canonical UTF-8 JSON."""

    if not isinstance(binding, ApprovalBinding):
        raise TypeError("binding must be ApprovalBinding")
    verified = ApprovalBinding(**_approval_binding_constructor_values(binding))
    return _canonical_transport_bytes(_approval_binding_transport_payload(verified))


def reconstruct_approval_binding(
    payload: bytes | str | Mapping[str, Any],
) -> ApprovalBinding:
    """Strictly reconstruct an approval binding from closed-schema transport data."""

    raw = _decode_transport_payload(payload, "approval binding")
    _require_exact_transport_keys(raw, _APPROVAL_BINDING_TRANSPORT_KEYS, "approval binding")
    values = _approval_binding_values_from_transport(raw)
    return ApprovalBinding(**values)


def serialize_approval_record(record: ApprovalRecord) -> bytes:
    """Serialize one verified approval record as canonical UTF-8 JSON."""

    verified = _verified_record(record)
    return _canonical_transport_bytes(_approval_record_transport_payload(verified))


def reconstruct_approval_record(
    payload: bytes | str | Mapping[str, Any],
) -> ApprovalRecord:
    """Strictly reconstruct one approval record and reverify its supplied identities."""

    raw = _decode_transport_payload(payload, "approval record")
    is_semantic = (
        isinstance(raw, Mapping)
        and raw.get("schema_version") == APPROVAL_RECORD_SEMANTIC_SCHEMA_VERSION
    )
    expected_keys = (
        _APPROVAL_RECORD_TRANSPORT_KEYS_SEMANTIC
        if is_semantic
        else _APPROVAL_RECORD_TRANSPORT_KEYS
    )
    _require_exact_transport_keys(raw, expected_keys, "approval record")
    _require_fixed_false(raw, "approval record")
    if type(raw["revision_number"]) is not int:
        raise ValueError("revision_number must be a positive integer")
    binding_raw = raw["binding"]
    if not isinstance(binding_raw, Mapping):
        raise ValueError("binding must be an object")
    reason_codes = _require_string_array(raw["reason_codes"], "reason_codes")
    details = _require_string_array(raw["details"], "details")
    try:
        approval_kind = ApprovalKind(raw["approval_kind"])
    except (TypeError, ValueError) as exc:
        raise ValueError("approval_kind is unsupported") from exc
    try:
        state = ApprovalState(raw["state"])
    except (TypeError, ValueError) as exc:
        raise ValueError("state is unsupported") from exc
    return ApprovalRecord(
        schema_version=raw["schema_version"],
        approval_id=raw["approval_id"],
        approval_revision=raw["approval_revision"],
        revision_number=raw["revision_number"],
        previous_revision=raw["previous_revision"],
        approval_kind=approval_kind,
        state=state,
        binding=reconstruct_approval_binding(binding_raw),
        authorizer_id=raw["authorizer_id"],
        decision_id=raw["decision_id"],
        decision_at=raw["decision_at"],
        expires_at=raw["expires_at"],
        supersedes_approval_id=raw["supersedes_approval_id"],
        reason_codes=reason_codes,
        details=details,
        semantic_subject_id=raw.get("semantic_subject_id"),
    )


def serialize_approval_applicability_result(
    result: ApprovalApplicabilityResult,
) -> bytes:
    """Serialize one applicability result without creating authorization."""

    if not isinstance(result, ApprovalApplicabilityResult):
        raise TypeError("result must be ApprovalApplicabilityResult")
    return _canonical_transport_bytes(
        {
            "status": result.status,
            "approval_id": result.approval_id,
            "approval_revision": result.approval_revision,
            "current_proposal_id": result.current_proposal_id,
            "reason_codes": list(result.reason_codes),
            "changed_bindings": list(result.changed_bindings),
            "approval_applicable": result.approval_applicable,
            "details": list(result.details),
            "execution_authorized": False,
            "side_effects_performed": False,
        }
    )


def reconstruct_approval_applicability_result(
    payload: bytes | str | Mapping[str, Any],
) -> ApprovalApplicabilityResult:
    """Strictly reconstruct one approval applicability result."""

    raw = _decode_transport_payload(payload, "approval applicability result")
    _require_exact_transport_keys(
        raw,
        _APPROVAL_APPLICABILITY_TRANSPORT_KEYS,
        "approval applicability result",
    )
    _require_fixed_false(raw, "approval applicability result")
    if type(raw["approval_applicable"]) is not bool:
        raise ValueError("approval_applicable must be a boolean")
    for name, pattern in (
        ("approval_id", _APPROVAL_ID_RE),
        ("approval_revision", _REVISION_ID_RE),
        ("current_proposal_id", _PROPOSAL_ID_RE),
    ):
        value = raw[name]
        if value is not None and (
            not isinstance(value, str) or not pattern.fullmatch(value)
        ):
            raise ValueError(f"{name} is malformed")
    return ApprovalApplicabilityResult(
        status=raw["status"],
        approval_id=raw["approval_id"],
        approval_revision=raw["approval_revision"],
        current_proposal_id=raw["current_proposal_id"],
        reason_codes=_require_string_array(raw["reason_codes"], "reason_codes"),
        changed_bindings=_require_string_array(
            raw["changed_bindings"], "changed_bindings"
        ),
        approval_applicable=raw["approval_applicable"],
        details=_require_string_array(raw["details"], "details"),
    )


def _approval_binding_constructor_values(binding: ApprovalBinding) -> dict[str, Any]:
    return {
        "proposal_version": binding.proposal_version,
        "proposal_id": binding.proposal_id,
        "handoff_digest": binding.handoff_digest,
        "graph_digest": binding.graph_digest,
        "planning_result_digest": binding.planning_result_digest,
        "repository": binding.repository,
        "base_branch": binding.base_branch,
        "evaluated_repository_sha": binding.evaluated_repository_sha,
        "evaluator_commit_sha": binding.evaluator_commit_sha,
        "supplied_node_ids": binding.supplied_node_ids,
        "cohort_summaries": binding.cohort_summaries,
        "issueplan_current_state_evidence_id": binding.issueplan_current_state_evidence_id,
        "repository_state_evidence_id": binding.repository_state_evidence_id,
        "repository_evidence_type": binding.repository_evidence_type,
        "tested_repository_sha": binding.tested_repository_sha,
        "source_snapshot_fingerprint": binding.source_snapshot_fingerprint,
        "scanner_result_fingerprint": binding.scanner_result_fingerprint,
        "implementation_contract_fingerprint": binding.implementation_contract_fingerprint,
        "allowed_files": binding.allowed_files,
        "forbidden_paths": binding.forbidden_paths,
        "required_tests": binding.required_tests,
    }


def _approval_binding_transport_payload(binding: ApprovalBinding) -> dict[str, Any]:
    values = _approval_binding_constructor_values(binding)
    return {
        **values,
        "supplied_node_ids": list(binding.supplied_node_ids),
        "cohort_summaries": [_cohort_transport_payload(item) for item in binding.cohort_summaries],
        "allowed_files": list(binding.allowed_files),
        "forbidden_paths": list(binding.forbidden_paths),
        "required_tests": list(binding.required_tests),
    }


def _approval_record_transport_payload(record: ApprovalRecord) -> dict[str, Any]:
    payload = {
        "schema_version": record.schema_version,
        "approval_id": record.approval_id,
        "approval_revision": record.approval_revision,
        "revision_number": record.revision_number,
        "previous_revision": record.previous_revision,
        "approval_kind": record.approval_kind.value,
        "state": record.state.value,
        "binding": _approval_binding_transport_payload(record.binding),
        "authorizer_id": record.authorizer_id,
        "decision_id": record.decision_id,
        "decision_at": record.decision_at,
        "expires_at": record.expires_at,
        "supersedes_approval_id": record.supersedes_approval_id,
        "reason_codes": list(record.reason_codes),
        "details": list(record.details),
        "execution_authorized": False,
        "side_effects_performed": False,
    }
    if record.schema_version == APPROVAL_RECORD_SEMANTIC_SCHEMA_VERSION:
        payload["semantic_subject_id"] = record.semantic_subject_id
    return payload


def _approval_binding_values_from_transport(raw: Mapping[str, Any]) -> dict[str, Any]:
    for name in ("supplied_node_ids", "allowed_files", "forbidden_paths", "required_tests"):
        _require_string_array(raw[name], name)
    cohorts_raw = raw["cohort_summaries"]
    if not isinstance(cohorts_raw, list):
        raise ValueError("cohort_summaries must be a JSON array")
    cohorts = tuple(_reconstruct_transport_cohort(item) for item in cohorts_raw)
    return {
        "proposal_version": raw["proposal_version"],
        "proposal_id": raw["proposal_id"],
        "handoff_digest": raw["handoff_digest"],
        "graph_digest": raw["graph_digest"],
        "planning_result_digest": raw["planning_result_digest"],
        "repository": raw["repository"],
        "base_branch": raw["base_branch"],
        "evaluated_repository_sha": raw["evaluated_repository_sha"],
        "evaluator_commit_sha": raw["evaluator_commit_sha"],
        "supplied_node_ids": tuple(raw["supplied_node_ids"]),
        "cohort_summaries": cohorts,
        "issueplan_current_state_evidence_id": raw["issueplan_current_state_evidence_id"],
        "repository_state_evidence_id": raw["repository_state_evidence_id"],
        "repository_evidence_type": raw["repository_evidence_type"],
        "tested_repository_sha": raw["tested_repository_sha"],
        "source_snapshot_fingerprint": raw["source_snapshot_fingerprint"],
        "scanner_result_fingerprint": raw["scanner_result_fingerprint"],
        "implementation_contract_fingerprint": raw["implementation_contract_fingerprint"],
        "allowed_files": tuple(raw["allowed_files"]),
        "forbidden_paths": tuple(raw["forbidden_paths"]),
        "required_tests": tuple(raw["required_tests"]),
    }


def _cohort_transport_payload(cohort: HandoffCohort) -> dict[str, Any]:
    return {
        "node_ids": list(cohort.node_ids),
        "classification": cohort.classification,
        "reason_codes": list(cohort.reason_codes),
    }


def _reconstruct_transport_cohort(payload: object) -> HandoffCohort:
    if not isinstance(payload, Mapping):
        raise ValueError("cohort_summaries entries must be objects")
    _require_exact_transport_keys(payload, _COHORT_TRANSPORT_KEYS, "cohort summary")
    node_ids = _require_string_array(payload["node_ids"], "cohort node_ids")
    reason_codes = _require_string_array(payload["reason_codes"], "cohort reason_codes")
    classification = payload["classification"]
    if not isinstance(classification, str) or not classification:
        raise ValueError("cohort classification must be a non-empty string")
    if not node_ids or any(not item for item in node_ids):
        raise ValueError("cohort node_ids must contain non-empty strings")
    if any(not item for item in reason_codes):
        raise ValueError("cohort reason_codes must contain non-empty strings")
    return HandoffCohort(tuple(node_ids), classification, tuple(reason_codes))


def _decode_transport_payload(
    payload: bytes | str | Mapping[str, Any], name: str
) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{name} must be UTF-8 JSON") from exc
    elif isinstance(payload, str):
        text = payload
    else:
        raise TypeError(f"{name} must be bytes, string, or mapping")
    try:
        decoded = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"{name} must contain valid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError(f"{name} must contain a JSON object")
    return decoded


def _require_exact_transport_keys(
    payload: Mapping[str, Any], expected: frozenset[str], name: str
) -> None:
    actual = set(payload)
    unknown = actual - expected
    missing = expected - actual
    if unknown:
        raise ValueError(f"{name} contains unknown fields: {sorted(unknown)}")
    if missing:
        raise ValueError(f"{name} is missing fields: {sorted(missing)}")


def _require_string_array(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must contain only strings")
    return tuple(value)


def _require_fixed_false(payload: Mapping[str, Any], name: str) -> None:
    if payload["execution_authorized"] is not False:
        raise ValueError(f"{name} execution_authorized must be false")
    if payload["side_effects_performed"] is not False:
        raise ValueError(f"{name} side_effects_performed must be false")


def _canonical_transport_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
