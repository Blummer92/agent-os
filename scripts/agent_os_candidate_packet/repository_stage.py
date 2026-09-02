"""AOS-AUTO1C repository-observation stage (#752).

Converts one immutable, caller-supplied ``RepositoryObservation`` into
canonical ``RepositoryStateEvidence`` and validates it with the canonical GEX
validator, so a proposal is only ever attempted against verified repository
facts.

Repository-observation requirements
-----------------------------------

The observation is the *only* source of repository facts. This module reuses,
and never reimplements, ``RepositoryIdentity``, ``RepositoryStateEvidence``,
``RepositoryEvidenceType``, ``WorktreeState``, and
``validate_repository_state_evidence`` from
``scripts.agent_os_execution_capabilities``.

An approved read-only adapter must supply, explicitly:

* ``repository_identity`` -- host, owner, repository, fork/upstream, and
  default branch, as a canonical ``RepositoryIdentity``.
* ``base_ref``/``base_sha`` and ``head_ref``/``head_sha`` -- the branch the
  work targets and the branch it is on.
* ``requested_ref``/``requested_sha`` -- the source head the caller asked
  about, kept distinct from what was actually tested.
* ``observed_sha`` -- what the adapter actually saw.
* ``tested_sha`` -- what validation actually ran against.
* ``pushed_sha``, ``proposed_pr_sha``, ``synthetic_merge_sha``, and
  ``external_build_sha`` -- separate identities, so a pushed head, a PR head, a
  synthetic merge commit, and an external build never collapse into one
  another.
* ``evidence_type`` -- which of those identities the evidence is *about*
  (``branch-head``, ``base-sha``, ``synthetic-pr-merge``, or
  ``uncommitted-worktree``). The adapter selects it from what it observed; this
  stage never infers it from the SHAs it was handed.
* ``worktree_state`` and ``worktree_reason_codes`` -- ``clean``, ``dirty``, or
  ``indeterminate``. ``indeterminate`` is a real answer and produces
  ``needs-decision``; it is never quietly treated as clean.
* ``contract_fingerprint``, ``freshness_boundary``, and ``observed_at`` -- the
  implementation contract the observation is bound to, how stale it may be, and
  when it was taken.

This module performs no clone, checkout, worktree creation, command execution,
credential access, network call, or write of any kind. An unobserved fact is
never invented: an observation that cannot form canonical evidence fails closed
to ``invalid`` rather than being repaired.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Literal

from scripts.agent_os_execution_capabilities import (
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    RepositoryStateValidationResult,
    WorktreeState,
    reconstruct_repository_state_validation_result,
    serialize_repository_state_validation_result,
    validate_repository_state_evidence,
)

from .stage_models import STAGE_SCHEMA_VERSION, require_exact_keys

REPOSITORY_OBSERVATION_REJECTED = "repository-observation-rejected"
"""The observation could not form canonical evidence at all."""

REPOSITORY_OUTCOME_UNMAPPED = "repository-outcome-unmapped"
"""The canonical validator returned an outcome this stage cannot classify."""

_REQUIRED_OBSERVATION_TEXT = (
    "producer_adapter",
    "producer_adapter_version",
    "correlation_id",
    "base_ref",
    "base_sha",
    "head_ref",
    "head_sha",
    "observed_sha",
    "contract_fingerprint",
    "observed_at",
    "freshness_boundary",
)

_OPTIONAL_OBSERVATION_TEXT = (
    "requested_ref",
    "requested_sha",
    "tested_sha",
    "pushed_sha",
    "proposed_pr_sha",
    "synthetic_merge_sha",
    "external_build_sha",
)

_REPOSITORY_IDENTITY_PAYLOAD_KEYS = frozenset(
    item.name for item in fields(RepositoryIdentity)
)

_REPOSITORY_STATE_EVIDENCE_PAYLOAD_KEYS = frozenset(
    item.name for item in fields(RepositoryStateEvidence)
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RepositoryObservation:
    """One immutable repository observation supplied by a read-only adapter.

    Every field is an explicit caller-supplied fact. Nothing in this package
    clones, checks out, creates a worktree, runs a command, reads a credential,
    or otherwise probes a live repository, so a fact the adapter did not
    observe is passed as an explicit ``None``: absence is stated, never
    inferred.

    Every optional SHA and ref is a required keyword with no default. A caller
    that omits one gets a ``TypeError`` rather than a silent ``None`` that
    would read as a positive "not present" observation.

    Canonical format rules -- full lowercase 40-character SHAs, a SHA-256
    contract fingerprint, and approved ``worktree.*`` reason codes -- belong to
    ``RepositoryStateEvidence`` and ``validate_repository_state_evidence`` and
    are not repeated here.
    """

    producer_adapter: str
    producer_adapter_version: str
    correlation_id: str
    repository_identity: RepositoryIdentity
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str
    requested_ref: str | None
    requested_sha: str | None
    observed_sha: str
    tested_sha: str | None
    pushed_sha: str | None
    proposed_pr_sha: str | None
    synthetic_merge_sha: str | None
    external_build_sha: str | None
    evidence_type: RepositoryEvidenceType
    contract_fingerprint: str
    worktree_state: WorktreeState
    observed_at: str
    freshness_boundary: str
    worktree_reason_codes: tuple[str, ...] = ()
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.repository_identity, RepositoryIdentity):
            raise TypeError("repository_identity must be a RepositoryIdentity")
        if not isinstance(self.evidence_type, RepositoryEvidenceType):
            raise TypeError("evidence_type must be a RepositoryEvidenceType")
        if not isinstance(self.worktree_state, WorktreeState):
            raise TypeError("worktree_state must be a WorktreeState")
        for name in _REQUIRED_OBSERVATION_TEXT:
            object.__setattr__(self, name, _observed_text(getattr(self, name), name))
        for name in _OPTIONAL_OBSERVATION_TEXT:
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _observed_text(value, name))
        codes = self.worktree_reason_codes
        if isinstance(codes, str) or not isinstance(codes, (tuple, list)):
            raise TypeError("worktree_reason_codes must be a tuple of strings")
        object.__setattr__(
            self,
            "worktree_reason_codes",
            tuple(_observed_text(code, "worktree_reason_codes") for code in codes),
        )


class RepositoryStageStatus(str, Enum):
    """Mirrors the canonical repository-state validation outcomes exactly."""

    VALID = "valid"
    STALE = "stale"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs-decision"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class RepositoryStageResult:
    """Canonical repository evidence plus the canonical validation verdict.

    ``evidence`` and ``validation`` are both present whenever the observation
    formed canonical evidence, and both absent when it did not. Nothing here
    re-derives a verdict: ``status`` is the canonical validator's own outcome.
    """

    status: RepositoryStageStatus
    evidence: RepositoryStateEvidence | None
    validation: RepositoryStateValidationResult | None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, RepositoryStageStatus):
            raise TypeError("status must be a RepositoryStageStatus")
        if (self.evidence is None) != (self.validation is None):
            raise ValueError(
                "repository evidence and its validation result are inseparable"
            )
        if self.evidence is None and self.status is not RepositoryStageStatus.INVALID:
            raise ValueError("only an invalid result may omit repository evidence")
        if self.validation is not None and self.validation.outcome != self.status.value:
            raise ValueError("status must match the canonical validation outcome")
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))


def prepare_repository_state_evidence(
    repository_observation: RepositoryObservation,
    *,
    expected_repository: RepositoryIdentity | None = None,
    expected_base_ref: str | None = None,
    expected_base_sha: str | None = None,
    expected_head_ref: str | None = None,
    expected_head_sha: str | None = None,
    expected_requested_sha: str | None = None,
    expected_contract_fingerprint: str | None = None,
    expected_pr_sha: str | None = None,
) -> RepositoryStageResult:
    """Bind one observation into canonical evidence and validate it.

    Each ``expected_*`` argument is forwarded unchanged to
    ``validate_repository_state_evidence``; a caller that cannot state an
    expectation passes ``None`` and that binding is simply not asserted. This
    function adds no expectation of its own and invents no repository fact.
    """
    if not isinstance(repository_observation, RepositoryObservation):
        raise TypeError("repository_observation must be a RepositoryObservation")

    try:
        evidence = _canonical_evidence(repository_observation)
    except (TypeError, ValueError):
        return RepositoryStageResult(
            status=RepositoryStageStatus.INVALID,
            evidence=None,
            validation=None,
            reason_codes=(REPOSITORY_OBSERVATION_REJECTED,),
        )

    validation = validate_repository_state_evidence(
        evidence,
        expected_repository=expected_repository,
        expected_base_ref=expected_base_ref,
        expected_base_sha=expected_base_sha,
        expected_head_ref=expected_head_ref,
        expected_head_sha=expected_head_sha,
        expected_requested_sha=expected_requested_sha,
        expected_contract_fingerprint=expected_contract_fingerprint,
        expected_pr_sha=expected_pr_sha,
    )
    try:
        status = RepositoryStageStatus(validation.outcome)
    except ValueError:
        # The canonical validator constrains its own outcome vocabulary, but it
        # is another package: an outcome added there must still land as one
        # deterministic fail-closed result here, never an escaping exception.
        return RepositoryStageResult(
            status=RepositoryStageStatus.INVALID,
            evidence=None,
            validation=None,
            reason_codes=(REPOSITORY_OUTCOME_UNMAPPED, *validation.reason_codes),
        )
    return RepositoryStageResult(
        status=status,
        evidence=evidence,
        validation=validation,
        reason_codes=validation.reason_codes,
    )


# --------------------------------------------------------------------------
# Canonical serialization -- round trip without semantic drift.
# --------------------------------------------------------------------------


def repository_state_evidence_to_dict(
    evidence: RepositoryStateEvidence,
) -> dict[str, Any]:
    if not isinstance(evidence, RepositoryStateEvidence):
        raise TypeError("evidence must be a RepositoryStateEvidence")
    return {
        "schema_name": evidence.schema_name,
        "evidence_schema_version": evidence.evidence_schema_version,
        "producer_adapter": evidence.producer_adapter,
        "producer_adapter_version": evidence.producer_adapter_version,
        "correlation_id": evidence.correlation_id,
        "repository_identity": {
            name: getattr(evidence.repository_identity, name)
            for name in sorted(_REPOSITORY_IDENTITY_PAYLOAD_KEYS)
        },
        "base_ref": evidence.base_ref,
        "base_sha": evidence.base_sha,
        "head_ref": evidence.head_ref,
        "head_sha": evidence.head_sha,
        "requested_ref": evidence.requested_ref,
        "requested_sha": evidence.requested_sha,
        "observed_sha": evidence.observed_sha,
        "tested_sha": evidence.tested_sha,
        "pushed_sha": evidence.pushed_sha,
        "proposed_pr_sha": evidence.proposed_pr_sha,
        "synthetic_merge_sha": evidence.synthetic_merge_sha,
        "external_build_sha": evidence.external_build_sha,
        "evidence_type": evidence.evidence_type.value,
        "contract_fingerprint": evidence.contract_fingerprint,
        "worktree_state": evidence.worktree_state.value,
        "worktree_reason_codes": list(evidence.worktree_reason_codes),
        "observed_at": evidence.observed_at,
        "freshness_boundary": evidence.freshness_boundary,
        "evidence_id": evidence.evidence_id,
        "execution_authorized": False,
        "side_effects_performed": False,
    }


def repository_state_evidence_from_dict(
    payload: Mapping[str, Any],
) -> RepositoryStateEvidence:
    """Reconstruct canonical repository-state evidence, failing closed on drift.

    ``evidence_id`` is carried through and re-verified by
    ``RepositoryStateEvidence``: a payload whose identity no longer matches its
    own content is rejected rather than silently re-derived.
    """
    require_exact_keys(
        payload, _REPOSITORY_STATE_EVIDENCE_PAYLOAD_KEYS, "repository state evidence"
    )
    if payload["execution_authorized"] is not False:
        raise ValueError("execution_authorized must be false")
    if payload["side_effects_performed"] is not False:
        raise ValueError("side_effects_performed must be false")
    codes = payload["worktree_reason_codes"]
    if not isinstance(codes, list):
        raise ValueError("worktree_reason_codes must be a list")
    return RepositoryStateEvidence(
        schema_name=payload["schema_name"],
        evidence_schema_version=payload["evidence_schema_version"],
        producer_adapter=payload["producer_adapter"],
        producer_adapter_version=payload["producer_adapter_version"],
        correlation_id=payload["correlation_id"],
        repository_identity=_repository_identity_from_dict(
            payload["repository_identity"]
        ),
        base_ref=payload["base_ref"],
        base_sha=payload["base_sha"],
        head_ref=payload["head_ref"],
        head_sha=payload["head_sha"],
        requested_ref=payload["requested_ref"],
        requested_sha=payload["requested_sha"],
        observed_sha=payload["observed_sha"],
        tested_sha=payload["tested_sha"],
        pushed_sha=payload["pushed_sha"],
        proposed_pr_sha=payload["proposed_pr_sha"],
        synthetic_merge_sha=payload["synthetic_merge_sha"],
        external_build_sha=payload["external_build_sha"],
        evidence_type=RepositoryEvidenceType(payload["evidence_type"]),
        contract_fingerprint=payload["contract_fingerprint"],
        worktree_state=WorktreeState(payload["worktree_state"]),
        worktree_reason_codes=tuple(codes),
        observed_at=payload["observed_at"],
        freshness_boundary=payload["freshness_boundary"],
        evidence_id=payload["evidence_id"],
    )


_REPOSITORY_STAGE_RESULT_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "evidence",
        "validation",
        "reason_codes",
        "execution_authorized",
        "side_effects_performed",
    }
)


def repository_stage_result_to_dict(result: RepositoryStageResult) -> dict[str, Any]:
    """Serialize one canonical RepositoryStageResult, delegating every nested object.

    ``evidence`` is delegated to this module's own
    ``repository_state_evidence_to_dict``; ``validation`` is delegated to the
    canonical ``RepositoryStateValidationResult`` transport owned by
    ``scripts.agent_os_execution_capabilities``. Neither nested shape is
    reimplemented here.
    """
    if not isinstance(result, RepositoryStageResult):
        raise TypeError("result must be a RepositoryStageResult")
    payload = {
        "schema_version": STAGE_SCHEMA_VERSION,
        "status": result.status.value,
        "evidence": (
            None
            if result.evidence is None
            else repository_state_evidence_to_dict(result.evidence)
        ),
        "validation": (
            None
            if result.validation is None
            else json.loads(
                serialize_repository_state_validation_result(result.validation)
            )
        ),
        "reason_codes": list(result.reason_codes),
        "execution_authorized": False,
        "side_effects_performed": False,
    }
    if repository_stage_result_from_dict(payload) != result:
        raise ValueError("result has noncanonical repository stage fields")
    return payload


def repository_stage_result_from_dict(payload: Mapping[str, Any]) -> RepositoryStageResult:
    """Reconstruct one canonical RepositoryStageResult, failing closed on drift.

    The carried ``validation.evidence_id`` is verified against the reconstructed
    ``evidence.evidence_id`` when both are present: the canonical validator
    always binds its verdict to the evidence it evaluated, so a payload whose
    two nested objects disagree about which evidence was validated is rejected
    rather than silently paired.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("repository stage result must be a mapping")
    if payload.get("schema_version") != STAGE_SCHEMA_VERSION:
        raise ValueError("unsupported stage schema_version")
    require_exact_keys(
        payload, _REPOSITORY_STAGE_RESULT_PAYLOAD_KEYS, "repository stage result"
    )
    if payload["execution_authorized"] is not False:
        raise ValueError("execution_authorized must be false")
    if payload["side_effects_performed"] is not False:
        raise ValueError("side_effects_performed must be false")

    evidence_payload = payload["evidence"]
    validation_payload = payload["validation"]
    evidence = (
        None
        if evidence_payload is None
        else repository_state_evidence_from_dict(evidence_payload)
    )
    validation = (
        None
        if validation_payload is None
        else reconstruct_repository_state_validation_result(validation_payload)
    )
    if evidence is not None and validation is not None:
        if validation.evidence_id != evidence.evidence_id:
            raise ValueError("validation does not bind to the carried evidence")

    reason_codes = payload["reason_codes"]
    if not isinstance(reason_codes, list) or not all(
        isinstance(item, str) for item in reason_codes
    ):
        raise ValueError("reason_codes must be a list of strings")

    return RepositoryStageResult(
        status=RepositoryStageStatus(payload["status"]),
        evidence=evidence,
        validation=validation,
        reason_codes=tuple(reason_codes),
    )


def _repository_identity_from_dict(payload: Mapping[str, Any]) -> RepositoryIdentity:
    require_exact_keys(
        payload, _REPOSITORY_IDENTITY_PAYLOAD_KEYS, "repository identity"
    )
    return RepositoryIdentity(
        **{name: payload[name] for name in _REPOSITORY_IDENTITY_PAYLOAD_KEYS}
    )


def _canonical_evidence(observation: RepositoryObservation) -> RepositoryStateEvidence:
    """Copy observed facts into canonical evidence, adding only schema identity."""
    return RepositoryStateEvidence(
        schema_name=CAPABILITY_EVIDENCE_SCHEMA_NAME,
        evidence_schema_version=CAPABILITY_EVIDENCE_SCHEMA_VERSION,
        producer_adapter=observation.producer_adapter,
        producer_adapter_version=observation.producer_adapter_version,
        correlation_id=observation.correlation_id,
        repository_identity=observation.repository_identity,
        base_ref=observation.base_ref,
        base_sha=observation.base_sha,
        head_ref=observation.head_ref,
        head_sha=observation.head_sha,
        requested_ref=observation.requested_ref,
        requested_sha=observation.requested_sha,
        observed_sha=observation.observed_sha,
        tested_sha=observation.tested_sha,
        pushed_sha=observation.pushed_sha,
        proposed_pr_sha=observation.proposed_pr_sha,
        synthetic_merge_sha=observation.synthetic_merge_sha,
        external_build_sha=observation.external_build_sha,
        evidence_type=observation.evidence_type,
        contract_fingerprint=observation.contract_fingerprint,
        worktree_state=observation.worktree_state,
        worktree_reason_codes=observation.worktree_reason_codes,
        observed_at=observation.observed_at,
        freshness_boundary=observation.freshness_boundary,
    )


def _observed_text(value: object, name: str) -> str:
    """Validate one non-empty, control-character-free observed string."""
    if isinstance(value, bool) or not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    if any(character < " " or character == "\x7f" for character in normalized):
        raise ValueError(f"{name} must not contain control characters")
    return normalized
