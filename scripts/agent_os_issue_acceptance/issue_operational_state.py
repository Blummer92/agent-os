"""Pure-local canonical operational-state projection for one Agent OS issue.

The projection consumes supplied evidence only. It does not read GitHub, mutate
repository state, execute work, or create authorization. Existing IssuePlan,
approval, merge-authorization, and lifecycle-mutation records remain the
sources of the projected meanings represented here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from .approval_records import ApprovalApplicabilityResult
from .lifecycle_mutation_guard import AdmissionStatus, LifecycleMutationAdmissionResult
from .merge_authorization import MergeAuthorizationApplicabilityResult

ISSUE_OPERATIONAL_STATE_SCHEMA_NAME = "agent-os-issue-operational-state"
ISSUE_OPERATIONAL_STATE_SCHEMA_VERSION = "1.0"
MAX_EVIDENCE_IDS = 64
MAX_PRIMARY_CLAIMS = 8
MAX_LABELS = 64
MAX_REASON_CODES = 64
MAX_SERIALIZED_BYTES = 32 * 1024

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}:[0-9a-f]{64}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/ -]{0,127}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class OperationalOutcome(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs-decision"
    STALE = "stale"
    CONFLICTING = "conflicting"
    TERMINAL = "terminal"
    INVALID = "invalid"


class SourceState(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"
    CONFLICTING = "conflicting"


class IssueState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class LifecycleStage(str, Enum):
    PLANNING = "planning"
    IMPLEMENTATION = "implementation"
    DRAFT_PR = "draft-pr"
    REVIEW = "review"
    MERGED = "merged"
    CLOSED = "closed"


class TerminalDisposition(str, Enum):
    NONE = "none"
    COMPLETED = "completed"
    NOT_PLANNED = "not-planned"
    DUPLICATE = "duplicate"


class ReadinessState(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs-decision"
    TERMINAL = "terminal"


class AuthorizationState(str, Enum):
    AUTHORIZED = "authorized"
    NOT_AUTHORIZED = "not-authorized"
    STALE = "stale"
    NEEDS_DECISION = "needs-decision"
    NOT_APPLICABLE = "not-applicable"


class DependencyState(str, Enum):
    CLEAR = "clear"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class ClaimState(str, Enum):
    NONE = "none"
    SINGLE = "single"
    CONFLICTING = "conflicting"


class PrimaryPrState(str, Enum):
    NONE = "none"
    DRAFT = "draft"
    READY = "ready"
    MERGED = "merged"
    CONFLICTING = "conflicting"


class ValidationState(str, Enum):
    NOT_RUN = "not-run"
    PASSED = "passed"
    FAILED = "failed"
    PENDING = "pending"
    STALE = "stale"


class FreshnessState(str, Enum):
    CURRENT = "current"
    STALE = "stale"


REASON_CODES = frozenset(
    {
        "source.partial",
        "source.missing",
        "source.unsupported",
        "source.conflicting",
        "source.stale",
        "contract.readiness-blocked",
        "contract.readiness-needs-decision",
        "contract.readiness-terminal",
        "authorization.implementation-not-authorized",
        "authorization.implementation-stale",
        "authorization.implementation-needs-decision",
        "authorization.ready-for-review-not-authorized",
        "authorization.ready-for-review-stale",
        "authorization.ready-for-review-needs-decision",
        "authorization.execution-not-authorized",
        "authorization.execution-stale",
        "authorization.execution-needs-decision",
        "authorization.merge-not-authorized",
        "authorization.merge-stale",
        "authorization.merge-needs-decision",
        "authorization.closure-not-authorized",
        "authorization.closure-stale",
        "authorization.closure-needs-decision",
        "authorization.external-write-not-authorized",
        "authorization.external-write-stale",
        "authorization.external-write-needs-decision",
        "dependency.blocked",
        "dependency.unknown",
        "claim.multiple-primary",
        "validation.failed",
        "validation.pending",
        "validation.stale",
        "lifecycle.closed",
        "lifecycle.terminal-disposition",
        "lifecycle.stage-conflict",
        "reconciliation.closed-with-ready-label",
        "reconciliation.merged-pr-open-issue",
    }
)

_AUTHORITY_FIELDS = (
    "implementation_authorization",
    "ready_for_review_authorization",
    "execution_authorization",
    "merge_authorization",
    "closure_authorization",
    "external_write_authorization",
)
_AUTHORITY_REASON_PREFIX = {
    "implementation_authorization": "authorization.implementation",
    "ready_for_review_authorization": "authorization.ready-for-review",
    "execution_authorization": "authorization.execution",
    "merge_authorization": "authorization.merge",
    "closure_authorization": "authorization.closure",
    "external_write_authorization": "authorization.external-write",
}


def _exact_text(value: object, name: str, maximum: int = 4096) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a built-in string")
    if not value or len(value.encode("utf-8")) > maximum or _CONTROL_RE.search(value):
        raise ValueError(f"{name} is outside bounds")
    return value


def _repository(value: object) -> str:
    text = _exact_text(value, "repository", 255)
    if not _REPOSITORY_RE.fullmatch(text):
        raise ValueError("repository is malformed")
    return text


def _sha40(value: object, name: str) -> str:
    text = _exact_text(value, name, 40)
    if not _SHA40_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase 40-character SHA")
    return text


def _optional_sha40(value: object, name: str) -> str | None:
    return None if value is None else _sha40(value, name)


def _timestamp(value: object) -> str:
    text = _exact_text(value, "observed_at", 20)
    if not _TIMESTAMP_RE.fullmatch(text):
        raise ValueError("observed_at must use YYYY-MM-DDTHH:MM:SSZ")
    return text


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise TypeError(f"{name} must be a positive built-in integer")
    return value


def _enum(value: object, enum_type: type[Enum], name: str) -> Enum:
    if not isinstance(value, enum_type):
        raise TypeError(f"{name} must be {enum_type.__name__}")
    return value


def _canonical_strings(
    values: object,
    *,
    name: str,
    maximum: int,
    pattern: re.Pattern[str] | None = None,
) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    if len(values) > maximum:
        raise ValueError(f"{name} exceeds its bound")
    checked = tuple(_exact_text(value, name, 512) for value in values)
    if len(set(checked)) != len(checked):
        raise ValueError(f"{name} contains duplicates")
    if pattern is not None and any(not pattern.fullmatch(item) for item in checked):
        raise ValueError(f"{name} contains a malformed value")
    return tuple(sorted(checked))


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _state_id(payload: object) -> str:
    material = b"agent-os-issue-operational-state:v1\0" + _canonical_json(payload).encode(
        "utf-8"
    )
    return f"issue-operational-state:{hashlib.sha256(material).hexdigest()}"


def _strict_keys(payload: dict[str, Any], expected: frozenset[str], name: str) -> None:
    unknown = set(payload) - expected
    missing = expected - set(payload)
    if unknown:
        raise ValueError(f"{name} contains unknown fields: {sorted(unknown)}")
    if missing:
        raise ValueError(f"{name} is missing fields: {sorted(missing)}")


@dataclass(frozen=True, slots=True)
class AuthorityProjection:
    state: AuthorizationState
    evidence_id: str | None = None
    bound_base_sha: str | None = None
    observed_base_sha: str | None = None

    def __post_init__(self) -> None:
        _enum(self.state, AuthorizationState, "authority state")
        if self.evidence_id is not None:
            evidence_id = _exact_text(self.evidence_id, "authority evidence_id", 128)
            if not _SHA256_ID_RE.fullmatch(evidence_id):
                raise ValueError("authority evidence_id is malformed")
        if self.state in {
            AuthorizationState.AUTHORIZED,
            AuthorizationState.STALE,
        } and self.evidence_id is None:
            raise ValueError(f"{self.state.value} authority requires evidence_id")
        _optional_sha40(self.bound_base_sha, "bound_base_sha")
        _optional_sha40(self.observed_base_sha, "observed_base_sha")
        if (self.bound_base_sha is None) != (self.observed_base_sha is None):
            raise ValueError("authority SHA binding requires both bound and observed SHA")

    def effective(self) -> AuthorityProjection:
        if (
            self.state is AuthorizationState.AUTHORIZED
            and self.bound_base_sha is not None
            and self.bound_base_sha != self.observed_base_sha
        ):
            return AuthorityProjection(
                state=AuthorizationState.STALE,
                evidence_id=self.evidence_id,
                bound_base_sha=self.bound_base_sha,
                observed_base_sha=self.observed_base_sha,
            )
        return self

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "evidence_id": self.evidence_id,
            "bound_base_sha": self.bound_base_sha,
            "observed_base_sha": self.observed_base_sha,
        }

    @classmethod
    def from_approval_applicability(
        cls, result: ApprovalApplicabilityResult
    ) -> AuthorityProjection:
        """Project an existing approval applicability result without re-evaluating it."""

        if type(result) is not ApprovalApplicabilityResult:
            raise TypeError("result must be an exact ApprovalApplicabilityResult")
        state = {
            "applicable": AuthorizationState.AUTHORIZED,
            "stale": AuthorizationState.STALE,
            "needs-decision": AuthorizationState.NEEDS_DECISION,
            "blocked": AuthorizationState.NOT_AUTHORIZED,
            "invalid": AuthorizationState.NOT_AUTHORIZED,
        }[result.status]
        return cls(
            state=state,
            evidence_id=result.approval_revision or result.approval_id,
        )

    @classmethod
    def from_merge_authorization_applicability(
        cls, result: MergeAuthorizationApplicabilityResult
    ) -> AuthorityProjection:
        """Project the canonical merge-authorization applicability result."""

        if type(result) is not MergeAuthorizationApplicabilityResult:
            raise TypeError(
                "result must be an exact MergeAuthorizationApplicabilityResult"
            )
        state = {
            "applicable": AuthorizationState.AUTHORIZED,
            "stale": AuthorizationState.STALE,
            "needs-decision": AuthorizationState.NEEDS_DECISION,
            "blocked": AuthorizationState.NOT_AUTHORIZED,
            "invalid": AuthorizationState.NOT_AUTHORIZED,
            "consumed": AuthorizationState.NOT_AUTHORIZED,
        }[result.status]
        return cls(
            state=state,
            evidence_id=result.authorization_revision or result.authorization_id,
        )

    @classmethod
    def from_lifecycle_admission(
        cls, result: LifecycleMutationAdmissionResult
    ) -> AuthorityProjection:
        """Project one canonical lifecycle-mutation admission result."""

        if type(result) is not LifecycleMutationAdmissionResult:
            raise TypeError(
                "result must be an exact LifecycleMutationAdmissionResult"
            )
        state = {
            AdmissionStatus.ADMITTED: AuthorizationState.AUTHORIZED,
            AdmissionStatus.STALE: AuthorizationState.STALE,
            AdmissionStatus.BLOCKED: AuthorizationState.NOT_AUTHORIZED,
            AdmissionStatus.INVALID: AuthorizationState.NOT_AUTHORIZED,
        }[result.status]
        return cls(state=state, evidence_id=result.result_id)

    @classmethod
    def from_dict(cls, payload: object) -> AuthorityProjection:
        if type(payload) is not dict:
            raise TypeError("authority projection must be an exact object")
        _strict_keys(
            payload,
            frozenset(
                {"state", "evidence_id", "bound_base_sha", "observed_base_sha"}
            ),
            "authority projection",
        )
        try:
            state = AuthorizationState(payload["state"])
        except (TypeError, ValueError) as exc:
            raise ValueError("authority projection state is unsupported") from exc
        return cls(
            state=state,
            evidence_id=payload["evidence_id"],
            bound_base_sha=payload["bound_base_sha"],
            observed_base_sha=payload["observed_base_sha"],
        )


@dataclass(frozen=True, slots=True)
class PrimaryIssueClaim:
    pull_request_number: int
    branch: str
    head_sha: str
    state: Literal["draft", "ready", "merged"]
    claim_id: str = ""

    def __post_init__(self) -> None:
        _positive_int(self.pull_request_number, "pull_request_number")
        branch = _exact_text(self.branch, "branch", 255)
        if not _BRANCH_RE.fullmatch(branch) or branch == "main":
            raise ValueError("branch is malformed or protected")
        _sha40(self.head_sha, "head_sha")
        if self.state not in {"draft", "ready", "merged"}:
            raise ValueError("primary claim state is unsupported")
        expected = f"issue-primary-claim:{hashlib.sha256(_canonical_json(self._payload()).encode('utf-8')).hexdigest()}"
        if self.claim_id and self.claim_id != expected:
            raise ValueError("claim_id does not match primary claim content")
        object.__setattr__(self, "claim_id", expected)

    def _payload(self) -> dict[str, object]:
        return {
            "pull_request_number": self.pull_request_number,
            "branch": self.branch,
            "head_sha": self.head_sha,
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class IssueOperationalEvidence:
    repository: str
    issue_number: int
    source_revision: str
    observed_at: str
    evidence_ids: tuple[str, ...]
    source_state: SourceState
    issue_state: IssueState
    lifecycle_stage: LifecycleStage
    terminal_disposition: TerminalDisposition
    readiness: ReadinessState
    implementation_authorization: AuthorityProjection
    ready_for_review_authorization: AuthorityProjection
    execution_authorization: AuthorityProjection
    merge_authorization: AuthorityProjection
    closure_authorization: AuthorityProjection
    external_write_authorization: AuthorityProjection
    dependency_state: DependencyState
    primary_claims: tuple[PrimaryIssueClaim, ...]
    validation_state: ValidationState
    freshness_state: FreshnessState
    observed_labels: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _repository(self.repository)
        _positive_int(self.issue_number, "issue_number")
        _sha40(self.source_revision, "source_revision")
        _timestamp(self.observed_at)
        object.__setattr__(
            self,
            "evidence_ids",
            _canonical_strings(
                self.evidence_ids,
                name="evidence_ids",
                maximum=MAX_EVIDENCE_IDS,
                pattern=_SHA256_ID_RE,
            ),
        )
        for name, enum_type in (
            ("source_state", SourceState),
            ("issue_state", IssueState),
            ("lifecycle_stage", LifecycleStage),
            ("terminal_disposition", TerminalDisposition),
            ("readiness", ReadinessState),
            ("dependency_state", DependencyState),
            ("validation_state", ValidationState),
            ("freshness_state", FreshnessState),
        ):
            _enum(getattr(self, name), enum_type, name)
        for name in _AUTHORITY_FIELDS:
            if not isinstance(getattr(self, name), AuthorityProjection):
                raise TypeError(f"{name} must be AuthorityProjection")
        if type(self.primary_claims) is not tuple:
            raise TypeError("primary_claims must be an exact tuple")
        if len(self.primary_claims) > MAX_PRIMARY_CLAIMS:
            raise ValueError("primary_claims exceeds its bound")
        if any(type(item) is not PrimaryIssueClaim for item in self.primary_claims):
            raise TypeError("primary_claims must contain exact PrimaryIssueClaim values")
        claims = tuple(sorted(self.primary_claims, key=lambda item: item.pull_request_number))
        if len({item.pull_request_number for item in claims}) != len(claims):
            raise ValueError("primary_claims contains duplicate pull request numbers")
        object.__setattr__(self, "primary_claims", claims)
        object.__setattr__(
            self,
            "observed_labels",
            _canonical_strings(
                self.observed_labels,
                name="observed_labels",
                maximum=MAX_LABELS,
                pattern=_LABEL_RE,
            ),
        )


@dataclass(frozen=True, slots=True)
class IssueOperationalState:
    schema_name: Literal["agent-os-issue-operational-state"]
    schema_version: Literal["1.0"]
    repository: str
    issue_number: int
    source_revision: str
    observed_at: str
    evidence_ids: tuple[str, ...]
    primary_claim_ids: tuple[str, ...]
    outcome: OperationalOutcome
    issue_state: IssueState
    lifecycle_stage: LifecycleStage
    terminal_disposition: TerminalDisposition
    readiness: ReadinessState
    implementation_authorization: AuthorityProjection
    ready_for_review_authorization: AuthorityProjection
    execution_authorization: AuthorityProjection
    merge_authorization: AuthorityProjection
    closure_authorization: AuthorityProjection
    external_write_authorization: AuthorityProjection
    dependency_state: DependencyState
    claim_state: ClaimState
    active_branch: str | None
    primary_pr_numbers: tuple[int, ...]
    primary_pr_state: PrimaryPrState
    validation_state: ValidationState
    freshness_state: FreshnessState
    reconciliation_required: bool
    blocker_codes: tuple[str, ...]
    reason_codes: tuple[str, ...]
    state_id: str = ""
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != ISSUE_OPERATIONAL_STATE_SCHEMA_NAME or self.schema_version != ISSUE_OPERATIONAL_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported issue operational state schema")
        _repository(self.repository)
        _positive_int(self.issue_number, "issue_number")
        _sha40(self.source_revision, "source_revision")
        _timestamp(self.observed_at)
        object.__setattr__(
            self,
            "evidence_ids",
            _canonical_strings(
                self.evidence_ids,
                name="evidence_ids",
                maximum=MAX_EVIDENCE_IDS,
                pattern=_SHA256_ID_RE,
            ),
        )
        object.__setattr__(
            self,
            "primary_claim_ids",
            _canonical_strings(
                self.primary_claim_ids,
                name="primary_claim_ids",
                maximum=MAX_PRIMARY_CLAIMS,
                pattern=_SHA256_ID_RE,
            ),
        )
        for name, enum_type in (
            ("outcome", OperationalOutcome),
            ("issue_state", IssueState),
            ("lifecycle_stage", LifecycleStage),
            ("terminal_disposition", TerminalDisposition),
            ("readiness", ReadinessState),
            ("dependency_state", DependencyState),
            ("claim_state", ClaimState),
            ("primary_pr_state", PrimaryPrState),
            ("validation_state", ValidationState),
            ("freshness_state", FreshnessState),
        ):
            _enum(getattr(self, name), enum_type, name)
        for name in _AUTHORITY_FIELDS:
            if not isinstance(getattr(self, name), AuthorityProjection):
                raise TypeError(f"{name} must be AuthorityProjection")
        if self.active_branch is not None:
            branch = _exact_text(self.active_branch, "active_branch", 255)
            if not _BRANCH_RE.fullmatch(branch):
                raise ValueError("active_branch is malformed")
        if type(self.primary_pr_numbers) is not tuple:
            raise TypeError("primary_pr_numbers must be an exact tuple")
        if any(type(value) is not int or value < 1 for value in self.primary_pr_numbers):
            raise TypeError("primary_pr_numbers must contain positive integers")
        if tuple(sorted(set(self.primary_pr_numbers))) != self.primary_pr_numbers:
            raise ValueError("primary_pr_numbers must be sorted and unique")
        if type(self.reconciliation_required) is not bool:
            raise TypeError("reconciliation_required must be a built-in bool")
        blockers = _reason_tuple(self.blocker_codes, "blocker_codes")
        reasons = _reason_tuple(self.reason_codes, "reason_codes")
        if not set(blockers) <= set(reasons):
            raise ValueError("blocker_codes must be a subset of reason_codes")
        object.__setattr__(self, "blocker_codes", blockers)
        object.__setattr__(self, "reason_codes", reasons)
        if self.side_effects_performed is not False:
            raise ValueError("operational state cannot record side effects")
        expected = _state_id(self._payload())
        if self.state_id and self.state_id != expected:
            raise ValueError("state_id does not match issue operational state content")
        object.__setattr__(self, "state_id", expected)
        if len(_canonical_json(self.to_dict()).encode("utf-8")) > MAX_SERIALIZED_BYTES:
            raise ValueError("issue operational state exceeds serialized bound")

    def _payload(self) -> dict[str, object]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "source_revision": self.source_revision,
            "observed_at": self.observed_at,
            "evidence_ids": list(self.evidence_ids),
            "primary_claim_ids": list(self.primary_claim_ids),
            "outcome": self.outcome.value,
            "issue_state": self.issue_state.value,
            "lifecycle_stage": self.lifecycle_stage.value,
            "terminal_disposition": self.terminal_disposition.value,
            "readiness": self.readiness.value,
            "implementation_authorization": self.implementation_authorization.to_dict(),
            "ready_for_review_authorization": self.ready_for_review_authorization.to_dict(),
            "execution_authorization": self.execution_authorization.to_dict(),
            "merge_authorization": self.merge_authorization.to_dict(),
            "closure_authorization": self.closure_authorization.to_dict(),
            "external_write_authorization": self.external_write_authorization.to_dict(),
            "dependency_state": self.dependency_state.value,
            "claim_state": self.claim_state.value,
            "active_branch": self.active_branch,
            "primary_pr_numbers": list(self.primary_pr_numbers),
            "primary_pr_state": self.primary_pr_state.value,
            "validation_state": self.validation_state.value,
            "freshness_state": self.freshness_state.value,
            "reconciliation_required": self.reconciliation_required,
            "blocker_codes": list(self.blocker_codes),
            "reason_codes": list(self.reason_codes),
            "side_effects_performed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "state_id": self.state_id}


def _reason_tuple(values: object, name: str) -> tuple[str, ...]:
    checked = _canonical_strings(values, name=name, maximum=MAX_REASON_CODES)
    if any(value not in REASON_CODES for value in checked):
        raise ValueError(f"{name} contains an unsupported reason code")
    return checked


def _authority_reason(name: str, state: AuthorizationState) -> str | None:
    if state in {AuthorizationState.AUTHORIZED, AuthorizationState.NOT_APPLICABLE}:
        return None
    suffix = {
        AuthorizationState.NOT_AUTHORIZED: "not-authorized",
        AuthorizationState.STALE: "stale",
        AuthorizationState.NEEDS_DECISION: "needs-decision",
    }[state]
    return f"{_AUTHORITY_REASON_PREFIX[name]}-{suffix}"


def build_issue_operational_state(
    evidence: IssueOperationalEvidence,
) -> IssueOperationalState:
    """Build one deterministic, authority-preserving operational projection."""

    if type(evidence) is not IssueOperationalEvidence:
        raise TypeError("evidence must be an exact IssueOperationalEvidence")

    reasons: set[str] = set()
    blockers: set[str] = set()
    authorities = {
        name: getattr(evidence, name).effective() for name in _AUTHORITY_FIELDS
    }
    for name, authority in authorities.items():
        reason = _authority_reason(name, authority.state)
        if reason is not None:
            reasons.add(reason)
            blockers.add(reason)

    if evidence.source_state is SourceState.PARTIAL:
        reasons.add("source.partial")
        blockers.add("source.partial")
    elif evidence.source_state is SourceState.MISSING:
        reasons.add("source.missing")
        blockers.add("source.missing")
    elif evidence.source_state is SourceState.UNSUPPORTED:
        reasons.add("source.unsupported")
        blockers.add("source.unsupported")
    elif evidence.source_state is SourceState.CONFLICTING:
        reasons.add("source.conflicting")
        blockers.add("source.conflicting")

    if evidence.freshness_state is FreshnessState.STALE:
        reasons.add("source.stale")
        blockers.add("source.stale")

    if evidence.readiness is ReadinessState.BLOCKED:
        reasons.add("contract.readiness-blocked")
        blockers.add("contract.readiness-blocked")
    elif evidence.readiness is ReadinessState.NEEDS_DECISION:
        reasons.add("contract.readiness-needs-decision")
        blockers.add("contract.readiness-needs-decision")
    elif evidence.readiness is ReadinessState.TERMINAL:
        reasons.add("contract.readiness-terminal")
        blockers.add("contract.readiness-terminal")

    if evidence.dependency_state is DependencyState.BLOCKED:
        reasons.add("dependency.blocked")
        blockers.add("dependency.blocked")
    elif evidence.dependency_state is DependencyState.UNKNOWN:
        reasons.add("dependency.unknown")
        blockers.add("dependency.unknown")

    if evidence.validation_state is ValidationState.FAILED:
        reasons.add("validation.failed")
        blockers.add("validation.failed")
    elif evidence.validation_state is ValidationState.PENDING:
        reasons.add("validation.pending")
        blockers.add("validation.pending")
    elif evidence.validation_state is ValidationState.STALE:
        reasons.add("validation.stale")
        blockers.add("validation.stale")

    claims = evidence.primary_claims
    primary_pr_numbers = tuple(item.pull_request_number for item in claims)
    primary_claim_ids = tuple(item.claim_id for item in claims)
    reconciliation_required = False
    if not claims:
        claim_state = ClaimState.NONE
        active_branch = None
        primary_pr_state = PrimaryPrState.NONE
    elif len(claims) == 1:
        claim = claims[0]
        claim_state = ClaimState.SINGLE
        active_branch = claim.branch
        primary_pr_state = PrimaryPrState(claim.state)
        if claim.state == "merged" and evidence.issue_state is IssueState.OPEN:
            reconciliation_required = True
            reasons.add("reconciliation.merged-pr-open-issue")
            blockers.add("reconciliation.merged-pr-open-issue")
    else:
        claim_state = ClaimState.CONFLICTING
        active_branch = None
        primary_pr_state = PrimaryPrState.CONFLICTING
        reconciliation_required = True
        reasons.add("claim.multiple-primary")
        blockers.add("claim.multiple-primary")

    terminal = (
        evidence.issue_state is IssueState.CLOSED
        or evidence.terminal_disposition is not TerminalDisposition.NONE
    )
    if evidence.issue_state is IssueState.CLOSED:
        reasons.add("lifecycle.closed")
        if "status:ready" in evidence.observed_labels:
            reconciliation_required = True
            reasons.add("reconciliation.closed-with-ready-label")
            blockers.add("reconciliation.closed-with-ready-label")
    if evidence.terminal_disposition is not TerminalDisposition.NONE:
        reasons.add("lifecycle.terminal-disposition")
    if evidence.issue_state is IssueState.CLOSED and evidence.lifecycle_stage is not LifecycleStage.CLOSED:
        reasons.add("lifecycle.stage-conflict")
        reconciliation_required = True
    if evidence.lifecycle_stage is LifecycleStage.MERGED and evidence.issue_state is IssueState.OPEN:
        reconciliation_required = True
        reasons.add("reconciliation.merged-pr-open-issue")
        blockers.add("reconciliation.merged-pr-open-issue")

    implementation_state = authorities["implementation_authorization"].state
    any_stale_authority = any(
        authority.state is AuthorizationState.STALE for authority in authorities.values()
    )

    if evidence.source_state is SourceState.UNSUPPORTED:
        outcome = OperationalOutcome.INVALID
    elif evidence.source_state is SourceState.CONFLICTING or claim_state is ClaimState.CONFLICTING:
        outcome = OperationalOutcome.CONFLICTING
    elif terminal:
        outcome = OperationalOutcome.TERMINAL
    elif (
        evidence.freshness_state is FreshnessState.STALE
        or any_stale_authority
        or evidence.validation_state is ValidationState.STALE
    ):
        outcome = OperationalOutcome.STALE
    elif (
        evidence.readiness is ReadinessState.BLOCKED
        or evidence.dependency_state is DependencyState.BLOCKED
        or evidence.validation_state is ValidationState.FAILED
        or implementation_state is AuthorizationState.NOT_AUTHORIZED
    ):
        outcome = OperationalOutcome.BLOCKED
    elif (
        evidence.source_state in {SourceState.PARTIAL, SourceState.MISSING}
        or evidence.readiness is ReadinessState.NEEDS_DECISION
        or evidence.dependency_state is DependencyState.UNKNOWN
        or evidence.validation_state is ValidationState.PENDING
        or implementation_state is AuthorizationState.NEEDS_DECISION
        or reconciliation_required
    ):
        outcome = OperationalOutcome.NEEDS_DECISION
    elif evidence.readiness is ReadinessState.READY and implementation_state is AuthorizationState.AUTHORIZED:
        outcome = OperationalOutcome.READY
    else:
        outcome = OperationalOutcome.BLOCKED

    return IssueOperationalState(
        schema_name=ISSUE_OPERATIONAL_STATE_SCHEMA_NAME,
        schema_version=ISSUE_OPERATIONAL_STATE_SCHEMA_VERSION,
        repository=evidence.repository,
        issue_number=evidence.issue_number,
        source_revision=evidence.source_revision,
        observed_at=evidence.observed_at,
        evidence_ids=evidence.evidence_ids,
        primary_claim_ids=primary_claim_ids,
        outcome=outcome,
        issue_state=evidence.issue_state,
        lifecycle_stage=evidence.lifecycle_stage,
        terminal_disposition=evidence.terminal_disposition,
        readiness=evidence.readiness,
        implementation_authorization=authorities["implementation_authorization"],
        ready_for_review_authorization=authorities["ready_for_review_authorization"],
        execution_authorization=authorities["execution_authorization"],
        merge_authorization=authorities["merge_authorization"],
        closure_authorization=authorities["closure_authorization"],
        external_write_authorization=authorities["external_write_authorization"],
        dependency_state=evidence.dependency_state,
        claim_state=claim_state,
        active_branch=active_branch,
        primary_pr_numbers=primary_pr_numbers,
        primary_pr_state=primary_pr_state,
        validation_state=evidence.validation_state,
        freshness_state=evidence.freshness_state,
        reconciliation_required=reconciliation_required,
        blocker_codes=tuple(blockers),
        reason_codes=tuple(reasons),
    )


def serialize_issue_operational_state(state: IssueOperationalState) -> str:
    if type(state) is not IssueOperationalState:
        raise TypeError("state must be an exact IssueOperationalState")
    return _canonical_json(state.to_dict())


def deserialize_issue_operational_state(serialized: object) -> IssueOperationalState:
    if type(serialized) is not str:
        raise TypeError("serialized state must be a built-in string")
    if len(serialized.encode("utf-8")) > MAX_SERIALIZED_BYTES:
        raise ValueError("serialized state exceeds its bound")
    try:
        payload = json.loads(serialized)
    except json.JSONDecodeError as exc:
        raise ValueError("serialized state is not valid JSON") from exc
    if type(payload) is not dict:
        raise TypeError("serialized state must contain an exact JSON object")

    expected = frozenset(
        {
            "schema_name",
            "schema_version",
            "repository",
            "issue_number",
            "source_revision",
            "observed_at",
            "evidence_ids",
            "primary_claim_ids",
            "outcome",
            "issue_state",
            "lifecycle_stage",
            "terminal_disposition",
            "readiness",
            "implementation_authorization",
            "ready_for_review_authorization",
            "execution_authorization",
            "merge_authorization",
            "closure_authorization",
            "external_write_authorization",
            "dependency_state",
            "claim_state",
            "active_branch",
            "primary_pr_numbers",
            "primary_pr_state",
            "validation_state",
            "freshness_state",
            "reconciliation_required",
            "blocker_codes",
            "reason_codes",
            "side_effects_performed",
            "state_id",
        }
    )
    _strict_keys(payload, expected, "issue operational state")
    if payload["side_effects_performed"] is not False:
        raise ValueError("serialized state cannot claim side effects")

    def enum_value(key: str, enum_type: type[Enum]) -> Enum:
        try:
            return enum_type(payload[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} is unsupported") from exc

    list_fields = (
        "evidence_ids",
        "primary_claim_ids",
        "primary_pr_numbers",
        "blocker_codes",
        "reason_codes",
    )
    for key in list_fields:
        if type(payload[key]) is not list:
            raise TypeError(f"{key} must be an exact JSON array")

    return IssueOperationalState(
        schema_name=payload["schema_name"],
        schema_version=payload["schema_version"],
        repository=payload["repository"],
        issue_number=payload["issue_number"],
        source_revision=payload["source_revision"],
        observed_at=payload["observed_at"],
        evidence_ids=tuple(payload["evidence_ids"]),
        primary_claim_ids=tuple(payload["primary_claim_ids"]),
        outcome=enum_value("outcome", OperationalOutcome),
        issue_state=enum_value("issue_state", IssueState),
        lifecycle_stage=enum_value("lifecycle_stage", LifecycleStage),
        terminal_disposition=enum_value("terminal_disposition", TerminalDisposition),
        readiness=enum_value("readiness", ReadinessState),
        implementation_authorization=AuthorityProjection.from_dict(
            payload["implementation_authorization"]
        ),
        ready_for_review_authorization=AuthorityProjection.from_dict(
            payload["ready_for_review_authorization"]
        ),
        execution_authorization=AuthorityProjection.from_dict(
            payload["execution_authorization"]
        ),
        merge_authorization=AuthorityProjection.from_dict(payload["merge_authorization"]),
        closure_authorization=AuthorityProjection.from_dict(
            payload["closure_authorization"]
        ),
        external_write_authorization=AuthorityProjection.from_dict(
            payload["external_write_authorization"]
        ),
        dependency_state=enum_value("dependency_state", DependencyState),
        claim_state=enum_value("claim_state", ClaimState),
        active_branch=payload["active_branch"],
        primary_pr_numbers=tuple(payload["primary_pr_numbers"]),
        primary_pr_state=enum_value("primary_pr_state", PrimaryPrState),
        validation_state=enum_value("validation_state", ValidationState),
        freshness_state=enum_value("freshness_state", FreshnessState),
        reconciliation_required=payload["reconciliation_required"],
        blocker_codes=tuple(payload["blocker_codes"]),
        reason_codes=tuple(payload["reason_codes"]),
        state_id=payload["state_id"],
    )
