from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict
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
from .reason_codes import APPROVED_REASON_CODES

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
        "side_effects_performed",
    }
)
_REPOSITORY_FIELDS = frozenset(
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
        "worktree_reason_codes",
        "observed_at",
        "freshness_boundary",
        "evidence_id",
        "execution_authorized",
        "side_effects_performed",
    }
)
_IDENTITY_FIELDS = frozenset(
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


def validate_capability_evidence(
    value: CapabilityEvidenceEnvelope | Mapping[str, Any],
) -> CapabilityEvidenceEnvelope:
    if isinstance(value, CapabilityEvidenceEnvelope):
        return value
    if not isinstance(value, Mapping):
        return _fallback_capability(("schema.unknown-field",))

    supplied = dict(value)
    reasons: set[str] = set()
    if _contains_secret_like(supplied):
        return _fallback_capability(("schema.unknown-field",))
    if set(supplied) - _ENVELOPE_FIELDS:
        reasons.add("schema.unknown-field")
    if supplied.get("execution_authorized", False) is not False or supplied.get(
        "side_effects_performed", False
    ) is not False:
        reasons.add("schema.unknown-field")

    version = supplied.get("evidence_schema_version")
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        reasons.add("schema.malformed-version")
        version = "0.0"
    elif version != CAPABILITY_EVIDENCE_SCHEMA_VERSION:
        reasons.add("schema.unsupported-version")

    if supplied.get("schema_name") != CAPABILITY_EVIDENCE_SCHEMA_NAME:
        reasons.add("schema.unknown-field")

    adapter = _string(supplied.get("producer_adapter"), "unknown-adapter")
    adapter_version = _string(supplied.get("producer_adapter_version"), "0.0")
    if adapter == "unknown-adapter" or not _VERSION_RE.fullmatch(adapter_version):
        reasons.add("adapter.incompatible")

    capabilities: list[CapabilityEvidence] = []
    raw_capabilities = supplied.get("capabilities", ())
    if not isinstance(raw_capabilities, (tuple, list)):
        reasons.add("schema.unknown-field")
    else:
        for raw in raw_capabilities:
            parsed = _parse_capability(raw, reasons)
            if parsed is not None:
                capabilities.append(parsed)
    if len({item.capability_id for item in capabilities}) != len(capabilities):
        reasons.add("schema.unknown-field")
        capabilities = list({item.capability_id: item for item in capabilities}.values())

    for code in supplied.get("invalidation_reasons", ()):
        if isinstance(code, str) and code in APPROVED_REASON_CODES:
            reasons.add(code)
        else:
            reasons.add("schema.unknown-field")

    decision = _capability_decision(tuple(capabilities), reasons)
    return CapabilityEvidenceEnvelope(
        schema_name=CAPABILITY_EVIDENCE_SCHEMA_NAME,
        evidence_schema_version=version,
        serializer_version=_valid_version(supplied.get("serializer_version")),
        producer_adapter=adapter,
        producer_adapter_version=(
            adapter_version if _VERSION_RE.fullmatch(adapter_version) else "0.0"
        ),
        correlation_id=_string(supplied.get("correlation_id"), "unknown"),
        environment_class=_string(supplied.get("environment_class"), "analysis-only"),
        repository_identity=_parse_identity(supplied.get("repository_identity"), reasons),
        base_ref=_optional_string(supplied.get("base_ref")),
        head_ref=_optional_string(supplied.get("head_ref")),
        observed_sha=_optional_sha(supplied.get("observed_sha"), reasons),
        contract_fingerprint=_optional_fingerprint(
            supplied.get("contract_fingerprint"), reasons
        ),
        capabilities=tuple(capabilities),
        invalidation_reasons=tuple(reasons),
        handoffs=_string_collection(supplied.get("handoffs", ())),
        decision=decision,
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
        return _result(None, "invalid", reasons or {"schema.unknown-field"})

    if evidence.evidence_schema_version != CAPABILITY_EVIDENCE_SCHEMA_VERSION:
        reasons.add("schema.unsupported-version")

    if expected_repository is not None and (
        evidence.repository_identity.canonical_key != expected_repository.canonical_key
    ):
        actual = evidence.repository_identity
        expected = expected_repository
        same_repo = (
            actual.host,
            actual.owner,
            actual.repository,
            actual.repository_id,
        ) == (
            expected.host,
            expected.owner,
            expected.repository,
            expected.repository_id,
        )
        if same_repo:
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
        reasons.add("ref.test-sha-mismatch")
    if expected_contract_fingerprint is not None and (
        evidence.contract_fingerprint != expected_contract_fingerprint
    ):
        reasons.add("ref.contract-mismatch")
    if expected_pr_sha is not None and evidence.proposed_pr_sha != expected_pr_sha:
        reasons.add("ref.pr-head-mismatch")

    _validate_sha_bindings(evidence, reasons)
    reasons.update(evidence.worktree_reason_codes)
    if evidence.worktree_state == WorktreeState.DIRTY:
        reasons.add("worktree.dirty")
    elif evidence.worktree_state == WorktreeState.INDETERMINATE:
        reasons.add("worktree.indeterminate")

    if reasons & {
        "schema.malformed-version",
        "schema.unsupported-version",
        "schema.unknown-field",
        "adapter.incompatible",
    }:
        outcome = "invalid"
    elif "worktree.indeterminate" in reasons:
        outcome = "needs-decision"
    elif reasons & {
        "worktree.uncommitted",
        "worktree.dirty",
        "worktree.untracked",
        "worktree.ignored-relevant",
        "worktree.operation-unresolved",
        "worktree.detached-head",
        "worktree.shallow-history",
    }:
        outcome = "blocked"
    elif reasons:
        outcome = "stale"
    else:
        outcome = "valid"
    return _result(evidence, outcome, reasons)


def _validate_sha_bindings(
    evidence: RepositoryStateEvidence, reasons: set[str]
) -> None:
    if evidence.tested_sha is None:
        reasons.add("ref.test-sha-mismatch")
    if evidence.requested_sha is not None and evidence.tested_sha is not None:
        if evidence.requested_sha != evidence.tested_sha:
            reasons.add("ref.test-sha-mismatch")
    if evidence.external_build_sha is not None and evidence.tested_sha is not None:
        if evidence.external_build_sha != evidence.tested_sha:
            reasons.add("ref.build-sha-mismatch")
    if evidence.pushed_sha is not None and evidence.pushed_sha != evidence.head_sha:
        reasons.add("ref.stale-sha")
    if evidence.proposed_pr_sha is not None and evidence.proposed_pr_sha != evidence.head_sha:
        reasons.add("ref.pr-head-mismatch")
    if evidence.evidence_type == RepositoryEvidenceType.BRANCH_HEAD:
        if evidence.observed_sha != evidence.head_sha or evidence.tested_sha != evidence.head_sha:
            reasons.add("ref.stale-sha")
        if evidence.synthetic_merge_sha is not None:
            reasons.add("ref.test-sha-mismatch")
    elif evidence.evidence_type == RepositoryEvidenceType.SYNTHETIC_PR_MERGE:
        if evidence.synthetic_merge_sha is None:
            reasons.add("ref.test-sha-mismatch")
        elif not (
            evidence.observed_sha
            == evidence.tested_sha
            == evidence.synthetic_merge_sha
        ):
            reasons.add("ref.stale-sha")
    elif evidence.evidence_type == RepositoryEvidenceType.BASE_SHA:
        if evidence.observed_sha != evidence.base_sha or evidence.tested_sha != evidence.base_sha:
            reasons.add("ref.stale-sha")
    elif evidence.evidence_type == RepositoryEvidenceType.UNCOMMITTED_WORKTREE:
        reasons.add("worktree.uncommitted")


def _coerce_repository_state(
    value: RepositoryStateEvidence | Mapping[str, Any], reasons: set[str]
) -> RepositoryStateEvidence | None:
    if isinstance(value, RepositoryStateEvidence):
        return value
    if not isinstance(value, Mapping):
        return None
    supplied = dict(value)
    if _contains_secret_like(supplied):
        reasons.add("schema.unknown-field")
        return None
    if set(supplied) - _REPOSITORY_FIELDS:
        reasons.add("schema.unknown-field")
    if supplied.get("execution_authorized", False) is not False or supplied.get(
        "side_effects_performed", False
    ) is not False:
        reasons.add("schema.unknown-field")

    version = supplied.get("evidence_schema_version")
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        reasons.add("schema.malformed-version")
        return None
    if version != CAPABILITY_EVIDENCE_SCHEMA_VERSION:
        reasons.add("schema.unsupported-version")

    identity = _parse_identity(supplied.get("repository_identity"), reasons)
    if identity is None:
        return None
    try:
        worktree_state = WorktreeState(supplied.get("worktree_state"))
        evidence_type = RepositoryEvidenceType(supplied.get("evidence_type"))
    except (TypeError, ValueError):
        reasons.add("schema.unknown-field")
        return None
    worktree_reasons = _valid_reason_collection(
        supplied.get("worktree_reason_codes", ()), reasons, prefix="worktree."
    )
    try:
        return RepositoryStateEvidence(
            schema_name=supplied.get("schema_name"),
            evidence_schema_version=version,
            producer_adapter=_string(supplied.get("producer_adapter"), "unknown-adapter"),
            producer_adapter_version=_valid_version(
                supplied.get("producer_adapter_version")
            ),
            correlation_id=_string(supplied.get("correlation_id"), "unknown"),
            repository_identity=identity,
            base_ref=_string(supplied.get("base_ref"), "unknown"),
            base_sha=_required_sha(supplied.get("base_sha")),
            head_ref=_string(supplied.get("head_ref"), "unknown"),
            head_sha=_required_sha(supplied.get("head_sha")),
            requested_ref=_optional_string(supplied.get("requested_ref")),
            requested_sha=_optional_sha(supplied.get("requested_sha"), reasons),
            observed_sha=_required_sha(supplied.get("observed_sha")),
            tested_sha=_optional_sha(supplied.get("tested_sha"), reasons),
            pushed_sha=_optional_sha(supplied.get("pushed_sha"), reasons),
            proposed_pr_sha=_optional_sha(supplied.get("proposed_pr_sha"), reasons),
            synthetic_merge_sha=_optional_sha(
                supplied.get("synthetic_merge_sha"), reasons
            ),
            external_build_sha=_optional_sha(
                supplied.get("external_build_sha"), reasons
            ),
            evidence_type=evidence_type,
            contract_fingerprint=_required_fingerprint(
                supplied.get("contract_fingerprint")
            ),
            worktree_state=worktree_state,
            worktree_reason_codes=worktree_reasons,
            observed_at=_string(supplied.get("observed_at"), "unknown"),
            freshness_boundary=_string(
                supplied.get("freshness_boundary"), "unknown"
            ),
            evidence_id=_string(supplied.get("evidence_id"), ""),
        )
    except (TypeError, ValueError):
        reasons.add("schema.unknown-field")
        return None


def _result(
    evidence: RepositoryStateEvidence | None,
    outcome: str,
    reasons: set[str],
) -> RepositoryStateValidationResult:
    details = tuple(f"reason:{code}" for code in sorted(reasons))
    return RepositoryStateValidationResult(
        outcome=outcome,
        schema_version=(
            evidence.evidence_schema_version if evidence else CAPABILITY_EVIDENCE_SCHEMA_VERSION
        ),
        evidence_id=evidence.evidence_id if evidence else "",
        repository_identity=evidence.repository_identity if evidence else None,
        base_ref=evidence.base_ref if evidence else None,
        base_sha=evidence.base_sha if evidence else None,
        head_ref=evidence.head_ref if evidence else None,
        head_sha=evidence.head_sha if evidence else None,
        requested_ref=evidence.requested_ref if evidence else None,
        requested_sha=evidence.requested_sha if evidence else None,
        observed_sha=evidence.observed_sha if evidence else None,
        tested_sha=evidence.tested_sha if evidence else None,
        pushed_sha=evidence.pushed_sha if evidence else None,
        proposed_pr_sha=evidence.proposed_pr_sha if evidence else None,
        synthetic_merge_sha=evidence.synthetic_merge_sha if evidence else None,
        external_build_sha=evidence.external_build_sha if evidence else None,
        evidence_type=evidence.evidence_type if evidence else None,
        contract_fingerprint=evidence.contract_fingerprint if evidence else None,
        worktree_state=evidence.worktree_state if evidence else None,
        reason_codes=tuple(reasons),
        details=details,
    )


def _parse_capability(
    value: object, reasons: set[str]
) -> CapabilityEvidence | None:
    if not isinstance(value, Mapping):
        reasons.add("schema.unknown-field")
        return None
    supplied = dict(value)
    if set(supplied) - _CAPABILITY_FIELDS:
        reasons.add("schema.unknown-field")
    try:
        return CapabilityEvidence(
            capability_id=supplied.get("capability_id"),
            status=CapabilityStatus(supplied.get("status")),
            evidence_strength=EvidenceStrength(supplied.get("evidence_strength")),
            operation_scope=supplied.get("operation_scope"),
            repository_scope=_optional_string(supplied.get("repository_scope")),
            ref_scope=_optional_string(supplied.get("ref_scope")),
            sha_scope=_optional_sha(supplied.get("sha_scope"), reasons),
            principal_type=_optional_string(supplied.get("principal_type")),
            runtime_fingerprint=_optional_string(
                supplied.get("runtime_fingerprint")
            ),
            freshness_boundary=_optional_string(
                supplied.get("freshness_boundary")
            ),
            reason_code=supplied.get("reason_code", "adapter.incompatible"),
            reason=_string(supplied.get("reason"), ""),
            required_handoff=_optional_string(
                supplied.get("required_handoff")
            ),
        )
    except (TypeError, ValueError):
        reasons.add("schema.unknown-field")
        return None


def _capability_decision(
    capabilities: tuple[CapabilityEvidence, ...], reasons: set[str]
) -> ExecutionDecision:
    if reasons & {
        "schema.malformed-version",
        "schema.unsupported-version",
        "schema.unknown-field",
        "adapter.incompatible",
    }:
        return ExecutionDecision.NEEDS_DECISION
    if any(item.status == CapabilityStatus.INDETERMINATE for item in capabilities):
        return ExecutionDecision.NEEDS_DECISION
    if any(item.status == CapabilityStatus.UNAVAILABLE for item in capabilities):
        return ExecutionDecision.HANDOFF_REQUIRED
    if any(item.status == CapabilityStatus.NOT_REQUIRED for item in capabilities):
        return ExecutionDecision.PROCEED_WITH_LIMITS
    return ExecutionDecision.PROCEED


def _parse_identity(value: object, reasons: set[str]) -> RepositoryIdentity | None:
    if value is None:
        return None
    if isinstance(value, RepositoryIdentity):
        return value
    if not isinstance(value, Mapping):
        reasons.add("repo.identity-mismatch")
        return None
    supplied = dict(value)
    if set(supplied) - _IDENTITY_FIELDS:
        reasons.add("schema.unknown-field")
    try:
        return RepositoryIdentity(**{key: supplied.get(key) for key in _IDENTITY_FIELDS})
    except (TypeError, ValueError):
        reasons.add("repo.identity-mismatch")
        return None


def _fallback_capability(reasons: tuple[str, ...]) -> CapabilityEvidenceEnvelope:
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


def _valid_reason_collection(
    value: object, reasons: set[str], *, prefix: str
) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (tuple, list, set, frozenset)):
        reasons.add("schema.unknown-field")
        return ()
    result: set[str] = set()
    for code in value:
        if isinstance(code, str) and code in APPROVED_REASON_CODES and code.startswith(prefix):
            result.add(code)
        else:
            reasons.add("schema.unknown-field")
    return tuple(sorted(result))


def _string_collection(value: object) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (tuple, list, set, frozenset)):
        return ()
    return tuple(sorted({item for item in value if isinstance(item, str) and item}))


def _string(value: object, default: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _valid_version(value: object) -> str:
    return value if isinstance(value, str) and _VERSION_RE.fullmatch(value) else "0.0"


def _required_sha(value: object) -> str:
    if not isinstance(value, str) or not _SHA40_RE.fullmatch(value):
        raise ValueError("required SHA is malformed")
    return value


def _optional_sha(value: object, reasons: set[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SHA40_RE.fullmatch(value):
        reasons.add("schema.unknown-field")
        return None
    return value


def _required_fingerprint(value: object) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError("contract fingerprint is malformed")
    return value


def _optional_fingerprint(value: object, reasons: set[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        reasons.add("schema.unknown-field")
        return None
    return value
