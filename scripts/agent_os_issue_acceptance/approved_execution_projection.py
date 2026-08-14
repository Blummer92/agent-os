from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from scripts.agent_os_execution_capabilities import (
    RepositoryEvidenceType,
    RepositoryStateEvidence,
)

from .approval_records import (
    APPROVAL_INVALIDATION_REASON_CODES,
    APPROVAL_RECORD_SUPPORTED_SCHEMA_VERSIONS,
    ApprovalApplicabilityResult,
    ApprovalKind,
    ApprovalRecord,
    ApprovalState,
    compute_current_approval_binding,
    evaluate_approval_applicability,
)
from .issueplan_current_state import IssuePlanCurrentStateEvidence
from .planning_binding import PlanningBindingEvidence
from .scheduler_handoff import HandoffCohort

APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION = "1.0"

_PROJECTION_ID_RE = re.compile(r"^approved-execution-projection:[0-9a-f]{64}$")
_APPROVAL_ID_RE = re.compile(r"^approval:[0-9a-f]{64}$")
_APPROVAL_REVISION_RE = re.compile(r"^approval-revision:[0-9a-f]{64}$")
_PROPOSAL_ID_RE = re.compile(r"^draft-task-proposal:[0-9a-f]{64}$")
_ISSUEPLAN_ID_RE = re.compile(r"^issueplan-current-state:[0-9a-f]{64}$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_RESULT_STATUSES = frozenset(
    {"complete", "stale", "blocked", "invalid", "needs-decision"}
)


@dataclass(frozen=True, slots=True)
class ApprovedExecutionProjection:
    """Portable, complete, read-only projection of one approved proposal."""

    schema_version: str
    projection_id: str
    proposal_version: str
    proposal_id: str
    approval_id: str
    approval_revision: str
    approval_revision_number: int
    approval_kind: str
    approval_state: Literal["approved"]
    approval_authorizer_id: str
    approval_decision_id: str
    approval_decision_at: str
    approval_expires_at: str | None
    approval_supersedes_id: str | None
    handoff_digest: str
    graph_digest: str
    planning_result_digest: str
    repository: str
    base_branch: str
    evaluated_repository_sha: str
    evaluator_commit_sha: str
    tested_repository_sha: str
    repository_evidence_type: str
    supplied_node_ids: tuple[str, ...]
    cohort_summaries: tuple[HandoffCohort, ...]
    issueplan_current_state_evidence_id: str
    repository_state_evidence_id: str
    source_snapshot_fingerprint: str
    scanner_result_fingerprint: str
    implementation_contract_fingerprint: str
    allowed_files: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_tests: tuple[str, ...]
    projected_at: str
    complete: Literal[True] = field(default=True, init=False)
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION:
            raise ValueError("unsupported projection schema version")
        _matches(self.proposal_id, _PROPOSAL_ID_RE, "proposal_id")
        _matches(self.approval_id, _APPROVAL_ID_RE, "approval_id")
        _matches(self.approval_revision, _APPROVAL_REVISION_RE, "approval_revision")
        _matches(
            self.issueplan_current_state_evidence_id,
            _ISSUEPLAN_ID_RE,
            "issueplan_current_state_evidence_id",
        )
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
        for name in (
            "proposal_version",
            "repository",
            "base_branch",
            "approval_authorizer_id",
            "approval_decision_id",
        ):
            _text(getattr(self, name), name)
        if self.repository.count("/") != 1:
            raise ValueError("repository must use owner/name form")
        if self.approval_kind not in {item.value for item in ApprovalKind}:
            raise ValueError("approval_kind is unsupported")
        if self.approval_state != ApprovalState.APPROVED.value:
            raise ValueError("projection requires approved approval state")
        if (
            not isinstance(self.approval_revision_number, int)
            or isinstance(self.approval_revision_number, bool)
            or self.approval_revision_number < 2
        ):
            raise ValueError("approved projection requires a decision revision")
        _timestamp(self.approval_decision_at, "approval_decision_at")
        _optional_timestamp(self.approval_expires_at, "approval_expires_at")
        _timestamp(self.projected_at, "projected_at")
        if self.approval_supersedes_id is not None:
            _matches(
                self.approval_supersedes_id,
                _APPROVAL_ID_RE,
                "approval_supersedes_id",
            )
        if self.repository_evidence_type not in {
            item.value for item in RepositoryEvidenceType
        }:
            raise ValueError("repository_evidence_type is unsupported")

        nodes = _strings(self.supplied_node_ids, "supplied_node_ids", allow_empty=False)
        cohorts = _cohorts(self.cohort_summaries)
        covered = tuple(sorted(node for cohort in cohorts for node in cohort.node_ids))
        if covered != nodes:
            raise ValueError("cohort_summaries must cover supplied_node_ids exactly")
        object.__setattr__(self, "supplied_node_ids", nodes)
        object.__setattr__(self, "cohort_summaries", cohorts)
        for name in ("allowed_files", "forbidden_paths", "required_tests"):
            object.__setattr__(
                self,
                name,
                _strings(getattr(self, name), name, allow_empty=True),
            )

        expected_id = _projection_id(_semantic_payload(self))
        if self.projection_id and self.projection_id != expected_id:
            raise ValueError("projection_id does not match projection content")
        object.__setattr__(self, "projection_id", expected_id)


@dataclass(frozen=True, slots=True)
class ApprovedExecutionProjectionResult:
    """Fail-closed result for portable approved-execution projection building."""

    status: str
    projection: ApprovedExecutionProjection | None
    reason_codes: tuple[str, ...]
    details: tuple[str, ...] = ()
    complete: bool = field(init=False)
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.status not in _RESULT_STATUSES:
            raise ValueError("unsupported projection result status")
        reasons = _reason_codes(self.reason_codes)
        details = tuple(str(item) for item in self.details)
        is_complete = self.status == "complete"
        if is_complete:
            if not isinstance(self.projection, ApprovedExecutionProjection):
                raise ValueError("complete result requires one projection")
            if reasons:
                raise ValueError("complete result cannot carry reason codes")
        else:
            if self.projection is not None:
                raise ValueError("non-complete result cannot carry a projection")
            if not reasons:
                raise ValueError("non-complete result requires reason codes")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "details", details)
        object.__setattr__(self, "complete", is_complete)


def build_approved_execution_projection(
    proposal: object,
    approval_record: ApprovalRecord | None,
    approval_applicability: ApprovalApplicabilityResult | None,
    issueplan_current_state_evidence: IssuePlanCurrentStateEvidence | None,
    repository_state_evidence: RepositoryStateEvidence | None,
    *,
    projected_at: str,
    planning_binding: PlanningBindingEvidence | None = None,
    schema_version: str = APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION,
) -> ApprovedExecutionProjectionResult:
    """Build one complete projection from supplied, reverified immutable evidence."""

    if schema_version != APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION:
        return _failure("invalid", ("version.unsupported",), ("schema-version",))
    try:
        _timestamp(projected_at, "projected_at")
    except ValueError as exc:
        return _failure("invalid", ("projection.incomplete",), (str(exc),))
    if planning_binding is not None and not isinstance(
        planning_binding, PlanningBindingEvidence
    ):
        return _failure(
            "invalid",
            ("projection.incomplete",),
            ("planning-binding:invalid-type",),
        )
    if approval_record is None:
        return _failure(
            "needs-decision",
            ("projection.lookup-failed",),
            ("approval-record:missing",),
        )
    if not isinstance(issueplan_current_state_evidence, IssuePlanCurrentStateEvidence):
        return _failure(
            "needs-decision",
            ("projection.incomplete",),
            ("issueplan-evidence:missing-or-invalid",),
        )
    if not isinstance(repository_state_evidence, RepositoryStateEvidence):
        return _failure(
            "needs-decision",
            ("projection.incomplete",),
            ("repository-evidence:missing-or-invalid",),
        )
    if not isinstance(approval_applicability, ApprovalApplicabilityResult):
        return _failure(
            "invalid",
            ("projection.incomplete",),
            ("approval-applicability:invalid-type",),
        )

    try:
        recomputed = evaluate_approval_applicability(
            approval_record,
            proposal,
            issueplan_current_state_evidence,
            repository_state_evidence,
            evaluated_at=projected_at,
            planning_binding=planning_binding,
        )
    except (TypeError, ValueError) as exc:
        reason = (
            "version.unsupported"
            if getattr(approval_record, "schema_version", None)
            not in APPROVAL_RECORD_SUPPORTED_SCHEMA_VERSIONS
            else "projection.incomplete"
        )
        return _failure("invalid", (reason,), (f"verification:{exc}",))

    if approval_applicability != recomputed:
        return _failure(
            "invalid",
            ("projection.incomplete",),
            ("approval-applicability:mismatch",),
        )

    if approval_record.state != ApprovalState.APPROVED:
        lifecycle_reason = {
            ApprovalState.EXPIRED: "approval.expired",
            ApprovalState.INVALIDATED: "approval.invalidated",
            ApprovalState.SUPERSEDED: "approval.superseded",
        }.get(approval_record.state, "projection.incomplete")
        status = recomputed.status if recomputed.status != "applicable" else "blocked"
        return _failure(
            status,
            (*recomputed.reason_codes, lifecycle_reason),
            (f"approval-state:{approval_record.state.value}",),
        )

    if recomputed.status != "applicable":
        reasons = recomputed.reason_codes
        if not reasons:
            reasons = (
                ("candidate.changed",)
                if recomputed.status == "stale"
                else ("projection.incomplete",)
            )
        return _failure(recomputed.status, reasons, recomputed.details)

    if repository_state_evidence.tested_sha is None:
        return _failure(
            "needs-decision",
            ("projection.incomplete",),
            ("repository-tested-sha:missing",),
        )
    try:
        # Always bind CURRENT exact identities (proposal/repository-state/
        # planning-handoff), not the stored approval_record.binding -- when
        # semantic carry-forward applies those stored IDs are a stale prior
        # attempt's IDs even though the approval itself remains applicable.
        binding = compute_current_approval_binding(
            proposal,
            issueplan_current_state_evidence,
            repository_state_evidence,
            planning_binding,
        )
    except (TypeError, ValueError) as exc:
        return _failure(
            "invalid", ("projection.incomplete",), (f"current-binding:{exc}",)
        )

    try:
        projection = ApprovedExecutionProjection(
            schema_version=schema_version,
            projection_id="",
            proposal_version=binding.proposal_version,
            proposal_id=binding.proposal_id,
            approval_id=approval_record.approval_id,
            approval_revision=approval_record.approval_revision,
            approval_revision_number=approval_record.revision_number,
            approval_kind=approval_record.approval_kind.value,
            approval_state=approval_record.state.value,
            approval_authorizer_id=approval_record.authorizer_id,
            approval_decision_id=approval_record.decision_id,
            approval_decision_at=approval_record.decision_at,
            approval_expires_at=approval_record.expires_at,
            approval_supersedes_id=approval_record.supersedes_approval_id,
            handoff_digest=binding.handoff_digest,
            graph_digest=binding.graph_digest,
            planning_result_digest=binding.planning_result_digest,
            repository=binding.repository,
            base_branch=binding.base_branch,
            evaluated_repository_sha=binding.evaluated_repository_sha,
            evaluator_commit_sha=binding.evaluator_commit_sha,
            tested_repository_sha=binding.tested_repository_sha,
            repository_evidence_type=binding.repository_evidence_type,
            supplied_node_ids=binding.supplied_node_ids,
            cohort_summaries=binding.cohort_summaries,
            issueplan_current_state_evidence_id=(
                binding.issueplan_current_state_evidence_id
            ),
            repository_state_evidence_id=binding.repository_state_evidence_id,
            source_snapshot_fingerprint=binding.source_snapshot_fingerprint,
            scanner_result_fingerprint=binding.scanner_result_fingerprint,
            implementation_contract_fingerprint=(
                binding.implementation_contract_fingerprint
            ),
            allowed_files=binding.allowed_files,
            forbidden_paths=binding.forbidden_paths,
            required_tests=binding.required_tests,
            projected_at=projected_at,
        )
    except (TypeError, ValueError) as exc:
        return _failure("invalid", ("projection.incomplete",), (f"projection:{exc}",))

    return ApprovedExecutionProjectionResult("complete", projection, (), ())


def serialize_approved_execution_projection(
    projection: ApprovedExecutionProjection,
) -> bytes:
    """Serialize one verified projection as canonical UTF-8 JSON plus one newline."""

    verified = _verified_projection(projection)
    return _canonical_bytes(_projection_payload(verified)) + b"\n"


def _verified_projection(
    projection: ApprovedExecutionProjection,
) -> ApprovedExecutionProjection:
    if not isinstance(projection, ApprovedExecutionProjection):
        raise TypeError("projection must be ApprovedExecutionProjection")
    return ApprovedExecutionProjection(
        schema_version=projection.schema_version,
        projection_id=projection.projection_id,
        proposal_version=projection.proposal_version,
        proposal_id=projection.proposal_id,
        approval_id=projection.approval_id,
        approval_revision=projection.approval_revision,
        approval_revision_number=projection.approval_revision_number,
        approval_kind=projection.approval_kind,
        approval_state=projection.approval_state,
        approval_authorizer_id=projection.approval_authorizer_id,
        approval_decision_id=projection.approval_decision_id,
        approval_decision_at=projection.approval_decision_at,
        approval_expires_at=projection.approval_expires_at,
        approval_supersedes_id=projection.approval_supersedes_id,
        handoff_digest=projection.handoff_digest,
        graph_digest=projection.graph_digest,
        planning_result_digest=projection.planning_result_digest,
        repository=projection.repository,
        base_branch=projection.base_branch,
        evaluated_repository_sha=projection.evaluated_repository_sha,
        evaluator_commit_sha=projection.evaluator_commit_sha,
        tested_repository_sha=projection.tested_repository_sha,
        repository_evidence_type=projection.repository_evidence_type,
        supplied_node_ids=projection.supplied_node_ids,
        cohort_summaries=projection.cohort_summaries,
        issueplan_current_state_evidence_id=(
            projection.issueplan_current_state_evidence_id
        ),
        repository_state_evidence_id=projection.repository_state_evidence_id,
        source_snapshot_fingerprint=projection.source_snapshot_fingerprint,
        scanner_result_fingerprint=projection.scanner_result_fingerprint,
        implementation_contract_fingerprint=(
            projection.implementation_contract_fingerprint
        ),
        allowed_files=projection.allowed_files,
        forbidden_paths=projection.forbidden_paths,
        required_tests=projection.required_tests,
        projected_at=projection.projected_at,
    )


def _semantic_payload(projection: ApprovedExecutionProjection) -> dict[str, Any]:
    payload = _projection_payload(projection)
    payload.pop("projection_id")
    payload.pop("projected_at")
    payload.pop("complete")
    payload.pop("authoritative")
    payload.pop("execution_authorized")
    payload.pop("side_effects_performed")
    return payload


def _projection_payload(projection: ApprovedExecutionProjection) -> dict[str, Any]:
    return {
        "schema_version": projection.schema_version,
        "projection_id": projection.projection_id,
        "proposal_version": projection.proposal_version,
        "proposal_id": projection.proposal_id,
        "approval_id": projection.approval_id,
        "approval_revision": projection.approval_revision,
        "approval_revision_number": projection.approval_revision_number,
        "approval_kind": projection.approval_kind,
        "approval_state": projection.approval_state,
        "approval_authorizer_id": projection.approval_authorizer_id,
        "approval_decision_id": projection.approval_decision_id,
        "approval_decision_at": projection.approval_decision_at,
        "approval_expires_at": projection.approval_expires_at,
        "approval_supersedes_id": projection.approval_supersedes_id,
        "handoff_digest": projection.handoff_digest,
        "graph_digest": projection.graph_digest,
        "planning_result_digest": projection.planning_result_digest,
        "repository": projection.repository,
        "base_branch": projection.base_branch,
        "evaluated_repository_sha": projection.evaluated_repository_sha,
        "evaluator_commit_sha": projection.evaluator_commit_sha,
        "tested_repository_sha": projection.tested_repository_sha,
        "repository_evidence_type": projection.repository_evidence_type,
        "supplied_node_ids": list(projection.supplied_node_ids),
        "cohort_summaries": [
            {
                "node_ids": list(cohort.node_ids),
                "classification": cohort.classification,
                "reason_codes": list(cohort.reason_codes),
            }
            for cohort in projection.cohort_summaries
        ],
        "issueplan_current_state_evidence_id": (
            projection.issueplan_current_state_evidence_id
        ),
        "repository_state_evidence_id": projection.repository_state_evidence_id,
        "source_snapshot_fingerprint": projection.source_snapshot_fingerprint,
        "scanner_result_fingerprint": projection.scanner_result_fingerprint,
        "implementation_contract_fingerprint": (
            projection.implementation_contract_fingerprint
        ),
        "allowed_files": list(projection.allowed_files),
        "forbidden_paths": list(projection.forbidden_paths),
        "required_tests": list(projection.required_tests),
        "projected_at": projection.projected_at,
        "complete": True,
        "authoritative": False,
        "execution_authorized": False,
        "side_effects_performed": False,
    }


def _projection_id(payload: object) -> str:
    return f"approved-execution-projection:{hashlib.sha256(_canonical_bytes(payload)).hexdigest()}"


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _failure(
    status: str,
    reasons: tuple[str, ...],
    details: tuple[str, ...],
) -> ApprovedExecutionProjectionResult:
    return ApprovedExecutionProjectionResult(status, None, reasons, details)


def _cohorts(values: tuple[HandoffCohort, ...]) -> tuple[HandoffCohort, ...]:
    cohorts = tuple(values)
    if not cohorts or not all(isinstance(item, HandoffCohort) for item in cohorts):
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
    values: tuple[str, ...], name: str, *, allow_empty: bool
) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{name} must be a sequence")
    result = tuple(sorted(set(values)))
    if (not allow_empty and not result) or not all(
        isinstance(item, str) and item for item in result
    ):
        raise ValueError(f"{name} must contain non-empty strings")
    return result


def _reason_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError("reason_codes must be a sequence")
    result = tuple(sorted(set(values)))
    if not set(result) <= APPROVAL_INVALIDATION_REASON_CODES:
        raise ValueError("reason_codes must use the ratified vocabulary")
    return result


def _matches(value: object, pattern: re.Pattern[str], name: str) -> None:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{name} is malformed")


def _text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _sha40(value: object, name: str) -> None:
    _matches(value, _SHA40_RE, name)


def _sha256(value: object, name: str) -> None:
    _matches(value, _SHA256_RE, name)


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise ValueError(f"{name} must be an RFC3339 UTC timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid RFC3339 UTC timestamp") from exc


def _optional_timestamp(value: object, name: str) -> datetime | None:
    return None if value is None else _timestamp(value, name)


_PROJECTION_TRANSPORT_KEYS = frozenset(
    {
        "schema_version",
        "projection_id",
        "proposal_version",
        "proposal_id",
        "approval_id",
        "approval_revision",
        "approval_revision_number",
        "approval_kind",
        "approval_state",
        "approval_authorizer_id",
        "approval_decision_id",
        "approval_decision_at",
        "approval_expires_at",
        "approval_supersedes_id",
        "handoff_digest",
        "graph_digest",
        "planning_result_digest",
        "repository",
        "base_branch",
        "evaluated_repository_sha",
        "evaluator_commit_sha",
        "tested_repository_sha",
        "repository_evidence_type",
        "supplied_node_ids",
        "cohort_summaries",
        "issueplan_current_state_evidence_id",
        "repository_state_evidence_id",
        "source_snapshot_fingerprint",
        "scanner_result_fingerprint",
        "implementation_contract_fingerprint",
        "allowed_files",
        "forbidden_paths",
        "required_tests",
        "projected_at",
        "complete",
        "authoritative",
        "execution_authorized",
        "side_effects_performed",
    }
)
_PROJECTION_RESULT_TRANSPORT_KEYS = frozenset(
    {
        "status",
        "projection",
        "reason_codes",
        "details",
        "complete",
        "authoritative",
        "execution_authorized",
        "side_effects_performed",
    }
)


def reconstruct_approved_execution_projection(
    payload: bytes | str | dict[str, Any],
) -> ApprovedExecutionProjection:
    """Strictly reconstruct one projection and reverify its supplied identity."""

    raw = _decode_projection_transport_payload(payload, "approved execution projection")
    _require_projection_transport_keys(
        raw, _PROJECTION_TRANSPORT_KEYS, "approved execution projection"
    )
    if raw["complete"] is not True:
        raise ValueError("projection complete must be true")
    _require_projection_fixed_false(raw, "projection")
    if type(raw["approval_revision_number"]) is not int:
        raise ValueError("approval_revision_number must be an integer")
    supplied_node_ids = _projection_transport_string_array(
        raw["supplied_node_ids"], "supplied_node_ids"
    )
    allowed_files = _projection_transport_string_array(raw["allowed_files"], "allowed_files")
    forbidden_paths = _projection_transport_string_array(
        raw["forbidden_paths"], "forbidden_paths"
    )
    required_tests = _projection_transport_string_array(raw["required_tests"], "required_tests")
    cohorts_raw = raw["cohort_summaries"]
    if not isinstance(cohorts_raw, list):
        raise ValueError("cohort_summaries must be a JSON array")
    from .approval_records import _reconstruct_transport_cohort

    cohorts = tuple(_reconstruct_transport_cohort(item) for item in cohorts_raw)
    return ApprovedExecutionProjection(
        schema_version=raw["schema_version"],
        projection_id=raw["projection_id"],
        proposal_version=raw["proposal_version"],
        proposal_id=raw["proposal_id"],
        approval_id=raw["approval_id"],
        approval_revision=raw["approval_revision"],
        approval_revision_number=raw["approval_revision_number"],
        approval_kind=raw["approval_kind"],
        approval_state=raw["approval_state"],
        approval_authorizer_id=raw["approval_authorizer_id"],
        approval_decision_id=raw["approval_decision_id"],
        approval_decision_at=raw["approval_decision_at"],
        approval_expires_at=raw["approval_expires_at"],
        approval_supersedes_id=raw["approval_supersedes_id"],
        handoff_digest=raw["handoff_digest"],
        graph_digest=raw["graph_digest"],
        planning_result_digest=raw["planning_result_digest"],
        repository=raw["repository"],
        base_branch=raw["base_branch"],
        evaluated_repository_sha=raw["evaluated_repository_sha"],
        evaluator_commit_sha=raw["evaluator_commit_sha"],
        tested_repository_sha=raw["tested_repository_sha"],
        repository_evidence_type=raw["repository_evidence_type"],
        supplied_node_ids=supplied_node_ids,
        cohort_summaries=cohorts,
        issueplan_current_state_evidence_id=raw["issueplan_current_state_evidence_id"],
        repository_state_evidence_id=raw["repository_state_evidence_id"],
        source_snapshot_fingerprint=raw["source_snapshot_fingerprint"],
        scanner_result_fingerprint=raw["scanner_result_fingerprint"],
        implementation_contract_fingerprint=raw[
            "implementation_contract_fingerprint"
        ],
        allowed_files=allowed_files,
        forbidden_paths=forbidden_paths,
        required_tests=required_tests,
        projected_at=raw["projected_at"],
    )


def serialize_approved_execution_projection_result(
    result: ApprovedExecutionProjectionResult,
) -> bytes:
    """Serialize one fail-closed projection result as canonical JSON plus newline."""

    if not isinstance(result, ApprovedExecutionProjectionResult):
        raise TypeError("result must be ApprovedExecutionProjectionResult")
    projection_payload = (
        _projection_payload(_verified_projection(result.projection))
        if result.projection is not None
        else None
    )
    payload = {
        "status": result.status,
        "projection": projection_payload,
        "reason_codes": list(result.reason_codes),
        "details": list(result.details),
        "complete": result.complete,
        "authoritative": False,
        "execution_authorized": False,
        "side_effects_performed": False,
    }
    return _canonical_bytes(payload) + b"\n"


def reconstruct_approved_execution_projection_result(
    payload: bytes | str | dict[str, Any],
) -> ApprovedExecutionProjectionResult:
    """Strictly reconstruct one projection result without creating authority."""

    raw = _decode_projection_transport_payload(payload, "projection result")
    _require_projection_transport_keys(
        raw, _PROJECTION_RESULT_TRANSPORT_KEYS, "projection result"
    )
    _require_projection_fixed_false(raw, "projection result")
    if type(raw["complete"]) is not bool:
        raise ValueError("projection result complete must be a boolean")
    status = raw["status"]
    if status not in _RESULT_STATUSES:
        raise ValueError("unsupported projection result status")
    if raw["complete"] != (status == "complete"):
        raise ValueError("projection result complete must match status")
    reasons = _projection_transport_string_array(raw["reason_codes"], "reason_codes")
    details = _projection_transport_string_array(raw["details"], "details")
    projection_raw = raw["projection"]
    if status == "complete":
        if not isinstance(projection_raw, dict):
            raise ValueError("complete result requires one projection")
        if reasons:
            raise ValueError("complete result cannot carry reason codes")
        projection = reconstruct_approved_execution_projection(projection_raw)
    else:
        if projection_raw is not None:
            raise ValueError("non-complete result cannot carry a projection")
        if not reasons:
            raise ValueError("non-complete result requires reason codes")
        projection = None
    return ApprovedExecutionProjectionResult(status, projection, reasons, details)


def _decode_projection_transport_payload(
    payload: bytes | str | dict[str, Any], name: str
) -> dict[str, Any]:
    if isinstance(payload, dict):
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
    if not isinstance(decoded, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return decoded


def _require_projection_transport_keys(
    payload: dict[str, Any], expected: frozenset[str], name: str
) -> None:
    actual = set(payload)
    unknown = actual - expected
    missing = expected - actual
    if unknown:
        raise ValueError(f"{name} contains unknown fields: {sorted(unknown)}")
    if missing:
        raise ValueError(f"{name} is missing fields: {sorted(missing)}")


def _projection_transport_string_array(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must contain only strings")
    return tuple(value)


def _require_projection_fixed_false(payload: dict[str, Any], name: str) -> None:
    if payload["authoritative"] is not False:
        raise ValueError(f"{name} authoritative must be false")
    if payload["execution_authorized"] is not False:
        raise ValueError(f"{name} execution_authorized must be false")
    if payload["side_effects_performed"] is not False:
        raise ValueError(f"{name} side_effects_performed must be false")
