"""Pure semantic no-progress detection for Agent OS continuation recovery.

This module extends the existing #1188 continuation seam without performing
recovery, retry, lease mutation, branch refresh, validation, or external I/O.
Callers supply stable canonical evidence identities. The projection answers only
whether a later recovery observation represents semantic progress, equivalent
state, or a repeated no-progress transition that must stop for human decision.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum

from workflow_scheduler.execution.continuation import ContinuationDecision

RECOVERY_PROGRESS_SCHEMA_VERSION = "1.0"
_MAX_TEXT = 512
_MAX_IDENTITIES = 16


class RecoveryProgressDisposition(str, Enum):
    INITIAL = "initial"
    PROGRESSED = "progressed"
    EQUIVALENT = "equivalent"
    RECOVERY_STALLED = "recovery-stalled"


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoverySemanticEvidence:
    """Stable semantic identities relevant to one recovery observation.

    Observational timestamps are intentionally absent. Callers should pass only
    canonical identities whose semantic movement can change the effective
    blocker or recovery state. Optional domain identities allow this projection
    to compose #918/#972/dependency/validation/branch-review evidence without
    copying or redefining those upstream contracts.
    """

    continuation: ContinuationDecision
    recovery_action: str
    effective_blocker: str
    route_decision_id: str | None = None
    environment_evidence_id: str | None = None
    dependency_readiness_evidence_id: str | None = None
    validation_evidence_id: str | None = None
    branch_freshness_evidence_id: str | None = None
    review_blocker_identity: str | None = None
    additional_semantic_identities: tuple[str, ...] = ()
    semantic_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.continuation) is not ContinuationDecision:
            raise TypeError("continuation must be exact ContinuationDecision")
        _bounded_text(self.recovery_action, "recovery_action")
        _bounded_text(self.effective_blocker, "effective_blocker")
        optional = (
            self.route_decision_id,
            self.environment_evidence_id,
            self.dependency_readiness_evidence_id,
            self.validation_evidence_id,
            self.branch_freshness_evidence_id,
            self.review_blocker_identity,
        )
        for value in optional:
            if value is not None:
                _bounded_text(value, "semantic_identity")
        if type(self.additional_semantic_identities) is not tuple:
            raise TypeError("additional_semantic_identities must be an exact tuple")
        if len(self.additional_semantic_identities) > _MAX_IDENTITIES:
            raise ValueError("additional_semantic_identities exceeds the bounded count")
        if tuple(sorted(set(self.additional_semantic_identities))) != self.additional_semantic_identities:
            raise ValueError("additional_semantic_identities must be sorted and unique")
        for value in self.additional_semantic_identities:
            _bounded_text(value, "additional_semantic_identity")
        payload = _semantic_payload(self)
        object.__setattr__(
            self,
            "semantic_fingerprint",
            "recovery-semantic:" + hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryProgressDecision:
    schema_version: str
    disposition: RecoveryProgressDisposition
    current_fingerprint: str
    prior_fingerprint: str | None
    prior_transition_fingerprint: str | None
    transition_fingerprint: str | None
    progress_made: bool
    reason_codes: tuple[str, ...]
    recommended_action: str
    decision_id: str = field(init=False)
    retry_authorized: bool = field(default=False, init=False)
    lease_takeover_authorized: bool = field(default=False, init=False)
    branch_refresh_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)
    external_writes_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != RECOVERY_PROGRESS_SCHEMA_VERSION:
            raise ValueError("unsupported recovery-progress schema version")
        if type(self.disposition) is not RecoveryProgressDisposition:
            raise TypeError("disposition must be exact RecoveryProgressDisposition")
        _bounded_text(self.current_fingerprint, "current_fingerprint")
        for value in (
            self.prior_fingerprint,
            self.prior_transition_fingerprint,
            self.transition_fingerprint,
        ):
            if value is not None:
                _bounded_text(value, "fingerprint")
        if type(self.progress_made) is not bool:
            raise TypeError("progress_made must be an exact boolean")
        if type(self.reason_codes) is not tuple or tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("reason_codes must be a sorted unique exact tuple")
        for reason in self.reason_codes:
            _bounded_text(reason, "reason_code")
        _bounded_text(self.recommended_action, "recommended_action")
        payload = {
            "schema_version": self.schema_version,
            "disposition": self.disposition.value,
            "current_fingerprint": self.current_fingerprint,
            "prior_fingerprint": self.prior_fingerprint,
            "prior_transition_fingerprint": self.prior_transition_fingerprint,
            "transition_fingerprint": self.transition_fingerprint,
            "progress_made": self.progress_made,
            "reason_codes": list(self.reason_codes),
            "recommended_action": self.recommended_action,
            "retry_authorized": False,
            "lease_takeover_authorized": False,
            "branch_refresh_authorized": False,
            "merge_authorized": False,
            "external_writes_authorized": False,
        }
        object.__setattr__(
            self,
            "decision_id",
            "recovery-progress:" + hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        )


def classify_recovery_progress(
    current: RecoverySemanticEvidence,
    *,
    prior: RecoverySemanticEvidence | None = None,
    prior_transition_fingerprint: str | None = None,
) -> RecoveryProgressDecision:
    """Classify semantic recovery movement without executing recovery.

    A single equivalent observation is evidence of no progress, not by itself a
    loop. A recovery is stalled only when the same semantic transition has
    already been observed and the current recovery produces that same transition
    again. This avoids an arbitrary retry-count threshold while still detecting
    deterministic cycles.
    """
    if type(current) is not RecoverySemanticEvidence:
        raise TypeError("current must be exact RecoverySemanticEvidence")
    if prior is not None and type(prior) is not RecoverySemanticEvidence:
        raise TypeError("prior must be exact RecoverySemanticEvidence or None")
    if prior_transition_fingerprint is not None:
        _bounded_text(prior_transition_fingerprint, "prior_transition_fingerprint")

    if prior is None:
        return _result(
            RecoveryProgressDisposition.INITIAL,
            current=current,
            prior=None,
            transition=None,
            prior_transition=prior_transition_fingerprint,
            progress=False,
            reasons=("recovery.initial-observation",),
            action="record the semantic recovery observation and continue only through existing canonical recovery contracts",
        )

    transition = _transition_fingerprint(prior.semantic_fingerprint, current.semantic_fingerprint)
    if current.semantic_fingerprint != prior.semantic_fingerprint:
        return _result(
            RecoveryProgressDisposition.PROGRESSED,
            current=current,
            prior=prior,
            transition=transition,
            prior_transition=prior_transition_fingerprint,
            progress=True,
            reasons=("recovery.semantic-state-changed",),
            action="continue through the existing continuation contract using the newly changed semantic evidence",
        )

    if prior_transition_fingerprint == transition:
        return _result(
            RecoveryProgressDisposition.RECOVERY_STALLED,
            current=current,
            prior=prior,
            transition=transition,
            prior_transition=prior_transition_fingerprint,
            progress=False,
            reasons=("recovery.no-semantic-progress", "recovery.repeated-equivalent-transition"),
            action="stop automatic recovery as RECOVERY_STALLED and route the unchanged blocker to its canonical recovery owner for human decision",
        )

    return _result(
        RecoveryProgressDisposition.EQUIVALENT,
        current=current,
        prior=prior,
        transition=transition,
        prior_transition=prior_transition_fingerprint,
        progress=False,
        reasons=("recovery.no-semantic-progress",),
        action="record the equivalent recovery transition; do not treat timestamps, regenerated evidence, or mechanical state churn as progress",
    )


def _semantic_payload(evidence: RecoverySemanticEvidence) -> dict[str, object]:
    decision = evidence.continuation
    # Deliberately omit decision_id and raw observed/current SHAs. Those may move
    # mechanically (for example, base refresh) without changing the effective
    # recovery state. Stable semantic identities and the effective blocker own
    # progress classification.
    return {
        "schema_version": RECOVERY_PROGRESS_SCHEMA_VERSION,
        "repository": decision.repository,
        "issue_number": decision.issue_number,
        "branch": decision.branch,
        "invocation_id": decision.invocation_id,
        "execution_id": decision.execution_id,
        "candidate_identity": decision.candidate_identity,
        "checkpoint_lineage_identity": decision.checkpoint_lineage_identity,
        "authorization_identity": decision.authorization_identity,
        "executor_identity": decision.executor_identity,
        "scope_identity": decision.scope_identity,
        "continuation_disposition": decision.disposition.value,
        "resume_point": decision.resume_point,
        "lease_identity": decision.lease_identity,
        "lease_holder_identity": decision.lease_holder_identity,
        "lease_generation": decision.lease_generation,
        "recovery_action": evidence.recovery_action,
        "effective_blocker": evidence.effective_blocker,
        "route_decision_id": evidence.route_decision_id,
        "environment_evidence_id": evidence.environment_evidence_id,
        "dependency_readiness_evidence_id": evidence.dependency_readiness_evidence_id,
        "validation_evidence_id": evidence.validation_evidence_id,
        "branch_freshness_evidence_id": evidence.branch_freshness_evidence_id,
        "review_blocker_identity": evidence.review_blocker_identity,
        "additional_semantic_identities": list(evidence.additional_semantic_identities),
    }


def _transition_fingerprint(before: str, after: str) -> str:
    payload = {"before": before, "after": after}
    return "recovery-transition:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _result(
    disposition: RecoveryProgressDisposition,
    *,
    current: RecoverySemanticEvidence,
    prior: RecoverySemanticEvidence | None,
    transition: str | None,
    prior_transition: str | None,
    progress: bool,
    reasons: tuple[str, ...],
    action: str,
) -> RecoveryProgressDecision:
    return RecoveryProgressDecision(
        schema_version=RECOVERY_PROGRESS_SCHEMA_VERSION,
        disposition=disposition,
        current_fingerprint=current.semantic_fingerprint,
        prior_fingerprint=None if prior is None else prior.semantic_fingerprint,
        prior_transition_fingerprint=prior_transition,
        transition_fingerprint=transition,
        progress_made=progress,
        reason_codes=tuple(sorted(reasons)),
        recommended_action=action,
    )


def _bounded_text(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise TypeError(f"{name} must be a non-empty exact string")
    if len(value) > _MAX_TEXT:
        raise ValueError(f"{name} exceeds the bounded length")
    return value
