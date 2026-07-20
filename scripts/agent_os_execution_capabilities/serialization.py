from __future__ import annotations

import json
import re
from typing import Any

from .models import CapabilityEvidenceEnvelope, RepositoryIdentity

_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
)


def serialize_capability_evidence(value: CapabilityEvidenceEnvelope) -> bytes:
    if not isinstance(value, CapabilityEvidenceEnvelope):
        raise TypeError("value must be a CapabilityEvidenceEnvelope")
    payload = _envelope_payload(value)
    if _contains_secret_like(payload):
        raise ValueError("capability evidence contains a prohibited secret-like value")
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _envelope_payload(value: CapabilityEvidenceEnvelope) -> dict[str, Any]:
    return {
        "schema_name": value.schema_name,
        "evidence_schema_version": value.evidence_schema_version,
        "serializer_version": value.serializer_version,
        "producer_adapter": value.producer_adapter,
        "producer_adapter_version": value.producer_adapter_version,
        "correlation_id": value.correlation_id,
        "environment_class": value.environment_class,
        "repository_identity": _repository_identity_payload(value.repository_identity),
        "base_ref": value.base_ref,
        "head_ref": value.head_ref,
        "observed_sha": value.observed_sha,
        "contract_fingerprint": value.contract_fingerprint,
        "capabilities": [
            {
                "capability_id": item.capability_id,
                "status": item.status.value,
                "evidence_strength": item.evidence_strength.value,
                "operation_scope": item.operation_scope,
                "repository_scope": item.repository_scope,
                "ref_scope": item.ref_scope,
                "sha_scope": item.sha_scope,
                "principal_type": item.principal_type,
                "runtime_fingerprint": item.runtime_fingerprint,
                "freshness_boundary": item.freshness_boundary,
                "reason_code": item.reason_code,
                "reason": item.reason,
                "required_handoff": item.required_handoff,
            }
            for item in value.capabilities
        ],
        "invalidation_reasons": list(value.invalidation_reasons),
        "handoffs": list(value.handoffs),
        "decision": value.decision.value,
        "execution_authorized": False,
        "side_effects_performed": False,
    }


def _repository_identity_payload(
    value: RepositoryIdentity | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "host": value.host,
        "owner": value.owner,
        "repository": value.repository,
        "repository_id": value.repository_id,
        "is_fork": value.is_fork,
        "upstream_owner": value.upstream_owner,
        "upstream_repository": value.upstream_repository,
        "upstream_repository_id": value.upstream_repository_id,
        "default_branch": value.default_branch,
    }


def _contains_secret_like(value: object) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _SECRET_PATTERNS)
    if isinstance(value, dict):
        return any(
            _contains_secret_like(key) or _contains_secret_like(item)
            for key, item in value.items()
        )
    if isinstance(value, (tuple, list, set, frozenset)):
        return any(_contains_secret_like(item) for item in value)
    return False
