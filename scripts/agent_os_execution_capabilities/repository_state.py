from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .models import (
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    CAPABILITY_EVIDENCE_SERIALIZER_VERSION,
    CapabilityEvidence,
    CapabilityEvidenceEnvelope,
    CapabilityStatus,
    EvidenceStrength,
    ExecutionDecision,
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    RepositoryStateValidationResult,
    WorktreeState,
)
from .reason_codes import APPROVED_REASON_CODES, normalize_reason_codes

_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
)

_CAPABILITY_FIELDS = frozenset(
    {
        "capability_id",
        "status",
        "evidence_strength",
        "operation_scope",
        "repository_scope",
        "ref_scope",
        "sha_scope",
        "principal_type",
        "runtime_fingerprint",
        "freshness_boundary",
        "reason_code",
        "reason",
        "required_handoff",
    }
)
_ENVELOPE_FIELDS = frozenset(
    {
        "schema_name",
        "evidence_schema_version",
        "serializer_version",
        "producer_adapter",
        "producer_adapter_version",
        "correlation_id",
        "environment_class",
        "repository_identity",
        "base_ref",
        "head_ref",
        "observed_sha",
        "contract_fingerprint",
        "capabilities",
        "invalidation_reasons",
        "handoffs",
        "decision",
        "execution_authorized",
    }
)
_REPOSITORY_IDENTITY_FIELDS = frozenset(
    {
        "host",
        "owner",
        "repository",
        "repository_id",
        "is_fork",
        "upstream_owner",
        "upstream_repository",
        "upstream_repository_id",
        "default_branch",
    }
)
_REPOSITORY_STATE_FIELDS = frozenset(
    {
        "schema_name",
        "evidence_schema_version",
        "producer_adapter",
        "producer_adapter_version",
        "correlation_id",
        "repository_identity",
        "base_ref",
        "base_sha",
        "head_ref",
        "head_sha",
        "requested_ref",
        "requested_sha",
        "observed_sha",
        "tested_sha",
        "pushed_sha",
        "proposed_pr_sha",
        "synthetic_merge_sha",
        "external_build_sha",
        "evidence_type",
        "contract_fingerprint",
        "worktree_state",
        "observed_at",
        "freshness_boundary",
        "evidence_id",
        "execution_authorized",
    }
)


def validate_capability_evidence(
    value: CapabilityEvidenceEnvelope | Mapping[str, Any],
) -> CapabilityEvidenceEnvelope:
    if isinstance(value, CapabilityEvidenceEnvelope):
        supplied = _envelope_to_mapping(value)
    elif isinstance(value, Mapping):
        supplied = dict(value)
    else:
        return _fallback_capability_envelope(("schema.incomplete",))

    reasons: set[str] = set()
    if _contains_secret_like(supplied):
        return _fallback_capability_envelope(("schema.secret-like-value",))
    if set(supplied) - _ENVELOPE_FIELDS:
        reasons.add("schema.unknown-field")
    if supplied.get("execution_authorized", False) is not False:
        reasons.add("schema.contradictory")

    schema_name = supplied.get("schema_name")
    if schema_name != CAPABILITY_EVIDENCE_SCHEMA_NAME:
        reasons.add("schema.name-mismatch")

    version = supplied.get("evidence_schema_version")
    if version is None:
        reasons.add("schema.version-missing")
    elif not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        reasons.add("schema.version-malformed")
    elif version != CAPABILITY_EVIDENCE_SCHEMA_VERSION:
        reasons.add("schema.version-unsupported")

    serializer_version = supplied.get("serializer_version")
    if not isinstance(serializer_version, str) or not _VERSION_RE.fullmatch(
        serializer_version
    ):
        reasons.add("schema.version-malformed")
        serializer_version = CAPABILITY_EVIDENCE_SERIALIZER_VERSION

    producer_adapter = _safe_string(supplied.get("producer_adapter"), "unknown-adapter")
    producer_adapter_version = _safe_string(
        supplied.get("producer_adapter_version"), "0.0"
    )
    if producer_adapter == "unknown-adapter":
        reasons.add("adapter.missing")
    if not _VERSION_RE.fullmatch(producer_adapter_version):
        reasons.add("adapter.malformed")
        producer_adapter_version = "0.0"

    correlation_id = _safe_string(supplied.get("correlation_id"), "unknown")
    environment_class = _safe_string(
        supplied.get("environment_class"), "analysis-only"
    )
    repository_identity = _parse_repository_identity(
        supplied.get("repository_identity"), reasons, optional=True
    )
    base_ref = _optional_string(supplied.get("base_ref"), reasons)
    head_ref = _optional_string(supplied.get("head_ref"), reasons)
    observed_sha = _optional_sha(supplied.get("observed_sha"), reasons)
    contract_fingerprint = _optional_fingerprint(
        supplied.get("contract_fingerprint"), reasons
    )

    capabilities: list[CapabilityEvidence] = []
    raw_capabilities = supplied.get("capabilities")
    if not isinstance(raw_capabilities, (tuple, list)):
        reasons.add("schema.incomplete")
    else:
        for item in raw_capabilities:
            parsed = _parse_capability(item, reasons)
            if parsed is not None:
                capabilities.append(parsed)
    ids = [item.capability_id for item in capabilities]
    if len(ids) != len(set(ids)):
        reasons.add("schema.duplicate-capability")
        capabilities = list({item.capability_id: item for item in capabilities}.values())

    raw_reasons = supplied.get("invalidation_reasons", ())
    if isinstance(raw_reasons, (tuple, list, set, frozenset)) and not isinstance(
        raw_reasons, str
    ):
        for reason in raw_reasons:
            if reason in APPROVED_REASON_CODES:
                reasons.add(reason)
            else:
                reasons.add("schema.unknown-enum")
    else:
        reasons.add("schema.incomplete")

    handoffs = _safe_string_collection(supplied.get("handoffs", ()), reasons)
    derived_decision = _derive_capability_decision(tuple(capabilities), reasons)
    supplied_decision = supplied.get("decision")
    if isinstance(supplied_decision, ExecutionDecision):
        supplied_decision = supplied_decision.value
    if supplied_decision is not None:
        try:
            parsed_decision = ExecutionDecision(supplied_decision)
        except (TypeError, ValueError):
            reasons.add("schema.unknown-enum")
        else:
            if parsed_decision != derived_decision:
                reasons.add("schema.contradictory")
                derived_decision = ExecutionDecision.NEEDS_DECISION

    if reasons & {
        "schema.name-mismatch",
        "schema.version-missing",
        "schema.version-malformed",
        "schema.version-unsupported",
        "schema.unknown-field",
        "schema.unknown-enum",
        "schema.duplicate-capability",
        "schema.incomplete",
        "schema.contradictory",
        "schema.secret-like-value",
        "adapter.missing",
        "adapter.malformed",
        "adapter.scope-mismatch",
    }:
        derived_decision = ExecutionDecision.NEEDS_DECISION

    return CapabilityEvidenceEnvelope(
        schema_name=CAPABILITY_EVIDENCE_SCHEMA_NAME,
        evidence_schema_version=(
            version if isinstance(version, str) and _VERSION_RE.fullmatch(version) else "0.0"
        ),
        serializer_version=serializer_version,
        producer_adapter=producer_adapter,
        producer_adapter_version=producer_adapter_version,
        correlation_id=correlation_id,
        environment_class=environment_class,
        repository_identity=repository_identity,
        base_ref=base_ref,
        head_ref=head_ref,
        observed_sha=observed_sha,
        contract_fingerprint=contract_fingerprint,
        capabilities=tuple(capabilities),
        invalidation_reasons=tuple(reasons),
        handoffs=handoffs,
        decision=derived_decision,
    )


def validate_repository_state_evidence(
    value: RepositoryStateEvidence | Mapping[str, Any],
    *,
    expected_repository: RepositoryIdentity | None = None,
    expected_base_ref: str | None = None,
    expected_base_sha: str | None = None,
    expected_head_ref: str | None = None,
    expected_head_sha: str | None = None,
    expected_requested_sha: str | None = None,
    expected_contract_fingerprint: str | None = None,
    expected_pr_sha: str | None = None,
) -> RepositoryStateValidationResult:
    reasons: set[str] = set()
    evidence = _coerce_repository_state(value, reasons)
    if evidence is None:
        return _repository_result(
            decision=ExecutionDecision.NEEDS_DECISION,
            evidence_id=_mapping_string(value, "evidence_id"),
            tested_sha=_mapping_string(value, "tested_sha"),
            reasons=reasons or {"schema.incomplete"},
        )

    if evidence.evidence_schema_version != CAPABILITY_EVIDENCE_SCHEMA_VERSION:
        reasons.add("schema.version-unsupported")
    if expected_repository is not None:
        if not isinstance(expected_repository, RepositoryIdentity):
            reasons.add("schema.incomplete")
        elif evidence.repository_identity.canonical_key != expected_repository.canonical_key:
            if (
                evidence.repository_identity.host == expected_repository.host
                and evidence.repository_identity.owner == expected_repository.owner
                and evidence.repository_identity.repository == expected_repository.repository
                and evidence.repository_identity.is_fork != expected_repository.is_fork
            ):
                reasons.add("repo.fork-upstream-mismatch")
            else:
                reasons.add("repo.identity-mismatch")
    if expected_base_ref is not None and evidence.base_ref != expected_base_ref:
        reasons.add("ref.base-mismatch")
    if expected_base_sha is not None and evidence.base_sha != expected_base_sha:
        reasons.add("ref.base-mismatch")
    if expected_head_ref is not None and evidence.head_ref != expected_head_ref:
        reasons.add("ref.head-mismatch")
    if expected_head_sha is not None and evidence.head_sha != expected_head_sha:
        reasons.add("ref.branch-moved")
    if expected_requested_sha is not None and evidence.requested_sha != expected_requested_sha:
        reasons.add("ref.requested-tested-mismatch")
    if (
        expected_contract_fingerprint is not None
        and evidence.contract_fingerprint != expected_contract_fingerprint
    ):
        reasons.add("ref.contract-mismatch")
    if expected_pr_sha is not None and evidence.proposed_pr_sha != expected_pr_sha:
        reasons.add("ref.pr-head-mismatch")

    _validate_sha_bindings(evidence, reasons)
    _validate_worktree(evidence.worktree_state, reasons)

    if reasons & {
        "schema.name-mismatch",
        "schema.version-missing",
        "schema.version-malformed",
        "schema.version-unsupported",
        "schema.unknown-field",
        "schema.unknown-enum",
        "schema.incomplete",
        "schema.contradictory",
        "schema.secret-like-value",
        "ref.tested-sha-missing",
        "ref.tested-sha-ambiguous",
    }:
        decision = ExecutionDecision.NEEDS_DECISION
    elif reasons:
        decision = ExecutionDecision.HANDOFF_REQUIRED
    else:
        decision = ExecutionDecision.PROCEED
    return _repository_result(
        decision=decision,
        evidence_id=evidence.evidence_id,
        tested_sha=evidence.tested_sha,
        reasons=reasons,
    )


def _validate_sha_bindings(
    evidence: RepositoryStateEvidence, reasons: set[str]
) -> None:
    if evidence.tested_sha is None:
        reasons.add("ref.tested-sha-missing")
    if evidence.observed_sha != evidence.head_sha:
        reasons.add("ref.observed-sha-stale")
    if evidence.requested_sha is not None and evidence.requested_sha != evidence.head_sha:
        reasons.add("ref.requested-tested-mismatch")
    if evidence.external_build_sha is not None and evidence.tested_sha is not None:
        if evidence.external_build_sha != evidence.tested_sha:
            reasons.add("ref.build-sha-mismatch")
    if evidence.pushed_sha is not None and evidence.pushed_sha != evidence.head_sha:
        reasons.add("ref.pushed-sha-mismatch")
    if evidence.proposed_pr_sha is not None and evidence.proposed_pr_sha != evidence.head_sha:
        reasons.add("ref.pr-head-mismatch")

    if evidence.evidence_type == RepositoryEvidenceType.BRANCH_HEAD:
        if evidence.tested_sha is not None and evidence.tested_sha != evidence.head_sha:
            reasons.add("ref.tested-sha-mismatch")
        if evidence.synthetic_merge_sha is not None:
            reasons.add("ref.evidence-type-mismatch")
    elif evidence.evidence_type == RepositoryEvidenceType.SYNTHETIC_PR_MERGE:
        if evidence.synthetic_merge_sha is None or evidence.tested_sha is None:
            reasons.add("ref.tested-sha-ambiguous")
        elif evidence.tested_sha != evidence.synthetic_merge_sha:
            reasons.add("ref.tested-sha-mismatch")
        if evidence.tested_sha == evidence.head_sha:
            reasons.add("ref.evidence-type-mismatch")
    elif evidence.evidence_type == RepositoryEvidenceType.BASE_SHA:
        if evidence.tested_sha is not None and evidence.tested_sha != evidence.base_sha:
            reasons.add("ref.tested-sha-mismatch")
    elif evidence.evidence_type == RepositoryEvidenceType.UNCOMMITTED_WORKTREE:
        reasons.add("ref.tested-sha-ambiguous")
        if WorktreeState.UNCOMMITTED not in evidence.worktree_state:
            reasons.add("ref.evidence-type-mismatch")


def _validate_worktree(
    states: tuple[WorktreeState, ...], reasons: set[str]
) -> None:
    mapping = {
        WorktreeState.DIRTY: "worktree.dirty",
        WorktreeState.UNTRACKED: "worktree.untracked",
        WorktreeState.IGNORED: "worktree.ignored-relevant",
        WorktreeState.DETACHED: "worktree.detached",
        WorktreeState.SHALLOW: "worktree.shallow",
        WorktreeState.UNRESOLVED_OPERATION: "worktree.unresolved-operation",
        WorktreeState.UNCOMMITTED: "worktree.uncommitted",
    }
    for state, reason in mapping.items():
        if state in states:
            reasons.add(reason)


def _coerce_repository_state(
    value: RepositoryStateEvidence | Mapping[str, Any], reasons: set[str]
) -> RepositoryStateEvidence | None:
    if isinstance(value, RepositoryStateEvidence):
        return value
    if not isinstance(value, Mapping):
        reasons.add("schema.incomplete")
        return None
    raw = dict(value)
    if _contains_secret_like(raw):
        reasons.add("schema.secret-like-value")
        return None
    if set(raw) - _REPOSITORY_STATE_FIELDS:
        reasons.add("schema.unknown-field")
    if raw.get("execution_authorized", False) is not False:
        reasons.add("schema.contradictory")
    if raw.get("schema_name") != CAPABILITY_EVIDENCE_SCHEMA_NAME:
        reasons.add("schema.name-mismatch")
    version = raw.get("evidence_schema_version")
    if version is None:
        reasons.add("schema.version-missing")
    elif not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        reasons.add("schema.version-malformed")
        version = "0.0"
    identity = _parse_repository_identity(raw.get("repository_identity"), reasons)
    if identity is None:
        return None
    try:
        evidence_type = RepositoryEvidenceType(raw.get("evidence_type"))
    except (TypeError, ValueError):
        reasons.add("schema.unknown-enum")
        return None
    states_raw = raw.get("worktree_state")
    if not isinstance(states_raw, (tuple, list)):
        reasons.add("schema.incomplete")
        return None
    try:
        states = tuple(WorktreeState(item) for item in states_raw)
    except (TypeError, ValueError):
        reasons.add("schema.unknown-enum")
        return None
    try:
        return RepositoryStateEvidence(
            schema_name=CAPABILITY_EVIDENCE_SCHEMA_NAME,
            evidence_schema_version=version,
            producer_adapter=raw.get("producer_adapter"),
            producer_adapter_version=raw.get("producer_adapter_version"),
            correlation_id=raw.get("correlation_id"),
            repository_identity=identity,
            base_ref=raw.get("base_ref"),
            base_sha=raw.get("base_sha"),
            head_ref=raw.get("head_ref"),
            head_sha=raw.get("head_sha"),
            requested_ref=raw.get("requested_ref"),
            requested_sha=raw.get("requested_sha"),
            observed_sha=raw.get("observed_sha"),
            tested_sha=raw.get("tested_sha"),
            pushed_sha=raw.get("pushed_sha"),
            proposed_pr_sha=raw.get("proposed_pr_sha"),
            synthetic_merge_sha=raw.get("synthetic_merge_sha"),
            external_build_sha=raw.get("external_build_sha"),
            evidence_type=evidence_type,
            contract_fingerprint=raw.get("contract_fingerprint"),
            worktree_state=states,
            observed_at=raw.get("observed_at"),
            freshness_boundary=raw.get("freshness_boundary"),
            evidence_id=raw.get("evidence_id", ""),
        )
    except (TypeError, ValueError):
        reasons.add("schema.incomplete")
        return None


def _parse_capability(
    value: object, reasons: set[str]
) -> CapabilityEvidence | None:
    if isinstance(value, CapabilityEvidence):
        return value
    if not isinstance(value, Mapping):
        reasons.add("schema.incomplete")
        return None
    raw = dict(value)
    if set(raw) - _CAPABILITY_FIELDS:
        reasons.add("schema.unknown-field")
    if _contains_secret_like(raw):
        reasons.add("schema.secret-like-value")
        return None
    try:
        status = CapabilityStatus(raw.get("status"))
        strength = EvidenceStrength(raw.get("evidence_strength"))
    except (TypeError, ValueError):
        reasons.add("schema.unknown-enum")
        return None
    reason_code = raw.get("reason_code", "adapter.evidence-unproven")
    if reason_code not in APPROVED_REASON_CODES:
        reasons.add("schema.unknown-enum")
        reason_code = "adapter.evidence-unproven"
    try:
        return CapabilityEvidence(
            capability_id=raw.get("capability_id"),
            status=status,
            evidence_strength=strength,
            operation_scope=raw.get("operation_scope"),
            repository_scope=raw.get("repository_scope"),
            ref_scope=raw.get("ref_scope"),
            sha_scope=raw.get("sha_scope"),
            principal_type=raw.get("principal_type"),
            runtime_fingerprint=raw.get("runtime_fingerprint"),
            freshness_boundary=raw.get("freshness_boundary"),
            reason_code=reason_code,
            reason=raw.get("reason", ""),
            required_handoff=raw.get("required_handoff"),
        )
    except (TypeError, ValueError):
        reasons.add("schema.incomplete")
        return None


def _parse_repository_identity(
    value: object, reasons: set[str], *, optional: bool = False
) -> RepositoryIdentity | None:
    if value is None and optional:
        return None
    if isinstance(value, RepositoryIdentity):
        return value
    if not isinstance(value, Mapping):
        reasons.add("schema.incomplete")
        return None
    raw = dict(value)
    if set(raw) - _REPOSITORY_IDENTITY_FIELDS:
        reasons.add("schema.unknown-field")
    try:
        return RepositoryIdentity(
            host=raw.get("host"),
            owner=raw.get("owner"),
            repository=raw.get("repository"),
            repository_id=raw.get("repository_id"),
            is_fork=raw.get("is_fork", False),
            upstream_owner=raw.get("upstream_owner"),
            upstream_repository=raw.get("upstream_repository"),
            upstream_repository_id=raw.get("upstream_repository_id"),
            default_branch=raw.get("default_branch", "main"),
        )
    except (TypeError, ValueError):
        reasons.add("schema.incomplete")
        return None


def _derive_capability_decision(
    capabilities: tuple[CapabilityEvidence, ...], reasons: set[str]
) -> ExecutionDecision:
    if reasons:
        return ExecutionDecision.NEEDS_DECISION
    if any(item.status == CapabilityStatus.INDETERMINATE for item in capabilities):
        return ExecutionDecision.NEEDS_DECISION
    if any(
        item.status == CapabilityStatus.UNAVAILABLE and item.required_handoff
        for item in capabilities
    ):
        return ExecutionDecision.HANDOFF_REQUIRED
    if any(item.status == CapabilityStatus.UNAVAILABLE for item in capabilities):
        return ExecutionDecision.PROCEED_WITH_LIMITS
    if any(
        item.status == CapabilityStatus.AVAILABLE
        and item.evidence_strength == EvidenceStrength.DECLARED
        for item in capabilities
    ):
        return ExecutionDecision.PROCEED_WITH_LIMITS
    return ExecutionDecision.PROCEED


def _fallback_capability_envelope(
    reasons: tuple[str, ...],
) -> CapabilityEvidenceEnvelope:
    return CapabilityEvidenceEnvelope(
        schema_name=CAPABILITY_EVIDENCE_SCHEMA_NAME,
        evidence_schema_version="0.0",
        serializer_version=CAPABILITY_EVIDENCE_SERIALIZER_VERSION,
        producer_adapter="unknown-adapter",
        producer_adapter_version="0.0",
        correlation_id="unknown",
        environment_class="analysis-only",
        repository_identity=None,
        base_ref=None,
        head_ref=None,
        observed_sha=None,
        contract_fingerprint=None,
        capabilities=(),
        invalidation_reasons=reasons,
        handoffs=(),
        decision=ExecutionDecision.NEEDS_DECISION,
    )


def _repository_result(
    *,
    decision: ExecutionDecision,
    evidence_id: str,
    tested_sha: str | None,
    reasons: set[str] | tuple[str, ...],
) -> RepositoryStateValidationResult:
    reason_codes = normalize_reason_codes(tuple(reasons))
    details = tuple(f"reason: {reason}" for reason in reason_codes)
    return RepositoryStateValidationResult(
        decision=decision,
        valid=not reason_codes,
        evidence_id=evidence_id if isinstance(evidence_id, str) else "",
        tested_sha=(
            tested_sha
            if isinstance(tested_sha, str) and _SHA40_RE.fullmatch(tested_sha)
            else None
        ),
        reason_codes=reason_codes,
        details=details,
    )


def _envelope_to_mapping(value: CapabilityEvidenceEnvelope) -> dict[str, Any]:
    return {
        "schema_name": value.schema_name,
        "evidence_schema_version": value.evidence_schema_version,
        "serializer_version": value.serializer_version,
        "producer_adapter": value.producer_adapter,
        "producer_adapter_version": value.producer_adapter_version,
        "correlation_id": value.correlation_id,
        "environment_class": value.environment_class,
        "repository_identity": value.repository_identity,
        "base_ref": value.base_ref,
        "head_ref": value.head_ref,
        "observed_sha": value.observed_sha,
        "contract_fingerprint": value.contract_fingerprint,
        "capabilities": value.capabilities,
        "invalidation_reasons": value.invalidation_reasons,
        "handoffs": value.handoffs,
        "decision": value.decision,
        "execution_authorized": False,
    }


def _safe_string(value: object, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _optional_string(value: object, reasons: set[str]) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    reasons.add("schema.incomplete")
    return None


def _optional_sha(value: object, reasons: set[str]) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and _SHA40_RE.fullmatch(value):
        return value
    reasons.add("schema.incomplete")
    return None


def _optional_fingerprint(value: object, reasons: set[str]) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and _SHA256_RE.fullmatch(value):
        return value
    reasons.add("schema.incomplete")
    return None


def _safe_string_collection(value: object, reasons: set[str]) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list, set, frozenset)) or isinstance(value, str):
        reasons.add("schema.incomplete")
        return ()
    if not all(isinstance(item, str) and item for item in value):
        reasons.add("schema.incomplete")
        return ()
    return tuple(sorted(set(value)))


def _contains_secret_like(value: object) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _SECRET_PATTERNS)
    if isinstance(value, Mapping):
        return any(
            _contains_secret_like(key) or _contains_secret_like(item)
            for key, item in value.items()
        )
    if isinstance(value, (tuple, list, set, frozenset)):
        return any(_contains_secret_like(item) for item in value)
    return False


def _mapping_string(value: object, key: str) -> str:
    if isinstance(value, Mapping):
        result = value.get(key)
        return result if isinstance(result, str) else ""
    return ""
