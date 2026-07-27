from __future__ import annotations

import re
from typing import Any

from .models import (
    EXECUTION_SERVICE_REQUEST_SCHEMA_VERSION,
    ExecutionServiceReason,
    ExecutionServiceRequest,
    ExecutionServiceResult,
    parse_canonical_utc,
)

_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.ASCII),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b", re.ASCII),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b", re.ASCII),
    re.compile(r"\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*\S+", re.IGNORECASE | re.ASCII),
)


def validate_execution_service_request(
    request: object,
    *,
    evaluated_at: object,
) -> tuple[ExecutionServiceReason, ...]:
    if type(request) is not ExecutionServiceRequest:
        return (ExecutionServiceReason.MALFORMED_REQUEST,)
    try:
        evaluated = parse_canonical_utc(evaluated_at)
    except (TypeError, ValueError):
        return (ExecutionServiceReason.MALFORMED_REQUEST,)

    reasons: set[ExecutionServiceReason] = set()
    if request.schema_version != EXECUTION_SERVICE_REQUEST_SCHEMA_VERSION:
        reasons.add(ExecutionServiceReason.UNSUPPORTED_SCHEMA)
    created = parse_canonical_utc(request.created_at)
    expires = parse_canonical_utc(request.expires_at)
    if expires <= created or evaluated < created:
        reasons.add(ExecutionServiceReason.MALFORMED_REQUEST)
    elif evaluated >= expires:
        reasons.add(ExecutionServiceReason.EXPIRED_REQUEST)
    return tuple(sorted(reasons, key=lambda item: item.value))


def redact_public_text(value: str) -> str:
    if type(value) is not str:
        raise TypeError("public text must be an exact string")
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def contains_secret_marker(value: str) -> bool:
    if type(value) is not str:
        raise TypeError("public text must be an exact string")
    return any(pattern.search(value) for pattern in _SECRET_PATTERNS)


def project_public_result(result: ExecutionServiceResult) -> dict[str, Any]:
    if type(result) is not ExecutionServiceResult:
        raise TypeError("result must be an exact ExecutionServiceResult")
    projected = {
        "schema_version": result.schema_version,
        "request_id": result.request_id,
        "request_revision": result.request_revision,
        "request_fingerprint": result.request_fingerprint,
        "evaluated_at": result.evaluated_at,
        "service_version": result.service_version,
        "status": result.status.value,
        "reasons": [item.value for item in result.reasons],
        "repository_identity": (
            {
                "host": result.repository_identity.host,
                "owner": result.repository_identity.owner,
                "repository": result.repository_identity.repository,
                "repository_id": result.repository_identity.repository_id,
                "is_fork": result.repository_identity.is_fork,
                "upstream_owner": result.repository_identity.upstream_owner,
                "upstream_repository": result.repository_identity.upstream_repository,
                "upstream_repository_id": result.repository_identity.upstream_repository_id,
                "default_branch": result.repository_identity.default_branch,
            }
            if result.repository_identity is not None
            else None
        ),
        "requested_ref": result.requested_ref,
        "expected_sha": result.expected_sha,
        "observed_ref": result.observed_ref,
        "observed_sha": result.observed_sha,
        "inspected_file_count": result.inspected_file_count,
        "inspected_byte_count": result.inspected_byte_count,
        "public_summary": redact_public_text(result.public_summary),
        "result_fingerprint": result.result_fingerprint,
        "side_effects_performed": False,
    }
    if contains_secret_marker(str(projected)):
        projected["public_summary"] = "result available; sensitive detail withheld"
    return projected
