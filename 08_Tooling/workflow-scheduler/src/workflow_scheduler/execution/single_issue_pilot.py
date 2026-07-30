"""Pure-local WSC5 single-issue execution orchestration.

The orchestrator drives exactly one already-approved issue through one bounded
lifecycle using injected adapters. It performs no external I/O, opens no
network connection, spawns no subprocess, touches no clock, persists nothing,
enqueues nothing, starts no daemon, and never retries. It owns no Scheduler
runtime object and does not use the legacy mutable Scheduler executor as the
lifecycle owner.

All canonical evidence is supplied by the caller and reverified here through
the canonical public APIs (WSC4 projection consumption, IssuePlan current-state
comparison, approval applicability, and the GEX serializers and identity
functions). This module defines no competing projection, approval, repository
state, serializer, digest, reason-code, validation, executor framework, or
concurrency system.

One canonical lifecycle serves both supported execution modes. ``standard``
dispatches the approved executor exactly once and is unchanged. The additive
``validation-only`` mode reuses the same lease, workspace, cancellation,
validation, containment, cleanup, and release steps but dispatches no executor
at all, and records that absence truthfully instead of any synthetic process
observation.

Every terminal path is fail-closed: ``completed`` is returned only when every
success invariant is independently proven, and any unproven termination,
unresolved workspace, failed cleanup, or ambiguous release escalates to
``quarantined``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from scripts.agent_os_issue_acceptance import (
    ApprovalApplicabilityResult,
    ApprovalRecord,
    ApprovedExecutionProjection,
    IssuePlanCurrentStateEvidence,
    IssuePlanCurrentStateOutcome,
    compare_issueplan_current_state,
    evaluate_approval_applicability,
)
from scripts.agent_os_remote_validation.advisory_gate import (
    AdvisoryEvidenceResult,
    advisory_evidence_result_id,
    serialize_advisory_evidence_result,
)
from scripts.agent_os_remote_validation.advisory_render import (
    AdvisoryRenderResult,
    advisory_render_result_id,
    serialize_advisory_render_result,
)
from scripts.agent_os_remote_validation.evidence_bundle import (
    ValidationEvidenceBundle,
    serialize_validation_evidence_bundle,
    validation_evidence_bundle_id,
)
from scripts.agent_os_remote_validation.models import ValidationPlan
from scripts.agent_os_remote_validation.selector import (
    serialize_validation_plan,
    validation_plan_id,
)
from workflow_scheduler.planning.projection_consumer import (
    consume_approved_execution_projection,
)

SINGLE_ISSUE_PILOT_SCHEMA_NAME = "agent-os-wsc5-single-issue-pilot"
SINGLE_ISSUE_PILOT_SCHEMA_VERSION = "1.0"
SUPPORTED_PILOT_CONCURRENCY = 1

MAX_PILOT_STRING_LENGTH = 4096
MAX_PILOT_REASON_CODES = 64
MAX_PILOT_DETAILS = 64
MAX_PILOT_PATHS = 256
MAX_PILOT_TESTS = 64
MAX_PILOT_SERIALIZED_BYTES = 262_144

PilotStatus = Literal[
    "completed",
    "blocked",
    "stale",
    "cancelled",
    "timed-out",
    "failed",
    "quarantined",
    "needs-decision",
]

PilotPhase = Literal[
    "input-validation",
    "projection-consumption",
    "issueplan-revalidation",
    "approval-revalidation",
    "evidence-identity",
    "identity-cross-check",
    "pre-lease-cancellation",
    "lease-acquisition",
    "post-lease-cancellation",
    "workspace-creation",
    "workspace-inspection",
    "pre-execution-cancellation",
    "execution",
    "post-execution-path-check",
    "validation",
    "post-validation-path-check",
    "finalization",
]

ExecutorOutcome = Literal["succeeded", "failed", "cancelled", "timed-out"]

# The one canonical lifecycle runs in exactly one of two explicit modes.
# ``standard`` keeps the original behavior unchanged. ``validation-only``
# reuses every other step of the same lifecycle but dispatches no executor at
# all: no process is started, so there is no post-executor change evidence and
# no termination to confirm.
RuntimeExecutionMode = Literal["standard", "validation-only"]

STANDARD_EXECUTION_MODE: RuntimeExecutionMode = "standard"
VALIDATION_ONLY_EXECUTION_MODE: RuntimeExecutionMode = "validation-only"

RUNTIME_EXECUTION_MODES: frozenset[str] = frozenset(
    {STANDARD_EXECUTION_MODE, VALIDATION_ONLY_EXECUTION_MODE}
)

CancellationCheckpoint = Literal[
    "pre-lease",
    "post-lease",
    "post-workspace",
    "pre-executor",
]

PILOT_STATUSES: frozenset[str] = frozenset(
    {
        "completed",
        "blocked",
        "stale",
        "cancelled",
        "timed-out",
        "failed",
        "quarantined",
        "needs-decision",
    }
)

PILOT_REASON_CODES: frozenset[str] = frozenset(
    {
        "input.no-issue",
        "input.multiple-issues",
        "input.ambiguous",
        "input.concurrency-unsupported",
        "input.identity-missing",
        "contract.unsupported",
        "projection.rejected",
        "projection.stale",
        "projection.blocked",
        "projection.needs-decision",
        "issueplan.stale",
        "issueplan.blocked",
        "issueplan.invalid",
        "issueplan.needs-decision",
        "approval.not-applicable",
        "approval.stale",
        "approval.blocked",
        "approval.invalid",
        "approval.needs-decision",
        "evidence.plan-mismatch",
        "evidence.bundle-mismatch",
        "evidence.advisory-mismatch",
        "evidence.render-mismatch",
        "evidence.unsupported",
        "identity.repository-mismatch",
        "identity.base-branch-mismatch",
        "identity.base-sha-mismatch",
        "identity.source-head-sha-mismatch",
        "identity.tested-sha-mismatch",
        "identity.issue-mismatch",
        "identity.invocation-mismatch",
        "identity.allowed-files-mismatch",
        "identity.forbidden-paths-mismatch",
        "identity.required-tests-mismatch",
        "cancellation.requested",
        "cancellation.unconfirmed",
        "lease.duplicate-request",
        "lease.acquisition-failed",
        "lease.identity-mismatch",
        "lease.holder-drift",
        "lease.generation-drift",
        "lease.release-failed",
        "lease.release-ambiguous",
        "lease.release-forced",
        "workspace.creation-failed",
        "workspace.repository-mismatch",
        "workspace.branch-mismatch",
        "workspace.dirty",
        "workspace.detached",
        "workspace.reused",
        "workspace.missing",
        "workspace.prunable",
        "workspace.locked",
        "workspace.revision-mismatch",
        "workspace.unresolved",
        "workspace.filesystem-cleanup-failed",
        "workspace.metadata-cleanup-failed",
        "workspace.force-cleanup-forbidden",
        "executor.duplicate-dispatch",
        "executor.failed",
        "executor.exception",
        "executor.timeout",
        "executor.termination-unconfirmed",
        "executor.possible-partial-effects",
        "changed-paths.forbidden",
        "changed-paths.out-of-allowlist",
        "validation.failed",
        "validation.error",
        "validation.required-tests-missing",
        "pilot.unexpected-error",
    }
)

_EXPECTED_ADAPTER_EXCEPTIONS = (TypeError, ValueError, RuntimeError, OSError)


# --------------------------------------------------------------------------
# Deterministic identity helpers
# --------------------------------------------------------------------------


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _semantic_digest(domain: str, payload: object) -> str:
    return hashlib.sha256(
        f"{domain}:v1".encode("utf-8") + b"\0" + _canonical_bytes(payload)
    ).hexdigest()


def pilot_lease_identity(request: "PilotLeaseRequest") -> str:
    """Return the deterministic lease identity bound to every governed input."""
    return "pilot-lease:" + _semantic_digest(
        "agent-os-wsc5-pilot-lease",
        {
            "repository": request.repository,
            "issue_number": request.issue_number,
            "invocation_id": request.invocation_id,
            "branch": request.branch,
            "workspace_request_id": request.workspace_request_id,
            "projection_id": request.projection_id,
            "approval_id": request.approval_id,
            "source_head_sha": request.source_head_sha,
        },
    )


def pilot_holder_identity(request: "PilotLeaseRequest") -> str:
    """Return the deterministic single holder identity for one invocation."""
    return "pilot-holder:" + _semantic_digest(
        "agent-os-wsc5-pilot-holder",
        {
            "repository": request.repository,
            "issue_number": request.issue_number,
            "invocation_id": request.invocation_id,
        },
    )


def pilot_workspace_identity(request: "WorkspaceRequest") -> str:
    """Return the deterministic workspace request identity."""
    return "pilot-workspace:" + _semantic_digest(
        "agent-os-wsc5-pilot-workspace",
        {
            "repository": request.repository,
            "branch": request.branch,
            "expected_revision": request.expected_revision,
            "workspace_request_id": request.workspace_request_id,
        },
    )


# --------------------------------------------------------------------------
# Bounded terminal-result helpers
# --------------------------------------------------------------------------


def _bounded_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > MAX_PILOT_STRING_LENGTH:
        raise ValueError(f"{name} exceeds the bounded string length")
    return value


def _bounded_optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, name)


def _bounded_strings(values: object, name: str, *, maximum: int) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise TypeError(f"{name} must be an iterable of strings")
    items = tuple(str(item) for item in values)
    if len(items) > maximum:
        raise ValueError(f"{name} exceeds the bounded item count")
    for item in items:
        if not item or len(item) > MAX_PILOT_STRING_LENGTH:
            raise ValueError(f"{name} contains an unbounded or empty value")
    return items


def _bounded_reason_codes(values: object) -> tuple[str, ...]:
    codes = tuple(sorted(set(_bounded_strings(values, "reason_codes", maximum=MAX_PILOT_REASON_CODES))))
    unsupported = set(codes) - PILOT_REASON_CODES
    if unsupported:
        raise ValueError(f"unsupported pilot reason codes: {sorted(unsupported)}")
    return codes


def _bounded_details(values: object) -> tuple[str, ...]:
    return _bounded_strings(values, "details", maximum=MAX_PILOT_DETAILS)


# --------------------------------------------------------------------------
# Adapter request and observation records
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class PilotLeaseRequest:
    """One deterministic, fully bound request for a single pilot lease."""

    repository: str
    issue_number: int
    invocation_id: str
    branch: str
    workspace_request_id: str
    projection_id: str
    approval_id: str
    source_head_sha: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PilotLeaseGrant:
    """Observed result of one lease acquisition attempt."""

    acquired: bool
    lease_identity: str
    holder_identity: str
    generation: int
    reason: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class PilotLeaseReleaseObservation:
    """Observed result of one release attempt for one acquired holder."""

    released: bool
    lease_identity: str
    holder_identity: str
    generation: int
    ambiguous: bool = False
    forced: bool = False
    reason: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceRequest:
    """One request for a single bounded workspace."""

    workspace_request_id: str
    repository: str
    branch: str
    expected_revision: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceHandle:
    """Observed result of one workspace creation attempt."""

    created: bool
    workspace_identity: str
    reason: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceInspection:
    """Observed workspace state, reported as explicit independent facts."""

    resolved: bool
    repository: str
    branch: str
    expected_revision: str
    actual_revision: str
    clean: bool
    detached: bool
    reused: bool
    locked: bool
    locked_expected: bool = False
    missing: bool
    prunable: bool
    reason: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceCleanup:
    """Observed result of one workspace cleanup attempt.

    Filesystem removal and repository administrative-metadata removal are
    reported separately. Path absence alone is never treated as cleanup
    success, and a cleanup that required force is never a successful path.
    """

    filesystem_removed: bool
    metadata_removed: bool
    path_absent: bool = False
    force_required: bool = False
    reason: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class PilotExecutionRequest:
    """One bounded execution request for exactly one approved issue."""

    invocation_id: str
    repository: str
    issue_number: int
    branch: str
    workspace_identity: str
    source_head_sha: str
    allowed_files: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_tests: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class PilotExecutionObservation:
    """Observed executor result with termination evidence kept explicit."""

    outcome: ExecutorOutcome
    started: bool
    cancellation_requested: bool = False
    termination_confirmed: bool = False
    possible_partial_effects: bool = False
    changed_paths: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class PilotValidationRequest:
    """One bounded validation request bound to the verified plan identity."""

    invocation_id: str
    workspace_identity: str
    plan_id: str
    required_tests: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class PilotValidationObservation:
    """Observed validation result for one bounded validation attempt."""

    attempted: bool
    passed: bool
    completed_tests: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    reason: str = ""


# --------------------------------------------------------------------------
# Adapter protocols
# --------------------------------------------------------------------------


@runtime_checkable
class LeaseAdapter(Protocol):
    """Acquire and release exactly one deterministic pilot lease."""

    def acquire(self, request: PilotLeaseRequest) -> PilotLeaseGrant: ...

    def release(self, grant: PilotLeaseGrant) -> PilotLeaseReleaseObservation: ...


@runtime_checkable
class WorkspaceAdapter(Protocol):
    """Create, inspect, and clean up exactly one bounded workspace."""

    def create(self, request: WorkspaceRequest) -> WorkspaceHandle: ...

    def inspect(self, handle: WorkspaceHandle) -> WorkspaceInspection: ...

    def cleanup(self, handle: WorkspaceHandle) -> WorkspaceCleanup: ...


@runtime_checkable
class PilotExecutor(Protocol):
    """Run exactly one approved issue at most once."""

    def run(self, request: PilotExecutionRequest) -> PilotExecutionObservation: ...


@runtime_checkable
class ValidationAdapter(Protocol):
    """Run the required validation exactly once."""

    def validate(
        self, request: PilotValidationRequest
    ) -> PilotValidationObservation: ...


@runtime_checkable
class CancellationProbe(Protocol):
    """Report whether cancellation was requested at one named checkpoint."""

    def __call__(self, checkpoint: CancellationCheckpoint) -> bool: ...


# --------------------------------------------------------------------------
# Pilot input
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class SingleIssuePilotInput:
    """Immutable, fully supplied input for exactly one single-issue pilot."""

    schema_version: str = SINGLE_ISSUE_PILOT_SCHEMA_VERSION
    execution_mode: RuntimeExecutionMode = STANDARD_EXECUTION_MODE
    issue_numbers: tuple[int, ...]
    requested_concurrency: int
    repository: str
    base_branch: str
    base_sha: str
    source_head_sha: str
    tested_sha: str
    branch: str
    invocation_id: str
    workspace_request_id: str
    projection: object
    expected_projection_id: str
    expected_proposal_id: str
    expected_approval_id: str
    expected_issueplan_evidence: IssuePlanCurrentStateEvidence
    current_issueplan_evidence: IssuePlanCurrentStateEvidence
    approval_record: ApprovalRecord | None
    current_proposal: object
    repository_state_evidence: object
    evaluated_at: str
    validation_plan: ValidationPlan
    expected_plan_id: str
    evidence_bundle: ValidationEvidenceBundle
    expected_bundle_id: str
    advisory_result: AdvisoryEvidenceResult
    expected_advisory_result_id: str
    advisory_render: AdvisoryRenderResult
    expected_advisory_render_id: str
    allowed_files: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_tests: tuple[str, ...]
    invalidation_events: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.execution_mode not in RUNTIME_EXECUTION_MODES:
            raise ValueError("unsupported single-issue pilot execution mode")
        object.__setattr__(self, "issue_numbers", tuple(self.issue_numbers))
        object.__setattr__(
            self,
            "allowed_files",
            _bounded_strings(self.allowed_files, "allowed_files", maximum=MAX_PILOT_PATHS),
        )
        object.__setattr__(
            self,
            "forbidden_paths",
            _bounded_strings(
                self.forbidden_paths, "forbidden_paths", maximum=MAX_PILOT_PATHS
            ),
        )
        object.__setattr__(
            self,
            "required_tests",
            _bounded_strings(self.required_tests, "required_tests", maximum=MAX_PILOT_TESTS),
        )
        object.__setattr__(
            self,
            "invalidation_events",
            _bounded_strings(
                self.invalidation_events,
                "invalidation_events",
                maximum=MAX_PILOT_REASON_CODES,
            ),
        )


# --------------------------------------------------------------------------
# Pilot result
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class SingleIssuePilotResult:
    """Immutable, deterministic, non-authoritative single-issue pilot evidence."""

    schema_name: str
    schema_version: str
    execution_mode: RuntimeExecutionMode = STANDARD_EXECUTION_MODE
    result_id: str
    phase: PilotPhase
    primary_status: PilotStatus
    status: PilotStatus
    repository: str
    base_branch: str
    branch: str
    issue_numbers: tuple[int, ...]
    invocation_id: str
    base_sha: str
    source_head_sha: str
    tested_sha: str
    projection_id: str | None
    proposal_id: str | None
    approval_id: str | None
    approval_revision: str | None
    issueplan_evidence_id: str | None
    plan_id: str | None
    bundle_id: str | None
    advisory_result_id: str | None
    advisory_render_id: str | None
    lease_identity: str | None
    lease_holder_identity: str | None
    lease_generation: int | None
    lease_acquire_attempts: int
    lease_acquired: bool
    lease_release_attempts: int
    lease_released: bool
    workspace_identity: str | None
    workspace_create_attempts: int
    workspace_created: bool
    workspace_inspected: bool
    workspace_safe: bool
    workspace_cleanup_attempts: int
    workspace_filesystem_cleaned: bool
    workspace_metadata_cleaned: bool
    executor_dispatch_attempts: int
    executor_called: bool
    executor_started: bool
    cancellation_requested: bool
    termination_confirmed: bool
    possible_partial_effects: bool
    validation_attempts: int
    validation_attempted: bool
    validation_passed: bool
    changed_paths: tuple[str, ...]
    required_tests: tuple[str, ...]
    completed_tests: tuple[str, ...]
    reason_codes: tuple[str, ...]
    details: tuple[str, ...]
    primary_error: str | None
    cleanup_errors: tuple[str, ...]
    release_errors: tuple[str, ...]
    authoritative: Literal[False] = field(default=False, init=False)
    implementation_authorized: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    publication_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    attestation_verified: Literal[False] = field(default=False, init=False)
    side_effects_authorized: Literal[False] = field(default=False, init=False)
    retry_attempted: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != SINGLE_ISSUE_PILOT_SCHEMA_NAME:
            raise ValueError("unsupported single-issue pilot schema name")
        if self.schema_version != SINGLE_ISSUE_PILOT_SCHEMA_VERSION:
            raise ValueError("unsupported single-issue pilot schema version")
        if self.status not in PILOT_STATUSES or self.primary_status not in PILOT_STATUSES:
            raise ValueError("unsupported single-issue pilot status")
        object.__setattr__(self, "issue_numbers", tuple(self.issue_numbers))
        object.__setattr__(
            self,
            "changed_paths",
            _bounded_strings(self.changed_paths, "changed_paths", maximum=MAX_PILOT_PATHS),
        )
        object.__setattr__(
            self,
            "required_tests",
            _bounded_strings(self.required_tests, "required_tests", maximum=MAX_PILOT_TESTS),
        )
        object.__setattr__(
            self,
            "completed_tests",
            _bounded_strings(
                self.completed_tests, "completed_tests", maximum=MAX_PILOT_TESTS
            ),
        )
        object.__setattr__(self, "reason_codes", _bounded_reason_codes(self.reason_codes))
        object.__setattr__(self, "details", _bounded_details(self.details))
        object.__setattr__(
            self,
            "cleanup_errors",
            _bounded_strings(self.cleanup_errors, "cleanup_errors", maximum=MAX_PILOT_DETAILS),
        )
        object.__setattr__(
            self,
            "release_errors",
            _bounded_strings(self.release_errors, "release_errors", maximum=MAX_PILOT_DETAILS),
        )
        object.__setattr__(
            self, "primary_error", _bounded_optional_text(self.primary_error, "primary_error")
        )
        if self.executor_dispatch_attempts > 1:
            raise ValueError("the pilot executor may be dispatched at most once")
        if self.lease_acquire_attempts > 1:
            raise ValueError("the pilot lease may be acquired at most once")
        if self.lease_release_attempts > 1:
            raise ValueError("the pilot lease may be released at most once")
        if self.workspace_create_attempts > 1:
            raise ValueError("the pilot workspace may be created at most once")
        if self.workspace_cleanup_attempts > 1:
            raise ValueError("the pilot workspace may be cleaned up at most once")
        if self.validation_attempts > 1:
            raise ValueError("pilot validation may be attempted at most once")
        if self.status == "completed" and not _completed_invariants_hold(self):
            raise ValueError("completed requires every success invariant to be proven")


def serialize_single_issue_pilot_result(
    result: SingleIssuePilotResult,
) -> dict[str, object]:
    """Return verified JSON-compatible pilot evidence."""
    if not isinstance(result, SingleIssuePilotResult):
        raise TypeError("result must be SingleIssuePilotResult")
    payload = _result_payload(result)
    expected = "single-issue-pilot:" + _semantic_digest(
        SINGLE_ISSUE_PILOT_SCHEMA_NAME, payload
    )
    if result.result_id != expected:
        raise ValueError("single-issue pilot result ID mismatch")
    serialized = dict(payload)
    serialized["result_id"] = result.result_id
    if len(_canonical_bytes(serialized)) > MAX_PILOT_SERIALIZED_BYTES:
        raise ValueError("single-issue pilot result exceeds the canonical size limit")
    return serialized


def single_issue_pilot_result_id(result: SingleIssuePilotResult) -> str:
    """Return the verified domain-separated pilot result identity."""
    return str(serialize_single_issue_pilot_result(result)["result_id"])


def _result_payload(result: SingleIssuePilotResult) -> dict[str, object]:
    return {
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "execution_mode": result.execution_mode,
        "phase": result.phase,
        "primary_status": result.primary_status,
        "status": result.status,
        "repository": result.repository,
        "base_branch": result.base_branch,
        "branch": result.branch,
        "issue_numbers": list(result.issue_numbers),
        "invocation_id": result.invocation_id,
        "base_sha": result.base_sha,
        "source_head_sha": result.source_head_sha,
        "tested_sha": result.tested_sha,
        "projection_id": result.projection_id,
        "proposal_id": result.proposal_id,
        "approval_id": result.approval_id,
        "approval_revision": result.approval_revision,
        "issueplan_evidence_id": result.issueplan_evidence_id,
        "plan_id": result.plan_id,
        "bundle_id": result.bundle_id,
        "advisory_result_id": result.advisory_result_id,
        "advisory_render_id": result.advisory_render_id,
        "lease_identity": result.lease_identity,
        "lease_holder_identity": result.lease_holder_identity,
        "lease_generation": result.lease_generation,
        "lease_acquire_attempts": result.lease_acquire_attempts,
        "lease_acquired": result.lease_acquired,
        "lease_release_attempts": result.lease_release_attempts,
        "lease_released": result.lease_released,
        "workspace_identity": result.workspace_identity,
        "workspace_create_attempts": result.workspace_create_attempts,
        "workspace_created": result.workspace_created,
        "workspace_inspected": result.workspace_inspected,
        "workspace_safe": result.workspace_safe,
        "workspace_cleanup_attempts": result.workspace_cleanup_attempts,
        "workspace_filesystem_cleaned": result.workspace_filesystem_cleaned,
        "workspace_metadata_cleaned": result.workspace_metadata_cleaned,
        "executor_dispatch_attempts": result.executor_dispatch_attempts,
        "executor_called": result.executor_called,
        "executor_started": result.executor_started,
        "cancellation_requested": result.cancellation_requested,
        "termination_confirmed": result.termination_confirmed,
        "possible_partial_effects": result.possible_partial_effects,
        "validation_attempts": result.validation_attempts,
        "validation_attempted": result.validation_attempted,
        "validation_passed": result.validation_passed,
        "changed_paths": list(result.changed_paths),
        "required_tests": list(result.required_tests),
        "completed_tests": list(result.completed_tests),
        "reason_codes": list(result.reason_codes),
        "details": list(result.details),
        "primary_error": result.primary_error,
        "cleanup_errors": list(result.cleanup_errors),
        "release_errors": list(result.release_errors),
        "authoritative": False,
        "implementation_authorized": False,
        "execution_authorized": False,
        "publication_authorized": False,
        "merge_authorized": False,
        "attestation_verified": False,
        "side_effects_authorized": False,
        "retry_attempted": False,
    }


def _executor_completion_invariants_hold(result: SingleIssuePilotResult) -> bool:
    """Report whether the executor evidence proves completion for this mode.

    Standard completion still requires exactly one dispatched executor that
    started and whose termination was confirmed. Validation-only completion
    requires the opposite proof: nothing was dispatched, called, or started,
    and no termination was confirmed. An absent executor is explicit governed
    behavior, never a synthetic successful process observation, so a
    validation-only result claiming termination confirmation is not complete.
    """
    if result.execution_mode == VALIDATION_ONLY_EXECUTION_MODE:
        return (
            result.executor_dispatch_attempts == 0
            and not result.executor_called
            and not result.executor_started
            and not result.termination_confirmed
        )
    return (
        result.executor_dispatch_attempts == 1
        and result.executor_called
        and result.executor_started
        and result.termination_confirmed
    )


def _completed_invariants_hold(result: SingleIssuePilotResult) -> bool:
    return (
        result.primary_status == "completed"
        and len(result.issue_numbers) == 1
        # An unsupported mode is never a proven mode, so it never completes.
        and result.execution_mode in RUNTIME_EXECUTION_MODES
        and _executor_completion_invariants_hold(result)
        and not result.cancellation_requested
        and not result.possible_partial_effects
        and result.lease_acquired
        and result.lease_released
        and result.workspace_created
        and result.workspace_inspected
        and result.workspace_safe
        and result.workspace_filesystem_cleaned
        and result.workspace_metadata_cleaned
        and result.validation_attempted
        and result.validation_passed
        and result.validation_attempts == 1
        and not result.reason_codes
        and result.primary_error is None
        and not result.cleanup_errors
        and not result.release_errors
        # Completion proves every governed test ran, not that nothing else did:
        # a validator reporting an additional successful test is still a
        # complete run. Both tuples are bounded, and ``completed_tests`` is
        # rejected upstream if it repeats an entry, so set containment is a
        # deterministic comparison over bounded, order-independent evidence.
        and set(result.required_tests) <= set(result.completed_tests)
    )


# --------------------------------------------------------------------------
# Internal orchestration state
# --------------------------------------------------------------------------


class _PilotStop(Exception):
    """Internal control-flow signal ending the lifecycle at one phase."""


@dataclass
class _PilotState:
    """Mutable local accumulator; never returned and never shared."""

    pilot_input: SingleIssuePilotInput
    phase: PilotPhase = "input-validation"
    primary_status: PilotStatus = "completed"
    quarantined: bool = False
    reason_codes: set[str] = field(default_factory=set)
    details: list[str] = field(default_factory=list)
    primary_error: str | None = None
    cleanup_errors: list[str] = field(default_factory=list)
    release_errors: list[str] = field(default_factory=list)

    projection: ApprovedExecutionProjection | None = None
    projection_id: str | None = None
    proposal_id: str | None = None
    approval_id: str | None = None
    approval_revision: str | None = None
    issueplan_evidence_id: str | None = None
    plan_id: str | None = None
    bundle_id: str | None = None
    advisory_result_id: str | None = None
    advisory_render_id: str | None = None

    lease_request: PilotLeaseRequest | None = None
    lease_grant: PilotLeaseGrant | None = None
    lease_identity: str | None = None
    lease_holder_identity: str | None = None
    lease_generation: int | None = None
    lease_acquire_attempts: int = 0
    lease_acquired: bool = False
    lease_release_attempts: int = 0
    lease_released: bool = False

    workspace_handle: WorkspaceHandle | None = None
    workspace_identity: str | None = None
    workspace_create_attempts: int = 0
    workspace_created: bool = False
    workspace_inspected: bool = False
    workspace_safe: bool = False
    workspace_cleanup_attempts: int = 0
    workspace_filesystem_cleaned: bool = False
    workspace_metadata_cleaned: bool = False

    executor_dispatch_attempts: int = 0
    executor_called: bool = False
    executor_started: bool = False
    cancellation_requested: bool = False
    termination_confirmed: bool = False
    possible_partial_effects: bool = False

    validation_attempts: int = 0
    validation_attempted: bool = False
    validation_passed: bool = False
    changed_paths: tuple[str, ...] = ()
    completed_tests: tuple[str, ...] = ()

    def stop(
        self,
        status: PilotStatus,
        *,
        reasons: tuple[str, ...] = (),
        detail: str | None = None,
        error: str | None = None,
        quarantine: bool = False,
    ) -> _PilotStop:
        self.primary_status = status
        self.reason_codes.update(reasons)
        if detail is not None:
            self.details.append(detail)
        if error is not None and self.primary_error is None:
            self.primary_error = error
        if quarantine:
            self.quarantined = True
        return _PilotStop()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def run_single_issue_pilot(
    pilot_input: SingleIssuePilotInput,
    *,
    lease: LeaseAdapter,
    workspace: WorkspaceAdapter,
    executor: PilotExecutor | None = None,
    validator: ValidationAdapter,
    cancelled: CancellationProbe,
) -> SingleIssuePilotResult:
    """Run exactly one approved issue through one bounded, fail-closed lifecycle.

    ``pilot_input.execution_mode`` selects the mode of that one lifecycle. An
    absent executor is accepted only in validation-only mode, and an executor
    supplied in validation-only mode is refused before any adapter is touched:
    the mode never silently gains or loses execution authority.
    """
    if not isinstance(pilot_input, SingleIssuePilotInput):
        raise TypeError("pilot_input must be SingleIssuePilotInput")
    if pilot_input.execution_mode == VALIDATION_ONLY_EXECUTION_MODE:
        if executor is not None:
            raise TypeError("validation-only mode must not be given an executor")
    elif executor is None:
        raise TypeError("standard mode requires a pilot executor")

    state = _PilotState(pilot_input=pilot_input)
    lifecycle_hard_stop: BaseException | None = None
    teardown_hard_stop: BaseException | None = None
    try:
        try:
            _drive_lifecycle(
                state,
                lease_adapter=lease,
                workspace_adapter=workspace,
                executor=executor,
                validator=validator,
                cancelled=cancelled,
            )
        except _PilotStop:
            pass
        except Exception as exc:  # noqa: BLE001 - converted to fail-closed evidence
            # An unexpected error from a canonical API or a non-executor
            # adapter proves nothing, so it becomes deterministic quarantine
            # evidence rather than escaping past teardown.
            _record_unexpected_failure(state, exc)
        except BaseException as exc:
            # Process-level termination is never converted into evidence. It is
            # held so teardown still runs, then re-raised unchanged below.
            lifecycle_hard_stop = exc
            _record_hard_stop(state, exc)
    finally:
        # Teardown is reached on every exit path and attempts cleanup and
        # release independently of each other.
        teardown_hard_stop = _finalize(
            state, lease_adapter=lease, workspace_adapter=workspace
        )

    if lifecycle_hard_stop is not None:
        # The original termination always wins over a teardown termination.
        raise lifecycle_hard_stop
    if teardown_hard_stop is not None:
        raise teardown_hard_stop

    return _build_result(state)


def _record_unexpected_failure(state: _PilotState, exc: BaseException) -> None:
    """Convert an unexpected lifecycle error into fail-closed evidence."""
    state.primary_status = "quarantined"
    state.quarantined = True
    state.reason_codes.add("pilot.unexpected-error")
    state.details.append(f"{state.phase}:unexpected-error")
    if state.primary_error is None:
        state.primary_error = f"{type(exc).__name__}: {exc}"


def _record_hard_stop(state: _PilotState, exc: BaseException) -> None:
    """Record a process-level termination without turning it into an outcome."""
    state.quarantined = True
    state.reason_codes.add("pilot.unexpected-error")
    state.details.append(f"{state.phase}:process-terminated")
    if state.primary_error is None:
        state.primary_error = f"{type(exc).__name__}: {exc}"


def _drive_lifecycle(
    state: _PilotState,
    *,
    lease_adapter: LeaseAdapter,
    workspace_adapter: WorkspaceAdapter,
    executor: PilotExecutor | None,
    validator: ValidationAdapter,
    cancelled: CancellationProbe,
) -> None:
    _validate_input(state)
    _consume_projection(state)
    _revalidate_issueplan(state)
    _revalidate_approval(state)
    _verify_evidence_identity(state)
    _cross_check_identities(state)
    _check_cancellation(state, "pre-lease", "pre-lease-cancellation", cancelled)
    _acquire_lease(state, lease_adapter)
    _check_cancellation(state, "post-lease", "post-lease-cancellation", cancelled)
    _create_workspace(state, workspace_adapter)
    _inspect_workspace(state, workspace_adapter)
    _check_cancellation(state, "post-workspace", "workspace-inspection", cancelled)
    _check_cancellation(state, "pre-executor", "pre-execution-cancellation", cancelled)
    if state.pilot_input.execution_mode != VALIDATION_ONLY_EXECUTION_MODE:
        # Validation-only mode branches here and only here: no executor is
        # dispatched and no process is started, so there is also no
        # post-executor change evidence to contain. Every other step of this
        # one lifecycle -- lease, workspace, cancellation, validation,
        # post-validation containment, cleanup, and release -- is shared.
        assert executor is not None  # guaranteed by the entry-point mode check
        _dispatch_executor(state, executor)
        _check_changed_paths(state, "post-execution-path-check", state.changed_paths)
    _run_validation(state, validator)
    _check_changed_paths(state, "post-validation-path-check", state.changed_paths)


# --------------------------------------------------------------------------
# Lifecycle steps 1-3: input and identity validation
# --------------------------------------------------------------------------


def _validate_input(state: _PilotState) -> None:
    state.phase = "input-validation"
    supplied = state.pilot_input

    if supplied.schema_version != SINGLE_ISSUE_PILOT_SCHEMA_VERSION:
        raise state.stop(
            "needs-decision",
            reasons=("contract.unsupported",),
            detail="pilot-input:schema-version",
        )
    if supplied.execution_mode not in RUNTIME_EXECUTION_MODES:
        raise state.stop(
            "needs-decision",
            reasons=("contract.unsupported",),
            detail=f"pilot-input:execution-mode:{supplied.execution_mode!r}",
        )

    issues = supplied.issue_numbers
    if not issues:
        raise state.stop(
            "blocked", reasons=("input.no-issue",), detail="issue-numbers:empty"
        )
    if len(issues) > 1:
        raise state.stop(
            "blocked",
            reasons=("input.multiple-issues",),
            detail=f"issue-numbers:{len(issues)}",
        )
    issue = issues[0]
    if not isinstance(issue, int) or isinstance(issue, bool) or issue < 1:
        raise state.stop(
            "needs-decision",
            reasons=("input.ambiguous",),
            detail="issue-numbers:not-a-positive-integer",
        )

    if (
        not isinstance(supplied.requested_concurrency, int)
        or isinstance(supplied.requested_concurrency, bool)
        or supplied.requested_concurrency != SUPPORTED_PILOT_CONCURRENCY
    ):
        raise state.stop(
            "blocked",
            reasons=("input.concurrency-unsupported",),
            detail=f"requested-concurrency:{supplied.requested_concurrency!r}",
        )

    required_identities = (
        ("repository", supplied.repository),
        ("base_branch", supplied.base_branch),
        ("base_sha", supplied.base_sha),
        ("source_head_sha", supplied.source_head_sha),
        ("tested_sha", supplied.tested_sha),
        ("branch", supplied.branch),
        ("invocation_id", supplied.invocation_id),
        ("workspace_request_id", supplied.workspace_request_id),
        ("expected_projection_id", supplied.expected_projection_id),
        ("expected_proposal_id", supplied.expected_proposal_id),
        ("expected_approval_id", supplied.expected_approval_id),
        ("expected_plan_id", supplied.expected_plan_id),
        ("expected_bundle_id", supplied.expected_bundle_id),
        ("expected_advisory_result_id", supplied.expected_advisory_result_id),
        ("expected_advisory_render_id", supplied.expected_advisory_render_id),
        ("evaluated_at", supplied.evaluated_at),
    )
    missing = tuple(
        name
        for name, value in required_identities
        if not isinstance(value, str) or not value.strip()
    )
    if missing:
        raise state.stop(
            "needs-decision",
            reasons=("input.identity-missing",),
            detail=f"missing-identity:{','.join(missing)}",
        )
    if not supplied.required_tests:
        raise state.stop(
            "needs-decision",
            reasons=("input.identity-missing",),
            detail="missing-identity:required_tests",
        )


# --------------------------------------------------------------------------
# Lifecycle step 4: WSC4 approved-projection consumption
# --------------------------------------------------------------------------


def _consume_projection(state: _PilotState) -> None:
    state.phase = "projection-consumption"
    supplied = state.pilot_input

    consumption = consume_approved_execution_projection(
        supplied.projection,
        expected_repository=supplied.repository,
        expected_base_branch=supplied.base_branch,
        expected_evaluated_repository_sha=supplied.source_head_sha,
        expected_tested_repository_sha=supplied.tested_sha,
        expected_projection_id=supplied.expected_projection_id,
        expected_proposal_id=supplied.expected_proposal_id,
        expected_approval_id=supplied.expected_approval_id,
    )
    if consumption.status != "accepted" or consumption.projection is None:
        mapped: dict[str, tuple[PilotStatus, str]] = {
            "rejected": ("blocked", "projection.rejected"),
            "stale": ("stale", "projection.stale"),
            "blocked": ("blocked", "projection.blocked"),
            "needs-decision": ("needs-decision", "projection.needs-decision"),
        }
        status, reason = mapped[consumption.status]
        raise state.stop(
            status,
            reasons=(reason,),
            detail=f"projection-consumption:{consumption.status}",
            error="; ".join(consumption.reason_codes) or consumption.status,
        )

    projection = consumption.projection
    state.projection = projection
    state.projection_id = projection.projection_id
    state.proposal_id = projection.proposal_id
    state.approval_id = projection.approval_id
    state.approval_revision = projection.approval_revision


# --------------------------------------------------------------------------
# Lifecycle step 5: IssuePlan current-state revalidation
# --------------------------------------------------------------------------


def _revalidate_issueplan(state: _PilotState) -> None:
    state.phase = "issueplan-revalidation"
    supplied = state.pilot_input

    try:
        comparison = compare_issueplan_current_state(
            supplied.expected_issueplan_evidence,
            supplied.current_issueplan_evidence,
        )
    except (TypeError, ValueError) as exc:
        raise state.stop(
            "needs-decision",
            reasons=("issueplan.needs-decision",),
            detail="issueplan-comparison:unsupported",
            error=str(exc),
        ) from exc

    state.issueplan_evidence_id = comparison.current_evidence_id
    if comparison.outcome is IssuePlanCurrentStateOutcome.CURRENT:
        return

    mapped: dict[IssuePlanCurrentStateOutcome, tuple[PilotStatus, str]] = {
        IssuePlanCurrentStateOutcome.STALE: ("stale", "issueplan.stale"),
        IssuePlanCurrentStateOutcome.BLOCKED: ("blocked", "issueplan.blocked"),
        IssuePlanCurrentStateOutcome.INVALID: ("needs-decision", "issueplan.invalid"),
        IssuePlanCurrentStateOutcome.NEEDS_DECISION: (
            "needs-decision",
            "issueplan.needs-decision",
        ),
    }
    status, reason = mapped[comparison.outcome]
    raise state.stop(
        status,
        reasons=(reason,),
        detail=f"issueplan-current-state:{comparison.outcome.value}",
        error="; ".join(comparison.reason_codes) or comparison.outcome.value,
    )


# --------------------------------------------------------------------------
# Lifecycle step 6: approval applicability and invalidation
# --------------------------------------------------------------------------


def _revalidate_approval(state: _PilotState) -> None:
    state.phase = "approval-revalidation"
    supplied = state.pilot_input

    try:
        applicability = evaluate_approval_applicability(
            supplied.approval_record,
            supplied.current_proposal,
            supplied.current_issueplan_evidence,
            supplied.repository_state_evidence,
            evaluated_at=supplied.evaluated_at,
            invalidation_events=supplied.invalidation_events,
        )
    except (TypeError, ValueError) as exc:
        raise state.stop(
            "needs-decision",
            reasons=("approval.needs-decision",),
            detail="approval-applicability:unsupported",
            error=str(exc),
        ) from exc

    if not isinstance(applicability, ApprovalApplicabilityResult):
        raise state.stop(
            "needs-decision",
            reasons=("approval.needs-decision",),
            detail="approval-applicability:unsupported-type",
        )
    if applicability.status == "applicable" and applicability.approval_applicable:
        if applicability.approval_id != state.approval_id:
            raise state.stop(
                "blocked",
                reasons=("approval.not-applicable",),
                detail="approval-applicability:approval-id-mismatch",
            )
        if applicability.current_proposal_id != state.proposal_id:
            raise state.stop(
                "blocked",
                reasons=("approval.not-applicable",),
                detail="approval-applicability:proposal-id-mismatch",
            )
        return

    mapped: dict[str, tuple[PilotStatus, str]] = {
        "stale": ("stale", "approval.stale"),
        "blocked": ("blocked", "approval.blocked"),
        "invalid": ("needs-decision", "approval.invalid"),
        "needs-decision": ("needs-decision", "approval.needs-decision"),
    }
    status, reason = mapped.get(
        applicability.status, ("blocked", "approval.not-applicable")
    )
    raise state.stop(
        status,
        reasons=(reason,),
        detail=f"approval-applicability:{applicability.status}",
        error="; ".join(applicability.reason_codes) or applicability.status,
    )


# --------------------------------------------------------------------------
# Lifecycle step 7: canonical evidence serialization and identity
# --------------------------------------------------------------------------


def _verify_evidence_identity(state: _PilotState) -> None:
    state.phase = "evidence-identity"
    supplied = state.pilot_input

    # ``key`` is the serialized field carrying the canonical identity, or
    # ``None`` when the upstream serializer does not embed its own ID.
    checks: tuple[tuple[str, object, type, object, object, str | None, str], ...] = (
        (
            "plan",
            supplied.validation_plan,
            ValidationPlan,
            serialize_validation_plan,
            validation_plan_id,
            None,
            "evidence.plan-mismatch",
        ),
        (
            "bundle",
            supplied.evidence_bundle,
            ValidationEvidenceBundle,
            serialize_validation_evidence_bundle,
            validation_evidence_bundle_id,
            "bundle_id",
            "evidence.bundle-mismatch",
        ),
        (
            "advisory",
            supplied.advisory_result,
            AdvisoryEvidenceResult,
            serialize_advisory_evidence_result,
            advisory_evidence_result_id,
            "result_id",
            "evidence.advisory-mismatch",
        ),
        (
            "render",
            supplied.advisory_render,
            AdvisoryRenderResult,
            serialize_advisory_render_result,
            advisory_render_result_id,
            "render_id",
            "evidence.render-mismatch",
        ),
    )
    expected_ids = {
        "plan": supplied.expected_plan_id,
        "bundle": supplied.expected_bundle_id,
        "advisory": supplied.expected_advisory_result_id,
        "render": supplied.expected_advisory_render_id,
    }
    observed: dict[str, str] = {}

    for name, evidence, kind, serializer, identity, key, reason in checks:
        if not isinstance(evidence, kind):
            raise state.stop(
                "needs-decision",
                reasons=("evidence.unsupported",),
                detail=f"{name}-evidence:unsupported-type",
            )
        try:
            serialized = serializer(evidence)  # type: ignore[operator]
            computed = identity(evidence)  # type: ignore[operator]
        except (TypeError, ValueError) as exc:
            raise state.stop(
                "needs-decision",
                reasons=("evidence.unsupported",),
                detail=f"{name}-evidence:serialization-failed",
                error=str(exc),
            ) from exc
        embedded_mismatch = key is not None and serialized.get(key) != computed
        if embedded_mismatch or computed != expected_ids[name]:
            raise state.stop(
                "blocked",
                reasons=(reason,),
                detail=f"{name}-evidence:identity-mismatch",
            )
        observed[name] = str(computed)

    state.plan_id = observed["plan"]
    state.bundle_id = observed["bundle"]
    state.advisory_result_id = observed["advisory"]
    state.advisory_render_id = observed["render"]

    if supplied.advisory_render.advisory_result_id != state.advisory_result_id:
        raise state.stop(
            "blocked",
            reasons=("evidence.render-mismatch",),
            detail="render-evidence:advisory-binding-mismatch",
        )
    if supplied.advisory_result.bundle_id != state.bundle_id:
        raise state.stop(
            "blocked",
            reasons=("evidence.advisory-mismatch",),
            detail="advisory-evidence:bundle-binding-mismatch",
        )
    if supplied.advisory_result.plan_id != state.plan_id:
        raise state.stop(
            "blocked",
            reasons=("evidence.advisory-mismatch",),
            detail="advisory-evidence:plan-binding-mismatch",
        )
    if supplied.evidence_bundle.plan_id != state.plan_id:
        raise state.stop(
            "blocked",
            reasons=("evidence.bundle-mismatch",),
            detail="bundle-evidence:plan-binding-mismatch",
        )


# --------------------------------------------------------------------------
# Lifecycle step 8: full identity cross-check
# --------------------------------------------------------------------------


def _cross_check_identities(state: _PilotState) -> None:
    state.phase = "identity-cross-check"
    supplied = state.pilot_input
    projection = state.projection
    bundle = supplied.evidence_bundle
    advisory = supplied.advisory_result
    assert projection is not None  # guaranteed by accepted consumption

    issue = supplied.issue_numbers[0]
    expected_nodes = (f"issue-{issue}",)

    # A canonical ID proves an evidence object is internally intact, not that
    # it describes this repository. Every independently supplied canonical
    # object is therefore checked against the pilot repository.
    expected_repository = _normalized_repository(supplied.repository)
    repositories: tuple[tuple[str, object], ...] = (
        ("projection-repository", projection.repository),
        ("plan-repository", supplied.validation_plan.repository),
        ("bundle-repository", bundle.repository_identity),
        ("advisory-repository", advisory.repository_identity),
    )
    for name, observed in repositories:
        if _normalized_repository(observed) != expected_repository:
            raise state.stop(
                "blocked",
                reasons=("identity.repository-mismatch",),
                detail=f"cross-check:{name}",
            )

    comparisons: tuple[tuple[str, object, object, str], ...] = (
        ("repository", projection.repository, supplied.repository, "identity.repository-mismatch"),
        ("bundle-base-branch", bundle.base_branch, supplied.base_branch, "identity.base-branch-mismatch"),
        ("advisory-base-branch", advisory.base_branch, supplied.base_branch, "identity.base-branch-mismatch"),
        ("projection-base-branch", projection.base_branch, supplied.base_branch, "identity.base-branch-mismatch"),
        ("bundle-base-sha", bundle.base_sha, supplied.base_sha, "identity.base-sha-mismatch"),
        ("advisory-base-sha", advisory.base_sha, supplied.base_sha, "identity.base-sha-mismatch"),
        ("bundle-source-head-sha", bundle.source_head_sha, supplied.source_head_sha, "identity.source-head-sha-mismatch"),
        ("advisory-source-head-sha", advisory.source_head_sha, supplied.source_head_sha, "identity.source-head-sha-mismatch"),
        ("projection-source-head-sha", projection.evaluated_repository_sha, supplied.source_head_sha, "identity.source-head-sha-mismatch"),
        ("bundle-tested-sha", bundle.tested_sha, supplied.tested_sha, "identity.tested-sha-mismatch"),
        ("advisory-tested-sha", advisory.tested_sha, supplied.tested_sha, "identity.tested-sha-mismatch"),
        ("projection-tested-sha", projection.tested_repository_sha, supplied.tested_sha, "identity.tested-sha-mismatch"),
        ("projection-issue", tuple(projection.supplied_node_ids), expected_nodes, "identity.issue-mismatch"),
        ("issueplan-issue", tuple(supplied.current_issueplan_evidence.entity_ids), expected_nodes, "identity.issue-mismatch"),
        ("bundle-invocation", bundle.invocation_id, supplied.invocation_id, "identity.invocation-mismatch"),
        ("advisory-invocation", advisory.invocation_id, supplied.invocation_id, "identity.invocation-mismatch"),
        ("bundle-projection", bundle.projection_id, supplied.expected_projection_id, "identity.invocation-mismatch"),
        ("bundle-proposal", bundle.proposal_id, supplied.expected_proposal_id, "identity.invocation-mismatch"),
        ("bundle-approval", bundle.approval_id, supplied.expected_approval_id, "identity.invocation-mismatch"),
        ("allowed-files", tuple(projection.allowed_files), tuple(supplied.allowed_files), "identity.allowed-files-mismatch"),
        ("forbidden-paths", tuple(projection.forbidden_paths), tuple(supplied.forbidden_paths), "identity.forbidden-paths-mismatch"),
        ("required-tests", tuple(projection.required_tests), tuple(supplied.required_tests), "identity.required-tests-mismatch"),
    )
    for name, observed, expected, reason in comparisons:
        if observed != expected:
            raise state.stop(
                "blocked",
                reasons=(reason,),
                detail=f"cross-check:{name}",
            )


# --------------------------------------------------------------------------
# Cancellation checkpoints
# --------------------------------------------------------------------------


def _normalized_repository(value: object) -> str:
    """Return a comparable ``owner/repository`` key.

    Canonical evidence carries the repository either as a ``RepositoryIdentity``
    or as an ``owner/repository`` string, and GitHub treats both halves as
    case-insensitive, so both forms normalize to the same key.
    """
    owner = getattr(value, "owner", None)
    repository = getattr(value, "repository", None)
    if isinstance(owner, str) and isinstance(repository, str):
        return f"{owner}/{repository}".strip().lower()
    return str(value).strip().lower()


def _check_cancellation(
    state: _PilotState,
    checkpoint: CancellationCheckpoint,
    phase: PilotPhase,
    cancelled: CancellationProbe,
) -> None:
    state.phase = phase
    try:
        requested = bool(cancelled(checkpoint))
    except _EXPECTED_ADAPTER_EXCEPTIONS as exc:
        raise state.stop(
            "needs-decision",
            reasons=("cancellation.requested",),
            detail=f"cancellation-probe:{checkpoint}:error",
            error=str(exc),
        ) from exc
    if not requested:
        return
    state.cancellation_requested = True
    # Nothing has been dispatched at any of these checkpoints, so no execution
    # can be in flight; the denial is safe and terminates as cancelled.
    raise state.stop(
        "cancelled",
        reasons=("cancellation.requested",),
        detail=f"cancellation-requested:{checkpoint}",
    )


# --------------------------------------------------------------------------
# Lifecycle steps 10-12: lease acquisition and identity verification
# --------------------------------------------------------------------------


def _acquire_lease(state: _PilotState, lease_adapter: LeaseAdapter) -> None:
    state.phase = "lease-acquisition"
    supplied = state.pilot_input
    assert state.projection is not None

    if state.lease_acquire_attempts:
        raise state.stop(
            "quarantined",
            reasons=("lease.duplicate-request",),
            detail="lease:second-acquisition-refused",
            quarantine=True,
        )

    request = PilotLeaseRequest(
        repository=supplied.repository,
        issue_number=supplied.issue_numbers[0],
        invocation_id=supplied.invocation_id,
        branch=supplied.branch,
        workspace_request_id=supplied.workspace_request_id,
        projection_id=str(state.projection_id),
        approval_id=str(state.approval_id),
        source_head_sha=supplied.source_head_sha,
    )
    state.lease_request = request
    expected_identity = pilot_lease_identity(request)
    expected_holder = pilot_holder_identity(request)

    state.lease_acquire_attempts = 1
    try:
        grant = lease_adapter.acquire(request)
    except _EXPECTED_ADAPTER_EXCEPTIONS as exc:
        raise state.stop(
            "blocked",
            reasons=("lease.acquisition-failed",),
            detail="lease-acquire:error",
            error=str(exc),
        ) from exc

    if not isinstance(grant, PilotLeaseGrant):
        raise state.stop(
            "needs-decision",
            reasons=("lease.acquisition-failed",),
            detail="lease-acquire:unsupported-observation",
        )
    if not grant.acquired:
        raise state.stop(
            "blocked",
            reasons=("lease.acquisition-failed",),
            detail="lease-acquire:not-acquired",
            error=grant.reason or "lease not acquired",
        )

    state.lease_acquired = True
    state.lease_grant = grant
    state.lease_identity = grant.lease_identity
    state.lease_holder_identity = grant.holder_identity
    state.lease_generation = grant.generation

    if grant.lease_identity != expected_identity:
        raise state.stop(
            "quarantined",
            reasons=("lease.identity-mismatch",),
            detail="lease-acquire:identity-mismatch",
            quarantine=True,
        )
    if grant.holder_identity != expected_holder:
        raise state.stop(
            "quarantined",
            reasons=("lease.holder-drift",),
            detail="lease-acquire:holder-drift",
            quarantine=True,
        )
    if (
        not isinstance(grant.generation, int)
        or isinstance(grant.generation, bool)
        or grant.generation < 1
    ):
        raise state.stop(
            "quarantined",
            reasons=("lease.generation-drift",),
            detail="lease-acquire:generation-not-observable",
            quarantine=True,
        )


# --------------------------------------------------------------------------
# Lifecycle steps 13-14: workspace creation and inspection
# --------------------------------------------------------------------------


def _create_workspace(state: _PilotState, workspace_adapter: WorkspaceAdapter) -> None:
    state.phase = "workspace-creation"
    supplied = state.pilot_input

    if state.workspace_create_attempts:
        raise state.stop(
            "quarantined",
            reasons=("workspace.creation-failed",),
            detail="workspace:second-creation-refused",
            quarantine=True,
        )

    request = WorkspaceRequest(
        workspace_request_id=supplied.workspace_request_id,
        repository=supplied.repository,
        branch=supplied.branch,
        expected_revision=supplied.source_head_sha,
    )
    expected_identity = pilot_workspace_identity(request)

    state.workspace_create_attempts = 1
    try:
        handle = workspace_adapter.create(request)
    except _EXPECTED_ADAPTER_EXCEPTIONS as exc:
        raise state.stop(
            "blocked",
            reasons=("workspace.creation-failed",),
            detail="workspace-create:error",
            error=str(exc),
        ) from exc

    if not isinstance(handle, WorkspaceHandle):
        raise state.stop(
            "needs-decision",
            reasons=("workspace.creation-failed",),
            detail="workspace-create:unsupported-observation",
        )
    if not handle.created:
        raise state.stop(
            "blocked",
            reasons=("workspace.creation-failed",),
            detail="workspace-create:not-created",
            error=handle.reason or "workspace not created",
        )

    state.workspace_created = True
    state.workspace_handle = handle
    state.workspace_identity = handle.workspace_identity

    if handle.workspace_identity != expected_identity:
        raise state.stop(
            "blocked",
            reasons=("workspace.unresolved",),
            detail="workspace-create:identity-mismatch",
        )


def _inspect_workspace(state: _PilotState, workspace_adapter: WorkspaceAdapter) -> None:
    state.phase = "workspace-inspection"
    supplied = state.pilot_input
    handle = state.workspace_handle
    assert handle is not None

    try:
        inspection = workspace_adapter.inspect(handle)
    except _EXPECTED_ADAPTER_EXCEPTIONS as exc:
        raise state.stop(
            "blocked",
            reasons=("workspace.unresolved",),
            detail="workspace-inspect:error",
            error=str(exc),
        ) from exc

    if not isinstance(inspection, WorkspaceInspection):
        raise state.stop(
            "needs-decision",
            reasons=("workspace.unresolved",),
            detail="workspace-inspect:unsupported-observation",
        )
    state.workspace_inspected = True

    rejections: tuple[tuple[bool, str, str], ...] = (
        (not inspection.resolved, "workspace.unresolved", "unresolved"),
        (inspection.missing, "workspace.missing", "missing"),
        (inspection.prunable, "workspace.prunable", "prunable"),
        (inspection.reused, "workspace.reused", "reused"),
        (inspection.detached, "workspace.detached", "detached"),
        (not inspection.clean, "workspace.dirty", "dirty"),
        (
            inspection.locked and not inspection.locked_expected,
            "workspace.locked",
            "locked-unexpectedly",
        ),
        (
            inspection.repository != supplied.repository,
            "workspace.repository-mismatch",
            "repository-mismatch",
        ),
        (
            inspection.branch != supplied.branch,
            "workspace.branch-mismatch",
            "branch-mismatch",
        ),
        (
            inspection.expected_revision != supplied.source_head_sha
            or inspection.actual_revision != supplied.source_head_sha,
            "workspace.revision-mismatch",
            "revision-mismatch",
        ),
    )
    failures = tuple(
        (reason, label) for failed, reason, label in rejections if failed
    )
    if failures:
        raise state.stop(
            "blocked",
            reasons=tuple(reason for reason, _ in failures),
            detail="workspace-inspect:" + ",".join(label for _, label in failures),
            error=inspection.reason or "workspace state rejected",
        )
    state.workspace_safe = True


# --------------------------------------------------------------------------
# Lifecycle steps 16-17: bounded executor dispatch
# --------------------------------------------------------------------------


def _dispatch_executor(state: _PilotState, executor: PilotExecutor) -> None:
    state.phase = "execution"
    supplied = state.pilot_input
    handle = state.workspace_handle
    assert handle is not None

    if state.executor_dispatch_attempts:
        raise state.stop(
            "quarantined",
            reasons=("executor.duplicate-dispatch",),
            detail="executor:second-dispatch-refused",
            quarantine=True,
        )

    request = PilotExecutionRequest(
        invocation_id=supplied.invocation_id,
        repository=supplied.repository,
        issue_number=supplied.issue_numbers[0],
        branch=supplied.branch,
        workspace_identity=handle.workspace_identity,
        source_head_sha=supplied.source_head_sha,
        allowed_files=supplied.allowed_files,
        forbidden_paths=supplied.forbidden_paths,
        required_tests=supplied.required_tests,
    )

    state.executor_dispatch_attempts = 1
    state.executor_called = True
    try:
        observation = executor.run(request)
    except Exception as exc:  # noqa: BLE001 - unknown termination is unsafe
        # An ordinary executor exception proves nothing about termination or
        # effects, so it becomes fail-closed evidence.
        state.executor_started = True
        state.possible_partial_effects = True
        raise state.stop(
            "quarantined",
            reasons=(
                "executor.exception",
                "executor.termination-unconfirmed",
                "executor.possible-partial-effects",
            ),
            detail="executor-run:exception",
            error=f"{type(exc).__name__}: {exc}",
            quarantine=True,
        ) from exc
    except BaseException:
        # Process-level termination is not an outcome this orchestrator may
        # report. It is recorded as unsafe and then propagates to the outer
        # teardown boundary, which releases the lease and cleans the workspace
        # before re-raising it unchanged.
        state.executor_started = True
        state.possible_partial_effects = True
        raise

    if not isinstance(observation, PilotExecutionObservation):
        state.possible_partial_effects = True
        raise state.stop(
            "quarantined",
            reasons=("executor.termination-unconfirmed", "executor.possible-partial-effects"),
            detail="executor-run:unsupported-observation",
            quarantine=True,
        )

    state.executor_started = bool(observation.started)
    state.cancellation_requested = (
        state.cancellation_requested or bool(observation.cancellation_requested)
    )
    state.termination_confirmed = bool(observation.termination_confirmed)
    state.possible_partial_effects = bool(observation.possible_partial_effects)
    state.changed_paths = tuple(observation.changed_paths)

    if state.possible_partial_effects:
        raise state.stop(
            "quarantined",
            reasons=("executor.possible-partial-effects",),
            detail=f"executor-run:{observation.outcome}:possible-partial-effects",
            error=observation.reason or "possible partial effects",
            quarantine=True,
        )

    if observation.outcome == "timed-out":
        # A timeout is not proof that execution stopped.
        if not state.termination_confirmed:
            raise state.stop(
                "quarantined",
                reasons=("executor.timeout", "executor.termination-unconfirmed"),
                detail="executor-run:timed-out:termination-unconfirmed",
                error=observation.reason or "timeout without confirmed termination",
                quarantine=True,
            )
        raise state.stop(
            "timed-out",
            reasons=("executor.timeout",),
            detail="executor-run:timed-out:termination-confirmed",
            error=observation.reason or "timeout with confirmed termination",
        )

    if observation.outcome == "cancelled":
        # A cancellation request is not proof of termination.
        state.cancellation_requested = True
        if not state.termination_confirmed:
            raise state.stop(
                "quarantined",
                reasons=("cancellation.unconfirmed", "executor.termination-unconfirmed"),
                detail="executor-run:cancelled:termination-unconfirmed",
                error=observation.reason or "cancellation without confirmed termination",
                quarantine=True,
            )
        raise state.stop(
            "cancelled",
            reasons=("cancellation.requested",),
            detail="executor-run:cancelled:termination-confirmed",
        )

    if observation.outcome == "failed":
        if not state.termination_confirmed:
            raise state.stop(
                "quarantined",
                reasons=("executor.failed", "executor.termination-unconfirmed"),
                detail="executor-run:failed:termination-unconfirmed",
                error=observation.reason or "failure without confirmed termination",
                quarantine=True,
            )
        raise state.stop(
            "failed",
            reasons=("executor.failed",),
            detail="executor-run:failed",
            error=observation.reason or "executor reported failure",
        )

    if observation.outcome != "succeeded":
        raise state.stop(
            "needs-decision",
            reasons=("executor.termination-unconfirmed",),
            detail=f"executor-run:unsupported-outcome:{observation.outcome}",
            quarantine=True,
        )

    if not state.executor_started or not state.termination_confirmed:
        raise state.stop(
            "quarantined",
            reasons=("executor.termination-unconfirmed",),
            detail="executor-run:succeeded:termination-unconfirmed",
            quarantine=True,
        )
    if state.cancellation_requested:
        # A suppressed cancellation reported alongside success is never a
        # completed pilot.
        raise state.stop(
            "quarantined",
            reasons=("cancellation.unconfirmed",),
            detail="executor-run:succeeded:suppressed-cancellation",
            quarantine=True,
        )


# --------------------------------------------------------------------------
# Lifecycle steps 18 and 21: changed-path containment
# --------------------------------------------------------------------------


def _check_changed_paths(
    state: _PilotState, phase: PilotPhase, changed_paths: tuple[str, ...]
) -> None:
    state.phase = phase
    supplied = state.pilot_input

    forbidden = tuple(
        path for path in changed_paths if _matches_any(path, supplied.forbidden_paths)
    )
    if forbidden:
        raise state.stop(
            "quarantined",
            reasons=("changed-paths.forbidden",),
            detail=f"{phase}:forbidden:{','.join(sorted(forbidden))}",
            error="forbidden path written",
            quarantine=True,
        )
    outside = tuple(
        path for path in changed_paths if not _matches_any(path, supplied.allowed_files)
    )
    if outside:
        raise state.stop(
            "quarantined",
            reasons=("changed-paths.out-of-allowlist",),
            detail=f"{phase}:out-of-allowlist:{','.join(sorted(outside))}",
            error="path written outside the approved allowlist",
            quarantine=True,
        )


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if pattern == path:
            return True
        if pattern.endswith("/**") and path.startswith(pattern[:-2]):
            return True
        if pattern.endswith("*") and path.startswith(pattern[:-1]):
            return True
    return False


# --------------------------------------------------------------------------
# Lifecycle steps 19-20: bounded validation
# --------------------------------------------------------------------------


def _run_validation(state: _PilotState, validator: ValidationAdapter) -> None:
    state.phase = "validation"
    supplied = state.pilot_input
    handle = state.workspace_handle
    assert handle is not None

    if state.validation_attempts:
        raise state.stop(
            "quarantined",
            reasons=("validation.error",),
            detail="validation:second-attempt-refused",
            quarantine=True,
        )

    request = PilotValidationRequest(
        invocation_id=supplied.invocation_id,
        workspace_identity=handle.workspace_identity,
        plan_id=str(state.plan_id),
        required_tests=supplied.required_tests,
    )

    state.validation_attempts = 1
    try:
        observation = validator.validate(request)
    except _EXPECTED_ADAPTER_EXCEPTIONS as exc:
        raise state.stop(
            "failed",
            reasons=("validation.error",),
            detail="validation:error",
            error=str(exc),
        ) from exc

    if not isinstance(observation, PilotValidationObservation):
        raise state.stop(
            "needs-decision",
            reasons=("validation.error",),
            detail="validation:unsupported-observation",
        )

    state.validation_attempted = bool(observation.attempted)
    state.validation_passed = bool(observation.passed)

    # Bound the reported evidence here so an oversized, unbounded or duplicated
    # observation becomes a deterministic outcome instead of an exception
    # raised from result construction after teardown has already run.
    try:
        completed = _bounded_strings(
            observation.completed_tests, "completed_tests", maximum=MAX_PILOT_TESTS
        )
    except (TypeError, ValueError) as exc:
        raise state.stop(
            "needs-decision",
            reasons=("validation.error",),
            detail="validation:unbounded-completed-tests",
            error=str(exc),
        ) from exc
    if len(set(completed)) != len(completed):
        raise state.stop(
            "needs-decision",
            reasons=("validation.error",),
            detail="validation:duplicate-completed-tests",
            error="validation reported the same completed test more than once",
        )
    state.completed_tests = completed

    if observation.changed_paths:
        merged = tuple(
            dict.fromkeys((*state.changed_paths, *observation.changed_paths))
        )
        try:
            state.changed_paths = _bounded_strings(
                merged, "changed_paths", maximum=MAX_PILOT_PATHS
            )
        except (TypeError, ValueError) as exc:
            raise state.stop(
                "needs-decision",
                reasons=("validation.error",),
                detail="validation:unbounded-changed-paths",
                error=str(exc),
            ) from exc

    if not state.validation_attempted:
        raise state.stop(
            "failed",
            reasons=("validation.error",),
            detail="validation:not-attempted",
            error=observation.reason or "validation was not attempted",
        )
    if not state.validation_passed:
        raise state.stop(
            "failed",
            reasons=("validation.failed",),
            detail="validation:failed",
            error=observation.reason or "validation failed",
        )

    missing = tuple(
        test for test in supplied.required_tests if test not in state.completed_tests
    )
    if missing:
        raise state.stop(
            "failed",
            reasons=("validation.required-tests-missing",),
            detail="validation:missing-required-tests:" + ",".join(sorted(missing)),
            error="required tests did not complete",
        )


# --------------------------------------------------------------------------
# Lifecycle steps 22-24: exactly-once cleanup and release
# --------------------------------------------------------------------------


def _finalize(
    state: _PilotState,
    *,
    lease_adapter: LeaseAdapter,
    workspace_adapter: WorkspaceAdapter,
) -> BaseException | None:
    """Attempt cleanup once and release once, preserving the primary outcome.

    Cleanup and release are attempted independently: a failure of either --
    including a process-level ``BaseException`` -- never prevents the other
    from being attempted. Both attempts are counted before their adapter call,
    so a teardown error still leaves each attempted exactly once and can never
    replace the primary error.

    Returns the first process-level termination raised by teardown, if any, so
    the caller can re-raise it once the original lifecycle termination has been
    given priority.
    """
    before = len(state.cleanup_errors) + len(state.release_errors)
    hard_stop: BaseException | None = None
    try:
        _cleanup_workspace(state, workspace_adapter)
    except Exception as exc:  # noqa: BLE001 - teardown must not mask the outcome
        state.cleanup_errors.append(
            f"workspace-cleanup:unexpected-error:{type(exc).__name__}: {exc}"
        )
        state.reason_codes.add("workspace.filesystem-cleanup-failed")
        state.quarantined = True
    except BaseException as exc:
        state.cleanup_errors.append(
            f"workspace-cleanup:process-terminated:{type(exc).__name__}: {exc}"
        )
        state.reason_codes.add("workspace.filesystem-cleanup-failed")
        state.quarantined = True
        hard_stop = exc
    try:
        _release_lease(state, lease_adapter)
    except Exception as exc:  # noqa: BLE001 - teardown must not mask the outcome
        state.release_errors.append(
            f"lease-release:unexpected-error:{type(exc).__name__}: {exc}"
        )
        state.reason_codes.add("lease.release-ambiguous")
        state.quarantined = True
    except BaseException as exc:
        state.release_errors.append(
            f"lease-release:process-terminated:{type(exc).__name__}: {exc}"
        )
        state.reason_codes.add("lease.release-ambiguous")
        state.quarantined = True
        if hard_stop is None:
            hard_stop = exc
    if len(state.cleanup_errors) + len(state.release_errors) != before:
        # Only finalization itself degraded the outcome; otherwise the phase
        # keeps recording where the primary outcome was determined.
        state.phase = "finalization"
    return hard_stop


def _cleanup_workspace(state: _PilotState, workspace_adapter: WorkspaceAdapter) -> None:
    handle = state.workspace_handle
    if handle is None or not state.workspace_created or state.workspace_cleanup_attempts:
        return

    state.workspace_cleanup_attempts = 1
    try:
        cleanup = workspace_adapter.cleanup(handle)
    except _EXPECTED_ADAPTER_EXCEPTIONS as exc:
        state.cleanup_errors.append(f"workspace-cleanup:error:{exc}")
        state.reason_codes.add("workspace.filesystem-cleanup-failed")
        state.quarantined = True
        return

    if not isinstance(cleanup, WorkspaceCleanup):
        state.cleanup_errors.append("workspace-cleanup:unsupported-observation")
        state.reason_codes.add("workspace.filesystem-cleanup-failed")
        state.quarantined = True
        return

    if cleanup.force_required:
        # Forced cleanup is never a successful path.
        state.cleanup_errors.append("workspace-cleanup:force-required")
        state.reason_codes.add("workspace.force-cleanup-forbidden")
        state.quarantined = True
        return

    state.workspace_filesystem_cleaned = bool(cleanup.filesystem_removed)
    state.workspace_metadata_cleaned = bool(cleanup.metadata_removed)

    if not state.workspace_filesystem_cleaned:
        # Path absence alone is not cleanup success.
        state.cleanup_errors.append(
            "workspace-cleanup:filesystem-not-removed"
            + (":path-absent" if cleanup.path_absent else "")
            + (f":{cleanup.reason}" if cleanup.reason else "")
        )
        state.reason_codes.add("workspace.filesystem-cleanup-failed")
        state.quarantined = True
    if not state.workspace_metadata_cleaned:
        state.cleanup_errors.append(
            "workspace-cleanup:metadata-not-removed"
            + (f":{cleanup.reason}" if cleanup.reason else "")
        )
        state.reason_codes.add("workspace.metadata-cleanup-failed")
        state.quarantined = True


def _release_lease(state: _PilotState, lease_adapter: LeaseAdapter) -> None:
    grant = state.lease_grant
    if grant is None or not state.lease_acquired or state.lease_release_attempts:
        return

    state.lease_release_attempts = 1
    try:
        release = lease_adapter.release(grant)
    except _EXPECTED_ADAPTER_EXCEPTIONS as exc:
        state.release_errors.append(f"lease-release:error:{exc}")
        state.reason_codes.add("lease.release-failed")
        state.quarantined = True
        return

    if not isinstance(release, PilotLeaseReleaseObservation):
        state.release_errors.append("lease-release:unsupported-observation")
        state.reason_codes.add("lease.release-ambiguous")
        state.quarantined = True
        return

    if release.forced:
        # Forced release is never a successful path.
        state.release_errors.append("lease-release:forced")
        state.reason_codes.add("lease.release-forced")
        state.quarantined = True
        return
    if release.ambiguous:
        state.release_errors.append(
            "lease-release:ambiguous" + (f":{release.reason}" if release.reason else "")
        )
        state.reason_codes.add("lease.release-ambiguous")
        state.quarantined = True
        return
    if release.lease_identity != grant.lease_identity:
        state.release_errors.append("lease-release:identity-mismatch")
        state.reason_codes.add("lease.release-ambiguous")
        state.quarantined = True
        return
    if release.holder_identity != grant.holder_identity:
        state.release_errors.append("lease-release:holder-drift")
        state.reason_codes.add("lease.holder-drift")
        state.quarantined = True
        return
    if release.generation != grant.generation:
        state.release_errors.append("lease-release:generation-drift")
        state.reason_codes.add("lease.generation-drift")
        state.quarantined = True
        return
    if not release.released:
        state.release_errors.append(
            "lease-release:not-released" + (f":{release.reason}" if release.reason else "")
        )
        state.reason_codes.add("lease.release-failed")
        state.quarantined = True
        return

    state.lease_released = True


# --------------------------------------------------------------------------
# Lifecycle step 25: status precedence and immutable result construction
# --------------------------------------------------------------------------


def _side_effects_were_possible(state: _PilotState) -> bool:
    """Report whether the run ever reached a side-effect-capable phase.

    A lease or workspace that exists, an executor that was called, possible
    partial effects, uncertain termination, or a failed teardown all mean the
    run left something behind that a human has to look at.
    """
    return (
        state.lease_acquired
        or state.workspace_created
        or state.executor_called
        or state.possible_partial_effects
        or (state.cancellation_requested and not state.termination_confirmed)
        or bool(state.cleanup_errors)
        or bool(state.release_errors)
    )


def _final_status(state: _PilotState) -> PilotStatus:
    """Apply the governed status precedence.

    ``primary_status`` is preserved independently and always reported. Once a
    side-effect-capable phase has been reached, ``quarantined`` dominates every
    other final status, including ``needs-decision`` and ``stale`` -- a later
    cleanup or release failure must never be reported as a decision request. A
    pre-execution ``needs-decision`` or ``stale`` outcome that acquired no
    lease, no workspace, and never dispatched the executor is decided before
    anything could be left behind, so it is kept unchanged.
    """
    if state.quarantined and _side_effects_were_possible(state):
        return "quarantined"
    if state.primary_status == "needs-decision":
        return "needs-decision"
    if state.primary_status == "stale":
        return "stale"
    if state.quarantined:
        return "quarantined"
    return state.primary_status


def _build_result(state: _PilotState) -> SingleIssuePilotResult:
    supplied = state.pilot_input
    status = _final_status(state)

    fields: dict[str, object] = {
        "schema_name": SINGLE_ISSUE_PILOT_SCHEMA_NAME,
        "schema_version": SINGLE_ISSUE_PILOT_SCHEMA_VERSION,
        "execution_mode": supplied.execution_mode,
        "result_id": "",
        "phase": state.phase,
        "primary_status": state.primary_status,
        "status": status,
        "repository": supplied.repository,
        "base_branch": supplied.base_branch,
        "branch": supplied.branch,
        "issue_numbers": supplied.issue_numbers,
        "invocation_id": supplied.invocation_id,
        "base_sha": supplied.base_sha,
        "source_head_sha": supplied.source_head_sha,
        "tested_sha": supplied.tested_sha,
        "projection_id": state.projection_id,
        "proposal_id": state.proposal_id,
        "approval_id": state.approval_id,
        "approval_revision": state.approval_revision,
        "issueplan_evidence_id": state.issueplan_evidence_id,
        "plan_id": state.plan_id,
        "bundle_id": state.bundle_id,
        "advisory_result_id": state.advisory_result_id,
        "advisory_render_id": state.advisory_render_id,
        "lease_identity": state.lease_identity,
        "lease_holder_identity": state.lease_holder_identity,
        "lease_generation": state.lease_generation,
        "lease_acquire_attempts": state.lease_acquire_attempts,
        "lease_acquired": state.lease_acquired,
        "lease_release_attempts": state.lease_release_attempts,
        "lease_released": state.lease_released,
        "workspace_identity": state.workspace_identity,
        "workspace_create_attempts": state.workspace_create_attempts,
        "workspace_created": state.workspace_created,
        "workspace_inspected": state.workspace_inspected,
        "workspace_safe": state.workspace_safe,
        "workspace_cleanup_attempts": state.workspace_cleanup_attempts,
        "workspace_filesystem_cleaned": state.workspace_filesystem_cleaned,
        "workspace_metadata_cleaned": state.workspace_metadata_cleaned,
        "executor_dispatch_attempts": state.executor_dispatch_attempts,
        "executor_called": state.executor_called,
        "executor_started": state.executor_started,
        "cancellation_requested": state.cancellation_requested,
        "termination_confirmed": state.termination_confirmed,
        "possible_partial_effects": state.possible_partial_effects,
        "validation_attempts": state.validation_attempts,
        "validation_attempted": state.validation_attempted,
        "validation_passed": state.validation_passed,
        "changed_paths": state.changed_paths,
        "required_tests": supplied.required_tests,
        "completed_tests": state.completed_tests,
        "reason_codes": tuple(sorted(state.reason_codes)),
        "details": tuple(state.details),
        "primary_error": state.primary_error,
        "cleanup_errors": tuple(state.cleanup_errors),
        "release_errors": tuple(state.release_errors),
    }
    preliminary = SingleIssuePilotResult(**fields)  # type: ignore[arg-type]
    result_id = "single-issue-pilot:" + _semantic_digest(
        SINGLE_ISSUE_PILOT_SCHEMA_NAME, _result_payload(preliminary)
    )
    fields["result_id"] = result_id
    return SingleIssuePilotResult(**fields)  # type: ignore[arg-type]
