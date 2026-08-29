"""Pure, deterministic authorization drift review over supplied evidence only.

This module performs no retrieval or mutation and never grants authorization.
Callers supply normalized base-to-current evidence; the result only classifies
whether that movement is irrelevant, needs revalidation, conflicts with the
original authorization contract, is no longer applicable, is incomplete, or
needs a human decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

SCHEMA_NAME = "agent-os-authorization-drift-review"
SCHEMA_VERSION = "1.0"
MAX_ITEMS = 256
MAX_TEXT_BYTES = 4096
MAX_SERIALIZED_BYTES = 64 * 1024
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
EVIDENCE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}:[0-9a-f]{64}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

REASON_CODES = frozenset({
    "identity.repository-mismatch", "identity.issue-mismatch",
    "identity.base-sha-mismatch", "identity.current-sha-invalid",
    "source.range-evidence-missing", "source.range-evidence-incomplete",
    "source.provenance-stale", "source.unsupported-version",
    "authorization.expired", "authorization.revoked",
    "authorization.superseded", "authorization.consumed",
    "authorization.applicability-stale",
    "scope.allowlisted-path-changed", "scope.expected-path-changed",
    "scope.forbidden-surface-implicated", "scope.contract-fingerprint-changed",
    "dependency.identity-changed", "dependency.public-interface-changed",
    "dependency.missing-or-unknown",
    "validation.required-test-changed", "validation.command-or-profile-changed",
    "validation.policy-changed",
    "governance.ownership-changed", "governance.source-of-truth-changed",
    "governance.write-authorization-changed", "governance.safe-lane-contract-changed",
    "governance.lifecycle-contract-changed", "governance.approval-contract-changed",
    "contract.incompatible-current-main", "relevance.unresolved",
    "relevance.no-relevant-change",
})
GOVERNANCE_REASONS = {
    "ownership": "governance.ownership-changed",
    "source-of-truth": "governance.source-of-truth-changed",
    "write-authorization": "governance.write-authorization-changed",
    "safe-lane": "governance.safe-lane-contract-changed",
    "lifecycle": "governance.lifecycle-contract-changed",
    "approval": "governance.approval-contract-changed",
}
REQUIRED_GOVERNANCE_KINDS = frozenset(GOVERNANCE_REASONS)


class DriftOutcome(str, Enum):
    NO_RELEVANT_DRIFT = "no-relevant-drift"
    REVALIDATION_REQUIRED = "revalidation-required"
    CONTRACT_CONFLICT = "contract-conflict"
    AUTHORIZATION_EXPIRED = "authorization-expired"
    EVIDENCE_INCOMPLETE = "evidence-incomplete"
    MANUAL_DECISION_REQUIRED = "manual-decision-required"


class AuthorizationState(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    SUPERSEDED = "superseded"
    CONSUMED = "consumed"


class CompatibilityState(str, Enum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AuthorizationStateEvidence:
    state: AuthorizationState
    applicable: bool = True
    applicability_current: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.state, AuthorizationState):
            raise TypeError("state must be AuthorizationState")
        if type(self.applicable) is not bool or type(self.applicability_current) is not bool:
            raise TypeError("authorization applicability flags must be bool")


@dataclass(frozen=True, slots=True)
class RangeEvidence:
    base_sha: str
    head_sha: str
    changed_paths: tuple[str, ...]
    present: bool = True
    complete: bool = True
    provenance_current: bool = True
    provenance_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.base_sha, "base_sha")
        _text(self.head_sha, "head_sha")
        object.__setattr__(self, "changed_paths", _paths(self.changed_paths, "changed_paths"))
        object.__setattr__(self, "provenance_ids", _evidence_ids(self.provenance_ids))
        for name in ("present", "complete", "provenance_current"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be bool")


@dataclass(frozen=True, slots=True)
class DependencyEvidence:
    dependency_id: str
    original_revision: str
    current_revision: str
    public_interface_changed: bool | None
    complete: bool = True

    def __post_init__(self) -> None:
        _text(self.dependency_id, "dependency_id")
        _text(self.original_revision, "original_revision")
        _text(self.current_revision, "current_revision")
        if self.public_interface_changed is not None and type(self.public_interface_changed) is not bool:
            raise TypeError("public_interface_changed must be bool or None")
        if type(self.complete) is not bool:
            raise TypeError("complete must be bool")


@dataclass(frozen=True, slots=True)
class GovernanceContractEvidence:
    kind: str
    original_revision: str
    current_revision: str
    compatibility: CompatibilityState
    complete: bool = True

    def __post_init__(self) -> None:
        if self.kind not in GOVERNANCE_REASONS:
            raise ValueError("unsupported governance contract kind")
        _text(self.original_revision, "original_revision")
        _text(self.current_revision, "current_revision")
        if not isinstance(self.compatibility, CompatibilityState):
            raise TypeError("compatibility must be CompatibilityState")
        if type(self.complete) is not bool:
            raise TypeError("complete must be bool")


@dataclass(frozen=True, slots=True)
class ValidationContractEvidence:
    original_required_tests: tuple[str, ...]
    current_required_tests: tuple[str, ...]
    original_command_or_profile: str
    current_command_or_profile: str
    original_policy_revision: str
    current_policy_revision: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "original_required_tests", _strings(self.original_required_tests, "original_required_tests"))
        object.__setattr__(self, "current_required_tests", _strings(self.current_required_tests, "current_required_tests"))
        for name in ("original_command_or_profile", "current_command_or_profile", "original_policy_revision", "current_policy_revision"):
            _text(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class AuthorizationDriftReviewRequest:
    schema_name: str
    schema_version: str
    repository: str
    issue_number: int
    authorization_repository: str
    authorization_issue_number: int
    authorization_id: str
    authorization_revision: str
    base_branch: str
    authorization_base_sha: str
    current_main_sha: str
    authorization_state: AuthorizationStateEvidence
    range_evidence: RangeEvidence | None
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    expected_paths: tuple[str, ...]
    original_contract_fingerprint: str
    current_contract_fingerprint: str
    contract_compatibility: CompatibilityState
    forbidden_surface_implicated: bool
    dependencies: tuple[DependencyEvidence, ...]
    governance_contracts: tuple[GovernanceContractEvidence, ...]
    validation: ValidationContractEvidence
    issue_operational_state_id: str | None = None
    issue_operational_state_current: bool = True
    relevance_resolved: bool = True

    def __post_init__(self) -> None:
        for name in ("schema_name", "schema_version", "repository", "authorization_repository", "authorization_id", "authorization_revision", "base_branch", "authorization_base_sha", "current_main_sha", "original_contract_fingerprint", "current_contract_fingerprint"):
            _text(getattr(self, name), name)
        _positive_int(self.issue_number, "issue_number")
        _positive_int(self.authorization_issue_number, "authorization_issue_number")
        if not isinstance(self.authorization_state, AuthorizationStateEvidence):
            raise TypeError("authorization_state must be AuthorizationStateEvidence")
        if self.range_evidence is not None and not isinstance(self.range_evidence, RangeEvidence):
            raise TypeError("range_evidence must be RangeEvidence or None")
        if not isinstance(self.contract_compatibility, CompatibilityState):
            raise TypeError("contract_compatibility must be CompatibilityState")
        if type(self.forbidden_surface_implicated) is not bool:
            raise TypeError("forbidden_surface_implicated must be bool")
        object.__setattr__(self, "allowed_paths", _paths(self.allowed_paths, "allowed_paths"))
        object.__setattr__(self, "forbidden_paths", _paths(self.forbidden_paths, "forbidden_paths"))
        object.__setattr__(self, "expected_paths", _paths(self.expected_paths, "expected_paths"))
        if type(self.dependencies) is not tuple or len(self.dependencies) > MAX_ITEMS:
            raise ValueError("dependencies outside bounds")
        if any(not isinstance(item, DependencyEvidence) for item in self.dependencies):
            raise TypeError("dependencies must contain DependencyEvidence")
        if len({item.dependency_id for item in self.dependencies}) != len(self.dependencies):
            raise ValueError("duplicate dependency_id")
        object.__setattr__(self, "dependencies", tuple(sorted(self.dependencies, key=lambda item: item.dependency_id)))
        if type(self.governance_contracts) is not tuple or len(self.governance_contracts) > len(REQUIRED_GOVERNANCE_KINDS):
            raise ValueError("governance_contracts outside bounds")
        if any(not isinstance(item, GovernanceContractEvidence) for item in self.governance_contracts):
            raise TypeError("governance_contracts must contain GovernanceContractEvidence")
        if len({item.kind for item in self.governance_contracts}) != len(self.governance_contracts):
            raise ValueError("duplicate governance contract kind")
        object.__setattr__(self, "governance_contracts", tuple(sorted(self.governance_contracts, key=lambda item: item.kind)))
        if not isinstance(self.validation, ValidationContractEvidence):
            raise TypeError("validation must be ValidationContractEvidence")
        for name in ("issue_operational_state_current", "relevance_resolved"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be bool")
        if self.issue_operational_state_id is not None and not EVIDENCE_ID_RE.fullmatch(self.issue_operational_state_id):
            raise ValueError("issue_operational_state_id malformed")


@dataclass(frozen=True, slots=True)
class AuthorizationDriftReviewResult:
    outcome: DriftOutcome
    reason_codes: tuple[str, ...]
    review_id: str
    request_fingerprint: str
    repository: str
    issue_number: int
    authorization_id: str
    authorization_revision: str
    original_base_branch: str
    original_base_sha: str
    current_main_sha: str
    original_contract_fingerprint: str
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_tests: tuple[str, ...]
    authorization_granted: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes", _reasons(self.reason_codes))
        expected = _identity("authorization-drift-review", self._payload())
        if self.review_id and self.review_id != expected:
            raise ValueError("review_id does not match review content")
        object.__setattr__(self, "review_id", expected)
        if len(self.to_json().encode()) > MAX_SERIALIZED_BYTES:
            raise ValueError("serialized review outside bounds")

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
            "outcome": self.outcome.value, "reason_codes": list(self.reason_codes),
            "request_fingerprint": self.request_fingerprint,
            "repository": self.repository, "issue_number": self.issue_number,
            "authorization_id": self.authorization_id,
            "authorization_revision": self.authorization_revision,
            "original_base_branch": self.original_base_branch,
            "original_base_sha": self.original_base_sha,
            "current_main_sha": self.current_main_sha,
            "original_contract_fingerprint": self.original_contract_fingerprint,
            "allowed_paths": list(self.allowed_paths), "forbidden_paths": list(self.forbidden_paths),
            "required_tests": list(self.required_tests),
            "authorization_granted": False, "side_effects_performed": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"review_id": self.review_id, **self._payload()}

    def to_json(self) -> str:
        return _json(self.to_dict())


@dataclass(frozen=True, slots=True)
class AuthorizationRefreshHandoff:
    handoff_id: str
    repository: str
    issue_number: int
    original_authorization_id: str
    original_authorization_revision: str
    drift_review_id: str
    drift_outcome: DriftOutcome
    original_base_branch: str
    original_base_sha: str
    proposed_refreshed_base_sha: str
    unchanged_contract_fingerprint: str
    unchanged_allowed_paths: tuple[str, ...]
    unchanged_forbidden_paths: tuple[str, ...]
    unchanged_required_tests: tuple[str, ...]
    revalidation_evidence_ids: tuple[str, ...]
    authorization_decision_target: str
    authorization_granted: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _text(self.authorization_decision_target, "authorization_decision_target")
        object.__setattr__(self, "revalidation_evidence_ids", _evidence_ids(self.revalidation_evidence_ids))
        expected = _identity("authorization-refresh-handoff", self._payload())
        if self.handoff_id and self.handoff_id != expected:
            raise ValueError("handoff_id does not match handoff content")
        object.__setattr__(self, "handoff_id", expected)

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_name": "agent-os-authorization-refresh-handoff", "schema_version": "1.0",
            "repository": self.repository, "issue_number": self.issue_number,
            "original_authorization_id": self.original_authorization_id,
            "original_authorization_revision": self.original_authorization_revision,
            "drift_review_id": self.drift_review_id, "drift_outcome": self.drift_outcome.value,
            "original_base_branch": self.original_base_branch,
            "original_base_sha": self.original_base_sha,
            "proposed_refreshed_base_sha": self.proposed_refreshed_base_sha,
            "unchanged_contract_fingerprint": self.unchanged_contract_fingerprint,
            "unchanged_allowed_paths": list(self.unchanged_allowed_paths),
            "unchanged_forbidden_paths": list(self.unchanged_forbidden_paths),
            "unchanged_required_tests": list(self.unchanged_required_tests),
            "revalidation_evidence_ids": list(self.revalidation_evidence_ids),
            "authorization_decision_target": self.authorization_decision_target,
            "authorization_granted": False, "side_effects_performed": False,
        }

    def to_json(self) -> str:
        return _json({"handoff_id": self.handoff_id, **self._payload()})


def evaluate_authorization_drift(request: AuthorizationDriftReviewRequest) -> AuthorizationDriftReviewResult:
    """Classify supplied drift using the frozen #854 precedence."""
    if not isinstance(request, AuthorizationDriftReviewRequest):
        raise TypeError("request must be AuthorizationDriftReviewRequest")

    incomplete: set[str] = set()
    if request.schema_name != SCHEMA_NAME or request.schema_version != SCHEMA_VERSION:
        incomplete.add("source.unsupported-version")
    if not REPOSITORY_RE.fullmatch(request.repository) or request.repository != request.authorization_repository:
        incomplete.add("identity.repository-mismatch")
    if request.issue_number != request.authorization_issue_number:
        incomplete.add("identity.issue-mismatch")
    if not SHA40_RE.fullmatch(request.authorization_base_sha):
        incomplete.add("identity.base-sha-mismatch")
    if not SHA40_RE.fullmatch(request.current_main_sha):
        incomplete.add("identity.current-sha-invalid")

    range_evidence = request.range_evidence
    if range_evidence is None or not range_evidence.present:
        incomplete.add("source.range-evidence-missing")
    else:
        if range_evidence.base_sha != request.authorization_base_sha:
            incomplete.add("identity.base-sha-mismatch")
        if range_evidence.head_sha != request.current_main_sha:
            incomplete.add("identity.current-sha-invalid")
        if not range_evidence.complete or not range_evidence.provenance_ids:
            incomplete.add("source.range-evidence-incomplete")
        if not range_evidence.provenance_current:
            incomplete.add("source.provenance-stale")
    if request.issue_operational_state_id is not None and not request.issue_operational_state_current:
        incomplete.add("source.provenance-stale")
    if {item.kind for item in request.governance_contracts} != REQUIRED_GOVERNANCE_KINDS:
        incomplete.add("source.range-evidence-incomplete")
    if any(not item.complete for item in request.governance_contracts):
        incomplete.add("source.range-evidence-incomplete")
    if any(not item.complete or item.public_interface_changed is None for item in request.dependencies):
        incomplete.add("dependency.missing-or-unknown")
    if incomplete:
        return _result(request, DriftOutcome.EVIDENCE_INCOMPLETE, incomplete)

    expired: set[str] = set()
    state_reason = {
        AuthorizationState.EXPIRED: "authorization.expired",
        AuthorizationState.REVOKED: "authorization.revoked",
        AuthorizationState.SUPERSEDED: "authorization.superseded",
        AuthorizationState.CONSUMED: "authorization.consumed",
    }.get(request.authorization_state.state)
    if state_reason:
        expired.add(state_reason)
    if not request.authorization_state.applicable or not request.authorization_state.applicability_current:
        expired.add("authorization.applicability-stale")
    if expired:
        return _result(request, DriftOutcome.AUTHORIZATION_EXPIRED, expired)

    assert range_evidence is not None
    conflict: set[str] = set()
    revalidation: set[str] = set()
    unresolved: set[str] = set()
    if request.forbidden_surface_implicated or _overlap(range_evidence.changed_paths, request.forbidden_paths):
        conflict.add("scope.forbidden-surface-implicated")
    if request.original_contract_fingerprint != request.current_contract_fingerprint:
        if request.contract_compatibility is CompatibilityState.INCOMPATIBLE:
            conflict.update({"scope.contract-fingerprint-changed", "contract.incompatible-current-main"})
        elif request.contract_compatibility is CompatibilityState.UNKNOWN:
            unresolved.add("relevance.unresolved")
        else:
            revalidation.add("scope.contract-fingerprint-changed")
    elif request.contract_compatibility is CompatibilityState.INCOMPATIBLE:
        conflict.add("contract.incompatible-current-main")
    elif request.contract_compatibility is CompatibilityState.UNKNOWN:
        unresolved.add("relevance.unresolved")

    for item in request.governance_contracts:
        if item.original_revision == item.current_revision:
            continue
        reason = GOVERNANCE_REASONS[item.kind]
        if item.compatibility is CompatibilityState.INCOMPATIBLE:
            conflict.update({reason, "contract.incompatible-current-main"})
        elif item.compatibility is CompatibilityState.UNKNOWN:
            unresolved.add("relevance.unresolved")
        else:
            revalidation.add(reason)
    if conflict:
        return _result(request, DriftOutcome.CONTRACT_CONFLICT, conflict)

    changed = range_evidence.changed_paths
    if _overlap(changed, request.allowed_paths):
        revalidation.add("scope.allowlisted-path-changed")
    if _overlap(changed, request.expected_paths):
        revalidation.add("scope.expected-path-changed")
    for item in request.dependencies:
        if item.original_revision != item.current_revision:
            revalidation.add("dependency.identity-changed")
        if item.public_interface_changed:
            revalidation.add("dependency.public-interface-changed")
    validation = request.validation
    if validation.original_required_tests != validation.current_required_tests:
        revalidation.add("validation.required-test-changed")
    if validation.original_command_or_profile != validation.current_command_or_profile:
        revalidation.add("validation.command-or-profile-changed")
    if validation.original_policy_revision != validation.current_policy_revision:
        revalidation.add("validation.policy-changed")
    if revalidation:
        return _result(request, DriftOutcome.REVALIDATION_REQUIRED, revalidation)
    if unresolved or not request.relevance_resolved:
        return _result(request, DriftOutcome.MANUAL_DECISION_REQUIRED, {"relevance.unresolved"})
    return _result(request, DriftOutcome.NO_RELEVANT_DRIFT, {"relevance.no-relevant-change"})


def build_authorization_refresh_handoff(
    review: AuthorizationDriftReviewResult,
    *,
    authorization_decision_target: str,
    revalidation_evidence_ids: tuple[str, ...] = (),
    revalidation_complete: bool = False,
) -> AuthorizationRefreshHandoff:
    """Build evidence for the existing authorization owner; never grant authority."""
    if review.outcome is DriftOutcome.NO_RELEVANT_DRIFT:
        if revalidation_complete or revalidation_evidence_ids:
            raise ValueError("no-relevant-drift handoff cannot claim revalidation")
    elif review.outcome is DriftOutcome.REVALIDATION_REQUIRED:
        if not revalidation_complete or not revalidation_evidence_ids:
            raise ValueError("completed revalidation evidence required")
    else:
        raise ValueError("review outcome cannot produce a refresh handoff")
    return AuthorizationRefreshHandoff(
        handoff_id="", repository=review.repository, issue_number=review.issue_number,
        original_authorization_id=review.authorization_id,
        original_authorization_revision=review.authorization_revision,
        drift_review_id=review.review_id, drift_outcome=review.outcome,
        original_base_branch=review.original_base_branch,
        original_base_sha=review.original_base_sha,
        proposed_refreshed_base_sha=review.current_main_sha,
        unchanged_contract_fingerprint=review.original_contract_fingerprint,
        unchanged_allowed_paths=review.allowed_paths,
        unchanged_forbidden_paths=review.forbidden_paths,
        unchanged_required_tests=review.required_tests,
        revalidation_evidence_ids=revalidation_evidence_ids,
        authorization_decision_target=authorization_decision_target,
    )


def _result(request: AuthorizationDriftReviewRequest, outcome: DriftOutcome, reasons: set[str]) -> AuthorizationDriftReviewResult:
    return AuthorizationDriftReviewResult(
        outcome=outcome, reason_codes=tuple(sorted(reasons)), review_id="",
        request_fingerprint=_identity("authorization-drift-input", _request_payload(request)),
        repository=request.repository, issue_number=request.issue_number,
        authorization_id=request.authorization_id, authorization_revision=request.authorization_revision,
        original_base_branch=request.base_branch, original_base_sha=request.authorization_base_sha,
        current_main_sha=request.current_main_sha,
        original_contract_fingerprint=request.original_contract_fingerprint,
        allowed_paths=request.allowed_paths, forbidden_paths=request.forbidden_paths,
        required_tests=request.validation.original_required_tests,
    )


def _request_payload(request: AuthorizationDriftReviewRequest) -> dict[str, Any]:
    r = request.range_evidence
    return {
        "schema_name": request.schema_name, "schema_version": request.schema_version,
        "repository": request.repository, "issue_number": request.issue_number,
        "authorization_repository": request.authorization_repository,
        "authorization_issue_number": request.authorization_issue_number,
        "authorization_id": request.authorization_id,
        "authorization_revision": request.authorization_revision,
        "base_branch": request.base_branch, "authorization_base_sha": request.authorization_base_sha,
        "current_main_sha": request.current_main_sha,
        "authorization_state": [request.authorization_state.state.value, request.authorization_state.applicable, request.authorization_state.applicability_current],
        "range_evidence": None if r is None else [r.base_sha, r.head_sha, list(r.changed_paths), r.present, r.complete, r.provenance_current, list(r.provenance_ids)],
        "allowed_paths": list(request.allowed_paths), "forbidden_paths": list(request.forbidden_paths),
        "expected_paths": list(request.expected_paths),
        "original_contract_fingerprint": request.original_contract_fingerprint,
        "current_contract_fingerprint": request.current_contract_fingerprint,
        "contract_compatibility": request.contract_compatibility.value,
        "forbidden_surface_implicated": request.forbidden_surface_implicated,
        "dependencies": [[x.dependency_id, x.original_revision, x.current_revision, x.public_interface_changed, x.complete] for x in request.dependencies],
        "governance_contracts": [[x.kind, x.original_revision, x.current_revision, x.compatibility.value, x.complete] for x in request.governance_contracts],
        "validation": [list(request.validation.original_required_tests), list(request.validation.current_required_tests), request.validation.original_command_or_profile, request.validation.current_command_or_profile, request.validation.original_policy_revision, request.validation.current_policy_revision],
        "issue_operational_state_id": request.issue_operational_state_id,
        "issue_operational_state_current": request.issue_operational_state_current,
        "relevance_resolved": request.relevance_resolved,
    }


def _paths(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    checked = _strings(values, name)
    if any(v.startswith("/") or v.endswith("/") or "//" in v for v in checked):
        raise ValueError(f"{name} contains malformed path")
    return checked


def _strings(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if type(values) is not tuple or len(values) > MAX_ITEMS:
        raise ValueError(f"{name} outside bounds")
    checked = tuple(_text(v, name) for v in values)
    if len(set(checked)) != len(checked):
        raise ValueError(f"{name} contains duplicates")
    return tuple(sorted(checked))


def _evidence_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    checked = _strings(values, "evidence_ids")
    if any(not EVIDENCE_ID_RE.fullmatch(v) for v in checked):
        raise ValueError("malformed evidence identity")
    return checked


def _reasons(values: tuple[str, ...]) -> tuple[str, ...]:
    if any(v not in REASON_CODES for v in values):
        raise ValueError("unsupported reason code")
    return tuple(sorted(set(values)))


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or len(value.encode()) > MAX_TEXT_BYTES or CONTROL_RE.search(value):
        raise ValueError(f"{name} must be bounded text")
    return value


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be positive integer")
    return value


def _overlap(changed: tuple[str, ...], governed: tuple[str, ...]) -> bool:
    return any(a == b or a.startswith(b + "/") or b.startswith(a + "/") for a in changed for b in governed)


def _json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _identity(prefix: str, payload: object) -> str:
    material = f"agent-os:{prefix}:v1\0".encode() + _json(payload).encode()
    return f"{prefix}:{hashlib.sha256(material).hexdigest()}"
